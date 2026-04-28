from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib


class ArtifactLoader:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir

    def load(self, relative_path: str | Path) -> Any:
        artifact_path = self.base_dir / relative_path
        if not artifact_path.exists():
            raise FileNotFoundError(f"Artifact not found: {artifact_path}")
        return joblib.load(artifact_path)
