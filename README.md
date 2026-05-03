# Nexora Backend

Backend untuk Nexora yang menangani ingestion MQTT, data API operasional, dan integrasi AI service eksternal.

## Progress Backend (Current)

Status implementasi saat ini:
- MQTT ingestion aktif (`energy/+/+/consumption`) dengan adapter payload generator existing.
- API operasional untuk summary/load curve/peak risk/devices sudah berjalan.
- Integrasi AI deploy sudah aktif (health, trigger manual, last result, fallback stale).
- Scheduler internal backend jalan tiap 1 jam untuk update ke AI.
- Storage utama sudah migrasi ke **PostgreSQL**.
- Manajemen schema sudah pakai **Alembic** (baseline `0001_baseline`).
- Runtime sudah containerized dengan Docker Compose (backend + postgres).

## Arsitektur

- Backend: FastAPI (Python 3.14)
- DB: PostgreSQL
- Migration: Alembic
- MQTT broker: eksternal
- AI service: eksternal (`AI_BASE_URL`)

## Endpoint Utama

### Health & AI Observability
- `GET /health`
- `GET /ai/health`
- `GET /ai/last-result?community_id=C01`
- `POST /ai/run-now?community_id=C01`
- `POST /ai/run-now`

### Data Operasional
- `GET /units/{id}/summary?community_id=C01`
- `GET /communities/{id}/load-curve`
- `GET /communities/{id}/peak-risk`
- `GET /units/{id}/devices?community_id=C01`
- `PUT /units/{id}/va?community_id=C01`

## Jalankan dengan Docker (Recommended)

1. Siapkan env:
```bash
cp .env.ai.example .env
```

2. Edit `.env`:
- isi `POSTGRES_PASSWORD`
- isi `MQTT_PASSWORD`
- pastikan `MQTT_HOST` dan `AI_BASE_URL` benar

3. Start:
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

## Migration Workflow

Startup backend container otomatis:
1. wait PostgreSQL ready
2. `alembic upgrade head`
3. start uvicorn

Perintah manual (opsional):
```bash
alembic upgrade head
alembic downgrade -1
alembic revision -m "your change"
```

## Verifikasi Cepat

- `GET http://127.0.0.1:8100/health`
- `GET http://127.0.0.1:8100/ai/health`
- `POST http://127.0.0.1:8100/ai/run-now?community_id=C01`

Jika `run-now` mengembalikan `No snapshot data for community ...`, artinya data ingestion komunitas itu belum masuk dari simulator/publisher.

## Catatan

- Migrasi SQLite -> PostgreSQL dilakukan sebagai **fresh start**.
- Hasil AI terakhir disimpan di tabel `ai_analysis_results`.
- Saat AI timeout/error, backend simpan status failed dan fallback hasil terakhir (`stale=true`) jika tersedia.