from __future__ import annotations

import logging
from logging.config import dictConfig


LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
        }
    },
    "loggers": {
        # yfinance re-logs every failed symbol at ERROR on every call. run_pulse_scan runs
        # every 5 minutes over the whole universe, so two permanently-dead tickers were
        # producing tens of thousands of ERROR lines a day — enough to bury real errors and
        # to matter for disk on a 49G volume. Real failures still surface: callers log their
        # own message, and yfinance WARNING and above still comes through.
        "yfinance": {"level": "CRITICAL", "handlers": ["console"], "propagate": False},
        "peewee": {"level": "WARNING", "handlers": ["console"], "propagate": False},
        "urllib3": {"level": "WARNING", "handlers": ["console"], "propagate": False},
    },
    "root": {
        "level": "INFO",
        "handlers": ["console"],
    },
}


def configure_logging() -> None:
    dictConfig(LOGGING_CONFIG)
    # httpx logs every request URL at INFO, and FMP/FRED take the API key as a query
    # parameter — so the keys were being written to `docker logs` in plain text on every
    # collection run. Warnings and errors still come through.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
