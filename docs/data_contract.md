# Nexora Backend AI Integration Contract

## External AI Source
- Base URL default: `http://ai-nexora.kumalabs.tech`
- Backend call: `GET /health`, `POST /analyze`, `POST /reset` (opsional)

## Backend AI Endpoints

### GET /ai/health
Proxy health check ke AI external.

### GET /ai/last-result?community_id=C01
Ambil hasil analisis terakhir komunitas.

Response contoh:
```json
{
  "community_id": "C01",
  "exists": true,
  "analyzed_at": "2026-05-03T20:00:00+00:00",
  "status": "success",
  "stale": false,
  "error": "",
  "result": {}
}
```

### POST /ai/run-now?community_id=C01
Trigger analisis manual satu komunitas.

### POST /ai/run-now
Trigger analisis manual semua komunitas yang punya snapshot.

## Scheduler
- Internal scheduler backend kirim snapshot ke AI tiap 1 jam (`AI_SCHEDULER_INTERVAL_SECONDS=3600`).
- Snapshot dibentuk dari data terbaru di DB ingestion (`energy_readings`, `units`, `devices`).

## Fallback
- Jika AI timeout/error, backend simpan record failed dan mengembalikan hasil sukses terakhir (`stale=true`) bila ada.