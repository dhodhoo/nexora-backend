from contextlib import asynccontextmanager
import asyncio
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.api.routes import router
from app.database import SessionLocal
from app.models import AuditLog, User, UserRole, UserStatus
from app.services.auth import AuthService
from app.services.ai_integration import ai_orchestrator
from app.services.mqtt_consumer import MQTTConsumer
from app.services.realtime_ws import dashboard_ws_manager
from app.services.tariff import TariffService
from app.config import settings
from app.utils.time import utc_now

consumer = MQTTConsumer()


@asynccontextmanager
async def lifespan(_: FastAPI):
    dashboard_ws_manager.bind_loop(asyncio.get_running_loop())

    db = SessionLocal()
    TariffService.seed_defaults(db)
    admin = db.execute(select(User).where(User.email == settings.bootstrap_admin_email)).scalar_one_or_none()
    if not admin:
        db.add(
            User(
                user_id="admin-001",
                full_name="Nexora Admin",
                email=settings.bootstrap_admin_email,
                password_hash=AuthService.hash_password(settings.bootstrap_admin_password),
                role=UserRole.ADMIN,
                status=UserStatus.ACTIVE,
            )
        )
        db.commit()
    db.close()

    if settings.enable_mqtt:
        consumer.start()
    ai_orchestrator.scheduler_start()
    try:
        yield
    finally:
        if settings.enable_mqtt:
            consumer.stop()
        ai_orchestrator.scheduler_stop()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(router)


@app.middleware("http")
async def audit_write_actions(request: Request, call_next):
    response = await call_next(request)
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and response.status_code < 500:
        db = SessionLocal()
        try:
            user = getattr(request.state, "current_user", None)
            db.add(
                AuditLog(
                    log_id=str(uuid.uuid4()),
                    user_id=user.user_id if user else None,
                    role=user.role.value if user else None,
                    action=request.method,
                    resource=request.url.path,
                    payload=None,
                    ip_address=request.client.host if request.client else None,
                    created_at=utc_now(),
                )
            )
            db.commit()
        finally:
            db.close()
    return response


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=400, content={"error": "Request body must be valid JSON"})


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == 404:
        return JSONResponse(status_code=404, content={"error": "Not found"})
    if exc.status_code == 400:
        return JSONResponse(status_code=400, content={"error": str(exc.detail)})
    return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail)})


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"error": f"Internal error: {str(exc)}"})


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/healthz")
def healthz():
    db_ok = False
    db_error = ""
    db = SessionLocal()
    try:
        db.execute(select(User.id).limit(1)).first()
        db_ok = True
    except Exception as exc:
        db_error = str(exc)
    finally:
        db.close()

    ai_ok = False
    ai_error = ""
    if settings.ai_enabled:
        try:
            ai_ok = bool(ai_orchestrator.client.health().get("status") == "ok")
        except Exception as exc:
            ai_error = str(exc)
    else:
        ai_ok = True

    mqtt_status = consumer.status()
    overall = db_ok and ai_ok and (not settings.enable_mqtt or mqtt_status.get("running", False))
    return {
        "status": "ok" if overall else "degraded",
        "app": {"name": settings.app_name},
        "db": {"ok": db_ok, "error": db_error},
        "mqtt": {
            "enabled": settings.enable_mqtt,
            "host": settings.mqtt_host,
            "port": settings.mqtt_port,
            "running": mqtt_status.get("running", False),
            "connected": mqtt_status.get("connected", False),
            "last_error": mqtt_status.get("last_error", ""),
            "topics": mqtt_status.get("topics", []),
        },
        "ai": {
            "enabled": settings.ai_enabled,
            "ok": ai_ok,
            "base_url": settings.ai_base_url,
            "error": ai_error,
        },
    }
