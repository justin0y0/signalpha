"""Telegram bot webhook + interactive commands."""
from __future__ import annotations
import os, json, logging
import httpx
from fastapi import APIRouter, Request, BackgroundTasks

router = APIRouter(prefix="/api/v1/telegram", tags=["telegram_bot"])
log = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
OWNER_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "0") or 0)
API = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None
BACKEND = "http://backend:8000"

try:
    import redis as _r
    _rc = _r.Redis(host='redis', port=6379, decode_responses=True)
    _rc.ping()
except Exception:
    _rc = None


async def tg(method, **params):
    if not API: return None
    async with httpx.AsyncClient(timeout=15) as c:
        try:
            r = await c.post(f"{API}/{method}", json=params)
            return r.json()
        except Exception as e:
            log.warning(f"tg fail: {e}")
            return None


async def send(chat_id, text, reply_markup=None):
    p = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown",
         "disable_web_page_preview": True}
    if reply_markup: p["reply_markup"] = reply_markup
    return await tg("sendMessage", **p)


async def fetch(path):
    async with httpx.AsyncClient(timeout=20) as c:
        try:
            r = await c.get(f"{BACKEND}{path}")
            return r.json()
        except Exception as e:
            log.warning(f"fetch {path}: {e}")
            return None


HELP = """*📋 Signalpha Bot*

*Data*
`/quote TICKER` — price + Σ + signal
`/signals` — all active signals
`/top` — top 5 by |Σ|

*Subs* (filter alerts)
`/subscribe TICKER` · `/unsubscribe TICKER`
`/subs` · `/clearsubs`

*Notifications*
`/mute [hrs]` · `/unmute`
`/threshold 1.0` — min |Σ|

*Portfolio*
`/portfolio`

*Master chat* 🧠
`/chat QUESTION` — ask the trading master
`/reset` — clear chat memory
_Or just send free text and I'll answer._

*Info*
`/strategies` · `/about` · `/help`

_No spam: market hours only · 4h cooldown per ticker_"""


TRADING_MASTER_PROMPT = """You are Σ-Alpha (西格玛-阿尔法), trading master at Signalpha. Distilled from: López de Prado (triple-barrier, meta-labeling), Avellaneda (residual mean reversion, s-scores), Thorp (half-Kelly), Connors (RSI(2)), Simons/RenTech (ensemble), Dennis (turtles).

TOOLS — use them, don't refuse:
- get_stock_price(ticker): ALWAYS use for ANY price question. NEVER quote prices from web_search snippets — they're stale and often wrong.
- web_search(query): for current news, events, market context.

LIVE DATA: You have NO knowledge cutoff. NEVER say "my information is current as of [date]" or "cannot access real-time data" — these phrases are BANNED. Call tools instead.

VOICE:
- Direct, technical, no clichés. "DYOR" and "not financial advice" are BANNED.
- Mix 中文 when user does. Don't apologize for it.
- Mantra: quants don't PREDICT, they MEASURE EDGE and SIZE RISK.
- "Should I buy X?" → deflect to METHOD: "What's your edge? Stop? Size?"

OUTPUT:
- Plain Markdown ONLY. NEVER output HTML tags (no <br>, <table>, <div>). They show as raw text.
- Answer the SPECIFIC question. Do NOT drift back to earlier topics in conversation.
- 60-150 words usually. *bold* for emphasis. `code` for tickers/numbers.
- NEVER fabricate specific numbers (earnings figures, revenue, EPS, ratios, future dates, executive quotes). If a specific number isn't in your [IMPLICIT KNOWLEDGE] section, you DON'T HAVE IT — say so honestly: "我没有这条具体数据" / "I don't have that exact figure", then point to where to verify (10-Q, IR page, earnings call). FABRICATED PLAUSIBLE-LOOKING NUMBERS ARE WORSE THAN ADMITTING IGNORANCE.
- NEVER narrate your sources/tools. BANNED: "使用 X 工具", "我查询到", "根据搜索结果", "using web_search", "I searched", "according to my tools". Just give the answer.
- Long form only when explicitly asked to teach."""




