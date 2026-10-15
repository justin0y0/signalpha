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

**核心 ML（2026-10-05 起）**：两个模型。① 9 个 sector 分层的 3 分类方向模型（UP/FLAT/DOWN）；② 一个 pooled 的 breakout 模型（XGB 二分类：这次财报会不会动得比该股平时大）。**只用 61 个 point-in-time 特征**（白名单 `models/features.py`）——期权、分析师、基本面、持仓、情绪、`last_8q_reactions` 因为拿不到历史时点值而排除，详见 6d。

> ⚠ **描述与实现不符**：文档和 About 页都说是「XGBoost + LightGBM + LogisticRegression 的 VotingClassifier」。`models/ensemble.py:92` 确实构造了三模型 soft-voting VotingClassifier，`fit()` 也训练了全部三个——但 `predict()`（`ensemble.py:224`）调的是 `direction_model.named_estimators_["xgb"]`，**只用 XGBoost，绕开了投票**。LightGBM 和 LogisticRegression 训练了但推理时从不参与。
> 好消息是 `models/train.py:118` 的评估走的是**同一条 xgb-only 路径**，所以 **这个准确率测的就是线上真正跑的东西，数字本身诚实**，只有「三模型集成」这个说法不实。
> 两条路（需 Justin 定）：① 把描述改成 XGBoost（零风险）；② 把推理切到真正的 soft-vote —— 但那样当前的准确率就不再描述线上，必须重测。

> ⛔ **2026-10-10：下面这段的数字建立在错位的反应日和有泄漏的特征上，已作废，见 6f。当前口径：财报前方向 AUC 0.50（没有）；breakout AUC 0.584；方向只在财报后给——高开 > 2× 平时波动、收盘买、持有 20 天，64.3% vs 56.8%，t=3.9。**

**（旧）诚实定位（2026-10-05 PIT 口径）**：方向**没有 edge**——3 分类 **38.94% vs 全押 FLAT 47.3%**（n=5,603），每类 precision ≈ 基准率。真正站得住的一句话是：「breakout 风险前 10% 的财报里，**67.85%** 动得比该股平时大，基准 **53.93%**（n=339，z=5.14，AUC 0.569）。」7 月的「P(FLAT)≥0.60 识别非事件 76.30%」**已撤回**（泄漏特征上测的；PIT 下最低 10% 只有 53.4% vs 46.1%）。**绝不能包装成"能跑赢市场"**。可辩护的价值是：透明（赢和亏都展示）、每日复用、个性化、分发渠道。卖的是研究和教育，不是投资建议。

> **数字不许写死在前端或文案里**：一律读 `GET /api/v1/model/headline`（`headline_service.py`，10 分钟缓存；breakout 部分来自 `artifacts/move_metrics.json`）。前端用 `useHeadline()`。这个站点两次因为文案引用已不存在的模型的数字而自相矛盾。

---

## 1. 工作流（2026-07-20 起改这个，和以前不一样）

**以前**：Justin 在 GCP Console 浏览器 SSH 里手工粘贴，超 80 行会被截断，所以文件要分块 heredoc 写。
**现在**：Claude Code 直接改本地文件、直接 SSH 部署。**Justin 不跑任何 terminal / SSH 命令**，他只看网站和我的汇报。

- 本地 repo：`/Users/justinyu/signalpha`（= 权威源），remote `git@github.com:justin0y0/signalpha.git`（SSH，private），分支 `main`。
  - 2026-10-02 起 remote 从 HTTPS 换成 SSH：HTTPS 的 keychain token 过期后 push 一直失败。现在用 `~/.ssh/id_ed25519_myvoice_github`（账号级 key），`~/.ssh/config` 里 `Host github.com` 已指定。
- 服务器：**Oracle Cloud Always Free**，`VM.Standard.A1.Flex`，2 OCPU / 12GB / 50GB，**ARM (aarch64)**，Ubuntu 22.04，凤凰城 PHX-AD-1，公网 IP `129.146.68.232`。
  - SSH：`ssh oracle-sp`（`~/.ssh/config` 别名 → `ubuntu@129.146.68.232`，key `~/.ssh_signalpha_oracle/oracle_signalpha`）。ubuntu 在 docker 组，**不需要 sudo**。
  - 服务器代码：`~/signalpha`，**用 `rsync` 从本地同步**（服务器上没有 GitHub 凭据，不 `git pull`）。
  - 主机加固由 Muse 完成：SSH 仅密钥、禁 root/密码登录、fail2ban、2G swap；OCI 安全列表和主机 iptables 只开 22/80/443。
- ~~GCP `signalpha-prod`~~：2026-08 试用到期后项目被停计费，VM 和磁盘连同全部数据丢失，见第 6c 节。
- 分块 heredoc 那套限制**已作废**，直接用 Write/Edit 工具改文件。

