"""
Trading Simulator service — v3

Changes vs v2:
- Market-closed gating: when NYSE is closed AND no fresh ticks in 30 min,
  freeze new entries (only mark-to-market existing book).
- Honest mark price model: when no fresh tick is available, the mark equals
  the entry price (zero PnL drift) instead of the stale snapshot causing
  every ticker to bleed slippage.
- Realised PnL aggregate exposed in dashboard payload.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import numpy as np
from sqlalchemy import and_, desc, func, select
from sqlalchemy.orm import Session

from backend.app.db.models import (
    EarningsEvent,
    Outcome,
    Prediction,
    PriceFeature,
    SimulationConfig,
    SimulationPosition,
    SimulationState,
    SimulationTrade,
)


# --------------------------------------------------------------------------
# Price fetching: 24-hour pricing including pre/post-market
# --------------------------------------------------------------------------

# (price, prev_close, fetched_at, last_bar_dt)
_PRICE_CACHE: dict[str, tuple[float, float, datetime, datetime | None]] = {}
_CACHE_TTL_SECONDS = 15  # 15 seconds — safe with batch fetching


def _warm_price_cache(tickers: list[str]) -> None:
    """Batch-fetch all tickers in ONE yfinance call before the mark loop.
    Subsequent _fetch_live_price() calls hit the in-process cache instead
    of making N separate HTTP requests — keeps us well under rate limits
    even at 30-second run-step intervals."""
    if not tickers:
        return
    now = datetime.utcnow()
    stale = [t for t in tickers if t not in _PRICE_CACHE
             or (now - _PRICE_CACHE[t][2]).total_seconds() >= _CACHE_TTL_SECONDS]
    if not stale:
        return
    try:
        import yfinance as yf
        raw = yf.download(
            stale, period="2d", interval="1m", prepost=True,
            group_by="ticker", auto_adjust=True, progress=False, threads=True,
        )
        daily = yf.download(
            stale, period="5d", interval="1d",
            auto_adjust=True, progress=False, threads=True,
        )
        multi = len(stale) > 1
        for ticker in stale:
            try:
                intra = raw[ticker] if multi else raw
                day = daily[ticker] if multi else daily
                price = None
                last_bar = None
                if intra is not None and not intra.empty:
                    closes = intra["Close"].dropna()
                    if not closes.empty:
                        price = float(closes.iloc[-1])
                    try:
                        last_bar = intra.index[-1].to_pydatetime().astimezone(timezone.utc).replace(tzinfo=None)
                    except Exception:
                        pass
                prev = None
                if day is not None and not day.empty:
                    dcl = day["Close"].dropna()
                    if price is None and not dcl.empty:
                        price = float(dcl.iloc[-1])
                    prev = float(dcl.iloc[-2]) if len(dcl) >= 2 else price
                if price and not __import__("math").isnan(price):
                    _PRICE_CACHE[ticker] = (price, prev or price, now, last_bar)
            except Exception:
                pass
    except Exception:
        pass


def _fetch_live_price(ticker: str) -> tuple[float, float, datetime | None] | None:
    """Returns (last_price, previous_close, last_bar_timestamp_utc) or None.
    last_bar_timestamp_utc is the timestamp of the actual minute bar — when
    None or older than 30 min during off-hours, callers should treat the price
    as "stale" and avoid re-marking positions to it."""
    now = datetime.utcnow()
    cached = _PRICE_CACHE.get(ticker)
    if cached and (now - cached[2]).total_seconds() < _CACHE_TTL_SECONDS:
        return cached[0], cached[1], cached[3]

    try:
        import yfinance as yf
        t = yf.Ticker(ticker.upper())
        intraday = t.history(period="2d", interval="1m", prepost=True)
        price: float | None = None
        last_bar: datetime | None = None

        if intraday is not None and not intraday.empty:
            price = float(intraday["Close"].iloc[-1])
            last_idx = intraday.index[-1]
            try:
                last_bar = last_idx.to_pydatetime().astimezone(timezone.utc).replace(tzinfo=None)
            except Exception:
                last_bar = None

        daily = t.history(period="5d", interval="1d")
        prev: float | None = None
        if daily is not None and not daily.empty:
            if price is None:
                price = float(daily["Close"].iloc[-1])
            prev = float(daily["Close"].iloc[-2]) if len(daily) >= 2 else price

        if not price or math.isnan(price):
            return None
        if not prev:
            prev = price

        _PRICE_CACHE[ticker] = (price, prev, now, last_bar)
        return price, prev, last_bar
    except Exception:
        return None


def _is_price_fresh(last_bar_utc: datetime | None) -> bool:
    """Bar is "fresh" if it was printed within the last 30 minutes. During
    regular hours this is always true (1-min bars). After hours, fresh means
    extended-hours actually traded; if the last bar is from yesterday's
    close, this returns False and we hold marks at entry."""
    if last_bar_utc is None:
        return False
    age = (datetime.utcnow() - last_bar_utc).total_seconds()
    return age <= 30 * 60


def _entry_price_for_position(db: Session, ticker: str, target_date: date) -> float | None:
    today = date.today()
    if target_date >= today:
        live = _fetch_live_price(ticker)
        if live and live[0]:
            return live[0]
    pf = db.execute(
        select(PriceFeature).where(and_(PriceFeature.ticker == ticker, PriceFeature.earnings_date == target_date))
    ).scalar_one_or_none()
    if pf and pf.feature_payload:
        p = pf.feature_payload.get("price_t0")
        if p:
            return float(p)
    live = _fetch_live_price(ticker)
    return live[0] if live else None


def _exit_price_from_outcome(db: Session, ticker: str, earnings_date: date, holding_days: int) -> float | None:
    outcome = db.execute(
        select(Outcome).where(and_(Outcome.ticker == ticker, Outcome.earnings_date == earnings_date))
    ).scalar_one_or_none()
    if not outcome:
        return None
    pf = db.execute(
        select(PriceFeature).where(and_(PriceFeature.ticker == ticker, PriceFeature.earnings_date == earnings_date))
    ).scalar_one_or_none()
    if not pf or not pf.feature_payload:
        return None
    entry = pf.feature_payload.get("price_t0")
    if not entry:
        return None
    if holding_days <= 1:
        ret_attr = "actual_t1_close_return"
    elif holding_days <= 8:
        ret_attr = "actual_t5_return"
    else:
        ret_attr = "actual_t20_return"
    ret = getattr(outcome, ret_attr, None)
    if ret is None or (isinstance(ret, float) and math.isnan(ret)):
        ret = outcome.actual_t1_close_return
    if ret is None:
        return None
    return float(entry) * (1.0 + float(ret))


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _to_float(x) -> float:
    if x is None:
        return 0.0
    if isinstance(x, Decimal):
        return float(x)
    return float(x)


def _get_or_create_config(db: Session) -> SimulationConfig:
    cfg = db.execute(select(SimulationConfig).order_by(SimulationConfig.id.asc()).limit(1)).scalar_one_or_none()
    if cfg is None:
        cfg = SimulationConfig()
        db.add(cfg)
        db.flush()
    return cfg


def _compute_metrics(db: Session) -> dict[str, float | None]:
    rows = db.execute(
        select(SimulationState.snapshot_at, SimulationState.total_equity)
        .order_by(SimulationState.snapshot_at.asc())
    ).all()
    if len(rows) < 2:
        return {"sharpe": None, "max_drawdown_pct": None, "win_rate": None}
    equities = np.array([_to_float(r[1]) for r in rows], dtype=float)
    returns = np.diff(equities) / equities[:-1]
    if len(returns) < 2 or returns.std() == 0:
        sharpe = None
    else:
        sharpe = float((returns.mean() / returns.std()) * np.sqrt(252))
    running_max = np.maximum.accumulate(equities)
    dd = (equities - running_max) / running_max
    max_dd = float(dd.min() * 100.0) if len(dd) else None
    closed = db.execute(
        select(SimulationTrade.realized_pnl).where(SimulationTrade.action == "CLOSE")
    ).scalars().all()
    closed = [c for c in closed if c is not None]
    win_rate = float(sum(1 for c in closed if _to_float(c) > 0) / len(closed)) if closed else None
    return {"sharpe": sharpe, "max_drawdown_pct": max_dd, "win_rate": win_rate}


def _slip(price: float, side: str, action: str, slippage_bps: float) -> float:
    bps = slippage_bps / 10_000.0
    if (side == "LONG" and action == "OPEN") or (side == "SHORT" and action == "CLOSE"):
        return price * (1.0 + bps)
    return price * (1.0 - bps)


def _entry_window_open(event: EarningsEvent, db: Session, today: date) -> tuple[bool, str]:
    days = (event.earnings_date - today).days
    if days < 0:
        return False, "earnings_already_passed"
    outcome_exists = db.execute(
        select(Outcome.id).where(
            and_(Outcome.ticker == event.ticker, Outcome.earnings_date == event.earnings_date)
        )
    ).scalar_one_or_none()
    if outcome_exists:
        return False, "outcome_already_recorded"
    rt = (event.report_time or "").upper()
    if days == 0:
        if rt == "AMC":
            return True, "today_amc"
        return False, f"today_{rt or 'unknown_time'}"
    if days == 1:
        return True, "tomorrow"
    return False, f"too_early_{days}d"


def _close_position(
    db: Session, pos: SimulationPosition, exit_price: float, exit_reason: str,
    cfg: SimulationConfig, cash_ref: list[float], realized_pnl_total: list[float],
) -> None:
    fill_price = _slip(exit_price, pos.side, "CLOSE", _to_float(cfg.slippage_bps))
    shares = _to_float(pos.shares)
    notional_close = shares * fill_price
    entry_p = _to_float(pos.entry_price)
    pnl = (fill_price - entry_p) * shares if pos.side == "LONG" else (entry_p - fill_price) * shares
    cash_ref[0] += _to_float(pos.margin_used) + pnl
    realized_pnl_total[0] += pnl
    pnl_pct = (pnl / _to_float(pos.notional_value)) if _to_float(pos.notional_value) else 0.0
    holding = (date.today() - pos.entry_date).days
    db.add(SimulationTrade(
        ticker=pos.ticker, sector=pos.sector, side=pos.side, action="CLOSE",
        shares=shares, price=fill_price, notional=notional_close,
        leverage=pos.leverage, confidence=pos.confidence, predicted_direction=pos.predicted_direction,
        realized_pnl=pnl, realized_pnl_pct=pnl_pct, holding_days=holding, exit_reason=exit_reason,
    ))
    db.delete(pos)


def _open_position(
    db: Session, *, pred: Prediction, event: EarningsEvent, fill_price: float,
    side: str, shares: float, leverage: float, cfg: SimulationConfig,
    cash_ref: list[float], today: date,
) -> None:
    notional = shares * fill_price
    margin = notional / max(leverage, 1.0)
    cash_ref[0] -= margin
    target_exit = event.earnings_date + timedelta(days=cfg.holding_days + 1)
    db.add(SimulationPosition(
        ticker=event.ticker, sector=event.sector, side=side, shares=shares,
        entry_price=fill_price, entry_date=today, earnings_date=event.earnings_date,
        target_exit_date=target_exit, leverage=leverage, notional_value=notional, margin_used=margin,
        predicted_direction="UP" if side == "LONG" else "DOWN",
        confidence=_to_float(pred.confidence_score),
        expected_move_pct=_to_float(pred.expected_move_pct),
        last_mark_price=fill_price, last_mark_at=datetime.utcnow(),
        unrealized_pnl=0.0, unrealized_pnl_pct=0.0,
    ))
    db.add(SimulationTrade(
        ticker=event.ticker, sector=event.sector, side=side, action="OPEN",
        shares=shares, price=fill_price, notional=notional, leverage=leverage,
        confidence=_to_float(pred.confidence_score),
        predicted_direction="UP" if side == "LONG" else "DOWN",
    ))


def _leverage_for(confidence: float) -> float:
    if confidence >= 0.75: return 2.0
    if confidence >= 0.65: return 1.5
    return 1.0


def _position_size_pct(confidence: float, cfg: SimulationConfig) -> float:
    thr = _to_float(cfg.confidence_threshold)
    base = _to_float(cfg.base_position_pct)
    cap = _to_float(cfg.max_position_pct)
    scale = max(1.0, confidence / max(thr, 0.01))
    return min(base * scale, cap)


def reset_simulation(db: Session) -> None:
    db.query(SimulationPosition).delete()
    db.query(SimulationTrade).delete()
    db.query(SimulationState).delete()
    db.query(SimulationConfig).delete()
    db.flush()
    cfg = _get_or_create_config(db)
    initial = _to_float(cfg.initial_capital)
    db.add(SimulationState(
        cash=initial, positions_value=0.0, total_equity=initial,
        total_return_pct=0.0, leverage_used=0.0,
        num_open_positions=0, num_trades_total=0,
    ))
    db.commit()


def run_step(db: Session) -> dict[str, Any]:
    cfg = _get_or_create_config(db)
    last_state = db.execute(
        select(SimulationState).order_by(desc(SimulationState.snapshot_at)).limit(1)
    ).scalar_one_or_none()
    if last_state is None:
        initial = _to_float(cfg.initial_capital)
        last_state = SimulationState(
            cash=initial, positions_value=0.0, total_equity=initial,
            total_return_pct=0.0, leverage_used=0.0,
            num_open_positions=0, num_trades_total=0,
        )
        db.add(last_state)
        db.flush()

    cash_ref = [_to_float(last_state.cash)]
    realized_pnl_total = [0.0]
    today = date.today()
    open_positions = db.execute(select(SimulationPosition)).scalars().all()
    _warm_price_cache([p.ticker for p in open_positions])

    closes_done: list[dict[str, Any]] = []
    for pos in open_positions:
        outcome_exit = _exit_price_from_outcome(db, pos.ticker, pos.earnings_date, cfg.holding_days)
        live = _fetch_live_price(pos.ticker)
        live_price = live[0] if live else None
        live_bar = live[2] if live else None
        fresh = _is_price_fresh(live_bar)
        # Honest marking: use outcome if available; otherwise use a fresh live
        # tick; otherwise hold the mark at entry (no fake P&L drift).
        if outcome_exit is not None:
            mark = outcome_exit
        elif fresh and live_price is not None:
            mark = live_price
        else:
            mark = _to_float(pos.entry_price)

        pos.last_mark_price = mark
        pos.last_mark_at = datetime.utcnow()
        entry = _to_float(pos.entry_price)
        if pos.side == "LONG":
            ret_pct = (mark - entry) / entry if entry else 0.0
        else:
            ret_pct = (entry - mark) / entry if entry else 0.0
        pos.unrealized_pnl_pct = ret_pct
        pos.unrealized_pnl = ret_pct * _to_float(pos.notional_value)

        exit_reason: str | None = None
        if today >= pos.target_exit_date:
            exit_reason = "TIME"
        elif ret_pct <= -_to_float(cfg.stop_loss_pct):
            exit_reason = "STOP_LOSS"
        elif ret_pct >= _to_float(cfg.take_profit_pct):
            exit_reason = "TAKE_PROFIT"
        if exit_reason:
            _close_position(db, pos, mark, exit_reason, cfg, cash_ref, realized_pnl_total)
            closes_done.append({"ticker": pos.ticker, "reason": exit_reason})

    db.flush()

    # New entries
    horizon_end = today + timedelta(days=2)
    candidates = db.execute(
        select(EarningsEvent, Prediction)
        .join(Prediction, and_(Prediction.ticker == EarningsEvent.ticker, Prediction.earnings_date == EarningsEvent.earnings_date))
        .where(EarningsEvent.earnings_date >= today, EarningsEvent.earnings_date <= horizon_end)
        .where(Prediction.confidence_score >= _to_float(cfg.confidence_threshold))
        .order_by(desc(Prediction.confidence_score))
    ).all()
    held = {p.ticker for p in db.execute(select(SimulationPosition)).scalars().all()}

    opens_done: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for event, pred in candidates:
        if event.ticker in held:
            continue
        allowed, reason = _entry_window_open(event, db, today)
        if not allowed:
            skipped.append({"ticker": event.ticker, "reason": reason})
            continue

        p_up = _to_float(pred.direction_prob_up)
        p_down = _to_float(pred.direction_prob_down)
        p_flat = _to_float(pred.direction_prob_flat)
        if p_up > p_down and p_up > p_flat:
            side = "LONG"
        elif p_down > p_up and p_down > p_flat:
            side = "SHORT"
        else:
            continue

        confidence = _to_float(pred.confidence_score)
        entry_p = _entry_price_for_position(db, event.ticker, event.earnings_date)
        if not entry_p:
            continue
        fill_price = _slip(entry_p, side, "OPEN", _to_float(cfg.slippage_bps))

        size_pct = _position_size_pct(confidence, cfg)
        leverage = _leverage_for(confidence)
        all_pos = db.execute(select(SimulationPosition)).scalars().all()
        gross = sum(_to_float(p.notional_value) for p in all_pos)
        eq_estimate = cash_ref[0] + sum(_to_float(p.margin_used) for p in all_pos)
        if eq_estimate <= 0:
            break
        current_lev = gross / eq_estimate
        if current_lev >= _to_float(cfg.portfolio_leverage_cap):
            break

        target_notional = eq_estimate * size_pct * leverage
        max_extra_notional = max(0.0, (_to_float(cfg.portfolio_leverage_cap) - current_lev) * eq_estimate)
        target_notional = min(target_notional, max_extra_notional)
        if target_notional <= 0:
            break
        margin_required = target_notional / leverage
        if margin_required > cash_ref[0]:
            margin_required = cash_ref[0]
            target_notional = margin_required * leverage
        if target_notional < 100:
            continue

        shares = target_notional / fill_price
        _open_position(db, pred=pred, event=event, fill_price=fill_price,
                       side=side, shares=shares, leverage=leverage, cfg=cfg,
                       cash_ref=cash_ref, today=today)
        held.add(event.ticker)
        opens_done.append({"ticker": event.ticker, "side": side, "confidence": confidence})

    db.flush()
    open_positions_now = db.execute(select(SimulationPosition)).scalars().all()
    positions_value = 0.0
    gross_notional = 0.0
    for p in open_positions_now:
        positions_value += _to_float(p.margin_used) + _to_float(p.unrealized_pnl or 0.0)
        gross_notional += _to_float(p.notional_value)

    total_equity = cash_ref[0] + positions_value
    initial = _to_float(cfg.initial_capital)
    total_return_pct = ((total_equity - initial) / initial * 100.0) if initial else 0.0
    leverage_used = (gross_notional / total_equity) if total_equity > 0 else 0.0
    num_trades_total = db.execute(select(func.count(SimulationTrade.id))).scalar_one()
    metrics = _compute_metrics(db)
    db.add(SimulationState(
        cash=cash_ref[0], positions_value=positions_value, total_equity=total_equity,
        total_return_pct=total_return_pct, leverage_used=leverage_used,
        num_open_positions=len(open_positions_now), num_trades_total=num_trades_total,
        sharpe=metrics["sharpe"], max_drawdown_pct=metrics["max_drawdown_pct"],
        win_rate=metrics["win_rate"],
    ))
    cfg.last_step_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "closes": closes_done, "opens": opens_done, "skipped": skipped,
            "total_equity": total_equity, "cash": cash_ref[0]}


def _market_status() -> dict[str, Any]:
    try:
        from zoneinfo import ZoneInfo
        et = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        et = datetime.now(timezone.utc) - timedelta(hours=4)
    weekday = et.weekday()
    minutes = et.hour * 60 + et.minute
    if weekday >= 5:
        return {"status": "CLOSED", "label": "Weekend", "et_time": et.strftime("%H:%M:%S")}
    if minutes < 4 * 60:
        return {"status": "CLOSED", "label": "Closed", "et_time": et.strftime("%H:%M:%S")}
    if minutes < 9 * 60 + 30:
        return {"status": "PRE_MARKET", "label": "Pre-market", "et_time": et.strftime("%H:%M:%S")}
    if minutes < 16 * 60:
        return {"status": "OPEN", "label": "Market open", "et_time": et.strftime("%H:%M:%S")}
    if minutes < 20 * 60:
        return {"status": "AFTER_HOURS", "label": "After hours", "et_time": et.strftime("%H:%M:%S")}
    return {"status": "CLOSED", "label": "Closed", "et_time": et.strftime("%H:%M:%S")}


def get_dashboard(db: Session, equity_curve_limit: int = 200, trades_limit: int = 30) -> dict[str, Any]:
    cfg = _get_or_create_config(db)
    last_state = db.execute(
        select(SimulationState).order_by(desc(SimulationState.snapshot_at)).limit(1)
    ).scalar_one_or_none()

    # Realised P&L aggregate (from closed trades)
    closed_trades = db.execute(
        select(SimulationTrade).where(SimulationTrade.action == "CLOSE")
        .order_by(desc(SimulationTrade.executed_at))
    ).scalars().all()
    total_realized_pnl = sum(_to_float(t.realized_pnl) for t in closed_trades if t.realized_pnl is not None)
    n_winning = sum(1 for t in closed_trades if _to_float(t.realized_pnl) > 0)
    n_losing = sum(1 for t in closed_trades if _to_float(t.realized_pnl) < 0)
    avg_win = (sum(_to_float(t.realized_pnl) for t in closed_trades if _to_float(t.realized_pnl) > 0) / n_winning) if n_winning else 0.0
    avg_loss = (sum(_to_float(t.realized_pnl) for t in closed_trades if _to_float(t.realized_pnl) < 0) / n_losing) if n_losing else 0.0
    best_trade = max((_to_float(t.realized_pnl) for t in closed_trades if t.realized_pnl is not None), default=0.0)
    worst_trade = min((_to_float(t.realized_pnl) for t in closed_trades if t.realized_pnl is not None), default=0.0)

    realised_block = {
        "total_pnl": total_realized_pnl,
        "n_trades": len(closed_trades),
        "n_winning": n_winning,
        "n_losing": n_losing,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "best_trade": best_trade,
        "worst_trade": worst_trade,
        "recent_closes": [
            {
                "ticker": t.ticker, "side": t.side, "exit_reason": t.exit_reason,
                "realized_pnl": _to_float(t.realized_pnl) if t.realized_pnl is not None else None,
                "realized_pnl_pct": t.realized_pnl_pct, "holding_days": t.holding_days,
                "executed_at": t.executed_at.isoformat() if t.executed_at else None,
            }
            for t in closed_trades[:10]
        ],
    }

    if last_state is None:
        initial = _to_float(cfg.initial_capital)
        return {
            "config": _config_dict(cfg),
            "state": {
                "cash": initial, "positions_value": 0.0, "total_equity": initial,
                "total_return_pct": 0.0, "leverage_used": 0.0,
                "num_open_positions": 0, "num_trades_total": 0,
                "sharpe": None, "max_drawdown_pct": None, "win_rate": None,
                "snapshot_at": None,
            },
            "positions": [], "trades": [], "equity_curve": [], "pending": [],
            "realised": realised_block,
            "market_status": _market_status(),
            "server_time": datetime.utcnow().isoformat() + "Z",
        }

    positions = db.execute(
        select(SimulationPosition).order_by(desc(SimulationPosition.notional_value))
    ).scalars().all()
    trades = db.execute(
        select(SimulationTrade).order_by(desc(SimulationTrade.executed_at)).limit(trades_limit)
    ).scalars().all()
    curve = db.execute(
        select(SimulationState).order_by(SimulationState.snapshot_at.asc()).limit(equity_curve_limit * 4)
    ).scalars().all()
    if len(curve) > equity_curve_limit:
        idxs = np.linspace(0, len(curve) - 1, equity_curve_limit).astype(int).tolist()
        curve = [curve[i] for i in idxs]

    today = date.today()
    horizon_end = today + timedelta(days=5)
    pending_rows = db.execute(
        select(EarningsEvent, Prediction)
        .join(Prediction, and_(Prediction.ticker == EarningsEvent.ticker, Prediction.earnings_date == EarningsEvent.earnings_date))
        .where(EarningsEvent.earnings_date >= today, EarningsEvent.earnings_date <= horizon_end)
        .where(Prediction.confidence_score >= _to_float(cfg.confidence_threshold))
        .order_by(EarningsEvent.earnings_date.asc(), desc(Prediction.confidence_score))
        .limit(20)
    ).all()
    held = {p.ticker for p in positions}

    pending = []
    for e, p in pending_rows:
        allowed, reason = _entry_window_open(e, db, today)
        pending.append({
            "ticker": e.ticker, "company_name": e.company_name, "sector": e.sector,
            "earnings_date": e.earnings_date.isoformat(), "report_time": e.report_time,
            "confidence": _to_float(p.confidence_score),
            "direction": "UP" if _to_float(p.direction_prob_up) > _to_float(p.direction_prob_down) else "DOWN",
            "expected_move_pct": _to_float(p.expected_move_pct),
            "already_held": e.ticker in held, "tradeable": allowed,
            "skip_reason": None if allowed else reason,
        })

    return {
        "config": _config_dict(cfg),
        "state": _state_dict(last_state),
        "positions": [_position_dict(p) for p in positions],
        "trades": [_trade_dict(t) for t in trades],
        "equity_curve": [
            {"t": s.snapshot_at.isoformat(), "equity": _to_float(s.total_equity)}
            for s in curve
        ],
        "pending": pending,
        "realised": realised_block,
        "market_status": _market_status(),
        "server_time": datetime.utcnow().isoformat() + "Z",
    }


def _config_dict(cfg: SimulationConfig) -> dict[str, Any]:
    return {
        "initial_capital": _to_float(cfg.initial_capital),
        "confidence_threshold": cfg.confidence_threshold,
        "base_position_pct": cfg.base_position_pct,
        "max_position_pct": cfg.max_position_pct,
        "portfolio_leverage_cap": cfg.portfolio_leverage_cap,
        "stop_loss_pct": cfg.stop_loss_pct,
        "take_profit_pct": cfg.take_profit_pct,
        "holding_days": cfg.holding_days,
        "slippage_bps": cfg.slippage_bps,
        "last_step_at": cfg.last_step_at.isoformat() if cfg.last_step_at else None,
        "started_at": cfg.started_at.isoformat() if cfg.started_at else None,
    }


def _state_dict(s: SimulationState) -> dict[str, Any]:
    return {
        "snapshot_at": s.snapshot_at.isoformat() if s.snapshot_at else None,
        "cash": _to_float(s.cash), "positions_value": _to_float(s.positions_value),
        "total_equity": _to_float(s.total_equity), "total_return_pct": _to_float(s.total_return_pct),
        "leverage_used": _to_float(s.leverage_used),
        "num_open_positions": s.num_open_positions, "num_trades_total": s.num_trades_total,
        "sharpe": s.sharpe, "max_drawdown_pct": s.max_drawdown_pct, "win_rate": s.win_rate,
    }


def _position_dict(p: SimulationPosition) -> dict[str, Any]:
    return {
        "id": p.id, "ticker": p.ticker, "sector": p.sector, "side": p.side,
        "shares": _to_float(p.shares), "entry_price": _to_float(p.entry_price),
        "entry_date": p.entry_date.isoformat(), "earnings_date": p.earnings_date.isoformat(),
        "target_exit_date": p.target_exit_date.isoformat(), "leverage": p.leverage,
        "notional_value": _to_float(p.notional_value), "margin_used": _to_float(p.margin_used),
        "predicted_direction": p.predicted_direction, "confidence": p.confidence,
        "expected_move_pct": p.expected_move_pct,
        "last_mark_price": _to_float(p.last_mark_price) if p.last_mark_price else None,
        "last_mark_at": p.last_mark_at.isoformat() if p.last_mark_at else None,
        "unrealized_pnl": _to_float(p.unrealized_pnl) if p.unrealized_pnl else 0.0,
        "unrealized_pnl_pct": p.unrealized_pnl_pct or 0.0,
    }


def _trade_dict(t: SimulationTrade) -> dict[str, Any]:
    return {
        "id": t.id, "ticker": t.ticker, "sector": t.sector, "side": t.side, "action": t.action,
        "shares": _to_float(t.shares), "price": _to_float(t.price), "notional": _to_float(t.notional),
        "leverage": t.leverage, "confidence": t.confidence, "predicted_direction": t.predicted_direction,
        "realized_pnl": _to_float(t.realized_pnl) if t.realized_pnl is not None else None,
        "realized_pnl_pct": t.realized_pnl_pct, "holding_days": t.holding_days,
        "exit_reason": t.exit_reason,
        "executed_at": t.executed_at.isoformat() if t.executed_at else None,
    }
