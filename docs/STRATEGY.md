# SignAlpha 方向与护城河（2026-10-06 定稿，2026-10-10 修订，2026-10-21 转向 Autopilot）

## 00. 2026-10-21 修订：从「裁判」到「替你执行、但只执行经得起检验的」

Justin 10-19 决定做全自动交易（Autopilot），10-21 要求：至少 10 条可选策略、和站内内容挂钩、接入所有能接的券商、达到可以宣传找用户的状态。

**产品一句话**：财报季的自动驾驶——十条策略，每条扣成本回测、公开实盘记录、写明它从站里哪个页面来；在你自己的券商账户里运行，模拟盘免费。

**策略（全部同一标准：扣成本、发表后/样本外、对 SPY；个股规则另对同一批幸存股票的等权组合）**，按信号来源分三类：
- 财报（日历、方向信号簿、简报）：逢暴涨做空、逢暴跌抄底（按机器人 9:30:20 实际成交价重放仍跑赢 SPY）、顺势追涨、业绩不及就做空（弱，默认关）、财报前埋伏（Frazzini-Lamont/Barber 2013）、双重超预期漂移（Bernard-Thomas + 高开确认）。
- SEC 申报（名人台）：内部人扎堆买入（≥3 位董事/高管 30 天内公开市场买入；对 SPY +1.96%/笔 t 2.7，对等权 +1.67% t 2.3）。
- 大盘（市场页）：SPY 急跌抄底 RSI-2（Connors，发表后持有日 vs 空仓日 t 2.1）、10 个月均线择时（Faber，回撤减半、收益略低）、行业动量（弱）。
**淘汰并公开在实验室**：财报前 ML 方向（抛硬币）、ML 大波动 × 追涨（风险溢价）、ML × 财报跨式（期权已定价，每档都亏）、盘中 AL 回归和尾盘动量（扣成本前就不赚）、名人喊单（5 日超额为负）、13F 跟投巴菲特/阿克曼/伯瑞（无 edge）、GEM 双动量（发表后失效）、月末效应、隔夜效应、议息前漂移（不显著）、个股 RSI-2、个股动量（幸存者偏差无法去除）。
**ML 模型的定位因此改变**：大波动模型准确，但它的信息已经在期权价格里——它卖的是「风险提示/信息」，不是交易信号。

**券商**：原生 Alpaca（密钥/OAuth）、moomoo（官方 REST OAuth，只需勾 trade:read + trade:write，无任何资金划转权限）、Tradier（token）、tastytrade（个人 OAuth 授权）、Robinhood（官方 Trading MCP，agentic 账户，只能做多）；SnapTrade 一个入口覆盖 E*TRADE/Webull/Public/Wealthsimple/Trading 212（不能做空；需要站长注册 SnapTrade 拿 key）。IBKR/嘉信需要第三方供应商审批，富达无 API。

**监管（最重要的未决项）**：替他人实盘账户运行我们的策略 = 美国投资顾问业务。在注册（加州州级 RIA：Series 65 + Form ADV）或找合作 RIA 之前，实盘只对站长/受邀测试者开放（`AUTOPILOT_LIVE_PUBLIC=0`），模拟盘对所有人开放。不是律师意见，上线收费前必须找律师确认。

**定价**：免费 = 全部研究 + 实验室 + 模拟盘 Autopilot；Pro（未开卖，等待名单）= 实盘 Autopilot + 每条策略信号推送 + 跨式检查 + 持仓风险 + MCP。第 8 节「不做自动下单」作废。


> 一句话：**别人做「让 AI 替你交易」，我们做「AI 交易之前必须先问的那个裁判」——专攻财报事件，拿得出可验证的证据。**

---

## 0. 2026-10-10 修订：方向性 + Alinea

**Justin 的两点反馈**：(1) 没人会为「波动比预期大」付费，要做成方向性的；(2) 他说的那家是 **Alinea Invest**，不是 Nof1。

