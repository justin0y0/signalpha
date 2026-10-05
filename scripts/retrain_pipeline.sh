#!/usr/bin/env bash
# Full retrain -> regenerate -> recalibrate, in a ONE-OFF container.
#
# Never docker exec this into signalpha-backend-1: that container serves the API and
# runs the Oracle worker in the same process, and this pipeline pegged it at 113% CPU
# while the site was live. `compose run --rm` builds a throwaway container from the
# same image with the same artifacts/ and data/ mounts, so training writes real model
# files without competing with anything a visitor is waiting on.
set -euo pipefail
cd ~/signalpha
docker compose run --rm --no-deps -T backend python3 - <<'PYEOF'
import warnings
warnings.filterwarnings("ignore")
import subprocess, sys

print("[1/4] retrain_models — walk-forward per sector, writes model_performance", flush=True)
from data_pipeline.jobs import retrain_models
retrain_models()
print("[1/4] done", flush=True)

print("[2/4] regenerate_predictions", flush=True)
from data_pipeline.regenerate_predictions import regenerate
print(regenerate(), flush=True)

print("[3/4] move_model — pooled breakout model, writes prob_move + move_metrics.json", flush=True)
from data_pipeline.move_model import run as run_move_model
m = run_move_model()
print({"auc": m.get("auc"), "top_decile": m.get("top_decile"), "written": m.get("written")}, flush=True)

print("[4/4] recalibrate_predictions", flush=True)
from data_pipeline.recalibrate_predictions import recalibrate
print(recalibrate(), flush=True)

print("PIPELINE COMPLETE", flush=True)
PYEOF