**一路做完再汇报，不要中途停下来问。**（Justin 2026-07 多次明确："做完汇报就行，不同意会让你回滚"。）例外只有安全规则要求的：对外可见的账号操作（改 DNS、付费、发消息）先要一句明确同意。

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
git push origin main      # 先推，保证 GitHub 是权威副本
rsync -az --delete --exclude node_modules --exclude frontend/dist --exclude __pycache__ --exclude artifacts --exclude data --exclude .env ./ oracle-sp:~/signalpha/
ssh oracle-sp 'cd ~/signalpha && docker compose up -d --build backend scheduler frontend'
```

⚠️ **`--exclude artifacts --exclude data --exclude .env` 一个都不能少**：这三个只存在于服务器（训练好的模型、缓存、密钥），`--delete` 会把本地没有的东西在服务器上删掉。2026-10-05 一次漏了 artifacts，只因为文件归 root、rsync 没权限才没删成 9 个模型。

改了什么就 build 什么，但 **`backend/` 和 `data_pipeline/` 的改动必须同时 `--build backend scheduler`**（两个容器共用同一个镜像源码树，只 build backend 会让 scheduler 继续跑旧代码）。

**镜像有 10.8GB**（ARM 上的 torch 轮子带了用不上的 CUDA 库），重建 backend 时导出镜像很慢（几分钟）。一次性脚本可以 `-v` 挂载单个文件进 `docker compose run --rm` 来跑，避免为一个脚本重建。

### 同一台机器上还跑着 MyVoice
`frontend/nginx.conf` 顶部 `include /etc/nginx/extra/*.conf;`，compose 把主机 `/srv/edge-vhosts` 挂进去。MyVoice 的 vhost（`myvoice.signalpha.app` → `myvoice-backend:8080`）就放在那里，配置本体在 MyVoice 仓库 `deploy/oracle/`。
**两个站共用一个 nginx：那个目录里任何一个坏文件都会让 signalpha.app 起不来**（2026-10-02 真发生过，宕机不到一分钟）。改之前先用一次性容器 `nginx -t` 校验，见 MyVoice 仓库的 runbook。

### TLS
Cloudflare 代理（橙色云），SSL 模式 **Full**。源站证书是 Let's Encrypt（webroot `/var/www/certbot`，nginx 80/443 都放行 `/.well-known/acme-challenge/`），**由主机上的 `certbot.timer` 自动续期**，deploy hook 是 `docker exec signalpha-frontend-1 nginx -s reload`。`certbot renew --dry-run` 已验证通过。

### 🔴 部署后必须跑这个，否则不许说"好了"

```bash
./scripts/verify_deploy.sh
```

从**外部、经真实域名**打一遍所有 API 和页面——用户怎么访问就怎么验。

**为什么加这条**：2026-07-21 我把站搞挂了，每个 tab 包括 `/admin` 全是 502，持续到 Justin 发现才知道。根因是重建 backend 容器后它换了 IP，而 nginx 的 `proxy_pass http://backend:8000` **只在启动时解析一次**并永久缓存。当时用的部署检查全部通过——因为那些检查只问"我的代码进容器了吗"，那是关于我的问题，不是关于用户能不能用的问题。

nginx 侧已改为变量 + Docker DNS 按请求解析，但**验证习惯比那个修复更重要**：容器内 grep 通过 ≠ 网站能用。

### 另一条铁律：不要在 backend 容器里跑重活

重训练/回填这类几十分钟的任务**不许 `docker exec` 进 `signalpha-backend-1`**——它和 Oracle worker 共用进程资源，我那次跑到 113% CPU。用 `signalpha-scheduler-1` 或起一次性容器。

### 常用运维命令（Claude 直接跑）
```bash
ssh oracle-sp 'docker exec -i signalpha-postgres-1 psql -U earnings -d earnings -c "SELECT count(*) FROM predictions;"'
ssh oracle-sp 'docker logs --tail 100 signalpha-backend-1'
ssh oracle-sp 'docker logs --tail 200 signalpha-scheduler-1'      # job 成功/失败看这里
ssh oracle-sp 'docker exec -i signalpha-redis-1 redis-cli KEYS "pulse:*"'
ssh oracle-sp 'docker exec signalpha-backend-1 sh -c "cd /app && md5sum data_pipeline/jobs.py"'   # 代码真的进容器了吗
```

### 🔴 备份（2026-10-02 起必须有）
上一台机器死的时候，最新的数据库备份是 5 个月前的。**没有备份 = 下一次迁移还会丢数据。** 见第 6c 节。

Admin 面板：`https://signalpha.app/admin`，粘 `ADMIN_TOKEN`（存在 localStorage `sa_admin`）。

---

## 4. 关键 gotcha（这些反复搞坏过东西）

1. **backend / scheduler 代码 baked 进镜像**。`docker compose restart` 对代码改动**完全无效**，必须 `up -d --build`。改 `data_pipeline/` 别忘了 scheduler。
2. **`.env` 是 gitignored**，只在服务器和 Justin 本地各一份。**绝不硬编码 secret，一律 `os.getenv`**，也绝不把值写进文档或 chat。
3. **模型 artifacts 不在 git**。`artifacts/*.joblib`（9 个 sector ensemble + calibrator，~179M）通过 compose 的 `./artifacts:/app/artifacts` volume 挂载。`.gitignore` 里有 `artifacts/`。本地要跑预测得先从服务器 `scp oracle-sp:~/signalpha/artifacts/...` 拉下来。（旧 git 历史里还留着，是个警告不是阻塞。）
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

### 6a-3. 第三批（2026-07-21）

| # | 内容 | 验证 |
|---|------|------|
| 20 | **概率校准重做**：`recalibrate_predictions.py` expanding-window isotonic，读 `raw_prob_*` 只写展示列 | 校准器未见过的 5,077 行上 ECE **0.2342 → 0.0415**（改善 5.6×） |
| 21 | **封停 `calibrate_predictions.py`**（泄漏源），运行即 exit 1 并说明三条罪状 | 实测拒绝运行 |
| 22 | **导航 11 → 7**：Model(Performance+TrackRecord) / Strategy(Backtest+Showdown+Simulator)，新增 `SubNav`，5 个旧路径全部重定向 | 12 条路由实测全 200 |
| 23 | **Accuracy vs Baseline 面板**：用页面自己的混淆矩阵算，Model 48.12% vs Always-FLAT 49.96%，Edge **−1.84 pts** | DOM 文本 + API 双向确认 |
| 24 | **Pulse 研究声明**：Profit Factor 0.979(税前)/含成本为负/t=−0.12/score 秩相关 +0.04 | 进 bundle 确认 |
| 25 | **MANUAL.md**：7 页全覆盖到每个数字的算式，4 处读不出的标 TODO 未编造 | — |

> ⚠️ **校准的副作用（产品层面要知道）**：概率压回基准率后，模型在 **97.5%** 事件上 argmax 落 FLAT，只在 2.5% 事件给方向（给方向时 53.5%，n=71，无统计意义）。Calendar 的 PREDICTION 列因此基本全是 FLAT。
> 核心结论仍成立（2026-07-22 按每股票区间重算）：P(FLAT)≥0.60 时准确率 **76.30%**（基线 60.63%，n=1,055，z=10.4）。
> ⛔ **2026-10-05 撤回**：这个数字是在含 PIT 泄漏的特征上测的，见 6d。
> **待定**：Calendar 该列建议改为展示三类概率分布而非 argmax 标签——argmax 对一个无方向 edge 的校准模型没有信息量。未改，等 Justin 定。

### 6a-2. 2026-07-22：判分口径统一 + i18n 全量接线

| # | 内容 | 验证 |
|---|------|------|
| 26 | **判分口径统一**：新建 `backend/app/services/flat_band.py` 作为「什么算非事件」的唯一定义。此前训练用每股票 0.5σ、Calendar 用同规则的 SQL、Track Record 用固定 ±2%（docstring 却写 1.5%）、Performance 用固定 2.0%（注释却声称是 per-stock）。四处口径不一致，正是同一个模型在一页显示 49.3%、另一页显示 59.9% 的原因 | 一次性容器实测：Track Record 49.32% → **59.84%**，与 About 页 59.8% 一致；混淆矩阵对角线与 summary 完全吻合 |
| 27 | **分母 bug**：`/summary` 与 `/confusion` 用 `len(rows)` 做分母，但循环里 `continue` 掉的行没被扣除 —— 每个无法判分的行都被静默计成一次 miss | 分母改为 `scored`；5,477 → 5,468 |
| 28 | **baseline 由后端算**：`/summary` 新增 `baseline` / `baseline_class` / `actual_distribution`，前端不再硬编码 33.3% 和 50% | 实测 baseline=60.63% (FLAT) |
| 29 | **4 个 endpoint 缺 select 列**：confusion / calibration / rolling / confidence_breakdown 的 SELECT 里没有 `ticker`，而 per-stock 查表需要它 —— 上线即 AttributeError | 静态检查 + 容器实跑全通过 |
| 30 | **i18n 接线 104 → 245 key**，21 个文件。About 页之所以一直是英文：它的 tab 卡片 `map((t, i) =>` 用 `t` 做循环变量，**遮蔽了 i18n 的 `t`** | 线上 DOM 采样：7 个页面中 6 个中文模式下 0 英文残留 |
| 31 | **`orc.*` 命名空间合并回 `oracle.*`** —— 我自己造了个和既有 key 重复的平行命名空间 | 字典去重，`orc.` 计数归 0 |
| 32 | **前端过期数字清理**：Brief 页「66.6% / 49.8% 基线」（改标注方案前的旧值）、Backtest 页「5,393 events」、Track Record 脚注「49.3%，47 folds」、About benchmark 条「Always-FLAT 50.0% / ±2%」（与同页正文的 60.7% 自相矛盾） | 全部改为实测值 |
| 33 | **方向性能力的说法纠正**：此前网站说「给方向时约一半正确，与随机无异」。新口径实测是 **25.45%（n=165），低于三分类随机的 33.3%** | 已改为实测表述 |
| 34 | **HeroBackdrop 双 ref**：两个 `<path>` 绑同一个 ref，后者覆盖前者，主线（1.6px）永远拿不到 `d`，只有 0.6px/40% 透明度的副线在动 | 拆成两个 ref |

> **fold 数实测**：81 个 fold 跨 9 个 sector 模型（Industrials/Technology/Consumer Cyclical/Energy/
> Financial Services/Healthcare 各 10，Communication Services/Consumer Defensive 各 9，general 3）。
> 文档和 About 页此前都写「47 folds」，是旧数。

> **band 分布实测**：150 个 ticker 有足够样本算出自己的区间。中位数 2.50%（即多数股票落在 floor 上），
> 最大 6.88%。TSLA ±4.30%、NVDA ±3.94%，而 KO / JNJ / PG / MMM 都在 2.50% 的下限。

### 6a-3. 2026-07-22（下午）：标签重定义为每股票中位数 —— 类别分布终于是 25/50/25

**起因**：Justin 早在若干轮之前就要求「25-50-25 的定义分布」。我当时只改了「用不用每股票
自适应」，**没检查改完之后类别分布到底是多少**。实际是 21 / 61 / 18，离要求差很远。

**根因**：`clamp(0.5σ, 2.5%, 10%)` 里的 2.5% 下限。实测 **150 只股票里 113 只(75%)的
0.5σ 低于 2.5%**，所以对四分之三的标的，决定 band 的是那个固定下限而不是股票自身波动率。
规则名义上自适应，实际上就是个固定 ±2.5%。

**四种规则实测分布**（5,521 个事件）：

| 规则 | UP | FLAT | DOWN |
|---|---|---|---|
| clamp(0.5σ, 2.5%, 10%)（旧） | 21.1% | 60.7% | 18.2% |
| 0.5σ 去掉下限 | 30.7% | 43.2% | 26.1% |
| **每股票 median(\|收益\|)（新）** | **26.8%** | **50.8%** | **22.5%** |

新规则上线后在全量 5,553 个事件上实测：**28.1 / 47.7 / 24.3**。

| # | 内容 | 验证 |
|---|------|------|
| 35 | **标签改为每股票历史 median(\|收益\|)**，中位数的定义保证一半事件在区间外，25/50/25 按构造成立 | 5,553 事件实测 28.1/47.7/24.3 |
| 36 | **band 持久化到 `outcomes.flat_band`**，逐事件一个值，训练和所有判分面读同一列。不重算 → 不可能再漂移 | 5,553 行写入 |
| 37 | **point-in-time**：band 用该事件之前的历史算，事件不参与自己的 band | expanding band 收敛到各自全样本中位数（META 6.80 vs 6.31、NVDA 4.00 vs 3.98） |
| 38 | **拦下一个泄漏**：`flat_band` 是数值列，会被 `feature_cols` 自动扫进去当特征——而它**就是 label 边界**，等于白送一半答案。两处排除名单都已加 | 静态检查脚本验证 6 个 label 派生列在两处名单里都齐 |
| 39 | **不设下限**（刻意）：JNJ band 0.49%、META 6.80%，14 倍跨度。旧规则会把其中 6 只压成同一个 2.50% | 逐股抽查 |

> **基线随之变化**：「全押 FLAT」基线从 60.63% 降到 **47.7%**。门槛低了，但这是个有意义的门槛——
> 旧的 60.63% 基线之所以那么高，只是因为 label 把太多东西定义成了「没发生」。

> ⚠️ **本节所有准确率数字在重训完成前都是旧的**。重训 → regenerate → recalibrate 全流程
> 跑完后必须重新测一遍并更新第 6a-2 节的表格。

### 6c. 2026-10-02：GCP 停服 → 迁到 Oracle，数据部分丢失

**发生了什么**：GCP $300 试用 2026-08 到期，账单关闭，项目停用。VM `signalpha-prod` 和磁盘（含 Postgres 全量数据、模型 artifacts、TLS 证书）随之不可访问，按 GCP 政策 30 天后删除。网站从 8 月起一直下线。7-26 那次带 move 头的重训当时跑到 stage 2，结果随机器一起丢了。

**恢复用的东西**：
- `~/Desktop/sp_dump.sql`（**2026-04-28** 的 pg_dump，迁到 GCP 那天导的）：5,530 事件 / 5,530 特征 / 5,407 结果 / 1,836 宏观。
- 本地 `.env`（2026-07-20）：所有 API key 完好。

**永久丢失**：4-28 之后的用户账号（只有 Justin 和女朋友两个）、Oracle 信号历史、Pulse 交易日志、simulator 状态、model_performance 历史。

**4-28 之后的财报**：用新写的 `data_pipeline/backfill_gap.py` 补（只补已追踪的 ticker，不扩大 universe；事件 → 特征 → 结果，幂等）。之后 `compute_flat_bands` → `retrain_pipeline.sh` 全量重训。

**dump 里的 predictions 是泄漏时代的**（is_out_of_sample 默认 FALSE），`OUT_OF_SAMPLE_ONLY` 会把它们全部挡掉，重训的 regenerate 步骤会覆盖。所以重训完成前 Track Record / Backtest 显示为空是**正确行为**，不是 bug。

**这次的教训**：迁移前没有备份，数据库的命根子是一份 5 个月前的手工 dump。**待办：在 Oracle 上配每日 `pg_dump` → 推到机器外（如 Cloudflare R2 免费额度）。**

### 6d. 2026-10-05：PIT 泄漏、转向 breakout、全站巡检修复

**PIT 泄漏（决定性发现）**：`collect_event_snapshot` 把带日期的数据源和只能返回「今天值」的数据源混在一起——期权链、分析师预期、基本面、空头/持仓、新闻/10-Q 情绪，以及 `last_8q_reactions`/`beats`（采集时最近 8 次，回填事件里**包含事件本身**）。对 backfill 的历史事件这些全是事后值。修法：`models/features.py` 白名单（61 个 PIT 特征 + `own_band`/`mom20_vs_band` 两个派生），训练、regenerate、线上 `run_predictions` 全走 `feature_columns()`。PIT 全量重训 10-05 18:30 UTC 启动（log `~/retrain_pit_20261005.log`），完成后 `~/after_retrain.sh`（setsid 常驻）自动跑 `run_predictions` + 重启 backend，结果写 `~/after_retrain_20261005.log`；**有 Traceback 就不推上线**。

**Breakout 模型**（`data_pipeline/move_model.py`）：pooled XGB，target = `|ret| > flat_band`，walk-forward 从 40% 起 10 折。指标写 `artifacts/move_metrics.json`，模型 `artifacts/move_model.joblib`。档位：`threshold_top_decile` → breakout，`top_quintile` → elevated（`headline_service.move_tier`）。

**本轮巡检的 bug 台账**（全部 observed，验证方式在最后一列）：

| # | 问题 | 修法 | 验证 |
|---|---|---|---|
| 1 | 部署后浏览器继续跑旧 bundle（index.html 无 Cache-Control，被启发式缓存）；旧前端读新 API → Brief 整页白屏 | `frontend/nginx.conf`：`/` no-cache，`/assets/` immutable 一年 | `curl -I` 两个头都对 |
| 2 | 没有 ErrorBoundary，任何渲染错误整站变黑屏 | `components/RouteBoundary.tsx`（按 pathname key；检测到新版本自动 reload 一次）+ `hooks/useBuildCheck.ts`（导航时最多 5 分钟比对一次 entry hash，有新版下一次导航整页加载） | tsc 通过；线上 bundle 已含 |
| 3 | Pulse 首次加载 8–10 秒 | `scan_market_cached()` stale-while-revalidate + 启动预热；scheduler 仍直调 `scan_market()` | `/pulse` 0.17s |
| 4 | `/pulse/track-record` 每次加载请求 3 次 | `api/pulseTrackRecord.ts` 30 秒共享 promise | — |
| 5 | Pulse 1 笔交易显示「100.0% win rate」 | <10 笔改显示「too few to judge」 | 页面实测 |
| 6 | Showdown SNIPER 98 天 0 笔（breakout 前 10% ∧ 方向置信前 20%） | 改为 breakout 前 10% ∧ gap 超过 band → 顺 gap，归入 POST_EARNINGS | API：1 笔；全历史回放 n=61 +1.27% t=0.82（不显著，文案不吹） |
| 7 | BandTimeline 琥珀色 =「回归估计 > band」≈ 一半事件，与 Calendar 只有 3 个 breakout 矛盾；popup 硬编码英文 | 颜色按 `move_tier`；柱改为期权隐含波动；i18n；只在 Backtest tab 显示 | 截图 |
| 8 | 回归 `expected_move_pct` 输给朴素基线（Spearman 0.273 vs band 0.371；MAE 24.69pp vs 2.06pp） | Calendar 列改「Options imply + usual」；calendar API 加 `implied_move_pct`（price_features 的 straddle/spot，51/77 覆盖） | API 实测 |
| 9 | 深度页 IV 环按 P(FLAT)<0.5 判「likely to break out」——校准后几乎所有股票都满足 | `CrushChamber` 改吃 `moveTier` | GS 显示「flagged — top decile」 |
| 10 | 深度页 KPI 以方向领衔；`hist avg ±0.00%`（None 当 0） | KPI：Breakout risk / Usual move / Direction(context) / Completeness；`/predict` 加 `prob_move/move_tier/flat_band/implied_move_pct/breakout_base_rate` | `/api/v1/predict/GS` 实测 |
| 11 | Oracle 迁移后 0 信号：`src_ark` 第一行 `return []`（7 月 snapshot 带进来的）；Pelosi 来源 house-stock-watcher 403 | ARK 恢复（最新交易日、≥0.10%、前 3）；Pelosi 改读 House Clerk 官方 PTR（`{year}FD.zip` + PDF，`pypdf`） | `oracle_signals` 出现 CBRS / BWXT 两条；PTR 正则在 3 份真实 PDF 上验证 |
| 12 | 健康徽章只认「交付条目」，Pelosi/Buffett 两次申报之间被标 NEWS ONLY | 主数据源成功应答即 `_mark_ok` → LIVE | Cathie Wood 显示 LIVE |

**没修 / 待办**：
- DAL、TLRY 等少数日历 ticker 没有 outcomes → 无 band。要扩 universe 时用 `backfill_gap.py`。
- 方向模型 SHAP 里有 `price_t0`、`spy_200ma` 等价格**水平**特征——不是泄漏，但树模型可能拿它当 ticker ID。PIT 白名单可以考虑只保留收益率/比值类。
- FMP 免费档：国会交易只给最新 25 条且按名查询 402；10-05 下午配额已被打满（429）。别再拿它做轮询源。
- Simulator 持仓卡仍显示回归 `expected_move_pct`。

### 6e. 2026-10-06：Arena / Straddle Check / Pro / MCP / Paper Account 改版

方向文件：`docs/STRATEGY.md`（定位、护城河、定价、路线图、kill criteria）。PIT 重训 10-05 22:37 UTC 完成并自动上线：3 分类 39.37% vs 47.3%；breakout 数字不变（确定性）。

| 模块 | 文件 | 要点 | 验证 |
|---|---|---|---|
| **Earnings Arena** `/arena` | `services/arena_service.py`、`routes/arena.py`、`pages/ArenaPage.tsx` | 每份财报前 3 天内，5 个预测者（SignAlpha ML / 期权市场 / 基准率 / GPT-OSS 120B / Qwen3.8 27B，via Groq）回答同一问题 P(\|T+1\| > band)。payload 规范化 JSON → SHA-256 → 每批 manifest 的哈希提交 OpenTimestamps（alice+bob 两个日历）→ 比特币。T+1 后 Brier 打分，和基准率做配对 bootstrap 90% 区间；<20 份一律 warming_up。Claude 槽位已写好，设 `ANTHROPIC_API_KEY` 自动加入（`claude-opus-5-5`，structured output + `fallbacks: "default"`）。scheduler：每 2 小时 :20 封存、每小时 :25 判分 | 首批 PEP 5 条；外部下载 manifest/.ots 用官方 `ots verify` 通过（pending→Bitcoin）；每条 payload 哈希=digest |
| **Straddle Check** | `routes/moves.py`、`components/StraddleCheck.tsx` | 单股页：历史每次财报反应的 beeswarm，平时 band / 期权定价两条线，可拖阈值；均值÷定价比率 | JNJ：平时 ±0.5%、均值 ±0.7%、定价 ±1.7%、25 次里只有 2 次超过 |
| **Pro + waitlist** `/pro` | `pages/PricingPage.tsx`、`routes/waitlist.py`、表 `pro_waitlist` | 没有支付——如实说「还没开卖」，按创始价留邮箱 + 勾选愿付费功能 = WTP 数据。每个功能标 live / beta / coming | 非法邮箱 422 |
| **MCP server** `/api/mcp` | `backend/app/mcp_server.py`（mcp 2.x 的 `MCPServer`，**不是** FastMCP） | 5 个只读 tool：upcoming_earnings / earnings_risk / portfolio_earnings_risk / model_track_record / arena_standings。stateless + JSON。**必须显式 allowed_hosts**，SDK 默认只放 localhost → 421。用精确 Route 挂载而非 Mount（Mount 会吞 trailing-slash 重定向） | 公网 initialize / tools/list / tools/call 均 200；伪造 Host 421 |
| **Paper Account 改规则** | `services/simulation_service.py` | 旧规则（方向置信≥55% 且领先 FLAT 15pp）校准后永不触发。新：大动风险前 20% + 开盘跳空超过 band → 顺跳空方向，反应日按实时价进场，持有约 5 个交易日，5% 仓位不加杠杆。report_time 未知的取两个候选日中跳空大的那个，且要等两天都开盘 | 已重置为 $1M；旧数据备份 `~/backups/sim_pre_breakout_20261006.sql` |
| **安全** | `routes/simulator.py` | `/simulator/reset` 原来无鉴权，任何人一个 POST 就清空公开战绩 → 需 `X-Admin-Token`；`/run-step` 全局 55 秒节流 | 无 token 403 |
| 依赖 | `backend/requirements.txt` | mcp 2.x 需要 uvicorn≥0.31.1 → fastapi 0.111→0.115.14、starlette 0.46、uvicorn 0.39；新增 anthropic、mcp、pypdf | 全站 verify_deploy 通过 |
| 导航 | `Layout.tsx` | 加 Arena、Pro；Contact 移出导航（About 和 Pro 页有入口） | — |

**待办**：Arena 用户判断目前只存 localStorage（不能做跨设备排行榜）→ S2 加登录后服务端存储；`ots upgrade` 可在 Bitcoin 确认后把完整证明存回库里；期权快照只覆盖 51/77 个事件。

### 6f. 2026-10-10：反应日 bug + 特征泄漏 + 方向信号（**此前所有数字作废**）

**起因**：Justin 要求把产品做成方向性的。为了测"财报后方向"去抓 EPS surprise，顺带暴露了两个底层 bug。

**Bug 1 — 反应日错位（影响 47% 的标签）**：`earnings_events.report_time` 对全部 5,730 个事件都是 NULL；`outcome_snapshot` 一律把 `earnings_date` 那根 K 线当反应日。盘后（AMC，约 42%）的财报真正在**下一个交易日**反应。例：GTLB 2022-03-14 库里 T+1 = −6.8%（财报前的白天），真实反应是次日 +27%。
- 修法：`data_pipeline/earnings_timing.py`（yfinance `get_earnings_dates` 的时间戳 → BMO/AMC/DMH + EPS surprise，存 `earnings_surprises` 表，回写 `report_time`）；`outcome_snapshot(history, date, report_time)` 按正确 session 算，新增 `outcomes.reaction_date`；无 report_time 时取两个候选日里跳空大的。
- 结果：5,718 事件打上时间（3,251 BMO / 2,429 AMC），**2,661 / 5,655 条 outcome 被改写**。备份 `~/backups/pre_reaction_fix_20261010.sql.gz`。

**Bug 2 — 特征两批约定相反**：A 批特征截到 D−1、标签用 D（BMO 对、AMC 错）；B 批（2020 后为主，占 BMO 约四成）特征截到 D、标签用 D+1（AMC 对；BMO 的特征里含反应本身，`ret_1d_pre == 标签`）。标签错的时候两个错互相掩盖；标签一修正，B 批变成"财报前方向 AUC 0.66、前 10% 上涨 81%"——**是泄漏，不是信号**。另有实时采集的事件特征是数月前的陈旧快照。
- 修法：`data_pipeline/rebuild_pit_features.py`，统一规则 = **特征只用 `reaction_date` 之前的 K 线**（未来事件用到今天为止）；每个 symbol 行情只下一次。慢宏观（收益率/联邦基金/CPI/PCE）保持原值。重建 5,707 个事件。备份 `~/backups/price_features_pre_rebuild_20261010.sql.gz`。`run_predictions` 每次先刷新未来事件的特征。

**干净数据上的结论（walk-forward，pooled XGB）**：

| 问题 | 结果 |
|---|---|
| 财报**前**方向 | AUC **0.502**，多空 −0.19%。彻底没有 |
| breakout（会不会大动） | AUC **0.584**，前 10% 69.4% vs 基准 56.9%；后 10% 平静 60.6% vs 43.1%（现在两头都有效）。以重训后的 `move_metrics.json` 为准 |
| 财报**后**方向，模型（开盘→T+5） | 前 10% 上涨 59.4% / 后 10% 48.8%，L/S +0.87%，t=3.0。有但弱，且不比规则好 |
| **规则：高开 > 2× band，反应日收盘买，持有 20 session** | n=555（2008–2026），64.3% 上涨 vs 全体 56.8%，每笔超额 **+1.73%，t=3.9**，13 个样本≥20 的年份里 9 年为正 |
| 同规则只持有 5 session | t=2.4（只看 2021+ 是 3.9——**不要挑窗口**） |
| 低开做空 | ≈0，没有 |

**产品决定**：方向只在财报后给，且只做多。`services/playbook_service.py`（`SIGNAL_K=2.0, SIGNAL_HOLD=20, SIGNAL_ENTRY="close"`；`test()` 任意规则 vs「对全部财报做同样交易」基准，`grid()`，`live()`，`signal_summary()`）；`/api/v1/playbook/{test,grid,live}`；headline 新增 `follow_through`。局限写死在 payload：幸存者偏差（今天的大盘股）、成本、多重检验。

**Strategy tab 重写**：原 Backtest（方向回测）、Showdown（5 机器人）都交易已证伪的财报前方向，删除（`BacktestingPage.tsx` / `ShowdownPage.tsx` / `BandTimeline.tsx`）。现在两块：**Playbook**（`PlaybookPage.tsx`：最近反应的财报 + 规则实验室 + 热力图）和 **Live book**（模拟盘，规则改为同一条：高开 > 2× band 只做多，持有约 20 session）。日历/简报的"方向概率"列换成发布时间（盘前/盘后）。

**新增任务**：`sync_earnings_timing`（7:40/16:40/21:40 ET）；`alert_follow_through`（9:38/9:50/10:20 ET，Telegram，每 ticker 每天一次，靠 redis 去重）。MCP 新工具 `post_earnings_signals`。

**重训**：10-10 19:1x UTC 启动 `~/retrain_and_promote.sh`（log `~/retrain_fix_20261010.log`），成功后自动刷新未来特征 → run_predictions → 重启 backend；有 Traceback 不上线。**完成前，站上 3 分类/ breakout 数字仍是旧模型对新标签，不可引用。**

**教训**：(1) 同一份数据两批回填、约定不同，是最隐蔽的泄漏来源；(2) 结果好得不像真的就一定不是真的——81% 那一刻要先查泄漏而不是庆祝；(3) 选规则要在全历史上选，不能挑好看的窗口。

### 6g. 2026-10-11：重训上线 + 方向倾向（lean）+ 期权到期日 bug + Night Edition 全站重设计

**重训结果（10-10 23:43 UTC PROMOTED，线上 `/model/headline` 实读）**：3 分类 40.27% vs 全押 FLAT 43.74%（n=5,610）；breakout AUC 0.5847，前 10% **70.59% vs 56.91%**（z=5.09，n=340），后 10% 平静 59.12% vs 43.09%；follow-through 64.3% vs 56.8%，t=3.92，n=555。6f 表里的 69.4% 是重训前的估计，以这组为准。

**方向倾向 `data_pipeline/direction_lean.py`（Justin 要财报前方向，综合特征 + Avellaneda-Lee reversion）**：透明的逻辑回归打分卡，产物 `artifacts/lean_model.json`。拟合因子：reversion（−AL s-score，`rebuild_pit_features._reversion` 算日频 AL：60 日对 SPY+板块 ETF 回归、残差 OU 拟合）、runup、past_prints、momentum、beat_streak；只有实时值、无法回测的因子（revisions / skew / put_call）给固定小权重并在 UI 上标「unproven」。**walk-forward 50.55%，n=3,393，z=0.64，AUC 0.504，verdict=`coin_flip`**。结论：财报前方向没有 edge，这个打分卡如实展示为「实验性」，并封存进 Arena 用未来财报检验（`arena_forecasts.lean_hit`，榜单 `dir_n/dir_hit` + Wilson 区间）。`predictions.lean_up / lean_factors`；`run_predictions` 末尾 `score_upcoming()`。**任何地方展示 lean 都必须带「回测 = 抛硬币」这句。**

**Bug — 期权隐含波动取错到期日**：`YFinanceClient.options_snapshot` 一律取 `expiries[0]`。周期权在财报前到期时，「隐含波动」是几个普通交易日的价格（10-10 凌晨 GS 读出 0.19%、JPM 0.20%）。同一函数还有三个错：跨式用 lastPrice 而不是买卖中间价；put/call「比率」数的是行权价个数；「25-delta skew」其实是两个 ATM IV。修法：`options_snapshot(ticker, on_or_after=反应日)` 取第一个覆盖反应日的到期日（BMO/DMH = 财报日，AMC 或未知 = 次日），mid 报价，成交量比，skew 用现价 ±5% 的行权价；`collect_event_snapshot(..., report_time)` 传入。影响面：全站「Options imply」、Straddle Check、Arena 的 options_market、MCP。

**⏳ 待 Justin 决定 — 作废 10-13 那批 Arena 判断**：C/GS/JNJ/JPM/UNH/WFC 共 30 条在 10-10 04:20 UTC 封存，早于当晚的反应日修复——band 是错的（JPM 0.80% vs 现 1.89%），隐含波动是上面那个 bug 的垃圾值。代码已就绪：`arena_service.void_unresolved(db, date, sealed_before, reason)` 把**未评分**的行移到 `arena_voided`（保留 digest 和 anchor，榜单 `voided` 字段 + Arena 页披露块），然后 `seal_due` 重封。服务器脚本 `~/reseal_run.sh` + `/tmp/void_reseal.py`，备份 `~/backups/arena_pre_void_20261012.sql.gz`。**没有执行**——改公开封存记录需要 Justin 明确同意；截止 10-13 09:10 ET。不作废的话这 30 条会按错误的 band 评分。

**模拟盘与规则对齐**：之前声称执行 Playbook 规则（持有 20 session），实际带 −8%/+15% 止损止盈，且标价用 T+5 结果（缺失时退回 T+1，等于第二天就把持仓冻结在反应日收盘价）。现在 `USE_STOPS = False`，标价用 `SIGNAL_HOLD` 对应的结果、未到期用实时价；`_config_dict` 新增 `holding_sessions / stops_active`；参数面板不再显示 T+5 / 2.5× 杠杆。

**Night Edition 设计系统（全站重做，Justin：「像 vibe code 量产出来的」）**：
- 令牌在 `frontend/src/index.css` 顶部：暖墨底 `--bg-0:#0c0b0a`、哑光平面 + 发丝线（**不用玻璃 / blur / glow / 渐变文字**）；颜色只表达含义（`--signal` 琥珀 = 模型在喊、`--up` 薄荷、`--down` 珊瑚、`--model` 天蓝）；奶油色「纸」`.paper`（`--paper / --paper-ink`）只用于**已封存 / 已定论 / 要签字**的东西（Brief、Arena 回执、About 对账单、Pro 订单、Contact 名片）。字体 Newsreader（display 衬线，标题里 `<em>` 斜体 = 这页的关键词）/ Instrument Sans / JetBrains Mono（标签、数字）。旧令牌名保留为别名（`--accent-cyan` → signal）。
- 每页同一个开头：`components/PageHead.tsx`（kicker + 衬线标题 + lede + 右侧 `.figs` 数字 + 琥珀波形线）。新页面必须用它，不要再写自己的 hero。
- 闭环：`lib/journey.ts` 定义 01 Calendar → 02 Brief → 03 Arena → 04 Strategy → 05 Model（+ 研究台 Pulse / Oracle）；导航编号、PageHead、页脚 `JourneyRail`、About 的索引都读它。
- 标志性交互：`EarningsTrace`（日历画成地震仪）、`BreakoutDial`（CSS 旋转，`transform-box: view-box`）、`LeanCard`（拔河）、Arena 回执盖章、About 对账单逐行盖章（HOLDS / FAILS / COIN FLIP，实时读 headline）、⌘K 命令面板、`Tape`、卡片光标聚光。
- 旧的「mission control」界面（Pulse、模拟盘、ticker 详情面板）没有重写布局，由 `src/styles/desks.css` 统一压平外观（在 index.css 之后加载）。
- About 重写为：对账单 + 闭环索引 + 方法 + **更正栏**（每次数字出错的日期和处理）；写死的基准条形图、过期路线图删除。Contact 重写（四个理由各自打开带主题的邮件草稿 + 名片）。
- 导航按钮「Start free trial」改为「Get alerts」：Pro 并未开卖，账号实际提供的是 30 天 Telegram 提醒。
- 手机端：`html, body { overflow-x: clip }`；抽屉导航用 transform；≤700px `.figs` 改成行；≤520px 语言切换和搜索进抽屉。375px 下 13 个路由 `scrollWidth == 375` 已验证。
- i18n 一律走 `scripts/i18n_set.py`（`apply({key: (en, zh)})`，在 `scripts/` 目录运行）。

### 6h. 2026-10-14：全美股股票池 + 兑现记录 + 今日简报 + 按需打分

**股票池（`data_pipeline/universe.py`，表 `universe`，DDL 在 `schema_guard.UNIVERSE_DDL`）**：NASDAQ screener 一次拉全美上市股（5,881 只，去掉优先股/权证/单位；ADR 保留；同一公司多类股只留一个，其余 tier=`dup`）。tier：`core`（原 180 只）、`large` ≥$10B、`mid` $2–10B、`small` $0.3–2B（这三档入库完整历史并参与训练）、`micro` <$300M（只能搜索，`/lookup` 按需打分）。
- `python -m data_pipeline.universe refresh | build [--limit N] | status`；build 可断点续跑（`history_at`），按市值从大到小；每只：Yahoo 财报日期（`earnings_timing.fetch`，2008 起）→ 行情 → 正确反应日的 outcome → 反应日之前的 PIT 特征（`features_asof`，FRED 慢变量取最近一条已有事件的值，`SlowMacro`）。单只约 5 秒。
- 服务器脚本：`~/universe_run.sh`（log `~/universe_build.log`，结束写 `UNIVERSE_DONE`）→ `~/universe_train.sh` 自动接力（log `~/universe_train.log`）：备份 artifacts 和 predictions → move_model 重训（新增 `by_tier` 分层评估，并为新事件建 Prediction 行）→ direction_lean.fit → run_predictions。备份：`~/backups/full_pre_universe_20261014.sql.gz`、`artifacts_pre_universe_20261015`。
- 每日 `sync_universe_calendar`（06:50/15:50 ET）从 NASDAQ 财报日历补未来 45 天日期，给新事件建空 `price_features` 行，run_predictions 负责填特征（`rebuild_pit_features` 遇到无 FRED 字段的行会用 `SlowMacro` 补）。
- **有意的范围限制**：Arena 只封存 core + large（每条要 2 次 LLM 调用，几千只小盘会打爆免费额度）；`collect_options_data` 仍按 21 天窗口跑全部，注意耗时。
- 幸存者偏差：股票池是今天还在上市的公司，退市/被收购的不在历史里，小盘更严重——分层结果必须带这句。

**兑现记录（`services/receipts_service.py`，表 `call_log`，`/api/v1/receipts`，Model 页默认子页）**：只收结果出来之前就挂在站上的判断，`LIVE_SINCE=2026-10-12`。
- 财报后跟进信号：按最新收盘价逐日标价（已过 n/20 个交易日、收益、同期 SPY、每笔 $10k 盈亏），满 20 个交易日按第 20 天收盘平仓。行情用 `yf.download` 批量拉、缓存 10 分钟（不复权，与 outcomes 一致）。
- 财报前判断：`freeze_due` 在每份财报开盘铃后把当时的 prob_move / 档位 / band / lean 冻结进 `call_log`（之后重训覆盖 predictions 也不影响），`grade_due` 等 outcome 出来后评分。任务 `freeze_and_grade_receipts` 每小时 :05/:35。10-12～10-14 的 7 条是 10-15 补录的（从赛前写下的 predictions 复制），页面有披露（`late_frozen`）。

**今日简报（`services/today_service.py`，`/api/v1/today`，Brief 页默认「今日」，「本周」是原来的纸面简报）**：指数和 11 个板块 ETF 的涨跌、今天及下一个开盘前发财报的公司、最新交易日的反应（相对平时波动的倍数、是否被标记、是否触发跟进）、持仓信号。首段文字由同页数字拼出，不用 LLM。

**搜索与按需打分（`services/lookup_service.py`）**：`/api/v1/search?q=` 查 universe（代码前缀 + 公司名）；⌘K 面板接入。`/api/v1/lookup/{ticker}`：没有入库历史的股票现场拉 Yahoo 财报日期和行情、测历史反应、取中位数作平时波动、用线上 breakout 模型给下一次财报打分（缓存 6 小时，约 5–10 秒）；个股页 404 时自动回退到 `OnDemandDossier`，微盘股明确写「超出训练范围，分数属于外推」。

**Bug（存在已久）— 新财报结果没有平时波动带**：`outcomes.flat_band` 只由手动脚本 `compute_flat_bands` 写，小时级的结果采集从不写 → 10 月以来所有新反应 band 为 NULL → Playbook 实时页、兑现、今日简报里的跟进信号**永远不会触发**（Telegram 提醒用的是 `load_flat_bands` 最新值，不受影响）。修法：`compute(missing_only=True)`，结果采集写入后自动调用。同时结果采集改为只处理「还没结果」或「T+20 未填且今天没更新过」的事件，否则全市场下每小时要重拉上千只。

**全市场重训结果（2026-10-15 06:12 UTC 上线，线上 headline 实读）**：3,221 只建完历史（1 只失败），共 143,553 个事件；股票池 3,233 只、149,283 个事件。
- breakout（pooled XGB，61 个 PIT 特征，walk-forward 86,414 份）：AUC **0.606**，前 10% **73.4% vs 55.6%**（z=33）。分层（全局阈值切前 10%）：大盘 71.1% vs 54.3%（n=26,649，z=14）；中盘 72.4% vs 54.8%（z=19）；小盘 75.1% vs 57.4%（z=23）。**三档都成立。**
- 财报后跟进（高开 >2× band、收盘买、持有 20 日）：全部 n=10,180，54.4% vs 52.5%，每笔超额 **+0.93%**，t=5.99，19 年里 11 年为正。大盘 57.6% vs 55.1%、超额 +0.74%、t=3.4（n=3,125）；中盘 53.4% vs 52.3%、+0.98%、t=3.6；小盘 52.7% vs 50.1%、+1.03%、t=3.4。**仍成立，但旧口径（180 只、+1.73%、64.3%）明显高估了**——数字以 headline 为准。
- 方向倾向：86,408 份，命中 51.39%，同期上涨占 51.52%，**输给「永远猜涨」**，多空 t=0.87 → `coin_flip`。注意：重训脚本一开始把它判成了 `edge`（判定拿 50% 当基准），挂了约 1.5 小时，已修（`direction_lean.evaluate` 现在要求跑赢多数方向且多空 t≥2），并写进 About 更正栏。
- 三分类：仍是原 5,617 份（新股票没有三分类预测），40.3% vs 43.7%。
- 性能：`/performance` 原来加载整行 ORM（9 万行带 JSON），改为只取列 + 10 分钟缓存（11.5s → 0.8s）。

**Arena 作废（待 Justin 明确同意）**：10-13 那 30 条判断在截止前没能重封，已经按错误的 band 评完分。代码 `void_calls(include_graded=True)` + `PRE_FIX_CUTOFF` 已部署，`arena_voided` 加了评分列，页面会连得分一起公开。**执行被 auto-mode 拦下：作废已评分的公开记录与 Justin 当初同意的「赛前作废重封」不是同一件事，需要他单独点头。**

### 6b. 仍未解决

0. **✅ 已解决 — 标签泄漏（walk-forward 重生成完成并上线）**

   `regenerate_predictions.py` 已跑完：**5,505 条打分，5,477 条写回**（覆盖 98.4%）。四个消费面已接 `OUT_OF_SAMPLE_ONLY` 过滤并部署验证。原表备份在 `predictions_backup_20260720`（5,567 行）。

   **诚实数字（线上实测）**：
   | 指标 | 泄漏时 | walk-forward OOS |
   |---|---|---|
   | Backtest 胜率 @0.65 | 97.48% | **44.86%** |
   | Backtest 总收益 / Sharpe | +70.01% / 8.18 | **−5.66% / −0.578** |
   | Track Record 命中率 | 67.7% | **46.3%** |
   | Showdown QUANT | +24.28% | **−1.34%** |

   ### 🔑 由此得到的核心结论（对产品定位是决定性的）

   **模型没有方向预测能力，但有显著的"平静事件"识别能力。**

   > ⛔ **2026-10-05 更正**：后半句不成立。下表用的特征含 point-in-time 泄漏（6d）；只用 PIT 特征后「平静事件」识别很弱（最低 10%：53.4% vs 46.1%），站得住的是反方向——识别**会大动**的财报（前 10%：67.85% vs 53.93%）。下表保留作历史记录。

   > ⚠️ **下表已于 2026-07-22 用「每股票自适应区间」重算**。旧版用固定 ±2% 判分，
   > 而模型是按每只股票 0.5σ 训练的——等于拿错的答案卷判分。详见第 26 条。

   | 情形 | 准确率 | 基线 | 样本 | 结论 |
   |---|---|---|---|---|
   | P(FLAT)≥0.60（识别非事件） | **76.30%** | 60.63% | 1,055 | **+15.68pp，z=10.4，强显著** |
   | P(FLAT)≥0.70 | **78.48%** | 60.63% | 409 | +17.86pp，z=7.4 |
   | 模型给出**方向**时 | **25.45%** | 33.3%(三分类随机) | 165 | **比瞎猜还差**（z≈−2.1） |
   | 全样本 3 分类准确率 | **59.84%** | 60.63%(全押FLAT) | 5,468 | **低于最蠢基线 0.79pp** |

   独立交叉验证：用 `/performance` 页早就在显示的 `model_performance` 混淆矩阵算，准确率 48.12% vs 全押FLAT 49.96%，**同样低于基线**——说明这不是重生成引入的，是一直如此，只是从来没和正确基线对比过。

   **产品含义**：
   - ❌ 不能说"我们预测涨跌" —— 数据明确否定
   - ✅ 可以说"我们识别哪些财报大概率是非事件" —— 强统计支持，且**有真实交易用途**（卖 premium / 短跨式吃 IV crush；管理持仓风险）
   - 现有 pipeline 里的 `expected_move_pct` 和期权 IV 数据正好支撑这个方向

   **仍待办**：重做校准（只在 holdout 上 fit，写进 `raw_prob_*` 之外的列）。现在平均 confidence 0.71 对应 46.4% 准确率，**严重过度自信，直接展示给用户是误导**。

   以下是原始问题记录（保留备查）：

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

HANDOFF.md §5 的 10 个 bug 里：#2/#3/#4/#7/#8 已修。#5（Oracle 不出信号）在迁移后**复发**：表是空的（4-28 dump 之后的信号丢了），且 ARK 被 stub、Pelosi 来源 403——见 6d 第 11 条。

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

Oracle 的 `oracle_worker()` 不在 scheduler 里——它在 `backend` 容器的后台线程里跑（`main.py`），每 `ORACLE_SCAN_SEC`（90）秒一次。各数据源另有 `_due()` 节流（redis `oracle:srcrun:*`，ARK/国会/EDGAR 1 小时）——**手工调试时直接调 `src_*()` 会吃掉这个节流**，worker 一小时内不会再跑它；调完 `redis-cli del oracle:srcrun:<name>`。

backend 启动时还会后台预热一次 Pulse 扫描（`warm_scan_cache()`）。
