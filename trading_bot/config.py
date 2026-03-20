"""Trading system configuration and constants."""

import os
from dotenv import load_dotenv

load_dotenv()

# === Exchange Settings ===
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
SYMBOL = os.getenv("SYMBOL", "BTC/USDT")
LEVERAGE = int(os.getenv("LEVERAGE", "10"))
TOTAL_CAPITAL = float(os.getenv("TOTAL_CAPITAL", "1000"))
USE_TESTNET = True  # True = Testnet, False = Real

# === Telegram Settings ===
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# === Indicator Parameters ===
ZLSMA_LENGTH = 150
EMA_PERIODS = [5, 15, 25, 50, 200]
BOLLINGER_PERIOD = 20
BOLLINGER_STD = 2.0
ALMA_OFFSET = 0.85
ALMA_SIGMA = 6
ALMA_WINDOW = 9

# === Volume Settings ===
VOLUME_CANDLE_COUNT = 8  # Recent 8 candles for average
VOLUME_MULTIPLIER = 2.0  # 2x average volume required

# === Position Sizing (% of total capital) ===
POSITION_SIZE_EMA25 = 0.10       # 10% - EMA 25 touch (early entry)
POSITION_SIZE_EMA50 = 0.50       # 50% - EMA 50 touch (main entry)
POSITION_SIZE_EMA50_VWMA = 0.20  # 20% - EMA 50 + VWMA (strong entry)
POSITION_SIZE_BB_LOWER = 0.20    # 20% - 4H Bollinger lower touch
MAX_POSITION_RATIO = 0.80        # 80% max total position

# === Take Profit ===
TP1_RATIO = 0.30  # 30% at ZLSMA level
TP2_RATIO = 0.30  # 30% at 1H Bollinger upper
TP3_RATIO = 0.40  # 40% manual decision or avg price exit

# === Timeframes ===
TIMEFRAME_15M = "15m"
TIMEFRAME_1H = "1h"
TIMEFRAME_4H = "4h"

# === Polling Interval (seconds) ===
POLL_INTERVAL = 10

# === Trading Modes ===
MODE_LONG = "long"
MODE_SHORT = "short"
MODE_SCALP = "scalp"  # 단타 (both directions)
MODE_STOP = "stop"
