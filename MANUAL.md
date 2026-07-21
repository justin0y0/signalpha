# SignAlpha 用户手册

> 这份手册面向**想真正看懂每个数字含义**的用户。每个指标都给出确切定义（算式、口径、样本），以及容易误解的地方。
>
> 凡是我无法从代码里读出确切定义的，都标了 **`TODO 待确认`**，不会编。
>
> **最后更新：2026-07-21**。页面结构在这一天从 11 个 tab 收敛为 7 个，本文描述的是新结构。

---

## ⚠️ 开篇必读：这个网站的数字诚实到什么程度

SignAlpha 展示的所有历史表现，都来自**严格 walk-forward 重建**的预测——每个事件由"训练窗口截止于该事件之前"的模型打分，不存在用未来数据回看的情况。

这一点值得单独说，因为 2026-07-20 之前**并非如此**：历史预测是事后批量补的，概率还被一个用已知结果拟合的校准器覆写过，导致回测显示 97.5% 胜率。那些数字已经全部作废重算。

**当前诚实结论（不粉饰）：**

| 结论 | 数字 | 说明 |
|---|---|---|
| 模型**低于最蠢的基线** | 3 分类准确率 49.33% vs 全押 FLAT 49.84% | 低 0.5 个百分点 |
| 模型**几乎不做方向判断** | 97.5% 的事件预测为 FLAT；只在 2.5% 的事件上给方向 | 校准后的诚实结果 |
| 模型**没有可测的方向能力** | 给方向时准确率 53.5%，但 **n=71** | 与抛硬币无统计差异 |
| 模型**唯一可证实的能力**：识别"非事件" | conf≥0.60 且预测 FLAT 时准确率 **66.59%**（基线 49.84%，n=862） | **+16.8pp，约 9.9 个标准误** |
| Pulse 盘中信号**无 edge** | Profit Factor 0.979（税前），含成本为负 | 与随机无法区分（t=−0.12）|

**这个网站不提供投资建议。** 所有内容是研究与教育用途。

---

## 全站通用概念

在读任何页面之前，先搞清这几个反复出现的量。**它们的定义在全站是统一的**（2026-07-21 修复了 Performance 页曾经用 T+5 的口径不一致问题）。

### 时间锚点

以财报事件日为界：
- **`prev_close`** = 财报日**之前**最后一个交易日的收盘价 —— 所有收益率的分母
- **`open_t1`** = 财报日当天（或之后第一个交易日）的开盘价
- **`close_t1`** = 同一根 bar 的收盘价
- **`close_t5` / `close_t20`** = 之后第 5 / 第 20 根 bar 的收盘价

### 核心指标定义

| 名称 | 算式 | 含义 |
|---|---|---|
| **Gap（跳空）** | `open_t1 / prev_close − 1` | 隔夜跳空幅度。财报后第一笔价格相对财报前收盘的变动 |
| **T+1 收益** | `close_t1 / prev_close − 1` | **模型训练用的标签**，也是 Backtest / Track Record / Model 页评分的口径 |
| **T+5 收益** | `close_t5 / prev_close − 1` | **含 gap**。Showdown 用它 |
| **T+20 收益** | `close_t20 / prev_close − 1` | 长期漂移，目前只存不展示 |
| **最大盘中波动** | `max(\|high_t1/open_t1 − 1\|, \|low_t1/open_t1 − 1\|)` | 相对**开盘价**，不是收盘价 |
| **Gap filled** | 前 20 根 bar 内最低价 ≤ `prev_close` ≤ 最高价 | 跳空是否被回补 |

> **最容易误解的一点**：T+5 收益是从**财报前收盘**算起的，所以它**包含**了跳空。一个 T+1 开盘才进场的策略拿不到这段。Showdown 页对此做了修正（见下）。

### 三分类标签

所有"方向"都是 **UP / FLAT / DOWN 三分类**，阈值 **±2%**：

```
T+1 收益 > +2%  → UP
T+1 收益 < −2%  → DOWN
其余            → FLAT
```

