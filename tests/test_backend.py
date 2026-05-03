import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath("."))

os.environ["DATABASE_URL"] = "sqlite:///./test_nexora.db"
os.environ["ENABLE_MQTT"] = "false"
os.environ["AI_ENABLED"] = "true"

from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import Unit
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
