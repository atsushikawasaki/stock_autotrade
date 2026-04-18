"""Configuration for the trade executor."""

import os
import subprocess
from dotenv import load_dotenv

load_dotenv()


def _read_keychain_secret(service: str) -> str:
    """
    Read a secret from macOS Keychain (login keychain of the current user).

    Uses `security find-generic-password -a <user> -s <service> -w`. Returns an
    empty string on any failure so callers can decide how strict to be.
    """
    try:
        user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
        if not user:
            return ""
        result = subprocess.run(
            ["security", "find-generic-password", "-a", user, "-s", service, "-w"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if result.returncode != 0:
            return ""
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


# ─── Supabase ─────────────────────────────────────────────────────────────────
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

# ─── moomoo OpenD ─────────────────────────────────────────────────────────────
OPEND_HOST = os.environ.get("OPEND_HOST", "127.0.0.1")
OPEND_PORT = int(os.environ.get("OPEND_PORT", "11111"))

# Trade password: prefer macOS Keychain (service=moomoo_trade_pwd). Falls back
# to MOOMOO_TRADE_PWD env var for compatibility / non-macOS dev environments.
# Register via: security add-generic-password -a "$USER" -s "moomoo_trade_pwd" -w
MOOMOO_TRADE_PWD = (
    _read_keychain_secret("moomoo_trade_pwd")
    or os.environ.get("MOOMOO_TRADE_PWD", "")
)

# ─── Trade Environment ────────────────────────────────────────────────────────
# "SIMULATE" for paper trading, "REAL" for live trading
TRADE_ENV = os.environ.get("TRADE_ENV", "SIMULATE")

# ─── Trading Rules ────────────────────────────────────────────────────────────
# Max % of account value per position
MAX_POSITION_PCT = float(os.environ.get("MAX_POSITION_PCT", "5"))
# Max concurrent open positions
MAX_POSITIONS = int(os.environ.get("MAX_POSITIONS", "10"))
# Symbol prefix for US stocks on moomoo
MOOMOO_SYMBOL_PREFIX = "US."

# ─── Anthropic (Claude AI) ───────────────────────────────────────────────────
# Prefer macOS Keychain (service=gemini_api_key). Falls back to env var.
# Register via: security add-generic-password -a "$USER" -s "gemini_api_key" -w
GEMINI_API_KEY = (
    _read_keychain_secret("gemini_api_key")
    or os.environ.get("GEMINI_API_KEY", "")
)

# ─── Polling ──────────────────────────────────────────────────────────────────
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "15"))
