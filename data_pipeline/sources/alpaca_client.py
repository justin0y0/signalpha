from __future__ import annotations

from typing import Any

from data_pipeline.sources.base_client import BaseAPIClient


class AlpacaClient(BaseAPIClient):
    def __init__(self, api_key: str, secret_key: str):
        super().__init__(
            base_url="https://data.alpaca.markets",
            headers={"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret_key},
            min_interval_seconds=0.15,
        )

    def bars(self, symbols: str, timeframe: str, start: str, end: str) -> dict[str, Any]:
        return self.get_json("v2/stocks/bars", params={"symbols": symbols, "timeframe": timeframe, "start": start, "end": end})

    def options_chain(self, underlying_symbol: str, expiration_date: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"underlying_symbols": underlying_symbol}
        if expiration_date:
            params["expiration_date"] = expiration_date
        return self.get_json("v1beta1/options/snapshots", params=params)
