import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import { PageHead } from '../components/PageHead'
import { Candles, type Candle } from '../components/Candles'
import { EquityLine } from '../components/EquityLine'
import { useT } from '../i18n'
import './AutopilotPage.css'

/**
 * Autopilot — the direction strategies, run by the site in a brokerage account.
 *
 * Top to bottom: who you are and which account (paper or live) is running; the four
 * strategies, each with its backtest (a sleeve run 2008–2026 at the exact sizing the bot
 * uses), the broker-tape replay at the 9:31 fill, the rule's live record since it went
 * public and this account's own record — all as return K-lines; then the account itself
 * (equity K-line, positions, today's calls, orders, log), risk limits, and the live-money
 * desk. Everything comes from /api/v1/autopilot; the catalog is public, the rest needs a
 * sign-in code (Telegram for the owner, email for everyone else).
 */

const API = '/api/v1/autopilot'
const TOKEN_KEY = 'sa_ap_token'
// The catalog's order; the server's /strategies `cards` carry the rest.
const ORDER = ['fade_spike', 'buy_flush', 'follow_gap', 'fade_miss', 'pre_run', 'sue_gap', 'insider_cluster', 'rsi2', 'trend', 'sectors'] as const
type Key = (typeof ORDER)[number]
type Family = 'earnings' | 'filings' | 'market'
const FAMILIES: Family[] = ['earnings', 'filings', 'market']

type Pt = { t: string; v: number }
type CardStats = {
  cagr: number | null; spy_cagr: number | null; max_dd: number | null; spy_max_dd?: number | null; sharpe: number | null
  spy_sharpe?: number | null; years_up: number | null; years_total: number | null; years: { y: number; ret: number }[]
  span: (string | null)[] | null; trades: number | null; signals: number | null; hit: number | null; avg: number | null
  excess: number | null; excess_t: number | null; excess_ew?: number | null; excess_ew_t?: number | null
  post_cagr?: number | null; post_spy_cagr?: number | null; published?: string | null
  stress_cagr?: number | null; holdout_cagr?: number | null; basis?: 'replay' | 'backtest'
}
type LiveCall = { ticker: string; session: string; status: string; entry_price?: number; mark?: number; ret?: number | null; exit_session?: string }
type Card = {
  key: Key; family: Family; kind: 'direction' | 'event' | 'target'; side: 'LONG' | 'SHORT'; entry: 'open' | 'close'
  hold: number | null; slots: number; alloc: number; on: boolean; source: string; desk: string; live_from?: string
  backtest: { stats: CardStats; series: Pt[]; bench: Pt[]; now?: Record<string, any> | null
    replay_summary?: { same_trades: { yahoo: Stat; open: Stat; fill: Stat; late?: Stat }; realistic: Stat; agree: number | null } | null }
  alt?: { basis: 'open'; series: Pt[]; bench: Pt[]; cagr: number | null }
  live: { n: number | null; closed: number | null; right?: number | null; ret?: number | null; mean?: number | null
    calls: LiveCall[]; candles?: Candle[]; target?: { session: string; weights: Record<string, number>; why: string } | null }
}
type Stat = { n: number; mean: number | null; hit: number | null; t: number | null }
type Research = { key: string; verdict: 'edge' | 'weak' | 'none' | 'pending'; n?: number; since?: string
  nums?: Record<string, any>; curve?: Candle[] }
type Sub = { on: boolean; alloc: number; slots: number }
type Settings = {
  enabled: boolean; strategies: Record<Key, Sub>; daily_loss_pct: number; max_gross_pct: number; min_price: number
  allow_short: boolean; notify: boolean; live_ack_at: string | null
}
type Broker = string
type Conn = { id: number; broker: Broker; name?: string; mode: 'paper' | 'live'; auth: string; account_hint: string; key_hint: string; settings: Settings }
type BrokerInfo = { key: string; name: string; via: string | null; paper: boolean | string | null; shorts: boolean | null; note: string; ready: boolean; oauth?: boolean }
type Me = {
  role: 'owner' | 'user'; email: string | null; live_allowed: boolean; live_ack_phrase: string; oauth: boolean; moomoo?: boolean
  brokers?: BrokerInfo[]
  caps: { live_per_trade: number; live_gross: number; short_min_equity: number }; accounts: Conn[]; now_et: string
}
type Trade = { call_id: number; rule: Key; ticker: string; side: string; qty: number; entry: number; exit: number | null; mark: number | null
  status: string; exit_session: string | null; opened: string | null; pnl: number | null; ret: number | null }
type State = {
  id: number; mode: 'paper' | 'live'; settings: Settings; broker_error?: string
  account?: { status: string; equity: string; last_equity: string; cash: string; buying_power: string; shorting_enabled: boolean }
  positions?: { symbol: string; qty: string; side: string; avg_entry_price: string; current_price: string; market_value: string
    unrealized_pl: string; unrealized_plpc: string; strategy: Key | null }[]
  clock?: { is_open: boolean; next_open: string; next_close: string }
  candles?: Candle[]
  strategies: Record<Key, { candles: Candle[]; open: number; closed: number; wins: number; realized: number; unrealized: number }>
  trades: Trade[]
  orders: { client_order_id: string; rule: string; ticker: string; leg: string; side: string; qty: number; tif: string; status: string
    submitted_at: string; filled_qty: number | null; filled_avg_price: number | null; error: string | null }[]
  events: { at: string; level: string; message: string }[]
  today: { id: number; rule: Key; ticker: string; side: string; entry: string; gap_x: number; tier: string; called_at: string }[]
}

class ApiError extends Error {}

async function call<T>(path: string, opts: { method?: string; body?: unknown; token?: string | null } = {}): Promise<T> {
  const r = await fetch(API + path, {
    method: opts.method ?? 'GET',
    headers: { 'Content-Type': 'application/json', ...(opts.token ? { 'X-Autopilot-Token': opts.token } : {}) },
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
  })
  if (!r.ok) {
    let msg = `${r.status}`
    try { const j = await r.json(); msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail ?? j) } catch { /* not json */ }
    throw new ApiError(msg)
  }
  return r.json() as Promise<T>
}

