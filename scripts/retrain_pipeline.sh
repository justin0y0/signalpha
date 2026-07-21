#!/usr/bin/env bash
# Full retrain -> regenerate -> recalibrate, in a ONE-OFF container.
#
# Never docker exec this into signalpha-backend-1: that container serves the API and
# runs the Oracle worker in the same process, and this pipeline pegged it at 113% CPU.
# `compose run --rm` builds a throwaway container from the same image with the same
# artifacts/ and data/ mounts, so training writes real model files without competing
# with anything a visitor is waiting on.
set -euo pipefail
cd ~/signalpha
sudo docker compose run --rm --no-deps -T backend sh -c '
  set -e
  echo "[1/3] retrain_models — walk-forward per sector, writes model_performance"
  python3 -c "
import warnings; warnings.filterwarnings\"ignore\" if False else warnings.filterwarnings(\"ignore\")
from data_pipeline.jobs import retrain_models
retrain_models()
print(\"[1/3] done\", flush=True)"
  echo "[2/3] regenerate_predictions — walk-forward historical predictions"
  python3 -m data_pipeline.regenerate_predictions
  echo "[3/3] recalibrate_predictions — expanding-window isotonic"
  python3 -m data_pipeline.recalibrate_predictions
  echo "PIPELINE COMPLETE"
'
