from __future__ import annotations

from pathlib import Path

from models.ensemble import ModelEnsemble


class ModelRegistry:
    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)

    @staticmethod
    def _slug(sector: str) -> str:
        return sector.lower().replace("/", "-").replace(" ", "-")

    def model_path(self, sector: str) -> Path:
        return self.base_dir / self._slug(sector) / "ensemble.joblib"

    def save_for_sector(self, sector: str, model: ModelEnsemble) -> Path:
        path = self.model_path(sector)
        model.save(path)
        return path

    def load_for_sector(self, sector: str) -> ModelEnsemble:
        preferred = self.model_path(sector)
        fallback = self.model_path("general")
        if preferred.exists():
            return ModelEnsemble.load(preferred)
        if fallback.exists():
            return ModelEnsemble.load(fallback)
        raise FileNotFoundError(f"No model artifacts found for sector {sector!r} and no general fallback exists.")