function readToken(): string | null {
  try { return localStorage.getItem(TOKEN_KEY) } catch { return null }
}
function writeToken(v: string | null) {
  try { if (v) localStorage.setItem(TOKEN_KEY, v); else localStorage.removeItem(TOKEN_KEY) } catch { /* private mode */ }
}

const pct = (v: number | null | undefined, d = 1) => (v == null ? '—' : `${v >= 0 ? '+' : '−'}${Math.abs(v * 100).toFixed(d)}%`)
const pctAbs = (v: number | null | undefined, d = 1) => (v == null ? '—' : `${(v * 100).toFixed(d)}%`)
const usd = (v: number | string | null | undefined, sign = false) => {
  if (v == null || v === '') return '—'
  const n = typeof v === 'string' ? parseFloat(v) : v
  if (!isFinite(n)) return '—'
  const s = `$${Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: Math.abs(n) >= 1000 ? 0 : 2 })}`
  return sign ? `${n >= 0 ? '+' : '−'}${s}` : (n < 0 ? `−${s}` : s)
}
const tone = (v: number | null | undefined) => (v == null ? '' : v > 0 ? 'is-up' : v < 0 ? 'is-down' : '')
// Every time on this page is New York time: that is the clock the market and the bot run on.
const NYT = { timeZone: 'America/New_York' } as const
const hm = (iso: string) => new Date(iso).toLocaleTimeString([], { ...NYT, hour: '2-digit', minute: '2-digit', hour12: false })
const md = (iso: string) => new Date(iso).toLocaleDateString([], { ...NYT, month: 'short', day: 'numeric' })

export function AutopilotPage() {
  const { t } = useT()
  return (
    <div className="page-stack">
      <PageHead kicker={t('nav.autopilot')} title={<>{t('ap.h.a')} <em>{t('ap.h.b')}</em></>} lede={t('ap.h.lede')} spike={0.42} />
      <AutopilotDesk />
    </div>
  )
}

