import os, re, json, time, datetime as dt
import httpx, yfinance as yf
from sqlalchemy import text
from backend.app.db.session import SessionLocal

UA = {"User-Agent": "Mozilla/5.0 Signalpha-research"}
GROQ = os.getenv("GROQ_API_KEY", "").strip()
CANDIDATES = [c for c in [os.getenv("ORACLE_MODEL","").strip(), "llama-3.3-70b-versatile",
              "llama-3.1-8b-instant", "openai/gpt-oss-120b"] if c]
_MODEL = {"id": None}
RECENT_DAYS = 150
NEG = re.compile(r'(insider sell|sells? \$?\d|sold \$|reduce[sd]|trim(s|med)?|deregister|10b5-1|'
                 r'files? (for|to)|registration statement|prospectus|dividend declar|transcript|'
                 r'q[1-4] \d{4} earnings call|stake reduction)', re.I)
HINT = re.compile(r'(\$[A-Za-z]{1,5}\b|\b(stock|shares|company|tariff|market|oil|steel|crypto|bitcoin|'
                  r'chip|semiconductor|Nvidia|Apple|Tesla|Boeing|economy|drug|pharma|deal|buy|sell)\b)', re.I)

def _probe(m):
    try:
        r=httpx.post("https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization":f"Bearer {GROQ}"},
            json={"model":m,"messages":[{"role":"user","content":"Return JSON {\"ok\":1}"}],
                  "max_tokens":20,"response_format":{"type":"json_object"}},timeout=20)
        return r.status_code
    except Exception: return 0

def pick_model():
    for m in CANDIDATES:
        if _probe(m)==200: _MODEL["id"]=m; return m
    return None

def llm(name, txt):
    if not GROQ or not _MODEL["id"]: return None
    prompt=(f'Article about {name}: "{txt[:480]}"\n'
            f'Does it describe {name} EXPRESSING a bullish/bearish VIEW on a stock, praising or criticizing a '
            f'company, or making a notable CONVICTION bet/purchase? If yes, give the ONE US-listed ticker and tone. '
            f'If it is a routine insider share sale, an administrative/regulatory filing, fund (de)registration, '
            f'a stake trim for liquidity, an earnings-call transcript, or only tangential -> {{"ticker":null}}. '
            f'STRICT JSON {{"ticker":"SYM","sentiment":"bullish"|"bearish"}} or {{"ticker":null}}.')
    try:
        r=httpx.post("https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization":f"Bearer {GROQ}"},
            json={"model":_MODEL["id"],"messages":[{"role":"user","content":prompt}],
                  "temperature":0.1,"max_tokens":60,"response_format":{"type":"json_object"}},timeout=20)
        if r.status_code!=200: return None
        j=json.loads(r.json()["choices"][0]["message"]["content"])
        tk=(j.get("ticker") or "").upper().strip()
        if re.match(r'^[A-Z]{1,5}$', tk): return (tk, j.get("sentiment","bullish"))
    except Exception: pass
    return None

def price_on(tk, day):
    try:
        h=yf.download(tk,start=day-dt.timedelta(days=8),end=day+dt.timedelta(days=8),progress=False,auto_adjust=True)
        if h is None or h.empty: return None,None,None
        entry=float(h["Close"].values.flatten()[0])
        t=yf.Ticker(tk); cur=0.0; mc=None
        try:
            fi=t.fast_info; cur=float(fi.get("last_price") or 0); mc=int(fi.get("market_cap") or 0) or None
        except Exception: pass
        if not cur: cur=float(t.history(period="1d")["Close"].values.flatten()[-1])
        return entry,cur,mc
    except Exception: return None,None,None

def mktx(q, n=3):
    key=os.getenv("MARKETAUX_KEY","").strip()
    if not key: return []
    after=(dt.date.today()-dt.timedelta(days=RECENT_DAYS)).isoformat()
    try:
        r=httpx.get("https://api.marketaux.com/v1/news/all",headers=UA,timeout=20,
            params={"search":q,"language":"en","limit":n,"published_after":after,"api_token":key})
        if r.status_code!=200: return []
        arts=sorted(r.json().get("data",[]),key=lambda a:a.get("published_at",""),reverse=True)
        return [((a.get("title","") or "")+" — "+((a.get("snippet","") or "")[:200]),
                 a.get("url",""),(a.get("published_at","") or "")[:10]) for a in arts]
    except Exception: return []

def dnews(q, n=5):
    for mod in ("ddgs","duckduckgo_search"):
        try:
            m=__import__(mod,fromlist=["DDGS"])
            with m.DDGS() as d: res=list(d.news(q,max_results=n))
            return [((x.get("title","") or "")+" — "+((x.get("body","") or "")[:200]),
                     x.get("url",""),(x.get("date","") or "")[:10]) for x in res]
        except Exception: continue
    return []

