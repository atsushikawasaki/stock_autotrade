"""Price data fetcher via yfinance for US stocks.

Uses yfinance (free) for OHLCV and current price.
moomoo OpenAPI is used only for order execution.
"""

from __future__ import annotations

from dataclasses import dataclass

import yfinance as yf


@dataclass(frozen=True)
class PriceRow:
    date: str       # YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float
    volume: int


def _to_ticker(symbol: str) -> str:
    """Strip moomoo prefix if present: US.AAPL -> AAPL"""
    if symbol.startswith("US."):
        return symbol[3:]
    return symbol


def fetch_daily_prices(symbol: str, days: int = 120) -> list[PriceRow]:
    """Fetch daily OHLCV via yfinance."""
    ticker = _to_ticker(symbol)
    period = f"{max(days, 30)}d"

    try:
        df = yf.download(ticker, period=period, interval="1d", progress=False, auto_adjust=True)
        if df is None or df.empty:
            print(f"[WARN] No data for {symbol}")
            return []

        # yfinance may return MultiIndex columns for single ticker
        if hasattr(df.columns, "levels") and len(df.columns.levels) > 1:
            df = df.droplevel(level=1, axis=1)

        rows: list[PriceRow] = []
        for idx, row in df.iterrows():
            close = row.get("Close")
            if close is None or close != close:  # NaN check
                continue
            date_str = str(idx)[:10]
            rows.append(PriceRow(
                date=date_str,
                open=float(row.get("Open", close)),
                high=float(row.get("High", close)),
                low=float(row.get("Low", close)),
                close=float(close),
                volume=int(row.get("Volume", 0)),
            ))
        return rows

    except Exception as e:
        print(f"[WARN] yfinance error for {symbol}: {e}")
        return []


def fetch_current_price(symbol: str) -> float | None:
    """Get latest price for a US stock via yfinance."""
    ticker = _to_ticker(symbol)
    try:
        t = yf.Ticker(ticker)
        info = t.fast_info
        price = getattr(info, "last_price", None)
        if price is None:
            price = getattr(info, "previous_close", None)
        return float(price) if price is not None else None
    except Exception as e:
        print(f"[WARN] Quote failed for {symbol}: {e}")
        return None
