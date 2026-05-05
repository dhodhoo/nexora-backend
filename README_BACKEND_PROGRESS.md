# Backend Progress Report - Nexora

Dokumen ini merangkum progress backend terbaru untuk sinkronisasi tim FE, AI, dan simulator.

## Status Saat Ini (Latest)

Backend sudah mencapai fase **production-demo ready** dengan komponen utama berikut:
- MQTT ingestion aktif.
- Integrasi AI eksternal aktif.
- Storage utama sudah **migrasi ke PostgreSQL**.
- Schema dikelola oleh **Alembic**.
- Runtime sudah containerized via Docker Compose.

## Capaian yang Sudah Selesai

### 1) Ingestion & Data Layer
- Backend subscribe MQTT topic konsumsi (`energy/+/+/consumption`).
- Data disimpan ke DB relasional (PostgreSQL).
- Adapter payload generator existing tetap didukung.
- Metadata device (`controllable`, `schedules`) tersimpan.

### 2) Kontrak Data Unit/Tarif
- `va` disimpan per unit.
- Tarif dihitung dari lookup per `va`.
- Endpoint update VA sudah ada:
  - `PUT /units/{unit_id}/va?community_id=...`

### 3) API Operasional
Endpoint existing tetap berjalan:
- `GET /health`
- `GET /units/{id}/summary?community_id=...`
- `GET /communities/{id}/load-curve`
- `GET /communities/{id}/peak-risk`
- `GET /units/{id}/devices?community_id=...`
- `PUT /units/{id}/va?community_id=...`

### 4) Integrasi AI Service (Deploy)
Primary AI source:
- `http://ai-nexora.kumalabs.tech`

Endpoint observability backend:
- `GET /ai/health`
- `GET /ai/last-result?community_id=...`
- `POST /ai/run-now?community_id=...`
- `POST /ai/run-now`

Behavior reliability:
- retry + timeout ke AI external.
- fallback `stale=true` saat AI timeout/error.
- hasil AI terakhir disimpan ke DB (`ai_analysis_results`).
- scheduler internal jalan tiap 1 jam (default).

### 5) Migrasi PostgreSQL (Completed)
Migrasi dari SQLite ke PostgreSQL sudah selesai dengan model **fresh start**:
- Docker Compose sekarang menjalankan:
  - `postgres`
  - `nexora-backend`
- Alembic baseline migration berhasil:
  - revision `0001_baseline`
- Tabel inti berhasil dibuat di Postgres:
  - `units`
  - `devices`
  - `energy_readings`
  - `device_state`
  - `tariff_lookup_by_va`
  - `dead_letters`
  - `ai_analysis_results`
  - `alembic_version`

### 6) Dockerization
- `Dockerfile` backend production-ready.
- `docker-entrypoint.sh` menjalankan flow:
  1. wait postgres
  2. `alembic upgrade head`
  3. start uvicorn
- Persistence DB via Docker volume Postgres.

## Bukti Verifikasi Terbaru

- Unit test backend: **5 passed** (Python 3.14).
- Docker build: sukses.
- Compose up: sukses.
- Log startup backend menunjukkan:
  - postgres ready
  - migration jalan
  - uvicorn running
  - mqtt subscribed

## Kondisi Integrasi Saat Ini

- Jika endpoint AI run-now mengembalikan `No snapshot data for community ...`, itu berarti data konsumsi komunitas belum masuk dari simulator/publisher (bukan error Postgres/backend startup).
- Control panel yang state kembali OFF setelah refresh biasanya menandakan simulator subscriber control belum aktif kontinu.

## Next Steps Tim

1. Pastikan simulator/publisher tim aktif terus ke broker dan topic yang sama.
2. Sinkronkan `community_id` + `unit_id` antar FE, simulator, backend, AI.
3. Set `va` per unit sesuai data tim (gunakan endpoint update VA).
4. Lakukan smoke test bersama:
   - `/health`
   - `/ai/health`
   - `/ai/run-now?community_id=C01`
   - `/ai/last-result?community_id=C01`

## Ringkasan untuk Stakeholder

Backend sudah melewati fase pondasi: bukan lagi mock/local-only. Sekarang sudah berjalan di Docker, memakai PostgreSQL + Alembic, terhubung ke MQTT, dan terintegrasi ke AI deploy dengan fallback reliability.