import { useCallback, useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link, useSearchParams } from 'react-router-dom'
import { PageHead } from '../components/PageHead'
import { EquityLine } from '../components/EquityLine'
import { useT } from '../i18n'
import './LibraryPage.css'

/**
 * The strategy library — every well-known rule (and the same rules on twenty popular
 * stocks), backtested one way: after costs, total return, cash at the T-bill rate, the
 * record split at 2015, compared with simply holding the same instrument, and graded
 * after a deflation for how many rules were tried. Most lose to buying and holding; the
 * page says so. A signed-in reader can also write a rule (or describe one to the LLM),
 * backtest it the same way, and send it to Autopilot on a paper account.
 *
 * Data: /api/v1/autopilot/library (data_pipeline/run_library.py, refreshed weekly).
 */

const API = '/api/v1/autopilot'
const TOKEN_KEY = 'sa_ap_token'
type Grade = 'A' | 'B' | 'C' | 'D' | 'F' | 'N'
const GRADES: Grade[] = ['A', 'B', 'C', 'D', 'F']
const FAMILIES = ['trend', 'reversion', 'seasonal', 'volatility', 'allocation', 'earnings'] as const
type Fam = (typeof FAMILIES)[number]
type W = { cagr: number | null; sharpe: number | null; max_dd: number | null; start?: string }
type Filter = { template: string; params: Record<string, number> }
type Row = {
  id: string; family: Fam; template: string; params: Record<string, any>; assets: string[]; filters?: Filter[]; bench: string
  source: string; published: number | null; executable: boolean; note: string; grade: Grade; dsr: number | null
  oos: W; bench_oos: W; full: W; alpha_t: number | null; alpha_t_oos: number | null; exposure: number | null; entries_yr: number | null
}
type Stats = { cagr?: number; sharpe?: number | null; max_dd?: number; vol?: number; start?: string; end?: string; years_up?: number; years_total?: number; cash_cagr?: number }
type Alpha = { alpha?: number; alpha_t?: number; beta?: number }
type Detail = Row & {
  full: Stats; bench_full: Stats; oos: Stats; bench_oos: Stats; is: Stats; bench_is: Stats
  alpha: Alpha; alpha_oos: Alpha; alpha_is: Alpha; post: (Stats & { from: string; bench: Stats; alpha: Alpha }) | null
  activity: { exposure: number; entries_yr: number; turnover_yr: number; avg_hold: number | null }
  curve?: { s: { t: string; v: number }[]; b: { t: string; v: number }[] } | null; trials?: number; now?: Record<string, number>
}
type Tpl = { t: string; kind: 'single' | 'multi' | 'earnings'; bounds: Record<string, [number, number]>; live: boolean; fixed: string[] | null }
type Table = { generated_at?: string; split?: string; trials?: number; count: number; grades?: Record<string, number>; rows: Row[]; templates: Tpl[] }
type Mine = { id: string; name: string; spec: Spec; origin: 'llm' | 'manual'; prompt: string | null; thesis: string | null; created_at: string
  grade: Grade | null; executable: boolean | null; brief: Row | null }
type Spec = { template: string; params: Record<string, any>; assets: string[]; filters?: Filter[] }
type Saved = { id: string; name: string; spec: Spec; origin: string; thesis: string | null; result: Detail; tried: number }
type Conn = { id: number; broker: string; name?: string; mode: 'paper' | 'live'; account_hint: string
  settings: { library?: Record<string, { on: boolean; alloc: number }>; strategies: Record<string, { on: boolean; alloc: number }>; enabled: boolean } }

function token(): string | null { try { return localStorage.getItem(TOKEN_KEY) } catch { return null } }

async function call<T>(path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  const tk = token()
  const r = await fetch(API + path, {
    method: opts.method ?? 'GET',
    headers: { 'Content-Type': 'application/json', ...(tk ? { 'X-Autopilot-Token': tk } : {}) },
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
  })
  if (!r.ok) {
    let msg = `${r.status}`
    try { const j = await r.json(); msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail ?? j) } catch { /* not json */ }
    throw new Error(msg)
  }
  return r.json() as Promise<T>
}

