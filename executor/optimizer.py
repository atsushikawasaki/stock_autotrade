"""Parameter optimizer: grid search and walk-forward analysis for Strategy A."""

from __future__ import annotations

import itertools
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone

from supabase import create_client

from config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from backtest import backtest_stock, summarize_trades, Trade
from price_client import PriceRow, fetch_daily_prices, fetch_daily_prices_cached
from market_filter import get_market_regime

log = logging.getLogger("optimizer")

sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


# ─── Data Types ──────────────────────────────────────────────────────────────


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


@dataclass(frozen=True)
class WalkForwardWindow:
    """One train/test window in walk-forward analysis."""
    window_id: int
    train_params: ParamSet
    train_result: OptResult
    test_result: OptResult


@dataclass(frozen=True)
class WalkForwardResult:
    """Aggregated walk-forward analysis result."""
    windows: list[WalkForwardWindow]
    best_params: ParamSet
    oos_total_trades: int
    oos_win_rate: float
    oos_avg_return: float
    oos_sharpe: float | None
    robustness_score: float  # 0~1, higher = more robust (less overfit)


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


# ─── Internals ───────────────────────────────────────────────────────────────


class _OverrideParams:
    """Context manager to temporarily override Strategy A constants."""

    def __init__(self, params: ParamSet) -> None:
        self._params = params
        self._originals: dict[str, object] = {}

    def __enter__(self) -> None:
        import constants
        fields = (
            "STRATEGY_A_BREAKOUT_LOOKBACK", "STRATEGY_A_RSI_MIN",
            "STRATEGY_A_RSI_MAX", "STRATEGY_A_VOLUME_RATIO_MIN",
            "STRATEGY_A_SL_ATR_MULT", "STRATEGY_A_TP_ATR_MULT",
            "STRATEGY_A_ADX_MIN",
        )
        for f in fields:
            self._originals[f] = getattr(constants, f)

        constants.STRATEGY_A_BREAKOUT_LOOKBACK = self._params.breakout_lookback
        constants.STRATEGY_A_RSI_MIN = self._params.rsi_min
        constants.STRATEGY_A_RSI_MAX = self._params.rsi_max
        constants.STRATEGY_A_VOLUME_RATIO_MIN = self._params.volume_ratio_min
        constants.STRATEGY_A_SL_ATR_MULT = self._params.sl_atr_mult
        constants.STRATEGY_A_TP_ATR_MULT = self._params.tp_atr_mult
        constants.STRATEGY_A_ADX_MIN = self._params.adx_min

    def __exit__(self, *exc: object) -> None:
        import constants
        for attr, val in self._originals.items():
            setattr(constants, attr, val)


def _calc_score(win_rate: float, avg_return: float, sharpe: float | None, total_trades: int) -> float:
    """Composite score: balances profitability, consistency, and sample size."""
    if total_trades < 5:
        return -999.0
    s = (sharpe or 0) * 0.4 + avg_return * 0.4 + (win_rate - 50) * 0.2
    return round(s, 4)


def _fetch_sample_stocks(n: int = 20) -> list[str]:
    """Fetch top N active stocks for optimization (by backtest trade count)."""
    result = (
        sb.table("us_backtest_results")
        .select("stock_code")
        .eq("strategy", "strategy_a")
        .order("total_trades", desc=True)
        .limit(n)
        .execute()
    )
    codes = list({r["stock_code"] for r in (result.data or [])})
    if not codes:
        # Fallback: use active us_stocks
        data = sb.table("us_stocks").select("code").eq("is_active", True).limit(n).execute()
        codes = [r["code"] for r in (data.data or [])]
    return codes


def _generate_combos(grid: dict, max_combos: int) -> list[dict]:
    """Generate parameter combinations, sampling if too many."""
    keys = list(grid.keys())
    values = list(grid.values())
    all_combos = [dict(zip(keys, combo)) for combo in itertools.product(*values)]

    if len(all_combos) > max_combos:
        import random
        random.seed(42)
        all_combos = random.sample(all_combos, max_combos)

    return all_combos


