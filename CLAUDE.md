# CLAUDE.md — SignAlpha 工作手册

> ## 铁律（每轮都要对照）
> 1. **每次修改代码后必须同步更新 `CLAUDE.md`、`MANUAL.md` 和相关 docs。** 代码变了文档没变 = 这轮没做完。
> 2. **绝不声称功能可用而不给出验证命令。** 每个"修好了"后面必须跟一条能跑的 curl / psql / 编译检查，并附上真实输出。没跑过的只能说"已改代码，未验证"。
> 3. **区分三种状态并在每轮收尾明确标注**：`observed`（跑过、有输出）/ `coded-but-unobserved`（改了没验证）/ `not-done`。"编译过"永远不等于"线上好了"。

---

## 0. 这个项目是什么

**SignAlpha**（https://signalpha.app）= 全栈 ML 量化交易平台。两个目标同时跑：
1. 面向 quant 岗位（Citadel 一类）的严肃作品集；
2. 真能用的产品，长期做成 Bloomberg-Terminal 式的多信号 app，有付费转化意图。

Owner：**Justin**，USC Applied & Computational Mathematics，GitHub `justin0y0`。
沟通用中文 + 英文术语，要直接诚实、不要 filler、不要编造结果。

**核心 ML**：9 个 sector 分层模型，**102 features**（含 FinBERT 情绪、期权 IV、宏观），Purged K-Fold CV 防泄漏，做的是财报驱动的价格反应（PEAD）。Walk-forward OOS ≈ **49.3%**（3 分类 UP/FLAT/DOWN，47 folds，5,393 events）。

> ⚠ **描述与实现不符**：文档和 About 页都说是「XGBoost + LightGBM + LogisticRegression 的 VotingClassifier」。`models/ensemble.py:92` 确实构造了三模型 soft-voting VotingClassifier，`fit()` 也训练了全部三个——但 `predict()`（`ensemble.py:224`）调的是 `direction_model.named_estimators_["xgb"]`，**只用 XGBoost，绕开了投票**。LightGBM 和 LogisticRegression 训练了但推理时从不参与。
> 好消息是 `models/train.py:118` 的评估走的是**同一条 xgb-only 路径**，所以 **49.3% 这个数字测的就是线上真正跑的东西，数字本身诚实**，只有「三模型集成」这个说法不实。
> 两条路（需 Justin 定）：① 把描述改成 XGBoost（零风险）；② 把推理切到真正的 soft-vote —— 但那样 49.3% 就不再描述线上，必须重测。

**诚实定位（对外必须这么说）**：49.3% 是**3 分类准确率，不是胜率**，只比"全押 FLAT"的 baseline 高一点点，**不能包装成"能跑赢市场"**。可辩护的价值是：透明（赢和亏都展示）、每日复用、个性化、分发渠道。卖的是研究和教育，不是投资建议——每个用户可见的界面都要有 "not investment advice"。

---

## 1. 工作流（2026-07-20 起改这个，和以前不一样）

**以前**：Justin 在 GCP Console 浏览器 SSH 里手工粘贴，超 80 行会被截断，所以文件要分块 heredoc 写。
**现在**：Claude Code 直接改本地文件、直接跑 `gcloud` 部署。**Justin 不跑任何 terminal / SSH 命令**，他只看网站和我的汇报。

- 本地 repo：`/Users/justinyu/signalpha`（= 权威源），remote `github.com/justin0y0/signalpha`（private），分支 `main`。
- 服务器 repo：GCP `signalpha-prod` 的 `~/signalpha`，通过 `git pull` 同步。
- `gcloud` 已在 Mac 上认证好（账号 `justinyu0315@gmail.com`，项目 `project-a807fce0-70fd-41ff-86b`），Claude Code 可直接调用，**不需要 Justin 介入**。
- 分块 heredoc 那套限制**已作废**，直接用 Write/Edit 工具改文件。

