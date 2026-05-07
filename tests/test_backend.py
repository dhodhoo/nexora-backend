import os
import sys
from datetime import datetime, timedelta, timezone

import psycopg

sys.path.insert(0, os.path.abspath("."))

os.environ["ENABLE_MQTT"] = "false"
os.environ["AI_ENABLED"] = "false"

TEST_DB_HOST = os.getenv("TEST_DB_HOST", "localhost")
TEST_DB_PORT = int(os.getenv("TEST_DB_PORT", "5432"))
TEST_DB_USER = os.getenv("TEST_DB_USER", "nexora")
TEST_DB_PASSWORD = os.getenv("TEST_DB_PASSWORD", "password-nexora")
TEST_DB_NAME = os.getenv("TEST_DB_NAME", "nexora_test")


def _ensure_test_database():
    admin_dsn = (
        f"host={TEST_DB_HOST} port={TEST_DB_PORT} dbname=postgres "
        f"user={TEST_DB_USER} password={TEST_DB_PASSWORD}"
    )
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            # Force-clean test DB for deterministic schema/enum lifecycle.
            cur.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s AND pid <> pg_backend_pid()
                """,
                (TEST_DB_NAME,),
            )
            cur.execute(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}"')
            cur.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')


_ensure_test_database()
os.environ["DATABASE_URL"] = (
    f"postgresql+psycopg://{TEST_DB_USER}:{TEST_DB_PASSWORD}@{TEST_DB_HOST}:{TEST_DB_PORT}/{TEST_DB_NAME}"
)

from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import AIAnalysisResult, Building, BuildingUnit, Community, DeviceCatalog, DeviceCommand, Unit, User, UserRole, UserStatus
from app.services.ai_integration import ai_orchestrator
from app.services.ingestion import IngestionService
from app.utils.time import utc_now


def setup_module(module):
    # DB was recreated in _ensure_test_database.
    Base.metadata.create_all(bind=engine)


def _auth_headers(client: TestClient):
    login = client.post("/auth/login", json={"email": "admin@nexora.local", "password": "admin12345"})
    assert login.status_code == 200
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_health_contract():
    with TestClient(app) as client:
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}


def test_auth_register_creates_pending_user_with_generated_id():
    with TestClient(app) as client:
        res = client.post(
            "/auth/register",
            json={
                "full_name": "Register User",
                "email": "register-user@nexora.local",
                "password": "register12345",
            },
        )
        assert res.status_code == 201
        body = res.json()
        assert body["user_id"].startswith("usr-")
        assert body["role"] == "ROLE_RESIDENT"
        assert body["status"] == "PENDING"
        assert body["unit_id"] is None

        login = client.post(
            "/auth/login",
            json={"email": "register-user@nexora.local", "password": "register12345"},
        )
        assert login.status_code == 200
        token = login.json()["access_token"]
        me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json()["status"] == "PENDING"


def test_admin_create_user_auto_generates_user_id_and_unit_id_optional():
    db = SessionLocal()
    if not db.query(Building).filter(Building.building_id == "B-AUTO").first():
        db.add(Building(building_id="B-AUTO", name="Tower Auto"))
    db.commit()
    db.close()

    with TestClient(app) as client:
        headers = _auth_headers(client)
        res = client.post(
            "/users",
            json={
                "full_name": "Auto Manager",
                "email": "auto-manager@nexora.local",
                "password": "manager12345",
                "role": "ROLE_BUILDING_MANAGER",
                "status": "ACTIVE",
            },
            headers=headers,
        )
        assert res.status_code == 200
        body = res.json()
        assert body["user_id"].startswith("usr-")
        assert body["role"] == "ROLE_BUILDING_MANAGER"
        assert body["unit_id"] is None
        assert body["building_id"] is None


def test_update_user_can_clear_building_assignment_with_null():
    db = SessionLocal()
    if not db.query(Building).filter(Building.building_id == "B-CLEAR").first():
        db.add(Building(building_id="B-CLEAR", name="Tower Clear"))
    db.commit()
    db.close()

    with TestClient(app) as client:
        headers = _auth_headers(client)
        created = client.post(
            "/users",
            json={
                "user_id": "mgr-clear",
                "full_name": "Manager Clear",
                "email": "mgr-clear@nexora.local",
                "password": "manager12345",
                "role": "ROLE_BUILDING_MANAGER",
                "status": "PENDING",
            },
            headers=headers,
        )
        assert created.status_code in (200, 400)

        assigned = client.put(
            "/users/mgr-clear",
            json={"building_id": "B-CLEAR"},
            headers=headers,
        )
        assert assigned.status_code == 200
        assert assigned.json()["building_id"] == "B-CLEAR"

        cleared = client.put(
            "/users/mgr-clear",
            json={"building_id": None},
            headers=headers,
        )
        assert cleared.status_code == 200
        assert cleared.json()["building_id"] is None


def test_list_users_supports_role_and_status_filters():
    with TestClient(app) as client:
        headers = _auth_headers(client)

        coord_create = client.post(
            "/users",
            json={
                "user_id": "coord-filter",
                "full_name": "Coordinator Filter",
                "email": "coord-filter@nexora.local",
                "password": "coord12345",
                "role": "ROLE_COORDINATOR",
                "status": "ACTIVE",
            },
            headers=headers,
        )
        assert coord_create.status_code in (200, 400)

        resident_create = client.post(
            "/users",
            json={
                "user_id": "resident-filter",
                "full_name": "Resident Filter",
                "email": "resident-filter@nexora.local",
                "password": "resident12345",
                "role": "ROLE_RESIDENT",
                "status": "PENDING",
            },
            headers=headers,
        )
        assert resident_create.status_code in (200, 400)

        by_role = client.get("/users", params={"role": "ROLE_COORDINATOR"}, headers=headers)
        assert by_role.status_code == 200
        role_items = by_role.json()["items"]
        assert any(item["user_id"] == "coord-filter" for item in role_items)
        assert all(item["role"] == "ROLE_COORDINATOR" for item in role_items)

        by_status = client.get("/users", params={"status": "PENDING"}, headers=headers)
        assert by_status.status_code == 200
        status_items = by_status.json()["items"]
        assert any(item["user_id"] == "resident-filter" for item in status_items)
        assert all(item["status"] == "PENDING" for item in status_items)

        combined = client.get(
            "/users",
            params={"q": "coord-filter", "role": "ROLE_COORDINATOR", "status": "ACTIVE"},
            headers=headers,
        )
        assert combined.status_code == 200
        combined_items = combined.json()["items"]
        assert any(item["user_id"] == "coord-filter" for item in combined_items)
        assert all(item["role"] == "ROLE_COORDINATOR" and item["status"] == "ACTIVE" for item in combined_items)


def test_create_building_auto_generates_building_id():
    with TestClient(app) as client:
        headers = _auth_headers(client)
        res = client.post(
            "/buildings",
            json={
                "name": "Tower Auto Generated",
            },
            headers=headers,
        )
        assert res.status_code == 200
        body = res.json()
        assert body["building_id"].startswith("bld-")
        assert body["name"] == "Tower Auto Generated"


def test_building_responses_include_manager_user_id():
    db = SessionLocal()
    if not db.query(Building).filter(Building.building_id == "B-MGR").first():
        db.add(Building(building_id="B-MGR", name="Tower Manager"))
    if not db.query(User).filter(User.user_id == "mgr-building").first():
        db.add(
            User(
                user_id="mgr-building",
                full_name="Manager Building",
                email="mgr-building@nexora.local",
                password_hash="hashed",
                role=UserRole.BUILDING_MANAGER,
                status=UserStatus.ACTIVE,
                building_id="B-MGR",
            )
        )
    db.commit()
    db.close()

    with TestClient(app) as client:
        headers = _auth_headers(client)

        detail = client.get("/buildings/B-MGR", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["manager_user_id"] == "mgr-building"

        listed = client.get("/buildings", headers=headers)
        assert listed.status_code == 200
        row = next((item for item in listed.json()["items"] if item["building_id"] == "B-MGR"), None)
        assert row is not None
        assert row["manager_user_id"] == "mgr-building"


def test_building_units_require_floor_and_support_floor_filter():
    db = SessionLocal()
    if not db.query(Building).filter(Building.building_id == "B-FLR").first():
        db.add(Building(building_id="B-FLR", name="Tower Floor"))
    db.commit()
    db.close()

    with TestClient(app) as client:
        headers = _auth_headers(client)

        missing_floor = client.post(
            "/buildings/B-FLR/units",
            json={"unit_id": "UF-01", "is_active": True},
            headers=headers,
        )
        assert missing_floor.status_code == 400

        created_1 = client.post(
            "/buildings/B-FLR/units",
            json={"unit_id": "UF-01", "floor": 1, "is_active": True, "metadata_json": {"zone": "north"}},
            headers=headers,
        )
        assert created_1.status_code == 200
        assert created_1.json()["floor"] == 1
        assert created_1.json()["metadata_json"]["floor"] == 1

        created_2 = client.post(
            "/buildings/B-FLR/units",
            json={"floor": 2, "is_active": True},
            headers=headers,
        )
        assert created_2.status_code == 200
        assert created_2.json()["unit_id"].startswith("unt-")
        assert created_2.json()["floor"] == 2

        floor_1 = client.get("/buildings/B-FLR/units", params={"floor": 1}, headers=headers)
        assert floor_1.status_code == 200
        rows = floor_1.json()["items"]
        assert len(rows) == 1
        assert rows[0]["unit_id"] == "UF-01"
        assert rows[0]["floor"] == 1


def test_building_detail_includes_available_floors():
    db = SessionLocal()
    if not db.query(Building).filter(Building.building_id == "B-FLOORS").first():
        db.add(Building(building_id="B-FLOORS", name="Tower Floors"))
    if not db.query(BuildingUnit).filter(BuildingUnit.building_id == "B-FLOORS", BuildingUnit.unit_id == "F-01").first():
        db.add(BuildingUnit(building_id="B-FLOORS", unit_id="F-01", is_active=True, metadata_json={"floor": 3}))
    if not db.query(BuildingUnit).filter(BuildingUnit.building_id == "B-FLOORS", BuildingUnit.unit_id == "F-02").first():
        db.add(BuildingUnit(building_id="B-FLOORS", unit_id="F-02", is_active=True, metadata_json={"floor": 1}))
    if not db.query(BuildingUnit).filter(BuildingUnit.building_id == "B-FLOORS", BuildingUnit.unit_id == "F-03").first():
        db.add(BuildingUnit(building_id="B-FLOORS", unit_id="F-03", is_active=True, metadata_json={"floor": 3}))
    db.commit()
    db.close()

    with TestClient(app) as client:
        headers = _auth_headers(client)
        detail = client.get("/buildings/B-FLOORS", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["available_floors"] == [1, 3]


def test_ingestion_and_unit_summary():
    db = SessionLocal()
    community = Community(community_id="C01", name="Community 01")
    db.add(community)
    unit = Unit(community_id="C01", unit_id="U01", va=1300)
    db.add(unit)
    db.commit()

    payload = {
        "community_id": "C01",
        "unit_id": "U01",
        "device_id": "ac",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "kwh": 1.2,
        "controllable": True,
        "schedules": [{"start_hour": 18, "end_hour": 22}],
    }
    IngestionService.ingest_event(db, payload, "energy/C01/U01/consumption")
    db.add(DeviceCatalog(device_key="ac", display_name="Air Conditioner", controllable=True, is_active=True))
    db.commit()
    db.close()

    with TestClient(app) as client:
        headers = _auth_headers(client)
        res = client.get("/units/U01/summary", params={"community_id": "C01"}, headers=headers)
        assert res.status_code == 200
        assert res.json()["total_kwh"] >= 1.2
        assert "device_emissions" in res.json()
        assert len(res.json()["device_emissions"]) == 1
        assert res.json()["device_emissions"][0]["device_name"] == "Air Conditioner"


def test_unit_daily_emissions_endpoint():
    db = SessionLocal()
    community = Community(community_id="CDE", name="Community Daily Emission")
    db.add(community)
    unit = Unit(community_id="CDE", unit_id="UDE", va=1300)
    db.add(unit)
    db.commit()

    base = datetime.now(timezone.utc)
    payloads = [
        {
            "community_id": "CDE",
            "unit_id": "UDE",
            "device_id": "ac",
            "timestamp": (base - timedelta(days=1)).isoformat(),
            "kwh": 1.0,
            "controllable": True,
            "schedules": [],
        },
        {
            "community_id": "CDE",
            "unit_id": "UDE",
            "device_id": "lamp",
            "timestamp": base.isoformat(),
            "kwh": 0.5,
            "controllable": True,
            "schedules": [],
        },
    ]
    for payload in payloads:
        IngestionService.ingest_event(db, payload, "energy/CDE/UDE/consumption")
    db.close()

    with TestClient(app) as client:
        headers = _auth_headers(client)
        res = client.get("/units/UDE/emissions/daily", params={"community_id": "CDE", "days": 30, "period": "all"}, headers=headers)
        assert res.status_code == 200
        body = res.json()
        assert body["community_id"] == "CDE"
        assert body["unit_id"] == "UDE"
        assert "series" in body
        assert len(body["series"]) >= 2
        assert body["total_emission_kg_co2e"] > 0


def test_unit_reports_history_multi_month_contract():
    db = SessionLocal()
    community = db.query(Community).filter(Community.community_id == "CRH").first()
    if not community:
        db.add(Community(community_id="CRH", name="Community Report History"))
    unit = db.query(Unit).filter(Unit.community_id == "CRH", Unit.unit_id == "URH").first()
    if not unit:
        db.add(Unit(community_id="CRH", unit_id="URH", va=1300))
    db.commit()

    payloads = [
        {"ts": datetime(2026, 1, 15, 9, 0, tzinfo=timezone.utc), "kwh": 3.0},
        {"ts": datetime(2026, 2, 15, 9, 0, tzinfo=timezone.utc), "kwh": 2.0},
        {"ts": datetime(2026, 3, 15, 9, 0, tzinfo=timezone.utc), "kwh": 1.0},
    ]
    for p in payloads:
        IngestionService.ingest_event(
            db,
            {
                "community_id": "CRH",
                "unit_id": "URH",
                "device_id": "ac",
                "timestamp": p["ts"].isoformat(),
                "kwh": p["kwh"],
                "controllable": True,
                "schedules": [],
            },
            "energy/CRH/URH/consumption",
        )
    db.close()

    with TestClient(app) as client:
        headers = _auth_headers(client)
        res = client.get(
            "/units/URH/reports/history",
            params={"community_id": "CRH", "limit": 2, "offset": 0},
            headers=headers,
        )
        assert res.status_code == 200
        body = res.json()
        assert "items" in body and "meta" in body
        assert body["meta"]["limit"] == 2
        assert body["meta"]["total"] >= 3
        assert body["items"][0]["period"] == "2026-03"
        assert body["items"][1]["period"] == "2026-02"
        assert "estimated_emission_kg_co2e" in body["items"][0]
        assert "estimated_cost" in body["items"][0]


def test_unit_reports_export_formats():
    db = SessionLocal()
    community = db.query(Community).filter(Community.community_id == "CEX").first()
    if not community:
        db.add(Community(community_id="CEX", name="Community Export"))
    unit = db.query(Unit).filter(Unit.community_id == "CEX", Unit.unit_id == "UEX").first()
    if not unit:
        db.add(Unit(community_id="CEX", unit_id="UEX", va=1300))
    db.commit()

    IngestionService.ingest_event(
        db,
        {
            "community_id": "CEX",
            "unit_id": "UEX",
            "device_id": "lamp",
            "timestamp": datetime(2026, 3, 10, 8, 0, tzinfo=timezone.utc).isoformat(),
            "kwh": 1.5,
            "controllable": True,
            "schedules": [],
        },
        "energy/CEX/UEX/consumption",
    )
    db.close()

    with TestClient(app) as client:
        headers = _auth_headers(client)
        csv_res = client.get(
            "/units/UEX/reports/export",
            params={"community_id": "CEX", "format": "csv", "period": "2026-03"},
            headers=headers,
        )
        assert csv_res.status_code == 200
        assert csv_res.headers["content-type"].startswith("text/csv")
        assert "attachment; filename=\"unit_UEX_report_2026-03.csv\"" in csv_res.headers["content-disposition"]

        xlsx_res = client.get(
            "/units/UEX/reports/export",
            params={"community_id": "CEX", "format": "xlsx", "period": "2026-03"},
            headers=headers,
        )
        assert xlsx_res.status_code == 200
        assert xlsx_res.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert xlsx_res.content[:2] == b"PK"

        pdf_res = client.get(
            "/units/UEX/reports/export",
            params={"community_id": "CEX", "format": "pdf", "period": "2026-03"},
            headers=headers,
        )
        assert pdf_res.status_code == 200
        assert pdf_res.headers["content-type"].startswith("application/pdf")
        assert pdf_res.content[:4] == b"%PDF"


def test_community_units_and_residents_detailed_contract():
    db = SessionLocal()
    if not db.query(Community).filter(Community.community_id == "CDTL").first():
        db.add(Community(community_id="CDTL", name="Community Detail"))
    if not db.query(Unit).filter(Unit.community_id == "CDTL", Unit.unit_id == "UD01").first():
        db.add(Unit(community_id="CDTL", unit_id="UD01", va=1300))
    if not db.query(User).filter(User.user_id == "resident-dtl").first():
        db.add(
            User(
                user_id="resident-dtl",
                full_name="Resident Detail",
                email="resident-dtl@nexora.local",
                password_hash="hashed",
                role=UserRole.RESIDENT,
                status=UserStatus.ACTIVE,
                community_id="CDTL",
                unit_id="UD01",
            )
        )
    db.commit()
    IngestionService.ingest_event(
        db,
        {
            "community_id": "CDTL",
            "unit_id": "UD01",
            "device_id": "ac",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "kwh": 1.1,
            "controllable": True,
            "schedules": [],
        },
        "energy/CDTL/UD01/consumption",
    )
    db.close()

    with TestClient(app) as client:
        headers = _auth_headers(client)
        units_res = client.get("/communities/CDTL/units/detailed", headers=headers)
        assert units_res.status_code == 200
        units_body = units_res.json()
        assert "items" in units_body and "meta" in units_body
        assert len(units_body["items"]) >= 1
        assert {"unit_id", "owner", "consumption", "devices_count", "risk", "recommendation", "last_seen", "status"}.issubset(
            set(units_body["items"][0].keys())
        )

        residents_res = client.get("/communities/CDTL/residents/detailed", headers=headers)
        assert residents_res.status_code == 200
        residents_body = residents_res.json()
        assert "items" in residents_body and "meta" in residents_body
        assert len(residents_body["items"]) >= 1
        assert {"user", "unit", "consumption", "risk", "interaction_metadata"}.issubset(
            set(residents_body["items"][0].keys())
        )


def test_community_reports_history_and_daily_contract():
    db = SessionLocal()
    if not db.query(Community).filter(Community.community_id == "CRPT").first():
        db.add(Community(community_id="CRPT", name="Community Report"))
    if not db.query(Unit).filter(Unit.community_id == "CRPT", Unit.unit_id == "URPT").first():
        db.add(Unit(community_id="CRPT", unit_id="URPT", va=1300))
    db.commit()
    IngestionService.ingest_event(
        db,
        {
            "community_id": "CRPT",
            "unit_id": "URPT",
            "device_id": "lamp",
            "timestamp": datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc).isoformat(),
            "kwh": 2.5,
            "controllable": True,
            "schedules": [],
        },
        "energy/CRPT/URPT/consumption",
    )
    db.close()

    with TestClient(app) as client:
        headers = _auth_headers(client)
        history_res = client.get("/communities/CRPT/reports/history", headers=headers)
        assert history_res.status_code == 200
        history = history_res.json()
        assert "items" in history and "meta" in history
        daily_res = client.get("/communities/CRPT/consumption/daily", params={"days": 7}, headers=headers)
        assert daily_res.status_code == 200
        daily = daily_res.json()
        assert {"community_id", "series", "period_used", "period_start", "last_timestamp", "is_fresh"}.issubset(set(daily.keys()))


def test_community_settings_notification_preferences_and_optimization():
    db = SessionLocal()
    if not db.query(Community).filter(Community.community_id == "CSET").first():
        db.add(Community(community_id="CSET", name="Community Settings"))
    if not db.query(Unit).filter(Unit.community_id == "CSET", Unit.unit_id == "USET").first():
        db.add(Unit(community_id="CSET", unit_id="USET", va=1300))
    db.commit()
    IngestionService.ingest_event(
        db,
        {
            "community_id": "CSET",
            "unit_id": "USET",
            "device_id": "ac",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "kwh": 1.0,
            "controllable": True,
            "schedules": [],
        },
        "energy/CSET/USET/consumption",
    )
    db.add(
        AIAnalysisResult(
            community_id="CSET",
            status="success",
            stale=False,
            source="manual",
            payload={},
            result={
                "result": {
                    "recommendations": [
                        {
                            "unit_id": "USET",
                            "device": "ac",
                            "action": "turn_off",
                            "estimated_reduction_kwh": 1.2,
                            "saving": 1000,
                            "co2_reduction": 0.5,
                            "reasons": ["test"],
                        }
                    ]
                }
            },
            error="",
        )
    )
    db.commit()
    db.close()

    with TestClient(app) as client:
        headers = _auth_headers(client)
        get_settings = client.get("/communities/CSET/settings", headers=headers)
        assert get_settings.status_code == 200
        put_settings = client.put(
            "/communities/CSET/settings",
            json={
                "tariff": 1500,
                "emission_factor": 0.9,
                "thresholds": {"high_kwh": 2.0, "critical_kwh": 3.5},
                "notification_config": {"enabled": True, "daily_digest": False, "realtime_alert": True},
            },
            headers=headers,
        )
        assert put_settings.status_code == 200
        assert put_settings.json()["tariff"] == 1500

        prefs_put = client.put(
            "/users/admin-001/notification-preferences",
            json={"preferences": {"email": True, "push": False}},
            headers=headers,
        )
        assert prefs_put.status_code == 200
        prefs_get = client.get("/users/admin-001/notification-preferences", headers=headers)
        assert prefs_get.status_code == 200
        assert prefs_get.json()["preferences"]["email"] is True

        sim = client.get("/communities/CSET/optimization-simulation", headers=headers)
        assert sim.status_code == 200
        sim_body = sim.json()
        assert {"community_id", "exists", "summary", "scenarios"}.issubset(set(sim_body.keys()))


def test_ai_health_and_run_now_success():
    ai_orchestrator.client.health = lambda: {"status": "ok"}
    ai_orchestrator.client.analyze = lambda payload: {
        "status": "success",
        "community_id": payload["community_id"],
        "result": {"community": {"current": 1.2}},
    }

    with TestClient(app) as client:
        headers = _auth_headers(client)
        h = client.get("/ai/health", headers=headers)
        assert h.status_code == 200
        assert h.json()["status"] == "ok"

        run = client.post("/ai/run-now", params={"community_id": "C01"}, headers=headers)
        assert run.status_code == 200
        assert run.json()["status"] == "success"

        last = client.get("/ai/last-result", params={"community_id": "C01"}, headers=headers)
        assert last.status_code == 200
        assert last.json()["exists"] is True
        assert last.json()["stale"] is False


def test_ai_fallback_stale_on_error():
    ai_orchestrator.client.analyze = lambda payload: (_ for _ in ()).throw(Exception("timeout"))

    with TestClient(app) as client:
        headers = _auth_headers(client)
        run = client.post("/ai/run-now", params={"community_id": "C01"}, headers=headers)
        assert run.status_code == 200
        body = run.json()
        assert body["status"] == "failed"
        assert body["stale"] is True

        last = client.get("/ai/last-result", params={"community_id": "C01"}, headers=headers)
        assert last.status_code == 200
        assert "exists" in last.json()


def test_update_unit_va():
    with TestClient(app) as client:
        headers = _auth_headers(client)
        res = client.put("/units/U01/va", params={"community_id": "C01"}, json={"va": 2200}, headers=headers)
        assert res.status_code == 200
        body = res.json()
        assert body["community_id"] == "C01"
        assert body["unit_id"] == "U01"
        assert body["va"] == 2200


def test_community_and_unit_crud_minimum():
    with TestClient(app) as client:
        headers = _auth_headers(client)
        created = client.post("/communities", json={"community_id": "C02", "name": "Community 02"}, headers=headers)
        assert created.status_code == 200
        assert created.json()["community_id"] == "C02"

        listed = client.get("/communities", headers=headers)
        assert listed.status_code == 200
        assert any(c["community_id"] == "C02" for c in listed.json()["items"])

        unit_create = client.post("/communities/C02/units", json={"unit_id": "U99", "va": 1300}, headers=headers)
        assert unit_create.status_code == 200
        assert unit_create.json()["unit_id"] == "U99"

        unit_update = client.put("/communities/C02/units/U99", json={"va": 2200}, headers=headers)
        assert unit_update.status_code == 200
        assert unit_update.json()["va"] == 2200

        unit_delete = client.delete("/communities/C02/units/U99", headers=headers)
        assert unit_delete.status_code == 200

        community_delete = client.delete("/communities/C02", headers=headers)
        assert community_delete.status_code == 200


def test_community_units_summary():
    with TestClient(app) as client:
        headers = _auth_headers(client)
        res = client.get("/communities/C01/units-summary", headers=headers)
        assert res.status_code == 200
        rows = res.json()
        assert any(r["unit_id"] == "U01" for r in rows)


def test_advanced_list_communities_contract_and_filter():
    with TestClient(app) as client:
        headers = _auth_headers(client)
        res = client.get("/communities", params={"offset": 0, "limit": 10, "q": "C0", "sort_by": "community_id", "sort_order": "asc"}, headers=headers)
        assert res.status_code == 200
        body = res.json()
        assert "items" in body and "meta" in body
        assert {"total", "offset", "limit", "has_next"}.issubset(set(body["meta"].keys()))


def test_advanced_list_units_contract_filter_sort():
    with TestClient(app) as client:
        headers = _auth_headers(client)
        res = client.get(
            "/communities/C01/units",
            params={"offset": 0, "limit": 10, "q": "U0", "sort_by": "va", "sort_order": "desc"},
            headers=headers,
        )
        assert res.status_code == 200
        body = res.json()
        assert "items" in body and "meta" in body
        assert {"total", "offset", "limit", "has_next"}.issubset(set(body["meta"].keys()))


def test_bulk_delete_units_mixed_found_and_not_found():
    with TestClient(app) as client:
        headers = _auth_headers(client)
        client.post("/communities/C01/units", json={"unit_id": "U88", "va": 1300}, headers=headers)
        client.post("/communities/C01/units", json={"unit_id": "U89", "va": 1300}, headers=headers)

        res = client.post("/communities/C01/units/bulk-delete", json={"unit_ids": ["U88", "U89", "U404"]}, headers=headers)
        assert res.status_code == 200
        body = res.json()
        assert body["requested_count"] == 3
        assert body["deleted_count"] == 2
        assert "U404" in body["not_found_unit_ids"]


def test_ai_status_contract():
    ai_orchestrator.client.health = lambda: {"status": "ok"}
    with TestClient(app) as client:
        headers = _auth_headers(client)
        res = client.get("/ai/status", params={"community_id": "C01"}, headers=headers)
        assert res.status_code == 200
        body = res.json()
        assert body["community_id"] == "C01"
        assert "exists" in body
        assert "healthy" in body
        assert "last_run_at" in body
        assert "last_success_at" in body
        assert "stale" in body
        assert "error" in body
        assert "source" in body


def test_dashboard_bundle_contract():
    ai_orchestrator.client.health = lambda: {"status": "ok"}
    with TestClient(app) as client:
        headers = _auth_headers(client)
        res = client.get("/communities/C01/dashboard", headers=headers)
        assert res.status_code == 200
        body = res.json()
        assert "community" in body
        assert "units_summary" in body
        assert "load_curve" in body
        assert "peak_risk" in body
        assert "ai_status" in body
        assert "unit_ai_recommendations" in body
        assert isinstance(body["unit_ai_recommendations"], dict)
        assert "generated_at" in body
        assert body["community"]["community_id"] == "C01"


def test_dashboard_bundle_community_not_found():
    with TestClient(app) as client:
        headers = _auth_headers(client)
        res = client.get("/communities/UNKNOWN/dashboard", headers=headers)
        assert res.status_code == 404


def test_ws_dashboard_initial_snapshot():
    db = SessionLocal()
    exists = db.query(Community).filter(Community.community_id == "C01").first()
    if not exists:
        db.add(Community(community_id="C01", name="Community 01"))
    unit_exists = db.query(Unit).filter(Unit.community_id == "C01", Unit.unit_id == "U01").first()
    if not unit_exists:
        db.add(Unit(community_id="C01", unit_id="U01", va=1300))
    db.commit()
    db.close()

    with TestClient(app) as client:
        headers = _auth_headers(client)
        token = headers["Authorization"].split(" ", 1)[1]
        with client.websocket_connect(f"/ws/communities/C01/dashboard?token={token}") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "dashboard_snapshot"
            assert msg["community_id"] == "C01"
            assert "data" in msg
            assert msg["data"]["community"]["community_id"] == "C01"


def test_ws_dashboard_realtime_update():
    db = SessionLocal()
    exists = db.query(Community).filter(Community.community_id == "C01").first()
    if not exists:
        db.add(Community(community_id="C01", name="Community 01"))
    unit_exists = db.query(Unit).filter(Unit.community_id == "C01", Unit.unit_id == "U01").first()
    if not unit_exists:
        db.add(Unit(community_id="C01", unit_id="U01", va=1300))
    db.commit()
    db.close()

    with TestClient(app) as client:
        headers = _auth_headers(client)
        token = headers["Authorization"].split(" ", 1)[1]
        with client.websocket_connect(f"/ws/communities/C01/dashboard?token={token}") as ws:
            # Initial snapshot
            _ = ws.receive_json()

            db = SessionLocal()
            payload = {
                "community_id": "C01",
                "unit_id": "U01",
                "device_id": "lamp",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "kwh": 0.7,
                "controllable": True,
            }
            IngestionService.ingest_event(db, payload, "energy/C01/U01/consumption")
            db.close()

            msg = ws.receive_json()
            assert msg["type"] == "dashboard_snapshot"
            assert msg["community_id"] == "C01"


def test_unit_dashboard_contract():
    db = SessionLocal()
    if not db.query(Community).filter(Community.community_id == "C01").first():
        db.add(Community(community_id="C01", name="Community 01"))
    if not db.query(Unit).filter(Unit.community_id == "C01", Unit.unit_id == "U01").first():
        db.add(Unit(community_id="C01", unit_id="U01", va=1300))
    db.commit()
    db.close()

    with TestClient(app) as client:
        headers = _auth_headers(client)
        res = client.get("/communities/C01/units/U01/dashboard", headers=headers)
        assert res.status_code == 200
        body = res.json()
        assert body["community_id"] == "C01"
        assert body["unit_id"] == "U01"
        assert "unit_summary" in body
        assert "load_curve" in body
        assert "peak_risk" in body
        assert "ai_recommendations" in body
        assert "generated_at" in body


def test_ws_unit_dashboard_initial_and_update_isolation():
    db = SessionLocal()
    if not db.query(Community).filter(Community.community_id == "C01").first():
        db.add(Community(community_id="C01", name="Community 01"))
    if not db.query(Unit).filter(Unit.community_id == "C01", Unit.unit_id == "U01").first():
        db.add(Unit(community_id="C01", unit_id="U01", va=1300))
    if not db.query(Unit).filter(Unit.community_id == "C01", Unit.unit_id == "U02").first():
        db.add(Unit(community_id="C01", unit_id="U02", va=1300))
    db.commit()
    db.close()

    with TestClient(app) as client:
        headers = _auth_headers(client)
        token = headers["Authorization"].split(" ", 1)[1]
        with client.websocket_connect(f"/ws/communities/C01/units/U01/dashboard?token={token}") as ws_u01:
            with client.websocket_connect(f"/ws/communities/C01/units/U02/dashboard?token={token}") as ws_u02:
                m1 = ws_u01.receive_json()
                m2 = ws_u02.receive_json()
                assert m1["type"] == "unit_dashboard_snapshot"
                assert m1["unit_id"] == "U01"
                assert m2["type"] == "unit_dashboard_snapshot"
                assert m2["unit_id"] == "U02"

                db = SessionLocal()
                IngestionService.ingest_event(
                    db,
                    {
                        "community_id": "C01",
                        "unit_id": "U01",
                        "device_id": "ac",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "kwh": 0.4,
                        "controllable": True,
                    },
                    "energy/C01/U01/consumption",
                )
                db.close()

                upd = ws_u01.receive_json()
                assert upd["type"] == "unit_dashboard_snapshot"
                assert upd["unit_id"] == "U01"


def test_ai_recommendations_contract_exists_false():
    with TestClient(app) as client:
        headers = _auth_headers(client)
        res = client.get("/communities/UNKNOWN/ai-recommendations", headers=headers)
        assert res.status_code == 200
        body = res.json()
        assert body["community_id"] == "UNKNOWN"
        assert body["exists"] is False
        assert body["recommendations"] == []


def test_ai_recommendations_contract_exists_true():
    ai_orchestrator.client.analyze = lambda payload: {
        "result": {
            "recommendations": [
                {
                    "unit_id": "U01",
                    "device": "ac",
                    "action": "turn_off",
                    "saving": 1000.5,
                    "co2_reduction": 0.25,
                    "estimated_reduction_kwh": 0.3,
                    "reasons": ["outside schedule"],
                }
            ]
        }
    }
    with TestClient(app) as client:
        headers = _auth_headers(client)
        run = client.post("/ai/run-now", params={"community_id": "C01"}, headers=headers)
        assert run.status_code == 200
        res = client.get("/communities/C01/ai-recommendations", headers=headers)
        assert res.status_code == 200
        body = res.json()
        assert body["exists"] is True
        assert isinstance(body["recommendations"], list)
        assert body["recommendations"][0]["unit_id"] == "U01"


def test_unit_ai_recommendations_contract_exists_false():
    db = SessionLocal()
    if not db.query(Community).filter(Community.community_id == "C08").first():
        db.add(Community(community_id="C08", name="Community 08"))
    if not db.query(Unit).filter(Unit.community_id == "C08", Unit.unit_id == "U08").first():
        db.add(Unit(community_id="C08", unit_id="U08", va=1300))
    db.commit()
    db.close()
    with TestClient(app) as client:
        headers = _auth_headers(client)
        res = client.get("/units/U08/ai-recommendations", params={"community_id": "C08"}, headers=headers)
        assert res.status_code == 200
        body = res.json()
        assert body["exists"] is False
        assert body["recommendations"] == []


def test_unit_ai_recommendations_contract_exists_true():
    ai_orchestrator.client.analyze = lambda payload: {
        "result": {
            "recommendations": [
                {
                    "unit_id": "U01",
                    "device": "ac",
                    "action": "turn_off",
                    "saving": 1200.0,
                    "co2_reduction": 0.3,
                    "estimated_reduction_kwh": 0.4,
                    "reasons": ["outside schedule"],
                },
                {
                    "unit_id": "U02",
                    "device": "tv",
                    "action": "reduce",
                    "saving": 500.0,
                    "co2_reduction": 0.1,
                    "estimated_reduction_kwh": 0.2,
                    "reasons": ["peak risk"],
                },
            ]
        }
    }
    db = SessionLocal()
    if not db.query(Unit).filter(Unit.community_id == "C01", Unit.unit_id == "U02").first():
        db.add(Unit(community_id="C01", unit_id="U02", va=1300))
        db.commit()
    db.close()
    with TestClient(app) as client:
        headers = _auth_headers(client)
        run = client.post("/ai/run-now", params={"community_id": "C01"}, headers=headers)
        assert run.status_code == 200
        res = client.get("/units/U01/ai-recommendations", params={"community_id": "C01"}, headers=headers)
        assert res.status_code == 200
        body = res.json()
        assert body["community_id"] == "C01"
        assert body["unit_id"] == "U01"
        assert body["exists"] is True
        assert isinstance(body["recommendations"], list)
        assert all(item.get("unit_id") == "U01" for item in body["recommendations"])


def test_ops_ingestion_status_contract():
    with TestClient(app) as client:
        headers = _auth_headers(client)
        res = client.get("/ops/ingestion-status", headers=headers)
        assert res.status_code == 200
        body = res.json()
        assert "mqtt" in body
        assert "totals" in body
        assert "latest" in body
        assert "per_community" in body
        assert "energy_readings_count" in body["totals"]
        assert "dead_letters_count" in body["totals"]


def test_ops_dead_letters_contract_and_limit():
    # Insert one invalid event to produce dead letter.
    db = SessionLocal()
    invalid_payload = {
        "community_id": "C01",
        "unit_id": "U01",
        "device_id": "ac",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "controllable": True,
    }
    IngestionService.ingest_event(db, invalid_payload, "energy/C01/U01/consumption")
    db.close()

    with TestClient(app) as client:
        headers = _auth_headers(client)
        res = client.get("/ops/dead-letters", params={"offset": 0, "limit": 10, "sort_by": "created_at", "sort_order": "desc"}, headers=headers)
        assert res.status_code == 200
        body = res.json()
        assert "meta" in body
        assert "items" in body
        assert isinstance(body["items"], list)
        assert {"total", "offset", "limit", "has_next"}.issubset(set(body["meta"].keys()))
        if body["items"]:
            item = body["items"][0]
            assert "id" in item
            assert "topic" in item
            assert "reason" in item
            assert "raw_payload" in item
            assert "created_at" in item


def test_building_analytics_notifications_and_config():
    db = SessionLocal()
    if not db.query(Community).filter(Community.community_id == "C01").first():
        db.add(Community(community_id="C01", name="Community 01"))
    if not db.query(Unit).filter(Unit.community_id == "C01", Unit.unit_id == "U01").first():
        db.add(Unit(community_id="C01", unit_id="U01", va=1300))
    if not db.query(Building).filter(Building.building_id == "B01").first():
        db.add(Building(building_id="B01", name="Tower A"))
    if not db.query(BuildingUnit).filter(BuildingUnit.building_id == "B01", BuildingUnit.unit_id == "U01").first():
        db.add(BuildingUnit(building_id="B01", unit_id="U01", is_active=True, metadata_json={"floor": 1}))

    payload = {
        "community_id": "C01",
        "unit_id": "U01",
        "device_id": "ac",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "kwh": 0.9,
        "controllable": True,
    }
    IngestionService.ingest_event(db, payload, "energy/C01/U01/consumption")

    db.add(
        AIAnalysisResult(
            community_id="C01",
            status="success",
            stale=False,
            source="manual",
            payload={"community_id": "C01"},
            result={
                "result": {
                    "unit_predictions": {"U01": 1.1},
                    "recommendations": [
                        {
                            "unit_id": "U01",
                            "device": "ac",
                            "action": "reduce",
                            "saving": 500.0,
                            "co2_reduction": 0.2,
                            "estimated_reduction_kwh": 0.3,
                            "reasons": ["peak risk"],
                        }
                    ],
                }
            },
            error="",
        )
    )
    db.commit()
    db.close()

    with TestClient(app) as client:
        headers = _auth_headers(client)

        consumption = client.get("/buildings/B01/consumption", params={"window": "hourly", "hours": 24}, headers=headers)
        assert consumption.status_code == 200
        cbody = consumption.json()
        assert cbody["building_id"] == "B01"
        assert "series" in cbody
        assert "total_kwh" in cbody

        predictions = client.get("/buildings/B01/predictions", headers=headers)
        assert predictions.status_code == 200
        pbody = predictions.json()
        assert pbody["building_id"] == "B01"
        assert "exists" in pbody
        assert "unit_predictions" in pbody

        recommendations = client.get("/buildings/B01/recommendations", headers=headers)
        assert recommendations.status_code == 200
        rbody = recommendations.json()
        assert rbody["building_id"] == "B01"
        assert "exists" in rbody
        assert "items" in rbody

        notify = client.post("/buildings/B01/notifications", json={"message": "Demo alert"}, headers=headers)
        assert notify.status_code == 200
        nbody = notify.json()
        assert nbody["status"] == "queued"
        assert nbody["scope"] == "building"

        get_cfg = client.get("/buildings/B01/config", headers=headers)
        assert get_cfg.status_code == 200
        assert "peak_threshold_kwh" in get_cfg.json()

        put_cfg = client.put("/buildings/B01/config", json={"peak_threshold_kwh": 4.2}, headers=headers)
        assert put_cfg.status_code == 200
        assert put_cfg.json()["peak_threshold_kwh"] == 4.2


def test_building_manager_scope_access_enforced():
    db = SessionLocal()
    if not db.query(Building).filter(Building.building_id == "B01").first():
        db.add(Building(building_id="B01", name="Tower A"))
    if not db.query(Building).filter(Building.building_id == "B02").first():
        db.add(Building(building_id="B02", name="Tower B"))
    db.commit()
    db.close()

    with TestClient(app) as client:
        admin_headers = _auth_headers(client)
        create_manager = client.post(
            "/users",
            json={
                "user_id": "mgr-b01",
                "full_name": "Manager B01",
                "email": "mgr-b01@nexora.local",
                "password": "manager12345",
                "role": "ROLE_BUILDING_MANAGER",
                "status": "ACTIVE",
            },
            headers=admin_headers,
        )
        # idempotent for reruns
        assert create_manager.status_code in (200, 400)
        assign_manager = client.put(
            "/users/mgr-b01",
            json={"building_id": "B01"},
            headers=admin_headers,
        )
        assert assign_manager.status_code == 200

        login_mgr = client.post("/auth/login", json={"email": "mgr-b01@nexora.local", "password": "manager12345"})
        assert login_mgr.status_code == 200
        mgr_token = login_mgr.json()["access_token"]
        mgr_headers = {"Authorization": f"Bearer {mgr_token}"}

        allowed = client.get("/buildings/B01/config", headers=mgr_headers)
        assert allowed.status_code == 200

        forbidden_config = client.get("/buildings/B02/config", headers=mgr_headers)
        assert forbidden_config.status_code == 403

        forbidden_consumption = client.get(
            "/buildings/B02/consumption",
            params={"window": "hourly", "hours": 24},
            headers=mgr_headers,
        )
        assert forbidden_consumption.status_code == 403

        forbidden_predictions = client.get("/buildings/B02/predictions", headers=mgr_headers)
        assert forbidden_predictions.status_code == 403

        forbidden_recommendations = client.get("/buildings/B02/recommendations", headers=mgr_headers)
        assert forbidden_recommendations.status_code == 403

        forbidden_notifications = client.post(
            "/buildings/B02/notifications",
            json={"message": "forbidden test"},
            headers=mgr_headers,
        )
        assert forbidden_notifications.status_code == 403


def test_community_members_crud_and_scope():
    db = SessionLocal()
    if not db.query(Community).filter(Community.community_id == "C03").first():
        db.add(Community(community_id="C03", name="Community 03"))
    db.commit()
    db.close()

    with TestClient(app) as client:
        admin_headers = _auth_headers(client)

        create_member = client.post(
            "/users",
            json={
                "user_id": "resident-c03",
                "full_name": "Resident C03",
                "email": "resident-c03@nexora.local",
                "password": "resident12345",
                "role": "ROLE_RESIDENT",
                "status": "ACTIVE",
            },
            headers=admin_headers,
        )
        assert create_member.status_code in (200, 400)

        add_member = client.post("/communities/C03/members", json={"user_id": "resident-c03"}, headers=admin_headers)
        assert add_member.status_code == 200
        assert add_member.json()["status"] in ("added", "already_member")

        list_members = client.get("/communities/C03/members", headers=admin_headers)
        assert list_members.status_code == 200
        body = list_members.json()
        assert "items" in body and "meta" in body
        assert any(item["user_id"] == "resident-c03" for item in body["items"])

        create_coord = client.post(
            "/users",
            json={
                "user_id": "coord-c03",
                "full_name": "Coordinator C03",
                "email": "coord-c03@nexora.local",
                "password": "coord12345",
                "role": "ROLE_COORDINATOR",
                "status": "ACTIVE",
            },
            headers=admin_headers,
        )
        assert create_coord.status_code in (200, 400)
        assign_coord = client.put(
            "/users/coord-c03",
            json={"community_id": "C03", "unit_id": "U01"},
            headers=admin_headers,
        )
        assert assign_coord.status_code == 200

        create_other_community = client.post(
            "/communities",
            json={"community_id": "C04", "name": "Community 04"},
            headers=admin_headers,
        )
        assert create_other_community.status_code in (200, 400)

        login_coord = client.post("/auth/login", json={"email": "coord-c03@nexora.local", "password": "coord12345"})
        assert login_coord.status_code == 200
        coord_headers = {"Authorization": f"Bearer {login_coord.json()['access_token']}"}

        allowed_coord_list = client.get("/communities/C03/members", headers=coord_headers)
        assert allowed_coord_list.status_code == 200

        forbidden_coord_list = client.get("/communities/C04/members", headers=coord_headers)
        assert forbidden_coord_list.status_code == 403

        remove_member = client.delete("/communities/C03/members/resident-c03", headers=admin_headers)
        assert remove_member.status_code == 200
        assert remove_member.json()["status"] == "removed"


def test_community_members_assign_user_with_building_scope_rejected():
    db = SessionLocal()
    if not db.query(Community).filter(Community.community_id == "C05").first():
        db.add(Community(community_id="C05", name="Community 05"))
    if not db.query(Building).filter(Building.building_id == "B05").first():
        db.add(Building(building_id="B05", name="Tower B05"))
    db.commit()
    db.close()

    with TestClient(app) as client:
        admin_headers = _auth_headers(client)
        create_user = client.post(
            "/users",
            json={
                "user_id": "mgr-b05",
                "full_name": "Manager B05",
                "email": "mgr-b05@nexora.local",
                "password": "manager12345",
                "role": "ROLE_BUILDING_MANAGER",
                "status": "ACTIVE",
            },
            headers=admin_headers,
        )
        assert create_user.status_code in (200, 400)
        assign_user = client.put(
            "/users/mgr-b05",
            json={"building_id": "B05"},
            headers=admin_headers,
        )
        assert assign_user.status_code == 200
        add = client.post("/communities/C05/members", json={"user_id": "mgr-b05"}, headers=admin_headers)
        assert add.status_code == 400


def test_me_dashboard_role_aware_contract():
    db = SessionLocal()
    if not db.query(Community).filter(Community.community_id == "C06").first():
        db.add(Community(community_id="C06", name="Community 06"))
    if not db.query(Unit).filter(Unit.community_id == "C06", Unit.unit_id == "U06").first():
        db.add(Unit(community_id="C06", unit_id="U06", va=1300))
    db.commit()
    db.close()

    with TestClient(app) as client:
        admin_headers = _auth_headers(client)
        admin_me = client.get("/me/dashboard", headers=admin_headers)
        assert admin_me.status_code == 200
        abody = admin_me.json()
        assert {"user", "scope", "widgets", "generated_at"}.issubset(set(abody.keys()))

        create_coord = client.post(
            "/users",
            json={
                "user_id": "coord-c06",
                "full_name": "Coordinator C06",
                "email": "coord-c06@nexora.local",
                "password": "coord12345",
                "role": "ROLE_COORDINATOR",
                "status": "ACTIVE",
            },
            headers=admin_headers,
        )
        assert create_coord.status_code in (200, 400)
        assign_coord = client.put(
            "/users/coord-c06",
            json={"community_id": "C06", "unit_id": "U06"},
            headers=admin_headers,
        )
        assert assign_coord.status_code == 200
        login_coord = client.post("/auth/login", json={"email": "coord-c06@nexora.local", "password": "coord12345"})
        assert login_coord.status_code == 200
        coord_headers = {"Authorization": f"Bearer {login_coord.json()['access_token']}"}
        coord_me = client.get("/me/dashboard", headers=coord_headers)
        assert coord_me.status_code == 200
        cbody = coord_me.json()
        assert "community_dashboard" in cbody["widgets"]


def test_simulation_toggle_and_status_contract_admin_and_coordinator():
    db = SessionLocal()
    if not db.query(Community).filter(Community.community_id == "C07").first():
        db.add(Community(community_id="C07", name="Community 07"))
    db.commit()
    db.close()

    with TestClient(app) as client:
        admin_headers = _auth_headers(client)

        status_default = client.get("/communities/C07/simulations", headers=admin_headers)
        assert status_default.status_code == 200
        assert status_default.json()["simulation_enabled"] is False
        assert status_default.json()["source"] == "default"

        toggled = client.post(
            "/communities/C07/simulations/toggle",
            json={"simulation_enabled": True},
            headers=admin_headers,
        )
        assert toggled.status_code == 200
        assert toggled.json()["simulation_enabled"] is True
        assert toggled.json()["source"] == "custom"

        create_coord = client.post(
            "/users",
            json={
                "user_id": "coord-c07",
                "full_name": "Coordinator C07",
                "email": "coord-c07@nexora.local",
                "password": "coord12345",
                "role": "ROLE_COORDINATOR",
                "status": "ACTIVE",
            },
            headers=admin_headers,
        )
        assert create_coord.status_code in (200, 400)
        assign_coord = client.put(
            "/users/coord-c07",
            json={"community_id": "C07", "unit_id": "U01"},
            headers=admin_headers,
        )
        assert assign_coord.status_code == 200

        login_coord = client.post("/auth/login", json={"email": "coord-c07@nexora.local", "password": "coord12345"})
        assert login_coord.status_code == 200
        coord_headers = {"Authorization": f"Bearer {login_coord.json()['access_token']}"}

        coord_status = client.get("/communities/C07/simulations", headers=coord_headers)
        assert coord_status.status_code == 200
        assert coord_status.json()["simulation_enabled"] is True

        forbidden_scope = client.get("/communities/C01/simulations", headers=coord_headers)
        assert forbidden_scope.status_code == 403


def test_simulation_endpoint_role_restriction():
    with TestClient(app) as client:
        admin_headers = _auth_headers(client)

        create_manager = client.post(
            "/users",
            json={
                "user_id": "mgr-sim",
                "full_name": "Manager Sim",
                "email": "mgr-sim@nexora.local",
                "password": "manager12345",
                "role": "ROLE_BUILDING_MANAGER",
                "status": "ACTIVE",
            },
            headers=admin_headers,
        )
        assert create_manager.status_code in (200, 400)
        assign_manager = client.put(
            "/users/mgr-sim",
            json={"building_id": "B01"},
            headers=admin_headers,
        )
        assert assign_manager.status_code == 200

        login_mgr = client.post("/auth/login", json={"email": "mgr-sim@nexora.local", "password": "manager12345"})
        assert login_mgr.status_code == 200
        mgr_headers = {"Authorization": f"Bearer {login_mgr.json()['access_token']}"}

        denied = client.get("/communities/C01/simulations", headers=mgr_headers)
        assert denied.status_code == 403


def test_healthz_contract():
    with TestClient(app) as client:
        res = client.get("/healthz")
        assert res.status_code == 200
        body = res.json()
        assert "status" in body
        assert "db" in body and "ok" in body["db"]
        assert "mqtt" in body and "enabled" in body["mqtt"]
        assert "ai" in body and "enabled" in body["ai"]


def test_validation_guardrails_offset_limit_sort():
    with TestClient(app) as client:
        headers = _auth_headers(client)

        bad_offset = client.get("/communities", params={"offset": -1, "limit": 20}, headers=headers)
        assert bad_offset.status_code == 400

        bad_limit = client.get("/communities", params={"offset": 0, "limit": 0}, headers=headers)
        assert bad_limit.status_code == 400

        bad_sort_order = client.get(
            "/communities",
            params={"offset": 0, "limit": 20, "sort_by": "community_id", "sort_order": "up"},
            headers=headers,
        )
        assert bad_sort_order.status_code == 400

        bad_sort_by_units = client.get(
            "/communities/C01/units",
            params={"offset": 0, "limit": 20, "sort_by": "unknown", "sort_order": "asc"},
            headers=headers,
        )
        assert bad_sort_by_units.status_code == 400

        bad_sort_dead_letters = client.get(
            "/ops/dead-letters",
            params={"offset": 0, "limit": 20, "sort_by": "unknown", "sort_order": "desc"},
            headers=headers,
        )
        assert bad_sort_dead_letters.status_code == 400


def test_ai_run_now_rate_limit_for_coordinator():
    db = SessionLocal()
    if not db.query(Community).filter(Community.community_id == "CRATE").first():
        db.add(Community(community_id="CRATE", name="Community Rate"))
    if not db.query(Unit).filter(Unit.community_id == "CRATE", Unit.unit_id == "URATE").first():
        db.add(Unit(community_id="CRATE", unit_id="URATE", va=1300))
    db.commit()
    IngestionService.ingest_event(
        db,
        {
            "community_id": "CRATE",
            "unit_id": "URATE",
            "device_id": "ac",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "kwh": 1.0,
            "controllable": True,
        },
        "energy/CRATE/URATE/consumption",
    )
    db.close()

    ai_orchestrator.client.analyze = lambda payload: {"status": "success", "community_id": payload["community_id"], "result": {}}

    with TestClient(app) as client:
        headers = _auth_headers(client)
        create_coord = client.post(
            "/users",
            json={
                "user_id": "coord-crate",
                "full_name": "Coordinator CRATE",
                "email": "coord-crate@nexora.local",
                "password": "coord12345",
                "role": "ROLE_COORDINATOR",
                "status": "ACTIVE",
            },
            headers=headers,
        )
        assert create_coord.status_code in (200, 400)
        assign_coord = client.put(
            "/users/coord-crate",
            json={"community_id": "CRATE", "unit_id": "URATE"},
            headers=headers,
        )
        assert assign_coord.status_code == 200
        login_coord = client.post("/auth/login", json={"email": "coord-crate@nexora.local", "password": "coord12345"})
        assert login_coord.status_code == 200
        coord_headers = {"Authorization": f"Bearer {login_coord.json()['access_token']}"}

        last_status = 200
        for _ in range(13):
            res = client.post("/ai/run-now", params={"community_id": "CRATE"}, headers=coord_headers)
            last_status = res.status_code
        assert last_status == 429


def test_include_simulation_query_behavior():
    db = SessionLocal()
    if not db.query(Community).filter(Community.community_id == "CSIM").first():
        db.add(Community(community_id="CSIM", name="Community Sim"))
    if not db.query(Unit).filter(Unit.community_id == "CSIM", Unit.unit_id == "USIM").first():
        db.add(Unit(community_id="CSIM", unit_id="USIM", va=1300))
    db.commit()

    IngestionService.ingest_event(
        db,
        {
            "community_id": "CSIM",
            "unit_id": "USIM",
            "device_id": "ac",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "kwh": 1.0,
            "controllable": True,
            "is_simulation": False,
        },
        "energy/CSIM/USIM/consumption",
    )
    IngestionService.ingest_event(
        db,
        {
            "community_id": "CSIM",
            "unit_id": "USIM",
            "device_id": "lamp",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "kwh": 2.0,
            "controllable": True,
            "is_simulation": True,
        },
        "energy/CSIM/USIM/consumption",
    )
    db.close()

    with TestClient(app) as client:
        admin_headers = _auth_headers(client)
        create_coord = client.post(
            "/users",
            json={
                "user_id": "coord-csim",
                "full_name": "Coordinator CSIM",
                "email": "coord-csim@nexora.local",
                "password": "coord12345",
                "role": "ROLE_COORDINATOR",
                "status": "ACTIVE",
            },
            headers=admin_headers,
        )
        assert create_coord.status_code in (200, 400)
        assign_coord = client.put(
            "/users/coord-csim",
            json={"community_id": "CSIM", "unit_id": "USIM"},
            headers=admin_headers,
        )
        assert assign_coord.status_code == 200
        login_coord = client.post("/auth/login", json={"email": "coord-csim@nexora.local", "password": "coord12345"})
        assert login_coord.status_code == 200
        coord_headers = {"Authorization": f"Bearer {login_coord.json()['access_token']}"}

        admin_default = client.get("/communities/CSIM/dashboard", headers=admin_headers)
        assert admin_default.status_code == 200
        assert admin_default.json()["include_simulation_used"] is True
        assert admin_default.json()["community"]["total_kwh"] >= 3.0

        coord_default = client.get("/communities/CSIM/dashboard", headers=coord_headers)
        assert coord_default.status_code == 200
        assert coord_default.json()["include_simulation_used"] is False
        assert coord_default.json()["community"]["total_kwh"] < admin_default.json()["community"]["total_kwh"]

        coord_include_true = client.get(
            "/communities/CSIM/dashboard",
            params={"include_simulation": "true"},
            headers=coord_headers,
        )
        assert coord_include_true.status_code == 200
        assert coord_include_true.json()["include_simulation_used"] is True
        assert coord_include_true.json()["community"]["total_kwh"] >= admin_default.json()["community"]["total_kwh"]


def test_notifications_device_catalog_device_control_and_csv_export():
    db = SessionLocal()
    if not db.query(Community).filter(Community.community_id == "C10").first():
        db.add(Community(community_id="C10", name="Community 10"))
    if not db.query(Unit).filter(Unit.community_id == "C10", Unit.unit_id == "U10").first():
        db.add(Unit(community_id="C10", unit_id="U10", va=2200))
    if not db.query(Building).filter(Building.building_id == "B10").first():
        db.add(Building(building_id="B10", name="Tower 10"))
    if not db.query(BuildingUnit).filter(BuildingUnit.building_id == "B10", BuildingUnit.unit_id == "U10").first():
        db.add(BuildingUnit(building_id="B10", unit_id="U10", is_active=True, metadata_json={}))
    db.commit()
    IngestionService.ingest_event(
        db,
        {
            "community_id": "C10",
            "unit_id": "U10",
            "device_id": "ac",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "kwh": 0.4,
            "controllable": True,
        },
        "energy/C10/U10/consumption",
    )
    db.close()

    with TestClient(app) as client:
        headers = _auth_headers(client)

        g_create = client.post(
            "/devices",
            json={"device_key": "aircon", "display_name": "Air Conditioner", "default_power_watt": 900, "controllable": True},
            headers=headers,
        )
        assert g_create.status_code in (200, 400)

        g_list = client.get("/devices", headers=headers)
        assert g_list.status_code == 200
        assert "items" in g_list.json()

        d_create = client.post(
            "/units/U10/devices",
            params={"community_id": "C10"},
            json={"device_id": "ac-main", "controllable": True, "schedules": [{"start_hour": 18, "end_hour": 22}]},
            headers=headers,
        )
        assert d_create.status_code in (200, 400)

        d_control = client.post(
            "/units/U10/devices/ac-main/control",
            params={"community_id": "C10"},
            json={"action": "on"},
            headers=headers,
        )
        assert d_control.status_code == 200
        assert d_control.json()["status"] in ("sent", "failed")

        n1 = client.post("/communities/C10/notifications", json={"message": "Test community notif"}, headers=headers)
        assert n1.status_code == 200
        n2 = client.post("/buildings/B10/notifications", json={"message": "Test building notif"}, headers=headers)
        assert n2.status_code == 200

        n_list = client.get("/notifications", headers=headers)
        assert n_list.status_code == 200
        assert "items" in n_list.json()
        assert "unread_count" in n_list.json()["meta"]
        if n_list.json()["items"]:
            assert "is_read" in n_list.json()["items"][0]
            assert n_list.json()["items"][0]["is_read"] is False
        if n_list.json()["items"]:
            notif_id = n_list.json()["items"][0]["notification_id"]
            n_detail = client.get(f"/notifications/{notif_id}", headers=headers)
            assert n_detail.status_code == 200
            assert n_detail.json()["is_read"] is False

            mark_one = client.post(f"/notifications/{notif_id}/mark-read", headers=headers)
            assert mark_one.status_code == 200
            assert mark_one.json()["status"] == "ok"

            n_detail_after = client.get(f"/notifications/{notif_id}", headers=headers)
            assert n_detail_after.status_code == 200
            assert n_detail_after.json()["is_read"] is True
            assert n_detail_after.json()["read_at"] is not None

        only_unread = client.get("/notifications", params={"status": "unread"}, headers=headers)
        assert only_unread.status_code == 200
        for item in only_unread.json()["items"]:
            assert item["is_read"] is False

        mark_all = client.post("/notifications/mark-all-read", headers=headers)
        assert mark_all.status_code == 200
        assert mark_all.json()["status"] == "ok"
        assert mark_all.json()["affected_count"] >= 0

        only_unread_after = client.get("/notifications", params={"status": "unread"}, headers=headers)
        assert only_unread_after.status_code == 200
        assert only_unread_after.json()["meta"]["unread_count"] == 0

        bad_status = client.get("/notifications", params={"status": "invalid"}, headers=headers)
        assert bad_status.status_code == 400

        c_export = client.get(
            "/communities/C10/reports/export",
            params={"format": "csv"},
            headers=headers,
        )
        assert c_export.status_code == 200
        assert "text/csv" in c_export.headers.get("content-type", "")

        b_export = client.get(
            "/buildings/B10/reports/export",
            params={"format": "csv"},
            headers=headers,
        )
        assert b_export.status_code == 200
        assert "text/csv" in b_export.headers.get("content-type", "")


def test_unit_device_qty_contract_and_validation():
    db = SessionLocal()
    if not db.query(Community).filter(Community.community_id == "CQTY").first():
        db.add(Community(community_id="CQTY", name="Community Qty"))
    if not db.query(Unit).filter(Unit.community_id == "CQTY", Unit.unit_id == "UQTY").first():
        db.add(Unit(community_id="CQTY", unit_id="UQTY", va=2200))
    db.commit()
    db.close()

    with TestClient(app) as client:
        headers = _auth_headers(client)

        create_default = client.post(
            "/units/UQTY/devices",
            params={"community_id": "CQTY"},
            json={"device_id": "lamp-qty", "controllable": True},
            headers=headers,
        )
        assert create_default.status_code in (200, 400)
        if create_default.status_code == 200:
            assert create_default.json()["qty"] == 1
            assert create_default.json()["is_active"] is True

        update_qty = client.put(
            "/units/UQTY/devices/lamp-qty",
            params={"community_id": "CQTY"},
            json={"qty": 3, "is_active": False},
            headers=headers,
        )
        assert update_qty.status_code == 200
        assert update_qty.json()["qty"] == 3
        assert update_qty.json()["is_active"] is False

        list_devices = client.get(
            "/units/UQTY/devices",
            params={"community_id": "CQTY", "offset": 0, "limit": 20},
            headers=headers,
        )
        assert list_devices.status_code == 200
        items = list_devices.json()["items"]
        target = next((x for x in items if x["device_id"] == "lamp-qty"), None)
        assert target is not None
        assert target["qty"] == 3
        assert target["is_active"] is False

        invalid_qty = client.post(
            "/units/UQTY/devices",
            params={"community_id": "CQTY"},
            json={"device_id": "invalid-qty", "qty": 0, "controllable": True},
            headers=headers,
        )
        assert invalid_qty.status_code == 400

        control_qty = client.post(
            "/units/UQTY/devices/lamp-qty/control",
            params={"community_id": "CQTY"},
            json={"action": "off"},
            headers=headers,
        )
        assert control_qty.status_code == 400
        err_msg = control_qty.json().get("detail") or control_qty.json().get("error", "")
        assert "inactive" in err_msg.lower()

        reactivate = client.put(
            "/units/UQTY/devices/lamp-qty",
            params={"community_id": "CQTY"},
            json={"is_active": True},
            headers=headers,
        )
        assert reactivate.status_code == 200
        assert reactivate.json()["is_active"] is True

        control_qty_after_reactivate = client.post(
            "/units/UQTY/devices/lamp-qty/control",
            params={"community_id": "CQTY"},
            json={"action": "off"},
            headers=headers,
        )
        assert control_qty_after_reactivate.status_code == 200
        assert control_qty_after_reactivate.json()["status"] in ("sent", "failed")


def test_unit_device_update_strict_validation_and_schedule_update():
    db = SessionLocal()
    if not db.query(Community).filter(Community.community_id == "CUPD").first():
        db.add(Community(community_id="CUPD", name="Community Update"))
    if not db.query(Unit).filter(Unit.community_id == "CUPD", Unit.unit_id == "UUPD").first():
        db.add(Unit(community_id="CUPD", unit_id="UUPD", va=2200))
    db.commit()
    db.close()

    with TestClient(app) as client:
        headers = _auth_headers(client)

        create = client.post(
            "/units/UUPD/devices",
            params={"community_id": "CUPD"},
            json={"device_id": "ac-upd", "controllable": True, "schedules": [{"start_hour": 8, "end_hour": 10}]},
            headers=headers,
        )
        assert create.status_code in (200, 400)

        bad_typo = client.put(
            "/units/UUPD/devices/ac-upd",
            params={"community_id": "CUPD"},
            json={"schedule": [{"start_hour": 9, "end_hour": 11}]},
            headers=headers,
        )
        assert bad_typo.status_code == 400

        no_op = client.put(
            "/units/UUPD/devices/ac-upd",
            params={"community_id": "CUPD"},
            json={},
            headers=headers,
        )
        assert no_op.status_code == 400

        good_update = client.put(
            "/units/UUPD/devices/ac-upd",
            params={"community_id": "CUPD"},
            json={"schedules": [{"start_hour": 9, "end_hour": 11}]},
            headers=headers,
        )
        assert good_update.status_code == 200

        listed = client.get(
            "/units/UUPD/devices",
            params={"community_id": "CUPD", "offset": 0, "limit": 20},
            headers=headers,
        )
        assert listed.status_code == 200
        item = next((x for x in listed.json()["items"] if x["device_id"] == "ac-upd"), None)
        assert item is not None
        assert item["schedules"] == [{"start_hour": 9, "end_hour": 11}]


def test_mqtt_ingestion_without_schedules_does_not_clear_manual_schedules():
    db = SessionLocal()
    if not db.query(Community).filter(Community.community_id == "CMQTT").first():
        db.add(Community(community_id="CMQTT", name="Community MQTT"))
    if not db.query(Unit).filter(Unit.community_id == "CMQTT", Unit.unit_id == "UMQTT").first():
        db.add(Unit(community_id="CMQTT", unit_id="UMQTT", va=2200))
    db.commit()
    db.close()

    with TestClient(app) as client:
        headers = _auth_headers(client)

        create = client.post(
            "/units/UMQTT/devices",
            params={"community_id": "CMQTT"},
            json={
                "device_id": "ac-mqtt",
                "controllable": True,
                "schedules": [{"start_hour": 18, "end_hour": 22}],
            },
            headers=headers,
        )
        assert create.status_code in (200, 400)

        # Ingestion event without schedules should not wipe schedules set by PUT/POST.
        db2 = SessionLocal()
        IngestionService.ingest_event(
            db2,
            {
                "community_id": "CMQTT",
                "unit_id": "UMQTT",
                "device_id": "ac-mqtt",
                "timestamp": "2026-05-07T12:00:00+00:00",
                "kwh": 1.1,
                "controllable": True,
            },
            "energy/CMQTT/UMQTT/consumption",
        )
        # A payload with explicit schedules=null must also keep existing schedule.
        IngestionService.ingest_event(
            db2,
            {
                "community_id": "CMQTT",
                "unit_id": "UMQTT",
                "device_id": "ac-mqtt",
                "timestamp": "2026-05-07T12:30:00+00:00",
                "kwh": 1.05,
                "controllable": True,
                "schedules": None,
            },
            "energy/CMQTT/UMQTT/consumption",
        )
        db2.close()

        listed = client.get(
            "/units/UMQTT/devices",
            params={"community_id": "CMQTT", "offset": 0, "limit": 20},
            headers=headers,
        )
        assert listed.status_code == 200
        item = next((x for x in listed.json()["items"] if x["device_id"] == "ac-mqtt"), None)
        assert item is not None
        assert item["schedules"] == [{"start_hour": 18, "end_hour": 22}]
        assert item["schedule_source"] == "manual"

        # Ingestion event with explicit schedules must NOT overwrite because source is manual.
        db3 = SessionLocal()
        IngestionService.ingest_event(
            db3,
            {
                "community_id": "CMQTT",
                "unit_id": "UMQTT",
                "device_id": "ac-mqtt",
                "timestamp": "2026-05-07T13:00:00+00:00",
                "kwh": 1.2,
                "controllable": True,
                "schedules": [{"start_hour": 9, "end_hour": 11}],
            },
            "energy/CMQTT/UMQTT/consumption",
        )
        db3.close()

        listed_after = client.get(
            "/units/UMQTT/devices",
            params={"community_id": "CMQTT", "offset": 0, "limit": 20},
            headers=headers,
        )
        assert listed_after.status_code == 200
        item_after = next((x for x in listed_after.json()["items"] if x["device_id"] == "ac-mqtt"), None)
        assert item_after is not None
        assert item_after["schedules"] == [{"start_hour": 18, "end_hour": 22}]
        assert item_after["schedule_source"] == "manual"


def test_mqtt_schedule_source_device_can_still_update_from_mqtt():
    db = SessionLocal()
    if not db.query(Community).filter(Community.community_id == "CMQ2").first():
        db.add(Community(community_id="CMQ2", name="Community MQTT 2"))
    if not db.query(Unit).filter(Unit.community_id == "CMQ2", Unit.unit_id == "UMQ2").first():
        db.add(Unit(community_id="CMQ2", unit_id="UMQ2", va=2200))
    db.commit()

    # Create device via ingestion path (source=mqtt).
    IngestionService.ingest_event(
        db,
        {
            "community_id": "CMQ2",
            "unit_id": "UMQ2",
            "device_id": "ac-live",
            "timestamp": "2026-05-07T10:00:00+00:00",
            "kwh": 1.0,
            "controllable": True,
            "schedules": [{"start_hour": 7, "end_hour": 9}],
        },
        "energy/CMQ2/UMQ2/consumption",
    )
    # Another ingestion updates schedules because source remains mqtt.
    IngestionService.ingest_event(
        db,
        {
            "community_id": "CMQ2",
            "unit_id": "UMQ2",
            "device_id": "ac-live",
            "timestamp": "2026-05-07T11:00:00+00:00",
            "kwh": 1.1,
            "controllable": True,
            "schedules": [{"start_hour": 9, "end_hour": 11}],
        },
        "energy/CMQ2/UMQ2/consumption",
    )
    db.close()

    with TestClient(app) as client:
        headers = _auth_headers(client)
        listed = client.get(
            "/units/UMQ2/devices",
            params={"community_id": "CMQ2", "offset": 0, "limit": 20},
            headers=headers,
        )
        assert listed.status_code == 200
        item = next((x for x in listed.json()["items"] if x["device_id"] == "ac-live"), None)
        assert item is not None
        assert item["schedule_source"] == "mqtt"
        assert item["schedules"] == [{"start_hour": 9, "end_hour": 11}]


def test_period_month_week_filter_and_comparison():
    db = SessionLocal()
    if not db.query(Community).filter(Community.community_id == "CPER").first():
        db.add(Community(community_id="CPER", name="Community Period"))
    if not db.query(Unit).filter(Unit.community_id == "CPER", Unit.unit_id == "UPER").first():
        db.add(Unit(community_id="CPER", unit_id="UPER", va=2200))
    db.commit()

    IngestionService.ingest_event(
        db,
        {
            "community_id": "CPER",
            "unit_id": "UPER",
            "device_id": "ac",
            "timestamp": "2026-04-20T10:00:00+00:00",
            "kwh": 5.0,
            "controllable": True,
        },
        "energy/CPER/UPER/consumption",
    )
    IngestionService.ingest_event(
        db,
        {
            "community_id": "CPER",
            "unit_id": "UPER",
            "device_id": "lamp",
            "timestamp": "2026-05-04T10:00:00+00:00",
            "kwh": 2.0,
            "controllable": True,
        },
        "energy/CPER/UPER/consumption",
    )
    db.close()

    with TestClient(app) as client:
        headers = _auth_headers(client)

        all_summary = client.get("/units/UPER/summary", params={"community_id": "CPER", "period": "all"}, headers=headers)
        month_summary = client.get("/units/UPER/summary", params={"community_id": "CPER", "period": "month"}, headers=headers)
        week_summary = client.get("/units/UPER/summary", params={"community_id": "CPER", "period": "week"}, headers=headers)
        assert all_summary.status_code == 200
        assert month_summary.status_code == 200
        assert week_summary.status_code == 200
        assert all_summary.json()["period_used"] == "all"
        assert month_summary.json()["period_used"] == "month"
        assert week_summary.json()["period_used"] == "week"
        assert month_summary.json()["period_start"] is not None
        assert week_summary.json()["period_start"] is not None
        assert all_summary.json()["total_kwh"] > month_summary.json()["total_kwh"]
        assert week_summary.json()["comparison"] is not None
        assert "consumption_pct" in week_summary.json()["comparison"]

        units_month = client.get("/communities/CPER/units-summary", params={"period": "month"}, headers=headers)
        units_week = client.get("/communities/CPER/units-summary", params={"period": "week"}, headers=headers)
        assert units_month.status_code == 200
        assert units_week.status_code == 200
        if units_month.json():
            assert units_month.json()[0]["period_used"] == "month"
            assert units_month.json()[0]["period_start"] is not None
            assert "comparison" in units_month.json()[0]
        if units_week.json():
            assert units_week.json()[0]["period_used"] == "week"
            assert "comparison" in units_week.json()[0]

        dash_month = client.get("/communities/CPER/dashboard", params={"period": "month"}, headers=headers)
        dash_week = client.get("/communities/CPER/dashboard", params={"period": "week"}, headers=headers)
        assert dash_month.status_code == 200
        assert dash_week.status_code == 200
        assert dash_month.json()["period_used"] == "month"
        assert dash_month.json()["period_start"] is not None
        assert dash_month.json()["community"]["period_used"] == "month"
        assert dash_month.json()["comparison"] is not None
        assert dash_month.json()["community"]["comparison"] is not None
        assert dash_week.json()["period_used"] == "week"
        assert dash_week.json()["comparison"] is not None

        bad_period = client.get("/communities/CPER/units-summary", params={"period": "weekly"}, headers=headers)
        assert bad_period.status_code == 400


def test_recommendation_compliance_command_matched():
    db = SessionLocal()
    if not db.query(Community).filter(Community.community_id == "CCMP").first():
        db.add(Community(community_id="CCMP", name="Community Compliance"))
    if not db.query(Unit).filter(Unit.community_id == "CCMP", Unit.unit_id == "UCMP").first():
        db.add(Unit(community_id="CCMP", unit_id="UCMP", va=2200))
    db.commit()

    analyzed_at = utc_now().replace(tzinfo=None) - timedelta(hours=2)
    db.add(
        AIAnalysisResult(
            community_id="CCMP",
            analyzed_at=analyzed_at,
            status="success",
            stale=False,
            source="manual",
            payload={},
            result={
                "result": {
                    "recommendations": [
                        {
                            "unit_id": "UCMP",
                            "device": "ac-main",
                            "action": "turn_off",
                            "saving": 1000,
                            "co2_reduction": 0.1,
                            "estimated_reduction_kwh": 0.2,
                            "reasons": ["outside schedule"],
                        }
                    ]
                }
            },
            error="",
        )
    )
    db.add(
        DeviceCommand(
            command_id="cmd-cmpr-1",
            community_id="CCMP",
            unit_id="UCMP",
            device_id="ac-main",
            action="off",
            topic="energy/CCMP/UCMP/control/ac-main",
            status="sent",
            error=None,
            created_by_user_id="admin-1",
            created_at=analyzed_at + timedelta(hours=1),
        )
    )
    db.commit()
    db.close()

    with TestClient(app) as client:
        headers = _auth_headers(client)
        u = client.get("/units/UCMP/summary", params={"community_id": "CCMP", "period": "week"}, headers=headers)
        assert u.status_code == 200
        ub = u.json()["recommendation_compliance"]
        assert ub["total_recommendations"] >= 1
        assert ub["followed_recommendations"] >= 1
        assert ub["compliance_pct"] is not None

        d = client.get("/communities/CCMP/dashboard", params={"period": "week"}, headers=headers)
        assert d.status_code == 200
        dbody = d.json()
        assert "recommendation_compliance" in dbody
        assert "recommendation_compliance" in dbody["community"]
        assert dbody["comparison"] is not None
        assert "compliance_pct_point_delta" in dbody["comparison"]