**Alinea Invest 是什么**（[College Investor 评测](https://thecollegeinvestor.com/56733/alinea-invest-review/)、[官网](https://www.alinea-invest.com/press/can-ai-actually-invest-for-you-how-alineas-allie-acts-on-your-behalf)）：面向 Gen-Z 的投资 app，2020 年成立，AI 助手 Allie 帮你建组合 / 自动定投（Automated / Vibe Investing），**AI 提议、人工复核后才成交**；$120/年订阅，第三方称 200 万+ 会员，App Store 12 万评分 4.7；2026-02 拿到 $2250 万**获客融资**（不是股权轮）。
- 它卖的不是 alpha，是「**替我做决定 + 省心**」：一句话告诉我该干什么。没有任何跑赢市场的证据，也不需要。
- 对我们的启示：用户付费买的是**明确的行动指令**，不是概率分布。「这次波动会比平时大」不是指令，「这只高开的可以跟」才是。Justin 的反馈在产品层面是对的。

**但方向不能硬造**。在修正后的干净数据上（见 CLAUDE.md 6f）：财报**前**预测涨跌 AUC 0.50，谁卖这个谁在卖抛硬币。数据支持的方向信号只有一个，在财报**之后**：

> **高开超过平时波动 2 倍 → 反应日收盘买入 → 持有 20 个交易日：64.3% 上涨（全部财报 56.8%），每笔超额 +1.73%，t=3.9，n=555。只做多；大幅低开做空没有优势。**

所以产品的方向性 = **财报后跟进信号**（Strategy → Playbook、Telegram 提醒、模拟盘、MCP 工具）。breakout 降为辅助（告诉你哪些财报值得盯）。这条信号的弱点如实写在产品里：幸存者偏差、只有多头一边、每季只触发几十次。

**2026-10-11 补充——财报前方向试过了**：按 Justin 的要求把特征和 Avellaneda-Lee 均值回归分数合成了一个透明的方向打分卡（`direction_lean.py`）。walk-forward 3,393 份财报：**50.55%，z=0.64**，就是抛硬币。它以「实验性」身份留在个股页，并封存进 Arena 用未来财报继续检验；如果一个财报季后实盘方向命中率的区间仍然包含 50%，就把它撤掉。产品的方向性卖点仍然只有财报后跟进这一条。

**2026-10-15 补充——全市场**：股票池扩到全美市值 3 亿美元以上（约 3,400 只，14.4 万份财报）。breakout 在大/中/小盘都成立（前 10% 大动 71–75% vs 54–57%）；跟进规则也在三档都成立，但每笔超额从旧口径的 +1.73% 降到 +0.93%（大盘只有 +0.74%）——旧数字是 180 只赢家股的样本偏差。产品卖点要用新数字。搜索覆盖全部 5,800 多只美股，微盘按需打分。新增「兑现记录」：只收赛前挂出的判断，按最新价逐日标价——这是对 Alinea 式黑盒最直接的差异化。

**和 Alinea 的差异化**：Alinea 是「把钱交给我」的黑盒理财；我们是「**每个信号都带完整历史战绩、你自己下单**」的白盒。不碰资金、不需要牌照、信号可验证。目标用户不是完全不想管的小白，而是想自己操作但需要一个有证据的理由的人。

## 1. 市场现在是什么样（2026-10 调研，来源见文末）

| 玩家 | 做什么 | 规模/现状 | 弱点 |
|---|---|---|---|
| **Nof1 · Alpha Arena** | 6–8 个前沿模型各拿 $10k 实盘交易加密永续，公开排名 | 2026-05 融 $15M，Season 2 + 准备做 consumer 平台；粉丝多、传播强 | 每季几周、几个账户，量到的主要是方差。Season 1 六个模型里四个亏钱，冠军 Qwen +22%、GPT-5 −59%——这是娱乐，不是技能证明 |
| **Robinhood / IBKR / Alpaca / Scalable Capital** | 通过 MCP 让用户自己的 Claude/ChatGPT 下单 | Robinhood 头几周 5 万+ agentic 账户；Scalable Capital（€60B AUM）开放给 Claude/ChatGPT/Grok | **执行和分发是券商的**，startup 抢不过。agent 本身不懂事件风险 |
| **Elm Wealth 研究** | 历史数据上 LLM vs 人类交易 | 「Claude 76% 场次赢人类」 | 仓位开到 7–12x，风控失败；而且**用历史数据测 LLM 本身就有泄漏**（模型读过答案） |

**结论**：「AI 替你交易」正在被券商商品化（execution + custody + distribution 都是券商的）。稀缺的不是会下单的 AI，而是：
1. **可验证的证据**——这个 AI/信号到底有没有 edge，用运气骗不了的方式测；
2. **事件感知**——agent 不知道明天有财报；
3. **风控纪律**——LLM 懂 Kelly 但不会用。

## 2. 定位

**SignAlpha = 财报事件的风险层 + 公开裁判。**

- 对散户/期权交易者：每份财报前告诉你「这次会不会动得比平时大」（唯一有样本外技能的判断：前 10% 命中 67.85% vs 基准 53.93%），以及期权市场是否已经把它定价了（Straddle Check）。
- 对 AI agent：通过 MCP 成为 agent 下单前调用的 check（`portfolio_earnings_risk`）。我们**不碰执行**，所以不受券商牌照/监管约束，反而搭券商 MCP 浪潮的便车。
- 对整个「AI 交易」话题：**Earnings Arena** 是可信的裁判——每份财报前封存所有模型的预测、SHA-256 + 比特币锚定、Brier 打分、和基准率做配对 bootstrap 区间。这是 Alpha Arena 的「严肃版」，也是我们的获客内容。

## 3. 护城河（按耐久度排序）

1. **Point-in-time 数据资产（时间护城河，钱买不到）**：每天在财报前采集的期权快照（隐含波动）、封存的预测、事后结果。历史 PIT 期权数据没法免费回补——10-05 的泄漏发现正说明了回补数据是脏的。每过一个财报季，这个数据集就更难被复制。
2. **不可篡改的公开战绩**：Arena 的比特币锚定 + walk-forward 全历史（包括失败）。竞争对手可以抄 UI，抄不了一份从 2026-10 开始、被比特币时间戳钉死的记录。
3. **诚实作为品牌**：全站数字实时读 `/model/headline`，失败也展示。在一个充斥「AI 赚 76%」营销的品类里，「我们告诉你哪里不行」本身是差异化。
4. **Agent 分发**：MCP 接入后，SignAlpha 成为 agent 工作流里的默认步骤；切换成本来自用户的 prompt/工作流习惯。

明确**不是**护城河的：模型本身（XGBoost + 61 个公开特征，谁都能训）。护城河在数据、记录和分发，不在算法。

## 4. 产品与定价

| | Free（永久） | Pro（创始价 $19/月 或 $190/年，之后 $29） |
|---|---|---|
| 财报日历 + 大动风险 + 平时/隐含波动 | ✅ | ✅ |
| Earnings Arena（看 + 自己下判断） | ✅ | ✅ + 分歧摘要（模型 vs 期权分歧最大的财报） |
| 完整战绩 / 模型证据 | ✅ | ✅ |
| Straddle Check（历史反应 vs 当前定价） | 测试期免费 | ✅ |
| 自选股大动提醒（Telegram） | — | ✅ |
| 持仓财报风险扫描 | — | ✅ |
| MCP / API（接自己的 agent） | 测试期免费 | ✅（限额） |

原则：**能证明「是真的」的东西永远免费**（日历、Arena、战绩）；**每天要用的工作流收费**。

当前没有支付通路：`/pro` 是量化的 fake door——留邮箱 + 勾选愿意付费的功能，写进 `pro_waitlist`。决策用数据，不用感觉。

## 5. 路线图

| 阶段 | 时间 | 交付 | 成功标准（数字） |
|---|---|---|---|
| **S1 · Q3 财报季** | 2026-10-06 → 11-15 | Arena Season 1 跑满一个财报季；Straddle Check；MCP beta；Paper Account（breakout follow-through） | Arena 封存 ≥ 300 份财报 × 5 预测者；waitlist ≥ 100 邮箱；MCP 有外部调用 |
| **S2 · 证据** | 11-15 → 12-31 | 发布 Season 1 报告（哪个模型跑赢基准率、置信区间）——这是获客内容；加 Claude（需 Anthropic key）/ GPT 进 Arena | 报告在 X/Reddit/HN 传播；waitlist ≥ 300；≥ 30% 勾选 straddle/alerts |
| **S3 · 收费** | 2027-01 | 接 Stripe，开 Pro；自选股提醒 + 持仓扫描上线 | 付费转化 ≥ 3% of waitlist；月流失 < 8% |
| **S4 · 扩展** | 2027 Q1-Q2 | universe 180 → 500；期权 PIT 数据 API 给 agent 开发者（B2B）；Arena 开放第三方模型提交（带 API key 的「报名」） | 第三方模型 ≥ 5 个；B2B 首单 |

## 6. 每季要盯的指标

- **证据**：breakout 前 10% 命中率 vs 基准（walk-forward + Arena 实盘两条线）；Arena 各预测者的 Brier skill 区间。
- **需求**：waitlist 数、勾选分布、`/pro` → 留邮箱转化率、MCP 调用数（按 tool）。
- **留存**：Arena「你的判断」使用率（localStorage 无法统计 → S2 要加登录后的服务端记录）。

## 7. 什么情况下要转向（kill criteria）

- Season 1 + Season 2 合计 ≥ 600 份财报后，**SignAlpha ML 的 Brier skill 区间仍跨 0** → breakout 技能在实盘里不成立，停止以它为卖点，转向纯「数据 + 裁判」（Arena + PIT 期权数据），不再宣称自有模型有 edge。
- 2027-01 waitlist < 150 → 不接支付，Pro 降级为免费功能，项目定位回到作品集 + 研究。
- 期权市场预测者在 Arena 稳定跑赢所有模型 → 这本身是个可以发表的结论；产品重心转向「期权定价 vs 历史」的工具（Straddle Check 做深）。

## 8. 明确不做

- ~~不做自动下单~~（2026-10-21 作废，见第 00 节）。仍然不托管资金：钱永远在用户自己的券商。
- 不做「AI 帮你选股」式营销；不发布没有区间的胜率。
- 不用 LLM 回测历史事件来宣传（训练数据泄漏，见 Arena「为什么只看未来」）。

---

来源：
- [Fortune: Scalable Capital lets Claude/ChatGPT trade (2026-08-26)](https://fortune.com/2026/08/26/scalable-capital-claude-chatgpt-traders-bank-invest/)
- [Nof1 raises $15M (aiweekly)](https://aiweekly.co/alerts/nof1-raises-15m-to-run-ai-models-in-live-trading) · [ventureburn](https://ventureburn.com/nof1-raises-15m-to-expand-ai-trading-platform/)
- [Alpha Arena Season 1 results (forklog)](https://forklog.com/en/four-out-of-six-ai-models-suffer-losses-in-trading-tournament/amp) · [Season 1.5 (forklog)](https://forklog.com/en/news/ai-model-grok-4-2-triumphs-in-trading-tournament)
- [Robinhood agentic trading beta (bitsminds)](https://www.bitsminds.com/news/robinhood-agentic-trading-claude-chatgpt-mcp-2026) · [Brokers expand AI trading tools (Investing.com)](https://www.investing.com/news/stock-market-news/brokers-expand-ai-trading-tools-as-automated-agents-gain-traction-93CH-4764495)
- [CNBC: AI agents trade 24/7 (2026-07-28)](https://www.cnbc.com/2026/07/28/ai-agents-build-to-trade-24/7-the-future-of-wall-street.html)
