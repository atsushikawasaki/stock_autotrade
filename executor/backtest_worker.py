"""Backtest queue worker: picks up requests from Supabase and runs backtest."""

from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone

from supabase import create_client

from config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from backtest import backtest_stock, summarize_trades, save_results_to_supabase
from price_client import fetch_daily_prices, fetch_daily_prices_cached
from market_filter import get_market_regime

log = logging.getLogger("backtest_worker")

sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def poll_and_run() -> bool:
    """
    Check for pending backtest requests and run the oldest one.
    Returns True if a request was processed, False if queue is empty.

    Uses atomic claim: UPDATE ... WHERE status='pending' to prevent
    duplicate processing by concurrent workers.
    """
    # Fetch oldest pending request
    result = (
        sb.table("us_backtest_requests")
        .select("id")
        .eq("status", "pending")
        .order("created_at")
        .limit(1)
        .execute()
    )

    if not result.data:
        return False

    req_id = result.data[0]["id"]

    # Atomic claim: only update if still pending (prevents race conditions)
    claim = (
        sb.table("us_backtest_requests")
        .update({
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", req_id)
        .eq("status", "pending")  # optimistic lock
        .select("*")
        .execute()
    )

    if not claim.data:
        log.info("[BACKTEST] Request %s already claimed by another worker", req_id)
        return False

    req = claim.data[0]
    params = req.get("params") or {}

    log.info("[BACKTEST] Processing request %s (params: %s)", req_id, params)

    try:
        mode = params.get("mode", "backtest")
        if mode == "walk_forward":
            output = _run_walk_forward(params)
        elif mode == "optimize":
            output = _run_optimization(params)
        else:
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
    days = int(params.get("days", 730))

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
            prices = fetch_daily_prices_cached(sym, days)
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


def _run_walk_forward(params: dict) -> str:
    """Run walk-forward optimization. Returns summary text."""
    from optimizer import run_walk_forward

    max_combos = int(params.get("max_combos", 50))
    days = int(params.get("days", 730))
    sample_stocks = int(params.get("sample_stocks", 20))
    train_days = int(params.get("train_days", 250))
    test_days = int(params.get("test_days", 125))
    step_days = int(params.get("step_days", 125))

    wf = run_walk_forward(
        sample_stocks=sample_stocks,
        days=days,
        max_combos=max_combos,
        train_days=train_days,
        test_days=test_days,
        step_days=step_days,
    )

    if wf is None:
        return "Walk-forward optimization produced no results (insufficient data)"

    p = wf.best_params
    lines = [
        "Walk-Forward Optimization Results",
        "=" * 50,
        "",
        f"Windows: {len(wf.windows)}",
        f"OOS trades: {wf.oos_total_trades}",
        f"OOS win rate: {wf.oos_win_rate:.1f}%",
        f"OOS avg return: {wf.oos_avg_return:+.2f}%",
        f"OOS Sharpe: {f'{wf.oos_sharpe:.2f}' if wf.oos_sharpe else 'N/A'}",
        f"Robustness: {wf.robustness_score:.2f}",
        "",
        "Per-window breakdown:",
    ]

    for w in wf.windows:
        lines.append(
            f"  Window {w.window_id}: "
            f"train({w.train_result.avg_return:+.2f}% "
            f"sharpe={f'{w.train_result.sharpe:.2f}' if w.train_result.sharpe else 'N/A'}) -> "
            f"test({w.test_result.avg_return:+.2f}% "
            f"sharpe={f'{w.test_result.sharpe:.2f}' if w.test_result.sharpe else 'N/A'})"
        )
        lines.append(
            f"    params: lookback={w.train_params.breakout_lookback} "
            f"rsi={w.train_params.rsi_min}-{w.train_params.rsi_max} "
            f"vol={w.train_params.volume_ratio_min} "
            f"sl={w.train_params.sl_atr_mult} tp={w.train_params.tp_atr_mult} "
            f"adx={w.train_params.adx_min}"
        )

    lines.append("")
    lines.append(
        f"Best params: lookback={p.breakout_lookback} "
        f"rsi={p.rsi_min}-{p.rsi_max} vol={p.volume_ratio_min} "
        f"sl={p.sl_atr_mult} tp={p.tp_atr_mult} adx={p.adx_min}"
    )

    return "\n".join(lines)


def _run_optimization(params: dict) -> str:
    """Run parameter optimization. Returns summary text."""
    from optimizer import run_optimization

    max_combos = int(params.get("max_combos", 50))
    days = int(params.get("days", 365))
    sample_stocks = int(params.get("sample_stocks", 20))

    results = run_optimization(
        sample_stocks=sample_stocks,
        days=days,
        max_combos=max_combos,
    )

    if not results:
        return "No optimization results (no data)"

    lines = ["Parameter Optimization Results", "=" * 50, ""]
    for i, r in enumerate(results[:10], 1):
        lines.append(
            f"#{i} score={r.score:.2f} | trades={r.total_trades} "
            f"win={r.win_rate:.1f}% avg={r.avg_return:+.2f}% "
            f"sharpe={f'{r.sharpe:.2f}' if r.sharpe else 'N/A'}"
        )
        lines.append(
            f"   lookback={r.params.breakout_lookback} rsi={r.params.rsi_min}-{r.params.rsi_max} "
            f"vol={r.params.volume_ratio_min} sl={r.params.sl_atr_mult} tp={r.params.tp_atr_mult} "
            f"adx={r.params.adx_min}"
        )

    best = results[0]
    lines.append("")
    lines.append(f"Best params saved to us_optimization_results (top 10)")
    lines.append(f"Recommended: lookback={best.params.breakout_lookback} "
                 f"rsi={best.params.rsi_min}-{best.params.rsi_max} "
                 f"vol={best.params.volume_ratio_min} sl={best.params.sl_atr_mult} "
                 f"tp={best.params.tp_atr_mult} adx={best.params.adx_min}")

    return "\n".join(lines)