def _evaluate_params_on_prices(
    params: ParamSet,
    symbol_prices: dict[str, list[PriceRow]],
    regime: str,
) -> OptResult:
    """Run backtest with given params on pre-fetched price data."""
    all_trades: list[Trade] = []

    with _OverrideParams(params):
        for sym, prices in symbol_prices.items():
            if len(prices) < 80:
                continue
            try:
                trades = backtest_stock(sym, prices, regime)
                a_trades = [t for t in trades if t.strategy == "strategy_a"]
                all_trades.extend(a_trades)
            except Exception:
                continue

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


def _slice_prices(
    symbol_prices: dict[str, list[PriceRow]], start_idx: int, end_idx: int,
) -> dict[str, list[PriceRow]]:
    """Slice each stock's price list by index range."""
    return {
        sym: prices[start_idx:end_idx]
        for sym, prices in symbol_prices.items()
    }


def _fetch_all_prices(symbols: list[str], days: int) -> dict[str, list[PriceRow]]:
    """Fetch price data for all symbols. Uses Supabase cache."""
    result: dict[str, list[PriceRow]] = {}
    for sym in symbols:
        try:
            prices = fetch_daily_prices_cached(sym, days)
            if len(prices) >= 80:
                result[sym] = prices
        except Exception as e:
            log.warning("[OPT] Failed to fetch %s: %s", sym, e)
    return result


def _calc_robustness(train_avg: float, test_avg: float) -> float:
    """Robustness score: 0~1. Higher = train and test performance are closer."""
    denom = max(abs(train_avg), 1.0)
    return round(max(0.0, 1.0 - abs(train_avg - test_avg) / denom), 4)


def _calc_oos_sharpe(returns: list[float]) -> float | None:
    """Annualized Sharpe from a list of per-trade returns."""
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(var) if var > 0 else 0
    if std == 0:
        return None
    return round((mean / std) * math.sqrt(252), 4)


# ─── Legacy: Simple Grid Search ──────────────────────────────────────────────


def _evaluate_params(params: ParamSet, symbols: list[str], days: int, regime: str) -> OptResult:
    """Run backtest with given params on sample stocks (legacy: fetches prices per call)."""
    all_trades: list[Trade] = []

    with _OverrideParams(params):
        for sym in symbols:
            try:
                prices = fetch_daily_prices(sym, days)
                if len(prices) < 80:
                    continue
                trades = backtest_stock(sym, prices, regime)
                a_trades = [t for t in trades if t.strategy == "strategy_a"]
                all_trades.extend(a_trades)
            except Exception:
                continue

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

    all_combos = _generate_combos(grid, max_combos)
    log.info("[OPT] Testing %d parameter combinations", len(all_combos))

    results: list[OptResult] = []
    for i, combo in enumerate(all_combos):
        params = ParamSet(**combo)
        result = _evaluate_params(params, symbols, days, regime)
        results.append(result)

        if (i + 1) % 10 == 0:
            log.info("[OPT] Progress: %d/%d", i + 1, len(all_combos))

    results.sort(key=lambda r: r.score, reverse=True)

    _save_optimization_results(results[:10], method="grid_search")

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


# ─── Walk-Forward Analysis ───────────────────────────────────────────────────


