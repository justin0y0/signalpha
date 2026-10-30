import { useEffect, useMemo, useState, useCallback } from 'react'
import './OraclePage.css'
import { PageHead } from '../components/PageHead'
import { OracleVerdict } from '../components/OracleVerdict'
import { Num } from '../components/ui/Num'
import { OhlcChart } from './OhlcChart'
import { useT } from '../i18n'

type Portrait = { src: string; license: string | null; author: string | null; page: string | null; focus: string | null }
type Health = 'live' | 'news_only' | 'quiet'
type Group = 'movers' | 'funds' | 'congress' | 'media'
type Figure = {
  key: string; name: string; zh?: string; group: Group; type?: string
  why?: string; why_zh?: string; cadence: 'live' | 'daily' | 'filing' | 'quarterly'
  enabled: boolean; health: { status: Health }; portrait: Portrait | null
  signals_30d: number; signals: number; last_signal: string | null
}
type Signal = {
  figure: string; figure_name: string; source_url?: string; headline?: string; ticker: string
  sentiment: string; confidence: number; rationale?: string; price?: number; market_cap?: number
  pulse_score?: number | null; detected_at: string; kind?: string | null
  return_since?: number | null; excess_since?: number | null; price_now?: number | null
}
type LbRow = {
  figure: string; figure_name: string; portrait: Portrait | null
  calls: number; hit_rate: number; avg_return: number; avg_excess: number | null; beat_spy: number | null
}

const GROUPS: Group[] = ['movers', 'funds', 'congress', 'media']

const initials = (name: string) => {
  const p = (name || '').trim().split(/\s+/)
  return ((p[0]?.[0] || '') + (p.length > 1 ? p[p.length - 1][0] : '')).toUpperCase() || '?'
}
const fmtCap = (n?: number) => {
  if (!n) return '—'
  if (n >= 1e12) return '$' + (n / 1e12).toFixed(2) + 'T'
  if (n >= 1e9) return '$' + (n / 1e9).toFixed(1) + 'B'
  if (n >= 1e6) return '$' + (n / 1e6).toFixed(0) + 'M'
  return '$' + n
}
const ago = (iso: string) => {
  const d = (Date.now() - new Date(iso).getTime()) / 1000
  if (d < 60) return Math.max(0, Math.floor(d)) + 's'
  if (d < 3600) return Math.floor(d / 60) + 'm'
  if (d < 86400) return Math.floor(d / 3600) + 'h'
  return Math.floor(d / 86400) + 'd'
}
const signed = (v: number, d = 1) => (v >= 0 ? '+' : '−') + Math.abs(v).toFixed(d) + '%'

/** 13F deadlines: 45 days after each quarter end. */
function next13F(): Date {
  const now = new Date()
  for (const y of [now.getFullYear(), now.getFullYear() + 1]) {
    for (const [m, d] of [[1, 14], [4, 15], [7, 14], [10, 14]] as const) {
      const at = new Date(y, m, d)
      if (at > now) return at
    }
  }
  return now
}

function Face({ name, p, size = 'md' }: { name: string; p: Portrait | null; size?: 'sm' | 'md' | 'lg' }) {
  const credit = p?.license ? `${p.author ? p.author + ' · ' : ''}${p.license}` : undefined
  return (
    <span className={'orc2-face is-' + size} title={credit}>
      {p ? <img src={p.src} alt={name} loading="lazy" style={p.focus ? { objectPosition: p.focus } : undefined} /> : initials(name)}
    </span>
  )
}

