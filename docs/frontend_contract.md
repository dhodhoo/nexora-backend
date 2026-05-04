# Frontend Contract Mapping (Backend-First)

Dokumen ini adalah mapping cepat endpoint backend untuk dashboard FE Nexora.

## Target Flow FE

1. Connect `WS /ws/communities/{community_id}/dashboard` sebagai realtime primary source.
2. Saat connect/reconnect, panggil `GET /communities/{community_id}/dashboard` untuk fallback snapshot.
3. Panggil `GET /communities/{community_id}/ai-recommendations` untuk panel rekomendasi.
4. Panggil endpoint granular hanya jika butuh detail tambahan.

## Endpoint Mapping

| FE Need | Backend Endpoint | Query Param | Status |
|---|---|---|---|
| Communities table | `GET /communities` | `offset,limit,q,sort_by,sort_order` | `ready` |
| Units table | `GET /communities/{community_id}/units` | `offset,limit,q,va_min,va_max,sort_by,sort_order` | `ready` |
| Dead letters table | `GET /ops/dead-letters` | `offset,limit,topic,reason_q,sort_by,sort_order` | `ready` |
| Dashboard initial payload | `GET /communities/{community_id}/dashboard` | path `community_id` | `ready` |
| Dashboard realtime payload | `WS /ws/communities/{community_id}/dashboard` | path `community_id` | `ready` |
| Ringkasan per unit | `dashboard.units_summary` | - | `ready` |
| Kurva beban komunitas | `dashboard.load_curve` | - | `ready` |
| Risiko peak | `dashboard.peak_risk` | - | `ready` |
| Status AI | `dashboard.ai_status` / `GET /ai/status` | `community_id` | `ready` |
| Rekomendasi AI FE-ready | `GET /communities/{community_id}/ai-recommendations` | path `community_id` | `ready` |
| Hasil AI detail | `GET /ai/last-result` | `community_id` | `ready` |
| Detail metadata device unit | `GET /units/{unit_id}/devices` | `community_id` | `ready` |

## Field Mapping (utama)

| FE Field | Source | Nullable | Notes |
|---|---|---|---|
| `community_id` | `dashboard.community.community_id` | no | komunitas target |
| `total_units` | `dashboard.community.total_units` | no | jumlah unit terdaftar |
| `total_kwh` | `dashboard.community.total_kwh` | no | agregasi seluruh unit |
| `estimated_cost` | `dashboard.community.estimated_cost` | no | berbasis tariff by VA |
| `estimated_emission_kg_co2e` | `dashboard.community.estimated_emission_kg_co2e` | no | faktor emisi backend |
| `last_timestamp` | `dashboard.community.last_timestamp` | yes | null jika belum ada data |
| `is_fresh` | `dashboard.community.is_fresh` | no | freshness 10 menit |
| `unit_id` | `dashboard.units_summary[*].unit_id` | no | id unit |
| `va` | `dashboard.units_summary[*].va` | no | daya VA unit |
| `unit_total_kwh` | `dashboard.units_summary[*].total_kwh` | no | total kWh unit |
| `unit_estimated_cost` | `dashboard.units_summary[*].estimated_cost` | no | estimasi biaya unit |
| `peak_risk_level` | `dashboard.peak_risk.risk_level` | no | `normal/high/critical` |
| `ai_exists` | `dashboard.ai_status.exists` | no | pernah run AI |
| `ai_healthy` | `dashboard.ai_status.healthy` | no | health AI service |
| `ai_stale` | `dashboard.ai_status.stale` | no | status stale hasil terakhir |
| `ai_last_run_at` | `dashboard.ai_status.last_run_at` | yes | null jika belum ada run |
| `ai_last_success_at` | `dashboard.ai_status.last_success_at` | yes | null jika belum sukses |
| `ai_error` | `dashboard.ai_status.error` | no | empty string jika aman |
| `ai_source` | `dashboard.ai_status.source` | no | `scheduler/manual/unknown` |
| `recommendations` | `/communities/{id}/ai-recommendations.recommendations` | no | array, kosong jika belum ada |
| `rec_action` | `recommendations[*].action` | yes | contoh `turn_off/reduce` |
| `rec_saving` | `recommendations[*].saving` | yes | estimasi saving |
| `rec_co2_reduction` | `recommendations[*].co2_reduction` | yes | estimasi pengurangan emisi |

| `meta.total` | list response `.meta.total` | no | total rows untuk pagination |
| `meta.offset` | list response `.meta.offset` | no | offset aktif |
| `meta.limit` | list response `.meta.limit` | no | limit aktif |
| `meta.has_next` | list response `.meta.has_next` | no | tombol next page |

## Fallback Behavior

- Jika data ingestion belum ada:
  - `dashboard` tetap `200`, section agregasi bernilai default/array kosong.
- Jika `community_id` tidak ada:
  - return `404`.
- Jika AI gagal sementara:
  - dashboard tetap tersedia, `ai_status.stale=true` dan `ai_status.error` terisi.
- Jika belum ada hasil AI:
  - endpoint rekomendasi tetap `200` dengan `exists=false` dan `recommendations=[]`.
- Jika WS terputus:
  - FE fallback ke polling `GET /communities/{community_id}/dashboard`.
