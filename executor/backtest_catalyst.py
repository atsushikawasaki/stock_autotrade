#!/usr/bin/env python3
"""
Backtest engine for Strategy D (Catalyst-Driven).

Uses historical data to simulate catalyst-based entries:
1. Insider buying: SEC EDGAR Form 4 XML → open-market purchases only (code "P")
2. Earnings beat momentum: enter DAY AFTER confirmed earnings beat

Usage:
  cd executor
  python backtest_catalyst.py                     # default: 10 stocks
  python backtest_catalyst.py --symbols AAPL NVDA # specific stocks
  python backtest_catalyst.py --threshold 40      # test lower threshold
  python backtest_catalyst.py --sensitivity       # threshold sensitivity analysis
"""

from __future__ import annotations

import argparse
import math
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError

from dotenv import load_dotenv

load_dotenv()

import yfinance as yf

from price_client import PriceRow, fetch_daily_prices
from catalyst_scanner import _parse_form4_xml, _classify_role, _INSIDER_ROLE_SCORES
from constants import (
    STRATEGY_D_SL_ATR_MULT,
    STRATEGY_D_TP_ATR_MULT,
    STRATEGY_D_SCORE_THRESHOLD,
    MAX_HOLDING_DAYS_D,
    BACKTEST_SLIPPAGE_PCT,
    BACKTEST_COMMISSION_PCT,
    SCORE_D_GRADE_A_MIN,
    SCORE_D_GRADE_B_MIN,
)

_SEC_USER_AGENT = "StockTradeBot/1.0 (personal research)"
_SEC_INTERVAL = 0.5
_last_sec_req: float = 0.0


def _sec_fetch(url: str) -> bytes | None:
    global _last_sec_req
    elapsed = time.time() - _last_sec_req
    if elapsed < _SEC_INTERVAL:
        time.sleep(_SEC_INTERVAL - elapsed)
    _last_sec_req = time.time()
    try:
        req = Request(url, headers={"User-Agent": _SEC_USER_AGENT})
        with urlopen(req, timeout=15) as resp:
            return resp.read()
    except (URLError, OSError):
        return None


@dataclass(frozen=True)
class CatalystTrade:
    stock_code: str
    catalyst_type: str       # "insider" or "earnings_beat"
    catalyst_detail: str
    catalyst_score: int
    grade: str
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    exit_reason: str
    stop_loss: float
    take_profit: float
    holding_days: int
    return_pct: float


@dataclass(frozen=True)
class CatalystBacktestResult:
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    avg_return_pct: float
    total_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float | None
    avg_holding_days: float
    trades: list[CatalystTrade]
    by_catalyst_type: dict


# ---------------------------------------------------------------------------
# Historical insider filings — with Form 4 XML parsing (purchase only)
# ---------------------------------------------------------------------------

