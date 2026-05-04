# Nexora Backend

Backend orchestrator untuk Nexora: consume data MQTT generator, simpan ke PostgreSQL, sediakan API dashboard, dan orkestrasi call ke AI service per 1 jam.

## 1) Progress Backend (Ringkas)

### Sudah selesai
- FastAPI backend jalan di Docker.
- Database runtime sudah PostgreSQL.
- Alembic sudah jadi source of truth schema.
- MQTT ingestion aktif (auth + topic configurable).
- Simpan data energi, metadata device (`controllable`, `schedules`), dead letter, dan hasil AI.
- Tariff by VA + estimasi biaya.
- Endpoint dashboard inti (`summary`, `load-curve`, `peak-risk`, `devices`, update `va`).
- AI orchestration ke AI deploy (`/ai/health`, `/ai/run-now`, `/ai/last-result`).
- Scheduler internal 1 jam untuk auto-run AI.
- Fallback stale result saat AI gagal/timeout.

### Belum selesai / belum full scope PRD
- Manajemen user/auth/RBAC.
- Manajemen workspace/building multi-role.
- Notifikasi aktif ke user/koordinator.
- Export laporan PDF/CSV.
- Endpoint komparasi before vs after secara dedicated.
- Kontrol perangkat otomatis (masih capability flag, bukan executor).

## 2) Arsitektur Saat Ini

- Backend: FastAPI (Python 3.14)
- DB: PostgreSQL
- Migration: Alembic
- MQTT Broker: eksternal (tim)
- AI Service: eksternal (`AI_BASE_URL`, default `http://ai-nexora.kumalabs.tech`)

Alur:
1. Generator publish ke topic consumption.
2. Backend subscribe topic MQTT, validasi dan simpan ke Postgres.
3. Dashboard FE consume endpoint backend.
4. Scheduler backend membentuk snapshot komunitas dan kirim ke AI `/analyze` tiap 1 jam.
5. Hasil AI disimpan di DB, FE ambil dari backend (bukan direct ke AI).

## 3) Quick Start (Docker Recommended)

1. Copy env:
```bash
cp .env.ai.example .env
```

2. Isi minimal:
- `POSTGRES_PASSWORD`
- `MQTT_HOST`
- `MQTT_PORT`
- `MQTT_USERNAME`
- `MQTT_PASSWORD`
- `AI_BASE_URL` (jika perlu override)

3. Jalankan:
```bash
docker compose up --build -d
```

4. Cek log:
```bash
docker compose logs -f nexora-backend
```

5. Stop:
```bash
docker compose down
```

## 3.1) Automated Test (Full PostgreSQL)

Test backend sudah menggunakan PostgreSQL (bukan SQLite).

Jalankan:
```bash
py -3.14 -m pytest -q
```

Default koneksi test DB:
- host: `localhost`
- port: `5432`
- user: `nexora`
- db: `nexora_test`

Override via env (opsional):
- `TEST_DB_HOST`
- `TEST_DB_PORT`
- `TEST_DB_USER`
- `TEST_DB_PASSWORD`
- `TEST_DB_NAME`

Catatan:
- Test akan membuat database test jika belum ada.
- MQTT dimatikan saat test (`ENABLE_MQTT=false`) agar test stabil dan tidak tergantung broker eksternal.

## 4) MQTT Configuration

Mode wildcard:
- `MQTT_TOPIC_PATTERN=energy/+/+/consumption`

Mode topic spesifik (kalau ACL broker ketat):
- `MQTT_TOPICS=energy/C01/U01/consumption,energy/C01/U02/consumption`

Catatan:
- Jika `MQTT_TOPICS` diisi, backend subscribe daftar itu.
- Jika kosong, backend fallback ke `MQTT_TOPIC_PATTERN`.

## 5) Endpoint Backend + Contoh

Base URL:
- `http://127.0.0.1:8100`

### Health
- `GET /health`
```json
{"status":"ok"}
```

### Unit Summary
- `GET /units/{unit_id}/summary?community_id=C01`
- Contoh: `GET /units/U01/summary?community_id=C01`
```json
{
  "community_id":"C01",
  "unit_id":"U01",
  "total_kwh":12.34,
  "estimated_cost":17819.0,
  "estimated_emission_kg_co2e":10.489,
  "last_timestamp":"2026-05-04T10:00:00",
  "is_fresh":true
}
```

### Community Load Curve
- `GET /communities/{community_id}/load-curve`
- Contoh: `GET /communities/C01/load-curve`
```json
[
  {"bucket":"2026-05-04T08:00:00","total_kwh":1.42},
  {"bucket":"2026-05-04T09:00:00","total_kwh":1.76}
]
```

