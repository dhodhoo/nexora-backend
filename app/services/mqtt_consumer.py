import json

import paho.mqtt.client as mqtt
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.services.ingestion import IngestionService


class MQTTConsumer:
    def __init__(self):
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if settings.mqtt_username and settings.mqtt_password:
            self.client.username_pw_set(settings.mqtt_username, settings.mqtt_password)

        self.client.on_connect = self.on_connect
        self.client.on_subscribe = self.on_subscribe
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        self._pending_subscribe_topics: dict[int, str] = {}

    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code != 0:
            print(f"[MQTT][CONNECT_FAILED] reason={reason_code}")
            return

        topics = self._resolve_topics()
        for topic in topics:
            result, mid = client.subscribe(topic)
            self._pending_subscribe_topics[mid] = topic
            print(f"[MQTT][SUBSCRIBE_SENT] topic={topic} subscribe_result={result} mid={mid}")

    def on_subscribe(self, client, userdata, mid, reason_codes, properties=None):
        topic = self._pending_subscribe_topics.pop(mid, "unknown")
        if not reason_codes:
            print(f"[MQTT][SUBACK] topic={topic} mid={mid} reason_codes=[]")
            return

        rejected = [str(code) for code in reason_codes if str(code).lower() in {"failure", "not authorized"}]
        if rejected:
            print(f"[MQTT][SUBACK_FAILED] topic={topic} mid={mid} reason_codes={[str(code) for code in reason_codes]}")
            return

        print(f"[MQTT][SUBACK_OK] topic={topic} mid={mid} reason_codes={[str(code) for code in reason_codes]}")

    def on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties=None):
        print(f"[MQTT][DISCONNECTED] reason={reason_code}")

    @staticmethod
    def _resolve_topics() -> list[str]:
        if settings.mqtt_topics:
            topics = [t.strip() for t in settings.mqtt_topics.split(",") if t.strip()]
            if topics:
                return topics
        return [settings.mqtt_topic_pattern]

    def on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
        except Exception:
            payload = {"raw": msg.payload.decode(errors="ignore")}

        events = self._normalize_events(payload)
        db: Session = SessionLocal()
        try:
            for event in events:
                IngestionService.ingest_event(db, payload=event, topic=msg.topic)
        finally:
            db.close()

    @staticmethod
    def _normalize_events(payload: dict) -> list[dict]:
        # Native normalized event
        if "device_id" in payload:
            return [payload]

        # Adapter for existing generator payload shape
        if "device_consumption_kwh" in payload and isinstance(payload["device_consumption_kwh"], dict):
            community_id = payload.get("community_id")
            unit_id = payload.get("unit_id")
            timestamp = payload.get("timestamp")
            device_flags = payload.get("devices", {})
            events = []
            for device_id, kwh in payload["device_consumption_kwh"].items():
                events.append(
                    {
                        "community_id": community_id,
                        "unit_id": unit_id,
                        "device_id": device_id,
                        "timestamp": timestamp,
                        "kwh": kwh,
                        "controllable": bool(device_flags.get(device_id, False)),
                        "schedules": None,
                    }
                )
            return events

        return [payload]

    def start(self):
        self.client.connect(settings.mqtt_host, settings.mqtt_port, 60)
        self.client.loop_start()

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()
