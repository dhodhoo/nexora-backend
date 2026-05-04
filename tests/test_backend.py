import os
import sys
from datetime import datetime, timezone

import psycopg

sys.path.insert(0, os.path.abspath("."))

os.environ["ENABLE_MQTT"] = "false"
os.environ["AI_ENABLED"] = "true"

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
from app.models import Community, Unit
from app.services.ai_integration import ai_orchestrator
from app.services.ingestion import IngestionService


def setup_module(module):
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


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
        res = client.get("/units/U01/summary", params={"community_id": "C01"})
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
        h = client.get("/ai/health")
        assert h.status_code == 200
        assert h.json()["status"] == "ok"

        run = client.post("/ai/run-now", params={"community_id": "C01"})
        assert run.status_code == 200
        assert run.json()["status"] == "success"

        last = client.get("/ai/last-result", params={"community_id": "C01"})
        assert last.status_code == 200
        assert last.json()["exists"] is True
        assert last.json()["stale"] is False


def test_ai_fallback_stale_on_error():
    ai_orchestrator.client.analyze = lambda payload: (_ for _ in ()).throw(Exception("timeout"))

    with TestClient(app) as client:
        run = client.post("/ai/run-now", params={"community_id": "C01"})
        assert run.status_code == 200
        body = run.json()
        assert body["status"] == "failed"
        assert body["stale"] is True

        last = client.get("/ai/last-result", params={"community_id": "C01"})
        assert last.status_code == 200
        assert "exists" in last.json()


def test_update_unit_va():
    with TestClient(app) as client:
        res = client.put("/units/U01/va", params={"community_id": "C01"}, json={"va": 2200})
        assert res.status_code == 200
        body = res.json()
        assert body["community_id"] == "C01"
        assert body["unit_id"] == "U01"
        assert body["va"] == 2200


def test_community_and_unit_crud_minimum():
    with TestClient(app) as client:
        created = client.post("/communities", json={"community_id": "C02", "name": "Community 02"})
        assert created.status_code == 200
        assert created.json()["community_id"] == "C02"

        listed = client.get("/communities")
        assert listed.status_code == 200
        assert any(c["community_id"] == "C02" for c in listed.json())

        unit_create = client.post("/communities/C02/units", json={"unit_id": "U99", "va": 1300})
        assert unit_create.status_code == 200
        assert unit_create.json()["unit_id"] == "U99"

        unit_update = client.put("/communities/C02/units/U99", json={"va": 2200})
        assert unit_update.status_code == 200
        assert unit_update.json()["va"] == 2200

        unit_delete = client.delete("/communities/C02/units/U99")
        assert unit_delete.status_code == 200

        community_delete = client.delete("/communities/C02")
        assert community_delete.status_code == 200


def test_community_units_summary():
    with TestClient(app) as client:
        res = client.get("/communities/C01/units-summary")
        assert res.status_code == 200
        rows = res.json()
        assert any(r["unit_id"] == "U01" for r in rows)
