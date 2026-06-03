"""Pulse signal exit worker — TP/SL touch detection + time barrier fallback."""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy import text
from backend.app.db.session import SessionLocal

log = logging.getLogger(__name__)


async def signal_exit_worker():
    """Every 2min: walk 1-min bars to find first TP/SL touch, else time barrier exit."""
    log.info("Signal exit worker v2 started (TP/SL touch + time)")
    while True:
        try:
            await asyncio.sleep(120)  # 2min — fast SL reaction
            try:
                import yfinance as yf
            except ImportError:
                continue
            db = SessionLocal()
            try:
                rows = db.execute(text("""
                    SELECT id, ticker, side, entry_price, entry_time,
                           expected_exit_time, tp_price, sl_price, suggested_size
                    FROM pulse_signal_log
                    WHERE status='open'
                    LIMIT 100
                """)).fetchall()
                now_utc = datetime.now(timezone.utc)

                for row in rows:
                    try:
                        if not row.entry_time: continue
                        age_min = (now_utc - row.entry_time).total_seconds() / 60
                        if age_min < 2: continue  # give entry a sec

                        start_d = row.entry_time.date()
                        end_d = (now_utc + timedelta(days=1)).date()
                        h = yf.Ticker(row.ticker).history(start=start_d, end=end_d, interval="1m")
                        if h.empty: continue
                        h = h[h.index >= row.entry_time]
                        if h.empty: continue

                        entry_px = float(row.entry_price)
                        tp = float(row.tp_price) if row.tp_price else None
                        sl = float(row.sl_price) if row.sl_price else None
                        side = row.side
                        exit_px = exit_t = reason = None

                        # Walk bars chronologically; first TP/SL touch wins
                        for ts, bar in h.iterrows():
                            hi, lo = float(bar["High"]), float(bar["Low"])
                            if side == "LONG":
                                # SL first (conservative — assume bad fill on stop)
                                if sl and lo <= sl: exit_px, exit_t, reason = sl, ts, "sl"; break
                                if tp and hi >= tp: exit_px, exit_t, reason = tp, ts, "tp"; break
                            else:  # SHORT
                                if sl and hi >= sl: exit_px, exit_t, reason = sl, ts, "sl"; break
                                if tp and lo <= tp: exit_px, exit_t, reason = tp, ts, "tp"; break

                        # Hard max-hold force-close (safety net vs overnight/weekend holds)
                        import os as _os
                        _max_hold = float(_os.getenv("PULSE_MAX_HOLD_MIN", "480"))
                        # Time barrier fallback
                        if exit_px is None:
                            if row.expected_exit_time and row.expected_exit_time < now_utc:
                                exit_px = float(h["Close"].iloc[-1])
                                exit_t = h.index[-1]
                                reason = "time"
                            elif age_min > _max_hold:
                                exit_px = float(h["Close"].iloc[-1])
                                exit_t = h.index[-1]
                                reason = "maxhold"
                        if exit_px is None: continue  # still open, no trigger yet

                        ret = ((exit_px - entry_px)/entry_px) if side == "LONG" else ((entry_px - exit_px)/entry_px)
                        size = float(row.suggested_size or 50000)
                        pnl = ret * size
                        et = exit_t.to_pydatetime() if hasattr(exit_t,"to_pydatetime") else exit_t

                        db.execute(text("""
                            UPDATE pulse_signal_log
                            SET exit_price=:ep, exit_time=:et, return_pct=:r,
                                pnl_dollars=:pnl, win=:w, status='closed',
                                exit_reason=:rs, updated_at=NOW()
                            WHERE id=:id
                        """), {"ep":exit_px,"et":et,"r":ret,"pnl":pnl,"w":ret>0,"rs":reason,"id":row.id})
                        log.info(f"closed {row.ticker} {side} ret={ret*100:.2f}% pnl=${pnl:.0f} reason={reason}")
                        # Fire exit order at broker (if enabled)
                        try:
                            import os
                            from backend.app.services.broker_service import place_exit_order
                            px = float(row.entry_price); sz = float(row.suggested_size or 200)
                            max_usd = float(os.getenv("MOOMOO_MAX_POSITION_USD","200"))
                            qty = max(1, int(min(sz, max_usd) / px))
                            exit_res = place_exit_order(row.ticker, side, qty)
                            if exit_res.get("placed"):
                                log.info(f"broker exit: {exit_res}")
                        except Exception:
                            log.exception("broker exit hook fail")
                    except Exception as e:
                        log.warning(f"worker check {row.ticker}: {e}")
                db.commit()
            finally:
                db.close()
        except Exception:
            log.exception("worker err")