**FLAT 是多数类**（本数据集占 49.8%）。这就是为什么"准确率 46%"听起来还行、实际上很差——因为无脑全猜 FLAT 就有 49.8%。

### 置信度（confidence_score）

```
confidence_score = max(P(UP), P(FLAT), P(DOWN))
```

**这不是"猜对的概率"**，是三个类别概率里最大的那个。

这三个概率经过 **walk-forward isotonic 校准**：每一批预测由"只见过更早数据"的校准器映射。校准前平均置信度 0.695 对应 46.1% 准确率（过度自信，ECE 0.234）；校准后 0.517 对应 49.2%（ECE **0.042**，改善 5.6 倍）。所以现在页面上显示的置信度**大致可以按字面理解**。

> **校准的一个重要副作用**：把概率压回真实基准率之后，模型在 **97.5%** 的事件上 argmax 落在 FLAT。也就是说 Calendar 上的"方向"列现在绝大多数是 FLAT。这不是 bug，是模型在没有方向 edge 时的诚实表现——**建议看三个类别的概率分布，而不是只看那个标签**。

---

## 1. Calendar（`/`）—— 首页

**这个页面干嘛的**：未来 90 天 + 过去 30 天的财报日历，每个事件配一个 ML 预测。
**数据来自**：`GET /api/v1/calendar?days_forward=90&days_back=30`

### 顶部 4 张卡

| 卡片 | 含义 | 注意 |
|---|---|---|
| **TRACKED EVENTS** | 窗口内事件总数 | 副标题写"rolling 120-day window" = 90 天前瞻 + 30 天回看 |
| **NEXT 7 DAYS** | 未来 7 天内的财报数 | 含今天 |
| **WITH ML PREDICTION** | 有预测的事件数 + 覆盖率 | 覆盖率 <100% 通常是特征缺失导致该事件跳过了 |
| **BULLISH SIGNALS** | 预测方向为 UP 的事件数 | **不是"看涨的把握"**，只是 argmax 落在 UP 的计数 |

### 表格每一列

| 列 | 含义 |
|---|---|
| **TICKER** | 股票代码，等宽字体。点整行进入深度分析 |
| **COMPANY** | 公司名，来自 FMP profile 接口 |
| **SECTOR** | 板块。**这个字段决定用 9 个 sector 模型里的哪一个**，为空则回落到 general 模型 |
| **EARNINGS DATE** | 财报日 + 倒计时（`Today` / `in 3d` / `5d ago`）。<br>⚠️ 2026-07-21 前这里**全站早一天**（UTC 解析 bug），现已修 |
| **PREDICTION** | `方向 · 置信度`。<span style="color:#34d399">绿=UP</span> / <span style="color:#fb7185">红=DOWN</span> / 灰=FLAT |
| **EXPECTED MOVE** | `±X.XX%`，见下 |

### `EXPECTED MOVE` 到底是什么

后端返回的是**小数**（如 `0.0337`），前端乘 100 显示为 `±3.37%`。

它是一个**独立回归模型**（VotingRegressor）预测的 **T+1 收益绝对值**，即"预计会动多大"，**与方向无关**。所以 `±3.37%` 读作："预计 T+1 收盘相对财报前收盘会变动约 3.37%，方向看 PREDICTION 那一列。"

**误解提醒**：这不是期权隐含波动率，也不是置信区间。区间是 `expected_move_low/high = 点估计 ∓ 训练残差标准差`，只在深度分析页展示。

---

## 2. Model（`/model`）—— 模型有多好

两个子页面（顶部 SubNav 切换，URL 用 `?view=`）。**2026-07-21 由原 Performance 和 Track Record 两个 tab 合并**——它们重复了约三分之二的内容。

### 2a. Model Quality（`?view=quality`）

**数据来自**：`GET /api/v1/performance` → `model_performance` 表。
**这张表是 `models/train.py` 的 purged walk-forward 评估产物，从未被污染过。**

**顶部 4 张卡**：整体准确率 + F1 / 最佳 sector / 最差 sector / 总样本数。

**★ Accuracy vs Baseline（新增，最该看的一块）**