**每个大步骤做完停下来等 Justin 确认，不要自己一路跑完。**

---

## 2. 架构：5 个容器（注意：旧文档写"4 containers"是错的）

| 容器 | 是什么 | 代码怎么进去 |
|------|--------|--------------|
| `signalpha-backend-1` | FastAPI (Python 3.10)，`backend/Dockerfile` | **baked 进镜像** |
| `signalpha-scheduler-1` | `python -m data_pipeline.scheduler`，APScheduler 定时任务，**和 backend 共用同一个 Dockerfile** | **baked 进镜像** |
| `signalpha-frontend-1` | React + Vite，nginx 提供 80/443，挂 `/etc/letsencrypt` | **baked 进镜像** |
| `signalpha-postgres-1` | PostgreSQL 16，volume `postgres_data`，`db/init.sql` 只在首次初始化时跑 | — |
| `signalpha-redis-1` | Redis 7，Pulse 冷却 / 缓存 | — |

边缘层：Cloudflare 挡在 `signalpha.app` 前面，把 `https://signalpha.app/api/v1/...` 代理到 backend。

**数据流**：`data_pipeline/scheduler.py`（7 个 cron job）→ `data_pipeline/jobs.py` 写 Postgres → `backend/app/api/routes/*` 读 → React 页面轮询。

**四个几乎独立的子系统挂在同一个 backend 上**：
1. **ML PEAD** — Calendar / Backtest / Performance / Track Record / Showdown / Simulator
2. **Pulse** — 盘中 AL_REVERSION（Avellaneda-Lee 均值回归）+ intraday_momentum，Telegram 推送
3. **Oracle** — 名人/影响者信号扫描（10 个人物，LLM 抽 ticker+方向+信念度）
4. **Accounts** — 邮箱验证 → Telegram 深链绑定 → 30 天试用 → token 保护的 `/admin`

---

## 3. 部署（唯一正确姿势）

```bash
gcloud compute ssh justinyu0315@signalpha-prod --zone us-west2-a --command \
  'cd ~/signalpha && git pull && sudo docker compose up -d --build backend scheduler frontend'
```

改了什么就 build 什么，但 **`backend/` 和 `data_pipeline/` 的改动必须同时 `--build backend scheduler`**（两个容器共用同一个镜像源码树，只 build backend 会让 scheduler 继续跑旧代码）。

**部署前必须先 `git push`**，服务器靠 `git pull` 拿代码，本地改了不 push 等于没改。

### 常用运维命令（Claude 直接跑）
```bash
# psql
gcloud compute ssh justinyu0315@signalpha-prod --zone us-west2-a --command \
  'sudo docker exec -i signalpha-postgres-1 psql -U earnings -d earnings -c "SELECT count(*) FROM predictions;"'

# 看 backend 日志
gcloud compute ssh justinyu0315@signalpha-prod --zone us-west2-a --command \
  'sudo docker logs --tail 100 signalpha-backend-1'

# 看 scheduler 日志（job 成功/失败看这里）
gcloud compute ssh justinyu0315@signalpha-prod --zone us-west2-a --command \
  'sudo docker logs --tail 200 signalpha-scheduler-1'

# Redis
gcloud compute ssh justinyu0315@signalpha-prod --zone us-west2-a --command \
  'sudo docker exec -i signalpha-redis-1 redis-cli KEYS "pulse:*"'

# 验证部署后代码真的进了容器（md5 对比，比看日志靠谱）
gcloud compute ssh justinyu0315@signalpha-prod --zone us-west2-a --command \
  'sudo docker exec signalpha-backend-1 sh -c "cd /app && md5sum data_pipeline/jobs.py"'
```

Admin 面板：`https://signalpha.app/admin`，粘 `ADMIN_TOKEN`（存在 localStorage `sa_admin`）。

---

## 4. 关键 gotcha（这些反复搞坏过东西）

