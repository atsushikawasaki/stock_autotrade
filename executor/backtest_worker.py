"""Backtest queue worker: picks up requests from Supabase and runs backtest."""

from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone

from supabase import create_client

from config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from backtest import backtest_stock, summarize_trades, save_results_to_supabase
from price_client import fetch_daily_prices
from market_filter import get_market_regime

log = logging.getLogger("backtest_worker")

sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def poll_and_run() -> bool:
    """
    Check for pending backtest requests and run the oldest one.
    Returns True if a request was processed, False if queue is empty.
    """
    # Fetch oldest pending request
    result = (
        sb.table("us_backtest_requests")
        .select("*")
        .eq("status", "pending")
        .order("created_at")
        .limit(1)
        .execute()
    )

    if not result.data:
        return False

    req = result.data[0]
    req_id = req["id"]
    params = req.get("params") or {}

    log.info("[BACKTEST] Processing request %s (params: %s)", req_id, params)

    # Mark as running
    sb.table("us_backtest_requests").update({
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", req_id).execute()

    try:
        output = _run_backtest(params)

        sb.table("us_backtest_requests").update({
            "status": "completed",
            "output": output,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", req_id).execute()

        log.info("[BACKTEST] Request %s completed", req_id)

    except Exception as e:
        error_msg = f"{e}\n{traceback.format_exc()}"
        sb.table("us_backtest_requests").update({
            "status": "failed",
            "error": error_msg[:5000],
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", req_id).execute()

        log.error("[BACKTEST] Request %s failed: %s", req_id, e)

    return True


def _run_backtest(params: dict) -> str:
    """Run backtest with given parameters. Returns summary text."""
    symbol = params.get("symbol")
    days = int(params.get("days", 365))

    market_regime = get_market_regime()
    lines: list[str] = [f"Market regime: {market_regime}", f"Lookback: {days} days", ""]

    # Get stock list
    if symbol:
        symbols = [symbol.upper()]
    else:
        data = (
            sb.table("us_stocks")
            .select("code")
            .eq("is_active", True)
            .order("code")
            .execute()
        )
        symbols = [row["code"] for row in (data.data or [])]

    lines.append(f"Backtesting {len(symbols)} stock(s)...\n")

    all_results = []
    all_trades = []

    for sym in symbols:
        try:
            prices = fetch_daily_prices(sym, days)
            if len(prices) < 80:
                continue

            trades = backtest_stock(sym, prices, market_regime)
            if not trades:
                continue

            lines.append(f"{sym} ({len(trades)} trades)")

            for strat in ("strategy_a", "strategy_b", "strategy_c"):
                strat_trades = [t for t in trades if t.strategy == strat]
                if strat_trades:
                    result = summarize_trades(sym, strat, strat_trades)
                    all_results.append(result)
                    label = strat.replace("strategy_", "").upper()
                    sharpe = f"{result.sharpe_ratio:.2f}" if result.sharpe_ratio is not None else "N/A"
                    lines.append(
                        f"  Strategy {label}: {result.total_trades} trades, "
                        f"Win: {result.win_rate}%, Avg: {result.avg_return_pct:+.2f}%, "
                        f"MDD: {result.max_drawdown_pct:.1f}%, Sharpe: {sharpe}"
                    )

            all_trades.extend(trades)
        except Exception as e:
            lines.append(f"  {sym}: ERROR {e}")

    # Overall summary
    if all_trades:
        lines.append("")
        lines.append("=" * 50)
        lines.append("OVERALL SUMMARY")
        lines.append("=" * 50)

        for strat in ("strategy_a", "strategy_b", "strategy_c"):
            strat_trades = [t for t in all_trades if t.strategy == strat]
            if strat_trades:
                result = summarize_trades("ALL", strat, strat_trades)
                label = strat.replace("strategy_", "").upper()
                sharpe = f"{result.sharpe_ratio:.2f}" if result.sharpe_ratio is not None else "N/A"
                lines.append(
                    f"  Strategy {label}: {result.total_trades} trades, "
                    f"Win: {result.win_rate}%, Avg: {result.avg_return_pct:+.2f}%, "
                    f"Sharpe: {sharpe}"
                )

        total_wins = sum(1 for t in all_trades if t.return_pct > 0)
        lines.append(
            f"\n  Total: {len(all_trades)} trades, "
            f"Win: {total_wins / len(all_trades) * 100:.1f}%, "
            f"Avg: {sum(t.return_pct for t in all_trades) / len(all_trades):+.2f}%"
        )
    else:
        lines.append("No trades found in backtest period.")

    # Save to Supabase
    if all_results:
        save_results_to_supabase(all_results)
        lines.append(f"\nSaved {len([r for r in all_results if r.total_trades > 0])} results to Supabase")

    return "\n".join(lines)
