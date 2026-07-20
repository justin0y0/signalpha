"""Oracle — primary-source scan: X API, Truth Social, Google News RSS, generic RSS,
plus SEC EDGAR / ARK / Congress."""
from __future__ import annotations
import os, json, time, hashlib, logging, re
import xml.etree.ElementTree as ET
from urllib.parse import quote
import httpx

log = logging.getLogger(__name__)
UA = {"User-Agent": "Signalpha-research contact@signalpha.app"}
try:
    import redis as _rl
    _rc = _rl.Redis(host='redis', port=6379, decode_responses=True); _rc.ping()
except Exception:
    _rc = None

FIGURES = {
  "trump":   {"name":"Donald Trump","emoji":"🇺🇸","type":"policy","why":"Truth Social posts move markets",
     "sources":[{"type":"truth","handle":"realDonaldTrump"},{"type":"x","handle":"realDonaldTrump"},
                {"type":"gnews","queries":["Trump stocks company","Trump tariff stock"]}]},
  "huang":   {"name":"Jensen Huang","emoji":"🟢","type":"tech_ceo","why":"AI/semis comments",
     "sources":[{"type":"gnews","queries":["Jensen Huang stock company","Nvidia CEO comment stock"]},
                {"type":"news","queries":["Jensen Huang says stock"]}]},
  "serenity":{"name":"Serenity","emoji":"🐦","type":"x_trader","why":"X trader",
     "sources":[{"type":"x","handle":"<SERENITY_X>"},{"type":"rss","url_env":"ORACLE_RSS_SERENITY"},
                {"type":"gnews","queries":["Serenity trader stock pick"]}]},
  "musk":    {"name":"Elon Musk","emoji":"🚀","type":"x_mover","why":"X posts, high variance",
     "sources":[{"type":"x","handle":"elonmusk"},{"type":"gnews","queries":["Elon Musk stock comment"]}]},
  "su":      {"name":"Lisa Su","emoji":"🔴","type":"tech_ceo","why":"AMD/AI guidance",
     "sources":[{"type":"gnews","queries":["Lisa Su AMD stock comment"]}]},
  "wood":    {"name":"Cathie Wood","emoji":"📈","type":"fund","why":"ARK daily trades + X",
     "sources":[{"type":"ark"},{"type":"x","handle":"CathieDWood"},{"type":"gnews","queries":["Cathie Wood ARK buy stock"]}]},
  "ackman":  {"name":"Bill Ackman","emoji":"🎯","type":"activist","why":"X theses + 13D",
     "sources":[{"type":"x","handle":"BillAckman"},{"type":"edgar","cik":"1336528"},{"type":"gnews","queries":["Bill Ackman stock stake"]}]},
  "pelosi":  {"name":"Nancy Pelosi","emoji":"🏛","type":"congress","why":"Congressional disclosures",
     "sources":[{"type":"congress","name":"Pelosi"},{"type":"gnews","queries":["Nancy Pelosi stock trade"]}]},
  "buffett": {"name":"Warren Buffett","emoji":"💰","type":"value","why":"Berkshire 13F/13D",
     "sources":[{"type":"edgar","cik":"1067983"},{"type":"gnews","queries":["Warren Buffett Berkshire stock buy"]}]},
  "burry":   {"name":"Michael Burry","emoji":"🐻","type":"contrarian","why":"X (Cassandra) + 13F",
     "sources":[{"type":"x","handle":"michaeljburry"},{"type":"edgar","cik":"1649339"},{"type":"gnews","queries":["Michael Burry Scion stock"]}]},
}

def _enabled():
    if _rc is None: return set(FIGURES)
    try:
        v=_rc.get("oracle:enabled"); return set(FIGURES) if v is None else set(json.loads(v))
    except Exception: return set(FIGURES)
def set_enabled(keys):
    if _rc is None: return
    try: _rc.set("oracle:enabled", json.dumps(sorted(set(keys)&set(FIGURES))))
    except Exception: pass
