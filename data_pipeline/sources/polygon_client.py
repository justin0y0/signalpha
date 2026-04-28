from __future__ import annotations

from typing import Any

from data_pipeline.sources.base_client import BaseAPIClient


class PolygonClient(BaseAPIClient):
    def __init__(self, api_key: str):
        super().__init__(base_url="https://api.polygon.io", min_interval_seconds=0.15)
        self.api_key = api_key

    def previous_close(self, ticker: str) -> dict[str, Any]:
        return self.get_json(f"v2/aggs/ticker/{ticker}/prev", params={"adjusted": "true", "apiKey": self.api_key})

    def historical_bars(self, ticker: str, multiplier: int, timespan: str, start: str, end: str) -> dict[str, Any]:
        return self.get_json(
            f"v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{start}/{end}",
            params={"adjusted": "true", "sort": "asc", "apiKey": self.api_key},
        )
