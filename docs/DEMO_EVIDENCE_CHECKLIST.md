# Demo Evidence Checklist - Nexora Backend

Dokumen ini dipakai untuk bukti backend berjalan normal saat demo tanpa perlu akses DB manual.

## 0) Pre-check
- Service sudah running via Docker.
- Token admin sudah tersedia dari login.

## 1) Service Up
### 1.1 Liveness
Request:
```bash
curl http://127.0.0.1:8100/health
```
Expected:
```json
{"status":"ok"}
```

### 1.2 Readiness
Request:
```bash
curl -H "Authorization: Bearer <token>" http://127.0.0.1:8100/healthz
```
Expected key:
- `status`
- `db.ok`
- `mqtt.enabled`
- `mqtt.running`
- `mqtt.connected`
- `ai.enabled`
- `ai.ok`

## 2) Ingestion Evidence
Request:
```bash
curl -H "Authorization: Bearer <token>" http://127.0.0.1:8100/ops/ingestion-status
```
Expected:
- `totals.energy_readings_count > 0`
- `latest.last_ingestion_at != null`
- `per_community[]` terisi minimal 1 komunitas.

### 2.1 Guardrail timestamp (wajib sebelum demo)
- Cek nilai `latest.last_ingestion_at`.
- Jika timestamp jauh di masa depan (mis. tahun 2030+), `load_curve` 7 hari bisa kosong.
- Solusi cepat: jalankan backfill jam real-time lalu trigger AI manual.

Contoh backfill cepat (jalankan dari container backend):
```bash
python - <<'PY'
import json, os
from datetime import datetime, timedelta, timezone
from random import Random
import paho.mqtt.publish as mqtt_publish

host=os.getenv("MQTT_HOST","localhost")
port=int(os.getenv("MQTT_PORT","1883"))
user=os.getenv("MQTT_USERNAME")
pwd=os.getenv("MQTT_PASSWORD")
auth={"username":user,"password":pwd} if user and pwd else None

community="C01"
units=[f"U{i:02d}" for i in range(1,21)]
devices=["ac","lamp","washing_machine","tv","charger"]
base={"ac":1.2,"lamp":0.15,"washing_machine":0.7,"tv":0.25,"charger":0.1}
rng=Random(42)
hours=48
end=datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)
start=end-timedelta(hours=hours-1)

for i in range(hours):
  ts=start+timedelta(hours=i)
  for u in units:
    for d in devices:
      kwh=max(0.02, round(base.get(d,0.2)+rng.uniform(-0.2,0.2),4))
      payload={
        "community_id":community,
        "unit_id":u,
        "device_id":d,
        "timestamp":ts.isoformat(),
        "kwh":kwh,
        "controllable": d in {"ac","lamp","tv","charger"},
        "schedules":[{"start_hour":18,"end_hour":22}] if d in {"ac","tv"} else None,
        "is_simulation":False,
      }
      mqtt_publish.single(
        topic=f"energy/{community}/{u}/consumption",
        payload=json.dumps(payload),
        hostname=host,
        port=port,
        auth=auth,
        qos=1,
        retain=False,
      )
print("backfill published")
PY
```

Lalu jalankan:
```bash
curl -X POST -H "Authorization: Bearer <token>" "http://127.0.0.1:8100/ai/run-now?community_id=C01"
```

## 3) Dashboard Evidence
Request:
```bash
curl -H "Authorization: Bearer <token>" "http://127.0.0.1:8100/communities/C01/dashboard"
```
Expected:
- `community.community_id = C01`
- ada `units_summary`, `load_curve`, `peak_risk`, `ai_status`
- ada `include_simulation_used`

## 4) AI Orchestration Evidence
### 4.1 Trigger manual AI
```bash
curl -X POST -H "Authorization: Bearer <token>" "http://127.0.0.1:8100/ai/run-now?community_id=C01"
```
Expected:
- `status` `success` atau `failed` dengan fallback aman.

### 4.2 Last AI result
```bash
curl -H "Authorization: Bearer <token>" "http://127.0.0.1:8100/ai/last-result?community_id=C01"
```
Expected:
- `exists=true` jika sudah pernah run
- ada `result` atau fallback result.

## 5) Simulation Toggle Evidence
### 5.1 Read state
```bash
curl -H "Authorization: Bearer <token>" "http://127.0.0.1:8100/communities/C01/simulations"
```

### 5.2 Toggle ON
```bash
curl -X POST -H "Authorization: Bearer <token>" -H "Content-Type: application/json" -d "{\"simulation_enabled\":true}" "http://127.0.0.1:8100/communities/C01/simulations/toggle"
```

### 5.3 Compare dashboard mode
```bash
curl -H "Authorization: Bearer <token>" "http://127.0.0.1:8100/communities/C01/dashboard?include_simulation=false"
curl -H "Authorization: Bearer <token>" "http://127.0.0.1:8100/communities/C01/dashboard?include_simulation=true"
```
Expected:
- `include_simulation_used` berubah sesuai query.

## 6) Realtime WS Evidence
Connect:
- `ws://127.0.0.1:8100/ws/communities/C01/dashboard?token=<access_token>`

Expected message awal:
- `type = dashboard_snapshot`
- `community_id = C01`
- `data` berisi shape dashboard.

## 7) Quick Diagnosis Matrix
- `/health ok`, `/healthz db.ok=false`: masalah koneksi Postgres.
- `mqtt.enabled=true` tapi `mqtt.connected=false`: masalah broker/credential/topic ACL.
- `/ai/health` gagal: AI deploy timeout/down.
- `403` di community endpoint: scope token tidak cocok.
- dashboard kosong: ingestion belum masuk untuk community tersebut.

## 8) New Feature Evidence (Notifications, Devices, CSV, Control)
1. `GET /devices` -> pastikan katalog device global terbaca.
2. `POST /units/{unit_id}/devices/{device_id}/control?community_id=...` -> status `sent`/`failed` + `command_id` tercatat.
3. `POST /communities/{id}/notifications` atau `POST /buildings/{id}/notifications` -> dapat `notification_id`.
4. `GET /notifications` -> notifikasi muncul dengan `deliveries`.
5. `GET /communities/{id}/reports/export?format=csv` -> response `text/csv` dan file terunduh.