def _seen(fk, uid):
    if _rc is None or not uid: return False
    k="oracle:seen:"+hashlib.md5((fk+"|"+str(uid)).encode()).hexdigest()
    try:
        if _rc.exists(k): return True
        _rc.setex(k,604800,"1"); return False
    except Exception: return False
def _due(stype, ttl):
    if _rc is None: return True
    k=f"oracle:srcrun:{stype}"
    try:
        if _rc.exists(k): return False
        _rc.setex(k,ttl,"1"); return True
    except Exception: return True

def _parse_rss(xml_text, limit=6):
    out=[]
    try:
        root=ET.fromstring(xml_text)
        items=root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
        for it in items[:limit]:
            def g(tag):
                e=it.find(tag)
                if e is None: e=it.find("{http://www.w3.org/2005/Atom}"+tag)
                return (e.text or "") if e is not None else ""
            title=g("title"); link=g("link")
            if not link:
                le=it.find("{http://www.w3.org/2005/Atom}link")
                link=le.get("href") if le is not None else ""
            desc=g("description") or g("summary") or g("content")
            if title: out.append({"title":title,"body":re.sub("<[^>]+>","",desc)[:500],"url":link})
    except Exception: pass
    return out

def _fetch_news(query,n=3):
    for mod in ("ddgs","duckduckgo_search"):
        try:
            m=__import__(mod,fromlist=["DDGS"])
            with m.DDGS() as d: return list(d.news(query,max_results=n))
        except Exception: continue
    return []

def src_gnews(query):
    try:
        r=httpx.get(f"https://news.google.com/rss/search?q={quote(query)}&hl=en-US&gl=US&ceid=US:en",
                    headers=UA,timeout=15,follow_redirects=True)
        if r.status_code!=200: return []
        return [{"kind":"news","headline":x["title"],"body":x["body"],"url":x["url"],"uid":x["url"] or x["title"]}
                for x in _parse_rss(r.text,5)]
    except Exception as e: log.warning(f"gnews: {e}"); return []

def src_rss(url):
    if not url or url.startswith("<"): return []
    try:
        r=httpx.get(url,headers=UA,timeout=15,follow_redirects=True)
        if r.status_code!=200: return []
        return [{"kind":"news","headline":x["title"],"body":x["body"],"url":x["url"],"uid":x["url"] or x["title"]}
                for x in _parse_rss(r.text,6)]
    except Exception as e: log.warning(f"rss: {e}"); return []

def _x_uid(handle,bearer):
    if _rc is not None:
        c=_rc.get(f"oracle:xid:{handle}")
        if c: return c
    r=httpx.get(f"https://api.twitter.com/2/users/by/username/{handle}",
                headers={"Authorization":f"Bearer {bearer}"},timeout=15)
    if r.status_code!=200: return None
    uid=r.json().get("data",{}).get("id")
    if uid and _rc is not None:
        try: _rc.setex(f"oracle:xid:{handle}",86400,uid)
        except Exception: pass
    return uid

def src_x(handle):
    bearer=os.getenv("X_BEARER_TOKEN","").strip()
    if not bearer or not handle or handle.startswith("<"): return []
    if not _due(f"x:{handle}",300): return []
    try:
        uid=_x_uid(handle,bearer)
        if not uid: return []
        r=httpx.get(f"https://api.twitter.com/2/users/{uid}/tweets",
            params={"max_results":5,"tweet.fields":"created_at"},
            headers={"Authorization":f"Bearer {bearer}"},timeout=15)
        if r.status_code!=200: log.warning(f"x {handle} {r.status_code}"); return []
        return [{"kind":"news","headline":f"@{handle}: {t.get('text','')[:120]}","body":t.get("text",""),
                 "url":f"https://x.com/{handle}/status/{t.get('id')}","uid":f"tweet:{t.get('id')}"}
                for t in r.json().get("data",[])]
    except Exception as e: log.warning(f"x {handle}: {e}"); return []

