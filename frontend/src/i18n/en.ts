/**
 * English copy — the source of truth.
 *
 * Every user-visible string that has a Chinese counterpart lives here. Keys are
 * `page.thing`, flat and greppable, so finding where a phrase renders is one search.
 * Add here first; `zh.ts` is typed against this object, so a missing or misspelled
 * Chinese key is a build error rather than a page that silently stays English.
 */
export const en = {
  // ── Navigation ────────────────────────────────────────────────────────────
  'nav.calendar': 'Calendar',
  'nav.brief': 'Brief',
  'nav.model': 'Model',
  'nav.strategy': 'Strategy',
  'nav.pulse': 'Pulse',
  'nav.oracle': 'Oracle',
  'nav.about': 'About',
  'nav.contact': 'Contact',
  'nav.trial': 'Start free trial',
  'nav.language': 'Language',

  // ── Calendar ──────────────────────────────────────────────────────────────
  'cal.hero.title': 'Which earnings will be non-events',
  'cal.hero.sub':
    '{n} reports ahead. Tight clusters are the ones the model expects to pass quietly — the one call it makes measurably well.',
  'cal.stat.tracked': 'Tracked events',
  'cal.stat.tracked.helper': 'rolling 120-day window',
  'cal.stat.next7': 'Next 7 days',
  'cal.stat.next7.helper': 'upcoming reports',
  'cal.stat.withPrediction': 'With ML prediction',
  'cal.stat.coverage': '{pct}% coverage',
  'cal.sector.all': 'All',
  'cal.stat.quiet': 'Likely quiet',
  'cal.stat.quiet.helper': "P(FLAT) ≥ 60% · the model's one validated skill",
  'cal.search': 'Search',
  'cal.search.placeholder': 'Ticker or company…',
  'cal.sector': 'Sector',
  'cal.live': 'Live data',
  'cal.col.ticker': 'Ticker',
  'cal.col.company': 'Company',
  'cal.col.sector': 'Sector',
  'cal.col.date': 'Earnings date',
  'cal.col.forecast': 'Forecast · superposed',
  'cal.col.move': 'Expected move',
  'cal.empty': 'No events match your filters.',
  'cal.today': 'Today',
  'cal.tracked': 'tracked',
  'cal.readsQuiet': 'reads quiet',
  'cal.readsLoud': 'reads loud',

  // ── Forecast wording ──────────────────────────────────────────────────────
  'forecast.likelyQuiet': 'likely quiet',
  'forecast.leaningQuiet': 'leaning quiet',
  'forecast.moveExpected': 'move expected',
  'forecast.resolved': 'resolved {outcome}',

  // ── Brief ─────────────────────────────────────────────────────────────────
  'brief.title': 'Alpha Brief',
  'brief.sub':
    'Earnings in the next {days} days, sorted by how likely the model thinks each one is to be a non-event.',
  'brief.personalised': ' Personalised to your {n}-ticker watchlist.',
  'brief.signIn': ' Sign in and star tickers to personalise this.',
  'brief.stat.ahead': 'Earnings ahead',
  'brief.stat.quiet': 'Likely quiet',
  'brief.stat.loud': 'Move expected',
  'brief.stat.watchlist': 'Watchlist',
  'brief.section.quiet': 'Likely quiet',
  'brief.section.loud': 'Move expected',
  'brief.note':
    'Highest-conviction non-events — 76.4% correct against a 60.7% base rate. The IV column is here because that combination is what premium sellers screen for.',
  'brief.empty': 'No earnings in this window.',
  'brief.col.iv': 'ATM IV',

  // ── Model ─────────────────────────────────────────────────────────────────
  'model.tab.quality': 'Model quality',
  'model.tab.record': 'Prediction record',
  'model.baseline.title': 'Accuracy vs baseline',
  'model.baseline.sub':
    'A 3-class accuracy number is only meaningful against the trivial rule it has to beat. FLAT is the majority class here, so “always predict FLAT” is the bar.',
  'model.baseline.model': 'Model',
  'model.baseline.flat': 'Always-FLAT baseline',
  'model.baseline.random': 'Random (1 of 3)',
  'model.baseline.edge': 'Edge over baseline',
  'model.baseline.note':
    'Below the majority-class baseline on 3-class accuracy. The model’s measurable skill is elsewhere: at P(FLAT) ≥ 0.60 it identifies a non-event 76.4% of the time against a 60.7% base rate (n=1,058).',

  // ── Strategy ──────────────────────────────────────────────────────────────
  'strategy.tab.backtest': 'Backtest',
  'strategy.tab.showdown': 'Showdown',
  'strategy.tab.paper': 'Paper account',
  'band.kicker': 'Flat band, to scale',
  'band.title': 'What counts as a move depends on the stock',
  'band.sub':
    'The grey slab is how far this name has to travel before the model calls it a direction — its own historical reaction sigma, not a fixed 2%. The bar is the move it expects.',
  'band.hint': 'sweep across to scrub',
  'band.legend.band': 'flat band for this stock',
  'band.legend.bar': 'expected move',
  'band.legend.breach': 'expected to break out',
  'band.pop.band': 'flat band ±{v}%',
  'band.pop.expected': 'expected ±{v}%',
  'band.pop.breaks': 'expected to break its band',
  'band.pop.stays': 'expected to stay inside',

  // ── Pulse ─────────────────────────────────────────────────────────────────
  'pulse.eyebrow': 'Multi-factor conviction scanner',
  'pulse.title': 'Anomaly detection · 4-factor score',
  'pulse.sub':
    'Σ = Avellaneda–Lee mean reversion (0.55) + Gao 2018 intraday momentum (0.25) + Connors RSI(2) regime (0.15), damped by a volume z-score.',
  'pulse.disclaimer':
    '200 closed trades since 2026-06-03 · 71.5% win rate · profit factor 0.979 before costs',
  'pulse.methodology': 'methodology',

  // ── Oracle ────────────────────────────────────────────────────────────────
  'oracle.title': 'Oracle',
  'oracle.sub':
    "Market-moving voices, read in real time — their words distilled into a signal, a sizing, and the call's realized P&L.",
  'oracle.stat.signals': 'signals · 24h',
  'oracle.stat.tracking': 'tracking',
  'oracle.stat.avg': 'avg call',
  'oracle.scan': 'Scan now',
  'oracle.feed': 'Signal feed',
  'oracle.filter.all': 'All',
  'oracle.filter.bullish': 'Bullish',
  'oracle.filter.bearish': 'Bearish',

  // ── Audio ─────────────────────────────────────────────────────────────────
  'audio.hear': 'hear the week',
  'audio.mute': 'muting',

  // ── Boot ──────────────────────────────────────────────────────────────────
  'boot.skip': 'press any key to skip',
  'boot.link': 'link',
  'boot.linkOk': 'signalpha.app · established',
  'boot.linkBad': 'degraded — showing cached view',
  'boot.calendar': 'calendar',
  'boot.readsQuiet': 'reads quiet',
  'boot.model': 'model',
  'boot.vsBaseline': 'vs baseline',
  'boot.ready': 'ready',
  'boot.notAdvice': 'not investment advice',

  // ── About ─────────────────────────────────────────────────────────────────
  'about.hero.title': 'An instrument for reading earnings risk',
  'about.hero.sub':
    'Signalpha forecasts how much a US large-cap will move on its earnings — not which way. It is transparent about what it can and cannot do, including where it fails.',
  'about.stat.equities': 'Tracked equities',
  'about.stat.events': 'Earnings events',
  'about.stat.features': 'Engineered features',
  'about.stat.folds': 'Sector models',
  'about.finding.kicker': 'What the data actually says',
  'about.finding.title': 'No directional edge. A real one on stillness.',
  'about.finding.body':
    'On purged walk-forward evaluation the model scores 59.9% three-class accuracy against a 60.7% always-FLAT baseline — it does not beat the trivial rule. It commits to a direction on roughly 2.5% of events and is right about half of those, which is indistinguishable from chance. Where it does show measurable skill is the opposite question: when it is confident an event will be a non-event, it is right 76.4% of the time against a 60.7% base rate on 1,058 cases.',
  'about.honesty.kicker': 'What changed, and why you should trust these numbers more',
  'about.honesty.title': 'The previous numbers were wrong. Here is what was fixed.',
  'about.honesty.body':
    'Until 2026-07-20 the historical predictions on this site were backfilled after their outcomes were known, and a calibrator had been fit on those same outcomes and written back over the probabilities. The backtest reported a 97.5% win rate. Every historical prediction has since been rebuilt walk-forward — each event scored by a model trained only on data preceding it — and the probabilities recalibrated on an expanding window. Expected calibration error fell from 0.244 to 0.040.',
  'about.labels.kicker': 'Per-stock labelling',
  'about.labels.title': 'A 2% move means different things to different stocks',
  'about.labels.body':
    'A 2% earnings move is enormous for an industrial and noise for a high-beta name, so the model no longer labels everything against a fixed ±2%. Each stock is scored against half its own historical earnings-reaction sigma, clamped to [2.5%, 10%] — MMM at ±2.5%, TSLA at ±4.4%. Making the target coherent lifted high-confidence non-event accuracy from 66.6% to 76.4%.',
  'about.arch.kicker': 'How it works',
  'about.arch.title': 'Pipeline',
  'about.model.note':
    'Nine sector-stratified models plus a general fallback. The ensemble contains XGBoost, LightGBM and logistic regression, but inference reads the XGBoost estimator directly — evaluation runs through the same path, so the reported accuracy describes what actually serves.',
  'about.bench.title': 'Where this sits',
  'about.bench.sub':
    'Directional earnings prediction on US large-caps is one of the most informationally efficient settings in markets. A few reference points for what these numbers mean.',
  'about.notAdvice': 'Research and education only. Not investment advice.',

  // ── Performance / Model quality ───────────────────────────────────────────
  'perf.title': 'Model Performance Tracker',
  'perf.sub': 'Sector-level accuracy, confusion matrix, and SHAP feature attribution',
  'perf.stat.overall': 'Overall accuracy',
  'perf.stat.best': 'Best sector',
  'perf.stat.worst': 'Worst sector',
  'perf.stat.samples': 'Total samples',
  'perf.tiers.title': 'High-conviction accuracy · confidence tiers',
  'perf.tiers.sub': 'The headline accuracy treats all predictions equally — but trading only uses high-conviction calls. Directional excludes FLAT predictions and FLAT actuals.',
  'perf.sector.title': 'Per-sector performance · accuracy heatmap',
  'perf.shap.title': 'Top feature importance · SHAP',
  'perf.cm.title': 'Confusion matrix',
  'perf.cm.note': 'Rows = actual direction · columns = predicted direction',
  'perf.col.sector': 'Sector',
  'perf.col.accuracy': 'Accuracy',
  'perf.col.precision': 'Precision',
  'perf.col.recall': 'Recall',
  'perf.directional': 'Directional',
  'perf.samples': 'samples',

  // ── Track record ──────────────────────────────────────────────────────────
  'tr.title': 'Track Record',
  'tr.sub': 'Every prediction the model has made — joined against realised outcomes. No cherry-picking.',
  'tr.stat.total': 'Total predictions',
  'tr.stat.hitRate': 'Overall hit rate',
  'tr.stat.highConf': 'High confidence',
  'tr.stat.avgMove': 'Avg actual move',
  'tr.stat.bestSector': 'Best sector',
  'tr.calibration': 'Calibration curve',
  'tr.calibration.sub': 'when the model says X% confident, the actual hit rate should match',
  'tr.rolling': 'Rolling 90-day accuracy',
  'tr.rolling.sub': 'weekly snapshots',
  'tr.recent': 'Recent predictions',
  'tr.bySector': 'Accuracy by sector',

  // ── Backtest ──────────────────────────────────────────────────────────────
  'bt.badge': 'Backtester',
  'bt.title': 'Strategy Simulator',
  'bt.sub': 'Replay the ML signal on historical earnings events. Adjust the confidence threshold and scope to explore risk/return tradeoffs.',
  'bt.field.ticker': 'Ticker',
  'bt.field.sector': 'Sector',
  'bt.field.start': 'Start date',
  'bt.field.end': 'End date',
  'bt.field.threshold': 'Min confidence',
  'bt.run': 'Run backtest',
  'bt.running': 'Running…',
  'bt.allTickers': 'All tickers',
  'bt.allSectors': 'All sectors',
  'bt.kpi.totalReturn': 'Total return',
  'bt.kpi.sharpe': 'Sharpe ratio',
  'bt.kpi.sortino': 'Sortino',
  'bt.kpi.maxdd': 'Max drawdown',
  'bt.kpi.winRate': 'Win rate',
  'bt.kpi.pf': 'Profit factor',
  'bt.kpi.avgWinLoss': 'Avg win / loss',
  'bt.kpi.cagr': 'CAGR',
  'bt.kpi.alpha': 'Alpha vs SPY',
  'bt.kpi.beta': 'Beta',
  'bt.equity': 'Equity curve vs SPY',
  'bt.drawdown': 'Drawdown',
  'bt.dirBreakdown': 'Direction breakdown',
  'bt.noTrades': '{n} events matched, but none cleared a {pct}% probability gate, so there are no trades to report. Probabilities are calibrated to the base rate — try 35–45%.',

  // ── Showdown ──────────────────────────────────────────────────────────────
  'sd.booting': 'Initializing mission control',
  'sd.title': 'Signalpha Mission Control',
  'sd.leader': 'Leader',
  'sd.nextSignal': 'Next signal fires in',
  'sd.trades': 'Trades',
  'sd.sharpe': 'Sharpe',
  'sd.open': 'Open',
  'sd.winRate': 'Win %',
  'sd.raceChart': 'Race chart',
  'sd.signalCalendar': 'Signal calendar',
  'sd.eventLog': 'Event log',

  // ── Deep dive ─────────────────────────────────────────────────────────────
  'dd.back': 'Calendar',
  'dd.stat.direction': 'Predicted direction',
  'dd.stat.move': 'Expected move',
  'dd.stat.band': 'Convergence band',
  'dd.stat.completeness': 'Data completeness',
  'dd.probs': 'Direction probabilities',
  'dd.historical': 'Historical reactions',
  'dd.similar': 'Similar cases',
  'dd.features': 'Feature snapshot',
  'dd.drivers': 'Key drivers',
  'dd.confidence': '{pct}% confidence',
  'dd.horizon': '{d}-day horizon',
  'dd.warnings': '{n} warnings',

  // ── Oracle extras ─────────────────────────────────────────────────────────
  'oracle.whoMoves': 'Who moves markets',
  'oracle.sinceSignal': 'since signal',
  'oracle.size': 'size',
  'oracle.source': 'source',

  // ── Contact ───────────────────────────────────────────────────────────────
  'contact.title': 'Get in touch',
  'contact.sub': 'Questions, feedback, or a role you think fits.',

  // ── Shared ────────────────────────────────────────────────────────────────
  'common.loading': 'Loading…',
  'common.error': 'Something went wrong.',
  'common.retry': 'Retry',
  'common.notAdvice': 'Not investment advice.',
} as const