const pct = (v: number | null | undefined, d = 1) => (v == null ? '—' : `${v >= 0 ? '+' : '−'}${Math.abs(v * 100).toFixed(d)}%`)
const pctAbs = (v: number | null | undefined, d = 0) => (v == null ? '—' : `${(v * 100).toFixed(d)}%`)
const num = (v: number | null | undefined, d = 2) => (v == null ? '—' : v.toFixed(d))
const tone = (v: number | null | undefined) => (v == null ? '' : v > 0 ? 'is-up' : v < 0 ? 'is-down' : '')

export function useRuleName() {
  const { t } = useT()
  return useCallback((r: { id: string; family?: string; template: string; params: Record<string, any>; filters?: Filter[] }, name?: string) => {
    if (name) return name
    const key = (r.family === 'allocation' && !r.id.startsWith('u') ? `lib.t.${r.id}` : `lib.t.${r.template}`) as 'lib.t.rsi2'
    const base = t(key)
    const ps = r.template === 'static' ? '' : Object.entries(r.params || {}).map(([k, v]) => `${k}=${v}`).join(' ')
    const f = (r.filters || []).map((x) => ` + ${t(`lib.t.${x.template}` as 'lib.t.rsi2')}${Object.keys(x.params).length ? ` (${Object.entries(x.params).map(([k, v]) => `${k}=${v}`).join(' ')})` : ''}`).join('')
    return `${base}${ps && r.family !== 'allocation' ? ` (${ps})` : ''}${f}`
  }, [t])
}