def src_truth(handle):
    u=os.getenv("TRUTHSOCIAL_USERNAME","").strip(); p=os.getenv("TRUTHSOCIAL_PASSWORD","").strip()
    if not u or not p: return []
    if not _due(f"truth:{handle}",300): return []
    try:
        from truthbrush import Api
        api=Api(u,p); out=[]
        for st in api.pull_statuses(handle,replies=False,verbose=False):
            txt=re.sub("<[^>]+>","",st.get("content","") or "")
            out.append({"kind":"news","headline":f"Truth @{handle}: {txt[:120]}","body":txt,
                        "url":st.get("url",""),"uid":"truth:"+str(st.get("id"))})
            if len(out)>=5: break
        return out
    except Exception as e: log.warning(f"truth {handle}: {e}"); return []

def src_ark():
    return []
    if not _due("ark",3600): return []
    try:
        r=httpx.get("https://arkfunds.io/api/v2/etf/trades",params={"symbol":"ARKK","limit":15},headers=UA,timeout=15)
        if r.status_code!=200: return []
        out=[]
        for t in r.json().get("trades",[])[:15]:
            tk=(t.get("ticker") or "").upper().strip()
            if not tk.isalpha() or len(tk)>5: continue
            d=(t.get("direction") or "").lower()
            out.append({"kind":"trade","ticker":tk,"sentiment":"bullish" if "buy" in d else "bearish",
                "headline":f"ARK {t.get('direction','')} {tk} ({t.get('shares','?')}sh)",
                "rationale":f"Cathie Wood / ARK {d} {t.get('date','')}","url":"https://ark-funds.com/funds/arkk/",
                "conf":0.8,"uid":f"ark:{t.get('date')}:{tk}:{d}"})
        return out
    except Exception as e: log.warning(f"ark: {e}"); return []

def src_congress(name):
    if not _due("congress",3600): return []
    try:
        ck=f"oracle:cong:{name}"
        if _rc is not None:
            c=_rc.get(ck)
            if c: return json.loads(c)
        r=httpx.get("https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json",headers=UA,timeout=25)
        if r.status_code!=200: return []
        rows=[t for t in r.json() if name.lower() in (t.get("representative","") or "").lower()]
        rows.sort(key=lambda x:x.get("disclosure_date",""),reverse=True)
        out=[]
        for t in rows[:8]:
            tk=(t.get("ticker") or "").upper().strip()
            if not tk.isalpha() or len(tk)>5: continue
            typ=(t.get("type") or "").lower()
            out.append({"kind":"trade","ticker":tk,"sentiment":"bullish" if "purchase" in typ else "bearish",
                "headline":f"{name} {typ} {tk}","rationale":f"Congress disclosure {t.get('transaction_date','')}",
                "url":"https://housestockwatcher.com","conf":0.7,"uid":f"cong:{t.get('transaction_date')}:{tk}:{typ}"})
        if _rc is not None:
            try: _rc.setex(ck,3600,json.dumps(out))
            except Exception: pass
        return out
    except Exception as e: log.warning(f"congress: {e}"); return []

def src_edgar(cik,name):
    if not _due(f"edgar:{cik}",3600): return []
    try:
        r=httpx.get(f"https://data.sec.gov/submissions/CIK{str(cik).zfill(10)}.json",headers=UA,timeout=15)
        if r.status_code!=200: return []
        rec=r.json().get("filings",{}).get("recent",{})
        forms,dates,accns=rec.get("form",[]),rec.get("filingDate",[]),rec.get("accessionNumber",[])
        import datetime as _dt
        cutoff=(_dt.date.today()-_dt.timedelta(days=int(os.getenv("ORACLE_EDGAR_DAYS","10")))).isoformat()
        out=[]
        for i in range(min(12,len(forms))):
            if forms[i] not in ("13F-HR","SC 13D","SC 13D/A","SC 13G","SC 13G/A"): continue
            if dates[i] < cutoff: continue
            out.append({"kind":"filing","headline":f"{name} filed {forms[i]} ({dates[i]})",
                "url":f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={forms[i]}",
                "uid":f"edgar:{accns[i]}"})
        return out
    except Exception as e: log.warning(f"edgar: {e}"); return []

