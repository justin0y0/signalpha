import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { PageHead } from '../components/PageHead'
import { Num } from '../components/ui/Num'
import { useT } from '../i18n'
import './MarketsPage.css'

/**
 * Markets — the whole tape on one page, in the order a trader scans it: the four
 * indices with today's line, breadth, where the money moved (heatmap), who moved most,
 * then everything that is not a stock — futures, rates, commodities, currencies, crypto
 * and the overseas close — and the news. /api/v1/markets; refreshed every two minutes.
 */

type Q = { symbol: string; name: string; last: number; chg: number; abs: number; as_of: string; spark: number[]; intraday?: number[] }
type Row = { ticker: string; name: string; price: number; chg: number; volume: number; cap: number; sector: string }
type Sector = { name: string; cap: number; chg: number; up: number; down: number; stocks: { ticker: string; cap: number; chg: number }[] }
type M = {
  as_of: string; snapshot?: { as_of: string; updated_at: string; n: number }
  breadth?: { up: number; down: number; flat: number; total: number; cap_weighted: number; big_up: number; big_down: number }
  gainers?: Row[]; losers?: Row[]; active?: Row[]; megacaps?: Row[]; heatmap?: Sector[]
  majors?: Q[]; groups?: Record<string, Q[]>; news?: { title: string; publisher: string; link: string; time: string | null }[]
}

const sg = (v: number, d = 2) => `${v >= 0 ? '+' : ''}${(v * 100).toFixed(d)}%`
const capS = (v: number) => (v >= 1e12 ? `$${(v / 1e12).toFixed(2)}T` : v >= 1e9 ? `$${(v / 1e9).toFixed(1)}B` : `$${(v / 1e6).toFixed(0)}M`)
const fmt = (q: Q) => {
  if (['^IRX', '^FVX', '^TNX', '^TYX'].includes(q.symbol)) return `${q.last.toFixed(3)}%`
  if (q.last >= 1000) return q.last.toLocaleString(undefined, { maximumFractionDigits: 2 })
  return q.last.toFixed(q.last < 10 ? 4 : 2)
}
const tone = (c: number) => {
  const a = Math.min(1, Math.abs(c) / 0.03)
  return c >= 0 ? `color-mix(in srgb, var(--up) ${Math.round(18 + a * 62)}%, var(--bg-1))` : `color-mix(in srgb, var(--down) ${Math.round(18 + a * 62)}%, var(--bg-1))`
}

function Line({ v, w = 240, h = 56, fill = true }: { v: number[]; w?: number; h?: number; fill?: boolean }) {
  if (v.length < 2) return null
  const lo = Math.min(...v), hi = Math.max(...v)
  const pts = v.map((x, i) => `${(i / (v.length - 1)) * w},${(h - ((x - lo) / (hi - lo || 1)) * (h - 4) - 2).toFixed(1)}`)
  const up = v[v.length - 1] >= v[0]
  return (
    <svg className={`mk-line ${up ? 'is-up' : 'is-down'}`} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden="true">
      {fill && <polygon points={`0,${h} ${pts.join(' ')} ${w},${h}`} />}
      <polyline points={pts.join(' ')} />
    </svg>
  )
}

/** Recursive halving treemap: split the list where the weights balance, alternate axes. */
type Rect = { x: number; y: number; w: number; h: number }
function layout<T extends { cap: number }>(items: T[], r: Rect): (T & Rect)[] {
  if (!items.length) return []
  if (items.length === 1) return [{ ...items[0], ...r }]
  const total = items.reduce((s, x) => s + x.cap, 0)
  let acc = 0, k = 0
  while (k < items.length - 1 && acc + items[k].cap < total / 2) acc += items[k++].cap
  if (k === 0) { acc = items[0].cap; k = 1 }
  const f = acc / total
  if (r.w >= r.h) {
    const w1 = r.w * f
    return [...layout(items.slice(0, k), { ...r, w: w1 }), ...layout(items.slice(k), { x: r.x + w1, y: r.y, w: r.w - w1, h: r.h })]
  }
  const h1 = r.h * f
  return [...layout(items.slice(0, k), { ...r, h: h1 }), ...layout(items.slice(k), { x: r.x, y: r.y + h1, w: r.w, h: r.h - h1 })]
}

