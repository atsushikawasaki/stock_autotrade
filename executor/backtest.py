#!/usr/bin/env python3
"""
Backtest engine for Strategy A/B/C.

Fetches historical kline data via moomoo, simulates trades,
and reports performance metrics (win rate, P&L ratio, MDD, Sharpe).

Usage:
  cd executor
  python backtest.py                    # all active stocks, 1 year
  python backtest.py --symbol AAPL      # single stock
  python backtest.py --days 500         # custom lookback
  python backtest.py --save             # save results to Supabase
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

from price_client import PriceRow, fetch_daily_prices
from strategies import evaluate_all_strategies
from market_filter import get_market_regime
from constants import (
    MAX_HOLDING_DAYS_A, MAX_HOLDING_DAYS_B, MAX_HOLDING_DAYS_C,
)


@dataclass(frozen=True)
class Trade:
    stock_code: str
    strategy: str
    grade: str
    score: int
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    exit_reason: str
    stop_loss: float | None
    take_profit: float | None
    holding_days: int
    return_pct: float
    pnl: float


@dataclass(frozen=True)
class BacktestResult:
    stock_code: str
    strategy: str
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    avg_return_pct: float
    total_pnl: float
    max_drawdown_pct: float
    sharpe_ratio: float | None
    avg_holding_days: float
    trades: list[Trade]


def _max_holding_days(strategy: str) -> int:
    if strategy == "strategy_b":
        return MAX_HOLDING_DAYS_B
    if strategy == "strategy_c":
        return MAX_HOLDING_DAYS_C
    return MAX_HOLDING_DAYS_A


def _simulate_trade(
    signal_idx: int,
    prices: list[PriceRow],
    strategy: str,
    stop_loss: float | None,
    take_profit: float | None,
) -> tuple[int, str, float]:
    """Simulate forward from signal day. Returns (exit_idx, exit_reason, exit_price)."""
    entry_price = prices[signal_idx].close
    max_days = _max_holding_days(strategy)

    for offset in range(1, max_days + 1):
        idx = signal_idx + offset
        if idx >= len(prices):
            return len(prices) - 1, "end_of_data", prices[-1].close

        bar = prices[idx]

        # Check SL hit (intraday low)
        if stop_loss is not None and bar.low <= stop_loss:
            return idx, "stop_loss", stop_loss

        # Check TP hit (intraday high)
        if take_profit is not None and bar.high >= take_profit:
            return idx, "take_profit", take_profit

    # Time expiry
    exit_idx = min(signal_idx + max_days, len(prices) - 1)
    return exit_idx, "time_expiry", prices[exit_idx].close


def _calc_sharpe(returns: list[float], annual_factor: float = 252) -> float | None:
    """Annualized Sharpe ratio (assuming 0 risk-free rate)."""
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(var) if var > 0 else 0
    if std == 0:
        return None
    return (mean / std) * math.sqrt(annual_factor)


def _calc_max_drawdown(equity_curve: list[float]) -> float:
    """Max drawdown as a percentage."""
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for val in equity_curve:
        if val > peak:
            peak = val
        dd = (peak - val) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
    return round(max_dd * 100, 2)


def backtest_stock(
    stock_code: str,
    prices: list[PriceRow],
    market_regime: str,
    min_window: int = 80,
) -> list[Trade]:
    """Run backtest on a single stock. Walk-forward simulation."""
    trades: list[Trade] = []

    if len(prices) < min_window:
        return trades

    in_trade: dict[str, int] = {}  # strategy -> exit_idx (avoid overlapping trades)

    for i in range(min_window, len(prices) - 1):
        window = prices[: i + 1]
        signals = evaluate_all_strategies(window, market_regime)

        for sig in signals:
            if not sig.triggered:
                continue

            # Skip if already in a trade for this strategy
            if sig.strategy in in_trade and i <= in_trade[sig.strategy]:
                continue

            exit_idx, exit_reason, exit_price = _simulate_trade(
                i, prices, sig.strategy, sig.stop_loss, sig.take_profit,
            )

            entry_price = sig.entry_price
            return_pct = round(((exit_price - entry_price) / entry_price) * 100, 2) if entry_price > 0 else 0.0
            holding = exit_idx - i

            trades.append(Trade(
                stock_code=stock_code,
                strategy=sig.strategy,
                grade=sig.grade,
                score=sig.score,
                entry_date=prices[i].date,
                entry_price=entry_price,
                exit_date=prices[exit_idx].date,
                exit_price=exit_price,
                exit_reason=exit_reason,
                stop_loss=sig.stop_loss,
                take_profit=sig.take_profit,
                holding_days=holding,
                return_pct=return_pct,
                pnl=round(exit_price - entry_price, 2),
            ))

            in_trade[sig.strategy] = exit_idx

    return trades


def summarize_trades(stock_code: str, strategy: str, trades: list[Trade]) -> BacktestResult:
    """Aggregate trades into a BacktestResult."""
    if not trades:
        return BacktestResult(
            stock_code=stock_code, strategy=strategy,
            total_trades=0, wins=0, losses=0, win_rate=0, avg_return_pct=0,
            total_pnl=0, max_drawdown_pct=0, sharpe_ratio=None, avg_holding_days=0,
            trades=[],
        )

    wins = sum(1 for t in trades if t.return_pct > 0)
    losses = len(trades) - wins
    returns = [t.return_pct for t in trades]
    equity = [100.0]
    for r in returns:
        equity.append(equity[-1] * (1 + r / 100))

    return BacktestResult(
        stock_code=stock_code,
        strategy=strategy,
        total_trades=len(trades),
        wins=wins,
        losses=losses,
        win_rate=round(wins / len(trades) * 100, 1),
        avg_return_pct=round(sum(returns) / len(returns), 2),
        total_pnl=round(sum(t.pnl for t in trades), 2),
        max_drawdown_pct=_calc_max_drawdown(equity),
        sharpe_ratio=_calc_sharpe(returns),
        avg_holding_days=round(sum(t.holding_days for t in trades) / len(trades), 1),
        trades=trades,
    )


def print_result(result: BacktestResult) -> None:
    """Pretty print a backtest result."""
    label = result.strategy.replace("strategy_", "").upper()
    sharpe = f"{result.sharpe_ratio:.2f}" if result.sharpe_ratio is not None else "N/A"
    print(f"  Strategy {label}: {result.total_trades} trades, "
          f"Win: {result.win_rate}%, Avg: {result.avg_return_pct:+.2f}%, "
          f"MDD: {result.max_drawdown_pct:.1f}%, Sharpe: {sharpe}, "
          f"Hold: {result.avg_holding_days:.0f}d")


def save_results_to_supabase(results: list[BacktestResult]) -> None:
    """Save backtest results to us_backtest_results table."""
    from config import SUPABASE_URL, SUPABASE_SERVICE_KEY
    from supabase import create_client

    sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    now = datetime.now(timezone.utc).isoformat()

    for r in results:
        if r.total_trades == 0:
            continue
        row = {
            "stock_code": r.stock_code,
            "strategy": r.strategy,
            "total_trades": r.total_trades,
            "wins": r.wins,
            "losses": r.losses,
            "win_rate": r.win_rate,
            "avg_return_pct": r.avg_return_pct,
            "total_pnl": r.total_pnl,
            "max_drawdown_pct": r.max_drawdown_pct,
            "sharpe_ratio": r.sharpe_ratio,
            "avg_holding_days": r.avg_holding_days,
            "backtest_date": now,
        }
        sb.table("us_backtest_results").upsert(
            row, on_conflict="stock_code,strategy",
        ).execute()

    print(f"[OK] Saved {len([r for r in results if r.total_trades > 0])} results to Supabase")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest Strategy A/B/C")
    parser.add_argument("--symbol", type=str, help="Single stock symbol (e.g. AAPL)")
    parser.add_argument("--days", type=int, default=365, help="Lookback days (default: 365)")
    parser.add_argument("--save", action="store_true", help="Save results to Supabase")
    args = parser.parse_args()

    market_regime = get_market_regime()
    print(f"Market regime: {market_regime}")
    print(f"Lookback: {args.days} days\n")

    if args.symbol:
        symbols = [args.symbol]
    else:
        from config import SUPABASE_URL, SUPABASE_SERVICE_KEY
        from supabase import create_client

        sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        data = sb.table("us_stocks").select("code").eq("is_active", True).order("code").execute()
        symbols = [row["code"] for row in (data.data or [])]

    print(f"Backtesting {len(symbols)} stock(s)...\n")

    all_results: list[BacktestResult] = []
    all_trades: list[Trade] = []

    for sym in symbols:
        prices = fetch_daily_prices(sym, args.days)
        if len(prices) < 80:
            print(f"  {sym}: insufficient data ({len(prices)} bars)")
            continue

        trades = backtest_stock(sym, prices, market_regime)
        if not trades:
            continue

        print(f"\n{sym} ({len(trades)} trades)")

        for strat in ("strategy_a", "strategy_b", "strategy_c"):
            strat_trades = [t for t in trades if t.strategy == strat]
            if strat_trades:
                result = summarize_trades(sym, strat, strat_trades)
                all_results.append(result)
                print_result(result)

        all_trades.extend(trades)

    # Overall summary
    if all_trades:
        print("\n" + "=" * 60)
        print("OVERALL SUMMARY")
        print("=" * 60)
        for strat in ("strategy_a", "strategy_b", "strategy_c"):
            strat_trades = [t for t in all_trades if t.strategy == strat]
            if strat_trades:
                result = summarize_trades("ALL", strat, strat_trades)
                print_result(result)

        total_wins = sum(1 for t in all_trades if t.return_pct > 0)
        print(f"\n  Total: {len(all_trades)} trades, "
              f"Win: {total_wins / len(all_trades) * 100:.1f}%, "
              f"Avg: {sum(t.return_pct for t in all_trades) / len(all_trades):+.2f}%")

    if args.save and all_results:
        save_results_to_supabase(all_results)

    if not all_trades:
        print("No trades found in backtest period.")


if __name__ == "__main__":
    main()