export function AutopilotDesk() {
  const { t } = useT()
  const [params, setParams] = useSearchParams()
  const [token, setTokenState] = useState<string | null>(readToken)
  const [catalog, setCatalog] = useState<Card[] | null>(null)
  const [research, setResearch] = useState<Research[]>([])
  const [catErr, setCatErr] = useState(false)
  const [me, setMe] = useState<Me | null>(null)
  const [sel, setSel] = useState<number | 'new' | null>(null)
  const [st, setSt] = useState<State | null>(null)
  const [busy, setBusy] = useState(false)
  const [flash, setFlash] = useState<{ ok: boolean; msg: string } | null>(null)

  const setToken = (v: string | null) => { writeToken(v); setTokenState(v) }
  const say = (ok: boolean, msg: string) => { setFlash({ ok, msg }); window.setTimeout(() => setFlash(null), 6000) }

  useEffect(() => {
    call<{ cards: Card[]; research?: Research[] }>('/strategies')
      .then((d) => { setCatalog(d.cards); setResearch(d.research ?? []) }).catch(() => setCatErr(true))
  }, [])

  const loadMe = useCallback(async () => {
    if (!token) { setMe(null); return }
    try { setMe(await call<Me>('/me', { token })) } catch (e) {
      if (e instanceof ApiError && e.message.includes('Sign in')) setToken(null)
    }
  }, [token])
  useEffect(() => { loadMe() }, [loadMe])

  useEffect(() => {
    const c = params.get('connected'), o = params.get('oauth')
    if (c) { say(true, t('ap.flash.connected')); want.current = { mode: c, broker: params.get('broker') ?? 'alpaca' } }
    if (o) say(false, o === 'denied' ? t('ap.flash.denied') : o === 'noaccount' ? t('ap.flash.noUs') : t('ap.flash.oauthFail'))
    if (c || o) { const n = new URLSearchParams(params); ['connected', 'oauth', 'broker'].forEach((k) => n.delete(k)); setParams(n, { replace: true }) }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Which connection is on screen: the one just connected, else the first, else the connect panel.
  const want = useRef<{ mode: string; broker: string } | null>(null)
  useEffect(() => {
    if (!me) return
    const w = want.current
    const hit = w && me.accounts.find((a) => a.mode === w.mode && a.broker === w.broker)
    if (hit) { setSel(hit.id); want.current = null; return }
    if (sel === null || (typeof sel === 'number' && !me.accounts.some((a) => a.id === sel))) setSel(me.accounts[0]?.id ?? 'new')
  }, [me]) // eslint-disable-line react-hooks/exhaustive-deps
  const conn = me?.accounts.find((a) => a.id === sel) ?? null
  const loadState = useCallback(async () => {
    if (!token || !conn) { setSt(null); return }
    try { setSt(await call<State>(`/accounts/${conn.id}`, { token })) } catch { /* keep last */ }
  }, [token, conn?.id]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    loadState()
    const id = window.setInterval(loadState, st?.clock?.is_open ? 30_000 : 120_000)
    return () => window.clearInterval(id)
  }, [loadState, st?.clock?.is_open])

  const settings = st?.settings ?? conn?.settings ?? null
  const equity = st?.account ? parseFloat(st.account.equity) : null

  const save = async (patch: Partial<Settings> | { strategies: Partial<Record<Key, Partial<Sub>>> }) => {
    if (!conn || !token) return
    setBusy(true)
    try {
      await call(`/accounts/${conn.id}/settings`, { method: 'PUT', body: patch, token })
      await Promise.all([loadMe(), loadState()])
    } catch (e) { say(false, (e as Error).message) } finally { setBusy(false) }
  }

  const kill = async (flatten: boolean) => {
    if (!conn || !token) return
    if (!window.confirm(flatten ? t('ap.kill.confirmFlat') : t('ap.kill.confirm'))) return
    setBusy(true)
    try { await call(`/accounts/${conn.id}/kill`, { method: 'POST', body: { flatten }, token }); say(true, t('ap.kill.done')); await Promise.all([loadMe(), loadState()]) }
    catch (e) { say(false, (e as Error).message) } finally { setBusy(false) }
  }

  const totalAlloc = settings ? ORDER.reduce((n, k) => n + (settings.strategies[k]?.on ? settings.strategies[k].alloc : 0), 0) : 0

  return (
    <div className="ap">
      {flash && <div className={`ap-flash ${flash.ok ? 'is-ok' : 'is-bad'}`} role="status">{flash.msg}</div>}

      {!token ? (
        <SignIn onToken={(v) => { setToken(v); say(true, t('ap.flash.signedIn')) }} />
      ) : !me ? (
        <div className="shimmer" style={{ height: 120 }} />
      ) : (
        <section className="ap-bar">
          <div className="ap-bar__who">
            <span className="ap-tag">{me.role === 'owner' ? t('ap.role.owner') : me.email}</span>
            <div className="ap-modes" role="tablist">
              {me.accounts.map((a) => (
                <button key={a.id} role="tab" aria-selected={sel === a.id} className={sel === a.id ? 'is-on' : ''} onClick={() => setSel(a.id)}>
                  {a.name ?? a.broker} · {a.mode === 'paper' ? t('ap.mode.paper') : t('ap.mode.live')}
                  <i className={a.mode === 'live' ? 'is-live' : a.settings.enabled ? '' : 'is-off'} />
                </button>
              ))}
              <button role="tab" aria-selected={sel === 'new'} className={sel === 'new' ? 'is-on' : ''} onClick={() => setSel('new')}>{t('ap.addBroker')}</button>
            </div>
            <button className="ap-link" onClick={() => { setToken(null); setMe(null); setSt(null) }}>{t('ap.signOut')}</button>
          </div>
          {conn && settings ? (
            <div className="ap-bar__acct">
              <div className="ap-fig"><span>{t('ap.fig.equity')}</span><b>{usd(st?.account?.equity)}</b></div>
              <div className="ap-fig"><span>{t('ap.fig.today')}</span>
                <b className={tone(st?.account ? parseFloat(st.account.equity) - parseFloat(st.account.last_equity) : null)}>
                  {st?.account ? usd(parseFloat(st.account.equity) - parseFloat(st.account.last_equity), true) : '—'}</b></div>
              <div className="ap-fig"><span>{t('ap.fig.account')}</span><b>{conn.name ?? conn.broker} …{conn.account_hint}</b></div>
              <div className="ap-fig"><span>{t('ap.fig.market')}</span>
                <b>{st?.clock ? (st.clock.is_open ? t('ap.market.open') : `${t('ap.market.next')} ${md(st.clock.next_open)} ${hm(st.clock.next_open)} ET`) : '—'}</b></div>
              <div className="ap-master">
                <Switch on={settings.enabled} disabled={busy || (conn.mode === 'live' && !settings.live_ack_at)}
                  onChange={(v) => save({ enabled: v })} label={settings.enabled ? t('ap.master.on') : t('ap.master.off')} big />
                <div className="ap-kill">
                  <button onClick={() => kill(false)} disabled={busy}>{t('ap.kill.pause')}</button>
                  <button onClick={() => kill(true)} disabled={busy} className="is-danger">{t('ap.kill.flat')}</button>
                </div>
              </div>
              {st?.broker_error && <p className="ap-warn">{t('ap.brokerError')}: {st.broker_error}</p>}
              {settings.enabled && <p className="ap-next">{t('ap.next', { n: ORDER.filter((k) => settings.strategies[k]?.on).length })}</p>}
            </div>
          ) : sel === 'new' || !me.accounts.length ? (
            <ConnectPanel me={me} token={token}
              onDone={async (r) => { want.current = { mode: r.mode, broker: r.broker }; await loadMe(); say(true, t('ap.flash.connected')) }}
              onError={(m) => say(false, m)} />
          ) : (
            <div className="shimmer" style={{ height: 90 }} />
          )}
        </section>
      )}

      <section className="ap-strats">
        <header className="ap-sec">
          <h2>{t('ap.strats.h')}</h2>
          <p>{t('ap.strats.lede')}</p>
          {settings && <p className={`ap-alloc ${totalAlloc > 100 ? 'is-bad' : ''}`}>{t('ap.alloc.total', { n: totalAlloc.toFixed(0) })}</p>}
        </header>
        {catErr && <div className="empty-state"><p>{t('ap.catErr')}</p></div>}
        {!catalog && !catErr && <div className="shimmer" style={{ height: 520 }} />}
        {FAMILIES.map((f) => {
          const cards = (catalog ?? []).filter((c) => c.family === f)
          if (!cards.length) return null
          return (
            <div key={f} className="ap-family">
              <header className="ap-family__head">
                <h3>{t(`ap.fam.${f}` as 'ap.fam.earnings')}</h3>
                <p>{t(`ap.fam.${f}.lede` as 'ap.fam.earnings.lede')}</p>
              </header>
              <div className="ap-cards">
                {cards.map((s) => (
                  <StrategyCard key={s.key} s={s} sub={settings?.strategies[s.key] ?? null} mine={st?.strategies?.[s.key] ?? null}
                    equity={equity} disabled={busy} live={conn?.mode === 'live'} caps={me?.caps ?? null}
                    onSave={(p) => save({ strategies: { [s.key]: p } })} />
                ))}
              </div>
            </div>
          )
        })}
      </section>

      {research.length > 0 && <Lab rows={research} />}
      {conn && st && <AccountDetail st={st} />}
      {conn && settings && <Risk settings={settings} disabled={busy} onSave={save} live={conn.mode === 'live'} caps={me?.caps ?? null} />}
      {me && conn && conn.mode === 'live' && !conn.settings.live_ack_at && (
        <Acknowledge me={me} conn={conn} token={token!} onDone={async () => { await Promise.all([loadMe(), loadState()]); say(true, t('ap.flash.acked')) }}
          onError={(m) => say(false, m)} />
      )}
      <Notes />
    </div>
  )
}

/* ─────────────────────────── strategy card ─────────────────────────── */

type View = 'bt' | 'alt' | 'signal' | 'mine'

function StrategyCard({ s, sub, mine, equity, disabled, live, caps, onSave }: {
  s: Card; sub: Sub | null; mine: State['strategies'][Key] | null; equity: number | null; disabled: boolean; live: boolean
  caps: Me['caps'] | null; onSave: (p: Partial<Sub>) => void
}) {
  const { t } = useT()
  const [open, setOpen] = useState(false)
  const [view, setView] = useState<View>('bt')
  const b = s.backtest.stats
  const y0 = (b.span?.[0] ?? '').slice(0, 4)
  const per = sub && equity ? Math.min(equity * sub.alloc / 100 / (s.kind === 'target' ? 1 : Math.max(sub.slots, 1)),
    live && caps ? caps.live_per_trade : Infinity) : null
  const views: { k: View; label: string; ok: boolean }[] = [
    { k: 'bt', label: b.basis === 'replay' ? t('ap.v.real') : t('ap.v.bt'), ok: true },
    ...(s.alt ? [{ k: 'alt' as View, label: t('ap.v.open'), ok: true }] : []),
    { k: 'signal', label: t('ap.v.signal'), ok: true },
    { k: 'mine', label: t('ap.v.mine'), ok: !!sub },
  ]
  const liveChart = s.live.candles && s.live.candles.length > 1
    ? <Candles data={s.live.candles} />
    : <LiveList card={s} />
  const chart = view === 'bt'
    ? <EquityLine series={s.backtest.series} bench={s.backtest.bench} years={b.years} benchLabel={t('ap.bench')} />
    : view === 'alt' && s.alt
      ? <EquityLine series={s.alt.series} bench={s.alt.bench} benchLabel={t('ap.bench')} />
      : view === 'signal' ? liveChart
        : <Candles data={mine?.candles ?? []} empty={t('ap.mine.none')} />
  const beat = b.cagr != null && b.spy_cagr != null && b.cagr > b.spy_cagr
  return (
    <article className={`ap-card ${s.side === 'LONG' ? 'is-long' : 'is-short'} ${sub?.on ? 'is-running' : ''}`}>
      <header>
        <span className={`db-side ${s.side === 'LONG' ? 'is-long' : 'is-short'}`}>{s.side === 'LONG' ? t('db.long') : t('db.short')}</span>
        <span className="db-hold">{t(`ap.hold.${s.key}` as 'ap.hold.pre_run')}</span>
        {s.on && <span className="ap-pick-tag">{t('ap.rec')}</span>}
        {sub && <Switch on={sub.on} disabled={disabled} onChange={(v) => onSave({ on: v })} label={sub.on ? t('ap.run.on') : t('ap.run.off')} />}
      </header>
      <h3>{t(`ap.name.${s.key}` as 'ap.name.pre_run')}</h3>
      <p className="ap-when">{t(`ap.rule.${s.key}` as 'ap.rule.pre_run')}</p>
      <p className="ap-origin">
        <span>{t('ap.origin')} {s.source}</span>
        <a href={s.desk}>{t('ap.from')} {t(`ap.desk.${s.desk.replace(/\W/g, '') || 'home'}` as 'ap.desk.home')} →</a>
      </p>

      <p className="ap-basis">{b.basis === 'replay' ? t('ap.basis.replay', { y: y0 }) : t('ap.basis.any', { y: y0 })}</p>
      <dl className="ap-bt">
        <div><dt>{t('ap.bt.cagr')}</dt><dd className={tone(b.cagr)}>{pct(b.cagr)}</dd></div>
        <div><dt>{t('ap.bt.spy')}</dt><dd className={beat ? '' : 'ap-dim'}>{pct(b.spy_cagr)}</dd></div>
        <div><dt>{t('ap.bt.dd')}</dt><dd className="is-down">{pct(b.max_dd, 0)}{b.spy_max_dd != null && <small> / {pct(b.spy_max_dd, 0)}</small>}</dd></div>
        {s.kind === 'target'
          ? <div><dt>{t('ap.bt.sharpe')}</dt><dd className={b.sharpe != null && b.spy_sharpe != null && b.sharpe > b.spy_sharpe ? 'is-up' : ''}>{b.sharpe?.toFixed(2) ?? '—'}<small> / {b.spy_sharpe?.toFixed(2) ?? '—'}</small></dd></div>
          : <div><dt>{t('ap.bt.edge')}</dt><dd className={tone(b.excess)}>{edgeText(b)}</dd></div>}
      </dl>
      {chart}
      <div className="ap-views" role="tablist">
        {views.map((v) => (
          <button key={v.k} role="tab" aria-selected={view === v.k} className={view === v.k ? 'is-on' : ''} disabled={!v.ok} onClick={() => setView(v.k)}>{v.label}</button>
        ))}
        <button className="ap-more" onClick={() => setOpen((o) => !o)} aria-expanded={open}>{open ? t('ap.less') : t('ap.more')}</button>
      </div>

      {open && (
        <div className="ap-detail">
          <dl className="ap-bt is-small">
            <div><dt>{t('ap.bt.years')}</dt><dd>{b.years_up ?? '—'}/{b.years_total ?? '—'}</dd></div>
            <div><dt>{t('ap.bt.sharpe')}</dt><dd>{b.sharpe?.toFixed(2) ?? '—'}{b.spy_sharpe != null && <small> / {b.spy_sharpe.toFixed(2)}</small>}</dd></div>
            <div><dt>{t('ap.bt.hit')}</dt><dd>{pctAbs(b.hit)}</dd></div>
            <div><dt>{t('ap.bt.avg')}</dt><dd className={tone(b.avg)}>{pct(b.avg, 2)}</dd></div>
            {b.excess_ew != null && <div><dt>{t('ap.bt.ew')}</dt><dd className={tone(b.excess_ew)}>{pct(b.excess_ew, 2)} · t {b.excess_ew_t?.toFixed(1) ?? '—'}</dd></div>}
            {b.post_cagr != null && <div><dt>{t('ap.bt.post', { y: (b.published ?? '').slice(0, 4) })}</dt><dd className={tone(b.post_cagr)}>{pct(b.post_cagr)}<small> / {pct(b.post_spy_cagr ?? null)}</small></dd></div>}
            {b.holdout_cagr != null && <div><dt>{t('ap.bt.holdout')}</dt><dd className={tone(b.holdout_cagr)}>{pct(b.holdout_cagr)}</dd></div>}
            {b.stress_cagr != null && <div><dt>{t('ap.bt.stress')}</dt><dd className={tone(b.stress_cagr)}>{pct(b.stress_cagr)}</dd></div>}
            {b.trades != null && <div><dt>{t('ap.bt.trades')}</dt><dd>{b.trades.toLocaleString()}</dd></div>}
          </dl>
          <p className="ap-cap">{t(`ap.how.${s.key}` as 'ap.how.pre_run')}</p>
          {s.backtest.replay_summary && (
            <p className="ap-replay">{t('ap.replay.line', { y: pct(s.backtest.replay_summary.same_trades.yahoo.mean, 2),
              f: pct(s.backtest.replay_summary.same_trades.fill.mean, 2), t: s.backtest.replay_summary.realistic.t?.toFixed(1) ?? '—' })}</p>
          )}
          {s.live.target && <p className="ap-now">{t('ap.now', { d: s.live.target.session, w: Object.entries(s.live.target.weights).map(([k, v]) => `${k} ${Math.round(v * 100)}%`).join(' · '), why: s.live.target.why })}</p>}
          {s.side === 'SHORT' && <p className="ap-cap">{t('ap.shortNote')}</p>}
          {sub && (
            <div className="ap-size">
              <label>{t('ap.size.alloc')}
                <NumIn value={sub.alloc} min={0} max={100} step={5} suffix="%" disabled={disabled} onCommit={(v) => onSave({ alloc: v })} />
              </label>
              {s.kind !== 'target' && (
                <label>{t('ap.size.slots')}
                  <NumIn value={sub.slots} min={1} max={30} step={1} disabled={disabled} onCommit={(v) => onSave({ slots: v })} />
                </label>
              )}
              <span className="ap-size__per">{per != null ? t(s.kind === 'target' ? 'ap.size.sleeve' : 'ap.size.per', { v: usd(per) }) : ''}</span>
            </div>
          )}
        </div>
      )}
    </article>
  )
}

function edgeText(b: CardStats): string {
  if (b.excess == null) return '—'
  return `${pct(b.excess, 2)}${b.excess_t != null ? ` · t ${b.excess_t.toFixed(1)}` : ''}`
}

function LiveList({ card }: { card: Card }) {
  const { t } = useT()
  const calls = card.live.calls ?? []
  if (!calls.length) return <div className="kl-empty">{t('ap.live.none')}</div>
  return (
    <ol className="ap-livelist">
      {calls.slice(0, 8).map((c, i) => (
        <li key={i}>
          <b>{c.ticker}</b><span>{c.session}</span>
          <span className={c.ret == null ? 'ap-dim' : tone(c.ret)}>{c.ret == null ? t('ap.live.pending') : pct(c.ret, 2)}</span>
          <span className="ap-dim">{c.status === 'closed' ? t('ap.live.closed') : c.status === 'open' ? t('ap.live.open') : ''}</span>
        </li>
      ))}
    </ol>
  )
}

/* ─────────────────────────── the rest of the lab ─────────────────────────── */

function Lab({ rows }: { rows: Research[] }) {
  const { t } = useT()
  const num = (r: Research) => {
    const n = r.nums ?? {}
    const v: Record<string, string | number> = { n: r.n?.toLocaleString() ?? '—', since: r.since ?? '' }
    for (const [k, x] of Object.entries(n)) {
      if (typeof x !== 'number') continue
      v[k] = /(_t|^t)$/.test(k) || k === 'top_t' ? x.toFixed(1)
        : ['sharpe', 'spy_sharpe'].includes(k) ? x.toFixed(2)
          : ['cagr', 'spy', 'dd'].includes(k) ? pct(x, 1)
            : ['hit', 'majority', 'top_beat', 'top_implied', 'top_realised', 'mid_implied'].includes(k) ? pctAbs(x, 1) : pct(x, 2)
    }
    return v
  }
  return (
    <section className="ap-lab" id="lab">
      <header className="ap-sec"><h2>{t('ap.lab.h')}</h2><p>{t('ap.lab.lede')}</p></header>
      <ol className="ap-lab__list">
        {rows.map((r) => (
          <li key={r.key} className={`is-${r.verdict}`}>
            <div className="ap-lab__head">
              <h3>{t(`ap.lab.${r.key}.name` as 'ap.lab.oracle.name')}</h3>
              <span className={`ap-verdict is-${r.verdict}`}>{t(`ap.verdict.${r.verdict}` as 'ap.verdict.none')}</span>
            </div>
            <p className="ap-lab__what">{t(`ap.lab.${r.key}.what` as 'ap.lab.oracle.what')}</p>
            <p className="ap-lab__res">{r.verdict === 'pending' ? t('ap.lab.pending') : t(`ap.lab.${r.key}.res` as 'ap.lab.oracle.res', num(r))}</p>
            {r.curve && r.curve.length > 1 && <EquityLine series={r.curve.map((c) => ({ t: c.t, v: c.c }))} />}
          </li>
        ))}
      </ol>
    </section>
  )
}

/* ─────────────────────────── account ─────────────────────────── */

function AccountDetail({ st }: { st: State }) {
  const { t } = useT()
  const [tab, setTab] = useState<'pos' | 'today' | 'trades' | 'orders' | 'log'>('pos')
  return (
    <section className="ap-acct">
      <header className="ap-sec"><h2>{t('ap.acct.h')}</h2><p>{t('ap.acct.lede')}</p></header>
      <div className="ap-acct__chart">
        <Candles data={st.candles ?? []} empty={t('ap.acct.none')} height={200} />
      </div>
      <div className="ap-views" role="tablist">
        {(['pos', 'today', 'trades', 'orders', 'log'] as const).map((k) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? 'is-on' : ''} onClick={() => setTab(k)}>
            {t(`ap.tab.${k}` as 'ap.tab.pos')}
            {k === 'pos' && st.positions ? ` · ${st.positions.length}` : k === 'today' ? ` · ${st.today.length}` : ''}
          </button>
        ))}
      </div>
      <div className="ap-table-wrap">
        {tab === 'pos' && (
          <Table empty={t('ap.empty.pos')} head={[t('ap.col.ticker'), t('ap.col.strategy'), t('ap.col.qty'), t('ap.col.entry'), t('ap.col.mark'), t('ap.col.pl')]}
            rows={(st.positions ?? []).map((p) => [p.symbol, p.strategy ? t(`db.rule.${p.strategy}` as 'db.rule.follow_gap') : t('ap.manual'), p.qty,
              usd(p.avg_entry_price), usd(p.current_price),
              <span className={tone(parseFloat(p.unrealized_pl))}>{usd(p.unrealized_pl, true)} · {pct(parseFloat(p.unrealized_plpc), 2)}</span>])} />
        )}
        {tab === 'today' && (
          <Table empty={t('ap.empty.today')} head={[t('ap.col.time'), t('ap.col.ticker'), t('ap.col.strategy'), t('ap.col.side'), t('ap.col.gap'), t('ap.col.tier')]}
            rows={st.today.map((c) => [hm(c.called_at), c.ticker, t(`db.rule.${c.rule}` as 'db.rule.follow_gap'),
              <span className={c.side === 'LONG' ? 'is-up' : 'is-down'}>{c.side === 'LONG' ? t('db.long') : t('db.short')}</span>,
              `${c.gap_x >= 0 ? '+' : ''}${c.gap_x.toFixed(1)}×`, c.tier])} />
        )}
        {tab === 'trades' && (
          <Table empty={t('ap.empty.trades')} head={[t('ap.col.ticker'), t('ap.col.strategy'), t('ap.col.side'), t('ap.col.qty'), t('ap.col.entry'), t('ap.col.exit'), t('ap.col.pl')]}
            rows={st.trades.map((x) => [x.ticker, t(`db.rule.${x.rule}` as 'db.rule.follow_gap'), x.side === 'LONG' ? t('db.long') : t('db.short'), x.qty,
              usd(x.entry), x.exit != null ? usd(x.exit) : `${usd(x.mark)} · ${x.exit_session ?? ''}`,
              <span className={tone(x.pnl)}>{usd(x.pnl, true)} · {pct(x.ret, 2)}</span>])} />
        )}
        {tab === 'orders' && (
          <Table empty={t('ap.empty.orders')} head={[t('ap.col.time'), t('ap.col.ticker'), t('ap.col.leg'), t('ap.col.side'), t('ap.col.qty'), t('ap.col.status'), t('ap.col.fill')]}
            rows={st.orders.map((o) => [`${md(o.submitted_at)} ${hm(o.submitted_at)}`, o.ticker, `${o.leg} · ${o.tif}`, o.side.toUpperCase(), o.qty || '—',
              <span className={o.status === 'skipped' || o.status === 'failed' ? 'ap-dim' : ''} title={o.error ?? ''}>{o.status}{o.error ? ` — ${o.error}` : ''}</span>,
              o.filled_avg_price ? usd(o.filled_avg_price) : '—'])} />
        )}
        {tab === 'log' && (
          <ol className="ap-log">
            {st.events.length === 0 && <li className="ap-dim">{t('ap.empty.log')}</li>}
            {st.events.map((e, i) => (
              <li key={i} className={`is-${e.level}`}><time>{md(e.at)} {hm(e.at)}</time><span>{e.message}</span></li>
            ))}
          </ol>
        )}
      </div>
    </section>
  )
}