| 格子 | 含义 |
|---|---|
| Model | 模型 3 分类准确率 |
| Always-FLAT baseline | 全押 FLAT 的准确率 = FLAT 在样本中的占比 |
| Random (1 of 3) | 33.33% |
| **Edge over baseline** | 模型 − 基线。<span style="color:#fb7185">红色 = 没跑赢</span> |

这块直接用页面下方那个混淆矩阵算，**不可能和旁边的数字对不上**。目前显示 **−1.84 pts**，即模型没跑赢基线。下面附了一段说明：模型真正有能力的地方是识别非事件。

**Confidence Tiers（置信分层）**

按置信度阈值切片后的准确率。两列要分清：
- **准确率** = 3 分类准确率（UP/FLAT/DOWN 全算）
- **Directional** = **只统计"模型预测方向 且 实际也是方向"的子集**，把 FLAT 完全排除

⚠️ **这两列的走势相反，而这正是最重要的信息**：准确率随置信度上升（46.4%→58.8%），方向准确率却下降（46.8%→40.7%）。原因是高置信度里 82.2% 是 FLAT 预测——**模型越有把握，越是在说"不会有事"，而不是"会涨/会跌"**。

**Per-Sector Heatmap**：每个 sector 的 Accuracy / Precision / Recall / F1 / MAE / Sharpe。
- MAE = 预期波动幅度的平均绝对误差（对 `|T+1 收益|`）
- Sharpe = `models/backtest.py:sharpe_ratio()` 对该 sector 的 walk-forward 策略收益序列计算 — **`TODO 待确认`：年化因子的确切取值我没有逐行核对，需要你确认是否与 Backtest 页的 `sqrt(n/years)` 一致**

**SHAP Top Features**：XGBoost 的 SHAP 值，取绝对值均值排序。表示"这个特征对模型输出的平均影响强度"，**不代表因果**。

**Confusion Matrix**：行 = 实际方向，列 = 预测方向。对角线 = 猜对。

### 2b. Prediction Record（`?view=record`）

**数据来自**：`GET /api/v1/track-record/*`（6 个 endpoint）
**只统计 `is_out_of_sample = TRUE` 的行**（当前 5,477 条）。

| 指标 | 定义 |
|---|---|
| **TOTAL PREDICTIONS** | 有已知结果的 out-of-sample 预测数 |
| **OVERALL HIT RATE** | argmax 类别 == 实际类别 的比例（3 分类，T+1，±2%）|
| **HIGH CONFIDENCE** | 高置信子集的命中率 — **`TODO 待确认`：阈值我读到是 0.65，但请你确认前端展示的是哪一档** |
| **AVG ACTUAL MOVE** | `平均 \|T+1 收益\|`，单位 % |
| **BEST SECTOR** | 命中率最高的 sector |

**Calibration Curve（校准曲线）**：横轴=模型说的置信度，纵轴=实际命中率。**点落在对角线上 = 校准良好**。点在对角线下方 = 过度自信。走完 walk-forward 校准后，这条线应该明显贴近对角线了。

**Rolling 90-Day Accuracy**：90 天滚动窗口的准确率，按周取样。看模型有没有随时间衰减。

---

## 3. Strategy（`/strategy`）—— 把信号变成交易

三个子页面。**2026-07-21 由原 Backtest / Showdown / Simulator 三个 tab 合并。**

### 3a. Backtest（`?view=backtest`）

交互式回测：选 ticker / sector / 日期区间 / 最低置信度，点 Run。

**交易规则**：`P(UP) ≥ 阈值 → 做多`，`P(DOWN) ≥ 阈值 → 做空`，否则不交易。持有 **T+1**（用 `actual_t1_close_return` 结算）。每笔固定 **5% 仓位**，初始 **$1,000,000**，权益复利。