export function LibraryPage() {
  const { t } = useT()
  const [params, setParams] = useSearchParams()
  const [tab, setTab] = useState<Table | null>(null)
  const [err, setErr] = useState(false)
  const [fam, setFam] = useState<Fam | 'all'>('all')
  const [grade, setGrade] = useState<Grade | 'all'>('all')
  const [kind, setKind] = useState<'all' | 'index' | 'stock' | 'portfolio'>('all')
  const [liveOnly, setLiveOnly] = useState(false)
  const [q, setQ] = useState('')
  const [sort, setSort] = useState<'grade' | 'alpha' | 'cagr' | 'sharpe' | 'dd'>('grade')
  const [mine, setMine] = useState<Mine[] | null>(null)
  const open = params.get('s')
  const setOpen = (id: string | null) => { const n = new URLSearchParams(params); if (id) n.set('s', id); else n.delete('s'); setParams(n, { replace: true }) }
  const name = useRuleName()

  useEffect(() => { call<Table>('/library').then(setTab).catch(() => setErr(true)) }, [])
  const loadMine = useCallback(() => { if (token()) call<{ rows: Mine[] }>('/library/mine').then((d) => setMine(d.rows)).catch(() => setMine(null)) }, [])
  useEffect(() => { loadMine() }, [loadMine])

  const rows = useMemo(() => {
    if (!tab) return []
    const order: Record<string, number> = { A: 0, B: 1, C: 2, D: 3, F: 4, N: 5 }
    const ql = q.trim().toUpperCase()
    const out = tab.rows.filter((r) => (fam === 'all' || r.family === fam) && (grade === 'all' || r.grade === grade)
      && (!liveOnly || r.executable)
      && (kind === 'all' || (kind === 'portfolio' ? r.assets.length > 1 : kind === 'index' ? r.assets.length === 1 && ['SPY', 'QQQ', 'IWM', 'DIA'].includes(r.assets[0]) : r.assets.length === 1 && !['SPY', 'QQQ', 'IWM', 'DIA'].includes(r.assets[0])))
      && (!ql || r.assets.some((a) => a.includes(ql)) || r.id.toUpperCase().includes(ql) || name(r).toUpperCase().includes(ql)))
    const k = (r: Row) => sort === 'grade' ? order[r.grade] * 100 - (r.alpha_t ?? 0) : sort === 'alpha' ? -(r.alpha_t ?? -99)
      : sort === 'cagr' ? -(r.oos.cagr ?? -9) : sort === 'sharpe' ? -((r.oos.sharpe ?? -9) - (r.bench_oos.sharpe ?? 0)) : -(r.oos.max_dd ?? -9)
    return out.sort((a, b) => k(a) - k(b))
  }, [tab, fam, grade, kind, liveOnly, q, sort, name])

  const g = tab?.grades ?? {}
  return (
    <div className="page-stack lib">
      <PageHead kicker={t('nav.library')} title={<>{t('lib.h.a')} <em>{t('lib.h.b')}</em></>}
        lede={t('lib.h.lede', { n: tab?.count ?? '…' })} spike={0.3}>
        {tab?.count ? (
          <div className="lib-grades">
            {GRADES.map((x) => (
              <button key={x} className={`lib-g lib-g--${x} ${grade === x ? 'is-on' : ''}`} onClick={() => setGrade(grade === x ? 'all' : x)}>
                <b>{x}</b><span>{g[x] ?? 0}</span>
              </button>
            ))}
          </div>
        ) : null}
      </PageHead>

      <details className="lib-how">
        <summary>{t('lib.how.title')}</summary>
        <ul>
          <li>{t('lib.how.1')}</li><li>{t('lib.how.2', { trials: tab?.trials ?? '…' })}</li><li>{t('lib.how.3')}</li>
          <li>{t('lib.how.4')}</li><li>{t('lib.how.5')}</li>
        </ul>
        <p className="lib-dim">{t('lib.how.grades')}</p>
      </details>

      <Brainstorm templates={tab?.templates ?? []} onSaved={(s) => { loadMine(); setOpen(s.id) }} />

      {mine && mine.length > 0 && (
        <section className="lib-mine">
          <h2>{t('lib.mine.title')} <span className="lib-dim">· {t('lib.mine.tried', { n: mine.length })}</span></h2>
          <ul>
            {mine.map((m) => (
              <li key={m.id}>
                <button className="lib-mine__row" onClick={() => setOpen(m.id)}>
                  <span className={`lib-badge lib-g--${m.grade ?? 'N'}`}>{m.grade ?? '—'}</span>
                  <b>{m.name}</b>
                  <span className="lib-dim">{m.spec.assets.join(', ')} · {m.origin === 'llm' ? t('lib.mine.llm') : t('lib.mine.manual')}</span>
                  {m.brief && <span className={tone((m.brief.oos.sharpe ?? 0) - (m.brief.bench_oos.sharpe ?? 0))}>Sharpe {num(m.brief.oos.sharpe)} / {num(m.brief.bench_oos.sharpe)}</span>}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="lib-filters">
        <div className="lib-chips">
          <button className={fam === 'all' ? 'is-on' : ''} onClick={() => setFam('all')}>{t('lib.f.all')}</button>
          {FAMILIES.map((f) => <button key={f} className={fam === f ? 'is-on' : ''} onClick={() => setFam(f)}>{t(`lib.fam.${f}` as 'lib.fam.trend')}</button>)}
        </div>
        <div className="lib-chips">
          {(['all', 'index', 'stock', 'portfolio'] as const).map((k) => <button key={k} className={kind === k ? 'is-on' : ''} onClick={() => setKind(k)}>{t(`lib.k.${k}` as 'lib.k.all')}</button>)}
          <label className="lib-check"><input type="checkbox" checked={liveOnly} onChange={(e) => setLiveOnly(e.target.checked)} /> {t('lib.f.live')}</label>
          <input className="lib-search" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('lib.f.search')} />
        </div>
      </section>

      {err ? <p className="lib-dim">{t('lib.err')}</p> : !tab ? <div className="shimmer" style={{ height: 300 }} /> : (
        <section className="lib-table-wrap">
          <table className="lib-table">
            <thead>
              <tr>
                <th>{t('lib.c.rule')}</th><th>{t('lib.c.on')}</th>
                <th className="is-sort" onClick={() => setSort('grade')}>{t('lib.c.grade')}{sort === 'grade' ? ' ↓' : ''}</th>
                <th className="is-sort is-num" onClick={() => setSort('cagr')}>{t('lib.c.cagr')}{sort === 'cagr' ? ' ↓' : ''}</th>
                <th className="is-sort is-num" onClick={() => setSort('sharpe')}>{t('lib.c.sharpe')}{sort === 'sharpe' ? ' ↓' : ''}</th>
                <th className="is-sort is-num" onClick={() => setSort('dd')}>{t('lib.c.dd')}{sort === 'dd' ? ' ↓' : ''}</th>
                <th className="is-sort is-num" onClick={() => setSort('alpha')}>{t('lib.c.alpha')}{sort === 'alpha' ? ' ↓' : ''}</th>
                <th className="is-num">{t('lib.c.exposure')}</th>
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 300).map((r) => (
                <tr key={r.id} onClick={() => setOpen(r.id)} className={open === r.id ? 'is-open' : ''}>
                  <td><b>{name(r)}</b><span className="lib-dim">{t(`lib.fam.${r.family}` as 'lib.fam.trend')}{r.executable ? '' : ` · ${t('lib.notLive')}`}</span></td>
                  <td>{r.assets.length > 3 ? `${r.assets.slice(0, 3).join(', ')} +${r.assets.length - 3}` : r.assets.join(', ')}</td>
                  <td><span className={`lib-badge lib-g--${r.grade}`}>{r.grade}</span></td>
                  <td className="is-num">{pct(r.oos.cagr)} <span className="lib-dim">/ {pct(r.bench_oos.cagr)}</span></td>
                  <td className={`is-num ${tone((r.oos.sharpe ?? 0) - (r.bench_oos.sharpe ?? 0))}`}>{num(r.oos.sharpe)} <span className="lib-dim">/ {num(r.bench_oos.sharpe)}</span></td>
                  <td className="is-num">{pctAbs(r.oos.max_dd)} <span className="lib-dim">/ {pctAbs(r.bench_oos.max_dd)}</span></td>
                  <td className={`is-num ${tone(r.alpha_t)}`}>{num(r.alpha_t, 1)}</td>
                  <td className="is-num">{pctAbs(r.exposure)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length > 300 && <p className="lib-dim">{t('lib.more', { n: rows.length - 300 })}</p>}
          {!rows.length && <p className="lib-dim">{t('lib.none')}</p>}
          <p className="lib-dim lib-foot">{t('lib.foot', { at: tab.generated_at?.slice(0, 10) ?? '—', split: tab.split ?? '2015' })}</p>
        </section>
      )}

      {open && createPortal(<DetailPanel id={open} mine={mine?.find((m) => m.id === open) ?? null} trials={tab?.trials}
        onClose={() => setOpen(null)} onDeleted={() => { setOpen(null); loadMine() }} />, document.body)}
    </div>
  )
}

/* ───────────────────────── one strategy ───────────────────────── */

function DetailPanel({ id, mine, trials, onClose, onDeleted }: { id: string; mine: Mine | null; trials?: number; onClose: () => void; onDeleted: () => void }) {
  const { t } = useT()
  const name = useRuleName()
  const [d, setD] = useState<Detail | null>(null)
  const [meta, setMeta] = useState<{ name?: string; thesis?: string | null; prompt?: string | null } | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    setD(null); setErr(null)
    call<any>(`/library/${encodeURIComponent(id)}`)
      .then((x) => { if (x.result) { setD({ ...x.result, id }); setMeta({ name: x.name, thesis: x.thesis, prompt: x.prompt }) } else { setD(x); setMeta(null) } })
      .catch((e) => setErr((e as Error).message))
  }, [id])
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [onClose])
  const del = async () => {
    if (!window.confirm(t('lib.d.delConfirm'))) return
    try { await call(`/library/${id}`, { method: 'DELETE' }); onDeleted() } catch (e) { setErr((e as Error).message) }
  }
  const win = (label: string, s?: Stats, b?: Stats, a?: Alpha) => s?.cagr == null ? null : (
    <tr>
      <th>{label}<span className="lib-dim">{s.start?.slice(0, 4)}–{s.end?.slice(0, 4)}</span></th>
      <td className="is-num">{pct(s.cagr)}<span className="lib-dim">{pct(b?.cagr)}</span></td>
      <td className={`is-num ${tone((s.sharpe ?? 0) - (b?.sharpe ?? 0))}`}>{num(s.sharpe)}<span className="lib-dim">{num(b?.sharpe)}</span></td>
      <td className="is-num">{pctAbs(s.max_dd)}<span className="lib-dim">{pctAbs(b?.max_dd)}</span></td>
      <td className={`is-num ${tone(a?.alpha)}`}>{pct(a?.alpha)}<span className="lib-dim">t {num(a?.alpha_t, 1)}</span></td>
    </tr>
  )
  return (
    <div className="lib-panel" role="dialog" aria-modal="true">
      <div className="lib-panel__scrim" onClick={onClose} />
      <aside className="lib-panel__body">
        <button className="lib-panel__x" onClick={onClose} aria-label={t('lib.d.close')}>×</button>
        {err ? <p className="lib-dim">{err}</p> : !d ? <div className="shimmer" style={{ height: 320 }} /> : (
          <>
            <div className="lib-panel__head">
              <span className={`lib-badge lib-badge--lg lib-g--${d.grade}`}>{d.grade}</span>
              <div>
                <h2>{name(d, meta?.name)}</h2>
                <p className="lib-dim">{d.assets.join(', ')} · {t('lib.d.vs', { b: d.family === 'allocation' ? 'SPY' : t('lib.d.holding', { b: d.bench }) })}</p>
              </div>
            </div>
            <p className="lib-grade-say">{t(`lib.g.${d.grade}` as 'lib.g.A')}</p>
            {meta?.thesis && <p className="lib-thesis">{meta.thesis}</p>}
            {d.curve?.s?.length ? <EquityLine series={d.curve.s} bench={d.curve.b} benchLabel={d.family === 'allocation' ? 'SPY' : d.bench} /> : null}
            <table className="lib-win">
              <thead><tr><th /><th className="is-num">{t('lib.d.cagr')}</th><th className="is-num">Sharpe</th><th className="is-num">{t('lib.d.dd')}</th><th className="is-num">{t('lib.d.alpha')}</th></tr></thead>
              <tbody>
                {win(t('lib.d.full'), d.full, d.bench_full, d.alpha)}
                {win(t('lib.d.is'), d.is, d.bench_is, d.alpha_is)}
                {win(t('lib.d.oos'), d.oos, d.bench_oos, d.alpha_oos)}
                {d.post && win(t('lib.d.post', { y: d.post.from.slice(0, 4) }), d.post, d.post.bench, d.post.alpha)}
              </tbody>
            </table>
            <p className="lib-dim lib-small">{t('lib.d.legend')}</p>
            <div className="lib-facts">
              <div><span>{t('lib.d.dsr')}</span><b>{d.dsr == null ? '—' : `${Math.round(d.dsr * 100)}%`}</b><em>{t('lib.d.dsrSay', { n: d.trials ?? trials ?? '—' })}</em></div>
              <div><span>{t('lib.d.exposure')}</span><b>{pctAbs(d.activity?.exposure)}</b></div>
              <div><span>{t('lib.d.entries')}</span><b>{num(d.activity?.entries_yr, 1)}</b></div>
              <div><span>{t('lib.d.hold')}</span><b>{d.activity?.avg_hold == null ? '—' : t('lib.d.days', { n: Math.round(d.activity.avg_hold) })}</b></div>
            </div>
            <p className="lib-src"><span className="lib-dim">{t('lib.d.source')}</span> {d.source === 'custom' ? t('lib.d.custom') : d.source}</p>
            {d.now && Object.keys(d.now).length > 0 && <p className="lib-dim">{t('lib.d.now', { w: Object.entries(d.now).map(([a, v]) => `${a} ${Math.round(v * 100)}%`).join(', ') })}</p>}
            {d.executable ? <RunIt id={id} /> : <p className="lib-note">{t((d.note || 'lib.note.earnings') as 'lib.note.earnings')}</p>}
            {mine && <button className="ap-link lib-del" onClick={del}>{t('lib.d.delete')}</button>}
          </>
        )}
      </aside>
    </div>
  )
}

/** Switch a strategy on in one of the reader's Autopilot connections (paper by default). */
function RunIt({ id }: { id: string }) {
  const { t } = useT()
  const [accts, setAccts] = useState<Conn[] | null>(null)
  const [pick, setPick] = useState<number | null>(null)
  const [alloc, setAlloc] = useState(10)
  const [msg, setMsg] = useState<{ ok: boolean; m: string } | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (!token()) { setAccts([]); return }
    call<{ accounts: Conn[] }>('/me').then((m) => { setAccts(m.accounts); setPick(m.accounts.find((a) => a.mode === 'paper')?.id ?? m.accounts[0]?.id ?? null) })
      .catch(() => setAccts([]))
  }, [])
  if (accts === null) return null
  if (!token() || !accts.length) return <p className="lib-run lib-dim">{t('lib.run.connect')} <Link to="/autopilot">{t('lib.run.go')}</Link></p>
  const conn = accts.find((a) => a.id === pick)
  const on = conn?.settings.library?.[id]?.on
  const used = conn ? [...Object.values(conn.settings.strategies ?? {}), ...Object.entries(conn.settings.library ?? {}).filter(([k]) => k !== id).map(([, v]) => v)]
    .reduce((n, x) => n + (x.on ? x.alloc : 0), 0) : 0
  const free = Math.max(0, Math.round(100 - used))
  const go = async (turnOn: boolean) => {
    if (!conn) return
    if (turnOn && conn.mode === 'live' && !window.confirm(t('lib.run.liveConfirm'))) return
    setBusy(true); setMsg(null)
    try {
      await call(`/accounts/${conn.id}/settings`, { method: 'PUT', body: { library: { [id]: turnOn ? { on: true, alloc } : null } } })
      const m = await call<{ accounts: Conn[] }>('/me'); setAccts(m.accounts)
      setMsg({ ok: true, m: turnOn ? t('lib.run.on', { a: alloc }) : t('lib.run.off') })
    } catch (e) { setMsg({ ok: false, m: (e as Error).message }) } finally { setBusy(false) }
  }
  return (
    <div className="lib-run">
      <b>{t('lib.run.title')}</b>
      <div className="lib-run__row">
        <select value={pick ?? ''} onChange={(e) => setPick(Number(e.target.value))}>
          {accts.map((a) => <option key={a.id} value={a.id}>{a.name ?? a.broker} · {a.mode === 'paper' ? t('ap.mode.paper') : t('ap.mode.live')} …{a.account_hint}</option>)}
        </select>
        {!on && <label>{t('lib.run.alloc')} <input type="number" min={1} max={100} value={alloc} onChange={(e) => setAlloc(Math.max(1, Math.min(100, Number(e.target.value) || 1)))} />%</label>}
        {on ? <button className="btn" disabled={busy} onClick={() => go(false)}>{t('lib.run.stop')}</button>
          : <button className="btn btn-primary" disabled={busy || alloc > free} onClick={() => go(true)}>{t('lib.run.start')}</button>}
      </div>
      {!on && <p className={`lib-small ${alloc > free ? 'is-down' : 'lib-dim'}`}>{t('lib.run.free', { n: free })}{alloc > free ? <> {t('lib.run.full')} <Link to="/autopilot">{t('lib.run.go')}</Link></> : null}</p>}
      <p className="lib-dim lib-small">{t('lib.run.how')}{conn && !conn.settings.enabled ? ` ${t('lib.run.apOff')}` : ''}</p>
      {msg && <p className={msg.ok ? 'is-up' : 'is-down'}>{msg.m}</p>}
    </div>
  )
}

