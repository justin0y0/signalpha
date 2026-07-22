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
  { icon: Database, label: 'Ingestion', detail: 'yfinance · SEC EDGAR · FRED · FMP', tint: 'cyan' },
  { icon: CircuitBoard, label: 'Feature engineering', detail: 'price · macro · options · sentiment', tint: 'purple' },
  { icon: Brain, label: 'FinBERT NLP', detail: 'news headlines + 10-Q MD&A scoring', tint: 'emerald' },
  { icon: Network, label: 'Sector ensembles', detail: 'XGBoost served · LGBM + LogReg trained', tint: 'amber' },
  { icon: Eye, label: 'SHAP attribution', detail: 'tree-explainer per prediction', tint: 'cyan' },
] as const

const TAB_GUIDE = [
  {
    name: 'Calendar',
    to: '/',
    icon: Calendar,
    tag: 'Live',
    blurb:
      'Every upcoming earnings release, scored for stillness rather than direction. Each row shows the full probability distribution the model produced — UP, FLAT and DOWN held in superposition — with the flat score leading, because that is the call the model can actually make.',
    actions: [
      'Cluster tightness in the hero is P(FLAT); the cursor pushes through the field',
      'Rows stay superposed until an outcome exists, then collapse to one state',
      'Click any row for the per-stock deep dive',
    ],
  },
  {
    name: 'Brief',
    to: '/brief',
    icon: ClipboardList,
    tag: 'Daily',
    blurb:
      'The next seven days of earnings, split into likely non-events and likely moves, with implied vol alongside. Rendered from data with no model in the loop, so it cannot invent a number. Sign in and star tickers to narrow it to your own names.',
    actions: [
      'Quiet list is the model\u2019s one validated skill: 76.4% against a 60.7% base rate',
      'ATM IV sits next to the quiet score because that pairing is what premium sellers screen for',
      'Watchlist personalisation requires an account; the brief itself is public',
    ],
  },
  {
    name: 'Model',
    to: '/model',
    icon: BarChart3,
    tag: 'Diagnostic',
    blurb:
      'How good the model is, stated against the bar it has to clear. Accuracy is shown next to the always-FLAT baseline, because a three-class accuracy figure means nothing on its own. Includes per-sector metrics, SHAP attribution, a confusion matrix, and the full prediction record joined to realised outcomes.',
    actions: [
      'Accuracy vs baseline is computed from the confusion matrix on the same page',
      'Confidence tiers rise only because the model is choosing FLAT \u2014 watch the directional column',
      'Prediction Record shows every out-of-sample call, including the losing ones',
    ],
  },
  {
    name: 'Strategy',
    to: '/strategy',
    icon: ChartLine,
    tag: 'Research',
    blurb:
      'Three harnesses over the same signal: an interactive backtest, five strategy personas racing on T+5, and a $1M paper account. Above them sits each stock\u2019s own flat band drawn to scale \u2014 the reason a 2% move means different things to different names.',
    actions: [
      'Backtest settles on T+1; Showdown on T+5 with the gap removed for post-earnings entries',
      'Probabilities are calibrated, so useful thresholds sit near 0.40 rather than 0.65',
      'Paper account resolves stops against the realised price path, not the closing mark',
    ],
  },
  {
    name: 'Pulse',
    to: '/pulse',
    icon: Activity,
    tag: 'Real-time',
    blurb:
      'Intraday scanner over roughly 100 large-caps. \u03a3 combines Avellaneda\u2013Lee mean reversion (0.55), Gao 2018 intraday momentum (0.25) and a Connors RSI(2) regime term (0.15), damped by a volume z-score. Trades fire at |\u03a3| \u2265 0.50; alerts at 0.60.',
    actions: [
      'Background turbulence is driven by the same breadth the page reports',
      'Track record is public: 200 closed trades, profit factor 0.979 before costs',
      'The conviction score has no measured relationship to outcome \u2014 Spearman +0.04',
    ],
  },
  {
    name: 'Oracle',
    to: '/oracle',
    icon: Trophy,
    tag: 'Signals',
    blurb:
      'Ten market-moving figures, watched for stock mentions. An LLM extracts ticker, direction and conviction from news and posts; every ticker is price-validated before it is stored. The feed shows subsequent price action honestly, including the calls that went wrong.',
    actions: [
      'Avatars are symbolic pixel art, never real likenesses',
      'X/Twitter is unreachable from the server, so Musk and Serenity stay quiet',
      'A negative return badge is not a bug \u2014 that figure was wrong that time',
    ],
  },
  {
    name: 'Contact',
    to: '/contact',
    icon: CandlestickChart,
    tag: 'Reach out',
    blurb:
      'Questions, corrections, or a role you think fits. If you find a number on this site you think is wrong, that is the most useful message you can send.',
    actions: [
      'Every figure here is reproducible from the repository',
      'Corrections are published, not quietly patched',
      'Research and education only \u2014 not investment advice',
    ],
  },
] as const

