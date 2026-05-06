# Nexora API Reference (Backend As-Is)

Dokumen ini adalah referensi utama endpoint backend Nexora untuk tim Backend, Frontend, dan AI.

## 1. Gambaran Umum

- Base URL lokal: `http://127.0.0.1:8100`
- Format body request: `application/json`
- Format response: `application/json`
- Auth:
  - Public endpoint: `/health`, `/auth/login`, `/auth/refresh`
  - Endpoint lain: wajib `Authorization: Bearer <access_token>`

Contoh header protected:
```http
Authorization: Bearer <access_token>
Content-Type: application/json
```

## 2. Kontrak Error Umum

Contoh standar:

- `400 Bad Request`
```json
{"error":"Request body must be valid JSON"}
```

- `401 Unauthorized`
```json
{"error":"Missing bearer token"}
```
atau
```json
{"error":"Invalid token"}
```

- `403 Forbidden`
```json
{"error":"Forbidden"}
```
atau
```json
{"error":"Community scope mismatch"}
```

- `404 Not Found`
```json
{"error":"Not found"}
```

- `500 Internal Server Error`
```json
{"error":"Internal error: <message>"}
```

## 3. Ringkasan Role Akses (As-Is)

| Area | ROLE_ADMIN | ROLE_COORDINATOR | ROLE_BUILDING_MANAGER | ROLE_RESIDENT |
|---|---|---|---|---|
| Auth (`/auth/*`) | Ya | Ya | Ya | Ya |
| Users (`/users*`) | Full | Limited (self via `/auth/me`) | Limited (self via `/auth/me`) | Limited (self via `/auth/me`) |
| Buildings (`/buildings`) | GET/POST | Tidak | Tidak | Tidak |
| Communities dashboard/analytics | Ya | Scope komunitas sendiri | Belum dipakai untuk flow komunitas | Scope komunitas sendiri (jika scope cocok) |
| Ops (`/ops/*`) | Ya | Tidak | Tidak | Tidak |
| AI run (`/ai/run-now`) | Ya | Ya (scope komunitas sendiri) | Tidak | Tidak |
| WebSocket dashboard | Ya (all) | Scope komunitas sendiri | Scope komunitas sendiri bila claim community cocok | Scope komunitas sendiri |

Catatan penting:
- Semua request protected mengecek JWT dan status akun `ACTIVE`.
- Non-admin otomatis membaca data non-simulasi (`is_simulation=false`) pada endpoint analitik yang sudah menerapkan filter.
- Data ingestion konsumsi bersifat append-only.

---

## 4. Endpoint Reference

### 4.1 Health

#### `GET /health`
- Tujuan: cek service hidup.
- Auth: Public.

Response `200`:
```json
{"status":"ok"}
```

#### `GET /healthz`
- Tujuan: readiness check dependency (DB, MQTT, AI) untuk operasional/demo.
- Auth: Public.

Response `200` (contoh):
```json
{
  "status": "ok",
  "app": {"name": "Nexora Backend"},
  "db": {"ok": true, "error": ""},
  "mqtt": {
    "enabled": true,
    "host": "broker-nexora.kumalabs.tech",
    "port": 1883,
    "running": true,
    "connected": true,
    "last_error": "",
    "topics": ["energy/+/+/consumption"]
  },
  "ai": {
    "enabled": true,
    "ok": true,
    "base_url": "http://ai-nexora.kumalabs.tech",
    "error": ""
  }
}
```

---

### 4.2 Auth

#### `POST /auth/login`
- Tujuan: login user dan mendapatkan access + refresh token.
- Auth: Public.

Body:
```json
{
  "email": "admin@nexora.local",
  "password": "admin12345"
}
```

Response `200`:
```json
{
  "access_token": "<jwt>",
  "refresh_token": "<jwt>",
  "token_type": "bearer"
}
```

#### `POST /auth/refresh`
- Tujuan: refresh token pair.
- Auth: Public.

Body:
```json
{
  "refresh_token": "<refresh_token>"
}
```

Response `200`:
```json
{
  "access_token": "<jwt_baru>",
  "refresh_token": "<refresh_token_baru>",
  "token_type": "bearer"
}
```

#### `POST /auth/logout`
- Tujuan: revoke refresh token.
- Auth: Protected.

Header:
```http
Authorization: Bearer <access_token>
```

Body:
```json
{
  "refresh_token": "<refresh_token>"
}
```

Response `200`:
```json
{"status":"logged_out"}
```

#### `GET /auth/me`
- Tujuan: cek profil user aktif dari token.
- Auth: Protected.

Response `200`:
```json
{
  "user_id": "admin-001",
  "full_name": "Nexora Admin",
  "email": "admin@nexora.local",
  "role": "ROLE_ADMIN",
  "status": "ACTIVE",
  "community_id": null,
  "building_id": null,
  "unit_id": null
}
```

#### `GET /me/dashboard`
- Tujuan: bundle dashboard berdasarkan role user yang login.
- Auth: Protected.

Response `200`:
```json
{
  "user": {
    "user_id": "coord-c01",
    "full_name": "Koordinator C01",
    "email": "coord.c01@nexora.local",
    "role": "ROLE_COORDINATOR",
    "status": "ACTIVE"
  },
  "scope": {
    "community_id": "C01",
    "building_id": null,
    "unit_id": "U01"
  },
  "widgets": {
    "community_dashboard": {},
    "ai_status": {}
  },
  "generated_at": "2026-05-05T15:00:00+00:00"
}
```

---

### 4.3 Users

#### `GET /users`
- Tujuan: list user (admin only).
- Auth: Protected (`ROLE_ADMIN`).
- Query: `offset`, `limit`, `q`.

