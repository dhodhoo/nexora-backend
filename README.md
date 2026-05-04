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
