# SignAlpha — how to get it in front of people (2026-11-12)

Rules that apply to every channel below:

1. **Post as the founder, and say so.** "I built this" in the first line or a
   "Disclosure: I made signalpha.app" line. No sock-puppet accounts, no replying to your
   own posts from another account, no asking friends to upvote. Reddit and HN ban for it,
   and on a finance product it is the fastest way to lose the one thing the site sells:
   that its numbers can be trusted.
2. **Only numbers the site shows today**, each next to its baseline. No "returns", no
   "beats the market", no screenshots of the paper account as if it were money.
   "Research, not advice" on anything that mentions a trade.
3. **Lead with something useful without the link** (a finding, a dataset, an answer),
   link last. The posts that work on Reddit/HN would be worth reading with the link removed.
4. **Autopilot is paper-only for everyone but you** — talk about it as a paper-trading
   tool. Live trading other people's money is the RIA question still open.

## Where, ranked by fit

| Channel | Fit | Rules that matter | Who posts |
|---|---|---|---|
| Google (SEO) | Best long-term. 3,264 stock pages now have their own title/description and a sitemap | Submit `https://signalpha.app/sitemap.xml` in Google Search Console and Bing Webmaster Tools (needs your Google login; I can add the verification file) | You set up once |
| Hacker News — Show HN | Strong: free, no signup, non-trivial, honest about failures, Bitcoin-anchored forecasts | Title starts "Show HN:"; must be tryable without signup (it is); a top comment from you; reply to every comment; never ask for upvotes | You (log in), or me after you approve the exact text |
| V2EX 分享创造 | Strong for the Chinese UI; the node is active and already has stock tools | Post in 分享创造 only; be around to answer | You, or me after approval |
| r/SideProject, r/indiehackers, r/webdev (Showoff Saturday) | Medium: builder audience, self-promo allowed | Follow each sidebar; one link | **You** (Claude in Chrome cannot open Reddit) |
| r/algotrading | Medium-high if the post is research | Not for promoting firms; projects must follow its "rules of engagement" wiki — post the finding, not the product | You |
| r/investing, r/options, r/stocks | **Don't.** r/investing bans self-promotion permanently even for free tools; r/options bans promoting apps | Only answer questions, never link the site | — |
| X / 即刻 / 小红书 / 雪球 | Medium, slow build | A weekly post from the site's own data ("earnings that moved most vs usual this week", "Arena scoreboard"), link in the reply | You |
| Product Hunt | One-off spike | Needs an account and a launch day; do it after HN/V2EX feedback | You |

## Things the site already has that are worth talking about (true as of 2026-11-12)

- **Earnings Arena:** 3,753 forecasts sealed before the bell on 756 reports, each hashed
  and anchored in Bitcoin. After 736 graded reports our model is the only forecaster
  measurably better than the base rate (Brier 0.241 vs 0.249). GPT-OSS-120B and Qwen are
  indistinguishable from it; the options market is worse than the base rate.
- **Breakout flags, live since Oct 12:** 191 of 270 flagged reports (70.7%, 66–75%) moved
  more than the stock usually does, against 51.3% for all reports. Backtest said 73.4%.
- **What does not work, published:** pre-report direction is a coin flip (49.8% live);
  copying Buffett/Ackman 13Fs lost to SPY; most of 496 famous strategies lose to buy-and-hold.
- **Earnings timing to the second** from the SEC 8-K acceptance stamp, plus each company's
  reported numbers and the original filings on every stock page.

## Drafts (edit freely; post only what you have read)

### Show HN

**Title:** Show HN: I seal earnings forecasts from AI models before the bell and anchor them in Bitcoin

**Top comment (you):**

