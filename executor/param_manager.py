"""Parameter proposal and application manager.

Flow:
1. optimizer.py runs walk-forward → calls propose_params()
2. propose_params() saves to us_param_proposals + sends LINE notification
3. User reviews on dashboard and clicks Approve/Reject
4. API route calls approve_proposal() or reject_proposal()
5. approve_proposal() writes new values to us_param_proposals (status=approved)
6. Executor main loop calls apply_approved_params() once per day
7. apply_approved_params() reads approved proposals and updates constants at runtime
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from supabase import create_client

from config import SUPABASE_URL, SUPABASE_SERVICE_KEY
import constants
import notifier

log = logging.getLogger("param_manager")

sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# Maps proposal param keys to constants module attribute names
_PARAM_TO_CONSTANT = {
    "breakout_lookback": "STRATEGY_A_BREAKOUT_LOOKBACK",
    "rsi_min": "STRATEGY_A_RSI_MIN",
    "rsi_max": "STRATEGY_A_RSI_MAX",
    "volume_ratio_min": "STRATEGY_A_VOLUME_RATIO_MIN",
    "sl_atr_mult": "STRATEGY_A_SL_ATR_MULT",
    "tp_atr_mult": "STRATEGY_A_TP_ATR_MULT",
    "adx_min": "STRATEGY_A_ADX_MIN",
}


def _get_current_params() -> dict:
    """Read current Strategy A parameters from constants module."""
    return {
        key: getattr(constants, const_name)
        for key, const_name in _PARAM_TO_CONSTANT.items()
    }


def propose_params(
    proposed: dict,
    metrics: dict,
    method: str = "walk_forward",
    strategy: str = "strategy_a",
) -> str | None:
    """Create a parameter change proposal and notify via LINE.

    Args:
        proposed: dict of param keys to new values
        metrics: OOS metrics (win_rate, avg_return, sharpe, robustness, etc.)
        method: optimization method used
        strategy: which strategy

    Returns:
        proposal ID or None on failure.
    """
    current = _get_current_params()

    # Only propose if something actually changed
    changes = {k: v for k, v in proposed.items() if current.get(k) != v}
    if not changes:
        log.info("[PARAM] No parameter changes to propose")
        return None

    try:
        result = sb.table("us_param_proposals").insert({
            "strategy": strategy,
            "current_params": current,
            "proposed_params": proposed,
            "optimization_method": method,
            "metrics": metrics,
            "status": "pending",
        }).execute()

        proposal_id = result.data[0]["id"]
        log.info("[PARAM] Proposal created: %s", proposal_id)

        # LINE notification
        _notify_proposal(current, proposed, changes, metrics, method)

        return proposal_id
    except Exception as e:
        log.error("[PARAM] Failed to create proposal: %s", e)
        return None


def _notify_proposal(
    current: dict, proposed: dict, changes: dict, metrics: dict, method: str,
) -> None:
    """Send LINE notification with proposal summary."""
    lines = [f"[Param Proposal] {method}"]
    lines.append("")

    for key, new_val in changes.items():
        old_val = current.get(key, "?")
        lines.append(f"  {key}: {old_val} -> {new_val}")

    lines.append("")
    lines.append(f"OOS Trades: {metrics.get('total_trades', '?')}")
    lines.append(f"OOS WinRate: {metrics.get('win_rate', '?'):.1f}%")
    lines.append(f"OOS AvgReturn: {metrics.get('avg_return', '?'):.2f}%")

    sharpe = metrics.get("sharpe")
    if sharpe is not None:
        lines.append(f"OOS Sharpe: {sharpe:.2f}")

    robustness = metrics.get("robustness")
    if robustness is not None:
        lines.append(f"Robustness: {robustness:.2f}")

    lines.append("")
    lines.append("Approve/Reject on dashboard")

    notifier._send("\n".join(lines))


def approve_proposal(proposal_id: str) -> bool:
    """Mark a proposal as approved."""
    try:
        sb.table("us_param_proposals").update({
            "status": "approved",
            "approved_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", proposal_id).eq("status", "pending").execute()
        log.info("[PARAM] Proposal %s approved", proposal_id)
        return True
    except Exception as e:
        log.error("[PARAM] Failed to approve %s: %s", proposal_id, e)
        return False


def reject_proposal(proposal_id: str) -> bool:
    """Mark a proposal as rejected."""
    try:
        sb.table("us_param_proposals").update({
            "status": "rejected",
        }).eq("id", proposal_id).eq("status", "pending").execute()
        log.info("[PARAM] Proposal %s rejected", proposal_id)
        return True
    except Exception as e:
        log.error("[PARAM] Failed to reject %s: %s", proposal_id, e)
        return False


def apply_approved_params() -> int:
    """Apply all approved proposals by updating runtime constants.

    Returns count of proposals applied.
    """
    result = (
        sb.table("us_param_proposals")
        .select("*")
        .eq("status", "approved")
        .order("approved_at")
        .execute()
    )
    proposals = result.data or []
    if not proposals:
        return 0

    applied = 0
    for p in proposals:
        proposed = p["proposed_params"]
        strategy = p["strategy"]

        if strategy != "strategy_a":
            log.warning("[PARAM] Unsupported strategy %s, skipping", strategy)
            continue

        # Apply each parameter to the constants module at runtime
        for key, value in proposed.items():
            const_name = _PARAM_TO_CONSTANT.get(key)
            if const_name is None:
                continue
            old_val = getattr(constants, const_name)
            setattr(constants, const_name, type(old_val)(value))
            log.info("[PARAM] %s: %s -> %s", const_name, old_val, value)

        # Mark as applied
        sb.table("us_param_proposals").update({
            "status": "applied",
        }).eq("id", p["id"]).execute()
        applied += 1

    if applied > 0:
        log.info("[PARAM] Applied %d proposal(s)", applied)
        notifier._send(f"[Params Applied] {applied} proposal(s) activated")

    return applied