function Heatmap({ sectors }: { sectors: Sector[] }) {
  const boxes = useMemo(() => layout([...sectors].sort((a, b) => b.cap - a.cap), { x: 0, y: 0, w: 100, h: 100 }), [sectors])
  return (
    <div className="mk-heat" role="img" aria-label="Sector heatmap">
      {boxes.map((s) => {
        const inner = layout(s.stocks.filter((x) => x.cap > 0), { x: 0, y: 0, w: 100, h: 100 })
        return (
          <div key={s.name} className="mk-heat__sec" style={{ left: `${s.x}%`, top: `${s.y}%`, width: `${s.w}%`, height: `${s.h}%` }}>
            <span className="mk-heat__name">{s.name} <b>{sg(s.chg)}</b></span>
            {inner.map((x) => (
              <Link key={x.ticker} to={`/predict/${x.ticker}`} className="mk-heat__cell"
                style={{ left: `${x.x}%`, top: `${x.y}%`, width: `${x.w}%`, height: `${x.h}%`, background: tone(x.chg) }}
                title={`${x.ticker} ${sg(x.chg)}`}>
                {x.w * s.w > 260 && x.h * s.h > 180 && <><b>{x.ticker}</b><i>{sg(x.chg, 1)}</i></>}
              </Link>
            ))}
          </div>
        )
      })}
    </div>
  )
}

const GROUP_ORDER = ['futures', 'rates', 'volatility', 'commodities', 'fx', 'crypto', 'world'] as const

