import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { Anchor, CheckCircle2, Lock, ShieldCheck, Timer, XCircle } from 'lucide-react'
import { useT } from '../i18n'
import { formatDateShort } from '../utils/date'
import { PageHead } from '../components/PageHead'
import { Num } from '../components/ui/Num'
import './ArenaPage.css'

/**
 * Earnings Arena — forecasters seal a call before every report, then get graded.
 *
 * The page exists to answer the question the "let an AI trade for you" products skip:
 * does any of this have skill, measured in a way luck can't fake? So every element is
 * about the evidence trail: what was called, when it was sealed (and the hash that pins
 * it), what happened, and whether the running score is distinguishable from the base
 * rate yet. Visitors can drop their own call on any open report; those stay on this
 * device and are graded against the same outcomes.
 */

type Call = {
  forecaster: string; p: number; lean: 'UP' | 'DOWN' | null; rationale: string | null
  digest: string; payload: string; sealed_at: string; anchor_id: number | null; brier: number | null
}
type ArenaEvent = {
  ticker: string; company: string | null; sector: string | null; earnings_date: string
  report_time: string | null; band: number; implied_move: number | null; cutoff: string
  actual_move: number | null; broke_out: boolean | null; calls: Call[]
}
type Forecaster = { code: string; name: string; kind: string; provider: string; blurb: string; active: boolean; calls: number }
type Lb = { code: string; n: number; brier: number; skill?: number; skill_lo?: number; skill_hi?: number; bss?: number; verdict: string; dir_n?: number; dir_hit?: number; dir_lo?: number; dir_hi?: number }
type Board = {
  season: { id: string; name: string; opened: string }
  question: string
  forecasters: Forecaster[]
  leaderboard: Lb[]
  pending: ArenaEvent[]
  resolved: ArenaEvent[]
  queued: { ticker: string; company: string | null; earnings_date: string; report_time: string | null; opens: string }[]
  anchors: { id: number; root: string; calendars: string; created_at: string; calls: number }[]
  totals: { calls: number; graded: number; events: number; voided?: number }
  voided?: { ticker: string; earnings_date: string; calls: number; sealed_at: string; voided_at: string
    band: number; implied_move: number | null; anchor_id: number | null; reason: string }[]
}
type MyCall = { p: number; lean: 'UP' | 'DOWN' | null; at: string }

const COLOR: Record<string, string> = {
  signalpha_ml: 'var(--accent-cyan)',
  options_market: 'var(--accent-amber)',
  base_rate: 'var(--text-tertiary)',
  gpt_oss_120b: 'var(--accent-emerald)',
  qwen3: 'var(--accent-purple)',
  claude: '#f4a27a',
  you: 'var(--text-primary)',
}
const GLYPH: Record<string, string> = {
  signalpha_ml: 'ML', options_market: 'OPT', base_rate: 'BR', gpt_oss_120b: 'GPT', qwen3: 'QW', claude: 'CL', you: 'YOU',
}

const MINE_KEY = 'sa_arena_mine_v1'
const keyOf = (e: { ticker: string; earnings_date: string }) => `${e.ticker}|${e.earnings_date}`

function loadMine(): Record<string, MyCall> {
  try { return JSON.parse(localStorage.getItem(MINE_KEY) || '{}') } catch { return {} }
}
function saveMine(m: Record<string, MyCall>) {
  try { localStorage.setItem(MINE_KEY, JSON.stringify(m)) } catch { /* storage blocked: calls live for this visit */ }
}

function useNow(ms = 30_000) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => { const id = setInterval(() => setNow(Date.now()), ms); return () => clearInterval(id) }, [ms])
  return now
}

function countdown(target: string, now: number): string {
  const s = Math.max(0, Math.floor((new Date(target).getTime() - now) / 1000))
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60)
  return d > 0 ? `${d}d ${h}h` : h > 0 ? `${h}h ${m}m` : `${m}m`
}