Response `200`:
```json
{
  "items": [
    {
      "user_id": "admin-001",
      "full_name": "Nexora Admin",
      "email": "admin@nexora.local",
      "role": "ROLE_ADMIN",
      "status": "ACTIVE",
      "community_id": null,
      "building_id": null,
      "unit_id": null
    }
  ],
  "meta": {
    "total": 1,
    "offset": 0,
    "limit": 20,
    "has_next": false
  }
}
```

#### `POST /users`
- Tujuan: create user baru (admin only).
- Auth: Protected (`ROLE_ADMIN`).

Body:
```json
{
  "user_id": "coord-001",
  "full_name": "Koordinator C01",
  "email": "coord.c01@nexora.local",
  "password": "Password123!",
  "role": "ROLE_COORDINATOR",
  "status": "ACTIVE",
  "community_id": "C01",
  "building_id": null,
  "unit_id": "U01"
}
```

Response `200`:
```json
{
  "user_id": "coord-001",
  "full_name": "Koordinator C01",
  "email": "coord.c01@nexora.local",
  "role": "ROLE_COORDINATOR",
  "status": "ACTIVE",
  "community_id": "C01",
  "building_id": null
}
```

#### `GET /users/{user_id}`
- Tujuan: get detail user.
- Auth: Protected (admin atau owner user tersebut).

Response `200`: sama shape dengan `POST /users`.

#### `PUT /users/{user_id}`
- Tujuan: update data user.
- Auth: Protected (admin full; non-admin terbatas profil sendiri).

Contoh body:
```json
{
  "full_name": "Nama Baru",
  "email": "baru@nexora.local"
}
```

Response `200`: shape `UserResponse`.

#### `POST /users/{user_id}/reset-password`
- Tujuan: reset password user (admin only).
- Auth: Protected (`ROLE_ADMIN`).

Body:
```json
{
  "new_password": "PasswordBaru123!"
}
```

Response `200`:
```json
{
  "status": "password_reset",
  "user_id": "coord-001"
}
```

---

### 4.4 Buildings

#### `GET /buildings`
- Tujuan: list building.
- Auth: Protected (`ROLE_ADMIN`).
- Query: `offset`, `limit`.

Response `200`:
```json
{
  "items": [
    {
      "building_id": "B01",
      "name": "Tower A"
    }
  ],
  "meta": {
    "total": 1,
    "offset": 0,
    "limit": 20,
    "has_next": false
  }
}
```

#### `POST /buildings`
- Tujuan: create building.
- Auth: Protected (`ROLE_ADMIN`).

Body:
```json
{
  "building_id": "B01",
  "name": "Tower A"
}
```

Response `200`:
```json
{
  "building_id": "B01",
  "name": "Tower A"
}
```

#### `GET /buildings/{building_id}`
- Tujuan: detail 1 building.
- Auth: Protected (`ROLE_ADMIN`, `ROLE_BUILDING_MANAGER` dengan scope building cocok).

Response `200`:
```json
{
  "building_id": "B01",
  "name": "Tower A"
}
```

#### `PUT /buildings/{building_id}`
- Tujuan: update nama building.
- Auth: Protected (`ROLE_ADMIN`, `ROLE_BUILDING_MANAGER` dengan scope building cocok).

Body:
```json
{
  "name": "Tower A Renovated"
}
```

Response `200`:
```json
{
  "building_id": "B01",
  "name": "Tower A Renovated"
}
```

#### `DELETE /buildings/{building_id}`
- Tujuan: hapus building.
- Auth: Protected (`ROLE_ADMIN`).
- Catatan: akan gagal jika masih ada unit aktif.

Response `200`:
```json
{
  "status": "deleted",
  "building_id": "B01"
}
```

#### `GET /buildings/{building_id}/units`
- Tujuan: list unit dalam building.
- Auth: Protected (`ROLE_ADMIN`, `ROLE_BUILDING_MANAGER` dengan scope building cocok).
- Query: `offset`, `limit`, `q`.

Response `200`:
```json
{
  "items": [
    {
      "building_id": "B01",
      "unit_id": "A-01",
      "is_active": true,
      "metadata_json": {
        "floor": 1
      },
      "created_at": "2026-05-05T10:00:00+00:00",
      "updated_at": "2026-05-05T10:00:00+00:00"
    }
  ],
  "meta": {
    "total": 1,
    "offset": 0,
    "limit": 20,
    "has_next": false
  }
}
```

#### `POST /buildings/{building_id}/units`
- Tujuan: create unit baru di building.
- Auth: Protected (`ROLE_ADMIN`, `ROLE_BUILDING_MANAGER` dengan scope building cocok).

Body:
```json
{
  "unit_id": "A-01",
  "is_active": true,
  "metadata_json": {
    "floor": 1,
    "zone": "north"
  }
}
```

Response `200`: shape `BuildingUnitResponse`.

#### `PUT /buildings/{building_id}/units/{unit_id}`
- Tujuan: update status/metadata unit building.
- Auth: Protected (`ROLE_ADMIN`, `ROLE_BUILDING_MANAGER` dengan scope building cocok).

Body:
```json
{
  "is_active": false,
  "metadata_json": {
    "floor": 1,
    "zone": "north",
    "notes": "temporary inactive"
  }
}
```

Response `200`: shape `BuildingUnitResponse`.

#### `DELETE /buildings/{building_id}/units/{unit_id}`
- Tujuan: delete unit building.
- Auth: Protected (`ROLE_ADMIN`, `ROLE_BUILDING_MANAGER` dengan scope building cocok).

Response `200`:
```json
{
  "status": "deleted",
  "building_id": "B01",
  "unit_id": "A-01"
}
```

#### `GET /buildings/{building_id}/reports`
- Tujuan: report placeholder untuk FE.
- Auth: Protected (`ROLE_ADMIN`, `ROLE_BUILDING_MANAGER` dengan scope building cocok).
- Query opsional: `period_start`, `period_end`.

