"""Moomoo auto-trading via moomoo-api Python SDK. SIMULATE (paper) by default."""
from __future__ import annotations
import os
import logging
import concurrent.futures

log = logging.getLogger(__name__)


def _flag(name):
    return os.getenv(name,"").lower() in ("1","true","yes","on")

def moomoo_enabled():
    return _flag("MOOMOO_ENABLED")

def is_paper():
    return os.getenv("MOOMOO_ENV","SIMULATE").upper() == "SIMULATE"



def _socket_ok(host, port, timeout=2):
    """Fast pre-check: is OpenD actually reachable? Avoids SDK infinite retry."""
    import socket
    try:
        s = socket.socket(); s.settimeout(timeout)
        s.connect((host, int(port))); s.close()
        return True
    except Exception:
        return False

def _get_ctx():
    """Open trade context. Returns (ctx, env, error_str_or_None)."""
    try:
        from moomoo import OpenSecTradeContext, TrdMarket, TrdEnv, SecurityFirm
    except ImportError:
        return None, None, "moomoo-api SDK not installed"
    host = os.getenv("MOOMOO_HOST","127.0.0.1")
    port = int(os.getenv("MOOMOO_PORT","11111"))
    firm_name = os.getenv("MOOMOO_FIRM","FUTUINC")
    try:
        firm = getattr(SecurityFirm, firm_name)
    except AttributeError:
        return None, None, f"invalid MOOMOO_FIRM={firm_name}"
    env = TrdEnv.SIMULATE if is_paper() else TrdEnv.REAL
    if not _socket_ok(host, port):
        return None, None, f"OpenD unreachable at {host}:{port} (tunnel down?)"
    try:
        ctx = OpenSecTradeContext(filter_trdmarket=TrdMarket.US,
                                  host=host, port=port, security_firm=firm)
        return ctx, env, None
    except Exception as e:
        return None, None, f"open ctx fail: {str(e)[:120]}"


def _sync_place(signal):
    if not moomoo_enabled():
        return {"placed": False, "reason": "MOOMOO_ENABLED=0"}
    if _flag("MOOMOO_KILL_SWITCH"):
        return {"placed": False, "reason": "kill_switch=1"}
    ticker = signal["ticker"]; side = signal["side"]
    price = float(signal.get("price",0) or 0)
    if price <= 0: return {"placed": False, "reason": "no price"}
    max_usd = float(os.getenv("MOOMOO_MAX_POSITION_USD","200"))
    min_usd = float(os.getenv("MOOMOO_MIN_POSITION_USD","100"))
    target = min(float(signal.get("suggested_size",max_usd)), max_usd)
    if target < min_usd: return {"placed": False, "reason": f"<min ${min_usd}"}
    qty = max(1, int(target / price))

    ctx, env, err = _get_ctx()
    if err: return {"placed": False, "reason": err}
    try:
        from moomoo import OrderType, TrdSide, TrdEnv, RET_OK
        if env == TrdEnv.REAL:
            pwd = os.getenv("MOOMOO_TRADE_PWD","")
            if not pwd: return {"placed": False, "reason": "MOOMOO_TRADE_PWD missing for REAL"}
            ret, _ = ctx.unlock_trade(pwd)
            if ret != RET_OK: return {"placed": False, "reason": "unlock failed"}
        if side == "LONG":
            trd_side = TrdSide.BUY; limit_px = round(price*1.005, 2)
        else:
            trd_side = TrdSide.SELL_SHORT; limit_px = round(price*0.995, 2)
        # Extended hours support (only effective in REAL mode; paper ignores)
        from moomoo import TimeInForce
        fill_eth = os.getenv("MOOMOO_FILL_OUTSIDE_RTH","0").lower() in ("1","true","yes")
        tif_name = os.getenv("MOOMOO_TIME_IN_FORCE","DAY").upper()
        tif = getattr(TimeInForce, tif_name, TimeInForce.DAY)
        ret, data = ctx.place_order(
            price=limit_px, qty=qty, code=f"US.{ticker}",
            trd_side=trd_side, order_type=OrderType.NORMAL, trd_env=env,
            time_in_force=tif, fill_outside_rth=fill_eth,
        )
        if ret != RET_OK:
            return {"placed": False, "reason": f"place_order: {str(data)[:120]}"}
        order_id = str(data['order_id'].iloc[0]) if hasattr(data,'iloc') else str(data)
        return {"placed": True, "ticker": ticker, "side": side, "qty": qty,
                "limit_price": limit_px, "est_usd": round(qty*limit_px,2),
                "order_id": order_id, "paper": is_paper()}
    except Exception as e:
        log.exception("moomoo place fail")
        return {"placed": False, "reason": f"exception: {str(e)[:120]}"}
    finally:
        try: ctx.close()
        except: pass