/* ───────────────────────── write or brainstorm a rule ───────────────────────── */

function Brainstorm({ templates, onSaved }: { templates: Tpl[]; onSaved: (s: Saved) => void }) {
  const { t, locale } = useT()
  const [mode, setMode] = useState<'llm' | 'manual'>('llm')
  const [prompt, setPrompt] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [last, setLast] = useState<Saved | null>(null)
  const [tpl, setTpl] = useState('rsi2')
  const [assets, setAssets] = useState('SPY')
  const [ps, setPs] = useState<Record<string, number>>({ lo: 10 })
  const [flt, setFlt] = useState('')
  const [fps, setFps] = useState<Record<string, number>>({})
  const name = useRuleName()
  const T = templates.find((x) => x.t === tpl)
  const F = templates.find((x) => x.t === flt)
  const signed = !!token()

  const pickTpl = (v: string) => {
    setTpl(v)
    const x = templates.find((y) => y.t === v)
    setPs(Object.fromEntries(Object.entries(x?.bounds ?? {}).map(([k, [lo, hi]]) => [k, Number.isInteger(lo) && Number.isInteger(hi) ? Math.round((lo + hi) / 4) || lo : lo])))
    if (x?.fixed) setAssets(x.fixed.join(', '))
  }
  const pickFlt = (v: string) => {
    setFlt(v)
    const x = templates.find((y) => y.t === v)
    setFps(Object.fromEntries(Object.entries(x?.bounds ?? {}).map(([k, [lo]]) => [k, lo])))
  }
  const run = async () => {
    setBusy(true); setErr(null)
    try {
      const s = mode === 'llm'
        ? await call<Saved>('/library/brainstorm', { method: 'POST', body: { prompt, lang: locale, base: last?.spec ?? null } })
        : await call<Saved>('/library/backtest', { method: 'POST', body: {
            spec: { template: tpl, params: tpl === 'static' ? { w: Object.fromEntries(assets.split(',').map((a) => a.trim().split(':')).filter((x) => x[0]).map(([a, w]) => [a.toUpperCase(), Number(w) || 0])) } : ps,
              assets: assets.split(',').map((a) => a.trim().split(':')[0]).filter(Boolean), filters: flt ? [{ template: flt, params: fps }] : [] },
            name: '' } })
      setLast(s); onSaved(s)
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  return (
    <section className="lib-lab">
      <div className="lib-lab__head">
        <h2>{t('lib.lab.title')}</h2>
        <div className="lib-chips">
          <button className={mode === 'llm' ? 'is-on' : ''} onClick={() => setMode('llm')}>{t('lib.lab.llm')}</button>
          <button className={mode === 'manual' ? 'is-on' : ''} onClick={() => setMode('manual')}>{t('lib.lab.manual')}</button>
        </div>
      </div>
      <p className="lib-dim">{t('lib.lab.lede')}</p>
      {!signed ? <p>{t('lib.lab.signin')} <Link to="/autopilot">{t('lib.run.go')}</Link></p> : mode === 'llm' ? (
        <div className="lib-lab__llm">
          <textarea rows={3} value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder={t('lib.lab.ph')} maxLength={1500} />
          <div className="lib-lab__go">
            {last && <span className="lib-dim">{t('lib.lab.refine', { n: last.name })}</span>}
            {last && <button className="ap-link" onClick={() => setLast(null)}>{t('lib.lab.fresh')}</button>}
            <button className="btn btn-primary" disabled={busy || prompt.trim().length < 4} onClick={run}>{busy ? t('lib.lab.busy') : t('lib.lab.go')}</button>
          </div>
          <div className="lib-lab__ideas">
            {(['1', '2', '3', '4'] as const).map((k) => <button key={k} className="ap-link" onClick={() => setPrompt(t(`lib.lab.idea${k}` as 'lib.lab.idea1'))}>{t(`lib.lab.idea${k}` as 'lib.lab.idea1')}</button>)}
          </div>
        </div>
      ) : (
        <div className="lib-lab__form">
          <label>{t('lib.lab.tpl')}
            <select value={tpl} onChange={(e) => pickTpl(e.target.value)}>
              {templates.map((x) => <option key={x.t} value={x.t}>{t(`lib.t.${x.t}` as 'lib.t.rsi2')}{x.live ? '' : ` · ${t('lib.notLive')}`}</option>)}
            </select>
          </label>
          <label>{tpl === 'static' ? t('lib.lab.weights') : T?.kind === 'multi' ? t('lib.lab.assets') : t('lib.lab.asset')}
            <input value={assets} onChange={(e) => setAssets(e.target.value.toUpperCase())} disabled={!!T?.fixed} placeholder={tpl === 'static' ? 'SPY:0.6, TLT:0.4' : 'NVDA'} />
          </label>
          {Object.entries(T?.bounds ?? {}).map(([k, [lo, hi]]) => (
            <label key={k}>{k} <span className="lib-dim">{lo}–{hi}</span>
              <input type="number" step="any" value={ps[k] ?? ''} onChange={(e) => setPs({ ...ps, [k]: Number(e.target.value) })} />
            </label>
          ))}
          {T?.kind === 'single' && (
            <label>{t('lib.lab.filter')}
              <select value={flt} onChange={(e) => pickFlt(e.target.value)}>
                <option value="">—</option>
                {templates.filter((x) => x.kind === 'single' && x.t !== 'buy_hold').map((x) => <option key={x.t} value={x.t}>{t(`lib.t.${x.t}` as 'lib.t.rsi2')}</option>)}
              </select>
            </label>
          )}
          {F && Object.entries(F.bounds).map(([k, [lo, hi]]) => (
            <label key={`f-${k}`}>{t('lib.lab.filter')} {k} <span className="lib-dim">{lo}–{hi}</span>
              <input type="number" step="any" value={fps[k] ?? ''} onChange={(e) => setFps({ ...fps, [k]: Number(e.target.value) })} />
            </label>
          ))}
          <button className="btn btn-primary" disabled={busy} onClick={run}>{busy ? t('lib.lab.busy') : t('lib.lab.test')}</button>
        </div>
      )}
      {err && <p className="is-down">{err}</p>}
      {last && (
        <div className="lib-lab__out">
          <span className={`lib-badge lib-g--${last.result.grade}`}>{last.result.grade}</span>
          <b>{last.name}</b> <span className="lib-dim">{name(last.result)} · {last.spec.assets.join(', ')}</span>
          <span className="lib-dim">{t('lib.lab.tried', { n: last.tried })}</span>
        </div>
      )}
    </section>
  )
}