1. **backend / scheduler 代码 baked 进镜像**。`docker compose restart` 对代码改动**完全无效**，必须 `up -d --build`。改 `data_pipeline/` 别忘了 scheduler。
2. **`.env` 是 gitignored**，只在服务器和 Justin 本地各一份。**绝不硬编码 secret，一律 `os.getenv`**，也绝不把值写进文档或 chat。
3. **模型 artifacts 不在 git**。`artifacts/*.joblib`（9 个 sector ensemble + calibrator，~179M）通过 compose 的 `./artifacts:/app/artifacts` volume 挂载。`.gitignore` 里有 `artifacts/`。本地要跑预测得先 `gcloud compute scp` 拉下来。（旧 git 历史里还留着，是个警告不是阻塞。）
4. **Groq 模型弃用会静默返回空**。老的 `meta-llama/llama-4-scout-17b-16e-instruct` 被弃用后返回空字符串，直接导致过"所有数字都是 0"的历史 bug。当前可用：`llama-3.3-70b-versatile`（`ORACLE_MODEL`）。**凡是用模型名的地方都要留一个 self-heal 候选列表**，别让一个死模型名把整条链清零。
5. **datacenter IP 封锁一堆抓取源**。从 GCP IP 出去：
   - ❌ 挂了：Google News RSS（consent wall）、nitter（Cloudflare/Anubis）、truthbrush（Cloudflare）、X/Twitter 抓取
   - ✅ 能用：Marketaux、ddgs（DuckDuckGo，快速循环会被限流，要 sleep+retry）、CNN Truth-Social 归档、SEC EDGAR、yfinance
6. **JSON 写入安全**。pandas Timestamp / numpy / NaN / Inf 写进 Postgres JSON(B) 列会让 `session.commit()` 抛异常；如果 commit 在 per-row try 的**外面**，整个 job 会挂掉 → 静默零产出。`data_pipeline/jobs.py` 有 `_json_safe()`，`backend/app/main.py` 有 `SafeJSONResponse`。**⚠ 目前只有 `run_predictions` 用了 `_json_safe`，`collect_options_data` / `collect_macro_data` / `retrain_models` 都没用——见 §6。**
7. **LLM 会幻觉出不存在的 ticker**。持久化任何信号前必须用 yfinance 验证这个 ticker 真能取到价。
8. **Oracle 的 X/Twitter 源从服务器解不开**。`src_nitter` / `src_x` 代码在但跑不通，需要付费 X 源（GetXAPI ~$0.001/call，对 datacenter 友好）或在 Justin 的 Mac 上跑 twikit（住宅 IP，小号，ToS 灰色）。尚未实现。

---

## 5. 已核实的基线（2026-07-20）

- 本地 HEAD = 服务器 HEAD = `3cbd5ba`，工作区干净，与 origin/main 同步。
- 镜像构建于 2026-06-29，但 **81 个 py 文件容器内 md5 与 repo 逐一相同** → 跑着的代码 = repo 代码，无漂移。
- 前端 bundle 与 repo 源码一致（用 "35-feature" 探针字符串确认）。
- 5 个容器全部 Up。
- `.env` 里 `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` 各重复两行，**已核实两次的值相同**，无害（后者覆盖前者）。`MOOMOO_TRADE_PWD` 为空（REAL 模式才需要，当前 SIMULATE，正常）。

---

## 6. 技术债

### 6a. 已修复并线上验证（2026-07-20）

