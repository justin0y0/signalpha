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

from backend.app.services.oracle_figures import FIGURES, LEGACY

def _enabled():
    """Figures the scanner polls. Stored as the switched-OFF set: storing the ON set
    (as before 2026-10-29) left every figure added later silently disabled."""
    if _rc is None: return set(FIGURES)
    try:
        off=_rc.get("oracle:disabled")
        if off is None:
            on=_rc.get("oracle:enabled")
            off=json.dumps(sorted(LEGACY-set(json.loads(on)))) if on else "[]"
            _rc.set("oracle:disabled",off)
        return set(FIGURES)-set(json.loads(off))
    except Exception: return set(FIGURES)
def set_enabled(keys):
    if _rc is None: return
    try: _rc.set("oracle:disabled", json.dumps(sorted(set(FIGURES)-set(keys))))
    except Exception: pass
def _seen_key(fk, uid):
    return "oracle:seen:"+hashlib.md5((fk+"|"+str(uid)).encode()).hexdigest()
def _is_seen(fk, uid):
    if _rc is None or not uid: return False
    try: return bool(_rc.exists(_seen_key(fk,uid)))
    except Exception: return False
def _mark_seen(fk, uid):
    # Marked only AFTER an item was actually processed. Marking on first sight meant
    # that while the LLM was returning 404 (2026-10), every item was consumed unread
    # and skipped for the next 7 days, so fixing the model recovered nothing.
    # 30 days: with 7, the same Serenity article was re-read and re-emitted every week.
    if _rc is None or not uid: return
    try: _rc.setex(_seen_key(fk,uid),2592000,"1")
    except Exception: pass
def _due(stype, ttl):
    if _rc is None: return True
    k=f"oracle:srcrun:{stype}"
    try:
        if _rc.exists(k): return False
        _rc.setex(k,ttl,"1"); return True
    except Exception: return True

def _ts(raw):
    """Feed timestamp → epoch seconds (None when absent or unparseable)."""
    if not raw: return None
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(raw).timestamp()
    except Exception: pass
    try:
        import datetime as _dt
        return _dt.datetime.fromisoformat(raw.replace("Z","+00:00")).timestamp()
    except Exception: return None

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
            if not desc:
                md=it.find(".//{http://search.yahoo.com/mrss/}description")
                desc=(md.text or "") if md is not None else ""
            if title: out.append({"title":title,"body":re.sub("<[^>]+>","",desc)[:500],"url":link,
                                  "ts":_ts(g("pubDate") or g("published") or g("updated"))})
    except Exception: pass
    return out

def _fetch_news(query,n=3):
    for mod in ("ddgs","duckduckgo_search"):
        try:
            m=__import__(mod,fromlist=["DDGS"])
            with m.DDGS() as d: return list(d.news(query,max_results=n))
        except Exception: continue
    return []

def src_gnews(query, hl="en-US"):
    gl,ceid=("CN","CN:zh-Hans") if hl=="zh-CN" else ("US","US:en")
    try:
        r=httpx.get(f"https://news.google.com/rss/search?q={quote(query)}+when:3d&hl={hl}&gl={gl}&ceid={ceid}",
                    headers=UA,timeout=15,follow_redirects=True)
        if r.status_code!=200: return []
        return [{"kind":"news","headline":x["title"],"body":x["body"],"url":x["url"],"uid":x["url"] or x["title"],"ts":x["ts"]}
                for x in _parse_rss(r.text,5)]
    except Exception as e: log.warning(f"gnews: {e}"); return []

def src_rss(url):
    if not url or url.startswith("<"): return []
    try:
        r=httpx.get(url,headers=UA,timeout=15,follow_redirects=True)
        if r.status_code!=200: return []
        _mark_ok("rss")
        return [{"kind":"news","headline":x["title"],"body":x["body"],"url":x["url"],"uid":x["url"] or x["title"],"ts":x["ts"]}
                for x in _parse_rss(r.text,6)]
    except Exception as e: log.warning(f"rss: {e}"); return []

