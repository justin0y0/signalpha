"""One shared rule for which predictions may appear in a performance number.

Historical rows in `predictions` were backfilled after their outcomes were already
known, and `calibrate_predictions.py` then fit isotonic calibrators on those same
outcomes and wrote them back over the probabilities. Anything reporting accuracy,
hit rate, P&L or Sharpe from such a row is reporting in-sample fit as live skill --
which is how a 0.65-threshold backtest came to claim a 97.5% win rate from a model
whose honest walk-forward accuracy is 49.3%.

`data_pipeline/regenerate_predictions.py` rewrites what it can walk-forward and sets
`is_out_of_sample = TRUE`. Every performance surface must filter on that flag:

    from backend.app.services.prediction_filters import OUT_OF_SAMPLE_ONLY
    stmt = stmt.where(OUT_OF_SAMPLE_ONLY)

Surfaces currently covered: Backtest, Showdown, Track Record, and the Performance
page's confidence-tier block. The Performance page's headline cards, sector heatmap,
confusion matrix and SHAP chart read `model_performance` instead, which comes from
the purged walk-forward in `models/train.py` and was never contaminated.
"""
from __future__ import annotations

from backend.app.db.models import Prediction

# True only for rows produced by a model trained purely on data predating the event.
OUT_OF_SAMPLE_ONLY = Prediction.is_out_of_sample.is_(True)
