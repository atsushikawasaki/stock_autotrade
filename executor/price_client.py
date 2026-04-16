"""Price data fetcher for US stocks.

Primary: moomoo OpenD (real-time, LV2).
Fallback: yfinance (free, delayed) when OpenD is unavailable.
Backtest: Supabase us_daily_prices cache (pre-loaded via load_prices.py).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from moomoo import OpenQuoteContext, RET_OK, KLType

from config import OPEND_HOST, OPEND_PORT

log = logging.getLogger("price_client")


@dataclass(frozen=True)
class PriceRow:
    date: str       # YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float
    volume: int


def _to_moomoo_code(symbol: str) -> str:
    """Ensure moomoo format: AAPL -> US.AAPL"""
    if symbol.startswith("US."):
        return symbol
    return f"US.{symbol}"


def _to_ticker(symbol: str) -> str:
    """Strip moomoo prefix if present: US.AAPL -> AAPL"""
    if symbol.startswith("US."):
        return symbol[3:]
    return symbol


def _moomoo_fetch_daily(symbol: str, days: int) -> list[PriceRow] | None:
    """Fetch daily OHLCV via moomoo OpenD. Returns None on failure."""
    code = _to_moomoo_code(symbol)
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    ctx: OpenQuoteContext | None = None
    try:
        ctx = OpenQuoteContext(host=OPEND_HOST, port=OPEND_PORT)
        ret, data, _ = ctx.request_history_kline(
            code, start=start, end=end, ktype=KLType.K_DAY, max_count=1000,
        )
        if ret != RET_OK:
            log.warning("moomoo history_kline failed for %s: %s", symbol, data)
            return None

        rows: list[PriceRow] = []
        for _, row in data.iterrows():
            close_val = row.get("close")
            if close_val is None or close_val != close_val:
                continue
            date_str = str(row.get("time_key", ""))[:10]
            rows.append(PriceRow(
                date=date_str,
                open=float(row.get("open", close_val)),
                high=float(row.get("high", close_val)),
                low=float(row.get("low", close_val)),
                close=float(close_val),
                volume=int(row.get("volume", 0)),
            ))
        return rows
    except Exception as e:
        log.warning("moomoo OpenD error for %s: %s", symbol, e)
        return None
    finally:
        if ctx is not None:
            try:
                ctx.close()
            except Exception:
                pass


def _moomoo_fetch_current(symbol: str) -> float | None:
    """Fetch current price via moomoo OpenD snapshot. Returns None on failure."""
    code = _to_moomoo_code(symbol)

    ctx: OpenQuoteContext | None = None
    try:
        ctx = OpenQuoteContext(host=OPEND_HOST, port=OPEND_PORT)
        ret, data = ctx.get_market_snapshot([code])
        if ret != RET_OK:
            log.warning("moomoo snapshot failed for %s: %s", symbol, data)
            return None

        price = data.iloc[0].get("last_price")
        return float(price) if price is not None and price == price else None
    except Exception as e:
        log.warning("moomoo OpenD quote error for %s: %s", symbol, e)
        return None
    finally:
        if ctx is not None:
            try:
                ctx.close()
            except Exception:
                pass


def _yfinance_fetch_daily(symbol: str, days: int) -> list[PriceRow]:
    """Fallback: fetch daily OHLCV via yfinance."""
    import yfinance as yf

    ticker = _to_ticker(symbol)
    period = f"{max(days, 30)}d"
    try:
        df = yf.download(ticker, period=period, interval="1d", progress=False, auto_adjust=True)
        if df is None or df.empty:
            return []

        if hasattr(df.columns, "levels") and len(df.columns.levels) > 1:
            df = df.droplevel(level=1, axis=1)

        rows: list[PriceRow] = []
        for idx, row in df.iterrows():
            close_val = row.get("Close")
            if close_val is None or close_val != close_val:
                continue
            date_str = str(idx)[:10]
            rows.append(PriceRow(
                date=date_str,
                open=float(row.get("Open", close_val)),
                high=float(row.get("High", close_val)),
                low=float(row.get("Low", close_val)),
                close=float(close_val),
                volume=int(row.get("Volume", 0)),
            ))
        return rows
    except Exception as e:
        log.warning("yfinance error for %s: %s", symbol, e)
        return []


def _yfinance_fetch_current(symbol: str) -> float | None:
    """Fallback: get latest price via yfinance."""
    import yfinance as yf

    ticker = _to_ticker(symbol)
    try:
        t = yf.Ticker(ticker)
        info = t.fast_info
        price = getattr(info, "last_price", None)
        if price is None:
            price = getattr(info, "previous_close", None)
        return float(price) if price is not None else None
    except Exception as e:
        log.warning("yfinance quote failed for %s: %s", symbol, e)
        return None


# ─── Supabase Cache ──────────────────────────────────────────────────────────


def _supabase_fetch_daily(symbol: str, days: int) -> list[PriceRow] | None:
    """Read cached daily prices from Supabase us_daily_prices. Returns None if unavailable."""
    try:
        from config import SUPABASE_URL, SUPABASE_SERVICE_KEY
        from supabase import create_client

        ticker = _to_ticker(symbol)
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        result = (
            sb.table("us_daily_prices")
            .select("trade_date,open,high,low,close,volume")
            .eq("stock_code", ticker)
            .gte("trade_date", since)
            .order("trade_date")
            .execute()
        )

        if not result.data:
            return None

        rows: list[PriceRow] = []
        for r in result.data:
            rows.append(PriceRow(
                date=str(r["trade_date"]),
                open=float(r["open"]),
                high=float(r["high"]),
                low=float(r["low"]),
                close=float(r["close"]),
                volume=int(r["volume"]),
            ))
        return rows if rows else None
    except Exception as e:
        log.warning("Supabase fetch failed for %s: %s", symbol, e)
        return None


# ─── Public API ──────────────────────────────────────────────────────────────


def fetch_daily_prices(symbol: str, days: int = 120) -> list[PriceRow]:
    """Fetch daily OHLCV. Primary: moomoo OpenD, fallback: yfinance."""
    rows = _moomoo_fetch_daily(symbol, days)
    if rows is not None and len(rows) > 0:
        return rows

    log.info("Falling back to yfinance for %s daily prices", symbol)
    return _yfinance_fetch_daily(symbol, days)


def fetch_daily_prices_cached(symbol: str, days: int = 730) -> list[PriceRow]:
    """Fetch daily OHLCV for backtest. Supabase cache -> moomoo -> yfinance."""
    rows = _supabase_fetch_daily(symbol, days)
    if rows is not None and len(rows) > 0:
        log.debug("Supabase cache hit for %s: %d rows", symbol, len(rows))
        return rows

    log.info("Cache miss for %s, fetching from moomoo", symbol)
    return fetch_daily_prices(symbol, days)


def fetch_current_price(symbol: str) -> float | None:
    """Get latest price. Primary: moomoo OpenD, fallback: yfinance."""
    price = _moomoo_fetch_current(symbol)
    if price is not None:
        return price

    log.info("Falling back to yfinance for %s current price", symbol)
    return _yfinance_fetch_current(symbol)
