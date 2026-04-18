"""Strategy D: Catalyst-driven signal generation.

Scans for fundamental catalysts (insider buying, earnings momentum,
news sentiment) and generates entry signals WITHOUT requiring technical
breakout confirmation. This allows earlier entries at better prices.

Data sources:
1. SEC EDGAR Form 4 XML (insider transactions) — parses actual filings
   to filter open-market purchases only (transaction code "P")
2. Earnings beat momentum — enters AFTER confirmed beat (next trading day)
3. News sentiment — via yfinance headlines + Gemini scoring
"""

from __future__ import annotations

import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError

import yfinance as yf

from constants import (
    STRATEGY_D_ENABLED,
    STRATEGY_D_SCORE_THRESHOLD,
    STRATEGY_D_SL_ATR_MULT,
    STRATEGY_D_TP_ATR_MULT,
    STRATEGY_D_POSITION_SCALE,
    STRATEGY_D_INSIDER_LOOKBACK_DAYS,
    STRATEGY_D_EARNINGS_NEAR_DAYS,
    SCORE_D_GRADE_A_MIN,
    SCORE_D_GRADE_B_MIN,
    SCORE_D_GRADE_C_MIN,
)

log = logging.getLogger("catalyst_scanner")

# SEC EDGAR requires a User-Agent header with contact info
_SEC_USER_AGENT = "StockTradeBot/1.0 (personal research)"
_SEC_REQUEST_INTERVAL = 0.5  # SEC fair-use: max 10 req/sec


@dataclass(frozen=True)
class InsiderSignal:
    role: str           # "CEO", "CFO", "VP", "Director", "Officer"
    title: str          # full officer title
    shares: int
    value_usd: float
    filed_date: str     # ISO date string
    tx_code: str        # "P" = open-market purchase


@dataclass(frozen=True)
class CatalystResult:
    insider_score: int
    earnings_score: int
    news_score: int
    total_score: int
    details: dict       # raw detail for logging/storage


@dataclass(frozen=True)
class StrategyDSignal:
    stock_code: str
    strategy: str       # "strategy_d"
    score: int
    grade: str
    entry_price: float
    stop_loss: float
    take_profit: float
    reason: str
    indicators: dict
    position_scale: float


# ---------------------------------------------------------------------------
# SEC EDGAR helpers
# ---------------------------------------------------------------------------

_INSIDER_ROLE_SCORES = {
    "CEO": 40,
    "CFO": 40,
    "COO": 35,
    "President": 35,
    "VP": 30,
    "Director": 30,
    "Officer": 25,
}

_last_sec_request: float = 0.0


def _sec_throttle() -> None:
    """Respect SEC EDGAR rate limit."""
    global _last_sec_request
    elapsed = time.time() - _last_sec_request
    if elapsed < _SEC_REQUEST_INTERVAL:
        time.sleep(_SEC_REQUEST_INTERVAL - elapsed)
    _last_sec_request = time.time()


def _sec_fetch(url: str, timeout: int = 10) -> bytes | None:
    """Fetch a URL from SEC EDGAR with rate limiting."""
    _sec_throttle()
    try:
        req = Request(url, headers={"User-Agent": _SEC_USER_AGENT})
        with urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except (URLError, OSError) as e:
        log.debug("[SEC] Fetch failed: %s — %s", url, e)
        return None


def _classify_role(title: str) -> str:
    """Classify insider role from officer title string."""
    t = title.upper()
    if "CEO" in t or "CHIEF EXECUTIVE" in t:
        return "CEO"
    if "CFO" in t or "CHIEF FINANCIAL" in t:
        return "CFO"
    if "COO" in t or "CHIEF OPERATING" in t:
        return "COO"
    if "PRESIDENT" in t:
        return "President"
    if "VP" in t or "VICE PRESIDENT" in t:
        return "VP"
    if "DIRECTOR" in t:
        return "Director"
    return "Officer"


# ---------------------------------------------------------------------------
# Form 4 XML detailed parsing (purchase-only filter)
# ---------------------------------------------------------------------------