Response `200`:
```json
{
  "building_id": "B01",
  "report_type": "building_summary",
  "generated_at": "2026-05-05T10:00:00+00:00",
  "period": {
    "start": "2026-05-01",
    "end": "2026-05-31"
  },
  "summary": {
    "total_units": 12,
    "active_units": 10
  },
  "download_url": null
}
```

#### `GET /buildings/{building_id}/consumption`
- Tujuan: ringkasan konsumsi energi untuk unit aktif dalam building.
- Auth: Protected (`ROLE_ADMIN`, `ROLE_BUILDING_MANAGER` dengan scope building cocok).
- Query:
  - `window`: `hourly` atau `daily` (default `hourly`)
  - `hours`: jumlah jam lookback (default `24`)

Response `200`:
```json
{
  "building_id": "B01",
  "series": [
    {
      "bucket": "2026-05-05T10:00:00",
      "total_kwh": 2.7,
      "estimated_cost": 3898.8
    }
  ],
  "total_kwh": 2.7,
  "estimated_cost": 3898.8,
  "last_timestamp": "2026-05-05T10:12:00",
  "is_fresh": true
}
```

#### `GET /buildings/{building_id}/predictions`
- Tujuan: view prediksi building yang diturunkan dari hasil AI komunitas terbaru.
- Auth: Protected (`ROLE_ADMIN`, `ROLE_BUILDING_MANAGER` dengan scope building cocok).

Response `200` (ada data):
```json
{
  "building_id": "B01",
  "exists": true,
  "generated_at": "2026-05-05T10:00:00+00:00",
  "community_context": {
    "community_ids": ["C01"],
    "source_community_id": "C01"
  },
  "unit_predictions": {
    "U01": 5.1
  }
}
```

Response `200` (belum ada data AI):
```json
{
  "building_id": "B01",
  "exists": false,
  "generated_at": null,
  "community_context": {},
  "unit_predictions": {}
}
```

#### `GET /buildings/{building_id}/recommendations`
- Tujuan: rekomendasi building hasil filter dari rekomendasi AI komunitas terbaru.
- Auth: Protected (`ROLE_ADMIN`, `ROLE_BUILDING_MANAGER` dengan scope building cocok).

Response `200` (ada data):
```json
{
  "building_id": "B01",
  "exists": true,
  "generated_at": "2026-05-05T10:00:00+00:00",
  "items": [
    {
      "unit_id": "U01",
      "device": "washing_machine",
      "action": "turn_off",
      "saving": 1155.2,
      "co2_reduction": 0.68,
      "estimated_reduction_kwh": 0.8,
      "reasons": [
        "Histori komunitas belum cukup untuk deteksi peak yang stabil"
      ]
    }
  ]
}
```

Response `200` (belum ada data AI):
```json
{
  "building_id": "B01",
  "exists": false,
  "generated_at": null,
  "items": []
}
```

#### `POST /buildings/{building_id}/notifications`
- Tujuan: queue notifikasi internal level building (v1 placeholder, belum ada external dispatcher).
- Auth: Protected (`ROLE_ADMIN`, `ROLE_BUILDING_MANAGER` dengan scope building cocok).
- Catatan:
  - `ROLE_BUILDING_MANAGER` dibatasi 5 request/hari per user.
  - `ROLE_ADMIN` tidak dibatasi.

Body:
```json
{
  "message": "Mohon kurangi beban puncak pukul 19:00-21:00"
}
```

Response `200`:
```json
{
  "status": "queued",
  "scope": "building",
  "building_id": "B01",
  "notification_id": "f3c35b8a-7e94-492d-9925-03d0ef1d8f46"
}
```

#### `GET /buildings/{building_id}/reports/export?format=csv&period_start=...&period_end=...`
- Tujuan: export report building ke file CSV.
- Auth: Protected (`ROLE_ADMIN`, `ROLE_BUILDING_MANAGER` sesuai scope).

Response `200`:
- Content-Type: `text/csv`
- File attachment: `building_{building_id}_report.csv`

#### `GET /buildings/{building_id}/config`
- Tujuan: membaca config lokal building (v1).
- Auth: Protected (`ROLE_ADMIN`, `ROLE_BUILDING_MANAGER` dengan scope building cocok).
- Catatan:
  - jika belum ada config custom, backend mengembalikan default global.

Response `200`:
```json
{
  "building_id": "B01",
  "peak_threshold_kwh": 3.0,
  "source": "default"
}
```

#### `PUT /buildings/{building_id}/config`
- Tujuan: set/update config lokal building (v1 threshold only).
- Auth: Protected (`ROLE_ADMIN`, `ROLE_BUILDING_MANAGER` dengan scope building cocok).

Body:
```json
{
  "peak_threshold_kwh": 4.2
}
```

Response `200`:
```json
{
  "building_id": "B01",
  "peak_threshold_kwh": 4.2,
  "source": "custom"
}
```

---

### 4.5 Communities

#### `GET /communities`
- Tujuan: list community.
- Auth: Protected (`ROLE_ADMIN`).
- Query: `offset`, `limit`, `q`, `sort_by`, `sort_order`.

Response `200`:
```json
{
  "items": [
    {
      "community_id": "C01",
      "name": "Community 01"
    }
  ],
  "meta": {
    "total": 1,
    "offset": 0,
    "limit": 20,
    "has_next": false
  }
}
```

#### `POST /communities`
- Tujuan: create community.
- Auth: Protected (`ROLE_ADMIN`).

Body:
```json
{
  "community_id": "C01",
  "name": "Community 01"
}
```

Response `200`:
```json
{
  "community_id": "C01",
  "name": "Community 01"
}
```

