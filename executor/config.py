"""Configuration for the trade executor."""

import os
from dotenv import load_dotenv

load_dotenv()

# ─── Supabase ─────────────────────────────────────────────────────────────────
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

# ─── moomoo OpenD ─────────────────────────────────────────────────────────────
OPEND_HOST = os.environ.get("OPEND_HOST", "127.0.0.1")
OPEND_PORT = int(os.environ.get("OPEND_PORT", "11111"))
MOOMOO_TRADE_PWD = os.environ.get("MOOMOO_TRADE_PWD", "")

# ─── Trading Rules ────────────────────────────────────────────────────────────
# Max % of account value per position
MAX_POSITION_PCT = float(os.environ.get("MAX_POSITION_PCT", "5"))
# Max concurrent open positions
MAX_POSITIONS = int(os.environ.get("MAX_POSITIONS", "10"))
# Symbol prefix for US stocks on moomoo
MOOMOO_SYMBOL_PREFIX = "US."

# ─── Polling ──────────────────────────────────────────────────────────────────
POLL_INTERVAL_SECONDS = 60
