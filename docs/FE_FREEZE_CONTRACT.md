# FE Freeze Contract (Final) - Nexora Backend

Dokumen ini adalah kontrak final untuk integrasi Frontend ke backend Nexora pada fase demo saat ini.

## 1) Base & Auth
- Base URL: `http://127.0.0.1:8100`
- Protected endpoint wajib header:
  - `Authorization: Bearer <access_token>`

## 2) Endpoint Final untuk FE

### A. Bootstrap User
1. `POST /auth/login`
2. `GET /auth/me`
3. `GET /me/dashboard`

### B. Community Dashboard Core
1. `GET /communities/{community_id}/simulations`
2. `GET /communities/{community_id}/dashboard`
3. `GET /communities/{community_id}/ai-recommendations`
4. `GET /units/{unit_id}/ai-recommendations?community_id=...`
4. `WS /ws/communities/{community_id}/dashboard`

### C. Management Views
- Communities list: `GET /communities`
- Community members list: `GET /communities/{community_id}/members`
- Add member: `POST /communities/{community_id}/members`
- Remove member: `DELETE /communities/{community_id}/members/{user_id}`
- Units list: `GET /communities/{community_id}/units`
- Global devices list: `GET /devices`
- Unit devices CRUD:
  - `GET /units/{unit_id}/devices?community_id=...`
  - `POST /units/{unit_id}/devices?community_id=...`
  - `PUT /units/{unit_id}/devices/{device_id}?community_id=...`
  - `DELETE /units/{unit_id}/devices/{device_id}?community_id=...`
- Device control:
  - `POST /units/{unit_id}/devices/{device_id}/control?community_id=...`
- Notifications:
  - `POST /communities/{community_id}/notifications`
  - `POST /buildings/{building_id}/notifications`
  - `GET /notifications`
  - `GET /notifications/{notification_id}`
- CSV export:
  - `GET /communities/{community_id}/reports/export?format=csv`
  - `GET /buildings/{building_id}/reports/export?format=csv`

### D. Ops & Debug (Admin)
- `GET /health`
- `GET /healthz`
- `GET /ops/ingestion-status`
- `GET /ops/dead-letters`

## 3) Payload Wajib yang Dipakai FE

### `/communities/{id}/dashboard`
Field wajib:
- `community`
- `units_summary`
- `load_curve`
- `peak_risk`
- `ai_status`
- `unit_ai_recommendations`
- `include_simulation_used`
- `generated_at`

### `/communities/{id}/ai-recommendations`
Field wajib:
- `community_id`
- `exists`
- `status`
- `stale`
- `source`
- `recommendations[]`

### `/units/{unit_id}/ai-recommendations`
Field wajib:
- `community_id`
- `unit_id`
- `exists`
- `status`
- `stale`
- `source`
- `recommendations[]`

### `/me/dashboard`
Field wajib:
- `user`
- `scope`
- `widgets`
- `generated_at`

### `/communities/{id}/simulations`
Field wajib:
- `community_id`
- `simulation_enabled`
- `updated_at`
- `source`

### `/communities/{id}/members`
Field wajib:
- `items[]`
- `meta.total`
- `meta.offset`
- `meta.limit`
- `meta.has_next`

## 4) Fallback Behavior Standar
- Jika dashboard belum ada data ingestion:
  - tetap `200`, section agregat default/array kosong.
- Jika AI gagal sementara:
  - dashboard tetap jalan, cek `ai_status.stale=true` dan `ai_status.error`.
- Jika belum ada hasil AI:
  - `ai-recommendations` tetap `200` dengan `exists=false` dan `recommendations=[]`.
  - `unit ai-recommendations` juga `200` dengan `exists=false` dan `recommendations=[]`.
- Jika WS putus:
  - FE fallback polling `GET /communities/{id}/dashboard`.
- Simulation mode:
  - FE baca status via `/simulations`,
  - lalu panggil dashboard dengan query explicit `include_simulation=true|false`.

## 5) Urutan Integrasi FE (Recommended)
1. Login -> simpan access token.
2. Load `/auth/me` dan `/me/dashboard`.
3. Ambil `/communities/{id}/simulations`.
4. Ambil `/communities/{id}/dashboard` (dengan `include_simulation` sesuai toggle FE).
5. Ambil `/communities/{id}/ai-recommendations`.
6. Connect WebSocket dashboard untuk realtime update.
7. Jika WS disconnect, fallback ke polling dashboard.