| KPI | 确切算式 | 注意 |
|---|---|---|
| **Total Return** | 累计权益 / 初始 − 1 | |
| **CAGR** | `(1+总收益)^(1/年数) − 1` | 年数 = 区间天数/365.25，下限 0.25 |
| **Sharpe** | `均值/标准差 × sqrt(交易数/年数)` | **按实际交易频率年化**，不是 sqrt(252) |
| **Sortino** | 同上，但分母只用**负收益**的标准差 | |
| **Max Drawdown** | 权益曲线相对历史高点的最大跌幅 | |
| **Win Rate** | 盈利笔数 / 总交易笔数 | |
| **Profit Factor** | 总盈利 / 总亏损绝对值。>1 才赚钱 | 显示 ∞ 表示没有亏损笔 |
| **Avg Win / Loss** | 平均盈利% 和平均亏损%（按 T+1 收益，非权益） | |
| **Alpha vs SPY** | `总收益 − beta × SPY收益`（CAPM，无风险利率取 0）| **2026-07-20 前 beta 硬编码 0**，那时这个"alpha"其实只是超额收益 |
| **Beta** | 策略日收益对 SPY 日收益的 **OLS 斜率** | 事件收益先聚合到日频再对齐；重叠日 <3 天返回 0 |

**Equity vs SPY 图**：策略权益曲线（面积）+ SPY 基准（虚线）。SPY 用日线前向填充对齐到事件日，所以是**近似对比**。

**Confusion Matrix / Direction Breakdown**：同 Model 页口径。

### 3b. Showdown（`?view=showdown`）

5 个策略人格跑同一批信号，**T+5 持有期**（注意与 Backtest 的 T+1 不同）。

| 策略 | 规则 | 出处 |
|---|---|---|
| 🤖 **QUANT** | 置信度 > 0.55 时按 argmax 方向交易 | 纯 ML |
| 🚀 **DRIFTER** | gap > +3% 做多，< −3% 做空 | Bernard & Thomas (JFE 1989) |
| 🎯 **SNIPER** | 置信度 ≥ 0.75 **且** 预期波动 ≥ 4% | Buffett 式选择性 |
| 🐢 **TREND_LORD** | 任何 gap 都交易，不看大小 | Turtle Traders (1983) |
| 🌱 **COMPOUNDER** | 只做多，永不做空 | Buffett 规则一 |

**★ 收益口径（2026-07-20 修复的重要问题）**

- **QUANT / SNIPER / COMPOUNDER** 财报前建仓，持有穿过跳空 → 收益 = `T+5 收益`（含 gap，合理）
- **DRIFTER / TREND_LORD** 要看到 gap 才能发信号，T+1 开盘才进场 → 收益 = **`(1+T5)/(1+gap) − 1`**

  第二个式子精确等于 `close_t5 / open_t1 − 1`（因为两者分母同为 `prev_close`，可以约掉，实测误差 0）。修复前这两个策略拿的是含 gap 的 T+5 收益，**等于白送了它们错过的那一天催化剂**——对 PEAD 策略来说这就是把全部 edge 重复计算了一遍。

**Sharpe**：`均值/标准差 × sqrt(该策略交易数/年数)`。修复前是硬编码 `sqrt(50)`，会抬高交易少的策略（SNIPER）、压低交易多的（TREND_LORD）。

**仓位**：每笔固定 5% 权益，复利。⚠️ **同时持仓不受资金约束**——每笔都按当时的全部权益算 5%，所以并发持仓多时实际杠杆 >1。这是已知的简化。

### 3c. Paper Account（`?view=paper`）

$1M 纸上交易账户，每 30 分钟自动步进一次（工作日 04:00–20:00 ET）。

| 参数 | 值 |
|---|---|
| 入选条件 | 未来财报 且 置信度 ≥ 55% |
| 建仓时点 | 财报前 T−1，或财报当日盘后 |
| 方向 | UP→做多，DOWN→做空，FLAT→跳过 |
| **仓位** | `min(5% × max(1, 置信度/0.55), 15%)` |
| **杠杆** | 置信度 ≥0.75 → 2.0×；≥0.65 → 1.5×；否则 1.0×。组合上限 2.5× |
| 平仓 | T+5，或 **−8% 止损**，或 **+15% 止盈** |
| 滑点 | 单边 5 bps |

