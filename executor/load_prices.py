#!/usr/bin/env python3
"""
Load 2 years of daily OHLCV from moomoo OpenD into Supabase us_daily_prices.

Usage:
  cd executor
  python load_prices.py                  # all active us_stocks
  python load_prices.py --symbol AAPL    # single stock
  python load_prices.py --days 730       # custom lookback (default: 2 years)
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

from moomoo import OpenQuoteContext, RET_OK, KLType

from config import OPEND_HOST, OPEND_PORT, SUPABASE_URL, SUPABASE_SERVICE_KEY
from supabase import create_client

log = logging.getLogger("load_prices")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

BATCH_SIZE = 500  # upsert batch size
DEFAULT_DAYS = 730  # 2 years


def _to_moomoo_code(symbol: str) -> str:
    if symbol.startswith("US."):
        return symbol
    return f"US.{symbol}"


def _fetch_all_klines(
    ctx: OpenQuoteContext, code: str, start: str, end: str,
) -> list[dict]:
    """Fetch all daily klines with pagination."""
    all_rows: list[dict] = []
    page_key = None

    while True:
        ret, data, page_key = ctx.request_history_kline(
            code, start=start, end=end,
            ktype=KLType.K_DAY, max_count=1000,
            page_req_key=page_key,
        )
        if ret != RET_OK:
            log.warning("kline fetch failed for %s: %s", code, data)
            break

        for _, row in data.iterrows():
            close_val = row.get("close")
            if close_val is None or close_val != close_val:
                continue
            all_rows.append({
                "stock_code": code.replace("US.", ""),
                "trade_date": str(row.get("time_key", ""))[:10],
                "open": float(row.get("open", close_val)),
                "high": float(row.get("high", close_val)),
                "low": float(row.get("low", close_val)),
                "close": float(close_val),
                "volume": int(row.get("volume", 0)),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            })

        if page_key is None:
            break

    return all_rows


def _upsert_batch(sb, rows: list[dict]) -> int:
    """Upsert rows into us_daily_prices. Returns count of upserted rows."""
    if not rows:
        return 0

    # Process in batches
    total = 0
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        sb.table("us_daily_prices").upsert(
            batch, on_conflict="stock_code,trade_date",
        ).execute()
        total += len(batch)

    return total


def load_stock_prices(
    ctx: OpenQuoteContext, sb, symbol: str, days: int,
) -> int:
    """Load prices for one stock. Returns row count."""
    code = _to_moomoo_code(symbol)
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    rows = _fetch_all_klines(ctx, code, start, end)
    if not rows:
        log.info("  %s: no data from moomoo", symbol)
        return 0

    count = _upsert_batch(sb, rows)
    log.info("  %s: %d rows upserted (%s ~ %s)", symbol, count, rows[0]["trade_date"], rows[-1]["trade_date"])
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Load US stock prices into Supabase")
    parser.add_argument("--symbol", type=str, help="Single stock symbol (e.g. AAPL)")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help=f"Lookback days (default: {DEFAULT_DAYS})")
    args = parser.parse_args()

    sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

    # Get stock list
    if args.symbol:
        symbols = [args.symbol.upper()]
    else:
        data = (
            sb.table("us_stocks")
            .select("code")
            .eq("is_active", True)
            .order("code")
            .execute()
        )
        symbols = [row["code"] for row in (data.data or [])]

    log.info("Loading %d stock(s), %d days lookback", len(symbols), args.days)

    ctx = OpenQuoteContext(host=OPEND_HOST, port=OPEND_PORT)
    total_rows = 0

    try:
        for i, sym in enumerate(symbols, 1):
            try:
                count = load_stock_prices(ctx, sb, sym, args.days)
                total_rows += count
            except Exception as e:
                log.error("  %s: ERROR %s", sym, e)

            # Rate limit: moomoo OpenD has request frequency limits
            if i < len(symbols):
                time.sleep(0.5)

    finally:
        ctx.close()

    log.info("Done. Total: %d rows for %d stocks", total_rows, len(symbols))


if __name__ == "__main__":
    main()