#### `GET /communities/{community_id}`
- Tujuan: detail community.
- Auth: Protected (admin/all role sesuai scope community).

Response `200`:
```json
{
  "community_id": "C01",
  "name": "Community 01"
}
```

#### `PUT /communities/{community_id}`
- Tujuan: update community.
- Auth: Protected (`ROLE_ADMIN`).

Body:
```json
{
  "name": "Community 01 Updated"
}
```

Response `200`:
```json
{
  "community_id": "C01",
  "name": "Community 01 Updated"
}
```

#### `DELETE /communities/{community_id}`
- Tujuan: delete community jika sudah tidak punya unit.
- Auth: Protected (`ROLE_ADMIN`).

Response `200`:
```json
{
  "status": "deleted",
  "community_id": "C01"
}
```

#### `GET /communities/{community_id}/members`
- Tujuan: list member komunitas.
- Auth: Protected (`ROLE_ADMIN`, `ROLE_COORDINATOR` dengan scope komunitas cocok).
- Query: `offset`, `limit`, `q`.

Response `200`:
```json
{
  "items": [
    {
      "user_id": "resident-001",
      "full_name": "Resident 001",
      "email": "resident1@nexora.local",
      "role": "ROLE_RESIDENT",
      "status": "ACTIVE",
      "community_id": "C01"
    }
  ],
  "meta": {
    "total": 1,
    "offset": 0,
    "limit": 20,
    "has_next": false
  }
}
```

#### `POST /communities/{community_id}/members`
- Tujuan: tambah user sebagai member komunitas.
- Auth: Protected (`ROLE_ADMIN`, `ROLE_COORDINATOR` dengan scope komunitas cocok).

Body:
```json
{
  "user_id": "resident-001"
}
```

Response `200`:
```json
{
  "community_id": "C01",
  "user_id": "resident-001",
  "status": "added"
}
```

Catatan:
- Jika user sudah member komunitas yang sama, status bisa `already_member`.
- Jika user punya `building_id` aktif, request ditolak `400`.

#### `DELETE /communities/{community_id}/members/{user_id}`
- Tujuan: keluarkan member dari komunitas.
- Auth: Protected (`ROLE_ADMIN`, `ROLE_COORDINATOR` dengan scope komunitas cocok).

Response `200`:
```json
{
  "community_id": "C01",
  "user_id": "resident-001",
  "status": "removed"
}
```

#### `GET /communities/{community_id}/simulations`
- Tujuan: melihat status preferensi visibilitas simulation komunitas.
- Auth: Protected (`ROLE_ADMIN`, `ROLE_COORDINATOR` dengan scope komunitas cocok).

Response `200`:
```json
{
  "community_id": "C01",
  "simulation_enabled": false,
  "updated_at": null,
  "source": "default"
}
```

#### `POST /communities/{community_id}/simulations/toggle`
- Tujuan: set preferensi visibilitas simulation komunitas (read filter mode).
- Auth: Protected (`ROLE_ADMIN`, `ROLE_COORDINATOR` dengan scope komunitas cocok).

Body:
```json
{
  "simulation_enabled": true
}
```

Response `200`:
```json
{
  "community_id": "C01",
  "simulation_enabled": true,
  "updated_at": "2026-05-05T15:40:00+00:00",
  "source": "custom"
}
```

---

### 4.6 Units (di bawah Community)

#### `GET /communities/{community_id}/units`
- Tujuan: list unit di community.
- Auth: Protected (scope check community).
- Query: `offset`, `limit`, `q`, `va_min`, `va_max`, `sort_by`, `sort_order`.

Response `200`:
```json
{
  "items": [
    {
      "community_id": "C01",
      "unit_id": "U01",
      "va": 1300
    }
  ],
  "meta": {
    "total": 1,
    "offset": 0,
    "limit": 20,
    "has_next": false
  }
}
```

#### `POST /communities/{community_id}/units`
- Tujuan: create unit.
- Auth: Protected (`ROLE_ADMIN`).

Body:
```json
{
  "unit_id": "U01",
  "va": 1300
}
```

Response `200`:
```json
{
  "community_id": "C01",
  "unit_id": "U01",
  "va": 1300
}
```

#### `GET /communities/{community_id}/units/{unit_id}`
- Tujuan: detail unit.
- Auth: Protected (scope check community).

Response `200`: shape `UnitCrudResponse`.

#### `PUT /communities/{community_id}/units/{unit_id}`
- Tujuan: update unit.
- Auth: Protected (`ROLE_ADMIN`).

Body:
```json
{
  "va": 2200
}
```

Response `200`:
```json
{
  "community_id": "C01",
  "unit_id": "U01",
  "va": 2200
}
```

#### `DELETE /communities/{community_id}/units/{unit_id}`
- Tujuan: delete unit.
- Auth: Protected (`ROLE_ADMIN`).

Response `200`:
```json
{
  "status": "deleted",
  "community_id": "C01",
  "unit_id": "U01"
}
```

#### `POST /communities/{community_id}/units/bulk-delete`
- Tujuan: hapus banyak unit sekaligus.
- Auth: Protected (`ROLE_ADMIN`).

Body:
```json
{
  "unit_ids": ["U88", "U89", "U404"]
}
```

Response `200`:
```json
{
  "community_id": "C01",
  "requested_count": 3,
  "deleted_count": 2,
  "not_found_unit_ids": ["U404"]
}
```

---

### 4.7 Dashboard & Analytics

Catatan umum analytics:
- Query `period` didukung: `all|month|week` (default `all`).
- Blok `recommendation_compliance` tersedia di response summary/dashboard:
  - `total_recommendations`
  - `followed_recommendations`
  - `compliance_pct`
  - `window_hours` (24)
- Untuk `period=month|week`, blok `comparison` berisi juga `compliance_pct_point_delta`.

