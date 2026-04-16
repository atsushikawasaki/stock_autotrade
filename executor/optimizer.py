"""Parameter optimizer: grid search over strategy constants to maximize performance."""

from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from supabase import create_client

from config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from backtest import backtest_stock, summarize_trades
from price_client import fetch_daily_prices
from market_filter import get_market_regime

log = logging.getLogger("optimizer")

sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


@dataclass(frozen=True)
class ParamSet:
    """A set of strategy parameters to evaluate."""
    breakout_lookback: int
    rsi_min: int
    rsi_max: int
    volume_ratio_min: float
    sl_atr_mult: float
    tp_atr_mult: float
    adx_min: int


@dataclass(frozen=True)
class OptResult:
    """Result of evaluating one parameter set."""
    params: ParamSet
    total_trades: int
    win_rate: float
    avg_return: float
    sharpe: float | None
    max_drawdown: float
    score: float  # composite metric for ranking


# Default grid — kept small for reasonable runtime
DEFAULT_GRID = {
    "breakout_lookback": [15, 20, 25],
    "rsi_min": [45, 50, 55],
    "rsi_max": [70, 75, 80],
    "volume_ratio_min": [1.2, 1.3, 1.5],
    "sl_atr_mult": [1.5, 2.0, 2.5],
    "tp_atr_mult": [3.0, 4.0, 5.0],
    "adx_min": [15, 20, 25],
}


def _apply_params(params: ParamSet) -> None:
    """Temporarily override constants with given params."""
    import constants
    constants.STRATEGY_A_BREAKOUT_LOOKBACK = params.breakout_lookback
    constants.STRATEGY_A_RSI_MIN = params.rsi_min
    constants.STRATEGY_A_RSI_MAX = params.rsi_max
    constants.STRATEGY_A_VOLUME_RATIO_MIN = params.volume_ratio_min
    constants.STRATEGY_A_SL_ATR_MULT = params.sl_atr_mult
    constants.STRATEGY_A_TP_ATR_MULT = params.tp_atr_mult
    constants.STRATEGY_A_ADX_MIN = params.adx_min


def _restore_defaults() -> None:
    """Restore original constants (reimport)."""
    import importlib
    import constants
    importlib.reload(constants)


def _calc_score(win_rate: float, avg_return: float, sharpe: float | None, total_trades: int) -> float:
    """Composite score: balances profitability, consistency, and sample size."""
    if total_trades < 5:
        return -999.0
    s = (sharpe or 0) * 0.4 + avg_return * 0.4 + (win_rate - 50) * 0.2
    return round(s, 4)


def _fetch_sample_stocks(n: int = 20) -> list[str]:
    """Fetch top N active stocks for optimization (by backtest PnL)."""
    result = (
        sb.table("us_backtest_results")
        .select("stock_code")
        .eq("strategy", "strategy_a")
        .order("total_trades", desc=True)
        .limit(n)
        .execute()
    )
    return list({r["stock_code"] for r in (result.data or [])})


def _evaluate_params(params: ParamSet, symbols: list[str], days: int, regime: str) -> OptResult:
    """Run backtest with given params on sample stocks."""
    _apply_params(params)

    all_trades = []
    for sym in symbols:
        try:
            prices = fetch_daily_prices(sym, days)
            if len(prices) < 80:
                continue
            trades = backtest_stock(sym, prices, regime)
            # Only Strategy A trades (since we're tuning Strategy A params)
            a_trades = [t for t in trades if t.strategy == "strategy_a"]
            all_trades.extend(a_trades)
        except Exception:
            continue

    _restore_defaults()

    if not all_trades:
        return OptResult(
            params=params, total_trades=0, win_rate=0,
            avg_return=0, sharpe=None, max_drawdown=0, score=-999,
        )

    result = summarize_trades("OPT", "strategy_a", all_trades)
    score = _calc_score(result.win_rate, result.avg_return_pct, result.sharpe_ratio, result.total_trades)

    return OptResult(
        params=params,
        total_trades=result.total_trades,
        win_rate=result.win_rate,
        avg_return=result.avg_return_pct,
        sharpe=result.sharpe_ratio,
        max_drawdown=result.max_drawdown_pct,
        score=score,
    )


