<div align="center">

# Alphasignal

### ML-Powered Earnings Intelligence Platform

**Predicting post-earnings price movements with FinBERT sentiment analysis on 10-Q MD&A filings, FinBERT news sentiment, macro factors, and a sector-aware XGBoost + LightGBM ensemble.**

![Status](https://img.shields.io/badge/status-live_demo-34d399)
![Stack](https://img.shields.io/badge/stack-FastAPI_%7C_React_%7C_XGBoost_%7C_FinBERT-38bdf8)
![Model](https://img.shields.io/badge/model_accuracy-52.7%25_general%20%7C%2069.1%25_industrials-a78bfa)

</div>

---

## ✨ What it does

Alphasignal ingests earnings calendars from 60 US large-caps, engineers 35+ features across price action, macro regime, historical reactions, FinBERT-scored news, FinBERT-scored SEC 10-Q/10-K Management Discussion sections, and cross-feature interactions. A sector-aware ensemble (XGBoost + LightGBM + Logistic Regression, voting classifier) predicts the post-earnings direction (UP / FLAT / DOWN), expected move magnitude with quantile forests for convergence bands, and produces SHAP explanations for every prediction.

The React dashboard visualizes predictions in a Bloomberg-terminal-style UI with live quote integration, per-sector performance heatmaps, confusion matrices, equity curves, and feature importance plots.

## 🎯 Key results

| Scope | Accuracy | F1 (weighted) | Notes |
|---|---|---|---|
| **General model** | **52.7%** | 49.6% | vs. 33.3% random baseline (3-class) |
| Industrials | **69.1%** | 60.2% | Best sector |
| Financial Services | 64.5% | 59.2% | |
| Consumer Defensive | 61.1% | 54.8% | |
| Healthcare | 58.1% | 52.1% | |
| Technology | 37.6% | 36.2% | Hardest sector — high vol, FLAT sparse |

Evaluated via walk-forward out-of-sample splits across 1,496 earnings events. Full breakdown lives at `/performance` in the dashboard.

## 🏗️ Architecture

```mermaid
flowchart LR
    subgraph Sources[Data Sources]
        A1[yfinance<br/>prices + news]
        A2[SEC EDGAR<br/>10-Q / 10-K]
        A3[FRED<br/>macro]
    end

    subgraph Pipeline[Data Pipeline · APScheduler]
        B1[Collector]
        B2[Feature<br/>Engineering]
        B3[FinBERT<br/>Inference]
    end

    subgraph Store[PostgreSQL]
        C1[(earnings_events)]
        C2[(price_features<br/>35 features)]
        C3[(predictions)]
        C4[(model_performance)]
    end

    subgraph Models[ML Training]
        D1[Walk-Forward<br/>Splits]
        D2[XGBoost +<br/>LightGBM +<br/>LogReg]
        D3[Quantile Forest<br/>Convergence Bands]
        D4[SHAP<br/>Explainer]
    end

    subgraph Serve[Serving Layer]
        E1[FastAPI<br/>/api/v1]
        E2[React<br/>Dashboard]
    end

    Sources --> Pipeline
    Pipeline --> Store
    Store --> Models
    Models --> Store
    Store --> E1
    E1 --> E2

    style Models fill:#141b2e,stroke:#38bdf8
    style Serve fill:#141b2e,stroke:#a78bfa
```

## 🧪 Feature engineering

The 35-feature payload is organized into six groups:

```mermaid
flowchart TD
    Target[Post-earnings<br/>T+5 close return] --> Features

    subgraph Features[35 features]
        F1[Price action<br/>10 features<br/>RSI, MACD, Bollinger,<br/>52w-distance, momentum]
        F2[Macro regime<br/>6 features<br/>VIX, SPY/QQQ returns,<br/>Fed rate, yield curve]
        F3[Historical reactions<br/>3 features<br/>8Q mean, std, beat-rate]
        F4[FinBERT news<br/>3 features<br/>sentiment, confidence,<br/>positive ratio]
        F5[FinBERT 10-Q MD&A<br/>5 features<br/>sentiment, risk intensity,<br/>forward-looking tone, length]
        F6[Interaction crosses<br/>7 features<br/>eps × vix, sentiment × beta,<br/>spy × relative strength...]
    end

    style F4 fill:#141b2e,stroke:#a78bfa
    style F5 fill:#141b2e,stroke:#a78bfa
```

**SEC 10-Q/10-K pipeline details:**
- 665/667 filings successfully parsed MD&A sections (99.7% success rate)
- FinBERT (`ProsusAI/finbert`) scores paragraphs individually, aggregated with length weighting
- Forward-looking segments are re-scored separately for the `forward_sentiment` feature
- Matched to earnings events by filing date ±15 days

## 📦 Stack

| Layer | Technology |
|---|---|
| **ML** | XGBoost, LightGBM, scikit-learn VotingClassifier, RandomForest quantile regression, SHAP TreeExplainer, FinBERT (ProsusAI) |
| **Backend** | FastAPI, SQLAlchemy 2.0, Pydantic v2, APScheduler, httpx |
| **Data** | PostgreSQL 16, Redis, yfinance, SEC EDGAR, FRED |
| **Frontend** | React 18, TypeScript, Vite, Recharts, Framer Motion, Lucide icons |
| **Infra** | Docker Compose (7 services), nginx reverse-proxy |

## 🚀 Getting started

### Prerequisites
- Docker Desktop
- API keys: [FinancialModelingPrep](https://financialmodelingprep.com/), [FRED](https://fred.stlouisfed.org/docs/api/api_key.html)

### Setup

```bash
# 1. clone and configure
git clone https://github.com/YOURNAME/alphasignal && cd alphasignal
cp .env.example .env
# edit .env with your API keys

# 2. build + run
docker compose up --build -d

# 3. open the dashboard
open http://localhost:5173
```

### First-time data bootstrap

```bash
# fetch calendars + prices (5 min)
docker compose exec scheduler python -m data_pipeline.bootstrap

# score FinBERT on news (30 min)
docker compose exec backend python -m scripts.score_news

# fetch + score SEC 10-Q/10-K filings (60 min)
docker compose exec backend python -m scripts.score_filings

# train the model
docker compose exec backend python -m models.train \
  --database-url "postgresql+psycopg://earnings:earnings@postgres:5432/earnings" \
  --model-dir /app/artifacts
```

## 📸 Screenshots

> Replace these with your own screenshots. Place them in `docs/images/`.

**Calendar — ML predictions across 120-day window**
![calendar](docs/images/calendar.png)

**Prediction Deep Dive — live quote, SHAP drivers, convergence zone**
![detail](docs/images/detail.png)

**Performance Tracker — sector heatmap, confusion matrix, SHAP importance**
![performance](docs/images/performance.png)

## 🗺️ Roadmap

- [ ] **Walk-forward backtest UI** — distinguish in-sample (training hits) vs out-of-sample (walk-forward) modes in the Backtest page
- [ ] **Expand universe** from 60 → 200 tickers for richer sector samples
- [ ] **SMOTE for Technology sector** — FLAT class is under-represented, dragging accuracy
- [ ] **Earnings call transcript NLP** — upgrade from 10-Q MD&A to real transcripts via FMP's paid tier
- [ ] **Live deployment** — Railway (backend) + Vercel (frontend)
- [ ] **Realistic trading simulation** — add slippage, commissions, position sizing

## ⚠️ Honest disclaimers

1. **Not investment advice.** This is a research / portfolio project. Past performance of any ML model does not guarantee future results, and the 52.7% general accuracy — while meaningfully above random — is far from a reliable trading edge after transaction costs and slippage.
2. **Training-set predictions look too good.** The in-sample Backtest page will show near-perfect accuracy because the model has seen those events. The Performance page shows the honest walk-forward numbers.
3. **NLP coverage is uneven.** FinBERT news features use yfinance's ~10 recent headlines per ticker (static, not per-event historical). 10-Q MD&A features only cover ~37% of the earnings events (recent 3 years, 60 tickers × ~12 filings each).

## 🙏 Credits

Built by [Justin Yu](https://github.com/YOURNAME) · Columbia MSAI '26

- **FinBERT** — [ProsusAI/finbert](https://huggingface.co/ProsusAI/finbert)
- **SEC EDGAR** data used under their fair-access policy with proper `User-Agent`
- Inspired by Bloomberg Terminal, Stripe Dashboard, and Linear design languages

---

<div align="center">
<em>If you found this project interesting, please ⭐ the repo.</em>
</div>