const FEATURE_GROUPS = [
  {
    title: 'Price & momentum',
    items: ['RSI', 'MACD', 'Bollinger position', 'Dist 52w high/low', 'Pre-earn momentum 5/10/20d'],
  },
  {
    title: 'Macro regime',
    items: ['VIX / VIX9D', 'Yield curve slope', '10y yield', 'CPI / PCE YoY', 'HYG-LQD spread', 'Fed funds rate'],
  },
  {
    title: 'Options surface',
    items: ['IV rank', 'IV 52w high', 'ATM straddle / spot', 'Put/call ratio', 'Put/call skew', 'Expected move %'],
  },
  {
    title: 'Fundamentals & analyst',
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
    title: 'Positioning',
    items: ['Short ratio', 'Short % float', 'Institutional ownership', 'Days to cover'],
  },
  {
    title: 'Sentiment (FinBERT)',
    items: ['News headline sentiment', 'Positive news ratio', '10-Q MD&A sentiment', 'Forward-looking sentiment', 'Risk language intensity'],
  },
] as const

const BENCHMARKS = [
  {
    label: 'Random baseline',
    value: 33.3,
    detail: '3-class equally-weighted prior',
    source: 'Theoretical',
    sourceLink: null,
    tint: 'muted',
  },
  {
    label: 'Always-FLAT baseline (this dataset)',
    value: 50.0,
    detail: 'Always predict no-move (~\u00B12%)',
    source: 'Class distribution',
    sourceLink: null,
    tint: 'muted',
  },
  {
    label: 'Renaissance Medallion (live)',
    value: 50.75,
    detail: 'Per-trade directional accuracy across ~300k trades/yr',
    source: 'Zuckerman, The Man Who Solved the Market (2019)',
    sourceLink:
      'https://novelinvestor.com/notes/the-man-who-solved-the-market-by-gregory-zuckerman/',
    tint: 'amber',
  },
  {
    label: 'Signalpha (this project)',
    value: 59.9,
    detail: 'Walk-forward OOS — below the 60.7% always-FLAT baseline',
    source: 'Purged walk-forward, 5,477 held-out events · per-stock labelling (2026-07-21)',
    sourceLink: null,
    tint: 'cyan',
  },
  {
    label: 'PEAD academic literature',
    value: 56.0,
    detail: 'Best-published direction models w/ rigorous walk-forward',
    source: 'Kaczmarek & Zaremba (2025); Cohen-Malloy-Nguyen, Lazy Prices (JoF 2020)',
    sourceLink: 'https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12885',
    tint: 'emerald',
  },
  {
    label: 'GPT-4 + chain-of-thought (experimental)',
    value: 60.4,
    detail: 'On standardised statements, narrow universe',
    source: 'Kim, Muhn & Nikolaev, arXiv 2407.17866 (2024)',
    sourceLink: 'https://arxiv.org/abs/2407.17866',
    tint: 'purple',
  },
]