> ⚠️ **已知缺陷（未修）**：止损是按**日线收盘价**判定的，不是盘中触发。也就是说日内跌破 −8% 不会平仓，要等收盘。配合最高 15% 的仓位，这会放大亏损。**这个数字目前偏乐观，修复前请这样理解。**

---

## 4. Pulse（`/pulse`）—— 盘中信号

**这个页面干嘛的**：对约 100 只大盘股做盘中多因子扫描，触发均值回归信号并推 Telegram。

> ⚠️ **页面顶部有黄色声明，请务必读**：275 笔已平仓交易显示 **Profit Factor 0.979（税前）**，含交易成本为负，平均收益与 0 无统计差异（t = −0.12），**conviction score 与结果无可测关系（Spearman +0.04）**。这是研究原型，不是交易建议。

### Σ-Score（6 因子分数）

**范围约 −1 到 +1，正=看多、负=看空。** 六个因子：

1. **AL s-score** — Avellaneda-Lee 均值回归的标准化残差 + 半衰期（bars）
2. **Gao 2018 盘中动量** — `r1` 首小时收益
3. **Connors RSI(2) 超卖 + 上升趋势**
4. **Connors RSI(2) 超买 + 下降趋势**
5. **成交量 z-score** — `+Nσ` 会**削弱**回归信号（AL 论文式 20）
6. `TODO 待确认`：第 6 个因子（sector / MA 距离 / gap 之一）我在代码里没有一一对应上，需要你确认 `market_pulse_service.py` 里 `factors.append` 的完整清单

**阈值**：`|score| ≥ 0.50` 触发交易；`|score| ≥ 0.60` 推 Telegram（"HIGH CONVICTION"）。

**⚠️ 但这个分数没有预测力。** 275 笔的秩相关是 +0.039（t=0.64，不显著）。四分位平均收益是非单调的。**不要把高分当成高胜算。**

### 风控参数

| 参数 | 值 |
|---|---|
| 止盈 | 1.0 × ATR |
| 止损 | 2.2 × ATR，最低 0.6% |
| 最长持仓 | 480 分钟 |
| 冷却 | 同 ticker 同方向 60 分钟 |
| 限制 | 仅常规交易时段；不隔夜；不跨周末 |

> **为什么胜率 71.5% 还是亏钱**：止盈 1.0 ATR / 止损 2.2 ATR 的配置**必然**产生"赢小钱、输大钱"。当前盈亏比 0.390，而在 71.5% 胜率下盈亏平衡需要 0.399 —— **差 2.2%**。这种"恰好卡在盈亏平衡线上"正是底层无 edge 的典型特征：参数只是在"胜率↔盈亏比"前沿上移动，不改变期望。

**Sector Treemap**：按板块分块，面积=市值，颜色=Σ-Score（绿看多/红看空）。点任意股票看详情。

---

## 5. Oracle（`/oracle`）—— 名人信号扫描

**这个页面干嘛的**：追踪 10 位市场人物（Trump / 黄仁勋 / Musk / 苏姿丰 / Cathie Wood / Ackman / Pelosi / Buffett / Burry / Serenity），用 LLM 从新闻和帖子里抽取 **ticker + 方向 + 信念度**，验证 ticker 真实存在后展示其后续价格表现。

### 顶部三个数字

| 数字 | 含义 |
|---|---|
| **SIGNALS · 24H** | 过去 24 小时新增信号数 |
| **TRACKING** | 开启追踪的人物数（可点卡片开关） |
| **AVG CALL** | 所有信号的平均"信号后收益" |

### 信号卡片

- **ticker + 方向徽章**（▲ Bullish / ▼ Bearish）
- **价格 · 市值**
- **时间**（多久之前）
- **标题** = 来源文章标题
- **理由** = LLM 生成的因果句
- **size $X** = 建议仓位（`ORACLE_SIZE_USD` 按信念度缩放）
- **`+X.X% since signal`** = 从信号价到当前价的收益。**做空信号会取反**（所以正数=这次看空对了）

