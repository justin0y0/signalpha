import { motion } from 'framer-motion'
import { useEffect, useMemo, useRef, useState } from 'react'
import { NavLink } from 'react-router-dom'
import {
  Activity,
  ArrowRight,
  BarChart3,
  Brain,
  Calendar,
  ChartLine,
  CandlestickChart,
  CircuitBoard,
  Cpu,
  Database,
  Eye,
  GitBranch,
  LineChart,
  Network,
  Sparkles,
  Target,
  TrendingUp,
  ClipboardList,
  Trophy,
} from 'lucide-react'
import { useT } from '../i18n'

// ============================================================
//  Signalpha — About Page
//  Bloomberg-terminal aesthetic, Apple-grade motion design.
// ============================================================

const STAT_ROW: { labelKey: string; value: string; tint: 'cyan' | 'purple' | 'emerald' | 'amber' }[] = [
  { labelKey: 'about.stat.equities', value: '199', tint: 'cyan' },
  { labelKey: 'about.stat.events', value: '6,322', tint: 'purple' },
  { labelKey: 'about.stat.features', value: '102', tint: 'emerald' },
  { labelKey: 'about.stat.folds', value: '9', tint: 'amber' },
]

const PIPELINE = [
  { icon: Database, k: 'about.pl.ingest', tint: 'cyan' },
  { icon: CircuitBoard, k: 'about.pl.feat', tint: 'purple' },
  { icon: Brain, k: 'about.pl.nlp', tint: 'emerald' },
  { icon: Network, k: 'about.pl.ens', tint: 'amber' },
  { icon: Eye, k: 'about.pl.shap', tint: 'cyan' },
] as const

const TAB_GUIDE = [
  { name: 'Calendar', to: '/', icon: Calendar, tag: 'Live', k: 'about.tab.cal' , nav: 'nav.calendar', tagK: 'about.tag.cal' },
  { name: 'Brief', to: '/brief', icon: ClipboardList, tag: 'Daily', k: 'about.tab.brief' , nav: 'nav.brief', tagK: 'about.tag.brief' },
  { name: 'Model', to: '/model', icon: BarChart3, tag: 'Diagnostic', k: 'about.tab.model' , nav: 'nav.model', tagK: 'about.tag.model' },
  { name: 'Strategy', to: '/strategy', icon: ChartLine, tag: 'Research', k: 'about.tab.strategy' , nav: 'nav.strategy', tagK: 'about.tag.strategy' },
  { name: 'Pulse', to: '/pulse', icon: Activity, tag: 'Real-time', k: 'about.tab.pulse' , nav: 'nav.pulse', tagK: 'about.tag.pulse' },
  { name: 'Oracle', to: '/oracle', icon: Trophy, tag: 'Signals', k: 'about.tab.oracle' , nav: 'nav.oracle', tagK: 'about.tag.oracle' },
  { name: 'Contact', to: '/contact', icon: CandlestickChart, tag: 'Reach out', k: 'about.tab.contact' , nav: 'nav.contact', tagK: 'about.tag.contact' },
] as const

const FEATURE_GROUPS = [
  {
    k: 'about.fg.price',
    items: ['RSI', 'MACD', 'Bollinger position', 'Dist 52w high/low', 'Pre-earn momentum 5/10/20d'],
  },
  {
    k: 'about.fg.macro',
    items: ['VIX / VIX9D', 'Yield curve slope', '10y yield', 'CPI / PCE YoY', 'HYG-LQD spread', 'Fed funds rate'],
  },
  {
    k: 'about.fg.options',
    items: ['IV rank', 'IV 52w high', 'ATM straddle / spot', 'Put/call ratio', 'Put/call skew', 'Expected move %'],
  },
  {
    k: 'about.fg.funda',
    items: [
      'EPS surprise %',
      'Forward EPS avg / low / high',
      'Forward revenue growth',
      'Analyst target upside',
      'Analyst target dispersion',
      'Recommendation mean',
      'Profit margins',
      'Debt / equity',
      'Return on equity',
    ],
  },
  {
    k: 'about.fg.pos',
    items: ['Short ratio', 'Short % float', 'Institutional ownership', 'Days to cover'],
  },
  {
    k: 'about.fg.sent',
    items: ['News headline sentiment', 'Positive news ratio', '10-Q MD&A sentiment', 'Forward-looking sentiment', 'Risk language intensity'],
  },
] as const

