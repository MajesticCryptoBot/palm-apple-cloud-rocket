import os
import sys
import io
import aiohttp
import re
import requests 
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import torch
import pandas as pd
import asyncio
import math
import json
import csv
import pytz
import warnings
import platform
import time
from datetime import datetime, timedelta, timezone
import shutil
from collections import defaultdict
from telegram import Update, Bot
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.events import EVENT_JOB_ERROR
from logging.handlers import RotatingFileHandler
from binance.async_client import AsyncClient
from binance.exceptions import BinanceAPIException
import numpy as np
import contextvars

try:
    import openpyxl
    from openpyxl.styles import PatternFill
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False

binance_client = None
live_client = None             # New: for fallback metrics
USE_LIVE_FALLBACK = True       # Master switch

analyzer = SentimentIntensityAnalyzer()


# Active lane for THIS asyncio task only. Default USDT keeps Isaac and the
# original command set on the original state file and log.
ACTIVE_SLOT = contextvars.ContextVar("abin_active_slot", default="USDT")


class LaneRotatingFileHandler(RotatingFileHandler):
    """Write AAA.log only while the USDT lane (or Isaac / startup) is active,
    and AAA_USDC.log only while the USDC lane is active."""

    def __init__(self, filename, lane, **kwargs):
        super().__init__(filename, **kwargs)
        self.lane = lane

    def emit(self, record):
        try:
            current = ACTIVE_SLOT.get()
        except Exception:
            current = "USDT"
        if self.lane == "USDC" and current != "USDC":
            return
        if self.lane == "USDT" and current == "USDC":
            return
        super().emit(record)


class _LaneFloat:
    """Separate USDT and USDC capital that still behaves like the original float.

    Reads and in-place += follow ACTIVE_SLOT. Isaac runs on the default USDT
    slot, so its MAIN_ALLOCATED_USDT += profit path is unchanged.
    """

    def __init__(self, usdt, usdc):
        self.usdt = float(usdt)
        self.usdc = float(usdc)

    def get(self, lane=None):
        if lane == "USDC":
            return float(self.usdc)
        if lane == "USDT":
            return float(self.usdt)
        return float(self.usdc if ACTIVE_SLOT.get() == "USDC" else self.usdt)

    def set(self, value, lane=None):
        if lane is None:
            lane = "USDC" if ACTIVE_SLOT.get() == "USDC" else "USDT"
        if lane == "USDC":
            self.usdc = float(value)
        else:
            self.usdt = float(value)

    def __float__(self):
        return self.get()

    def __int__(self):
        return int(self.get())

    def __str__(self):
        return str(self.get())

    def __repr__(self):
        return f"_LaneFloat(USDT={self.usdt}, USDC={self.usdc})"

    def __format__(self, spec):
        return format(self.get(), spec)

    def __iadd__(self, other):
        self.set(self.get() + float(other))
        return self

    def __isub__(self, other):
        self.set(self.get() - float(other))
        return self

    def __add__(self, other):
        return self.get() + float(other)

    def __radd__(self, other):
        return float(other) + self.get()

    def __sub__(self, other):
        return self.get() - float(other)

    def __rsub__(self, other):
        return float(other) - self.get()

    def __mul__(self, other):
        return self.get() * float(other)

    def __rmul__(self, other):
        return float(other) * self.get()

    def __truediv__(self, other):
        return self.get() / float(other)

    def __rtruediv__(self, other):
        return float(other) / self.get()

    def __lt__(self, other):
        return self.get() < float(other)

    def __le__(self, other):
        return self.get() <= float(other)

    def __gt__(self, other):
        return self.get() > float(other)

    def __ge__(self, other):
        return self.get() >= float(other)

    def __eq__(self, other):
        try:
            return self.get() == float(other)
        except Exception:
            return False

    def __neg__(self):
        return -self.get()

    def __bool__(self):
        return self.get() != 0.0

    def __round__(self, n=0):
        return round(self.get(), n)

    def __floor__(self):
        return math.floor(self.get())

    def __ceil__(self):
        return math.ceil(self.get())


class SafeLogHandler(logging.StreamHandler):
    def emit(self, record):
        try:
            msg = self.format(record)
            if hasattr(sys.stdout, 'buffer'):
                # Binary mode writing for Windows
                sys.stdout.buffer.write(msg.encode('utf-8') + self.terminator.encode('utf-8'))
                sys.stdout.buffer.flush()  # Force flush after each log
            else:
                # Fallback for non-Windows
                self.stream.write(msg + self.terminator)
                self.flush()
        except Exception:
            self.handleError(record)

os.system("title ABinance Trading Bot")

# Set WindowsSelectorEventLoopPolicy immediately on Windows
if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())   

async def check_prerequisites(update: Update, context: ContextTypes.DEFAULT_TYPE, checks: dict) -> bool:
    """
    Check prerequisites for a command and send warnings if unmet.
    checks: Dict with keys 'pair', and values as error messages.
    Returns: True if all checks pass, False otherwise.
    """
    bot = update.get_bot()
    for key, message in checks.items():
        if key == "pair" and not active_symbol():
            if ACTIVE_SLOT.get() == "USDC" and message == "Set a trading pair with /pair first":
                message = "Set a trading pair with /pair2 first"
            logger.warning(f"Prerequisite failed: {message}")
            await send_telegram_message(bot, message)
            return False
    return True

# Binance Demo credentials
BINANCE_API_KEY = "yMMIIjGtgFrZ83s171vKCU0KgUU7NsxmMXKdfOg9XG7EIQ14uDB4Flqntnpc6iuq"
BINANCE_SECRET = "EziRRL1EKFDBRLphSgnrwJr2rRRb8TUKU6K46VFIEM1w7FBL6n7CBJlYOei94vg6"

# Telegram credentials
TELEGRAM_TOKEN = "7613189849:AAE9RSeHeFXSSpkAxtNZErLa3O9EBTmNuuE"
TELEGRAM_USER_ID = "5704509563"

# Save PID to a file
PID_FILE = os.path.join(r"C:\Users\pauld\Desktop\IG", f"{__file__.split('.')[0]}_pid.txt")
with open(PID_FILE, "w") as f:
    f.write(str(os.getpid()))

# Suppress warnings
warnings.filterwarnings("ignore", category=UserWarning)

# Configure logging: INFO+ to file, INFO to CMD for debugging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# File handlers with rotation (10MB per file, 5 backups).
# USDT + Isaac + startup -> AAA.log. USDC lane -> AAA_USDC.log.
_log_fmt = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler = LaneRotatingFileHandler('AAA.log', 'USDT', maxBytes=10*1024*1024, backupCount=5)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(_log_fmt)
file_handler_usdc = LaneRotatingFileHandler('AAA_USDC.log', 'USDC', maxBytes=10*1024*1024, backupCount=5)
file_handler_usdc.setLevel(logging.DEBUG)
file_handler_usdc.setFormatter(_log_fmt)

# Safe console handler for Windows
console_handler = SafeLogHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

# Add handlers
logger.addHandler(file_handler)
logger.addHandler(file_handler_usdc)
logger.addHandler(console_handler)

# Suppress noisy library logs
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("ccxt").setLevel(logging.WARNING)


async def create_binance_clients():
    global binance_client, live_client

    # 1. TESTNET client (authenticated – all trading / balances / orders)
    if binance_client is None:
        binance_client = await AsyncClient.create(
            api_key=BINANCE_API_KEY,
            api_secret=BINANCE_SECRET,
            testnet=True,
            requests_params={'timeout': 10}
        )
        await binance_client.get_exchange_info()
        logger.info("TESTNET Binance client created")

    # 2. LIVE client – PUBLIC ONLY (no API key / secret)
    # Used solely for metrics fallback + live price. No trading possible.
    if live_client is None:
        live_client = await AsyncClient.create(
            # deliberately no api_key / api_secret
            testnet=False,
            requests_params={'timeout': 10}
        )
        # Public call to confirm connectivity
        await live_client.get_exchange_info()
        logger.info("LIVE Binance client created (public data only – no keys)")


async def create_binance_client():
    """
    Compatibility wrapper so all existing calls still work.
    """
    await create_binance_clients()
    return binance_client

# Global variables
SYMBOL = None
SYMBOL2 = None          # USDC lane symbol (/pair2). Equal to SYMBOL, not secondary.
LAST_SYMBOL2 = None
MIN_TRADE_QUANTITY = 0.0
STEP_SIZE = 0.0
MIN_NOTIONAL = 0.0
SELL_MULTIPLIER_UP = 10.0
BUY_MULTIPLIER_DOWN = 0.1
LAST_SYMBOL = None
pre_orders = {}
open_orders = []
symbol_info_cache = {}
state_lock = asyncio.Lock()

# ISAAC Spot DCA (Martingale) Config
ISAAC_DCA_ENABLED = True  
ISAAC_DCA_SYMBOL = 'NEAR/USDT'  
ISAAC_DCA_INITIAL_USDT = 5000.0  
ISAAC_DCA_SIZE_MULTIPLIER = 1.5  
ISAAC_DCA_MAX_ORDERS = 7  
#ISAAC_DCA_TP_PCT = 2.5  
ISAAC_DCA_MAX_POSITION_PCT = 0.6  
ISAAC_DCA_CHECK_INTERVAL_MIN = 1
DCA_MIN_USDT = 100.0  # Pause if alloc < this (safety floor)
# ==================== CAPITAL ALLOCATION (Dedicated Pools) ====================
MAIN_ALLOCATED_USDT = _LaneFloat(5000.0, 5000.0)
RESCUE_ALLOCATED_USDT = 20000.0     # Dedicated for rescue / averaging down (USDT lane)
RESCUE_ALLOCATED_USDC = 20000.0     # Equal rescue pool for the USDC lane
ISAAC_ALLOCATED_USDT = 36500.0

# ==================== COMPOUNDING & HISTORY TRACKING ====================
COMPOUNDING_HISTORY_FILE = "compounding_historyABINANCE.json"
compounding_history = []  # List of all events (USDT lane + Isaac)
COMPOUNDING_HISTORY_FILE_USDC = "compounding_historyABINANCE_USDC.json"
compounding_history_usdc = []  # USDC lane only. Isaac never writes here.

# Live Excel tracker (same folder as this script). Auto-filled for USDT profits only.
EXCEL_TRACKER_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "ABINANCE_Live_Tracker.xlsx",
)
# Section 2 on "Live Tracker" sheet: yellow input rows B22:G36
_EXCEL_SECTION2_FIRST_ROW = 22
_EXCEL_SECTION2_LAST_ROW = 36

# API rate limiting variables
API_CALL_COUNT = 0
API_CALL_WINDOW_START = time.time()
API_RATE_LIMIT_THRESHOLD = 800  # Increased from 120 

# State file path
STATE_FILE = "AAA.json"
STATE_FILE_USDC = "AAA_USDC.json"  # USDC lane state. Never read by Isaac.

ISAAC_STATE_FILE = "isaac_dca.json"  # Dedicated file for ISAAC state

# ==================== STATE BACKUP CONFIG ====================
STATE_BACKUP_FOLDER = r"E:\STATES"
STATE_BACKUP_INTERVAL_MINUTES = 1
MAX_BACKUP_FILES = 50   # Keep only the last 50 backups

# Conversation states
PAIR, BUY_PRICE, MB_AMOUNT = range(3)

# Global cache for indicators
indicator_cache = {}

# ==================== DUAL LANE (USDT / USDC) ====================
# /pair  -> one USDT pair, state AAA.json, log AAA.log, original commands
# /pair2 -> one USDC pair, state AAA_USDC.json, log AAA_USDC.log, *2 commands
# Either lane can run alone. Isaac DCA is not part of either lane.

def quote_of(symbol):
    """Quote asset of a pair. Slashless Binance ids are accepted."""
    if not isinstance(symbol, str) or not symbol:
        return "USDC" if ACTIVE_SLOT.get() == "USDC" else "USDT"
    raw = symbol.upper().replace("_SPBL", "")
    if "/" in raw:
        q = raw.split("/")[-1]
        if q in ("USDT", "USDC"):
            return q
    if raw.endswith("USDC"):
        return "USDC"
    if raw.endswith("USDT"):
        return "USDT"
    return "USDC" if ACTIVE_SLOT.get() == "USDC" else "USDT"

def _rescue_loss_freeze(pre, current_price):
    """True only when a sell from here would book a loss.
    Rescues must already be finished (5/5), the stop must be under the entry,
    and the price must be within 1% above that stop. A stop above the entry,
    or a price still in profit, returns False so the normal sell can run.
    An active 3rd-rescue dip is left alone so that buy can still happen."""
    if pre.get("rescue_trailing_dip_active"):
        return False
    if int(pre.get("rescue_count") or 0) < 5:
        return False
    try:
        entry = float(pre.get("entry_price") or 0)
        ts = float(pre.get("trailing_stop") or 0)
        price = float(current_price or 0)
    except (TypeError, ValueError):
        return False
    if entry <= 0 or ts <= 0 or price <= 0:
        return False
    if ts >= entry or price >= entry:
        return False
    return price <= ts * 1.01


async def _shutdown_keep_position(bot, symbol, reason):
    """Stop the process. Do not sell. Restart later and the open trade continues."""
    text = (
        f"❄BOT SHUTDOWN – POSITION KEPT\n"
        f"{symbol}\n"
        f"Reason: {reason}\n"
        f"No sell was sent. Restart the bot when you want this trade to continue."
    )
    try:
        await send_telegram_message(bot, text)
    except Exception:
        pass
    logger.critical(text)
    os._exit(0)

def sentiment_token(symbol):
    """Same token the old .replace('USDT') produced, plus USDC."""
    if not symbol:
        return ""
    s = str(symbol)
    if s.endswith("USDT") or s.endswith("USDC"):
        s = s[:-4]
    return s.lower()


def active_symbol():
    if ACTIVE_SLOT.get() == "USDC":
        return SYMBOL2
    return SYMBOL


def active_last_symbol():
    if ACTIVE_SLOT.get() == "USDC":
        return LAST_SYMBOL2 or SYMBOL2
    return LAST_SYMBOL or SYMBOL


def active_pair_cmd():
    return "/pair2" if ACTIVE_SLOT.get() == "USDC" else "/pair"


def active_quote():
    return "USDC" if ACTIVE_SLOT.get() == "USDC" else "USDT"


def managed_symbols():
    out = []
    if SYMBOL:
        out.append(SYMBOL)
    if SYMBOL2:
        out.append(SYMBOL2)
    return out


def lane_rescue_pool():
    if ACTIVE_SLOT.get() == "USDC":
        return RESCUE_ALLOCATED_USDC
    return RESCUE_ALLOCATED_USDT


def reserved_base_other_lane(symbol):
    """Base size already tracked by the other quote lane.

    Returns 0 unless both lanes hold the same coin (ETH/USDT and ETH/USDC).
    A single-lane bot therefore keeps the original wallet sync.
    """
    if not isinstance(symbol, str) or "/" not in symbol:
        return 0.0
    base = symbol.split("/")[0].upper()
    lane = quote_of(symbol)
    reserved = 0.0
    for sym, pre in pre_orders.items():
        if not isinstance(sym, str) or "/" not in sym or sym == symbol:
            continue
        if quote_of(sym) == lane:
            continue
        if sym.split("/")[0].upper() != base:
            continue
        try:
            reserved += float(pre.get("amount") or 0.0)
        except (TypeError, ValueError):
            continue
    return reserved


def bind_lane_from_symbol(symbol):
    ACTIVE_SLOT.set("USDC" if quote_of(symbol) == "USDC" else "USDT")


def _pre_keep(pre):
    """Keep only meaningful lane state. Drop pure idle shells (order_type None)."""
    if not isinstance(pre, dict):
        return False

    # Open (or incomplete) buy with targets
    if pre.get("order_type") == "buy":
        return all(
            pre.get(key) is not None
            for key in (
                "primary_target", "secondary_target", "stop_loss",
                "trailing_stop", "trailing_distance", "entry_price",
            )
        )

    # Pending buy setup / dip engines
    if pre.get("trailing_dip_active") or pre.get("rescue_trailing_dip_active"):
        return True
    if pre.get("buy_target") is not None:
        return True

    # order_type is None and no active setup → do not persist
    return False


def _serialize_pre(pre):
    return {
        "order_type": pre.get("order_type", None),
        "last_btc_ig": pre.get("last_btc_ig", "neutral"),
        "buy_target": pre.get("buy_target"),
        "primary_target": pre.get("primary_target"),
        "secondary_target": pre.get("secondary_target"),
        "stop_loss": pre.get("stop_loss"),
        "trailing_stop": pre.get("trailing_stop"),
        "trailing_distance": pre.get("trailing_distance"),
        "amount": pre.get("amount"),
        "current_order_type": pre.get("current_order_type"),
        "order_count": pre.get("order_count", 0),
        "last_price": pre.get("last_price"),
        "last_base_balance": pre.get("last_base_balance"),
        "last_base_locked": pre.get("last_base_locked"),
        "entry_price": pre.get("entry_price"),
        "bullish_adjusted": pre.get("bullish_adjusted", False),
        "bearish_adjusted": pre.get("bearish_adjusted", False),
        "last_adjustment_time": pre.get("last_adjustment_time", 0),
        "btc_ig": pre.get("btc_ig", None),
        "csi": pre.get("csi", None),
        "last_bullish": pre.get("last_bullish", None),
        "deactivation_achieved": pre.get("deactivation_achieved", False),
        "main_scale_count": pre.get("main_scale_count", 0),
        "main_scale_slice": pre.get("main_scale_slice", 0.0),
        "main_scale_budget": pre.get("main_scale_budget", 0.0),
        "main_scale_p1_price": pre.get("main_scale_p1_price"),
        "main_scale_p2_price": pre.get("main_scale_p2_price"),
        "main_scale_p3_price": pre.get("main_scale_p3_price"),
        "trailing_dip_active": pre.get("trailing_dip_active", False),
        "dip_level": pre.get("dip_level"),
        "dip_distance": pre.get("dip_distance"),
        "dip_tightening_time": pre.get("dip_tightening_time", 0),
        "original_trigger_price": pre.get("original_trigger_price"),
        "entry_pattern": pre.get("entry_pattern"),
        "rescue_count": pre.get("rescue_count", 0),
        "rescue_used": pre.get("rescue_used", 0.0),
        "sell_profit_pct": pre.get("sell_profit_pct", 0.0),
        "flip_persistence": pre.get("flip_persistence", 0),
        "last_flip_time": pre.get("last_flip_time", 0),
        "position_open_time": pre.get("position_open_time"),
        "rescue_trailing_dip_active": pre.get("rescue_trailing_dip_active", False),
        "rescue_dip_level": pre.get("rescue_dip_level"),
        "rescue_dip_distance": pre.get("rescue_dip_distance"),
        "rescue_dip_trigger_price": pre.get("rescue_dip_trigger_price"),
    }


def _hydrate_pre(pre):
    return {
        "order_type": pre.get("order_type", None),
        "last_btc_ig": pre.get("last_btc_ig", "neutral"),
        "last_bullish": pre.get("last_bullish", None),
        "buy_target": pre.get("buy_target"),
        "primary_target": pre.get("primary_target"),
        "secondary_target": pre.get("secondary_target"),
        "stop_loss": pre.get("stop_loss"),
        "trailing_stop": pre.get("trailing_stop"),
        "trailing_distance": pre.get("trailing_distance"),
        "amount": pre.get("amount", 0.0),
        "current_order_type": pre.get("current_order_type", None),
        "order_count": pre.get("order_count", 0),
        "last_price": pre.get("last_price"),
        "last_base_balance": pre.get("last_base_balance", 0.0),
        "last_base_locked": pre.get("last_base_locked", 0.0),
        "entry_price": pre.get("entry_price"),
        "bullish_adjusted": pre.get("bullish_adjusted", False),
        "bearish_adjusted": pre.get("bearish_adjusted", False),
        "last_adjustment_time": pre.get("last_adjustment_time", 0),
        "btc_ig": pre.get("btc_ig", None),
        "csi": pre.get("csi", None),
        "last_status_time": pre.get("last_status_time", 0),
        "last_csi": pre.get("last_csi", 0),
        "main_scale_count": pre.get("main_scale_count", 0),
        "main_scale_slice": pre.get("main_scale_slice", 0.0),
        "main_scale_budget": pre.get("main_scale_budget", 0.0),
        "main_scale_p1_price": pre.get("main_scale_p1_price"),
        "main_scale_p2_price": pre.get("main_scale_p2_price"),
        "main_scale_p3_price": pre.get("main_scale_p3_price"),
        "deactivation_achieved": pre.get("deactivation_achieved", False),
        "trailing_dip_active": pre.get("trailing_dip_active", False),
        "dip_level": pre.get("dip_level"),
        "dip_distance": pre.get("dip_distance"),
        "dip_tightening_time": pre.get("dip_tightening_time", 0),
        "original_trigger_price": pre.get("original_trigger_price"),
        "entry_pattern": pre.get("entry_pattern"),
        "rescue_count": pre.get("rescue_count", 0),
        "rescue_used": pre.get("rescue_used", 0.0),
        "sell_profit_pct": pre.get("sell_profit_pct", 0.0),
        "flip_persistence": pre.get("flip_persistence", 0),
        "last_flip_time": pre.get("last_flip_time", 0),
        "position_open_time": pre.get("position_open_time"),
        "rescue_trailing_dip_active": pre.get("rescue_trailing_dip_active", False),
        "rescue_dip_level": pre.get("rescue_dip_level"),
        "rescue_dip_distance": pre.get("rescue_dip_distance"),
        "rescue_dip_trigger_price": pre.get("rescue_dip_trigger_price"),
    }


def _atomic_write_json(path, payload):
    temp_file = path + ".tmp"
    backup_file = path + ".backup"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4)
    if os.path.exists(path):
        try:
            if os.path.exists(backup_file):
                os.remove(backup_file)
            os.replace(path, backup_file)
        except Exception as e:
            logger.debug(f"Could not update backup (non-critical): {e}")
    os.replace(temp_file, path)


def with_usdc_lane(func):
    """Run a command against the USDC lane only. The caller's task slot is restored."""
    async def _wrapped(update, context):
        token = ACTIVE_SLOT.set("USDC")
        try:
            return await func(update, context)
        finally:
            ACTIVE_SLOT.reset(token)
    _wrapped.__name__ = getattr(func, "__name__", "cmd") + "_usdc"
    _wrapped.__doc__ = getattr(func, "__doc__", None)
    return _wrapped



async def get_cached_indicators(symbol, current_price, timeframe='1h', limit=100):
    """
    TESTNET BOT VERSION
    - Prefers Testnet metrics (normal behaviour)
    - Falls back to Live metrics if Testnet is unavailable
    """
    global binance_client, live_client

    cache_key = f"{symbol}_{timeframe}"
    current_time = time.time()

    # ---------- Cache cleaning ----------
    removed_count = 0
    for key in list(indicator_cache.keys()):
        if current_time - indicator_cache[key]["timestamp"] > 3600:
            del indicator_cache[key]
            removed_count += 1
    if removed_count > 0:
        logger.info(f"Cleaned {removed_count} stale cache entries older than 1 hour.")

    # ---------- Return cache if still valid ----------
    if cache_key in indicator_cache:
        cached = indicator_cache[cache_key]
        if (current_time - cached["timestamp"] < 300 and
            cached["last_price"] is not None and
            abs(current_price - cached["last_price"]) / cached["last_price"] < 0.01):
            logger.debug(f"Returning cached indicators for {symbol}")
            return cached["data"]

    data = None
    source = "testnet"
    original_client = binance_client

    # ============================================================
    # 1. TRY TESTNET FIRST (normal behaviour)
    # ============================================================
    try:
        logger.debug(f"[METRICS] Trying TESTNET for {symbol}...")
        data = await _original_calculate_indicators(symbol, current_price, timeframe, limit)

        if data and data.get("is_valid", True):
            source = "testnet"
            logger.info(f"[METRICS] Using TESTNET indicators for {symbol}")
        else:
            raise Exception("Testnet returned invalid data")
    except Exception as e:
        logger.warning(f"[METRICS] Testnet failed ({e}) >> falling back to LIVE")
        data = None

    # ============================================================
    # 2. FALLBACK TO LIVE METRICS
    # ============================================================
    if data is None and USE_LIVE_FALLBACK and live_client is not None:
        try:
            logger.debug(f"[METRICS] Using LIVE indicators as fallback for {symbol}")
            binance_client = live_client                # temporarily switch to Live

            data = await _original_calculate_indicators(symbol, current_price, timeframe, limit)
            source = "live"
            logger.info(f"[METRICS] Using LIVE indicators (fallback) for {symbol}")
        except Exception as e:
            logger.error(f"[METRICS] Live fallback also failed: {e}")
            data = None
        finally:
            binance_client = original_client            # always restore Testnet client

    if data is None:
        logger.error(f"[METRICS] Both Testnet and Live failed for {symbol}")
        return None

    data["metrics_source"] = source

    # Cache the result
    indicator_cache[cache_key] = {
        "data": data,
        "timestamp": current_time,
        "last_price": current_price
    }

    return data

async def _original_calculate_indicators(symbol, current_price, timeframe='1h', limit=100):
    """
    Fetch and cache technical indicators for a given symbol, matching original behavior.
    Now includes:
    - EMA50 and volatility_index
    - Enhanced VWAP calculations for Pattern #3 (ATR Squeeze Breakout)
    - Maintains all existing Fibonacci calculation and other indicators
    """
    cache_key = f"{symbol}_{timeframe}"
    current_time = time.time()

    # Clean up cache: Remove entries older than 1 hour
    removed_count = 0
    for key in list(indicator_cache.keys()):
        if current_time - indicator_cache[key]["timestamp"] > 3600:
            del indicator_cache[key]
            removed_count += 1
    if removed_count > 0:
        logger.info(f"Cleaned {removed_count} stale cache entries older than 1 hour.")

    # Check cache validity (TTL=300s, price change < 1%)
    if cache_key in indicator_cache:
        cached = indicator_cache[cache_key]
        if (current_time - cached["timestamp"] < 300 and 
            cached["last_price"] is not None and 
            abs(current_price - cached["last_price"]) / cached["last_price"] < 0.01):
            logger.debug(f"Returning cached indicators for {symbol}")
            return cached["data"]

    # Fetch OHLCV data
    ohlcv = await fetch_ohlcv(symbol, timeframe, limit)
    if ohlcv is None or len(ohlcv) < 50 or np.any(ohlcv[:, 0:4] <= 0):  # Check only OHLC, not volume
        logger.error(f"Invalid OHLCV for {symbol}: len={len(ohlcv) if ohlcv is not None else 'None'}, data={ohlcv}")
        return None
    
    if np.any(ohlcv[:, 4] == 0):  # Log zero volume separately
        zero_volume_count = np.sum(ohlcv[:, 4] == 0)
        logger.warning(f"Zero volume detected for {symbol} in {zero_volume_count}/{len(ohlcv)} candles")

    closes = ohlcv[:, 3]
    highs = ohlcv[:, 1]
    lows = ohlcv[:, 2]
    volumes = ohlcv[:, 4]

    # Initialize data dictionary with all indicators including new VWAP metrics
    data = {
        "closes": closes,
        "highs": highs,    # Add this
        "volumes": volumes, # Add this
        "ema_5": None,
        "ema_9": None,
        "ema_13": None,
        "ema_21": None,
        "ema_50": None,
        "ema_9_prev": None,
        "ema_21_prev": None,
        "rsi": None,
        "high": None,
        "low": None,
        "fib_levels": None,
        "support": None,
        "volume_spike": None,
        "vwap": None,
        "atr": None,
        "prev_atr": None,         # New: Previous ATR for squeeze detection
        "macd_line": None,
        "signal_line": None,
        "histogram": None,
        "middle_band": None,
        "upper_band": None,
        "lower_band": None,
        "volatility_index": None,
        "rsi_values": [],          # New: Store RSI values for divergence
        "cvd": None,  # NEW: Cumulative Volume Delta
        "cvd_signal": None,
        "cvd_values": [],  # NEW: Historical CVD values for divergence (mirrors rsi_values)
        "obi": None,  # NEW: Order Book Imbalance
        "obi_signal": None,
        "obi_values": []  # NEW: Historical OBI values (single snapshot + fallback for prev)
        
    }
            
    # Calculate basic indicators
    try:
        # Calculate EMAs (including EMA50 and EMA200)
        for period in [5, 9, 13, 21, 50, 200]:
            if len(closes) >= period:
                ema_result = calculate_ema(closes, period)
                if isinstance(ema_result, (float, np.floating)) and not np.isnan(ema_result):
                    data[f"ema_{period}"] = float(ema_result)
                else:
                    logger.warning(f"EMA_{period} calculation failed for {symbol}: result={ema_result}")

        if len(closes) >= 2:
            # Recalculate EMA9 and EMA21 on the previous candle only ([: -1])
            prev_ema_9 = calculate_ema(closes[:-1], 9)
            prev_ema_21 = calculate_ema(closes[:-1], 21)

            if isinstance(prev_ema_9, (float, np.floating)) and not np.isnan(prev_ema_9):
                data["ema_9_prev"] = float(prev_ema_9)
            else:
                data["ema_9_prev"] = data["ema_9"] * 0.99  # Safe fallback

            if isinstance(prev_ema_21, (float, np.floating)) and not np.isnan(prev_ema_21):
                data["ema_21_prev"] = float(prev_ema_21)
            else:
                data["ema_21_prev"] = data["ema_21"] * 0.99  # Safe fallback
        else:
            # Not enough data arrow use current as proxy (will be ignored in logic)
            data["ema_9_prev"] = data["ema_9"]
            data["ema_21_prev"] = data["ema_21"] 

        # Calculate RSI and store values
        if len(closes) >= 14:
            rsi_result = calculate_rsi(closes, 14)
            if isinstance(rsi_result, (float, np.floating)) and not np.isnan(rsi_result):
                data["rsi"] = float(rsi_result)
                # Store last 10 RSI values for divergence detection
                data["rsi_values"] = [calculate_rsi(closes[:i], 14) for i in range(14, len(closes)+1)][-14:]
            else:
                logger.warning(f"RSI calculation failed for {symbol}: result={rsi_result}")

        # Calculate ATR and store previous ATR
        if len(ohlcv) >= 14:
            atr_result = calculate_atr(ohlcv, 14)
            if isinstance(atr_result, (float, np.floating)) and not np.isnan(atr_result):
                data["atr"] = float(atr_result)
                # Calculate previous ATR for squeeze detection (Pattern #3)
                if len(ohlcv) >= 28:
                    data["prev_atr"] = calculate_atr(ohlcv[:-14], 14)
            else:
                logger.warning(f"ATR calculation failed for {symbol}: result={atr_result}")

        # Calculate volatility index
        if data["atr"] is not None and data["rsi"] is not None and current_price > 0:
            atr_ratio = (data["atr"] / current_price) * 100
            rsi_normalized = max(0, min(1, (data["rsi"] - 30) / (70 - 30)))
            data["volatility_index"] = min(100, max(0, (atr_ratio * 1.5 + (1 - rsi_normalized) * 30)))

        # Calculate high/low
        if len(highs) >= 20:
            data["high"] = float(np.max(highs[-20:]))
        if len(lows) >= 20:
            data["low"] = float(np.min(lows[-10:]))

        # Calculate Fibonacci levels
        if data["high"] is not None and data["low"] is not None:
            data["fib_levels"] = calculate_fibonacci_levels(data["high"], data["low"])

        # Calculate support and volume spike
        data["support"] = detect_swing_low(ohlcv)
        data["volume_spike"] = check_volume_spike(ohlcv, threshold=2.0, periods=10,
                                                support_fallback=data["support"],
                                                current_price=current_price)

        # Calculate VWAP (Volume-Weighted Average Price)
        typical_prices = (highs + lows + closes) / 3
        price_volume = typical_prices * volumes
        cumulative_pv = np.cumsum(price_volume)
        cumulative_volume = np.cumsum(volumes)
        vwap = cumulative_pv[-1] / cumulative_volume[-1] if cumulative_volume[-1] != 0 else None
        if isinstance(vwap, (float, np.floating)) and not np.isnan(vwap):
            data["vwap"] = float(vwap)
        else:
            logger.warning(f"VWAP calculation failed for {symbol}: result={vwap}")
        
    except Exception as e:
        logger.error(f"Error calculating basic indicators for {symbol}: {str(e)}")
        return None

    # NEW: Cumulative Volume Delta (CVD) - net buy/sell pressure
    try:
        opens = ohlcv[:, 0]  # FIXED: Open prices from OHLCV (was [:,1] = highs)
        cvd_array = np.cumsum(volumes * (closes - opens))  # Simple CVD: volume * (close - open)
        data["cvd"] = float(cvd_array[-1]) if len(cvd_array) > 0 else 0.0  # Latest CVD value
        data["cvd_signal"] = "bullish" if data["cvd"] > 0 else "bearish" if data["cvd"] < 0 else "neutral"
        # NEW: Store historical CVD values for divergence (mirrors RSI: last 14)
        data["cvd_values"] = cvd_array[-14:].tolist() if len(cvd_array) >= 14 else cvd_array.tolist()
        logger.debug(f"CVD calculated for {symbol}: latest={data['cvd']:.4f}, values_len={len(data['cvd_values'])}")
    except Exception as e:
        logger.warning(f"CVD calculation failed for {symbol}: {e}")
        data["cvd"] = 0.0
        data["cvd_signal"] = "neutral"
        data["cvd_values"] = [0.0]  # Fallback array for prev binding

    # Fetch MACD and Bollinger Bands
    try:
        macd_line, signal_line, histogram = await get_macd(symbol)
        if isinstance(macd_line, (float, np.floating)) and not np.isnan(macd_line):
            data["macd_line"] = float(macd_line)
        else:
            logger.warning(f"MACD line invalid for {symbol}: {macd_line}")
        if isinstance(signal_line, (float, np.floating)) and not np.isnan(signal_line):
            data["signal_line"] = float(signal_line)
        else:
            logger.warning(f"Signal line invalid for {symbol}: {signal_line}")
        if isinstance(histogram, (float, np.floating)) and not np.isnan(histogram):
            data["histogram"] = float(histogram)
        else:
            logger.warning(f"Histogram invalid for {symbol}: {histogram}")

        middle_band, upper_band, lower_band = await get_bollinger_bands(symbol)
        if isinstance(middle_band, (float, np.floating)) and not np.isnan(middle_band):
            data["middle_band"] = float(middle_band)
        else:
            logger.warning(f"Middle band invalid for {symbol}: {middle_band}")
        if isinstance(upper_band, (float, np.floating)) and not np.isnan(upper_band):
            data["upper_band"] = float(upper_band)
        else:
            logger.warning(f"Upper band invalid for {symbol}: {upper_band}")
        if isinstance(lower_band, (float, np.floating)) and not np.isnan(lower_band):
            data["lower_band"] = float(lower_band)
        else:
            logger.warning(f"Lower band invalid for {symbol}: {lower_band}")

        # NEW: Safe bb_width_proxy (None guard)
        if all(k in data for k in ['upper_band', 'lower_band', 'middle_band']) and data['middle_band'] is not None and data['middle_band'] > 0:
            bb_width_proxy = ((data['upper_band'] - data['lower_band']) / data['middle_band'])
            data['bb_width'] = float(bb_width_proxy) if not np.isnan(bb_width_proxy) else 0.02
        else:
            data['bb_width'] = 0.02
            logger.debug(f"BB width defaulted for {symbol}: None bands")    

    except Exception as e:
        logger.error(f"Error fetching MACD or Bollinger Bands for {symbol}: {str(e)}")

    # NEW: Order Book Imbalance (OBI) - bid/ask pressure
    try:
        book = await binance_client.get_order_book(symbol=symbol.replace('/', ''), limit=20)
        bids = sum(float(b[1]) for b in book['bids'])
        asks = sum(float(a[1]) for a in book['asks'])
        obi = (bids - asks) / (bids + asks) if (bids + asks) > 0 else 0.0
        
        data["obi"] = float(obi)
        data["obi_signal"] = "bullish" if obi > 0.15 else "bearish" if obi < -0.15 else "neutral"

        # === FIXED: Maintain history using correct cache name ===
        previous_obi_values = indicator_cache.get(cache_key, {}).get("data", {}).get("obi_values", [])
        if previous_obi_values:
            data["obi_values"] = (previous_obi_values[-9:] + [data["obi"]])[-10:]
        else:
            data["obi_values"] = [data["obi"]] * 2   # Seed with 2 values on first run

        logger.debug(f"OBI calculated for {symbol}: {data['obi']:.4f}, signal={data['obi_signal']}, history_len={len(data['obi_values'])}")

    except Exception as e:
        logger.warning(f"OBI fetch failed for {symbol}: {e}")
        data["obi"] = 0.0
        data["obi_signal"] = "neutral"
        data["obi_values"] = [0.0, 0.0]   # Safe fallback with 2 values

    critical_indicators = [
        "ema_5", "ema_13", "ema_9", "ema_21", "ema_50",
        "rsi", "atr",
        "macd_line", "signal_line", "histogram",
        "vwap", "volatility_index",
        "middle_band",
        "cvd", "obi"
    ]
    logger.debug(f"Indicators for {symbol}: { {k: v for k, v in data.items() if k in critical_indicators} }")

    # NEW: Validity gate - require ≥80% core indicators non-None/non-zero
    core_count = len(critical_indicators)
    valid_count = sum(1 for k in critical_indicators if (
        data.get(k) is not None and
        (not isinstance(data.get(k), (float, np.floating)) or (data[k] != 0 and not np.isnan(data[k])))
    ))
    data["is_valid"] = (valid_count / core_count) >= 0.8  # 80% threshold; adjust if needed
    if not data["is_valid"]:
        logger.warning(f"Indicators invalid for {symbol}: only {valid_count}/{core_count} core indicators succeeded (threshold 80%)")
        return None  # Block bad data upstream

    # Cache the results
    indicator_cache[cache_key] = {
        "data": data,
        "timestamp": current_time,
        "last_price": current_price
    }
    
    return data

async def save_obi_snapshot(indicators: dict, current_price: float = None):
    """Save OBI + RSI + all key indicators for the Live bot"""
    try:
        if not indicators:
            return

        if ACTIVE_SLOT.get() == "USDC":
            SNAPSHOT_FILE = r"C:\Users\pauld\Desktop\IG\obi_rsi_snapshot_USDC.json"
        else:
            SNAPSHOT_FILE = r"C:\Users\pauld\Desktop\IG\obi_rsi_snapshot.json"

        # OBI
        obi = indicators.get("obi")
        obi_values = indicators.get("obi_values", [obi] if obi is not None else [0.0])
        prev_obi = obi_values[-2] if len(obi_values) >= 2 else obi

        # RSI
        rsi = indicators.get("rsi")
        rsi_values = indicators.get("rsi_values", [rsi] if rsi is not None else [50])
        rsi_prev = rsi_values[-2] if len(rsi_values) >= 2 else (rsi - 1 if rsi is not None else 49)
        rsi_low = float(min(rsi_values)) if rsi_values else rsi

        # CVD
        cvd = indicators.get("cvd")
        cvd_values = indicators.get("cvd_values", [cvd] if cvd is not None else [0.0])
        prev_cvd = cvd_values[-2] if len(cvd_values) >= 2 else cvd

        # Volume
        volumes = indicators.get("volumes", [])
        volume = float(volumes[-1]) if len(volumes) > 0 else indicators.get("volume")
        avg_volume = float(np.mean(volumes[-10:])) if len(volumes) >= 10 else volume

        # ATR
        atr = indicators.get("atr")
        atr_percent = (atr / current_price * 100) if (atr is not None and current_price) else indicators.get("atr_percent")
        prev_atr = indicators.get("prev_atr")
        prev_atr_percent = (prev_atr / current_price * 100) if (prev_atr is not None and current_price) else None

        # Price levels
        closes = indicators.get("closes", [])
        prev_close = float(closes[-2]) if len(closes) >= 2 else None
        price_low = float(min(closes[-5:])) if len(closes) >= 5 else None

        # Histogram
        histogram = indicators.get("histogram")
        prev_histogram = indicators.get("prev_histogram")
        if prev_histogram is None and histogram is not None:
            prev_histogram = histogram - 0.1

        # Fib
        fib_levels = indicators.get("fib_levels") or {}
        fib_61_8 = fib_levels.get("61.8%") if isinstance(fib_levels, dict) else indicators.get("fib_61_8")

        data = {
            "timestamp": time.time(),

            # OBI
            "obi": float(obi) if obi is not None else 0.0,
            "prev_obi": float(prev_obi) if prev_obi is not None else 0.0,
            "obi_signal": indicators.get("obi_signal", "neutral"),

            # RSI
            "rsi": float(rsi) if rsi is not None else 50.0,
            "rsi_prev": float(rsi_prev) if rsi_prev is not None else 49.0,
            "rsi_low": float(rsi_low) if rsi_low is not None else 50.0,

            # EMAs
            "ema_5": indicators.get("ema_5"),
            "ema_9": indicators.get("ema_9"),
            "ema_13": indicators.get("ema_13"),
            "ema_21": indicators.get("ema_21"),
            "ema_50": indicators.get("ema_50"),

            # MACD
            "macd_line": indicators.get("macd_line"),
            "signal_line": indicators.get("signal_line"),
            "histogram": histogram,
            "prev_histogram": prev_histogram,

            # ATR
            "atr": atr,
            "prev_atr": prev_atr,
            "atr_percent": atr_percent,
            "prev_atr_percent": prev_atr_percent,

            # Bands / other
            "middle_band": indicators.get("middle_band"),
            "bb_width": indicators.get("bb_width"),
            "vwap": indicators.get("vwap"),
            "volatility_index": indicators.get("volatility_index"),
            "fib_61_8": fib_61_8,

            # Price levels
            "price_low": price_low,
            "recent_high": indicators.get("high"),
            "high": indicators.get("high"),
            "low": indicators.get("low"),
            "support": indicators.get("support"),
            "prev_close": prev_close,

            # CVD
            "cvd": float(cvd) if cvd is not None else 0.0,
            "prev_cvd": float(prev_cvd) if prev_cvd is not None else 0.0,

            # Volume
            "volume": volume,
            "avg_volume": avg_volume,

            
        }

        with open(SNAPSHOT_FILE, "w") as f:
            json.dump(data, f)

        logger.debug(f"[SNAPSHOT] Full saved | OBI={data['obi']:.4f} | RSI={data['rsi']:.2f}")
    except Exception as e:
        logger.error(f"[SNAPSHOT] Failed to save: {e}")

# Helper handling partial filled order Market and Limit
async def confirm_order_fill(ord_id, symbol, max_retries=3):
    """
    Fetch actual filled quantity for an order with retries.
    Returns filled_qty (float), or 0 on failure.
    """
    global binance_client
    if binance_client is None:
        await create_binance_client()
    
    # FIX: Unpack if dict response (from execute_sell/place_order)
    if isinstance(ord_id, dict):
        ord_id = ord_id.get("orderId") or ord_id.get("ordId")  # Handle 'orderId' or 'ordId' key
    ord_id = str(ord_id)  # FIXED: Convert to str early (SDK returns int)
    if not ord_id.isdigit():
        logger.error(f"Invalid ord_id for {symbol}: {ord_id} (expected digits)")
        return 0.0
    
    for attempt in range(1, max_retries + 1):
        try:
            params = {"ordId": ord_id, "instId": symbol}
            order_status = await binance_request("GET", "/api/v5/trade/order", params=params)
            if order_status and isinstance(order_status, list) and order_status:
                filled_qty = float(order_status[0].get("accFillSz", 0))
                if filled_qty > 0:
                    logger.debug(f"Confirmed fill for {ord_id} on {symbol}: {filled_qty:.8f} (attempt {attempt})")
                    return filled_qty
                elif attempt < max_retries:
                    logger.debug(f"Partial/zero fill for {ord_id} (attempt {attempt}), retrying...")
                    await asyncio.sleep(0.5)  # 0.5s delay
            else:
                logger.warning(f"No status for {ord_id} on {symbol} (attempt {attempt})")
        except Exception as e:
            logger.error(f"Error confirming {ord_id} (attempt {attempt}): {str(e)}")
            if attempt < max_retries:
                await asyncio.sleep(0.5)   # 0.5s delay
    logger.error(f"Failed to confirm fill for {ord_id} after {max_retries} retries")
    return 0.0  # Fallback: assume no fill on total failure

async def evaluate_pattern_matches(symbol, indicators, current_price, suppress_if_active=True):  # NEW: Optional param, default=True (original behavior)
    """
    Evaluate actual trading patterns from the script for near-trigger status.
    Returns a list of dicts with 'number', 'name', 'match_pct', 'near_trigger', 'valid'.
    Only includes patterns with >=50% match.
    """
    if not indicators or current_price <= 0:
        return []

    # NEW: Gate on indicator validity (from get_cached_indicators)
    if indicators.get("is_valid", False) is False:
        logger.warning(f"Skipping pattern eval for {symbol}: indicators invalid")
        return []

    pre = pre_orders.get(symbol, {})
    # UPDATED: Conditional suppression—only if flag=True and active
    if suppress_if_active and (pre.get("order_type") == "buy" or pre.get("trailing_dip_active", False)):
        return []

    patterns = []

    # Eval-aligned helpers (arrays for prev/current) - Safe computation
    volumes = indicators.get('volumes', np.array([current_price]))  # Fallback to current if None
    current_volume = volumes[-1] if len(volumes) > 0 else current_price
    avg_volume = np.mean(volumes[-10:]) if len(volumes) >= 10 else current_volume
    avg_volume_20 = np.mean(volumes[-20:]) if len(volumes) >= 20 else avg_volume
    prev_volume = volumes[-2] if len(volumes) >= 2 else current_volume * 0.9

    rsi_values = indicators.get('rsi_values', [indicators.get('rsi', 50)])
    rsi = indicators.get('rsi', 50)
    rsi_prev = rsi_values[-2] if len(rsi_values) >= 2 else rsi - 1  # Safe: -1 delta fallback

    btc_ig = pre_orders.get(symbol, {}).get("btc_ig", "N/A")

    macd_values = indicators.get('macd_values', [indicators.get('macd_line', 0)])
    macd_line = indicators.get('macd_line', 0)
    prev_macd = macd_values[-2] if len(macd_values) >= 2 else macd_line * 0.9

    histogram_values = indicators.get('histogram_values', [indicators.get('histogram', 0)])
    histogram = indicators.get('histogram', 0)
    prev_histogram = histogram_values[-2] if len(histogram_values) >= 2 else histogram - 0.1  # Delta fallback (bottoming trend)

    signal_values = indicators.get('signal_values', [indicators.get('signal_line', 0)])
    signal_line = indicators.get('signal_line', 0)
    prev_signal = signal_values[-2] if len(signal_values) >= 2 else signal_line * 0.9
    price_low = min(indicators['closes'][-5:]) if len(indicators['closes']) >= 5 else current_price
    fib_61_8 = indicators.get('fib_levels', {}).get('61.8%', None) if indicators.get('fib_levels') else None

    highs = indicators.get('highs', np.array([current_price]))
    prev_high = highs[-5:].max() if len(highs) >= 5 else current_price

    closes = indicators.get('closes', np.array([current_price]))
    prev_close = closes[-2] if len(closes) >= 2 else current_price * 0.99  # Safe fallback

    bb_width_proxy = indicators.get('bb_width', 0.02)
    atr = indicators.get('atr', current_price * 0.01)
    prev_atr = indicators.get('prev_atr', atr * 0.9)
    atr_percent = (atr / current_price * 100) if current_price > 0 else 0
    fib_levels = indicators.get('fib_levels', {})
    ema_5 = indicators.get('ema_5', current_price)
    ema_9 = indicators.get('ema_9', current_price)
    ema_13 = indicators.get('ema_13', current_price)
    ema_21 = indicators.get('ema_21', current_price)
    ema_50 = indicators.get('ema_50', current_price)
    vwap = indicators.get('vwap', current_price)
    bb_middle = indicators.get('middle_band', current_price)
    bb_upper = bb_middle + (bb_width_proxy * bb_middle) if bb_middle and bb_width_proxy else current_price * 1.02
    bb_lower = bb_middle - (bb_width_proxy * bb_middle) if bb_middle and bb_width_proxy else current_price * 0.98
    support = indicators.get('support', current_price)
    csi = pre.get('csi', 0)  # From pre, like eval

    # NEW: CVD vars (net buy/sell pressure) - Verified: Safe array fallback, prev=0.9x for continuity
    cvd_values = indicators.get('cvd_values', [indicators.get('cvd', 0)])
    cvd = indicators.get('cvd', 0)
    prev_cvd = cvd_values[-2] if len(cvd_values) >= 2 else cvd * 0.9  # Safe fallback
    cvd_change_pct = ((cvd - prev_cvd) / abs(prev_cvd + 1e-6)) * 100 if prev_cvd != 0 else 0  # % change; avoids div0

    # NEW: OBI vars (bid/ask imbalance)
    obi_values = indicators.get('obi_values', [indicators.get('obi', 0.0)])
    obi = indicators.get('obi', 0.0)

    # Better fallback logic
    if len(obi_values) >= 2:
        prev_obi = obi_values[-2]
    else:
        prev_obi = obi_values[0] if obi_values else obi

    obi_imbalance = obi - prev_obi
    
    # ---------- NEW SAFE HIGH-PRICE FILTER VARIABLES ----------
    recent_high_5 = max(highs[-5:]) if len(highs) >= 5 else current_price
    recent_high_10 = max(highs[-10:]) if len(highs) >= 10 else recent_high_5

    price_extension_pct = ((current_price - ema_21) / ema_21 * 100) if ema_21 > 0 else 0
    distance_from_low_pct = ((current_price - price_low) / price_low * 100) if price_low > 0 else 0
    near_recent_top = current_price >= recent_high_5 * 0.996
    overextended_price = current_price > ema_21 * 1.018

    # ==========================================================
    # ULTIMATE TOP DETECTOR + ATR BEAST vNEXT + PATTERNS
    # Final Consolidated Block - Cleaned & Improved Version
    # ==========================================================

    # -----------------------------
    # SAFE DEFAULTS
    # -----------------------------
    top_risk_score = 0.0
    top_detector_triggered = False
    top_detector_level = "LOW"
    hard_no_buy = False

    
    # ==========================================================
    # 1. ULTIMATE TOP DETECTOR
    # ==========================================================

    # ---------------------------------------------------------- 
    # 1. Price stretched near highs
    # ----------------------------------------------------------
    if near_recent_top:
        top_risk_score += 18
        
    if current_price >= recent_high_10 * 0.998:
        top_risk_score += 12
        
    if price_extension_pct > 1.8:
        top_risk_score += 12
        
    if price_extension_pct > 3.0:
        top_risk_score += 10
        
    # ---------------------------------------------------------- 
    # 2. RSI exhaustion
    # ----------------------------------------------------------
    if rsi > 72:
        top_risk_score += 15
        
    if rsi > 76:
        top_risk_score += 10
        
    if rsi < rsi_prev and rsi > 70:
        top_risk_score += 10
        
    # ---------------------------------------------------------- 
    # 3. Volume weakness / breakout failure
    # ----------------------------------------------------------
    if near_recent_top and current_volume < avg_volume * 0.85:
        top_risk_score += 15
        
    if current_volume < prev_volume * 0.80 and current_price >= prev_close:
        top_risk_score += 8
        
    # ---------------------------------------------------------- 
    # 4. Orderflow exhaustion
    # ----------------------------------------------------------
    if obi < 0:
        top_risk_score += 10
        
    if obi < prev_obi and current_price >= prev_close:
        top_risk_score += 8
        
    if cvd < prev_cvd and current_price >= prev_close:
        top_risk_score += 10
        
    if cvd_change_pct < -5:
        top_risk_score += 10
        
    # ---------------------------------------------------------- 
    # 5. Momentum stall
    # ----------------------------------------------------------
    if histogram < prev_histogram and histogram > 0:
        top_risk_score += 12
        
    if macd_line < signal_line and macd_line > 0:
        top_risk_score += 10
        
    # ---------------------------------------------------------- 
    # 6. Low ATR squeeze near highs (classic trap)
    # ----------------------------------------------------------
    if atr_percent < 0.55 and near_recent_top:
        top_risk_score += 10
        
    if bb_width_proxy < 0.014 and near_recent_top:
        top_risk_score += 8
        
    # ---------------------------------------------------------- 
    # 7. Resistance rejection micro signal
    # ----------------------------------------------------------
    if current_price < prev_close and near_recent_top:
        top_risk_score += 10
        
    # ---------------------------------------------------------- 
    # Clamp & Final Top Detector Result
    # ----------------------------------------------------------
    top_risk_score = max(0.0, min(100.0, top_risk_score))
    top_risk_pct = round(top_risk_score)

    if top_risk_score >= 75:
        top_detector_level = "EXTREME"
        top_detector_triggered = True
    elif top_risk_score >= 55:
        top_detector_level = "HIGH"
        top_detector_triggered = True
    elif top_risk_score >= 35:
        top_detector_level = "MEDIUM"
    else:
        top_detector_level = "LOW"

    # ---------------------------------------------------------- 
    # HARD NO-BUY CONDITIONS (Nuclear Protection)
    # ----------------------------------------------------------
    if (rsi > 73 and near_recent_top and current_volume < avg_volume * 0.90):
        hard_no_buy = True
        
    if (near_recent_top and obi < 0 and cvd < prev_cvd):
        hard_no_buy = True
        
    if (price_extension_pct > 3.0 and rsi > 75):
        hard_no_buy = True
        
    # Final Top Detector Summary
    

    # ==========================================================
    # ATR BEAST vNEXT - IMPROVED & CLEANED
    # Smart ATR Threshold + Confluence Engine + Regime Detection
    # ==========================================================

    
    # -----------------------------
    # CORE HELPERS & REGIME ENGINE
    # -----------------------------
    atr_threshold = 0.30
    volume_soft_mult = 0.60
    basic_bypass_min = 5
    obi_relax = -0.05
    min_tier_score = 15
    ema_rescue_min = 10

    # Trend & Pressure proxies
    trend_strength_proxy = abs((ema_9 - ema_21) / max(abs(ema_21), 1e-9)) * 100
    pressure_strength_proxy = (abs(cvd_change_pct) + abs(obi_imbalance) * 100) / 2

    # Divergence & Recovery signals
    cvd_divergence = (cvd > prev_cvd) and (current_price < prev_close)
    obi_recovery = (prev_obi < 0 and obi > 0)
    rsi_divergence = (rsi > rsi_prev and current_price < prev_close)
    macd_divergence = (macd_line > prev_macd and current_price < prev_close)

    # --- Market Regime Detection ---
    regime = "neutral"
    try:
        full_ema_stack = (ema_5 > ema_9 > ema_13 > ema_21 and ema_21 > ema_50 * 0.995)
    except:
        full_ema_stack = False

    if full_ema_stack and rsi > 52 and macd_line >= signal_line:
        regime = "trend_bull"
    elif current_price < ema_21 and rsi < 42 and macd_line < signal_line:
        regime = "trend_bear"
    elif bb_width_proxy < 0.018 and atr_percent < 1.0:
        regime = "compression"
    elif rsi < 30 and histogram > prev_histogram:
        regime = "reversal_up"
    elif rsi > 72 and histogram < prev_histogram:
        regime = "reversal_down"

    
    # -----------------------------
    # SMART ATR THRESHOLD ENGINE
    # -----------------------------
    # Base threshold based on volatility
    if atr_percent > 6.0:
        atr_threshold = 2.5
    elif atr_percent < 1.0:
        atr_threshold = 1.2
    else:
        atr_threshold = 0.30

    # Regime adjustments
    if regime == "trend_bull":
        atr_threshold *= 0.72
    elif regime == "trend_bear":
        atr_threshold *= 0.95
    elif regime == "compression":
        atr_threshold *= 1.45
    elif regime == "reversal_up":
        atr_threshold *= 0.82

    # Additional modifiers
    if trend_strength_proxy > 0.35:
        atr_threshold *= 0.92
    if pressure_strength_proxy > 4:
        atr_threshold *= 0.90

    high_vol = current_volume > avg_volume * 1.30
    if high_vol:
        atr_threshold *= 0.75

    # Final clamping
    atr_threshold = max(0.20, min(2.80, atr_threshold))

    logger.debug(f"ATR Threshold Engine >> atr_percent={atr_percent:.2f} | regime={regime} | final_atr_threshold={atr_threshold:.3f}")

    # -----------------------------
    # CONFLUENCE ENGINE (Cleaned & Improved)
    # -----------------------------
    confluence = 0          # Single unified confluence (replaces core + score split)
    atr_bypass_tier = 0
    atr_bypass_active = False

    # Fast Reversal Detection
    fast_reversal_core = (
        (obi > 0.10 and obi_recovery) and
        (cvd_change_pct > 5) and
        (rsi > 50 or rsi_divergence)
    )
    fast_reversal_boosters = 0
    if fast_reversal_core:
        if ema_5 > ema_9:
            fast_reversal_boosters += 1
        if histogram > prev_histogram * 1.10:
            fast_reversal_boosters += 1

    # Basic Bypass Conditions (Foundation)
    basic_bypass_conditions = {
        'ema_alignment': ema_9 > ema_21 > ema_50 * 0.99,
        'macd_above_signal': (macd_line > signal_line * 0.98) or (histogram > prev_histogram * 0.90),
        'histogram_rising': histogram > prev_histogram * 0.90,
        'rsi_neutral': 45 < rsi < 75,
        'price_above_support': current_price > support * 1.005 if support else (support_fallback := current_price * 0.98),
        'volume_sufficient': current_volume > avg_volume * volume_soft_mult,
        'csi_positive': pre.get('csi', 0) > 0.0,
        'fast_reversal_core': fast_reversal_core,
    }

    basic_bypass_met_count = sum(basic_bypass_conditions.values())

    # === Detailed Logging ===
    logger.debug("=== ATR CONFLUENCE ANALYSIS ===")
    logger.debug(f"Basic Bypass Conditions Met: {basic_bypass_met_count}/{len(basic_bypass_conditions)}")

    cond_desc = {
        'ema_alignment': f"EMA Alignment: ema9({ema_9:.6f}) > ema21({ema_21:.6f}) > ema50({ema_50:.6f})*0.99",
        'macd_above_signal': f"MACD Confirm: macd({macd_line:.6f}) > signal({signal_line:.6f}) or hist rising",
        'histogram_rising': f"Histogram Rising: {histogram:.6f} > prev({prev_histogram:.6f})*0.9",
        'rsi_neutral': f"RSI Neutral Zone: {rsi:.2f}",
        'price_above_support': f"Price > Support: {current_price:.6f} > {support:.6f}*1.005" if support else "support_fallback",
        'volume_sufficient': f"Volume: {current_volume:.2f} > avg({avg_volume:.2f}) * {volume_soft_mult:.2f}",
        'csi_positive': f"CSI: {pre.get('csi', 0):.2f} > 0.0",
        'fast_reversal_core': f"Fast Reversal Core: OBI+Recovery + CVD Surge + RSI"
    }

    for cond_name, cond_value in basic_bypass_conditions.items():
        status = "YES" if cond_value else "NO"
        logger.debug(f"   • {cond_desc.get(cond_name, cond_name)} >> {status}")

    # === TIER 1: Foundation ===
    tier1_activated = False
    tier1_reason = "Blocked"

    if (fast_reversal_core and 
        basic_bypass_conditions['ema_alignment'] and 
        basic_bypass_conditions['histogram_rising'] and 
        basic_bypass_conditions['volume_sufficient']):
        tier1_activated = True
        tier1_reason = "GOD-TIER FAST REVERSAL STACK"
    elif basic_bypass_met_count >= basic_bypass_min:
        tier1_activated = True
        tier1_reason = f"MAJORITY RULE ({basic_bypass_met_count}/{len(basic_bypass_conditions)})"

    if tier1_activated:
        confluence += 30
        logger.debug(f"TIER 1 ACTIVATED >> {tier1_reason} | +30 confluence")

    # === Additional Bonuses ===
    if cvd_divergence or obi_recovery:
        confluence += 15
        logger.debug("   +15 | Pressure Recovery Bonus (CVD div or OBI recovery)")

    if fast_reversal_core and fast_reversal_boosters >= 2:
        confluence += 25
        logger.debug(f"   +25 | Ultra-Fast Reversal Bonus (boosters={fast_reversal_boosters})")

    # === HIGHER TIERS (only if Tier 1 passed) ===
    if tier1_activated:
        # Tier 2 - Strong Trend
        if trend_strength_proxy > 0.40:
            confluence += 40
            atr_bypass_tier = max(atr_bypass_tier, 2)
            logger.debug("TIER 2 ACTIVATED (Strong Trend) >> +40 confluence")

        # Tier 3 - Pressure Explosion
        pressure_surge = (cvd_change_pct > 10 and obi_imbalance > 0.05 and high_vol)
        if pressure_surge:
            confluence += 20
            atr_bypass_tier = 4
            logger.debug("TIER 3 ACTIVATED (Pressure Explosion) >> +20 confluence")

        # Tier 4 - Sentiment Surge
        flip_detected = (btc_ig == 'bullish' and pre.get('last_btc_ig', 'neutral') in ['bearish', 'neutral'])
        if flip_detected and pre.get('csi', 0) > 0.50 and obi_recovery:
            confluence += 30
            atr_bypass_tier = max(atr_bypass_tier, 3)
            logger.debug("TIER 4 ACTIVATED (Sentiment Surge + Flip) >> +30 confluence")                    

    # EMA Dominant Shortcut
    if (full_ema_stack and 
        current_price > ema_5 * 1.005 and 
        50 < rsi < 75 and 
        current_volume > avg_volume * volume_soft_mult and 
        (obi > obi_relax or cvd_change_pct > 0)):
        confluence += 15
        logger.debug("   +15 | EMA-Dominant Stack Shortcut")

    # -----------------------------
    # LOW ATR BYPASS LOGIC
    # -----------------------------
    if atr_percent < atr_threshold and tier1_activated:
        atr_bypass_active = True
        # Relax threshold based on tier strength
        relaxation_factor = 0.70 - (atr_bypass_tier * 0.08)
        atr_threshold *= max(0.55, relaxation_factor)
        atr_threshold = max(0.20, atr_threshold)
        logger.debug(f"ATR BYPASS ACTIVE >> Tier {atr_bypass_tier} | Threshold relaxed to {atr_threshold:.3f}")

    # Recent bounce
    is_recent_bounce = False

    if support and support > 0 and atr and atr > 0:
        # Normal case: support exists
        is_recent_bounce = current_price > support * 1.002 and current_price < support + atr * 3.0
    else:
        # Fallback when support is None or invalid
        support_fallback = current_price * 0.98
        is_recent_bounce = current_price > support_fallback and current_price < support_fallback + (atr * 3.0 if atr and atr > 0 else 0)

    logger.debug(f"is_recent_bounce: {is_recent_bounce} (support={support}, atr={atr}, price={current_price}, fallback={support_fallback if 'support_fallback' in locals() else 'N/A'})")

    # BTC_IG flip bonus
    last_btc_ig = pre.get('last_btc_ig', 'neutral')
    flip_detected = (btc_ig == 'bullish' and last_btc_ig in ['bearish', 'neutral'])
    if flip_detected:
        confluence += 1
        logger.debug("BTC_IG flip -> +20 confluence")
    pre['last_btc_ig'] = btc_ig
    await save_state()
        
    # ==========================================================
    # PATTERN 6 : EMA Momentum Alignment (Elite)
    # ==========================================================
    pattern6_score = 0.0

    # Core EMA Stack
    if ema_5 > ema_9 > ema_13 > ema_21 and ema_21 > ema_50 * 0.995:
        pattern6_score += 40
        
    if ema_9 > ema_21 > ema_50 and pattern6_score == 0.0:
        pattern6_score += 30
            
    # MACD Confirmation
    if macd_line > signal_line:
        pattern6_score += 15
        
    # Price Above EMA Stack
    ema_max = max(ema_5, ema_9, ema_21, ema_50)
    if current_price > ema_max * 1.005:
        pattern6_score += 10
        
    # RSI Healthy Zone
    if 48 < rsi < 75:
        pattern6_score += 15
        
    # Volume + ATR Support
    if current_volume > avg_volume * 0.9 and atr_percent > atr_threshold * 0.7:
        pattern6_score += 10
        
    # Bull Regime Boost
    if regime == "trend_bull":
        pattern6_score += 8
        
    # === PENALTIES ===
    if cvd_change_pct < -12 and obi < -0.12:
        pattern6_score -= 20
        
    if bb_width_proxy < 0.012:
        pattern6_score -= 10
        
    if near_recent_top:
        pattern6_score -= 10
        
    if overextended_price:
        pattern6_score -= 8
        
    if distance_from_low_pct > 4.5:
        pattern6_score -= 8

    # Precision: range-high grind (stack intact, RSI hot, sitting on the 5-bar high)
    if near_recent_top and rsi >= 68:
        pattern6_score -= 12
    if near_recent_top and obi < 0:
        pattern6_score -= 8

    # ==========================================================
    # ANTI-DECELERATION PENALTIES for PATTERN 6  (UNCHANGED)
    # ==========================================================
    fade_score = 0.0
    fade_count = 0

    if rsi < rsi_prev - 0.5:
        fade_strength = rsi_prev - rsi
        fade_count += 1
        if fade_strength > 5.0:
            fade_score -= 18
            logger.debug(f"[P6 FADE] Strong RSI fading by {fade_strength:.2f} >> -18")
        else:
            fade_score -= 11
            logger.debug(f"[P6 FADE] RSI fading by {fade_strength:.2f} >> -11")
    else:
        logger.debug(f"[P6 FADE] RSI stable or rising (+{rsi - rsi_prev:.2f}) >> OK")

    if histogram < prev_histogram:
        fade_strength = prev_histogram - histogram
        fade_count += 1
        if fade_strength > 0.0008:
            fade_score -= 20
            logger.debug(f"[P6 FADE] Strong Histogram fading by {fade_strength:.5f} >> -20")
        elif fade_strength > 0.0003:
            fade_score -= 13
            logger.debug(f"[P6 FADE] Histogram fading by {fade_strength:.5f} >> -13")
        else:
            fade_score -= 8
    else:
        logger.debug(f"[P6 FADE] Histogram rising (+{histogram - prev_histogram:.5f}) >> Good")

    ema_max = max(ema_5, ema_9, ema_21, ema_50)
    if current_price < prev_close * 0.998 and current_price < ema_max * 0.999:
        fade_score -= 10
        logger.debug(f"[P6 FADE] Price pulling back below EMAs >> -10")

    if fade_count >= 2:
        fade_score -= 12
        logger.debug(f"[P6 FADE] Multi-Fade detected ({fade_count}) >> Extra -12")

    if fade_count >= 1 and regime in ["trend_bear", "compression"]:
        fade_score -= 9
        logger.debug(f"[P6 FADE] Fade in weak regime >> Extra -9")

    pattern6_score += fade_score
    logger.debug(f"[P6 FADE SUMMARY] Total fade penalty: {fade_score:+.1f} | Score now: {pattern6_score:.1f}")

    pattern6_score = max(0, min(100, pattern6_score))
    match_pct6 = round(pattern6_score)    
    
    pattern6_valid = (
        pattern6_score >= 85 and
        regime in ["trend_bull", "reversal_up"] and
        confluence >= 45 and
        not hard_no_buy and
        top_risk_score < 55 and
        not (near_recent_top and price_extension_pct > 2.0) and
        not (near_recent_top and rsi >= 68) and
        not (near_recent_top and obi < 0 and cvd < prev_cvd)
    )
    if pattern6_valid:
        patterns.append({
            'number': 6,
            'name': 'EMA Momentum Alignment (Elite)',
            'match_pct': match_pct6,
            'valid': True
        })
        
    # ==========================================================
    # PATTERN 15 : Momentum Acceleration (Elite)
    # ==========================================================
    pattern15_score = 0.0

    if rsi > rsi_prev + 1.5:
        pattern15_score += 15
        
    if macd_line > prev_macd + 0.0005:
        pattern15_score += 15
       
    if histogram > max(prev_histogram, -0.001):
        pattern15_score += 15
        
    if atr_percent > atr_threshold * 0.7 and rsi < 72 and bb_width_proxy > 0.015:
        pattern15_score += 20
        
    if current_price > ema_21 * 0.998:
        pattern15_score += 10
       
    if current_price > prev_close * 1.002:
        pattern15_score += 10
        
    if is_recent_bounce:
        pattern15_score += 10
       
    if current_volume > avg_volume * 1.2:
        pattern15_score += 5
        
    if cvd > prev_cvd * 1.05:
        pattern15_score += 5
        
    if obi > 0.15 and (obi > prev_obi or obi_recovery):
        pattern15_score += 5
        
    if obi_recovery:
        pattern15_score += 5
        
    if regime in ["trend_bull", "reversal_up"]:
        pattern15_score += 8
        
    if cvd_change_pct < -12 and obi < -0.12:
        pattern15_score -= 20
        
    if bb_width_proxy < 0.012:
        pattern15_score -= 8
        
    if near_recent_top:
        pattern15_score -= 12
        
    if overextended_price:
        pattern15_score -= 10
        
    if distance_from_low_pct > 5.0:
        pattern15_score -= 8

    if near_recent_top and rsi >= 70:
        pattern15_score -= 10

    # ==========================================================
    # ANTI-DECELERATION PENALTIES (UNCHANGED)
    # ==========================================================
    fade_score = 0.0
    fade_count = 0

    if rsi < rsi_prev:
        fade_strength = rsi_prev - rsi
        fade_count += 1
        if fade_strength > 8.0:
            fade_score -= 22
            logger.debug(f"[P15 FADE] STRONG RSI fading by {fade_strength:.2f} points >> -22")
        elif fade_strength > 2.0:
            fade_score -= 16
            logger.debug(f"[P15 FADE] Moderate RSI fading by {fade_strength:.2f} points >> -16")
        else:
            fade_score -= 9
            logger.debug(f"[P15 FADE] Light RSI fading by {fade_strength:.2f} points >> -9")
    else:
        logger.debug(f"[P15 FADE] RSI is rising (+{rsi - rsi_prev:.2f}) >> No penalty")

    if histogram < prev_histogram:
        fade_strength = prev_histogram - histogram
        fade_count += 1
        if fade_strength > 0.0008:
            fade_score -= 22
            logger.debug(f"[P15 FADE] STRONG Histogram fading by {fade_strength:.5f} >> -22")
        elif fade_strength > 0.0003:
            fade_score -= 14
            logger.debug(f"[P15 FADE] Moderate Histogram fading by {fade_strength:.5f} >> -14")
        else:
            fade_score -= 8
            logger.debug(f"[P15 FADE] Light Histogram fading by {fade_strength:.5f} >> -8")
    else:
        logger.debug(f"[P15 FADE] Histogram is rising (+{histogram - prev_histogram:.5f}) >> No penalty")

    if fade_count >= 2:
        fade_score -= 12
        logger.debug(f"[P15 FADE] MULTI-FADE detected ({fade_count}/2 indicators fading) >> Extra -12")
    elif fade_count == 1:
        logger.debug(f"[P15 FADE] Single indicator fading >> No extra multi penalty")

    if fade_count >= 1 and regime in ["trend_bear", "reversal_down", "compression"]:
        fade_score -= 10
        logger.debug(f"[P15 FADE] Fading momentum in WEAK regime ({regime}) >> Extra -10")

    pattern15_score += fade_score
    logger.debug(f"[P15 FADE SUMMARY] Total fade penalty: {fade_score:+.1f} | Final score after fade: {pattern15_score:.1f}")

    pattern15_score = max(0, min(100, pattern15_score))
    match_pct15 = round(pattern15_score)

    accel_count = sum([
        rsi > rsi_prev + 1.5,
        macd_line > prev_macd + 0.0005,
        histogram > prev_histogram
    ])
    
    pattern15_valid = (
        pattern15_score >= 85 and
        accel_count >= 2 and
        confluence >= 42 and
        regime != "compression" and
        atr_percent >= 1.0 and
        current_volume <= avg_volume * 2.5 and
        not hard_no_buy and
        top_risk_score < 55 and
        not (near_recent_top and price_extension_pct > 2.2) and
        not (near_recent_top and rsi >= 70)
    )
    if pattern15_valid:
        patterns.append({
            'number': 15,
            'name': 'Momentum Acceleration (Elite)',
            'match_pct': match_pct15,
            'valid': True
        })
        
    # ==========================================================
    # PATTERN 16 : Super-Power Rally Predictor (Ultra-Strong Bull Rally)
    # ==========================================================
    pattern16_score = 0.0
    
    # Critical: Perfect EMA stack with strong price dominance
    if (ema_5 > ema_9 > ema_13 > ema_21 > ema_50 and 
        current_price > ema_5 * 1.01 and current_price > ema_50 * 1.02):
        pattern16_score += 40
        
    # Strong sustainable momentum surge
    if (macd_line > signal_line > 0 and histogram > prev_histogram * 1.2 and 
        60 < rsi < 78 and rsi > rsi_prev + 2):
        pattern16_score += 30
       
    # Volume surge with breakout confluence
    if (current_volume > avg_volume * 2.0 and trend_strength_proxy > 2.0 and 
        current_price > vwap * 1.015 and current_price > prev_high * 1.002):
        pattern16_score += 25
        
    # Pressure confirmations (strong buying build-up)
    if cvd > 0 and cvd_change_pct > (20 if 'high_vol' in locals() and high_vol else 10):
        pattern16_score += 5
        
    if obi > 0.2 and obi_imbalance > 0.05:
        pattern16_score += 5
        
    # Strong penalty for conflicting bearish pressure
    if cvd_change_pct < -12 and obi < -0.12:
        pattern16_score -= 35
       
    # Final Score Processing
    pattern16_score = max(0.0, min(100.0, pattern16_score))
    match_pct16 = round(pattern16_score)
    
    if pattern16_score >= 85:
        patterns.append({
            'number': 16,
            'name': 'Super-Power Rally Predictor',
            'match_pct': match_pct16,
            'valid': True
        })
        
    # ==========================================================
    # PATTERN 18 : Bearish Rebound Hunter
    # ==========================================================
    pattern18_score = 0.0
    
    # === POSITIVE CONDITIONS ===
    if 15 < rsi < 25:
        pattern18_score += 35
        
    if rsi > rsi_prev + 0.5:
        pattern18_score += 18
       
    if -0.7 < pre.get('csi', 0) < -0.25:
        pattern18_score += 12
       
    if histogram > prev_histogram * 0.95 or (histogram > -0.001 and prev_histogram < -0.001):
        pattern18_score += 15
        
    if current_price < ema_50 * 0.985:
        pattern18_score += 10
        
    if cvd_divergence:
        pattern18_score += 10
       
    if cvd > prev_cvd and cvd > 0:
        pattern18_score += 12
       
    if obi > 0.05:
        pattern18_score += 8
       
    if atr > prev_atr * 1.1:
        pattern18_score += 6
        
    if obi_recovery:
        pattern18_score += 10
        
    if current_volume > avg_volume * 1.1:
        pattern18_score += 7
        
    if regime == "reversal_up":
        pattern18_score += 10
       
    # === PENALTY ===
    if cvd_change_pct < -8 or obi < -0.15 or current_price > price_low * 1.0045:
        pattern18_score -= 30
        
    # Final Score Processing
    pattern18_score = max(0, min(100, pattern18_score))
    match_pct18 = round(pattern18_score)
    
    if pattern18_score >= 85:
        patterns.append({'number': 18, 'name': 'Bearish Rebound Hunter', 'match_pct': match_pct18, 'valid': True})
        
    # ==========================================================
    # PATTERN 22 : Ultra Bearish Rebound
    # ==========================================================
    pattern22_score = 0.0
    
    # === POSITIVE CONDITIONS ===
    if rsi < 15:
        pattern22_score += 30
       
    if rsi > rsi_prev:
        pattern22_score += 5
       
    if cvd_divergence or (cvd > prev_cvd and cvd_change_pct > 3):
        pattern22_score += 12
        
    if obi_recovery or (obi > 0.05 and obi > prev_obi):
        pattern22_score += 10
       
    if histogram > prev_histogram:
        pattern22_score += 15
        
    if current_price < ema_50 * 0.97:
        pattern22_score += 5
        
    if current_volume > avg_volume:
        pattern22_score += 5
        
    if atr > prev_atr * 1.2:
        pattern22_score += 5
        
    if cvd_change_pct > 8 and obi > 0.08:
        pattern22_score += 8
       
    if current_price < ema_50 * 0.95:
        pattern22_score += 5
       
    if regime == "reversal_up":
        pattern22_score += 10
        
    # Final Score Processing
    pattern22_score = max(0, min(100, pattern22_score))
    match_pct22 = round(pattern22_score)
   
    if pattern22_score >= 85:
        patterns.append({'number': 22, 'name': 'Ultra Bearish Rebound', 'match_pct': match_pct22, 'valid': True})

    # ==========================================================
    # PATTERN 9 : VWAP Reclaim + Orderflow Flip (Neutral / mid-range)
    # Owns: range. Requires a true reclaim (was below VWAP).
    # ==========================================================
    pattern9_score = 0.0
    vwap_reclaim = (prev_close < vwap) and (current_price > vwap * 1.0005)
    not_chasing_vwap = current_price <= vwap * 1.015

    if vwap_reclaim:
        pattern9_score += 35
    if not_chasing_vwap:
        pattern9_score += 12
    if obi_recovery or (obi > 0.0 and obi > prev_obi):
        pattern9_score += 15
    if cvd > prev_cvd:
        pattern9_score += 12
    if histogram > prev_histogram:
        pattern9_score += 10
    if 40 < rsi < 65:
        pattern9_score += 10
    if current_volume > avg_volume * 0.90:
        pattern9_score += 8
    if current_price > bb_lower * 1.002:
        pattern9_score += 5

    if near_recent_top:
        pattern9_score -= 18
    if rsi > 70:
        pattern9_score -= 15
    if cvd_change_pct < -10 and obi < -0.12:
        pattern9_score -= 20
    if regime == "reversal_down":
        pattern9_score -= 18
    if overextended_price:
        pattern9_score -= 12

    pattern9_score = max(0, min(100, pattern9_score))
    match_pct9 = round(pattern9_score)
    pattern9_valid = (
        pattern9_score >= 85 and
        vwap_reclaim and
        not hard_no_buy and
        top_risk_score < 55 and
        regime not in ["reversal_down"] and
        not (near_recent_top and price_extension_pct > 1.8)
    )
    if pattern9_valid:
        patterns.append({
            'number': 9,
            'name': 'VWAP Reclaim Orderflow Flip',
            'match_pct': match_pct9,
            'valid': True
        })

    # ==========================================================
    # PATTERN 11 : Mid-Bear Relief (RSI 26-42)
    # Owns: normal bear bounce. 18 is 15-25, 22 is <15.
    # ==========================================================
    pattern11_score = 0.0
    mid_os_rsi = (26 <= rsi <= 42)
    structure_demand = False
    if support and support > 0 and current_price <= support * 1.012:
        structure_demand = True
    if fib_61_8 and fib_61_8 > 0 and abs(current_price - fib_61_8) / fib_61_8 <= 0.012:
        structure_demand = True
    if current_price <= bb_lower * 1.008:
        structure_demand = True

    if mid_os_rsi:
        pattern11_score += 32
    if rsi > rsi_prev + 0.4:
        pattern11_score += 15
    if regime == "trend_bear" or (current_price < ema_21 and macd_line < signal_line):
        pattern11_score += 15
    if structure_demand:
        pattern11_score += 12
    if histogram > prev_histogram:
        pattern11_score += 12
    if cvd_divergence or obi_recovery:
        pattern11_score += 12
    if current_volume > avg_volume:
        pattern11_score += 6

    if rsi < 25:
        pattern11_score -= 30
    if rsi > 45:
        pattern11_score -= 18
    if current_price > ema_21 * 1.012:
        pattern11_score -= 15
    if cvd_change_pct < -10 and obi < -0.15:
        pattern11_score -= 20
    if current_price > price_low * 1.018:
        pattern11_score -= 10

    pattern11_score = max(0, min(100, pattern11_score))
    match_pct11 = round(pattern11_score)
    pattern11_valid = (
        pattern11_score >= 85 and
        mid_os_rsi and
        structure_demand and
        histogram > prev_histogram and
        rsi < 43 and
        not hard_no_buy
    )
    if pattern11_valid:
        patterns.append({
            'number': 11,
            'name': 'Mid-Bear Relief',
            'match_pct': match_pct11,
            'valid': True
        })


    # ==========================================================
    # PATTERN 12 : Support Spring (Failed Breakdown)
    # Owns: stop-run reclaim. Structure, not RSI window.
    # ==========================================================
    pattern12_score = 0.0
    ema_max_p7 = max(ema_5, ema_9, ema_21, ema_50)
    spring_support = support if (support and support > 0) else (current_price * 0.98)
    wick_through = price_low <= spring_support * 1.001
    close_back_above = current_price > spring_support * 1.0015
    spring_ok = wick_through and close_back_above

    if spring_ok:
        pattern12_score += 35
    if is_recent_bounce:
        pattern12_score += 15
    if current_volume > avg_volume * 1.15:
        pattern12_score += 12
    if obi_recovery or obi > 0.04:
        pattern12_score += 12
    if rsi > rsi_prev:
        pattern12_score += 10
    if histogram > prev_histogram:
        pattern12_score += 10
    if cvd > prev_cvd:
        pattern12_score += 8

    if near_recent_top:
        pattern12_score -= 25
    if overextended_price:
        pattern12_score -= 15
    if cvd_change_pct < -12 and obi < -0.15:
        pattern12_score -= 20
    if current_price > ema_max_p7 * 1.005:
        pattern12_score -= 12
    if regime == "reversal_down":
        pattern12_score -= 15

    pattern12_score = max(0, min(100, pattern12_score))
    match_pct12 = round(pattern12_score)
    pattern12_valid = (
        pattern12_score >= 85 and
        spring_ok and
        regime != "compression" and
        atr_percent >= 0.8 and
        not hard_no_buy and
        top_risk_score < 55 and
        not (near_recent_top and price_extension_pct > 2.0)
    )
    if pattern12_valid:
        patterns.append({
            'number': 12,
            'name': 'Support Spring',
            'match_pct': match_pct12,
            'valid': True
        })  
           
    # [NEW: Add valid flag once after all appends]
    for p in patterns:
        p['valid'] = p['match_pct'] >= 75  # True/false based on >=50%   

    # Sort by match_pct descending
    patterns.sort(key=lambda x: x['match_pct'], reverse=True)
    return patterns

async def fetch_ohlcv(symbol, timeframe='1h', limit=300):
    """Fetch OHLCV data for indicator calculations."""
    global binance_client
    if binance_client is None:
        await create_binance_client()
    try:
        clean_symbol = symbol.replace('/', '')  # e.g., "ETHUSDT"
        # Use Binance SDK's get_klines (returns [[ts, open, high, low, close, vol, ...]])
        klines = await binance_client.get_klines(symbol=clean_symbol, interval=timeframe, limit=limit)
        # Extract OHLCV: indices 1=open, 2=high, 3=low, 4=close, 5=volume
        ohlcv = np.array([[float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])] for k in klines])
        return ohlcv
    except Exception as e:
        logger.error(f"Error fetching OHLCV for {symbol}: {str(e)}")
        return None
    # No close()—global client reuse

def calculate_ema(prices, period):
    """Calculate Exponential Moving Average."""
    try:
        prices = np.array(prices, dtype=float)
        weights = np.exp(np.linspace(-1., 0., period))
        weights /= weights.sum()
        ema = np.convolve(prices, weights, mode='valid')
        return ema[-1] if len(ema) > 0 else None
    except Exception as e:
        logger.error(f"Error calculating EMA: {str(e)}")
        return None

def calculate_rsi(prices, period=14):
    """Calculate Relative Strength Index (14)."""
    try:
        prices = np.array(prices, dtype=float)
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains[-period:]) if len(gains) >= period else 0
        avg_loss = np.mean(losses[-period:]) if len(losses) >= period else 0
        rs = avg_gain / avg_loss if avg_loss != 0 else float('inf')
        rsi = 100 - (100 / (1 + rs))
        return rsi
    except Exception as e:
        logger.error(f"Error calculating RSI: {str(e)}")
        return None

def fmt_tg(title, rows, extra=None):
    """Build a clean, scannable Telegram message."""
    lines = [f"━━ {title} ━━"]
    for row in rows:
        if row is None:
            continue
        lines.append(str(row))
    if extra:
        lines.append("")
        lines.append(str(extra))
    return "\n".join(lines)    

def calculate_fibonacci_levels(high, low):
    try:
        if high <= low or high <= 0 or low <= 0:
            logger.warning(f"Invalid high/low for Fibonacci: high={high:.8f}, low={low:.8f}")
            return None

        diff = high - low
        fib_levels = {
            '0%': low,
            '23.6%': low + 0.236 * diff,
            '38.2%': low + 0.382 * diff,
            '50%': low + 0.5 * diff,
            '61.8%': low + 0.618 * diff,
            '100%': high
        }
        logger.debug(f"Fibonacci levels calculated: {fib_levels}")
        return fib_levels

    except Exception as e:
        logger.error(f"Error in calculate_fibonacci_levels: {str(e)}")
        return None

def detect_swing_low(ohlcv, lookback=20):
    """
    Detect the most recent swing low in OHLCV data.
   
    Args:
        ohlcv: numpy array with columns [timestamp, open, high, low, close, volume]
        lookback: number of candles to consider for swing low detection (default: 20)
   
    Returns:
        float: price of the detected swing low, or None if none found
    """
    try:
        if ohlcv is None or len(ohlcv) < 5:  # Minimum 5 candles for local minimum
            logger.debug(f"Insufficient OHLCV data for swing low detection: len={len(ohlcv) if ohlcv is not None else 'None'}")
            return None
        
        lows = ohlcv[:, 2]           # Low prices
        current_price = ohlcv[-1, 3] # Latest close price
        
        swing_lows = []
        logger.debug(f"Detecting swing lows: current_price={current_price:.8f}, lookback={lookback}, data_len={len(lows)}")
        
        # Check recent candles for local minima (more flexible than before)
        for i in range(max(3, len(lows) - lookback - 2), len(lows) - 2):
            # Relaxed condition: lower than immediate neighbors + below current price
            is_local_minimum = (
                lows[i] <= lows[i - 1] and
                lows[i] <= lows[i + 1] and
                lows[i] < current_price * 0.995   # Must be at least 0.5% below current price
            )
            
            if is_local_minimum and lows[i] > 0:
                swing_lows.append((lows[i], pd.to_datetime(ohlcv[i, 0], unit='ms')))
                logger.debug(f"Candidate swing low at index {i}: price={lows[i]:.8f}, time={pd.to_datetime(ohlcv[i, 0], unit='ms')}")

        if not swing_lows:
            logger.debug(f"No swing lows detected for lookback={lookback}, current_price={current_price:.8f}")
            
            # === SMART FALLBACK ===
            recent_low = min(lows[-lookback:]) if len(lows) >= lookback else min(lows)
            if recent_low > 0:
                logger.debug(f"Using recent lowest low as fallback support: {recent_low:.8f}")
                return recent_low
            else:
                fallback = current_price * 0.98
                logger.debug(f"Using price-based fallback support: {fallback:.8f}")
                return fallback

        # Select the most recent swing low
        swing_low = max(swing_lows, key=lambda x: x[1])[0]
        logger.debug(f"Selected swing low: {swing_low:.8f} for current price {current_price:.8f}")
        return swing_low

    except Exception as e:
        logger.error(f"Error in detect_swing_low: {str(e)}")
        return None

def calculate_atr(ohlcv, period=14):
    """Calculate Average True Range."""
    try:
        high = ohlcv[:, 1]
        low = ohlcv[:, 2]
        close = ohlcv[:, 3]
        tr = np.maximum(high - low, np.maximum(abs(high - np.roll(close, 1)), abs(low - np.roll(close, 1))))
        atr = np.mean(tr[-period:]) if len(tr) >= period else 0
        return atr
    except Exception as e:
        logger.error(f"Error calculating ATR: {str(e)}")
        return None

def check_volume_spike(ohlcv, threshold=2.0, periods=10, support_fallback=None, current_price=None):
    """
    Check for a volume spike where the current volume is at least 'threshold' times the average volume 
    of the last 'periods' candles, and the price is near the key support level (within 2%).

    Args:
        ohlcv (numpy.array): OHLCV data with columns [open, high, low, close, volume].
        threshold (float): Multiplier for the average volume (e.g., 2.0 for 2x, default=2.0).
        periods (int): Number of recent periods to calculate the average volume (default=10).
        support_fallback (float): The key support level price.
        current_price (float): The current market price.

    Returns:
        bool: True if volume spike condition is met and price is near support, else False.
    """
    try:
        if len(ohlcv) < periods:
            logger.debug(f"Insufficient data for volume spike check: {len(ohlcv)} < {periods}")
            return False
        
        # Extract volume data
        volumes = ohlcv[:, 4]
        recent_volumes = volumes[-periods:]
        avg_volume = np.mean(recent_volumes)
        current_volume = volumes[-1]
        
        # Check volume condition (at least 2x average by default)
        volume_condition = current_volume >= (1.3 * avg_volume)
        
        # Check price condition (within 2% of support)
        if support_fallback is None or current_price is None:
            logger.debug("Support fallback or current price is None, skipping price condition")
            return volume_condition  # Fallback to volume-only check if support/price unavailable
        else:
            price_condition = abs(current_price - support_fallback) / support_fallback <= 0.02
        
        return volume_condition and price_condition
    except Exception as e:
        logger.error(f"Error checking volume spike: {str(e)}")
        return False

async def get_macd(symbol, fast=12, slow=26, signal=9):
    """Calculate MACD, Signal Line, and Histogram."""
    global binance_client
    if binance_client is None:
        await create_binance_client()
    try:
        ohlcv = await fetch_ohlcv(symbol, limit=slow + signal + 10)  # Fetch extra for signal line (up from default 300 if needed)
        if ohlcv is None or len(ohlcv) < slow:
            logger.error(f"Insufficient OHLCV data for MACD calculation for {symbol}")
            return None, None, None
        closes = ohlcv[:, 3]  # Close prices
        # Calculate EMA for fast and slow periods
        ema_fast = calculate_ema(closes, fast)
        ema_slow = calculate_ema(closes, slow)
        if ema_fast is None or ema_slow is None:
            logger.error(f"EMA calculation failed for MACD for {symbol}")
            return None, None, None
        macd_line = ema_fast - ema_slow
        # Optimized: Build MACD series incrementally (avoids repeated prefix EMAs)
        macd_series = []
        for i in range(slow - 1, len(closes)):
            ema_f = calculate_ema(closes[:i+1], fast)
            ema_s = calculate_ema(closes[:i+1], slow)
            if ema_f is not None and ema_s is not None:
                macd_series.append(ema_f - ema_s)
        if len(macd_series) < signal:
            logger.error(f"Insufficient MACD data for signal line for {symbol}")
            return None, None, None
        signal_line = calculate_ema(np.array(macd_series), signal)
        if signal_line is None:
            logger.error(f"Signal line calculation failed for {symbol}")
            return None, None, None
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram
    except Exception as e:
        logger.error(f"Error calculating MACD for {symbol}: {str(e)}")
        return None, None, None

async def get_bollinger_bands(symbol, period=20, std_dev_multiplier=2):
    """Calculate Bollinger Bands (Middle, Upper, Lower)."""
    global binance_client
    if binance_client is None:
        await create_binance_client()
    try:
        ohlcv = await fetch_ohlcv(symbol, limit=period + 10)  # Fetch extra for robustness (up from default)
        if ohlcv is None or len(ohlcv) < period:
            logger.error(f"Insufficient OHLCV data for Bollinger Bands calculation for {symbol}")
            return None, None, None
        closes = ohlcv[:, 3]  # Close prices
        # Calculate middle band (SMA)
        middle_band = np.mean(closes[-period:])
        # Calculate standard deviation
        std_dev = np.std(closes[-period:])
        upper_band = middle_band + std_dev_multiplier * std_dev
        lower_band = middle_band - std_dev_multiplier * std_dev
        return middle_band, upper_band, lower_band
    except Exception as e:
        logger.error(f"Error calculating Bollinger Bands for {symbol}: {str(e)}")
        return None, None, None

# --- calculate_targets() with improved aggro threshold and phase defaults ---
async def calculate_targets(symbol, entry_price, current_price, atr, atr_percent, fib_extensions, momentum_factor, is_rescue=False, rescue_buy_price=None):
    try:
        if entry_price is None or entry_price <= 0:
            logger.warning(f"Invalid entry_price {entry_price} for {symbol}, using fallback {current_price or 100}")
            entry_price = current_price or 100.0
        if current_price is None or current_price <= 0:
            logger.warning(f"Invalid current_price {current_price} for {symbol}, using entry_price")
            current_price = entry_price

        momentum_factor = float(momentum_factor or 0.0)
        momentum_factor = max(min(momentum_factor, 1.0), 0)
        atr = float(atr or 0.0)
        atr_percent = float(atr_percent or 0.0)
        fib_extensions = fib_extensions or {}

        fib_primary_default = entry_price * 1.035
        fib_secondary_default = entry_price * 1.015
        fib_primary = float(fib_extensions.get("161.8%", fib_primary_default) or fib_primary_default)
        fib_secondary = float(fib_extensions.get("100%", fib_secondary_default) or fib_secondary_default)

        base_primary_target = entry_price * (1.035 + momentum_factor * 0.5)
        base_secondary_target = entry_price * (1.015 + momentum_factor * 0.25)
        atr_primary_target = entry_price + 3 * atr
        atr_secondary_target = entry_price + 1.5 * atr
        primary_target = max(base_primary_target, atr_primary_target, fib_primary) * 1.01
        secondary_target = max(base_secondary_target, atr_secondary_target, fib_secondary) * 1.01
        if secondary_target >= primary_target:
            secondary_target = primary_target * 0.98

        # ===================================================================
        # === STOP-LOSS LOGIC ===
        # ===================================================================
        if is_rescue and rescue_buy_price and rescue_buy_price > 0:
            # Use rescue buy price for stop-loss on rescue
            stop_loss = rescue_buy_price * 0.9019
            stop_loss_source = "Rescue -9.81%"
        else:
            # Regular entry - use original entry price
            stop_loss = entry_price * 0.9319
            stop_loss_source = "Initial -6.81%"

        # ===================================================================
        # === TRAILING STOP - PURE FIXED PERCENTAGE (NO ATR) ===
        # ===================================================================
        if not is_rescue:
            # Regular entry: 6.25% RUN buffer (was 5.75%). Combined with delayed
            # harvest locking this is what lets winners reach +5% to +10%.
            trailing_distance = entry_price * 0.0625
        else:
            # Rescue entry: Pure -8.75% from rescue buy price
            if not rescue_buy_price or rescue_buy_price <= 0:
                rescue_buy_price = current_price

            trailing_distance = rescue_buy_price * 0.0875
            
            logger.info(f"Rescue trailing initialized at exact -8.75% for {symbol} | "
                       f"Rescue Buy: {rescue_buy_price:.6f} | "
                       f"Trailing Stop: {rescue_buy_price - trailing_distance:.6f}")

        # Final Trailing Stop Calculation
        if is_rescue and rescue_buy_price and rescue_buy_price > 0:
            trailing_stop = rescue_buy_price - trailing_distance
        else:
            trailing_stop = entry_price - trailing_distance

        # Safety: Never allow stop_loss above trailing_stop
        if stop_loss > trailing_stop:
            logger.warning(
                f"Stop_loss ({stop_loss}) > trailing_stop ({trailing_stop}) for {symbol}. Adjusting stop_loss lower."
            )
            stop_loss = trailing_stop * 0.99     # ← This line fixes it
            

        # Initialize all state fields
        pre = pre_orders.get(symbol, {})
        pre.update({
            "trailing_distance": trailing_distance,
            "trailing_stop": trailing_stop,
            "trail_confirm_count": 0,
            "last_price": current_price,

            "shadow_active": False,
            "aggro_active": False,
            "surge_active": False,

            "trail_phase": "entry",
            "phase_last_change_time": time.time(),
            "phase_min_cooldown": 180,
            "vwap_reclaim": False,
        })
        pre_orders[symbol] = pre
        await save_state()

        logger.info(
            f"Targets Initialized {symbol} | "
            f"Stop-Loss: {stop_loss:.6f} ({stop_loss_source}) | "
            f"Trailing Stop: {trailing_stop:.6f} | "
            f"Distance: {trailing_distance:.6f} ({(trailing_distance/current_price*100):.2f}%) | "
            f"Primary: {primary_target:.6f} | Secondary: {secondary_target:.6f} | "
            f"{'Rescue' if is_rescue else 'Regular RUN 6.25%'}"
        )

        return {
            "primary_target": primary_target,
            "secondary_target": secondary_target,
            "stop_loss": stop_loss,
            "trailing_stop": trailing_stop,
            "trailing_distance": trailing_distance
        }
    
    except Exception as e:
        logger.error(f"Error calculating targets for {symbol}: {str(e)}")
        return {
            "primary_target": entry_price * 1.045 if entry_price else 104.5,
            "secondary_target": entry_price * 1.025 if entry_price else 102.5,
            "stop_loss": entry_price * 0.9519 if entry_price else 95.19,
            "trailing_stop": entry_price * 0.9525 if entry_price else 95.25,
            "trailing_distance": entry_price * 0.0475 if entry_price else 4.75
        }

async def binance_request(method, endpoint, params=None, body=None):
    global API_CALL_COUNT, API_CALL_WINDOW_START, binance_client
    if binance_client is None:
        await create_binance_client()
    max_retries = 3
    retry_delay = 10
    try:
        logger.info(f"Binance API request: method={method}, endpoint={endpoint}, params={params}, body={body}")
        
        current_time = time.time()
        if current_time - API_CALL_WINDOW_START >= 60:
            API_CALL_COUNT = 0
            API_CALL_WINDOW_START = current_time
        
        API_CALL_COUNT += 1
        if API_CALL_COUNT >= API_RATE_LIMIT_THRESHOLD:
            logger.warning(f"Approaching API rate limit: {API_CALL_COUNT}/{API_RATE_LIMIT_THRESHOLD} calls")
            bot = Bot(TELEGRAM_TOKEN)
            await send_telegram_message(bot, f"Warning: Approaching API rate limit ({API_CALL_COUNT}/{API_RATE_LIMIT_THRESHOLD} calls)")

        for attempt in range(1, max_retries + 1):
            try:
                # Helper: Clean symbol (replace '/' with '') for Binance SDK
                def clean_symbol(s):
                    return s.replace('/', '') if s else ''
                
                if endpoint == "/api/v5/public/instruments":
                    response = await binance_client.get_exchange_info()
                    # Format as list of dicts: instId, lotSize (stepSize), minSz (minQty), minNotional
                    data = []
                    for symbol_info in response['symbols']:
                        if symbol_info['status'] == 'TRADING' and symbol_info['quoteAsset'] in ('USDT', 'USDC'):
                            # Find LOT_SIZE filter (index ~2 usually)
                            lot_size_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'LOT_SIZE'), None)
                            if lot_size_filter:
                                lot_size = lot_size_filter['stepSize']
                                min_sz = lot_size_filter['minQty']
                            else:
                                lot_size = min_sz = '0.00000001'  # Fallback
                            
                            # Find MIN_NOTIONAL filter
                            min_notional_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'MIN_NOTIONAL'), None)
                            min_notional = min_notional_filter['notional'] if min_notional_filter else '10'
                            
                            data.append({
                                "instId": symbol_info['symbol'],  # Keep original slashless for response
                                "lotSize": lot_size,
                                "minSz": min_sz,
                                "minNotional": min_notional
                            })
                
                elif endpoint == "/api/v5/market/ticker":
                    sym = params.get("instId") if params else None
                    if not sym:
                        raise ValueError("Missing instId for ticker")
                    clean_sym = clean_symbol(sym)
                    ticker = await binance_client.get_symbol_ticker(symbol=clean_sym)
                    if not ticker or 'price' not in ticker:
                        raise ValueError(f"No valid ticker data for {sym}")
                    # Wrap in list to match original format
                    data = [{"last": float(ticker['price'])}]
                
                elif endpoint == "/api/v5/account/balances":
                    account = await binance_client.get_account()
                    data = []
                    for b in account['balances']:
                        free = float(b['free'])
                        locked = float(b['locked'])
                        if free > 0 or locked > 0:
                            data.append({
                                "ccy": b['asset'],
                                "availBal": free,
                                "frozenBal": locked
                            })
                
                elif endpoint == "/api/v5/trade/orders-pending":
                    sym = params.get("instId") if params else None
                    if sym:
                        clean_sym = clean_symbol(sym)
                        orders = await binance_client.get_open_orders(symbol=clean_sym)
                    else:
                        # Global fetch (no symbol param)
                        orders = await binance_client.get_open_orders()
                    data = []
                    for o in orders:
                        remaining = float(o['origQty']) - float(o['executedQty'])
                        # Reconstruct slash symbol if needed (SDK returns "ETHUSDT"; script expects "ETH/USDT")
                        o_symbol = o["symbol"]
                        if '/' not in o_symbol:
                            # Split by quote. USDT path is unchanged; USDC is the second lane.
                            if o_symbol.endswith('USDT'):
                                base = o_symbol[:-4]
                                o_symbol = f"{base}/USDT"
                            elif o_symbol.endswith('USDC'):
                                base = o_symbol[:-4]
                                o_symbol = f"{base}/USDC"
                        data.append({
                            "instId": o_symbol,
                            "ordId": o["orderId"],
                            "side": o["side"].upper(),
                            "px": float(o.get("price", 0)),
                            "sz": remaining
                        })
                
                elif endpoint == "/api/v5/trade/order" and method == "GET":
                    sym = params["instId"]
                    clean_sym = clean_symbol(sym)
                    order_id = params["ordId"]
                    order = await binance_client.get_order(symbol=clean_sym, orderId=order_id)
                    if order is None:
                        logger.warning(f"Order fetch returned None for {order_id} on {sym} (likely filled instantly or not found)")
                        data = [{"state": "filled", "accFillSz": 0.0}]
                    else:
                        status_map = {'NEW': 'open', 'PARTIALLY_FILLED': 'partial', 'FILLED': 'filled', 'CANCELED': 'canceled', 'REJECTED': 'rejected'}
                        state = status_map.get(order['status'], order['status'].lower())
                        data = [{"state": state, "accFillSz": float(order['executedQty'])}]
                    logger.info(f"Order status for {order_id}: state={data[0]['state']}, filled={data[0]['accFillSz']}")
                    return data
                
                elif endpoint == "/api/v5/trade/cancel-order":
                    sym = body["instId"]
                    clean_sym = clean_symbol(sym)
                    order_id = body["ordId"]
                    canceled = await binance_client.cancel_order(symbol=clean_sym, orderId=order_id)
                    data = {"ordId": order_id}
                
                elif endpoint == "/api/v5/trade/order" and method == "POST":
                    sym = body["instId"]
                    clean_sym = clean_symbol(sym)
                    side = body["side"].upper()
                    order_type = body["ordType"].lower()
                    
                    if order_type == "market" and side == "BUY":
                        # FIXED: Extract quote_qty from quoteOrderQty or fallback to sz
                        quote_qty = float(body.get("quoteOrderQty", body.get("sz", 0)))
                        if quote_qty <= 0:
                            raise ValueError(f"Invalid quote quantity for market buy: {quote_qty}")
                        # Use SDK with quoteOrderQty
                        response = await binance_client.order_market_buy(symbol=clean_sym, quoteOrderQty=quote_qty)
                    elif order_type == "market" and side == "SELL":
                        # For sell: Use quantity in base asset from sz
                        base_qty = float(body.get("sz", 0))
                        if base_qty <= 0:
                            raise ValueError(f"Invalid base quantity for market sell: {base_qty}")
                        response = await binance_client.order_market_sell(symbol=clean_sym, quantity=base_qty)
                    else:  # Limit orders
                        base_qty = float(body.get("sz", 0))
                        price = float(body.get("px", 0))
                        if base_qty <= 0 or price <= 0:
                            raise ValueError(f"Invalid quantity {base_qty} or price {price} for limit order")
                        if side == "BUY":
                            response = await binance_client.order_limit_buy(symbol=clean_sym, quantity=base_qty, price=price)
                        else:
                            response = await binance_client.order_limit_sell(symbol=clean_sym, quantity=base_qty, price=price)
                    
                    if response and "orderId" in response:
                        data = {"ordId": response["orderId"]}
                    else:
                        logger.error(f"Invalid response from create_order: {response}")
                        data = None
                    
                    return data
                
                else:
                    logger.error(f"Unsupported endpoint or method: {endpoint} {method}")
                    return None

                # Conditional logging to reduce noise
                if endpoint == "/api/v5/public/instruments":
                    logger.info(f"Binance API success on {endpoint}: retrieved {len(data)} instruments")
                elif endpoint == "/api/v5/account/balances":
                    num_balances = len(data)
                    total_usdt_free = sum(b['availBal'] for b in data if b['ccy'] == 'USDT')
                    logger.info(f"Binance API success on {endpoint}: retrieved {num_balances} balances (USDT free: {total_usdt_free:.2f})")
                elif endpoint == "/api/v5/trade/orders-pending":
                    logger.info(f"Binance API success on {endpoint}: retrieved {len(data)} open orders")
                else:
                    logger.info(f"Binance API success on {endpoint}: response={data}")
                
                return data
            except BinanceAPIException as e:
                logger.error(f"Binance API exception on attempt {attempt} for {endpoint}: {str(e)}")
                if attempt < max_retries:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                else:
                    raise e
            except Exception as e:
                logger.error(f"Attempt {attempt} failed for {endpoint}: {str(e)}")
                if attempt < max_retries:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                else:
                    logger.error(f"Max retries reached for {endpoint}")
                    raise e
    except Exception as e:
        logger.error(f"Binance API request failed: endpoint={endpoint}, error={str(e)}")
        raise
    # No client.close() here—global reuse; close only on shutdown

# Function to log price updates to a CSV file
def log_price_history(symbol, price):
    try:
        filename = f"price_history_{symbol.replace('/', '-')}.csv"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        file_exists = os.path.isfile(filename)
        with open(filename, "a", newline="") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["timestamp", "symbol", "price"])
            writer.writerow([timestamp, symbol, f"{price:.6f}"])
        logger.info(f"Logged price for {symbol}: ${price:.6f} at {timestamp}")
    except Exception as e:
        logger.error(f"Error logging price history for {symbol}: {str(e)}")

# Get current price for a symbol
async def get_current_price(symbol):
    """
    Always return the LIVE public price (no API keys).
    Testnet price is deliberately ignored so unstable testnet
    price spikes never affect targets / trailing / logic.
    """
    global live_client
    try:
        if not symbol:
            raise ValueError("Symbol is None or empty")

        if live_client is None:
            await create_binance_clients()

        clean_symbol = symbol.replace('/', '')          # ETH/USDT → ETHUSDT
        logger.debug(f"Fetching LIVE price for {symbol} (API symbol: {clean_symbol})")

        ticker = await live_client.get_symbol_ticker(symbol=clean_symbol)
        price = float(ticker['price']) if ticker and 'price' in ticker else None

        if price and price > 0:
            logger.info(f"LIVE price for {symbol}: ${price:.6f}")
            log_price_history(symbol, price)
            if symbol in pre_orders:
                pre_orders[symbol]["last_price"] = price
            return price

        logger.error(f"Invalid LIVE price received for {symbol}: {price} (ticker: {ticker})")

        # Fallback to last cached price only
        fallback = pre_orders.get(symbol, {}).get("last_price")
        logger.warning(f"Using cached fallback price for {symbol}: {fallback}")
        return fallback

    except Exception as e:
        logger.error(f"Error fetching LIVE price for {symbol}: {str(e)}")
        return pre_orders.get(symbol, {}).get("last_price")

# Function to save state to JSON file
def _lane_state_payload(lane):
    if lane == "USDC":
        sym, last_sym, alloc = SYMBOL2, LAST_SYMBOL2, MAIN_ALLOCATED_USDT.get("USDC")
        items = ((s, p) for s, p in pre_orders.items() if quote_of(s) == "USDC")
    else:
        sym, last_sym, alloc = SYMBOL, LAST_SYMBOL, MAIN_ALLOCATED_USDT.get("USDT")
        items = ((s, p) for s, p in pre_orders.items() if quote_of(s) != "USDC")
    return {
        "SYMBOL": sym,
        "LAST_SYMBOL": last_sym,
        "MAIN_ALLOCATED_USDT": alloc,
        "pre_orders": {
            symbol: _serialize_pre(pre)
            for symbol, pre in items
            if _pre_keep(pre)
        },
    }


async def save_state():
    global binance_client, MAIN_ALLOCATED_USDT
    if binance_client is None:
        await create_binance_client()
    async with state_lock:
        try:
            # Save USDT lane (original AAA.json) and USDC lane (AAA_USDC.json).
            state = _lane_state_payload("USDT")
            _atomic_write_json(STATE_FILE, state)
            _atomic_write_json(STATE_FILE_USDC, _lane_state_payload("USDC"))
            logger.info(f"State saved successfully | Main Capital: {MAIN_ALLOCATED_USDT.get('USDT'):.2f} USDT")
            logger.info(f"USDC lane state saved | Capital: {MAIN_ALLOCATED_USDT.get('USDC'):.2f} USDC | {STATE_FILE_USDC}")
            return
            # Legacy single-file writer kept below but no longer reached.
            state = {
                "SYMBOL": SYMBOL,
                "LAST_SYMBOL": LAST_SYMBOL,
                "MAIN_ALLOCATED_USDT": MAIN_ALLOCATED_USDT.get("USDT"),
                "pre_orders": {
                    symbol: {
                        "order_type": pre.get("order_type", None),
                        "last_btc_ig": pre.get("last_btc_ig", "neutral"),
                        "buy_target": pre.get("buy_target"),
                        "primary_target": pre.get("primary_target"),
                        "secondary_target": pre.get("secondary_target"),
                        "stop_loss": pre.get("stop_loss"),
                        "trailing_stop": pre.get("trailing_stop"),
                        "trailing_distance": pre.get("trailing_distance"),
                        "amount": pre.get("amount"),
                        "current_order_type": pre.get("current_order_type"),
                        "order_count": pre.get("order_count", 0),
                        "last_price": pre.get("last_price"),
                        "last_base_balance": pre.get("last_base_balance"),
                        "last_base_locked": pre.get("last_base_locked"),
                        "entry_price": pre.get("entry_price"),
                        "bullish_adjusted": pre.get("bullish_adjusted", False),
                        "bearish_adjusted": pre.get("bearish_adjusted", False),
                        "last_adjustment_time": pre.get("last_adjustment_time", 0),
                        "btc_ig": pre.get("btc_ig", None),
                        "csi": pre.get("csi", None),
                        "last_bullish": pre.get("last_bullish", None),  # Add last_bullish
                        "deactivation_achieved": pre.get("deactivation_achieved", False),  # NEW: For basic gate persistence
                        "main_scale_count": pre.get("main_scale_count", 0),
                        "main_scale_slice": pre.get("main_scale_slice", 0.0),
                        "main_scale_budget": pre.get("main_scale_budget", 0.0),
                        "main_scale_p1_price": pre.get("main_scale_p1_price"),
                        "main_scale_p2_price": pre.get("main_scale_p2_price"),
                        "main_scale_p3_price": pre.get("main_scale_p3_price"),
                        # New trailing-dip fields
                        "trailing_dip_active": pre.get("trailing_dip_active", False),
                        "dip_level": pre.get("dip_level"),
                        "dip_distance": pre.get("dip_distance"),
                        "dip_tightening_time": pre.get("dip_tightening_time", 0),
                        "original_trigger_price": pre.get("original_trigger_price"),
                        "entry_pattern": pre.get("entry_pattern"),
                        # Rescue count
                        "rescue_count": pre.get("rescue_count", 0),
                        "rescue_used": pre.get("rescue_used", 0.0),
                        # New persistent flip fields for btc_ig pattern20
                        "sell_profit_pct": pre.get("sell_profit_pct", 0.0),
                        "flip_persistence": pre.get("flip_persistence", 0),
                        "last_flip_time": pre.get("last_flip_time", 0),
                        "position_open_time": pre.get("position_open_time"),
                        # ================= NEW: RESCUE TRAILING DIP =================
                        "rescue_trailing_dip_active": pre.get("rescue_trailing_dip_active", False),
                        "rescue_dip_level": pre.get("rescue_dip_level"),
                        "rescue_dip_distance": pre.get("rescue_dip_distance"),
                        "rescue_dip_trigger_price": pre.get("rescue_dip_trigger_price")
                    } for symbol, pre in pre_orders.items()
                    if pre.get("order_type") is None or all(
                        pre.get(key) is not None for key in [
                            "primary_target", "secondary_target", "stop_loss",
                            "trailing_stop", "trailing_distance", "entry_price"
                        ] if pre.get("order_type") == "buy"
                    )  # Only save valid buy states    
                }
            }
            # === SAFE WINDOWS-PROOF SAVE (RECOMMENDED) ===
            temp_file = STATE_FILE + ".tmp"
            backup_file = STATE_FILE + ".backup"

            # 1. Write to temporary file first
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=4)

            # 2. Replace the main file (atomic on most systems)
            if os.path.exists(STATE_FILE):
                # Only replace backup if we can — ignore failure
                try:
                    if os.path.exists(backup_file):
                        os.remove(backup_file)
                    os.replace(STATE_FILE, backup_file)  # Atomic move
                except Exception as e:
                    logger.debug(f"Could not update backup (non-critical): {e}")

            # 3. Now put the new file in place
            os.replace(temp_file, STATE_FILE)  # This is atomic and safe

            logger.info(f"State saved successfully | Main Capital: {MAIN_ALLOCATED_USDT:.2f} USDT")
            
        except Exception as e:
            logger.error(f"Error saving state: {str(e)}")
            try:
                bot = Bot(TELEGRAM_TOKEN)
                await send_telegram_message(bot, f"State save failed: {str(e)}")
            except:
                pass
        
# Function to load and validate state
async def _merge_usdc_state():
    """Load AAA_USDC.json into SYMBOL2 / pre_orders. Does not touch USDT keys or Isaac."""
    global SYMBOL2, LAST_SYMBOL2, MAIN_ALLOCATED_USDT
    if not os.path.exists(STATE_FILE_USDC):
        logger.info("No USDC state file found, USDC lane idle until /pair2")
        return
    try:
        with open(STATE_FILE_USDC, "r", encoding="utf-8") as f:
            state = json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding USDC state file {STATE_FILE_USDC}: {e}")
        MAIN_ALLOCATED_USDT.set(5000.0, "USDC")
        return
    SYMBOL2 = state.get("SYMBOL") or None
    LAST_SYMBOL2 = state.get("LAST_SYMBOL") or None
    MAIN_ALLOCATED_USDT.set(state.get("MAIN_ALLOCATED_USDT", 5000.0), "USDC")
    for s in list(pre_orders):
        if quote_of(s) == "USDC":
            del pre_orders[s]
    symbols_data = await binance_request("GET", "/api/v5/public/instruments")
    valid_symbols = [s["instId"] for s in symbols_data] if symbols_data else []
    loaded = 0
    for symbol, pre in (state.get("pre_orders") or {}).items():
        if quote_of(symbol) != "USDC":
            logger.warning(f"Ignoring non-USDC symbol in {STATE_FILE_USDC}: {symbol}")
            continue
        clean_symbol = symbol.replace("/", "")
        if valid_symbols and clean_symbol not in valid_symbols:
            logger.warning(f"Removing invalid USDC pair from state: {symbol}")
            continue
        pre_orders[symbol] = _hydrate_pre(pre)
        loaded += 1
    logger.info(f"USDC state loaded | pairs={loaded} | symbol={SYMBOL2} | capital={MAIN_ALLOCATED_USDT.get('USDC'):.2f}")


async def _load_usdt_state_body():
    global SYMBOL, LAST_SYMBOL, pre_orders, MAIN_ALLOCATED_USDT
    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    SYMBOL = state.get("SYMBOL") if state.get("SYMBOL") else None
    LAST_SYMBOL = state.get("LAST_SYMBOL") if state.get("LAST_SYMBOL") else None
    # ==================== LOAD MAIN ALLOCATED CAPITAL ====================
    MAIN_ALLOCATED_USDT.set(state.get("MAIN_ALLOCATED_USDT", 5000.0), "USDT")
    logger.info(f" Loaded Main Allocated Capital: {MAIN_ALLOCATED_USDT:.2f} USDT")
    # ===================================================================
    pre_orders.clear()

    # Clean pre_orders keys: Normalize and merge _SPBL dups to clean symbol
    cleaned_pre = {}
    for sym, pre in state.get("pre_orders", {}).items():
        clean_sym = sym
        if clean_sym in cleaned_pre:
            cleaned_pre[clean_sym].update(pre)  # Merge/overwrite with latest
            logger.debug(f"Merged duplicate state for {clean_sym}")
        else:
            cleaned_pre[clean_sym] = pre

    symbols_data = await binance_request("GET", "/api/v5/public/instruments")
    valid_symbols = [s["instId"] for s in symbols_data] if symbols_data else []

    for symbol, pre in cleaned_pre.items():
        # Clean for validation (strip / to match API e.g., "SOLUSDT")
        clean_symbol = symbol.replace('/', '')
        if clean_symbol not in valid_symbols:
            logger.warning(f"Removing invalid pair from state: {symbol} (clean: {clean_symbol} not in API symbols)")
            continue   
                    
        pre_orders[symbol] = {
            "order_type": pre.get("order_type", None),
            "last_btc_ig": pre.get("last_btc_ig", "neutral"),
            "last_bullish": pre.get("last_bullish", None),  # Ensure True default
            "buy_target": pre.get("buy_target"),
            "primary_target": pre.get("primary_target"),
            "secondary_target": pre.get("secondary_target"),
            "stop_loss": pre.get("stop_loss"),
            "trailing_stop": pre.get("trailing_stop"),
            "trailing_distance": pre.get("trailing_distance"),
            "amount": pre.get("amount", 0.0),
            "current_order_type": pre.get("current_order_type", None),
            "order_count": pre.get("order_count", 0),
            "last_price": pre.get("last_price"),
            "last_base_balance": pre.get("last_base_balance", 0.0),
            "last_base_locked": pre.get("last_base_locked", 0.0),
            "entry_price": pre.get("entry_price"),
            "bullish_adjusted": pre.get("bullish_adjusted", False),
            "bearish_adjusted": pre.get("bearish_adjusted", False),
            "last_adjustment_time": pre.get("last_adjustment_time", 0),
            "btc_ig": pre.get("btc_ig", None),
            "csi": pre.get("csi", None),
            "last_status_time": pre.get("last_status_time", 0),
            "last_csi": pre.get("last_csi", 0),
            "main_scale_count": pre.get("main_scale_count", 0),
            "main_scale_slice": pre.get("main_scale_slice", 0.0),
            "main_scale_budget": pre.get("main_scale_budget", 0.0),
            "main_scale_p1_price": pre.get("main_scale_p1_price"),
            "main_scale_p2_price": pre.get("main_scale_p2_price"),
            "main_scale_p3_price": pre.get("main_scale_p3_price"),
            # New trailing-dip fields
            "deactivation_achieved": pre.get("deactivation_achieved", False),
            "trailing_dip_active": pre.get("trailing_dip_active", False),
            "dip_level": pre.get("dip_level"),
            "dip_distance": pre.get("dip_distance"),
            "dip_tightening_time": pre.get("dip_tightening_time", 0),
            "original_trigger_price": pre.get("original_trigger_price"),
            "entry_pattern": pre.get("entry_pattern"),
            # Rescue count
            "rescue_count": pre.get("rescue_count", 0),
            "rescue_used": pre.get("rescue_used", 0.0),
            # New persistent flip fields for btc_ig pattern20
            "sell_profit_pct": pre.get("sell_profit_pct", 0.0),
            "flip_persistence": pre.get("flip_persistence", 0),
            "last_flip_time": pre.get("last_flip_time", 0),
            "position_open_time": pre.get("position_open_time"),
            # ================= NEW: RESCUE TRAILING DIP =================
            "rescue_trailing_dip_active": pre.get("rescue_trailing_dip_active", False),
            "rescue_dip_level": pre.get("rescue_dip_level"),
            "rescue_dip_distance": pre.get("rescue_dip_distance"),
            "rescue_dip_trigger_price": pre.get("rescue_dip_trigger_price")
        }
            

async def load_state():
    global SYMBOL, LAST_SYMBOL, pre_orders, binance_client, MAIN_ALLOCATED_USDT, SYMBOL2, LAST_SYMBOL2
    if binance_client is None:
        await create_binance_client()
    try:
        if not os.path.exists(STATE_FILE):
            logger.info("No state file found, starting with default state")
            # Set default capital if no state file
            MAIN_ALLOCATED_USDT.set(5000.0, "USDT")
        else:
            await _load_usdt_state_body()
        await _merge_usdc_state()

        # NEW: For each loaded pre, ensure flag defaults to False if missing (post-population safety net)
        for sym, pre in list(pre_orders.items()):  # Use list() for safety in case of mods
            pre.setdefault("deactivation_achieved", False)

        # NEW: Force deact if Tdip active but fields missing (invalid state)
        for sym, pre in list(pre_orders.items()):
            if pre.get("trailing_dip_active", False) and (pre.get("dip_level") is None or pre.get("dip_distance") is None):
                pre["trailing_dip_active"] = False
                pre["dip_level"] = None
                pre["dip_distance"] = None
                pre["dip_tightening_time"] = 0
                pre["original_trigger_price"] = None
                logger.warning(f"Forced Tdip deact for {sym}: Active=True but fields missing (load recovery)")

        # <-- ADD: Default targets if buy active and None
        for symbol in pre_orders:
            pre = pre_orders[symbol]
            if pre.get("order_type") == "buy":
                entry = pre.get("entry_price")
                if entry:
                    if pre.get("trailing_stop") is None:
                        pre["trailing_stop"] = entry * 0.98
                        logger.info(f"Defaulted trailing_stop in load for {symbol}: {pre['trailing_stop']:.8f}")
                    if pre.get("stop_loss") is None:
                        pre["stop_loss"] = entry * 0.985
                        logger.info(f"Defaulted stop_loss in load for {symbol}: {pre['stop_loss']:.8f}")

        # NEW: In the for loop (added debug)
        for sym in pre_orders:
            if 'dca_orders' in pre_orders[sym]:
                logger.debug(f"Loaded DCA for {sym}: {len(pre_orders[sym]['dca_orders'])} orders")

        # Safety defaults for Rescue Trailing Dip
        for sym, pre in list(pre_orders.items()):
            # Legacy full-size positions: do not invent P2/P3, keep rescue alive
            if pre.get("order_type") == "buy" and "main_scale_count" not in pre:
                pre["main_scale_count"] = 3
            pre.setdefault("main_scale_count", 0)
            pre.setdefault("main_scale_slice", 0.0)
            pre.setdefault("main_scale_budget", 0.0)
            pre.setdefault("main_scale_p1_price", None)
            pre.setdefault("main_scale_p2_price", None)
            pre.setdefault("main_scale_p3_price", None)
            pre.setdefault("rescue_trailing_dip_active", False)
            pre.setdefault("rescue_dip_level", None)
            pre.setdefault("rescue_dip_distance", None)
            pre.setdefault("rescue_dip_trigger_price", None)

        logger.info(f"State loaded with {len(pre_orders)} valid pairs | Main Capital: {MAIN_ALLOCATED_USDT:.2f} USDT")
        await save_state()  # Persist cleaned state
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding state file {STATE_FILE}: {e}")
        MAIN_ALLOCATED_USDT.set(5000.0, "USDT")
    except Exception as e:
        logger.error(f"Error loading state from {STATE_FILE}: {e}")
        MAIN_ALLOCATED_USDT.set(5000.0, "USDT")

async def backup_state_file():
    """Create timestamped backups and keep only the last 50 files per lane."""
    try:
        os.makedirs(STATE_BACKUP_FOLDER, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        jobs = (
            (STATE_FILE, f"AAA_{timestamp}.json", "AAA_"),
            (STATE_FILE_USDC, f"AAA_USDC_{timestamp}.json", "AAA_USDC_"),
        )
        for src_path, backup_filename, prefix in jobs:
            if not os.path.exists(src_path):
                logger.warning(f"Backup skipped: state file not found at {src_path}")
                continue
            backup_path = os.path.join(STATE_BACKUP_FOLDER, backup_filename)
            shutil.copy2(src_path, backup_path)
            logger.info(f"State backup created: {backup_filename}")
            try:
                backups = []
                for fname in os.listdir(STATE_BACKUP_FOLDER):
                    if not fname.endswith(".json"):
                        continue
                    if prefix == "AAA_USDC_":
                        if fname.startswith("AAA_USDC_"):
                            backups.append(fname)
                    else:
                        # Original AAA_ backups only. Do not eat USDC backups.
                        if fname.startswith("AAA_") and not fname.startswith("AAA_USDC_"):
                            backups.append(fname)
                backups.sort(key=lambda x: os.path.getctime(os.path.join(STATE_BACKUP_FOLDER, x)), reverse=True)
                for old_file in backups[MAX_BACKUP_FILES:]:
                    old_path = os.path.join(STATE_BACKUP_FOLDER, old_file)
                    os.remove(old_path)
                    logger.debug(f"Old backup deleted: {old_file}")
            except Exception as cleanup_error:
                logger.warning(f"Backup cleanup failed: {cleanup_error}")
    except Exception as e:
        logger.error(f"State backup failed: {str(e)}")
    
async def send_telegram_message(bot, message):
    try:
        await bot.send_message(chat_id=TELEGRAM_USER_ID, text=message, parse_mode=None)
        logger.info(f"Telegram message sent: {message}")
    except Exception as e:
        logger.error(f"Error sending Telegram message: {str(e)}")

async def handle_unauthorized(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not update.message or not update.effective_user:
                return
            if str(update.effective_user.id) != TELEGRAM_USER_ID:   # ← Using your existing variable
                logger.warning(f"🚫 Unauthorized access from user_id: {update.effective_user.id}")
                try:
                    await update.message.reply_text("❌ This is a private bot. Access denied.")
                except:
                    pass
                return

# Sync open orders from Binance
async def sync_open_orders():
    global open_orders, binance_client
    if binance_client is None:
        await create_binance_client()
    max_retries = 3
    retry_delay = 5
    attempt = 1

    while attempt <= max_retries:
        try:
            temp_orders = []
            logger.debug(f"Attempt {attempt}: Fetching open orders from Binance API")
            data = await binance_request("GET", "/api/v5/trade/orders-pending")
            if not isinstance(data, list):
                logger.error(f"Invalid data format received for open orders: {data}")
                return
            seen_order_ids = set()
            for order in data:
                order_id = order.get("ordId")
                if not order_id or order_id in seen_order_ids:
                    continue
                seen_order_ids.add(order_id)
                try:
                    quantity = float(order.get("sz", "0"))
                    price = float(order.get("px", "0"))
                    api_symbol = order.get("instId", "")  # Already 'BTC/USDT'
                    symbol = api_symbol  # Store as 'BTC/USDT' internally
                    side = order.get("side", "").upper()
                    if not symbol or not side or quantity <= 0 or price <= 0:
                        logger.warning(f"Invalid order data: symbol={symbol}, side={side}, order={order}")
                        continue
                    temp_orders.append({
                        "symbol": symbol,
                        "orderId": order_id,
                        "side": side,
                        "price": price,
                        "quantity": quantity
                    })
                except (ValueError, TypeError) as e:
                    logger.error(f"Error processing order {order_id}: {str(e)}")
                    continue
            open_orders[:] = temp_orders
            logger.info(f"Synced {len(open_orders)} open orders on attempt {attempt} (Binance)")

            # Update pre_orders for active buy orders to ensure state consistency
            for symbol in pre_orders:
                active_buy_orders = [o for o in open_orders if o["symbol"] == symbol and o["side"] == "BUY"]
                pre = pre_orders[symbol]
                if active_buy_orders and pre.get("order_type") is None:
                    pre["order_type"] = "buy"
                    logger.info(f"Updated pre_orders for {symbol}: set order_type to 'buy' due to active buy order")
                    # Ensure targets are preserved if previously set
                    if not pre.get("entry_price") and active_buy_orders:
                        # Use the price of the first active buy order as a fallback entry price
                        pre["entry_price"] = active_buy_orders[0]["price"]
                        logger.debug(f"Set fallback entry_price for {symbol}: {pre['entry_price']:.6f}")
                        # Recalculate targets if none exist
                        current_price = await get_current_price(symbol)
                        indicators = await get_cached_indicators(symbol, current_price)
                        
                        if indicators:
                            atr = indicators["atr"]
                            atr_percent = (atr / current_price * 100) if atr and current_price else 0.0
                            rsi = indicators["rsi"]
                            momentum_factor = rsi / 100 if rsi else 0.0
                            fib_extensions = indicators.get("fib_levels", {})
                            targets = await calculate_targets(
                                symbol, pre["entry_price"], current_price, atr, atr_percent, fib_extensions, momentum_factor
                            )
                            pre["primary_target"] = targets["primary_target"]
                            pre["secondary_target"] = targets["secondary_target"]
                            pre["stop_loss"] = targets["stop_loss"]
                            pre["trailing_distance"] = targets["trailing_distance"]
                            pre["trailing_stop"] = targets["trailing_stop"]
                            logger.info(f"Recalculated targets for {symbol} due to active buy order")
                            if not pre.get("primary_target") or not pre.get("secondary_target") or not pre.get("stop_loss"):
                                logger.warning(f"Skipping state save for {symbol}: Invalid targets after sync")
                            else:
                                await save_state()
                    
            # Successful sync, break the retry loop
            return

        except Exception as e:
            logger.error(f"Error syncing open orders on attempt {attempt}: {str(e)}")
            if attempt == max_retries:
                # Max retries reached, notify user and exit
                bot = Bot(TELEGRAM_TOKEN)
                await send_telegram_message(bot, f"Failed to sync open orders after {max_retries} attempts: {str(e)}")
                logger.error(f"Max retries ({max_retries}) reached for syncing open orders")
                return
            # Wait before retrying
            logger.info(f"Retrying sync_open_orders in {retry_delay} seconds...")
            await asyncio.sleep(retry_delay)
            attempt += 1

# Round quantity to step size - Final Safe Version
def round_to_step_size(quantity, step_size):
    if quantity <= 0 or step_size is None or step_size <= 0:
        return quantity
    
    try:
        # Special case for DOGE and tokens with stepSize = 1.0
        if step_size >= 1.0:
            return math.floor(quantity)               # Force whole number
        
        # Normal case for other tokens
        rounded = math.floor(quantity / step_size) * step_size
        
        # Safe precision calculation
        try:
            precision = int(round(-math.log10(step_size)))
            precision = max(0, precision)
        except:
            precision = 8
        
        return round(rounded, precision)
    
    except Exception as e:
        logger.error(f"Error in round_to_step_size: quantity={quantity}, step_size={step_size}, error={str(e)}")
        return math.floor(quantity)   # Safe fallback

# Calculate profit percentage
def calculate_profit_percentage(sell_price, initial_buy_price):
    if initial_buy_price <= 0:
        return 0.0
    return ((sell_price - initial_buy_price) / initial_buy_price) * 100

# Place limit or market order
async def place_order(side, price, quantity, symbol, order_type="limit", total_cost=None, is_rescue=False, use_exact_cost=False):
    global binance_client, MAIN_ALLOCATED_USDT
    if binance_client is None:
        await create_binance_client()
    
    try:
        # ==================== SYMBOL INFO & PRECISION ====================
        symbol_info = await binance_request("GET", "/api/v5/public/instruments")
        precision = 8
        step_size = 0.00000001
        min_qty = 0.00000001
        min_notional = 1.0
        api_symbol = symbol
        
        for info in symbol_info:
            if info["instId"] == api_symbol:
                lot_size_str = info.get("lotSize")
                if lot_size_str is not None:
                    try:
                        step_size = float(lot_size_str)
                        precision = int(-math.log10(step_size))
                    except (ValueError, TypeError):
                        pass
                min_sz_str = info.get("minSz") or "0.00000001"
                try:
                    min_qty = float(min_sz_str)
                except (ValueError, TypeError):
                    min_qty = 0.00000001
                min_notional_str = info.get("minNotional") or "1.0"
                try:
                    min_notional = float(min_notional_str)
                except (ValueError, TypeError):
                    min_notional = 1.0
                break

        # Log incoming request
        safe_price = price if price is not None else 'N/A'
        safe_quantity = f"{quantity:.8f}" if quantity is not None else 'N/A'
        bind_lane_from_symbol(symbol)
        quote_ccy = quote_of(symbol)
        logger.info(f"Place order: side={side}, price={safe_price}, quantity={safe_quantity}, "
                   f"symbol={symbol}, order_type={order_type}, total_cost={total_cost}, is_rescue={is_rescue}")

        # ==================== MARKET BUY HANDLING (FIXED) ====================
        if order_type == "market" and side == "buy":
            if total_cost is None or total_cost <= 0:
                logger.error(f"Invalid total_cost for market buy order on {symbol}: {total_cost}")
                return None

            # Fetch current USDT balance
            account = await binance_request("GET", "/api/v5/account/balances")
            available = 0.0
            for asset in account or []:
                if asset["ccy"].upper() == quote_ccy:
                    available = float(asset.get("availBal", "0"))
                    break

            # === RESPECT SPECIAL CASES (RESCUE, EXACT COST, ISAAC, etc.) ===
            if is_rescue and total_cost is not None:
                use_amount = total_cost
                logger.info(f"RESCUE BUY: Using caller-specified amount {use_amount:.2f} {quote_ccy}")
            elif use_exact_cost and total_cost is not None:
                use_amount = min(float(total_cost), available)
                logger.info(f"EXACT COST BUY: requested={float(total_cost):.2f} | using={use_amount:.2f} | wallet={available:.2f}")
            else:
                # Normal Main Bot behavior (legacy 100% path — unused by Tdip P1 now)
                main_available = min(available, MAIN_ALLOCATED_USDT)
                use_amount = main_available
                logger.debug(f"Main Bot Market Buy | Allocated Capital: {MAIN_ALLOCATED_USDT:.2f} | Using: {use_amount:.2f} {quote_ccy}")

            total_cost = math.floor(use_amount * 100) / 100   # Floor to 2 decimals
            
            if total_cost < min_notional:
                logger.error(f"Market buy total_cost {total_cost:.2f} below minimum {min_notional:.2f} for {symbol}")
                return None
                
            adjusted_quantity = 0.0  # Not used for market buys

        else:
            # ==================== LIMIT / SELL / OTHER ORDERS ====================
            if price is None and order_type != "market":
                logger.error(f"Invalid price (None) for {side} {order_type} order on {symbol}")
                return None

            adjusted_quantity = round_to_step_size(quantity, step_size) if quantity is not None else 0.0
            if adjusted_quantity < min_qty:
                logger.error(f"Order quantity {adjusted_quantity:.8f} below minimum {min_qty:.8f} for {symbol}")
                return None
            if price and price * adjusted_quantity < min_notional and order_type != "market":
                logger.error(f"Order notional {price * adjusted_quantity:.2f} below minimum {min_notional:.2f} for {symbol}")
                return None

        # ==================== PRICE & BALANCE VALIDATION ====================
        current_price = await get_current_price(symbol) if price is None else price

        # Fetch account balance again for final check
        account = await binance_request("GET", "/api/v5/account/balances")
        base_asset = api_symbol.split('/')[0].upper()
        available = 0.0
        for asset in account:
            if asset["ccy"].upper() == (base_asset if side == "sell" else quote_ccy).upper():
                available = float(asset.get("availBal", "0.0"))
                break

        # For buy orders
        if side == "buy":
            if order_type == "market":
                usdt_required = total_cost
                if usdt_required > available:
                    floored_usdt = math.floor(available * 100) / 100
                    total_cost = floored_usdt
                    logger.info(f"Adjusted market buy total_cost to {total_cost:.2f} (available {quote_ccy}: {available:.2f})")
            else:
                usdt_required = price * adjusted_quantity if price and adjusted_quantity else 0
                if usdt_required > available:
                    floored_usdt = math.floor(available * 100) / 100
                    adjusted_quantity = round_to_step_size(floored_usdt / price, step_size) if price else 0.0
                    usdt_required = price * adjusted_quantity if price else floored_usdt

        # For sell orders
        if side == "sell":
            adjusted_quantity = min(adjusted_quantity, round_to_step_size(available, step_size))
            logger.info(f"Adjusted sell quantity to {adjusted_quantity:.8f} based on available {available:.8f}")

        # Final balance check
        if side == "sell" and adjusted_quantity <= 0:
            logger.error(f"Insufficient {base_asset} balance for {symbol}: {available:.8f} < {adjusted_quantity:.8f}")
            return None
        elif side == "buy" and usdt_required > available:
            logger.error(f"Insufficient {quote_ccy} balance for {symbol}: {available:.2f} < {usdt_required:.2f}")
            return None

        # ==================== BUILD ORDER BODY ====================
        body = {
            "instId": api_symbol,
            "side": side,
            "ordType": order_type
        }
        
        if order_type == "market" and side == "buy":
            body["quoteOrderQty"] = f"{total_cost:.2f}"
            logger.debug(f"Market buy order for {symbol}: quoteOrderQty={total_cost}")
        else:
            sz_value = adjusted_quantity if adjusted_quantity is not None else 0.0
            if not isinstance(precision, int) or precision < 0:
                precision = 8
            body["sz"] = f"{sz_value:.{precision}f}"
            
            if order_type == "limit":
                px_value = price if price is not None else current_price
                body["px"] = f"{px_value:.6f}"

        # ==================== EXECUTE ORDER ====================
        response = await binance_request("POST", "/api/v5/trade/order", body=body)
        
        if response and "ordId" in response:
            if order_type == "market" and side == "buy":
                log_qty = total_cost / current_price if current_price and total_cost else 0.0
                log_price = current_price
            else:
                log_qty = adjusted_quantity if adjusted_quantity is not None else 0.0
                log_price = price if price is not None else current_price
                
            logger.info(f"Placed {side} {order_type} order: {log_qty:.{precision}f} at ${log_price:.6f} "
                       f"({symbol}), Order ID: {response['ordId']}")
            return {
                "orderId": response["ordId"],
                "quantity": log_qty
            }
        else:
            logger.error(f"Failed to place {side} {order_type} order for {symbol}: {response}")
            return None
        
    except Exception as e:
        logger.error(f"Error placing {side} order for {symbol}: {str(e)}", exc_info=True)
        return None

def get_main_scale_slice():
    """1/3 of current MAIN_ALLOCATED_USDT, floored to whole USDT (1694.43 → 1694)."""
    return float(math.floor(float(MAIN_ALLOCATED_USDT) / 3.0))


def init_main_scale_state(pre):
    slice_usdt = get_main_scale_slice()
    pre["main_scale_slice"] = slice_usdt
    pre["main_scale_budget"] = slice_usdt * 3.0
    pre["main_scale_count"] = 0
    pre["main_scale_p1_price"] = None
    pre["main_scale_p2_price"] = None
    pre["main_scale_p3_price"] = None
    return slice_usdt

async def execute_trailing_dip_buy(symbol, current_price, pre, bot, silent=False):
    """
    Execute buy order on trailing dip recovery trigger.
    Args:
        symbol (str): Trading pair (e.g., 'SOL/USDT').
        current_price (float): Current market price.
        pre (dict): Pre-order state dict (for quantity, targets, etc.).
        bot (telegram.Bot): Bot instance for notifications.
        silent (bool): If True, suppress Telegram notification.
    """
    global binance_client, MAIN_ALLOCATED_USDT  
    if binance_client is None:
        await create_binance_client()
    
    try:
        bind_lane_from_symbol(symbol)
        quote_ccy = quote_of(symbol)
        logger.info(f"Executing trailing dip buy for {symbol} at {current_price:.8f}")
        
        # Fetch fresh indicators for targets
        indicators = await get_cached_indicators(symbol, current_price)
        
            
        if indicators is None:
            logger.error(f"Failed to fetch indicators for {symbol} in trailing dip buy")
            return None
        
        # FIXED: Use 100% of entire USDT balance (your original floor)
        account = await binance_request("GET", "/api/v5/account/balances")
        usdt_balance = 0.0
        for asset in account:
            if asset["ccy"].upper() == quote_ccy:
                usdt_balance = float(asset.get("availBal", "0"))
                break
        
        # === P1 uses 1/3 of MAIN (slices frozen in state) ===
        slice_usdt = init_main_scale_state(pre)
        main_available = min(usdt_balance, slice_usdt)
        total_cost = math.floor(main_available * 100) / 100
        logger.info(
            f"P1 SCALE | MAIN={MAIN_ALLOCATED_USDT:.2f} | slice={slice_usdt:.2f} | "
            f"wallet={usdt_balance:.2f} | using={total_cost:.2f}"
        )       
        if total_cost <= 0:
            logger.warning(f"Insufficient total_cost for trailing dip buy on {symbol}: {total_cost}")
            return None
        
        # FIXED: For market buy orders, we only need total_cost, not quantity
        # The place_order function will handle the market buy with total_cost
        order = await place_order(
            "buy", None, None, symbol,
            order_type="market",
            total_cost=total_cost,
            use_exact_cost=True
        )
        
        if order:
            # Fetch status for actual filled quantity (accFillSz)
            params = {"ordId": order["orderId"], "instId": symbol}
            order_status = await binance_request("GET", "/api/v5/trade/order", params=params)
            
            # FIXED: Safely extract filled quantity
            if order_status and isinstance(order_status, list) and len(order_status) > 0:
                actual_quantity = float(order_status[0].get("accFillSz", 0))
                # If no fill quantity returned, calculate from total_cost and current_price
                if actual_quantity <= 0:
                    actual_quantity = total_cost / current_price
            else:
                actual_quantity = total_cost / current_price
            
            if actual_quantity <= 0:
                logger.error(f"Invalid actual_quantity {actual_quantity} for trailing dip buy on {symbol}")
                return None
            
            # Update open_orders with actuals
            open_orders.append({
                "symbol": symbol,
                "orderId": order["orderId"],
                "side": "BUY",
                "price": current_price,
                "quantity": actual_quantity,
                "type": "trailing_dip_buy"
            })
            
            # Update state
            pre["order_type"] = "buy"
            pre["amount"] = actual_quantity
            pre["entry_price"] = current_price
            pre["main_scale_count"] = 1
            pre["main_scale_p1_price"] = current_price
            pre["main_scale_slice"] = slice_usdt
            pre["main_scale_budget"] = slice_usdt * 3.0
            pre["entry_pattern"] = pre.get("entry_pattern", 21)
            pre["trailing_dip_active"] = False  # Deactivate after buy
            pre["dip_level"] = None
            pre["dip_distance"] = None
            pre["original_trigger_price"] = None

            # === NEW: Record Position Open Time (only for the first main buy) ===
            if "position_open_time" not in pre or not pre.get("position_open_time"):
                from datetime import datetime, timezone
                pre["position_open_time"] = datetime.now(timezone.utc).isoformat()
                logger.info(f"✅ Main position open time recorded for {symbol} at {pre['position_open_time']}")
            # =======================================================
            
            # Calculate and set targets
            atr = indicators["atr"]
            atr_percent = (atr / current_price * 100) if atr and current_price else 0.0
            rsi = indicators["rsi"]
            momentum_factor = rsi / 100 if rsi else 0.0
            fib_extensions = indicators.get("fib_levels", {})
            targets = await calculate_targets(symbol, current_price, current_price, atr, atr_percent, fib_extensions, momentum_factor)
            if targets:
                pre["primary_target"] = targets["primary_target"]
                pre["secondary_target"] = targets["secondary_target"]
                pre["stop_loss"] = targets["stop_loss"]
                pre["trailing_distance"] = targets["trailing_distance"]
                pre["trailing_stop"] = targets["trailing_stop"]
            
            await save_state()
            
            # FIXED: Safe notification with proper formatting
            base_asset = symbol.split('/')[0].upper()
            primary_target = pre.get('primary_target', 0)
            secondary_target = pre.get('secondary_target', 0)
            trailing_stop = pre.get('trailing_stop', 0)
            stop_loss = pre.get('stop_loss', 0)
            rsi_str = f"{rsi:.2f}" if rsi else "N/A"
            csi_str = f"{pre.get('csi', 0):.2f}" if pre.get('csi') is not None else "N/A"
            
            message = (
                f"Trailing Dip Buy Executed\n"
                f"{base_asset}: {actual_quantity:.6f} at {current_price:.8f} (Total {quote_ccy}: {total_cost:.2f})\n"
                f"Primary: {primary_target:.8f}\n"
                f"Secondary: {secondary_target:.8f}\n"
                f"Trailing-Stop: {trailing_stop:.8f}\n" 
                f"Stop-Loss: {stop_loss:.8f}\n"
                f"Scale: P1/3 | Slice: {slice_usdt:.2f} {quote_ccy} | Reserved P2+P3: {slice_usdt * 2:.2f}\n"
                f"RSI: {rsi_str}, CSI: {csi_str}"
            )
            logger.info(message)
            if not silent:
                await send_telegram_message(bot, message)
            
            # FIXED: Return enhanced dict with quantity (prevents None in loop)
            return {
                "orderId": order["orderId"],
                "quantity": actual_quantity,
                "total_cost": total_cost  # Optional: For loop cost verification
            }
        else:
            logger.error(f"Failed to place trailing dip buy order for {symbol}")
            return None
        
    except Exception as e:
        logger.error(f"Error in execute_trailing_dip_buy for {symbol}: {str(e)}")
        # Reset on failure to prevent loop
        if symbol in pre_orders:
            pre_orders[symbol]["trailing_dip_active"] = False
            pre_orders[symbol]["dip_level"] = None
            pre_orders[symbol]["dip_distance"] = None
            pre_orders[symbol]["original_trigger_price"] = None
        await save_state()
        return None  # FIXED: Explicit None on fail, loop checks if order

async def execute_main_scale_add(symbol, current_price, pre, bot, purchase_n):
    """
    Direct P2 or P3 add. Price-only. No pattern / Tdip / blockers.
    Trigger is handled by the caller (TS * 1.02, TS underwater).
    """
    global MAIN_ALLOCATED_USDT
    try:
        bind_lane_from_symbol(symbol)
        quote_ccy = quote_of(symbol)
        slice_usdt = float(pre.get("main_scale_slice") or get_main_scale_slice())
        slice_usdt = math.floor(slice_usdt * 100) / 100
        if slice_usdt < 10:
            logger.error(f"P{purchase_n} aborted {symbol}: slice {slice_usdt:.2f} below min")
            return False

        account = await binance_request("GET", "/api/v5/account/balances")
        usdt_balance = 0.0
        for asset in account or []:
            if asset.get("ccy", "").upper() == quote_ccy:
                usdt_balance = float(asset.get("availBal", "0"))
                break

        total_cost = math.floor(min(slice_usdt, usdt_balance) * 100) / 100
        if total_cost < 10:
            logger.error(f"P{purchase_n} aborted {symbol}: wallet {usdt_balance:.2f} too small")
            return False

        order = await place_order(
            "buy", None, None, symbol,
            order_type="market",
            total_cost=total_cost,
            use_exact_cost=True
        )
        if not order:
            return False

        order_id = order.get("orderId") or order.get("ordId")
        filled_qty = await confirm_order_fill(order_id, symbol)
        if filled_qty <= 0:
            filled_qty = total_cost / current_price if current_price else 0.0
        if filled_qty <= 0:
            logger.error(f"P{purchase_n} no fill for {symbol}")
            return False

        old_entry = pre.get("entry_price") or current_price
        old_amount = pre.get("amount") or 0.0
        new_avg = ((old_entry * old_amount) + (current_price * filled_qty)) / (old_amount + filled_qty)

        # Inventory / PnL = average. Stops & targets = THIS buy price (more room).
        pre["entry_price"] = new_avg
        pre["amount"] = old_amount + filled_qty
        pre["main_scale_count"] = purchase_n
        pre[f"main_scale_p{purchase_n}_price"] = current_price

        indicators = await get_cached_indicators(symbol, current_price)
        
        atr = (indicators or {}).get("atr") or current_price * 0.01
        atr_percent = (atr / current_price * 100) if current_price else 0.0
        rsi = (indicators or {}).get("rsi") or 50.0
        momentum_factor = rsi / 100.0
        fib_extensions = (indicators or {}).get("fib_levels", {}) or {}

        targets = await calculate_targets(
            symbol, current_price, current_price, atr, atr_percent,
            fib_extensions, momentum_factor, is_rescue=False
        )
        if targets:
            pre["primary_target"] = targets["primary_target"]
            pre["secondary_target"] = targets["secondary_target"]
            pre["stop_loss"] = targets["stop_loss"]
            pre["trailing_distance"] = targets["trailing_distance"]
            pre["trailing_stop"] = targets["trailing_stop"]

        await save_state()

        ts = pre.get("trailing_stop", 0)
        msg = (
            f"MAIN SCALE P{purchase_n}/3 EXECUTED\n"
            f"{symbol}: +{filled_qty:.6f} @ {current_price:.8f} ({total_cost:.2f} {quote_ccy})\n"
            f"Old entry: {old_entry:.8f} → New avg: {new_avg:.8f}\n"
            f"New TS: {ts:.8f} | New SL: {pre.get('stop_loss', 0):.8f}\n"
            f"Avg entry: {new_avg:.8f} (PnL) | Stops from fill {current_price:.8f} | New TS {pre.get('trailing_stop', 0):.8f}\n"
            f"Slice: {slice_usdt:.2f} | Count: {purchase_n}/3\n"
            f"Rescue locked until P3 done"
        )
        logger.info(msg)
        await send_telegram_message(bot, msg)
        return True
    except Exception as e:
        logger.error(f"execute_main_scale_add P{purchase_n} {symbol}: {e}")
        return False
        
# Cancel existing orders for a symbol
async def cancel_orders(symbol, side=None):
    global binance_client
    if binance_client is None:
        await create_binance_client()
    
    try:
        orders_to_cancel = [o for o in open_orders if o["symbol"] == symbol and (side is None or o["side"] == side)]
        canceled_count = 0
        for order in orders_to_cancel[:]:
            api_symbol = order["symbol"]
            body = {"ordId": order["orderId"], "instId": api_symbol}
            result = await binance_request("POST", "/api/v5/trade/cancel-order", body=body)
            if result:
                open_orders.remove(order)
                logger.info(f"Cancelled {order['side']} order {order['orderId']} ({symbol})")
                bot = Bot(TELEGRAM_TOKEN)
                await send_telegram_message(bot, f"Cancelled {order['side']} order {order['orderId']} for {symbol} at ${order['price']:.6f}")
                canceled_count += 1
            else:
                logger.error(f"Failed to cancel order {order['orderId']} ({symbol})")
        return canceled_count
    except Exception as e:
        logger.error(f"Error cancelling orders for {symbol}: {str(e)}")
        return 0

# Get symbol info
async def get_symbol_info(symbol):
    data = await binance_request("GET", "/api/v5/public/instruments")
    api_symbol = symbol
    for s in data or []:
        if s["instId"] == api_symbol:
            return {
                "instId": s["instId"],
                "lotSize": s["lotSize"],
                "minSz": s["minSz"],
                "minNotional": s["minNotional"],
                "lotSz": s.get("lotSz", "0.000001")
            }
    logger.error(f"Symbol {symbol} not found")
    return None

# Reset state
async def reset_state(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global SYMBOL, LAST_SYMBOL, SYMBOL2, LAST_SYMBOL2, pre_orders
    try:
        if ACTIVE_SLOT.get() == "USDC":
            async with state_lock:
                SYMBOL2 = None
                LAST_SYMBOL2 = None
                for sym in list(pre_orders):
                    if quote_of(sym) == "USDC":
                        del pre_orders[sym]
                # Force clean file (do not rely only on _pre_keep)
                _atomic_write_json(STATE_FILE_USDC, {
                    "SYMBOL": None,
                    "LAST_SYMBOL": None,
                    "MAIN_ALLOCATED_USDT": MAIN_ALLOCATED_USDT.get("USDC"),
                    "pre_orders": {},
                })
                # Still save USDT lane normally so both files stay consistent
                _atomic_write_json(STATE_FILE, _lane_state_payload("USDT"))
            logger.info("USDC lane state reset (forced empty pre_orders)")
            await send_telegram_message(
                update.get_bot(),
                "USDC lane reset. Set a new pair with /pair2.",
            )
        else:
            async with state_lock:
                SYMBOL = None
                LAST_SYMBOL = None
                for sym in list(pre_orders):
                    if quote_of(sym) != "USDC":
                        del pre_orders[sym]
                _atomic_write_json(STATE_FILE, _lane_state_payload("USDT"))
                _atomic_write_json(STATE_FILE_USDC, _lane_state_payload("USDC"))
            logger.info("State reset")
            await send_telegram_message(
                update.get_bot(),
                "Bot state reset. Set new pair with /pair.",
            )
    except Exception as e:
        logger.error(f"Error resetting state: {str(e)}")
        await send_telegram_message(update.get_bot(), f"Error resetting state: {str(e)}")

# Magic Sell Button
async def magic_sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /magic_sell
    EMERGENCY: Sells ONLY the current SYMBOL (set with /pair) using market order.
    DOES NOT touch ISAAC DCA or any other coins in the wallet.
    """
    if str(update.message.chat_id) != TELEGRAM_USER_ID:
        return

    bot = update.get_bot()

    lane_symbol = active_symbol()
    if not lane_symbol:
        await send_telegram_message(bot, f"No trading pair set ({active_pair_cmd()}). Nothing to sell.")
        return

    base_asset = lane_symbol.split('/')[0].upper()

    # 1. Get real available balance for this specific asset
    account = await binance_request("GET", "/api/v5/account/balances")
    if not account:
        await send_telegram_message(bot, "Failed to fetch balances.")
        return

    quantity = 0.0
    for asset in account:
        if asset["ccy"].upper() == base_asset:
            quantity = float(asset.get("availBal", 0))
            break

    if quantity <= 0.00000001:
        await send_telegram_message(bot, f"No {base_asset} available to sell.")
        return

    current_price = await get_current_price(lane_symbol)
    if current_price is None or current_price <= 0:
        await send_telegram_message(bot, f"Cannot get price for {lane_symbol}.")
        return

    # 2. Market sell the entire available balance of THIS lane.
    # If the other lane holds the same coin, sell only this lane's tracked size.
    reserved_other = reserved_base_other_lane(lane_symbol)
    if reserved_other > 0:
        tracked = float(pre_orders.get(lane_symbol, {}).get("amount") or 0.0)
        quantity = min(quantity, tracked if tracked > 0 else max(0.0, quantity - reserved_other))
        if quantity <= 0.00000001:
            await send_telegram_message(bot, f"No {base_asset} tracked on {lane_symbol} (the other lane holds this coin).")
            return
    
    clean_symbol = lane_symbol.replace('/', '')

    # Use exchange LOT_SIZE (same approach as execute_sell / place_order)
    step_size = 0.00000001
    min_qty = 0.00000001
    try:
        symbols_data = await binance_request("GET", "/api/v5/public/instruments")
        if symbols_data:
            for info in symbols_data:
                if info.get("instId") == clean_symbol:
                    step_size = float(info.get("lotSize") or info.get("stepSize") or 0.00000001)
                    min_qty = float(info.get("minSz") or 0.00000001)
                    break
    except Exception as e:
        logger.warning(f"magic_sell: could not load LOT_SIZE for {clean_symbol}: {e}")

    quantity = round_to_step_size(quantity, step_size)
    # Slightly under available balance to avoid "insufficient balance" after fees/rounding
    if step_size > 0 and quantity >= step_size:
        quantity = max(0.0, quantity - step_size)
        quantity = round_to_step_size(quantity, step_size)

    if quantity < min_qty or quantity <= 0:
        await send_telegram_message(
            bot,
            f"Quantity too small after step-size adjust: {quantity} (min {min_qty}). Nothing sold.",
        )
        return

    # Format sz without scientific notation / excess trailing zeros
    try:
        precision = max(0, int(round(-math.log10(step_size)))) if step_size < 1 else 0
    except Exception:
        precision = 8
    sz_str = f"{quantity:.{precision}f}".rstrip("0").rstrip(".")
    if not sz_str or sz_str == "0":
        await send_telegram_message(bot, f"Quantity rounded to zero for {base_asset}. Nothing sold.")
        return

    body = {
        "instId": clean_symbol,
        "side": "sell",
        "ordType": "market",
        "sz": sz_str,
    }

    try:
        response = await binance_request("POST", "/api/v5/trade/order", body=body)
        order_id = response.get("ordId") if response else None

        if not order_id:
            error_msg = response.get("msg", "Unknown error")
            await send_telegram_message(bot, f"Sell failed: {error_msg}")
            return

        # Small delay + confirm fill
        await asyncio.sleep(1.2)
        filled_qty = await confirm_order_fill(order_id, clean_symbol)

        if filled_qty <= 0:
            await send_telegram_message(bot,
                f"Order placed (ID: {order_id}) but fill not confirmed yet.\nCheck Binance manually.")
            return

        sold_value = filled_qty * current_price

        # Clean up pattern state if it existed (safe even if manual buy)
        if lane_symbol in pre_orders:
            del pre_orders[lane_symbol]
            await save_state()

        message = (
            f" MAGIC SELL (EMERGENCY) EXECUTED\n"
            f"{base_asset}: {filled_qty:.6f} sold @ ~{current_price:.6f}\n"
            f"Recovered ≈ ${sold_value:.2f} {quote_of(lane_symbol)}\n"
            f"Order ID: {order_id}\n"
            f"ISAAC DCA was NOT affected."
        )

        await send_telegram_message(bot, message)
        logger.info(f"Magic sell: {filled_qty:.6f} {base_asset} ≈ ${sold_value:.2f}")

    except Exception as e:
        logger.error(f"Magic sell error for {lane_symbol}: {str(e)}")
        await send_telegram_message(bot, f"Error during magic sell: {str(e)}")     

# Set trading pair
async def pair_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if args:
        return await set_pair(update, context)
    example = "BTC/USDC" if ACTIVE_SLOT.get() == "USDC" else "BTC/USDT"
    await send_telegram_message(update.get_bot(), f"Enter trading pair (e.g., {example})")
    return PAIR

async def set_pair(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global SYMBOL, LAST_SYMBOL, SYMBOL2, LAST_SYMBOL2
    try:
        args = context.args or update.message.text.strip().split()
        logger.info(f"Pair input: text='{update.message.text}', args={args}")
        
        if args and (args[0].startswith('/pair')):
            args = args[1:]
        
        lane = "USDC" if ACTIVE_SLOT.get() == "USDC" else "USDT"
        example = "BTC/USDC" if lane == "USDC" else "BTC/USDT"
        if len(args) != 1:
            logger.warning(f"Invalid number of arguments: {args}")
            await send_telegram_message(update.get_bot(), f"Enter trading pair (e.g., {example})")
            return ConversationHandler.END
        
        pair_input = args[0].upper().replace("-", "/")
        if "/" not in pair_input or pair_input.split("/")[-1] != lane:
            if lane == "USDC":
                await send_telegram_message(update.get_bot(), f"/pair2 only accepts a USDC pair (e.g. {example}). USDT pairs use /pair.")
            else:
                await send_telegram_message(update.get_bot(), f"/pair only accepts a USDT pair (e.g. {example}). USDC pairs use /pair2.")
            return ConversationHandler.END

        # One open pair per lane. Refuse to orphan a live position.
        for sym in list(pre_orders):
            if quote_of(sym) != lane or sym == pair_input:
                continue
            pre = pre_orders[sym]
            if pre.get("order_type") == "buy" and float(pre.get("amount") or 0) > 0:
                cmd = "/magic_sell2" if lane == "USDC" else "/magic_sell"
                await send_telegram_message(
                    update.get_bot(),
                    f"{sym} is still open on this lane. Close it with {cmd} before switching pairs."
                )
                return ConversationHandler.END
            del pre_orders[sym]
        symbols_data = await binance_request("GET", "/api/v5/public/instruments")
        symbols = [s["instId"] for s in symbols_data or []] if symbols_data else []
        
        # Clean for validation (strip / to match API format e.g., "SOLUSDT")
        clean_pair = pair_input.replace('/', '')
        if clean_pair not in symbols:
            logger.warning(f"Invalid pair: {pair_input} (clean: {clean_pair} not in API symbols)")
            await send_telegram_message(update.get_bot(), f"Invalid pair: {pair_input}. Try {example}.")
            return ConversationHandler.END
        
        # Keep original with / for internal use. Lanes never overwrite each other.
        if lane == "USDC":
            SYMBOL2 = pair_input
            LAST_SYMBOL2 = pair_input
        else:
            SYMBOL = pair_input
            LAST_SYMBOL = pair_input
        message = f"{pair_input} pair added"
        logger.info(message)
        await send_telegram_message(update.get_bot(), message)
        await save_state()

        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error setting pair: {str(e)}")
        await send_telegram_message(update.get_bot(), f"Error setting pair: {str(e)}")
        return ConversationHandler.END

async def pair_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_telegram_message(update.get_bot(), "Pair setting cancelled")
    return ConversationHandler.END

# Buy price conversation (for pre-existing BTC)
async def buy_price_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) == 3:
        return await set_buy_price(update, context)
    example = "SOL/USDC 150 2" if ACTIVE_SLOT.get() == "USDC" else "BTC/USDT 80000 0.1"
    cmd = active_pair_cmd()
    await send_telegram_message(update.get_bot(), f"Enter pair, buy price, and amount: <pair> <buy_price> <amount> (e.g., {example}). This command only affects {cmd}.")
    return BUY_PRICE

# Buy price conversation (for pre-existing BTC)
async def set_buy_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global pre_orders
    try:
        if not await check_prerequisites(update, context, {
            "pair": "Set a trading pair with /pair first"
        }):
            return BUY_PRICE if not context.args else ConversationHandler.END

        args = context.args or update.message.text.strip().split()
        logger.info(f"Buy price input: text='{update.message.text}', args={args}")
        
        if args and args[0].startswith('/buy_price'):
            args = args[1:]
        
        if len(args) != 3:
            logger.warning(f"Invalid number of arguments: {args}")
            example = "SOL/USDC 150 2" if ACTIVE_SLOT.get() == "USDC" else "BTC/USDT 80000 0.1"
            await send_telegram_message(update.get_bot(), f"Use: <pair> <buy_price> <amount> (e.g., {example})")
            return BUY_PRICE if not context.args else ConversationHandler.END
        
        pair_input = args[0].upper()
        symbol = pair_input
        if quote_of(symbol) != active_quote():
            if active_quote() == "USDC":
                await send_telegram_message(update.get_bot(), f"/buy_price2 only accepts a USDC pair, got {symbol}.")
            else:
                await send_telegram_message(update.get_bot(), f"/buy_price only accepts a USDT pair, got {symbol}.")
            return BUY_PRICE if not context.args else ConversationHandler.END

        # === FIXED: Robust pair validation (already improved in previous version) ===
        symbols_data = await binance_request("GET", "/api/v5/public/instruments")
        symbols = [s["instId"] for s in symbols_data or []] if symbols_data else []

        clean_symbol = symbol.replace("/", "")
        is_valid_pair = False

        for s in symbols:
            if s == symbol or s == clean_symbol or s.replace("/", "") == clean_symbol:
                is_valid_pair = True
                # Normalize to consistent format with slash
                if '/' not in symbol and len(clean_symbol) > 3:
                    symbol = f"{clean_symbol[:len(clean_symbol)//2]}/{clean_symbol[len(clean_symbol)//2:]}"
                break

        if not is_valid_pair:
            if symbol in pre_orders or (SYMBOL and symbol.upper() == SYMBOL.upper()) or clean_symbol in [k.replace("/", "") for k in pre_orders.keys()]:
                is_valid_pair = True

        if not is_valid_pair:
            logger.warning(f"Invalid pair: {pair_input}")
            await send_telegram_message(update.get_bot(), f"Invalid pair: {pair_input}")
            return BUY_PRICE if not context.args else ConversationHandler.END
        # === END OF VALIDATION ===

        try:
            buy_price = float(args[1])
            amount = float(args[2])
            if buy_price <= 0 or amount <= 0:
                logger.warning(f"Invalid inputs: buy_price={buy_price}, amount={amount}")
                await send_telegram_message(update.get_bot(), "Buy price and amount must be positive")
                return BUY_PRICE if not context.args else ConversationHandler.END
        except ValueError:
            logger.warning(f"Invalid numeric arguments: {args[1:]}")
            await send_telegram_message(update.get_bot(), "Buy price and amount must be numbers")
            return BUY_PRICE if not context.args else ConversationHandler.END
        
        account = await binance_request("GET", "/api/v5/account/balances")
        base_balance = 0.0
        base_asset = symbol.split('/')[0].upper()
        for asset in account or []:
            if asset["ccy"].upper() == base_asset.upper():
                base_balance = float(asset.get("availBal", "0"))
        
        # === FIXED: Safe handling of get_symbol_info (this was causing the NoneType error) ===
        symbol_info = await get_symbol_info(symbol)
        if symbol_info is None:
            logger.warning(f"get_symbol_info returned None for {symbol}. Using safe defaults.")
            min_qty = 0.00000001   # very small safe default
        else:
            min_qty = float(symbol_info.get("minSz", "0.00000001"))
        
        if amount < min_qty:
            logger.warning(f"Amount {amount:.8f} below minimum {min_qty:.8f} for {symbol}")
            await send_telegram_message(update.get_bot(), f"Amount {amount:.8f} below minimum {min_qty:.8f} for {symbol}")
            return BUY_PRICE if not context.args else ConversationHandler.END
        if amount > base_balance:
            logger.warning(f"Insufficient {base_asset} balance: {base_balance:.8f} < {amount:.8f}")
            await send_telegram_message(update.get_bot(), f"Insufficient {base_asset} balance: {base_balance:.8f} < {amount:.8f}")
            return BUY_PRICE if not context.args else ConversationHandler.END
        
        # Fetch indicators for calculate_targets
        ohlcv = await fetch_ohlcv(symbol, timeframe='1h', limit=100)
        if ohlcv is None or len(ohlcv) < 26:  # Ensure enough data for MACD
            logger.error(f"Skipping {symbol}: No or insufficient OHLCV data")
            await send_telegram_message(update.get_bot(), f"Failed to fetch OHLCV data for {symbol}, using static targets")
            # Fallback to static targets
            pre_orders[symbol] = {
                "order_type": "buy",
                "buy_target": None,
                "entry_price": buy_price,
                "primary_target": buy_price * 1.03,
                "secondary_target": buy_price * 1.015,
                "stop_loss": buy_price * 0.98,
                "trailing_distance": buy_price * 0.02,
                "trailing_stop": buy_price * 0.98,
                "amount": amount,
                "current_order_type": None,
                "order_count": 0,
                "last_price": await get_current_price(symbol),
                "last_base_balance": base_balance,
                "last_base_locked": 0.0
            }
            await save_state()
            message = (f"Position initialized for {symbol}: {amount:.8f} {base_asset} at entry price ${buy_price:.6f}\n"
                       f"Primary ${pre_orders[symbol]['primary_target']:.6f}, Secondary ${pre_orders[symbol]['secondary_target']:.6f}, "
                       f"Stop-Loss ${pre_orders[symbol]['stop_loss']:.6f}, Trailing Stop ${pre_orders[symbol]['trailing_stop']:.6f}")
            logger.info(message)
            await send_telegram_message(update.get_bot(), message)
            return ConversationHandler.END

        closes = ohlcv[:, 3]
        atr = calculate_atr(ohlcv, 14)
        rsi = calculate_rsi(closes, 14)
        current_price = await get_current_price(symbol)
        atr_percent = (atr / current_price * 100) if atr and current_price else 0.0
        momentum_factor = rsi / 100 if rsi else 0.0
        fib_extensions = {}

        targets = await calculate_targets(symbol, buy_price, current_price, atr, atr_percent, fib_extensions, momentum_factor)
        
        if (targets["primary_target"] <= 0 or
            targets["secondary_target"] <= 0 or
            targets["primary_target"] < targets["secondary_target"]):
            logger.error(f"Invalid targets for {symbol}: primary={targets['primary_target']}, "
                         f"secondary={targets['secondary_target']}")
            await send_telegram_message(update.get_bot(), f"Invalid target calculations for {symbol}, using static targets")
            targets = {
                "primary_target": buy_price * 1.03,
                "secondary_target": buy_price * 1.015,
                "stop_loss": buy_price * 0.98,
                "trailing_stop": buy_price * 0.98,
                "trailing_distance": buy_price * 0.02
            }

        pre_orders[symbol] = {
            "order_type": "buy",
            "living": True,
            "buy_target": None,
            "entry_price": buy_price,
            "primary_target": targets["primary_target"],
            "secondary_target": targets["secondary_target"],
            "stop_loss": targets["stop_loss"],
            "trailing_distance": targets["trailing_distance"],
            "trailing_stop": targets["trailing_stop"],
            "amount": amount,
            "current_order_type": None,
            "order_count": 0,
            "last_price": current_price,
            "last_base_balance": base_balance,
            "last_base_locked": 0.0
        }

        await save_state()
        message = (f"Position initialized for {symbol}: {amount:.8f} {base_asset} at entry price ${buy_price:.6f}\n"
                   f"Primary ${pre_orders[symbol]['primary_target']:.6f}, Secondary ${pre_orders[symbol]['secondary_target']:.6f}, "
                   f"Stop-Loss ${pre_orders[symbol]['stop_loss']:.6f}, Trailing Stop ${pre_orders[symbol]['trailing_stop']:.6f}")
        logger.info(message)
        await send_telegram_message(update.get_bot(), message)
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error setting buy price: {str(e)}")
        await send_telegram_message(update.get_bot(), f"Error setting buy price: {str(e)}")
        return BUY_PRICE if not context.args else ConversationHandler.END

# Manual Direct Buy    
async def mb_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.chat_id) != TELEGRAM_USER_ID:
        return ConversationHandler.END
    if not active_symbol():
        await send_telegram_message(update.get_bot(), f"No trading pair set. Use {active_pair_cmd()} first.")
        return ConversationHandler.END
    args = context.args or []
    if args:
        return await mb_execute_amount(update, context, args[0])
    await send_telegram_message(
        update.get_bot(),
        f"Manual buy on {active_symbol()}\nSend the {active_quote()} amount (e.g. 1500)\n/cancel to abort"
    )
    return MB_AMOUNT


async def mb_amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.chat_id) != TELEGRAM_USER_ID:
        return ConversationHandler.END
    return await mb_execute_amount(update, context, (update.message.text or "").strip())


async def mb_execute_amount(update: Update, context: ContextTypes.DEFAULT_TYPE, amount_text):
    bot = update.get_bot()
    try:
        requested = float(str(amount_text).replace(",", "").strip())
    except (TypeError, ValueError):
        await send_telegram_message(bot, "Invalid amount. Send a number (e.g. 1500).")
        return MB_AMOUNT

    if requested <= 0:
        await send_telegram_message(bot, "Amount must be > 0.")
        return MB_AMOUNT

    lane_symbol = active_symbol()
    quote_ccy = active_quote()
    if not lane_symbol:
        await send_telegram_message(bot, f"No trading pair set. Use {active_pair_cmd()} first.")
        return ConversationHandler.END

    current_price = await get_current_price(lane_symbol)
    if current_price is None or current_price <= 0:
        await send_telegram_message(bot, f"Cannot get current price for {lane_symbol}.")
        return ConversationHandler.END

    account = await binance_request("GET", "/api/v5/account/balances")
    usdt_balance = 0.0
    for asset in account or []:
        if asset.get("ccy", "").upper() == quote_ccy:
            usdt_balance = float(asset.get("availBal", "0"))
            break

    usdt_to_use = math.floor(min(requested, usdt_balance) * 100) / 100
    if usdt_to_use < 10:
        await send_telegram_message(
            bot,
            f"Insufficient {quote_ccy}: requested ${requested:.2f} | wallet ${usdt_balance:.2f} | using ${usdt_to_use:.2f}"
        )
        return ConversationHandler.END

    order = await place_order(
        "buy", None, None, lane_symbol,
        order_type="market",
        total_cost=usdt_to_use,
        use_exact_cost=True
    )
    if not order:
        await send_telegram_message(bot, "Buy order failed.")
        return ConversationHandler.END

    order_id = order.get("orderId") or order.get("ordId")
    await asyncio.sleep(1.2)
    filled_qty = await confirm_order_fill(order_id, lane_symbol.replace("/", ""))
    base_asset = lane_symbol.split("/")[0].upper()
    spent = filled_qty * current_price if filled_qty > 0 else usdt_to_use

    await send_telegram_message(
        bot,
        f"**MANUAL MARKET BUY EXECUTED**\n"
        f"{base_asset}: {filled_qty:.6f} @ ~{current_price:.8f}\n"
        f"Requested: ${requested:.2f} {quote_ccy} | Used: ${usdt_to_use:.2f} | Wallet: ${usdt_balance:.2f}\n"
        f"Order ID: {order_id}\n"
        f"(No pattern targets or trailing stop set — manual buy)"
    )
    logger.info(f"Manual buy {filled_qty:.6f} {base_asset} requested={requested:.2f} used={usdt_to_use:.2f} id={order_id}")
    return ConversationHandler.END    

# Check balance
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        shown = active_last_symbol()
        if not shown:
            await send_telegram_message(update.get_bot(), f"No pair set. Use {active_pair_cmd()}")
            return
        base_asset = shown.split('/')[0].upper()
        quote_asset = quote_of(shown)
        account = await binance_request("GET", "/api/v5/account/balances")
        base_balance = base_locked = quote_balance = quote_locked = 0.0
        for asset in account or []:
            if asset["ccy"].upper() == base_asset.upper():
                base_balance = float(asset.get("availBal", "0"))
                base_locked = float(asset.get("frozenBal", "0"))
            if asset["ccy"].upper() == quote_asset.upper():
                quote_balance = float(asset.get("availBal", "0"))
                quote_locked = float(asset.get("frozenBal", "0"))
        message = (f"Spot Wallet: {base_balance:.8f} {base_asset} (free), {base_locked:.8f} {base_asset} (locked), "
                   f"{quote_balance:.2f} {quote_asset} (free), {quote_locked:.2f} {quote_asset} (locked)")
        await send_telegram_message(update.get_bot(), message)
    except Exception as e:
        logger.error(f"Error fetching balance: {str(e)}")
        await send_telegram_message(update.get_bot(), f"Error fetching balance: {str(e)}")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not await check_prerequisites(update, context, {
            "pair": "Set a trading pair with /pair first"
        }):
            return ConversationHandler.END

        await sync_open_orders()

        # Initialize message parts
        messages = []

        # Clean pre_orders keys, then keep ONLY this lane so /status and /status2 never mix.
        lane_quote = active_quote()
        clean_pre_orders = {}
        for sym, pre in pre_orders.items():
            if quote_of(sym) != lane_quote:
                continue
            clean_sym = sym
            if clean_sym in clean_pre_orders:
                clean_pre_orders[clean_sym].update(pre)  # Merge/overwrite with latest
            else:
                clean_pre_orders[clean_sym] = pre
        pre_orders_temp = clean_pre_orders  # Use clean for this status

        lane_symbol = active_last_symbol()
        symbols = [lane_symbol] if lane_symbol else list(pre_orders_temp.keys())
        if not symbols:
            await send_telegram_message(update.get_bot(), f"No trading pairs set. Use {active_pair_cmd()} to set a pair.")
            return ConversationHandler.END

        for symbol in symbols:
            if symbol not in pre_orders_temp and symbol != lane_symbol:
                continue  # Skip invalid symbols

            base_asset = symbol.split('/')[0] if '/' in symbol else symbol[:-4]  # Binance clean: split or slice
            quote_asset = quote_of(symbol)
            base_balance = base_locked = quote_balance = quote_locked = 0.0
            current_price = "N/A"

            # Fetch account balances
            account = await binance_request("GET", "/api/v5/account/balances")
            if not account:
                await send_telegram_message(update.get_bot(), f"Error fetching status for {symbol}: No account data")
                continue
            for asset in account:
                if asset["ccy"].upper() == base_asset.upper():
                    base_balance = float(asset.get("availBal", "0"))
                    base_locked = float(asset.get("frozenBal", "0"))
                if asset["ccy"].upper() == quote_asset.upper():
                    quote_balance = float(asset.get("availBal", "0"))
                    quote_locked = float(asset.get("frozenBal", "0"))

            # Fetch current price
            price = await get_current_price(symbol)
            current_price = price if price and isinstance(price, float) else "N/A"

            # Calculate profit
            pre = pre_orders_temp.get(symbol, {})
            order_quantity = pre.get("amount", 0.0)
            if pre.get("entry_price") is not None and isinstance(current_price, float):
                profit_percent = ((current_price - pre["entry_price"]) / pre["entry_price"]) * 100
                profit_usd = (current_price - pre["entry_price"]) * order_quantity
                profit_str = f"Profit: {profit_percent:.2f}% (${profit_usd:.2f})"
            else:
                profit_str = "Profit: N/A"

            # Fetch indicators using cached function
            indicators = await get_cached_indicators(symbol, current_price)
            
           
                
            if indicators is None:
                logger.error(f"Failed to fetch indicators for {symbol}")
                indicators_str = "N/A"
                btc_ig = pre_orders_temp.get(symbol, {}).get("btc_ig", "N/A")
                csi = pre_orders_temp.get(symbol, {}).get("csi", None)
            else:
                ema_9 = indicators["ema_9"]
                ema_21 = indicators["ema_21"]
                ema_5 = indicators["ema_5"]
                ema_13 = indicators["ema_13"]
                ema_50 = indicators["ema_50"]
                rsi = indicators["rsi"]
                atr = indicators["atr"]
                fib_levels = indicators["fib_levels"]
                btc_ig = pre_orders.get(symbol, {}).get("btc_ig", "N/A")
                csi = pre_orders.get(symbol, {}).get("csi", "N/A")
                macd_line = indicators["macd_line"]
                signal_line = indicators["signal_line"]
                middle_band = indicators["middle_band"]
                volumes_list = indicators.get('volumes')
                volume = volumes_list[-1] if volumes_list is not None and len(volumes_list) > 0 else 0
                if (volume is None) or (volume <= 0):
                    _nz = [float(v) for v in (list(volumes_list[:-1]) if volumes_list is not None and len(volumes_list) > 1 else []) if float(v) > 0]
                    volume = _nz[-1] if _nz else 0.0
                support_fallback = indicators["support"]
                rsi_prev = indicators['rsi_values'][-2] if indicators['rsi_values'] and len(indicators['rsi_values']) >= 2 else None
                rsi_low = min(indicators['rsi_values'][-5:]) if indicators['rsi_values'] and len(indicators['rsi_values']) >= 5 else None
                price_low = min(indicators['closes'][-5:]) if len(indicators['closes']) >= 5 else None
                histogram = indicators["histogram"]
                prev_atr = indicators["prev_atr"]
                volatility_index = indicators["volatility_index"]
                cvd = indicators.get('cvd', 0.0)
                cvd_signal = indicators.get('cvd_signal', 'neutral')
                prev_close = indicators["closes"][-2] if len(indicators.get("closes", [])) >= 2 else indicators.get("closes", [])[-1] if indicators.get("closes") else None
                prev_histogram = indicators.get('histogram', 0) - 0.1 if indicators.get('histogram') is not None else None  # Delta fallback
                recent_high = indicators.get('high', None)  # Recent high
                avg_volume = np.mean(indicators.get('volumes', [0])[-10:]) if len(indicators.get('volumes', [])) >= 10 else indicators.get('volumes', [0])[-1] if indicators.get('volumes') else 0
                bb_width = indicators.get('bb_width', 0.02)
                prev_cvd = indicators.get('cvd_values', [cvd])[-2] if len(indicators.get('cvd_values', [cvd])) >= 2 else cvd * 0.9  # Safe fallback for change_pct
                obi = indicators.get('obi', 0.0)
                prev_obi = indicators.get('obi_values', [obi])[-2] if len(indicators.get('obi_values', [obi])) >= 2 else obi
                obi_signal = indicators.get('obi_signal', 'neutral')
                obi_values = indicators.get('obi_values', [indicators.get('obi', 0.0)])
                

                # Indicator statuses and formatted strings
                ema_status = "Bullish" if ema_9 > ema_21 else "Bearish" if ema_9 < ema_21 else "Neutral"
                emaS_status = "BullishShort" if ema_5 > ema_13 else "BearishShort" if ema_5 < ema_13 else "NeutralShort"
                ema50_status = "Bullish" if ema_50 is not None and current_price > ema_50 else "Bearish" if ema_50 is not None and current_price < ema_50 else "Neutral"
                ema_9_str = f"{ema_9:.6f}" if ema_9 is not None else "N/A"
                ema_21_str = f"{ema_21:.6f}" if ema_21 is not None else "N/A"
                ema_5_str = f"{ema_5:.6f}" if ema_5 is not None else "N/A"
                ema_13_str = f"{ema_13:.6f}" if ema_13 is not None else "N/A"
                ema_50_str = f"{ema_50:.6f}" if ema_50 is not None else "N/A"
                rsi_str = f"{rsi:.2f}" if rsi is not None else "N/A"
                csi_str = f"{csi:.2f}" if csi is not None else "N/A"
                atr_str = f"{atr:.8f}" if atr is not None else "N/A"
                atr_percent = (atr / current_price) * 100 if atr is not None and isinstance(current_price, float) and current_price > 0 else None
                prev_atr_percent = (prev_atr / current_price) * 100 if prev_atr is not None and isinstance(current_price, float) and current_price > 0 else None
                atr_percent_str = f"{atr_percent:.2f}" if atr_percent is not None else "N/A"
                prev_atr_percent_str = f"{prev_atr_percent:.2f}" if prev_atr_percent is not None else "N/A"
                fib_61_8_str = f"{fib_levels.get('61.8%'):.8f}" if fib_levels and fib_levels.get("61.8%") else "N/A"
                vwap_str = f"{indicators['vwap']:.8f}" if indicators["vwap"] is not None else "N/A"
                volume_spike_str = "Yes" if indicators["volume_spike"] else "No"
                volume_str = f"{volume:.0f}" if volume is not None else "N/A"
                macd_line_str = f"{macd_line:.6f}" if macd_line is not None else "N/A"
                signal_line_str = f"{signal_line:.6f}" if signal_line is not None else "N/A"
                middle_band_str = f"{middle_band:.6f}" if middle_band is not None else "N/A"
                support_fallback_str = f"{support_fallback:.8f}" if support_fallback is not None else "N/A"
                rsi_prev_str = f"{rsi_prev:.2f}" if rsi_prev is not None else "N/A"
                rsi_low_str = f"{rsi_low:.2f}" if rsi_low is not None else "N/A"
                price_low_str = f"{price_low:.6f}" if price_low is not None else "N/A"
                histogram_str = f"{histogram:.6f}" if histogram is not None else "N/A"
                prev_atr_str = f"{prev_atr:.6f}" if prev_atr is not None else "N/A"
                volatility_index_str = f"{volatility_index:.2f}" if volatility_index is not None else "N/A"
                cvd_str = f"{cvd:.2f}" if cvd != 0 else "N/A"
                cvd_signal_str = cvd_signal   
                prev_close_str = f"{prev_close:.6f}" if prev_close is not None else "N/A"
                prev_histogram_str = f"{prev_histogram:.6f}" if prev_histogram is not None else "N/A"
                recent_high_str = f"{recent_high:.6f}" if recent_high is not None else "N/A"
                avg_volume_str = f"{avg_volume:.0f}" if avg_volume is not None else "N/A"
                bb_width_str = f"{bb_width:.4f}" if bb_width is not None else "N/A"
                prev_cvd_str = f"{prev_cvd:.2f}" if prev_cvd is not None else "N/A"
                obi_str = f"{obi:.2f}" if obi != 0 else "N/A"
                obi_signal_str = obi_signal
                prev_obi_str = f"{prev_obi:.2f}" if prev_obi is not None else "N/A"
                
                indicators_str = (
                    f"EMA9-21: {ema_status} ({ema_9_str}/{ema_21_str})\n"
                    f"EMA5-13: {emaS_status} ({ema_5_str}/{ema_13_str})\n"
                    f"EMA50: {ema50_status} ({ema_50_str})\n" 
                    f"RSI: {rsi_str}\n"
                    f"RSI Prev: {rsi_prev_str}\n"
                    f"RSI Low: {rsi_low_str}\n"
                    f"Price Low: {price_low_str}\n"
                    f"CSI: {csi_str}\n"
                    f"BTC_IG: {btc_ig}\n"
                    f"ATR%: {atr_percent_str}\n"
                    f"Prev ATR%: {prev_atr_percent_str}\n"
                    f"ATR: {atr_str}\n"
                    f"Prev ATR: {prev_atr_str}\n"
                    f"Volatility Index: {volatility_index_str}\n"
                    f"Fib 61.8%: {fib_61_8_str}\n"
                    f"VWAP: {vwap_str}\n"
                    f"Volume Spike: {volume_spike_str}\n"
                    f"Volume: {volume_str}\n"
                    f"Avg Volume: {avg_volume_str}\n"
                    f"MACD Line: {macd_line_str}\n"
                    f"Signal Line: {signal_line_str}\n"
                    f"Histogram: {histogram_str}\n"
                    f"Prev Histogram: {prev_histogram_str}\n"
                    f"Middle Band: {middle_band_str}\n"
                    f"BB Width: {bb_width_str}\n"
                    f"Support: {support_fallback_str}\n"
                    f"Prev Close: {prev_close_str}\n"
                    f"Recent High: {recent_high_str}\n"
                    f"CVD: {cvd_str} ({cvd_signal_str})\n"
                    f"Prev CVD: {prev_cvd_str}\n"    
                    f"OBI: {obi_str} ({obi_signal_str})\n"
                    f"Prev_OBI: {prev_obi_str}\n"
                    
                    
                )

                # ============================================================
                # UPDATED TIERS LOGIC - EXACT MATCH TO evaluate_pattern_matches
                # (Ultimate Top Detector + ATR Beast vNEXT + Full Confluence Engine)
                # ============================================================
                if not isinstance(current_price, float) or current_price <= 0:
                    current_price = 0.0
                if atr is None: atr = current_price * 0.01
                if prev_atr is None: prev_atr = atr * 0.9
                if volume is None: volume = 0.0
                if avg_volume is None: avg_volume = volume
                if support_fallback is None: support_fallback = current_price * 0.98
                if prev_close is None: prev_close = current_price * 0.99
                if prev_histogram is None: prev_histogram = (histogram or 0) * 0.9
                if prev_cvd is None: prev_cvd = (cvd or 0) * 0.9
                if ema_5 is None: ema_5 = current_price
                if ema_13 is None: ema_13 = current_price
                if ema_50 is None: ema_50 = current_price
                if signal_line is None: signal_line = 0
                if histogram is None: histogram = 0
                if rsi_prev is None: rsi_prev = rsi - 1 if rsi else 50
                if obi is None: obi = 0.0
                atr_percent = (atr / current_price * 100) if current_price > 0 else 0.0
                cvd_change_pct = ((cvd - prev_cvd) / abs(prev_cvd + 1e-6)) * 100 if prev_cvd != 0 else 0.0
                obi_imbalance = obi - (obi * 0.9)
                trend_strength_proxy = abs((ema_9 - ema_21) / max(abs(ema_21 or 1), 1e-9)) * 100
                pressure_strength_proxy = (abs(cvd_change_pct) + abs(obi_imbalance) * 100) / 2
                cvd_divergence = (cvd > prev_cvd) and (current_price < prev_close)
                obi_recovery = ((obi * 0.9) < 0 and obi > 0)
                rsi_divergence = (rsi > rsi_prev) and (current_price < prev_close) if rsi_prev is not None else False
                macd_divergence = (macd_line > (macd_line * 0.9)) and (current_price < prev_close) if macd_line else False
                prev_macd = macd_line * 0.9 if macd_line else 0
                prev_obi = obi * 0.9 if obi else 0
                bb_width_proxy = bb_width

                # === ULTIMATE TOP DETECTOR - EXACT MATCH TO evaluate_pattern_matches ===
                top_risk_score = 0.0
                top_detector_level = "LOW"
                hard_no_buy = False

                # Robust variable preparation
                recent_high_5 = recent_high if isinstance(recent_high, (int, float)) else current_price
                recent_high_10 = recent_high_5

                price_extension_pct = ((current_price - ema_21) / ema_21 * 100) if ema_21 and ema_21 > 0 else 0
                _top_band = max(float(atr or 0.0) * 1.0, current_price * 0.0004) if current_price else current_price * 0.0004
                near_recent_top = current_price >= (recent_high_5 - _top_band)

                current_volume = volume if isinstance(volume, (int, float)) else 0.0
                
                volumes = indicators.get('volumes', [])
                prev_volume = volumes[-2] if len(volumes) >= 2 else current_volume * 0.95

                # === Scoring (Exact same as evaluate_pattern_matches) ===
                if near_recent_top:
                    top_risk_score += 8
                if current_price >= recent_high_10 - max(float(atr or 0.0) * 1.0, current_price * 0.0004):
                    top_risk_score += 5
                if price_extension_pct > 1.2:
                    top_risk_score += 6
                if price_extension_pct > 2.2:
                    top_risk_score += 5

                if rsi and rsi > 72: top_risk_score += 8
                if rsi and rsi > 76: top_risk_score += 5
                if rsi and rsi_prev and rsi < rsi_prev and rsi > 70: top_risk_score += 5

                if near_recent_top and current_volume < avg_volume * 0.85: top_risk_score += 6
                if current_volume < prev_volume * 0.80 and current_price >= prev_close: top_risk_score += 3

                if obi < -0.12: top_risk_score += 4
                if obi < prev_obi and current_price >= prev_close: top_risk_score += 3
                if cvd < prev_cvd and current_price >= prev_close: top_risk_score += 4
                if cvd_change_pct < -5: top_risk_score += 4

                if histogram and prev_histogram and histogram < prev_histogram and histogram > 0: top_risk_score += 5
                if macd_line and signal_line and macd_line < signal_line and macd_line > 0: top_risk_score += 4

                if atr_percent < 0.08 and near_recent_top: top_risk_score += 3
                if bb_width_proxy < 0.0020 and near_recent_top: top_risk_score += 3

                if current_price < prev_close and near_recent_top: top_risk_score += 10

                # Final
                top_risk_score = max(0.0, min(100.0, top_risk_score))

                if top_risk_score >= 90:
                    top_detector_level = "EXTREME"
                elif top_risk_score >= 70:
                    top_detector_level = "HIGH"
                elif top_risk_score >= 50:
                    top_detector_level = "MEDIUM"
                else:
                    top_detector_level = "LOW"

                if (rsi and rsi > 82 and near_recent_top and current_volume < avg_volume * 0.50):
                    hard_no_buy = True
                if (near_recent_top and obi < -0.25 and cvd < prev_cvd):
                    hard_no_buy = True
                if (price_extension_pct > 6.0 and rsi and rsi > 82):
                    hard_no_buy = True
                    
                # === ATR BEAST vNEXT (Regime + Smart Threshold + Confluence) ===
                atr_threshold = 0.08
                volume_soft_mult = 0.25
                basic_bypass_min = 4
                obi_relax = -0.12
                if atr_percent > 0.80:
                    atr_threshold = 0.45
                elif atr_percent < 0.12:
                    atr_threshold = max(0.015, atr_percent * 0.55)
                else:
                    atr_threshold = max(0.025, atr_percent * 0.40)
                regime = "neutral"
                try:
                    full_ema_stack = (ema_5 > ema_9 > ema_13 > ema_21 and ema_21 > ema_50 * 0.995)
                except:
                    full_ema_stack = False
                if full_ema_stack and rsi > 52 and macd_line >= signal_line:
                    regime = "trend_bull"
                elif current_price < ema_21 and rsi < 42 and macd_line < signal_line:
                    regime = "trend_bear"
                elif bb_width_proxy < 0.0025 and atr_percent < 0.08:
                    regime = "compression"
                elif rsi < 42 and histogram > prev_histogram:
                    regime = "reversal_up"
                elif rsi > 72 and histogram < prev_histogram:
                    regime = "reversal_down"
                if regime == "trend_bull":
                    atr_threshold *= 0.72
                elif regime == "trend_bear":
                    atr_threshold *= 0.95
                elif regime == "compression":
                    atr_threshold *= 1.12
                elif regime == "reversal_up":
                    atr_threshold *= 0.82
                if trend_strength_proxy > 0.35:
                    atr_threshold *= 0.92
                if pressure_strength_proxy > 4:
                    atr_threshold *= 0.90
                high_vol = volume > avg_volume * 1.30
                if high_vol:
                    atr_threshold *= 0.75
                atr_threshold = max(0.015, min(0.80, atr_threshold))

                # Confluence Engine
                confluence = 0
                atr_bypass_tier = 0
                fast_reversal_core = (
                    (obi > 0.10 and obi_recovery) and
                    (cvd_change_pct > 5) and
                    (rsi > 50 or rsi_divergence)
                )
                fast_reversal_boosters = 0
                if fast_reversal_core:
                    if ema_5 > ema_9: fast_reversal_boosters += 1
                    if histogram > prev_histogram * 1.10: fast_reversal_boosters += 1
                basic_bypass_conditions = {
                    'ema_alignment': ema_9 > ema_21 > ema_50 * 0.99 if ema_50 else False,
                    'macd_above_signal': (macd_line > signal_line * 0.98) or (histogram > prev_histogram * 0.90),
                    'histogram_rising': histogram > prev_histogram * 0.90 if histogram is not None else False,
                    'rsi_neutral': 45 < rsi < 75,
                    'price_above_support': current_price > support_fallback * 1.001 if support_fallback else False,
                    'volume_sufficient': (volume if volume else current_volume) > avg_volume * volume_soft_mult,
                    'csi_positive': csi > 0.0 if csi is not None else False,
                    'fast_reversal_core': fast_reversal_core,
                }
                basic_bypass_met_count = sum(basic_bypass_conditions.values())
                tier1_activated = False
                tier1_reason_display = "Skipped"
                if (fast_reversal_core and
                    basic_bypass_conditions['ema_alignment'] and
                    basic_bypass_conditions['histogram_rising'] and
                    basic_bypass_conditions['volume_sufficient']):
                    tier1_activated = True
                    tier1_reason_display = "GOD-TIER FAST REVERSAL"
                elif (basic_bypass_conditions['fast_reversal_core'] and
                      basic_bypass_conditions['ema_alignment'] and
                      basic_bypass_met_count >= 5):
                    tier1_activated = True
                    tier1_reason_display = "STRONG FAST CORE + EMA"
                elif (basic_bypass_conditions['ema_alignment'] and
                      basic_bypass_conditions['macd_above_signal'] and
                      basic_bypass_conditions['histogram_rising'] and
                      basic_bypass_conditions['volume_sufficient'] and
                      basic_bypass_conditions['rsi_neutral'] and
                      basic_bypass_met_count >= 6):
                    tier1_activated = True
                    tier1_reason_display = "CLASSIC CLEAN STACK"
                elif basic_bypass_met_count >= basic_bypass_min:
                    tier1_activated = True
                    tier1_reason_display = f"MAJORITY ({basic_bypass_met_count}/10)"
                if tier1_activated:
                    confluence += 30
                    if cvd_divergence or obi_recovery:
                        confluence += 15
                    if fast_reversal_core and fast_reversal_boosters >= 2:
                        confluence += 25
                    atr_bypass_tier = max(atr_bypass_tier, 1)
                tier1_status = f"MET ({tier1_reason_display}) +30" if tier1_activated else "Skipped"
                tier2_met = tier1_activated and (trend_strength_proxy > 0.08 or (rsi_divergence or macd_divergence))
                if tier2_met:
                    atr_bypass_tier = max(atr_bypass_tier, 2)
                    confluence += 40
                tier2_status = "MET (+40)" if tier2_met else "Skipped"

                pressure_surge = tier1_activated and cvd_change_pct > 10 and obi_imbalance > 0.05 and high_vol
                flip_detected = (btc_ig == 'bullish' and pre.get('last_btc_ig', 'neutral') in ['bearish', 'neutral'])

                tier3_met = tier1_activated and pressure_surge
                if tier3_met:
                    atr_bypass_tier = max(atr_bypass_tier, 3)
                    confluence += 20
                tier3_status = "MET (+20)" if tier3_met else "Skipped"

                tier4_met = tier1_activated and flip_detected and (csi > 0.50 if csi is not None else False) and obi_recovery
                if tier4_met:
                    atr_bypass_tier = max(atr_bypass_tier, 4)
                    confluence += 30
                tier4_status = "MET (+30)" if tier4_met else "Skipped"

                if atr_bypass_tier > 0:
                    relaxation = 0.70 - (atr_bypass_tier * 0.08)
                    atr_threshold = max(0.015, atr_threshold * max(0.55, relaxation))

                cond_statuses = []
                for name, met in basic_bypass_conditions.items():
                    emoji = "✅" if met else "❌"
                    cond_statuses.append(f"{emoji} {name.replace('_', ' ').title()}")

                tiers_str = (
                    f"Regime: {regime.upper()}\n"
                    f"Top Risk: {top_risk_score:.0f}% ({top_detector_level}) | Hard No-Buy: {'YES' if hard_no_buy else 'NO'}\n"
                    f"Tier Analysis [{basic_bypass_met_count}/8 conditions]\n"
                    f"{chr(10).join(cond_statuses)}\n\n"
                    f"Tier1: {tier1_status}\n"
                    f"Tier2 (Trend): {tier2_status}\n"
                    f"Tier3 (Pressure): {tier3_status}\n"
                    f"Tier4 (Sentiment): {tier4_status}\n"
                    f"ATR Bypass Tier: {atr_bypass_tier} | Threshold: {atr_threshold:.2f}%\n"
                    f"Confluence: {confluence}"
                )

            # Build open orders string
            seen_order_ids = set()
            unique_orders = []
            for order in open_orders:
                if order["orderId"] not in seen_order_ids and order["symbol"] == symbol:
                    unique_orders.append(order)
                    seen_order_ids.add(order["orderId"])
            
            orders_str = "None"
            if unique_orders:
                orders = [
                    f"{order['side']} Order ID: {order['orderId']} "
                    f"({order['symbol']}, {order['quantity']:.8f} at ${order['price']:.2f})"
                    for order in unique_orders
                ]
                orders_str = "\n".join(orders)

            # Build pre-orders string
            order_str = []
            primary_target = pre.get("primary_target", None)
            secondary_target = pre.get("secondary_target", None)
            stop_loss = pre.get("stop_loss", None)
            trailing_stop = pre.get("trailing_stop", "N/A")
            entry_price = pre.get("entry_price", None)
            current_order_type = pre.get("current_order_type", "None")

            # === Rescue Count ===
            rescue_count = pre.get("rescue_count", 0)
            if rescue_count > 0:
                rescue_str = f"RESCUE ACTIVE: {rescue_count}/5"
            else:
                rescue_str = "Rescue: 0/5"

            # === MAIN SCALE P2 / P3 status ===
            SCALE_TS_MIN_DD = 0.04
            scale_count = int(pre.get("main_scale_count") or 0)
            scale_slice = float(pre.get("main_scale_slice") or 0.0)
            ts_now = pre.get("trailing_stop")
            entry_now = pre.get("entry_price")

            if scale_count <= 0:
                scale_str = "Scale: —"
            elif scale_count >= 3:
                scale_str = f"Scale: P3/3 DONE | Slice: {scale_slice:.0f} {quote_asset}"
            else:
                scale_str = f"Scale: P{scale_count}/3 | Next: P{scale_count + 1} | Slice: {scale_slice:.0f} {quote_asset}"

            next_px_str = "N/A"
            if (pre.get("order_type") == "buy"
                and scale_count in (1, 2)
                and isinstance(ts_now, float) and isinstance(entry_now, float)
                and entry_now > 0 and ts_now > 0):

                ts_dd = (ts_now / entry_now) - 1.0
                scale_trigger = ts_now * 1.02
                ts_underwater = ts_now < entry_now
                ts_deep_enough = ts_now <= entry_now * (1.0 - SCALE_TS_MIN_DD)
                trigger_underwater = scale_trigger < entry_now

                if ts_underwater and ts_deep_enough and trigger_underwater:
                    if isinstance(current_price, float) and current_price > 0:
                        dist_px = ((scale_trigger - current_price) / current_price) * 100
                        if dist_px <= 0:
                            next_px_str = (
                                f"${scale_trigger:.6f}  (TS+2% | P{scale_count + 1} soon or active)"
                            )
                        else:
                            next_px_str = (
                                f"${scale_trigger:.6f}  (TS+2% | {dist_px:.2f}% from now | P{scale_count + 1})"
                            )
                    else:
                        next_px_str = f"${scale_trigger:.6f}  (TS+2% | P{scale_count + 1})"
                else:
                    next_px_str = "T.S out of range; Rescue Unlocked"
            elif scale_count >= 3:
                next_px_str = "P3 done — rescue may arm"

            if pre.get("order_type") == "buy":
                market_price_str = f"${current_price:.6f}" if isinstance(current_price, float) else current_price

                # Calculate profit percentages
                primary_profit = calculate_profit_percentage(primary_target, entry_price) if primary_target and entry_price else 0.0
                secondary_profit = calculate_profit_percentage(secondary_target, entry_price) if secondary_target and entry_price else 0.0
                stop_loss_profit = calculate_profit_percentage(stop_loss, entry_price) if stop_loss and entry_price else 0.0
                trailing_stop_profit = calculate_profit_percentage(trailing_stop, entry_price) if isinstance(trailing_stop, float) and entry_price else 0.0

                primary_profit_str = f"{primary_profit:.2f}%" if primary_profit >= 0 else f"({-primary_profit:.2f}%)"
                secondary_profit_str = f"{secondary_profit:.2f}%" if secondary_profit >= 0 else f"({-secondary_profit:.2f}%)"
                stop_loss_profit_str = f"-{-stop_loss_profit:.2f}%" if stop_loss_profit <= 0 else f"{stop_loss_profit:.2f}%"
                trailing_stop_profit_str = f"{trailing_stop_profit:.2f}%" if trailing_stop_profit >= 0 else f"-{-trailing_stop_profit:.2f}%"

                # === Total Invested ===
                total_invested = (pre.get("amount", 0) * entry_price) if entry_price else 0.0

                # === Smart Next Rescue Trigger ===
                rescue_trigger_distance = 0.004
                next_rescue_price = trailing_stop * (1 + rescue_trigger_distance) if isinstance(trailing_stop, float) else None

                # Only show Next Rescue Trigger when we are still in the rescue activation zone
                if (isinstance(current_price, float) and isinstance(entry_price, float) and 
                    -8.81 <= trailing_stop_profit <= 0.4):
                    if isinstance(next_rescue_price, float) and current_price > 0:
                        distance_to_next = ((next_rescue_price - current_price) / current_price * 100)
                        if distance_to_next <= 0:
                            next_rescue_str = f"${next_rescue_price:.6f} (Trigger soon or active)"
                        else:
                            next_rescue_str = f"${next_rescue_price:.6f} ({distance_to_next:.2f}% from now)"
                    else:
                        next_rescue_str = "N/A"
                else:
                    next_rescue_str = "Outside rescue zone"

                # === Shutdown T.S+1% (Keep & Wait) – only when Rescue 5/5 and TS is a loss ===
                shutdown_ts_str = "N/A"
                if (rescue_count >= 5 and
                    isinstance(trailing_stop, float) and isinstance(entry_price, float) and
                    trailing_stop > 0 and entry_price > 0 and
                    trailing_stop < entry_price):          # TS must be under entry (loss zone)
                    shutdown_price = trailing_stop * 1.01
                    shutdown_ts_str = f"${shutdown_price:.6f}"

                # === NEW: Position Open Since + Duration ===
                open_time = pre.get("position_open_time")
                if open_time:
                    try:
                        dt = datetime.fromisoformat(open_time.replace("Z", "+00:00"))
                        time_str = dt.strftime("%Y-%m-%d %H:%M:%S UTC")

                        # Calculate duration
                        now = datetime.now(timezone.utc)
                        delta = now - dt
                        days = delta.days
                        hours = delta.seconds // 3600
                        minutes = (delta.seconds % 3600) // 60
                        
                        if days > 0:
                            duration_str = f"{days}d {hours}h {minutes}m"
                        elif hours > 0:
                            duration_str = f"{hours}h {minutes}m"
                        else:
                            duration_str = f"{minutes}m"
                    except:
                        time_str = "Unknown"
                        duration_str = "N/A"
                else:
                    time_str = "Not recorded yet"
                    duration_str = "N/A"

                # Safe Entry string
                entry_str = f"${entry_price:.6f}" if isinstance(entry_price, float) else "N/A"

                # ===== Main position info =====
                order_str.append(
                    f"{symbol} (Position Open)\n"
                    f"⏰ Opened: {time_str} ({duration_str})\n"
                    f"🎯 Average Entry Price: {entry_str}\n"
                    f"{rescue_str}\n"
                    f"{scale_str}\n"
                    f"✅ Invested: ${total_invested:.2f} | Qty XRP: {order_quantity:.2f}\n"
                    f"Unrealized: {profit_str}\n"
                    f"Next P2/P3 Trigger: {next_px_str}\n"
                    f"Next Rescue Trigger: {next_rescue_str}\n\n"
                    
                    f"❄ Shutdown T.S+1%: {shutdown_ts_str}\n"
                    f"🆘Trailing Stop: ${trailing_stop:.6f} ({trailing_stop_profit_str})\n"
                    f"Stop-Loss: ${stop_loss:.6f} ({stop_loss_profit_str})\n\n"

                    f"Current Market: {market_price_str}\n"
                )
            else:
                order_str.append(
                    f"{symbol} (No active position)\n"
                    f"Quantity: {quote_balance:.2f} {quote_asset}"
                ) 
                

                # ==================== RESCUE TRAILING DIP ====================
                if pre.get("rescue_trailing_dip_active", False):
                    order_str.append("\n\n🆘 Rescue Trailing Dip: ACTIVE")
                    
                    rescue_dip_level = pre.get("rescue_dip_level")
                    rescue_dip_distance = pre.get("rescue_dip_distance")
                    
                    if rescue_dip_level is not None:
                        order_str.append(f"📉 Rescue Dip Level: {rescue_dip_level:.6f}")
                    if rescue_dip_distance is not None:
                        order_str.append(f"📏 Rescue Dip Distance: {rescue_dip_distance:.6f}")
                    
                    order_str.append(f"💰 Current Price: {current_price:.6f}")
                    
                    if isinstance(rescue_dip_level, float) and isinstance(current_price, float) and rescue_dip_level > 0:
                        distance_pct = ((rescue_dip_level - current_price) / current_price) * 100
                        order_str.append(f"📏 Distance to Rebound: {distance_pct:.2f}%")
            
            # --- Trailing-Dip (pre-entry) ---
            # Only show trailing-dip info when no buy order is active (pre-entry management)
            if pre.get("trailing_dip_active", False) and pre.get("order_type") is None:
                dip_level = pre.get("dip_level")
                dip_distance = pre.get("dip_distance")
                original_trigger_price = pre.get("original_trigger_price")
                entry_pattern = pre.get("entry_pattern")
                
                order_str.append("🚀 Trailing-Dip: ACTIVE")
                
                if dip_level is not None:
                    order_str.append(f"📉 Dip Level: {dip_level:.6f}")
                if dip_distance is not None:
                    order_str.append(f"📏 Dip Distance: {dip_distance:.6f}")
                if original_trigger_price is not None:
                    order_str.append(f"🎯 Trigger Price: {original_trigger_price:.6f}")
                
                # Current Price
                order_str.append(f"💰 Current Price: {current_price:.6f}")
                
                if entry_pattern is not None:
                    order_str.append(f"🔍 Entry Pattern: {entry_pattern}")

            order_str = "\n".join(order_str) if order_str else "None"
            pair = symbol


            # NEW: Pattern Radar Block (All >=60% from evaluate, sorted descending)
            patterns_radar = ""
            if isinstance(current_price, float) and indicators is not None:
                patterns = await evaluate_pattern_matches(symbol, indicators, current_price, suppress_if_active=True)
                
                # Filter to >=60%, sort by match_pct descending
                qualifying_patterns = [p for p in patterns if p['match_pct'] >= 65]
                sorted_patterns = sorted(qualifying_patterns, key=lambda p: p['match_pct'], reverse=True)
                
                if sorted_patterns:
                    patterns_radar = f"Valid Patterns (>=65%): {len(sorted_patterns)} found\n\n"
                    for p in sorted_patterns:
                        patterns_radar += f"PATTERN {p['number']}: {p['name']}\n"
                        patterns_radar += f"Match: {p['match_pct']}%\n\n"
                else:
                    patterns_radar = "No Qualified Pattern to trigger For Now\n\n"

            # === Fetch BTC Price ===
            btc_price = "N/A"
            try:
                btc_price_data = await get_current_price("BTC/USDT")
                if isinstance(btc_price_data, float) and btc_price_data > 0:
                    btc_price = f"${btc_price_data:,.2f}"
                else:
                    btc_price = "N/A"
            except:
                btc_price = "N/A"

            # Construct message for this symbol
            message = (
                f"Status Panel:\n\n"
                f"Pair: {pair}\n"
                f"Live Price: ${current_price:.6f}\n"
                f"Live BTC Price: {btc_price}\n\n"
                f"Balances (Wallet):\n"
                f"Free: {base_balance:.8f} {base_asset}\n"
                f"Locked: {base_locked:.8f} {base_asset}\n"
                f"Free {quote_asset}: {quote_balance:.2f} {quote_asset}\n"
                f"Locked {quote_asset}: {quote_locked:.2f} {quote_asset}\n\n"
                f"Live Indicators:\n"
                f"{indicators_str}\n\n"
                f"Tiers Analysis:\n"
                f"{tiers_str}\n\n"
                f"{profit_str}\n\n"
                f"Orders:\n"
                f"{order_str}\n\n"
                f"{patterns_radar}\n\n"
                f"Actual Price: ${current_price:.6f}\n"
                f"BTC Price: {btc_price}\n\n"
            )
            messages.append(message)

        # Send combined message
        full_message = "\n".join(messages)
        await send_telegram_message(update.get_bot(), full_message)
        logger.info(f"Telegram message sent: {full_message}")
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Error fetching status: {str(e)}")
        await send_telegram_message(update.get_bot(), f"Error fetching status: {str(e)}")
        return ConversationHandler.END

async def isaac_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bot = update.get_bot()
        isaac = await load_isaac_state()
        symbol = ISAAC_DCA_SYMBOL
        base_asset = symbol.split('/')[0].upper()
        current_price = await get_current_price(symbol)
        if not current_price:
            await send_telegram_message(bot, "ISAAC STATUS ERROR: Unable to fetch price.")
            return

        account = await binance_request("GET", "/api/v5/account/balances")
        base_balance = 0.0
        quote_balance = 0.0
        if account:
            for asset in account:
                if asset["ccy"].upper() == base_asset:
                    base_balance = float(asset.get("availBal", "0"))
                if asset["ccy"].upper() == "USDT":
                    quote_balance = float(asset.get("availBal", "0"))

        orders = isaac.get("orders", [])
        num_orders = len(orders)
        if num_orders > 0:
            total_size = sum(o['size'] for o in orders)
            avg_entry = sum(o['size'] * o['entry_price'] for o in orders) / total_size
            last_entry = orders[-1]['entry_price']
        else:
            total_size = 0.0
            avg_entry = 0.0
            last_entry = 0.0

        # Calculate next buy trigger price
        if last_entry > 0:
            # ==================== DYNAMIC DROP % DISPLAY ====================
            if num_orders == 0:
                next_drop_pct = 0.0      # Order 1 = Direct buy
            elif num_orders == 1:
                next_drop_pct = 3.0
            elif num_orders == 2:
                next_drop_pct = 5.0
            elif num_orders == 3:
                next_drop_pct = 8.0
            elif num_orders == 4:
                next_drop_pct = 24.0
            elif num_orders == 5:
                next_drop_pct = 32.0
            else:  # num_orders >= 6
                next_drop_pct = 40.0     # Trailing Dip for 7th order

            next_buy_price = last_entry * (1 - next_drop_pct / 100)
            next_buy_str = f"${next_buy_price:.6f} (-{next_drop_pct}% from last entry)"
        else:
            next_buy_str = "Waiting for first entry"

        # Dynamic TP
        if num_orders <= 1:
            dynamic_tp = 2.5
        elif num_orders == 2:
            dynamic_tp = 2.8
        elif num_orders == 3:
            dynamic_tp = 3.2
        elif num_orders == 4:
            dynamic_tp = 3.7
        elif num_orders == 5:
            dynamic_tp = 4.2
        elif num_orders == 6:
            dynamic_tp = 4.7
        else:  # 7/7
            dynamic_tp = 5.2
            
        tp_price = avg_entry * (1 + dynamic_tp / 100) if avg_entry > 0 else 0.0

        # PnL
        pnl_usd = (current_price - avg_entry) * total_size if avg_entry > 0 else 0.0
        pnl_pct = ((current_price - avg_entry) / avg_entry * 100) if avg_entry > 0 else 0.0

        # Pool & Portfolio
        used_by_isaac = base_balance * current_price
        available_for_isaac = max(0.0, ISAAC_ALLOCATED_USDT - used_by_isaac)
        virtual_usdt = min(available_for_isaac, isaac.get('virtual_usdt', ISAAC_ALLOCATED_USDT))
        dca_value = base_balance * current_price
        portfolio_estimate = quote_balance + dca_value
        weight_pct = (dca_value / portfolio_estimate * 100) if portfolio_estimate > 0 else 0.0

        # ================= TRAILING DIP STATUS =================
        td_status = "Inactive"
        td_info = ""
        if isaac.get("isaac_trailing_dip_active", False):
            td_status = "🟡 ACTIVE"
            dip_level = isaac.get("isaac_dip_level") or 0
            dip_distance = isaac.get("isaac_dip_distance") or 0
            td_info = (
                f" • Current Price : ${current_price:.6f}\n"
                f" • Dip Level     : ${dip_level:.6f}\n"
                f" • Dip Distance  : ${dip_distance:.6f}\n"
                f" • Distance %    : {(dip_distance/current_price*100 if current_price > 0 else 0):.2f}%"
            )

        # ================= TRAILING STOP STATUS =================
        ts_status = "Inactive"
        ts_info = ""
        if isaac.get("isaac_trailing_stop") is not None:
            ts_status = "🔴 ACTIVE"
            stop_level = isaac.get("isaac_trailing_stop") or 0
            stop_distance = isaac.get("isaac_trailing_distance") or 0
            ts_info = (
                f" • Current Price : ${current_price:.6f}\n"
                f" • Stop Level    : ${stop_level:.6f}\n"
                f" • Distance      : ${stop_distance:.6f}\n"
                f" • Distance %    : {(stop_distance/current_price*100 if current_price > 0 else 0):.2f}%"
            )

        msg = (
            "ISAAC DCA STATUS PANEL\n\n"
            f"Symbol: {symbol}\n"
            f"Status: {'Running' if not isaac.get('paused', False) else 'Paused'}\n\n"
            f"Live Price: ${current_price:.6f}\n"
            f"Purchased Amount: {total_size:.6f} {base_asset}\n"
            f"Average Entry: ${avg_entry:.6f}\n"
            f"Last Entry: ${last_entry:.6f}\n\n"
            f"Wallet:\n"
            f"• {base_balance:.6f} {base_asset}\n"
            f"• {quote_balance:.2f} USDT (total)\n\n"
            f"Virtual USDT Pool: ${virtual_usdt:.2f} / {ISAAC_ALLOCATED_USDT:.0f}\n"
            f"Initial Buy Size: ${ISAAC_DCA_INITIAL_USDT:.0f} (Scaled)\n"
            f"Orders in Cycle: {num_orders}/7 \n\n"
            f"Take Profit: ${tp_price:.6f} (+{dynamic_tp}% Dynamic)\n"
            f"Next Buy Trigger: {next_buy_str}\n\n" 
            f"Unrealized PnL:\n"
            f"• {pnl_usd:.2f} USDT\n"
            f"• {pnl_pct:.2f}%\n\n"
            f"Portfolio Weight: {dca_value:.2f}$ / {portfolio_estimate:.2f}$ ({weight_pct:.2f}%)\n\n"
            f"Trailing Dip: {td_status}\n{td_info}\n\n"
            f"Trailing Stop: {ts_status}\n{ts_info}\n\n"
            # New dynamic drop settings display
            f"Dynamic Drop Settings:\n"
            f"• Order 1 >> Direct Buy >> 5000 USDT\n"
            f"• Order 2 >> -3% >> 1500 USDT\n" 
            f"• Order 3 >> -5% >> 2250 USDT\n"
            f"• Order 4 >> -8% >> 3375 USDT\n"
            f"• Order 5 >> -24% >> 5062.5 USDT\n"
            f"• Order 6 >> -32% >> 7593.75 USDT\n"
            f"• Order 7 >> Trailing Dip @ -40% >> 11390.625 USDT\n\n"
            # New dynamic TP settings display
            f"Dynamic TP Settings:\n"
            f"• Order 1 >> +2.5%\n"
            f"• Order 2 >> +2.8%\n"
            f"• Order 3 >> +3.2%\n"
            f"• Order 4 >> +3.7%\n"
            f"• Order 5 >> +4.2%\n"
            f"• Order 6 >> +4.7%\n"
            f"• Order 7 >> +5.2%\n"
        )
        await send_telegram_message(bot, msg)

    except Exception as e:
        logger.error(f"ISAAC STATUS ERROR: {str(e)}")
        await send_telegram_message(bot, f"ISAAC STATUS ERROR: {str(e)}")

# Check price
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        shown = active_last_symbol()
        if not shown:
            await send_telegram_message(update.get_bot(), f"No pair set. Use {active_pair_cmd()}")
            return
        price = await get_current_price(shown)
        if price:
            await send_telegram_message(update.get_bot(), f"{shown}: ${price:.6f}")
        else:
            await send_telegram_message(update.get_bot(), f"Error fetching price for {shown}")
    except Exception as e:
        logger.error(f"Error fetching price: {str(e)}")
        await send_telegram_message(update.get_bot(), f"Error fetching price: {str(e)}")

def read_crypto_financial(file_path, time_window_hours=24):
    """Read messages from crypto_financial.txt within the specified time window."""
    try:
        messages = []
        filtered_count = 0
        current_time = datetime.now(timezone.utc)
        time_threshold = current_time - timedelta(hours=time_window_hours)
        
        with open(file_path, 'r', encoding='utf-8') as file:
            for line in file:
                line = line.strip()
                if not line or len(line) < 10:  # Skip empty or very short lines
                    continue
                timestamp = None
                message = line
                if line.startswith('[') and ']' in line:
                    try:
                        timestamp_str = line[1:line.index(']')]
                        timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                        timestamp = timestamp.replace(tzinfo=timezone.utc)
                        message = line[line.index(']') + 2:].strip()
                    except ValueError:
                        logger.warning(f"Invalid timestamp in line: {line[:50]}...")
                if timestamp and timestamp < time_threshold:
                    filtered_count += 1
                    continue
                if message:  # Ensure message is non-empty
                    messages.append(message)
        logger.info(f"Read {len(messages)} messages from {file_path}, filtered {filtered_count} outdated messages")
        return messages
    except FileNotFoundError:
        logger.error(f"File not found: {file_path}")
        return []
    except Exception as e:
        logger.error(f"Error reading {file_path}: {str(e)}")
        return []

def adjust_crypto_sentiment(raw_score, text, symbol=None):
    """
    Post-process VADER score with crypto-specific keyword biases.
    Adjusted to be less aggressive and more balanced.
    Works for any symbol + special BTC treatment.
    Returns adjusted compound score (-1 to +1).
    """
    adjusted = float(raw_score)
    
    text_lower = text.lower()
    
    # Crypto keyword biases - milder and more targeted
    crypto_keywords = {
        # Strong negatives (fear, crashes, liquidations)
        r'liquidat|crash|plunge|dump|extreme fear|capitulation|bloodbath': -0.20,
        # Moderate negatives (sell pressure, weakness)
        r'sell-off|bear market|correction|down \d+%|fell below|drop \d+%|weakness': -0.12,
        # Mild negatives
        r'fall|decline|weaken|pressure|cautious': -0.07,
        
        # Strong positives (bullish catalysts)
        r'launch|upgrade|rally|bull run|breakout|all-time high|sustainable growth': +0.20,
        # Moderate positives
        r'positive|optimistic|adoption|expansion|higher|gain \d+%|recovery': +0.12,
        # Mild positives
        r'free|bonus|commit|innovat|supportive': +0.07,
    }
    
    for pattern, delta in crypto_keywords.items():
        if re.search(pattern, text_lower):
            adjusted += delta
            break  # Only one major adjustment per message
    
    # BTC special treatment - BTC news has stronger market impact
    if 'btc' in text_lower or 'bitcoin' in text_lower:
        if any(neg in text_lower for neg in ['crash', 'liquidat', 'plunge', 'fear']):
            adjusted -= 0.08
        elif any(pos in text_lower for pos in ['rally', 'breakout', 'adoption']):
            adjusted += 0.06
    
    # Symbol-specific gentle boost (for the traded pair)
    if symbol:
        symbol_clean = sentiment_token(symbol)
        if symbol_clean in text_lower or symbol_clean.replace(' ', '') in text_lower:
            # Small boost if the message is directly about the traded pair
            if adjusted > 0:
                adjusted += 0.04
            elif adjusted < 0:
                adjusted -= 0.04
    
    # Clamp to valid range
    return max(-1.0, min(1.0, adjusted))

async def fetch_live_sentiment(symbol='XRPUSDT', btc_weight=0.6):
    """
    Fetch real-time crypto sentiment via Fear & Greed Index API (free, lightweight).
    Normalizes 0-100 to -1/+1: Extreme Fear (-1) to Extreme Greed (+1).
    Blends with symbol bias (alts less extreme than BTC).
    Returns dict: {'symbol_score': float, 'btc_score': float, 'final_score': float}
    """
    try:
        url = "https://api.alternative.me/fng/?limit=1"  # Free API, no key needed
        resp = requests.get(url, timeout=5)  # 5s timeout for speed
        if resp.status_code == 200:
            data = resp.json().get('data', [{}])[0]
            if data:
                greed_raw = int(data['value'])  # 0=Extreme Fear, 100=Extreme Greed
                fng_normalized = (greed_raw / 50.0) - 1.0  # Map to -1 (fear) to +1 (greed)
                
                # Symbol adjustment: Alts (e.g., DOGE) follow BTC but dampened
                symbol_adj = fng_normalized * 0.85  # 15% less extreme for volatility
                
                btc_score = fng_normalized
                symbol_score = symbol_adj
                final_score = (symbol_score * (1 - btc_weight)) + (btc_score * btc_weight)
                
                logger.info(f"Live F&G: Raw={greed_raw}, BTC={btc_score:.3f}, {symbol}={symbol_score:.3f}, Final={final_score:.3f}")
                return {'symbol_score': symbol_score, 'btc_score': btc_score, 'final_score': final_score}
        
        logger.warning("F&G API fetch failed – fallback to 0.0")
        return {'symbol_score': 0.0, 'btc_score': 0.0, 'final_score': 0.0}
    
    except Exception as e:
        logger.error(f"Live sentiment error: {str(e)} – fallback to 0.0")
        return {'symbol_score': 0.0, 'btc_score': 0.0, 'final_score': 0.0}

_MACRO_NEG = [
    (re.compile(r'\b(cpi|pce|nfp|nonfarm|payrolls|fomc|fed)\b.{0,48}\b(hot|hotter|higher|beat|beats|surge|surged|above|hawkish|sticky|hike|hikes)\b', re.I), -0.95, "HOT_MACRO"),
    (re.compile(r'\b(hawkish|rate hike|rates hiked|higher for longer|no cut|cuts delayed|yields? spike|yields? surge)\b', re.I), -0.90, "HAWKISH"),
    (re.compile(r'\b(liquidation cascade|flash crash|bank run|emergency rate)\b', re.I), -0.92, "CASCADE"),
]
_MACRO_POS = [
    (re.compile(r'\b(cpi|pce|nfp|payrolls|fomc|fed)\b.{0,48}\b(cool|cooler|soft|softer|below|miss|misses|dovish|cut|cuts)\b', re.I), 0.75, "COOL_MACRO"),
    (re.compile(r'\b(dovish|rate cut|rates cut|pause confirmed)\b', re.I), 0.70, "DOVISH"),
]

def _macro_hit(text):
    for cre, score, tag in _MACRO_NEG:
        if cre.search(text):
            return score, tag
    for cre, score, tag in _MACRO_POS:
        if cre.search(text):
            return score, tag
    return 0.0, ""

def _read_news_events(file_path, hours):
    """(age_minutes, text). Unstamped lines are kept only if nothing in the file has a time."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    stamped, bare = [], []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if len(line) < 10:
                    continue
                ts, text = None, line
                if line.startswith("[") and "]" in line:
                    try:
                        ts = datetime.strptime(line[1:line.index("]")], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                        text = line[line.index("]") + 1:].strip()
                    except ValueError:
                        ts = None
                if not text:
                    continue
                if ts is None:
                    bare.append(text)
                elif ts >= cutoff:
                    stamped.append(((now - ts).total_seconds() / 60.0, text))
    except FileNotFoundError:
        return []
    if stamped:
        return stamped
    return [(0.0, t) for t in bare[-8:]]

def _decayed_mean(events, half_life_min):
    if not events:
        return 0.0, ""
    num = den = 0.0
    worst_tag, worst = "", 0.0
    for age, text in events:
        macro, tag = _macro_hit(text)
        vader = adjust_crypto_sentiment(analyzer.polarity_scores(text)["compound"], text)
        score = (0.25 * vader + 0.75 * macro) if macro else vader
        w = math.exp(-age / half_life_min)
        num += score * w
        den += w
        if macro < worst:
            worst, worst_tag = macro, tag
    return (num / den if den else 0.0), worst_tag

async def calculate_sentiment(symbol="DOGEUSDT"):
    """
    Fast news shock. Fear & Greed is only 10% and cannot block a buy by itself.
    Technicals are not included.
    """
    try:
        shock_events = _read_news_events("crypto_financial.txt", hours=0.75)   # 45 min
        context_events = _read_news_events("crypto_financial.txt", hours=6)
        shock, shock_tag = _decayed_mean(shock_events, half_life_min=12)
        context, context_tag = _decayed_mean(context_events, half_life_min=90)
        tag = shock_tag or context_tag
        live = await fetch_live_sentiment(symbol)
        fng = live.get("final_score", 0.0)
        dynamic = (0.75 * shock) + (0.15 * context) + (0.10 * fng)
        dynamic = max(-1.0, min(1.0, dynamic))
        logger.info(
            f"NEWS SHOCK {symbol}: shock={shock:.3f} context={context:.3f} "
            f"fng={fng:.3f} dynamic={dynamic:.3f} tag={tag or '-'}"
        )
        return {"final_score": dynamic, "shock": shock, "context": context, "tag": tag}
    except Exception as e:
        logger.error(f"Sentiment calculation error: {str(e)}")
        return {"final_score": 0.0, "shock": 0.0, "context": 0.0, "tag": ""}
    
# --- NEW: Pattern-aware check for trailing-dip validity (paste above trading loop) ---
async def check_active_patterns(symbol: str, indicators: dict, current_price: float, pre: dict, strict_for_execution: bool = False) -> bool:    
    
    try:
        logger.debug(f"check_active_patterns for {symbol} | strict_for_execution={strict_for_execution} | entry_pattern={pre.get('entry_pattern')}")
        entry_pat = pre.get('entry_pattern')  # Specific triggering pattern
        def g(k, d=None):  # Script-aligned defaults
            v = indicators.get(k)
            if v is None:
                if d is None:  # Stricter: raise if no default specified
                    raise ValueError(f"Missing required indicator: {k}")
                return d
            return v

        # Eval-aligned helpers (arrays for prev/current) - Safe computation
        volumes = indicators.get('volumes', np.array([current_price]))  # Fallback to current if None
        current_volume = volumes[-1] if len(volumes) > 0 else current_price
        avg_volume = np.mean(volumes[-10:]) if len(volumes) >= 10 else current_volume
        avg_volume_20 = np.mean(volumes[-20:]) if len(volumes) >= 20 else avg_volume
        prev_volume = volumes[-2] if len(volumes) >= 2 else current_volume * 0.9

        rsi_values = indicators.get('rsi_values', [indicators.get('rsi', 50)])
        rsi = indicators.get('rsi', 50)
        rsi_prev = rsi_values[-2] if len(rsi_values) >= 2 else rsi - 1  # Safe: -1 delta fallback

        btc_ig = pre_orders.get(symbol, {}).get("btc_ig", "N/A")

        macd_values = indicators.get('macd_values', [indicators.get('macd_line', 0)])
        macd_line = indicators.get('macd_line', 0)
        prev_macd = macd_values[-2] if len(macd_values) >= 2 else macd_line * 0.9
        fib_61_8 = indicators.get('fib_levels', {}).get('61.8%', None) if indicators.get('fib_levels') else None

        histogram_values = indicators.get('histogram_values', [indicators.get('histogram', 0)])
        histogram = indicators.get('histogram', 0)
        prev_histogram = histogram_values[-2] if len(histogram_values) >= 2 else histogram - 0.1  # Delta fallback (bottoming trend)

        signal_values = indicators.get('signal_values', [indicators.get('signal_line', 0)])
        signal_line = indicators.get('signal_line', 0)
        prev_signal = signal_values[-2] if len(signal_values) >= 2 else signal_line * 0.9
        price_low = min(indicators['closes'][-5:]) if len(indicators['closes']) >= 5 else current_price

        highs = indicators.get('highs', np.array([current_price]))
        prev_high = highs[-5:].max() if len(highs) >= 5 else current_price

        closes = indicators.get('closes', np.array([current_price]))
        prev_close = closes[-2] if len(closes) >= 2 else current_price * 0.99  # Safe fallback

        bb_width_proxy = indicators.get('bb_width', 0.02)
        atr = indicators.get('atr', current_price * 0.01)
        prev_atr = indicators.get('prev_atr', atr * 0.9)
        atr_percent = (atr / current_price * 100) if current_price > 0 else 0
        fib_levels = indicators.get('fib_levels', {})
        ema_5 = indicators.get('ema_5', current_price)
        ema_9 = indicators.get('ema_9', current_price)
        ema_13 = indicators.get('ema_13', current_price)
        ema_21 = indicators.get('ema_21', current_price)
        ema_50 = indicators.get('ema_50', current_price)
        vwap = indicators.get('vwap', current_price)
        bb_middle = indicators.get('middle_band', current_price)
        bb_upper = bb_middle + (bb_width_proxy * bb_middle) if bb_middle and bb_width_proxy else current_price * 1.02
        bb_lower = bb_middle - (bb_width_proxy * bb_middle) if bb_middle and bb_width_proxy else current_price * 0.98
        support = indicators.get('support', current_price)
        csi = pre.get('csi', 0)  # From pre, like eval

        # NEW: CVD vars (net buy/sell pressure) - Verified: Safe array fallback, prev=0.9x for continuity
        cvd_values = indicators.get('cvd_values', [indicators.get('cvd', 0)])
        cvd = indicators.get('cvd', 0)
        prev_cvd = cvd_values[-2] if len(cvd_values) >= 2 else cvd * 0.9  # Safe fallback
        cvd_change_pct = ((cvd - prev_cvd) / abs(prev_cvd + 1e-6)) * 100 if prev_cvd != 0 else 0  # % change; avoids div0

        # NEW: OBI vars (bid/ask imbalance)
        obi_values = indicators.get('obi_values', [indicators.get('obi', 0.0)])
        obi = indicators.get('obi', 0.0)

        # Better fallback logic
        if len(obi_values) >= 2:
            prev_obi = obi_values[-2]
        else:
            prev_obi = obi_values[0] if obi_values else obi

        obi_imbalance = obi - prev_obi
        

        # ---------- NEW SAFE HIGH-PRICE FILTER VARIABLES ----------
        recent_high_5 = max(highs[-5:]) if len(highs) >= 5 else current_price
        recent_high_10 = max(highs[-10:]) if len(highs) >= 10 else recent_high_5

        price_extension_pct = ((current_price - ema_21) / ema_21 * 100) if ema_21 > 0 else 0
        distance_from_low_pct = ((current_price - price_low) / price_low * 100) if price_low > 0 else 0
        near_recent_top = current_price >= recent_high_5 * 0.996
        overextended_price = current_price > ema_21 * 1.018

        # ==========================================================
        # ULTIMATE TOP DETECTOR + ATR BEAST vNEXT + PATTERNS
        # Final Consolidated Block - Cleaned & Improved Version
        # ==========================================================

        # -----------------------------
        # SAFE DEFAULTS
        # -----------------------------
        top_risk_score = 0.0
        top_detector_triggered = False
        top_detector_level = "LOW"
        hard_no_buy = False

        # ==========================================================
        # 1. ULTIMATE TOP DETECTOR
        # ==========================================================

        # ---------------------------------------------------------- 
        # 1. Price stretched near highs
        # ----------------------------------------------------------
        if near_recent_top:
            top_risk_score += 18
            
        if current_price >= recent_high_10 * 0.998:
            top_risk_score += 12
            
        if price_extension_pct > 1.8:
            top_risk_score += 12
            
        if price_extension_pct > 3.0:
            top_risk_score += 10
            
        # ---------------------------------------------------------- 
        # 2. RSI exhaustion
        # ----------------------------------------------------------
        if rsi > 72:
            top_risk_score += 15
            
        if rsi > 76:
            top_risk_score += 10
            
        if rsi < rsi_prev and rsi > 70:
            top_risk_score += 10
            
        # ---------------------------------------------------------- 
        # 3. Volume weakness / breakout failure
        # ----------------------------------------------------------
        if near_recent_top and current_volume < avg_volume * 0.85:
            top_risk_score += 15
            
        if current_volume < prev_volume * 0.80 and current_price >= prev_close:
            top_risk_score += 8
            
        # ---------------------------------------------------------- 
        # 4. Orderflow exhaustion
        # ----------------------------------------------------------
        if obi < 0:
            top_risk_score += 10
            
        if obi < prev_obi and current_price >= prev_close:
            top_risk_score += 8
            
        if cvd < prev_cvd and current_price >= prev_close:
            top_risk_score += 10
            
        if cvd_change_pct < -5:
            top_risk_score += 10
            
        # ---------------------------------------------------------- 
        # 5. Momentum stall
        # ----------------------------------------------------------
        if histogram < prev_histogram and histogram > 0:
            top_risk_score += 12
            
        if macd_line < signal_line and macd_line > 0:
            top_risk_score += 10
            
        # ---------------------------------------------------------- 
        # 6. Low ATR squeeze near highs (classic trap)
        # ----------------------------------------------------------
        if atr_percent < 0.55 and near_recent_top:
            top_risk_score += 10
            
        if bb_width_proxy < 0.014 and near_recent_top:
            top_risk_score += 8
            
        # ---------------------------------------------------------- 
        # 7. Resistance rejection micro signal
        # ----------------------------------------------------------
        if current_price < prev_close and near_recent_top:
            top_risk_score += 10
            
        # ---------------------------------------------------------- 
        # Clamp & Final Top Detector Result
        # ----------------------------------------------------------
        top_risk_score = max(0.0, min(100.0, top_risk_score))
        top_risk_pct = round(top_risk_score)

        if top_risk_score >= 75:
            top_detector_level = "EXTREME"
            top_detector_triggered = True
        elif top_risk_score >= 55:
            top_detector_level = "HIGH"
            top_detector_triggered = True
        elif top_risk_score >= 35:
            top_detector_level = "MEDIUM"
        else:
            top_detector_level = "LOW"

        # ---------------------------------------------------------- 
        # HARD NO-BUY CONDITIONS (Nuclear Protection)
        # ----------------------------------------------------------
        if (rsi > 73 and near_recent_top and current_volume < avg_volume * 0.90):
            hard_no_buy = True
            
        if (near_recent_top and obi < 0 and cvd < prev_cvd):
            hard_no_buy = True
            
        if (price_extension_pct > 3.0 and rsi > 75):
            hard_no_buy = True
            
        # Final Top Detector Summary


        # ==========================================================
        # ATR BEAST vNEXT - IMPROVED & CLEANED
        # Smart ATR Threshold + Confluence Engine + Regime Detection
        # ==========================================================


        # -----------------------------
        # CORE HELPERS & REGIME ENGINE
        # -----------------------------
        atr_threshold = 0.30
        volume_soft_mult = 0.60
        basic_bypass_min = 5
        obi_relax = -0.05
        min_tier_score = 15
        ema_rescue_min = 10

        # Trend & Pressure proxies
        trend_strength_proxy = abs((ema_9 - ema_21) / max(abs(ema_21), 1e-9)) * 100
        pressure_strength_proxy = (abs(cvd_change_pct) + abs(obi_imbalance) * 100) / 2

        # Divergence & Recovery signals
        cvd_divergence = (cvd > prev_cvd) and (current_price < prev_close)
        obi_recovery = (prev_obi < 0 and obi > 0)
        rsi_divergence = (rsi > rsi_prev and current_price < prev_close)
        macd_divergence = (macd_line > prev_macd and current_price < prev_close)

        # --- Market Regime Detection ---
        regime = "neutral"
        try:
            full_ema_stack = (ema_5 > ema_9 > ema_13 > ema_21 and ema_21 > ema_50 * 0.995)
        except:
            full_ema_stack = False

        if full_ema_stack and rsi > 52 and macd_line >= signal_line:
            regime = "trend_bull"
        elif current_price < ema_21 and rsi < 42 and macd_line < signal_line:
            regime = "trend_bear"
        elif bb_width_proxy < 0.018 and atr_percent < 1.0:
            regime = "compression"
        elif rsi < 30 and histogram > prev_histogram:
            regime = "reversal_up"
        elif rsi > 72 and histogram < prev_histogram:
            regime = "reversal_down"

        # -----------------------------
        # SMART ATR THRESHOLD ENGINE
        # -----------------------------
        # Base threshold based on volatility
        if atr_percent > 6.0:
            atr_threshold = 2.5
        elif atr_percent < 1.0:
            atr_threshold = 1.2
        else:
            atr_threshold = 0.30

        # Regime adjustments
        if regime == "trend_bull":
            atr_threshold *= 0.72
        elif regime == "trend_bear":
            atr_threshold *= 0.95
        elif regime == "compression":
            atr_threshold *= 1.45
        elif regime == "reversal_up":
            atr_threshold *= 0.82

        # Additional modifiers
        if trend_strength_proxy > 0.35:
            atr_threshold *= 0.92
        if pressure_strength_proxy > 4:
            atr_threshold *= 0.90

        high_vol = current_volume > avg_volume * 1.30
        if high_vol:
            atr_threshold *= 0.75

        # Final clamping
        atr_threshold = max(0.20, min(2.80, atr_threshold))

        logger.debug(f"ATR Threshold Engine >> atr_percent={atr_percent:.2f} | regime={regime} | final_atr_threshold={atr_threshold:.3f}")

        # -----------------------------
        # CONFLUENCE ENGINE (Cleaned & Improved)
        # -----------------------------
        confluence = 0          # Single unified confluence (replaces core + score split)
        atr_bypass_tier = 0
        atr_bypass_active = False

        # Fast Reversal Detection
        fast_reversal_core = (
            (obi > 0.10 and obi_recovery) and
            (cvd_change_pct > 5) and
            (rsi > 50 or rsi_divergence)
        )
        fast_reversal_boosters = 0
        if fast_reversal_core:
            if ema_5 > ema_9:
                fast_reversal_boosters += 1
            if histogram > prev_histogram * 1.10:
                fast_reversal_boosters += 1

        # Basic Bypass Conditions (Foundation)
        basic_bypass_conditions = {
            'ema_alignment': ema_9 > ema_21 > ema_50 * 0.99,
            'macd_above_signal': (macd_line > signal_line * 0.98) or (histogram > prev_histogram * 0.90),
            'histogram_rising': histogram > prev_histogram * 0.90,
            'rsi_neutral': 45 < rsi < 75,
            'price_above_support': current_price > support * 1.005 if support else (support_fallback := current_price * 0.98),
            'volume_sufficient': current_volume > avg_volume * volume_soft_mult,
            'csi_positive': pre.get('csi', 0) > 0.0,
            'fast_reversal_core': fast_reversal_core,
        }

        basic_bypass_met_count = sum(basic_bypass_conditions.values())

        # === Detailed Logging ===
        logger.debug("=== ATR CONFLUENCE ANALYSIS ===")
        logger.debug(f"Basic Bypass Conditions Met: {basic_bypass_met_count}/{len(basic_bypass_conditions)}")

        cond_desc = {
            'ema_alignment': f"EMA Alignment: ema9({ema_9:.6f}) > ema21({ema_21:.6f}) > ema50({ema_50:.6f})*0.99",
            'macd_above_signal': f"MACD Confirm: macd({macd_line:.6f}) > signal({signal_line:.6f}) or hist rising",
            'histogram_rising': f"Histogram Rising: {histogram:.6f} > prev({prev_histogram:.6f})*0.9",
            'rsi_neutral': f"RSI Neutral Zone: {rsi:.2f}",
            'price_above_support': f"Price > Support: {current_price:.6f} > {support:.6f}*1.005" if support else "support_fallback",
            'volume_sufficient': f"Volume: {current_volume:.2f} > avg({avg_volume:.2f}) * {volume_soft_mult:.2f}",
            'csi_positive': f"CSI: {pre.get('csi', 0):.2f} > 0.0",
            'fast_reversal_core': f"Fast Reversal Core: OBI+Recovery + CVD Surge + RSI"
        }

        for cond_name, cond_value in basic_bypass_conditions.items():
            status = "YES" if cond_value else "NO"
            logger.debug(f"   • {cond_desc.get(cond_name, cond_name)} >> {status}")

        # === TIER 1: Foundation ===
        tier1_activated = False
        tier1_reason = "Blocked"

        if (fast_reversal_core and 
            basic_bypass_conditions['ema_alignment'] and 
            basic_bypass_conditions['histogram_rising'] and 
            basic_bypass_conditions['volume_sufficient']):
            tier1_activated = True
            tier1_reason = "GOD-TIER FAST REVERSAL STACK"
        elif basic_bypass_met_count >= basic_bypass_min:
            tier1_activated = True
            tier1_reason = f"MAJORITY RULE ({basic_bypass_met_count}/{len(basic_bypass_conditions)})"

        if tier1_activated:
            confluence += 30
            logger.debug(f"TIER 1 ACTIVATED >> {tier1_reason} | +30 confluence")

        # === Additional Bonuses ===
        if cvd_divergence or obi_recovery:
            confluence += 15
            logger.debug("   +15 | Pressure Recovery Bonus (CVD div or OBI recovery)")

        if fast_reversal_core and fast_reversal_boosters >= 2:
            confluence += 25
            logger.debug(f"   +25 | Ultra-Fast Reversal Bonus (boosters={fast_reversal_boosters})")

        # === HIGHER TIERS (only if Tier 1 passed) ===
        if tier1_activated:
            # Tier 2 - Strong Trend
            if trend_strength_proxy > 0.40:
                confluence += 40
                atr_bypass_tier = max(atr_bypass_tier, 2)
                logger.debug("TIER 2 ACTIVATED (Strong Trend) >> +40 confluence")

            # Tier 3 - Pressure Explosion
            pressure_surge = (cvd_change_pct > 10 and obi_imbalance > 0.05 and high_vol)
            if pressure_surge:
                confluence += 20
                atr_bypass_tier = 4
                logger.debug("TIER 3 ACTIVATED (Pressure Explosion) >> +20 confluence")

            # Tier 4 - Sentiment Surge
            flip_detected = (btc_ig == 'bullish' and pre.get('last_btc_ig', 'neutral') in ['bearish', 'neutral'])
            if flip_detected and pre.get('csi', 0) > 0.50 and obi_recovery:
                confluence += 30
                atr_bypass_tier = max(atr_bypass_tier, 3)
                logger.debug("TIER 4 ACTIVATED (Sentiment Surge + Flip) >> +30 confluence")                    

        # EMA Dominant Shortcut
        if (full_ema_stack and 
            current_price > ema_5 * 1.005 and 
            50 < rsi < 75 and 
            current_volume > avg_volume * volume_soft_mult and 
            (obi > obi_relax or cvd_change_pct > 0)):
            confluence += 15
            logger.debug("   +15 | EMA-Dominant Stack Shortcut")

        # -----------------------------
        # LOW ATR BYPASS LOGIC
        # -----------------------------
        if atr_percent < atr_threshold and tier1_activated:
            atr_bypass_active = True
            # Relax threshold based on tier strength
            relaxation_factor = 0.70 - (atr_bypass_tier * 0.08)
            atr_threshold *= max(0.55, relaxation_factor)
            atr_threshold = max(0.20, atr_threshold)
            logger.debug(f"ATR BYPASS ACTIVE >> Tier {atr_bypass_tier} | Threshold relaxed to {atr_threshold:.3f}")

        # Recent bounce
        is_recent_bounce = False

        if support and support > 0 and atr and atr > 0:
            # Normal case: support exists
            is_recent_bounce = current_price > support * 1.002 and current_price < support + atr * 3.0
        else:
            # Fallback when support is None or invalid
            support_fallback = current_price * 0.98
            is_recent_bounce = current_price > support_fallback and current_price < support_fallback + (atr * 3.0 if atr and atr > 0 else 0)

        logger.debug(f"is_recent_bounce: {is_recent_bounce} (support={support}, atr={atr}, price={current_price}, fallback={support_fallback if 'support_fallback' in locals() else 'N/A'})")

        # BTC_IG flip bonus
        last_btc_ig = pre.get('last_btc_ig', 'neutral')
        flip_detected = (btc_ig == 'bullish' and last_btc_ig in ['bearish', 'neutral'])
        if flip_detected:
            confluence += 1
            logger.debug("BTC_IG flip -> +20 confluence")
        pre['last_btc_ig'] = btc_ig
        await save_state()

        # ==========================================================
        # END OF ULTIMATE TOP DETECTOR + ATR BEAST vNEXT BLOCK
        # ==========================================================       

        # Reuse evaluate_pattern_matches for consistent, rounded scoring (bypass suppression for validation)
        patterns = await evaluate_pattern_matches(symbol, indicators, current_price, suppress_if_active=False)
        regular_contrib = 15 if any(p['number'] in [6, 15] and p['valid'] for p in patterns) else 0
        active_patterns = [p['number'] for p in patterns if p['valid']]

        # Extract booleans for regular patterns (unchanged)
        pattern6 = any(p['number'] == 6 and p['valid'] for p in patterns)        
        pattern15 = any(p['number'] == 15 and p['valid'] for p in patterns)
        pattern16 = any(p['number'] == 16 and p['valid'] for p in patterns)
        pattern9 = any(p['number'] == 9 and p['valid'] for p in patterns)
        
        # MODIFIED: Pattern 22 & Pattern 18 with exemption for persistence (dip-hunting in bearish conditions)
        pattern22 = any(p['number'] == 22 and p['valid'] for p in patterns)
        pattern18 = any(p['number'] == 18 and p['valid'] for p in patterns)
        
        pattern11 = any(p['number'] == 11 and p['valid'] for p in patterns)
        pattern12 = any(p['number'] == 12 and p['valid'] for p in patterns)
        
        # Pattern 22 persistence (already existed)
        if pre.get('entry_pattern') == 22:
            pattern22 = True
            if 22 not in active_patterns:
                active_patterns.append(22)
            logger.info(f"Pattern 22 exempted in {symbol}: Forced active (entry_pattern=22; trailing_dip persists for lower entries)")
        
        # Pattern 18 persistence – NEW: same logic, same power
        if pre.get('entry_pattern') == 18:
            pattern18 = True
            if 18 not in active_patterns:
                active_patterns.append(18)
            logger.info(f"Pattern 18 exempted in {symbol}: Forced active (entry_pattern=18; trailing_dip persists for mid-strength rebound hunting)")

        # Pattern 15 persistence – NEW: same logic, same power
        if pre.get('entry_pattern') == 15 and not strict_for_execution:
            pattern15 = True
            if 15 not in active_patterns:
                active_patterns.append(15)
            logger.info(f"Pattern 15 exempted in {symbol}: Forced active (entry_pattern=15; trailing_dip persists for momentum accelartion)")

        # Pattern 6 persistence – NEW: same logic, same power
        if pre.get('entry_pattern') == 6 and not strict_for_execution:
            pattern6 = True
            if 6 not in active_patterns:
                active_patterns.append(6)
            logger.info(f"Pattern 6 exempted in {symbol}: Forced active (entry_pattern=6; trailing_dip persists for momentum confirmation)")

        # Pattern 12 persistence – NEW: same logic, same power
        if pre.get('entry_pattern') == 12:
            pattern12 = True
            if 12 not in active_patterns:
                active_patterns.append(12)
            logger.info(f"Pattern 12 exempted in {symbol}: Forced active (entry_pattern=12; trailing_dip persists for momentum confirmation)")

        # Pattern 11 persistence – NEW: same logic, same power       
        if pre.get('entry_pattern') == 11:
            pattern11 = True
            if 11 not in active_patterns:
                active_patterns.append(11)
            logger.info(f"Pattern 11 exempted in {symbol}: Forced active (entry_pattern=11; trailing_dip persists for momentum confirmation)")

        # Pattern 9 persistence – NEW: same logic, same power        
        if pre.get('entry_pattern') == 9:
            pattern9 = True
            if 9 not in active_patterns:
                active_patterns.append(9)
            logger.info(f"Pattern 9 exempted in {symbol}: Forced active (entry_pattern=9; trailing_dip persists for momentum confirmation)")
               
        # Regular logging for non-persistent cases
        else:
            logger.debug(f"Pattern 22 status for {symbol}: {pattern22} (strict validity)")
            logger.debug(f"Pattern 18 status for {symbol}: {pattern18} (strict validity)")
            logger.debug(f"Pattern 15 status for {symbol}: {pattern15} (strict validity)")
            logger.debug(f"Pattern 6 status for {symbol}: {pattern6} (strict validity)")
            logger.debug(f"Pattern 12 status for {symbol}: {pattern12} (strict validity)")
            logger.debug(f"Pattern 11 status for {symbol}: {pattern11} (strict validity)")
            logger.debug(f"Pattern 9 status for {symbol}: {pattern9} (strict validity)")
            
            
        strongest_pattern_score = max((p['match_pct'] for p in patterns if p['valid'] and p['number'] in [6, 15, 9]), default=0)


        # FIXED: Initialize total_score unconditionally (neutral fallback)
        total_score = 0

        # --- PATTERN-FIRST Decision Logic (Option A: Surfer Model) ---
        # Only consider buys when we have a valid pattern (pattern-first). Tiers validate but do not fully gate.
        pre['buy_signal_ready'] = False
        base_conditions = False  # Compatibility: Set as flag for downstream flow (e.g., activation, pattern checks)
        if regular_contrib == 15:
            # ====================== ULTIMATE TOP DETECTOR VETO ======================
            if hard_no_buy or top_risk_score >= 55:
                logger.warning(f"ULTIMATE TOP DETECTOR VETO >> Buy blocked for {symbol} | "
                             f"Risk={top_risk_score}% | HardNoBuy={hard_no_buy} | Pattern={strongest_pattern_score}%")
                pre['buy_signal_ready'] = False
                base_conditions = False
                reason = "ULTIMATE TOP DETECTOR veto (Hard No-Buy or Risk >=55%)"
            else:
                # ====================== NORMAL PATTERN-FIRST LOGIC ======================
                total_score = confluence + regular_contrib
                # Adaptive threshold (strict for low ATR)
                threshold = 45 if atr_percent < 2 else 35
                logger.debug(f"Confluence threshold for {symbol}: {threshold} (ATR%: {atr_percent:.2f})")
                logger.debug(f"Pattern-first: total_score={total_score}, threshold={threshold}, confluence={confluence}, strongest_pattern={strongest_pattern_score}")

            # Primary acceptance: confluence must meet a modest minimum (min_tier_score)
            if confluence >= min_tier_score:
                # Strict pass if total_score >= threshold
                if total_score >= threshold:
                    pre['buy_signal_ready'] = True
                    base_conditions = True  # Compatibility: Gate downstream (activation, alerts)
                    reason = "pattern + tiers (strict pass)"
                else:
                    # Allow a conservative soft-pass when score is within 10 points and trend/EMA support present
                    if total_score >= (threshold - 10) and (full_ema_stack and trend_strength_proxy > 0.25):
                        pre['buy_signal_ready'] = True
                        base_conditions = True  # Compatibility: Gate downstream (activation, alerts)
                        reason = "pattern + tiers (soft pass: trend/EMA rescue)"
                    else:
                        pre['buy_signal_ready'] = False
                        base_conditions = False
                        reason = "pattern + tiers (short by points)"
            else:
                # If tiers low, allow EMA rescue for very strong patterns (>=80) with small core (>= ema_rescue_min)
                if strongest_pattern_score >= 80 and confluence >= ema_rescue_min and full_ema_stack:
                    pre['buy_signal_ready'] = True
                    base_conditions = True  # Compatibility: Gate downstream (activation, alerts)
                    reason = "very strong pattern + EMA rescue"
                else:
                    pre['buy_signal_ready'] = False
                    base_conditions = False
                    reason = "insufficient tier validation (pattern-first requires min tier score)"

            logger.info(f"Pattern-first decision for {symbol}: buy_ready={pre['buy_signal_ready']} (reason={reason}, total={total_score}, confluence={confluence}, pattern={strongest_pattern_score})")

        else:
            # No valid pattern -> do not buy (pattern-first model)
            logger.debug(f"No pattern-first trigger for {symbol} -> buy blocked. confluence={confluence}. total_score=0")
            pre['buy_signal_ready'] = False
            base_conditions = False

        # Position sizing hint (only when buy_signal_ready True)
        if pre['buy_signal_ready']:
            # Compatibility: Set matched_pattern here to trigger downstream activation
            top_number = next((p['number'] for p in patterns if p['valid'] and p['number'] in [6, 15, 9] and p['match_pct'] == strongest_pattern_score), 15)
            matched_pattern = top_number
            pre['entry_pattern'] = matched_pattern

        base_conditions = pre['buy_signal_ready']  # Light equiv: Use ready flag as gate
        regular_active = any([pattern15, pattern6, pattern9])

        any_active = pattern22 or pattern6 or pattern15 or pattern16 or pattern18 or pattern9 or pattern11 or pattern12 or (base_conditions and regular_active)

        # Specific check: If entry_pat invalid BUT others active, still keep (per your "no other" logic)
        specific_invalid = entry_pat and entry_pat not in active_patterns
        if specific_invalid and any_active:
            logger.debug(f"{symbol}: Entry pattern {entry_pat} invalid, but others active: {active_patterns}")
            any_active = True  # Keep trailing-dip (new pattern took over)

         # FIXED: Return rich data when strict_for_execution=True (for confirmation blocks)
        if strict_for_execution:
            return {
                'active': any_active,
                'tier1_active': tier1_activated,          # ← Tier 1 status
                'confluence': confluence,       # ← full tiers score
                'pattern_score': strongest_pattern_score
            }
        else:
            # Normal calls (non-strict) keep old bool behavior
            if regular_contrib > 0:
                logger.debug(f"{symbol}: Active patterns: {active_patterns}, base_confluence={confluence}, any_active={any_active}")
            else:
                logger.debug(f"{symbol}: Active patterns: {active_patterns}, base_confluence=0 (no patterns), any_active={any_active}")
            return any_active
    
    except Exception as e:
        logger.error(f"check_active_patterns error for {symbol}: {e}")
        return True if not strict_for_execution else {'active': True, 'tier1_active': False, 'confluence': 0, 'pattern_score': 0}

async def trading_loop():
    global SYMBOL, LAST_SYMBOL, pre_orders, open_orders, MAIN_ALLOCATED_USDT
    bot = Bot(TELEGRAM_TOKEN)
    global symbol_info_cache  # Ensure global access

    async def execute_sell(symbol, pre, price, quantity, order_type, reason, rsi, macd_line, middle_band, btc_ig, csi):
        global binance_client, MAIN_ALLOCATED_USDT
        if binance_client is None:
            await create_binance_client()

        try:
            # Get accurate LOT_SIZE info
            symbol_info = await binance_request("GET", "/api/v5/public/instruments")
            step_size = 0.00000001
            min_qty = 0.00000001
            min_notional = 1.0
            api_symbol = symbol.replace('/', '')

            for info in symbol_info or []:
                if info.get("instId") == api_symbol:
                    for f in info.get("filters", []):
                        if f.get("filterType") == "LOT_SIZE":
                            step_size = float(f.get("stepSize", 0.00000001))
                            min_qty = float(f.get("minSz", 0.00000001))
                            break
                    min_notional = float(info.get("minNotional", 1.0))
                    break

            # === SAFE ROUNDING FOR SELL (floor to stepSize) ===
            quantity = round_to_step_size(quantity, step_size)
            logger.debug(f"Rounded sell quantity for {symbol}: {quantity} (stepSize={step_size})")

            # Safety checks
            if quantity < min_qty:
                logger.warning(f"Sell quantity too small after rounding for {symbol}: {quantity:.8f} < {min_qty:.8f}. Skipping.")
                return None

            notional = quantity * price
            if notional < min_notional:
                logger.error(f"{reason.capitalize()} sell notional too low for {symbol}: {notional:.2f} < {min_notional:.2f}")
                return None

            # Cancel pending sell orders
            active_orders = [o for o in open_orders if o["symbol"] == symbol and o["side"] == "SELL"]
            if active_orders:
                await cancel_orders(symbol, "SELL")

            if price is None:
                logger.error(f"Cannot place {order_type} sell for {symbol}: price is None.")
                return None

            body = {
                "instId": api_symbol,
                "side": "sell",
                "ordType": order_type,
                "sz": f"{quantity:g}"
            }

            if order_type != "market":
                body["px"] = str(price)

            logger.debug(f"Placing sell order for {symbol}: sz={body['sz']} (stepSize={step_size})")

            order_response = await binance_request("POST", "/api/v5/trade/order", body=body)

            if not order_response or not order_response.get("ordId"):
                logger.error(f"Failed to place {order_type} sell for {symbol}: {order_response}")
                return None

            order = {
                "orderId": order_response["ordId"],
                "quantity": quantity,
                "price": price
            }

            # Profit calculation
            profit_percent = ((price - pre.get('entry_price', price)) / pre.get('entry_price', price) * 100) if pre.get('entry_price') else 0
            profit_usdt = quantity * (price - pre.get('entry_price', price)) if pre.get('entry_price') else 0

            message = (
                f"{reason.capitalize()} Sell\n"
                f"{symbol}: Sold {quantity:.6f} at {price:.8f}\n"
                f"Profit: {profit_percent:.2f}% (${profit_usdt:.2f})\n"
            )
            logger.info(message)
            await send_telegram_message(bot, message)

            if order_type == "market":
                filled_qty = await confirm_order_fill(order_response["ordId"], api_symbol)
                if filled_qty > 0:
                    quantity = filled_qty

                pre["amount"] -= quantity

                # ==================== ADD MAIN BOT PROFIT TO ALLOCATION ====================
                if pre.get("entry_price") and pre.get("amount", 0) <= min_qty * 0.99:
                    entry_p = pre.get('entry_price', price)
                    profit_usdt = quantity * (price - entry_p)
                    invested_usdt = quantity * entry_p
                    profit_pct = (profit_usdt / invested_usdt * 100) if invested_usdt > 0 else 0.0
                    
                    MAIN_ALLOCATED_USDT += profit_usdt
                    
                    logger.info(f"Main Bot Profit Added: +{profit_usdt:.2f} {quote_of(symbol)} | New MAIN_ALLOCATED = {MAIN_ALLOCATED_USDT:.2f}")
                    
                    # Record for compounding history (rich details)
                    await record_compound_event(
                        "main_profit", profit_usdt, "Main Bot Trade", f"{reason} sell",
                        invested=invested_usdt, profit_pct=profit_pct
                    )
                # =====================================================================

                if pre["amount"] <= min_qty * 0.99:
                    if symbol in pre_orders:
                        del pre_orders[symbol]
                    logger.info(f"Removed {symbol} from pre_orders after {reason} sell")
                await save_state()

            else:
                pre["order_count"] += 1
                pre["current_order_type"] = reason.lower()
                open_orders.append({
                    "symbol": symbol,
                    "orderId": order["orderId"],
                    "side": "SELL",
                    "price": price,
                    "quantity": quantity,
                    "type": reason.split("-")[0]
                })
                await save_state()

            return order

        except Exception as e:
            logger.error(f"Error in execute_sell for {symbol}: {str(e)}")
            return None

    async def cancel_orders(symbol, side):
        global binance_client
        if binance_client is None:
            await create_binance_client()
        for order in open_orders[:]:
            if order["symbol"] == symbol and order["side"] == side:
                try:
                    # Use body for POST cancel (matches binance_request expectation)
                    body = {"instId": symbol, "ordId": order["orderId"]}
                    await binance_request("POST", "/api/v5/trade/cancel-order", body=body)
                    open_orders.remove(order)
                    logger.info(f"Cancelled {side} order {order['orderId']} for {symbol}")
                except Exception as e:
                    logger.error(f"Error cancelling {side} order {order['orderId']} for {symbol}: {str(e)}")

    while True:
        try:
            # Check if any valid symbols exist
            symbols_to_process = list(pre_orders.keys())
            for _managed in managed_symbols():
                if _managed not in symbols_to_process:
                    symbols_to_process.append(_managed)
            if not symbols_to_process:
                logger.debug("No trading pairs set, skipping trading loop iteration")
                await asyncio.sleep(8)
                continue

            await sync_open_orders()
            for symbol in symbols_to_process:
                _lane_token = ACTIVE_SLOT.set('USDC' if quote_of(symbol) == 'USDC' else 'USDT')
                try:
                    if not symbol or not isinstance(symbol, str):
                        logger.warning(f"Skipping invalid symbol: {symbol}")
                        continue

                    if symbol not in pre_orders:
                        pre_orders[symbol] = {
                            "order_type": None,
                            "buy_target": None,
                            "primary_target": None,
                            "secondary_target": None,
                            "stop_loss": None,
                            "trailing_stop": None,
                            "trailing_distance": None,
                            "amount": 0.0,
                            "current_order_type": None,
                            "order_count": 0,
                            "last_price": None,
                            "last_base_balance": 0.0,
                            "last_base_locked": 0.0,
                            "entry_price": None,
                            "btc_ig": None,
                            "csi": None,
                            "last_status_time": 0,
                            "last_bullish": None,  # Initialize as True
                            "last_csi": 0
                        }
                    else:
                        pre = pre_orders[symbol]
                        for key, default in [
                            ("btc_ig", None),
                            ("csi", None),
                            ("last_status_time", 0),
                            ("last_csi", 0),
                            ("current_order_type", None)
                        ]:
                            if key not in pre:
                                pre[key] = default

                    # Guard clause to skip symbols with no active position and no balance
                    if pre_orders[symbol].get("order_type") is None and pre_orders[symbol].get("amount", 0) <= 0 and symbol not in managed_symbols():
                        logger.debug(f"Skipping {symbol}: No active position or balance in pre_orders")
                        continue           

                    pre = pre_orders[symbol]
                    current_price = await get_current_price(symbol)
                    if not current_price or current_price <= 0:
                        logger.error(f"Skipping {symbol}: Invalid price data ({current_price})")
                        continue
                
                    base_asset = symbol.split('/')[0]
                    account = await binance_request("GET", "/api/v5/account/balances")
                    base_balance = base_locked = quote_balance = 0.0
                    if account:
                        for asset in account:
                            if asset["ccy"].upper() == base_asset.upper():
                                base_balance = float(asset.get("availBal", "0"))
                                base_locked = float(asset.get("frozenBal", "0"))
                            if asset["ccy"].upper() == quote_of(symbol):
                                quote_balance = float(asset.get("availBal", "0"))
                        _reserved_base = reserved_base_other_lane(symbol)
                        if _reserved_base > 0:
                            base_balance = max(0.0, base_balance - _reserved_base)
                        pre["last_base_balance"] = base_balance
                        pre["last_base_locked"] = base_locked
                        if pre["order_type"] is None and pre["amount"] != base_balance:
                            logger.info(f"Syncing pre['amount'] from {pre['amount']:.8f} to base_balance {base_balance:.8f} for {symbol}")
                            pre["amount"] = base_balance
                        if pre["amount"] != base_balance and pre["order_type"] == "buy":
                            if base_balance > 0:                                          # ← keep previous amount if API returns 0
                                logger.info(f"Syncing pre['amount'] from {pre['amount']:.8f} to base_balance {base_balance:.8f} for {symbol}")
                                pre["amount"] = base_balance
                            else:
                                # Dangerous situation – API says 0 but we still have an open position
                                warning_msg = (
                                    f"⚠️ DANGER: API reports 0 {base_asset} but stored amount is {pre['amount']:.6f}\n"
                                    f"Symbol: {symbol}\n"
                                    f"Keeping previous amount to protect position!"
                                )
                                logger.warning(warning_msg)
                                bot = Bot(TELEGRAM_TOKEN)
                                await send_telegram_message(bot, warning_msg)

                        if pre["amount"] > base_balance and base_balance > 0:
                            logger.warning(f"Stored quantity {pre['amount']:.8f} exceeds available {base_balance:.8f} for {symbol}, adjusting")
                            pre["amount"] = base_balance
                        await save_state()

                    else:
                        logger.warning(f"Using cached balance for {symbol}")
                        base_balance = pre.get("last_base_balance", 0.0)
                        base_locked = pre.get("last_base_locked", 0.0)
                        quote_balance = 1000.0

                    if symbol not in symbol_info_cache:
                        symbol_info_list = await binance_request("GET", "/api/v5/public/instruments")
                        if symbol_info_list:
                            for info in symbol_info_list:
                                if info["instId"] == symbol:
                                    symbol_info_cache[symbol] = info
                                    break
                    symbol_info = symbol_info_cache.get(symbol)

                    # Safe extraction with fallbacks
                    if symbol_info:
                        min_sz = symbol_info.get("minSz")
                        min_notional_val = symbol_info.get("minNotional") 
                        lot_sz = symbol_info.get("lotSz")
                    
                        min_qty = float(min_sz) if min_sz and min_sz != "" else 0.00000001
                        min_notional = float(min_notional_val) if min_notional_val and min_notional_val != "" else 1.0
                        step_size = float(lot_sz) if lot_sz and lot_sz != "" else 0.00000001
                    else:
                        min_qty = 0.00000001
                        min_notional = 1.0
                        step_size = 0.00000001

                    # Early check for insufficient quote balance before buy logic
                    if pre["order_type"] is None and quote_balance < min_notional:
                        logger.debug(f"Skipping buy for {symbol}: quote balance {quote_balance:.2f} below min_notional {min_notional:.2f}")
                        # Optionally remove symbol from pre_orders to prevent re-processing
                        if symbol in pre_orders and pre["amount"] <= min_qty:
                            del pre_orders[symbol]
                            logger.info(f"Removed {symbol} from pre_orders due to insufficient quote balance")
                            await save_state()

                        continue

                    indicators = await get_cached_indicators(symbol, current_price)
                    # Always update OBI snapshot for Live bot
                    if indicators:
                        await save_obi_snapshot(indicators, current_price)
                    
                    if indicators is None or any(v is None for v in [indicators["ema_9"], indicators["ema_21"], indicators["rsi"], indicators["atr"]]):
                        logger.error(f"Skipping {symbol}: Failed to fetch valid indicators")
                        ema_status = "N/A"
                        rsi_str = "N/A"
                        csi_str = f"{pre.get('csi', 'N/A'):.2f}" if pre.get('csi') is not None else "N/A"
                        await send_telegram_message(bot, f"Trading Loop Error\nError: Invalid indicators\nEMA: {ema_status}, RSI: {rsi_str}, CSI: {csi_str}")
                        continue

                    closes = indicators["closes"]
                    ema_9 = indicators["ema_9"]
                    ema_21 = indicators["ema_21"]
                    ema_50 = indicators["ema_50"]
                    volatility_index = indicators["volatility_index"]
                    rsi = indicators["rsi"]
                    high = indicators["high"]
                    low = indicators["low"]
                    fib_levels = indicators["fib_levels"]
                    support = indicators["support"]
                    volume_spike = indicators["volume_spike"]
                    atr = indicators["atr"]
                    macd_line = indicators["macd_line"]
                    signal_line = indicators["signal_line"]
                    histogram = indicators["histogram"]
                    middle_band = indicators["middle_band"]
                    atr_percent = (atr / current_price) * 100 if atr and current_price else 0

                    fib_extensions = {}
                    if fib_levels and high and low:
                        fib_range = high - low
                        fib_extensions["100%"] = high
                        fib_extensions["161.8%"] = high + fib_range * 0.618
                        fib_extensions["261.8%"] = high + fib_range * 1.618

                    # ==================== IMPROVED BTC_IG (Balanced + Softened) ====================
                    btc_symbol = "BTC/USDT"
                    btc_indicators = await get_cached_indicators(btc_symbol, await get_current_price(btc_symbol))
                    btc_ig = "neutral"  # Safe default

                    if btc_indicators is not None and all(
                        btc_indicators.get(key) is not None 
                        for key in ["closes", "ema_9", "ema_21", "ema_50", "rsi", "atr", 
                                   "macd_line", "signal_line", "histogram", "middle_band", 
                                   "vwap", "fib_levels", "support"]
                    ):
                        btc_closes = btc_indicators["closes"]
                        btc_ema_9 = btc_indicators["ema_9"]
                        btc_ema_21 = btc_indicators["ema_21"]
                        btc_ema_50 = btc_indicators["ema_50"]
                        btc_rsi = btc_indicators["rsi"]
                        btc_atr = btc_indicators["atr"]
                        btc_macd_line = btc_indicators["macd_line"]
                        btc_signal_line = btc_indicators["signal_line"]
                        btc_histogram = btc_indicators["histogram"]
                        btc_middle_band = btc_indicators["middle_band"]
                        btc_vwap = btc_indicators["vwap"]
                        btc_fib_levels = btc_indicators["fib_levels"]
                        btc_support = btc_indicators["support"]

                        # Extra indicators
                        btc_bb_width = btc_indicators.get("bb_width", 0.02)
                        btc_volume_spike = btc_indicators.get("volume_spike", False)
                        btc_atr_percent = (btc_atr / btc_closes[-1] * 100) if btc_atr and len(btc_closes) > 0 and btc_closes[-1] > 0 else 0.0
                        btc_volatility_index = btc_indicators.get("volatility_index", 50.0)
                        btc_cvd = btc_indicators.get("cvd", 0.0)

                        if isinstance(btc_closes, np.ndarray) and len(btc_closes) > 0:
                            btc_current_price = float(btc_closes[-1])
                            btc_fib_618 = btc_fib_levels.get("61.8%", btc_current_price) if btc_fib_levels else btc_current_price

                            # ---------- CORE CONDITIONS (Balanced) ----------
                            core_bullish = (
                                btc_ema_9 > btc_ema_21 > btc_ema_50 and
                                42 < btc_rsi < 72 and
                                btc_macd_line > btc_signal_line and btc_histogram > 0 and
                                btc_current_price > max(btc_middle_band, btc_vwap, btc_support) * 0.997 and
                                btc_current_price > btc_fib_618 * 0.985
                            )

                            core_bearish = (
                                btc_ema_9 < btc_ema_21 < btc_ema_50 and
                                btc_rsi < 45 and
                                btc_macd_line < btc_signal_line and btc_histogram < 0 and
                                btc_current_price < min(btc_middle_band, btc_vwap, btc_support) * 1.003 and
                                btc_current_price < btc_fib_618 * 1.015
                            )

                            # ---------- CONFLUENCE (Cleaner & Fairer) ----------
                            bull_confluence = 0
                            bear_confluence = 0

                            # Volume & Volatility
                            if btc_volume_spike:
                                bull_confluence += 1
                            else:
                                bear_confluence += 0.5

                            if btc_bb_width > 0.022:
                                bull_confluence += 1
                            elif btc_bb_width < 0.013:
                                bear_confluence += 1

                            if btc_atr_percent > 0.9:
                                bull_confluence += 1
                            elif btc_atr_percent < 0.45:
                                bear_confluence += 1

                            if btc_volatility_index > 55:
                                bull_confluence += 1
                            elif btc_volatility_index < 35:
                                bear_confluence += 1

                            # Order flow
                            if btc_cvd > 0:
                                bull_confluence += 1
                            elif btc_cvd < 0:
                                bear_confluence += 1

                            # Fib proximity (mild)
                            if abs(btc_current_price - btc_fib_618) / btc_fib_618 < 0.015:
                                if btc_current_price > btc_fib_618:
                                    bull_confluence += 0.5
                                else:
                                    bear_confluence += 0.5

                            # ---------- FINAL DECISION (Softened) ----------
                            btc_bullish = core_bullish and bull_confluence >= 2.5
                            btc_bearish = core_bearish and bear_confluence >= 2.5

                            ema_stack_bullish = btc_ema_9 > btc_ema_21 > btc_ema_50

                            if btc_bullish and not btc_bearish:
                                btc_ig = "bullish"
                            elif btc_bearish and not btc_bullish:
                                btc_ig = "bearish"
                            else:
                                # Softened mixed-case logic
                                if bull_confluence - bear_confluence >= 1.5:
                                    btc_ig = "bullish"
                                elif bear_confluence - bull_confluence >= 2.0 and not ema_stack_bullish:
                                    # Only go bearish in mixed case if bear confluence is clearly stronger
                                    # AND the EMA stack is no longer bullish
                                    btc_ig = "bearish"
                                else:
                                    btc_ig = "neutral"

                            # Logging
                            ema_stack = (
                                "Bullish" if ema_stack_bullish else
                                "Bearish" if btc_ema_9 < btc_ema_21 < btc_ema_50 else "Neutral"
                            )
                            logger.info(
                                f"BTC Indicators for {btc_symbol}: EMA9/21/50: {ema_stack} "
                                f"(EMA50: {'Above' if btc_current_price > btc_ema_50 else 'Below'}), "
                                f"RSI={btc_rsi:.2f}, Fib61.8={btc_fib_618:.2f}, Support={btc_support:.2f}, "
                                f"ATR={btc_atr_percent:.2f}%, MACD={btc_macd_line:.6f}, Signal={btc_signal_line:.6f}, "
                                f"Histogram={btc_histogram:.6f}, Price={btc_current_price:.2f}, "
                                f"BB_Middle={btc_middle_band:.2f}, VWAP={btc_vwap:.2f}, BB_Width={btc_bb_width:.3f}, "
                                f"Vol_Spike={btc_volume_spike}, Vol_Index={btc_volatility_index:.1f}, CVD={btc_cvd:.0f}, "
                                f"Bull_Conf={bull_confluence:.1f}, Bear_Conf={bear_confluence:.1f}, "
                                f"BTC_IG={btc_ig}"
                            )
                        else:
                            logger.error(f"Invalid btc_closes for {btc_symbol}")
                    else:
                        logger.warning(f"Skipping BTC indicators for {btc_symbol}: Invalid or missing indicators → BTC_IG=neutral")

                    pre["btc_ig"] = btc_ig
                    await save_state()
                    # ==================== END IMPROVED BTC_IG ====================

                    if any(v is None for v in [ema_9, ema_21, rsi, atr, fib_levels, ema_50, volatility_index]):
                        logger.error(f"Critical indicator failure for {symbol}: ema_9={ema_9}, ema_21={ema_21}, rsi={rsi}, atr={atr}, fib_levels={fib_levels}, ema_50={ema_50}, volatility_index={volatility_index}")
                        continue

                    support_fallback = np.min(closes[-50:]) if support is None else support
                    if support is None:
                        logger.warning(f"Support is None for {symbol}, using lowest low ({support_fallback:.8f}) as fallback")

                    csi = None
                    ema_score = 1 if ema_9 > ema_21 else -1 if ema_9 < ema_21 else 0 if ema_9 and ema_21 else 0
                    ema50_score = 1 if current_price > ema_50 else -1 if current_price < ema_50 else 0 if ema_50 else 0
                    rsi_score = 1 if rsi > 50 else -1 if rsi < 30 else 0 if rsi else 0
                    macd_score = 1 if macd_line > signal_line else -1 if macd_line < signal_line else 0 if macd_line and signal_line else 0
                    bb_score = 1 if middle_band and current_price > middle_band else -1 if middle_band and current_price < middle_band else 0
                    atr_score = 1 if atr_percent > 1.5 else -1 if atr_percent < 0.5 else 0 if atr_percent else 0
                    fib_61_8 = fib_levels.get("61.8%")
                    fib_score = (1 if fib_61_8 and abs(current_price - fib_61_8) / fib_61_8 < 0.02 and current_price >= fib_61_8
                                else -1 if fib_61_8 and abs(current_price - fib_61_8) / fib_61_8 < 0.02 and current_price < fib_61_8
                                else 0)
                    # Updated btc_ig_score handling (now supports neutral as 0)
                    if btc_ig == "bullish":
                        btc_ig_score = 1.0
                    elif btc_ig == "bearish":
                        btc_ig_score = -1.0
                    else:  # neutral or None
                        btc_ig_score = 0.0
                
                    # Compute TA composite (Technical Analysis part) - your original weights
                    ta_composite = (0.15 * ema_score) + (0.15 * ema50_score) + (0.20 * rsi_score) + \
                                   (0.15 * macd_score) + (0.15 * bb_score) + (0.10 * atr_score) + \
                                   (0.05 * fib_score) + (0.05 * btc_ig_score)
                
                    # Fetch enhanced sentiment (VADER + keyword bias + live Fear & Greed)
                    sent = await calculate_sentiment(symbol)
                    news_score = sent["final_score"]
                    csi = max(-1.0, min(1.0, news_score))

                    macro_tag = sent.get("tag") or ""
                    bear_now = (csi <= -0.42) or (macro_tag in ("HOT_MACRO", "HAWKISH", "CASCADE") and csi <= -0.28)
                    if bear_now:
                        pre["csi_bear_until"] = time.time() + 75 * 60
                    csi_dynamic_bear = bear_now or time.time() < float(pre.get("csi_bear_until") or 0)

                    pre["csi"] = csi
                    pre["news_sentiment"] = news_score
                    pre["csi_shock"] = sent.get("shock", 0.0)
                    pre["csi_tag"] = macro_tag
                    pre["csi_dynamic_bear"] = csi_dynamic_bear
                    if not csi_dynamic_bear:
                        pre["csi_block_logged"] = False
                
                    logger.info(f"CSI for {symbol}: EMA9/21={ema_score}, EMA50={ema50_score}, RSI={rsi_score}, "
                                f"MACD={macd_score}, BB={bb_score}, ATR={atr_score}, Fib={fib_score}, "
                                f"BTC_IG={btc_ig_score}, News={news_score:.3f}, TA_Comp={ta_composite:.3f}, Total={csi:.3f}")
                
                    if ema_9 is None or ema_21 is None or ema_50 is None or rsi is None or macd_line is None or signal_line is None or middle_band is None:
                        logger.warning(f"Skipping bullish check for {symbol}: Missing indicators (ema_9={ema_9}, ema_21={ema_21}, ema_50={ema_50}, rsi={rsi}, macd_line={macd_line}, signal_line={signal_line}, middle_band={middle_band})")
                        bullish = False
                    else:
                        bullish = (ema_9 > ema_21 and current_price > ema_50 and rsi > 50 and macd_line > signal_line and current_price > middle_band)

                    momentum_factor = (
                        (rsi / 50 if rsi and rsi < 50 else rsi / 100 if rsi else 0) +  
                        (histogram / abs(max(histogram, 1e-6)) if histogram else 0) +
                        (1 if volume_spike else 0)) / 4

                    # Compute all variables for logger (before the info line)
                    prev_close = indicators["closes"][-2] if len(indicators.get("closes", [])) >= 2 else indicators.get("closes", [])[-1] if indicators.get("closes") else None
                    prev_histogram = indicators.get('histogram', 0) - 0.1 if indicators.get('histogram') is not None else None  # Delta fallback
                    rsi_prev = indicators.get('rsi_values', [])[-2] if len(indicators.get('rsi_values', [])) >= 2 else None  # From rsi_values series
                    rsi_low = min(indicators.get('rsi_values', [indicators.get('rsi', 50)]), default=50) if indicators.get('rsi_values') else indicators.get('rsi', 50)
                    price_low = min(indicators['closes'][-5:]) if len(indicators['closes']) >= 5 else current_price
                    fib_61_8 = indicators.get('fib_levels', {}).get('61.8%', None) if indicators.get('fib_levels') else None
                    recent_high = indicators.get('high', None)  # Recent high
                    avg_volume = np.mean(indicators.get('volumes', [0])[-10:]) if len(indicators.get('volumes', [])) >= 10 else indicators.get('volumes', [0])[-1] if indicators.get('volumes') else 0
                    bb_width = indicators.get('bb_width', 0.02)
                    support = indicators.get('support', None)
                    volume_spike = indicators.get('volume_spike', None)
                    histogram = indicators.get('histogram', None)
                    macd_line = indicators.get('macd_line', None)
                    signal_line = indicators.get('signal_line', None)
                    atr = indicators.get('atr', current_price * 0.01)
                    prev_atr = indicators.get('prev_atr', atr * 0.9)
                    atr_percent = (indicators.get('atr', 0) / current_price * 100) if current_price > 0 else 0
                    prev_atr_percent = (prev_atr / current_price * 100) if prev_atr is not None and current_price > 0 else 0
                    btc_ig = pre.get('btc_ig', 'N/A')
                    csi = pre.get('csi', None)
                    volatility_index = indicators.get('volatility_index', None)

                    # NEW: CVD, OBI, Funding vars
                    cvd = indicators.get('cvd', 0.0)
                    cvd_signal = indicators.get('cvd_signal', 'neutral')
                    obi = indicators.get('obi', 0.0)
                    obi_signal = indicators.get('obi_signal', 'neutral')
                    prev_cvd = indicators.get('cvd_values', [cvd])[-2] if len(indicators.get('cvd_values', [cvd])) >= 2 else cvd * 0.9  # Safe fallback for change_pct
                    # OBI previous value - Uses history from the fixed cache
                    obi_values = indicators.get('obi_values', [obi])
                    prev_obi = obi_values[-2] if len(obi_values) >= 2 else obi
                
                     # Logger statement for debugging (safe f-string, all defined)
                    logger.info(
                        f"Buy check for {symbol}: "
                        f"current_price={current_price:.6f}, "
                        f"ema_5={'N/A' if indicators.get('ema_5') is None else f'{indicators['ema_5']:.6f}'}, "
                        f"ema_9={'N/A' if indicators.get('ema_9') is None else f'{indicators['ema_9']:.6f}'}, "
                        f"ema_13={'N/A' if indicators.get('ema_13') is None else f'{indicators['ema_13']:.6f}'}, "
                        f"ema_21={'N/A' if indicators.get('ema_21') is None else f'{indicators['ema_21']:.6f}'}, "
                        f"ema_50={'N/A' if indicators.get('ema_50') is None else f'{indicators['ema_50']:.6f}'}, "
                        f"ema_200={'N/A' if indicators.get('ema_200') is None else f'{indicators['ema_200']:.6f}'}, "
                        f"rsi={'N/A' if indicators.get('rsi') is None else f'{indicators['rsi']:.2f}'}, "
                        f"rsi_prev={'N/A' if rsi_prev is None else f'{rsi_prev:.2f}'}, "
                        f"rsi_low={'N/A' if rsi_low is None else f'{rsi_low:.2f}'}, "
                        f"price_low={'N/A' if price_low is None else f'{price_low:.6f}'}, "
                        f"macd_line={'N/A' if macd_line is None else f'{macd_line:.6f}'}, "
                        f"signal_line={'N/A' if signal_line is None else f'{signal_line:.6f}'}, "
                        f"histogram={'N/A' if histogram is None else f'{histogram:.6f}'}, "
                        f"prev_histogram={'N/A' if prev_histogram is None else f'{prev_histogram:.6f}'}, "
                        f"middle_band={'N/A' if indicators.get('middle_band') is None else f'{indicators['middle_band']:.6f}'}, "
                        f"atr={'N/A' if indicators.get('atr') is None else f'{indicators['atr']:.6f}'}, "
                        f"prev_atr={'N/A' if indicators.get('prev_atr') is None else f'{indicators['prev_atr']:.6f}'}, "
                        f"atr_percent={atr_percent:.2f}, "
                        f"prev_atr_percent={prev_atr_percent:.2f}, "
                        f"fib_61_8={'N/A' if fib_61_8 is None else f'{fib_61_8:.6f}'}, "
                        f"vwap={'N/A' if indicators.get('vwap') is None else f'{indicators['vwap']:.6f}'}, "
                        f"csi={'N/A' if csi is None else f'{csi:.2f}'}, "
                        f"btc_ig={btc_ig}, "
                        f"volatility_index={'N/A' if volatility_index is None else f'{volatility_index:.2f}'}, "
                        f"cvd={'N/A' if cvd is None else f'{cvd:.2f}'} ({cvd_signal}), "
                        f"prev_cvd={'N/A' if prev_cvd is None else f'{prev_cvd:.2f}'}, "
                        f"obi={'N/A' if obi is None else f'{obi:.2f}'} ({obi_signal}), "
                        f"prev_obi={'N/A' if prev_obi is None else f'{prev_obi:.2f}'}, "
                        f"recent_high={'N/A' if recent_high is None else f'{recent_high:.6f}'}, "
                        f"high={'N/A' if indicators.get('high') is None else f'{indicators['high']:.6f}'}, "
                        f"low={'N/A' if indicators.get('low') is None else f'{indicators['low']:.6f}'}, "
                        f"support={'N/A' if support is None else f'{support:.6f}'}, "
                        f"volume={'N/A' if indicators.get('volumes') is None or len(indicators['volumes']) == 0 else f'{indicators['volumes'][-1]:.2f}'}, "
                        f"volume_spike={'N/A' if volume_spike is None else f'{volume_spike}'}, "
                        f"avg_volume={'N/A' if avg_volume == 0 else f'{avg_volume:.2f}'}, "
                        f"bb_width={'N/A' if indicators.get('bb_width') is None else f'{indicators['bb_width']:.4f}'}, "
                        f"prev_close={'N/A' if prev_close is None else f'{prev_close:.6f}'}"
                    )

                

                    # Eval-aligned helpers (arrays for prev/current) - Safe computation
                    volumes = indicators.get('volumes', np.array([current_price]))  # Fallback to current if None
                    current_volume = volumes[-1] if len(volumes) > 0 else current_price
                    avg_volume = np.mean(volumes[-10:]) if len(volumes) >= 10 else current_volume
                    avg_volume_20 = np.mean(volumes[-20:]) if len(volumes) >= 20 else avg_volume
                    prev_volume = volumes[-2] if len(volumes) >= 2 else current_volume * 0.9

                    rsi_values = indicators.get('rsi_values', [indicators.get('rsi', 50)])
                    rsi = indicators.get('rsi', 50)
                    rsi_prev = rsi_values[-2] if len(rsi_values) >= 2 else rsi - 1  # Safe: -1 delta fallback

                    btc_ig = pre_orders.get(symbol, {}).get("btc_ig", "N/A")

                    macd_values = indicators.get('macd_values', [indicators.get('macd_line', 0)])
                    macd_line = indicators.get('macd_line', 0)
                    prev_macd = macd_values[-2] if len(macd_values) >= 2 else macd_line * 0.9
                    fib_61_8 = indicators.get('fib_levels', {}).get('61.8%', None) if indicators.get('fib_levels') else None

                    histogram_values = indicators.get('histogram_values', [indicators.get('histogram', 0)])
                    histogram = indicators.get('histogram', 0)
                    prev_histogram = histogram_values[-2] if len(histogram_values) >= 2 else histogram - 0.1  # Delta fallback (bottoming trend)

                    signal_values = indicators.get('signal_values', [indicators.get('signal_line', 0)])
                    signal_line = indicators.get('signal_line', 0)
                    prev_signal = signal_values[-2] if len(signal_values) >= 2 else signal_line * 0.9
                    price_low = min(indicators['closes'][-5:]) if len(indicators['closes']) >= 5 else current_price

                    highs = indicators.get('highs', np.array([current_price]))
                    prev_high = highs[-5:].max() if len(highs) >= 5 else current_price

                    closes = indicators.get('closes', np.array([current_price]))
                    prev_close = closes[-2] if len(closes) >= 2 else current_price * 0.99  # Safe fallback

                    bb_width_proxy = indicators.get('bb_width', 0.02)
                    atr = indicators.get('atr', current_price * 0.01)
                    prev_atr = indicators.get('prev_atr', atr * 0.9)
                    atr_percent = (atr / current_price * 100) if current_price > 0 else 0
                    fib_levels = indicators.get('fib_levels', {})
                    ema_5 = indicators.get('ema_5', current_price)
                    ema_9 = indicators.get('ema_9', current_price)
                    ema_13 = indicators.get('ema_13', current_price)
                    ema_21 = indicators.get('ema_21', current_price)
                    ema_50 = indicators.get('ema_50', current_price)
                    vwap = indicators.get('vwap', current_price)
                    bb_middle = indicators.get('middle_band', current_price)
                    bb_upper = bb_middle + (bb_width_proxy * bb_middle) if bb_middle and bb_width_proxy else current_price * 1.02
                    bb_lower = bb_middle - (bb_width_proxy * bb_middle) if bb_middle and bb_width_proxy else current_price * 0.98
                    support = indicators.get('support', current_price)
                    csi = pre.get('csi', 0)  # From pre, like eval

                    # NEW: CVD vars (net buy/sell pressure) - Verified: Safe array fallback, prev=0.9x for continuity
                    cvd_values = indicators.get('cvd_values', [indicators.get('cvd', 0)])
                    cvd = indicators.get('cvd', 0)
                    prev_cvd = cvd_values[-2] if len(cvd_values) >= 2 else cvd * 0.9  # Safe fallback
                    cvd_change_pct = ((cvd - prev_cvd) / abs(prev_cvd + 1e-6)) * 100 if prev_cvd != 0 else 0  # % change; avoids div0

                    # NEW: OBI vars (bid/ask imbalance)
                    obi_values = indicators.get('obi_values', [indicators.get('obi', 0.0)])
                    obi = indicators.get('obi', 0.0)

                    # Better fallback logic
                    if len(obi_values) >= 2:
                        prev_obi = obi_values[-2]
                    else:
                        prev_obi = obi_values[0] if obi_values else obi

                    obi_imbalance = obi - prev_obi
                
                    # ---------- NEW SAFE HIGH-PRICE FILTER VARIABLES ----------
                    recent_high_5 = max(highs[-5:]) if len(highs) >= 5 else current_price
                    recent_high_10 = max(highs[-10:]) if len(highs) >= 10 else recent_high_5

                    price_extension_pct = ((current_price - ema_21) / ema_21 * 100) if ema_21 > 0 else 0
                    distance_from_low_pct = ((current_price - price_low) / price_low * 100) if price_low > 0 else 0
                    near_recent_top = current_price >= recent_high_5 * 0.996
                    overextended_price = current_price > ema_21 * 1.018

                    # ==========================================================
                    # ULTIMATE TOP DETECTOR + ATR BEAST vNEXT + PATTERNS
                    # Final Consolidated Block - Cleaned & Improved Version
                    # ==========================================================

                    # -----------------------------
                    # SAFE DEFAULTS
                    # -----------------------------
                    top_risk_score = 0.0
                    top_detector_triggered = False
                    top_detector_level = "LOW"
                    hard_no_buy = False

                    logger.debug("=== ULTIMATE TOP DETECTOR ANALYSIS ===")

                    # ==========================================================
                    # 1. ULTIMATE TOP DETECTOR
                    # ==========================================================

                    # ---------------------------------------------------------- 
                    # 1. Price stretched near highs
                    # ----------------------------------------------------------
                    if near_recent_top:
                        top_risk_score += 18
                        logger.debug("TOP +18 | Near recent top")

                    if current_price >= recent_high_10 * 0.998:
                        top_risk_score += 12
                        logger.debug("TOP +12 | Near 10-candle high")

                    if price_extension_pct > 1.8:
                        top_risk_score += 12
                        logger.debug(f"TOP +12 | Extended above EMA21 ({price_extension_pct:.2f}%)")

                    if price_extension_pct > 3.0:
                        top_risk_score += 10
                        logger.debug(f"TOP +10 | Extreme extension ({price_extension_pct:.2f}%)")

                    # ---------------------------------------------------------- 
                    # 2. RSI exhaustion
                    # ----------------------------------------------------------
                    if rsi > 72:
                        top_risk_score += 15
                        logger.debug(f"TOP +15 | RSI hot ({rsi:.2f})")

                    if rsi > 76:
                        top_risk_score += 10
                        logger.debug(f"TOP +10 | RSI overheated ({rsi:.2f})")

                    if rsi < rsi_prev and rsi > 70:
                        top_risk_score += 10
                        logger.debug("TOP +10 | RSI rolling over from hot zone")

                    # ---------------------------------------------------------- 
                    # 3. Volume weakness / breakout failure
                    # ----------------------------------------------------------
                    if near_recent_top and current_volume < avg_volume * 0.85:
                        top_risk_score += 15
                        logger.debug("TOP +15 | Near top with weak volume")

                    if current_volume < prev_volume * 0.80 and current_price >= prev_close:
                        top_risk_score += 8
                        logger.debug("TOP +8 | Price up but volume fading")

                    # ---------------------------------------------------------- 
                    # 4. Orderflow exhaustion
                    # ----------------------------------------------------------
                    if obi < 0:
                        top_risk_score += 10
                        logger.debug("TOP +10 | Negative OBI")

                    if obi < prev_obi and current_price >= prev_close:
                        top_risk_score += 8
                        logger.debug("TOP +8 | OBI fading while price stable/up")

                    if cvd < prev_cvd and current_price >= prev_close:
                        top_risk_score += 10
                        logger.debug("TOP +10 | CVD selling into strength")

                    if cvd_change_pct < -5:
                        top_risk_score += 10
                        logger.debug(f"TOP +10 | CVD deterioration ({cvd_change_pct:.2f}%)")

                    # ---------------------------------------------------------- 
                    # 5. Momentum stall
                    # ----------------------------------------------------------
                    if histogram < prev_histogram and histogram > 0:
                        top_risk_score += 12
                        logger.debug("TOP +12 | Bull momentum slowing")

                    if macd_line < signal_line and macd_line > 0:
                        top_risk_score += 10
                        logger.debug("TOP +10 | MACD bearish cross above zero")

                    # ---------------------------------------------------------- 
                    # 6. Low ATR squeeze near highs (classic trap)
                    # ----------------------------------------------------------
                    if atr_percent < 0.55 and near_recent_top:
                        top_risk_score += 10
                        logger.debug("TOP +10 | Low ATR squeeze near highs")

                    if bb_width_proxy < 0.014 and near_recent_top:
                        top_risk_score += 8
                        logger.debug("TOP +8 | Band compression near highs")

                    # ---------------------------------------------------------- 
                    # 7. Resistance rejection micro signal
                    # ----------------------------------------------------------
                    if current_price < prev_close and near_recent_top:
                        top_risk_score += 10
                        logger.debug("TOP +10 | Rejection candle near highs")

                    # ---------------------------------------------------------- 
                    # Clamp & Final Top Detector Result
                    # ----------------------------------------------------------
                    top_risk_score = max(0.0, min(100.0, top_risk_score))
                    top_risk_pct = round(top_risk_score)

                    if top_risk_score >= 75:
                        top_detector_level = "EXTREME"
                        top_detector_triggered = True
                    elif top_risk_score >= 55:
                        top_detector_level = "HIGH"
                        top_detector_triggered = True
                    elif top_risk_score >= 35:
                        top_detector_level = "MEDIUM"
                    else:
                        top_detector_level = "LOW"

                    # ---------------------------------------------------------- 
                    # HARD NO-BUY CONDITIONS (Nuclear Protection)
                    # ----------------------------------------------------------
                    if (rsi > 73 and near_recent_top and current_volume < avg_volume * 0.90):
                        hard_no_buy = True
                        logger.debug("TOP HARD BLOCK: RSI hot + near top + weak volume")

                    if (near_recent_top and obi < 0 and cvd < prev_cvd):
                        hard_no_buy = True
                        logger.debug("TOP HARD BLOCK: Near top + negative flow")

                    if (price_extension_pct > 3.0 and rsi > 75):
                        hard_no_buy = True
                        logger.debug("TOP HARD BLOCK: Extreme extension + RSI mania")

                    # Final Top Detector Summary
                    logger.debug("=== ULTIMATE TOP DETECTOR FINAL RESULT ===")
                    logger.debug(f"• Risk Score : {top_risk_pct}%")
                    logger.debug(f"• Level      : {top_detector_level}")
                    logger.debug(f"• Triggered  : {top_detector_triggered}")
                    logger.debug(f"• Hard No-Buy: {hard_no_buy}")


                    # ==========================================================
                    # ATR BEAST vNEXT - IMPROVED & CLEANED
                    # Smart ATR Threshold + Confluence Engine + Regime Detection
                    # ==========================================================

                    logger.debug("=== ATR BEAST vNEXT ANALYSIS START ===")

                    # -----------------------------
                    # CORE HELPERS & REGIME ENGINE
                    # -----------------------------
                    atr_threshold = 0.30
                    volume_soft_mult = 0.60
                    basic_bypass_min = 5
                    obi_relax = -0.05
                    min_tier_score = 15
                    ema_rescue_min = 10

                    # Trend & Pressure proxies
                    trend_strength_proxy = abs((ema_9 - ema_21) / max(abs(ema_21), 1e-9)) * 100
                    pressure_strength_proxy = (abs(cvd_change_pct) + abs(obi_imbalance) * 100) / 2

                    # Divergence & Recovery signals
                    cvd_divergence = (cvd > prev_cvd) and (current_price < prev_close)
                    obi_recovery = (prev_obi < 0 and obi > 0)
                    rsi_divergence = (rsi > rsi_prev and current_price < prev_close)
                    macd_divergence = (macd_line > prev_macd and current_price < prev_close)

                    # --- Market Regime Detection ---
                    regime = "neutral"
                    try:
                        full_ema_stack = (ema_5 > ema_9 > ema_13 > ema_21 and ema_21 > ema_50 * 0.995)
                    except:
                        full_ema_stack = False

                    if full_ema_stack and rsi > 52 and macd_line >= signal_line:
                        regime = "trend_bull"
                    elif current_price < ema_21 and rsi < 42 and macd_line < signal_line:
                        regime = "trend_bear"
                    elif bb_width_proxy < 0.018 and atr_percent < 1.0:
                        regime = "compression"
                    elif rsi < 30 and histogram > prev_histogram:
                        regime = "reversal_up"
                    elif rsi > 72 and histogram < prev_histogram:
                        regime = "reversal_down"

                    logger.debug(f"=== MARKET REGIME DETECTED: {regime} ===")
                    logger.debug(f"full_ema_stack={full_ema_stack}, trend_strength={trend_strength_proxy:.2f}%, pressure={pressure_strength_proxy:.2f}")

                    # -----------------------------
                    # SMART ATR THRESHOLD ENGINE
                    # -----------------------------
                    # Base threshold based on volatility
                    if atr_percent > 6.0:
                        atr_threshold = 2.5
                    elif atr_percent < 1.0:
                        atr_threshold = 1.2
                    else:
                        atr_threshold = 0.30

                    # Regime adjustments
                    if regime == "trend_bull":
                        atr_threshold *= 0.72
                    elif regime == "trend_bear":
                        atr_threshold *= 0.95
                    elif regime == "compression":
                        atr_threshold *= 1.45
                    elif regime == "reversal_up":
                        atr_threshold *= 0.82

                    # Additional modifiers
                    if trend_strength_proxy > 0.35:
                        atr_threshold *= 0.92
                    if pressure_strength_proxy > 4:
                        atr_threshold *= 0.90

                    high_vol = current_volume > avg_volume * 1.30
                    if high_vol:
                        atr_threshold *= 0.75

                    # Final clamping
                    atr_threshold = max(0.20, min(2.80, atr_threshold))

                    logger.debug(f"ATR Threshold Engine >> atr_percent={atr_percent:.2f} | regime={regime} | final_atr_threshold={atr_threshold:.3f}")

                    # -----------------------------
                    # CONFLUENCE ENGINE (Cleaned & Improved)
                    # -----------------------------
                    confluence = 0          # Single unified confluence (replaces core + score split)
                    atr_bypass_tier = 0
                    atr_bypass_active = False

                    # Fast Reversal Detection
                    fast_reversal_core = (
                        (obi > 0.10 and obi_recovery) and
                        (cvd_change_pct > 5) and
                        (rsi > 50 or rsi_divergence)
                    )
                    fast_reversal_boosters = 0
                    if fast_reversal_core:
                        if ema_5 > ema_9:
                            fast_reversal_boosters += 1
                        if histogram > prev_histogram * 1.10:
                            fast_reversal_boosters += 1

                    # Basic Bypass Conditions (Foundation)
                    basic_bypass_conditions = {
                        'ema_alignment': ema_9 > ema_21 > ema_50 * 0.99,
                        'macd_above_signal': (macd_line > signal_line * 0.98) or (histogram > prev_histogram * 0.90),
                        'histogram_rising': histogram > prev_histogram * 0.90,
                        'rsi_neutral': 45 < rsi < 75,
                        'price_above_support': current_price > support * 1.005 if support else (support_fallback := current_price * 0.98),
                        'volume_sufficient': current_volume > avg_volume * volume_soft_mult,
                        'csi_positive': pre.get('csi', 0) > 0.0,
                        'fast_reversal_core': fast_reversal_core,
                    }

                    basic_bypass_met_count = sum(basic_bypass_conditions.values())

                    # === Detailed Logging ===
                    logger.debug("=== ATR CONFLUENCE ANALYSIS ===")
                    logger.debug(f"Basic Bypass Conditions Met: {basic_bypass_met_count}/{len(basic_bypass_conditions)}")

                    cond_desc = {
                        'ema_alignment': f"EMA Alignment: ema9({ema_9:.6f}) > ema21({ema_21:.6f}) > ema50({ema_50:.6f})*0.99",
                        'macd_above_signal': f"MACD Confirm: macd({macd_line:.6f}) > signal({signal_line:.6f}) or hist rising",
                        'histogram_rising': f"Histogram Rising: {histogram:.6f} > prev({prev_histogram:.6f})*0.9",
                        'rsi_neutral': f"RSI Neutral Zone: {rsi:.2f}",
                        'price_above_support': f"Price > Support: {current_price:.6f} > {support:.6f}*1.005" if support else "support_fallback",
                        'volume_sufficient': f"Volume: {current_volume:.2f} > avg({avg_volume:.2f}) * {volume_soft_mult:.2f}",
                        'csi_positive': f"CSI: {pre.get('csi', 0):.2f} > 0.0",
                        'fast_reversal_core': f"Fast Reversal Core: OBI+Recovery + CVD Surge + RSI"
                    }

                    for cond_name, cond_value in basic_bypass_conditions.items():
                        status = "YES" if cond_value else "NO"
                        logger.debug(f"   • {cond_desc.get(cond_name, cond_name)} >> {status}")

                    # === TIER 1: Foundation ===
                    tier1_activated = False
                    tier1_reason = "Blocked"

                    if (fast_reversal_core and 
                        basic_bypass_conditions['ema_alignment'] and 
                        basic_bypass_conditions['histogram_rising'] and 
                        basic_bypass_conditions['volume_sufficient']):
                        tier1_activated = True
                        tier1_reason = "GOD-TIER FAST REVERSAL STACK"
                    elif basic_bypass_met_count >= basic_bypass_min:
                        tier1_activated = True
                        tier1_reason = f"MAJORITY RULE ({basic_bypass_met_count}/{len(basic_bypass_conditions)})"

                    if tier1_activated:
                        confluence += 30
                        logger.debug(f"TIER 1 ACTIVATED >> {tier1_reason} | +30 confluence")

                    # === Additional Bonuses ===
                    if cvd_divergence or obi_recovery:
                        confluence += 15
                        logger.debug("   +15 | Pressure Recovery Bonus (CVD div or OBI recovery)")

                    if fast_reversal_core and fast_reversal_boosters >= 2:
                        confluence += 25
                        logger.debug(f"   +25 | Ultra-Fast Reversal Bonus (boosters={fast_reversal_boosters})")

                    # === HIGHER TIERS (only if Tier 1 passed) ===
                    if tier1_activated:
                        # Tier 2 - Strong Trend
                        if trend_strength_proxy > 0.40:
                            confluence += 40
                            atr_bypass_tier = max(atr_bypass_tier, 2)
                            logger.debug("TIER 2 ACTIVATED (Strong Trend) >> +40 confluence")

                        # Tier 3 - Pressure Explosion
                        pressure_surge = (cvd_change_pct > 10 and obi_imbalance > 0.05 and high_vol)
                        if pressure_surge:
                            confluence += 20
                            atr_bypass_tier = 4
                            logger.debug("TIER 3 ACTIVATED (Pressure Explosion) >> +20 confluence")

                        # Tier 4 - Sentiment Surge
                        flip_detected = (btc_ig == 'bullish' and pre.get('last_btc_ig', 'neutral') in ['bearish', 'neutral'])
                        if flip_detected and pre.get('csi', 0) > 0.50 and obi_recovery:
                            confluence += 30
                            atr_bypass_tier = max(atr_bypass_tier, 3)
                            logger.debug("TIER 4 ACTIVATED (Sentiment Surge + Flip) >> +30 confluence")                    

                    # EMA Dominant Shortcut
                    if (full_ema_stack and 
                        current_price > ema_5 * 1.005 and 
                        50 < rsi < 75 and 
                        current_volume > avg_volume * volume_soft_mult and 
                        (obi > obi_relax or cvd_change_pct > 0)):
                        confluence += 15
                        logger.debug("   +15 | EMA-Dominant Stack Shortcut")

                    # -----------------------------
                    # LOW ATR BYPASS LOGIC
                    # -----------------------------
                    if atr_percent < atr_threshold and tier1_activated:
                        atr_bypass_active = True
                        # Relax threshold based on tier strength
                        relaxation_factor = 0.70 - (atr_bypass_tier * 0.08)
                        atr_threshold *= max(0.55, relaxation_factor)
                        atr_threshold = max(0.20, atr_threshold)
                        logger.debug(f"ATR BYPASS ACTIVE >> Tier {atr_bypass_tier} | Threshold relaxed to {atr_threshold:.3f}")

                    # Recent bounce
                    is_recent_bounce = False

                    if support and support > 0 and atr and atr > 0:
                        # Normal case: support exists
                        is_recent_bounce = current_price > support * 1.002 and current_price < support + atr * 3.0
                    else:
                        # Fallback when support is None or invalid
                        support_fallback = current_price * 0.98
                        is_recent_bounce = current_price > support_fallback and current_price < support_fallback + (atr * 3.0 if atr and atr > 0 else 0)

                    logger.debug(f"is_recent_bounce: {is_recent_bounce} (support={support}, atr={atr}, price={current_price}, fallback={support_fallback if 'support_fallback' in locals() else 'N/A'})")

                    # BTC_IG flip bonus
                    last_btc_ig = pre.get('last_btc_ig', 'neutral')
                    flip_detected = (btc_ig == 'bullish' and last_btc_ig in ['bearish', 'neutral'])
                    if flip_detected:
                        confluence += 1
                        logger.debug("BTC_IG flip -> +20 confluence")
                    pre['last_btc_ig'] = btc_ig
                    await save_state()

                    logger.debug(f"=== ATR BEAST FINAL SUMMARY ===")
                    logger.debug(f"• Confluence     : {confluence}")
                    logger.debug(f"• ATR Bypass Tier  : {atr_bypass_tier}")
                    logger.debug(f"• ATR Bypass Active: {atr_bypass_active}")
                    logger.debug(f"• Final ATR Threshold: {atr_threshold:.3f}")
                    logger.debug(f"• Market Regime     : {regime}")

                    # ==========================================================
                    # PATTERN 6 : EMA Momentum Alignment (Elite)
                    # ==========================================================
                
                    pattern6_score = 0.0

                    logger.debug("==PATTERN 6 PATTERN 6 PATTERN 6 : EMA Momentum Alignment (Elite)==")

                    # Core EMA Stack
                    if ema_5 > ema_9 > ema_13 > ema_21 and ema_21 > ema_50 * 0.995:
                        pattern6_score += 40
                        logger.debug(f"YES | +40 | Full EMA Stack (5>9>13>21>50) | Score: 40")
                    else:
                        logger.debug(f"NO  | +0  | Full EMA Stack (5>9>13>21>50) | Score: 0")

                    if ema_9 > ema_21 > ema_50 and pattern6_score == 0.0:  # Only apply partial if full stack didn't trigger
                        pattern6_score += 30
                        logger.debug(f"YES | +30 | Partial EMA Stack (9>21>50) | Score: 30")
                    else:
                        if pattern6_score == 0.0:
                            logger.debug(f"NO  | +0  | Partial EMA Stack (9>21>50) | Score: 0")

                    # MACD Confirmation
                    if macd_line > signal_line:
                        pattern6_score += 15
                        logger.debug(f"YES | +15 | MACD Bullish (Line > Signal) | Score: 15")
                    else:
                        logger.debug(f"NO  | +0  | MACD Bullish (Line > Signal) | Score: 0")

                    # Price Above EMA Stack
                    ema_max = max(ema_5, ema_9, ema_21, ema_50)
                    if current_price > ema_max * 1.005:
                        pattern6_score += 10
                        logger.debug(f"YES | +10 | Price Above EMA Stack | Score: 10")
                    else:
                        logger.debug(f"NO  | +0  | Price Above EMA Stack | Score: 0")

                    # RSI Healthy Zone
                    if 48 < rsi < 75:
                        pattern6_score += 15
                        logger.debug(f"YES | +15 | RSI Healthy (48-75) | Score: 15")
                    else:
                        logger.debug(f"NO  | +0  | RSI Healthy (48-75) | Score: 0")

                    # Volume + ATR Support
                    if current_volume > avg_volume * 0.9 and atr_percent > atr_threshold * 0.7:
                        pattern6_score += 10
                        logger.debug(f"YES | +10 | Volume + ATR Support | Score: 10")
                    else:
                        logger.debug(f"NO  | +0  | Volume + ATR Support | Score: 0")

                    # Bull Regime Boost
                    if regime == "trend_bull":
                        pattern6_score += 8
                        logger.debug(f"YES | +8  | Bull Regime Boost | Score: 8")
                    else:
                        logger.debug(f"NO  | +0  | Bull Regime Boost | Score: 0")

                    # === PENALTIES ===
                    # Bearish Pressure Penalty
                    if cvd_change_pct < -12 and obi < -0.12:
                        pattern6_score -= 20
                        logger.debug(f"PENALTY | -20 | Strong Bear Pressure (CVD+OBI) | Score: -20")
                    else:
                        logger.debug(f"NO PENALTY | -0 | Strong Bear Pressure (CVD+OBI) | Score: 0")

                    # Compression Penalty
                    if bb_width_proxy < 0.012:
                        pattern6_score -= 10
                        logger.debug(f"PENALTY | -10 | BB Compression | Score: -10")
                    else:
                        logger.debug(f"NO PENALTY | -0 | BB Compression | Score: 0")

                    # High-Entry Protection
                    if near_recent_top:
                        pattern6_score -= 10
                        logger.debug(f"PENALTY | -10 | Near Recent Top | Score: -10")
                    else:
                        logger.debug(f"NO PENALTY | -0 | Near Recent Top | Score: 0")

                    if overextended_price:
                        pattern6_score -= 8
                        logger.debug(f"PENALTY | -8  | Overextended Above EMA21 | Score: -8")
                    else:
                        logger.debug(f"NO PENALTY | -0 | Overextended Above EMA21 | Score: 0")

                    if distance_from_low_pct > 4.5:
                        pattern6_score -= 8
                        logger.debug(f"PENALTY | -8  | Too Far From Recent Low | Score: -8")
                    else:
                        logger.debug(f"NO PENALTY | -0 | Too Far From Recent Low | Score: 0")

                    if near_recent_top and rsi >= 68:
                        pattern6_score -= 12
                        logger.debug(f"PENALTY | -12 | Hot RSI at recent high | Score: -12")
                    if near_recent_top and obi < 0:
                        pattern6_score -= 8
                        logger.debug(f"PENALTY | -8  | Offer-side at recent high | Score: -8")

                    # ==========================================================
                    # ANTI-DECELERATION PENALTIES for PATTERN 6
                    # ==========================================================
                    fade_score = 0.0
                    fade_count = 0

                    # 1. RSI Fade
                    if rsi < rsi_prev - 0.5:   # Small tolerance
                        fade_strength = rsi_prev - rsi
                        fade_count += 1
                        if fade_strength > 5.0:
                            fade_score -= 18
                            logger.debug(f"[P6 FADE] Strong RSI fading by {fade_strength:.2f} >> -18")
                        else:
                            fade_score -= 11
                            logger.debug(f"[P6 FADE] RSI fading by {fade_strength:.2f} >> -11")
                    else:
                        logger.debug(f"[P6 FADE] RSI stable or rising (+{rsi - rsi_prev:.2f}) >> OK")

                    # 2. Histogram Fade (Critical for momentum confirmation)
                    if histogram < prev_histogram:
                        fade_strength = prev_histogram - histogram
                        fade_count += 1
                        if fade_strength > 0.0008:
                            fade_score -= 20
                            logger.debug(f"[P6 FADE] Strong Histogram fading by {fade_strength:.5f} >> -20")
                        elif fade_strength > 0.0003:
                            fade_score -= 13
                            logger.debug(f"[P6 FADE] Histogram fading by {fade_strength:.5f} >> -13")
                        else:
                            fade_score -= 8
                    else:
                        logger.debug(f"[P6 FADE] Histogram rising (+{histogram - prev_histogram:.5f}) >> Good")

                    # 3. Price falling against EMA stack (Early warning)
                    ema_max = max(ema_5, ema_9, ema_21, ema_50)
                    if current_price < prev_close * 0.998 and current_price < ema_max * 0.999:
                        fade_score -= 10
                        logger.debug(f"[P6 FADE] Price pulling back below EMAs >> -10")

                    # 4. Multi-Fade + Weak Regime
                    if fade_count >= 2:
                        fade_score -= 12
                        logger.debug(f"[P6 FADE] Multi-Fade detected ({fade_count}) >> Extra -12")

                    if fade_count >= 1 and regime in ["trend_bear", "compression"]:
                        fade_score -= 9
                        logger.debug(f"[P6 FADE] Fade in weak regime >> Extra -9")

                    pattern6_score += fade_score
                    logger.debug(f"[P6 FADE SUMMARY] Total fade penalty: {fade_score:+.1f} | Score now: {pattern6_score:.1f}")
                    # ==========================================================

                    # Final Score Processing
                    pattern6_score = max(0, min(100, pattern6_score))
                    match_pct6 = round(pattern6_score)
                    pattern6 = (
                        pattern6_score >= 85 and
                        regime in ["trend_bull", "reversal_up"] and
                        confluence >= 45 and
                        not hard_no_buy and
                        top_risk_score < 55 and
                        not (near_recent_top and price_extension_pct > 2.0) and
                        not (near_recent_top and rsi >= 68) and
                        not (near_recent_top and obi < 0 and cvd < prev_cvd)
                    )

                    logger.debug("=== PATTERN 6 FINAL SUMMARY ===")
                    logger.debug(f"• Regime          : {regime}")
                    logger.debug(f"• Confluence      : {confluence}")
                    logger.debug(f"• Hard No-Buy     : {hard_no_buy}")
                    logger.debug(f"• Top Risk Score  : {top_risk_pct}%")
                    logger.debug(f"• Near Recent Top : {near_recent_top}")
                    logger.debug(f"• ========     PATTERN 6 FINAL Score:{match_pct6}%    ============================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")

                    # === ONE-TIME TG NOTIFICATION FOR PATTERN 6 ===
                    if pattern6:
                        if not pre.get("notified_pattern_6", False):
                            message = (
                                f"🟢 PATTERN 6 DETECTED\n\n"
                                f"Symbol: {symbol}\n"
                                f"Score: {match_pct6}%\n"
                                f"Regime: {regime}\n"
                                f"Confluence: {confluence}\n"
                                f"Top Risk: {top_risk_pct}%\n"
                                f"Price: {current_price:.6f}"
                            )
                            await send_telegram_message(bot, message)
                            logger.info(f"Pattern 6 TG Notification sent for {symbol} | Score: {match_pct6}%")

                            pre["notified_pattern_6"] = True
                            await save_state()
                    else:
                        if pre.get("notified_pattern_6", False):
                            pre["notified_pattern_6"] = False
                            await save_state()

                                              
                    # ==========================================================
                    # PATTERN 15 : Momentum Acceleration (Elite)
                    # ==========================================================

                    pattern15_score = 0.0

                    logger.debug("=== PATTERN 15 PATTERN 15 PATTERN 15 : Momentum Acceleration (Elite)===")
                    logger.debug(f"Starting score: {pattern15_score}")

                    # === POSITIVE CONDITIONS ===

                    if rsi > rsi_prev + 1.5:
                        pattern15_score += 15
                        logger.debug(f"YES | +15 | RSI Acceleration | Score: {pattern15_score}")
                    else:
                        logger.debug(f"NO  | +0  | RSI Acceleration | Score: {pattern15_score}")

                    if macd_line > prev_macd + 0.0005:
                        pattern15_score += 15
                        logger.debug(f"YES | +15 | MACD Acceleration | Score: {pattern15_score}")
                    else:
                        logger.debug(f"NO  | +0  | MACD Acceleration | Score: {pattern15_score}")

                    if histogram > max(prev_histogram, -0.001):
                        pattern15_score += 15
                        logger.debug(f"YES | +15 | Histogram Rising | Score: {pattern15_score}")
                    else:
                        logger.debug(f"NO  | +0  | Histogram Rising | Score: {pattern15_score}")

                    if atr_percent > atr_threshold * 0.7 and rsi < 72 and bb_width_proxy > 0.015:
                        pattern15_score += 20
                        logger.debug(f"YES | +20 | Expansion Zone | Score: {pattern15_score}")
                    else:
                        logger.debug(f"NO  | +0  | Expansion Zone | Score: {pattern15_score}")

                    if current_price > ema_21 * 0.998:
                        pattern15_score += 10
                        logger.debug(f"YES | +10 | Price Above EMA21 | Score: {pattern15_score}")
                    else:
                        logger.debug(f"NO  | +0  | Price Above EMA21 | Score: {pattern15_score}")

                    if current_price > prev_close * 1.002:
                        pattern15_score += 10
                        logger.debug(f"YES | +10 | Above Previous Close | Score: {pattern15_score}")
                    else:
                        logger.debug(f"NO  | +0  | Above Previous Close | Score: {pattern15_score}")

                    if is_recent_bounce:
                        pattern15_score += 10
                        logger.debug(f"YES | +10 | Recent Bounce | Score: {pattern15_score}")
                    else:
                        logger.debug(f"NO  | +0  | Recent Bounce | Score: {pattern15_score}")

                    if current_volume > avg_volume * 1.2:
                        pattern15_score += 5
                        logger.debug(f"YES | +5  | Strong Volume Support | Score: {pattern15_score}")
                    else:
                        logger.debug(f"NO  | +0  | Strong Volume Support | Score: {pattern15_score}")

                    if cvd > prev_cvd * 1.05:
                        pattern15_score += 5
                        logger.debug(f"YES | +5  | CVD Strength | Score: {pattern15_score}")
                    else:
                        logger.debug(f"NO  | +0  | CVD Strength | Score: {pattern15_score}")

                    if obi > 0.15 and (obi > prev_obi or obi_recovery):
                        pattern15_score += 5
                        logger.debug(f"YES | +5  | OBI Strength | Score: {pattern15_score}")
                    else:
                        logger.debug(f"NO  | +0  | OBI Strength | Score: {pattern15_score}")

                    if obi_recovery:
                        pattern15_score += 5
                        logger.debug(f"YES | +5  | OBI Recovery | Score: {pattern15_score}")
                    else:
                        logger.debug(f"NO  | +0  | OBI Recovery | Score: {pattern15_score}")

                    if regime in ["trend_bull", "reversal_up"]:
                        pattern15_score += 8
                        logger.debug(f"YES | +8  | Good Regime (Bull/Reversal) | Score: {pattern15_score}")
                    else:
                        logger.debug(f"NO  | +0  | Good Regime (Bull/Reversal) | Score: {pattern15_score}")

                    # === PENALTIES ===

                    if cvd_change_pct < -12 and obi < -0.12:
                        pattern15_score -= 20
                        logger.debug(f"PENALTY | -20 | Strong Bear Pressure (CVD+OBI) | Score: {pattern15_score}")
                    else:
                        logger.debug(f"NO PENALTY | -0 | Strong Bear Pressure (CVD+OBI) | Score: {pattern15_score}")

                    if bb_width_proxy < 0.012:
                        pattern15_score -= 8
                        logger.debug(f"PENALTY | -8  | BB Compression | Score: {pattern15_score}")
                    else:
                        logger.debug(f"NO PENALTY | -0 | BB Compression | Score: {pattern15_score}")

                    # High-Entry Protection
                    if near_recent_top:
                        pattern15_score -= 12
                        logger.debug(f"PENALTY | -12 | Near Recent Top | Score: {pattern15_score}")
                    else:
                        logger.debug(f"NO PENALTY | -0 | Near Recent Top | Score: {pattern15_score}")

                    if overextended_price:
                        pattern15_score -= 10
                        logger.debug(f"PENALTY | -10 | Overextended Above EMA21 | Score: {pattern15_score}")
                    else:
                        logger.debug(f"NO PENALTY | -0 | Overextended Above EMA21 | Score: {pattern15_score}")

                    if distance_from_low_pct > 5.0:
                        pattern15_score -= 8
                        logger.debug(f"PENALTY | -8  | Too Stretched From Recent Low | Score: {pattern15_score}")
                    else:
                        logger.debug(f"NO PENALTY | -0 | Too Stretched From Recent Low | Score: {pattern15_score}")

                    if near_recent_top and rsi >= 70:
                        pattern15_score -= 10
                        logger.debug(f"PENALTY | -10 | Hot RSI at recent high | Score: {pattern15_score}")

                    # ==========================================================
                    # ANTI-DECELERATION PENALTIES (Final Version)
                    # ==========================================================
                    fade_score = 0.0
                    fade_count = 0

                    # 1. RSI Fade Protection
                    if rsi < rsi_prev:
                        fade_strength = rsi_prev - rsi
                        fade_count += 1
                    
                        if fade_strength > 8.0:
                            fade_score -= 22
                            logger.debug(f"[P15 FADE] STRONG RSI fading by {fade_strength:.2f} points >> -22")
                        elif fade_strength > 2.0:
                            fade_score -= 16
                            logger.debug(f"[P15 FADE] Moderate RSI fading by {fade_strength:.2f} points >> -16")
                        else:
                            fade_score -= 9
                            logger.debug(f"[P15 FADE] Light RSI fading by {fade_strength:.2f} points >> -9")
                    else:
                        logger.debug(f"[P15 FADE] RSI is rising (+{rsi - rsi_prev:.2f}) >> No penalty")

                    # 2. Histogram Fade Protection
                    if histogram < prev_histogram:
                        fade_strength = prev_histogram - histogram
                        fade_count += 1
                    
                        if fade_strength > 0.0008:
                            fade_score -= 22
                            logger.debug(f"[P15 FADE] STRONG Histogram fading by {fade_strength:.5f} >> -22")
                        elif fade_strength > 0.0003:
                            fade_score -= 14
                            logger.debug(f"[P15 FADE] Moderate Histogram fading by {fade_strength:.5f} >> -14")
                        else:
                            fade_score -= 8
                            logger.debug(f"[P15 FADE] Light Histogram fading by {fade_strength:.5f} >> -8")
                    else:
                        logger.debug(f"[P15 FADE] Histogram is rising (+{histogram - prev_histogram:.5f}) >> No penalty")

                    # 3. Multi-Fade Penalty (Synergistic Decay)
                    if fade_count >= 2:
                        fade_score -= 12
                        logger.debug(f"[P15 FADE] MULTI-FADE detected ({fade_count}/2 indicators fading) >> Extra -12")
                    elif fade_count == 1:
                        logger.debug(f"[P15 FADE] Single indicator fading >> No extra multi penalty")

                    # 4. Context-Aware Penalty (Worse in weak regimes)
                    if fade_count >= 1 and regime in ["trend_bear", "reversal_down", "compression"]:
                        fade_score -= 10
                        logger.debug(f"[P15 FADE] Fading momentum in WEAK regime ({regime}) >> Extra -10")

                    # Apply the total fade penalty
                    pattern15_score += fade_score
                
                    logger.debug(f"[P15 FADE SUMMARY] Total fade penalty: {fade_score:+.1f} | Final score after fade: {pattern15_score:.1f}")
                    # ==========================================================

                    # Final Score Processing
                    pattern15_score = max(0, min(100, pattern15_score))
                    match_pct15 = round(pattern15_score)
                    accel_count = sum([
                        rsi > rsi_prev + 1.5,
                        macd_line > prev_macd + 0.0005,
                        histogram > prev_histogram
                    ])
                    pattern15 = (
                        pattern15_score >= 85 and
                        accel_count >= 2 and
                        confluence >= 42 and
                        regime != "compression" and
                        atr_percent >= 1.0 and
                        current_volume <= avg_volume * 2.5 and
                        not hard_no_buy and
                        top_risk_score < 55 and
                        not (near_recent_top and price_extension_pct > 2.2) and
                        not (near_recent_top and rsi >= 70)
                    )

                    logger.debug("=== PATTERN 15 FINAL SUMMARY ===")
                    logger.debug(f"• Regime           : {regime}")
                    logger.debug(f"• Confluence       : {confluence}")
                    logger.debug(f"• Hard No-Buy      : {hard_no_buy}")
                    logger.debug(f"• Top Risk Score   : {top_risk_pct}%")
                    logger.debug(f"• Near Recent Top  : {near_recent_top}")
                    logger.debug(f"• ========     PATTERN 15 FINAL Score:{match_pct15}%    ==========================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")

                    # === ONE-TIME TG NOTIFICATION FOR PATTERN 15 ===
                    if pattern15:
                        if not pre.get("notified_pattern_15", False):
                            message = (
                                f"🟢 PATTERN 15 DETECTED\n\n"
                                f"Symbol: {symbol}\n"
                                f"Score: {match_pct15}%\n"
                                f"Regime: {regime}\n"
                                f"Confluence: {confluence}\n"
                                f"Top Risk: {top_risk_pct}%\n"
                                f"Price: {current_price:.6f}"
                            )
                            await send_telegram_message(bot, message)
                            logger.info(f"Pattern 15 TG Notification sent for {symbol} | Score: {match_pct15}%")

                            pre["notified_pattern_15"] = True
                            await save_state()
                    else:
                        if pre.get("notified_pattern_15", False):
                            pre["notified_pattern_15"] = False
                            await save_state()

                
                    # ==========================================================
                    # PATTERN 16 : Super-Power Rally Predictor (Ultra-Strong Bull Rally)
                    # ==========================================================

                    pattern16_score = 0.0

                    logger.debug("=== PATTERN 16 PATTERN 16 PATTERN 16 : Super-Power Rally Predictor ===")
                    logger.debug(f"Starting score: {pattern16_score}")

                    # Critical: Perfect EMA stack with strong price dominance
                    if (ema_5 > ema_9 > ema_13 > ema_21 > ema_50 and 
                        current_price > ema_5 * 1.01 and current_price > ema_50 * 1.02):
                        pattern16_score += 40
                        logger.debug(f"YES | +40 | Perfect EMA Stack + Strong Price Dominance | Score: {pattern16_score}")
                    else:
                        logger.debug(f"NO  | +0  | Perfect EMA Stack + Strong Price Dominance | Score: {pattern16_score}")

                    # Strong sustainable momentum surge
                    if (macd_line > signal_line > 0 and histogram > prev_histogram * 1.2 and 
                        60 < rsi < 78 and rsi > rsi_prev + 2):
                        pattern16_score += 30
                        logger.debug(f"YES | +30 | Strong Sustainable Momentum Surge (MACD + RSI) | Score: {pattern16_score}")
                    else:
                        logger.debug(f"NO  | +0  | Strong Sustainable Momentum Surge (MACD + RSI) | Score: {pattern16_score}")

                    # Volume surge with breakout confluence
                    if (current_volume > avg_volume * 2.0 and trend_strength_proxy > 2.0 and 
                        current_price > vwap * 1.015 and current_price > prev_high * 1.002):
                        pattern16_score += 25
                        logger.debug(f"YES | +25 | Volume Surge + Breakout Confluence | Score: {pattern16_score}")
                    else:
                        logger.debug(f"NO  | +0  | Volume Surge + Breakout Confluence | Score: {pattern16_score}")

                    # Pressure confirmations (strong buying build-up)
                    if cvd > 0 and cvd_change_pct > (20 if 'high_vol' in locals() and high_vol else 10):
                        pattern16_score += 5
                        logger.debug(f"YES | +5  | Strong CVD Build-up | Score: {pattern16_score}")
                    else:
                        logger.debug(f"NO  | +0  | Strong CVD Build-up | Score: {pattern16_score}")

                    if obi > 0.2 and obi_imbalance > 0.05:
                        pattern16_score += 5
                        logger.debug(f"YES | +5  | Strong OBI Imbalance | Score: {pattern16_score}")
                    else:
                        logger.debug(f"NO  | +0  | Strong OBI Imbalance | Score: {pattern16_score}")

                    # Strong penalty for conflicting bearish pressure
                    if cvd_change_pct < -12 and obi < -0.12:
                        pattern16_score -= 35
                        logger.debug(f"PENALTY | -35 | Conflicting Bearish Pressure | Score: {pattern16_score}")
                    else:
                        logger.debug(f"NO PENALTY | -0 | Conflicting Bearish Pressure | Score: {pattern16_score}")

                    # Final Score Processing
                    pattern16_score = max(0.0, min(100.0, pattern16_score))
                    match_pct16 = round(pattern16_score)
                    pattern16 = pattern16_score >= 85

                    logger.debug("=== PATTERN 16 FINAL SUMMARY ===")
                    logger.debug(f"• Regime            : {regime}")
                    logger.debug(f"• RSI               : {rsi:.2f}")
                    logger.debug(f"• Top Risk Score    : {top_risk_pct}%")
                    logger.debug(f"• Trend Strength    : {trend_strength_proxy:.2f}")
                    logger.debug(f"• ========     PATTERN 16 FINAL Score:{match_pct16}%    ==========================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")

                    # === ONE-TIME TG NOTIFICATION FOR PATTERN 16 ===
                    if pattern16:
                        if not pre.get("notified_pattern_16", False):
                            message = (
                                f"🟢 PATTERN 16 DETECTED\n\n"
                                f"Symbol: {symbol}\n"
                                f"Score: {match_pct16}%\n"
                                f"Regime: {regime}\n"
                                f"Confluence: {confluence}\n"
                                f"Top Risk: {top_risk_pct}%\n"
                                f"Price: {current_price:.6f}"
                            )
                            await send_telegram_message(bot, message)
                            logger.info(f"Pattern 16 TG Notification sent for {symbol} | Score: {match_pct16}%")

                            pre["notified_pattern_16"] = True
                            await save_state()
                    else:
                        if pre.get("notified_pattern_16", False):
                            pre["notified_pattern_16"] = False
                            await save_state()
                    

                    # ==========================================================
                    # PATTERN 18 : Bearish Rebound Hunter
                    # ==========================================================

                    pattern18_score = 0.0

                    logger.debug("=== PATTERN 18 PATTERN 18 PATTERN 18 : Bearish Rebound Hunter ===")
                    logger.debug(f"Starting score: {pattern18_score}")

                    # === POSITIVE CONDITIONS ===

                    if 15 < rsi < 25:
                        pattern18_score += 35
                        logger.debug(f"YES | +35 | RSI Deep Oversold (15-22) | Score: {pattern18_score}")
                    else:
                        logger.debug(f"NO  | +0  | RSI Deep Oversold (15-22) | Score: {pattern18_score}")

                    if rsi > rsi_prev + 0.5:
                        pattern18_score += 18
                        logger.debug(f"YES | +18 | RSI Rising from Oversold | Score: {pattern18_score}")
                    else:
                        logger.debug(f"NO  | +0  | RSI Rising from Oversold | Score: {pattern18_score}")

                    if -0.7 < pre.get('csi', 0) < -0.25:
                        pattern18_score += 12
                        logger.debug(f"YES | +12 | CSI in Sweet Spot (-0.7 to -0.25) | Score: {pattern18_score}")
                    else:
                        logger.debug(f"NO  | +0  | CSI in Sweet Spot (-0.7 to -0.25) | Score: {pattern18_score}")

                    if histogram > prev_histogram * 0.95 or (histogram > -0.001 and prev_histogram < -0.001):
                        pattern18_score += 15
                        logger.debug(f"YES | +15 | Histogram Improving | Score: {pattern18_score}")
                    else:
                        logger.debug(f"NO  | +0  | Histogram Improving | Score: {pattern18_score}")

                    if current_price < ema_50 * 0.985:
                        pattern18_score += 10
                        logger.debug(f"YES | +10 | Price Well Below EMA50 | Score: {pattern18_score}")
                    else:
                        logger.debug(f"NO  | +0  | Price Well Below EMA50 | Score: {pattern18_score}")

                    if cvd_divergence:
                        pattern18_score += 10
                        logger.debug(f"YES | +10 | CVD Bullish Divergence | Score: {pattern18_score}")
                    else:
                        logger.debug(f"NO  | +0  | CVD Bullish Divergence | Score: {pattern18_score}")

                    if cvd > prev_cvd and cvd > 0:
                        pattern18_score += 12
                        logger.debug(f"YES | +12 | CVD Accumulation | Score: {pattern18_score}")
                    else:
                        logger.debug(f"NO  | +0  | CVD Accumulation | Score: {pattern18_score}")

                    if obi > 0.05:
                        pattern18_score += 8
                        logger.debug(f"YES | +8  | Positive OBI | Score: {pattern18_score}")
                    else:
                        logger.debug(f"NO  | +0  | Positive OBI | Score: {pattern18_score}")

                    if atr > prev_atr * 1.1:
                        pattern18_score += 6
                        logger.debug(f"YES | +6  | volatility expanding | Score: {pattern18_score}")
                    else:
                        logger.debug(f"NO  | +0  | volatility expanding | Score: {pattern18_score}")
                    
                    if obi_recovery:
                        pattern18_score += 10
                        logger.debug(f"YES | +10 | OBI Recovery | Score: {pattern18_score}")
                    else:
                        logger.debug(f"NO  | +0  | OBI Recovery | Score: {pattern18_score}")

                    if current_volume > avg_volume * 1.1:
                        pattern18_score += 7

                        logger.debug(f"YES | +7 | Volume support | Score: {pattern18_score}")
                    else:
                        logger.debug(f"NO  | +0  | Volume support | Score: {pattern18_score}")    

                    if regime == "reversal_up":
                        pattern18_score += 10
                        logger.debug(f"YES | +10 | Reversal Up Regime | Score: {pattern18_score}")
                    else:
                        logger.debug(f"NO  | +0  | Reversal Up Regime | Score: {pattern18_score}")

                    # === PENALTY ===
                    if cvd_change_pct < -8 or obi < -0.15 or current_price > price_low * 1.0045:
                        pattern18_score -= 30
                        logger.debug(f"PENALTY | -30 | Bearish Pressure or Price Rejection | Score: {pattern18_score}")
                    else:
                        logger.debug(f"NO PENALTY | -0 | Bearish Pressure or Price Rejection | Score: {pattern18_score}")

                    # Final Score Processing
                    pattern18_score = max(0, min(100, pattern18_score))
                    match_pct18 = round(pattern18_score)
                    pattern18 = pattern18_score >= 85

                    logger.debug("=== PATTERN 18 FINAL SUMMARY ===")
                    logger.debug(f"• Regime          : {regime}")
                    logger.debug(f"• RSI             : {rsi:.2f}")
                    logger.debug(f"• ========     PATTERN 18 FINAL Score:{match_pct18}%    ==========================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")

                    # === ONE-TIME TG NOTIFICATION FOR PATTERN 18 ===
                    if pattern18:
                        if not pre.get("notified_pattern_18", False):
                            message = (
                                f"🟠 PATTERN 18 DETECTED\n\n"
                                f"Symbol: {symbol}\n"
                                f"Score: {match_pct18}%\n"
                                f"Regime: {regime}\n"
                                f"Confluence: {confluence}\n"
                                f"Top Risk: {top_risk_pct}%\n"
                                f"Price: {current_price:.6f}"
                            )
                            await send_telegram_message(bot, message)
                            logger.info(f"Pattern 18 TG Notification sent for {symbol} | Score: {match_pct18}%")

                            pre["notified_pattern_18"] = True
                            await save_state()
                    else:
                        if pre.get("notified_pattern_18", False):
                            pre["notified_pattern_18"] = False
                            await save_state()

                
                    # ==========================================================
                    # PATTERN 22 : Ultra Bearish Rebound
                    # ==========================================================
                    pattern22_score = 0.0
                    logger.debug("=== PATTERN 22 PATTERN 22 PATTERN 22 : Ultra Bearish Rebound ===")
                    logger.debug(f"Starting score: {pattern22_score}")
                    # === POSITIVE CONDITIONS ===
                    if rsi < 15:
                        pattern22_score += 30
                        logger.debug(f"YES | +30 | Extreme RSI Oversold (<15) | Score: {pattern22_score}")
                    else:
                        logger.debug(f"NO  | +0  | Extreme RSI Oversold (<15) | Score: {pattern22_score}")
                    if rsi > rsi_prev:
                        pattern22_score += 5
                        logger.debug(f"YES | +5  | RSI Starting to Recover | Score: {pattern22_score}")
                    else:
                        logger.debug(f"NO  | +0  | RSI Starting to Recover | Score: {pattern22_score}")
                    if cvd_divergence or (cvd > prev_cvd and cvd_change_pct > 3):
                        pattern22_score += 12
                        logger.debug(f"YES | +12 | CVD Divergence / Strong Recovery | Score: {pattern22_score}")
                    else:
                        logger.debug(f"NO  | +0  | CVD Divergence / Strong Recovery | Score: {pattern22_score}")
                    if obi_recovery or (obi > 0.05 and obi > prev_obi):
                        pattern22_score += 10
                        logger.debug(f"YES | +10 | OBI Recovery / Positive Shift | Score: {pattern22_score}")
                    else:
                        logger.debug(f"NO  | +0  | OBI Recovery / Positive Shift | Score: {pattern22_score}")
                    if histogram > prev_histogram:
                        pattern22_score += 15
                        logger.debug(f"YES | +15 | Histogram Rising | Score: {pattern22_score}")
                    else:
                        logger.debug(f"NO  | +0  | Histogram Rising | Score: {pattern22_score}")
                    if current_price < ema_50 * 0.97:
                        pattern22_score += 5
                        logger.debug(f"YES | +5  | Price Deep Below EMA50 | Score: {pattern22_score}")
                    else:
                        logger.debug(f"NO  | +0  | Price Deep Below EMA50 | Score: {pattern22_score}")
                    if current_volume > avg_volume:
                        pattern22_score += 5
                        logger.debug(f"YES | +5  | Above Average Volume | Score: {pattern22_score}")
                    else:
                        logger.debug(f"NO  | +0  | Above Average Volume | Score: {pattern22_score}")
                    if atr > prev_atr * 1.2:
                        pattern22_score += 5
                        logger.debug(f"YES | +5  | ATR Expansion | Score: {pattern22_score}")
                    else:
                        logger.debug(f"NO  | +0  | ATR Expansion | Score: {pattern22_score}")
                    if cvd_change_pct > 8 and obi > 0.08:
                        pattern22_score += 8
                        logger.debug(f"YES | +8  | Dual Strong CVD + OBI Surge | Score: {pattern22_score}")
                    else:
                        logger.debug(f"NO  | +0  | Dual Strong CVD + OBI Surge | Score: {pattern22_score}")
                    if current_price < ema_50 * 0.95:
                        pattern22_score += 5
                        logger.debug(f"YES | +5  | Extreme Price Washout (< EMA50*0.95) | Score: {pattern22_score}")
                    else:
                        logger.debug(f"NO  | +0  | Extreme Price Washout (< EMA50*0.95) | Score: {pattern22_score}")
                    if regime == "reversal_up":
                        pattern22_score += 10
                        logger.debug(f"YES | +10 | Reversal Up Regime | Score: {pattern22_score}")
                    else:
                        logger.debug(f"NO  | +0  | Reversal Up Regime | Score: {pattern22_score}")
                    # Final Score Processing
                    pattern22_score = max(0, min(100, pattern22_score))
                    match_pct22 = round(pattern22_score)
                    pattern22 = pattern22_score >= 85
                    logger.debug("=== PATTERN 22 FINAL SUMMARY ===")
                    logger.debug(f"• Regime          : {regime}")
                    logger.debug(f"• RSI             : {rsi:.2f}")
                    logger.debug(f"• ========     PATTERN 22 FINAL Score:{match_pct22}%    ==========================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    # === ONE-TIME TG NOTIFICATION FOR PATTERN 22 ===
                    if pattern22:
                        if not pre.get("notified_pattern_22", False):
                            message = (
                                f"🔴 PATTERN 22 DETECTED\n\n"
                                f"Symbol: {symbol}\n"
                                f"Score: {match_pct22}%\n"
                                f"Regime: {regime}\n"
                                f"Confluence: {confluence}\n"
                                f"Top Risk: {top_risk_pct}%\n"
                                f"Price: {current_price:.6f}"
                            )
                            await send_telegram_message(bot, message)
                            logger.info(f"Pattern 22 TG Notification sent for {symbol} | Score: {match_pct22}%")
                            pre["notified_pattern_22"] = True
                            await save_state()
                    else:
                        if pre.get("notified_pattern_22", False):
                            pre["notified_pattern_22"] = False
                            await save_state()

                    # ==========================================================
                    # PATTERN 9 : VWAP Reclaim + Orderflow Flip
                    # ==========================================================
                    pattern9_score = 0.0

                    logger.debug("=== PATTERN 9 PATTERN 9 PATTERN 9 : VWAP Reclaim Orderflow Flip ===")
                    logger.debug(f"Starting score: {pattern9_score}")

                    vwap_reclaim = (prev_close < vwap) and (current_price > vwap * 1.0005)
                    not_chasing_vwap = current_price <= vwap * 1.015

                    if vwap_reclaim:
                        pattern9_score += 35
                        logger.debug(f"YES | +35 | VWAP reclaim | prev={prev_close:.6f} vwap={vwap:.6f} px={current_price:.6f} | Score: {pattern9_score}")
                    else:
                        logger.debug(f"NO  | +0  | VWAP reclaim | prev={prev_close:.6f} vwap={vwap:.6f} px={current_price:.6f} | Score: {pattern9_score}")

                    if not_chasing_vwap:
                        pattern9_score += 12
                        logger.debug(f"YES | +12 | Not chasing VWAP | px={current_price:.6f} cap={vwap * 1.015:.6f} | Score: {pattern9_score}")
                    else:
                        logger.debug(f"NO  | +0  | Not chasing VWAP | px={current_price:.6f} cap={vwap * 1.015:.6f} | Score: {pattern9_score}")

                    if obi_recovery or (obi > 0.0 and obi > prev_obi):
                        pattern9_score += 15
                        logger.debug(f"YES | +15 | OBI flip | obi={obi:.4f} prev={prev_obi:.4f} recovery={obi_recovery} | Score: {pattern9_score}")
                    else:
                        logger.debug(f"NO  | +0  | OBI flip | obi={obi:.4f} prev={prev_obi:.4f} recovery={obi_recovery} | Score: {pattern9_score}")

                    if cvd > prev_cvd:
                        pattern9_score += 12
                        logger.debug(f"YES | +12 | CVD rising | cvd={cvd:.4f} prev={prev_cvd:.4f} | Score: {pattern9_score}")
                    else:
                        logger.debug(f"NO  | +0  | CVD rising | cvd={cvd:.4f} prev={prev_cvd:.4f} | Score: {pattern9_score}")

                    if histogram > prev_histogram:
                        pattern9_score += 10
                        logger.debug(f"YES | +10 | Histogram rising | hist={histogram:.6f} prev={prev_histogram:.6f} | Score: {pattern9_score}")
                    else:
                        logger.debug(f"NO  | +0  | Histogram rising | hist={histogram:.6f} prev={prev_histogram:.6f} | Score: {pattern9_score}")

                    if 40 < rsi < 65:
                        pattern9_score += 10
                        logger.debug(f"YES | +10 | RSI reclaim zone (40-65) | rsi={rsi:.2f} | Score: {pattern9_score}")
                    else:
                        logger.debug(f"NO  | +0  | RSI reclaim zone (40-65) | rsi={rsi:.2f} | Score: {pattern9_score}")

                    if current_volume > avg_volume * 0.90:
                        pattern9_score += 8
                        logger.debug(f"YES | +8  | Volume sufficient | vol={current_volume:.2f} avg={avg_volume:.2f} | Score: {pattern9_score}")
                    else:
                        logger.debug(f"NO  | +0  | Volume sufficient | vol={current_volume:.2f} avg={avg_volume:.2f} | Score: {pattern9_score}")

                    if current_price > bb_lower * 1.002:
                        pattern9_score += 5
                        logger.debug(f"YES | +5  | Above BB lower | px={current_price:.6f} bb_low={bb_lower:.6f} | Score: {pattern9_score}")
                    else:
                        logger.debug(f"NO  | +0  | Above BB lower | px={current_price:.6f} bb_low={bb_lower:.6f} | Score: {pattern9_score}")

                    # === PENALTIES ===
                    if near_recent_top:
                        pattern9_score -= 18
                        logger.debug(f"PENALTY | -18 | Near recent top | Score: {pattern9_score}")
                    else:
                        logger.debug(f"NO PENALTY | -0 | Near recent top | Score: {pattern9_score}")

                    if rsi > 70:
                        pattern9_score -= 15
                        logger.debug(f"PENALTY | -15 | RSI overheated | rsi={rsi:.2f} | Score: {pattern9_score}")
                    else:
                        logger.debug(f"NO PENALTY | -0 | RSI overheated | rsi={rsi:.2f} | Score: {pattern9_score}")

                    if cvd_change_pct < -10 and obi < -0.12:
                        pattern9_score -= 20
                        logger.debug(f"PENALTY | -20 | Strong bear pressure (CVD+OBI) | cvd%={cvd_change_pct:.2f} obi={obi:.4f} | Score: {pattern9_score}")
                    else:
                        logger.debug(f"NO PENALTY | -0 | Strong bear pressure (CVD+OBI) | Score: {pattern9_score}")

                    if regime == "reversal_down":
                        pattern9_score -= 18
                        logger.debug(f"PENALTY | -18 | Reversal down regime | regime={regime} | Score: {pattern9_score}")
                    else:
                        logger.debug(f"NO PENALTY | -0 | Reversal down regime | regime={regime} | Score: {pattern9_score}")

                    if overextended_price:
                        pattern9_score -= 12
                        logger.debug(f"PENALTY | -12 | Overextended above EMA21 | Score: {pattern9_score}")
                    else:
                        logger.debug(f"NO PENALTY | -0 | Overextended above EMA21 | Score: {pattern9_score}")

                    pattern9_score = max(0, min(100, pattern9_score))
                    match_pct9 = round(pattern9_score)
                    pattern9 = (
                        pattern9_score >= 85 and
                        vwap_reclaim and
                        not hard_no_buy and
                        top_risk_score < 55 and
                        regime not in ["reversal_down"] and
                        not (near_recent_top and price_extension_pct > 1.8)
                    )

                    logger.debug("=== PATTERN 9 FINAL SUMMARY ===")
                    logger.debug(f"• VWAP reclaim      : {vwap_reclaim}")
                    logger.debug(f"• Not chasing VWAP  : {not_chasing_vwap}")
                    logger.debug(f"• Regime            : {regime}")
                    logger.debug(f"• Confluence        : {confluence}")
                    logger.debug(f"• Hard No-Buy       : {hard_no_buy}")
                    logger.debug(f"• Top Risk Score    : {top_risk_pct}%")
                    logger.debug(f"• Near Recent Top   : {near_recent_top}")
                    logger.debug(f"• Valid             : {pattern9}")
                    logger.debug(f"• ========     PATTERN 9 FINAL Score:{match_pct9}%    ===========================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")

                    if pattern9:
                        if not pre.get("notified_pattern_9", False):
                            message = (
                                f"⚪ PATTERN 9 DETECTED\n\n"
                                f"Symbol: {symbol}\n"
                                f"Score: {match_pct9}%\n"
                                f"Regime: {regime}\n"
                                f"Confluence: {confluence}\n"
                                f"Top Risk: {top_risk_pct}%\n"
                                f"Price: {current_price:.6f}"
                            )
                            await send_telegram_message(bot, message)
                            logger.info(f"Pattern 9 TG Notification sent for {symbol} | Score: {match_pct9}%")
                            pre["notified_pattern_9"] = True
                            await save_state()
                    else:
                        if pre.get("notified_pattern_9", False):
                            pre["notified_pattern_9"] = False
                            await save_state()

                    # ==========================================================
                    # PATTERN 11 : Mid-Bear Relief (RSI 26-42)
                    # ==========================================================
                    pattern11_score = 0.0

                    logger.debug("=== PATTERN 11 PATTERN 11 PATTERN 11 : Mid-Bear Relief ===")
                    logger.debug(f"Starting score: {pattern11_score}")

                    mid_os_rsi = (26 <= rsi <= 42)
                    structure_demand = False
                    if support and support > 0 and current_price <= support * 1.012:
                        structure_demand = True
                    if fib_61_8 and fib_61_8 > 0 and abs(current_price - fib_61_8) / fib_61_8 <= 0.012:
                        structure_demand = True
                    if current_price <= bb_lower * 1.008:
                        structure_demand = True

                    if mid_os_rsi:
                        pattern11_score += 32
                        logger.debug(f"YES | +32 | RSI mid-oversold (26-42) | rsi={rsi:.2f} | Score: {pattern11_score}")
                    else:
                        logger.debug(f"NO  | +0  | RSI mid-oversold (26-42) | rsi={rsi:.2f} | Score: {pattern11_score}")

                    if rsi > rsi_prev + 0.4:
                        pattern11_score += 15
                        logger.debug(f"YES | +15 | RSI turning up | rsi={rsi:.2f} prev={rsi_prev:.2f} | Score: {pattern11_score}")
                    else:
                        logger.debug(f"NO  | +0  | RSI turning up | rsi={rsi:.2f} prev={rsi_prev:.2f} | Score: {pattern11_score}")

                    if regime == "trend_bear" or (current_price < ema_21 and macd_line < signal_line):
                        pattern11_score += 15
                        logger.debug(f"YES | +15 | Still in bear structure | regime={regime} px={current_price:.6f} ema21={ema_21:.6f} | Score: {pattern11_score}")
                    else:
                        logger.debug(f"NO  | +0  | Still in bear structure | regime={regime} px={current_price:.6f} ema21={ema_21:.6f} | Score: {pattern11_score}")

                    if structure_demand:
                        pattern11_score += 12
                        logger.debug(f"YES | +12 | Structure demand | support={support} fib61.8={fib_61_8} bb_low={bb_lower:.6f} | Score: {pattern11_score}")
                    else:
                        logger.debug(f"NO  | +0  | Structure demand | support={support} fib61.8={fib_61_8} bb_low={bb_lower:.6f} | Score: {pattern11_score}")

                    if histogram > prev_histogram:
                        pattern11_score += 12
                        logger.debug(f"YES | +12 | Histogram rising | hist={histogram:.6f} prev={prev_histogram:.6f} | Score: {pattern11_score}")
                    else:
                        logger.debug(f"NO  | +0  | Histogram rising | hist={histogram:.6f} prev={prev_histogram:.6f} | Score: {pattern11_score}")

                    if cvd_divergence or obi_recovery:
                        pattern11_score += 12
                        logger.debug(f"YES | +12 | Flow divergence/recovery | cvd_div={cvd_divergence} obi_rec={obi_recovery} | Score: {pattern11_score}")
                    else:
                        logger.debug(f"NO  | +0  | Flow divergence/recovery | cvd_div={cvd_divergence} obi_rec={obi_recovery} | Score: {pattern11_score}")

                    if current_volume > avg_volume:
                        pattern11_score += 6
                        logger.debug(f"YES | +6  | Volume above average | vol={current_volume:.2f} avg={avg_volume:.2f} | Score: {pattern11_score}")
                    else:
                        logger.debug(f"NO  | +0  | Volume above average | vol={current_volume:.2f} avg={avg_volume:.2f} | Score: {pattern11_score}")

                    # === PENALTIES ===
                    if rsi < 25:
                        pattern11_score -= 30
                        logger.debug(f"PENALTY | -30 | RSI too deep (that's P18/22) | rsi={rsi:.2f} | Score: {pattern11_score}")
                    else:
                        logger.debug(f"NO PENALTY | -0 | RSI too deep | rsi={rsi:.2f} | Score: {pattern11_score}")

                    if rsi > 45:
                        pattern11_score -= 18
                        logger.debug(f"PENALTY | -18 | RSI already recovered | rsi={rsi:.2f} | Score: {pattern11_score}")
                    else:
                        logger.debug(f"NO PENALTY | -0 | RSI already recovered | rsi={rsi:.2f} | Score: {pattern11_score}")

                    if current_price > ema_21 * 1.012:
                        pattern11_score -= 15
                        logger.debug(f"PENALTY | -15 | Price already above EMA21 | px={current_price:.6f} ema21={ema_21:.6f} | Score: {pattern11_score}")
                    else:
                        logger.debug(f"NO PENALTY | -0 | Price already above EMA21 | Score: {pattern11_score}")

                    if cvd_change_pct < -10 and obi < -0.15:
                        pattern11_score -= 20
                        logger.debug(f"PENALTY | -20 | Still dumping (CVD+OBI) | cvd%={cvd_change_pct:.2f} obi={obi:.4f} | Score: {pattern11_score}")
                    else:
                        logger.debug(f"NO PENALTY | -0 | Still dumping (CVD+OBI) | Score: {pattern11_score}")

                    if current_price > price_low * 1.018:
                        pattern11_score -= 10
                        logger.debug(f"PENALTY | -10 | Bounce already stretched from low | px={current_price:.6f} low={price_low:.6f} | Score: {pattern11_score}")
                    else:
                        logger.debug(f"NO PENALTY | -0 | Bounce already stretched from low | Score: {pattern11_score}")

                    pattern11_score = max(0, min(100, pattern11_score))
                    match_pct11 = round(pattern11_score)
                    pattern11 = (
                        pattern11_score >= 85 and
                        mid_os_rsi and
                        structure_demand and
                        histogram > prev_histogram and
                        rsi < 43 and
                        not hard_no_buy
                    )

                    logger.debug("=== PATTERN 11 FINAL SUMMARY ===")
                    logger.debug(f"• Mid OS RSI        : {mid_os_rsi} (rsi={rsi:.2f})")
                    logger.debug(f"• Structure demand  : {structure_demand}")
                    logger.debug(f"• Regime            : {regime}")
                    logger.debug(f"• Confluence        : {confluence}")
                    logger.debug(f"• Hard No-Buy       : {hard_no_buy}")
                    logger.debug(f"• Top Risk Score    : {top_risk_pct}%")
                    logger.debug(f"• Near Recent Top   : {near_recent_top}")
                    logger.debug(f"• Valid             : {pattern11}")
                    logger.debug(f"• ========     PATTERN 11 FINAL Score:{match_pct11}%   ===========================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")

                    if pattern11:
                        if not pre.get("notified_pattern_11", False):
                            message = (
                                f"🟠 PATTERN 11 DETECTED\n\n"
                                f"Symbol: {symbol}\n"
                                f"Score: {match_pct11}%\n"
                                f"Regime: {regime}\n"
                                f"RSI: {rsi:.2f}\n"
                                f"Top Risk: {top_risk_pct}%\n"
                                f"Price: {current_price:.6f}"
                            )
                            await send_telegram_message(bot, message)
                            logger.info(f"Pattern 11 TG Notification sent for {symbol} | Score: {match_pct11}%")
                            pre["notified_pattern_11"] = True
                            await save_state()
                    else:
                        if pre.get("notified_pattern_11", False):
                            pre["notified_pattern_11"] = False
                            await save_state()

                    # ==========================================================
                    # PATTERN 12 : Support Spring (Failed Breakdown)
                    # ==========================================================
                    pattern12_score = 0.0

                    logger.debug("=== PATTERN 12 PATTERN 12 PATTERN 12 : Support Spring ===")
                    logger.debug(f"Starting score: {pattern12_score}")

                    ema_max_p7 = max(ema_5, ema_9, ema_21, ema_50)
                    spring_support = support if (support and support > 0) else (current_price * 0.98)
                    wick_through = price_low <= spring_support * 1.001
                    close_back_above = current_price > spring_support * 1.0015
                    spring_ok = wick_through and close_back_above

                    if spring_ok:
                        pattern12_score += 35
                        logger.debug(f"YES | +35 | Spring reclaim | low={price_low:.6f} support={spring_support:.6f} close={current_price:.6f} | Score: {pattern12_score}")
                    else:
                        logger.debug(f"NO  | +0  | Spring reclaim | low={price_low:.6f} support={spring_support:.6f} close={current_price:.6f} wick={wick_through} reclaim={close_back_above} | Score: {pattern12_score}")

                    if is_recent_bounce:
                        pattern12_score += 15
                        logger.debug(f"YES | +15 | Recent bounce flag | Score: {pattern12_score}")
                    else:
                        logger.debug(f"NO  | +0  | Recent bounce flag | Score: {pattern12_score}")

                    if current_volume > avg_volume * 1.15:
                        pattern12_score += 12
                        logger.debug(f"YES | +12 | Spring volume | vol={current_volume:.2f} avg={avg_volume:.2f} | Score: {pattern12_score}")
                    else:
                        logger.debug(f"NO  | +0  | Spring volume | vol={current_volume:.2f} avg={avg_volume:.2f} | Score: {pattern12_score}")

                    if obi_recovery or obi > 0.04:
                        pattern12_score += 12
                        logger.debug(f"YES | +12 | OBI recovery | obi={obi:.4f} recovery={obi_recovery} | Score: {pattern12_score}")
                    else:
                        logger.debug(f"NO  | +0  | OBI recovery | obi={obi:.4f} recovery={obi_recovery} | Score: {pattern12_score}")

                    if rsi > rsi_prev:
                        pattern12_score += 10
                        logger.debug(f"YES | +10 | RSI turning up | rsi={rsi:.2f} prev={rsi_prev:.2f} | Score: {pattern12_score}")
                    else:
                        logger.debug(f"NO  | +0  | RSI turning up | rsi={rsi:.2f} prev={rsi_prev:.2f} | Score: {pattern12_score}")

                    if histogram > prev_histogram:
                        pattern12_score += 10
                        logger.debug(f"YES | +10 | Histogram rising | hist={histogram:.6f} prev={prev_histogram:.6f} | Score: {pattern12_score}")
                    else:
                        logger.debug(f"NO  | +0  | Histogram rising | hist={histogram:.6f} prev={prev_histogram:.6f} | Score: {pattern12_score}")

                    if cvd > prev_cvd:
                        pattern12_score += 8
                        logger.debug(f"YES | +8  | CVD rising | cvd={cvd:.4f} prev={prev_cvd:.4f} | Score: {pattern12_score}")
                    else:
                        logger.debug(f"NO  | +0  | CVD rising | cvd={cvd:.4f} prev={prev_cvd:.4f} | Score: {pattern12_score}")

                    # === PENALTIES ===
                    if near_recent_top:
                        pattern12_score -= 25
                        logger.debug(f"PENALTY | -25 | Near recent top | Score: {pattern12_score}")
                    else:
                        logger.debug(f"NO PENALTY | -0 | Near recent top | Score: {pattern12_score}")

                    if overextended_price:
                        pattern12_score -= 15
                        logger.debug(f"PENALTY | -15 | Overextended above EMA21 | Score: {pattern12_score}")
                    else:
                        logger.debug(f"NO PENALTY | -0 | Overextended above EMA21 | Score: {pattern12_score}")

                    if cvd_change_pct < -12 and obi < -0.15:
                        pattern12_score -= 20
                        logger.debug(f"PENALTY | -20 | Strong bear pressure (CVD+OBI) | cvd%={cvd_change_pct:.2f} obi={obi:.4f} | Score: {pattern12_score}")
                    else:
                        logger.debug(f"NO PENALTY | -0 | Strong bear pressure (CVD+OBI) | Score: {pattern12_score}")

                    if current_price > ema_max_p7 * 1.005:
                        pattern12_score -= 12
                        logger.debug(f"PENALTY | -12 | Already above EMA stack | px={current_price:.6f} ema_max={ema_max_p7:.6f} | Score: {pattern12_score}")
                    else:
                        logger.debug(f"NO PENALTY | -0 | Already above EMA stack | Score: {pattern12_score}")

                    if regime == "reversal_down":
                        pattern12_score -= 15
                        logger.debug(f"PENALTY | -15 | Reversal down regime | regime={regime} | Score: {pattern12_score}")
                    else:
                        logger.debug(f"NO PENALTY | -0 | Reversal down regime | regime={regime} | Score: {pattern12_score}")

                    pattern12_score = max(0, min(100, pattern12_score))
                    match_pct12 = round(pattern12_score)
                    pattern12 = (
                        pattern12_score >= 85 and
                        spring_ok and
                        regime != "compression" and
                        atr_percent >= 0.8 and
                        not hard_no_buy and
                        top_risk_score < 55 and
                        not (near_recent_top and price_extension_pct > 2.0)
                    )

                    logger.debug("=== PATTERN 12 FINAL SUMMARY ===")
                    logger.debug(f"• Spring OK         : {spring_ok} (wick={wick_through} reclaim={close_back_above})")
                    logger.debug(f"• Support used      : {spring_support:.6f}")
                    logger.debug(f"• Regime            : {regime}")
                    logger.debug(f"• Confluence        : {confluence}")
                    logger.debug(f"• Hard No-Buy       : {hard_no_buy}")
                    logger.debug(f"• Top Risk Score    : {top_risk_pct}%")
                    logger.debug(f"• Near Recent Top   : {near_recent_top}")
                    logger.debug(f"• Valid             : {pattern12}")
                    logger.debug(f"• ========     PATTERN 12 FINAL Score:{match_pct12}%   ===========================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")
                    logger.debug(f"• ================================================================================")

                    if pattern12:
                        if not pre.get("notified_pattern_12", False):
                            message = (
                                f"🟤 PATTERN 12 DETECTED\n\n"
                                f"Symbol: {symbol}\n"
                                f"Score: {match_pct12}%\n"
                                f"Regime: {regime}\n"
                                f"Support: {spring_support:.6f}\n"
                                f"Top Risk: {top_risk_pct}%\n"
                                f"Price: {current_price:.6f}"
                            )
                            await send_telegram_message(bot, message)
                            logger.info(f"Pattern 12 TG Notification sent for {symbol} | Score: {match_pct12}%")
                            pre["notified_pattern_12"] = True
                            await save_state()
                    else:
                        if pre.get("notified_pattern_12", False):
                            pre["notified_pattern_12"] = False
                            await save_state()
                
                    # NEW: Flip flag on invalid scan (even gated/idle, for up-down-up unlock)
                    # Extra safety for XRP: price must also have cooled away from recent highs
                    if not any([pattern6, pattern15, pattern9]):
                        if pre.get('deactivation_achieved', False) == False:
                            price_has_cooled = (
                                not near_recent_top and
                                price_extension_pct < 1.8 and
                                current_price < recent_high_5 * 0.985 and    # softer: ~1% below recent high (≈1 ATR on XRP)
                                top_risk_score < 25 and                     # LOW risk level per top detector
                                not hard_no_buy
                            )
                            if price_has_cooled:
                                pre['deactivation_achieved'] = True
                                logger.info(
                                    f"Invalid scan for {symbol}: Flipped flag to True "
                                    f"(lull + price cooled | near_top={near_recent_top}, "
                                    f"ext={price_extension_pct:.2f}%, vs high={((current_price/recent_high_5-1)*100):.2f}%, "
                                    f"top_risk={top_risk_score}%)"
                                )
                            
                                # Telegram notification
                                await send_telegram_message(
                                    bot,
                                    f"✅ DEACTIVATION FLAG SET TO TRUE\n"
                                    f"Pair: {symbol}\n"
                                    f"Reason: Invalid scan + price has cooled\n"
                                    f"• Near recent top: {near_recent_top}\n"
                                    f"• Extension: {price_extension_pct:.2f}%\n"
                                    f"• vs Recent High: {((current_price/recent_high_5-1)*100):.2f}%\n"
                                    f"• Top Risk Score: {top_risk_score}%\n"
                                    f"Flag is now unlocked for future entries."
                                )
                                
                                await save_state()
                            else:
                                logger.debug(
                                    f"Invalid scan for {symbol} but price still elevated "
                                    f"(near_top={near_recent_top}, ext={price_extension_pct:.2f}%, "
                                    f"vs high={((current_price/recent_high_5-1)*100):.2f}%, "
                                    f"top_risk={top_risk_score}%, hard_no_buy={hard_no_buy}) — keeping flag False"
                                )

                    # --- determine regular_contrib (single highest valid pattern only) ---
                    regular_contrib = 0
                    valid_scores = []
                    # gather pattern results (use match_pct6, match_pct15 variables you already computed)
                    try:
                        if 'match_pct6' in locals() and match_pct6 >= 80:
                            valid_scores.append((6, match_pct6))
                        if 'match_pct15' in locals() and match_pct15 >= 80:
                            valid_scores.append((15, match_pct15))
                        if 'match_pct9' in locals() and match_pct9 >= 80:
                            valid_scores.append((9, match_pct9))
                    
                    except Exception:
                        valid_scores = []

                    strongest_pattern_score = 0
                    if valid_scores:
                        top_number, strongest_pattern_score = max(valid_scores, key=lambda x: x[1])
                        regular_contrib = 15
                        logger.debug(f"Pattern-first trigger: pattern {top_number} matched {strongest_pattern_score}% -> regular_contrib=15")
                    else:
                        logger.debug("No qualifying pattern (>=70%) found -> regular_contrib=0")

                    if pre["order_type"] is None:
                        # Early calculation of balances and risk check (available for all patterns)
                        account = await binance_request("GET", "/api/v5/account/balances")
                        quote_balance = 0.0
                        base_balance = 0.0
                        # FIXED: Correctly extract base_asset (handles both '/' and '-' separators, removes any '_SPBL' suffix first)
                        clean_symbol = symbol.replace("_SPBL", "")
                        if '/' in clean_symbol:
                            base_asset = clean_symbol.split('/')[0]
                        elif '-' in clean_symbol:
                            base_asset = clean_symbol.split('-')[0]
                        else:
                            base_asset = clean_symbol
                        for asset in account:
                            if asset["ccy"].upper() == quote_of(symbol):
                                quote_balance = float(asset.get("availBal", "0"))
                            elif asset["ccy"].upper() == base_asset.upper():
                                base_balance = float(asset.get("availBal", "0"))
                        _reserved_base = reserved_base_other_lane(symbol)
                        if _reserved_base > 0:
                            base_balance = max(0.0, base_balance - _reserved_base)

                        floored_quote_balance = math.floor(quote_balance * 100) / 100
                        if floored_quote_balance * 0.95 < min_notional:
                            logger.warning(f"Insufficient {quote_of(symbol)} for {symbol}: available={floored_quote_balance:.2f}, required={min_notional:.2f}")
                            continue  # Skip this symbol entirely if insufficient balance
                    
                        matched_pattern = None    

                        # Exempted Patterns: 22 (independent of base_conditions, ATR thresholds, BTC_IG bearish; 22 exempt from flip)
                        if pattern22:
                            matched_pattern = 22
                            if not pre.get("trailing_dip_active", False):
                                message = (
                                    f"Pattern 22 Triggered\n"
                                    f"{symbol.replace('_SPBL', '')}: Ultra Bearish Rebound (Counter-Trend Dip Buy)"
                                )
                                logger.info(f"STRONG BUY SIGNAL (Pattern 22 - Ultra Bearish Rebound) for {symbol}")
                                logger.info(message)
                                await send_telegram_message(bot, message)
                            else:
                                logger.debug(f"Pattern 22 re-triggered for {symbol}, but trailing-dip active. Suppressing notification.")

                        elif pattern16:
                            matched_pattern = 16
                            if not pre.get("trailing_dip_active", False):
                                message = (
                                    f"Pattern 16 Triggered\n"
                                    f"{symbol.replace('_SPBL', '')}: Super-Trend Bull (Prolonged Bull Entry)"  # FIXED: Correct label
                                )
                                logger.info(f"STRONG BUY SIGNAL (Pattern 16 - Super-Trend Bull) for {symbol}")
                                logger.info(message)
                                await send_telegram_message(bot, message)
                            else:
                                logger.debug(f"Pattern 16 re-triggered for {symbol}, but trailing-dip active. Suppressing notification.")

                        elif pattern18:
                            matched_pattern = 18
                            if not pre.get("trailing_dip_active", False):
                                message = (
                                    f"Pattern 18 Triggered\n"
                                    f"{symbol.replace('_SPBL', '')}: Bearish Rebound Hunter (Mid-Strength Dip Buy)"
                                )
                                logger.info(f"STRONG BUY SIGNAL (Pattern 18 - Bearish Rebound Hunter) for {symbol}")
                                logger.info(message)
                                await send_telegram_message(bot, message)
                            else:
                                logger.debug(f"Pattern 18 re-triggered for {symbol}, but trailing-dip active. Suppressing notification.")

                        elif pattern12:
                            matched_pattern = 12
                            if not pre.get("trailing_dip_active", False):
                                message = (
                                    f"Pattern 12 Triggered\n"
                                    f"{symbol.replace('_SPBL', '')}: Support Spring (Failed Breakdown)"
                                )
                                logger.info(f"STRONG BUY SIGNAL (Pattern 12 - Support Spring) for {symbol}")
                                await send_telegram_message(bot, message)
                            else:
                                logger.debug(f"Pattern 12 re-triggered for {symbol}, but trailing-dip active. Suppressing notification.")

                        elif pattern11:
                            matched_pattern = 11
                            if not pre.get("trailing_dip_active", False):
                                message = (
                                    f"Pattern 11 Triggered\n"
                                    f"{symbol.replace('_SPBL', '')}: Mid-Bear Relief (RSI 26-42)"
                                )
                                logger.info(f"STRONG BUY SIGNAL (Pattern 11 - Mid-Bear Relief) for {symbol}")
                                await send_telegram_message(bot, message)
                            else:
                                logger.debug(f"Pattern 11 re-triggered for {symbol}, but trailing-dip active. Suppressing notification.")
                    
                        # Regular Patterns: Subject to base conditions, ATR thresholds, BTC_IG bearish; exempted from BTC_IG flip
                        if btc_ig != 'bearish':
                            # --- PATTERN-FIRST Decision Logic (Option A: Surfer Model) ---
                            pre['buy_signal_ready'] = False
                            base_conditions = False

                            if regular_contrib == 15:
                                # ====================== ULTIMATE TOP DETECTOR VETO ======================
                                if hard_no_buy or top_risk_score >= 55:
                                    logger.warning(f"ULTIMATE TOP DETECTOR BLOCKED buy for {symbol} "
                                                 f"(Risk={top_risk_score}%, HardNoBuy={hard_no_buy}, "
                                                 f"Pattern={strongest_pattern_score}%)")
                                    pre['buy_signal_ready'] = False
                                    base_conditions = False
                                    reason = "ULTIMATE TOP DETECTOR veto"
                                else:
                                    # Normal pattern logic only runs if Top Detector is clear
                                    total_score = confluence + regular_contrib
                                    threshold = 45 if atr_percent < 2 else 35
                                    logger.debug(f"Confluence threshold for {symbol}: {threshold} (ATR%: {atr_percent:.2f})")
                                    logger.debug(f"Pattern-first: total_score={total_score}, threshold={threshold}, confluence={confluence}, strongest_pattern={strongest_pattern_score}")

                                    if confluence >= min_tier_score:
                                        if total_score >= threshold:
                                            pre['buy_signal_ready'] = True
                                            base_conditions = True
                                            reason = "pattern + tiers (strict pass)"
                                        else:
                                            if total_score >= (threshold - 10) and (full_ema_stack and trend_strength_proxy > 0.25):
                                                pre['buy_signal_ready'] = True
                                                base_conditions = True
                                                reason = "pattern + tiers (soft pass: trend/EMA rescue)"
                                            else:
                                                pre['buy_signal_ready'] = False
                                                base_conditions = False
                                                reason = "pattern + tiers (short by points)"
                                    else:
                                        if strongest_pattern_score >= 80 and confluence >= ema_rescue_min and full_ema_stack:
                                            pre['buy_signal_ready'] = True
                                            base_conditions = True
                                            reason = "very strong pattern + EMA rescue"
                                        else:
                                            pre['buy_signal_ready'] = False
                                            base_conditions = False
                                            reason = "insufficient tier validation"

                                # Log decision (always runs when regular_contrib == 15)
                                logger.info(f"Pattern-first decision for {symbol}: buy_ready={pre['buy_signal_ready']} "
                                          f"(reason={reason}, total={total_score if 'total_score' in locals() else 0}, "
                                          f"confluence={confluence}, pattern={strongest_pattern_score})")
                            else:
                                logger.debug(f"No pattern-first trigger for {symbol} -> buy blocked. confluence={confluence}")
                                pre['buy_signal_ready'] = False
                                base_conditions = False

                            # Position sizing hint (only when buy_signal_ready True)
                            if pre['buy_signal_ready']:
                                # Compatibility: Set matched_pattern here to trigger downstream activation (trailing_dip_active=True, dip_level set)
                                matched_pattern = top_number  # Use strongest pattern (e.g., 15) - Tag for old flow
                                pre['entry_pattern'] = matched_pattern  # For targets/logging

                                risk_per_trade = 0.01  # 1% risk
                                account_balance = floored_quote_balance  # Use fresh from API (updated for real-time)
                                atr_value = indicators.get('atr', current_price * 0.01)
                                suggested_size = (account_balance * risk_per_trade) / (atr_value * 2)
                                logger.info(f"Base Conditions Met: Confluence {confluence + regular_contrib}/100, Suggested Size: {suggested_size:.4f} units")

                                # Check regular patterns in order of profitability (moved inside for gating; old flow compatibility)
                                if pattern15:
                                    matched_pattern = 15
                                    if not pre.get("trailing_dip_active", False):
                                        # NEW: Gate for deactivation (inline, no func)
                                        deactivation_achieved = pre.get('deactivation_achieved', False)
                                        if deactivation_achieved:
                                            # Ungated: Fire normally
                                            message = (
                                                f"Pattern 15 Triggered\n"
                                                f"{symbol.replace('_SPBL', '')}: Momentum Acceleration"
                                            )
                                            logger.info(f"STRONG BUY SIGNAL (Pattern 15 - Momentum Acceleration) for {symbol}")
                                            logger.info(message)
                                            await send_telegram_message(bot, message)
                                        else:
                                            # Gated: Cooldown (120min/symbol)
                                            alert_cooldown_key = f"{symbol}_alert_cooldown"
                                            last_alert_time = pre.get(alert_cooldown_key, 0)
                                            if time.time() - last_alert_time >= 7200:  # 7200s = 120min
                                                pre[alert_cooldown_key] = time.time()
                                                await save_state()  # Persist cooldown
                                                message = (
                                                    f"Pattern 15 Triggered\n"
                                                    f"{symbol.replace('_SPBL', '')}: Momentum Acceleration But Tdip Gate Active"
                                                )
                                                logger.info(f"STRONG BUY SIGNAL (Pattern 15 - Momentum Acceleration) for {symbol}")
                                                logger.info(message)
                                                await send_telegram_message(bot, message)
                                            else:
                                                logger.debug(f"Pattern 15 alert skipped for {symbol}: Gated + cooldown active")
                                    else:
                                        logger.debug(f"Pattern 15 re-triggered for {symbol}, but trailing-dip active. Suppressing notification.")

                                elif pattern6:
                                    matched_pattern = 6
                                    if not pre.get("trailing_dip_active", False):
                                        # NEW: Gate for deactivation (inline, no func)
                                        deactivation_achieved = pre.get('deactivation_achieved', False)
                                        if deactivation_achieved:
                                            # Ungated: Fire normally
                                            message = (
                                                f"Pattern 6 Triggered\n"
                                                f"{symbol.replace('_SPBL', '')}: EMA Momentum Alignment"
                                            )
                                            logger.info(f"STRONG BUY SIGNAL (Pattern 6 - EMA Momentum Alignment) for {symbol}")
                                            logger.info(message)
                                            await send_telegram_message(bot, message)
                                        else:
                                            # Gated: Cooldown (120min/symbol)
                                            alert_cooldown_key = f"{symbol}_alert_cooldown"
                                            last_alert_time = pre.get(alert_cooldown_key, 0)
                                            if time.time() - last_alert_time >= 7200:  # 7200s = 120min
                                                pre[alert_cooldown_key] = time.time()
                                                await save_state()  # Persist cooldown
                                                message = (
                                                    f"Pattern 6 Triggered\n"
                                                    f"{symbol.replace('_SPBL', '')}: EMA Momentum Alignment But Tdip Gate Active"
                                                )
                                                logger.info(f"STRONG BUY SIGNAL (Pattern 6 - EMA Momentum Alignment) for {symbol}")
                                                logger.info(message)
                                                await send_telegram_message(bot, message)
                                            else:
                                                logger.debug(f"Pattern 6 alert skipped for {symbol}: Gated + cooldown active")
                                    else:
                                        logger.debug(f"Pattern 6 re-triggered for {symbol}, but trailing-dip active. Suppressing notification.")

                                elif pattern9:
                                    matched_pattern = 9
                                    if not pre.get("trailing_dip_active", False):
                                        # NEW: Gate for deactivation (inline, no func)
                                        deactivation_achieved = pre.get('deactivation_achieved', False)
                                        if deactivation_achieved:
                                            # Ungated: Fire normally
                                            message = (
                                                f"Pattern 9 Triggered\n"
                                                f"{symbol.replace('_SPBL', '')}: VWAP Reclaim"
                                            )
                                            logger.info(f"STRONG BUY SIGNAL (Pattern 9 - VWAP Reclaim) for {symbol}")
                                            logger.info(message)
                                            await send_telegram_message(bot, message)
                                        else:
                                            # Gated: Cooldown (120min/symbol)
                                            alert_cooldown_key = f"{symbol}_alert_cooldown"
                                            last_alert_time = pre.get(alert_cooldown_key, 0)
                                            if time.time() - last_alert_time >= 7200:  # 7200s = 120min
                                                pre[alert_cooldown_key] = time.time()
                                                await save_state()  # Persist cooldown
                                                message = (
                                                    f"Pattern 9 Triggered\n"
                                                    f"{symbol.replace('_SPBL', '')}: VWAP Reclaim But Tdip Gate Active"
                                                )
                                                logger.info(f"STRONG BUY SIGNAL (Pattern 9 - VWAP Reclaim) for {symbol}")
                                                logger.info(message)
                                                await send_telegram_message(bot, message)
                                            else:
                                                logger.debug(f"Pattern 9 alert skipped for {symbol}: Gated + cooldown active")
                                    else:
                                        logger.debug(f"Pattern 9 re-triggered for {symbol}, but trailing-dip active. Suppressing notification.")

                             

                            else:
                                # Helpful debug: how many points short were we for threshold (if pattern existed)
                                if regular_contrib == 15 and not (hard_no_buy or top_risk_score >= 55):
                                    total_score = confluence + regular_contrib
                                    threshold = 55 if atr_percent < 2 else 45
                                    short_by = max(0, threshold - total_score)
                                    logger.debug(f"Buy NOT triggered for {symbol}: total={total_score}, threshold={threshold}, short_by={short_by}")
                        else:
                            logger.debug(f"Regular patterns blocked for {symbol}: BTC_IG bearish ({btc_ig})")


                        # Dynamic bearish news blocks bull-trend entries only.
                        # p11, p12, p18, p22 still buy. p6 / p15 / p16 wait.
                        if matched_pattern in (6, 15, 16) and pre.get("csi_dynamic_bear"):
                            logger.warning(
                                f"CSI SHOCK BLOCKED P{matched_pattern} for {symbol} | "
                                f"csi={pre.get('csi', 0):.2f} tag={pre.get('csi_tag') or '-'}"
                            )
                            if not pre.get("csi_block_logged"):
                                await send_telegram_message(
                                    bot,
                                    f"CSI SHOCK BLOCK\n"
                                    f"{symbol}: P{matched_pattern} refused\n"
                                    f"News {pre.get('csi', 0):.2f} ({pre.get('csi_tag') or 'shock'})\n"
                                    f"Bull-trend entry closed. Bear patterns p11 / p18 / p22 still allowed."
                                )
                                pre["csi_block_logged"] = True
                            matched_pattern = None
                            
                        # PLACE ORDER FOR ANY TRIGGERED PATTERN (New Pattern Init Only)
                        if matched_pattern is not None:
                            # Store pattern type for target calculation
                            pre['entry_pattern'] = matched_pattern
                            await save_state()

                            # FIXED: Additional vars needed for buy execution (with safeguards)
                            rsi = indicators.get('rsi') or 50.0  # FIXED: Neutral default if None
                            momentum_factor = rsi / 100 if rsi else 0.0  # Already safe
                            fib_extensions = indicators.get('fib_levels', {}) or {}  # FIXED: Force {} if None
                            # FIXED: Strip any None values from fib dict (prevents downstream None * float)
                            fib_extensions = {k: v for k, v in fib_extensions.items() if v is not None}
                            atr = indicators.get('atr') or 0.0  # FIXED: Zero default
                            # FIXED: Debug log for init indicators (check if Nones persist)
                            logger.debug(f"Init indicators for {symbol} - rsi:{rsi} ({type(rsi).__name__}), atr:{atr} ({type(atr).__name__}), fib_extensions:{fib_extensions} ({type(fib_extensions).__name__})")
                        

                            # Initialize Trailing-Dip on first trigger (if not already active)
                            if not pre.get("trailing_dip_active", False):
                                # Calculate initial dip_distance 
                            
                                # === PATTERN-SPECIFIC TDIP DISTANCE (init) ===
                                tdip_cfg = {
                                    15: {"atr_mult": 0.30, "min_pct": 0.0030, "cap_pct": 0.0045, "vol_hi": 1.08, "vol_lo": 0.85, "name": "P15-TIGHT"},
                                     6: {"atr_mult": 0.35, "min_pct": 0.0035, "cap_pct": 0.0055, "vol_hi": 1.10, "vol_lo": 0.85, "name": "P6-TIGHT"},
                                    16: {"atr_mult": 0.25, "min_pct": 0.0025, "cap_pct": 0.0040, "vol_hi": 1.05, "vol_lo": 0.90, "name": "P16-SNAP"},
                                     9: {"atr_mult": 0.50, "min_pct": 0.0045, "cap_pct": 0.0080, "vol_hi": 1.15, "vol_lo": 0.90, "name": "P9-VWAP"},
                                    12: {"atr_mult": 0.65, "min_pct": 0.0060, "cap_pct": 0.0110, "vol_hi": 1.15, "vol_lo": 0.90, "name": "P12-SPRING"},
                                    11: {"atr_mult": 0.70, "min_pct": 0.0070, "cap_pct": 0.0120, "vol_hi": 1.15, "vol_lo": 0.95, "name": "P11-RELIEF"},
                                    18: {"atr_mult": 0.80, "min_pct": 0.0080, "cap_pct": 0.0140, "vol_hi": 1.18, "vol_lo": 1.00, "name": "P18-WIDE"},
                                    22: {"atr_mult": 1.00, "min_pct": 0.0100, "cap_pct": 0.0180, "vol_hi": 1.20, "vol_lo": 1.00, "name": "P22-CRASH"},
                                }
                                cfg = tdip_cfg.get(matched_pattern, tdip_cfg[18])
                                atr_safe = float(atr) if atr else 0.0

                                min_dip_distance = max(atr_safe * cfg["atr_mult"], current_price * cfg["min_pct"]) if current_price else current_price * 0.01
                                dip_distance = min_dip_distance

                                vol_index = indicators.get('volatility_index', 0) or 0
                                if vol_index > 50:
                                    dip_distance *= cfg["vol_hi"]
                                elif vol_index < 20:
                                    dip_distance *= cfg["vol_lo"]

                                dip_distance = max(dip_distance, current_price * cfg["min_pct"])
                                dip_distance = min(dip_distance, current_price * cfg["cap_pct"])

                                pre["tdip_profile"] = cfg["name"]
                                logger.info(
                                    f"Tdip INIT {symbol} | Pattern {matched_pattern} {cfg['name']} | "
                                    f"Dist {dip_distance:.8f} ({dip_distance/current_price*100:.2f}%) | "
                                    f"ATR {atr_safe:.6f} | vol_index {vol_index:.1f}"
                                )

                                initial_dip_level = current_price + dip_distance

                                # NEW: Basic deactivation gate for Tdip activation
                                deactivation_achieved = pre.get('deactivation_achieved', False)
                                is_pattern22 = matched_pattern == 22
                                is_pattern16 = matched_pattern == 16  # NEW: Exemption for Pattern 16
                                is_pattern18 = matched_pattern == 18
                                is_pattern11 = matched_pattern == 11
                                is_pattern12 = matched_pattern == 12
                                if not (deactivation_achieved or is_pattern22 or is_pattern16 or is_pattern18 or is_pattern11 or is_pattern12):
                                    logger.info(f"Tdip activation gated for {symbol}: Awaiting deactivation (patterns valid but flag=False)")
                                    continue  # Skip activation until gate passes

                                # Reset flag on activation (for next cycle)
                                pre['deactivation_achieved'] = False
                            
                                pre["trailing_dip_active"] = True  
                                pre["dip_level"] = initial_dip_level
                                pre["dip_distance"] = dip_distance
                                pre["dip_tightening_time"] = time.time()  # For cooldown
                                pre["original_trigger_price"] = current_price  # For fallback
                                pre["dip_occurred"] = False  # New: Track if dip happened (for optional tightening/logging)

                                # NEW: Lock the confirmation mode to the pattern that first activated trailing-dip
                                # This will be used forever for this cycle (one-way ratchet possible later)
                                pre["confirmation_mode_locked"] = matched_pattern  # 18 or 22
                                logger.debug(f"Locked confirmation mode to {matched_pattern} for {symbol} on trailing-dip activation")
                                await save_state()

                                # safe format helper (avoid None formatting errors)
                                def _fmt(x, p=8):
                                    return f"{x:.{p}f}" if (x is not None) else "N/A"

                                message = (
                                    f"Trailing-Dip Activated (Pattern {matched_pattern} / {pre.get('tdip_profile', '')})\n"
                                    f"{symbol.replace('_SPBL', '')}: Waiting for rebound\n"
                                    f"Initial Dip Level: {initial_dip_level:.8f}\n"
                                    f"Distance: {dip_distance:.8f} ({dip_distance/current_price*100:.2f}%)\n"
                                )
                                logger.info(f"Trailing-Dip initialized for {symbol} (Pattern {matched_pattern})")
                                await send_telegram_message(bot, message)
                                await save_state()
                                continue  # Skip immediate buy on init, enter monitoring

                        # CONTINUOUS TRAILING-DIP MONITORING
                        if pre.get("trailing_dip_active", False):
                            # Safe format for dip_level
                            dip_level_safe = pre.get('dip_level')
                            dip_level_fmt = f"{dip_level_safe:.8f}" if isinstance(dip_level_safe, (int, float)) else str(dip_level_safe)
                            logger.debug(f"Trailing-Dip monitoring {symbol}: price={current_price:.8f}, dip_level={dip_level_fmt}, occurred={pre.get('dip_occurred', False)}")
                        
                            # --- UPDATED Deactivation if triggering pattern invalid and no other ---
                            keep_trailing = False  # Default to deact (defensive)
                            try:
                                keep_trailing = await check_active_patterns(symbol, indicators, current_price, pre, strict_for_execution=False)
                                if not keep_trailing:
                                    logger.info(f"Trailing-Dip deactivated for {symbol}: confluence too low and no other buy pattern active.")

                                    # NEW: Set deactivation flag on full invalidation
                                    pre['deactivation_achieved'] = True
                                    logger.info(f"Deactivation achieved for {symbol}: Flag set to True for future Tdip activations")

                                    # NEW: Telegram notification (add this line here)
                                    await send_telegram_message(bot, f"Trailing-Dip Deactivated for {symbol.replace('_SPBL', '')}\nReason: confluence too low, no other buy signals active.\nResuming new pattern scan.")
                                
                                    pre["trailing_dip_active"] = False
                                    pre["dip_level"] = None
                                    pre["dip_distance"] = None
                                    pre["dip_occurred"] = False
                                    pre["dip_tightening_time"] = 0
                                    pre["original_trigger_price"] = None
                                    pre["entry_pattern"] = None  # Clear stale pattern

                                    # NEW: Cleanup confirmation lock on deactivation
                                    if "confirmation_mode_locked" in pre:
                                        del pre["confirmation_mode_locked"]

                                    # Ensure mandatory keys
                                    for key, default in [("order_type", None), ("amount", 0), ("entry_price", 0), 
                                                         ("primary_target", 0), ("secondary_target", 0), ("stop_loss", 0),
                                                         ("trailing_stop", 0), ("trailing_distance", 0)]:
                                        pre.setdefault(key, default)
                                    await save_state()
                                    continue
                        
                            except Exception as e:
                                logger.error(f"Trailing-dip pattern recheck failed for {symbol}: {e} (defaulting to deactivate)")
                                pre["trailing_dip_active"] = False
                                # Clear fields (add your full clear code here if more keys)
                                if "confirmation_mode_locked" in pre:
                                    del pre["confirmation_mode_locked"]
                                await save_state()
                                continue

                            # Pre-buy risk check for monitoring buys
                            if floored_quote_balance * 0.95 < min_notional:
                                logger.warning(f"Insufficient {quote_of(symbol)} during monitoring for {symbol}: available={floored_quote_balance:.2f}, required={min_notional:.2f}")
                                # Optionally deactivate if balance too low
                                pre["trailing_dip_active"] = False
                                if "confirmation_mode_locked" in pre:
                                    del pre["confirmation_mode_locked"]
                                await save_state()
                                continue

                            # FIXED: Additional vars needed for buy execution in monitoring (enhanced safeguards)
                            rsi = indicators.get('rsi') or 50.0  # FIXED: Neutral default
                            momentum_factor = float(rsi / 100) if rsi else 0.0  # FIXED: Ensure float
                            fib_extensions = indicators.get('fib_levels', {}) or {}  # FIXED: Force {} if None (key fix!)
                            # FIXED: Strip any None values from fib dict (prevents None * float in calculate_targets)
                            fib_extensions = {k: float(v) if v is not None else 1.618 for k, v in fib_extensions.items()}  # Default to golden ratio if None
                            atr = indicators.get('atr') or 0.0  # FIXED: Zero default
                            atr_percent = (float(atr) / current_price * 100) if atr and current_price else 0.0  # FIXED: float() ensure

                            # FIXED: Continuous Dip Detection & Ratchet (runs every time price < original_trigger_price, but ratchet only on new lows)
                            # Repurpose dip_occurred: set on first dip for logging, but allow ongoing ratcheting if current_price < current dip_level (new low relative to buy zone)
                            if current_price < pre["original_trigger_price"]:
                                if not pre.get("dip_occurred", False):
                                    pre["dip_occurred"] = True
                                    logger.info(f"Dip detected for {symbol}: price {current_price:.8f} < trigger {pre['original_trigger_price']:.8f}")
                            
                                # Always calculate candidate based on current price (produces an ABOVE-price candidate; ratchet only if lower than present dip_level)
                                candidate_dip_level = current_price + pre["dip_distance"]

                                # Only ratchet dip_level lower (never raise it)
                                if candidate_dip_level < pre.get("dip_level", float("inf")):
                                    pre["dip_level"] = candidate_dip_level
                                    logger.debug(f"Trailing-Dip updated (ratcheted down) for {symbol}: new_level={pre['dip_level']:.8f} (price {current_price:.8f})")
                                    await save_state()

                            # === PATTERN-SPECIFIC TDIP RUNTIME ADJUST ===
                            tdip_rt = {
                                15: {"loosen": 1.03, "tighten": 0.88, "max_pct": 0.0060, "rsi_guard": None,           "allow_hi_vol_loosen": False, "name": "P15-TIGHT"},
                                 6: {"loosen": 1.04, "tighten": 0.90, "max_pct": 0.0070, "rsi_guard": None,           "allow_hi_vol_loosen": False, "name": "P6-TIGHT"},
                                16: {"loosen": 1.03, "tighten": 0.90, "max_pct": 0.0050, "rsi_guard": None,           "allow_hi_vol_loosen": False, "name": "P16-SNAP"},
                                 9: {"loosen": 1.07, "tighten": 0.92, "max_pct": 0.0100, "rsi_guard": None,           "allow_hi_vol_loosen": True,  "name": "P9-VWAP"},
                                12: {"loosen": 1.08, "tighten": 0.93, "max_pct": 0.0130, "rsi_guard": (32, 0.0110),   "allow_hi_vol_loosen": True,  "name": "P12-SPRING"},
                                11: {"loosen": 1.09, "tighten": 0.94, "max_pct": 0.0150, "rsi_guard": (30, 0.0120),   "allow_hi_vol_loosen": True,  "name": "P11-RELIEF"},
                                18: {"loosen": 1.09, "tighten": 0.95, "max_pct": 0.0160, "rsi_guard": (28, 0.0130),   "allow_hi_vol_loosen": True,  "name": "P18-WIDE"},
                                22: {"loosen": 1.12, "tighten": 1.00, "max_pct": 0.0220, "rsi_guard": (20, 0.0160),   "allow_hi_vol_loosen": True,  "name": "P22-CRASH"},
                            }
                            rt_pat = pre.get("confirmation_mode_locked") or pre.get("entry_pattern") or 18
                            rt = tdip_rt.get(rt_pat, tdip_rt[18])

                            tdip_floor = {
                                15: 0.0030, 6: 0.0035, 16: 0.0025, 3: 0.0040, 7: 0.0040,
                                 9: 0.0045, 12: 0.0060, 11: 0.0070, 18: 0.0080, 22: 0.0100,
                            }
                            min_dip_distance = max(
                                current_price * tdip_floor.get(rt_pat, 0.0080),
                                (float(atr) * 0.25 if atr else 0.0)
                            )

                            if (current_price < pre.get("last_price", current_price) and
                                pre["dip_distance"] > min_dip_distance):

                                atr_percent = (indicators.get("atr", 0) / current_price * 100) if current_price > 0 else 0.0

                                if atr_percent > 8.0:
                                    cooldown = 90
                                elif atr_percent > 6.5:
                                    cooldown = 150
                                elif atr_percent > 5.0:
                                    cooldown = 300
                                elif atr_percent > 3.5:
                                    cooldown = 600
                                else:
                                    cooldown = 1800

                                last_adjust = pre.get("dip_tightening_time", 0)
                                if time.time() - last_adjust <= cooldown:
                                    pass
                                else:
                                    rsi = indicators.get("rsi", 50)
                                    bb_width = indicators.get("bb_width", 0.02)
                                    adjustment_type = None

                                    # Trend patterns: high vol at highs = trap, do NOT give more room
                                    hi_vol = atr_percent > 5.8 or (atr_percent > 4.2 and bb_width > 0.028)
                                    lo_vol = atr_percent < 2.9 and bb_width < 0.022
                                    chasing_high = bool(near_recent_top) if 'near_recent_top' in locals() else False

                                    if hi_vol and rt["allow_hi_vol_loosen"] and not chasing_high:
                                        pre["dip_distance"] *= rt["loosen"]
                                        pre["dip_distance"] = min(pre["dip_distance"], current_price * rt["max_pct"])
                                        adjustment_type = f"loosened (high vol / {rt['name']})"

                                    elif lo_vol and rt["tighten"] < 1.0:
                                        pre["dip_distance"] *= rt["tighten"]
                                        pre["dip_distance"] = max(pre["dip_distance"], min_dip_distance)
                                        adjustment_type = f"tightened (low vol grind / {rt['name']})"

                                    # Crash/rebound only — never widen 6/15/3/7 into a knife
                                    if rt["rsi_guard"] is not None:
                                        rsi_lvl, rsi_floor_pct = rt["rsi_guard"]
                                        if rsi < rsi_lvl:
                                            pre["dip_distance"] = max(pre["dip_distance"], current_price * rsi_floor_pct)
                                            if adjustment_type is None or "loosened" not in str(adjustment_type):
                                                adjustment_type = f"loosened (RSI<{rsi_lvl} guard / {rt['name']})"

                                    pre["dip_distance"] = max(pre["dip_distance"], min_dip_distance)
                                    pre["dip_distance"] = min(pre["dip_distance"], current_price * rt["max_pct"])

                                    if adjustment_type:
                                        pre["dip_tightening_time"] = time.time()
                                        candidate_dip_level = current_price + pre["dip_distance"]
                                        if candidate_dip_level < pre.get("dip_level", float("inf")):
                                            pre["dip_level"] = candidate_dip_level

                                        logger.info(
                                            f"Trailing-Dip {adjustment_type} for {symbol} | "
                                            f"ATR% {atr_percent:.2f} | BBw {bb_width:.4f} | RSI {rsi:.1f} | "
                                            f"Cooldown {cooldown}s | "
                                            f"Distance {pre['dip_distance']:.6f} ({pre['dip_distance']/current_price*100:.2f}%) | "
                                            f"Level {pre['dip_level']:.6f}"
                                        )
                                        await save_state()

                            # === 2025 UNIFIED TRAILING-DIP ENTRY – PATTERN-SPECIFIC CONFIRMATION ===
                            if (pre.get("trailing_dip_active", False) and 
                                pre.get("dip_level") is not None and 
                                current_price >= pre["dip_level"] and
                                not pre.get("dip_buy_executed", False)):

                                dip_level = pre["dip_level"]
                                entry_pattern = pre.get("entry_pattern", 18)  # default to 18 for safety on dips
                                btc_ig = pre.get("btc_ig", "N/A")

                                # ── 1. Quick escape: price ran away without confirmation ──
                                # XRP-optimized volatility adaptive escape logic
                                # (ATR% already calculated earlier)

                                escape_map_hi = {15: 1.009, 6: 1.010, 16: 1.008, 3: 1.010, 7: 1.011, 9: 1.012, 12: 1.014, 11: 1.015, 18: 1.015, 22: 1.018}
                                escape_map_lo = {15: 1.008, 6: 1.008, 16: 1.007, 3: 1.009, 7: 1.010, 9: 1.012, 12: 1.013, 11: 1.014, 18: 1.014, 22: 1.017}
                                if atr_percent >= 1:
                                    escape_threshold = dip_level * escape_map_hi.get(entry_pattern, 1.012)
                                else:
                                    escape_threshold = dip_level * escape_map_lo.get(entry_pattern, 1.012)

                                if current_price >= escape_threshold:
                                    logger.warning(f"TRAILING-DIP ESCAPED {symbol} | price {current_price:.8f} ≥ {escape_threshold:.8f} "
                                                   f"({(escape_threshold / dip_level - 1) * 100:.1f}%) without confirmation >> deactivating")
                                    message = (
                                        f"Trailing-Dip Deactivated (Escape)\n"
                                        f"{symbol.replace('_SPBL', '')}: Price ran to {current_price:.8f} "
                                        f"(> +{(escape_threshold / dip_level - 1) * 100:.1f}% from dip {dip_level:.8f}) without strong confirmation"
                                    )
                                    await send_telegram_message(bot, message)

                                    pre["trailing_dip_active"] = False
                                    pre["dip_level"] = None
                                    pre["dip_distance"] = None
                                    pre["dip_occurred"] = False
                                    pre["dip_buy_executed"] = False
                                    pre["original_trigger_price"] = None
                                    if "confirmation_mode_locked" in pre:
                                        del pre["confirmation_mode_locked"]
                                    await save_state()
                                    continue

                                # === ROBUST CONFIRMATION MODE LOGIC - Handles all switches ===
                                confirmation_mode = pre.get("confirmation_mode_locked", entry_pattern)

                                # Allow normal pattern switches (6>>15, 6>>18, 15>>18, 6/15>>22, 18>>22)
                                if entry_pattern != confirmation_mode:
                                    if confirmation_mode == 18 and entry_pattern == 22:
                                        # One-way ratchet only: 18 >> 22 (more permissive)
                                        confirmation_mode = 22
                                        pre["confirmation_mode_locked"] = 22
                                        logger.info(f"Confirmation mode ratcheted 18>>22 for {symbol}")
                                    else:
                                        # Normal switch (including 6>>15 and 15>>18)
                                        confirmation_mode = entry_pattern
                                        pre["confirmation_mode_locked"] = entry_pattern
                                        logger.info(f"Confirmation mode updated {symbol}: {pre.get('confirmation_mode_locked')} >> {entry_pattern} (market conditions changed)")

                                logger.debug(f"Using confirmation_mode = {confirmation_mode} for {symbol} (entry_pattern = {entry_pattern})")

                                # Safe fallback if unknown mode
                                if confirmation_mode not in [6, 15, 18, 22, 9, 11, 12, 16]:
                                    confirmation_mode = 18
                                    logger.warning(f"Unknown confirmation_mode for {symbol} >> defaulting to Pattern 18 (safe fallback)")

                                logger.debug(f"Using confirmation_mode = {confirmation_mode} (entry_pattern = {entry_pattern}) for {symbol}")

                                # ── 2. Pattern-specific confirmation logic ──

                                confirmation_ok = False
                                reason = "no confirmation"
                            
                                # === PATTERN 16 CONFIRMATION BLOCK ===
                                if confirmation_mode == 16:
                                    confirmation_ok = True
                                    reason = "Pattern 16 – Super-Power Rally (no confirmation required)"
                                    logger.info(f"Pattern 16 confirmation OK for {symbol} – no check needed")
                                    await send_telegram_message(bot, f"✅ Pattern 16 activated on {symbol} – immediate entry allowed (no confirmation)")

                                # === PATTERN 6 CONFIRMATION BLOCK ===
                                elif confirmation_mode == 6:
                                    btc_filter_ok = (btc_ig != 'bearish')
                                    top_detector_ok = not (hard_no_buy or top_risk_score >= 55)

                                    result = await check_active_patterns(
                                        symbol=symbol,
                                        indicators=indicators,
                                        current_price=current_price,
                                        pre=pre,
                                        strict_for_execution=True
                                    )

                                    if isinstance(result, dict):
                                        pattern_alive = result.get('active', False)
                                        tier1_ok = result.get('tier1_active', False)
                                        confluence = result.get('confluence', 0)
                                        pattern_score = result.get('pattern_score', 0)

                                        ema_stack_ok = (ema_9 > ema_21 > ema_50) or \
                                                       (ema_5 > ema_9 > ema_13 > ema_21 and ema_21 > ema_50 * 0.995)
                                        macd_bullish = macd_line > signal_line
                                        # Tdip-compatible: hold TREND averages, allow dip into EMA5/9
                                        structure_hold = (current_price > ema_21 * 0.997) and (current_price > ema_50 * 0.995)
                                        no_bear_pressure = not (cvd_change_pct < -12 and obi < -0.12)
                                        rsi_healthy = 46 < rsi < 72
                                        hist_not_dying = (
                                            (prev_histogram is None) or
                                            (histogram >= prev_histogram * 0.88) or
                                            (histogram > 0)
                                        )
                                        not_buying_the_high = not (near_recent_top and rsi >= 68)

                                        key_conditions_ok = (
                                            ema_stack_ok and
                                            macd_bullish and
                                            structure_hold and
                                            no_bear_pressure and
                                            rsi_healthy and
                                            hist_not_dying and
                                            not_buying_the_high
                                        )

                                        # Efficiency: tier1 preferred; clean stack + confluence is enough
                                        base_ok = pattern_alive and pattern6 and (tier1_ok or confluence >= 32)

                                        confirmation_ok = (
                                            base_ok and key_conditions_ok and
                                            btc_filter_ok and top_detector_ok
                                        )

                                        reason = (
                                            f"Pattern 6 Confirmation >> alive={pattern_alive}, "
                                            f"tier1={tier1_ok}, confluence={confluence:.0f}, "
                                            f"pattern_score={pattern_score}, key={key_conditions_ok}, "
                                            f"stack={ema_stack_ok}, macd={macd_bullish}, "
                                            f"structure={structure_hold}, rsi_ok={rsi_healthy}, "
                                            f"hist_ok={hist_not_dying}, not_high={not_buying_the_high}, "
                                            f"BTC_ok={btc_filter_ok}, Top_ok={top_detector_ok} "
                                            f"(Risk={top_risk_score}%, HardNoBuy={hard_no_buy})"
                                        )
                                    else:
                                        confirmation_ok = bool(result)
                                        reason = "Pattern 6 – basic fallback check"

                                    if confirmation_ok:
                                        logger.info(f"Pattern 6 confirmation SUCCESS for {symbol} – {reason}")
                                        await send_telegram_message(
                                            bot,
                                            f"✅ Pattern 6 confirmed on {symbol} – stack held + Tdip structure >> ready to buy"
                                        )
                                    else:
                                        logger.warning(f"Pattern 6 confirmation FAILED for {symbol} – {reason}")

                                # === PATTERN 15 CONFIRMATION BLOCK ===
                                elif confirmation_mode == 15:
                                    top_detector_ok = not (hard_no_buy or top_risk_score >= 55)

                                    result = await check_active_patterns(
                                        symbol=symbol,
                                        indicators=indicators,
                                        current_price=current_price,
                                        pre=pre,
                                        strict_for_execution=True
                                    )

                                    if isinstance(result, dict):
                                        pattern_alive = result.get('active', False)
                                        tier1_ok = result.get('tier1_active', False)
                                        confluence = result.get('confluence', 0)
                                        pattern_score = result.get('pattern_score', 0)

                                        # Impulse already printed at trigger. Fill only if it is NOT reversing.
                                        rsi_not_fading = (rsi_prev is None) or (rsi >= rsi_prev - 0.8)
                                        hist_not_fading = (
                                            (prev_histogram is None) or
                                            (histogram >= prev_histogram * 0.90) or
                                            (histogram > 0)
                                        )
                                        price_hold = current_price > ema_21 * 0.996 if ema_21 else False
                                        no_bear_pressure = not (cvd_change_pct < -12 and obi < -0.12)
                                        not_overhot = rsi < 73 and not (near_recent_top and rsi >= 70)
                                        expansion_still = True
                                        if 'bb_width_proxy' in locals() and 'atr_threshold' in locals():
                                            expansion_still = (bb_width_proxy > 0.013) and (atr_percent > atr_threshold * 0.55)

                                        impulse_remnants = sum([
                                            rsi > rsi_prev if rsi_prev is not None else False,
                                            macd_line > prev_macd if prev_macd is not None else False,
                                            histogram > prev_histogram if prev_histogram is not None else False
                                        ])

                                        key_conditions_ok = (
                                            rsi_not_fading and
                                            hist_not_fading and
                                            price_hold and
                                            no_bear_pressure and
                                            not_overhot and
                                            expansion_still and
                                            impulse_remnants >= 2
                                        )

                                        base_ok = pattern_alive and pattern15 and (tier1_ok or confluence >= 32)
                                        confirmation_ok = base_ok and key_conditions_ok and top_detector_ok

                                        reason = (
                                            f"Pattern 15 Confirmation >> alive={pattern_alive}, "
                                            f"tier1={tier1_ok}, confluence={confluence:.0f}, "
                                            f"pattern_score={pattern_score}, remnants={impulse_remnants}/3, "
                                            f"key={key_conditions_ok}, expand={expansion_still}, "
                                            f"Top_ok={top_detector_ok} (Risk={top_risk_score}%, HardNoBuy={hard_no_buy})"
                                        )
                                    else:
                                        confirmation_ok = bool(result)
                                        reason = "Pattern 15 – basic pattern check (fallback)"

                                    if confirmation_ok:
                                        logger.info(f"Pattern 15 confirmation SUCCESS for {symbol} – {reason}")
                                        await send_telegram_message(
                                            bot,
                                            f"✅ Pattern 15 confirmed on {symbol} – impulse still alive after dip >> ready to buy"
                                        )
                                    else:
                                        logger.warning(f"Pattern 15 confirmation FAILED for {symbol} – {reason}")

                                # === PATTERN 9 CONFIRMATION BLOCK ===
                                elif confirmation_mode == 9:
                                    reclaim_held = current_price > vwap * 0.999
                                    flow_flip = (obi_recovery or obi > 0.0) and cvd >= prev_cvd
                                    rsi_mid = 38 < rsi < 68
                                    not_dumping = not (cvd_change_pct < -10 and obi < -0.15)
                                    confirmation_ok = reclaim_held and flow_flip and rsi_mid and not_dumping and not hard_no_buy
                                    reason = (f"Pattern 9 Confirmation | reclaim={reclaim_held} flow={flow_flip} "
                                              f"rsi_mid={rsi_mid} clean={not_dumping}")
                                    if confirmation_ok:
                                        logger.info(f"Pattern 9 confirmation SUCCESS for {symbol} – {reason}")
                                        await send_telegram_message(bot, f"✅ Pattern 9 confirmed on {symbol} – VWAP held + orderflow flip >> ready to buy")
                                    else:
                                        logger.warning(f"Pattern 9 confirmation FAILED for {symbol} – {reason}")

                                # === PATTERN 11 CONFIRMATION BLOCK ===
                                elif confirmation_mode == 11:
                                    rsi_turn = rsi > (rsi_prev + 0.6) if rsi_prev is not None else False
                                    hist_turn = histogram > prev_histogram
                                    price_up = len(closes) >= 2 and closes[-1] > closes[-2] * 1.0005
                                    flow_turn = (cvd_change_pct >= 0) or obi_recovery or (obi > -0.08)
                                    still_dumping = cvd_change_pct <= -12 or obi <= -0.22
                                    rsi_window = 26 <= rsi <= 44
                                    confirmation_ok = (
                                        rsi_window and
                                        sum([rsi_turn, hist_turn, price_up]) >= 2 and
                                        flow_turn and
                                        not still_dumping
                                    )
                                    reason = (f"Pattern 11 Confirmation | window={rsi_window} turn={rsi_turn}/{hist_turn}/{price_up} "
                                              f"flow={flow_turn} dump={still_dumping}")
                                    if confirmation_ok:
                                        logger.info(f"Pattern 11 confirmation SUCCESS for {symbol} – {reason}")
                                        await send_telegram_message(bot, f"✅ Pattern 11 confirmed on {symbol} – mid-bear relief turning >> ready to buy")
                                    else:
                                        logger.warning(f"Pattern 11 confirmation FAILED for {symbol} – {reason}")

                                # === PATTERN 12 CONFIRMATION BLOCK ===
                                elif confirmation_mode == 12:
                                    support_now = support if (support and support > 0) else current_price * 0.98
                                    held_above = current_price > support_now * 1.001
                                    bounce_ok = is_recent_bounce or (len(closes) >= 2 and closes[-1] > closes[-2])
                                    flow_ok = obi_recovery or obi > 0.0 or cvd > prev_cvd
                                    vol_ok = current_volume > avg_volume * 0.95
                                    still_dumping = cvd_change_pct <= -12 or obi <= -0.20
                                    confirmation_ok = held_above and bounce_ok and flow_ok and vol_ok and not still_dumping and not hard_no_buy
                                    reason = (f"Pattern 12 Confirmation | held={held_above} bounce={bounce_ok} "
                                              f"flow={flow_ok} vol={vol_ok} dump={still_dumping}")
                                    if confirmation_ok:
                                        logger.info(f"Pattern 12 confirmation SUCCESS for {symbol} – {reason}")
                                        await send_telegram_message(bot, f"✅ Pattern 12 confirmed on {symbol} – spring held above support >> ready to buy")
                                    else:
                                        logger.warning(f"Pattern 12 confirmation FAILED for {symbol} – {reason}") 
                                    
                            
                                # === PATTERN 18 CONFIRMATION BLOCK - BEARISH REBOUND HUNTER ===
                                elif confirmation_mode == 18:
                                    # Core Reversal Signals
                                    rsi_strong_turn = rsi > (rsi_prev + 1.8) if rsi_prev is not None else False
                                    hist_strong_recover = histogram > (prev_histogram * 1.25) if prev_histogram is not None else False
                                    price_momentum = closes[-1] > closes[-2] * 1.001 if len(closes) >= 2 else False

                                    # Orderflow Recovery
                                    cvd_recovering = cvd_change_pct >= +3.0
                                    obi_recovering = (obi >= -0.10 and (obi - prev_obi) >= +0.08) if prev_obi is not None else (obi >= -0.06)

                                    # Danger Filters (Continued Selling)
                                    still_dumping_hard = cvd_change_pct <= -15 or obi <= -0.25
                                    rsi_still_low_and_falling = rsi < 36 and (rsi - rsi_prev) < -0.4
                                    hist_still_negative_and_worsening = histogram < -0.0001 and histogram < prev_histogram * 0.95

                                    # Scoring
                                    positive_momentum_signals = sum([rsi_strong_turn, hist_strong_recover, price_momentum])
                                    positive_pressure_signals = sum([cvd_recovering, obi_recovering])

                                    confirmation_ok = (
                                        positive_momentum_signals >= 2          # 2 out of 3 momentum signals
                                        and positive_pressure_signals >= 2      # Both pressure signals (fixed bug)
                                        and not still_dumping_hard
                                        and not rsi_still_low_and_falling
                                        and not hist_still_negative_and_worsening
                                    )

                                    # === DETAILED REASON FOR LOGGING ===
                                    mom_list = []
                                    if rsi_strong_turn: mom_list.append("RSI_Turn")
                                    if hist_strong_recover: mom_list.append("Hist_Recover")
                                    if price_momentum: mom_list.append("Price_Up")

                                    press_list = []
                                    if cvd_recovering: press_list.append("CVD")
                                    if obi_recovering: press_list.append("OBI")

                                    contra_list = []
                                    if still_dumping_hard: contra_list.append("Dumping_Hard")
                                    if rsi_still_low_and_falling: contra_list.append("RSI_Falling")
                                    if hist_still_negative_and_worsening: contra_list.append("Hist_Worsening")

                                    mom_str = f"Mom:{positive_momentum_signals}/2 [{' + '.join(mom_list) if mom_list else 'None'}]"
                                    press_str = f"Press:{positive_pressure_signals}/2 [{' + '.join(press_list) if press_list else 'None'}]"
                                    contra_str = "Clean" if not contra_list else "CONTRA:[" + " + ".join(contra_list) + "]"

                                    reason = (f"Pattern 18 | {mom_str} | {press_str} | {contra_str} "
                                              f">> {'CONFIRMED' if confirmation_ok else 'Failed'}")

                                    logger.info(f"Pattern 18 Confirmation {symbol} | Last 3 closes: {closes[-3:]}")
                                    logger.info(f"Pattern 18 for {symbol}: {reason}")

                                    if confirmation_ok:
                                        await send_telegram_message(
                                            bot, 
                                            f"✅ **Pattern 18 Confirmed** on {symbol}\n"
                                            f"Strong rebound signals detected >> Ready for entry"
                                        )

                                # === PATTERN 22 CONFIRMATION BLOCK ===
                                elif confirmation_mode == 22:
                                    rsi_reversal_ok     = rsi > (rsi_prev + 0.5) if rsi_prev is not None else (rsi > 30)
                                    hist_turning_up     = histogram > (prev_histogram * 1.05) if prev_histogram is not None else (histogram > -0.01)
                                    candle_up           = len(closes) >= 2 and closes[-1] >= closes[-2] * 0.998

                                    cvd_positive_trend  = cvd_change_pct >= -25.0
                                    obi_not_catastrophic = obi >= -0.25

                                    still_panic_mode    = obi <= -0.45 or cvd_change_pct <= -50

                                    positive_signals = sum([
                                        rsi_reversal_ok,
                                        hist_turning_up,
                                        candle_up,
                                        cvd_positive_trend,
                                        obi_not_catastrophic
                                    ])

                                    confirmation_ok = (
                                        positive_signals >= 2.5
                                        and not still_panic_mode
                                    )

                                    reason = "Ultra-permissive Pattern 22 recovery (≥3 equiv. + minimal barriers)"
                                
                                    if confirmation_ok:
                                        logger.info(f"Pattern 22 confirmation OK for {symbol} – ultra-permissive recovery signals met")
                                        await send_telegram_message(bot, f"✅ Pattern 22 confirmed on {symbol} – post-capitulation bounce detected >>ready to buy")
                                    else:
                                        logger.info(f"Pattern 22 confirmation FAILED for {symbol} – still in panic mode or weak signals")
                                                                
                                # Fallback if somehow confirmation_mode is unknown
                                else:
                                    confirmation_mode = 18
                                    # run Pattern 18 logic as safe default for dips
                                    rsi_strong_turn = rsi > (rsi_prev + 1.2) if rsi_prev is not None else False
                                    hist_strong_recover = histogram > (prev_histogram * 1.20) if prev_histogram is not None else False
                                    price_momentum = closes[-1] > closes[-2] > closes[-3] if len(closes) >= 3 else False
                                    cvd_recovering = cvd_change_pct >= +2.0
                                    obi_recovering  = obi >= -0.12 and (obi - prev_obi) >= +0.06 if prev_obi is not None else (obi >= -0.10)
                                    still_dumping_hard = cvd_change_pct <= -12 or obi <= -0.22
                                    rsi_still_low_and_falling = rsi < 42 and (rsi - rsi_prev) < -0.4
                                    hist_still_negative_and_worsening = histogram < -0.001 and histogram < prev_histogram * 0.9
                                    positive_momentum_signals = sum([rsi_strong_turn, hist_strong_recover, price_momentum])
                                    positive_pressure_signals = sum([cvd_recovering, obi_recovering])
                                    confirmation_ok = (
                                        positive_momentum_signals >= 2 and positive_pressure_signals >= 1
                                        and not still_dumping_hard and not rsi_still_low_and_falling
                                        and not hist_still_negative_and_worsening
                                    )
                                    reason = "Pattern 18 fallback – relaxed mid-rebound"

                                # ── 3. Execute only if confirmed ────────────────────────────────────────────────
                                if confirmation_ok:
                                    logger.info(f"TRAILING-DIP CONFIRMED & EXECUTED {symbol} @ {current_price:.8f} | "
                                                f"Dip Level: {dip_level:.8f} | Mode: {confirmation_mode} | Reason: {reason}")

                                    # Refetch price just before execution (safety)
                                    old_price = current_price
                                    current_price = await get_current_price(symbol)
                                    if current_price is None:
                                        current_price = old_price

                                    # EXECUTE BUY
                                    order = await execute_trailing_dip_buy(symbol, current_price, pre, bot)
                                    if order:
                                        params = {"ordId": order["orderId"], "instId": symbol}
                                        order_status = await binance_request("GET", "/api/v5/trade/order", params=params)

                                        returned_total_cost = order.get("total_cost", 0)
                                        local_total_cost = returned_total_cost or (quantity * current_price)
                                        default_qty = order.get("quantity", local_total_cost / current_price if current_price else 0)
                                        executed_qty = float(order_status[0].get("accFillSz", default_qty)) if order_status and isinstance(order_status, list) and order_status else default_qty
                                        display_qty = executed_qty if executed_qty > 0 else quantity
                                        entry_price = current_price
                                        executed_dip_level = dip_level

                                        pre["order_type"] = "buy"
                                        pre["amount"] = executed_qty
                                        pre["entry_price"] = entry_price

                                        pre["trailing_dip_active"] = False
                                        pre["dip_level"] = None
                                        pre["dip_distance"] = None
                                        pre["dip_occurred"] = False
                                        pre["original_trigger_price"] = None
                                        pre["dip_buy_executed"] = True

                                        # Cleanup confirmation lock on successful buy
                                        if "confirmation_mode_locked" in pre:
                                            del pre["confirmation_mode_locked"]

                                        targets = await calculate_targets(symbol, entry_price, current_price, atr, atr_percent, fib_extensions, momentum_factor)
                                        if targets:
                                            pre.update(targets)

                                        open_orders.append({
                                            "symbol": symbol,
                                            "orderId": order["orderId"],
                                            "side": "BUY",
                                            "price": current_price,
                                            "quantity": executed_qty if executed_qty > 0 else quantity
                                        })
                                        await save_state()

                                        message = (
                                            f"Trailing-Dip Buy Executed ({reason})\n"
                                            f"{symbol.replace('_SPBL', '')}: {display_qty:.3f} at {current_price:.8f} "
                                            f"(dip level was {executed_dip_level:.8f})\n"
                                            f"Primary: {pre.get('primary_target', 0):.8f}\n"
                                            f"Secondary: {pre.get('secondary_target', 0):.8f}\n"
                                            f"Stop-Loss: {pre.get('stop_loss', 0):.8f}\n"
                                            f"Trailing Stop: {pre.get('trailing_stop', 0):.8f}"
                                        )
                                        logger.info(message)
                                        await send_telegram_message(bot, message)

                                        pre["last_price"] = current_price
                                        continue

                                else:
                                    # Confirmation failed >>wait (no buy, no deactivation unless escape hits)
                                    last_notify_key = f"{symbol}_last_dip_confirm_fail_notify"
                                    last_notify = pre.get(last_notify_key, 0)
                                    now = time.time()

                                    if now - last_notify > 1800:  # notify max once every 30 minutes
                                        pre[last_notify_key] = now
                                        await save_state()

                                        logger.debug(f"Trailing-Dip {symbol}: reached dip {dip_level:.8f} but {reason} failed >> waiting")
                                        await send_telegram_message(bot,
                                            f"Trailing-Dip {symbol}: Price {current_price:.8f} above dip level {dip_level:.8f}, "
                                            f"but {reason} failed — still monitoring"
                                        )
                                
                            # Fallback: if price rises significantly above original trigger without ever dipping, force buy (enhanced: 1% buffer from 2%)
                            original_trigger_price = pre.get("original_trigger_price", current_price)
                            miss_buffer = original_trigger_price * 1.01  # Enhanced: 1% above original to force buy (faster than 2%)
                            if current_price > miss_buffer and not pre.get("dip_occurred", False) and confirmation_ok:
                                logger.warning(f"Trailing-Dip fallback buy for {symbol}: Price rose {((current_price - original_trigger_price)/original_trigger_price*100):.2f}% above trigger (no dip occurred)")

                                # --- deterministic risk-based sizing (fallback buy) ---
                                RISK_PERCENT = 0.005  # 0.5% risk per trade (tuneable)

                                try:
                                    est_atr = float(atr) if atr is not None else 0.0
                                    min_stop_distance = current_price * 0.005  # 0.5% floor
                                    atr_stop_distance = est_atr * 1.0 if est_atr and est_atr > 0 else min_stop_distance
                                    stop_loss_est = current_price - max(atr_stop_distance, min_stop_distance)
                                    risk_distance = current_price - stop_loss_est

                                    if risk_distance <= 0:
                                        logger.error(f"{symbol}: computed risk distance <= 0 ({risk_distance}) in fallback — skipping sizing.")
                                        continue

                                    risk_dollars = floored_quote_balance * RISK_PERCENT
                                    base_qty = risk_dollars / risk_distance

                                    qty_candidate = round_to_step_size(base_qty, step_size)
                                    notional_value = qty_candidate * current_price

                                    if qty_candidate < MIN_TRADE_QUANTITY or notional_value < min_notional:
                                        logger.warning(f"{symbol}: Fallback risk-based qty too small (qty={qty_candidate:.8f}, notional={notional_value:.2f}) — skipping fallback buy.")
                                        await send_telegram_message(bot, f"❌ {symbol} fallback skipped — size too small (risk-based) qty={qty_candidate:.8f}")
                                        continue

                                    quantity = qty_candidate
                                    logger.info(f"{symbol}: Fallback risk-sizing -> qty={quantity:.8f}, risk_dollars=${risk_dollars:.2f}, stop_est={stop_loss_est:.6f}")

                                except Exception as e:
                                    logger.error(f"{symbol}: Error computing fallback risk-based qty: {e}")
                                    await send_telegram_message(bot, f"⚠️ {symbol} fallback sizing error: {e}")
                                    continue

                                old_price = current_price
                                current_price = await get_current_price(symbol)
                                if current_price is None:
                                    current_price = old_price
                                    logger.warning(f"Price refetch failed for {symbol}, using prior price {current_price:.8f}")
                                if current_price is None:  # FIXED: Double-check fallback (prevents None entry_price)
                                    logger.error(f"Critical: No valid price for {symbol}, skipping fallback buy")
                                    continue

                            
                                # FIXED: Added missing buy execution (assumed; matches entry pattern)
                                order = await execute_trailing_dip_buy(symbol, current_price, pre, bot)
                                if order:
                                    # FIXED: Use Binance v5 endpoint (was Bitget v2)
                                    params = {"ordId": order["orderId"], "instId": symbol}
                                    order_status = await binance_request("GET", "/api/v5/trade/order", params=params)
                                
                                    # FIXED: Safe default_qty with local fallback (no reliance on undefined total_cost)
                                    returned_total_cost = order.get("total_cost", 0)  # From function return
                                    local_total_cost = returned_total_cost or (quantity * current_price)  # Estimate from pre-calc quantity if missing
                                    default_qty = order.get("quantity", local_total_cost / current_price if current_price else 0)
                                    executed_qty = float(order_status[0].get("accFillSz", default_qty)) if order_status and isinstance(order_status, list) and len(order_status) > 0 else default_qty
                                    display_qty = executed_qty if executed_qty > 0 else order.get("quantity", quantity)  # Safe fallback to pre-calc
                                    entry_price = current_price

                                    # store before clearing dip_level for message usage
                                    executed_dip_level = pre.get("dip_level")

                                    pre["order_type"] = "buy"
                                    pre["amount"] = executed_qty
                                    pre["entry_price"] = entry_price

                                    # Deactivate trailing-dip now that buy is placed
                                    pre["trailing_dip_active"] = False
                                    pre["dip_level"] = None
                                    pre["dip_distance"] = None
                                    pre["dip_occurred"] = False  # Reset for future

                                    # FIXED: Local RSI/CSI strings for message (avoids scope issues)
                                    local_rsi_str = f"{rsi:.2f}" if rsi is not None else "N/A"
                                    local_csi_str = f"{pre.get('csi', 0):.2f}" if pre.get('csi') is not None else "N/A"

                                    # FIXED: Debug log to inspect inputs (remove after fix confirmed)
                                    logger.debug(f"Targets inputs for {symbol} (fallback) - atr:{atr} ({type(atr).__name__}), atr_percent:{atr_percent} ({type(atr_percent).__name__}), fib_extensions:{fib_extensions} ({type(fib_extensions).__name__}), momentum_factor:{momentum_factor} ({type(momentum_factor).__name__})")

                                    # FIXED: Final safe coercions before passing
                                    safe_atr = float(atr) if atr is not None else 0.0
                                    safe_atr_percent = float(atr_percent) if atr_percent is not None else 0.0
                                    safe_momentum = float(momentum_factor) if momentum_factor is not None else 0.0
                                    safe_fib = dict(fib_extensions)  # Already cleaned; copy for safety

                                    targets = await calculate_targets(
                                        symbol, entry_price, current_price, safe_atr, safe_atr_percent, safe_fib, safe_momentum
                                    )
                                    if targets:
                                        pre["primary_target"] = targets["primary_target"]
                                        pre["secondary_target"] = targets["secondary_target"]
                                        pre["stop_loss"] = targets["stop_loss"]
                                        pre["trailing_distance"] = targets["trailing_distance"]
                                        pre["trailing_stop"] = targets["trailing_stop"]

                                    open_orders.append({
                                        "symbol": symbol,
                                        "orderId": order["orderId"],
                                        "side": "BUY",
                                        "price": current_price,
                                        "quantity": executed_qty if executed_qty > 0 else quantity
                                    })
                                    await save_state()

                                    # FIXED: Safe executed_dip_level with fallback (prevents None:.8f)
                                    executed_dip_level = pre.get("dip_level") or current_price  # Use entry if no level (breakout case)

                                    message = (
                                        f"Trailing-Dip Buy Executed (Pattern {pre.get('entry_pattern', 'N/A')})\n"
                                        f"{symbol.replace('_SPBL', '')}: {display_qty:.3f} at {current_price:.8f} (trigger level {executed_dip_level:.8f})\n"
                                        f"Primary: {pre.get('primary_target') or 0:.8f}\n"  # FIXED: or 0 prevents None:.8f
                                        f"Secondary: {pre.get('secondary_target') or 0:.8f}\n"
                                        f"Stop-Loss: {pre.get('stop_loss') or 0:.8f}\n"
                                        f"Trailing Stop: {pre.get('trailing_stop') or 0:.8f}\n"
                                    
                                    )
                                    logger.info(message)
                                    await send_telegram_message(bot, message)
                                    pre["last_price"] = current_price
                                    continue  # FIXED: Skip rest of monitoring

                            pre["last_price"] = current_price
                            # end monitoring loop for this symbol         

                    elif pre["order_type"] == "buy" and base_balance >= min_qty and pre["amount"] > 0:
                        quantity = min(round_to_step_size(pre["amount"], step_size or 0.00000001), base_balance)
                    
                        # FIXED: Add null checks for critical values to prevent "NoneType * float" error
                        if pre.get("entry_price") is None:
                            logger.error(f"Entry price is None for {symbol}, skipping sell logic")
                            continue
                    
                        if current_price is None:
                            logger.error(f"Current price is None for {symbol}, skipping sell logic")
                            continue
                        
                        if pre.get("secondary_target") is None or pre.get("primary_target") is None:
                            logger.error(f"Targets are None for {symbol}, recalculating...")
                            # Recalculate targets
                            indicators = await get_cached_indicators(symbol, current_price)
                            # Always update OBI snapshot for Live bot
                            if indicators:
                                await save_obi_snapshot(indicators, current_price)
                            
                            if indicators:
                                atr = indicators["atr"]
                                atr_percent = (atr / current_price * 100) if atr and current_price else 0.0
                                rsi = indicators["rsi"]
                                momentum_factor = rsi / 100 if rsi else 0.0
                                fib_extensions = indicators.get("fib_levels", {})
                                targets = await calculate_targets(symbol, pre["entry_price"], current_price, atr, atr_percent, fib_extensions, momentum_factor)
                                if targets:
                                    pre["primary_target"] = targets["primary_target"]
                                    pre["secondary_target"] = targets["secondary_target"]
                                    pre["stop_loss"] = targets["stop_loss"]
                                    pre["trailing_distance"] = targets["trailing_distance"]
                                    pre["trailing_stop"] = targets["trailing_stop"]
                                    await save_state()
                            else:
                                logger.error(f"Failed to recalculate targets for {symbol}")
                                continue
                    
                        price_stagnant = abs(current_price - pre["last_price"]) / pre["last_price"] < 0.005 if pre["last_price"] else False
                    
                        # NEW: Check notional and clear state for negligible amounts
                        notional = current_price * quantity
                        if notional < min_notional or quantity < min_qty:
                            if pre.get("clear_count", 0) >= 3:
                                logger.info(f"Clearing pre_orders for {symbol}: notional {notional:.8f} < {min_notional} or quantity {quantity} < {min_qty}")
                                pre["order_type"] = None
                                pre["amount"] = 0
                                pre["clear_count"] = 0
                                await save_state()

                            else:
                                pre["clear_count"] = pre.get("clear_count", 0) + 1
                                logger.debug(f"Incremented clear_count for {symbol}: {pre['clear_count']}")
                            continue     
                        else:
                            pre["clear_count"] = 0

                    
                        RESCUE_MAX_COUNT = 5               # matches size_factors list
                        rescue_trigger_distance = 0.004    # same constant as rescue engine

                        current_trailing_stop = pre.get("trailing_stop")
                        current_stop_loss      = pre.get("stop_loss")
                        rescue_remaining       = lane_rescue_pool() - pre.get("rescue_used", 0.0)

                        # Rescue is only eligible while the position is in the loss
                        # zone and capital remains in the dedicated rescue pool.
                        rescue_eligible = (
                            isinstance(current_trailing_stop, (int, float)) and
                            current_trailing_stop > 0 and
                            pre.get("entry_price", 0) > 0 and
                            current_trailing_stop < pre.get("entry_price", 0) and
                            current_price <= pre.get("entry_price", 0) * 1.002 and
                            (
                                pre.get("rescue_count", 0) < RESCUE_MAX_COUNT or          # ← FIXED (was < 3) Use <3 in Binance live
                                pre.get("rescue_trailing_dip_active", False)
                            ) and
                            rescue_remaining > 5.0
                        )

                        rescue_trigger_price = (
                            current_trailing_stop * (1 + rescue_trigger_distance)
                            if isinstance(current_trailing_stop, (int, float)) and current_trailing_stop > 0
                            else None
                        )

                        rescue_pending = (
                            rescue_eligible and
                            rescue_trigger_price is not None and
                            current_price <= rescue_trigger_price
                        )

                        if rescue_pending:
                            logger.info(
                                f"RESCUE PRIORITY GUARD ACTIVE for {symbol}: S.L & T.S suppressed | "
                                f"price={current_price:.8f} <= rescue_trigger={rescue_trigger_price:.8f} "
                                f"(trailing_stop={current_trailing_stop:.8f}, stop_loss={current_stop_loss}) | "
                                f"rescue_count={pre.get('rescue_count', 0)}/{RESCUE_MAX_COUNT} | "
                                f"rescue_remaining={rescue_remaining:.2f} {quote_of(symbol)}"
                            )
                        # ===================================================================

                        # Stop Loss: Trigger if current_price <= stop_loss, no other conditions
                        if (pre.get("stop_loss") is not None and current_price <= pre["stop_loss"] and
                            not pre.get("rescue_trailing_dip_active", False) and
                            not rescue_pending):        # <<< RESCUE PRIORITY GUARD

                            if _rescue_loss_freeze(pre, current_price):
                                await _shutdown_keep_position(
                                    bot, symbol,
                                    "5/5 rescues used and price reached TS+1% under the entry. Loss sell blocked."
                                )
                        
                            # Keep a local reference to the pre dict so we don't accidentally use pre_orders[symbol] after deletion.
                            local_pre = pre

                            # Use actual tracked amount (no virtual_amount in Binance)
                            quantity = min(local_pre.get("amount", 0.0), local_pre.get("last_base_balance", 0.0))
                            logger.info(f"STOP-LOSS SELL TRIGGER {symbol}: amount = {local_pre.get('amount', 0.0):.8f}, quantity = {quantity:.8f}")

                            order_response = await execute_sell(symbol, local_pre, current_price, quantity, "market", "stop-loss", rsi, macd_line, middle_band, btc_ig, csi)
                            order_id = order_response.get("ordId") or order_response.get("orderId") if order_response else None
                            if not order_id:
                                logger.error(f"Stop-loss sell failed for {symbol}: No order ID")
                                continue

                            filled_qty = await confirm_order_fill(order_id, symbol)

                            # Adjust stored amount first (so logs show meaningful remnant)
                            # NOTE: don't rely on pre_orders after this point — use local_pre and fresh balance fetch.
                            try:
                                local_pre["amount"] = max(0.0, float(local_pre.get("amount", 0.0)) - float(filled_qty))
                            except Exception:
                                # defensive fallback
                                local_pre["amount"] = local_pre.get("amount", 0.0)

                            logger.info(f"Stop-loss sell for {symbol}: filled {filled_qty:.8f}, remnant {local_pre['amount']:.8f}")

                            # NEW: Reset trailing-dip on position close
                            if local_pre.get("trailing_dip_active", False):
                                local_pre["trailing_dip_active"] = False
                                local_pre["dip_level"] = None
                                local_pre["dip_distance"] = None
                                local_pre["dip_tightening_time"] = 0
                                local_pre["original_trigger_price"] = None
                                logger.debug(f"Trailing-Dip cleared for {symbol} after stop-loss close")

                            # Reset deactivation flag to False (prevents immediate re-buy until pattern invalid->valid cycle)
                            local_pre['deactivation_achieved'] = False

                            # Clear position fields in local_pre (safe even if we remove the entry)
                            local_pre["order_type"] = None
                            local_pre["buy_target"] = None
                            local_pre["primary_target"] = None
                            local_pre["secondary_target"] = None
                            local_pre["stop_loss"] = None
                            local_pre["trailing_stop"] = None
                            local_pre["trailing_distance"] = None
                            local_pre["entry_price"] = None

                            # Fetch fresh balances for completion check (do this BEFORE deleting the pre_orders entry)
                            balance_info = await binance_request("GET", "/api/v5/account/balances")
                            new_base_balance = 0.0
                            new_quote_balance = 0.0
                            if balance_info:
                                for asset in balance_info:
                                    if asset["ccy"].upper() == base_asset.upper():
                                        new_base_balance = float(asset.get("availBal", "0"))
                                    if asset["ccy"].upper() == quote_of(symbol):
                                        new_quote_balance = float(asset.get("availBal", "0"))

                            # Update local_pre with new balances (and persist them)
                            local_pre["last_base_balance"] = new_base_balance
                            local_pre["last_quote_balance"] = new_quote_balance
                            await save_state()

                            # Completion check (Single del only here for full close)
                            is_full_close = (new_base_balance <= 0.0001) and (new_quote_balance > 0) and (local_pre["amount"] <= MIN_TRADE_QUANTITY)
                            if is_full_close:
                                # Remove from pre_orders safely and immediately continue so no later code touches the deleted key
                                if symbol in pre_orders:
                                    del pre_orders[symbol]
                                    logger.info(f"Full position closed via stop-loss for {symbol}; removed from pre_orders")
                                # persist after deletion (already saved balances above)
                                await save_state()
                                continue
                            else:
                                # Partial: keep monitoring the remnant (do not delete). Reset deactivation flag to block immediate re-entry.
                                logger.warning(f"Partial stop-loss for {symbol}: remnant {local_pre['amount']:.8f} > min_qty; monitoring continues")
                                local_pre['deactivation_achieved'] = False
                                # Ensure last balances are saved (already saved above but keep explicit)
                                await save_state()
                                continue

                    
                        # New condition for Stop-Loss persistent market sell on price drop below stop-loss
                        if symbol not in pre_orders or pre.get("last_base_balance", 0) <= 0.0001:
                            logger.debug(f"Persistent stop-loss skipped for {symbol}: No remnant position")
                            continue

                        if (current_price <= pre.get("stop_loss", 0) and
                            pre.get("last_base_balance", 0) > 0.0001 and                     
                            not pre.get("rescue_trailing_dip_active", False) and
                            not rescue_pending):        # <<< RESCUE PRIORITY GUARD

                            if _rescue_loss_freeze(pre, current_price):
                                await _shutdown_keep_position(
                                    bot, symbol,
                                    "5/5 rescues used and price reached TS+1% under the entry. Loss sell blocked."
                                )
                            
                            quantity = pre["last_base_balance"]
                            if quantity * current_price >= min_notional and quantity > 0:
                                # Log intent BEFORE sell (with current state)
                                logger.info(f"Persistent stop-loss sell INITIATED for {symbol}: price={current_price:.8f}, quantity={quantity:.8f}, base_balance={pre['last_base_balance']:.8f}")

                                # NEW: Reset trailing-dip on position close (before sell)
                                if symbol in pre_orders and pre.get("trailing_dip_active", False):
                                    pre["trailing_dip_active"] = False
                                    pre["dip_level"] = None
                                    pre["dip_distance"] = None
                                    pre["dip_tightening_time"] = 0
                                    pre["original_trigger_price"] = None
                                    logger.debug(f"Trailing-Dip cleared for {symbol} after stop-loss initiation")
                            
                                try:
                                    order_response = await execute_sell(symbol, pre, current_price, quantity, "market", "stop-loss-persistent", rsi, macd_line, middle_band, btc_ig, csi)
                                    order_id = order_response.get("ordId") or order_response.get("orderId") if order_response else None
                                    if not order_id:
                                        raise ValueError("Sell order failed")
                                
                                    filled_qty = await confirm_order_fill(order_id, symbol)
                                
                                    # Fetch fresh balances (no invalid params)
                                    balance_info = await binance_request("GET", "/api/v5/account/balances")  # Remove params
                                    new_base_balance = 0.0
                                    new_quote_balance = 0.0
                                    if balance_info:
                                        for asset in balance_info:  # Parse all balances properly
                                            if asset["ccy"].upper() == base_asset.upper():
                                                new_base_balance = float(asset.get("availBal", "0"))
                                            if asset["ccy"].upper() == quote_of(symbol):
                                                new_quote_balance = float(asset.get("availBal", "0"))
                                
                                    pre["amount"] -= filled_qty
                                    pre["last_base_balance"] = new_base_balance
                                    pre["last_quote_balance"] = new_quote_balance
                                    logger.info(f"Persistent stop-loss for {symbol}: filled {filled_qty:.8f}, remnant {pre['amount']:.8f}, base={new_base_balance:.8f}")
                                
                                    # Clear targets (safe even if pre orphaned) - No early del
                                    pre["buy_target"] = None
                                    pre["primary_target"] = None
                                    pre["secondary_target"] = None
                                    pre["stop_loss"] = None
                                    pre["trailing_stop"] = None
                                    pre["trailing_distance"] = None
                                    pre["entry_price"] = None
                                
                                    # Now check completion (Single del only here for full close)
                                    is_full_close = new_base_balance <= 0.0001 and new_quote_balance > 0 and pre["amount"] <= MIN_TRADE_QUANTITY
                                    if is_full_close:
                                        pre['deactivation_achieved'] = False  # Reset before del
                                        del pre_orders[symbol]
                                        logger.info(f"Full position closed via persistent stop-loss for {symbol}; removed from pre_orders")
                                    else:
                                        logger.warning(f"Persistent stop-loss sell PARTIAL for {symbol}: base={new_base_balance:.8f} (expected ~0), retry next loop")
                                        pre['deactivation_achieved'] = False
                                        logger.debug(f"Partial stop-loss close for {symbol}; flag reset to False for remnant monitoring")
                                
                                    await save_state()  # Save after all (safe)                                
                                    # Now check completion (reachable) - Moved logic inside if above
                                    await asyncio.sleep(1)  # Rate limit delay
                                    continue  # Skip rest (position closed or partial monitored)
                                
                                except Exception as e:
                                    logger.error(f"Persistent stop-loss sell FAILED for {symbol}: {str(e)}")
                                    # NEW: On error, reset flag to False for safety
                                    if symbol in pre_orders and isinstance(pre_orders[symbol], dict):
                                        pre_orders[symbol]['deactivation_achieved'] = False
                                    await save_state()
                                    await asyncio.sleep(1)  # Retry delay
                                    continue  # Skip rest on error

                        # Trailing Stop: Trigger if current_price <= trailing_stop, no other conditions
                        if (pre.get("trailing_stop") is not None and 
                            current_price <= pre["trailing_stop"] and
                            not pre.get("rescue_trailing_dip_active", False) and
                            not rescue_pending):    # <<< RESCUE PRIORITY GUARD

                            if _rescue_loss_freeze(pre, current_price):
                                await _shutdown_keep_position(
                                    bot, symbol,
                                    "5/5 rescues used and price reached TS+1% under the entry. Loss sell blocked."
                                )
                        
                            # Local reference for safety — avoid using deleted pre_orders entries
                            local_pre = pre

                            # Use actual tracked amount (no virtual_amount)
                            quantity = min(local_pre.get("amount", 0.0), local_pre.get("last_base_balance", 0.0))
                            logger.info(f"TRAILING-STOP SELL TRIGGER {symbol}: amount = {local_pre.get('amount', 0.0):.8f}, quantity = {quantity:.8f}")

                            order_response = await execute_sell(symbol, local_pre, current_price, quantity, "market", "trailing-stop", rsi, macd_line, middle_band, btc_ig, csi)
                            order_id = order_response.get("ordId") or order_response.get("orderId") if order_response else None
                            if not order_id:
                                logger.error(f"Trailing-stop sell failed for {symbol}: No order ID")
                                continue

                            filled_qty = await confirm_order_fill(order_id, symbol)

                            # Adjust stored amount
                            try:
                                local_pre["amount"] = max(0.0, float(local_pre.get("amount", 0.0)) - float(filled_qty))
                            except Exception:
                                local_pre["amount"] = local_pre.get("amount", 0.0)

                            logger.info(f"Trailing-stop sell for {symbol}: filled {filled_qty:.8f}, remnant {local_pre['amount']:.8f}")

                            # Reset trailing-dip fields on position close
                            if local_pre.get("trailing_dip_active", False):
                                local_pre["trailing_dip_active"] = False
                                local_pre["dip_level"] = None
                                local_pre["dip_distance"] = None
                                local_pre["dip_tightening_time"] = 0
                                local_pre["original_trigger_price"] = None
                                logger.debug(f"Trailing-Dip cleared for {symbol} after trailing-stop close")

                            # Reset deactivation flag to False (prevents instant re-buy)
                            local_pre["deactivation_achieved"] = False

                            # Clear key fields (same logic as stop-loss)
                            local_pre["order_type"] = None
                            local_pre["buy_target"] = None
                            local_pre["primary_target"] = None
                            local_pre["secondary_target"] = None
                            local_pre["stop_loss"] = None
                            local_pre["trailing_stop"] = None
                            local_pre["trailing_distance"] = None
                            local_pre["entry_price"] = None

                            # Fetch balances for completion verification
                            balance_info = await binance_request("GET", "/api/v5/account/balances")
                            new_base_balance = 0.0
                            new_quote_balance = 0.0
                            if balance_info:
                                for asset in balance_info:
                                    if asset["ccy"].upper() == base_asset.upper():
                                        new_base_balance = float(asset.get("availBal", "0"))
                                    if asset["ccy"].upper() == quote_of(symbol):
                                        new_quote_balance = float(asset.get("availBal", "0"))

                            local_pre["last_base_balance"] = new_base_balance
                            local_pre["last_quote_balance"] = new_quote_balance
                            await save_state()

                            # Completion check — remove from pre_orders only when fully closed
                            is_full_close = (new_base_balance <= 0.0001) and (new_quote_balance > 0) and (local_pre["amount"] <= MIN_TRADE_QUANTITY)
                            if is_full_close:
                                if symbol in pre_orders:
                                    del pre_orders[symbol]
                                    logger.info(f"Full position closed via trailing-stop for {symbol}; removed from pre_orders")
                                await save_state()
                                continue
                            else:
                                logger.warning(f"Partial trailing-stop for {symbol}: remnant {local_pre['amount']:.8f} > min_qty; monitoring continues")
                                local_pre["deactivation_achieved"] = False
                                await save_state()
                                continue
      
                    
                        # New condition for trailing stop persistent market close on price drop below trailing stop
                        if symbol not in pre_orders or pre.get("last_base_balance", 0) <= 0.0001:
                            logger.debug(f"Persistent trailing-stop skipped for {symbol}: No remnant position")
                            continue
                    
                        if (current_price <= pre.get("trailing_stop", 0) and
                            pre.get("last_base_balance", 0) > 0.0001 and                     
                            not pre.get("rescue_trailing_dip_active", False) and
                            not rescue_pending):    # <<< RESCUE PRIORITY GUARD

                            if _rescue_loss_freeze(pre, current_price):
                                await _shutdown_keep_position(
                                    bot, symbol,
                                    "5/5 rescues used and price reached TS+1% under the entry. Loss sell blocked."
                                )
                            
                            quantity = pre["last_base_balance"]
                            if quantity * current_price >= min_notional and quantity > 0:
                                # Log intent BEFORE sell (with current state)
                                logger.info(f"Persistent market sell INITIATED for {symbol}: price={current_price:.8f}, quantity={quantity:.8f}, base_balance={pre['last_base_balance']:.8f}")

                                # NEW: Reset trailing-dip on position close (before sell)
                                if symbol in pre_orders and pre.get("trailing_dip_active", False):
                                    pre["trailing_dip_active"] = False
                                    pre["dip_level"] = None
                                    pre["dip_distance"] = None
                                    pre["dip_tightening_time"] = 0
                                    pre["original_trigger_price"] = None
                                    logger.debug(f"Trailing-Dip cleared for {symbol} after trailing-stop initiation")
                            
                                try:
                                    order_response = await execute_sell(symbol, pre, current_price, quantity, "market", "trailing-stop-persistent", rsi, macd_line, middle_band, btc_ig, csi)
                                    order_id = order_response.get("ordId") or order_response.get("orderId") if order_response else None
                                    if not order_id:
                                        raise ValueError("Sell order failed")
                                
                                    filled_qty = await confirm_order_fill(order_id, symbol)
                                
                                    # Fetch fresh balances (no invalid params)
                                    balance_info = await binance_request("GET", "/api/v5/account/balances")  # Remove params
                                    new_base_balance = 0.0
                                    new_quote_balance = 0.0
                                    if balance_info:
                                        for asset in balance_info:  # Parse all balances properly
                                            if asset["ccy"].upper() == base_asset.upper():
                                                new_base_balance = float(asset.get("availBal", "0"))
                                            if asset["ccy"].upper() == quote_of(symbol):
                                                new_quote_balance = float(asset.get("availBal", "0"))
                                
                                    pre["amount"] -= filled_qty
                                    pre["last_base_balance"] = new_base_balance
                                    pre["last_quote_balance"] = new_quote_balance
                                    logger.info(f"Persistent trailing-stop for {symbol}: filled {filled_qty:.8f}, remnant {pre['amount']:.8f}, base={new_base_balance:.8f}")
                                
                                    # Clear targets (safe even if pre orphaned) - No early del
                                    pre["buy_target"] = None
                                    pre["primary_target"] = None
                                    pre["secondary_target"] = None
                                    pre["stop_loss"] = None
                                    pre["trailing_stop"] = None
                                    pre["trailing_distance"] = None
                                    pre["entry_price"] = None
                                
                                    # Now check completion (Single del only here for full close)
                                    is_full_close = new_base_balance <= 0.0001 and new_quote_balance > 0 and pre["amount"] <= MIN_TRADE_QUANTITY
                                    if is_full_close:
                                        pre['deactivation_achieved'] = False  # Reset before del
                                        del pre_orders[symbol]
                                        logger.info(f"Full position closed via persistent trailing-stop for {symbol}; removed from pre_orders")
                                    else:
                                        logger.warning(f"Persistent sell PARTIAL for {symbol}: base={new_base_balance:.8f} (expected ~0), retry next loop")
                                        pre['deactivation_achieved'] = False
                                        logger.debug(f"Partial trailing-stop close for {symbol}; flag reset to False for remnant monitoring")
                                
                                    await save_state()  # Save after all (safe)
                                
                                    # Now check completion (reachable) - Moved logic inside if above
                                    # (No duplicate)
                                
                                    await asyncio.sleep(1)  # Rate limit delay
                                    continue  # Skip rest (position closed or partial monitored)
                                
                                except Exception as e:
                                    logger.error(f"Persistent market sell FAILED for {symbol}: {str(e)}")
                                    # NEW: On error, reset flag to False for safety
                                    if symbol in pre_orders and isinstance(pre_orders[symbol], dict):
                                        pre_orders[symbol]['deactivation_achieved'] = False
                                    await save_state()
                                    await asyncio.sleep(1)  # Retry delay
                                    continue  # Skip rest on error

                        # --- PERFECT Trailing-stop runtime block (2025 final edition + Rescue Trade) ---
                        if pre.get("trailing_stop") is not None:
                            # Indicator fallbacks
                            atr_value = indicators.get("atr") or current_price * 0.01
                            atr_percent = indicators.get("atr_percent", 0.0)
                            # Minimum sane distance
                            min_trailing_distance = current_price * 0.012
                            run_distance = current_price * 0.048   # 4.8% RUN buffer
                            # Skip distance reset if this position was widened by rescue
                            if pre.get("rescue_widened", False):
                                logger.debug(f"TRAIL distance reset skipped for {symbol} - rescue widened")
                            # === ONLY RESET IF NO PROFIT LOCKING PHASE IS ACTIVE ===
                            elif pre.get("profit_phase", 0) == 0 and \
                                 (pre.get("trailing_distance", 0) == 0 or pre.get("trailing_distance") < min_trailing_distance):
                            
                                pre["trailing_distance"] = run_distance
                            
                                await save_state()
                                logger.info(f"TRAILING DISTANCE RESET {symbol} to {pre['trailing_distance']:.6f} (RUN 4.8%)")
                                await send_telegram_message(
                                    bot,
                                    fmt_tg("TRAIL RESET", [
                                        f"Pair          {symbol}",
                                        f"Distance      {(pre['trailing_distance']/current_price)*100:.2f}%  (RUN buffer)",
                                        f"Stop          {pre.get('trailing_stop', 0):.6f}",
                                    ]),
                                )

                            # ==================== KEEP & WAIT / LOSS FREEZE ====================
                            if _rescue_loss_freeze(pre, current_price):
                                await _shutdown_keep_position(
                                    bot, symbol,
                                    f"5/5 rescues used. Price {current_price:.8f} is within 1% of "
                                    f"TS {float(pre.get('trailing_stop') or 0):.8f}, and that stop is under "
                                    f"entry {float(pre.get('entry_price') or 0):.8f}."
                                )

                            # ========== CONDITIONAL RATCHET ==========
                            # Phase 0 (RUN / underwater) → original min_ratchet (safe & slow)
                            # Phase >= 1 (BREATHE and later) → ABSOLUTE price-only (distance is SACRED)
                            new_stop = current_price - pre["trailing_distance"]

                            if pre.get("profit_phase", 0) >= 1:
                                # ===== PROFIT PHASES: NO LAG, NO EXCEPTIONS =====
                                if new_stop > pre.get("trailing_stop", -1e18):
                                    old_stop = pre.get("trailing_stop")
                                    pre["trailing_stop"] = new_stop
                                    pre["last_ratchet_price"] = current_price
                                    pre["trail_confirm_count"] = pre.get("trail_confirm_count", 0) + 1
                                    await save_state()
                                    logger.info(
                                        f"TRAIL RATCHET UP {symbol} | {old_stop} >> {new_stop:.8f} | "
                                        f"Dist {(pre['trailing_distance']/current_price)*100:.2f}% | Count {pre['trail_confirm_count']}"
                                    )
                            else:
                                # ===== RUN PHASE: original safe ratchet with min_ratchet =====
                                peak = pre.get("trail_peak_price") or current_price
                                atr_value_safe = indicators.get("atr") or current_price * 0.01
                                min_ratchet = max(current_price * 0.0020, float(atr_value_safe) * 0.25)
                                if current_price > peak:
                                    pre["trail_peak_price"] = current_price
                                    peak = current_price
                                if new_stop > pre.get("trailing_stop", -1e18) and (
                                    current_price >= (pre.get("last_ratchet_price") or 0) + min_ratchet
                                    or pre.get("last_ratchet_price") is None
                                ):
                                    old_stop = pre.get("trailing_stop")
                                    pre["trailing_stop"] = new_stop
                                    pre["last_ratchet_price"] = current_price
                                    pre["trail_confirm_count"] = pre.get("trail_confirm_count", 0) + 1
                                    await save_state()
                                    logger.info(
                                        f"TRAIL RATCHET UP {symbol} | {old_stop} >> {new_stop:.8f} | "
                                        f"Dist {(pre['trailing_distance']/current_price)*100:.2f}% | Count {pre['trail_confirm_count']}"
                                    )
                            # ========================================

                            unrealized_pct = ((current_price - pre.get("entry_price", current_price)) / pre.get("entry_price", current_price)) * 100
                            rsi = indicators.get('rsi', 50)

                            # ==================== MAIN SCALE P2 / P3 ====================
                            # Trigger = TS * 1.02, but ONLY if TS is deep enough that
                            # TS+2% is still a real drawdown (never add in/near profit).
                            SCALE_TS_MIN_DD = 0.04          # TS must be <= -4% vs entry
                            main_scale_count = int(pre.get("main_scale_count") or 0)
                            ts_now = float(pre.get("trailing_stop") or 0.0)
                            entry_now = float(pre.get("entry_price") or 0.0)

                            ts_underwater = (entry_now > 0 and ts_now > 0 and ts_now < entry_now)
                            ts_deep_enough = (entry_now > 0 and ts_now <= entry_now * (1.0 - SCALE_TS_MIN_DD))
                            scale_trigger = (ts_now * 1.02) if ts_now else None
                            trigger_underwater = (scale_trigger is not None and entry_now > 0 and scale_trigger < entry_now)
                            price_underwater = (entry_now > 0 and current_price < entry_now)

                            scale_ladder_ok = (
                                ts_underwater and ts_deep_enough and trigger_underwater and price_underwater
                            )

                            if (pre.get("order_type") == "buy"
                                and main_scale_count in (1, 2)
                                and scale_ladder_ok
                                and scale_trigger is not None
                                and current_price <= scale_trigger):

                                next_n = main_scale_count + 1
                                logger.warning(
                                    f"MAIN SCALE P{next_n} TRIGGER {symbol} | px={current_price:.8f} "
                                    f"<= TS+2% {scale_trigger:.8f} | TS={ts_now:.8f} "
                                    f"({((ts_now/entry_now)-1)*100:.2f}%) | entry={entry_now:.8f}"
                                )
                                ok = await execute_main_scale_add(symbol, current_price, pre, bot, next_n)
                                if ok:
                                    await save_state()
                                    continue

                            # Rescue: after P3, OR if the ladder is no longer valid (tight TS)
                            scale_rescue_unlocked = (
                                main_scale_count >= 3 or not scale_ladder_ok
                            )
                            
                            # ==================== RESCUE TRADE FEATURE ====================
                            if (pre.get("entry_price", 0) > 0 and
                                pre.get("trailing_stop", 0) < pre.get("entry_price", 0) and
                                current_price <= pre.get("entry_price", 0) * 1.002 and
                                (pre.get("rescue_count", 0) < 5 or pre.get("rescue_trailing_dip_active", False)) and
                                scale_rescue_unlocked):
                            
                                # Get live USDT balance
                                account = await binance_request("GET", "/api/v5/account/balances")
                                quote_balance = 0.0
                                for asset in account:
                                    if asset.get("ccy", "").upper() == quote_of(symbol):
                                        quote_balance = float(asset.get("availBal", "0"))
                                        break
                           
                                remaining_rescue = lane_rescue_pool() - pre.get("rescue_used", 0.0)
                           
                                logger.info(f"RESCUE: Dedicated Rescue Pool = {lane_rescue_pool():.2f} | "
                                            f"Remaining = {remaining_rescue:.2f} | "
                                            f"rescue_used = {pre.get('rescue_used', 0.0):.2f} | "
                                            f"Total Wallet = {quote_balance:.2f}")
                                rescue_trigger_distance = 0.004
                                rescue_trigger_price = pre["trailing_stop"] * (1 + rescue_trigger_distance)
                           
                                if current_price <= rescue_trigger_price or pre.get("rescue_trailing_dip_active", False):
                                    rescue_count = pre.get("rescue_count", 0) + 1
                               
                                    # ==================== RESCUE TRAILING DIP (Only 5th Order) ====================
                                    if rescue_count == 5 or pre.get("rescue_trailing_dip_active", False):
                                        if not pre.get("rescue_trailing_dip_active", False):
                                            pre["rescue_trailing_dip_active"] = True
                                            pre["rescue_dip_distance"] = current_price * 0.014
                                            pre["rescue_dip_level"] = current_price + pre["rescue_dip_distance"]
                                        
                                            logger.info(
                                                f"[RESCUE TRAILING DIP] Activated for 5th rescue order | "
                                                f"active={pre['rescue_trailing_dip_active']} | "
                                                f"dip_distance={pre['rescue_dip_distance']:.8f} | "
                                                f"dip_level={pre['rescue_dip_level']:.8f}"
                                            )
                                            await send_telegram_message(
                                                bot,
                                                f"📉 RESCUE TRAILING DIP ACTIVATED (5th order)\n"
                                                f"• Active: {pre['rescue_trailing_dip_active']}\n"
                                                f"• Dip Distance: {pre['rescue_dip_distance']:.8f}\n"
                                                f"• Dip Level: {pre['rescue_dip_level']:.8f}\n"
                                                f"• Current Price: {current_price:.8f}"
                                            )
                                            await save_state()
                                            continue
                                        # === Correct ratchet logic ===
                                        potential_new_level = current_price + pre.get("rescue_dip_distance", current_price * 0.014)
                                        if potential_new_level < pre.get("rescue_dip_level", float('inf')):
                                            old_level = pre.get("rescue_dip_level")
                                            pre["rescue_dip_level"] = potential_new_level
                                            await save_state()
                                            logger.info(
                                                f"[RESCUE TRAILING DIP] Level updated ↓ | "
                                                f"Old: {old_level:.8f} >> New: {pre['rescue_dip_level']:.8f} | "
                                                f"Price: {current_price:.8f}"
                                            )
                                            await send_telegram_message(
                                                bot,
                                                f"📉 RESCUE DIP LEVEL UPDATED ↓\n"
                                                f"• Old Level: {old_level:.8f}\n"
                                                f"• New Level: {pre['rescue_dip_level']:.8f}\n"
                                                f"• Dip Distance: {pre.get('rescue_dip_distance', 0):.8f}\n"
                                                f"• Current Price: {current_price:.8f}\n"
                                                f"• Active: {pre.get('rescue_trailing_dip_active')}"
                                            )
                                        # Buy on rebound
                                        if current_price >= pre.get("rescue_dip_level", 0):
                                            logger.info(
                                                f"[RESCUE TRAILING DIP] Rebound detected >> Executing 5th rescue buy | "
                                                f"Price: {current_price:.8f} ≥ Dip Level: {pre.get('rescue_dip_level'):.8f}"
                                            )
                                            await send_telegram_message(
                                                bot,
                                                f"✅ RESCUE TRAILING DIP REBOUND DETECTED\n"
                                                f"• Executing 5th rescue buy\n"
                                                f"• Current Price: {current_price:.8f}\n"
                                                f"• Dip Level: {pre.get('rescue_dip_level'):.8f}\n"
                                                f"• Dip Distance: {pre.get('rescue_dip_distance', 0):.8f}"
                                            )
                                            rescue_count = 5
                                        else:
                                            continue

                                    # ==================== NORMAL RESCUE BUY (for 1-4 and 5 after dip trigger) ====================
                                    size_factors = [0.50, 0.20, 0.30, 0.40, 0.90]
                                
                                    rescue_usdt = remaining_rescue * size_factors[rescue_count - 1]
                                    rescue_usdt = min(rescue_usdt, remaining_rescue, quote_balance)
                                    rescue_usdt = math.floor(rescue_usdt * 100) / 100

                                    if rescue_usdt < 5.0:
                                        await _shutdown_keep_position(
                                            bot, symbol,
                                            f"Rescue #{rescue_count} needs at least 5 {quote_of(symbol)} "
                                            f"but the wallet can pay {rescue_usdt:.2f}. "
                                            f"Free balance {quote_balance:.2f}. "
                                            f"Buy was not sent, so the trailing stop cannot sell this loss."
                                        )

                                    logger.warning(
                                        f"RESCUE TRADE ANTI SHAKE OUT #{rescue_count} ACTIVATED {symbol} | "
                                        f"Loss: {unrealized_pct:.2f}% | Buying {rescue_usdt:.6f} @ {current_price:.8f} market"
                                    )
                                    
                                    await send_telegram_message(bot, f" RESCUE TRADE ANTI SHAKE OUT #{rescue_count} activated on {symbol}! "
                                                                     f"Loss: {unrealized_pct:.2f}% – Buying {rescue_usdt:.2f} {quote_of(symbol)} at {current_price:.8f}")
                                    buy_order = await place_order(
                                        side="buy", 
                                        price=None, 
                                        quantity=None, 
                                        symbol=symbol, 
                                        order_type="market", 
                                        total_cost=rescue_usdt, 
                                        is_rescue=True
                                    )
                               
                                    if buy_order:
                                        filled_qty = await confirm_order_fill(buy_order.get("ordId") or buy_order.get("orderId"), symbol)
                                        if filled_qty > 0:
                                            old_entry = pre["entry_price"]
                                            new_avg = (old_entry * pre.get("amount", 0) + current_price * filled_qty) / (pre.get("amount", 0) + filled_qty)
                                       
                                            pre["entry_price"] = new_avg
                                            pre["amount"] += filled_qty
                                            pre["rescue_count"] = rescue_count
                                            pre["rescue_used"] = pre.get("rescue_used", 0.0) + rescue_usdt
                                            from datetime import datetime, timezone
                                            pre["rescue_buy_time"] = datetime.now(timezone.utc).isoformat()
                                       
                                            indicators = await get_cached_indicators(symbol, new_avg)
                                            atr = indicators.get("atr", atr_value)
                                            atr_percent = (atr / new_avg * 100) if new_avg > 0 else 0
                                            rsi = indicators.get("rsi", 50)
                                            momentum_factor = rsi / 100
                                            fib_extensions = indicators.get("fib_levels", {})
                                       
                                            targets = await calculate_targets(
                                                symbol, new_avg, new_avg, atr, atr_percent,
                                                fib_extensions, momentum_factor, is_rescue=True,
                                                rescue_buy_price=current_price
                                            )
                                            pre["primary_target"] = targets["primary_target"]
                                            pre["secondary_target"] = targets["secondary_target"]
                                            pre["stop_loss"] = targets["stop_loss"]
                                            pre["trailing_distance"] = targets["trailing_distance"]
                                            pre["trailing_stop"] = targets["trailing_stop"]
                                            pre["rescue_widened"] = True
                                       
                                            if pre.get("rescue_trailing_dip_active"):
                                                pre["rescue_trailing_dip_active"] = False
                                                pre["rescue_dip_level"] = None
                                                pre["rescue_dip_distance"] = None
                                            logger.info(f"RESCUE TRADE #{rescue_count} COMPLETED {symbol} | New Avg: {new_avg:.8f}")
                                            await send_telegram_message(bot, f" RESCUE #{rescue_count} done on {symbol}! New avg entry: {new_avg:.8f}")
                                       
                                            await save_state()
                                            continue
                                    
                            # ==================== PROFIT LOCKING PHASES (Custom Distances) ====================
                            current_phase = pre.get("profit_phase", 0)
                            original_entry_pattern = pre.get("entry_pattern", None)

                            phase_name = None
                            new_phase = current_phase
                            new_pct = None

                            # RUN: 0 → 1.8%
                            if unrealized_pct < 1.8:
                                if current_phase < 1:
                                    if pre.get("trailing_distance", 0) < current_price * 0.035:
                                        pre["trailing_distance"] = current_price * 0.048
                                    logger.debug(
                                        f"TRAIL RUN {symbol} +{unrealized_pct:.2f}% | "
                                        f"dist={(pre['trailing_distance']/current_price)*100:.2f}%"
                                    )
                            # BREATHE: +1.8% → 4.2%   → EXACT 0.8%
                            elif 1.8 <= unrealized_pct < 4.2 and current_phase < 1:
                                new_phase, new_pct, phase_name = 1, 0.0080, "BREATHE"
                            # LOCK: +4.2% → 5.8%      → EXACT 0.6%
                            elif 4.2 <= unrealized_pct < 5.8 and current_phase < 2:
                                new_phase, new_pct, phase_name = 2, 0.0060, "LOCK"
                            # STEEL: +5.8% → 7.8%     → EXACT 0.8%
                            elif 5.8 <= unrealized_pct < 7.8 and current_phase < 3:
                                new_phase, new_pct, phase_name = 3, 0.0080, "STEEL"
                            # HARVEST: +7.8% → 10.5%  → EXACT 0.8%
                            elif 7.8 <= unrealized_pct < 10.5 and current_phase < 4:
                                new_phase, new_pct, phase_name = 4, 0.0080, "HARVEST"
                            # MOONSHOT: +10.5%+       → EXACT 1.5%
                            elif unrealized_pct >= 10.5 and current_phase < 5:
                                new_phase, new_pct, phase_name = 5, 0.0150, "MOONSHOT"

                            if phase_name is not None and new_pct is not None:
                                pre["profit_phase"] = new_phase

                                # ========== ABSOLUTE DISTANCE — NEVER LOWER THE STOP ==========
                                candidate_distance = current_price * new_pct
                                candidate_stop     = current_price - candidate_distance

                                # Keep the better (higher) of the two stops
                                old_stop = pre.get("trailing_stop", -1e18)
                                if candidate_stop > old_stop:
                                    pre["trailing_distance"] = candidate_distance
                                    pre["trailing_stop"]     = candidate_stop
                                else:
                                    # Phase advanced but we keep the already-higher stop.
                                    # Distance is still set so future ratchets use the tighter value.
                                    pre["trailing_distance"] = candidate_distance
                                    # trailing_stop stays at the higher old value
                                # ==============================================================

                                locked_pct = ((pre["trailing_stop"] / pre.get("entry_price", current_price) - 1) * 100)
                                logger.info(
                                    f"{phase_name} ACTIVATED {symbol} +{unrealized_pct:.2f}% | Phase {new_phase} | "
                                    f"Trail {(pre['trailing_distance']/current_price)*100:.2f}% | "
                                    f"Stop {pre.get('trailing_stop', 0):.6f} | "
                                    f"LOCKED ≈ +{locked_pct:.2f}%"
                                )
                                await send_telegram_message(
                                    bot,
                                    fmt_tg(
                                        f"{phase_name}  +{unrealized_pct:.2f}%",
                                        [
                                            f"Pair          {symbol}",
                                            f"Unrealized    +{unrealized_pct:.2f}%",
                                            f"Trail         {(pre['trailing_distance']/current_price)*100:.2f}%",
                                            f"Stop          {pre.get('trailing_stop', 0):.6f}",
                                            f"Locked        ≈ +{locked_pct:.2f}%",
                                            f"Pattern       {original_entry_pattern}",
                                            f"Goal          Profit locked. Distance is SACRED.",
                                        ],
                                    ),
                                )

                            # ==================== SINGLE SAVE ====================
                            await save_state()
                        
                            # Enforce absolute bounds ONLY while still in RUN (phase 0).
                            # Once any profit phase is active the distance is SACRED and must never be touched.
                            if pre.get("profit_phase", 0) == 0:
                                if not pre.get("rescue_widened", False):
                                    pre["trailing_distance"] = min(pre["trailing_distance"], current_price * 0.08)   # 8.0% max
                                else:
                                    pre["trailing_distance"] = max(min_trailing_distance, pre["trailing_distance"])

                            logger.debug(f"After bounds enforcement {symbol} | "
                                         f"trailing_distance={pre['trailing_distance']:.6f} | "
                                         f"trailing_stop={pre['trailing_stop']:.8f} | "
                                         f"current_price={current_price:.8f} | "
                                         f"unrealized={unrealized_pct:.2f}% | "
                                         f"rescue_count={pre.get('rescue_count', 0)} | phase={pre.get('profit_phase', 0)}")
                            pre["last_price"] = current_price

                    _loop_symbol = symbol
                    for order in open_orders[:]:
                        try:
                            if order.get("symbol") != _loop_symbol:
                                continue
                            if not order.get("symbol"):
                                logger.error(f"Invalid order in open_orders: {order}")
                                open_orders.remove(order)
                                continue
                            api_symbol = order["symbol"]  # Binance fix
                            params = {"ordId": order["orderId"], "instId": api_symbol}
                            order_status = await binance_request("GET", "/api/v5/trade/order", params=params)
                            # Use helper for retry-enabled confirm (replaces direct fetch)
                            filled_qty = await confirm_order_fill(order["orderId"], order["symbol"])
                            status = "filled" if filled_qty > 0 else "partial_or_open"  # Infer from fill
                            if filled_qty > 0:
                                # Process filled order
                                logger.info(f"Order {order['orderId']} ({order['symbol']}) filled: {filled_qty:.8f}")
                                open_orders.remove(order)
                                # Safe executed_qty (no KeyError)
                                executed_qty = filled_qty  # Use confirmed
                                # Derive vars safely
                                symbol = order["symbol"]
                                bind_lane_from_symbol(symbol)
                                pre = pre_orders.get(symbol, {})
                                base_asset = order['symbol'].split('/')[0].upper()  # Clean display
                                message = (
                                    f"{order['side']} Order Filled\n"
                                    f"{base_asset}: {executed_qty:.3f} at {order['price']:.8f}\n"
                                
                                )
                                logger.info(message)
                                await send_telegram_message(bot, message)
                                if order["side"] == "BUY":
                                    pre["order_type"] = "buy"
                                    pre["amount"] = executed_qty
                                    pre["entry_price"] = order["price"]

                                    # Fetch fresh indicators for target calculation
                                    indicators = await get_cached_indicators(order["symbol"], order["price"])
                                    if indicators is None:
                                        logger.error(f"Failed to fetch indicators for {order['symbol']} after buy order filled")
                                        continue
                                    atr = indicators["atr"]
                                    atr_percent = (atr / order["price"] * 100) if atr and order["price"] else 0.0
                                    rsi = indicators["rsi"]
                                    momentum_factor = rsi / 100 if rsi else 0.0
                                    fib_extensions = indicators.get("fib_levels", {})
                                    # Calculate and store targets 
                                    targets = await calculate_targets(
                                        symbol, order["price"], order["price"], atr, atr_percent, fib_extensions, momentum_factor
                                    )
                                    pre["primary_target"] = targets["primary_target"]
                                    pre["secondary_target"] = targets["secondary_target"]
                                    pre["stop_loss"] = targets["stop_loss"]
                                    pre["trailing_distance"] = targets["trailing_distance"]
                                    pre["trailing_stop"] = targets["trailing_stop"]
                                    await save_state()

                                    # Send notification with targets
                                    message = (
                                        f"Buy Order Filled and Targets Set\n"
                                        f"{base_asset}: {executed_qty:.3f} at {order['price']:.8f}\n"
                                        f"Primary: {pre['primary_target']:.8f}\n"
                                        f"Secondary: {pre['secondary_target']:.8f}\n"
                                        f"Stop-Loss: {pre['stop_loss']:.8f}\n"
                                        f"Trailing Stop: {pre['trailing_stop']:.8f}\n"
                                    
                                    )
                                    logger.info(message)
                                    await send_telegram_message(bot, message)
                                elif order["side"] == "SELL":
                                    pre["amount"] -= executed_qty
                                    if pre["amount"] <= min_qty:
                                        # NEW: Reset trailing-dip on position close
                                        if pre.get("trailing_dip_active", False):
                                            pre["trailing_dip_active"] = False
                                            pre["dip_level"] = None
                                            pre["dip_distance"] = None
                                            pre["dip_tightening_time"] = 0
                                            pre["original_trigger_price"] = None
                                            logger.debug(f"Trailing-Dip cleared for {symbol} after SELL fill close")
                                        # NEW: For basic post-sell: Full close; reset flag to False before delete
                                        pre['deactivation_achieved'] = False
                                        del pre_orders[symbol]
                                        logger.info(f"Removed {symbol} from pre_orders after sell")
                                        await save_state()
                                    else:
                                        # NEW: For basic post-sell: Partial close; reset flag to False for remnant
                                        pre['deactivation_achieved'] = False
                                        logger.debug(f"Partial SELL fill for {symbol}; flag reset to False for remnant monitoring")
                                        await save_state()

                            elif status == "canceled":
                                # Process canceled order
                                logger.info(f"Order {order['orderId']} ({order['symbol']}) canceled")
                                open_orders.remove(order)
                                display_symbol = order['symbol']  # Use symbol directly
                                message = (
                                    f"Order Cancelled\n"
                                    f"{order['side']} order {order['orderId']} for {display_symbol}\n"
                                
                                )
                                logger.info(message)
                                await send_telegram_message(bot, message)
                                if order["symbol"] in pre_orders and order["side"] == "SELL" and pre["amount"] <= min_qty:
                                    del pre_orders[symbol]
                                    logger.info(f"Removed {symbol} from pre_orders after cancel")
                                    await save_state()
                        except Exception as e:
                            logger.error(f"Error checking order {order.get('orderId', 'unknown')} ({order.get('symbol', 'unknown')}): {str(e)}") 

                    sleep_duration = 4 if atr_percent > 1.5 else 12 if atr_percent < 0.5 else 8
                    await asyncio.sleep(sleep_duration)

                finally:
                    ACTIVE_SLOT.reset(_lane_token)
        except Exception as e:
            logger.error(f"Error in trading loop: {str(e)}")
            if "Insufficient balance" not in str(e):
                message = (
                    f"Trading Loop Error\n"
                    f"Error: {str(e)}\n"
            
                )
                await send_telegram_message(bot, message)
            sleep_duration = 4 if atr_percent > 1.5 else 12 if atr_percent < 0.5 else 8
            await asyncio.sleep(sleep_duration)

async def isaac_execute_sell(symbol, pre, price, quantity, order_type, reason, rsi, macd_line, middle_band, btc_ig, csi):
    """
    Dedicated sell function for ISAAC DCA.
    Enhanced with quantity precision handling to prevent -1111 'too much precision' error.
    """
    global binance_client
    
    if binance_client is None:
        await create_binance_client()
    
    try:
        # Clean symbol for API calls (remove slash)
        clean_symbol = symbol.replace('/', '')
        
        # Get symbol info from instruments endpoint
        symbols_data = await binance_request("GET", "/api/v5/public/instruments")
        symbol_info = None
        min_notional = 1.0
        min_qty = 0.00000001
        qty_precision = 8  # safe default fallback for most altcoins
        
        if symbols_data:
            for info in symbols_data:
                if info.get("instId") == clean_symbol:
                    symbol_info = info
                    min_notional = float(info.get("minNotional", "1.0"))
                    min_qty = float(info.get("minSz", "0.00000001"))
                    
                    # Infer precision from minSz string (e.g. "0.001" → 3 decimals)
                    min_sz_str = info.get("minSz", "0.00000001")
                    if '.' in min_sz_str:
                        decimal_part = min_sz_str.split('.')[-1].rstrip('0')
                        qty_precision = len(decimal_part) if decimal_part else 0
                    break
        
        if not symbol_info:
            logger.warning(f"ISAAC Symbol {symbol} (clean: {clean_symbol}) not found in instruments — using defaults")
        
        logger.debug(f"ISAAC sell {symbol} — minSz: {min_qty}, inferred qty precision: {qty_precision}")
        
        # Validate notional value
        notional = quantity * price
        if notional < min_notional:
            logger.error(f"ISAAC {reason} sell notional too low for {symbol}: {notional:.2f} < {min_notional}")
            return None
        
        # Validate minimum quantity before rounding
        if quantity < min_qty:
            logger.error(f"ISAAC {reason} sell quantity too low (pre-round): {quantity:.10f} < {min_qty:.8f}")
            return None
        
        # Round quantity to symbol's allowed precision
        quantity_rounded = round(quantity, qty_precision)
        
        # Extra safety: never go below min_qty after rounding
        if quantity_rounded < min_qty:
            logger.error(f"ISAAC {reason} sell quantity too low after rounding: {quantity_rounded:.10f} < {min_qty:.8f}")
            return None
        
        # Debug: show before/after
        logger.debug(
            f"ISAAC sell quantity adjustment — "
            f"raw: {quantity:.12f} | "
            f"rounded ({qty_precision} decimals): {quantity_rounded:.10f} | "
            f"str: {str(quantity_rounded)}"
        )
        
        # Prevent NoneType price
        if price is None:
            logger.error(f"Cannot place ISAAC {order_type} sell for {symbol}: price is None")
            return None
        
        # Prepare clean sz string (remove trailing zeros and dot if integer)
        sz_str = "{:.{}f}".format(quantity_rounded, qty_precision).rstrip('0').rstrip('.')
        if not sz_str:
            sz_str = "0"  # extremely rare safety
        
        # Place market sell order
        body = {
            "instId": clean_symbol,
            "side": "sell",
            "ordType": order_type,
            "sz": sz_str
        }
        if order_type != "market":
            body["px"] = str(price)
        
        logger.debug(f"ISAAC placing sell order: {body}")
        
        order_response = await binance_request("POST", "/api/v5/trade/order", body=body)
        if not order_response or not order_response.get("ordId"):
            logger.error(f"ISAAC failed to place {order_type} sell for {symbol}: {order_response}")
            return None
        
        order_id = order_response["ordId"]
        
        # Confirm fill for market orders
        if order_type == "market":
            filled_qty = await confirm_order_fill(order_id, clean_symbol)
            if filled_qty <= 0:
                logger.warning(f"ISAAC sell order {order_id} may not have filled properly")
        
        # Log successful sale
        base_asset = symbol.split('/')[0].upper()
        logger.info(
            f"ISAAC DCA {reason} Sell Executed: "
            f"{quantity_rounded:.6f} {base_asset} at {price:.8f} "
            f"(original qty: {quantity:.10f})"
        )
        
        bot = Bot(TELEGRAM_TOKEN)
        message = (
            f"ISAAC DCA {reason} Sell\n"
            f"{symbol}: Sold {quantity_rounded:.6f} at {price:.8f}\n"
            f"Order ID: {order_id}"
        )
        await send_telegram_message(bot, message)
        
        return {
            "orderId": order_id,
            "quantity": quantity_rounded,
            "price": price
        }
        
    except BinanceAPIException as api_err:
        logger.error(f"Binance API exception in ISAAC sell: {api_err}")
        return None
    except Exception as e:
        logger.error(f"ISAAC execute_sell error for {symbol}: {str(e)}")
        return None

async def save_isaac_state(isaac_data):
    """Save ISAAC state to dedicated file."""
    try:
        data_to_save = dict(isaac_data)
        
        data_to_save["version"] = "isaac_v3"
       
        data_to_save["ISAAC_DCA_INITIAL_USDT"] = ISAAC_DCA_INITIAL_USDT

        # ================= TRAILING STOP =================
        data_to_save["isaac_trailing_stop"] = (
            float(data_to_save["isaac_trailing_stop"])
            if data_to_save.get("isaac_trailing_stop") is not None else None
        )
        data_to_save["isaac_trailing_distance"] = (
            float(data_to_save["isaac_trailing_distance"])
            if data_to_save.get("isaac_trailing_distance") is not None else None
        )

        # ================= TRAILING DIP =================
        data_to_save["isaac_trailing_dip_active"] = bool(
            data_to_save.get("isaac_trailing_dip_active", False)
        )
        data_to_save["isaac_dip_level"] = (
            float(data_to_save["isaac_dip_level"])
            if data_to_save.get("isaac_dip_level") is not None else None
        )
        data_to_save["isaac_dip_distance"] = (
            float(data_to_save["isaac_dip_distance"])
            if data_to_save.get("isaac_dip_distance") is not None else None
        )

        with open(ISAAC_STATE_FILE, "w") as f:
            json.dump(data_to_save, f, indent=2, default=str)
        
        logger.debug("ISAAC state saved successfully (cleaned v3)")
        return True
    except Exception as e:
        logger.error(f"ISAAC state save failed: {e}")
        return False


async def load_isaac_state():
    """Load ISAAC state from dedicated file."""
    try:
        if os.path.exists(ISAAC_STATE_FILE):
            with open(ISAAC_STATE_FILE, "r") as f:
                data = json.load(f)

            global ISAAC_DCA_INITIAL_USDT

            if "ISAAC_DCA_INITIAL_USDT" in data:
                ISAAC_DCA_INITIAL_USDT = float(data["ISAAC_DCA_INITIAL_USDT"])

            # TRAILING STOP
            data["isaac_trailing_stop"] = (
                float(data["isaac_trailing_stop"]) 
                if data.get("isaac_trailing_stop") is not None else None
            )
            data["isaac_trailing_distance"] = (
                float(data["isaac_trailing_distance"]) 
                if data.get("isaac_trailing_distance") is not None else None
        
            )

            # TRAILING DIP
            data["isaac_trailing_dip_active"] = bool(data.get("isaac_trailing_dip_active", False))
            data["isaac_dip_level"] = (
                float(data["isaac_dip_level"]) 
                if data.get("isaac_dip_level") is not None else None
            )
            data["isaac_dip_distance"] = (
                float(data["isaac_dip_distance"]) 
                if data.get("isaac_dip_distance") is not None else None
            )

            # Safety defaults
            data.setdefault("orders", [])
            data.setdefault("virtual_usdt", 0.0)
            data.setdefault("paused", False)

            logger.info(f"ISAAC State Loaded | Version: {data.get('version')} | Orders: {len(data.get('orders', []))}")
            return data

        # Fresh start
        logger.info("No ISAAC state file found >> Creating new state (v3)")
        return {
            "version": "isaac_v3",
            "orders": [],
            "virtual_usdt": 0.0,
            "paused": False,
            "ISAAC_DCA_INITIAL_USDT": ISAAC_DCA_INITIAL_USDT,
            "isaac_trailing_stop": None,
            "isaac_trailing_distance": None,
            "isaac_trailing_dip_active": False,
            "isaac_dip_level": None,
            "isaac_dip_distance": None
            
        }

    except Exception as e:
        logger.error(f"ISAAC state load failed: {e}")
        return {
            "version": "isaac_v3",
            "orders": [],
            "virtual_usdt": 0.0,
            "paused": False,
            "ISAAC_DCA_INITIAL_USDT": ISAAC_DCA_INITIAL_USDT,
            "isaac_trailing_stop": None,
            "isaac_trailing_distance": None,
            "isaac_trailing_dip_active": False,
            "isaac_dip_level": None,
            "isaac_dip_distance": None
            
        }
    
async def isaac_dca_job():
    """ISAAC Spot DCA: Dedicated pool + automatic profit sweep to Main bot
       Special rule: First order uses 5000 USDT, later orders follow original 1000 * 1.5^n formula
    """
    logger.debug("ISAAC DCA Job: Starting check...")
    if not ISAAC_DCA_ENABLED:
        logger.debug("ISAAC DCA: Disabled")
        return
   
    bot = Bot(TELEGRAM_TOKEN)
    global MAIN_ALLOCATED_USDT
   
    try:
        symbol = ISAAC_DCA_SYMBOL
        current_price = await get_current_price(symbol)
        if current_price is None:
            logger.debug("ISAAC DCA: No price—skipping")
            return
       
        isaac = await load_isaac_state()
        if isaac.get('paused', False):
            logger.debug("ISAAC DCA paused—skipping")
            return
       
        # Fetch real balances
        account = await binance_request("GET", "/api/v5/account/balances")
        quote_balance = 0.0
        base_balance = 0.0
        base_asset = symbol.split('/')[0].upper()
        if account:
            for asset in account:
                if asset["ccy"].upper() == "USDT":
                    quote_balance = float(asset.get("availBal", "0"))
                if asset["ccy"].upper() == base_asset:
                    base_balance = float(asset.get("availBal", "0"))
        # Capital Management
        if isaac.get('virtual_usdt', 0) < ISAAC_ALLOCATED_USDT * 0.9:
            isaac['virtual_usdt'] = ISAAC_ALLOCATED_USDT
            logger.info(f"ISAAC DCA: Reset virtual_usdt to full allocated capital >> {ISAAC_ALLOCATED_USDT:.2f}")
            await save_isaac_state(isaac)
        used_by_isaac = base_balance * current_price if current_price > 0 else 0.0
        available_for_isaac = max(0.0, ISAAC_ALLOCATED_USDT - used_by_isaac)
        alloc_usdt = min(available_for_isaac, isaac['virtual_usdt'])
        if alloc_usdt < DCA_MIN_USDT:
            logger.debug(f"ISAAC DCA: No capital left in its pool ({alloc_usdt:.2f})")
            await save_isaac_state(isaac)
            return
        # Pause if main bot active
        pre = pre_orders.get(symbol, {})
        if pre.get('order_type') == 'buy' and pre.get('amount', 0) > 0:
            logger.debug("ISAAC DCA skipped: Active pattern position")
            isaac['paused'] = True
            await save_isaac_state(isaac)
            return
        # Cycle state
        if isaac['orders']:
            total_size = sum(o['size'] for o in isaac['orders'])
            avg_entry = sum(o['size'] * o['entry_price'] for o in isaac['orders']) / total_size
            last_entry = isaac['orders'][-1]['entry_price']
        else:
            avg_entry = last_entry = current_price
        num_orders = len(isaac['orders'])
       
        logger.debug(f"ISAAC DCA: Cycle - Orders: {num_orders}, Last: {last_entry if isaac['orders'] else 'New'}")
        # ==================== DYNAMIC TP ====================
        if num_orders <= 1:
            dynamic_tp = 2.5
        elif num_orders == 2:
            dynamic_tp = 2.8
        elif num_orders == 3:
            dynamic_tp = 3.2
        elif num_orders == 4:
            dynamic_tp = 3.7
        elif num_orders == 5:
            dynamic_tp = 4.2
        elif num_orders == 6:
            dynamic_tp = 4.7
        else:  # 7/7
            dynamic_tp = 5.2
        # SELL CHECK + PROFIT SWEEP
        if avg_entry > 0 and current_price >= avg_entry * (1 + dynamic_tp / 100) and base_balance > 0: 
            total_size = sum(o['size'] for o in isaac['orders'])
            if total_size > 0:
                order = await isaac_execute_sell(symbol, None, current_price, total_size, "market", "ISAAC_DCA_TP", None, None, None, None, None)
                if order:
                    proceeds = total_size * current_price
                    cost_basis = total_size * avg_entry
                    profit = proceeds - cost_basis
                    profit_pct = (profit / cost_basis * 100) if cost_basis > 0 else 0.0
                    order_info = f"Orders: {num_orders}"
                    isaac['virtual_usdt'] += proceeds
                    isaac['orders'] = []
                    await record_compound_event(
                        "isaac_profit", profit, "ISAAC DCA TP", f"Dynamic TP {dynamic_tp}%",
                        invested=cost_basis, profit_pct=profit_pct, order_info=order_info
                    )
                    MAIN_ALLOCATED_USDT += profit
                    logger.info(f"ISAAC DCA TP Success: +{profit:.2f} USDT")
                    await send_telegram_message(bot, f"✅ ISAAC DCA TP Success! (+{dynamic_tp}%)")
                    await save_isaac_state(isaac)
                    await save_state()
            return
        # ==================== TRAILING DIP FOR 7TH ORDER ====================
        if num_orders == 6:
            
            # =========================================================
            # ACTIVATE TRAILING DIP (only once)
            # =========================================================
            if not isaac.get("isaac_trailing_dip_active", False):
                drop_pct = ((last_entry - current_price) / last_entry) * 100 if last_entry > 0 else 0
                
                # Triggers at -10% for 7th order
                if drop_pct >= (10.0 - 0.5):
                    isaac["isaac_trailing_dip_active"] = True
                    isaac["isaac_dip_trigger_price"] = current_price
                    isaac["isaac_dip_distance"] = current_price * 0.018
                    isaac["isaac_dip_level"] = current_price + isaac["isaac_dip_distance"]
                    logger.info(f"[TRAILING DIP ACTIVATED] Trigger: {isaac['isaac_dip_trigger_price']:.6f} | Dip Level: {isaac['isaac_dip_level']:.6f}")
                    await send_telegram_message(bot, 
                        f"📉 TRAILING DIP ACTIVATED\n"
                        f"Fixed Trigger: {isaac['isaac_dip_trigger_price']:.6f}\n"
                        f"Initial Dip Level: {isaac['isaac_dip_level']:.6f}")
                    await save_isaac_state(isaac)
            # =========================================================
            # IF TRAILING DIP IS ACTIVE → MONITOR EVERY CYCLE
            # =========================================================
            if isaac.get("isaac_trailing_dip_active", False):
                
                # Ratchet dip level down if price falls further
                new_dip_level = current_price + isaac.get("isaac_dip_distance", current_price * 0.018)
                if new_dip_level < isaac.get("isaac_dip_level", float("inf")):
                    old = isaac.get("isaac_dip_level")
                    isaac["isaac_dip_level"] = new_dip_level
                    logger.info(f"[TRAILING DIP RATCHET] {old:.6f} >> {new_dip_level:.6f} (Current: {current_price:.6f})")
                    await save_isaac_state(isaac)
                # BUY TRIGGER
                if current_price >= isaac.get("isaac_dip_level", 0):
                    logger.info(f"[TRAILING DIP BUY TRIGGERED] at {current_price:.6f}")
                    await send_telegram_message(bot, f"⚡ TRAILING DIP BUY TRIGGERED at {current_price:.6f}")
                    
                    # === SPECIAL FIRST ORDER LOGIC DOES NOT APPLY HERE (this is order 7) ===
                    buy_amount = ISAAC_DCA_INITIAL_USDT * (ISAAC_DCA_SIZE_MULTIPLIER ** num_orders)
                    buy_amount = min(buy_amount, alloc_usdt, isaac['virtual_usdt'])
                    buy_amount = round(buy_amount, 2)
                    if buy_amount >= ISAAC_DCA_INITIAL_USDT * 0.5 and quote_balance >= buy_amount:
                        body = {
                            "instId": symbol.replace('/', ''),
                            "side": "buy",
                            "ordType": "market",
                            "quoteOrderQty": str(buy_amount)
                        }
                        order_response = await binance_request("POST", "/api/v5/trade/order", body=body)
                        
                        if order_response and order_response.get("ordId"):
                            filled_qty = await confirm_order_fill(order_response["ordId"], symbol)
                            if filled_qty > 0:
                                isaac["orders"].append({"entry_price": current_price, "size": filled_qty})
                                isaac["virtual_usdt"] -= buy_amount
                                
                                # Reset Trailing Dip
                                isaac["isaac_trailing_dip_active"] = False
                                isaac["isaac_dip_level"] = None
                                isaac["isaac_dip_distance"] = None
                                
                                logger.info(f"✅ TRAILING DIP BUY EXECUTED: {filled_qty:.6f} @ {current_price:.6f}")
                                await send_telegram_message(bot, f"✅ TRAILING DIP BUY EXECUTED\nQty: {filled_qty:.6f} @ {current_price:.6f}")
                                await save_isaac_state(isaac)
                    return
        # ==================== TRAILING STOP  ====================
        if num_orders >= 7 and base_balance > 0:
            
            # ACTIVATE TRAILING STOP
            if isaac.get("isaac_trailing_stop") is None:
                isaac["isaac_trailing_distance"] = current_price * 0.020  
                isaac["isaac_trailing_stop"] = current_price - isaac["isaac_trailing_distance"]
                logger.info(f"[TRAILING STOP ACTIVATED] 2% from current price ({current_price:.6f}) | Stop: {isaac['isaac_trailing_stop']:.6f}")
                await send_telegram_message(bot,
                    f"TRAILING STOP ACTIVATED\n"
                    f"Trailing Stop: ${isaac.get('isaac_trailing_stop'):.6f}")
                await save_isaac_state(isaac)
            # ==================== DYNAMIC RATCHET LOGIC ====================
            unrealizedISAAC_pct = ((current_price - avg_entry) / avg_entry * 100) if avg_entry > 0 else 0
                    
            # Dynamic distance based on profitability
            if unrealizedISAAC_pct > 3.0:
                dynamic_distance = current_price * 0.008   # 0.8%
            elif unrealizedISAAC_pct > 1.0:
                dynamic_distance = current_price * 0.012   # 1.2%
            else:
                dynamic_distance = current_price * 0.018   # 1.8%
            # Update stored distance if changed significantly
            if abs(dynamic_distance - isaac.get("isaac_trailing_distance", 0)) > current_price * 0.001:
                isaac["isaac_trailing_distance"] = dynamic_distance
            # Ratchet the stop up
            new_stop = current_price - isaac["isaac_trailing_distance"]
            if new_stop > isaac.get("isaac_trailing_stop", 0):
                old_stop = isaac.get("isaac_trailing_stop")
                isaac["isaac_trailing_stop"] = new_stop
                
                logger.info(f"[TRAILING STOP RATCHET ↑] {old_stop:.6f} >> {new_stop:.6f} "
                          f"(Distance: {isaac['isaac_trailing_distance']/current_price*100:.2f}%, Unrealized: {unrealizedISAAC_pct:.2f}%)")
                await save_isaac_state(isaac)
            # STOP HIT → SELL
            if current_price <= isaac.get("isaac_trailing_stop", 0):
                total_size = sum(o['size'] for o in isaac['orders'])
                if total_size > 0:
                    logger.warning(f"[TRAILING STOP HIT] Selling all at {current_price:.6f}")
                    await send_telegram_message(bot, f"TRAILING STOP HIT at {current_price:.6f} (+{unrealizedISAAC_pct:.2f}%)")
                    order = await isaac_execute_sell(
                        symbol, None, current_price, total_size, "market",
                        "ISAAC_TRAILING_STOP", None, None, None, None, None
                    )
                    if order:
                        proceeds = total_size * current_price
                        cost_basis = total_size * avg_entry if avg_entry > 0 else 0
                        profit = proceeds - cost_basis
                        profit_pct = (profit / cost_basis * 100) if cost_basis > 0 else 0.0
                        order_info = f"Orders: {num_orders}"
                        
                        isaac["virtual_usdt"] += proceeds
                        isaac["orders"] = []
                        isaac["isaac_trailing_stop"] = None
                        isaac["isaac_trailing_distance"] = None
                        
                        await record_compound_event(
                            "isaac_profit", profit, "ISAAC DCA Trailing Stop", "Test Mode",
                            invested=cost_basis, profit_pct=profit_pct, order_info=order_info
                        )
                        MAIN_ALLOCATED_USDT += profit
                        
                        await send_telegram_message(bot,
                            f"✅ FULL EXIT VIA TRAILING STOP\n"
                            f"Size: {total_size:.6f} | Price: {current_price:.6f} | PnL: ${profit:.2f} | +{unrealizedISAAC_pct:.2f}%")
                        await save_isaac_state(isaac)
                        await save_state()
                return
        # ==================== DYNAMIC DROP PERCENTAGE LOGIC ====================
        if num_orders == 0:
            required_drop = 0.0
        elif num_orders == 1:
            required_drop = 3.0
        elif num_orders == 2:
            required_drop = 5.0
        elif num_orders == 3:
            required_drop = 8.0
        elif num_orders == 4:
            required_drop = 24.0
        elif num_orders == 5:
            required_drop = 32.0
        else:
            required_drop = 40.0
        drop_pct = ((last_entry - current_price) / last_entry) * 100 if last_entry > 0 else 0
        logger.debug(f"ISAAC DCA: Price {current_price:.6f}, Last {last_entry:.6f}, Drop {drop_pct:.2f}% / Required: -{required_drop}% for order #{num_orders+1}")
        # ==================== NORMAL BUY CHECK ====================
        if (num_orders < ISAAC_DCA_MAX_ORDERS and 
            (num_orders == 0 or drop_pct >= required_drop) and
            not isaac.get("isaac_trailing_dip_active", False)):
            
            # ========== SPECIAL FIRST ORDER LOGIC ==========
            if num_orders == 0:
                buy_amount = 5000.0          # <-- Special larger first order
            else:
                # Original formula (as if first order was 1000)
                buy_amount = ISAAC_DCA_INITIAL_USDT * (ISAAC_DCA_SIZE_MULTIPLIER ** num_orders)
            
            buy_amount = min(buy_amount, alloc_usdt, isaac['virtual_usdt'])
            buy_amount = round(buy_amount, 2)
            
            if buy_amount < ISAAC_DCA_INITIAL_USDT * 0.5:
                logger.debug(f"ISAAC DCA buy_amount too low: {buy_amount}—skipping")
                return
            
            logger.debug(f"ISAAC DCA: Trigger #{num_orders+1} for ${buy_amount:.2f}")
            
            if quote_balance < buy_amount:
                logger.warning(f"ISAAC DCA insufficient USDT")
                return
            
            body = {
                "instId": symbol.replace('/', ''),
                "side": "buy",
                "ordType": "market",
                "quoteOrderQty": str(buy_amount)
            }
            order_response = await binance_request("POST", "/api/v5/trade/order", body=body)
            
            if order_response and order_response.get("ordId"):
                order_id = order_response["ordId"]
                filled_qty = await confirm_order_fill(order_id, symbol)
                if filled_qty > 0:
                    isaac['orders'].append({'entry_price': current_price, 'size': filled_qty})
                    isaac['virtual_usdt'] -= buy_amount
                    
                    logger.info(f"ISAAC DCA Buy #{num_orders+1}: {filled_qty:.6f} {base_asset} @ {current_price:.6f} (${buy_amount})")
                    await send_telegram_message(bot, f"ISAAC DCA #{num_orders+1}: Bought {filled_qty:.6f} @ {current_price:.6f} (${buy_amount})")
                    await save_isaac_state(isaac)
            else:
                logger.warning(f"ISAAC DCA Buy rejected")
    except Exception as e:
        logger.error(f"ISAAC DCA Job Error: {str(e)}")
    logger.debug("ISAAC DCA Job: Check complete")
    
async def emergency_isaac(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Emergency full sell for ISAAC DCA - calls official isaac_execute_sell for perfect sync"""
    bot = update.get_bot()
    symbol = ISAAC_DCA_SYMBOL

    try:
        current_price = await get_current_price(symbol)
        
        # Get real wallet balance
        account = await binance_request("GET", "/api/v5/account/balances")
        base_balance = 0.0
        base_asset = symbol.split('/')[0].upper()
        for asset in account or []:
            if asset["ccy"].upper() == base_asset:
                base_balance = float(asset.get("availBal", "0"))

        if base_balance <= 0:
            await send_telegram_message(bot, f"❌ No {base_asset} balance available for ISAAC DCA to sell.")
            return

        logger.warning(f"🚨 EMERGENCY SELL via /emergency_isaac >> Calling isaac_execute_sell for {base_balance:.6f} {base_asset}")

        # === CALL THE OFFICIAL FUNCTION ===
        order = await isaac_execute_sell(
            symbol=symbol, 
            pre=None, 
            price=current_price, 
            quantity=base_balance, 
            order_type="market", 
            reason="EMERGENCY_MANUAL", 
            rsi=None, macd_line=None, middle_band=None, btc_ig=None, csi=None
        )

        if order and order.get("quantity"):
            # Reset ISAAC state 
            isaac = await load_isaac_state()
            isaac['orders'] = []
            # Removed old trailing stop fields
            
            await save_isaac_state(isaac)

            await send_telegram_message(bot, 
                f"✅ EMERGENCY SELL SUCCESSFUL\n"
                f"Sold {order['quantity']:.6f} {base_asset} @ {current_price:.8f}\n"
                f"Cycle reset to 0/7. New buy cycle will start soon.")
        else:
            await send_telegram_message(bot, "❌ Emergency sell failed - check logs.")

    except Exception as e:
        logger.error(f"Emergency /emergency_isaac error: {e}")
        await send_telegram_message(bot, f"❌ Error during emergency sell: {e}")

def _append_profit_to_excel_tracker(
    bot_label: str,
    profit_usdt: float,
    engaged_usdt: float = None,
    profit_pct: float = None,
    notes: str = "",
    source: str = "",
    details: str = "",
    order_info: str = None,
):
    """
    Auto-append a closed-trade row to ABINANCE_Live_Tracker.xlsx (USDT only).

    Architecture respected:
      1. Live Tracker → Section 2 (next empty yellow row B22:G36)
         F column keeps its existing formula (=D/E).
      2. Full History → new permanent row (Date, Time, Type, Profit, Engaged,
         Profit %, Orders, Source, Details, Main Running After).

    Safe if the file is missing, locked by Excel, or openpyxl is unavailable:
    logs a warning and does not raise.
    """
    if not OPENPYXL_AVAILABLE:
        logger.warning("[EXCEL TRACKER] openpyxl not installed — skip Excel write")
        return False

    path = EXCEL_TRACKER_FILE
    if not os.path.isfile(path):
        logger.warning(f"[EXCEL TRACKER] File not found: {path}")
        return False

    try:
        now = datetime.now(timezone.utc)
        date_val = now.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
        time_str = now.strftime("%H:%M:%S")
        bot_label = str(bot_label).upper().strip()
        if bot_label not in ("MAIN", "ISAAC"):
            bot_label = "MAIN" if "main" in bot_label.lower() else "ISAAC"

        profit_usdt = round(float(profit_usdt), 4)
        engaged = round(float(engaged_usdt), 4) if engaged_usdt is not None else None
        pct = None
        if profit_pct is not None:
            # Full History stores Profit % as fraction (0.0298 = 2.98%)
            pct = float(profit_pct)
            if pct > 1.0:  # callers often pass percent (2.98) not fraction
                pct = pct / 100.0
            pct = round(pct, 6)
        elif engaged and engaged > 0:
            pct = round(profit_usdt / engaged, 6)

        # Parse order count from "Orders: 3" / "Order 1" style strings
        orders_val = None
        if order_info:
            m = re.search(r"(\d+)", str(order_info))
            if m:
                orders_val = int(m.group(1))

        note_text = notes or time_str
        if details and not notes:
            note_text = f"{time_str} | {details}"[:80]

        wb = openpyxl.load_workbook(path)

        # ---------- Section 2 (Live Tracker) ----------
        if "Live Tracker" in wb.sheetnames:
            ws = wb["Live Tracker"]
            target_row = None
            for r in range(_EXCEL_SECTION2_FIRST_ROW, _EXCEL_SECTION2_LAST_ROW + 1):
                # Empty when both Bot and Profit are blank
                if ws.cell(row=r, column=3).value in (None, "") and ws.cell(row=r, column=4).value in (None, ""):
                    target_row = r
                    break
            if target_row is not None:
                yellow = PatternFill(start_color="FFFF99", end_color="FFFF99", fill_type="solid")
                ws.cell(row=target_row, column=2).value = date_val          # B Date
                ws.cell(row=target_row, column=3).value = bot_label        # C MAIN/ISAAC
                ws.cell(row=target_row, column=4).value = profit_usdt      # D Profit USDT
                ws.cell(row=target_row, column=5).value = engaged          # E Engaged
                # F already has formula =IF(OR(D="",E=""),"",D/E) — leave it
                existing_f = ws.cell(row=target_row, column=6).value
                if not existing_f:
                    ws.cell(row=target_row, column=6).value = (
                        f'=IF(OR(D{target_row}="",E{target_row}=""),"",D{target_row}/E{target_row})'
                    )
                ws.cell(row=target_row, column=7).value = note_text        # G Notes
                for col in range(2, 8):
                    if col != 6:
                        ws.cell(row=target_row, column=col).fill = yellow
                logger.info(f"[EXCEL TRACKER] Section 2 row {target_row}: {bot_label} +{profit_usdt}")
            else:
                logger.warning(
                    "[EXCEL TRACKER] Section 2 full (rows 22-36). "
                    "Row still written to Full History only."
                )

        # ---------- Full History (permanent archive) ----------
        if "Full History" in wb.sheetnames:
            fh = wb["Full History"]
            next_row = fh.max_row + 1
            # Main Running After = last known running + this profit
            last_running = 0.0
            for r in range(fh.max_row, 1, -1):
                v = fh.cell(row=r, column=10).value  # J
                if v is not None:
                    try:
                        last_running = float(v)
                        break
                    except (TypeError, ValueError):
                        continue
            main_running_after = round(last_running + profit_usdt, 4)

            fh.cell(row=next_row, column=1).value = now.strftime("%Y-%m-%d")
            fh.cell(row=next_row, column=2).value = time_str
            fh.cell(row=next_row, column=3).value = bot_label
            fh.cell(row=next_row, column=4).value = profit_usdt
            fh.cell(row=next_row, column=5).value = engaged if engaged is not None else ""
            fh.cell(row=next_row, column=6).value = pct if pct is not None else ""
            fh.cell(row=next_row, column=7).value = orders_val if orders_val is not None else ""
            fh.cell(row=next_row, column=8).value = source or ""
            fh.cell(row=next_row, column=9).value = details or ""
            fh.cell(row=next_row, column=10).value = main_running_after
            logger.info(
                f"[EXCEL TRACKER] Full History row {next_row}: {bot_label} "
                f"+{profit_usdt} | running={main_running_after}"
            )

        wb.save(path)
        wb.close()
        return True
    except PermissionError:
        logger.error(
            f"[EXCEL TRACKER] Cannot write — file is open in Excel. "
            f"Close it and the next trade will be logged. Path: {path}"
        )
        return False
    except Exception as e:
        logger.error(f"[EXCEL TRACKER] Write failed: {e}")
        return False


async def record_compound_event(event_type: str, amount: float, source: str = "", details: str = "",
                                invested: float = None, profit_pct: float = None, order_info: str = None):
    """Record any compounding or profit event.
    amount = profit USDT (or injection amount)
    invested = capital engaged (cost basis)
    profit_pct = profit percentage
    order_info = e.g. 'Orders: 3' or 'Order 1' for Isaac
    """
    global compounding_history
    from datetime import datetime, timezone
    
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
        "amount": round(float(amount), 4),
        "source": source,
        "details": details,
        "invested": round(float(invested), 4) if invested is not None else None,
        "profit_pct": round(float(profit_pct), 4) if profit_pct is not None else None,
        "order_info": order_info
    }
    
    if ACTIVE_SLOT.get() == "USDC":
        compounding_history_usdc.append(event)
        if len(compounding_history_usdc) > 3000:
            del compounding_history_usdc[:-3000]
    else:
        compounding_history.append(event)
        # Keep only last 3000 events
        if len(compounding_history) > 3000:
            compounding_history = compounding_history[-3000:]
        # Auto-log closed Main / ISAAC profits into the Live Tracker Excel (USDT only)
        if event_type in ("main_profit", "isaac_profit"):
            bot_label = "MAIN" if event_type == "main_profit" else "ISAAC"
            try:
                _append_profit_to_excel_tracker(
                    bot_label=bot_label,
                    profit_usdt=event["amount"],
                    engaged_usdt=event.get("invested"),
                    profit_pct=event.get("profit_pct"),
                    notes="",
                    source=source,
                    details=details,
                    order_info=order_info,
                )
            except Exception as excel_err:
                logger.error(f"[EXCEL TRACKER] Unexpected error: {excel_err}")
    
    await save_compounding_history()


async def save_compounding_history():
    try:
        with open(COMPOUNDING_HISTORY_FILE, 'w') as f:
            json.dump(compounding_history, f, indent=2, default=str)
        with open(COMPOUNDING_HISTORY_FILE_USDC, 'w') as f:
            json.dump(compounding_history_usdc, f, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to save compounding history: {e}")


async def load_compounding_history():
    global compounding_history, compounding_history_usdc
    try:
        if os.path.exists(COMPOUNDING_HISTORY_FILE):
            with open(COMPOUNDING_HISTORY_FILE, 'r') as f:
                compounding_history = json.load(f)
            logger.info(f"Compounding history loaded: {len(compounding_history)} events")
        else:
            # Create empty history file on first run
            compounding_history = []
            logger.info("Compounding history file created (empty)")
        if os.path.exists(COMPOUNDING_HISTORY_FILE_USDC):
            with open(COMPOUNDING_HISTORY_FILE_USDC, 'r') as f:
                compounding_history_usdc = json.load(f)
            logger.info(f"USDC compounding history loaded: {len(compounding_history_usdc)} events")
        else:
            compounding_history_usdc = []
        await save_compounding_history()
            
    except Exception as e:
        logger.error(f"Failed to load compounding history: {e}")
        compounding_history = []
        compounding_history_usdc = []

async def compound_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bot = update.get_bot()
        isaac = await load_isaac_state()

        # Fetch current wallet
        account = await binance_request("GET", "/api/v5/account/balances")
        total_usdt = 0.0
        for asset in account or []:
            if asset["ccy"].upper() == "USDT":
                total_usdt = float(asset.get("availBal", "0"))
                break

        # Calculate totals from history
        main_profits = [e["amount"] for e in compounding_history if e["type"] == "main_profit"]
        isaac_profits = [e["amount"] for e in compounding_history if e["type"] == "isaac_profit"]
        
        total_main_profit = sum(main_profits)
        total_isaac_profit = sum(isaac_profits)

        main_trade_count = len(main_profits)
        isaac_trade_count = len(isaac_profits)

        # Calculate total growth
        total_growth = total_main_profit + total_isaac_profit

        msg = "🔥 COMPOUNDING STATUS PANEL 🔥\n\n"
        msg += f"📊 Total Wallet USDT     : ${total_usdt:,.2f}\n\n"

        # ==================== UPDATED SECTION 1 ====================
        msg += f"1. Main Bot Asset       : ${MAIN_ALLOCATED_USDT:,.2f}   (+${total_growth:,.2f} Total Growth)\n"
        msg += f"   (Started at 5000)\n"
        msg += f"   • ISAAC DCA Contribution : +${total_isaac_profit:,.2f}\n"
        msg += f"   • Main Bot Contribution  : +${total_main_profit:,.2f}\n\n"
        # ===========================================================

        msg += f"2. ISAAC DCA Asset      : ${ISAAC_ALLOCATED_USDT:,.2f}\n"
        msg += f"   Initial Buy Size     : ${ISAAC_DCA_INITIAL_USDT:.0f}\n\n"

        combined_profit = total_main_profit + total_isaac_profit
        main_pct = (total_main_profit / 5000 * 100) if total_main_profit > 0 else 0

        msg += f"3. Profit from Main Bot : ${total_main_profit:,.2f} ({main_pct:.1f}% from initial)\n"
        msg += f"4. Profit from ISAAC DCA: ${total_isaac_profit:,.2f}\n"
        msg += f"5. Combined Profit      : ${combined_profit:,.2f}\n\n"

        msg += f"6. Main Bot Trades      : {main_trade_count} trades\n"
        msg += f"7. ISAAC DCA Trades     : {isaac_trade_count} trades\n\n"

        # ========== OPEN POSITIONS (still invested, profit N/A) ==========
        open_main_lines = []
        for sym, pre in pre_orders.items():
            if quote_of(sym) == "USDC":
                continue
            if pre.get("order_type") == "buy" and pre.get("amount", 0) > 0 and pre.get("entry_price"):
                inv = pre["amount"] * pre["entry_price"]
                open_main_lines.append(
                    f"   • OPEN {sym} |Invested: ${inv:,.2f}"
                )
        if open_main_lines:
            msg += "📌 Open Main Bot Positions:\n"
            msg += "\n".join(open_main_lines) + "\n\n"

        open_isaac_lines = []
        isaac_orders = isaac.get("orders", [])
        if isaac_orders:
            total_size = sum(o["size"] for o in isaac_orders)
            avg_entry = sum(o["size"] * o["entry_price"] for o in isaac_orders) / total_size if total_size > 0 else 0
            inv = total_size * avg_entry
            num = len(isaac_orders)
            # Build per-order summary
            order_details = []
            for i, o in enumerate(isaac_orders, 1):
                o_inv = o["size"] * o["entry_price"]
                order_details.append(f"Order {i}: ${o_inv:,.2f}")
            details_str = " | ".join(order_details) if order_details else ""
            open_isaac_lines.append(
                f"   • OPEN |Invested:${inv:,.2f} ({num} order{'s' if num > 1 else ''})"
            )
            if details_str:
                open_isaac_lines.append(f"      ({details_str})")
        if open_isaac_lines:
            msg += "📌 Open ISAAC DCA Positions:\n"
            msg += "\n".join(open_isaac_lines) + "\n\n"

        # ========== Last 30 Main Bot Trades (rich) ==========
        msg += "8. Last 30 Main Bot Trades:\n"
        main_trades = [e for e in compounding_history if e["type"] == "main_profit"]
        if not main_trades:
            msg += "   (none yet)\n"
        else:
            for trade in reversed(main_trades[-30:]):
                time_str = trade["timestamp"][:16].replace("T", " ")
                inv = trade.get("invested")
                pct = trade.get("profit_pct")
                if inv is not None and pct is not None:
                    msg += f"   • {time_str} |${inv:,.2f}->TP:+${trade['amount']:.2f}/{pct:.2f}%\n"
                else:
                    # Backward compatible for old events
                    msg += f"   • {time_str} | Profit:+${trade['amount']:.2f}\n"

        # ========== Last 30 ISAAC DCA Trades (rich) ==========
        msg += "\n9. Last 30 ISAAC DCA Trades:\n"
        isaac_trades = [e for e in compounding_history if e["type"] == "isaac_profit"]
        if not isaac_trades:
            msg += "   (none yet)\n"
        else:
            for trade in reversed(isaac_trades[-30:]):
                time_str = trade["timestamp"][:16].replace("T", " ")
                inv = trade.get("invested")
                pct = trade.get("profit_pct")
                oinfo = trade.get("order_info") or ""
                if inv is not None and pct is not None:
                    inv_str = f"${inv:,.2f}"
                    if oinfo:
                        inv_str += f" ({oinfo})"
                    msg += f"   • {time_str} |{inv_str}->TP:+${trade['amount']:.2f}/{pct:.2f}%\n"
                else:
                    # Backward compatible
                    msg += f"   • {time_str} |Profit:+${trade['amount']:.2f}\n"

        await send_telegram_message(bot, msg)

    except Exception as e:
        logger.error(f"Compound Status Error: {e}")
        await send_telegram_message(bot, f"Compound Status Error: {e}")


async def compound_status2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """USDC-lane compounding panel. Does not include Isaac DCA."""
    token = ACTIVE_SLOT.set("USDC")
    try:
        bot = update.get_bot()
        account = await binance_request("GET", "/api/v5/account/balances")
        total_quote = 0.0
        for asset in account or []:
            if asset["ccy"].upper() == "USDC":
                total_quote = float(asset.get("availBal", "0"))
                break
        main_profits = [e["amount"] for e in compounding_history_usdc if e["type"] == "main_profit"]
        total_main_profit = sum(main_profits)
        alloc = MAIN_ALLOCATED_USDT.get("USDC")
        msg = "🔥 COMPOUNDING STATUS PANEL (USDC) 🔥\n\n"
        msg += f"📊 Total Wallet USDC     : ${total_quote:,.2f}\n\n"
        msg += f"1. USDC Lane Asset      : ${alloc:,.2f}   (+${total_main_profit:,.2f} growth)\n"
        msg += f"   (Started at 5000)\n"
        msg += f"   • This lane does not include Isaac DCA. Use /compound_status for Isaac.\n\n"
        msg += f"2. Profit from USDC lane: ${total_main_profit:,.2f}\n"
        msg += f"3. USDC lane trades     : {len(main_profits)} trades\n\n"
        shown = active_symbol()
        if shown:
            msg += f"Pair: {shown}\n\n"
        else:
            msg += "Pair: not set. Use /pair2\n\n"
        open_lines = []
        for sym, pre in pre_orders.items():
            if quote_of(sym) != "USDC":
                continue
            if pre.get("order_type") == "buy" and pre.get("amount", 0) > 0 and pre.get("entry_price"):
                inv = pre["amount"] * pre["entry_price"]
                open_lines.append(f"   • OPEN {sym} |Invested: ${inv:,.2f}")
        if open_lines:
            msg += "📌 Open USDC Lane Positions:\n" + "\n".join(open_lines) + "\n\n"
        msg += "4. Last 30 USDC Lane Trades:\n"
        if not main_profits:
            msg += "   (none yet)\n"
        else:
            trades = [e for e in compounding_history_usdc if e["type"] == "main_profit"]
            for trade in reversed(trades[-30:]):
                time_str = trade["timestamp"][:16].replace("T", " ")
                inv = trade.get("invested")
                pct = trade.get("profit_pct")
                if inv is not None and pct is not None:
                    msg += f"   • {time_str} |${inv:,.2f}->TP:+${trade['amount']:.2f}/{pct:.2f}%\n"
                else:
                    msg += f"   • {time_str} | Profit:+${trade['amount']:.2f}\n"
        await send_telegram_message(bot, msg)
    except Exception as e:
        logger.error(f"Compound Status2 Error: {e}")
        try:
            await send_telegram_message(update.get_bot(), f"Compound Status2 Error: {e}")
        except Exception:
            pass
    finally:
        ACTIVE_SLOT.reset(token)


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error: {context.error}", exc_info=True)
    if update:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="An error occurred. Please try again or contact the administrator."
        )     

async def main():
    logger.info("Bot started")
    try:
        await load_state()
        await load_compounding_history() 
        await sync_open_orders()

        scheduler = AsyncIOScheduler(timezone=pytz.UTC)
        logger.info("Scheduler initialized")
        
        def scheduler_error_handler(event):
            if event.exception:
                logger.error(f"Scheduler job failed: {event.exception}", exc_info=True)
        
        scheduler.add_listener(scheduler_error_handler, EVENT_JOB_ERROR)
        scheduler.start()
        logger.info("Scheduler running")

        # ===== INSERT HERE: ISAAC DCA Scheduler (after start, before app) =====
        scheduler.add_job(
            isaac_dca_job,
            'interval',
            minutes=ISAAC_DCA_CHECK_INTERVAL_MIN,
            timezone=pytz.UTC,
            id='isaac_dca_job',
            replace_existing=True
        )
        logger.info(f"ISAAC DCA scheduled: Every {ISAAC_DCA_CHECK_INTERVAL_MIN}min on {ISAAC_DCA_SYMBOL}, initial ${ISAAC_DCA_INITIAL_USDT}")
        logger.info("Dual lane ready | /pair -> USDT (AAA.json, AAA.log) | /pair2 -> USDC (AAA_USDC.json, AAA_USDC.log) | Isaac unchanged")
        # ===== END INSERT =====

        # ==================== STATE BACKUP SCHEDULER ====================
        scheduler.add_job(
            backup_state_file,
            'interval',
            minutes=STATE_BACKUP_INTERVAL_MINUTES,
            timezone=pytz.UTC,
            id='state_backup_job',
            replace_existing=True
        )
        logger.info(f"State backup scheduled every {STATE_BACKUP_INTERVAL_MINUTES} minutes to {STATE_BACKUP_FOLDER}")
        # =================================================================

        


        application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
        application.add_error_handler(error_handler)

        application.add_handler(
            MessageHandler(filters.COMMAND, handle_unauthorized), 
            group=-10
        )

        pair_handler = ConversationHandler(
            entry_points=[CommandHandler("pair", pair_start)],
            states={PAIR: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_pair)]},
            fallbacks=[CommandHandler("cancel", pair_cancel)],
        )

        buy_price_handler = ConversationHandler(
            entry_points=[CommandHandler("buy_price", buy_price_start)],
            states={BUY_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_buy_price)]},
            fallbacks=[CommandHandler("cancel", lambda update, context: ConversationHandler.END)],
        )

        mb_handler = ConversationHandler(
            entry_points=[CommandHandler("mb", mb_start)],
            states={MB_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, mb_amount_received)]},
            fallbacks=[CommandHandler("cancel", lambda update, context: ConversationHandler.END)],
        )
        
        application.add_handler(pair_handler)
        application.add_handler(buy_price_handler)
        application.add_handler(mb_handler)
        application.add_handler(CommandHandler("reset_state", reset_state))
        application.add_handler(CommandHandler("magic_sell", magic_sell))
        application.add_handler(CommandHandler("balance", balance))
        application.add_handler(CommandHandler("status", status))
        application.add_handler(CommandHandler("price", price))
        application.add_handler(CommandHandler("isaac_status", isaac_status))
        application.add_handler(CommandHandler("emergency_isaac", emergency_isaac))
        application.add_handler(CommandHandler("compound_status", compound_status))

        # ===== USDC lane. Same handlers, isolated slot. Isaac is not duplicated. =====
        pair2_handler = ConversationHandler(
            entry_points=[CommandHandler("pair2", with_usdc_lane(pair_start))],
            states={PAIR: [MessageHandler(filters.TEXT & ~filters.COMMAND, with_usdc_lane(set_pair))]},
            fallbacks=[CommandHandler("cancel", with_usdc_lane(pair_cancel))],
            name="lane_usdc_pair",
        )
        buy_price2_handler = ConversationHandler(
            entry_points=[CommandHandler("buy_price2", with_usdc_lane(buy_price_start))],
            states={BUY_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, with_usdc_lane(set_buy_price))]},
            fallbacks=[CommandHandler("cancel", lambda update, context: ConversationHandler.END)],
            name="lane_usdc_buy_price",
        )
        mb2_handler = ConversationHandler(
            entry_points=[CommandHandler("mb2", with_usdc_lane(mb_start))],
            states={MB_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, with_usdc_lane(mb_amount_received))]},
            fallbacks=[CommandHandler("cancel", lambda update, context: ConversationHandler.END)],
            name="lane_usdc_mb",
        )
        application.add_handler(pair2_handler)
        application.add_handler(buy_price2_handler)
        application.add_handler(mb2_handler)
        application.add_handler(CommandHandler("reset_state2", with_usdc_lane(reset_state)))
        application.add_handler(CommandHandler("magic_sell2", with_usdc_lane(magic_sell)))
        application.add_handler(CommandHandler("balance2", with_usdc_lane(balance)))
        application.add_handler(CommandHandler("status2", with_usdc_lane(status)))
        application.add_handler(CommandHandler("price2", with_usdc_lane(price)))
        application.add_handler(CommandHandler("compound_status2", compound_status2))

        await application.initialize()
        await application.start()
        
        await asyncio.gather(
            trading_loop(),
            application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        )
    except Exception as e:
        logger.error(f"Bot failed to start or crashed: {str(e)}", exc_info=True)
        if 'application' in locals():
            await application.bot.send_message(
                chat_id=TELEGRAM_USER_ID,
                text=f"Bot failed to start or crashed: {str(e)}"
            )
    finally:
        logger.info("Shutting down bot")
        if 'scheduler' in locals() and scheduler.running:
            scheduler.shutdown()
        if 'application' in locals() and application.updater.running:
            await application.updater.stop()
            await application.stop()
            await application.shutdown()
        logger.info("Bot shutdown complete")

if __name__ == "__main__":
    asyncio.run(main())