def _fetch_insider_purchases(symbol: str, max_filings: int = 40) -> list[dict]:
    """
    Fetch historical Form 4 filings from SEC EDGAR and parse XML
    to extract only open-market purchases (transaction code "P").

    Returns list of {date, role, title, shares, value_usd, score}.
    """
    atom_url = (
        f"https://www.sec.gov/cgi-bin/browse-edgar"
        f"?action=getcompany&CIK={symbol}&type=4"
        f"&dateb=&owner=include&count={max_filings}&output=atom"
    )
    atom_data = _sec_fetch(atom_url)
    if atom_data is None:
        return []

    try:
        root = ET.fromstring(atom_data)
    except ET.ParseError:
        return []

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries = root.findall("atom:entry", ns)

    purchases: list[dict] = []

    for entry in entries:
        # Get filing date
        updated_el = entry.find("atom:updated", ns)
        if updated_el is None or updated_el.text is None:
            continue
        try:
            filed = datetime.fromisoformat(updated_el.text.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue

        filed_str = filed.strftime("%Y-%m-%d")

        # Get index page URL
        link_el = entry.find("atom:link", ns)
        if link_el is None:
            continue
        index_url = link_el.get("href", "")
        if not index_url:
            continue

        # Fetch index page
        index_data = _sec_fetch(index_url)
        if index_data is None:
            continue

        index_html = index_data.decode("utf-8", errors="replace")
        xml_matches = re.findall(r'href="([^"]+/form4\.xml)"', index_html)
        if not xml_matches:
            xml_matches = re.findall(r'href="([^"]+\.xml)"', index_html)
            xml_matches = [m for m in xml_matches if "xsl" not in m.lower()]
        if not xml_matches:
            continue

        # Fetch and parse Form 4 XML
        xml_path = xml_matches[-1]
        if xml_path.startswith("/"):
            xml_url = f"https://www.sec.gov{xml_path}"
        else:
            base = index_url.rsplit("/", 1)[0]
            xml_url = f"{base}/{xml_path}"

        form4_data = _sec_fetch(xml_url)
        if form4_data is None:
            continue

        txs = _parse_form4_xml(form4_data)
        for tx in txs:
            purchases.append({
                "date": tx.get("date") or filed_str,
                "role": tx["role"],
                "title": tx["title"],
                "shares": tx["shares"],
                "value_usd": tx["value_usd"],
            })

    # Sort oldest first
    purchases.sort(key=lambda x: x["date"])
    return purchases


# ---------------------------------------------------------------------------
# Historical earnings beat events (post-beat)
# ---------------------------------------------------------------------------

def _fetch_earnings_beats(symbol: str) -> list[dict]:
    """
    Get historical earnings dates where the company beat estimates.
    Returns list of {date, surprise_pct, consecutive_beats}.
    Entry is on the DAY AFTER earnings report.
    """
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.earnings_history
        if hist is None or hist.empty:
            return []

        events: list[dict] = []
        consecutive = 0

        for idx, row in hist.iterrows():
            surprise = row.get("surprisePercent")
            report_date = row.get("reportDate") or row.get("quarter")

            if surprise is None:
                consecutive = 0
                continue

            surprise_val = float(surprise)
            if surprise_val > 0:
                consecutive += 1
            else:
                consecutive = 0

            # Enter after any beat (even single beat)
            if surprise_val > 0:
                date_str = str(report_date)[:10] if report_date else str(idx)[:10]
                events.append({
                    "date": date_str,
                    "surprise_pct": round(surprise_val, 2),
                    "consecutive_beats": consecutive,
                })

        return events

    except Exception as e:
        print(f"  [WARN] Earnings history failed for {symbol}: {e}")
        return []


# ---------------------------------------------------------------------------
# ATR + trade simulation
# ---------------------------------------------------------------------------

def _calc_atr_at(prices: list[PriceRow], idx: int, period: int = 14) -> float | None:
    if idx < period:
        return None
    trs: list[float] = []
    for i in range(idx - period + 1, idx + 1):
        tr = max(
            prices[i].high - prices[i].low,
            abs(prices[i].high - prices[i - 1].close),
            abs(prices[i].low - prices[i - 1].close),
        )
        trs.append(tr)
    return sum(trs) / len(trs) if trs else None


def _simulate_trade(
    prices: list[PriceRow],
    entry_idx: int,
    sl_mult: float,
    tp_mult: float,
    max_days: int,
) -> tuple[int, str, float, float, float]:
    """Returns (exit_idx, exit_reason, exit_price, sl_price, tp_price)."""
    entry_price = prices[entry_idx].close
    atr = _calc_atr_at(prices, entry_idx)
    if atr is None or atr <= 0:
        atr = entry_price * 0.02

    sl = entry_price - sl_mult * atr
    tp = entry_price + tp_mult * atr

    for offset in range(1, max_days + 1):
        idx = entry_idx + offset
        if idx >= len(prices):
            return len(prices) - 1, "end_of_data", prices[-1].close, sl, tp
        bar = prices[idx]
        if bar.low <= sl:
            return idx, "stop_loss", sl, sl, tp
        if bar.high >= tp:
            return idx, "take_profit", tp, sl, tp

    exit_idx = min(entry_idx + max_days, len(prices) - 1)
    return exit_idx, "time_expiry", prices[exit_idx].close, sl, tp


def _apply_costs(return_pct: float) -> float:
    return return_pct - (BACKTEST_SLIPPAGE_PCT * 2) - (BACKTEST_COMMISSION_PCT * 2)


def _find_price_idx(prices: list[PriceRow], date_str: str) -> int | None:
    for i, p in enumerate(prices):
        if p.date >= date_str:
            return i
    return None


def _assign_grade(score: int) -> str:
    if score >= SCORE_D_GRADE_A_MIN:
        return "A"
    if score >= SCORE_D_GRADE_B_MIN:
        return "B"
    return "C"


# ---------------------------------------------------------------------------
# Main backtest
# ---------------------------------------------------------------------------

def _score_insider_cluster(purchases: list[dict]) -> int:
    """Score a cluster of insider purchases on the same date."""
    score = 0
    roles_seen: set[str] = set()
    total_value = 0.0

    for p in purchases:
        role = p["role"]
        if role not in roles_seen:
            score += _INSIDER_ROLE_SCORES.get(role, 20)
            roles_seen.add(role)
        total_value += p.get("value_usd", 0)

    # Multi-insider bonus
    if len(purchases) >= 3:
        score += 15
    elif len(purchases) >= 2:
        score += 10

    # Large value bonus
    if total_value >= 500_000:
        score += 10
    elif total_value >= 100_000:
        score += 5

    return score


def backtest_catalyst_stock(
    symbol: str,
    threshold: int = STRATEGY_D_SCORE_THRESHOLD,
    sl_mult: float = STRATEGY_D_SL_ATR_MULT,
    tp_mult: float = STRATEGY_D_TP_ATR_MULT,
    max_days: int = MAX_HOLDING_DAYS_D,
) -> list[CatalystTrade]:
    """Backtest Strategy D on a single stock."""
    prices = fetch_daily_prices(symbol, 600)
    if len(prices) < 100:
        print(f"  [SKIP] {symbol}: insufficient price data ({len(prices)} bars)")
        return []

    earliest_date = prices[20].date  # ATR warmup
    trades: list[CatalystTrade] = []

    # --- 1. Insider purchases (Form 4 XML parsed — purchases only) ---
    print(f"  Fetching insider purchases...")
    insider_purchases = _fetch_insider_purchases(symbol)
    purchase_count = len(insider_purchases)
    print(f"  Found {purchase_count} open-market purchases")

    # Group by date
    by_date: dict[str, list[dict]] = defaultdict(list)
    for p in insider_purchases:
        by_date[p["date"]].append(p)

    for date_str, cluster in by_date.items():
        if date_str < earliest_date:
            continue

        score = _score_insider_cluster(cluster)
        if score < threshold:
            continue

        entry_idx = _find_price_idx(prices, date_str)
        if entry_idx is None or entry_idx + 1 >= len(prices):
            continue
        entry_idx += 1  # enter next trading day
        if entry_idx < 20:
            continue

        exit_idx, exit_reason, exit_price, sl, tp = _simulate_trade(
            prices, entry_idx, sl_mult, tp_mult, max_days,
        )

        entry_price = prices[entry_idx].close
        raw_return = ((exit_price - entry_price) / entry_price) * 100
        return_pct = round(_apply_costs(raw_return), 2)

        roles = sorted(set(p["role"] for p in cluster))
        total_val = sum(p["value_usd"] for p in cluster)
        val_str = f" ${total_val:,.0f}" if total_val > 0 else ""

        trades.append(CatalystTrade(
            stock_code=symbol,
            catalyst_type="insider",
            catalyst_detail=f"{', '.join(roles[:2])} buy ({len(cluster)}x{val_str})",
            catalyst_score=score,
            grade=_assign_grade(score),
            entry_date=prices[entry_idx].date,
            entry_price=round(entry_price, 2),
            exit_date=prices[exit_idx].date,
            exit_price=round(exit_price, 2),
            exit_reason=exit_reason,
            stop_loss=round(sl, 2),
            take_profit=round(tp, 2),
            holding_days=exit_idx - entry_idx,
            return_pct=return_pct,
        ))

    # --- 2. Earnings beat momentum (post-beat entry) ---
    print(f"  Fetching earnings beats...")
    earnings_events = _fetch_earnings_beats(symbol)
    print(f"  Found {len(earnings_events)} earnings beats")

    for event in earnings_events:
        date_str = event["date"]
        if date_str < earliest_date:
            continue

        consecutive = event["consecutive_beats"]
        surprise_pct = event["surprise_pct"]

        # Score
        score = 0
        if consecutive >= 4:
            score = 35
        elif consecutive >= 3:
            score = 30
        elif consecutive >= 2:
            score = 25
        else:
            score = 20

        if surprise_pct >= 20:
            score += 10
        elif surprise_pct >= 10:
            score += 5

        if score < threshold:
            continue

        # Enter day AFTER earnings report
        event_idx = _find_price_idx(prices, date_str)
        if event_idx is None or event_idx + 1 >= len(prices):
            continue
        entry_idx = event_idx + 1
        if entry_idx < 20:
            continue

        exit_idx, exit_reason, exit_price, sl, tp = _simulate_trade(
            prices, entry_idx, sl_mult, tp_mult, max_days,
        )

        entry_price = prices[entry_idx].close
        raw_return = ((exit_price - entry_price) / entry_price) * 100
        return_pct = round(_apply_costs(raw_return), 2)

        trades.append(CatalystTrade(
            stock_code=symbol,
            catalyst_type="earnings_beat",
            catalyst_detail=f"{consecutive}Q streak, surprise +{surprise_pct}%",
            catalyst_score=score,
            grade=_assign_grade(score),
            entry_date=prices[entry_idx].date,
            entry_price=round(entry_price, 2),
            exit_date=prices[exit_idx].date,
            exit_price=round(exit_price, 2),
            exit_reason=exit_reason,
            stop_loss=round(sl, 2),
            take_profit=round(tp, 2),
            holding_days=exit_idx - entry_idx,
            return_pct=return_pct,
        ))

    return trades


# ---------------------------------------------------------------------------
# Aggregate results
# ---------------------------------------------------------------------------

def _calc_sharpe(returns: list[float]) -> float | None:
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(var) if var > 0 else 0
    if std == 0:
        return None
    return round((mean / std) * math.sqrt(252), 2)


def _calc_max_drawdown(returns: list[float]) -> float:
    if not returns:
        return 0.0
    equity = 100.0
    peak = equity
    max_dd = 0.0
    for r in returns:
        equity *= (1 + r / 100)
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak
        if dd > max_dd:
            max_dd = dd
    return round(max_dd * 100, 2)


def aggregate_results(trades: list[CatalystTrade]) -> CatalystBacktestResult:
    if not trades:
        return CatalystBacktestResult(
            total_trades=0, wins=0, losses=0, win_rate=0,
            avg_return_pct=0, total_return_pct=0, max_drawdown_pct=0,
            sharpe_ratio=None, avg_holding_days=0, trades=[], by_catalyst_type={},
        )

    returns = [t.return_pct for t in trades]
    wins = sum(1 for r in returns if r > 0)

    by_type: dict[str, dict] = {}
    for ctype in ("insider", "earnings_beat"):
        type_trades = [t for t in trades if t.catalyst_type == ctype]
        if type_trades:
            type_returns = [t.return_pct for t in type_trades]
            type_wins = sum(1 for r in type_returns if r > 0)
            by_type[ctype] = {
                "trades": len(type_trades),
                "win_rate": round(type_wins / len(type_trades) * 100, 1),
                "avg_return": round(sum(type_returns) / len(type_returns), 2),
                "sharpe": _calc_sharpe(type_returns),
            }

    return CatalystBacktestResult(
        total_trades=len(trades),
        wins=wins,
        losses=len(trades) - wins,
        win_rate=round(wins / len(trades) * 100, 1),
        avg_return_pct=round(sum(returns) / len(returns), 2),
        total_return_pct=round(sum(returns), 2),
        max_drawdown_pct=_calc_max_drawdown(returns),
        sharpe_ratio=_calc_sharpe(returns),
        avg_holding_days=round(sum(t.holding_days for t in trades) / len(trades), 1),
        trades=trades,
        by_catalyst_type=by_type,
    )


# ---------------------------------------------------------------------------
# Sensitivity analysis
# ---------------------------------------------------------------------------

def run_sensitivity(symbols: list[str], thresholds: list[int] | None = None) -> dict[int, dict]:
    if thresholds is None:
        thresholds = [20, 25, 30, 35, 40, 45, 50, 60]

    all_trades: list[CatalystTrade] = []
    for symbol in symbols:
        print(f"  Scanning {symbol}...")
        trades = backtest_catalyst_stock(symbol, threshold=min(thresholds))
        all_trades.extend(trades)

    results: dict[int, dict] = {}
    for thr in thresholds:
        filtered = [t for t in all_trades if t.catalyst_score >= thr]
        if not filtered:
            results[thr] = {"trades": 0, "win_rate": 0, "avg_return": 0, "sharpe": None}
            continue
        returns = [t.return_pct for t in filtered]
        wins = sum(1 for r in returns if r > 0)
        results[thr] = {
            "trades": len(filtered),
            "win_rate": round(wins / len(filtered) * 100, 1),
            "avg_return": round(sum(returns) / len(returns), 2),
            "sharpe": _calc_sharpe(returns),
        }
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

_DEFAULT_SYMBOLS = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
    "META", "TSLA", "JPM", "V", "UNH",
]