def src_youtube(channel):
    """A channel's uploads feed — titles and descriptions of the latest videos."""
    if not channel or not _due(f"yt:{channel}",1800): return []
    try:
        r=httpx.get(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel}",headers=UA,timeout=15)
        if r.status_code!=200:
            # the public feed 404s for hours at a time (2026-10-29, from everywhere);
            # the Data API is the fallback when a key is set (1 quota unit per call)
            key=os.getenv("YOUTUBE_API_KEY","").strip()
            if not key: log.warning(f"youtube {channel} {r.status_code}"); return []
            j=httpx.get("https://www.googleapis.com/youtube/v3/playlistItems",timeout=15,params={
                "part":"snippet","playlistId":"UU"+channel[2:],"maxResults":6,"key":key}).json()
            _mark_ok("youtube")
            return [{"kind":"news","headline":"Video: "+it["snippet"]["title"],"body":it["snippet"].get("description","")[:500],
                     "url":"https://www.youtube.com/watch?v="+it["snippet"]["resourceId"]["videoId"],
                     "uid":"yt:https://www.youtube.com/watch?v="+it["snippet"]["resourceId"]["videoId"],
                     "ts":_ts(it["snippet"].get("publishedAt"))} for it in j.get("items",[])]
        _mark_ok("youtube")
        return [{"kind":"news","headline":"Video: "+x["title"],"body":x["body"],"url":x["url"],
                 "uid":"yt:"+(x["url"] or x["title"]),"ts":x["ts"]} for x in _parse_rss(r.text,6)]
    except Exception as e: log.warning(f"youtube {channel}: {e}"); return []

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
    # Was stubbed to `return []` in the 2026-07 snapshot with no note, which silently
    # made Cathie Wood a news-only figure. ARK's daily trade file is the most direct
    # primary source on the page, so it is back — limited to the latest trade date and to
    # positions of at least ORACLE_ARK_MIN_PCT of the fund, because the full file is
    # mostly rebalancing dust and a dozen pings a day would bury the rest of the feed.
    if not _due("ark",3600): return []
    try:
        r=httpx.get("https://arkfunds.io/api/v2/etf/trades",params={"symbol":"ARKK","limit":40},headers=UA,timeout=15)
        if r.status_code!=200: return []
        _mark_ok("ark")
        trades=r.json().get("trades",[]) or []
        if not trades: return []
        latest=max(t.get("date","") for t in trades)
        min_pct=float(os.getenv("ORACLE_ARK_MIN_PCT","0.10"))
        big=[t for t in trades if t.get("date")==latest and float(t.get("etf_percent") or 0)>=min_pct]
        big.sort(key=lambda t:-float(t.get("etf_percent") or 0))
        out=[]
        for t in big[:3]:
            tk=(t.get("ticker") or "").upper().strip()
            if not tk.isalpha() or len(tk)>5: continue
            d=(t.get("direction") or "").lower()
            out.append({"kind":"trade","ticker":tk,"sentiment":"bullish" if "buy" in d else "bearish",
                "headline":f"ARK {t.get('direction','')} {tk} — {int(t.get('shares') or 0):,} sh, {float(t.get('etf_percent') or 0):.2f}% of ARKK ({latest})",
                "rationale":f"Cathie Wood's ARKK disclosed a {d} of {t.get('company') or tk} on {latest}, {float(t.get('etf_percent') or 0):.2f}% of the fund.",
                "url":"https://ark-funds.com/funds/arkk/",
                "conf":0.75,"uid":f"ark:{t.get('date')}:{tk}:{d}"})
        return out
    except Exception as e: log.warning(f"ark: {e}"); return []

# "... (NVDA) [OP]  P 07/24/2026 08/06/2026 $1,000,001 - $5,000,000" — ticker, asset type,
# P/S, trade date, notification date, amount bracket (the bracket can wrap a line)
_PTR_ROW = re.compile(r"\(([A-Z][A-Z.]{0,5})\)\s*\[(ST|OP)\]\s*(P|S(?:\s*\(partial\))?)\s+(\d{2}/\d{2}/\d{4})"
                      r"(?:\s*\d{2}/\d{2}/\d{4})?\s*(\$[\d,]+(?:\s*-\s*\$[\d,]+)?|Over \$[\d,]+)?")
_house: dict = {"at":0.0,"rows":[]}