_BLOCKED_DOMAINS = {d.strip().lower() for d in os.getenv("ORACLE_BLOCK_DOMAINS",
    "foreignpolicyjournal.com,marketbeat.com,wallstreetpr.com,newsheater.com,etfdailynews.com,defenseworld.net,zerohedge.com").split(",") if d.strip()}
def _domain_ok(url):
    try:
        from urllib.parse import urlparse
        h=(urlparse(url or "").hostname or "").lower()
        if h.startswith("www."): h=h[4:]
        return not any(h==d or h.endswith("."+d) for d in _BLOCKED_DOMAINS)
    except Exception:
        return True

def _gather(fk,fig):
    items=[]
    for src in fig.get("sources",[]):
        st=src.get("type")
        try:
            if st=="news":
                for q in src.get("queries",[]):
                    for it in _fetch_news(q,3):
                        items.append({"kind":"news","headline":it.get("title",""),
                            "body":it.get("body","") or it.get("excerpt",""),
                            "url":it.get("url") or it.get("link",""),"uid":it.get("url") or it.get("title","")})
            elif st=="gnews":
                for q in src.get("queries",[]): items+=src_gnews(q)
            elif st=="rss":
                items+=src_rss(os.getenv(src.get("url_env",""),"") if src.get("url_env") else src.get("url",""))
            elif st=="x": items+=src_x(src.get("handle",""))
            elif st=="nitter": items+=src_nitter(src.get("handle",""))
            elif st=="truth": items+=src_truth(src.get("handle",""))
            elif st=="trumparchive": items+=src_truth_cnn()
            elif st=="marketaux": items+=src_marketaux(fig["name"])
            elif st=="ark": items+=src_ark()
            elif st=="congress": items+=src_congress(src.get("name",""))
            elif st=="edgar": items+=src_edgar(src.get("cik",""),fig["name"])
        except Exception as e: log.warning(f"gather {st} {fk}: {e}")
    return [it for it in items if _domain_ok(it.get("url",""))]

def _llm_analyze(fn,headline,body):
    key=os.getenv("GROQ_API_KEY","").strip()
    if not key: return []
    model=os.getenv("ORACLE_MODEL",os.getenv("CHAT_MODEL","llama-3.3-70b-versatile"))
    prompt=(
        f"You are a disciplined equity analyst. We track ONE specific market-moving person: {fn}.\n"
        f"Below is a news item that supposedly involves them.\n\n"
        f"HEADLINE: {headline}\nDETAIL: {body}\n\n"
        f"Decide if this is a REAL, tradable signal that {fn} PERSONALLY created. Output AT MOST ONE "
        "signal (a 2nd only if an equally direct, non-substitutable beneficiary). When in doubt, output nothing.\n\n"
        "Return EMPTY signals if ANY of these is true:\n"
        f"- The actor in the story is a DIFFERENT person/CEO, or a company/fund that merely shares a similar name "
        f"(a quote by another company's CEO is NOT a {fn} signal).\n"
        f"- It is an article ABOUT {fn} (their influence, a profile, 'can move markets', 'why X matters') rather "
        "than a specific thing they just SAID or DID.\n"
        "- It is speculation or analyst framing: 'could/may/might/how X impacts Y', 'is it time to buy', a "
        "price-target or rating piece. Act ONLY on the person's own concrete statement, post, or disclosed trade.\n"
        "- It is a routine holdings list, or a retrospective on an OLD trade ('exited months ago').\n"
        "- It is an extraordinary, unverified claim from a non-primary outlet -> treat as untrue and reject.\n"
        f"- The beneficiary would be a basket, an index, or a broad ETF (SPY, QQQ, ARKK, UNG...), or {fn}'s own fund.\n"
        "- The company is private/unlisted, or you are not certain of the EXACT US-listed ticker.\n\n"
        "IF it passes: pick the SINGLE purest-play beneficiary (one ticker, one hop). sentiment = direct "
        "first-order effect. confidence: 0.85+ ONLY for an explicit single-named catalyst, 0.6-0.8 for a clear "
        "but indirect link; never inflate.\n"
        f"rationale = ONE full sentence naming what {fn} specifically said/did, the company, and why it moves "
        "(NEVER a 2-3 word fragment like 'tariffs' or 'CEO speaks').\n\n"
        'Return STRICT JSON only: {"signals":[{"ticker":"TCKR","sentiment":"bullish|bearish","confidence":0.0,'
        '"rationale":"<one full causal sentence>"}]}  -- or {"signals":[]} if nothing qualifies.'
    )
    try:
        r=httpx.post("https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization":f"Bearer {key}"},
            json={"model":model,"messages":[{"role":"user","content":prompt}],
                  "temperature":0.1,"max_tokens":400,"response_format":{"type":"json_object"}},timeout=25)
        if r.status_code!=200: log.warning(f"llm {r.status_code}"); return []
        return (json.loads(r.json()["choices"][0]["message"]["content"]).get("signals",[]) or [])[:2]
    except Exception as e: log.warning(f"llm: {e}"); return []

