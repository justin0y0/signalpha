"""Pulse track record API — aggregated stats + full trade list + cohort breakdowns."""
from __future__ import annotations
from fastapi import APIRouter
from sqlalchemy import text
from backend.app.db.session import SessionLocal

router = APIRouter(prefix="/api/v1/pulse", tags=["track_record"])


@router.get("/track-record")
def get_track_record():
    db = SessionLocal()
    try:
        agg = db.execute(text("""
            SELECT COUNT(*) total, COUNT(*) FILTER (WHERE status='closed') closed,
                   COUNT(*) FILTER (WHERE status='open') opn,
                   COALESCE(SUM(pnl_dollars),0) total_pnl,
                   COALESCE(AVG(return_pct) FILTER (WHERE status='closed'),0) avg_ret,
                   COUNT(*) FILTER (WHERE win=true) wins,
                   COUNT(*) FILTER (WHERE win=false) losses
            FROM pulse_signal_log
        """)).fetchone()
        all_trades = db.execute(text("""
            SELECT id, ticker, side, score, strategy,
                   entry_price, entry_time, tp_price, sl_price,
                   expected_exit_time, exit_price, exit_time, exit_reason,
                   return_pct, pnl_dollars, win, status, suggested_size,
                   EXTRACT(EPOCH FROM (COALESCE(exit_time, NOW()) - entry_time))/3600.0 AS hours_held
            FROM pulse_signal_log ORDER BY entry_time DESC LIMIT 200
        """)).fetchall()
        by_strat = db.execute(text("""
            SELECT COALESCE(strategy,'—') strategy, COUNT(*) n,
                   COUNT(*) FILTER (WHERE win=true) wins,
                   COUNT(*) FILTER (WHERE win=false) losses,
                   COALESCE(SUM(pnl_dollars),0) pnl,
                   COALESCE(AVG(return_pct),0) avg_ret
            FROM pulse_signal_log WHERE status='closed'
            GROUP BY strategy ORDER BY pnl DESC
        """)).fetchall()
        by_side = db.execute(text("""
            SELECT side, COUNT(*) n,
                   COUNT(*) FILTER (WHERE win=true) wins,
                   COUNT(*) FILTER (WHERE win=false) losses,
                   COALESCE(SUM(pnl_dollars),0) pnl,
                   COALESCE(AVG(return_pct),0) avg_ret
            FROM pulse_signal_log WHERE status='closed'
            GROUP BY side ORDER BY pnl DESC
        """)).fetchall()
        by_session = db.execute(text("""
            SELECT CASE
                WHEN EXTRACT(HOUR FROM entry_time AT TIME ZONE 'America/New_York') BETWEEN 4 AND 8 THEN 'pre_market'
                WHEN EXTRACT(HOUR FROM entry_time AT TIME ZONE 'America/New_York') BETWEEN 9 AND 15 THEN 'market'
                WHEN EXTRACT(HOUR FROM entry_time AT TIME ZONE 'America/New_York') BETWEEN 16 AND 19 THEN 'after_hours'
                ELSE 'overnight' END AS session,
                COUNT(*) n, COUNT(*) FILTER (WHERE win=true) wins,
                COUNT(*) FILTER (WHERE win=false) losses,
                COALESCE(SUM(pnl_dollars),0) pnl,
                COALESCE(AVG(return_pct),0) avg_ret
            FROM pulse_signal_log WHERE status='closed'
            GROUP BY session ORDER BY pnl
        """)).fetchall()
        curve = db.execute(text("""
            SELECT entry_time::date d, COALESCE(SUM(pnl_dollars),0) daily
            FROM pulse_signal_log WHERE status='closed'
            GROUP BY entry_time::date ORDER BY entry_time::date
        """)).fetchall()
        wr = float(agg.wins / agg.closed) if agg.closed > 0 else 0.0
        cum = 0.0; equity = []
        for c in curve:
            cum += float(c.daily or 0)
            equity.append({"date": c.d.isoformat(), "cum_pnl": cum})
        trades = [dict(r._mapping) for r in all_trades]
        return {
            "total_signals": int(agg.total or 0), "closed": int(agg.closed or 0),
            "open": int(agg.opn or 0), "total_pnl_dollars": float(agg.total_pnl or 0),
            "avg_return_pct": float(agg.avg_ret or 0), "win_rate": wr,
            "wins": int(agg.wins or 0), "losses": int(agg.losses or 0),
            "recent": trades[:20], "all_trades": trades,
            "by_strategy": [dict(r._mapping) for r in by_strat],
            "by_side": [dict(r._mapping) for r in by_side],
            "by_session": [dict(r._mapping) for r in by_session],
            "equity_curve": equity,
        }
    finally:
        db.close()