def _house_index():
    """Every PTR in the House Clerk's yearly indexes (this year, plus last year in Jan–Feb),
    downloaded at most hourly and shared by all members."""
    import io, zipfile, datetime as _dt
    if time.time()-_house["at"] < 3600 and _house["rows"]: return _house["rows"]
    today=_dt.date.today(); rows=[]
    for y in ([today.year-1] if today.month<=2 else [])+[today.year]:
        r=httpx.get(f"https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{y}FD.zip",headers=UA,timeout=60)
        if r.status_code!=200: log.warning(f"congress index {y} {r.status_code}"); continue
        z=zipfile.ZipFile(io.BytesIO(r.content))
        for m in ET.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".xml")))):
            row={c.tag:(c.text or "").strip() for c in m}
            if row.get("FilingType")!="P": continue
            try: row["filed"]=_dt.datetime.strptime(row.get("FilingDate",""),"%m/%d/%Y").date()
            except ValueError: continue
            rows.append(row)
    if rows: _house.update(at=time.time(),rows=rows)
    return _house["rows"]

def _ptr_rows(doc, year):
    """(ticker, kind, P/S, trade date, amount text) rows of one PTR PDF; cached for good,
    since a filed report never changes. Scanned paper filings have no text and give []."""
    k=f"oracle:ptr:{doc}"
    if _rc is not None:
        try:
            hit=_rc.get(k)
            if hit is not None: return [tuple(x) for x in json.loads(hit)]
        except Exception: pass
    import io
    from pypdf import PdfReader
    pr=httpx.get(f"https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{year}/{doc}.pdf",headers=UA,timeout=30)
    if pr.status_code!=200: return []
    txt="\n".join(pg.extract_text() or "" for pg in PdfReader(io.BytesIO(pr.content)).pages)
    rows=[list(x) for x in _PTR_ROW.findall(txt)]
    if _rc is not None:
        try: _rc.setex(k,86400*120,json.dumps(rows))
        except Exception: pass
    return [tuple(x) for x in rows]

def _amount_top(txt):
    nums=[int(n.replace(",","")) for n in re.findall(r"\$([\d,]+)",txt or "")]
    return max(nums) if nums else 0

def src_congress(name, first=""):
    """Periodic Transaction Reports straight from the House Clerk.

    The old feed (house-stock-watcher's S3 dump) returned 403, so Pelosi had been dark
    with nothing in the logs. PTRs are FilingType "P" in the Clerk's free yearly index;
    each links a PDF. Filings from the last ORACLE_CONGRESS_DAYS (90) are read — on a
    first run those are emitted quietly, priced at the filing day's close. The amount
    bracket goes into the headline; ORACLE_CONGRESS_MIN_USD can drop the small ones.
    """
    if not _due(f"congress:{name}",3600): return []
    try:
        import datetime as _dt
        rows=_house_index()
        _mark_ok("congress")
        cutoff=_dt.date.today()-_dt.timedelta(days=int(os.getenv("ORACLE_CONGRESS_DAYS","90")))
        floor=int(os.getenv("ORACLE_CONGRESS_MIN_USD","0"))
        out=[]
        for row in rows:
            if row.get("Last","").lower()!=name.lower() or row["filed"]<cutoff: continue
            if first and not row.get("First","").lower().startswith(first.lower()): continue
            doc=row.get("DocID",""); filed=row["filed"]
            pdf_url=f"https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{filed.year}/{doc}.pdf"
            seen=set()
            for tk,kind,typ,tdate,amt in _ptr_rows(doc, filed.year):
                tk=tk.replace(".","-"); side="buy" if typ.startswith("P") else "sell"
                top=_amount_top(amt)
                if (tk,side) in seen or (top and top<floor): continue
                seen.add((tk,side))
                what="call options" if kind=="OP" else "shares"
                size=f" ({' '.join(amt.split())})" if amt else ""
                out.append({"kind":"trade","ticker":tk,"sentiment":"bullish" if side=="buy" else "bearish",
                    "headline":f"{name} disclosed a {side} of {tk} {what}{size} — traded {tdate}, filed {filed:%m/%d/%Y}",
                    "rationale":f"Periodic Transaction Report {doc}: {name} {'bought' if side=='buy' else 'sold'} {tk} {what} on {tdate}{size}.",
                    "url":pdf_url,"conf":0.7,"uid":f"cong:{doc}:{tk}:{side}",
                    "at":_et_ts(filed,16)})
        return out
    except Exception as e: log.warning(f"congress {name}: {e}"); return []