def run_optimization(
    grid: dict | None = None,
    sample_stocks: int = 20,
    days: int = 365,
    max_combos: int = 50,
) -> list[OptResult]:
    """
    Run grid search optimization on Strategy A parameters.

    Args:
        grid: Parameter grid (default: DEFAULT_GRID)
        sample_stocks: Number of stocks to test on
        days: Lookback days for backtest
        max_combos: Max parameter combinations to test (random sample if grid is larger)

    Returns:
        List of OptResult sorted by score (best first)
    """
    grid = grid or DEFAULT_GRID
    regime = get_market_regime()
    symbols = _fetch_sample_stocks(sample_stocks)

    if not symbols:
        log.warning("[OPT] No stocks found for optimization")
        return []

    log.info("[OPT] Starting optimization: %d stocks, %d days, regime=%s", len(symbols), days, regime)

    # Generate all combinations
    keys = list(grid.keys())
    values = list(grid.values())
    all_combos = [dict(zip(keys, combo)) for combo in itertools.product(*values)]

    # Sample if too many
    if len(all_combos) > max_combos:
        import random
        random.seed(42)
        all_combos = random.sample(all_combos, max_combos)

    log.info("[OPT] Testing %d parameter combinations", len(all_combos))

    results: list[OptResult] = []
    for i, combo in enumerate(all_combos):
        params = ParamSet(**combo)
        result = _evaluate_params(params, symbols, days, regime)
        results.append(result)

        if (i + 1) % 10 == 0:
            log.info("[OPT] Progress: %d/%d", i + 1, len(all_combos))

    results.sort(key=lambda r: r.score, reverse=True)

    # Save top results to Supabase
    _save_optimization_results(results[:10])

    # Log top 5
    log.info("[OPT] Top 5 results:")
    for r in results[:5]:
        log.info(
            "  score=%.2f trades=%d win=%.1f%% avg=%.2f%% sharpe=%s | "
            "lookback=%d rsi=%d-%d vol=%.1f sl=%.1f tp=%.1f adx=%d",
            r.score, r.total_trades, r.win_rate, r.avg_return,
            f"{r.sharpe:.2f}" if r.sharpe else "N/A",
            r.params.breakout_lookback, r.params.rsi_min, r.params.rsi_max,
            r.params.volume_ratio_min, r.params.sl_atr_mult, r.params.tp_atr_mult,
            r.params.adx_min,
        )

    return results


def _save_optimization_results(results: list[OptResult]) -> None:
    """Save optimization results to Supabase for review."""
    now = datetime.now(timezone.utc).isoformat()
    for rank, r in enumerate(results, 1):
        try:
            sb.table("us_optimization_results").upsert({
                "run_date": now[:10],
                "rank": rank,
                "strategy": "strategy_a",
                "params": {
                    "breakout_lookback": r.params.breakout_lookback,
                    "rsi_min": r.params.rsi_min,
                    "rsi_max": r.params.rsi_max,
                    "volume_ratio_min": r.params.volume_ratio_min,
                    "sl_atr_mult": r.params.sl_atr_mult,
                    "tp_atr_mult": r.params.tp_atr_mult,
                    "adx_min": r.params.adx_min,
                },
                "total_trades": r.total_trades,
                "win_rate": r.win_rate,
                "avg_return": r.avg_return,
                "sharpe": r.sharpe,
                "max_drawdown": r.max_drawdown,
                "score": r.score,
            }, on_conflict="run_date,rank").execute()
        except Exception as e:
            log.warning("[OPT] Failed to save result rank %d: %s", rank, e)
