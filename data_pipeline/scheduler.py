from __future__ import annotations

import signal
import sys
import time

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from backend.app.core.config import get_settings
from backend.app.core.logging import configure_logging, get_logger
from data_pipeline.jobs import (
    run_pulse_scan,
    run_simulator_step,
    collect_earnings_calendar,
    collect_macro_data,
    collect_options_data,
    collect_post_earnings_results,
    retrain_models,
    run_predictions,
)

settings = get_settings()
configure_logging()
logger = get_logger(__name__)

scheduler = BackgroundScheduler(timezone=settings.scheduler_timezone)

# A CronTrigger built by hand resolves its timezone AT CONSTRUCTION, from the process's
# local zone — the scheduler's `timezone=` only applies when you hand add_job() trigger
# *parameters* and let it build the trigger. The container has no TZ set, so every cron
# job below was silently running on UTC: collect_options_data fired at 12:30 ET (mid
# session) instead of 16:30 ET (after the close), and run_predictions at 13:00 ET.
# Passing tz explicitly is what actually binds them to market time.
TZ = settings.scheduler_timezone

scheduler.add_job(collect_options_data, CronTrigger(hour=16, minute=30, timezone=TZ), id="collect_options_data", max_instances=1, coalesce=True)
scheduler.add_job(
    collect_earnings_calendar,
    CronTrigger(day_of_week="mon", hour=7, minute=0, timezone=TZ),
    id="collect_earnings_calendar",
    max_instances=1,
    coalesce=True,
)
scheduler.add_job(collect_macro_data, CronTrigger(hour=8, minute=0, timezone=TZ), id="collect_macro_data", max_instances=1, coalesce=True)
scheduler.add_job(run_predictions, CronTrigger(hour=17, minute=0, timezone=TZ), id="run_predictions", max_instances=1, coalesce=True)
scheduler.add_job(retrain_models, CronTrigger(month="*/1", day=1, hour=2, minute=0, timezone=TZ), id="retrain_models", max_instances=1, coalesce=True)
scheduler.add_job(
    run_simulator_step,
    IntervalTrigger(minutes=30),
    id="run_simulator_step",
    max_instances=1,
    coalesce=True,
)
scheduler.add_job(
    collect_post_earnings_results,
    IntervalTrigger(hours=1),
    id="collect_post_earnings_results",
    max_instances=1,
    coalesce=True,
)


def _shutdown(*_: object) -> None:
    logger.info("Stopping scheduler")
    scheduler.shutdown(wait=False)
    sys.exit(0)


scheduler.add_job(
    run_pulse_scan,
    IntervalTrigger(minutes=5),
    id="run_pulse_scan",
    max_instances=1,
    coalesce=True,
)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    logger.info("Starting scheduler with timezone %s", settings.scheduler_timezone)
    scheduler.start()
    while True:
        time.sleep(5)