def _et_ts(d, hour):
    """Epoch seconds of `hour`:00 New York time on date d."""
    import datetime as _dt
    from zoneinfo import ZoneInfo
    return _dt.datetime(d.year,d.month,d.day,hour,0,tzinfo=ZoneInfo("America/New_York")).timestamp()

def _13f_table(cik, acc):
    """{(cusip, PUT|CALL|''): {"name","value","shares"}} of one 13F-HR, cached for good."""
    k=f"oracle:13f:{acc}"
    if _rc is not None:
        try:
            hit=_rc.get(k)
            if hit: return {tuple(x[0]):x[1] for x in json.loads(hit)}
        except Exception: pass
    base=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-','')}"
    idx=httpx.get(f"{base}/index.json",headers=UA,timeout=20).json()
    names=[i["name"] for i in idx.get("directory",{}).get("item",[]) if i["name"].lower().endswith(".xml")
           and i["name"].lower()!="primary_doc.xml"]
    if not names: return {}
    root=ET.fromstring(httpx.get(f"{base}/{names[0]}",headers=UA,timeout=30).content)
    loc=lambda e:e.tag.rsplit("}",1)[-1]
    out={}
    for it in root.iter():
        if loc(it)!="infoTable": continue
        f={loc(c):(c.text or "").strip() for c in it.iter()}
        key=(f.get("cusip","").upper(),f.get("putCall","").upper())
        v=out.setdefault(key,{"name":f.get("nameOfIssuer",""),"value":0.0,"shares":0.0})
        try: v["value"]+=float(f.get("value") or 0); v["shares"]+=float(f.get("sshPrnamt") or 0)
        except ValueError: pass
    if _rc is not None and out:
        try: _rc.setex(k,86400*400,json.dumps([[list(a),b] for a,b in out.items()]))
        except Exception: pass
    return out

def _cusip_tickers(cusips):
    """CUSIP → US ticker through OpenFIGI (free, 25 requests a minute without a key);
    answers, including "no ticker", are cached for months."""
    out,need={},[]
    for c in cusips:
        hit=_rc.get(f"oracle:cusip:{c}") if _rc is not None else None
        if hit is not None: out[c]=hit or None
        else: need.append(c)
    hdr={"Content-Type":"application/json"}
    if os.getenv("OPENFIGI_KEY","").strip(): hdr["X-OPENFIGI-APIKEY"]=os.getenv("OPENFIGI_KEY").strip()
    for i in range(0,len(need),10):
        chunk=need[i:i+10]
        try:
            r=httpx.post("https://api.openfigi.com/v3/mapping",headers=hdr,timeout=20,
                         json=[{"idType":"ID_CUSIP","idValue":c,"exchCode":"US"} for c in chunk])
            if r.status_code!=200: log.warning(f"openfigi {r.status_code}"); break
            for c,res in zip(chunk,r.json()):
                d=(res.get("data") or [{}])[0]
                tk=(d.get("ticker") or "").replace("/","-").upper()
                out[c]=tk or None
                if _rc is not None: _rc.setex(f"oracle:cusip:{c}",86400*(180 if tk else 30),tk)
        except Exception as e: log.warning(f"openfigi: {e}"); break
        if i+10<len(need): time.sleep(2.6)
    return out

