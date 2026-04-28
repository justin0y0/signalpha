from __future__ import annotations

from typing import Any

from data_pipeline.sources.base_client import BaseAPIClient


class FREDClient(BaseAPIClient):
    def __init__(self, api_key: str):
        super().__init__(base_url="https://api.stlouisfed.org/fred", min_interval_seconds=0.25)
        self.api_key = api_key

    def series_observations(self, series_id: str, **params: Any) -> list[dict[str, Any]]:
        payload = {"series_id": series_id, "api_key": self.api_key, "file_type": "json", **params}
        data = self.get_json("series/observations", params=payload)
        return data.get("observations", [])
