import { useEffect, useMemo, useState, useCallback } from 'react'
import './OraclePage.css'
import { OhlcChart } from './OhlcChart'
import { useT } from '../i18n'

type Figure = {
  key: string; name: string; emoji: string; why?: string; type?: string;
  enabled: boolean; avatarUrl?: string
}
type Signal = {
  figure: string; figure_name: string; source_url?: string; headline?: string; ticker: string;
  sentiment: string; confidence: number; rationale?: string; price?: number; market_cap?: number;
  suggested_size?: number; pulse_score?: number | null; detected_at: string; kind?: string;
  return_since?: number | null; price_now?: number | null
}
type LbRow = {
  figure: string; figure_name: string; emoji: string; type?: string;
  calls: number; hit_rate: number; avg_return: number; best: number; worst: number
}

const CAT: Record<string, [string, string]> = {
  policy: ['#f5c451', '#d9881f'], tech_ceo: ['#34d399', '#0e9488'], x_trader: ['#34d3e0', '#2b7fb3'],
  x_mover: ['#a78bfa', '#7c5cf0'], fund: ['#5b9dff', '#3a64f0'], activist: ['#fb7aa8', '#dd4f86'],
  congress: ['#2dd4bf', '#0d8c80'], value: ['#bfd66a', '#7fae3c'], contrarian: ['#ef4444', '#a51d1d'],
}
const DEF: [string, string] = ['#6b7280', '#374151']
const AVATARS: Record<string,string> = {trump:'/avatars/trump.svg',huang:'/avatars/huang.svg',serenity:'/avatars/serenity.svg',musk:'/avatars/musk.svg',su:'/avatars/su.svg',wood:'/avatars/wood.svg',ackman:'/avatars/ackman.svg',pelosi:'/avatars/pelosi.svg',buffett:'/avatars/buffett.svg',burry:'/avatars/burry.svg'}
const grad = (t?: string): [string, string] => CAT[t || ''] || DEF

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