def src_f13(cik, fund, who):
    """What changed between a manager's last two 13F-HR filings.

    Positions as of quarter end, filed up to 45 days later — a slow signal, but the
    trades are real. Reported: new positions, exits, and holdings at least doubled or
    halved, each worth ≥ ORACLE_13F_MIN_W (1%) of the portfolio, largest first, at most
    four per filing. A put is read as bearish. Only a filing from the last
    ORACLE_13F_DAYS (100) counts; on first sight it is emitted quietly, priced at the
    close of the day it became public.
    """
    ciks=[int(c) for c in (cik if isinstance(cik,(list,tuple)) else [cik])]
    if not _due(f"f13:{ciks[0]}",6*3600): return []
    try:
        import datetime as _dt
        from backend.app.services.schedule_service import _cik as _sec_listed
        fl=[]
        for c in ciks:   # a manager that moved filer entity (Pershing Square, 2026) spans several
            r=httpx.get(f"https://data.sec.gov/submissions/CIK{c:010d}.json",headers=UA,timeout=20)
            if r.status_code!=200: continue
            rec=r.json().get("filings",{}).get("recent",{})
            fl+=[(rec["accessionNumber"][i],rec["filingDate"][i],rec["reportDate"][i],rec["acceptanceDateTime"][i],c)
                 for i,f in enumerate(rec.get("form",[])) if f=="13F-HR"]
        fl.sort(key=lambda x:x[1],reverse=True)
        _mark_ok("f13")
        periods=list(dict.fromkeys(x[2] for x in fl))
        if len(periods)<2: return []
        acc,filed,period,accepted,cik=fl[0]
        if (_dt.date.today()-_dt.date.fromisoformat(filed)).days>int(os.getenv("ORACLE_13F_DAYS","100")): return []
        def merged(pd_):
            # one quarter can be split across entities: Pershing's Q1 2026 was HHH on the
            # new filer and everything else on the old one
            t={}
            for a,_,p_,_,c in fl:
                if p_!=pd_: continue
                for k,v in _13f_table(c,a).items():
                    x=t.setdefault(k,{"name":v["name"],"value":0.0,"shares":0.0})
                    x["value"]+=v["value"]; x["shares"]+=v["shares"]
            return t
        cur,old=merged(period),merged(periods[1])
        tc,tp=sum(v["value"] for v in cur.values()) or 1,sum(v["value"] for v in old.values()) or 1
        mw=float(os.getenv("ORACLE_13F_MIN_W","0.01"))
        moves=[]
        for key in set(cur)|set(old):
            c,p=cur.get(key),old.get(key); opt=key[1]
            if c and not p: act,w="new",c["value"]/tc
            elif p and not c: act,w="exit",p["value"]/tp
            else:
                ratio=c["shares"]/p["shares"] if p["shares"] else 1
                if ratio>=2: act="add"
                elif ratio<=0.5: act="cut"
                else: continue
                w=c["value"]/tc
            if w<mw or (opt=="PUT" and act in ("exit","cut")): continue
            up=act in ("new","add")
            moves.append((w,key,act,(not up) if opt!="PUT" else up,(c or p)["name"]))
        moves.sort(key=lambda m:-m[0])
        moves=moves[:8]
        tick=_cusip_tickers([m[1][0] for m in moves])
        q=_dt.date.fromisoformat(period); qn=f"Q{(q.month-1)//3+1} {q.year}"
        verb={"new":"opened a new position in","exit":"sold out of","add":"more than doubled","cut":"cut by half or more"}
        url=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-','')}/"
        at=_dt.datetime.fromisoformat(accepted.replace("Z","+00:00")).timestamp()
        out=[]
        for w,key,act,bear,name in moves:
            tk=tick.get(key[0])
            # SEC-registered listings only: OpenFIGI also maps foreign lines to OTC symbols
            if not tk or not tk.replace("-","").isalpha() or len(tk)>6 or not _sec_listed(tk): continue
            what=f" {tk} puts" if key[1]=="PUT" else f" {tk} calls" if key[1]=="CALL" else f" {tk}"
            out.append({"kind":"trade","ticker":tk,"sentiment":"bearish" if bear else "bullish",
                "headline":f"{fund} {verb[act]}{what} — {w:.1%} of the portfolio ({qn} 13F, filed {filed})",
                "rationale":f"{who}'s {fund} 13F for {qn} shows it {verb[act]} {name.title()}{' (puts)' if key[1]=='PUT' else ''}, "
                            f"{w:.1%} of reported holdings. 13F positions are as of quarter end.",
                "url":url,"conf":0.7,"uid":f"13f:{acc}:{tk}:{act}{key[1]}","at":at})
            if len(out)>=4: break
        return out
    except Exception as e: log.warning(f"f13 {cik}: {e}"); return []

