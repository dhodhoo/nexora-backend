from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.database import SessionLocal
from app.services.ai_integration import ai_orchestrator
from app.services.mqtt_consumer import MQTTConsumer
from app.services.realtime_ws import dashboard_ws_manager
from app.services.tariff import TariffService
from app.config import settings

consumer = MQTTConsumer()


@asynccontextmanager
async def lifespan(_: FastAPI):
    dashboard_ws_manager.bind_loop(asyncio.get_running_loop())

    db = SessionLocal()
    TariffService.seed_defaults(db)
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
