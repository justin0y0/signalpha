from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.routes.backtest import router as backtest_router
from backend.app.api.routes.calendar import router as calendar_router
from backend.app.api.routes.features import router as features_router
from backend.app.api.routes.health import router as health_router
from backend.app.api.routes.performance import router as performance_router
from backend.app.api.routes.predict import router as predict_router
from backend.app.api.routes.simulator import router as simulator_router
from backend.app.api.routes.quote import router as quote_router
from backend.app.core.config import get_settings
from backend.app.core.logging import configure_logging
from backend.app.db.base import Base
from backend.app.db.session import engine

settings = get_settings()
configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
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
app.include_router(simulator_router, prefix=settings.api_v1_prefix)


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Earnings Movement Platform API", "docs": "/docs"}