#### `GET /units/{unit_id}/summary?community_id={community_id}`
- Tujuan: summary konsumsi 1 unit.
- Auth: Protected (scope check community).
- Query opsional: `period=all|month|week` (default `all`).

Response `200`:
```json
{
  "community_id": "C01",
  "unit_id": "U01",
  "total_kwh": 12.34,
  "estimated_cost": 17819.0,
  "estimated_emission_kg_co2e": 10.489,
  "device_emissions": [
    {
      "device_id": "ac",
      "device_name": "Air Conditioner",
      "total_kwh": 6.2,
      "estimated_emission_kg_co2e": 5.27
    },
    {
      "device_id": "lamp",
      "device_name": "lamp",
      "total_kwh": 2.1,
      "estimated_emission_kg_co2e": 1.79
    }
  ],
  "last_timestamp": "2026-05-05T10:00:00",
  "is_fresh": true,
  "period_used": "month",
  "period_start": "2026-05-01T00:00:00+00:00",
  "recommendation_compliance": {
    "total_recommendations": 12,
    "followed_recommendations": 7,
    "compliance_pct": 58.33,
    "window_hours": 24
  },
  "comparison": {
    "previous_period_start": "2026-04-01T00:00:00+00:00",
    "previous_period_end": "2026-05-01T00:00:00+00:00",
    "consumption_pct": -6.3,
    "cost_pct": -6.3,
    "emission_pct": -6.3,
    "compliance_pct_point_delta": 12.0
  }
}
```
- Catatan: `device_name` diambil dari catalog global device, fallback ke `device_id` jika tidak ditemukan.

#### `GET /units/{unit_id}/emissions/daily?community_id={community_id}`
- Tujuan: data emisi harian per unit untuk grafik laporan.
- Auth: Protected (scope check community + unit).
- Query:
  - `days` opsional, default `30`, range `1..365`.
  - `period=all|month|week` opsional, default `all`.

Response `200`:
```json
{
  "community_id": "C01",
  "unit_id": "U01",
  "period_used": "month",
  "period_start": "2026-05-01T00:00:00+00:00",
  "series": [
    {
      "date": "2026-05-01",
      "total_kwh": 8.2,
      "estimated_emission_kg_co2e": 6.97
    },
    {
      "date": "2026-05-02",
      "total_kwh": 7.9,
      "estimated_emission_kg_co2e": 6.72
    }
  ],
  "total_emission_kg_co2e": 13.69,
  "last_timestamp": "2026-05-02T21:00:00",
  "is_fresh": true
}
```

#### `GET /communities/{community_id}/units-summary`
- Tujuan: ringkasan semua unit (quick FE).
- Auth: Protected (scope check community).
- Query opsional: `include_simulation=true|false`, `period=all|month|week` (default `all`).

Response `200`:
```json
[
  {
    "community_id": "C01",
    "unit_id": "U01",
    "va": 1300,
    "total_kwh": 12.34,
    "estimated_cost": 17819.0,
    "estimated_emission_kg_co2e": 10.489,
    "last_timestamp": "2026-05-05T10:00:00",
    "is_fresh": true,
    "period_used": "month",
    "period_start": "2026-05-01T00:00:00+00:00",
    "comparison": {
      "previous_period_start": "2026-04-01T00:00:00+00:00",
      "previous_period_end": "2026-05-01T00:00:00+00:00",
      "consumption_pct": -6.3,
      "cost_pct": -6.3,
      "emission_pct": -6.3
    }
  }
]
```

#### `GET /communities/{community_id}/dashboard`
- Tujuan: payload dashboard tunggal.
- Auth: Protected (scope check community).
- Query opsional: `include_simulation=true|false`, `period=all|month|week` (default `all`).

Response `200`:
```json
{
  "community": {
    "community_id": "C01",
    "name": "Community 01",
    "total_units": 1,
    "total_kwh": 12.34,
    "estimated_cost": 17819.0,
    "estimated_emission_kg_co2e": 10.489,
    "last_timestamp": "2026-05-05T10:00:00",
    "is_fresh": true,
    "period_used": "month",
    "period_start": "2026-05-01T00:00:00+00:00",
    "comparison": {
      "previous_period_start": "2026-04-01T00:00:00+00:00",
      "previous_period_end": "2026-05-01T00:00:00+00:00",
      "consumption_pct": -6.3,
      "cost_pct": -6.3,
      "emission_pct": -6.3
    }
  },
  "units_summary": [],
  "load_curve": [],
  "peak_risk": {
    "community_id": "C01",
    "peak_hour": null,
    "peak_kwh": 0.0,
    "risk_level": "normal",
    "period_used": "month",
    "period_start": "2026-05-01T00:00:00+00:00"
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
  "unit_ai_recommendations": {
    "U01": [
      {
        "unit_id": "U01",
        "device": "ac",
        "action": "turn_off",
        "saving": 1000.5,
        "co2_reduction": 0.25,
        "estimated_reduction_kwh": 0.3,
        "reasons": ["outside schedule"]
      }
    ]
  },
  "include_simulation_used": false,
  "period_used": "month",
  "period_start": "2026-05-01T00:00:00+00:00",
  "comparison": {
    "previous_period_start": "2026-04-01T00:00:00+00:00",
    "previous_period_end": "2026-05-01T00:00:00+00:00",
    "consumption_pct": -6.3,
    "cost_pct": -6.3,
    "emission_pct": -6.3
  },
  "generated_at": "2026-05-05T10:00:00+00:00"
}
```

#### `GET /communities/{community_id}/units/{unit_id}/dashboard`
- Tujuan: payload dashboard fokus 1 unit.
- Auth: Protected (scope community + unit access).
- Query opsional: `include_simulation=true|false`, `period=all|month|week` (default `all`).

