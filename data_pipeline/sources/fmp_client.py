from __future__ import annotations

from typing import Any

from data_pipeline.sources.base_client import BaseAPIClient


class FMPClient(BaseAPIClient):
    def __init__(self, api_key: str):
        super().__init__(base_url="https://financialmodelingprep.com/stable", min_interval_seconds=0.25)
        self.api_key = api_key

    def _params(self, **kwargs: Any) -> dict[str, Any]:
        return {"apikey": self.api_key, **kwargs}

    def earnings_calendar(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        params = self._params(to=end_date)
        params['from'] = start_date
        return self.get_json("earnings-calendar", params=params)

    def earnings_report(self, ticker: str, limit: int = 8) -> list[dict[str, Any]]:
        # /stable renamed this from "earnings-company"; the old path 404s.
        return self.get_json("earnings", params=self._params(symbol=ticker, limit=limit))

    def profile(self, ticker: str) -> list[dict[str, Any]]:
        """Company profile — the only /stable source for sector/industry/name/marketCap.

        /stable/earnings-calendar returns just symbol+date+eps/revenue estimates, so the
        calendar job has to enrich from here or `sector` stays NULL (and `sector` is what
        selects the per-sector model in run_predictions).
        """
        return self.get_json("profile", params=self._params(symbol=ticker))

    def income_statement(self, ticker: str, period: str = "quarter", limit: int = 8) -> list[dict[str, Any]]:
        return self.get_json("income-statement", params=self._params(symbol=ticker, period=period, limit=limit))

    def balance_sheet_statement(self, ticker: str, period: str = "quarter", limit: int = 8) -> list[dict[str, Any]]:
        return self.get_json("balance-sheet-statement", params=self._params(symbol=ticker, period=period, limit=limit))

    def cash_flow_statement(self, ticker: str, period: str = "quarter", limit: int = 8) -> list[dict[str, Any]]:
        return self.get_json("cash-flow-statement", params=self._params(symbol=ticker, period=period, limit=limit))

    # NOTE: financial_estimates and search_transcripts are gated behind a paid FMP plan on
    # /stable (402/404 with the current key). Callers wrap them in try/except and degrade to
    # {}, so forward guidance and transcript sentiment stay NULL until the plan is upgraded.
    def financial_estimates(self, ticker: str) -> list[dict[str, Any]]:
        return self.get_json("analyst-estimates", params=self._params(symbol=ticker))

    def price_target_summary(self, ticker: str) -> list[dict[str, Any]]:
        return self.get_json("price-target-summary", params=self._params(symbol=ticker))

    def search_transcripts(self, ticker: str) -> list[dict[str, Any]]:
        return self.get_json("search-transcripts", params=self._params(symbol=ticker))