def _sync_exit(ticker, side, qty):
    """Close existing position at market."""
    if not moomoo_enabled():
        return {"placed": False, "reason": "MOOMOO_ENABLED=0"}
    ctx, env, err = _get_ctx()
    if err: return {"placed": False, "reason": err}
    try:
        from moomoo import OrderType, TrdSide, TrdEnv, RET_OK
        if env == TrdEnv.REAL:
            pwd = os.getenv("MOOMOO_TRADE_PWD","")
            if pwd:
                ctx.unlock_trade(pwd)
        # LONG → SELL to close. SHORT → BUY_BACK to cover.
        trd_side = TrdSide.SELL if side == "LONG" else TrdSide.BUY_BACK
        from moomoo import TimeInForce
        fill_eth = os.getenv("MOOMOO_FILL_OUTSIDE_RTH","0").lower() in ("1","true","yes")
        # MARKET orders not supported during pre/after-market; use marketable LIMIT instead
        if fill_eth:
            # Get current quote, place aggressive limit
            try:
                from moomoo import OpenQuoteContext
                qctx = OpenQuoteContext(host=os.getenv("MOOMOO_HOST","127.0.0.1"),
                                       port=int(os.getenv("MOOMOO_PORT","11111")))
                ret_q, snap = qctx.get_market_snapshot([f"US.{ticker}"])
                qctx.close()
                px = float(snap['last_price'].iloc[0]) if ret_q == 0 else 0
            except Exception:
                px = 0
            if px > 0:
                # SELL → aggressive low limit (will fill at bid); BUY_BACK → aggressive high
                limit_px = round(px * (0.98 if side=="LONG" else 1.02), 2)
                ret, data = ctx.place_order(
                    price=limit_px, qty=int(qty), code=f"US.{ticker}",
                    trd_side=trd_side, order_type=OrderType.NORMAL, trd_env=env,
                    time_in_force=TimeInForce.DAY, fill_outside_rth=True,
                )
            else:
                ret, data = ctx.place_order(
                    price=0, qty=int(qty), code=f"US.{ticker}",
                    trd_side=trd_side, order_type=OrderType.MARKET, trd_env=env,
                )
        else:
            ret, data = ctx.place_order(
                price=0, qty=int(qty), code=f"US.{ticker}",
                trd_side=trd_side, order_type=OrderType.MARKET, trd_env=env,
            )
        if ret != RET_OK:
            return {"placed": False, "reason": f"exit order: {str(data)[:120]}"}
        return {"placed": True, "exit_action": "SELL" if side=="LONG" else "BUY_BACK",
                "qty": int(qty), "order_id": str(data['order_id'].iloc[0]) if hasattr(data,'iloc') else "?"}
    except Exception as e:
        return {"placed": False, "reason": f"exception: {str(e)[:120]}"}
    finally:
        try: ctx.close()
        except: pass


def place_signal_order(signal):
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(_sync_place, signal).result(timeout=20)
    except Exception as e:
        return {"placed": False, "reason": f"exec: {str(e)[:120]}"}


def place_exit_order(ticker, side, qty):
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(_sync_exit, ticker, side, qty).result(timeout=20)
    except Exception as e:
        return {"placed": False, "reason": f"exec: {str(e)[:120]}"}


def get_status():
    if not moomoo_enabled():
        return {"enabled": False, "reason": "MOOMOO_ENABLED=0"}
    if _flag("MOOMOO_KILL_SWITCH"):
        return {"enabled": True, "kill_switch": True, "paper": is_paper()}
    def _check():
        ctx, env, err = _get_ctx()
        if err: return {"enabled": True, "connection": "down", "error": err}
        try:
            from moomoo import RET_OK
            ret, acc = ctx.accinfo_query(trd_env=env)
            ret2, pos = ctx.position_list_query(trd_env=env)
            nav = float(acc['total_assets'].iloc[0]) if ret == RET_OK and len(acc) > 0 else None
            n_pos = len(pos) if hasattr(pos,'__len__') else 0
            return {"enabled": True, "connection": "up", "paper": is_paper(),
                    "firm": os.getenv("MOOMOO_FIRM","FUTUINC"),
                    "nav_usd": nav, "open_positions": n_pos,
                    "max_position_usd": float(os.getenv("MOOMOO_MAX_POSITION_USD","200"))}
        except Exception as e:
            return {"enabled": True, "connection": "error", "error": str(e)[:120]}
        finally:
            try: ctx.close()
            except: pass
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(_check).result(timeout=10)
    except Exception as e:
        return {"enabled": True, "error": str(e)[:120]}