// Author-year citations stay in the original regardless of locale — translating
// "Zuckerman (2019)" would make the source harder to look up, not easier.
const CITATIONS: Record<string, string> = {
  'about.bm.rentec': 'Zuckerman, The Man Who Solved the Market (2019)',
  'about.bm.pead': 'Kaczmarek & Zaremba (2025); Cohen-Malloy-Nguyen, Lazy Prices (JoF 2020)',
  'about.bm.gpt': 'Kim, Muhn & Nikolaev, arXiv 2407.17866 (2024)',
}

const BENCHMARKS = [
  { k: 'about.bm.random', value: 33.3, sourceLink: null, tint: 'muted' },
  // The always-FLAT bar is computed from the same 5,477 held-out events the model is
  // scored on, using each stock's own band. It read 50.0% with a "~±2%" note while the
  // paragraph above it said 60.6% — two numbers for one quantity, on one page.
  { k: 'about.bm.flat', value: 60.7, sourceLink: null, tint: 'muted' },
  {
    k: 'about.bm.rentec',
    value: 50.75,
    sourceLink: 'https://novelinvestor.com/notes/the-man-who-solved-the-market-by-gregory-zuckerman/',
    tint: 'amber',
  },
  { k: 'about.bm.self', value: 59.9, sourceLink: null, tint: 'cyan' },
  {
    k: 'about.bm.pead',
    value: 56.0,
    sourceLink: 'https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12885',
    tint: 'emerald',
  },
  {
    k: 'about.bm.gpt',
    value: 60.4,
    sourceLink: 'https://arxiv.org/abs/2407.17866',
    tint: 'purple',
  },
]

const ROADMAP = [
  {
    k: 'about.rm.now',
    state: 'shipped',
    items: [
      'Purged walk-forward CV, 81 folds across 9 sector models',
      'Manual class upsampling vs FLAT-bias',
      'FinBERT 10-Q MD&A sentiment',
      'SHAP per-prediction attribution',
    ],
  },
  {
    k: 'about.rm.next',
    state: 'in-progress',
    items: [
      'Combinatorial Purged CV (L\u00F3pez de Prado)',
      'Deflated Sharpe Ratio reporting',
      'Conformal prediction intervals',
      'Polygon.io options-flow integration',
    ],
  },
  {
    k: 'about.rm.research',
    state: 'planned',
    items: [
      'Lazy-Prices YoY transcript similarity',
      'Form 4 opportunistic-insider classifier',
      'Multi-modal late fusion (text + tabular)',
      'Meta-labeling per AFML Ch. 3',
    ],
  },
] as const

// ============================================================
//  Decorative SVG: animated wave grid behind the hero
// ============================================================

function HeroBackdrop() {
  // Two <path> elements previously shared one ref. React assigns in order, so the
  // second overwrote the first and only the faint 0.6px/40%-opacity echo ever
  // received a `d` attribute — the main 1.6px wave was never drawn at all.
  const pathRef = useRef<SVGPathElement>(null)
  const echoRef = useRef<SVGPathElement>(null)
  useEffect(() => {
    const path = pathRef.current
    if (!path) return
    let raf = 0
    let t = 0
    const loop = () => {
      t += 0.015
      const w = 1200
      const h = 320
      const segs: string[] = []
      const points = 24
      for (let i = 0; i <= points; i++) {
        const x = (i / points) * w
        const y = h / 2 + Math.sin(t + i * 0.4) * 30 + Math.cos(t * 0.6 + i * 0.21) * 18
        segs.push(`${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`)
      }
      const d = segs.join(' ')
      path.setAttribute('d', d)
      echoRef.current?.setAttribute('d', d)
      raf = requestAnimationFrame(loop)
    }
    loop()
    return () => cancelAnimationFrame(raf)
  }, [])
  return (
    <svg
      className="hero-backdrop"
      viewBox="0 0 1200 320"
      preserveAspectRatio="none"
      aria-hidden
    >
      <defs>
        <linearGradient id="waveGrad" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="rgba(56,189,248,0)" />
          <stop offset="35%" stopColor="rgba(56,189,248,0.55)" />
          <stop offset="65%" stopColor="rgba(167,139,250,0.55)" />
          <stop offset="100%" stopColor="rgba(167,139,250,0)" />
        </linearGradient>
        <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
          <path d="M 40 0 L 0 0 0 40" fill="none" stroke="rgba(148,163,214,0.06)" strokeWidth="1" />
        </pattern>
      </defs>
      <rect width="1200" height="320" fill="url(#grid)" />
      <path ref={pathRef} stroke="url(#waveGrad)" strokeWidth="1.6" fill="none" />
      <path ref={echoRef} stroke="url(#waveGrad)" strokeWidth="0.6" fill="none" opacity="0.4" />
    </svg>
  )
}