Response `200`:
```json
{
  "community_id": "C01",
  "unit_id": "U01",
  "unit_summary": {
    "community_id": "C01",
    "unit_id": "U01",
    "va": 2200,
    "total_kwh": 3.2,
    "estimated_cost": 4620.8,
    "estimated_emission_kg_co2e": 2.72,
    "last_timestamp": "2026-05-05T19:00:00",
    "is_fresh": true,
    "period_used": "month",
    "period_start": "2026-05-01T00:00:00+00:00",
    "comparison": {
      "previous_period_start": "2026-04-01T00:00:00+00:00",
      "previous_period_end": "2026-05-01T00:00:00+00:00",
      "consumption_pct": -6.3,
      "cost_pct": -6.3,
      "emission_pct": -6.3
    }
  },
  "load_curve": [],
  "peak_risk": {
    "community_id": "C01",
    "peak_hour": null,
    "peak_kwh": 0.0,
    "risk_level": "normal",
    "period_used": "month",
    "period_start": "2026-05-01T00:00:00+00:00"
  },
  "ai_recommendations": [],
  "period_used": "month",
  "period_start": "2026-05-01T00:00:00+00:00",
  "comparison": {
    "previous_period_start": "2026-04-01T00:00:00+00:00",
    "previous_period_end": "2026-05-01T00:00:00+00:00",
    "consumption_pct": -6.3,
    "cost_pct": -6.3,
    "emission_pct": -6.3
  },
  "generated_at": "2026-05-05T19:00:00+00:00"
}
```

#### `GET /communities/{community_id}/load-curve`
- Tujuan: kurva beban per jam.
- Auth: Protected (scope check community).
- Query opsional: `include_simulation=true|false`, `period=all|month|week` (default `all`).

Response `200`:
```json
[
  {
    "bucket": "2026-05-05T08:00:00",
    "total_kwh": 1.42
  }
]
```

#### `GET /communities/{community_id}/peak-risk`
- Tujuan: status risiko peak.
- Auth: Protected (scope check community).
- Query opsional: `include_simulation=true|false`, `period=all|month|week` (default `all`).

Response `200`:
```json
{
  "community_id": "C01",
  "peak_hour": "2026-05-05T19:00:00",
  "peak_kwh": 2.58,
  "risk_level": "high",
  "period_used": "month",
  "period_start": "2026-05-01T00:00:00+00:00"
}
```

#### `GET /devices`
- Tujuan: list global device catalog.
- Auth: Protected (semua role login, untuk read).
- Query: `offset`, `limit`, `q`.

#### `POST /devices`
- Tujuan: tambah global device catalog.
- Auth: Protected (`ROLE_ADMIN`).

#### `PUT /devices/{device_key}`
- Tujuan: update global device catalog.
- Auth: Protected (`ROLE_ADMIN`).

#### `DELETE /devices/{device_key}`
- Tujuan: soft-disable global device catalog (`is_active=false`).
- Auth: Protected (`ROLE_ADMIN`).

#### `GET /units/{unit_id}/devices?community_id={community_id}`
- Tujuan: list device per unit.
- Auth: Protected (scope role-based per unit).
- Catatan: setiap item sekarang punya field `qty` (jumlah perangkat sejenis dalam unit).
- Catatan: setiap item punya field `is_active` untuk status operasional device di unit.
- Catatan: `device_name` diambil dari `device_catalog.display_name`; fallback ke `device_id` jika belum terdaftar di catalog.

Response `200`:
```json
{
  "items": [
    {
      "device_id": "ac",
      "device_name": "Air Conditioner",
      "qty": 2,
      "is_active": true,
      "controllable": true,
      "schedules": [
        {
          "start_hour": 18,
          "end_hour": 22
        }
      ]
    }
  ],
  "meta": {
    "total": 1,
    "offset": 0,
    "limit": 20,
    "has_next": false
  }
}
```

#### `POST /units/{unit_id}/devices?community_id={community_id}`
- Tujuan: tambah device ke unit.
- Auth: Protected (admin/coordinator/building_manager/resident pada scope unit yang diizinkan).
- Body menerima `qty` (opsional, default `1`, minimal `1`).
- Body menerima `is_active` (opsional, default `true`).

Body:
```json
{
  "device_id": "ac-main",
  "qty": 2,
  "is_active": true,
  "controllable": true,
  "schedules": [
    {
      "hours": [9, 10, 11, 12, 13, 14, 15, 16, 17]
    }
  ]
}
```

Response `200`:
```json
{
  "device_id": "ac-main",
  "device_name": "Air Conditioner",
  "qty": 2,
  "is_active": true,
  "controllable": true,
  "schedules": [
    {
      "hours": [9, 10, 11, 12, 13, 14, 15, 16, 17]
    }
  ]
}
```

#### `PUT /units/{unit_id}/devices/{device_id}?community_id={community_id}`
- Tujuan: update metadata device unit.
- Auth: Protected (scope role-based).
- Dapat update `qty` (`>=1`), `is_active`, selain metadata lain.
- Gunakan field `schedules` (plural). Field tidak dikenal seperti `schedule` akan ditolak `400`.

Body:
```json
{
  "qty": 3,
  "is_active": false,
  "controllable": true,
  "schedules": [
    {
      "hours": [18, 19, 20, 21, 22]
    }
  ]
}
```

Response `200`:
```json
{
  "device_id": "ac-main",
  "device_name": "AC Main",
  "qty": 3,
  "is_active": false,
  "controllable": true,
  "schedules": [
    {
      "hours": [18, 19, 20, 21, 22]
    }
  ]
}
```

Contoh error `400` (body kosong / no-op):
```json
{
  "detail": "No updatable fields provided"
}
```

#### `DELETE /units/{unit_id}/devices/{device_id}?community_id={community_id}`
- Tujuan: hapus device dari unit.
- Auth: Protected (scope role-based).
- Body: tidak ada.

