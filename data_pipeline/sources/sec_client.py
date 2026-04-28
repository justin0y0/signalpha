from __future__ import annotations

from typing import Any

from data_pipeline.sources.base_client import BaseAPIClient


class SECClient(BaseAPIClient):
    def __init__(self, user_agent: str):
        super().__init__(
            base_url="https://data.sec.gov",
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate", "Host": "data.sec.gov"},
            min_interval_seconds=0.35,
        )
        self._ticker_map: dict[str, str] | None = None

    def company_tickers(self) -> dict[str, Any]:
        return self.get_json("files/company_tickers.json")

    def resolve_cik(self, ticker: str) -> str | None:
        if self._ticker_map is None:
            data = self.company_tickers()
            self._ticker_map = {
                str(item["ticker"]).upper(): str(item["cik_str"]).zfill(10)
                for item in data.values()
                if isinstance(item, dict) and item.get("ticker")
            }
        return self._ticker_map.get(ticker.upper())

    def company_facts(self, ticker: str) -> dict[str, Any]:
        cik = self.resolve_cik(ticker)
        if cik is None:
            raise ValueError(f"Unable to resolve CIK for ticker {ticker}")
        return self.get_json(f"api/xbrl/companyfacts/CIK{cik}.json")

    def submissions(self, ticker: str) -> dict[str, Any]:
        cik = self.resolve_cik(ticker)
        if cik is None:
            raise ValueError(f"Unable to resolve CIK for ticker {ticker}")
        return self.get_json(f"submissions/CIK{cik}.json")