function Table({ head, rows, empty }: { head: string[]; rows: ReactNode[][]; empty: string }) {
  if (!rows.length) return <p className="ap-dim ap-empty">{empty}</p>
  return (
    <table className="ap-table">
      <thead><tr>{head.map((h) => <th key={h}>{h}</th>)}</tr></thead>
      <tbody>{rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody>
    </table>
  )
}

/* ─────────────────────────── risk ─────────────────────────── */

function Risk({ settings, disabled, onSave, live, caps }: {
  settings: Settings; disabled: boolean; onSave: (p: Partial<Settings>) => void; live: boolean; caps: Me['caps'] | null
}) {
  const { t } = useT()
  return (
    <section className="ap-risk">
      <header className="ap-sec"><h2>{t('ap.risk.h')}</h2><p>{t('ap.risk.lede')}</p></header>
      <div className="ap-risk__grid">
        <label>{t('ap.risk.loss')}<NumIn value={settings.daily_loss_pct} min={0.5} max={20} step={0.5} suffix="%" disabled={disabled} onCommit={(v) => onSave({ daily_loss_pct: v })} /></label>
        <label>{t('ap.risk.gross')}<NumIn value={settings.max_gross_pct} min={10} max={200} step={10} suffix="%" disabled={disabled} onCommit={(v) => onSave({ max_gross_pct: v })} /></label>
        <label>{t('ap.risk.minPx')}<NumIn value={settings.min_price} min={1} max={100} step={1} prefix="$" disabled={disabled} onCommit={(v) => onSave({ min_price: v })} /></label>
        <label className="ap-risk__sw">{t('ap.risk.short')}<Switch on={settings.allow_short} disabled={disabled} onChange={(v) => onSave({ allow_short: v })} /></label>
        <label className="ap-risk__sw">{t('ap.risk.notify')}<Switch on={settings.notify} disabled={disabled} onChange={(v) => onSave({ notify: v })} /></label>
      </div>
      {live && caps && <p className="ap-cap">{t('ap.risk.caps', { a: usd(caps.live_per_trade), b: usd(caps.live_gross) })}</p>}
    </section>
  )
}

/* ─────────────────────────── sign-in and connections ─────────────────────────── */

function SignIn({ onToken }: { onToken: (t: string) => void }) {
  const { t } = useT()
  const [who, setWho] = useState<'user' | 'owner'>('user')
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [sent, setSent] = useState<string[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const send = async (e: FormEvent) => {
    e.preventDefault(); setErr(null); setBusy(true)
    try { const r = await call<{ sent: string[] }>('/code', { method: 'POST', body: { email: who === 'owner' ? null : email } }); setSent(r.sent) }
    catch (x) { setErr((x as Error).message) } finally { setBusy(false) }
  }
  const verify = async (e: FormEvent) => {
    e.preventDefault(); setErr(null); setBusy(true)
    try { const r = await call<{ token: string }>('/login', { method: 'POST', body: { code, email: who === 'owner' ? null : email } }); onToken(r.token) }
    catch (x) { setErr((x as Error).message) } finally { setBusy(false) }
  }
  return (
    <section className="ap-bar ap-signin">
      <div>
        <h2 className="serif">{t('ap.signin.h')}</h2>
        <p>{t('ap.signin.lede')}</p>
      </div>
      <div className="ap-signin__box">
        <div className="ap-modes" role="tablist">
          <button role="tab" aria-selected={who === 'user'} className={who === 'user' ? 'is-on' : ''} onClick={() => { setWho('user'); setSent(null) }}>{t('ap.signin.email')}</button>
          <button role="tab" aria-selected={who === 'owner'} className={who === 'owner' ? 'is-on' : ''} onClick={() => { setWho('owner'); setSent(null) }}>{t('ap.signin.owner')}</button>
        </div>
        {!sent ? (
          <form onSubmit={send} className="ap-form">
            {who === 'user' && <input type="email" required placeholder="you@example.com" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />}
            {who === 'owner' && <p className="ap-dim">{t('ap.signin.ownerNote')}</p>}
            <button className="ap-btn" disabled={busy}>{t('ap.signin.send')}</button>
          </form>
        ) : (
          <form onSubmit={verify} className="ap-form">
            <p className="ap-dim">{t('ap.signin.sent', { to: sent.join(' + ') })}</p>
            <input inputMode="numeric" pattern="[0-9]{6}" maxLength={6} required placeholder="000000" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} autoComplete="one-time-code" className="ap-code" />
            <button className="ap-btn" disabled={busy}>{t('ap.signin.verify')}</button>
          </form>
        )}
        {err && <p className="ap-warn">{err}</p>}
      </div>
    </section>
  )
}

type Done = { mode: 'paper' | 'live'; broker: Broker }

function ConnectPanel({ me, token, onDone, onError }: { me: Me; token: string; onDone: (r: Done) => void; onError: (m: string) => void }) {
  const { t } = useT()
  const brokers = me.brokers ?? []
  const [pick, setPick] = useState<string>('alpaca')
  const b = brokers.find((x) => x.key === pick)
  const paperOk = b?.paper === true || b?.paper === 'same_day'
  const [mode, setMode] = useState<'paper' | 'live'>('paper')
  const m: 'paper' | 'live' = paperOk ? mode : 'live'
  const [f1, setF1] = useState('')
  const [f2, setF2] = useState('')
  const [busy, setBusy] = useState(false)
  const reset = () => { setF1(''); setF2('') }
  const post = async (path: string, body: object, broker: string) => {
    setBusy(true)
    try { await call(path, { method: 'POST', body, token }); reset(); onDone({ mode: m, broker }) }
    catch (x) { onError((x as Error).message) } finally { setBusy(false) }
  }
  const go = async (path: string) => {
    setBusy(true)
    try { const r = await call<{ url: string }>(path, { token }); window.location.href = r.url } catch (x) { onError((x as Error).message); setBusy(false) }
  }
  const closed = m === 'live' && !me.live_allowed
  const tick = (v: boolean | string | null) => (v === true ? '✓' : v === 'same_day' ? t('ap.br.sameDay') : v === 't212' ? t('ap.br.t212') : '—')
  return (
    <div className="ap-connect is-wide">
      <div className="ap-brokers" role="tablist" aria-label={t('ap.connect.broker')}>
        {brokers.map((x) => (
          <button key={x.key} role="tab" aria-selected={pick === x.key} className={`ap-broker ${pick === x.key ? 'is-on' : ''} ${x.via ? '' : 'is-off'}`}
            onClick={() => { setPick(x.key); reset() }}>
            <b>{x.name}</b>
            <span>{t('ap.br.paper')} {tick(x.paper)} · {t('ap.br.shorts')} {tick(x.shorts)}</span>
            {!x.via ? <em>{t('ap.br.unsupported')}</em> : !x.ready ? <em>{t('ap.br.soon')}</em> : null}
          </button>
        ))}
      </div>
      {b && (
        <div className="ap-connect__body">
          <div>
            <h3>{b.name}</h3>
            <p className="ap-dim">{t(b.note as 'ap.br.alpaca')}</p>
            {b.via && paperOk && (
              <div className="ap-modes" role="tablist" aria-label={t('ap.connect.mode')}>
                {(['paper', 'live'] as const).map((x) => (
                  <button key={x} role="tab" aria-selected={m === x} className={m === x ? 'is-on' : ''} onClick={() => setMode(x)}>{x === 'paper' ? t('ap.mode.paper') : t('ap.mode.live')}</button>
                ))}
              </div>
            )}
            {b.via && <ol className="ap-steps">{[1, 2, 3].map((i) => <li key={i}>{t(`ap.br.${b.key}.${m}.${i}` as 'ap.br.alpaca.paper.1')}</li>)}</ol>}
            {m === 'live' && b.via && !closed && <p className="ap-dim">{t('ap.live.intro', { a: usd(me.caps.live_per_trade), b: usd(me.caps.live_gross) })}</p>}
          </div>
          <div>
            {!b.via ? null : closed ? (
              <><h3>{t('ap.live.closedH')}</h3><p className="ap-dim">{t('ap.live.closed')}</p></>
            ) : !b.ready ? (
              <p className="ap-dim">{t('ap.br.notReady')}</p>
            ) : b.key === 'alpaca' ? (
              <>
                {b.oauth && <button className="ap-btn" disabled={busy} onClick={() => go(`/oauth/start?mode=${m}`)}>{t('ap.connect.oauth')}</button>}
                <form onSubmit={(e) => { e.preventDefault(); post('/accounts', { mode: m, key_id: f1, secret: f2 }, 'alpaca') }} className="ap-form">
                  <input required placeholder={m === 'paper' ? 'Key ID · PK…' : 'Key ID · AK…'} value={f1} onChange={(e) => setF1(e.target.value)} autoComplete="off" spellCheck={false} />
                  <input required type="password" placeholder="Secret" value={f2} onChange={(e) => setF2(e.target.value)} autoComplete="off" />
                  <button className="ap-btn" disabled={busy}>{busy ? t('ap.connect.checking') : t('ap.connect.go')}</button>
                </form>
              </>
            ) : b.key === 'tradier' ? (
              <form onSubmit={(e) => { e.preventDefault(); post('/connect/tradier', { mode: m, token: f1 }, 'tradier') }} className="ap-form">
                <input required type="password" placeholder={m === 'paper' ? 'Sandbox access token' : 'API access token'} value={f1} onChange={(e) => setF1(e.target.value)} autoComplete="off" />
                <button className="ap-btn" disabled={busy}>{busy ? t('ap.connect.checking') : t('ap.connect.go')}</button>
              </form>
            ) : b.key === 'tastytrade' ? (
              <form onSubmit={(e) => { e.preventDefault(); post('/connect/tastytrade', { mode: m, client_secret: f1, refresh_token: f2 }, 'tastytrade') }} className="ap-form">
                <input required type="password" placeholder="Client secret" value={f1} onChange={(e) => setF1(e.target.value)} autoComplete="off" />
                <input required type="password" placeholder="Refresh token" value={f2} onChange={(e) => setF2(e.target.value)} autoComplete="off" />
                <button className="ap-btn" disabled={busy}>{busy ? t('ap.connect.checking') : t('ap.connect.go')}</button>
              </form>
            ) : b.key === 'moomoo' ? (
              <button className="ap-btn" disabled={busy} onClick={() => go(`/moomoo/start?mode=${m}`)}>{t('ap.mm.go')}</button>
            ) : b.key === 'robinhood' ? (
              <button className="ap-btn" disabled={busy} onClick={() => go('/robinhood/start')}>{t('ap.br.rhGo')}</button>
            ) : b.key === 'snaptrade' ? (
              <button className="ap-btn" disabled={busy} onClick={() => go('/snaptrade/start')}>{t('ap.br.snapGo')}</button>
            ) : null}
            {b.via && <p className="ap-dim">{t(`ap.br.${b.key}.privacy` as 'ap.br.alpaca.privacy')}</p>}
          </div>
        </div>
      )}
    </div>
  )
}

function Acknowledge({ me, conn, token, onDone, onError }: { me: Me; conn: Conn; token: string; onDone: () => void; onError: (m: string) => void }) {
  const { t } = useT()
  const [ack, setAck] = useState('')
  const [busy, setBusy] = useState(false)
  const s = conn.settings
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true)
    try { await call(`/accounts/${conn.id}/live`, { method: 'POST', body: { ack }, token }); onDone() }
    catch (x) { onError((x as Error).message) } finally { setBusy(false) }
  }
  return (
    <section className="paper ap-ack">
      <p className="ap-ack__kicker">{t('ap.ack.kicker')} · …{conn.account_hint}</p>
      <h2 className="serif">{t('ap.ack.h')}</h2>
      <ul>
        <li>{t('ap.ack.l1')}</li>
        <li>{t('ap.ack.l2', { a: usd(me.caps.live_per_trade), b: usd(me.caps.live_gross) })}</li>
        <li>{t('ap.ack.l3', { s: ORDER.filter((k) => s.strategies[k].on).map((k) => t(`db.rule.${k}` as 'db.rule.follow_gap')).join('、') || '—', l: s.daily_loss_pct })}</li>
        <li>{t('ap.ack.l4')}</li>
      </ul>
      <form onSubmit={submit} className="ap-form">
        <label>{t('ap.ack.type')} <code>{me.live_ack_phrase}</code></label>
        <input value={ack} onChange={(e) => setAck(e.target.value)} placeholder={me.live_ack_phrase} spellCheck={false} autoComplete="off" />
        <button className="ap-btn" disabled={busy || ack.trim() !== me.live_ack_phrase}>{t('ap.ack.sign')}</button>
      </form>
    </section>
  )
}