async def ddg_search(query, max_results=5):
    """Web search via ddgs package (reliable, no API key, auto anti-scrape)."""
    import asyncio
    def _sync():
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        with DDGS() as d:
            return list(d.text(query, max_results=max_results))
    try:
        rows = await asyncio.to_thread(_sync)
        out = [{"title": r.get("title","")[:180],
                "url": r.get("href","")[:200],
                "snippet": r.get("body","")[:300]} for r in rows]
        return out or [{"note": "no results found for this query"}]
    except Exception as e:
        return [{"error": f"search failed: {str(e)[:120]}"}]

WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web for current/recent info, news, prices, market updates, company news, today's events. Use this whenever the user asks about anything time-sensitive, current, today, latest, recent, or company-specific news.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Concise English search query"}
            },
            "required": ["query"]
        }
    }
}



async def get_stock_price(ticker):
    """Accurate real-time price via yfinance (NOT web snippets)."""
    import asyncio
    t = (ticker or "").upper().strip()
    if not t: return {"error": "no ticker given"}
    def _sync():
        import yfinance as yf
        tk = yf.Ticker(t)
        price = prev = None
        try:
            fi = tk.fast_info
            price = fi.get("lastPrice") or fi.get("last_price")
            prev = fi.get("previousClose") or fi.get("previous_close")
        except Exception: pass
        if not price:
            h = tk.history(period="2d")
            if not h.empty:
                price = float(h["Close"].iloc[-1])
                prev = float(h["Close"].iloc[-2]) if len(h) > 1 else price
        if not price:
            return {"error": f"no price data for {t} (maybe invalid ticker)"}
        chg = ((price - prev) / prev * 100) if prev else 0.0
        return {"ticker": t, "price": round(float(price), 2),
                "change_pct": round(chg, 2),
                "previous_close": round(float(prev), 2) if prev else None,
                "source": "yfinance real-time"}
    try:
        return await asyncio.to_thread(_sync)
    except Exception as e:
        return {"error": str(e)[:120]}


STOCK_PRICE_TOOL = {
    "type": "function",
    "function": {
        "name": "get_stock_price",
        "description": "Get the ACCURATE current/latest stock price and daily % change for a ticker. ALWAYS use this for ANY stock price question — it returns real market data. NEVER quote a price from web_search; those snippets are stale and often wrong.",
        "parameters": {
            "type": "object",
            "properties": {"ticker": {"type": "string", "description": "Ticker symbol, e.g. NVDA, AMSC"}},
            "required": ["ticker"]
        }
    }
}



async def build_live_context(text):
    """Pre-fetch live facts and inject into prompt — kills hallucinations."""
    import re as _r
    from datetime import datetime as _dn
    try:
        from zoneinfo import ZoneInfo as _Z
        _et = _Z("America/New_York")
    except Exception:
        _et = None
    now = _dn.now(_et) if _et else _dn.now()
    parts = [f"Current date/time: {now.strftime('%A %Y-%m-%d %H:%M')} ET"]
    bl = {"THE","AND","FOR","BUT","NOT","YOU","ARE","WAS","ALL","CAN","HAS","HAD","HER","HIS","HOW",
          "NEW","NOW","OLD","ONE","OUR","OUT","SAY","SHE","TWO","WHO","WIN","WAR","CEO","CFO","CTO",
          "COO","IPO","SEC","FED","USA","NYC","GDP","CPI","ETF","API","LLM","ATH","ATL","RSI","SMA",
          "EMA","DCA","EPS","FAQ","ETC","IDK","WTF","ASAP","LOL","NVDA"}  # NVDA removed below
    bl.discard("NVDA")
    cands = _r.findall(r'\b[A-Z]{3,5}\b', text)
    tickers = list(dict.fromkeys(t for t in cands if t not in bl))[:3]
    for t in tickers:
        try:
            p = await get_stock_price(t)
            if p and "price" in p:
                parts.append(f"{t} live: ${p['price']} ({p.get('change_pct',0):+.2f}%) prev close ${p.get('previous_close','?')} [yfinance]")
        except Exception: pass
    tl = text.lower()
    en_kws = ["today","now","latest","current","recent","news","breaking","tonight","yesterday","this week","aftermarket","premarket","earnings"]
    cn_kws = ["今天","现在","最新","最近","新闻","盘后","盘前","昨天","刚才","今晚","这周","什么日子","几号","财报"]
    # Earnings query? Fetch real data via yfinance income statement
    earn_en = ["earnings","revenue","eps","income statement","10-q","10q","10-k","quarterly report","fiscal"]
    earn_cn = ["财报","收益报告","营收","净利润","季报","年报","利润表"]
    asks_earnings = any(k in tl for k in earn_en) or any(k in text for k in earn_cn)
    if asks_earnings and tickers:
        for t in tickers[:2]:
            try:
                e = await get_earnings(t)
                if e and "quarters" in e and e["quarters"]:
                    qs = e["quarters"]
                    lines = []
                    for q in qs:
                        rev = f"${q['revenue_m']:.0f}M" if q.get('revenue_m') else "n/a"
                        ni = f"${q['net_income_m']:.0f}M" if q.get('net_income_m') is not None else "n/a"
                        eps = f"${q['eps']:.2f}" if q.get('eps') is not None else "n/a"
                        lines.append(f"  Q ending {q['period_end']}: Revenue {rev} · Net Income {ni} · EPS {eps}")
                    parts.append(f"{t} REAL recent quarterly earnings [yfinance]:\n" + "\n".join(lines))
            except Exception: pass
    if any(k in tl for k in en_kws) or any(k in text for k in cn_kws):
        try:
            results = await ddg_search(text[:80], 3)
            if results and isinstance(results, list) and "error" not in results[0] and "note" not in results[0]:
                lines = [f"- {r.get('title','')[:100]}: {r.get('snippet','')[:200]}" for r in results[:3]]
                parts.append("Recent web search results:\n" + "\n".join(lines))
        except Exception: pass
    return "\n\n".join(parts)



