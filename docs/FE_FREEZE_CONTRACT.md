# FE Freeze Contract (Final) - Nexora Backend

Dokumen ini adalah kontrak final untuk integrasi Frontend ke backend Nexora pada fase demo saat ini.

## 1) Base & Auth
- Base URL: `http://127.0.0.1:8100`
- Protected endpoint wajib header:
  - `Authorization: Bearer <access_token>`

## 2) Endpoint Final untuk FE

### A. Bootstrap User
1. `POST /auth/register`
1. `POST /auth/login`
2. `GET /auth/me`
3. `GET /me/dashboard`

Catatan bootstrap auth:
- `POST /auth/register` tidak butuh token.
- response register mengembalikan `user_id` yang di-generate backend.
- user hasil register default `ROLE_RESIDENT` dan `PENDING`.
- scope user tidak dikirim saat register/create.
- assignment `community_id`, `building_id`, dan `unit_id` dilakukan kemudian lewat edit user.

### B. Community Dashboard Core
1. `GET /communities/{community_id}/simulations`
2. `GET /communities/{community_id}/dashboard`
3. `GET /communities/{community_id}/ai-recommendations`
4. `GET /units/{unit_id}/ai-recommendations?community_id=...`
5. `GET /units/{unit_id}/summary?community_id=...`
6. `GET /units/{unit_id}/emissions/daily?community_id=...`
7. `WS /ws/communities/{community_id}/dashboard`
8. `GET /communities/{community_id}/units/{unit_id}/dashboard`
9. `WS /ws/communities/{community_id}/units/{unit_id}/dashboard`
10. `GET /communities/{community_id}/units/detailed`
11. `GET /communities/{community_id}/residents/detailed`
12. `GET /communities/{community_id}/reports/history`
13. `GET /communities/{community_id}/consumption/daily`
14. `GET /communities/{community_id}/settings`
15. `PUT /communities/{community_id}/settings`
16. `GET /communities/{community_id}/optimization-simulation`
- Untuk analytics periodik, endpoint dashboard/summary mendukung query `period=all|month|week` (default `all`).
- Untuk `period=month|week`, response juga menyertakan blok `comparison` (persen konsumsi/tagihan/emisi vs periode sebelumnya). Jika periode sebelumnya nol, nilai persen akan `null`.
- Semua endpoint analytics utama juga menyertakan blok `recommendation_compliance`:
  - `total_recommendations`
  - `followed_recommendations`
  - `compliance_pct`
  - `window_hours` (24)
- Pada `period=month|week`, `comparison` menyertakan `compliance_pct_point_delta` (selisih poin kepatuhan vs periode sebelumnya).

### C. Management Views
- Buildings list/detail:
  - `GET /buildings`
  - `GET /buildings/{building_id}`
  - response menyertakan `manager_user_id` (`string | null`)
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
  - note: jika `qty > 1`, action berlaku ke semua instance device di unit tersebut.
- Notifications:
  - `POST /communities/{community_id}/notifications`
  - `POST /buildings/{building_id}/notifications`
  - `GET /notifications?status=all|read|unread`
  - `GET /notifications/{notification_id}`
  - `POST /notifications/{notification_id}/mark-read`
  - `POST /notifications/mark-all-read`
- Export laporan:
  - `GET /communities/{community_id}/reports/export?format=csv`
  - `GET /buildings/{building_id}/reports/export?format=csv`
  - `GET /units/{unit_id}/reports/export?community_id=...&format=pdf|xlsx|csv&period=YYYY-MM`
- Riwayat laporan unit:
  - `GET /units/{unit_id}/reports/history?community_id=...&limit=12&offset=0`
- Preferences notifikasi user:
  - `GET /users/{user_id}/notification-preferences`
  - `PUT /users/{user_id}/notification-preferences`

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

### Unit Device Card (per unit)
Field wajib item device:
- `device_id`
- `device_name` (dari catalog, fallback ke `device_id`)
- `qty` (integer >= 1)
- `is_active` (boolean status operasional; jika `false`, control ditolak backend)
- `schedule_source` (`manual` | `mqtt`) untuk transparansi sumber schedule
- `controllable`
- `schedules`
- Catatan integrasi: saat update device, kirim field `schedules` (plural). Field typo seperti `schedule` akan ditolak `400`.

### `/units/{unit_id}/summary`
Field wajib:
- `estimated_emission_kg_co2e`
- `device_emissions[]`
- `device_emissions[].device_id`
- `device_emissions[].device_name`
- `device_emissions[].total_kwh`
- `device_emissions[].estimated_emission_kg_co2e`

### `/units/{unit_id}/emissions/daily`
Field wajib:
- `community_id`
- `unit_id`
- `period_used`
- `series[]`
- `series[].date`
- `series[].estimated_emission_kg_co2e`
- `total_emission_kg_co2e`

### `/units/{unit_id}/reports/history`
Field wajib:
- `items[]`
- `items[].period` (`YYYY-MM`)
- `items[].total_kwh`
- `items[].estimated_cost`
- `items[].estimated_emission_kg_co2e`
- `meta.total`
- `meta.offset`
- `meta.limit`
- `meta.has_next`

### Notifications List
Field wajib:
- `items[].notification_id`
- `items[].message`
- `items[].is_read`
- `items[].read_at`
- `meta.unread_count`

### `/buildings` dan `/buildings/{building_id}`
Field wajib:
- `building_id`
- `name`
- `manager_user_id`

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
   - Untuk tampilan bulanan FE, pakai `period=month`.
   - Untuk tampilan mingguan FE, pakai `period=week`.
5. Ambil `/communities/{id}/ai-recommendations`.
6. Connect WebSocket dashboard untuk realtime update.
7. Jika WS disconnect, fallback ke polling dashboard.
8. Untuk halaman fokus unit: panggil `/communities/{id}/units/{unit_id}/dashboard` lalu subscribe WS unit route.