function Notes() {
  const { t } = useT()
  return (
    <section className="ap-notes">
      <h3>{t('ap.notes.h')}</h3>
      <ol>
        <li>{t('ap.notes.1')}</li>
        <li>{t('ap.notes.2')}</li>
        <li>{t('ap.notes.3')}</li>
        <li>{t('ap.notes.4')}</li>
        <li>{t('ap.notes.5')}</li>
      </ol>
    </section>
  )
}

/* ─────────────────────────── controls ─────────────────────────── */

function Switch({ on, onChange, label, disabled, big }: { on: boolean; onChange: (v: boolean) => void; label?: string; disabled?: boolean; big?: boolean }) {
  return (
    <button type="button" role="switch" aria-checked={on} disabled={disabled} className={`ap-sw ${on ? 'is-on' : ''} ${big ? 'is-big' : ''}`} onClick={() => onChange(!on)}>
      <i />{label && <span>{label}</span>}
    </button>
  )
}

function NumIn({ value, min, max, step, onCommit, suffix, prefix, disabled }: {
  value: number; min: number; max: number; step: number; onCommit: (v: number) => void; suffix?: string; prefix?: string; disabled?: boolean
}) {
  const [v, setV] = useState(String(value))
  useEffect(() => setV(String(value)), [value])
  const commit = () => {
    const n = Math.min(max, Math.max(min, parseFloat(v)))
    if (!isFinite(n)) { setV(String(value)); return }
    if (n !== value) onCommit(n)
    else setV(String(value))
  }
  return (
    <span className="ap-num">
      {prefix}<input type="number" value={v} min={min} max={max} step={step} disabled={disabled} onChange={(e) => setV(e.target.value)}
        onBlur={commit} onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }} />{suffix}
    </span>
  )
}