### Community Peak Risk
- `GET /communities/{community_id}/peak-risk`
- Contoh: `GET /communities/C01/peak-risk`
```json
{
  "community_id":"C01",
  "peak_hour":"2026-05-04T19:00:00",
  "peak_kwh":2.58,
  "risk_level":"high"
}
```

### Community Units Summary (Agregasi cepat FE)
- `GET /communities/{community_id}/units-summary`
- Contoh: `GET /communities/C01/units-summary`
```json
[
  {
    "community_id":"C01",
    "unit_id":"U01",
    "va":1300,
    "total_kwh":12.34,
    "estimated_cost":17819.0,
    "estimated_emission_kg_co2e":10.489,
    "last_timestamp":"2026-05-04T10:00:00",
    "is_fresh":true
  }
]
```

### Community Dashboard Bundle (single call FE)
- `GET /communities/{community_id}/dashboard`
- Contoh: `GET /communities/C01/dashboard`
```json
{
  "community": {
    "community_id": "C01",
    "name": "Community 01",
    "total_units": 4,
    "total_kwh": 12.34,
    "estimated_cost": 17819.0,
    "estimated_emission_kg_co2e": 10.489,
    "last_timestamp": "2026-05-04T10:00:00",
    "is_fresh": true
  },
  "units_summary": [],
  "load_curve": [],
  "peak_risk": {
    "community_id": "C01",
    "peak_hour": null,
    "peak_kwh": 0.0,
    "risk_level": "normal"
  },
  "ai_status": {
    "community_id": "C01",
    "exists": false,
    "healthy": true,
    "last_run_at": null,
    "last_success_at": null,
    "stale": true,
    "error": "",
    "source": "unknown"
  },
  "generated_at": "2026-05-04T10:00:00+00:00"
}
```

### Community CRUD (minimum)
- `GET /communities`
- `POST /communities`
- `GET /communities/{community_id}`
- `PUT /communities/{community_id}`
- `DELETE /communities/{community_id}` (hanya jika unit sudah kosong)

Contoh create:
```json
{
  "community_id":"C02",
  "name":"Community 02"
}
```

Contoh list advanced:
`GET /communities?offset=0&limit=20&q=C0&sort_by=community_id&sort_order=asc`
```json
{
  "items":[{"community_id":"C01","name":"Community 01"}],
  "meta":{"total":1,"offset":0,"limit":20,"has_next":false}
}
```

### Unit CRUD (minimum)
- `GET /communities/{community_id}/units`
- `POST /communities/{community_id}/units`
- `GET /communities/{community_id}/units/{unit_id}`
- `PUT /communities/{community_id}/units/{unit_id}`
- `DELETE /communities/{community_id}/units/{unit_id}`

Contoh create unit:
```json
{
  "unit_id":"U05",
  "va":2200
}
```

Contoh list advanced:
`GET /communities/C01/units?offset=0&limit=20&q=U&va_min=1300&sort_by=va&sort_order=desc`
```json
{
  "items":[{"community_id":"C01","unit_id":"U01","va":2200}],
  "meta":{"total":1,"offset":0,"limit":20,"has_next":false}
}
```

### Bulk Delete Units
- `POST /communities/{community_id}/units/bulk-delete`
```json
{"unit_ids":["U05","U06","U404"]}
```
```json
{
  "community_id":"C01",
  "requested_count":3,
  "deleted_count":2,
  "not_found_unit_ids":["U404"]
}
```

### Unit Devices Metadata
- `GET /units/{unit_id}/devices?community_id=C01`
- Contoh: `GET /units/U01/devices?community_id=C01`
```json
[
  {"device_id":"ac","controllable":true,"schedules":[{"start_hour":8,"end_hour":10}]}
]
```

### Update VA per Unit
- `PUT /units/{unit_id}/va?community_id=C01`
- Body:
```json
{"va":2200}
```
- Response:
```json
{"community_id":"C01","unit_id":"U01","va":2200}
```

### AI Health (Proxy)
- `GET /ai/health`

### AI Run Manual
- `POST /ai/run-now?community_id=C01`
- atau semua komunitas:
- `POST /ai/run-now`

Jika belum ada snapshot komunitas, sekarang return 404 (bukan 500).

### AI Last Result
- `GET /ai/last-result?community_id=C01`
```json
{
  "community_id":"C01",
  "exists":true,
  "analyzed_at":"2026-05-04T10:00:00+00:00",
  "status":"success",
  "stale":false,
  "error":"",
  "result":{}
}
```

### AI Recommendations (FE-ready)
- `GET /communities/{community_id}/ai-recommendations`
```json
{
  "community_id":"C01",
  "exists":true,
  "analyzed_at":"2026-05-04T10:00:00+00:00",
  "status":"success",
  "stale":false,
  "source":"scheduler",
  "recommendations":[
    {
      "unit_id":"U01",
      "device":"ac",
      "action":"turn_off",
      "saving":1000.5,
      "co2_reduction":0.25,
      "estimated_reduction_kwh":0.3,
      "reasons":["outside schedule"]
    }
  ]
}
```

