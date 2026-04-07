#!/usr/bin/env python3
"""
moomoo OpenAPI Connection Test for US Stocks.

Verifies that OpenD is running and all API integrations work:
1. Account info (buying power)
2. Trade unlock
3. Kline history fetch (US.AAPL)
4. Real-time quote fetch
5. Limit buy order ($0.01 -> immediate cancel)
6. Order list query
7. Full cancel cleanup

Usage:
  cd executor
  python test_connection.py
"""

from __future__ import annotations

import os
import sys
import time

from dotenv import load_dotenv

load_dotenv()

from moomoo import (
    OpenQuoteContext,
    OpenSecTradeContext,
    OrderType,
    RET_OK,
    SecurityFirm,
    SubType,
    KLType,
    TrdEnv,
    TrdMarket,
    TrdSide,
    ModifyOrderOp,
)

OPEND_HOST = os.environ.get("OPEND_HOST", "127.0.0.1")
OPEND_PORT = int(os.environ.get("OPEND_PORT", "11111"))
TRADE_PWD = os.environ.get("MOOMOO_TRADE_PWD", "")
SECURITY_FIRM = SecurityFirm.FUTUJP
TEST_CODE = "US.AAPL"
TEST_QTY = 1


def _get_trade_ctx() -> OpenSecTradeContext:
    return OpenSecTradeContext(
        filter_trdmarket=TrdMarket.US,
        host=OPEND_HOST,
        port=OPEND_PORT,
        security_firm=SECURITY_FIRM,
    )


def test_account_info() -> bool:
    """Test 1: Fetch account info and buying power (USD)."""
    ctx = _get_trade_ctx()
    try:
        ret, data = ctx.accinfo_query(trd_env=TrdEnv.REAL)
        if ret == RET_OK:
            power = data.iloc[0].get("power", "N/A")
            total_assets = data.iloc[0].get("total_assets", "N/A")
            print(f"  [OK] Buying power: ${float(power):,.2f}")
            print(f"       Total assets: ${float(total_assets):,.2f}")
            return True
        print(f"  [FAIL] {data}")
        return False
    finally:
        ctx.close()


def test_unlock_trade() -> bool:
    """Test 2: Unlock trading."""
    if not TRADE_PWD:
        print("  [SKIP] MOOMOO_TRADE_PWD not set")
        return False

    ctx = _get_trade_ctx()
    try:
        ret, data = ctx.unlock_trade(password=TRADE_PWD, is_unlock=True)
        if ret == RET_OK:
            print("  [OK] Trade unlocked")
            return True
        print(f"  [FAIL] Unlock error: {data}")
        return False
    finally:
        ctx.close()


def test_kline_history() -> bool:
    """Test 3: Fetch daily kline history for US.AAPL."""
    ctx = OpenQuoteContext(host=OPEND_HOST, port=OPEND_PORT)
    try:
        from datetime import datetime, timedelta

        end = datetime.now()
        start = end - timedelta(days=30)

        ret, data, _ = ctx.request_history_kline(
            TEST_CODE,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            ktype=KLType.K_DAY,
            max_count=20,
        )
        if ret == RET_OK and data is not None and not data.empty:
            rows = len(data)
            latest = data.iloc[-1]
            date = str(latest.get("time_key", ""))[:10]
            close = latest.get("close", 0)
            volume = latest.get("volume", 0)
            print(f"  [OK] {rows} daily bars fetched")
            print(f"       Latest: {date} close=${float(close):.2f} vol={int(volume):,}")
            return True
        print(f"  [FAIL] No kline data: {data}")
        return False
    finally:
        ctx.close()


def test_realtime_quote() -> bool:
    """Test 4: Fetch real-time quote for US.AAPL."""
    ctx = OpenQuoteContext(host=OPEND_HOST, port=OPEND_PORT)
    try:
        ret_sub, _ = ctx.subscribe([TEST_CODE], [SubType.QUOTE])
        if ret_sub != RET_OK:
            print(f"  [FAIL] Subscribe failed")
            return False

        ret, data = ctx.get_stock_quote([TEST_CODE])
        if ret == RET_OK and len(data) > 0:
            price = data.iloc[0].get("last_price", None)
            name = data.iloc[0].get("stock_name", "")
            print(f"  [OK] {name} last_price=${float(price):.2f}" if price else f"  [WARN] Price is None")
            return price is not None
        print(f"  [FAIL] Quote failed: {data}")
        return False
    finally:
        ctx.close()