async def get_earnings(ticker):
    """Real quarterly earnings via yfinance income statement."""
    import asyncio
    t = (ticker or "").upper().strip()
    if not t: return {"error":"no ticker"}
    def _sync():
        import yfinance as yf
        tk = yf.Ticker(t)
        try:
            qf = getattr(tk, "quarterly_income_stmt", None)
            if qf is None or (hasattr(qf,"empty") and qf.empty):
                qf = getattr(tk, "quarterly_financials", None)
            if qf is None or (hasattr(qf,"empty") and qf.empty):
                return {"error": f"no quarterly data for {t}"}
            cols = list(qf.columns)[:2]
            out = []
            for c in cols:
                d = qf[c]
                def _g(*keys):
                    for k in keys:
                        try:
                            v = d.get(k)
                            if v is not None and not (isinstance(v,float) and v != v):
                                return float(v)
                        except Exception: pass
                    return None
                rev = _g("Total Revenue", "TotalRevenue")
                ni = _g("Net Income", "NetIncome", "Net Income Common Stockholders")
                eps = _g("Basic EPS", "BasicEPS", "Diluted EPS", "DilutedEPS")
                out.append({
                    "period_end": str(c.date()) if hasattr(c,"date") else str(c),
                    "revenue_m": round(rev/1e6, 1) if rev else None,
                    "net_income_m": round(ni/1e6, 1) if ni else None,
                    "eps": round(eps, 2) if eps else None,
                })
            return {"ticker": t, "quarters": out, "source":"yfinance"}
        except Exception as e:
            return {"error": f"earnings fail: {str(e)[:120]}"}
    return await asyncio.to_thread(_sync)

