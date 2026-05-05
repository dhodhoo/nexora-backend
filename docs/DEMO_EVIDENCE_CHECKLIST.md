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