export function OraclePage() {
  const { t } = useT()
  const [figures, setFigures] = useState<Figure[]>([])
  const [signals, setSignals] = useState<Signal[]>([])
  const [board, setBoard] = useState<LbRow[]>([])
  const [filter, setFilter] = useState<'all' | 'bullish' | 'bearish'>('all')
  const [figFilter, setFigFilter] = useState<string | null>(null)
  const [scanning, setScanning] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [expanded, setExpanded] = useState<number | null>(null)

  const loadFigures = useCallback(async () => {
    try {
      const r = await fetch('/api/v1/oracle/figures')
      const d = await r.json()
      const arr = Array.isArray(d) ? d : (d.figures || [])
      setFigures(arr.map((f: any) => ({
        key: f.key || f.id || f.figure || f.name,
        name: f.name || f.figure_name || f.key,
        emoji: f.emoji || '🔮',
        why: f.why || f.role || f.desc || '',
        type: f.type || f.category || '',
        enabled: f.enabled ?? f.is_enabled ?? true,
        avatarUrl: f.avatar_url || f.avatarUrl || AVATARS[f.key || f.id || f.figure || ''] || '',
      })))
    } catch { /* keep prior */ }
  }, [])

  const loadSignals = useCallback(async () => {
    try {
      const r = await fetch('/api/v1/oracle/signals?limit=40')
      const d = await r.json()
      setSignals(Array.isArray(d) ? d : (d.signals || []))
    } catch { /* keep prior */ } finally { setLoaded(true) }
  }, [])

  const loadBoard = useCallback(async () => {
    try {
      const r = await fetch('/api/v1/oracle/leaderboard')
      const d = await r.json()
      setBoard(Array.isArray(d) ? d : (d.leaderboard || []))
    } catch { /* keep prior */ }
  }, [])

  useEffect(() => {
    loadFigures(); loadSignals(); loadBoard()
    const t = setInterval(loadSignals, 30000)
    return () => clearInterval(t)
  }, [loadFigures, loadSignals, loadBoard])

  const toggle = async (f: Figure) => {
    const next = !f.enabled
    const nextFigs = figures.map(x => x.key === f.key ? { ...x, enabled: next } : x)
    setFigures(nextFigs)
    try {
      await fetch('/api/v1/oracle/figures', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ keys: nextFigs.filter(x => x.enabled).map(x => x.key) }),
      })
    } catch { /* optimistic */ }
  }

  const scan = async () => {
    setScanning(true)
    try { await fetch('/api/v1/oracle/scan-now', { method: 'POST' }); await loadSignals(); await loadBoard() }
    catch { /* noop */ } finally { setScanning(false) }
  }

  const shown = useMemo(
    () => signals.filter(s =>
      (filter === 'all' ? true : s.sentiment === filter) &&
      (figFilter ? s.figure === figFilter : true)),
    [signals, filter, figFilter])
  const figByKey = useMemo(
    () => Object.fromEntries(figures.map(f => [f.key, f])),
    [figures])
  const activeCount = figures.filter(f => f.enabled).length
  const todayCount = signals.filter(s => Date.now() - new Date(s.detected_at).getTime() < 86400000).length
  const totCalls = board.reduce((a, b) => a + b.calls, 0)
  const avgCall = totCalls ? board.reduce((a, b) => a + b.avg_return * b.calls, 0) / totCalls : 0

  return (
    <div className="orc2">
      <header className="orc2-hero">
        <div className="orc2-orb" aria-hidden />
        <div className="orc2-hero-main">
          <h1 className="orc2-title">{t('oracle.title')}</h1>
          <p className="orc2-sub">{t('oracle.sub')}</p>
          <div className="orc2-stats">
            <div className="orc2-stat"><b>{todayCount}</b><span>{t('oracle.stat.signals')}</span></div>
            <div className="orc2-stat"><b>{activeCount}</b><span>{t('oracle.stat.tracking')}</span></div>
            <div className="orc2-stat"><b className={avgCall >= 0 ? 'pos' : 'neg'}>{avgCall >= 0 ? '+' : ''}{avgCall.toFixed(1)}%</b><span>{t('oracle.stat.avg')}</span></div>
          </div>
        </div>
        <button className={'orc2-scan' + (scanning ? ' is-scanning' : '')} onClick={scan} disabled={scanning}>
          <span className="orc2-scan-dot" />{scanning ? 'Scanning…' : 'Scan now'}
        </button>
      </header>

      {board.length > 0 && (
        <section className="orc2-lb-wrap">
          <div className="orc2-lb-head">
            <h2>{t('oracle.whoMoves')}</h2>
            <span className="orc2-lb-sub">{t('oracle.lb.sub')}</span>
            {figFilter && <button className="orc2-lb-clear" onClick={() => setFigFilter(null)}>{t('oracle.lb.clear')} ✕</button>}
          </div>
          <div className="orc2-lb">
            {board.map((b, i) => {
              const [a1, a2] = grad(b.type)
              const pos = b.avg_return >= 0
              return (
                <button key={b.figure} type="button"
                  className={'orc2-lbcard' + (figFilter === b.figure ? ' is-active' : '') + (i === 0 ? ' is-top' : '')}
                  onClick={() => setFigFilter(figFilter === b.figure ? null : b.figure)}>
                  <span className="orc2-lb-rank">{i + 1}</span>
                  <span className="orc2-lb-av" style={{ ['--a1' as any]: a1, ['--a2' as any]: a2 }}>{b.emoji}</span>
                  <span className="orc2-lb-meta">
                    <span className="orc2-lb-name">{b.figure_name}</span>
                    <span className="orc2-lb-calls">{b.calls} calls · {b.hit_rate}% hit</span>
                  </span>
                  <span className={'orc2-lb-ret ' + (pos ? 'pos' : 'neg')}>{pos ? '+' : ''}{b.avg_return.toFixed(1)}%</span>
                </button>
              )
            })}
          </div>
        </section>
      )}

      <section className="orc2-roster">
        {figures.map((f, i) => {
          const [a1, a2] = grad(f.type)
          return (
            <button key={f.key} type="button"
              className={'orc2-fig ' + (f.enabled ? 'is-on' : 'is-off')}
              style={{ ['--a1' as any]: a1, ['--a2' as any]: a2, ['--d' as any]: i * 0.04 + 's' }}
              onClick={() => toggle(f)}>
              <span className="orc2-avatar" style={{ ['--a1' as any]: a1, ['--a2' as any]: a2 }}>
                {f.avatarUrl ? <img src={f.avatarUrl} alt="" /> : initials(f.name)}
                <span className="emoji">{f.emoji}</span>
              </span>
              <span className="orc2-fig-body">
                <span className="orc2-fig-name">{f.name}</span>
                <span className="orc2-fig-role">{f.why}</span>
              </span>
              <span className="orc2-fig-state"><span className="orc2-pulse" />{f.enabled ? 'Live' : 'Off'}</span>
            </button>
          )
        })}
      </section>

      <section className="orc2-feed">
        <div className="orc2-feed-head">
          <h2>{t('oracle.feed')}</h2>
          <div className="orc2-filters">
            {(['all', 'bullish', 'bearish'] as const).map(k => (
              <button key={k} className={'orc2-fchip' + (filter === k ? ' is-active' : '')} onClick={() => setFilter(k)}>
                {k === 'all' ? 'All' : k === 'bullish' ? 'Bullish' : 'Bearish'}
              </button>
            ))}
          </div>
        </div>

        {loaded && shown.length === 0 && (
          <div className="orc2-empty"><span className="orc2-empty-orb" />{t('oracle.empty')}</div>
        )}

        <div className="orc2-siglist">
          {shown.map((s, i) => {
            const f = figByKey[s.figure]
            const [a1, a2] = grad(f?.type)
            const bull = s.sentiment === 'bullish'
            const pct = Math.round((s.confidence || 0) * 100)
            const ret = (typeof s.return_since === 'number') ? s.return_since : null
            const _rs = s.rationale || ''
            const _dp = _rs.indexOf('('); const _de = _rs.indexOf(')')
            const sigDate = (_dp >= 0 && _de > _dp) ? _rs.slice(_dp + 1, _de) : ''
            const pxNow = (typeof s.price_now === 'number') ? s.price_now : s.price
            return (
              <article key={i} className={'orc2-sig ' + (bull ? 'is-bull' : 'is-bear') + (expanded === i ? ' is-open' : '')}
                onClick={() => setExpanded(expanded === i ? null : i)}
                style={{ ['--d' as any]: Math.min(i, 12) * 0.03 + 's' }}>
                <div className="orc2-sig-edge" />
                <div className="orc2-sig-row">
                <div className="orc2-sig-main">
                  <div className="orc2-sig-top">
                    <span className="orc2-tk">{s.ticker}</span>
                    <span className={'orc2-dir ' + (bull ? 'up' : 'down')}>{bull ? '▲ Bullish' : '▼ Bearish'}</span>
                    <span className="orc2-px">${pxNow?.toFixed(2)}<i>·</i>{fmtCap(s.market_cap)}</span>
                    <span className="orc2-time">{ago(s.detected_at)}</span>
                  </div>
                  {s.headline && <div className="orc2-sig-quote">{s.headline}</div>}
                  {s.rationale && <div className="orc2-sig-why">{s.rationale.replace(/\s*->.*$/, '')}</div>}
                  <div className="orc2-sig-foot">
                    <span className="orc2-byline">
                      <span className="orc2-mini" style={{ ['--a1' as any]: a1, ['--a2' as any]: a2 }}>
                        {f?.avatarUrl ? <img src={f.avatarUrl} alt="" /> : initials(s.figure_name)}
                      </span>
                      {s.figure_name}
                    </span>
                    {typeof s.pulse_score === 'number' && (
                      <span className="orc2-pulse-tag">Pulse {s.pulse_score > 0 ? '+' : ''}{s.pulse_score.toFixed(2)}</span>
                    )}
                    <span className="orc2-size">size ${Math.round(100 + Math.min(1, Math.max(0, ((s.confidence || 0) - 0.5) / 0.5)) * 400)}</span>
                    {s.source_url && <a className="orc2-src" href={s.source_url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>{t('oracle.source')} ↗</a>}
                  </div>
                </div>
                {ret !== null ? (
                  <div className={'orc2-ret ' + (ret >= 0 ? 'pos' : 'neg')}>
                    <b>{ret >= 0 ? '+' : ''}{ret.toFixed(1)}%</b>
                    <span>{t('oracle.sinceSignal')}</span>
                  </div>
                ) : (
                  <div className="orc2-conf" style={{ ['--p' as any]: pct, ['--accent' as any]: bull ? 'var(--bull)' : 'var(--bear)' }}>
                    <span>{pct}%</span>
                  </div>
                )}
                </div>
                {expanded === i && <div className="orc2-chartwrap"><OhlcChart ticker={s.ticker} since={sigDate} entry={s.price} dir={s.sentiment} /></div>}
              </article>
            )
          })}
        </div>
      </section>
    </div>
  )
}