def _parse_form4_xml(xml_data: bytes) -> list[dict]:
    """
    Parse a Form 4 XML filing for open-market purchases.

    Returns list of {role, title, shares, value_usd, tx_code, date}.
    Only includes transactions with code "P" (open-market purchase).
    Excludes: M (option exercise), A (grant/award), S (sale), G (gift).
    """
    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError:
        return []

    # Extract reporting owner info
    owner_el = root.find(".//reportingOwnerRelationship")
    officer_title = ""
    if owner_el is not None:
        title_el = owner_el.find("officerTitle")
        officer_title = title_el.text.strip() if title_el is not None and title_el.text else ""
        # Check isDirector if no officer title
        if not officer_title:
            is_dir = owner_el.find("isDirector")
            if is_dir is not None and is_dir.text and is_dir.text.strip() == "true":
                officer_title = "Director"

    role = _classify_role(officer_title) if officer_title else "Officer"

    purchases: list[dict] = []

    # Check nonDerivativeTransaction entries
    for tx in root.findall(".//nonDerivativeTransaction"):
        coding = tx.find("transactionCoding")
        if coding is None:
            continue

        code_el = coding.find("transactionCode")
        tx_code = code_el.text.strip() if code_el is not None and code_el.text else ""

        # Only open-market purchases
        if tx_code != "P":
            continue

        # Verify it's an acquisition (A), not disposition (D)
        acq_disp = tx.find(".//transactionAcquiredDisposedCode/value")
        if acq_disp is not None and acq_disp.text and acq_disp.text.strip() != "A":
            continue

        # Extract shares
        shares_el = tx.find(".//transactionShares/value")
        shares = 0
        if shares_el is not None and shares_el.text:
            try:
                shares = int(float(shares_el.text.strip()))
            except (ValueError, TypeError):
                pass

        # Extract price per share
        price_el = tx.find(".//transactionPricePerShare/value")
        price = 0.0
        if price_el is not None and price_el.text:
            try:
                price = float(price_el.text.strip())
            except (ValueError, TypeError):
                pass

        value_usd = shares * price

        # Extract transaction date
        date_el = tx.find(".//transactionDate/value")
        date_str = date_el.text.strip() if date_el is not None and date_el.text else ""

        purchases.append({
            "role": role,
            "title": officer_title,
            "shares": shares,
            "value_usd": value_usd,
            "tx_code": tx_code,
            "date": date_str,
        })

    return purchases


