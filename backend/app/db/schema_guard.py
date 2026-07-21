"""Idempotent DDL that runs on every backend boot.

Why this file exists
--------------------
The project had three disjoint ways of creating tables and no way at all to add a
column to an existing one:

  * ``db/init.sql``  -- mounted at ``docker-entrypoint-initdb.d``, so Postgres runs it
    ONLY when the data directory is empty. On a live volume it is dead weight; editing
    it changes nothing.
  * ``Base.metadata.create_all`` -- creates missing tables from the ORM, but never
    alters an existing one, so a new column on a mapped class is silently ignored.
  * ``auth_service.ensure_tables()`` -- hand-rolled DDL for ``platform_users`` only.

Consequence: ``oracle_signals`` and ``pulse_signal_log`` existed only because someone
typed CREATE TABLE into psql by hand. Nothing in the repo could recreate them, so
rebuilding the Postgres volume would have destroyed Oracle and Pulse with no way back.

Everything here must be safe to run repeatedly against a populated database: only
``IF NOT EXISTS`` forms, never a destructive or data-rewriting statement.
"""
from __future__ import annotations

from sqlalchemy import text

from backend.app.core.logging import get_logger
from backend.app.db.session import engine

logger = get_logger(__name__)


# Transcribed from the live production schema on 2026-07-20 so a rebuilt volume
# reproduces it exactly.
DDL_STATEMENTS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS oracle_signals (
        id             BIGSERIAL PRIMARY KEY,
        figure         TEXT NOT NULL,
        figure_name    TEXT,
        source_url     TEXT,
        headline       TEXT,
        ticker         TEXT NOT NULL,
        sentiment      TEXT,
        confidence     REAL,
        rationale      TEXT,
        price          REAL,
        market_cap     BIGINT,
        suggested_size REAL,
        pulse_score    REAL,
        status         TEXT DEFAULT 'new',
        detected_at    TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_oracle_detected ON oracle_signals (detected_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS pulse_signal_log (
        id                 BIGSERIAL PRIMARY KEY,
        ticker             VARCHAR(16) NOT NULL,
        side               VARCHAR(8) NOT NULL,
        strategy           VARCHAR(32),
        score              NUMERIC,
        entry_price        NUMERIC NOT NULL,
        entry_time         TIMESTAMPTZ DEFAULT NOW(),
        expected_exit_time TIMESTAMPTZ NOT NULL,
        tp_price           NUMERIC,
        sl_price           NUMERIC,
        suggested_size     NUMERIC,
        exit_price         NUMERIC,
        exit_time          TIMESTAMPTZ,
        exit_reason        VARCHAR(32),
        return_pct         NUMERIC,
        pnl_dollars        NUMERIC,
        win                BOOLEAN,
        status             VARCHAR(16) DEFAULT 'open',
        updated_at         TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_psl_status ON pulse_signal_log (status)",
    "CREATE INDEX IF NOT EXISTS idx_psl_exit_t ON pulse_signal_log (expected_exit_time)",
    "CREATE INDEX IF NOT EXISTS idx_psl_ticker ON pulse_signal_log (ticker)",

    # --- predictions: provenance + untouched model output -------------------------
    # `is_out_of_sample` distinguishes a genuine ex-ante forecast from a row that was
    # backfilled after the outcome was already known. Every page that reports
    # performance must filter on it; without the flag the two are indistinguishable
    # and in-sample rows silently inflate every headline number.
    "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS is_out_of_sample BOOLEAN DEFAULT FALSE",
    # `raw_prob_*` keeps the model's own output. calibrate_predictions.py used to
    # overwrite direction_prob_* in place, which permanently destroyed the originals
    # with no way to recover them.
    "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS raw_prob_up NUMERIC",
    "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS raw_prob_flat NUMERIC",
    "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS raw_prob_down NUMERIC",
    "CREATE INDEX IF NOT EXISTS idx_predictions_oos ON predictions (is_out_of_sample)",
]


def ensure_schema() -> None:
    """Apply every statement, isolating failures so one bad statement can't block the rest."""
    applied = failed = 0
    with engine.begin() as conn:
        for statement in DDL_STATEMENTS:
            try:
                conn.execute(text(statement))
                applied += 1
            except Exception as exc:  # noqa: BLE001 - never block boot on schema guard
                failed += 1
                logger.error("schema_guard statement failed: %s — %s", statement.strip()[:80], exc)
    logger.info("schema_guard: %s statements applied, %s failed", applied, failed)