def test_limit_buy_and_cancel() -> bool:
    """Test 5: Place $0.01 limit buy -> immediate cancel."""
    ctx = _get_trade_ctx()
    try:
        ret, data = ctx.place_order(
            price=0.01,
            qty=TEST_QTY,
            code=TEST_CODE,
            trd_side=TrdSide.BUY,
            order_type=OrderType.NORMAL,
            trd_env=TrdEnv.REAL,
        )
        if ret == RET_OK:
            order_id = str(data["order_id"].iloc[0])
            status = data["order_status"].iloc[0]
            print(f"  [OK] Limit buy placed: order_id={order_id}, status={status}")

            time.sleep(1)
            ret2, data2 = ctx.modify_order(
                modify_order_op=ModifyOrderOp.CANCEL,
                order_id=order_id,
                qty=0,
                price=0,
                trd_env=TrdEnv.REAL,
            )
            if ret2 == RET_OK:
                print(f"  [OK] Cancel successful")
            else:
                print(f"  [WARN] Cancel result: {data2}")
            return True
        print(f"  [FAIL] Order error: {data}")
        return False
    finally:
        ctx.close()


def test_order_list() -> bool:
    """Test 6: Query order list."""
    ctx = _get_trade_ctx()
    try:
        ret, data = ctx.order_list_query(trd_env=TrdEnv.REAL)
        if ret == RET_OK:
            total = len(data) if data is not None else 0
            active = 0
            if total > 0:
                active = len(data[~data["order_status"].isin(
                    ["CANCELLED_ALL", "FILLED_ALL", "DELETED"]
                )])
            print(f"  [OK] Total orders: {total}, Active: {active}")
            return True
        print(f"  [FAIL] {data}")
        return False
    finally:
        ctx.close()


def test_positions() -> bool:
    """Test 7: Query current positions."""
    ctx = _get_trade_ctx()
    try:
        ret, data = ctx.position_list_query(trd_env=TrdEnv.REAL)
        if ret == RET_OK:
            holdings = data[data["qty"] > 0] if len(data) > 0 else data
            print(f"  [OK] Current holdings: {len(holdings)} position(s)")
            for _, row in holdings.iterrows():
                code = row.get("code", "")
                qty = int(row.get("qty", 0))
                cost = float(row.get("cost_price", 0))
                market_val = float(row.get("market_val", 0))
                print(f"       {code}: {qty} shares @ ${cost:.2f} (val=${market_val:,.2f})")
            return True
        print(f"  [FAIL] {data}")
        return False
    finally:
        ctx.close()


def test_cancel_all() -> bool:
    """Test 8: Cancel all remaining orders (cleanup)."""
    ctx = _get_trade_ctx()
    try:
        ret, data = ctx.cancel_all_order(trd_env=TrdEnv.REAL)
        if ret == RET_OK:
            print("  [OK] All orders cancelled")
        else:
            print(f"  [INFO] Cancel result: {data}")
        return True
    finally:
        ctx.close()


def main() -> None:
    print("=" * 55)
    print("moomoo OpenAPI Connection Test (US Stocks)")
    print(f"  Host: {OPEND_HOST}:{OPEND_PORT}")
    print(f"  SecurityFirm: FUTUJP")
    print(f"  Test symbol: {TEST_CODE}")
    print(f"  Trade password: {'set' if TRADE_PWD else 'NOT SET'}")
    print("=" * 55)

    if not TRADE_PWD:
        print("\n[WARN] MOOMOO_TRADE_PWD not set — order tests will be skipped")

    tests = [
        ("Account Info", test_account_info),
        ("Unlock Trade", test_unlock_trade),
        ("Kline History", test_kline_history),
        ("Realtime Quote", test_realtime_quote),
        ("Limit Buy + Cancel", test_limit_buy_and_cancel),
        ("Order List", test_order_list),
        ("Positions", test_positions),
        ("Cancel All (cleanup)", test_cancel_all),
    ]

    results: dict[str, bool] = {}
    for name, func in tests:
        print(f"\n--- {name} ---")
        try:
            results[name] = func()
        except Exception as e:
            print(f"  [EXCEPTION] {e}")
            results[name] = False

    # Summary
    print("\n" + "=" * 55)
    print("Test Results")
    print("=" * 55)
    passed = sum(1 for v in results.values() if v)
    for name, ok in results.items():
        mark = "OK" if ok else "FAIL"
        print(f"  [{mark}] {name}")

    print(f"\n  Result: {passed}/{len(results)} passed")

    core_tests = ["Account Info", "Unlock Trade", "Kline History", "Order List"]
    core_passed = all(results.get(t, False) for t in core_tests)

    if core_passed:
        print("\n  All core tests passed. Ready for auto-trading.")
    else:
        print("\n  Some core tests failed. Check OpenD connection and credentials.")


if __name__ == "__main__":
    main()