def scan_insider_buying(symbol: str) -> tuple[int, list[InsiderSignal]]:
    """
    Check SEC EDGAR for recent open-market insider purchases.

    Fetches Atom feed → index pages → Form 4 XML → filters P (purchase) only.
    Returns (score, list_of_signals).
    """
    if not STRATEGY_D_ENABLED:
        return 0, []

    # Step 1: Fetch Atom feed for recent Form 4 filings
    atom_url = (
        f"https://www.sec.gov/cgi-bin/browse-edgar"
        f"?action=getcompany&CIK={symbol}&type=4"
        f"&dateb=&owner=include&count=10&output=atom"
    )
    atom_data = _sec_fetch(atom_url)
    if atom_data is None:
        return 0, []

    try:
        root = ET.fromstring(atom_data)
    except ET.ParseError:
        return 0, []

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries = root.findall("atom:entry", ns)

    cutoff = datetime.now(timezone.utc) - timedelta(days=STRATEGY_D_INSIDER_LOOKBACK_DAYS)
    signals: list[InsiderSignal] = []

    for entry in entries:
        # Check filing date
        updated_el = entry.find("atom:updated", ns)
        if updated_el is None or updated_el.text is None:
            continue

        try:
            filed = datetime.fromisoformat(updated_el.text.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue

        if filed < cutoff:
            continue

        # Step 2: Get filing index page URL
        link_el = entry.find("atom:link", ns)
        if link_el is None:
            continue
        index_url = link_el.get("href", "")
        if not index_url:
            continue

        # Step 3: Fetch index page and find form4.xml link
        index_data = _sec_fetch(index_url)
        if index_data is None:
            continue

        index_html = index_data.decode("utf-8", errors="replace")
        # Find the raw XML (not the XSLT-transformed one)
        xml_matches = re.findall(r'href="([^"]+/form4\.xml)"', index_html)
        if not xml_matches:
            # Try alternative patterns
            xml_matches = re.findall(r'href="([^"]+\.xml)"', index_html)
            # Filter out xsl-transformed versions
            xml_matches = [m for m in xml_matches if "xsl" not in m.lower()]

        if not xml_matches:
            continue

        # Step 4: Fetch and parse the Form 4 XML
        xml_path = xml_matches[-1]  # last match is usually the raw XML
        if xml_path.startswith("/"):
            xml_url = f"https://www.sec.gov{xml_path}"
        else:
            # Relative URL — derive base from index URL
            base = index_url.rsplit("/", 1)[0]
            xml_url = f"{base}/{xml_path}"

        form4_data = _sec_fetch(xml_url)
        if form4_data is None:
            continue

        purchases = _parse_form4_xml(form4_data)

        for p in purchases:
            signals.append(InsiderSignal(
                role=p["role"],
                title=p["title"],
                shares=p["shares"],
                value_usd=p["value_usd"],
                filed_date=filed.strftime("%Y-%m-%d"),
                tx_code=p["tx_code"],
            ))

    if not signals:
        return 0, []

    # Scoring — only genuine open-market purchases reach here
    score = 0
    roles_seen: set[str] = set()
    total_value = 0.0

    for sig in signals:
        role_score = _INSIDER_ROLE_SCORES.get(sig.role, 20)
        if sig.role not in roles_seen:
            score += role_score
            roles_seen.add(sig.role)
        total_value += sig.value_usd

    # Multiple insiders bonus
    if len(signals) >= 3:
        score += 15
    elif len(signals) >= 2:
        score += 10

    # Large purchase bonus (>$500K total)
    if total_value >= 500_000:
        score += 10
    elif total_value >= 100_000:
        score += 5

    log.info(
        "[INSIDER] %s: %d purchases, roles=%s, value=$%s, score=%d",
        symbol, len(signals), list(roles_seen),
        f"{total_value:,.0f}" if total_value > 0 else "unknown",
        score,
    )
    return score, signals


# ---------------------------------------------------------------------------
# Earnings beat momentum (post-beat entry)
# ---------------------------------------------------------------------------

def scan_earnings_momentum(symbol: str) -> tuple[int, dict]:
    """
    Score based on recent earnings beat history.

    Strategy: Enter AFTER a confirmed earnings beat, riding post-beat
    momentum. This is safer than pre-earnings entry because the outcome
    is known.

    Triggers if:
    - Most recent earnings was a beat (positive surprise)
    - Company has a pattern of consecutive beats
    - Earnings were reported within the last EARNINGS_NEAR_DAYS

    Returns (score, details_dict).
    """
    details: dict = {}
    try:
        ticker = yf.Ticker(symbol)

        # Check earnings history for recent beats
        hist = ticker.earnings_history
        if hist is None or hist.empty:
            return 0, details

        recent = hist.tail(4)
        if recent.empty:
            return 0, details

        # Check if last earnings was a beat
        last_row = recent.iloc[-1]
        last_surprise = last_row.get("surprisePercent")
        if last_surprise is None:
            return 0, details

        last_surprise_val = float(last_surprise)
        if last_surprise_val <= 0:
            return 0, details  # Last earnings was a miss — no signal

        # Check report date freshness
        report_date = last_row.get("reportDate") or last_row.name
        try:
            import pandas as pd
            if isinstance(report_date, (datetime, pd.Timestamp)):
                report_dt = report_date
                if hasattr(report_dt, "tzinfo") and report_dt.tzinfo is None:
                    report_dt = report_dt.replace(tzinfo=timezone.utc)
            else:
                report_dt = datetime.fromisoformat(str(report_date)[:10]).replace(tzinfo=timezone.utc)

            days_since = (datetime.now(timezone.utc) - report_dt).days
        except (ValueError, TypeError):
            days_since = 999

        details["last_surprise_pct"] = round(last_surprise_val, 2)
        details["days_since_report"] = days_since

        # Only trigger if earnings were within last N days
        if days_since > STRATEGY_D_EARNINGS_NEAR_DAYS:
            return 0, details

        # Count consecutive beats
        consecutive = 0
        for i in range(len(recent) - 1, -1, -1):
            row = recent.iloc[i]
            s = row.get("surprisePercent")
            if s is not None and float(s) > 0:
                consecutive += 1
            else:
                break

        details["consecutive_beats"] = consecutive
        details["last_report_date"] = str(report_date)[:10]

        # Scoring
        score = 0
        if consecutive >= 4:
            score = 35  # 4+ consecutive beats — very strong
        elif consecutive >= 3:
            score = 30
        elif consecutive >= 2:
            score = 25
        else:
            score = 20  # Single beat (most recent)

        # Bonus for large surprise
        if last_surprise_val >= 20:
            score += 10  # Massive beat (>20%)
        elif last_surprise_val >= 10:
            score += 5

        details["earnings_score"] = score
        return score, details

    except Exception as e:
        log.warning("[CATALYST] Earnings scan failed for %s: %s", symbol, e)
        return 0, details


# ---------------------------------------------------------------------------
# News sentiment scoring (via Gemini)
# ---------------------------------------------------------------------------

_news_cache: dict[str, tuple[int, float]] = {}  # symbol -> (score, timestamp)
_NEWS_CACHE_TTL = 86400  # 24 hours


def score_news_sentiment(symbol: str) -> tuple[int, dict]:
    """
    Score recent news sentiment using Gemini API.

    Returns (score, details). Returns 0 if no strong signal.
    Returns -999 if clearly negative (blocks signal generation).
    """
    cached = _news_cache.get(symbol)
    if cached and time.time() - cached[1] < _NEWS_CACHE_TTL:
        return cached[0], {"cached": True}

    details: dict = {}
    try:
        ticker = yf.Ticker(symbol)
        news = ticker.get_news()
        if not news:
            return 0, details

        headlines = [
            item.get("title", "") for item in news[:5] if item.get("title")
        ]
        if not headlines:
            return 0, details

        details["headlines"] = headlines

        # Use Gemini for sentiment analysis
        from claude_validator import _get_client, _check_budget, _record_call
        from constants import GEMINI_MODEL

        client = _get_client()
        if client is None or not _check_budget():
            score = _keyword_sentiment(headlines)
            _news_cache[symbol] = (score, time.time())
            return score, details

        prompt = (
            "Analyze these stock news headlines for trading sentiment. "
            "Rate as: strong_positive (major contract, FDA approval, "
            "acquisition target), positive, neutral, negative, "
            "strong_negative (lawsuit, SEC investigation, downgrade).\n\n"
            f"Stock: {symbol}\n"
            f"Headlines:\n" + "\n".join(f"- {h}" for h in headlines) + "\n\n"
            "Respond with ONLY JSON: "
            '{"sentiment": "strong_positive|positive|neutral|negative|strong_negative", '
            '"reasoning": "brief"}'
        )

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config={
                "max_output_tokens": 128,
                "response_mime_type": "application/json",
            },
        )
        _record_call()

        parsed = json.loads(response.text.strip())
        sentiment = parsed.get("sentiment", "neutral")
        details["sentiment"] = sentiment
        details["reasoning"] = parsed.get("reasoning", "")

        score_map = {
            "strong_positive": 25,
            "positive": 15,
            "neutral": 0,
            "negative": -999,
            "strong_negative": -999,
        }
        score = score_map.get(sentiment, 0)
        _news_cache[symbol] = (score, time.time())
        return score, details

    except Exception as e:
        log.warning("[CATALYST] News sentiment failed for %s: %s", symbol, e)
        return 0, details