| # | 问题 | 根因（生产 traceback 实证） | 修法 |
|---|------|------|------|
| 1 | `collect_macro_data` 自 2026-04-23 起**天天失败** | `collect_macro_snapshot()` 返回 `spy_price`/`spy_200ma`/`vix_history`，`MacroFeature` 没有这三列 → `TypeError: invalid keyword argument` | `_coerce_for_model()` 丢弃未知列并 warn 一次 |
| 2 | `collect_options_data` 自 2026-05-14 起**天天失败** | `collect_macro_snapshot()` 的 `feature_date` 是 `date` 对象，经 `**market_snapshot` 混进 JSONB → `Object of type date is not JSON serializable` | `_coerce_for_model()` 把所有 JSON/JSONB 列过 `_json_safe` |
| 3 | `collect_earnings_calendar` 挂死，未来事件只剩 12 个 | `base_client.py` 熔断器**没有复位路径**；collector 是模块级单例 → 一次 FMP 抖动就永久熔断所有 FMP job，直到容器重建 | 熔断器 900 秒后 half-open |
| 4 | 单行脏数据能让整个 job 零产出 | `session.commit()` 在 per-row try **外面** | 四个 collector job 全部改为逐行 commit + rollback |
| 5 | FMP `/stable` 日历只返回 symbol+date，sector 会被冲成 NULL | sector 决定 `run_predictions` 用哪个 sector 模型 | `_upsert` 不再用 None 覆盖已有值；新增 `profile()` 补 sector/name/marketCap |
| 6 | `earnings-company` endpoint 404 | `/stable` 已改名 | → `earnings` |
| 7 | Backtest `beta` 硬编码 0.0，`alpha` 却按 CAPM 标注 | — | 真 OLS 回归（日频对齐 SPY），alpha 改为 CAPM 残差 |
| 8 | Showdown 用 `t5_return` 给**所有**策略计 P&L | `t5_return` 从财报前收盘算起、含 gap；DRIFTER/TREND_LORD 在 T+1 开盘才进场，被白送了它们错过的催化日 | `_realized_return()` 精确去 gap：`(1+t5)/(1+gap)-1 == close_t5/open_t1-1` |
| 9 | Showdown Sharpe 硬编码 `sqrt(50)` | 假设所有策略一年交易 50 次 | 改为 `sqrt(n_trades/years)`，与 Backtest 口径一致 |
| 10 | Oracle `GET /leaderboard` 定义两遍（逐字节相同） | — | 删掉死的那份 |
| 11 | Performance 页 "35-feature"、Backtest 结束日期硬编码 `2026-04-01` | — | → 102-feature；结束日期默认今天 |
| 12 | 后端算了 `cagr`/`alpha`/`beta` 等 7 项，前端 TS 类型没声明、页面不显示，还用 `as any` 绕过类型检查 | — | 补齐类型，KPI 区新增 CAGR / Alpha / Beta |
| 13 | 服务器磁盘不足导致 `docker compose up` **静默失败**，容器 3 周没换过新镜像 | build cache 占 11.41GB | `docker builder prune -af` |

**教训（写进流程）**：`docker compose up -d --build` 里 build 成功 ≠ 容器换了。部署后必须验证容器内代码：
`sudo docker exec signalpha-backend-1 md5sum /app/<改过的文件>`，或对比 `docker ps` 的 `Up` 时长。

### 6a-2. 第二批修复（2026-07-20 稍晚）