Response `200`:
```json
{
  "status": "deleted",
  "unit_id": "U01",
  "device_id": "ac-main"
}
```

#### `POST /units/{unit_id}/devices/{device_id}/control?community_id={community_id}`
- Tujuan: kontrol device nyata (`action=on|off`) dan publish command ke MQTT.
- Auth: Protected (scope role-based).
- Untuk `qty > 1`, command berlaku ke seluruh instance device tersebut.
- Jika `is_active=false`, request control ditolak (`400 Device is inactive`).

Body:
```json
{
  "action": "on"
}
```

Response `200`:
```json
{
  "command_id": "58c04b95-6adb-4a96-8d8c-b7ec35f09f1f",
  "community_id": "C01",
  "unit_id": "U01",
  "device_id": "ac",
  "action": "on",
  "topic": "energy/C01/U01/control/ac",
  "status": "sent",
  "error": null,
  "created_at": "2026-05-05T19:00:00+00:00"
}
```

#### `PUT /units/{unit_id}/va?community_id={community_id}`
- Tujuan: update VA unit.
- Auth: Protected (`ROLE_ADMIN`).

Body:
```json
{
  "va": 2200
}
```

Response `200`:
```json
{
  "community_id": "C01",
  "unit_id": "U01",
  "va": 2200
}
```

#### `POST /communities/{community_id}/notifications`
- Tujuan: kirim broadcast komunitas.
- Auth: Protected (`ROLE_ADMIN` atau `ROLE_COORDINATOR` sesuai scope).
- Rate limit: non-admin maksimal 5/hari.

Body:
```json
{
  "message": "Mohon kurangi beban pada jam puncak malam ini."
}
```

Response `200`:
```json
{
  "status": "queued",
  "scope": "community",
  "community_id": "C01",
  "notification_id": "a61ec220-c0cb-48e4-a48f-ad4eb14d3c0a"
}
```

#### `GET /communities/{community_id}/reports/export?format=csv&period_start=...&period_end=...`
- Tujuan: export report community ke CSV.
- Auth: Protected (scope check community).

Response `200`:
- Content-Type: `text/csv`
- File attachment: `community_{community_id}_report.csv`

#### `GET /notifications`
- Tujuan: list notifikasi yang tersimpan (dengan delivery status).
- Auth: Protected.
- Query opsional:
  - `status=all|read|unread` (default `all`)

Response `200`:
```json
{
  "items": [
    {
      "notification_id": "a61ec220-c0cb-48e4-a48f-ad4eb14d3c0a",
      "scope": "community",
      "community_id": "C01",
      "building_id": null,
      "message": "Mohon kurangi beban pada jam puncak malam ini.",
      "created_by_user_id": "admin-001",
      "created_at": "2026-05-06T10:15:00Z",
      "is_read": false,
      "read_at": null,
      "deliveries": [
        {
          "target_type": "scope",
          "target_id": "C01",
          "status": "queued",
          "delivered_at": null,
          "error": null
        }
      ]
    }
  ],
  "meta": {
    "total": 1,
    "offset": 0,
    "limit": 20,
    "has_next": false,
    "unread_count": 1
  }
}
```

#### `GET /notifications/{notification_id}`
- Tujuan: detail notifikasi (termasuk delivery).
- Auth: Protected.

Response `200`:
```json
{
  "notification_id": "a61ec220-c0cb-48e4-a48f-ad4eb14d3c0a",
  "scope": "community",
  "community_id": "C01",
  "building_id": null,
  "message": "Mohon kurangi beban pada jam puncak malam ini.",
  "created_by_user_id": "admin-001",
  "created_at": "2026-05-06T10:15:00Z",
  "is_read": true,
  "read_at": "2026-05-06T10:17:00Z",
  "deliveries": []
}
```

#### `POST /notifications/{notification_id}/mark-read`
- Tujuan: menandai satu notifikasi sebagai sudah dibaca oleh user saat ini.
- Auth: Protected.
- Idempotent: jika sudah dibaca, tetap `200`.

Response `200`:
```json
{
  "status": "ok",
  "notification_id": "a61ec220-c0cb-48e4-a48f-ad4eb14d3c0a",
  "read_at": "2026-05-06T10:17:00Z"
}
```

#### `POST /notifications/mark-all-read`
- Tujuan: menandai semua notifikasi visible user saat ini sebagai sudah dibaca.
- Auth: Protected.

Response `200`:
```json
{
  "status": "ok",
  "affected_count": 12
}
```

---

### 4.8 AI Orchestration

#### `GET /ai/health`
- Tujuan: proxy health AI service eksternal.
- Auth: Protected.

Response `200`:
```json
{"status":"ok"}
```

#### `GET /ai/status?community_id={community_id}`
- Tujuan: status AI terakhir per komunitas.
- Auth: Protected (scope check community).

Response `200`:
```json
{
  "community_id": "C01",
  "exists": true,
  "healthy": true,
  "last_run_at": "2026-05-05T09:00:00+00:00",
  "last_success_at": "2026-05-05T09:00:00+00:00",
  "stale": false,
  "error": "",
  "source": "scheduler"
}
```

#### `GET /ai/last-result?community_id={community_id}`
- Tujuan: hasil AI detail terakhir.
- Auth: Protected (scope check community).

Response `200` (contoh):
```json
{
  "community_id": "C01",
  "exists": true,
  "analyzed_at": "2026-05-05T09:00:00+00:00",
  "status": "success",
  "stale": false,
  "error": "",
  "result": {}
}
```

#### `GET /communities/{community_id}/ai-recommendations`
- Tujuan: rekomendasi FE-ready.
- Auth: Protected (scope check community).

