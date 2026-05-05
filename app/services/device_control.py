from __future__ import annotations

import json

import paho.mqtt.publish as mqtt_publish

from app.config import settings


def publish_device_command(topic: str, payload: dict) -> tuple[bool, str | None]:
    try:
        auth = None
        if settings.mqtt_username and settings.mqtt_password:
            auth = {"username": settings.mqtt_username, "password": settings.mqtt_password}
        mqtt_publish.single(
            topic=topic,
            payload=json.dumps(payload),
            hostname=settings.mqtt_host,
            port=settings.mqtt_port,
            auth=auth,
            qos=1,
            retain=False,
        )
        return True, None
    except Exception as exc:  # pragma: no cover - defensive path
        return False, str(exc)