def run_walk_forward(
    grid: dict | None = None,
    sample_stocks: int = 20,
    days: int = 730,
    max_combos: int = 50,
    train_days: int = 250,
    test_days: int = 125,
    step_days: int = 125,
) -> WalkForwardResult | None:
    """
    Walk-forward optimization: train on one window, validate on the next.

    Splits the data into overlapping windows:
      Window 1: train[0:250], test[250:375]
      Window 2: train[125:375], test[375:500]
      ...

    For each window:
      1. Grid search on train period -> best params
      2. Evaluate best params on test period (out-of-sample)

    Returns aggregated OOS metrics and robustness score.
    """
    grid = grid or DEFAULT_GRID
    regime = get_market_regime()
    symbols = _fetch_sample_stocks(sample_stocks)

    if not symbols:
        log.warning("[WF] No stocks found for optimization")
        return None

    log.info(
        "[WF] Walk-forward: %d stocks, %d days, train=%d test=%d step=%d regime=%s",
        len(symbols), days, train_days, test_days, step_days, regime,
    )

    # Fetch all price data once
    all_prices = _fetch_all_prices(symbols, days)
    if not all_prices:
        log.warning("[WF] No price data available")
        return None

    # Determine data length (use shortest common length for consistent windows)
    min_len = min(len(p) for p in all_prices.values())
    log.info("[WF] Price data: %d stocks, min length=%d bars", len(all_prices), min_len)

    # Generate windows
    window_size = train_days + test_days
    windows: list[tuple[int, int, int]] = []  # (window_id, train_start, train_end)
    win_id = 0
    start = 0
    while start + window_size <= min_len:
        windows.append((win_id, start, start + train_days))
        start += step_days
        win_id += 1

    if not windows:
        log.warning("[WF] Not enough data for even one window (need %d, have %d)", window_size, min_len)
        return None

    log.info("[WF] Generated %d walk-forward windows", len(windows))

    # Generate combos once
    all_combos = _generate_combos(grid, max_combos)
    log.info("[WF] Testing %d parameter combinations per window", len(all_combos))

    # Run walk-forward
    wf_windows: list[WalkForwardWindow] = []
    all_oos_trades: list[Trade] = []
    param_counts: dict[ParamSet, list[OptResult]] = {}

    for wid, train_start, train_end in windows:
        test_start = train_end
        test_end = min(train_end + test_days, min_len)

        log.info(
            "[WF] Window %d: train[%d:%d] test[%d:%d]",
            wid, train_start, train_end, test_start, test_end,
        )

        train_prices = _slice_prices(all_prices, train_start, train_end)
        test_prices = _slice_prices(all_prices, test_start, test_end)

        # Grid search on train period
        best_train: OptResult | None = None
        for combo in all_combos:
            params = ParamSet(**combo)
            result = _evaluate_params_on_prices(params, train_prices, regime)
            if best_train is None or result.score > best_train.score:
                best_train = result

        if best_train is None or best_train.score <= -999:
            log.info("[WF] Window %d: no viable params found in train", wid)
            continue

        # Evaluate best params on test period (out-of-sample)
        test_result = _evaluate_params_on_prices(best_train.params, test_prices, regime)

        wf_windows.append(WalkForwardWindow(
            window_id=wid,
            train_params=best_train.params,
            train_result=best_train,
            test_result=test_result,
        ))

        # Track which params performed best across windows
        if best_train.params not in param_counts:
            param_counts[best_train.params] = []
        param_counts[best_train.params].append(test_result)

        # Collect OOS trades for aggregate metrics
        with _OverrideParams(best_train.params):
            for sym, prices in test_prices.items():
                if len(prices) < 80:
                    continue
                try:
                    trades = backtest_stock(sym, prices, regime)
                    all_oos_trades.extend(t for t in trades if t.strategy == "strategy_a")
                except Exception:
                    continue

        log.info(
            "[WF] Window %d: train(score=%.2f avg=%.2f%%) -> test(score=%.2f avg=%.2f%%)",
            wid, best_train.score, best_train.avg_return,
            test_result.score, test_result.avg_return,
        )

    if not wf_windows:
        log.warning("[WF] No valid walk-forward windows produced results")
        return None

    # Find the params that appeared most often as best, weighted by OOS score
    best_params = max(
        param_counts.keys(),
        key=lambda p: sum(r.score for r in param_counts[p]),
    )

    # Aggregate OOS metrics
    oos_wins = sum(1 for t in all_oos_trades if t.return_pct > 0)
    oos_total = len(all_oos_trades)
    oos_returns = [t.return_pct for t in all_oos_trades]

    oos_win_rate = round(oos_wins / oos_total * 100, 1) if oos_total > 0 else 0.0
    oos_avg_return = round(sum(oos_returns) / len(oos_returns), 2) if oos_returns else 0.0
    oos_sharpe = _calc_oos_sharpe(oos_returns)

    # Robustness: average across windows
    train_avgs = [w.train_result.avg_return for w in wf_windows]
    test_avgs = [w.test_result.avg_return for w in wf_windows]
    avg_train = sum(train_avgs) / len(train_avgs)
    avg_test = sum(test_avgs) / len(test_avgs)
    robustness = _calc_robustness(avg_train, avg_test)

    wf_result = WalkForwardResult(
        windows=wf_windows,
        best_params=best_params,
        oos_total_trades=oos_total,
        oos_win_rate=oos_win_rate,
        oos_avg_return=oos_avg_return,
        oos_sharpe=oos_sharpe,
        robustness_score=robustness,
    )

    # Log summary
    log.info("[WF] === Walk-Forward Summary ===")
    log.info("[WF] Windows: %d", len(wf_windows))
    log.info("[WF] OOS trades: %d, win: %.1f%%, avg: %.2f%%, sharpe: %s",
             oos_total, oos_win_rate, oos_avg_return,
             f"{oos_sharpe:.2f}" if oos_sharpe else "N/A")
    log.info("[WF] Robustness: %.2f (train avg=%.2f%% vs test avg=%.2f%%)",
             robustness, avg_train, avg_test)
    log.info("[WF] Best params: lookback=%d rsi=%d-%d vol=%.1f sl=%.1f tp=%.1f adx=%d",
             best_params.breakout_lookback, best_params.rsi_min, best_params.rsi_max,
             best_params.volume_ratio_min, best_params.sl_atr_mult, best_params.tp_atr_mult,
             best_params.adx_min)

    for w in wf_windows:
        log.info(
            "[WF]   Window %d: train(%.2f%% sharpe=%s) -> test(%.2f%% sharpe=%s) | "
            "lookback=%d rsi=%d-%d vol=%.1f",
            w.window_id,
            w.train_result.avg_return,
            f"{w.train_result.sharpe:.2f}" if w.train_result.sharpe else "N/A",
            w.test_result.avg_return,
            f"{w.test_result.sharpe:.2f}" if w.test_result.sharpe else "N/A",
            w.train_params.breakout_lookback, w.train_params.rsi_min, w.train_params.rsi_max,
            w.train_params.volume_ratio_min,
        )

    # Save to Supabase
    _save_walk_forward_results(wf_result)

    return wf_result


