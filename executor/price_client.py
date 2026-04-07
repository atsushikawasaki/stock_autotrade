"""Price data fetcher via moomoo OpenAPI for US stocks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from moomoo import OpenQuoteContext, SubType, KLType, RET_OK

from config import OPEND_HOST, OPEND_PORT, MOOMOO_SYMBOL_PREFIX


@dataclass(frozen=True)
class PriceRow:
    date: str       # YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float
    volume: int


def _to_code(symbol: str) -> str:
    if symbol.startswith(MOOMOO_SYMBOL_PREFIX):
        return symbol
    return f"{MOOMOO_SYMBOL_PREFIX}{symbol}"


def fetch_daily_prices(symbol: str, days: int = 120) -> list[PriceRow]:
    """Fetch daily OHLCV via moomoo OpenAPI (K-line history)."""
    code = _to_code(symbol)
    end = datetime.now()
    start = end - timedelta(days=int(days * 1.5))

    ctx = OpenQuoteContext(host=OPEND_HOST, port=OPEND_PORT)
    try:
        ret, data, _ = ctx.request_history_kline(
            code,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            ktype=KLType.K_DAY,
            max_count=days,
        )

        if ret != RET_OK or data is None or data.empty:
            print(f"[WARN] No kline data for {symbol}: {data}")
            return []

        rows: list[PriceRow] = []
        for _, row in data.iterrows():
            close = row.get("close")
            if close is None or close != close:
                continue
            # time_key format: "YYYY-MM-DD HH:MM:SS"
            date_str = str(row.get("time_key", ""))[:10]
            rows.append(PriceRow(
                date=date_str,
                open=float(row.get("open", close)),
                high=float(row.get("high", close)),
                low=float(row.get("low", close)),
                close=float(close),
                volume=int(row.get("volume", 0)),
            ))

        return rows
    finally:
        ctx.close()


def fetch_current_price(symbol: str) -> float | None:
    """Get latest price for a US stock via moomoo quote API."""
    code = _to_code(symbol)
    ctx = OpenQuoteContext(host=OPEND_HOST, port=OPEND_PORT)
    try:
        ret_sub, _ = ctx.subscribe([code], [SubType.QUOTE])
        if ret_sub != RET_OK:
            print(f"[WARN] Subscribe failed for {code}")
            return None

        ret, data = ctx.get_stock_quote([code])
        if ret == RET_OK and len(data) > 0:
            price = data.iloc[0].get("last_price", None)
            return float(price) if price is not None else None
        return None
    except Exception as e:
        print(f"[WARN] Quote failed for {symbol}: {e}")
        return None
    finally:
        ctx.close()
