import os
import sys
from datetime import datetime, timezone

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
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB_NAME,))
            exists = cur.fetchone()
            if not exists:
                cur.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')


_ensure_test_database()
os.environ["DATABASE_URL"] = (
    f"postgresql+psycopg://{TEST_DB_USER}:{TEST_DB_PASSWORD}@{TEST_DB_HOST}:{TEST_DB_PORT}/{TEST_DB_NAME}"
)

from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import AIAnalysisResult, Building, BuildingUnit, Community, Unit, User
from app.services.ai_integration import ai_orchestrator
from app.services.ingestion import IngestionService


def setup_module(module):
    Base.metadata.drop_all(bind=engine)
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
    db.close()

    with TestClient(app) as client:
        headers = _auth_headers(client)
        res = client.get("/units/U01/summary", params={"community_id": "C01"}, headers=headers)
        assert res.status_code == 200
        assert res.json()["total_kwh"] >= 1.2


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
                "building_id": "B01",
                "unit_id": "U01",
            },
            headers=admin_headers,
        )
        # idempotent for reruns
        assert create_manager.status_code in (200, 400)

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
                "unit_id": "U01",
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
                "community_id": "C03",
                "unit_id": "U01",
            },
            headers=admin_headers,
        )
        assert create_coord.status_code in (200, 400)

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
                "building_id": "B05",
                "unit_id": "U01",
            },
            headers=admin_headers,
        )
        assert create_user.status_code in (200, 400)
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
                "community_id": "C06",
                "unit_id": "U06",
            },
            headers=admin_headers,
        )
        assert create_coord.status_code in (200, 400)
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
                "community_id": "C07",
                "unit_id": "U01",
            },
            headers=admin_headers,
        )
        assert create_coord.status_code in (200, 400)

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
                "building_id": "B01",
                "unit_id": "U01",
            },
            headers=admin_headers,
        )
        assert create_manager.status_code in (200, 400)

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
                "community_id": "CRATE",
                "unit_id": "URATE",
            },
            headers=headers,
        )
        assert create_coord.status_code in (200, 400)
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
                "community_id": "CSIM",
                "unit_id": "USIM",
            },
            headers=admin_headers,
        )
        assert create_coord.status_code in (200, 400)
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
        if n_list.json()["items"]:
            notif_id = n_list.json()["items"][0]["notification_id"]
            n_detail = client.get(f"/notifications/{notif_id}", headers=headers)
            assert n_detail.status_code == 200

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