> I built SignAlpha (https://signalpha.app) because every earnings-prediction site I tried
> showed me its wins and none of its misses.
>
> One question per report: will the stock move more than it usually does? Before each
> report, our model (XGBoost on 61 point-in-time features), two open LLMs via Groq
> (GPT-OSS-120B, Qwen), the options market and a base rate each answer it. Every forecast
> is serialized, SHA-256 hashed, and the batch is timestamped in Bitcoin with
> OpenTimestamps, so none can be edited after the fact. After the first close they are
> scored with a Brier score against the base rate on the same reports, with a bootstrap
> interval.
>
> After 736 graded reports, the model is the only forecaster measurably better than the
> base rate (0.241 vs 0.249). The LLMs are indistinguishable from it. The options market is
> worse than the base rate — it prices bigger moves than happen.
>
> What does not work is on the site too: predicting direction before a report is a coin
> flip (49.8% live), copying 13F filings lost to the S&P, and most of 496 well-known
> trading rules lose to buy-and-hold once you grade them out of sample.
>
> Everything is free and needs no signup. Stack: FastAPI, Postgres, XGBoost, a scheduler
> on one 2-core ARM box, React. It is research, not advice. I'd love to hear where the
> methodology is wrong.

### V2EX 分享创造

**标题：** 做了个财报季研究网站：AI 预测在开盘前封存并锚定到比特币，所有失败的结果也一起公开 —— signalpha.app

> 大家好，我是作者。做这个是因为市面上的财报预测网站只晒对的，不晒错的。
>
> 每份财报只问一个问题：这次财报后股价会不会动得比它平时大？财报前，我们的模型、
> 两个开源大模型（GPT-OSS-120B、Qwen，经 Groq 调用）、期权市场和历史基准率各给一个
> 概率，全部哈希后用 OpenTimestamps 锚定到比特币，事后谁也改不了，出结果后按 Brier
> 分数和基准率比。
>
> 目前 736 份已判分财报：只有我们的模型统计上显著好于基准率（0.241 vs 0.249），两个
> 大模型和基准率分不出高下，期权市场反而比基准率差。
>
> 不灵的东西也写在站上：财报前猜涨跌是抛硬币（实盘 49.8%），抄 13F 跑输标普，496 条
> 有名的交易策略多数打不过买入持有。
>
> 有中文界面，免费、不用注册；每只股票页能看到精确到秒的财报时间（取自 SEC 8-K
> 接收时间）和公司原始财报文件。仅供研究，不构成投资建议。欢迎拍砖。

### r/algotrading (research post, link last)

**Title:** I sealed 3,700 earnings-move forecasts before the bell (our model, two LLMs, the options market). Only one beat the base rate.

> Method: before each report, five forecasters give P(|T+1 return| > the stock's usual
> earnings move). Forecasts are hashed and timestamped in Bitcoin (OpenTimestamps) before
> the bell; graded by Brier score against a base rate on the same reports, 90% bootstrap
> interval.
>
> Results after 736 graded reports: XGBoost on 61 point-in-time features 0.241; base rate
> 0.249; Qwen 0.247 (CI includes the base rate); GPT-OSS-120B 0.252 (same); options market
> (ATM straddle, normal approx.) 0.278 — consistently over-predicts big moves.
>
> Two things that bit me: (1) in my first version, for the ~40% of reports released after
> the close, the stored "T+1 reaction" was the session *before* the news — fixing that
> changed every label and every model; (2) Alpaca's paper engine is not a fill model: 19
> of 21 opening limit orders it left unfilled had traded at or through their limit on the
> SIP tape.
>
> Scoreboard and every sealed call (disclosure: I built it): https://signalpha.app/arena

### Reddit replies (only where someone asked)

Search Reddit for questions like "what time does X report earnings", "how much does X
usually move on earnings", "implied move vs actual". Answer the question first in full;
then one line: *"Disclosure: I built signalpha.app — the stock page shows the exact SEC
timestamp of the last release and the usual move vs what options price."* Never in
r/investing or r/options.

### X / 即刻 weekly post (template)

> Earnings week of {date}: the reports options price for the biggest move vs. how much
> each stock usually moves — {3 tickers with implied/usual ratio}. Last week {n} of {m}
> flagged reports broke their usual range (base rate {b}%). Sealed forecasts: signalpha.app/arena