| # | 问题 | 根因 | 修法 |
|---|------|------|------|
| 14 | repo 没有任何加列/建表的迁移路径；`oracle_signals`/`pulse_signal_log` 只存在于手工建的表 | `init.sql` 只在空数据目录跑一次；`create_all` 不改已有表 | 新增 `backend/app/db/schema_guard.py`，启动时跑幂等 DDL（11 条，已验证 0 失败） |
| 15 | **日历所有日期早一天**（美西时区） | `new Date('2026-07-21')` 按 UTC 午夜解析，`toLocaleDateString` 在负时区渲染成前一天。PDT 下实测 "Jul 21" 显示为 "Jul 20" | 新增 `frontend/src/utils/date.ts`，所有 DATE 型字段统一走 `parseLocalDate`；TIMESTAMPTZ 字段保持原样 |
| 16 | **所有 cron job 跑在 UTC 而非美东** | 手工构造的 `CronTrigger` 在**构造时**就锁定本地时区；scheduler 的 `timezone=` 只对"传参数让 add_job 自己建 trigger"生效。容器没设 TZ → 实测 `.timezone == Etc/UTC` | 每个 trigger 显式传 `timezone=TZ`。原来 `collect_options_data` 本该收盘后跑，实际跑在 12:30 ET 盘中 |
| 17 | yfinance 每次调用都把失败 ticker 重打一遍 ERROR，Pulse 每 5 分钟扫全universe → 每天几万行 ERROR，淹没真错误也吃磁盘 | `FI`/`MMC` 恒返回 0 行（AAPL 正常） | `logging.py` 压掉 yfinance/peewee/urllib3 的日志级别；扫描本身已能跳过缺失 ticker |
| 18 | 日历采集窗口 14 天，但前端请求 90 天、页面自称"rolling 120-day window" | — | `default_calendar_lookahead_days` 14 → 90；profile 缓存改为落盘（`./data/profile_cache.json`），免费额度扛得住 |
| 19 | Calendar/Performance/Deep-Dive 的 KPI 卡没有强调色边条、没有图标、没有 hover，和 Simulator/Contact 不像一个产品 | 共享 `StatCard` 组件比 `.sim-kpi` 少三样 | `StatCard` 升级为 `.sim-kpi` 的视觉语言，三个页面 12 处调用全部补图标 |

### 6b. 仍未解决

0. **🟡 处理中 — `predictions` 表标签泄漏（walk-forward 重生成已在跑）**

   状态：`schema_guard` 已加 `is_out_of_sample` / `raw_prob_*` 列；`data_pipeline/regenerate_predictions.py` 正在用 purged walk-forward 重算历史预测；四个消费面（Backtest / Showdown / Track Record / Performance 置信分层）已接上 `OUT_OF_SAMPLE_ONLY` 过滤，**但必须等重生成写完才能部署**，否则四个页面全空。
   原始 `predictions` 已备份到 `predictions_backup_20260720`（5,567 行）。

   以下是原始问题记录：

   **（原 P0）`predictions` 表存在标签泄漏，网站上所有回测/对战/战绩数字都被污染**

   **证据链（全部实测，非推断）**：
   - `predictions` 5,530 行里 **5,394 行的 `created_at` 晚于它所预测的 `earnings_date`**；全部在 **2026-04-26 一天批量写入**，覆盖 2008-01-17 ~ 2026-07-29 的财报。真正 ex-ante 的只有 173 行。
   - `data_pipeline/calibrate_predictions.py` 用**已知的 `actual_t5_return`** 训练 3 个 isotonic 校准器（按时间取前 70%），然后**把校准结果写回全部预测行**（第 78–99 行），**就地覆盖 `direction_prob_up/flat/down` 和 `confidence_score`**。前 70% 的行等于用自己的答案拟合了自己。
   - **原始模型概率被永久覆盖**，表里没有 `raw_prob_*` 列保留，无法从数据库还原。
   - 症状：`threshold=0.65` 的 Backtest 跑出 **159 笔交易 155 笔方向正确 = 97.48% 胜率、Sharpe 8.18、最大回撤 -0.69%**。底层模型是 49.3% 的 3 分类准确率，这个组合在真实 OOS 下不可能出现。

   **影响面**：凡是读 `predictions ⨝ outcomes` 的页面全部受污染 —— **Backtest、Showdown、Track Record，以及 Performance 页的"置信分层"区块**（`performance_service._confidence_tiers` 也读这张表；线上实测 CONF≥65% 显示 74.1% 准确率 / 86.5% 方向准确率）。
   Performance 页的顶部卡片、sector 热力图、混淆矩阵、SHAP 图读的是 `model_performance` 表（来自 `models/train.py` 的 purged walk-forward），**那部分和 49.3% 是诚实的**。
   所以网站现在同时展示"49.3% 准确率"和"97.5% 回测胜率"——这两个数字互相矛盾，矛盾本身就是破绽。

   **为什么这件事比任何 bug 都重要**：这是给 Citadel 一类机构看的作品集。Look-ahead leakage 是 quant 领域的头号原罪，面试官看到 49.3% 的模型跑出 Sharpe 8 会立刻追问，一问就穿。

   **附带问题**：校准目标用的是 `actual_t5_return`（±2% 分三类），但 Backtest 拿 `actual_t1_close_return` 去评分——**横轴不是同一个 horizon**。另外 `calibrate_predictions.py:105` 的 `correct_old` 定义了从没用过。

   **可选修法（需 Justin 拍板，不要擅自动）**：
   - (a) 诚实止血：给这些行打标记，Backtest/Showdown/Track Record 明确标注 "in-sample, illustrative only"，或直接只用那 173 行 ex-ante 数据（数据量会非常少）。
   - (b) 正确做法：走 walk-forward 重新生成历史预测——每个事件只用它之前的数据训练。`models/train.py` 已经实现了 purged walk-forward 评估，把它改成**顺便落盘每折的预测**即可。工作量中等，但这是唯一能让回测数字站得住的路。
   - (c) 停用 `calibrate_predictions.py`，或改成只在 holdout 上应用、并新增 `raw_prob_*` 列保留原始输出。