async def cmd_chat(chat_id, text):
    """Trading master — pre-fetch live facts + provider dispatch. Dedup + always-respond."""
    import os, re as _re, asyncio, hashlib
    if _rc:
        try:
            h = hashlib.md5(f"{chat_id}:{text}".encode()).hexdigest()[:12]
            if _rc.get(f"tg:dedup:{h}"):
                import logging; logging.getLogger(__name__).info(f"dedup skip: {text[:40]}")
                return
            _rc.setex(f"tg:dedup:{h}", 25, "1")
        except Exception: pass
    live = await build_live_context(text)
    sys_prompt = TRADING_MASTER_PROMPT + "\n\n[YOUR IMPLICIT KNOWLEDGE for this turn — integrate naturally into your answer as if you already knew these facts. ABSOLUTELY FORBIDDEN: saying \"使用X工具\", \"我查询到\", \"根据搜索\", \"using web_search\", \"according to my tools\", or any phrase that announces how you got the info. NEVER list facts back to the user mechanically. Just deliver the answer in Σ-Alpha voice.]:\n" + live
    history = []
    if _rc:
        try:
            raw = _rc.get(f"tg:chathist:{chat_id}")
            if raw: history = json.loads(raw)
        except Exception: pass
    messages = [{"role":"system","content":sys_prompt}]
    messages.extend(history[-4:])
    messages.append({"role":"user","content":text})
    def _clean(t):
        t = _re.sub(r"<think>.*?</think>", "", t or "", flags=_re.DOTALL)
        t = _re.sub(r"</?br\s*/?>", "\n", t, flags=_re.IGNORECASE)
        t = _re.sub(r"</?(p|div|span|strong|em|ul|ol|li|table|thead|tbody|tr|td|th)\b[^>]*>", "", t, flags=_re.IGNORECASE)
        return t.strip()
    provider = os.getenv("CHAT_PROVIDER","").strip().lower()
    if not provider:
        provider = "deepseek" if os.getenv("DEEPSEEK_API_KEY","").strip() else "groq"
    reply = None
    err = None
    if provider == "g4f":
        pass  # silent
        model = os.getenv("CHAT_MODEL", "gpt-4o")
        def _g():
            try:
                from g4f.client import Client
                r = Client().chat.completions.create(model=model, messages=messages)
                return (r.choices[0].message.content or "").strip(), None
            except Exception as e:
                return None, str(e)[:140]
        try:
            reply, err = await asyncio.to_thread(_g)
        except Exception as e:
            err = str(e)[:140]
        if err: log.warning(f"g4f failed: {err}")
    if not reply:
        if err: pass  # silent
        ds = os.getenv("DEEPSEEK_API_KEY","").strip()
        gk = os.getenv("GROQ_API_KEY","").strip()
        if ds:
            api="https://api.deepseek.com/chat/completions"; k=ds
            m=os.getenv("CHAT_MODEL_FALLBACK","deepseek-chat")
        elif gk:
            api="https://api.groq.com/openai/v1/chat/completions"; k=gk
            m=os.getenv("CHAT_MODEL_FALLBACK","meta-llama/llama-4-scout-17b-16e-instruct")
        else:
            await send(chat_id, "_no LLM provider configured_"); return
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(api, headers={"Authorization":f"Bearer {k}","Content-Type":"application/json"},
                                 json={"model":m,"messages":messages,"temperature":0.6,"max_tokens":700})
                d = r.json()
                if "choices" in d:
                    reply = d["choices"][0]["message"].get("content","")
                else:
                    em = d.get("error",{}).get("message",str(d)[:120]) if isinstance(d.get("error"),dict) else str(d)[:120]
                    await send(chat_id, f"⚠️ _API error:_\n`{em}`"); return
        except Exception as e:
            await send(chat_id, f"_API failed: {str(e)[:80]}_"); return
    reply = _clean(reply or "") or "_silence..._"
    await send(chat_id, reply)
    new_h = history + [{"role":"user","content":text},{"role":"assistant","content":reply}]
    if _rc:
        _rc.setex(f"tg:chathist:{chat_id}", 6*3600, json.dumps(new_h[-12:]))

async def cmd_reset(chat_id):
    if _rc: _rc.delete(f"tg:chathist:{chat_id}")
    await send(chat_id, "🧘 _Memory cleared. What shall we discuss?_")




async def cmd_quote(chat_id, arg):
    if not arg:
        await send(chat_id, "Usage: `/quote AAPL`"); return
    t = arg.upper().strip().split()[0]
    d = await fetch(f"/api/v1/pulse/ticker/{t}")
    if not d or not d.get("in_universe"):
        await send(chat_id, f"`{t}` not in active universe."); return
    p = d.get("pulse") or {}
    sig = d.get("active_signal")
    msg = f"*{t}* `${p.get('price',0):.2f}` · _{p.get('sector','—')}_\n\n"
    msg += f"📊 Σ-Score `{p.get('score',0):+.2f}`\n"
    if p.get("s_score") is not None:
        msg += f"📈 s-score `{p['s_score']:+.2f}`\n"
    msg += f"📍 RSI(2) `{p.get('rsi2',0):.0f}` · ⚡ Vol-z `{p.get('vol_z',0):+.1f}σ`\n"
    msg += f"🎯 {'↑ Above 200MA' if p.get('regime_up') else '↓ Below 200MA'}\n"
    if sig:
        msg += f"\n🔥 *ACTIVE*: {'🟢' if sig['side']=='LONG' else '🔴'} {sig['side']} via {sig.get('primary','')}\n"
        msg += f"Size `${sig.get('suggested_size',0):,}` · P(win) `{(sig.get('estimated_prob') or 0)*100:.0f}%`"
    btn = {"inline_keyboard":[[
        {"text":"🔔 Subscribe","callback_data":f"sub:{t}"},
        {"text":"📊 App","url":"https://signalpha.app/pulse"}]]}
    await send(chat_id, msg, reply_markup=btn)