### AI Status (ringan untuk FE indicator)
- `GET /ai/status?community_id=C01`
```json
{
  "community_id":"C01",
  "exists":true,
  "healthy":true,
  "last_run_at":"2026-05-04T10:00:00+00:00",
  "last_success_at":"2026-05-04T10:00:00+00:00",
  "stale":false,
  "error":"",
  "source":"scheduler"
}
```

### Ops Ingestion Status
- `GET /ops/ingestion-status`
```json
{
  "mqtt":{"enabled":true,"host":"broker-nexora.kumalabs.tech","port":1883},
  "totals":{"energy_readings_count":120,"dead_letters_count":2,"communities_with_data":1},
  "latest":{"last_ingestion_at":"2026-05-04T10:00:00","last_dead_letter_at":"2026-05-04T09:58:00"},
  "per_community":[{"community_id":"C01","readings_count":120,"last_ingestion_at":"2026-05-04T10:00:00"}]
}
```

### Ops Dead Letters
- `GET /ops/dead-letters?offset=0&limit=20&topic=energy/C01/U01/consumption&reason_q=kwh&sort_by=created_at&sort_order=desc`
```json
{
  "items": [
    {
      "id": 10,
      "topic": "energy/C01/U01/consumption",
      "reason": "Either kwh or power_watt must be provided",
      "raw_payload": "{...}",
      "created_at": "2026-05-04T10:01:00"
    }
  ],
  "meta":{"total":2,"offset":0,"limit":20,"has_next":false}
}
```

## 6) Contoh Flow Testing End-to-End

1. Nyalakan backend docker.
2. Pastikan MQTT connect sukses di log (bukan `Not authorized`).
3. Trigger ON/OFF dari generator control panel.
4. Cek:
- `GET /units/U01/summary?community_id=C01`
- `GET /communities/C01/load-curve`
5. Jalankan AI manual:
- `POST /ai/run-now?community_id=C01`
6. Cek hasil AI:
- `GET /ai/last-result?community_id=C01`

## 6.1) Rekomendasi FE Call Order (minimal)

1. Connect realtime stream:
- `ws://127.0.0.1:8100/ws/communities/{community_id}/dashboard`
2. Gunakan HTTP `GET /communities/{community_id}/dashboard` sebagai initial/fallback.
3. `GET /communities/{community_id}/ai-recommendations` untuk panel rekomendasi.
4. Gunakan endpoint granular hanya saat perlu detail tambahan:
- `/units/{id}/devices`
- `/communities/{id}/units-summary`

## 6.2) WebSocket Realtime v1

Endpoint:
- `WS /ws/communities/{community_id}/dashboard`

Kontrak message:
```json
{
  "type": "dashboard_snapshot",
  "community_id": "C01",
  "data": {
    "community": {},
    "units_summary": [],
    "load_curve": [],
    "peak_risk": {},
    "ai_status": {},
    "generated_at": "2026-05-04T10:00:00+00:00"
  }
}
```

Behavior:
- Saat connect: server langsung kirim snapshot awal.
- Saat ada ingestion event baru untuk community tersebut: server broadcast snapshot terbaru.
- Jika WS disconnect: FE fallback ke polling endpoint HTTP dashboard.

## 7) Mapping ke PRD (Status)

Mengacu ke `D:\nexora\prd_nexora_energy_orchestration.md`:

- F1 Dashboard konsumsi individu: `PARTIAL`
  - Data API sudah ada, visualisasi di FE tergantung tim frontend.
- F2 Dashboard beban komunitas: `PARTIAL`
  - API load curve + peak risk sudah ada.
- F3 Prediksi beban energi: `PARTIAL`
  - Prediksi/rekomendasi ada di AI service eksternal, backend sudah mengorkestrasi.
- F4 Rekomendasi load shifting: `PARTIAL`
  - Backend simpan/serve hasil rekomendasi AI, rule engine utama di service AI.
- F5 Notifikasi zona beban tinggi: `BELUM`
  - Belum ada push notification mechanism.
- F6 Estimasi tagihan & karbon: `SUDAH (backend API)`
  - Ada estimasi biaya dan emisi di summary.
- F7 Simulasi digital twin tanpa IoT: `SUDAH (integrasi)`
  - Konsumsi dari generator MQTT eksternal sudah didukung.

## 8) Known Notes

- Runtime backend dan test sudah fokus PostgreSQL.
- Untuk operasi tim, gunakan Docker service backend + postgres agar konsisten.