def src_edgar(cik,name):
    if not _due(f"edgar:{cik}",3600): return []
    try:
        r=httpx.get(f"https://data.sec.gov/submissions/CIK{str(cik).zfill(10)}.json",headers=UA,timeout=15)
        if r.status_code!=200: return []
        _mark_ok(f"edgar:{cik}")
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

PRIMARY_SOURCES={"truth","trumparchive","x","nitter","ark","congress","edgar","rss","f13","youtube"}

def _note_source(fk, st, n):
    """Remember when each (figure, source) was last confirmed working.

    The page used to badge every figure LIVE regardless of whether anything reached
    us — X/nitter has been unreachable from this server for months, so 'LIVE' on Musk
    meant 'enabled', not 'working'. figure_health() reads this instead.

    "Working" is either: the source delivered items, or a primary source answered
    successfully with nothing new (see _mark_ok). Counting deliveries alone badged
    Pelosi and Buffett "news only" between filings while their primary feeds were
    being polled fine — quiet is not broken."""
    if _rc is None or not n: return
    try: _rc.hset(f"oracle:health:{fk}", st, str(int(time.time())))
    except Exception: pass

_OK_NOW: set = set()

def _mark_ok(key):
    """Called by a primary source right after a successful fetch; _gather turns it
    into a health mark for the figure that asked."""
    _OK_NOW.add(key)

def figure_health(fk):
    fig=FIGURES.get(fk,{})
    try: seen=_rc.hgetall(f"oracle:health:{fk}") if _rc is not None else {}
    except Exception: seen={}
    now=time.time(); fresh={st for st,ts in (seen or {}).items() if now-float(ts) < 48*3600}
    primary=sorted(fresh & PRIMARY_SOURCES); news=sorted(fresh - PRIMARY_SOURCES)
    status="live" if primary else "news_only" if news else "quiet"
    configured=sorted({s.get("type") for s in fig.get("sources",[])})
    return {"status":status,"active_sources":primary+news,"configured_sources":configured,
            "last_seen":{st:int(float(ts)) for st,ts in (seen or {}).items()}}

def _gather(fk,fig):
    items=[]
    for src in fig.get("sources",[]):
        st=src.get("type")
        before=len(items)
        _OK_NOW.clear()
        try:
            if st=="news":
                for q in src.get("queries",[]):
                    for it in _fetch_news(q,3):
                        items.append({"kind":"news","headline":it.get("title",""),
                            "body":it.get("body","") or it.get("excerpt",""),
                            "url":it.get("url") or it.get("link",""),"uid":it.get("url") or it.get("title","")})
            elif st=="gnews":
                for q in src.get("queries",[]): items+=src_gnews(q,src.get("hl","en-US"))
            elif st=="rss":
                items+=src_rss(os.getenv(src.get("url_env",""),"") if src.get("url_env") else src.get("url",""))
            elif st=="x": items+=src_x(src.get("handle",""))
            elif st=="nitter": items+=src_nitter(src.get("handle",""))
            elif st=="truth": items+=src_truth(src.get("handle",""))
            elif st=="trumparchive": items+=src_truth_cnn()
            elif st=="marketaux": items+=src_marketaux(fig["name"])
            elif st=="ark": items+=src_ark()
            elif st=="congress": items+=src_congress(src.get("name",""),src.get("first",""))
            elif st=="edgar": items+=src_edgar(src.get("cik",""),fig["name"])
            elif st=="f13": items+=src_f13(src.get("cik"),src.get("fund",""),fig["name"])
            elif st=="youtube": items+=src_youtube(src.get("channel",""))
        except Exception as e: log.warning(f"gather {st} {fk}: {e}")
        _note_source(fk, st, max(len(items)-before, 1 if _OK_NOW else 0))
    # News older than ORACLE_NEWS_MAX_AGE_H is not a signal any more: priced at today's
    # quote it would be logged as fresh (Buffett's Lennar buy was logged twice that way).
    old=time.time()-3600*float(os.getenv("ORACLE_NEWS_MAX_AGE_H","72"))
    return [it for it in items if _domain_ok(it.get("url",""))
            and not (it.get("kind")=="news" and it.get("ts") and it["ts"]<old)]