def _quote(tk):
    try:
        import yfinance as yf
        t=yf.Ticker(tk); fi=t.fast_info
        price=float(fi.get("last_price") or fi.get("lastPrice") or 0)
        try: mcap=int(fi.get("market_cap") or fi.get("marketCap") or 0) or None
        except Exception: mcap=None
        if not price:
            h=t.history(period="1d")
            if not h.empty: price=float(h["Close"].iloc[-1])
        return price,mcap
    except Exception: return 0,None

def _pulse_score(tk):
    try:
        from backend.app.db.session import SessionLocal
        from sqlalchemy import text
        db=SessionLocal()
        row=db.execute(text("SELECT score FROM pulse_signal_log WHERE ticker=:t ORDER BY entry_time DESC LIMIT 1"),{"t":tk}).fetchone()
        db.close()
        return float(row.score) if row and row.score is not None else None
    except Exception: return None

def _push(m):
    tok=os.getenv("TELEGRAM_BOT_TOKEN","").strip(); ch=os.getenv("TELEGRAM_CHAT_ID","").strip()
    if not tok: return
    def _send(cid):
        try:
            httpx.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                json={"chat_id":cid,"text":m,"parse_mode":"Markdown","disable_web_page_preview":True},timeout=8)
        except Exception: pass
    done=set()
    if ch:
        _send(ch); done.add(str(ch))
    try:
        from backend.app.services import auth_service as _auth
        recips=_auth.verified_recipients()
        for rc in (recips or []):
            cid=rc.get("tg_chat_id") if isinstance(rc,dict) else rc
            if cid is None or str(cid) in done: continue
            _send(cid); done.add(str(cid))
    except Exception:
        try:
            from backend.app.services import auth_service as _auth2
            _auth2.broadcast(m)
        except Exception: pass


