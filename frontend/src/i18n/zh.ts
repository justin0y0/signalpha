import type { en } from './en'

/**
 * 简体中文文案。
 *
 * Typed as a partial of `en`, so a misspelled key is a build error and an untranslated
 * key falls through to English at runtime rather than rendering a raw identifier.
 *
 * Translation notes:
 * - Financial terms of art stay in English where that is what a Chinese-speaking quant
 *   actually says: IV, Sharpe, alpha, FLAT, walk-forward, backtest. Translating them
 *   would make the page harder to read for its audience, not easier.
 * - The honest framing is translated in full. The uncomfortable findings — no
 *   directional edge, below baseline, the leakage that was fixed — read exactly as
 *   plainly in Chinese as in English. Softening them in one locale would be the
 *   worst kind of translation choice.
 */
export const zh: Partial<Record<keyof typeof en, string>> = {
  // ── 导航 ──────────────────────────────────────────────────────────────────
  'nav.calendar': '财报日历',
  'nav.brief': '每日简报',
  'nav.model': '模型',
  'nav.strategy': '策略',
  'nav.pulse': '盘中脉搏',
  'nav.oracle': '名人信号',
  'nav.about': '关于',
  'nav.contact': '联系',
  'nav.trial': '开始免费试用',
  'nav.language': '语言',

  // ── 日历 ──────────────────────────────────────────────────────────────────
  'cal.hero.title': '哪些财报不会有事',
  'cal.hero.sub': '未来 {n} 场财报。聚得越紧，模型越认为它会平静度过——这是它唯一经得起检验的判断。',
  'cal.stat.tracked': '追踪事件',
  'cal.stat.tracked.helper': '滚动 120 天窗口',
  'cal.stat.next7': '未来 7 天',
  'cal.stat.next7.helper': '即将发布',
  'cal.stat.withPrediction': '有模型预测',
  'cal.stat.coverage': '覆盖率 {pct}%',
  'cal.sector.all': '全部',
  'cal.stat.quiet': '大概率平静',
  'cal.stat.quiet.helper': 'P(FLAT) ≥ 60% · 模型唯一验证过的能力',
  'cal.search': '搜索',
  'cal.search.placeholder': '代码或公司名…',
  'cal.sector': '板块',
  'cal.live': '实时数据',
  'cal.col.ticker': '代码',
  'cal.col.company': '公司',
  'cal.col.sector': '板块',
  'cal.col.date': '财报日',
  'cal.col.forecast': '预测分布（叠加态）',
  'cal.col.move': '预期波动',
  'cal.empty': '没有符合筛选条件的事件。',
  'cal.today': '今天',
  'cal.tracked': '追踪中',
  'cal.readsQuiet': '判为平静',
  'cal.readsLoud': '判为有动作',

  // ── 预测表述 ──────────────────────────────────────────────────────────────
  'forecast.likelyQuiet': '大概率平静',
  'forecast.leaningQuiet': '偏向平静',
  'forecast.moveExpected': '预期有动作',
  'forecast.resolved': '已揭晓 {outcome}',

  // ── 简报 ──────────────────────────────────────────────────────────────────
  'brief.title': '每日简报',
  'brief.sub': '未来 {days} 天的财报，按模型认为它「不会有事」的可能性排序。',
  'brief.personalised': ' 已按你收藏的 {n} 支股票个性化。',
  'brief.signIn': ' 登录并收藏股票即可个性化。',
  'brief.stat.ahead': '即将发布',
  'brief.stat.quiet': '大概率平静',
  'brief.stat.loud': '预期有动作',
  'brief.stat.watchlist': '自选股',
  'brief.section.quiet': '大概率平静',
  'brief.section.loud': '预期有动作',
  'brief.note':
    '模型最有把握的「非事件」——准确率 76.4%，而基准率是 60.7%。IV 那一列放在这里，是因为「模型说没事 + IV 却很高」正是卖 premium 的人在找的组合。',
  'brief.empty': '这个时间窗内没有财报。',
  'brief.col.iv': '平值 IV',

  // ── 模型 ──────────────────────────────────────────────────────────────────
  'model.tab.quality': '模型质量',
  'model.tab.record': '预测战绩',
  'model.baseline.title': '准确率 vs 基线',
  'model.baseline.sub':
    '三分类准确率脱离基线就没有意义。这里 FLAT 是多数类，所以「无脑全猜 FLAT」就是必须跨过的门槛。',
  'model.baseline.model': '模型',
  'model.baseline.flat': '全押 FLAT 基线',
  'model.baseline.random': '随机（三选一）',
  'model.baseline.edge': '相对基线的差值',
  'model.baseline.note':
    '三分类准确率低于多数类基线。模型真正可测的能力在另一边：当 P(FLAT) ≥ 0.60 时，它识别「非事件」的准确率是 76.4%，而基准率为 60.7%（n=1,058）。',

  // ── 策略 ──────────────────────────────────────────────────────────────────
  'strategy.tab.backtest': '回测',
  'strategy.tab.showdown': '策略对战',
  'strategy.tab.paper': '模拟账户',
  'band.kicker': 'FLAT 带宽（按真实比例）',
  'band.title': '多大算「动了」，取决于是哪只股票',
  'band.sub':
    '灰色块是这只股票要走多远，模型才判定它有方向——用的是它自己的历史反应 sigma，不是固定的 2%。柱子是模型预期的波动幅度。',
  'band.hint': '横向划过以刷动',
  'band.legend.band': '这只股票的 FLAT 带宽',
  'band.legend.bar': '预期波动',
  'band.legend.breach': '预期会突破带宽',
  'band.pop.band': 'FLAT 带宽 ±{v}%',
  'band.pop.expected': '预期 ±{v}%',
  'band.pop.breaks': '预期突破带宽',
  'band.pop.stays': '预期留在带内',

  // ── 盘中脉搏 ──────────────────────────────────────────────────────────────
  'pulse.eyebrow': '多因子信念度扫描',
  'pulse.title': '异动检测 · 4 因子评分',
  'pulse.sub':
    'Σ = Avellaneda–Lee 均值回归（0.55）+ Gao 2018 盘中动量（0.25）+ Connors RSI(2) 趋势状态（0.15），并由成交量 z-score 阻尼。',
  'pulse.disclaimer': '自 2026-06-03 起 200 笔已平仓 · 胜率 71.5% · 未计成本的 profit factor 0.979',
  'pulse.methodology': '方法说明',

  // ── 名人信号 ──────────────────────────────────────────────────────────────
  'oracle.title': '名人信号',
  'oracle.sub': '实时追踪能撬动市场的声音——把他们的言论提炼成信号、仓位建议，以及这次判断的真实盈亏。',
  'oracle.stat.signals': '24 小时信号',
  'oracle.stat.tracking': '追踪中',
  'oracle.stat.avg': '平均收益',
  'oracle.scan': '立即扫描',
  'oracle.feed': '信号流',
  'oracle.filter.all': '全部',
  'oracle.filter.bullish': '看多',
  'oracle.filter.bearish': '看空',

  // ── 声音 ──────────────────────────────────────────────────────────────────
  'audio.hear': '听这一周',
  'audio.mute': '静音',

  // ── 启动自检 ──────────────────────────────────────────────────────────────
  'boot.skip': '按任意键跳过',
  'boot.link': '连接',
  'boot.linkOk': 'signalpha.app · 已建立',
  'boot.linkBad': '连接降级——显示缓存视图',
  'boot.calendar': '日历',
  'boot.readsQuiet': '判为平静',
  'boot.model': '模型',
  'boot.vsBaseline': '相对基线',
  'boot.ready': '就绪',
  'boot.notAdvice': '不构成投资建议',

  // ── 关于 ──────────────────────────────────────────────────────────────────
  'about.hero.title': '一台读取财报风险的仪器',
  'about.hero.sub':
    'Signalpha 预测美股大盘股在财报后会动多大——而不是往哪个方向动。它对自己能做什么、不能做什么保持透明，包括它在哪里失败。',
  'about.stat.equities': '追踪标的',
  'about.stat.events': '财报事件',
  'about.stat.features': '工程化特征',
  'about.stat.folds': '板块模型',
  'about.finding.kicker': '数据实际说了什么',
  'about.finding.title': '没有方向预测能力。但在「平静」上有真本事。',
  'about.finding.body':
    '在 purged walk-forward 评估下，模型三分类准确率 59.9%，而「全押 FLAT」的基线是 60.7%——它没有跑赢这条最简单的规则。它只在约 2.5% 的事件上给出方向判断，其中约一半正确，与抛硬币无法区分。它真正可测的能力在相反的问题上：当它有把握某场财报不会有事时，准确率是 76.4%，而基准率为 60.7%，样本 1,058 例。',
  'about.honesty.kicker': '哪里变了，以及为什么现在的数字更可信',
  'about.honesty.title': '之前的数字是错的。这是修复经过。',
  'about.honesty.body':
    '在 2026-07-20 之前，本站的历史预测是在结果已知之后回填的，而且一个校准器用同一批结果拟合后又把概率覆写了回去，导致回测显示 97.5% 的胜率。此后全部历史预测都用 walk-forward 重建——每个事件只由「训练数据截止于该事件之前」的模型打分——概率也改用扩展窗口重新校准。期望校准误差从 0.244 降到 0.040。',
  'about.labels.kicker': '按股票分别标注',
  'about.labels.title': '2% 的波动，对不同股票意义完全不同',
  'about.labels.body':
    '2% 的财报波动对一只工业股是巨震，对一只高 beta 股只是噪声。所以模型不再用固定的 ±2% 标注所有股票，而是用每只股票自己历史财报反应 sigma 的一半，并限制在 [2.5%, 10%] 之间——MMM 是 ±2.5%，TSLA 是 ±4.4%。把预测目标变得自洽之后，高置信「非事件」判断的准确率从 66.6% 提升到 76.4%。',
  'about.arch.kicker': '它是怎么工作的',
  'about.arch.title': '数据管线',
  'about.model.note':
    '9 个按板块分层的模型加一个通用兜底模型。集成里包含 XGBoost、LightGBM 和逻辑回归，但推理时直接读取 XGBoost 那个估计器——评估走的是同一条路径，所以对外公布的准确率描述的就是线上真正在跑的东西。',
  'about.bench.title': '它处在什么位置',
  'about.bench.sub':
    '预测美股大盘股财报后的涨跌方向，是市场上信息效率最高的场景之一。下面几个参照点用来说明这些数字意味着什么。',
  'about.notAdvice': '仅供研究与教育用途，不构成投资建议。',

  // ── 模型质量 ──────────────────────────────────────────────────────────────
  'perf.title': '模型表现追踪',
  'perf.sub': '按板块的准确率、混淆矩阵与 SHAP 特征归因',
  'perf.stat.overall': '整体准确率',
  'perf.stat.best': '最佳板块',
  'perf.stat.worst': '最差板块',
  'perf.stat.samples': '样本总数',
  'perf.tiers.title': '高置信准确率 · 置信度分层',
  'perf.tiers.sub': '整体准确率把所有预测一视同仁，但实际交易只用高置信的那些。「方向准确率」一列剔除了所有 FLAT 预测和 FLAT 实际结果。',
  'perf.sector.title': '分板块表现 · 准确率热力图',
  'perf.shap.title': '特征重要性 Top · SHAP',
  'perf.cm.title': '混淆矩阵',
  'perf.cm.note': '行 = 实际方向 · 列 = 预测方向',
  'perf.col.sector': '板块',
  'perf.col.accuracy': '准确率',
  'perf.col.precision': '精确率',
  'perf.col.recall': '召回率',
  'perf.directional': '方向准确率',
  'perf.samples': '个样本',

  // ── 预测战绩 ──────────────────────────────────────────────────────────────
  'tr.title': '预测战绩',
  'tr.sub': '模型做过的每一次预测，对照真实结果——不挑好的展示。',
  'tr.stat.total': '预测总数',
  'tr.stat.hitRate': '整体命中率',
  'tr.stat.highConf': '高置信',
  'tr.stat.avgMove': '平均实际波动',
  'tr.stat.bestSector': '最佳板块',
  'tr.calibration': '校准曲线',
  'tr.calibration.sub': '模型说有 X% 把握时，实际命中率应该也是 X%',
  'tr.rolling': '滚动 90 天准确率',
  'tr.rolling.sub': '按周取样',
  'tr.recent': '最近的预测',
  'tr.bySector': '分板块准确率',

  // ── 回测 ──────────────────────────────────────────────────────────────────
  'bt.badge': '回测器',
  'bt.title': '策略模拟',
  'bt.sub': '在历史财报事件上重放模型信号。调整置信度阈值和范围，观察风险收益的取舍。',
  'bt.field.ticker': '股票代码',
  'bt.field.sector': '板块',
  'bt.field.start': '开始日期',
  'bt.field.end': '结束日期',
  'bt.field.threshold': '最低置信度',
  'bt.run': '运行回测',
  'bt.running': '运行中…',
  'bt.allTickers': '全部股票',
  'bt.allSectors': '全部板块',
  'bt.kpi.totalReturn': '总收益',
  'bt.kpi.sharpe': 'Sharpe 比率',
  'bt.kpi.sortino': 'Sortino',
  'bt.kpi.maxdd': '最大回撤',
  'bt.kpi.winRate': '胜率',
  'bt.kpi.pf': 'Profit Factor',
  'bt.kpi.avgWinLoss': '平均盈利 / 亏损',
  'bt.kpi.cagr': '年化增长率',
  'bt.kpi.alpha': 'Alpha（对 SPY）',
  'bt.kpi.beta': 'Beta',
  'bt.equity': '权益曲线 vs SPY',
  'bt.drawdown': '回撤',
  'bt.dirBreakdown': '方向拆解',
  'bt.noTrades': '匹配到 {n} 个事件，但没有一个通过 {pct}% 的概率门槛，因此没有交易可报。概率已按基准率校准，试试 35–45%。',

  // ── 策略对战 ──────────────────────────────────────────────────────────────
  'sd.booting': '正在初始化指挥中心',
  'sd.title': 'Signalpha 指挥中心',
  'sd.leader': '领先',
  'sd.nextSignal': '距下次信号',
  'sd.trades': '交易数',
  'sd.sharpe': 'Sharpe',
  'sd.open': '持仓中',
  'sd.winRate': '胜率',
  'sd.raceChart': '竞速曲线',
  'sd.signalCalendar': '信号日历',
  'sd.eventLog': '事件日志',

  // ── 深度分析 ──────────────────────────────────────────────────────────────
  'dd.back': '财报日历',
  'dd.stat.direction': '预测方向',
  'dd.stat.move': '预期波动',
  'dd.stat.band': '收敛区间',
  'dd.stat.completeness': '数据完整度',
  'dd.probs': '方向概率',
  'dd.historical': '历史财报反应',
  'dd.similar': '相似历史案例',
  'dd.features': '特征快照',
  'dd.drivers': '主要驱动因素',
  'dd.confidence': '{pct}% 置信度',
  'dd.horizon': '{d} 日区间',
  'dd.warnings': '{n} 条警告',

  // ── 名人信号补充 ──────────────────────────────────────────────────────────
  'oracle.whoMoves': '谁在撬动市场',
  'oracle.sinceSignal': '自信号发出',
  'oracle.size': '建议仓位',
  'oracle.source': '来源',

  // ── 联系 ──────────────────────────────────────────────────────────────────
  'contact.title': '联系我',
  'contact.sub': '问题、反馈，或者你觉得合适的职位。',

  // ── 通用 ──────────────────────────────────────────────────────────────────
  'common.loading': '加载中…',
  'common.error': '出错了。',
  'common.retry': '重试',
  'common.notAdvice': '不构成投资建议。',
}