def main():
    parser = argparse.ArgumentParser(description="Backtest Strategy D (Catalyst-Driven)")
    parser.add_argument("--symbols", nargs="+", default=None)
    parser.add_argument("--threshold", type=int, default=STRATEGY_D_SCORE_THRESHOLD)
    parser.add_argument("--sensitivity", action="store_true")
    parser.add_argument("--max-days", type=int, default=MAX_HOLDING_DAYS_D)
    parser.add_argument("--sl-mult", type=float, default=STRATEGY_D_SL_ATR_MULT)
    parser.add_argument("--tp-mult", type=float, default=STRATEGY_D_TP_ATR_MULT)
    args = parser.parse_args()

    symbols = args.symbols or _DEFAULT_SYMBOLS

    if args.sensitivity:
        print(f"\n{'='*60}")
        print(f"Strategy D Sensitivity Analysis (purchase-only + post-beat)")
        print(f"Symbols: {', '.join(symbols)}")
        print(f"SL: {args.sl_mult}x ATR, TP: {args.tp_mult}x ATR, Max: {args.max_days}d")
        print(f"{'='*60}\n")

        results = run_sensitivity(symbols)

        print(f"\n{'Threshold':<12}{'Trades':<10}{'Win Rate':<12}{'Avg Return':<14}{'Sharpe':<10}")
        print("-" * 58)
        for thr, m in sorted(results.items()):
            sharpe_str = f"{m['sharpe']:.2f}" if m['sharpe'] else "N/A"
            print(f"{thr:<12}{m['trades']:<10}{m['win_rate']:.1f}%{'':>5}{m['avg_return']:+.2f}%{'':>6}{sharpe_str}")
        return

    print(f"\n{'='*60}")
    print(f"Strategy D Backtest (Purchase-Only + Post-Beat)")
    print(f"Symbols: {', '.join(symbols)}")
    print(f"Threshold: {args.threshold}")
    print(f"SL: {args.sl_mult}x ATR, TP: {args.tp_mult}x ATR, Max: {args.max_days}d")
    print(f"{'='*60}\n")

    all_trades: list[CatalystTrade] = []

    for symbol in symbols:
        print(f"\n[{symbol}]")
        trades = backtest_catalyst_stock(
            symbol, threshold=args.threshold,
            sl_mult=args.sl_mult, tp_mult=args.tp_mult, max_days=args.max_days,
        )
        all_trades.extend(trades)

        if trades:
            wins = sum(1 for t in trades if t.return_pct > 0)
            avg_ret = sum(t.return_pct for t in trades) / len(trades)
            print(f"  => {len(trades)} trades, win {wins/len(trades)*100:.0f}%, avg {avg_ret:+.2f}%")
            for t in trades:
                print(f"    {t.entry_date} [{t.catalyst_type}] {t.catalyst_detail} "
                      f"→ {t.return_pct:+.2f}% ({t.exit_reason}, {t.holding_days}d)")
        else:
            print("  => No trades")

    print(f"\n{'='*60}")
    print("AGGREGATE RESULTS")
    print(f"{'='*60}")

    result = aggregate_results(all_trades)
    print(f"Total trades: {result.total_trades}")
    print(f"Win rate:     {result.win_rate:.1f}%")
    print(f"Avg return:   {result.avg_return_pct:+.2f}%")
    print(f"Total return: {result.total_return_pct:+.2f}%")
    print(f"Max drawdown: {result.max_drawdown_pct:.1f}%")
    print(f"Sharpe ratio: {result.sharpe_ratio or 'N/A'}")
    print(f"Avg holding:  {result.avg_holding_days:.1f} days")

    if result.by_catalyst_type:
        print(f"\nBy catalyst type:")
        for ctype, m in result.by_catalyst_type.items():
            sharpe = f", sharpe {m['sharpe']:.2f}" if m.get('sharpe') else ""
            print(f"  {ctype}: {m['trades']} trades, "
                  f"win {m['win_rate']:.1f}%, avg {m['avg_return']:+.2f}%{sharpe}")


if __name__ == "__main__":
    main()