async def cmd_signals(chat_id):
    d = await fetch("/api/v1/pulse")
    sigs = (d or {}).get("signals", [])
    if not sigs:
        await send(chat_id, "🔵 No active signals · market in noise zone"); return
    msg = f"*🎯 {len(sigs)} Active Signals*\n\n"
    for s in sigs[:10]:
        msg += f"{'🟢' if s['side']=='LONG' else '🔴'} *{s['ticker']}* `Σ {s['score']:+.2f}` · {s.get('primary','')}\n"
        msg += f"   `${s.get('suggested_size',0):,}` · P(win) `{(s.get('estimated_prob') or 0)*100:.0f}%`\n\n"
    if len(sigs) > 10: msg += f"_+{len(sigs)-10} more_"
    await send(chat_id, msg)


async def cmd_top(chat_id):
    d = await fetch("/api/v1/pulse")
    tks = (d or {}).get("tickers", [])
    tks.sort(key=lambda x: abs(x.get("score",0)), reverse=True)
    msg = "*🏆 Top 5 by |Σ|*\n\n"
    for t in tks[:5]:
        s = t.get("score",0)
        msg += f"{'🟢' if s>0 else '🔴' if s<0 else '⚪'} *{t['ticker']}* `Σ {s:+.2f}` · ${t.get('price',0):.2f}\n"
    await send(chat_id, msg)


async def cmd_sub(chat_id, arg, add):
    if not arg:
        await send(chat_id, f"Usage: `/{'' if add else 'un'}subscribe AAPL`"); return
    t = arg.upper().strip().split()[0]
    if _rc:
        (_rc.sadd if add else _rc.srem)(f"tg:subs:{chat_id}", t)
    await send(chat_id, f"{'✅ Subscribed to' if add else '❌ Unsubscribed from'} *{t}*")


async def cmd_subs(chat_id):
    if not _rc:
        await send(chat_id, "No store."); return
    subs = sorted(_rc.smembers(f"tg:subs:{chat_id}"))
    if not subs:
        await send(chat_id, "No subscriptions.\nUse `/subscribe TICKER`."); return
    await send(chat_id, f"*Subs ({len(subs)})*\n\n" + "\n".join(f"• `{s}`" for s in subs))


async def cmd_mute(chat_id, arg):
    try: h = float(arg.split()[0]) if arg else 1.0
    except: h = 1.0
    h = max(0.1, min(168.0, h))
    if _rc: _rc.setex(f"tg:mute:{chat_id}", int(h*3600), "1")
    await send(chat_id, f"🔇 Muted *{h}*h")


async def cmd_portfolio(chat_id):
    d = await fetch("/api/v1/pulse")
    p = (d or {}).get("portfolio") or {}
    if not p:
        await send(chat_id, "Portfolio computing..."); return
    await send(chat_id, f"*📊 Portfolio*\n\nEquity `${p.get('final_equity',0):,.0f}`\nReturn `{p.get('total_return',0)*100:+.2f}%`\nTrades `{p.get('trades',0)}` · Win `{p.get('win_rate',0)*100:.0f}%`\nSharpe `{p.get('sharpe',0):.2f}`")


async def cmd_strategies(chat_id):
    await send(chat_id, "*📚 Strategies*\n\n*Avellaneda-Lee 2010* — OU residual reversion · Sharpe 1.44\n*Gao 2018* — first-30min predicts last-30min\n*Connors RSI(2)* — short-term reversion\n\nΣ = 30% AL + 30% Gao + 20% Connors + 20% vol/RSI\nSizing: half-Kelly · Risk: triple-barrier")