1. **P0 — schema 没有单一真相源**：`oracle_signals` 和 `pulse_signal_log` 在整个 repo **没有任何 CREATE TABLE**（`db/init.sql` 只建 7 张 ML 表；`models.py` 的 11 个 ORM 类由 `main.py` 的 `Base.metadata.create_all` 建；`platform_users` 由 `auth_service.py` 的 `ensure_tables()` 建）。这两张表只存在于服务器手工建的表里。**postgres volume 一旦重建，Oracle 和 Pulse 全灭且无从恢复。**注意 `db/init.sql` 挂在 `docker-entrypoint-initdb.d`，**只在数据目录为空时执行一次**，所以补进 init.sql 对现有库无效——正确修法是加幂等的 `ensure_tables()`。
2. **P1 — Alpha Brief + Watchlist 根本没装**：repo 里 `brief_service` / `daily_briefs` / `user_watchlist` / `BRIEF_*` env **0 处命中**。HANDOFF §4f 描述的是还没应用的安装包（`sa_brief.tgz`）。四个付费潜力点里这占了两个。
3. **P1 — 没有任何付费通路**：全 repo 无 Stripe / checkout / pricing / billing。`platform_users.tier` 只能手工改 psql，`trial_ends_at` 只决定谁收 Telegram 推送、不 gate 网页。
4. **P1 — Simulator 止损按日线收盘执行**（HANDOFF §5 #1），−8% 止损配 15% 仓位 → 超额亏损。需要盘中价才能正确执行。
5. **P1 — FMP 免费档限制**：`analyst-estimates`（402）和 `earning-call-transcript-latest`（402）付费才有 → `forward_eps_guidance` / `forward_revenue_guidance` / `transcript_sentiment` 恒为 NULL。这几个是 102 features 的一部分，等于模型少喂了几个特征。
6. **P1 — 前端 API 调用分裂**：`api/client.ts` 只封装 6 个 endpoint，Oracle / Pulse / Showdown / Simulator / Track Record 全是各页面裸 `fetch`。（已核实**路径全部对得上后端**，但没有类型层保护。）
7. **P2 — `ibkr_service.py` + `ibkr_status.py` 是死代码**，IBKR 已否决但路由还注册着。
8. **P2 — 配置漂移**：`config.py:33` `default_calendar_lookahead_days = 14`，但 Calendar 页宣称 90 天前瞻窗口。
9. **P2 — Pulse 每 5 分钟拉 `FI`/`MMC` 都失败**（yfinance "possibly delisted"），刷屏日志且浪费调用。ticker 列表需要清理。
10. **P2 — scheduler cron 时区存疑**：`config.py` 设 `America/New_York`，但 apscheduler 日志打印的 next-run 是 UTC。若真按 UTC 跑，`collect_options_data` 的 16:30 就是美东 12:30（盘中）而非收盘后。待确认。