# ─── Persistence ─────────────────────────────────────────────────────────────


def _save_optimization_results(results: list[OptResult], method: str = "grid_search") -> None:
    """Save optimization results to Supabase for review."""
    now = datetime.now(timezone.utc).isoformat()
    for rank, r in enumerate(results, 1):
        try:
            sb.table("us_optimization_results").upsert({
                "run_date": now[:10],
                "rank": rank,
                "strategy": "strategy_a",
                "params": {
                    "method": method,
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


def _save_walk_forward_results(wf: WalkForwardResult) -> None:
    """Save walk-forward results to us_optimization_results."""
    now = datetime.now(timezone.utc).isoformat()
    p = wf.best_params

    window_details = [
        {
            "window_id": w.window_id,
            "train_avg_return": w.train_result.avg_return,
            "train_sharpe": w.train_result.sharpe,
            "train_trades": w.train_result.total_trades,
            "test_avg_return": w.test_result.avg_return,
            "test_sharpe": w.test_result.sharpe,
            "test_trades": w.test_result.total_trades,
            "params": {
                "breakout_lookback": w.train_params.breakout_lookback,
                "rsi_min": w.train_params.rsi_min,
                "rsi_max": w.train_params.rsi_max,
                "volume_ratio_min": w.train_params.volume_ratio_min,
                "sl_atr_mult": w.train_params.sl_atr_mult,
                "tp_atr_mult": w.train_params.tp_atr_mult,
                "adx_min": w.train_params.adx_min,
            },
        }
        for w in wf.windows
    ]

    try:
        sb.table("us_optimization_results").upsert({
            "run_date": now[:10],
            "rank": 1,
            "strategy": "strategy_a",
            "params": {
                "method": "walk_forward",
                "breakout_lookback": p.breakout_lookback,
                "rsi_min": p.rsi_min,
                "rsi_max": p.rsi_max,
                "volume_ratio_min": p.volume_ratio_min,
                "sl_atr_mult": p.sl_atr_mult,
                "tp_atr_mult": p.tp_atr_mult,
                "adx_min": p.adx_min,
                "robustness_score": wf.robustness_score,
                "windows": window_details,
            },
            "total_trades": wf.oos_total_trades,
            "win_rate": wf.oos_win_rate,
            "avg_return": wf.oos_avg_return,
            "sharpe": wf.oos_sharpe,
            "max_drawdown": None,
            "score": wf.robustness_score,
        }, on_conflict="run_date,rank").execute()
        log.info("[WF] Saved walk-forward results to Supabase")
    except Exception as e:
        log.warning("[WF] Failed to save walk-forward results: %s", e)