export function MarketsPage() {
  const { t } = useT()
  const [d, setD] = useState<M | null>(null)
  const [tab, setTab] = useState<'gainers' | 'losers' | 'active'>('gainers')
  useEffect(() => {
    let alive = true
    const load = () => fetch('/api/v1/markets').then((r) => r.json()).then((x) => { if (alive) setD(x) }).catch(() => {})
    load()
    const id = setInterval(load, 120_000)
    return () => { alive = false; clearInterval(id) }
  }, [])

  const spx = d?.majors?.find((m) => m.symbol === '^GSPC')
  const vix = d?.groups?.volatility?.find((m) => m.symbol === '^VIX')
  const b = d?.breadth
  const rows = d?.[tab] ?? []

  return (
    <div className="page-stack mk">
      <PageHead
        kicker={t('nav.markets')}
        title={<>{t('mk.h.a')} <em>{t('mk.h.b')}</em></>}
        lede={t('mk.h.lede', { n: d?.snapshot?.n?.toLocaleString() ?? '3,400' })}
        spike={0.46}
      >
        <div className="figs">
          <div className={spx && spx.chg < 0 ? 'is-down' : 'is-up'}><b>{spx ? sg(spx.chg) : '—'}</b><span>{t('mk.fig.spx')}</span></div>
          <div><b>{b ? `${b.up.toLocaleString()} / ${b.down.toLocaleString()}` : '—'}</b><span>{t('mk.fig.breadth')}</span></div>
          <div className="is-signal"><b><Num value={vix?.last ?? null} format={(v) => v.toFixed(1)} /></b><span>{t('mk.fig.vix')}</span></div>
        </div>
      </PageHead>

      {!d ? <div className="shimmer" style={{ height: 520 }} /> : (
        <>
          <section className="mk-majors">
            {(d.majors ?? []).map((q) => (
              <div key={q.symbol} className="mk-major">
                <span className="eyebrow">{q.name}</span>
                <div className="mk-major__row">
                  <b className="serif">{q.last.toLocaleString(undefined, { maximumFractionDigits: 2 })}</b>
                  <em className={q.chg >= 0 ? 'is-up' : 'is-down'}>{sg(q.chg)}</em>
                </div>
                <Line v={q.intraday && q.intraday.length > 3 ? q.intraday : q.spark} />
                <span className="mk-major__cap">{q.intraday && q.intraday.length > 3 ? t('mk.intraday', { d: q.as_of }) : t('mk.month')}</span>
              </div>
            ))}
          </section>

          {b && (
            <section className="mk-breadth">
              <div className="mk-breadth__bar" aria-label={t('mk.fig.breadth')}>
                <i className="is-up" style={{ width: `${(b.up / b.total) * 100}%` }} />
                <i className="is-flat" style={{ width: `${(b.flat / b.total) * 100}%` }} />
                <i className="is-down" style={{ width: `${(b.down / b.total) * 100}%` }} />
              </div>
              <p>{t('mk.breadth', { up: b.up.toLocaleString(), down: b.down.toLocaleString(), total: b.total.toLocaleString(), bu: b.big_up, bd: b.big_down, cw: sg(b.cap_weighted) })}</p>
            </section>
          )}

          <section className="mk-grid">
            <div className="card mk-heatcard">
              <h3 className="card-title">{t('mk.heat')}</h3>
              {d.heatmap ? <Heatmap sectors={d.heatmap} /> : <p className="page-note">{t('mk.noSnapshot')}</p>}
              <div className="mk-sectors">
                {(d.heatmap ?? []).slice().sort((a, b2) => b2.chg - a.chg).map((s) => (
                  <div key={s.name}><span>{s.name}</span><em className={s.chg >= 0 ? 'is-up' : 'is-down'}>{sg(s.chg)}</em><small>{s.up}↑ {s.down}↓</small></div>
                ))}
              </div>
            </div>

            <div className="card mk-movers">
              <div className="mk-movers__head">
                <h3 className="card-title">{t('mk.movers')}</h3>
                <div className="seg" role="group" aria-label={t('mk.movers')}>
                  {(['gainers', 'losers', 'active'] as const).map((k) => (
                    <button key={k} type="button" className={tab === k ? 'is-on' : ''} onClick={() => setTab(k)}>{t(`mk.tab.${k}` as 'mk.tab.gainers')}</button>
                  ))}
                </div>
              </div>
              <div className="table-scroll">
                <table className="data-table mk-table">
                  <thead><tr><th>{t('col.ticker')}</th><th className="r">{t('mk.col.price')}</th><th className="r">{t('mk.col.chg')}</th></tr></thead>
                  <tbody>
                    {rows.slice(0, 15).map((r) => (
                      <tr key={r.ticker}>
                        <td><Link to={`/predict/${r.ticker}`} className="mk-tk"><b className="mono">{r.ticker} <small>{capS(r.cap)}</small></b><span>{r.name}</span></Link></td>
                        <td className="r mono">${r.price.toFixed(2)}</td>
                        <td className={`r mono ${r.chg >= 0 ? 'is-up' : 'is-down'}`}>{sg(r.chg)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </section>

          <section className="mk-macro">
            {GROUP_ORDER.filter((g) => d.groups?.[g]?.length).map((g) => (
              <div key={g} className="mk-macro__col">
                <h3 className="card-title">{t(`mk.g.${g}` as 'mk.g.futures')}</h3>
                {d.groups![g].map((q) => (
                  <div key={q.symbol} className="mk-q">
                    <span>{q.name}</span>
                    <b className="mono">{fmt(q)}</b>
                    <em className={q.chg >= 0 ? 'is-up' : 'is-down'}>{sg(q.chg)}</em>
                    <Line v={q.spark} w={80} h={20} fill={false} />
                  </div>
                ))}
              </div>
            ))}
          </section>

          <section className="mk-bottom">
            <div className="mk-mega">
              <h3 className="card-title">{t('mk.mega')}</h3>
              {(d.megacaps ?? []).map((r) => (
                <Link key={r.ticker} to={`/predict/${r.ticker}`} className="mk-mega__row">
                  <b className="mono">{r.ticker}</b><span>{capS(r.cap)}</span><em className={r.chg >= 0 ? 'is-up' : 'is-down'}>{sg(r.chg)}</em>
                </Link>
              ))}
            </div>
            <div className="mk-news">
              <h3 className="card-title">{t('mk.news')}</h3>
              {(d.news ?? []).map((n) => (
                <a key={n.title} href={n.link} target="_blank" rel="noreferrer noopener" className="mk-news__item">
                  <span>{n.publisher}{n.time ? ` · ${new Date(n.time).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}` : ''}</span>
                  <b className="serif">{n.title}</b>
                </a>
              ))}
            </div>
          </section>
          <p className="page-note">{t('mk.note', { d: d.snapshot?.as_of ?? '—' })}</p>
        </>
      )}
    </div>
  )
}