def _emit(fk,fig,sig,headline,url):
    tk=(sig.get("ticker") or "").upper().strip()
    if not tk.isalpha() or len(tk)>5: return False
    try: conf=float(sig.get("confidence",0))
    except Exception: conf=0
    if conf<float(os.getenv("ORACLE_MIN_CONF","0.55")): return False
    if _rc is not None:
        try:
            if _rc.exists(f"oracle:cd:{fk}:{tk}"): return False
        except Exception: pass
    price,mcap=_quote(tk)
    if price<=0: return False
    pulse=_pulse_score(tk); size=float(os.getenv("ORACLE_SIZE_USD","200"))
    try:
        from backend.app.db.session import SessionLocal
        from sqlalchemy import text
        db=SessionLocal()
        _cd=int(os.getenv("ORACLE_CD_SEC","21600"))
        if db.execute(text("SELECT 1 FROM oracle_signals WHERE figure=:f AND ticker=:t AND sentiment=:s AND detected_at > now() - make_interval(secs=>:cd) LIMIT 1"),{"f":fk,"t":tk,"s":sig.get("sentiment"),"cd":_cd}).fetchone():
            db.close(); return False
        db.execute(text("""INSERT INTO oracle_signals(figure,figure_name,source_url,headline,ticker,
            sentiment,confidence,rationale,price,market_cap,suggested_size,pulse_score,status)
            VALUES(:f,:fn,:u,:h,:t,:s,:c,:r,:p,:mc,:sz,:ps,'new')"""),
            {"f":fk,"fn":fig["name"],"u":url,"h":headline[:500],"t":tk,"s":sig.get("sentiment"),
             "c":conf,"r":(sig.get("rationale","") or "")[:300],"p":price,"mc":mcap,"sz":size,"ps":pulse})
        db.commit(); db.close()
    except Exception as e: log.warning(f"db: {e}")
    bull=sig.get("sentiment")=="bullish"; mc=f"${mcap/1e9:.1f}B" if mcap else "—"
    ps=f"{pulse:+.2f}" if pulse is not None else "—"
    _push(f"🔮 *ORACLE · {fig['name']}* {fig['emoji']}\n\n{'🟢↑ BULLISH' if bull else '🔴↓ BEARISH'}  "
          f"`{tk}` @ ${price:.2f} ({mc})\nConf *{conf:.0%}* · Pulse {ps} · ${size:.0f}\n\n"
          f"_{headline[:160]}_\n_Why:_ {(sig.get('rationale','') or '')[:140]}\n\n[source]({url})")
    if os.getenv("ORACLE_AUTOTRADE","0").lower() in ("1","true","yes") and bull and conf>=float(os.getenv("ORACLE_MIN_CONF_TRADE","0.7")):
        try:
            from backend.app.services.broker_service import place_signal_order
            place_signal_order({"ticker":tk,"side":"LONG","price":price,"suggested_size":size})
        except Exception: log.exception("broker")
    if _rc is not None:
        try: _rc.setex(f"oracle:cd:{fk}:{tk}",int(os.getenv("ORACLE_CD_SEC","21600")),"1")
        except Exception: pass
    log.info(f"oracle {fk} {tk} {sig.get('sentiment')} {conf}")
    return True

def scan_once():
    new=0
    for fk in _enabled():
        fig=FIGURES.get(fk)
        if not fig: continue
        for item in _gather(fk,fig):
            uid=item.get("uid") or item.get("url") or item.get("headline","")
            if _seen(fk,uid): continue
            k=item.get("kind")
            if k=="trade":
                if _emit(fk,fig,{"ticker":item["ticker"],"sentiment":item["sentiment"],
                    "confidence":item.get("conf",0.75),"rationale":item.get("rationale","")},
                    item["headline"],item.get("url","")): new+=1
            elif k=="filing":
                _push(f"🔮 *ORACLE · {fig['name']}* {fig['emoji']}\n\n📄 {item['headline']}\n[filing]({item['url']})")
            else:
                for sig in _llm_analyze(fig["name"],item["headline"],item.get("body","")):
                    if _emit(fk,fig,sig,item["headline"],item.get("url","")): new+=1
            time.sleep(0.2)
    return new

# ── Nitter (free X mirror via xcancel) ──
NITTER_INSTANCES = [x.strip().rstrip("/") for x in os.getenv("NITTER_INSTANCES",
    "https://xcancel.com,https://nitter.poast.org,https://nitter.privacydev.net").split(",") if x.strip()]
