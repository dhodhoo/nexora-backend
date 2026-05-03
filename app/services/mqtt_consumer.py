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
        self.client.on_message = self.on_message

    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        client.subscribe(settings.mqtt_topic_pattern)
        print(f"[MQTT] subscribed topic={settings.mqtt_topic_pattern}")

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