// ============================================================
//  Animated counter for benchmark bar
// ============================================================

function Counter({ value, decimals = 1 }: { value: number; decimals?: number }) {
  const [n, setN] = useState(0)
  useEffect(() => {
    let raf = 0
    const start = performance.now()
    const dur = 1100
    const tick = (now: number) => {
      const e = Math.min(1, (now - start) / dur)
      const ease = 1 - Math.pow(1 - e, 3)
      setN(value * ease)
      if (e < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [value])
  return <>{n.toFixed(decimals)}</>
}

// ============================================================
//  Main Page
// ============================================================

export function AboutPage() {
  const { t } = useT()
  const sectionVariants = useMemo(
    () => ({
      hidden: { opacity: 0, y: 18 },
      visible: { opacity: 1, y: 0, transition: { duration: 0.5, ease: 'easeOut' as const } },
    }),
    [],
  )

  return (
    <div className="about-page">
      {/* ============= HERO ============= */}
      <section className="about-hero">
        <HeroBackdrop />
        <motion.div
          className="about-hero__inner"
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: 'easeOut' }}
        >
          <div className="about-hero__eyebrow">
            <Sparkles size={14} />
            <span>About this project</span>
          </div>
          <h1 className="about-hero__title">
            {t('about.hero.line1')}
            <br />
            <span className="about-hero__title-grad">{t('about.hero.line2')}</span>
          </h1>
          <p className="about-hero__lede">{t('about.hero.lede')}</p>
          <div className="about-hero__stats">
            {STAT_ROW.map((s) => (
              <div key={s.labelKey} className={`about-stat about-stat--${s.tint}`}>
                <div className="about-stat__value">{s.value}</div>
                <div className="about-stat__label">{t(s.labelKey as never)}</div>
              </div>
            ))}
          </div>
        </motion.div>
      </section>

      {/* ============= TAB GUIDE ============= */}
      <motion.section
        className="about-section"
        variants={sectionVariants}
        initial="hidden"
        whileInView="visible"
        viewport={{ once: true, margin: '-80px' }}
      >
        <div className="about-section__header">
          <div className="about-section__kicker">
            <Activity size={12} />
            <span>{t('about.nav.kicker')}</span>
          </div>
          <h2 className="about-section__title">{t('about.nav.title')}</h2>
          <p className="about-section__sub">{t('about.nav.sub')}</p>
        </div>

        <div className="about-tabs">
          {/* The map variable used to be named `t`, which shadowed the i18n `t` inside
              this entire block — the reason these seven cards stayed English while the
              rest of the page translated. */}
          {TAB_GUIDE.map((tab, i) => {
            const Icon = tab.icon
            return (
              <motion.div
                key={tab.name}
                className="about-tab-card"
                initial={{ opacity: 0, y: 16 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.45, delay: i * 0.08 }}
                whileHover={{ y: -4 }}
              >
                <div className="about-tab-card__head">
                  <div className="about-tab-card__iconwrap">
                    <Icon size={20} />
                  </div>
                  <div className="about-tab-card__tag">{t(tab.tagK as never)}</div>
                </div>
                <div className="about-tab-card__name">{t(tab.nav as never)}</div>
                <p className="about-tab-card__blurb">{t(`${tab.k}.blurb` as never)}</p>
                <ul className="about-tab-card__actions">
                  {[0, 1, 2].map((ai) => (
                    <li key={ai}>
                      <span className="about-tab-card__bullet" />
                      {t(`${tab.k}.a${ai}` as never)}
                    </li>
                  ))}
                </ul>
                <NavLink to={tab.to} className="about-tab-card__cta">
                  {t('about.tab.open', { name: t(tab.nav as never) })}
                  <ArrowRight size={14} />
                </NavLink>
              </motion.div>
            )
          })}
        </div>
      </motion.section>

      {/* ============= PIPELINE ============= */}
      <motion.section
        className="about-section"
        variants={sectionVariants}
        initial="hidden"
        whileInView="visible"
        viewport={{ once: true, margin: '-80px' }}
      >
        <div className="about-section__header">
          <div className="about-section__kicker">
            <Cpu size={12} />
            <span>{t('about.pipeline.kicker')}</span>
          </div>
          <h2 className="about-section__title">{t('about.pipeline.title')}</h2>
        </div>

        <div className="about-pipeline">
          {PIPELINE.map((step, i) => {
            const Icon = step.icon
            return (
              <div key={step.k} className="about-pipeline__step">
                <motion.div
                  className={`about-pipeline__node about-pipeline__node--${step.tint}`}
                  initial={{ opacity: 0, scale: 0.7 }}
                  whileInView={{ opacity: 1, scale: 1 }}
                  viewport={{ once: true }}
                  transition={{ duration: 0.4, delay: i * 0.12 }}
                >
                  <Icon size={22} />
                </motion.div>
                <motion.div
                  className="about-pipeline__meta"
                  initial={{ opacity: 0, y: 6 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true }}
                  transition={{ duration: 0.4, delay: 0.15 + i * 0.12 }}
                >
                  <div className="about-pipeline__name">{t(step.k as never)}</div>
                  <div className="about-pipeline__detail">{t(`${step.k}.d` as never)}</div>
                </motion.div>
                {i < PIPELINE.length - 1 && (
                  <motion.div
                    className="about-pipeline__connector"
                    initial={{ scaleX: 0 }}
                    whileInView={{ scaleX: 1 }}
                    viewport={{ once: true }}
                    transition={{ duration: 0.5, delay: 0.25 + i * 0.12 }}
                  />
                )}
              </div>
            )
          })}
        </div>
      </motion.section>

      {/* ============= FEATURE TAXONOMY ============= */}
      <motion.section
        className="about-section"
        variants={sectionVariants}
        initial="hidden"
        whileInView="visible"
        viewport={{ once: true, margin: '-80px' }}
      >
        <div className="about-section__header">
          <div className="about-section__kicker">
            <GitBranch size={12} />
            <span>{t('about.tax.kicker')}</span>
          </div>
          <h2 className="about-section__title">{t('about.tax.title')}</h2>
          <p className="about-section__sub">{t('about.tax.sub')}</p>
        </div>

        <div className="about-features">
          {FEATURE_GROUPS.map((g, i) => (
            <motion.div
              key={g.k}
              className="about-feature-group"
              initial={{ opacity: 0, y: 14 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.4, delay: i * 0.06 }}
            >
              <div className="about-feature-group__title">{t(g.k as never)}</div>
              <div className="about-feature-group__list">
                {g.items.map((it) => (
                  <span key={it} className="about-feature-chip">
                    {it}
                  </span>
                ))}
              </div>
            </motion.div>
          ))}
        </div>
      </motion.section>

      {/* ============= SIGNIFICANCE ============= */}
      <motion.section
        className="about-section about-section--accent"
        variants={sectionVariants}
        initial="hidden"
        whileInView="visible"
        viewport={{ once: true, margin: '-80px' }}
      >
        <div className="about-section__header">
          <div className="about-section__kicker">
            <Target size={12} />
            <span>{t('about.lit.kicker')}</span>
          </div>
          <h2 className="about-section__title">{t('about.finding.title')}</h2>
          <p className="about-section__sub">{t('about.finding.body')}</p>
        </div>

        <div className="benchmark-stack">
          {BENCHMARKS.map((b, i) => (
            <motion.div
              key={b.k}
              className={`benchmark-row benchmark-row--${b.tint}`}
              initial={{ opacity: 0, x: -20 }}
              whileInView={{ opacity: 1, x: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.5, delay: i * 0.1 }}
            >
              <div className="benchmark-row__head">
                <div className="benchmark-row__label">{t(b.k as never)}</div>
                <div className="benchmark-row__value">
                  <Counter value={b.value} />
                  <span className="benchmark-row__pct">%</span>
                </div>
              </div>
              <div className="benchmark-row__bar">
                <motion.div
                  className="benchmark-row__bar-fill"
                  initial={{ width: 0 }}
                  whileInView={{ width: `${b.value}%` }}
                  viewport={{ once: true }}
                  transition={{ duration: 1.1, delay: 0.2 + i * 0.1, ease: 'easeOut' }}
                />
              </div>
              <div className="benchmark-row__foot">
                <span className="benchmark-row__detail">{t(`${b.k}.d` as never)}</span>
                <span className="benchmark-row__source">
                  {b.sourceLink ? (
                    <a href={b.sourceLink} target="_blank" rel="noreferrer noopener">
                      {CITATIONS[b.k]}
                    </a>
                  ) : (
                    t(`${b.k}.s` as never)
                  )}
                </span>
              </div>
            </motion.div>
          ))}
        </div>

        <div className="about-callout">
          <div className="about-callout__icon">
            <TrendingUp size={18} />
          </div>
          <div className="about-callout__body">
            <div className="about-callout__title">{t('about.rentec.title')}</div>
            <p>{t('about.rentec.body')}</p>
          </div>
        </div>
      </motion.section>

      {/* ============= ROADMAP ============= */}
      <motion.section
        className="about-section"
        variants={sectionVariants}
        initial="hidden"
        whileInView="visible"
        viewport={{ once: true, margin: '-80px' }}
      >
        <div className="about-section__header">
          <div className="about-section__kicker">
            <LineChart size={12} />
            <span>{t('about.roadmap.kicker')}</span>
          </div>
          <h2 className="about-section__title">{t('about.roadmap.title')}</h2>
        </div>

        <div className="about-roadmap">
          {ROADMAP.map((r, i) => (
            <motion.div
              key={r.k}
              className={`about-roadmap__col about-roadmap__col--${r.state}`}
              initial={{ opacity: 0, y: 16 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.45, delay: i * 0.1 }}
            >
              <div className="about-roadmap__phase">
                <span className="about-roadmap__dot" />
                {t(r.k as never)}
              </div>
              <ul className="about-roadmap__list">
                {r.items.map((it) => (
                  <li key={it}>{it}</li>
                ))}
              </ul>
            </motion.div>
          ))}
        </div>
      </motion.section>

      {/* ============= STACK ============= */}
      <motion.section
        className="about-section"
        variants={sectionVariants}
        initial="hidden"
        whileInView="visible"
        viewport={{ once: true, margin: '-80px' }}
      >
        <div className="about-section__header">
          <div className="about-section__kicker">
            <CircuitBoard size={12} />
            <span>{t('about.stack.kicker')}</span>
          </div>
          <h2 className="about-section__title">{t('about.stack.title')}</h2>
        </div>

        <div className="about-stack-grid">
          {[
            { l: 'Backend', v: 'FastAPI · SQLAlchemy 2 · PostgreSQL 16' },
            { l: 'Models', v: 'XGBoost · LightGBM · scikit-learn · SHAP' },
            { l: 'NLP', v: 'FinBERT (ProsusAI) · transformers · torch' },
            { l: 'Frontend', v: 'React 18 · TypeScript · Vite · framer-motion · recharts' },
            { l: 'Data', v: 'yfinance · SEC EDGAR · FRED · Financial Modeling Prep' },
            { l: 'Infra', v: 'Docker Compose · Redis · APScheduler' },
          ].map((s) => (
            <div key={s.l} className="about-stack-cell">
              <div className="about-stack-cell__l">{s.l}</div>
              <div className="about-stack-cell__v">{s.v}</div>
            </div>
          ))}
        </div>
      </motion.section>

      {/* ============= CTA ============= */}
      <motion.section
        className="about-cta"
        initial={{ opacity: 0, y: 24 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true }}
        transition={{ duration: 0.5 }}
      >
        <div className="about-cta__title">{t('about.cta.title')}</div>
        <p className="about-cta__sub">{t('about.cta.sub')}</p>
        <div className="about-cta__actions">
          <NavLink to="/" className="about-cta__primary">
            {t('about.cta.primary')}
            <ArrowRight size={14} />
          </NavLink>
          <NavLink to="/contact" className="about-cta__secondary">
            {t('about.cta.secondary')}
          </NavLink>
        </div>
      </motion.section>
    </div>
  )
}
