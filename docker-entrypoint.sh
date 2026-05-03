#!/bin/sh
set -e

echo "[entrypoint] waiting for postgres..."
python - <<'PY'
import time
from sqlalchemy import create_engine, text
from app.config import settings

for i in range(60):
    try:
        engine = create_engine(settings.database_url, future=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("[entrypoint] postgres ready")
        break
    except Exception as e:
        if i == 59:
            raise
        time.sleep(2)
PY

echo "[entrypoint] running migrations..."
alembic upgrade head

echo "[entrypoint] starting app..."
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8100