export function OraclePage() {
  const { t, locale } = useT()
  const zh = locale === 'zh'
  const [figures, setFigures] = useState<Figure[]>([])
  const [signals, setSignals] = useState<Signal[]>([])
  const [board, setBoard] = useState<LbRow[]>([])
  const [filter, setFilter] = useState<'all' | 'bullish' | 'bearish'>('all')
  const [figFilter, setFigFilter] = useState<string | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [expanded, setExpanded] = useState<number | null>(null)

  const loadFigures = useCallback(async () => {
    try {
      const d = await (await fetch('/api/v1/oracle/figures')).json()
      setFigures(d.figures || [])
    } catch { /* keep prior */ }
  }, [])

  // A person's own calls are fetched for them: the latest 40 overall can miss someone
  // who files once a quarter.
  const loadSignals = useCallback(async () => {
    try {
      const q = figFilter ? `&figure=${encodeURIComponent(figFilter)}` : ''
      const d = await (await fetch(`/api/v1/oracle/signals?limit=40${q}`)).json()
      setSignals(d.signals || [])
    } catch { /* keep prior */ } finally { setLoaded(true) }
  }, [figFilter])

  const loadBoard = useCallback(async () => {
    try {
      const d = await (await fetch('/api/v1/oracle/leaderboard')).json()
      setBoard(d.leaderboard || [])
    } catch { /* keep prior */ }
  }, [])

  useEffect(() => { loadFigures(); loadBoard() }, [loadFigures, loadBoard])
  useEffect(() => {
    setExpanded(null)
    loadSignals()
    const id = setInterval(loadSignals, 30000)
    return () => clearInterval(id)
  }, [loadSignals])

  const pick = (key: string) => {
    setFigFilter(figFilter === key ? null : key)
    document.querySelector('.orc2-feed')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const shown = useMemo(() => signals.filter(s => filter === 'all' || s.sentiment === filter), [signals, filter])
  const figByKey = useMemo(() => Object.fromEntries(figures.map(f => [f.key, f])), [figures])
  const nameOf = (f?: Figure, fallback = '') => (f ? (zh && f.zh ? f.zh : f.name) : fallback)
  const todayCount = signals.filter(s => Date.now() - new Date(s.detected_at).getTime() < 86400000).length
  const scored = board.filter(b => b.avg_excess != null)
  const totCalls = scored.reduce((a, b) => a + b.calls, 0)
  const avgEx = totCalls ? scored.reduce((a, b) => a + (b.avg_excess as number) * b.calls, 0) / totCalls : 0
  const due = next13F().toLocaleDateString(zh ? 'zh-CN' : 'en-US', { month: 'short', day: 'numeric' })
  const cadence = (f: Figure) => f.cadence === 'quarterly' ? t('oracle.cad.quarterly').replace('{d}', due) : t(`oracle.cad.${f.cadence}` as never)
  const credited = figures.filter(f => f.portrait?.license)
  const sel = figFilter ? figByKey[figFilter] : undefined

  return (
    <div className="orc2">
      <PageHead
        kicker={t('pulse.kicker')}
        title={<>{t('oracle.h.a')} <em>{t('oracle.h.b')}</em></>}
        lede={t('oracle.sub')}
        spike={0.5}
      >
        <div className="figs">
          <div className="is-signal"><b><Num value={todayCount} /></b><span>{t('oracle.stat.signals')}</span></div>
          <div><b><Num value={figures.filter(f => f.enabled).length} /></b><span>{t('oracle.stat.tracking')}</span></div>
          <div className={!totCalls ? '' : avgEx >= 0 ? 'is-up' : 'is-down'}><b>{totCalls ? signed(avgEx) : '—'}</b><span>{t('oracle.stat.avg')}</span></div>
        </div>
      </PageHead>

      <OracleVerdict />

      {board.length > 0 && (
        <section className="orc2-lb-wrap">
          <div className="orc2-lb-head">
            <h2>{t('oracle.whoMoves')}</h2>
            <span className="orc2-lb-sub">{t('oracle.lb.sub')}</span>
          </div>
          <div className="orc2-lb">
            {board.map((b, i) => {
              const ex = b.avg_excess
              const f = figByKey[b.figure]
              return (
                <button key={b.figure} type="button"
                  className={'orc2-lbcard' + (figFilter === b.figure ? ' is-active' : '') + (i === 0 ? ' is-top' : '')}
                  onClick={() => pick(b.figure)}>
                  <span className="orc2-lb-rank">{i + 1}</span>
                  <Face name={b.figure_name} p={b.portrait} size="sm" />
                  <span className="orc2-lb-meta">
                    <span className="orc2-lb-name">{nameOf(f, b.figure_name)}</span>
                    <span className="orc2-lb-calls">
                      {t('oracle.lb.calls').replace('{n}', String(b.calls))}
                      {b.beat_spy != null && <> · {t('oracle.lb.beat').replace('{p}', String(b.beat_spy))}</>}
                    </span>
                  </span>
                  <span className="orc2-lb-ret-wrap">
                    {ex != null
                      ? <span className={'orc2-lb-ret ' + (ex >= 0 ? 'pos' : 'neg')}>{signed(ex)}</span>
                      : <span className="orc2-lb-ret">—</span>}
                    <span className="orc2-lb-vs">{t('oracle.vsSpy')} · {t('oracle.raw')} {signed(b.avg_return)}</span>
                  </span>
                </button>
              )
            })}
          </div>
        </section>
      )}

      {GROUPS.map(g => {
        const list = figures.filter(f => f.group === g)
        if (!list.length) return null
        return (
          <section key={g} className="orc2-group">
            <div className="orc2-lb-head">
              <h2>{t(`oracle.g.${g}` as never)}</h2>
              <span className="orc2-lb-sub">{t(`oracle.g.${g}.s` as never)}</span>
            </div>
            <div className="orc2-roster">
              {list.map(f => {
                const h = f.enabled ? f.health.status : 'off'
                return (
                  <button key={f.key} type="button"
                    className={'orc2-fig' + (figFilter === f.key ? ' is-active' : '') + (f.enabled ? '' : ' is-off')}
                    onClick={() => pick(f.key)}>
                    <Face name={f.name} p={f.portrait} size="lg" />
                    <span className="orc2-fig-body">
                      <span className="orc2-fig-name">{nameOf(f)}{zh && f.zh && f.zh !== f.name && <i>{f.name}</i>}</span>
                      <span className="orc2-fig-role">{zh ? f.why_zh || f.why : f.why}</span>
                      <span className="orc2-fig-foot">
                        <span className={'orc2-fig-state is-' + h} title={h !== 'off' ? t(`oracle.health.${h}.tip` as never) : undefined}>
                          <span className="orc2-pulse" />{cadence(f)}
                        </span>
                        <span className="orc2-fig-n">
                          {f.signals_30d
                            ? t('oracle.n30').replace('{n}', String(f.signals_30d))
                            : f.last_signal ? t('oracle.lastAgo').replace('{t}', ago(f.last_signal)) : t('oracle.none')}
                        </span>
                      </span>
                    </span>
                  </button>
                )
              })}
            </div>
          </section>
        )
      })}

      <section className="orc2-feed">
        <div className="orc2-feed-head">
          <h2>{sel ? t('oracle.feedOf').replace('{n}', nameOf(sel)) : t('oracle.feed')}</h2>
          <div className="orc2-filters">
            {sel && <button className="orc2-fchip is-clear" onClick={() => setFigFilter(null)}>{t('oracle.lb.clear')} ✕</button>}
            {(['all', 'bullish', 'bearish'] as const).map(k => (
              <button key={k} className={'orc2-fchip' + (filter === k ? ' is-active' : '')} onClick={() => setFilter(k)}>
                {t(`oracle.filter.${k}` as never)}
              </button>
            ))}
          </div>
        </div>

        {loaded && shown.length === 0 && (
          <div className="orc2-empty"><span className="orc2-empty-orb" />{sel ? t('oracle.emptyOne') : t('oracle.empty')}</div>
        )}

        <div className="orc2-siglist">
          {shown.map((s, i) => {
            const f = figByKey[s.figure]
            const bull = s.sentiment === 'bullish'
            const pct = Math.round((s.confidence || 0) * 100)
            const ret = typeof s.return_since === 'number' ? s.return_since : null
            const ex = typeof s.excess_since === 'number' ? s.excess_since : null
            const pxNow = typeof s.price_now === 'number' ? s.price_now : s.price
            const sigDate = s.detected_at ? s.detected_at.slice(0, 10) : ''
            return (
              <article key={i} className={'orc2-sig ' + (bull ? 'is-bull' : 'is-bear') + (expanded === i ? ' is-open' : '')}
                onClick={() => setExpanded(expanded === i ? null : i)}>
                <div className="orc2-sig-edge" />
                <div className="orc2-sig-row">
                  <div className="orc2-sig-main">
                    <div className="orc2-sig-top">
                      <span className="orc2-tk">{s.ticker}</span>
                      <span className={'orc2-dir ' + (bull ? 'up' : 'down')}>{bull ? '▲ ' + t('oracle.filter.bullish') : '▼ ' + t('oracle.filter.bearish')}</span>
                      <span className="orc2-px">${pxNow?.toFixed(2)}<i>·</i>{fmtCap(s.market_cap)}</span>
                      <span className={'orc2-kind is-' + (s.kind || 'news')}>{t(s.kind === 'disclosure' ? 'oracle.kind.disclosure' : 'oracle.kind.news')}</span>
                      <span className="orc2-time">{ago(s.detected_at)}</span>
                    </div>
                    {s.headline && <div className="orc2-sig-quote">{s.headline}</div>}
                    {s.rationale && <div className="orc2-sig-why">{s.rationale.replace(/\s*->.*$/, '')}</div>}
                    <div className="orc2-sig-foot">
                      <span className="orc2-byline">
                        <Face name={s.figure_name} p={f?.portrait ?? null} size="sm" />
                        {nameOf(f, s.figure_name)}
                      </span>
                      {typeof s.pulse_score === 'number' && (
                        <span className="orc2-pulse-tag">Pulse {s.pulse_score > 0 ? '+' : ''}{s.pulse_score.toFixed(2)}</span>
                      )}
                      {s.source_url && <a className="orc2-src" href={s.source_url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>{t('oracle.source')} ↗</a>}
                    </div>
                  </div>
                  {ret !== null ? (
                    <div className={'orc2-ret ' + ((ex ?? ret) >= 0 ? 'pos' : 'neg')}>
                      <b>{signed(ex ?? ret)}</b>
                      <span>{ex !== null ? t('oracle.sinceVsSpy') : t('oracle.sinceSignal')}</span>
                      {ex !== null && <span className="orc2-ret-raw">{t('oracle.raw')} {signed(ret)}</span>}
                    </div>
                  ) : (
                    <div className="orc2-conf" style={{ ['--p' as any]: pct, ['--accent' as any]: bull ? 'var(--bull)' : 'var(--bear)' }}><span>{pct}%</span></div>
                  )}
                </div>
                {expanded === i && <div className="orc2-chartwrap"><OhlcChart ticker={s.ticker} since={sigDate} entry={s.price} dir={s.sentiment} /></div>}
              </article>
            )
          })}
        </div>
      </section>

      {credited.length > 0 && (
        <details className="orc2-credits">
          <summary>{t('oracle.credits')}</summary>
          <p>{t('oracle.credits.note')}</p>
          <ul>
            {credited.map(f => (
              <li key={f.key}>
                {f.name} — {f.portrait!.author}, <a href={f.portrait!.page || '#'} target="_blank" rel="noreferrer">{f.portrait!.license}</a>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}