def _keyword_sentiment(headlines: list[str]) -> int:
    """Simple keyword-based sentiment fallback when Gemini is unavailable."""
    text = " ".join(headlines).lower()

    negative_keywords = [
        "lawsuit", "sued", "sec investigation", "downgrade",
        "recall", "fraud", "bankruptcy", "layoff", "miss",
    ]
    positive_keywords = [
        "upgrade", "approval", "beat", "record revenue",
        "contract", "acquisition", "partnership", "fda approv",
    ]

    neg_count = sum(1 for kw in negative_keywords if kw in text)
    pos_count = sum(1 for kw in positive_keywords if kw in text)

    if neg_count >= 2:
        return -999
    if pos_count >= 2:
        return 20
    if pos_count >= 1:
        return 10
    return 0


# ---------------------------------------------------------------------------
# Unified catalyst scoring
# ---------------------------------------------------------------------------

def compute_catalyst_score(symbol: str) -> CatalystResult:
    """Compute unified catalyst score from all data sources."""
    insider_score, insider_signals = scan_insider_buying(symbol)
    earnings_score, earnings_details = scan_earnings_momentum(symbol)
    news_score, news_details = score_news_sentiment(symbol)

    # Negative news blocks the entire signal
    if news_score == -999:
        return CatalystResult(
            insider_score=insider_score,
            earnings_score=earnings_score,
            news_score=0,
            total_score=0,
            details={
                "blocked": True,
                "block_reason": "negative_news",
                "news": news_details,
            },
        )

    total = insider_score + earnings_score + news_score

    return CatalystResult(
        insider_score=insider_score,
        earnings_score=earnings_score,
        news_score=news_score,
        total_score=total,
        details={
            "insider_purchases": len(insider_signals),
            "insider_roles": [s.role for s in insider_signals],
            "insider_value_usd": sum(s.value_usd for s in insider_signals),
            "earnings": earnings_details,
            "news": news_details,
        },
    )