def trump_cnn():
    try:
        posts=httpx.get("https://ix.cnn.io/data/truth-social/truth_archive.json",headers=UA,timeout=25).json()
        for p in posts[:120]:
            txt=re.sub("<[^>]+>","",p.get("content","") or "")
            if len(txt)<25 or not HINT.search(txt): continue
            res=llm("Donald Trump",txt)
            if not res: continue
            _d=(p.get("created_at") or "")[:10]
            try: _vd=dt.date.fromisoformat(_d) if len(_d)==10 else dt.date.today()
            except Exception: _vd=dt.date.today()
            if not price_on(res[0],_vd)[0]: continue
            return (f"Trump (Truth): {txt[:130]}",p.get("url",""),_d,res)
        return None
    except Exception: return None

print("=== model ===", pick_model(), " marketaux Nvidia:", len(mktx("Nvidia",2)))
FIG=[
 ("trump","Donald Trump","Trump tariffs company","Donald Trump stock company"),
 ("huang","Jensen Huang","Jensen Huang stock","Jensen Huang Marvell Nvidia comment"),
 ("su","Lisa Su","Lisa Su AMD","Lisa Su AMD outlook stock"),
 ("musk","Elon Musk","Elon Musk stock","Elon Musk stock comment"),
 ("ackman","Bill Ackman","Bill Ackman buys","Bill Ackman new stake stock"),
 ("burry","Michael Burry","Michael Burry bet","Michael Burry bought stock"),
 ("serenity","Serenity","aleabitoreddit stock","Serenity aleabitoreddit stock call"),
 ("pelosi","Nancy Pelosi","Nancy Pelosi bought","Nancy Pelosi stock trade"),
 ("buffett","Warren Buffett","Warren Buffett bought","Warren Buffett Berkshire bought stock"),
 ("wood","Cathie Wood","Cathie Wood ARK bought","Cathie Wood ARK bought stock"),
]
SIGS=[]
for fk,fn,mq,dq in FIG:
    hit=None
    if fk=="trump":
        tc=trump_cnn()
        if tc:
            title,url,d,res=tc; hit=(fk,fn,res[0],res[1],d,title[:140],url)
    if not hit:
        _seen=set(); arts=[]
        for a in mktx(mq,3)+dnews(dq,5):
            if a[1] and a[1] in _seen: continue
            _seen.add(a[1]); arts.append(a)
        arts.sort(key=lambda x:(x[2] or ""), reverse=True)
        for title,url,d in arts:
            if len(title)<12 or NEG.search(title): continue
            res=llm(fn,title)
            if not res: continue
            try: _vd=dt.date.fromisoformat(d) if d and len(d)==10 else dt.date.today()
            except Exception: _vd=dt.date.today()
            if not price_on(res[0],_vd)[0]: continue
            hit=(fk,fn,res[0],res[1],d,title[:140],url); break
        time.sleep(0.4)
    print(f"{fk:9s} {('HIT '+hit[2]+' @'+hit[4]) if hit else 'miss'}")
    if hit: SIGS.append(hit)

db=SessionLocal()
db.execute(text("DELETE FROM oracle_signals WHERE status='historical'")); db.commit()
n=0
for fk,fn,tk,se,d,head,url in SIGS:
    try: day=dt.date.fromisoformat(d) if d and len(d)==10 else dt.date.today()
    except Exception: day=dt.date.today()
    entry,cur,mc=price_on(tk,day)
    if not entry or not cur: print("  noprice",fk,tk); continue
    ret=(cur-entry)/entry*100
    rat=f"entry ${entry:.2f} ({day.isoformat()}) -> ${cur:.2f} · {ret:+.1f}% since"
    db.execute(text("""INSERT INTO oracle_signals(figure,figure_name,source_url,headline,ticker,
        sentiment,confidence,rationale,price,market_cap,suggested_size,pulse_score,status,detected_at)
        VALUES(:f,:fn,:u,:h,:t,:s,0.72,:r,:p,:mc,200,NULL,'historical',:dt)"""),
        {"f":fk,"fn":fn,"u":url,"h":head,"t":tk,"s":se,"r":rat,"p":entry,"mc":mc,
         "dt":dt.datetime.combine(day,dt.time(14,0))})
    n+=1; print(f"  {fk:9s} {tk:6s} {day} {ret:+6.1f}%")
db.commit(); db.close()
print("INSERTED",n,"(recent <=150d, filtered)")
