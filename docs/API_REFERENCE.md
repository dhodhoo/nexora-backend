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
  "building_id": null
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
    "building_id": null
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
      "building_id": null
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
  "building_id": null
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
  "message": "Mohon kurangi beban puncak pukul 19:00-21:00"
}
```

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

#### `GET /units/{unit_id}/summary?community_id={community_id}`
- Tujuan: summary konsumsi 1 unit.
- Auth: Protected (scope check community).

Response `200`:
```json
{
  "community_id": "C01",
  "unit_id": "U01",
  "total_kwh": 12.34,
  "estimated_cost": 17819.0,
  "estimated_emission_kg_co2e": 10.489,
  "last_timestamp": "2026-05-05T10:00:00",
  "is_fresh": true
}
```

#### `GET /communities/{community_id}/units-summary`
- Tujuan: ringkasan semua unit (quick FE).
- Auth: Protected (scope check community).
- Query opsional: `include_simulation=true|false`.

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
    "is_fresh": true
  }
]
```

#### `GET /communities/{community_id}/dashboard`
- Tujuan: payload dashboard tunggal.
- Auth: Protected (scope check community).
- Query opsional: `include_simulation=true|false`.

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
  "include_simulation_used": false,
  "generated_at": "2026-05-05T10:00:00+00:00"
}
```

#### `GET /communities/{community_id}/load-curve`
- Tujuan: kurva beban per jam.
- Auth: Protected (scope check community).
- Query opsional: `include_simulation=true|false`.

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
- Query opsional: `include_simulation=true|false`.

Response `200`:
```json
{
  "community_id": "C01",
  "peak_hour": "2026-05-05T19:00:00",
  "peak_kwh": 2.58,
  "risk_level": "high"
}
```

#### `GET /units/{unit_id}/devices?community_id={community_id}`
- Tujuan: metadata device per unit.
- Auth: Protected (scope check community).

Response `200`:
```json
[
  {
    "device_id": "ac",
    "controllable": true,
    "schedules": [
      {
        "start_hour": 18,
        "end_hour": 22
      }
    ]
  }
]
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
  "message": "Mohon kurangi beban pada jam puncak malam ini."
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