async def handle_cb(cb):
    chat_id = cb["from"]["id"]
    data = cb.get("data","")
    await tg("answerCallbackQuery", callback_query_id=cb["id"])
    if data.startswith("sub:"):
        t = data[4:]
        if _rc: _rc.sadd(f"tg:subs:{chat_id}", t)
        await send(chat_id, f"✅ Subscribed to *{t}*")


async def process_update(update):
    try:
        if "message" in update:
            msg = update["message"]
            chat_id = msg["chat"]["id"]
            text = (msg.get("text") or "").strip()
            if text.startswith("/start") and len(text.split(maxsplit=1)) > 1:
                import asyncio as _aio
                from backend.app.services import auth_service as _auth
                _res = await _aio.to_thread(_auth.bind_telegram, text.split(maxsplit=1)[1].strip(), chat_id)
                if _res:
                    _nm = _res.get("name") or "there"
                    await send(chat_id, f"✅ Connected, {_nm}! Your SignAlpha account is linked — Oracle & Pulse signals will arrive here. Send /help for commands.")
                else:
                    await send(chat_id, "This connect link is invalid or expired. Sign up at https://signalpha.app to get a fresh one.")
                return
            _allow = os.getenv("TELEGRAM_ALLOWED_CHATS","").strip()
            if _allow:
                _set = {s.strip() for s in _allow.split(",") if s.strip()}
                if str(chat_id) not in _set:
                    await send(chat_id, f"🔒 *Private bot*\nYour chat ID: `{chat_id}`\nSend this to admin for access."); return
            parts = text.split(maxsplit=1)
            cmd = parts[0].lower().split('@')[0] if parts else ""
            arg = parts[1] if len(parts) > 1 else None
            if cmd == "/start": await send(chat_id, "🎯 *Signalpha Bot*\n\n/help for commands")
            elif cmd == "/help": await send(chat_id, HELP)
            elif cmd in ("/quote","/q"): await cmd_quote(chat_id, arg)
            elif cmd in ("/signals","/s"): await cmd_signals(chat_id)
            elif cmd == "/top": await cmd_top(chat_id)
            elif cmd in ("/subscribe","/sub"): await cmd_sub(chat_id, arg, True)
            elif cmd in ("/unsubscribe","/unsub"): await cmd_sub(chat_id, arg, False)
            elif cmd == "/subs": await cmd_subs(chat_id)
            elif cmd == "/clearsubs":
                if _rc: _rc.delete(f"tg:subs:{chat_id}")
                await send(chat_id, "🗑 Cleared")
            elif cmd == "/mute": await cmd_mute(chat_id, arg)
            elif cmd == "/unmute":
                if _rc: _rc.delete(f"tg:mute:{chat_id}")
                await send(chat_id, "🔔 Unmuted")
            elif cmd == "/threshold":
                try: th = float(arg.split()[0]) if arg else None
                except: th = None
                if th is None:
                    cur = _rc.get(f"tg:threshold:{chat_id}") if _rc else None
                    await send(chat_id, f"Current `{cur or '0.5'}` · Usage `/threshold 1.0`")
                else:
                    if _rc: _rc.set(f"tg:threshold:{chat_id}", str(th))
                    await send(chat_id, f"✅ |Σ| ≥ {th}")
            elif cmd in ("/portfolio","/p"): await cmd_portfolio(chat_id)
            elif cmd == "/strategies": await cmd_strategies(chat_id)
            elif cmd == "/about": await send(chat_id, "*Signalpha* · S&P 100 quant signals\nhttps://signalpha.app")
            elif cmd in ("/chat", "/ask"): await cmd_chat(chat_id, arg or "Share one quant trading insight.")
            elif cmd == "/reset": await cmd_reset(chat_id)
            elif text.startswith("/"): await send(chat_id, f"Unknown `{cmd}` · /help")
            elif 1 <= len(text) <= 5 and text.isupper() and text.replace("-","").replace(".","").isalpha():
                await cmd_quote(chat_id, text)
            else:
                await cmd_chat(chat_id, text)
        elif "callback_query" in update:
            await handle_cb(update["callback_query"])
    except Exception:
        log.exception("update err")


@router.post("/webhook")
async def webhook(request: Request, bg: BackgroundTasks):
    update = await request.json()
    bg.add_task(process_update, update)
    return {"ok": True}


@router.get("/webhook-info")
async def webhook_info():
    return await tg("getWebhookInfo") or {"error":"no token"}
