from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.routes.pulse_detail import router as pulse_detail_router
from backend.app.api.routes.logos import router as logos_router
from backend.app.api.routes.telegram_webhook import router as tg_webhook_router
from backend.app.api.routes.backtest import router as backtest_router
from backend.app.api.routes.calendar import router as calendar_router
from backend.app.api.routes.features import router as features_router
from backend.app.api.routes.health import router as health_router
from backend.app.api.routes.performance import router as performance_router
from backend.app.api.routes.predict import router as predict_router
from backend.app.api.routes.simulator import router as simulator_router
from backend.app.api.routes.track_record import router as track_record_router
from backend.app.api.routes.pulse_track_record import router as pulse_track_record_router
from backend.app.api.routes.ibkr_status import router as ibkr_status_router
from backend.app.api.routes.moomoo_status import router as broker_status_router
from backend.app.api.routes.oracle import router as oracle_router, oracle_worker
from backend.app.api.routes.showdown import router as showdown_router
from backend.app.api.routes.pulse import router as pulse_router
from backend.app.api.routes.quote import router as quote_router
from backend.app.api.routes.auth import router as auth_router
from backend.app.core.config import get_settings
from backend.app.core.logging import configure_logging
from backend.app.db.base import Base
from backend.app.db.session import engine

settings = get_settings()
configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    try:
        from backend.app.services.auth_service import ensure_tables
        ensure_tables()
    except Exception:
        pass
    # Tables/columns that create_all cannot produce: the two hand-made tables
    # (oracle_signals, pulse_signal_log) and any ADD COLUMN on an existing table.
    try:
        from backend.app.db.schema_guard import ensure_schema
        ensure_schema()
    except Exception:
        pass
    yield


import math as _math
from fastapi.responses import JSONResponse as _JSONResponse

def _json_safe(o):
    if isinstance(o, float):
        return o if _math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_json_safe(v) for v in o]
    return o

class SafeJSONResponse(_JSONResponse):
    def render(self, content) -> bytes:
        return super().render(_json_safe(content))

app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan, default_response_class=SafeJSONResponse)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix=settings.api_v1_prefix)
app.include_router(calendar_router, prefix=settings.api_v1_prefix)
app.include_router(features_router, prefix=settings.api_v1_prefix)
app.include_router(predict_router, prefix=settings.api_v1_prefix)
app.include_router(quote_router, prefix=settings.api_v1_prefix)
app.include_router(backtest_router, prefix=settings.api_v1_prefix)
app.include_router(performance_router, prefix=settings.api_v1_prefix)
app.include_router(track_record_router, prefix=settings.api_v1_prefix)
app.include_router(showdown_router, prefix=settings.api_v1_prefix)
app.include_router(pulse_router, prefix=settings.api_v1_prefix)
app.include_router(pulse_detail_router)
app.include_router(pulse_track_record_router)
app.include_router(ibkr_status_router)
app.include_router(broker_status_router)
app.include_router(oracle_router)
app.include_router(logos_router)
app.include_router(tg_webhook_router)
app.include_router(simulator_router, prefix=settings.api_v1_prefix)
app.include_router(auth_router)


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Earnings Movement Platform API", "docs": "/docs"}


# ═══ Start signal exit worker in background thread ═══
import asyncio as _asyncio_w
import threading as _threading_w
def _start_signal_worker():
    from backend.app.services.signal_tracker import signal_exit_worker
    loop = _asyncio_w.new_event_loop()
    _asyncio_w.set_event_loop(loop)
    loop.create_task(oracle_worker())
    loop.run_until_complete(signal_exit_worker())
_threading_w.Thread(target=_start_signal_worker, daemon=True).start()
