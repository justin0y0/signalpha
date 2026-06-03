"""IBKR auto-trading via ib_async. Paper-mode default, multiple safety gates.

REQUIRED SETUP (do this BEFORE flipping IBKR_ENABLED=1):
  1. Open IBKR paper account at interactivebrokers.com
  2. Download & install IB Gateway (lighter than TWS)
  3. Run IB Gateway, log in with PAPER account
  4. Configure → API → Settings: enable ActiveX/Socket clients, port 7497 (paper) / 7496 (live)
  5. Add this server's IP to Trusted IPs (or 127.0.0.1 if running on same host)
  6. Set env vars in .env, then set IBKR_ENABLED=1
"""
from __future__ import annotations
import os
import logging
import concurrent.futures

log = logging.getLogger(__name__)


def _flag(name): return os.getenv(name,"").lower() in ("1","true","yes","on")
def ibkr_enabled(): return _flag("IBKR_ENABLED")
def is_paper(): return int(os.getenv("IBKR_PORT","7497")) == 7497


def _sync_place(signal):
    """Sync IBKR call — runs in thread pool to avoid asyncio conflicts."""
    if ibkr_enabled() is False:
        return {"placed": False, "reason": "IBKR_ENABLED=0 (off)"}
    if _flag("IBKR_KILL_SWITCH"):
        return {"placed": False, "reason": "KILL_SWITCH=1"}
    ticker, side = signal["ticker"], signal["side"]
    price = float(signal.get("price", 0) or 0)
    tp = float(signal.get("_tp_price", 0) or 0)
    sl = float(signal.get("_sl_price", 0) or 0)
    if price <= 0 or tp <= 0 or sl <= 0:
        return {"placed": False, "reason": "missing price/tp/sl"}

    max_usd = float(os.getenv("IBKR_MAX_POSITION_USD", "1000"))
    min_usd = float(os.getenv("IBKR_MIN_POSITION_USD", "100"))
    target_usd = min(float(signal.get("suggested_size", max_usd)), max_usd)
    if target_usd < min_usd:
        return {"placed": False, "reason": f"below min ${min_usd}"}
    qty = max(1, int(target_usd / price))

    try:
        from ib_async import IB, Stock
    except ImportError:
        return {"placed": False, "reason": "ib_async not installed"}

    ib = IB()
    host = os.getenv("IBKR_HOST", "127.0.0.1")
    port = int(os.getenv("IBKR_PORT", "7497"))
    cid = int(os.getenv("IBKR_CLIENT_ID", "11"))
    try:
        ib.connect(host, port, clientId=cid, timeout=8)
    except Exception as e:
        return {"placed": False, "reason": f"IB Gateway not reachable {host}:{port}: {str(e)[:80]}"}

    try:
        contract = Stock(ticker, "SMART", "USD")
        ib.qualifyContracts(contract)
        action = "BUY" if side == "LONG" else "SELL"
        # slight slippage tolerance on entry limit
        limit_px = round(price * (1.005 if action == "BUY" else 0.995), 2)
        # Bracket order: parent + TP + SL (OCA child orders, auto-cancel each other)
        bracket = ib.bracketOrder(action, qty,
                                  limitPrice=limit_px,
                                  takeProfitPrice=round(tp, 2),
                                  stopLossPrice=round(sl, 2))
        order_ids = []
        for o in bracket:
            o.outsideRth = False  # regular hours only
            trade = ib.placeOrder(contract, o)
            order_ids.append(trade.order.orderId)
        ib.sleep(2)
        return {
            "placed": True, "ticker": ticker, "side": side, "action": action,
            "qty": qty, "limit_price": limit_px, "tp": round(tp,2), "sl": round(sl,2),
            "est_usd": round(qty * limit_px, 2), "order_ids": order_ids,
            "paper": is_paper(),
        }
    except Exception as e:
        log.exception("IBKR place fail")
        return {"placed": False, "reason": f"exception: {str(e)[:120]}"}
    finally:
        try: ib.disconnect()
        except Exception: pass


def place_signal_order(signal: dict) -> dict:
    """Thread-pooled IBKR order placement. Safe from any sync/async context."""
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(_sync_place, signal).result(timeout=20)
    except concurrent.futures.TimeoutError:
        return {"placed": False, "reason": "IBKR timeout 20s"}
    except Exception as e:
        return {"placed": False, "reason": f"exec fail: {str(e)[:120]}"}


def get_status() -> dict:
    """Status endpoint helper."""
    if not ibkr_enabled():
        return {"enabled": False, "reason": "IBKR_ENABLED=0"}
    if _flag("IBKR_KILL_SWITCH"):
        return {"enabled": True, "kill_switch": True, "paper": is_paper()}
    def _check():
        try:
            from ib_async import IB
        except ImportError:
            return {"enabled": True, "ib_async": "not installed"}
        ib = IB()
        host = os.getenv("IBKR_HOST","127.0.0.1"); port = int(os.getenv("IBKR_PORT","7497"))
        cid = int(os.getenv("IBKR_CLIENT_ID","11"))
        try:
            ib.connect(host, port, clientId=cid, timeout=6)
            positions = ib.positions()
            avs = ib.accountValues()
            nav = next((float(a.value) for a in avs if a.tag == "NetLiquidation"), None)
            return {"enabled": True, "connection": "up", "paper": is_paper(),
                    "open_positions": len(positions), "nav": nav,
                    "max_position_usd": float(os.getenv("IBKR_MAX_POSITION_USD","1000"))}
        except Exception as e:
            return {"enabled": True, "connection": "down", "error": str(e)[:120], "paper": is_paper()}
        finally:
            try: ib.disconnect()
            except: pass
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(_check).result(timeout=10)
    except Exception as e:
        return {"enabled": True, "connection": "error", "error": str(e)[:120]}
