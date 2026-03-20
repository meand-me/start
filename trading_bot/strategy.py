"""Trading strategy: entry conditions, take profit, stop loss logic."""

import logging
from dataclasses import dataclass, field
from enum import Enum

import pandas as pd

from trading_bot import indicators as ind
from trading_bot.config import (
    ZLSMA_LENGTH, EMA_PERIODS, BOLLINGER_PERIOD, BOLLINGER_STD,
    VOLUME_CANDLE_COUNT, VOLUME_MULTIPLIER,
    POSITION_SIZE_EMA25, POSITION_SIZE_EMA50,
    POSITION_SIZE_EMA50_VWMA, POSITION_SIZE_BB_LOWER,
    MODE_LONG, MODE_SHORT, MODE_SCALP,
)

logger = logging.getLogger(__name__)


class EntryType(str, Enum):
    EMA25 = "ema25"
    EMA50 = "ema50"
    EMA50_VWMA = "ema50_vwma"
    BB_LOWER_4H = "bb_lower_4h"


@dataclass
class Signal:
    action: str  # "buy" | "sell" | "none"
    entry_type: EntryType | None = None
    size_ratio: float = 0.0
    stop_loss_price: float = 0.0
    reason: str = ""
    timeframe: str = ""


@dataclass
class TPSignal:
    level: str  # "TP1", "TP2", "TP3"
    close_ratio: float = 0.0
    reason: str = ""


@dataclass
class SLSignal:
    should_stop: bool = False
    reason: str = ""
    priority: int = 0  # 1=highest