Response `200`:
```json
{
  "community_id": "C01",
  "exists": true,
  "analyzed_at": "2026-05-05T09:00:00+00:00",
  "status": "success",
  "stale": false,
  "source": "manual",
  "recommendations": [
    {
      "unit_id": "U01",
      "device": "ac",
      "action": "turn_off",
      "saving": 1155.2,
      "co2_reduction": 0.68,
      "estimated_reduction_kwh": 0.8,
      "reasons": [
        "outside schedule"
      ]
    }
  ]
}
```

#### `GET /units/{unit_id}/ai-recommendations?community_id={community_id}`
- Tujuan: rekomendasi AI khusus untuk 1 unit.
- Auth: Protected (scope community + unit access).

Response `200` (ada data):
```json
{
  "community_id": "C01",
  "unit_id": "U01",
  "exists": true,
  "analyzed_at": "2026-05-05T09:00:00+00:00",
  "status": "success",
  "stale": false,
  "source": "manual",
  "recommendations": [
    {
      "unit_id": "U01",
      "device": "ac",
      "action": "turn_off",
      "saving": 1200.0,
      "co2_reduction": 0.3,
      "estimated_reduction_kwh": 0.4,
      "reasons": ["outside schedule"]
    }
  ]
}
```

Response `200` (belum ada hasil AI):
```json
{
  "community_id": "C01",
  "unit_id": "U01",
  "exists": false,
  "analyzed_at": null,
  "status": null,
  "stale": true,
  "source": "unknown",
  "recommendations": []
}
```

#### `POST /ai/run-now?community_id={community_id}`
- Tujuan: trigger AI manual.
- Auth:
  - `ROLE_ADMIN` bisa global atau per komunitas.
  - `ROLE_COORDINATOR` hanya komunitas scope sendiri.

Body: tidak wajib.

Response `200` (contoh):
```json
{
  "status": "success",
  "community_id": "C01",
  "stale": false
}
```

Kemungkinan `404`:
```json
{
  "error": "No snapshot data for community C01"
}
```

---

### 4.9 Ops / Observability

#### `GET /ops/ingestion-status`
- Tujuan: status MQTT + total data ingestion.
- Auth: Protected (`ROLE_ADMIN`).

Response `200`:
```json
{
  "mqtt": {
    "enabled": true,
    "host": "broker-nexora.kumalabs.tech",
    "port": 1883
  },
  "totals": {
    "energy_readings_count": 471710,
    "dead_letters_count": 0,
    "communities_with_data": 1
  },
  "latest": {
    "last_ingestion_at": "2030-09-01T18:00:00",
    "last_dead_letter_at": null
  },
  "per_community": [
    {
      "community_id": "C01",
      "readings_count": 471710,
      "last_ingestion_at": "2030-09-01T18:00:00"
    }
  ]
}
```

#### `GET /ops/dead-letters`
- Tujuan: list payload invalid ingestion.
- Auth: Protected (`ROLE_ADMIN`).
- Query: `offset`, `limit`, `topic`, `reason_q`, `sort_by`, `sort_order`.

Response `200`:
```json
{
  "items": [
    {
      "id": 1,
      "topic": "energy/C01/U01/consumption",
      "reason": "Either kwh or power_watt must be provided",
      "raw_payload": "{...}",
      "created_at": "2026-05-05T10:00:00"
    }
  ],
  "meta": {
    "total": 1,
    "offset": 0,
    "limit": 20,
    "has_next": false
  }
}
```

---

### 4.10 Realtime WebSocket

#### `WS /ws/communities/{community_id}/dashboard`
- Tujuan: stream snapshot dashboard realtime per komunitas.
- Auth: wajib token (query param `token` atau header bearer).
- Scope: non-admin hanya boleh community sendiri.

Contoh koneksi:
- `ws://127.0.0.1:8100/ws/communities/C01/dashboard?token=<access_token>`

Payload pertama saat connect (initial snapshot):
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
    "generated_at": "2026-05-05T10:00:00+00:00"
  }
}
```

Jika unauthorized atau scope tidak cocok:
- koneksi ditutup dengan policy violation.

#### `WS /ws/communities/{community_id}/units/{unit_id}/dashboard`
- Tujuan: stream snapshot realtime fokus 1 unit.
- Auth: wajib token (query `token` atau header bearer).
- Scope: non-admin harus lolos scope community + unit.

Payload awal:
```json
{
  "type": "unit_dashboard_snapshot",
  "community_id": "C01",
  "unit_id": "U01",
  "data": {
    "community_id": "C01",
    "unit_id": "U01",
    "unit_summary": {},
    "load_curve": [],
    "peak_risk": {},
    "ai_recommendations": [],
    "generated_at": "2026-05-05T19:00:00+00:00"
  }
}
```

---

## 5. Urutan Test Cepat (Postman + WS)

1. `GET /health`
2. `POST /auth/login` (ambil access token)
3. `GET /auth/me`
4. `POST /communities` (admin)
5. `POST /communities/{id}/units` (admin)
6. `GET /communities/{id}/dashboard`
7. `GET /ai/health`
8. `POST /ai/run-now?community_id={id}`
9. `GET /communities/{id}/ai-recommendations`
10. `GET /ops/ingestion-status` (admin)
11. `WS /ws/communities/{id}/dashboard?token=<access_token>`

## 6. Catatan Integrasi FE/AI

- FE wajib simpan `access_token` setelah login dan kirim di semua endpoint protected.
- Untuk dashboard realtime, FE gunakan WebSocket sebagai primary dan HTTP dashboard sebagai fallback.
- Jika `ai/run-now` memberi `404` snapshot not found, pastikan ingestion untuk komunitas tersebut sudah ada.
- Untuk coordinator/resident/building manager, pastikan claim scope di token cocok dengan `community_id`/`building_id` resource yang diakses.
