# Quick Start: AI Integration Test

## 1) Pilih env

### Mode integrasi MQTT + AI
```powershell
Copy-Item .env.ai.example .env -Force
```

### Mode local smoke (tanpa MQTT)
```powershell
Copy-Item .env.local.example .env -Force
```

## 2) Jalankan backend
```powershell
py -3.14 -m uvicorn app.main:app --port 8100
```

## 3) Postman endpoint order
Base URL: `http://127.0.0.1:8100`

1. `GET /health`
2. `GET /ai/health`
3. `POST /ai/run-now?community_id=C01`
4. `GET /ai/last-result?community_id=C01`

Jika ingin semua komunitas sekaligus:
- `POST /ai/run-now`

## 4) Expected
- `/ai/health` return status AI external.
- `/ai/run-now` return:
  - `status: success` jika AI reachable dan snapshot tersedia.
  - `status: failed` + `stale: true` jika AI timeout/error, dengan fallback hasil terakhir bila ada.
- `/ai/last-result` menunjukkan hasil analisis terakhir komunitas.

## 5) Troubleshooting cepat
- `No snapshot data for community ...`:
  belum ada data ingestion untuk komunitas itu.
- `/ai/health` timeout:
  cek akses jaringan ke `AI_BASE_URL`.
- hasil stagnan:
  cek publisher MQTT dan topic pattern.