def _assign_grade(score: int) -> str:
    """Assign grade based on catalyst score."""
    if score >= SCORE_D_GRADE_A_MIN:
        return "A"
    if score >= SCORE_D_GRADE_B_MIN:
        return "B"
    if score >= SCORE_D_GRADE_C_MIN:
        return "C"
    return "D"


# ---------------------------------------------------------------------------
# Signal generation
# ---------------------------------------------------------------------------

def _compute_atr(symbol: str) -> float | None:
    """Fetch ATR(14) for position sizing and SL/TP calculation."""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="30d")
        if hist is None or len(hist) < 15:
            return None

        highs = hist["High"].tolist()
        lows = hist["Low"].tolist()
        closes = hist["Close"].tolist()

        trs: list[float] = []
        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            trs.append(tr)

        if len(trs) < 14:
            return None
        return sum(trs[-14:]) / 14
    except Exception:
        return None


def generate_signal(symbol: str, catalyst: CatalystResult) -> StrategyDSignal | None:
    """Generate a Strategy D signal if catalyst score meets threshold."""
    if catalyst.total_score < STRATEGY_D_SCORE_THRESHOLD:
        return None

    grade = _assign_grade(catalyst.total_score)

    # Get current price for entry
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info
        current_price = getattr(info, "last_price", None)
        if current_price is None:
            current_price = getattr(info, "previous_close", None)
        if current_price is None or current_price <= 0:
            return None
        current_price = float(current_price)
    except Exception as e:
        log.warning("[CATALYST] Price fetch failed for %s: %s", symbol, e)
        return None

    # ATR for SL/TP
    atr = _compute_atr(symbol)
    if atr is None or atr <= 0:
        return None

    stop_loss = round(current_price - STRATEGY_D_SL_ATR_MULT * atr, 2)
    take_profit = round(current_price + STRATEGY_D_TP_ATR_MULT * atr, 2)

    # Build reason string
    reasons: list[str] = []
    if catalyst.insider_score > 0:
        roles = catalyst.details.get("insider_roles", [])
        n = catalyst.details.get("insider_purchases", 0)
        val = catalyst.details.get("insider_value_usd", 0)
        val_str = f" ${val:,.0f}" if val > 0 else ""
        reasons.append(f"Insider purchase ({', '.join(set(roles[:3]))}, {n}x{val_str})")
    if catalyst.earnings_score > 0:
        ed = catalyst.details.get("earnings", {})
        beats = ed.get("consecutive_beats", 0)
        surprise = ed.get("last_surprise_pct", 0)
        reasons.append(f"Earnings beat ({beats}Q streak, +{surprise}%)")
    if catalyst.news_score > 0:
        reasons.append("Positive news sentiment")

    return StrategyDSignal(
        stock_code=symbol,
        strategy="strategy_d",
        score=catalyst.total_score,
        grade=grade,
        entry_price=round(current_price, 2),
        stop_loss=stop_loss,
        take_profit=take_profit,
        reason=" + ".join(reasons),
        indicators={
            "atr": round(atr, 4),
            "catalyst_insider": catalyst.insider_score,
            "catalyst_earnings": catalyst.earnings_score,
            "catalyst_news": catalyst.news_score,
            "catalyst_total": catalyst.total_score,
        },
        position_scale=STRATEGY_D_POSITION_SCALE,
    )


# ---------------------------------------------------------------------------
# Main scan entry point
# ---------------------------------------------------------------------------

def run_catalyst_scan(symbols: list[str]) -> list[StrategyDSignal]:
    """
    Run catalyst scan on a list of symbols.

    Returns list of StrategyDSignal for symbols that meet threshold.
    Called periodically from main.py.
    """
    if not STRATEGY_D_ENABLED:
        return []

    signals: list[StrategyDSignal] = []

    for symbol in symbols:
        try:
            catalyst = compute_catalyst_score(symbol)

            if catalyst.total_score < STRATEGY_D_SCORE_THRESHOLD:
                continue

            signal = generate_signal(symbol, catalyst)
            if signal is not None:
                log.info(
                    "[CATALYST] %s score:%d grade:%s — %s",
                    symbol, signal.score, signal.grade, signal.reason,
                )
                signals.append(signal)

        except Exception as e:
            log.warning("[CATALYST] Error scanning %s: %s", symbol, e)

    return signals
