"""Yahoo Finance price data fetcher for US stocks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import yfinance as yf


@dataclass(frozen=True)
class PriceRow:
    date: str       # YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float
    volume: int


def fetch_daily_prices(symbol: str, days: int = 120) -> list[PriceRow]:
    """Fetch daily OHLCV from Yahoo Finance."""
    end = datetime.now()
    start = end - timedelta(days=int(days * 1.5))  # buffer for weekends

    ticker = yf.Ticker(symbol)
    df = ticker.history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))

    if df.empty:
        return []

    rows: list[PriceRow] = []
    for idx, row in df.iterrows():
        close = row.get("Close")
        if close is None or close != close:  # NaN check
            continue
        rows.append(PriceRow(
            date=idx.strftime("%Y-%m-%d"),  # type: ignore[union-attr]
            open=float(row.get("Open", close)),
            high=float(row.get("High", close)),
            low=float(row.get("Low", close)),
            close=float(close),
            volume=int(row.get("Volume", 0)),
        ))

    return rows