def _llm_analyze(fn,headline,body):
    key=os.getenv("GROQ_API_KEY","").strip()
    if not key: return None
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
    # Model resolved live: a hardcoded name went 404 when Groq retired it and this
    # function returned [] for every item for days. See services/groq_models.py.
    from backend.app.services.groq_models import chat
    try:
        content=chat([{"role":"user","content":prompt}],preferred_env="ORACLE_MODEL",
                     json_mode=True,temperature=0.1,max_tokens=400,timeout=30)
        if not content: return None
        return (json.loads(content).get("signals",[]) or [])[:2]
    except Exception as e: log.warning(f"llm: {e}"); return None

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
    # Subscribers get these only on request: following them has not paid so far
    # (data_pipeline/research_misc.py — five-session excess vs SPY negative), so they are
    # news for the owner's chat, not trade alerts for everyone.
    if os.getenv("ORACLE_PUSH_USERS","0")!="1": return
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


def _close_on(tk, ts):
    """Close of the first session on/after epoch ts — the price a follower could get."""
    try:
        import yfinance as yf, datetime as _dt
        d=_dt.datetime.utcfromtimestamp(ts).date()
        h=yf.Ticker(tk).history(start=d.isoformat(),end=(d+_dt.timedelta(days=7)).isoformat(),auto_adjust=False)
        return float(h["Close"].iloc[0]) if not h.empty else 0
    except Exception: return 0

_GENERIC={"inc","corp","corporation","co","company","holdings","holding","group","ltd","plc","sa","nv","ag","the",
          "class","common","stock","shares","ordinary","technologies","technology","international","financial",
          "capital","systems","global","energy","pharmaceuticals","therapeutics","bancorp","trust","partners","lp",
          "industries","enterprises","brands","resources","services","solutions","entertainment","de","new"}

def _named(tk, text_):
    """Does the article actually name this company — its ticker or a distinctive word of
    its SEC name? The LLM picked Sanofi (SNY) for 'a $5 billion cybersecurity company'
    and Hudson Pacific (HPP) for a Howard Hughes story; neither name was in the text."""
    t=(text_ or "").lower()
    if re.search(r"(?<![a-z0-9])\$?"+re.escape(tk.lower())+r"(?![a-z0-9])",t): return True
    try:
        from backend.app.services.schedule_service import sec_title
        title=sec_title(tk)
    except Exception: title=None
    if not title: return False
    words=[w for w in re.split(r"[^a-z0-9]+",title.lower()) if len(w)>=4 and w not in _GENERIC]
    return any(w in t for w in words)

