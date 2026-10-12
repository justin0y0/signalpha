import { Link } from 'react-router-dom'
import { ArrowUpRight } from 'lucide-react'
import { PageHead } from '../components/PageHead'
import { Num } from '../components/ui/Num'
import { useHeadline } from '../hooks/useHeadline'
import { JOURNEY, DESKS } from '../lib/journey'
import { useT } from '../i18n'
import './AboutPage.css'

/**
 * About — what the site claims, checked against itself.
 *
 * The page used to be a brochure: a gradient headline, a benchmark chart with our own
 * accuracy typed in by hand, a roadmap of things that had already shipped or been
 * dropped. Every one of those went stale without anyone noticing.
 *
 * It is now three things that cannot go stale quietly: a ledger of the four claims the
 * site makes, each read live from /model/headline beside the number it has to beat and
 * stamped with whether it holds; the loop, in order; and the corrections column — every
 * time a number on this site turned out to be wrong, dated, with what was done about it.
 */

type Verdict = 'holds' | 'fails' | 'coin' | 'wait'

// What the models train on, and what the site collects and shows but keeps out of
// training because the source only ever returns today's value (see models/features.py).
const FEATURE_GROUPS = [
  { k: 'about.fg.price', used: true, items: ['Returns 1/5/10/20/60d', 'RSI', 'MACD', 'Bollinger position', 'Dist 52w high/low', 'Volume anomaly'] },
  { k: 'about.fg.macro', used: true, items: ['VIX / VIX9D / VIX3M', 'Yield curve slope', '2y / 10y yield', 'CPI / PCE YoY', 'HYG-LQD spread', 'SPY / QQQ returns'] },
  { k: 'about.fg.sector', used: true, items: ['Sector ETF 20d return', 'Relative strength vs SPY', 'Market regime'] },
  { k: 'about.fg.band', used: true, items: ['Own median reaction', 'Momentum vs own band', 'Residual vs market + sector'] },
  { k: 'about.fg.options', used: false, items: ['ATM straddle / spot', 'Put/call volume', 'Skew'] },
  { k: 'about.fg.funda', used: false, items: ['EPS surprise', 'Forward estimates', 'Analyst targets', 'Margins / leverage'] },
  { k: 'about.fg.pos', used: false, items: ['Short interest', 'Institutional ownership'] },
  { k: 'about.fg.sent', used: false, items: ['FinBERT news sentiment', '10-Q MD&A tone'] },
] as const

const STEPS = ['collect', 'freeze', 'walk', 'seal', 'grade'] as const

// Newest first. Dates are when the fix shipped; the text says what was wrong.
const ERRATA = ['1011', '1010', '1005', '0722', '0720'] as const

const STACK = [
  ['about.stack.models', 'XGBoost · scikit-learn · walk-forward, purged'],
  ['about.stack.data', 'yfinance · SEC EDGAR · FRED · Groq'],
  ['about.stack.serve', 'FastAPI · PostgreSQL 16 · Redis · APScheduler'],
  ['about.stack.front', 'React 18 · TypeScript · Vite · framer-motion'],
  ['about.stack.proof', 'SHA-256 · OpenTimestamps · Bitcoin'],
  ['about.stack.infra', 'Docker Compose · Oracle Cloud ARM · MCP'],
] as const

const pct1 = (v: number | null | undefined) => (v == null ? '—' : `${(v * 100).toFixed(1)}%`)