> **最容易误解的地方**：Oracle **会忠实显示亏损的调用**。看到 `−15%` 不是 bug，是这位人物这次看错了。这是刻意的设计——只展示赢的调用就没有意义了。

**头像说明**：全部是像素风**符号化**头像（Trump=讲台、黄仁勋=GPU、Musk=火箭、Buffett=钱袋、Burry=熊…），不是真人肖像，这是有意的政策选择。

**⚠️ 数据源限制**：从服务器（GCP 数据中心 IP）出去，Google News RSS / nitter / truthbrush / X 抓取**全部被封**。目前可用：Marketaux、DuckDuckGo、CNN 的 Truth Social 归档、SEC EDGAR、yfinance。所以 Musk 和 Serenity 的 X 内容目前拿不到。

---

## 6. Prediction Deep-Dive（`/predict/:ticker`）

从 Calendar 点任意行进入。

| 区块 | 含义 |
|---|---|
| **顶部横幅** | 代码 + 公司名 + 方向徽章 + 板块 + 财报日倒计时 + 实时报价 |
| **Predicted Direction** | argmax 类别 + 置信度 |
| **Expected Move** | `±X%` 点估计，副标题给历史平均 |
| **Convergence Band** | 价格收敛区间 —— `TODO 待确认`：这是 `ConvergenceZonePredictor` 的输出，我没有读到它训练目标的确切定义（对应 `outcomes.convergence_low/high` = 前 20 根 bar 的最低/最高价），**请确认展示时是否应标注"20 日价格区间预测"** |
| **Data Completeness** | 该事件非空特征的占比。**<80% 会触发黄色警告**，说明输入数据不全，预测可靠性下降 |
| **Direction Probabilities** | 三个类别概率条，加总为 1 |
| **Historical Reactions** | 该股过去 8 次财报的 T+1 反应 |
| **Similar Cases** | 特征空间里最相近的 3 个历史事件及其实际结果 |
| **Feature Table** | 该事件的 102 个特征快照 |

---

## 7. About（`/about`）

项目介绍：102 特征分类、基准对比条形图、数据管线图、路线图、技术栈。

**基准对比图里的数字**：Random 33% / FLAT-only 50% / Renaissance 50.75%（Zuckerman 2019）/ SignAlpha / PEAD 56%（Cohen-Malloy-Nguyen, JoF 2020）/ GPT-4 CoT 60.4%（Kim-Muhn-Nikolaev, arXiv 2407.17866）。

> `TODO 待确认`：这个页面上的 SignAlpha 数值需要按 walk-forward 重算后的 **46.4%** 更新，并且应当明确标注它**低于 FLAT-only 基线**。我还没改这一页，因为需要你决定对外口径怎么写。

---

## 8. Contact（`/contact`）

联系方式：邮箱 `justinyu0315@gmail.com`、LinkedIn。3D 倾斜卡片 + 打字机动画。

---

## 9. Admin（`/admin`）—— 非公开

粘贴 `ADMIN_TOKEN` 后可见注册用户列表（邮箱 / 姓名 / tier / 是否验证 / 是否绑定 Telegram / 注册时间 / 试用到期）。token 存在浏览器 localStorage 的 `sa_admin`。

---

## 附录：已知缺陷清单（用户视角）

| # | 缺陷 | 影响 |
|---|---|---|
| 1 | Simulator 止损按日线收盘判定，非盘中 | 纸上账户收益偏乐观 |
| 2 | Showdown 并发持仓不受资金约束 | 高并发时实际杠杆 >1 |
| 3 | Backtest 的 SPY 基准是日线前向填充对齐 | 与事件型策略对比是近似的 |
| 4 | FMP 免费档限制 | `forward_eps_guidance` / `transcript_sentiment` 恒为空，等于模型少了几个特征 |
| 5 | Oracle 拿不到 X/Twitter | Musk、Serenity 长期无信号 |
| 6 | Alpha Brief / Watchlist 未实现 | 路线图上有，代码里没有 |

---

*本手册随代码变更同步更新。若发现页面与本文不符，以代码为准并提 issue。*