async function sha256Hex(text: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))
  return Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, '0')).join('')
}

const pct = (v: number | null | undefined, d = 0) => (v == null ? '—' : `${(v * 100).toFixed(d)}%`)

/* ───────────────────────── probability strip ───────────────────────── */

function ProbStrip({ ev, names, baseRate, mine, onMine, locked }: {
  ev: ArenaEvent; names: Record<string, string>; baseRate: number | null
  mine?: MyCall; onMine?: (p: number) => void; locked: boolean
}) {
  const { t } = useT()
  const ref = useRef<HTMLDivElement | null>(null)
  const [hover, setHover] = useState<Call | null>(null)
  const [drag, setDrag] = useState(false)

  // Calls a few points apart would print on top of each other; spread them over three
  // lanes (middle, above, below) so every forecaster stays visible and hoverable.
  const laned = useMemo(() => {
    const lanes = [0, -1, 1]
    const last: Record<number, number> = {}
    return [...ev.calls].sort((a, b) => a.p - b.p).map((c) => {
      const lane = lanes.find((l) => last[l] === undefined || c.p - last[l] > 0.06) ?? lanes[0]
      last[lane] = c.p
      return { c, lane }
    })
  }, [ev.calls])

  const place = (clientX: number) => {
    const el = ref.current
    if (!el || !onMine) return
    const r = el.getBoundingClientRect()
    onMine(Math.round(Math.min(0.99, Math.max(0.01, (clientX - r.left) / r.width)) * 100) / 100)
  }

  return (
    <div className="arena-strip">
      <div
        ref={ref}
        className={`arena-strip__track${!locked && onMine ? ' is-open' : ''}`}
        onPointerDown={(e) => { if (locked || !onMine) return; (e.target as HTMLElement).setPointerCapture?.(e.pointerId); setDrag(true); place(e.clientX) }}
        onPointerMove={(e) => { if (drag) place(e.clientX) }}
        onPointerUp={() => setDrag(false)}
        role={!locked && onMine ? 'slider' : undefined}
        aria-label={t('arena.you.slider')}
        aria-valuenow={mine ? Math.round(mine.p * 100) : undefined}
        tabIndex={!locked && onMine ? 0 : -1}
        onKeyDown={(e) => {
          if (locked || !onMine) return
          const cur = mine?.p ?? 0.5
          if (e.key === 'ArrowRight') onMine(Math.min(0.99, +(cur + 0.01).toFixed(2)))
          if (e.key === 'ArrowLeft') onMine(Math.max(0.01, +(cur - 0.01).toFixed(2)))
        }}
      >
        {[0, 0.25, 0.5, 0.75, 1].map((x) => <span key={x} className="arena-strip__tick" style={{ left: `${x * 100}%` }} />)}
        {baseRate != null && <span className="arena-strip__base" style={{ left: `${baseRate * 100}%` }} title={t('arena.baseLine')} />}
        {laned.map(({ c, lane }, i) => (
          <motion.button
            key={c.forecaster}
            type="button"
            className="arena-strip__dot"
            style={{ left: `${c.p * 100}%`, top: `calc(50% + ${lane * 15}px)`, ['--c' as string]: COLOR[c.forecaster] ?? 'var(--text-secondary)' }}
            initial={{ opacity: 0, scale: 0.4 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.05 * i, type: 'spring', stiffness: 300, damping: 20 }}
            onMouseEnter={() => setHover(c)}
            onMouseLeave={() => setHover(null)}
            onFocus={() => setHover(c)}
            onBlur={() => setHover(null)}
            onPointerDown={(e) => e.stopPropagation()}
            aria-label={`${names[c.forecaster] ?? c.forecaster} ${pct(c.p)}`}
          >
            <span>{GLYPH[c.forecaster] ?? '?'}</span>
          </motion.button>
        ))}
        {mine && (
          <span className="arena-strip__you" style={{ left: `${mine.p * 100}%` }}>
            <b>{pct(mine.p)}</b>
          </span>
        )}
      </div>
      <div className="arena-strip__axis"><span>0%</span><span>50%</span><span>100%</span></div>
      <div className="arena-strip__legend">
        {[...ev.calls].sort((a, b) => b.p - a.p).map((c) => (
          <span key={c.forecaster} style={{ ['--c' as string]: COLOR[c.forecaster] }}
            onMouseEnter={() => setHover(c)} onMouseLeave={() => setHover(null)}>
            <i />{names[c.forecaster] ?? c.forecaster} <b>{pct(c.p)}</b>{c.lean ? <em>{c.lean === 'UP' ? '↑' : '↓'}</em> : null}
          </span>
        ))}
      </div>
      <AnimatePresence>
        {hover && (
          <motion.div className="arena-strip__tip" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
            <b style={{ color: COLOR[hover.forecaster] }}>{names[hover.forecaster] ?? hover.forecaster}</b>
            <span className="mono"> {pct(hover.p, 1)}{hover.lean ? ` · ${t('arena.lean')} ${hover.lean}` : ''}</span>
            {hover.rationale && <p>{hover.rationale}</p>}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

/* ───────────────────────── seal verification ───────────────────────── */

function VerifyPanel({ call, name }: { call: Call; name: string }) {
  const { t } = useT()
  const [state, setState] = useState<'idle' | 'ok' | 'bad' | 'na'>('idle')
  const [hash, setHash] = useState('')
  const run = async () => {
    if (!window.crypto?.subtle) { setState('na'); return }
    const h = await sha256Hex(call.payload)
    setHash(h)
    setState(h === call.digest ? 'ok' : 'bad')
  }
  return (
    <div className={`arena-verify paper${state === 'ok' ? ' is-verified' : ''}`}>
      <span className="arena-verify__stamp" aria-hidden="true">{state === 'ok' ? t('arena.stamp.ok') : t('arena.stamp.sealed')}</span>
      <div className="arena-verify__head">
        <span style={{ color: COLOR[call.forecaster] }}>{name}</span>
        <span className="tertiary"> · {t('arena.sealedAt')} {new Date(call.sealed_at).toLocaleString()}</span>
      </div>
      <pre className="arena-verify__payload">{call.payload}</pre>
      <div className="arena-verify__row">
        <code className="arena-verify__digest">sha256 {call.digest}</code>
        <button type="button" className="btn arena-verify__btn" onClick={run}>
          <ShieldCheck size={13} /> {t('arena.verify.run')}
        </button>
      </div>
      {state === 'ok' && <p className="arena-verify__ok"><CheckCircle2 size={13} /> {t('arena.verify.ok')}</p>}
      {state === 'bad' && <p className="arena-verify__bad"><XCircle size={13} /> {t('arena.verify.bad')} <code>{hash}</code></p>}
      {state === 'na' && <p className="tertiary">{t('arena.verify.na')}</p>}
      {call.anchor_id != null ? (
        <p className="arena-verify__anchor">
          <Anchor size={12} /> {t('arena.verify.anchor')}{' '}
          <a href={`/api/v1/arena/anchors/${call.anchor_id}/manifest.txt`}>manifest</a> ·{' '}
          <a href={`/api/v1/arena/anchors/${call.anchor_id}/manifest.txt.ots`}>.ots proof</a>
          <code className="arena-verify__cmd">pip install opentimestamps-client && ots verify arena-{call.anchor_id}.txt.ots</code>
        </p>
      ) : (
        <p className="tertiary arena-verify__anchor"><Anchor size={12} /> {t('arena.verify.anchorPending')}</p>
      )}
    </div>
  )
}

/* ───────────────────────── leaderboard ───────────────────────── */

function SkillBar({ lo, hi, mid, scale }: { lo?: number; hi?: number; mid?: number; scale: number }) {
  if (mid == null || lo == null || hi == null) return <div className="arena-skill arena-skill--empty" />
  const x = (v: number) => `${50 + (Math.max(-scale, Math.min(scale, v)) / scale) * 50}%`
  const tone = lo > 0 ? 'good' : hi < 0 ? 'bad' : 'flat'
  return (
    <div className={`arena-skill arena-skill--${tone}`}>
      <span className="arena-skill__zero" />
      <span className="arena-skill__ci" style={{ left: x(lo), width: `calc(${x(hi)} - ${x(lo)})` }} />
      <span className="arena-skill__mid" style={{ left: x(mid) }} />
    </div>
  )
}

/* ───────────────────────── page ───────────────────────── */

export function ArenaPage() {
  const { t } = useT()
  const now = useNow()
  const [data, setData] = useState<Board | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [mine, setMine] = useState<Record<string, MyCall>>(() => loadMine())
  const [open, setOpen] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const r = await fetch('/api/v1/arena')
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      setData(await r.json())
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'failed')
    }
  }, [])
  useEffect(() => { load(); const id = setInterval(load, 120_000); return () => clearInterval(id) }, [load])

  const names = useMemo(() => {
    const m: Record<string, string> = { you: t('arena.you') }
    data?.forecasters.forEach((f) => { m[f.code] = f.name })
    return m
  }, [data, t])

  const baseRate = useMemo(() => {
    const c = data?.pending.flatMap((e) => e.calls).find((c) => c.forecaster === 'base_rate')
      ?? data?.resolved.flatMap((e) => e.calls).find((c) => c.forecaster === 'base_rate')
    return c?.p ?? null
  }, [data])

  // Your record: graded against the same outcomes, compared with the base rate on the
  // same events. Lives only in this browser.
  const myRow = useMemo(() => {
    if (!data) return null
    let n = 0, sum = 0, sumBase = 0, nb = 0
    for (const e of data.resolved) {
      const m = mine[keyOf(e)]
      if (!m || e.broke_out == null) continue
      const y = e.broke_out ? 1 : 0
      n += 1; sum += (m.p - y) ** 2
      const b = e.calls.find((c) => c.forecaster === 'base_rate')
      if (b) { nb += 1; sumBase += (b.p - y) ** 2 }
    }
    if (!n) return null
    return { n, brier: sum / n, skill: nb === n ? (sumBase - sum) / n : undefined }
  }, [data, mine])

  const setMyCall = (e: ArenaEvent, p: number) => {
    if (Date.now() >= new Date(e.cutoff).getTime()) return
    const next = { ...mine, [keyOf(e)]: { p, lean: mine[keyOf(e)]?.lean ?? null, at: new Date().toISOString() } }
    setMine(next); saveMine(next)
  }
  const setMyLean = (e: ArenaEvent, lean: 'UP' | 'DOWN' | null) => {
    const cur = mine[keyOf(e)]
    if (!cur || Date.now() >= new Date(e.cutoff).getTime()) return
    const next = { ...mine, [keyOf(e)]: { ...cur, lean } }
    setMine(next); saveMine(next)
  }

  if (error && !data) return <div className="empty-state">{t('arena.error')} ({error})</div>
  if (!data) return (
    <div className="arena">
      <div className="shimmer" style={{ height: 180 }} />
      <div className="shimmer" style={{ height: 320 }} />
    </div>
  )

  const scale = Math.max(0.03, ...data.leaderboard.flatMap((r) => [Math.abs(r.skill_lo ?? 0), Math.abs(r.skill_hi ?? 0)]))
  const lbByCode = Object.fromEntries(data.leaderboard.map((r) => [r.code, r]))
  const rows = data.forecasters.map((f) => ({ f, lb: lbByCode[f.code] as Lb | undefined }))
  rows.sort((a, b) => (a.lb?.brier ?? 9) - (b.lb?.brier ?? 9))

  return (
    <div className="arena">
      <PageHead
        kicker={data.season.name}
        title={<>{t('arena.h.a')} <em>{t('arena.h.b')}</em></>}
        lede={t('arena.lede')}
        spike={0.4}
      >
        <div className="figs">
          <div><b><Num value={data.totals.calls} /></b><span>{t('arena.stat.sealed')}</span></div>
          <div><b><Num value={data.totals.graded} /></b><span>{t('arena.stat.graded')}</span></div>
          <div className="is-signal"><b><Num value={data.anchors.length} /></b><span>{t('arena.stat.anchors')}</span></div>
        </div>
      </PageHead>

      <ol className="arena-steps">
        <li><b>{t('arena.step1.t')}</b><span>{t('arena.step1.d')}</span></li>
        <li><b>{t('arena.step2.t')}</b><span>{t('arena.step2.d')}</span></li>
        <li><b>{t('arena.step3.t')}</b><span>{t('arena.step3.d')}</span></li>
      </ol>

      {/* ── leaderboard ── */}
      <section className="card arena-board">
        <h3 className="card-title">{t('arena.board.title')}</h3>
        <p className="arena-board__note">{t('arena.board.note')}</p>
        <div className="arena-board__head">
          <span>{t('arena.board.who')}</span><span>{t('arena.board.n')}</span><span>Brier</span>
          <span>{t('arena.board.skill')}</span><span>{t('arena.board.dir')}</span><span>{t('arena.board.verdict')}</span>
        </div>
        {rows.map(({ f, lb }) => (
          <div key={f.code} className="arena-board__row">
            <div className="arena-who">
              <span className="arena-glyph" style={{ ['--c' as string]: COLOR[f.code] }}>{GLYPH[f.code]}</span>
              <div>
                <b>{f.name}</b>
                <span className="arena-who__prov">{f.provider}</span>
              </div>
            </div>
            <span className="mono">{lb?.n ?? 0}</span>
            <span className="mono">{lb ? lb.brier.toFixed(3) : '—'}</span>
            <SkillBar lo={lb?.skill_lo} hi={lb?.skill_hi} mid={lb?.skill} scale={scale} />
            <span className="mono arena-dir">
              {lb?.dir_n ? <>{(lb.dir_hit! * 100).toFixed(0)}%<i> {t('arena.board.dirN', { n: lb.dir_n })}</i></> : <i>—</i>}
            </span>
            <span className={`arena-verdict arena-verdict--${lb?.verdict ?? 'warming_up'}`}>
              {t(`arena.verdict.${lb?.verdict ?? 'warming_up'}` as 'arena.verdict.warming_up')}
            </span>
          </div>
        ))}
        {myRow && (
          <div className="arena-board__row arena-board__row--you">
            <div className="arena-who">
              <span className="arena-glyph" style={{ ['--c' as string]: COLOR.you }}>YOU</span>
              <div><b>{t('arena.you')}</b><span className="arena-who__prov">{t('arena.you.local')}</span></div>
            </div>
            <span className="mono">{myRow.n}</span>
            <span className="mono">{myRow.brier.toFixed(3)}</span>
            <span className="mono small">{myRow.skill != null ? `${myRow.skill >= 0 ? '+' : ''}${myRow.skill.toFixed(3)}` : '—'}</span>
            <span className="mono arena-dir"><i>—</i></span>
            <span className="arena-verdict arena-verdict--warming_up">{t('arena.verdict.warming_up')}</span>
          </div>
        )}
        <p className="arena-board__legend">{t('arena.board.legend')}</p>
      </section>

      {/* ── open & locked calls ── */}
      <section className="arena-deck">
        <h2 className="arena-h2"><Timer size={15} /> {t('arena.deck.title')}</h2>
        {data.pending.length === 0 && <div className="empty-state">{t('arena.deck.empty')}</div>}
        <div className="arena-grid">
          {data.pending.map((e) => {
            const locked = now >= new Date(e.cutoff).getTime()
            const m = mine[keyOf(e)]
            const k = keyOf(e)
            return (
              <motion.article key={k} className={`arena-event${locked ? ' is-locked' : ''}`} layout>
                <header className="arena-event__head">
                  <div>
                    <Link to={`/predict/${e.ticker}?earnings_date=${e.earnings_date}`} className="arena-event__ticker">{e.ticker}</Link>
                    <span className="arena-event__co">{e.company ?? ''}</span>
                  </div>
                  <span className={`arena-clock${locked ? ' is-locked' : ''}`}>
                    {locked ? <><Lock size={11} /> {t('arena.locked')}</> : <><Timer size={11} /> {t('arena.locksIn', { t: countdown(e.cutoff, now) })}</>}
                  </span>
                </header>
                <div className="arena-event__meta">
                  <span>{formatDateShort(e.earnings_date)}{e.report_time ? ` · ${e.report_time}` : ''}</span>
                  <span>{t('cal.usual', { v: (e.band * 100).toFixed(1) })}</span>
                  {e.implied_move != null && <span>{t('band.pop.expected', { v: (e.implied_move * 100).toFixed(1) })}</span>}
                </div>
                <ProbStrip ev={e} names={names} baseRate={baseRate} mine={m} onMine={(p) => setMyCall(e, p)} locked={locked} />
                <div className="arena-event__you">
                  {!m && !locked && <span className="tertiary">{t('arena.you.hint')}</span>}
                  {m && (
                    <>
                      <span>{t('arena.you.yours', { p: pct(m.p) })}</span>
                      <div className="arena-lean">
                        {(['UP', 'DOWN'] as const).map((l) => (
                          <button key={l} type="button" disabled={locked}
                            className={`arena-lean__btn${m.lean === l ? ' is-on' : ''}`}
                            onClick={() => setMyLean(e, m.lean === l ? null : l)}>{l}</button>
                        ))}
                      </div>
                    </>
                  )}
                  <button type="button" className="arena-event__proof" onClick={() => setOpen(open === k ? null : k)}>
                    <ShieldCheck size={12} /> {open === k ? t('arena.hideSeals') : t('arena.showSeals')}
                  </button>
                </div>
                <AnimatePresence>
                  {open === k && (
                    <motion.div className="arena-event__seals" initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }}>
                      {e.calls.map((c) => <VerifyPanel key={c.forecaster} call={c} name={names[c.forecaster] ?? c.forecaster} />)}
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.article>
            )
          })}
        </div>

        {data.queued.length > 0 && (
          <div className="arena-queue">
            <span className="arena-queue__label">{t('arena.queue')}</span>
            {data.queued.slice(0, 18).map((q) => (
              <span key={`${q.ticker}${q.earnings_date}`} className="arena-queue__chip" title={q.company ?? ''}>
                <b>{q.ticker}</b> {formatDateShort(q.earnings_date)}
                <i>{now >= new Date(q.opens).getTime() ? t('arena.queue.soon') : t('arena.queue.opens', { t: countdown(q.opens, now) })}</i>
              </span>
            ))}
          </div>
        )}
      </section>

      {/* ── graded ── */}
      <section className="card arena-graded">
        <h3 className="card-title">{t('arena.graded.title')}</h3>
        {data.resolved.length === 0 ? (
          <p className="tertiary">{t('arena.graded.empty')}</p>
        ) : (
          <div className="table-scroll">
            <table className="data-table arena-graded__table">
              <thead>
                <tr>
                  <th>{t('col.ticker')}</th><th>{t('col.date')}</th>
                  <th style={{ textAlign: 'right' }}>{t('arena.graded.move')}</th>
                  <th>{t('arena.graded.result')}</th>
                  {data.forecasters.map((f) => <th key={f.code} style={{ textAlign: 'right' }} title={f.name}>{GLYPH[f.code]}</th>)}
                  <th style={{ textAlign: 'right' }}>YOU</th>
                </tr>
              </thead>
              <tbody>
                {data.resolved.map((e) => {
                  const m = mine[keyOf(e)]
                  return (
                    <tr key={keyOf(e)}>
                      <td className="mono">{e.ticker}</td>
                      <td className="mono small">{formatDateShort(e.earnings_date)}</td>
                      <td className="mono r">{e.actual_move != null ? `${e.actual_move >= 0 ? '+' : ''}${(e.actual_move * 100).toFixed(2)}%` : '—'}<span className="tertiary"> / ±{(e.band * 100).toFixed(1)}%</span></td>
                      <td>{e.broke_out ? <span className="arena-out arena-out--yes">{t('arena.graded.broke')}</span> : <span className="arena-out">{t('arena.graded.held')}</span>}</td>
                      {data.forecasters.map((f) => {
                        const c = e.calls.find((x) => x.forecaster === f.code)
                        return (
                          <td key={f.code} className="mono r">
                            {c ? <span className={`arena-score ${c.brier != null && c.brier < 0.25 ? 'is-good' : 'is-bad'}`} title={`Brier ${c.brier?.toFixed(3)}`}>{pct(c.p)}</span> : <span className="tertiary">—</span>}
                          </td>
                        )
                      })}
                      <td className="mono r">{m ? <span className={`arena-score ${((m.p - (e.broke_out ? 1 : 0)) ** 2) < 0.25 ? 'is-good' : 'is-bad'}`}>{pct(m.p)}</span> : <span className="tertiary">—</span>}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* ── why ── */}
      <section className="arena-why">
        <div>
          <h3>{t('arena.why.t1')}</h3>
          <p>{t('arena.why.d1')}</p>
        </div>
        <div>
          <h3>{t('arena.why.t2')}</h3>
          <p>{t('arena.why.d2')}</p>
        </div>
        <div>
          <h3>{t('arena.why.t3')}</h3>
          <p>{t('arena.why.d3')}</p>
        </div>
      </section>

      {(data.voided?.length ?? 0) > 0 && (
        <details className="arena-voided">
          <summary>{t('arena.voided.title', { n: data.totals.voided ?? 0, r: data.voided!.length })}</summary>
          <p>{data.voided![0].reason}</p>
          <div className="arena-voided__list">
            {data.voided!.map((v) => (
              <div key={v.ticker + v.earnings_date}>
                <b className="mono">{v.ticker}</b>
                <span>{v.earnings_date}</span>
                <span>{t('arena.voided.row', { n: v.calls, band: (v.band * 100).toFixed(1), implied: v.implied_move != null ? (v.implied_move * 100).toFixed(1) : '—' })}</span>
                {v.anchor_id != null && <a href={`/api/v1/arena/anchors/${v.anchor_id}/manifest.txt`}>manifest #{v.anchor_id}</a>}
              </div>
            ))}
          </div>
        </details>
      )}

      {data.anchors.length > 0 && (
        <section className="arena-anchors">
          <h3 className="card-title"><Anchor size={12} /> {t('arena.anchors.title')}</h3>
          <div className="arena-anchors__list">
            {data.anchors.map((a) => (
              <div key={a.id} className="arena-anchors__row">
                <span className="mono">#{a.id}</span>
                <span className="tertiary">{new Date(a.created_at).toLocaleString()}</span>
                <span>{t('arena.anchors.calls', { n: a.calls })}</span>
                <code title={a.root}>{a.root.slice(0, 16)}…</code>
                <a href={`/api/v1/arena/anchors/${a.id}/manifest.txt`}>manifest</a>
                <a href={`/api/v1/arena/anchors/${a.id}/manifest.txt.ots`}>.ots</a>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
