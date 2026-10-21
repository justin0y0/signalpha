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
    freeze_and_grade_receipts,
    issue_direction_calls,
    autopilot_job,
    strategy_job,
    refresh_market_snapshot,
    sync_universe_calendar,
    run_pulse_scan,
    run_simulator_step,
    collect_earnings_calendar,
    collect_macro_data,
    collect_options_data,
    collect_post_earnings_results,
    retrain_full,
    run_predictions,
    seal_arena_forecasts,
    sync_earnings_timing,
    alert_follow_through,
    resolve_arena_forecasts,
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
scheduler.add_job(retrain_full, CronTrigger(month="*/1", day=1, hour=2, minute=0, timezone=TZ), id="retrain_models", max_instances=1, coalesce=True)
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


# Report times and surprises, before the open, after the close, and late evening when
# after-close numbers have been posted.
scheduler.add_job(sync_earnings_timing, CronTrigger(hour="7,16,21", minute=40, timezone=TZ),
                  id="sync_earnings_timing", max_instances=1, coalesce=True)

# Follow-through alerts shortly after the open, when the gap is known and still tradable.
scheduler.add_job(alert_follow_through, CronTrigger(day_of_week="mon-fri", hour=9, minute="38,50", timezone=TZ),
                  id="alert_follow_through", max_instances=1, coalesce=True)
scheduler.add_job(alert_follow_through, CronTrigger(day_of_week="mon-fri", hour=10, minute=20, timezone=TZ),
                  id="alert_follow_through_late", max_instances=1, coalesce=True)

# Earnings Arena. Sealing every two hours (at :20, after the 17:00 prediction run has a
# chance to land) catches new calendar entries well inside the 3-day window; resolution
# runs 25 minutes after each hourly outcome collection.
scheduler.add_job(seal_arena_forecasts, CronTrigger(minute=20, hour="*/2", timezone=TZ),
                  id="seal_arena_forecasts", max_instances=1, coalesce=True)
scheduler.add_job(resolve_arena_forecasts, CronTrigger(minute=25, timezone=TZ),
                  id="resolve_arena_forecasts", max_instances=1, coalesce=True)

# Receipts: freeze each report's standing call once its bell rings (before any retrain
# can overwrite predictions), grade it once the outcome lands.
scheduler.add_job(freeze_and_grade_receipts, CronTrigger(minute="5,35", timezone=TZ),
                  id="freeze_and_grade_receipts", max_instances=1, coalesce=True)
# Direction book: the gap is known a few minutes after the bell; again later for slow opens.
scheduler.add_job(issue_direction_calls, CronTrigger(day_of_week="mon-fri", hour=9, minute="36,50", timezone=TZ),
                  id="issue_direction_calls", max_instances=1, coalesce=True)
# Autopilot (services/autotrade_service.py): from 9:30:20 the opening prints come from the
# broker feed, the calls go out and orders follow in the same pass — every second counts:
# on SIP tape since 2016 an order a minute after the bell keeps only ~40% of the
# open-to-close edge (data_pipeline/replay_open_fills.py). Passes at :20 and :50 past
# 9:30, then 9:31:30 and 9:32:30 for late opens, and after each Yahoo pass above until
# 10:00. On-close orders before Alpaca's 15:50 cutoff; a market-order fallback at 15:56;
# fills and P&L marks every five minutes.
for _i, (_m, _s) in enumerate([(30, 20), (30, 50), (31, 30), (32, 30)]):
    scheduler.add_job(autopilot_job, CronTrigger(day_of_week="mon-fri", hour=9, minute=_m, second=_s, timezone=TZ),
                      args=["open"], id=f"autopilot_open_{_i}", max_instances=1, coalesce=True, misfire_grace_time=30)
scheduler.add_job(autopilot_job, CronTrigger(day_of_week="mon-fri", hour=9, minute="37,51", timezone=TZ),
                  args=["entries"], id="autopilot_entries", max_instances=1, coalesce=True)
scheduler.add_job(autopilot_job, CronTrigger(day_of_week="mon-fri", hour=15, minute=44, timezone=TZ),
                  args=["closes"], id="autopilot_closes", max_instances=1, coalesce=True)
scheduler.add_job(autopilot_job, CronTrigger(day_of_week="mon-fri", hour=15, minute=56, timezone=TZ),
                  args=["flatten"], id="autopilot_flatten", max_instances=1, coalesce=True)
# Signals for the other strategies (services/strategies.py), all before the 15:44 closing pass:
# insider clusters from yesterday's Form 4s before the open; surprises refreshed at 15:20 for
# the drift rule; the pre-earnings and drift signals and the ETF targets at 15:30–15:35.
scheduler.add_job(strategy_job, CronTrigger(day_of_week="mon-fri", hour=6, minute=30, timezone=TZ),
                  args=["insider"], id="strategy_insider", max_instances=1, coalesce=True)
scheduler.add_job(sync_earnings_timing, CronTrigger(day_of_week="mon-fri", hour=15, minute=20, timezone=TZ),
                  id="sync_earnings_timing_afternoon", max_instances=1, coalesce=True)
scheduler.add_job(strategy_job, CronTrigger(day_of_week="mon-fri", hour=15, minute=30, timezone=TZ),
                  args=["pre_run"], id="strategy_pre_run", max_instances=1, coalesce=True)
scheduler.add_job(strategy_job, CronTrigger(day_of_week="mon-fri", hour=15, minute=32, timezone=TZ),
                  args=["sue_gap"], id="strategy_sue_gap", max_instances=1, coalesce=True)
scheduler.add_job(strategy_job, CronTrigger(day_of_week="mon-fri", hour=15, minute=35, timezone=TZ),
                  args=["targets"], id="strategy_targets", max_instances=1, coalesce=True)
# Connections without a working on-close order (paper accounts, moomoo — see uses_moc) close
# at market at 15:58:20.
scheduler.add_job(autopilot_job, CronTrigger(day_of_week="mon-fri", hour=15, minute=58, second=20, timezone=TZ),
                  args=["closes_late"], id="autopilot_closes_late", max_instances=1, coalesce=True, misfire_grace_time=30)
scheduler.add_job(autopilot_job, CronTrigger(day_of_week="mon-fri", hour="9-16", minute="*/5", timezone=TZ),
                  args=["reconcile"], id="autopilot_reconcile", max_instances=1, coalesce=True)
scheduler.add_job(issue_direction_calls, CronTrigger(day_of_week="mon-fri", hour="10,17", minute=15, timezone=TZ),
                  id="issue_direction_calls_late", max_instances=1, coalesce=True)
# Markets page: every fifteen minutes (a full pass takes ~6) through the session, once after the close and pre-open.
scheduler.add_job(refresh_market_snapshot, CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*/15", timezone=TZ),
                  id="refresh_market_snapshot", max_instances=1, coalesce=True)
scheduler.add_job(refresh_market_snapshot, CronTrigger(day_of_week="mon-fri", hour="8,16", minute=35, timezone=TZ),
                  id="refresh_market_snapshot_edges", max_instances=1, coalesce=True)
# The whole US universe's report dates: before the morning and evening prediction runs.
scheduler.add_job(sync_universe_calendar, CronTrigger(hour="6,15", minute=50, timezone=TZ),
                  id="sync_universe_calendar", max_instances=1, coalesce=True)

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