class Strategy:
    """Evaluates entry/exit conditions based on the rule set."""

    def __init__(self, mode: str = MODE_LONG):
        self.mode = mode

    def set_mode(self, mode: str):
        self.mode = mode
        logger.info("Strategy mode set to: %s", mode)

    # ================================================================
    # ALMA pre-alert check
    # ================================================================
    def check_alma_alert(self, df_1h: pd.DataFrame) -> str | None:
        close = df_1h["close"]
        alma = ind.calc_alma(close)
        zlsma = ind.calc_zlsma(close, ZLSMA_LENGTH)

        if ind.alma_crossover_detected(alma, zlsma):
            return "ALMA 방향 전환! ZLSMA 양수 전환 가능성 있음. 매수 준비"
        return None

    # ================================================================
    # Common prerequisites
    # ================================================================
    def _check_common_long(self, df_15m: pd.DataFrame, close: float, zlsma_val: float) -> bool:
        """ZLSMA positive + 15m volume surge."""
        if not ind.zlsma_is_positive(zlsma_val, close):
            return False
        if not ind.volume_surge(df_15m["volume"], VOLUME_CANDLE_COUNT, VOLUME_MULTIPLIER):
            return False
        return True

    def _check_common_short(self, df_15m: pd.DataFrame, close: float, zlsma_val: float) -> bool:
        """ZLSMA negative + 15m volume surge (mirror of long)."""
        if ind.zlsma_is_positive(zlsma_val, close):
            return False
        if not ind.volume_surge(df_15m["volume"], VOLUME_CANDLE_COUNT, VOLUME_MULTIPLIER):
            return False
        return True

    # ================================================================
    # Entry signals (LONG)
    # ================================================================
    def _eval_long_entries(
        self, df: pd.DataFrame, df_15m: pd.DataFrame,
        df_4h: pd.DataFrame, indicators: dict, timeframe: str,
    ) -> Signal | None:
        close = df["close"].iloc[-1]
        low = df["low"].iloc[-1]
        high = df["high"].iloc[-1]
        zlsma = indicators["zlsma"]
        zlsma_val = zlsma.dropna().iloc[-1] if not zlsma.dropna().empty else close
        emas = indicators["emas"]
        vwma = indicators["vwma"]

        if not self._check_common_long(df_15m, close, zlsma_val):
            return None

        if not ind.has_bullish_pattern(df):
            return None

        pattern_low = ind.get_pattern_low(df)

        # Condition 3: EMA 50 + VWMA simultaneous touch (check first, highest priority among EMA)
        if 50 in emas and not emas[50].dropna().empty and not vwma.dropna().empty:
            ema50_val = emas[50].iloc[-1]
            vwma_val = vwma.iloc[-1]
            if (ind.price_touches_ema(low, high, ema50_val)
                    and ind.price_touches_vwma(low, high, vwma_val)
                    and ind.close_above_ema(close, ema50_val)):
                return Signal(
                    action="buy", entry_type=EntryType.EMA50_VWMA,
                    size_ratio=POSITION_SIZE_EMA50_VWMA,
                    stop_loss_price=pattern_low,
                    reason=f"EMA50+VWMA touch | close={close:.2f} ema50={ema50_val:.2f} vwma={vwma_val:.2f}",
                    timeframe=timeframe,
                )

        # Condition 2: EMA 50 touch (main entry)
        if 50 in emas and not emas[50].dropna().empty:
            ema50_val = emas[50].iloc[-1]
            if (ind.price_touches_ema(low, high, ema50_val)
                    and ind.close_above_ema(close, ema50_val)):
                return Signal(
                    action="buy", entry_type=EntryType.EMA50,
                    size_ratio=POSITION_SIZE_EMA50,
                    stop_loss_price=pattern_low,
                    reason=f"EMA50 touch | close={close:.2f} ema50={ema50_val:.2f}",
                    timeframe=timeframe,
                )

        # Condition 1: EMA 25 touch (early entry)
        if 25 in emas and not emas[25].dropna().empty:
            ema25_val = emas[25].iloc[-1]
            if (ind.price_touches_ema(low, high, ema25_val)
                    and ind.close_above_ema(close, ema25_val)):
                return Signal(
                    action="buy", entry_type=EntryType.EMA25,
                    size_ratio=POSITION_SIZE_EMA25,
                    stop_loss_price=pattern_low,
                    reason=f"EMA25 touch | close={close:.2f} ema25={ema25_val:.2f}",
                    timeframe=timeframe,
                )

        # Condition 4: 4H Bollinger lower touch
        if df_4h is not None and len(df_4h) > 0:
            bb_4h = ind.calc_bollinger(df_4h["close"], BOLLINGER_PERIOD, BOLLINGER_STD)
            bb_lower_val = bb_4h["lower"].iloc[-1]
            low_4h = df_4h["low"].iloc[-1]
            close_4h = df_4h["close"].iloc[-1]
            if (ind.price_touches_bb_lower(low_4h, bb_lower_val)
                    and ind.close_above_bb_lower(close_4h, bb_lower_val)):
                return Signal(
                    action="buy", entry_type=EntryType.BB_LOWER_4H,
                    size_ratio=POSITION_SIZE_BB_LOWER,
                    stop_loss_price=pattern_low,
                    reason=f"4H BB lower touch | close={close_4h:.2f} bb_lower={bb_lower_val:.2f}",
                    timeframe="4h",
                )

        return None

    # ================================================================
    # Entry signals (SHORT) — mirror of long
    # ================================================================
    def _eval_short_entries(
        self, df: pd.DataFrame, df_15m: pd.DataFrame,
        df_4h: pd.DataFrame, indicators: dict, timeframe: str,
    ) -> Signal | None:
        close = df["close"].iloc[-1]
        low = df["low"].iloc[-1]
        high = df["high"].iloc[-1]
        zlsma = indicators["zlsma"]
        zlsma_val = zlsma.dropna().iloc[-1] if not zlsma.dropna().empty else close
        emas = indicators["emas"]
        vwma = indicators["vwma"]

        if not self._check_common_short(df_15m, close, zlsma_val):
            return None

        if not ind.has_bearish_pattern(df):
            return None

        pattern_high = ind.get_pattern_high(df)

        # EMA 50 + VWMA touch (short)
        if 50 in emas and not emas[50].dropna().empty and not vwma.dropna().empty:
            ema50_val = emas[50].iloc[-1]
            vwma_val = vwma.iloc[-1]
            if (ind.price_touches_ema(low, high, ema50_val)
                    and ind.price_touches_vwma(low, high, vwma_val)
                    and ind.close_below_ema(close, ema50_val)):
                return Signal(
                    action="sell", entry_type=EntryType.EMA50_VWMA,
                    size_ratio=POSITION_SIZE_EMA50_VWMA,
                    stop_loss_price=pattern_high,
                    reason=f"SHORT EMA50+VWMA touch | close={close:.2f}",
                    timeframe=timeframe,
                )

        # EMA 50 touch (short)
        if 50 in emas and not emas[50].dropna().empty:
            ema50_val = emas[50].iloc[-1]
            if (ind.price_touches_ema(low, high, ema50_val)
                    and ind.close_below_ema(close, ema50_val)):
                return Signal(
                    action="sell", entry_type=EntryType.EMA50,
                    size_ratio=POSITION_SIZE_EMA50,
                    stop_loss_price=pattern_high,
                    reason=f"SHORT EMA50 touch | close={close:.2f}",
                    timeframe=timeframe,
                )

        # EMA 25 touch (short)
        if 25 in emas and not emas[25].dropna().empty:
            ema25_val = emas[25].iloc[-1]
            if (ind.price_touches_ema(low, high, ema25_val)
                    and ind.close_below_ema(close, ema25_val)):
                return Signal(
                    action="sell", entry_type=EntryType.EMA25,
                    size_ratio=POSITION_SIZE_EMA25,
                    stop_loss_price=pattern_high,
                    reason=f"SHORT EMA25 touch | close={close:.2f}",
                    timeframe=timeframe,
                )

        # 4H Bollinger upper touch (short)
        if df_4h is not None and len(df_4h) > 0:
            bb_4h = ind.calc_bollinger(df_4h["close"], BOLLINGER_PERIOD, BOLLINGER_STD)
            bb_upper_val = bb_4h["upper"].iloc[-1]
            high_4h = df_4h["high"].iloc[-1]
            close_4h = df_4h["close"].iloc[-1]
            if (ind.price_touches_bb_upper(high_4h, bb_upper_val)
                    and close_4h < bb_upper_val):
                return Signal(
                    action="sell", entry_type=EntryType.BB_LOWER_4H,
                    size_ratio=POSITION_SIZE_BB_LOWER,
                    stop_loss_price=pattern_high,
                    reason=f"SHORT 4H BB upper touch | close={close_4h:.2f}",
                    timeframe="4h",
                )

        return None

    # ================================================================
    # Main entry evaluation
    # ================================================================
    def evaluate_entry(
        self, df_1h: pd.DataFrame, df_15m: pd.DataFrame,
        df_4h: pd.DataFrame,
    ) -> Signal | None:
        """Evaluate entry conditions. Returns Signal or None."""
        indicators_1h = ind.compute_indicators(df_1h, EMA_PERIODS, ZLSMA_LENGTH)
        indicators_4h = ind.compute_indicators(df_4h, EMA_PERIODS, ZLSMA_LENGTH) if df_4h is not None else None

        signal = None

        if self.mode in (MODE_LONG, MODE_SCALP):
            # Check 4H first (stronger signal)
            signal = self._eval_long_entries(df_4h, df_15m, df_4h, indicators_4h, "4h") if indicators_4h else None
            if signal is None:
                signal = self._eval_long_entries(df_1h, df_15m, df_4h, indicators_1h, "1h")

        if signal is None and self.mode in (MODE_SHORT, MODE_SCALP):
            signal = self._eval_short_entries(df_4h, df_15m, df_4h, indicators_4h, "4h") if indicators_4h else None
            if signal is None:
                signal = self._eval_short_entries(df_1h, df_15m, df_4h, indicators_1h, "1h")

        return signal

    # ================================================================
    # 15m alert-only check
    # ================================================================
    def check_15m_alert(self, df_15m: pd.DataFrame) -> str | None:
        """15m timeframe: pattern detection for alert only (no entry)."""
        indicators = ind.compute_indicators(df_15m, EMA_PERIODS, ZLSMA_LENGTH)
        close = df_15m["close"].iloc[-1]
        low = df_15m["low"].iloc[-1]
        high = df_15m["high"].iloc[-1]
        emas = indicators["emas"]

        if not ind.has_bullish_pattern(df_15m):
            return None

        for period in [25, 50]:
            if period in emas and not emas[period].dropna().empty:
                ema_val = emas[period].iloc[-1]
                if ind.price_touches_ema(low, high, ema_val):
                    return f"[15분봉 알림] EMA{period} 터치 + 캔들 패턴 감지 | close={close:.2f}"
        return None

    # ================================================================
    # Take Profit evaluation
    # ================================================================
    def evaluate_tp(
        self, side: str, entry_price: float,
        df_1h: pd.DataFrame, tp1_done: bool, tp2_done: bool,
    ) -> TPSignal | None:
        close = df_1h["close"].iloc[-1]
        zlsma = ind.calc_zlsma(df_1h["close"], ZLSMA_LENGTH)
        zlsma_val = zlsma.dropna().iloc[-1] if not zlsma.dropna().empty else None
        bb_1h = ind.calc_bollinger(df_1h["close"], BOLLINGER_PERIOD, BOLLINGER_STD)

        if side == "long":
            # TP1: ZLSMA level
            if not tp1_done and zlsma_val is not None and close >= zlsma_val:
                return TPSignal("TP1", 0.30, f"ZLSMA 도달 | close={close:.2f} zlsma={zlsma_val:.2f}")

            # TP2: 1H Bollinger upper
            bb_upper = bb_1h["upper"].iloc[-1]
            if not tp2_done and close >= bb_upper:
                return TPSignal("TP2", 0.30, f"1H 볼린저 상단 도달 | close={close:.2f} bb_upper={bb_upper:.2f}")

        elif side == "short":
            # TP1: ZLSMA level (price below ZLSMA)
            if not tp1_done and zlsma_val is not None and close <= zlsma_val:
                return TPSignal("TP1", 0.30, f"ZLSMA 도달 | close={close:.2f} zlsma={zlsma_val:.2f}")

            # TP2: 1H Bollinger lower
            bb_lower = bb_1h["lower"].iloc[-1]
            if not tp2_done and close <= bb_lower:
                return TPSignal("TP2", 0.30, f"1H 볼린저 하단 도달 | close={close:.2f} bb_lower={bb_lower:.2f}")

        return None

    # ================================================================
    # Stop Loss evaluation
    # ================================================================
    def evaluate_sl(
        self, side: str, entry_type: str, sl_price: float,
        df: pd.DataFrame, df_15m: pd.DataFrame,
    ) -> SLSignal:
        close = df["close"].iloc[-1]
        zlsma = ind.calc_zlsma(df["close"], ZLSMA_LENGTH)
        zlsma_val = zlsma.dropna().iloc[-1] if not zlsma.dropna().empty else None

        if side == "long":
            # Priority 1: Candle pattern low break
            if close < sl_price:
                return SLSignal(True, f"캔들 패턴 저점 이탈 | close={close:.2f} sl={sl_price:.2f}", 1)

            # Priority 2: EMA 50 complete break (for EMA50 entries)
            if entry_type in (EntryType.EMA50, EntryType.EMA50_VWMA):
                emas = ind.calc_all_emas(df["close"], [50])
                ema50_val = emas[50].iloc[-1]
                if close < ema50_val:
                    return SLSignal(True, f"EMA50 완전 이탈 | close={close:.2f} ema50={ema50_val:.2f}", 2)

            # Priority 3: ZLSMA negative
            if zlsma_val is not None and not ind.zlsma_is_positive(zlsma_val, close):
                return SLSignal(True, f"ZLSMA 음수 전환 | close={close:.2f} zlsma={zlsma_val:.2f}", 3)

        elif side == "short":
            # Priority 1: Candle pattern high break
            if close > sl_price:
                return SLSignal(True, f"캔들 패턴 고점 돌파 | close={close:.2f} sl={sl_price:.2f}", 1)

            # Priority 2: EMA 50 complete break (for EMA50 entries)
            if entry_type in (EntryType.EMA50, EntryType.EMA50_VWMA):
                emas = ind.calc_all_emas(df["close"], [50])
                ema50_val = emas[50].iloc[-1]
                if close > ema50_val:
                    return SLSignal(True, f"EMA50 완전 돌파 | close={close:.2f} ema50={ema50_val:.2f}", 2)

            # Priority 3: ZLSMA positive (for short, means trend reversed)
            if zlsma_val is not None and ind.zlsma_is_positive(zlsma_val, close):
                return SLSignal(True, f"ZLSMA 양수 전환 | close={close:.2f} zlsma={zlsma_val:.2f}", 3)

        return SLSignal(False)