export function AboutPage() {
  const { t } = useT()
  const h = useHeadline()
  const b = h?.breakout
  const f = h?.follow_through
  const l = h?.lean
  const c = h?.three_class

  const rows: { key: string; ours: string; bar: string; n: string; stat: string; verdict: Verdict; to: string }[] = [
    {
      key: 'breakout', ours: pct1(b?.top_decile.move_rate), bar: pct1(b?.base_rate),
      n: b ? b.top_decile.n.toLocaleString() : '—', stat: b ? `z ${b.top_decile.z.toFixed(1)}` : '—',
      verdict: !b ? 'wait' : b.top_decile.z >= 2 ? 'holds' : 'fails', to: '/model',
    },
    {
      key: 'follow', ours: pct1(f?.hit), bar: pct1(f?.baseline_hit),
      n: f ? f.n.toLocaleString() : '—', stat: f ? `t ${f.t.toFixed(1)}` : '—',
      verdict: !f ? 'wait' : f.t >= 2 ? 'holds' : 'fails', to: '/strategy',
    },
    {
      key: 'three', ours: pct1(c?.accuracy), bar: pct1(c?.flat_baseline),
      n: c ? c.n.toLocaleString() : '—', stat: c?.accuracy != null && c.flat_baseline != null ? `${((c.accuracy - c.flat_baseline) * 100).toFixed(1)} pts` : '—',
      verdict: c?.accuracy == null || c.flat_baseline == null ? 'wait' : c.accuracy > c.flat_baseline ? 'holds' : 'fails', to: '/model',
    },
    {
      key: 'lean', ours: pct1(l?.accuracy), bar: '50.0%',
      n: l ? l.n.toLocaleString() : '—', stat: l ? `z ${l.z.toFixed(1)}` : '—',
      verdict: !l ? 'wait' : l.verdict === 'edge' ? 'holds' : 'coin', to: '/arena',
    },
  ]

  return (
    <div className="page-stack about">
      <PageHead
        kicker={t('nav.about')}
        title={<>{t('about.h.a')} <em>{t('about.h.b')}</em></>}
        lede={t('about.h.lede', { tickers: h?.universe.tickers ?? '—' })}
        spike={0.74}
      >
        <div className="figs">
          <div><b><Num value={h?.universe.tickers ?? null} /></b><span>{t('about.stat.equities')}</span></div>
          <div><b><Num value={h?.universe.events ?? null} /></b><span>{t('about.stat.events')}</span></div>
          <div className="is-signal"><b><Num value={h?.universe.features ?? null} /></b><span>{t('about.stat.features')}</span></div>
        </div>
      </PageHead>

      {/* ── the ledger ── */}
      <section className="paper ledger">
        <header className="ledger__head">
          <div>
            <span className="ledger__kicker">{t('about.ledger.kicker')}</span>
            <h2 className="serif">{t('about.ledger.title')}</h2>
          </div>
          <p>{t('about.ledger.sub')}</p>
        </header>
        <div className="ledger__cols" aria-hidden="true">
          <span>{t('about.ledger.c.claim')}</span><span>{t('about.ledger.c.ours')}</span><span>{t('about.ledger.c.bar')}</span>
          <span>{t('about.ledger.c.n')}</span><span>{t('about.ledger.c.stat')}</span><span />
        </div>
        {rows.map((r, i) => (
          <Link key={r.key} to={r.to} className={`ledger__row is-${r.verdict}`} style={{ animationDelay: `${0.12 + i * 0.09}s` }}>
            <div className="ledger__claim">
              <b className="serif">{t(`about.ledger.${r.key}` as 'about.ledger.breakout')}</b>
              <span>{t(`about.ledger.${r.key}.d` as 'about.ledger.follow.d', { k: f?.k ?? 2, hold: f?.hold ?? 20 })}</span>
            </div>
            <span className="ledger__num ledger__num--ours" data-l={t('about.ledger.c.ours')}>{r.ours}</span>
            <span className="ledger__num" data-l={t('about.ledger.c.bar')}>{r.bar}</span>
            <span className="ledger__num ledger__num--sm" data-l={t('about.ledger.c.n')}>{r.n}</span>
            <span className="ledger__num ledger__num--sm" data-l={t('about.ledger.c.stat')}>{r.stat}</span>
            <span className="ledger__stamp" style={{ animationDelay: `${0.5 + i * 0.14}s` }}>{t(`about.verdict.${r.verdict}` as 'about.verdict.holds')}</span>
          </Link>
        ))}
        <p className="ledger__foot">{t('about.ledger.foot')} <code>GET /api/v1/model/headline</code></p>
      </section>

      {/* ── the loop ── */}
      <section className="about-block">
        <header className="about-block__head">
          <span className="eyebrow">{t('about.loop.kicker')}</span>
          <h2 className="serif">{t('about.loop.title')}</h2>
        </header>
        <ol className="about-loop">
          {JOURNEY.map((j) => (
            <li key={j.key}>
              <Link to={j.to}>
                <span className="about-loop__n">{j.step}</span>
                <span className="about-loop__phase">{t(j.phase as 'journey.before')}</span>
                <b className="serif">{t(j.nav as 'nav.calendar')}</b>
                <p>{t(`about.loop.${j.key}` as 'about.loop.calendar')}</p>
                <ArrowUpRight size={15} />
              </Link>
            </li>
          ))}
        </ol>
        <p className="page-note">
          {t('about.loop.desks')}{' '}
          {DESKS.map((d, i) => (
            <span key={d.to}>{i > 0 && ' · '}<Link to={d.to} className="tlink">{t(d.nav as 'nav.pulse')}</Link></span>
          ))}
        </p>
      </section>

      {/* ── how a number gets made ── */}
      <section className="about-block">
        <header className="about-block__head">
          <span className="eyebrow">{t('about.make.kicker')}</span>
          <h2 className="serif">{t('about.make.title')}</h2>
        </header>
        <ol className="about-make">
          {STEPS.map((s, i) => (
            <li key={s}>
              <span className="about-make__n">{String.fromCharCode(65 + i)}</span>
              <b>{t(`about.make.${s}` as 'about.make.collect')}</b>
              <p>{t(`about.make.${s}.d` as 'about.make.collect.d')}</p>
            </li>
          ))}
        </ol>

        <div className="about-feats">
          {[true, false].map((used) => (
            <div key={String(used)} className={used ? 'is-used' : 'is-shown'}>
              <h3>{used ? t('about.feats.used', { n: h?.universe.features ?? '—' }) : t('about.feats.shown')}</h3>
              <p>{used ? t('about.feats.used.d') : t('about.feats.shown.d')}</p>
              <dl>
                {FEATURE_GROUPS.filter((g) => g.used === used).map((g) => (
                  <div key={g.k}>
                    <dt>{t(g.k as 'about.fg.price')}</dt>
                    <dd>{g.items.join(' · ')}</dd>
                  </div>
                ))}
              </dl>
            </div>
          ))}
        </div>
      </section>

      {/* ── corrections ── */}
      <section className="about-block">
        <header className="about-block__head">
          <span className="eyebrow">{t('about.errata.kicker')}</span>
          <h2 className="serif">{t('about.errata.title')}</h2>
          <p>{t('about.errata.sub')}</p>
        </header>
        <ol className="errata">
          {ERRATA.map((e) => (
            <li key={e}>
              <time>{t(`about.errata.${e}.when` as 'about.errata.1011.when')}</time>
              <div>
                <b className="serif">{t(`about.errata.${e}` as 'about.errata.1011')}</b>
                <p>{t(`about.errata.${e}.d` as 'about.errata.1011.d')}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      {/* ── colophon ── */}
      <section className="about-colophon">
        <dl>
          {STACK.map(([k, v]) => (
            <div key={k}><dt>{t(k as 'about.stack.models')}</dt><dd>{v}</dd></div>
          ))}
        </dl>
        <div className="about-colophon__cta">
          <p className="serif">{t('about.cta.wrong')}</p>
          <div>
            <Link to="/contact" className="btn btn-primary">{t('about.cta.secondary')}</Link>
            <Link to="/model" className="btn">{t('about.cta.evidence')}</Link>
          </div>
        </div>
      </section>
    </div>
  )
}