const ROADMAP = [
  {
    phase: 'Now',
    state: 'shipped',
    items: [
      'Walk-forward CV with 47 folds',
      'Manual class upsampling vs FLAT-bias',
      'FinBERT 10-Q MD&A sentiment',
      'SHAP per-prediction attribution',
    ],
  },
  {
    phase: 'Next',
    state: 'in-progress',
    items: [
      'Combinatorial Purged CV (L\u00F3pez de Prado)',
      'Deflated Sharpe Ratio reporting',
      'Conformal prediction intervals',
      'Polygon.io options-flow integration',
    ],
  },
  {
    phase: 'Research',
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
  const pathRef = useRef<SVGPathElement>(null)
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
      path.setAttribute('d', segs.join(' '))
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
      <path ref={pathRef as any} stroke="url(#waveGrad)" strokeWidth="0.6" fill="none" opacity="0.4" />
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
            An ML earnings signal,
            <br />
            <span className="about-hero__title-grad">engineered like a quant fund.</span>
          </h1>
          <p className="about-hero__lede">
            Signalpha forecasts the post-earnings price reaction of US large-caps using a 102-feature
            ensemble that fuses price action, options surface, macro regime, fundamentals, analyst
            consensus, and FinBERT-scored news + 10-Q sentiment. Walk-forward validated. Sector-stratified.
            SHAP-explained. End-to-end open source.
          </p>
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
            <span>How to navigate</span>
          </div>
          <h2 className="about-section__title">Five primary surfaces.</h2>
          <p className="about-section__sub">
            Each tab isolates a layer of the workflow — calendar, deep-dive prediction, walk-forward diagnostics, backtested signal performance, and a live paper-trading simulator.
          </p>
        </div>

        <div className="about-tabs">
          {TAB_GUIDE.map((t, i) => {
            const Icon = t.icon
            return (
              <motion.div
                key={t.name}
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
                  <div className="about-tab-card__tag">{t.tag}</div>
                </div>
                <div className="about-tab-card__name">{t.name}</div>
                <p className="about-tab-card__blurb">{t.blurb}</p>
                <ul className="about-tab-card__actions">
                  {t.actions.map((a) => (
                    <li key={a}>
                      <span className="about-tab-card__bullet" />
                      {a}
                    </li>
                  ))}
                </ul>
                <NavLink to={t.to} className="about-tab-card__cta">
                  Open {t.name}
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
            <span>The pipeline</span>
          </div>
          <h2 className="about-section__title">From raw filing to signal in five stages.</h2>
        </div>

        <div className="about-pipeline">
          {PIPELINE.map((step, i) => {
            const Icon = step.icon
            return (
              <div key={step.label} className="about-pipeline__step">
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
                  <div className="about-pipeline__name">{step.label}</div>
                  <div className="about-pipeline__detail">{step.detail}</div>
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
            <span>Feature taxonomy</span>
          </div>
          <h2 className="about-section__title">102 engineered features across six families.</h2>
          <p className="about-section__sub">
            Every feature is computed point-in-time so no information that wouldn't have been available
            ahead of the earnings event leaks into the prediction.
          </p>
        </div>

        <div className="about-features">
          {FEATURE_GROUPS.map((g, i) => (
            <motion.div
              key={g.title}
              className="about-feature-group"
              initial={{ opacity: 0, y: 14 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.4, delay: i * 0.06 }}
            >
              <div className="about-feature-group__title">{g.title}</div>
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
            <span>Where this sits in the literature</span>
          </div>
          <h2 className="about-section__title">{t('about.finding.title')}</h2>
          <p className="about-section__sub">
            Directional earnings prediction on US large-caps is one of the most informationally
            efficient settings in markets — and on this dataset the model has no directional edge:
            it commits to a direction on roughly 2.5% of events and is right about half of
            those, which is indistinguishable from chance. Where it does show measurable skill
            is the opposite question: at P(FLAT) ≥ 0.60 it correctly identifies a non-event
            <b>76.4%</b> of the time against a 60.7% base rate (n=1,058). Each stock is now
            labelled against half its own historical earnings-reaction sigma rather than a fixed
            ±2% — MMM at ±2.5%, TSLA at ±4.4% — which lifted that figure from 66.6%. These
            numbers come from a walk-forward rebuild that replaced an earlier backfill
            contaminated by look-ahead; the contaminated version reported a 97.5% win rate.
          </p>
        </div>

        <div className="benchmark-stack">
          {BENCHMARKS.map((b, i) => (
            <motion.div
              key={b.label}
              className={`benchmark-row benchmark-row--${b.tint}`}
              initial={{ opacity: 0, x: -20 }}
              whileInView={{ opacity: 1, x: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.5, delay: i * 0.1 }}
            >
              <div className="benchmark-row__head">
                <div className="benchmark-row__label">{b.label}</div>
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
                <span className="benchmark-row__detail">{b.detail}</span>
                <span className="benchmark-row__source">
                  {b.sourceLink ? (
                    <a href={b.sourceLink} target="_blank" rel="noreferrer noopener">
                      {b.source}
                    </a>
                  ) : (
                    b.source
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
            <div className="about-callout__title">A note on the Renaissance comparison.</div>
            <p>
              Medallion's per-trade directional accuracy of roughly 50.75% is famous because it is paired
              with breadth on the order of 300,000 trades per year — Grinold's fundamental law,
              IR &asymp; IC&nbsp;&times;&nbsp;&radic;Breadth, is doing most of the work. Signalpha is
              the opposite shape: a narrow window (a few hundred earnings events per year), which means
              the per-event accuracy bar is meaningfully higher. Anything materially above 60% on liquid
              US mega-caps is, in the published literature, a strong indicator of data leakage rather
              than alpha.
            </p>
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
            <span>Roadmap</span>
          </div>
          <h2 className="about-section__title">What's shipped, what's next, what's research.</h2>
        </div>

        <div className="about-roadmap">
          {ROADMAP.map((r, i) => (
            <motion.div
              key={r.phase}
              className={`about-roadmap__col about-roadmap__col--${r.state}`}
              initial={{ opacity: 0, y: 16 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.45, delay: i * 0.1 }}
            >
              <div className="about-roadmap__phase">
                <span className="about-roadmap__dot" />
                {r.phase}
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
            <span>Tech stack</span>
          </div>
          <h2 className="about-section__title">Pragmatic and production-shaped.</h2>
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
        <div className="about-cta__title">Curious about the implementation?</div>
        <p className="about-cta__sub">
          Walk through the live signals, dig into the diagnostics, run the backtest, or watch the paper-trading simulator deploy the model on a virtual $1M book.
        </p>
        <div className="about-cta__actions">
          <NavLink to="/" className="about-cta__primary">
            Open the calendar
            <ArrowRight size={14} />
          </NavLink>
          <NavLink to="/contact" className="about-cta__secondary">
            Contact me
          </NavLink>
        </div>
      </motion.section>
    </div>
  )
}
