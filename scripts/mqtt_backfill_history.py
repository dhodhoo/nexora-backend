from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from random import Random

import paho.mqtt.publish as mqtt_publish


def load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass
class BrokerConfig:
    host: str
    port: int
    username: str | None
    password: str | None


DEVICE_BASE_KWH = {
    "ac": 1.2,
    "lamp": 0.15,
    "washing_machine": 0.7,
    "tv": 0.25,
    "charger": 0.1,
}


def generate_payload(
    community_id: str,
    unit_id: str,
    device_id: str,
    ts: datetime,
    rng: Random,
) -> dict:
    base = DEVICE_BASE_KWH.get(device_id, 0.2)
    jitter = rng.uniform(-0.2, 0.2)
    kwh = max(0.02, round(base + jitter, 4))
    hour = ts.hour
    schedules = [{"start_hour": 18, "end_hour": 22}] if device_id in {"ac", "tv"} else None
    return {
        "community_id": community_id,
        "unit_id": unit_id,
        "device_id": device_id,
        "timestamp": ts.isoformat(),
        "kwh": kwh,
        "controllable": device_id in {"ac", "lamp", "tv", "charger"},
        "schedules": schedules,
        "is_simulation": False,
        "state": hour >= 18 and hour <= 22,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill MQTT history for Nexora AI warm-up.")
    parser.add_argument("--community-id", default="C01")
    parser.add_argument("--units", default="U01,U02,U03,U04,U05,U06,U07,U08,U09,U10,U11,U12,U13,U14,U15,U16,U17,U18,U19,U20")
    parser.add_argument("--devices", default="ac,lamp,washing_machine,tv,charger")
    parser.add_argument("--hours", type=int, default=26, help="How many hourly samples to backfill.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_env_file(Path(".env"))

    broker = BrokerConfig(
        host=os.getenv("MQTT_HOST", "localhost"),
        port=int(os.getenv("MQTT_PORT", "1883")),
        username=os.getenv("MQTT_USERNAME"),
        password=os.getenv("MQTT_PASSWORD"),
    )
    units = [u.strip() for u in args.units.split(",") if u.strip()]
    devices = [d.strip() for d in args.devices.split(",") if d.strip()]
    rng = Random(args.seed)
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=args.hours - 1)

    auth = None
    if broker.username and broker.password:
        auth = {"username": broker.username, "password": broker.password}

    messages = 0
    for i in range(args.hours):
        ts = start + timedelta(hours=i)
        for unit in units:
            for device in devices:
                topic = f"energy/{args.community_id}/{unit}/consumption"
                payload = generate_payload(args.community_id, unit, device, ts, rng)
                if args.dry_run:
                    print(json.dumps({"topic": topic, "payload": payload}))
                else:
                    mqtt_publish.single(
                        topic=topic,
                        payload=json.dumps(payload),
                        hostname=broker.host,
                        port=broker.port,
                        auth=auth,
                        qos=1,
                        retain=False,
                    )
                messages += 1

    mode = "DRY-RUN" if args.dry_run else "PUBLISHED"
    print(f"[{mode}] community={args.community_id} units={len(units)} devices={len(devices)} hours={args.hours} messages={messages}")


if __name__ == "__main__":
    main()