def _emit(fk,fig,sig,headline,url,at=None,quiet=False,derived=True,context=""):
    """Store (and push) one signal. `derived` = read out of news by the LLM, as opposed
    to a disclosed trade. `at`/`quiet` replay an older disclosure: dated and priced when
    it became public, and not pushed."""
    tk=(sig.get("ticker") or "").upper().strip()
    if not tk.replace("-","").isalpha() or len(tk)>6: return False
    if derived and tk in fig.get("own",()): return False   # a CEO praising their own company
    if derived and not _named(tk,headline+" "+(context or "")): 
        log.info(f"oracle {fk} {tk}: not named in the article — dropped"); return False
    try: conf=float(sig.get("confidence",0))
    except Exception: conf=0
    if conf<float(os.getenv("ORACLE_MIN_CONF","0.55")): return False
    if _rc is not None:
        try:
            if _rc.exists(f"oracle:cd:{fk}:{tk}"): return False
        except Exception: pass
    price,mcap=_quote(tk)
    if at and time.time()-at>86400: price=_close_on(tk,at) or 0
    if price<=0: return False
    pulse=_pulse_score(tk); size=float(os.getenv("ORACLE_SIZE_USD","200"))
    try:
        from backend.app.db.session import SessionLocal
        from sqlalchemy import text
        db=SessionLocal()
        # One call per person, stock and direction per ORACLE_REPEAT_DAYS: the same take
        # re-reported by ten outlets is one signal (Huang/NVDA had been logged 40 times).
        days=int(os.getenv("ORACLE_REPEAT_DAYS","14"))
        if db.execute(text("""SELECT 1 FROM oracle_signals WHERE figure=:f AND ticker=:t AND sentiment=:s
                AND status NOT IN ('duplicate','own_company','rejected')
                AND detected_at > COALESCE(to_timestamp(:at), now()) - make_interval(days=>:d)
                AND detected_at < COALESCE(to_timestamp(:at), now()) + make_interval(days=>:d) LIMIT 1"""),
                {"f":fk,"t":tk,"s":sig.get("sentiment"),"d":days,"at":at}).fetchone():
            db.close(); return False
        db.execute(text("""INSERT INTO oracle_signals(figure,figure_name,source_url,headline,ticker,
            sentiment,confidence,rationale,price,market_cap,suggested_size,pulse_score,status,detected_at,kind)
            VALUES(:f,:fn,:u,:h,:t,:s,:c,:r,:p,:mc,:sz,:ps,'new',COALESCE(to_timestamp(:at),now()),:k)"""),
            {"f":fk,"fn":fig["name"],"u":url,"h":headline[:500],"t":tk,"s":sig.get("sentiment"),
             "c":conf,"r":(sig.get("rationale","") or "")[:300],"p":price,"mc":mcap,"sz":size,"ps":pulse,
             "at":at,"k":"news" if derived else "disclosure"})
        db.commit(); db.close()
    except Exception as e:
        log.warning(f"db: {e}"); return False
    if quiet:
        log.info(f"oracle {fk} {tk} {sig.get('sentiment')} (backfill)")
        return True
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
    """One pass over every enabled figure. News items need an LLM read; at most
    ORACLE_LLM_PER_SCAN of them per pass (the rest wait, unseen, for the next one), and
    none after Groq says it is out of quota — the free tier's per-minute limit is shared
    with the Arena's sealed LLM forecasts, and the 31-figure roster's first scan used it
    all up within a minute (2026-10-30)."""
    new=0; budget=int(os.getenv("ORACLE_LLM_PER_SCAN","8"))
    for fk in _enabled():
        fig=FIGURES.get(fk)
        if not fig: continue
        for item in _gather(fk,fig):
            uid=item.get("uid") or item.get("url") or item.get("headline","")
            if _is_seen(fk,uid): continue
            k=item.get("kind")
            if k=="trade":
                at=item.get("at")
                if _emit(fk,fig,{"ticker":item["ticker"],"sentiment":item["sentiment"],
                    "confidence":item.get("conf",0.75),"rationale":item.get("rationale","")},
                    item["headline"],item.get("url",""),at=at,quiet=bool(at and time.time()-at>2*86400),
                    derived=False): new+=1
            elif k=="filing":
                _push(f"🔮 *ORACLE · {fig['name']}* {fig['emoji']}\n\n📄 {item['headline']}\n[filing]({item['url']})")
            else:
                if budget<=0: continue   # leave unseen for the next scan
                budget-=1
                sigs=_llm_analyze(fig["name"],item["headline"],item.get("body",""))
                if sigs is None:
                    # LLM unavailable: leave unseen so the next scan retries it — but an
                    # item the model keeps failing on (invalid JSON) is dropped after 3
                    # tries, or it would stall the queue at the front of every pass
                    budget=0
                    try:
                        if _rc is not None and _rc.incr(_seen_key(fk,uid)+":fail")>=3: _mark_seen(fk,uid)
                        elif _rc is not None: _rc.expire(_seen_key(fk,uid)+":fail",86400)
                    except Exception: pass
                    continue
                for sig in sigs:
                    if _emit(fk,fig,sig,item["headline"],item.get("url",""),context=item.get("body","")): new+=1
            _mark_seen(fk,uid)
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

# Nitter mirrors (xcancel 451, nitter.net 410, poast unreachable) and Marketaux (no
# signal in a month) were inserted into every X figure here; both are dead from this
# server, so they are no longer added. The functions stay for a working instance/key.

# ── Trump via CNN public Truth-Social archive (datacenter-friendly, 5-min fresh) ──
def src_truth_cnn():
    if not _due("trumparchive", int(os.getenv("TRUMP_POLL_SEC","300"))): return []
    try:
        r = httpx.get("https://ix.cnn.io/data/truth-social/truth_archive.json", headers=UA, timeout=20)
        if r.status_code != 200: log.warning(f"trump cnn {r.status_code}"); return []
        _mark_ok("trumparchive")
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