HANDOFF.md §5 的 10 个 bug 里：#2/#3/#4/#7/#8 已修，#5（Oracle live worker 不出信号）**已过期**——现在 `oracle_signals` 有 332 条 `status='new'`，live worker 是工作的。

---

## 7. Repo 索引（省 token，别每次全文扫）

已用 **graphify** 建好结构索引：`graphify-out/graph.json`（1005 nodes / 2339 edges）。

```bash
graphify explain "函数名或文件名"      # 看某个节点和它的邻居
graphify path "A" "B"                 # 两个节点之间的最短路径
graphify update .                     # 代码改动后重建索引（不需要 LLM）
```

"这个函数在哪调用 / 这个表哪里写入"这类问题**优先查索引**，不要每次重新全文扫描。索引会随代码变旧——大改之后记得 `graphify update .`。
（`.sql` 文件没进图，因为缺 `tree_sitter_sql`；schema 问题直接看 `db/init.sql` 和 `models.py`。）

---

## 8. 权威文档在哪（注意：主要文档不在 repo 里）

| 文件 | 位置 | 时效 |
|------|------|------|
| **HANDOFF.md** | `~/Downloads/HANDOFF.md` | **2026-07-20，最权威**，背景+架构+已知 bug+gotcha |
| 01_Custom_Instructions.md | `~/Downloads/files23/` | 2026-06-05，**部署方式那节已作废**（见 §1） |
| 02_SignAlpha_Knowledge.md | `~/Downloads/filewdws/` | 2026-06-05 |
| 03_Oracle_Deep_Dive.md | `~/Downloads/filewdws/` | 2026-06-05，Oracle 子系统唯一详细文档 |
| 04_Pages_Reference.md | `~/Downloads/filewdws/` | 2026-06-05，Showdown/Backtest 有完整 spec |

⚠ `~/Downloads/files23/` 和 Downloads 根目录下的 04 是**旧副本**，`filewdws/` 才是最新的那套。
⚠ 这四份都停在 2026-06-05，比 HANDOFF 旧 6 周，**冲突时以 HANDOFF + 实际代码为准**。已知漂移：04 说函数叫 `_sanitize_json`，实际叫 `_json_safe`。
⚠ `MANUAL.md`（用户手册）**尚未创建**，是第 3 步的产出。

---

## 9. 数据库速查

`db/init.sql` 建（首次初始化）：`earnings_events` `financial_metrics` `price_features` `macro_features` `predictions` `outcomes` `model_performance`
ORM `create_all` 建：以上 7 张 + `simulation_config` `simulation_state` `simulation_position` `simulation_trade`
`auth_service.ensure_tables()` 建：`platform_users`
**无人建（只在服务器手工存在）**：`oracle_signals` `pulse_signal_log` ← 见 §6.2

关键表的唯一约束：`predictions` / `outcomes` / `price_features` / `financial_metrics` 都是 `Unique(ticker, earnings_date)`；`macro_features` 是 `Unique(feature_date)`。

---

## 10. 定时任务（`data_pipeline/scheduler.py`，时区 America/New_York）

| Job | 触发 |
|-----|------|
| `collect_options_data` | 每天 16:30 |
| `collect_earnings_calendar` | 每周一 07:00 |
| `collect_macro_data` | 每天 08:00 |
| `run_predictions` | 每天 17:00 |
| `retrain_models` | 每月 1 号 02:00 |
| `run_simulator_step` | 每 30 分钟（仅工作日 04:00–20:00 ET） |
| `collect_post_earnings_results` | 每小时 |
| `run_pulse_scan` | 每 5 分钟（仅工作日 04:00–20:00 ET） |

Oracle 的 `oracle_worker()` 不在 scheduler 里——它在 `backend` 容器的后台线程里跑（`main.py:107`），每 `ORACLE_SCAN_SEC` 秒一次。