NITTER_UA = os.getenv("NITTER_UA",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

def _tweet_id(url):
    m = re.search(r"/status/(\d+)", url or "")
    return m.group(1) if m else None

def src_nitter(handle):
    if not handle or handle.startswith("<"): return []
    if not _due(f"nitter:{handle}", int(os.getenv("NITTER_POLL_SEC","300"))): return []
    for base in NITTER_INSTANCES:
        try:
            r = httpx.get(f"{base}/{handle}/rss",
                headers={"User-Agent":NITTER_UA,"Accept":"application/rss+xml, application/xml, */*"},
                timeout=15, follow_redirects=True)
            head = r.text[:400].lower()
            if r.status_code != 200 or ("<rss" not in head and "<feed" not in head):
                log.warning(f"nitter {base} {handle}: HTTP {r.status_code}")
                continue
            out=[]
            for x in _parse_rss(r.text, 6):
                tid=_tweet_id(x["url"])
                out.append({"kind":"news","headline":f"@{handle}: {x['title'][:120]}",
                    "body":(x['title']+" "+x['body'])[:500],"url":x["url"],
                    "uid":f"tweet:{tid}" if tid else "nitter:"+(x["url"] or x["title"])})
            if out:
                log.info(f"nitter ok {base} {handle} {len(out)}")
                return out
        except Exception as e:
            log.warning(f"nitter {base} {handle}: {e}")
    return []

# Insert nitter as PRIMARY source for X-based figures (free real posts)
_NITTER_HANDLES = {"trump":"realDonaldTrump","musk":"elonmusk","burry":"michaeljburry",
                   "ackman":"BillAckman","wood":"CathieDWood",
                   "serenity":os.getenv("ORACLE_X_SERENITY","<SERENITY_X>")}
for _fk,_h in _NITTER_HANDLES.items():
    if _fk in FIGURES and not any(s.get("type")=="nitter" for s in FIGURES[_fk]["sources"]):
        FIGURES[_fk]["sources"].insert(0, {"type":"nitter","handle":_h})

# ── Trump via CNN public Truth-Social archive (datacenter-friendly, 5-min fresh) ──
def src_truth_cnn():
    if not _due("trumparchive", int(os.getenv("TRUMP_POLL_SEC","300"))): return []
    try:
        r = httpx.get("https://ix.cnn.io/data/truth-social/truth_archive.json", headers=UA, timeout=20)
        if r.status_code != 200: log.warning(f"trump cnn {r.status_code}"); return []
        out=[]
        for p in r.json()[:12]:
            txt = re.sub("<[^>]+>", "", p.get("content","") or "").strip()
            if not txt: continue
            out.append({"kind":"news","headline":f"Trump (Truth): {txt[:120]}","body":txt[:600],
                        "url":p.get("url",""),"uid":"trump:"+str(p.get("id"))})
        return out
    except Exception as e: log.warning(f"trump cnn: {e}"); return []

# ── Marketaux: entity-tagged news (ticker + sentiment built in, free 100/day) ──
def src_marketaux(name):
    key = os.getenv("MARKETAUX_KEY","").strip()
    if not key or not name: return []
    if not _due(f"mktx:{name}", int(os.getenv("MARKETAUX_POLL_SEC","7200"))): return []
    try:
        r = httpx.get("https://api.marketaux.com/v1/news/all", headers=UA, timeout=20, params={
            "search": f'"{name}"', "filter_entities":"true", "language":"en",
            "limit":3, "api_token":key})
        if r.status_code != 200: log.warning(f"mktx {name} {r.status_code}"); return []
        out=[]
        for art in r.json().get("data", []):
            for ent in art.get("entities", []):
                tk=(ent.get("symbol") or "").upper()
                if not tk.isalpha() or len(tk)>5: continue
                sc=ent.get("sentiment_score")
                if sc is None: continue
                sent = "bullish" if sc>=0.15 else "bearish" if sc<=-0.15 else None
                if not sent: continue
                out.append({"kind":"trade","ticker":tk,"sentiment":sent,
                    "headline":(art.get("title","") or "")[:160],
                    "rationale":f"{name} in news · sentiment {sc:+.2f}",
                    "url":art.get("url",""),"conf":round(min(0.9,0.55+abs(sc)*0.4),2),
                    "uid":f"mktx:{art.get('uuid')}:{tk}"})
        return out
    except Exception as e: log.warning(f"mktx {name}: {e}"); return []

# wire datacenter-friendly sources to the front
for _fk in ("huang","su","musk","ackman","burry","serenity","wood"):
    if _fk in FIGURES and not any(s.get("type")=="marketaux" for s in FIGURES[_fk]["sources"]):
        FIGURES[_fk]["sources"].insert(0, {"type":"marketaux"})
if "trump" in FIGURES and not any(s.get("type")=="trumparchive" for s in FIGURES["trump"]["sources"]):
    FIGURES["trump"]["sources"].insert(0, {"type":"trumparchive"})
