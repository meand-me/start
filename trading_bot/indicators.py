"""Technical indicators: ZLSMA, EMA, VWMA, ALMA, Bollinger Bands, candle patterns, volume."""

import numpy as np
import pandas as pd


# ============================================================
# ZLSMA (Zero Lag Least Squares Moving Average)
# ============================================================
def calc_lsma(series: pd.Series, length: int) -> pd.Series:
    """Least Squares Moving Average."""
    result = pd.Series(index=series.index, dtype=float)
    for i in range(length - 1, len(series)):
        window = series.iloc[i - length + 1: i + 1].values
        x = np.arange(length)
        slope, intercept = np.polyfit(x, window, 1)
        result.iloc[i] = intercept + slope * (length - 1)
    return result


def calc_zlsma(close: pd.Series, length: int = 150) -> pd.Series:
    """Zero Lag LSMA = 2 * LSMA - LSMA(LSMA)."""
    lsma1 = calc_lsma(close, length)
    lsma2 = calc_lsma(lsma1.dropna(), length)
    # Align indices
    zlsma = 2 * lsma1 - lsma2
    return zlsma


def zlsma_is_positive(zlsma_value: float, close_value: float) -> bool:
    """ZLSMA is 'positive' when price is above ZLSMA (trending up)."""
    return close_value > zlsma_value


def zlsma_slope_positive(zlsma: pd.Series, lookback: int = 3) -> bool:
    """Check if ZLSMA slope is positive (heading up)."""
    recent = zlsma.dropna().tail(lookback)
    if len(recent) < 2:
        return False
    return recent.iloc[-1] > recent.iloc[-2]


# ============================================================
# EMA
# ============================================================
def calc_ema(close: pd.Series, period: int) -> pd.Series:
    return close.ewm(span=period, adjust=False).mean()


def calc_all_emas(close: pd.Series, periods: list[int]) -> dict[int, pd.Series]:
    return {p: calc_ema(close, p) for p in periods}


def price_touches_ema(low: float, high: float, ema_value: float) -> bool:
    """Price touches EMA if candle's low-high range covers the EMA value."""
    return low <= ema_value <= high


def close_above_ema(close: float, ema_value: float) -> bool:
    return close > ema_value


def close_below_ema(close: float, ema_value: float) -> bool:
    return close < ema_value


# ============================================================
# VWMA (Volume Weighted Moving Average)
# ============================================================
def calc_vwma(close: pd.Series, volume: pd.Series, period: int = 20) -> pd.Series:
    return (close * volume).rolling(window=period).sum() / volume.rolling(window=period).sum()


def price_touches_vwma(low: float, high: float, vwma_value: float) -> bool:
    return low <= vwma_value <= high


# ============================================================
# ALMA (Arnaud Legoux Moving Average)
# ============================================================
def calc_alma(close: pd.Series, window: int = 9, offset: float = 0.85, sigma: float = 6) -> pd.Series:
    result = pd.Series(index=close.index, dtype=float)
    m = offset * (window - 1)
    s = window / sigma

    for i in range(window - 1, len(close)):
        weights = np.array([np.exp(-((j - m) ** 2) / (2 * s * s)) for j in range(window)])
        weights /= weights.sum()
        val = np.dot(close.iloc[i - window + 1: i + 1].values, weights)
        result.iloc[i] = val
    return result


def alma_crossover_detected(alma: pd.Series, zlsma: pd.Series) -> bool:
    """ALMA crosses from negative to positive relative to ZLSMA (pre-alert)."""
    recent = (alma - zlsma).dropna().tail(3)
    if len(recent) < 2:
        return False
    return recent.iloc[-2] < 0 and recent.iloc[-1] >= 0


# ============================================================
# Bollinger Bands
# ============================================================
def calc_bollinger(close: pd.Series, period: int = 20, std_dev: float = 2.0) -> dict:
    middle = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    return {
        "upper": middle + std_dev * std,
        "middle": middle,
        "lower": middle - std_dev * std,
    }


def price_touches_bb_lower(low: float, bb_lower: float) -> bool:
    return low <= bb_lower


def price_touches_bb_upper(high: float, bb_upper: float) -> bool:
    return high >= bb_upper


def close_above_bb_lower(close: float, bb_lower: float) -> bool:
    return close > bb_lower


# ============================================================
# Candle Patterns
# ============================================================
def is_hammer(open_: float, high: float, low: float, close: float) -> bool:
    """Hammer pattern: small body at top, long lower shadow."""
    body = abs(close - open_)
    total_range = high - low
    if total_range == 0:
        return False
    lower_shadow = min(open_, close) - low
    upper_shadow = high - max(open_, close)
    return (
        lower_shadow >= 2 * body
        and upper_shadow <= body * 0.5
        and body / total_range <= 0.35
    )


def is_bullish_engulfing(
    prev_open: float, prev_close: float,
    curr_open: float, curr_close: float,
) -> bool:
    """Bullish engulfing: previous red candle fully engulfed by current green candle."""
    prev_bearish = prev_close < prev_open
    curr_bullish = curr_close > curr_open
    engulfs = curr_open <= prev_close and curr_close >= prev_open
    return prev_bearish and curr_bullish and engulfs


def is_inverted_hammer(open_: float, high: float, low: float, close: float) -> bool:
    """Inverted hammer (for short): small body at bottom, long upper shadow."""
    body = abs(close - open_)
    total_range = high - low
    if total_range == 0:
        return False
    upper_shadow = high - max(open_, close)
    lower_shadow = min(open_, close) - low
    return (
        upper_shadow >= 2 * body
        and lower_shadow <= body * 0.5
        and body / total_range <= 0.35
    )


def is_bearish_engulfing(
    prev_open: float, prev_close: float,
    curr_open: float, curr_close: float,
) -> bool:
    """Bearish engulfing for short positions."""
    prev_bullish = prev_close > prev_open
    curr_bearish = curr_close < curr_open
    engulfs = curr_open >= prev_close and curr_close <= prev_open
    return prev_bullish and curr_bearish and engulfs


def has_bullish_pattern(df: pd.DataFrame) -> bool:
    """Check if latest candle has hammer or bullish engulfing."""
    if len(df) < 2:
        return False
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    return (
        is_hammer(curr["open"], curr["high"], curr["low"], curr["close"])
        or is_bullish_engulfing(prev["open"], prev["close"], curr["open"], curr["close"])
    )


def has_bearish_pattern(df: pd.DataFrame) -> bool:
    """Check if latest candle has inverted hammer or bearish engulfing."""
    if len(df) < 2:
        return False
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    return (
        is_inverted_hammer(curr["open"], curr["high"], curr["low"], curr["close"])
        or is_bearish_engulfing(prev["open"], prev["close"], curr["open"], curr["close"])
    )


def get_pattern_low(df: pd.DataFrame) -> float:
    """Get the low of the candle pattern (for stop loss)."""
    if len(df) < 2:
        return df.iloc[-1]["low"]
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    # For engulfing, use the first candle's low
    if is_bullish_engulfing(prev["open"], prev["close"], curr["open"], curr["close"]):
        return prev["low"]
    # For hammer, use the hammer's low
    return curr["low"]


def get_pattern_high(df: pd.DataFrame) -> float:
    """Get the high of the candle pattern (for short stop loss)."""
    if len(df) < 2:
        return df.iloc[-1]["high"]
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    if is_bearish_engulfing(prev["open"], prev["close"], curr["open"], curr["close"]):
        return prev["high"]
    return curr["high"]


# ============================================================
# Volume
# ============================================================
def volume_surge(volume: pd.Series, count: int = 8, multiplier: float = 2.0) -> bool:
    """Check if latest volume is >= multiplier * average of last `count` candles."""
    if len(volume) < count + 1:
        return False
    avg_vol = volume.iloc[-(count + 1):-1].mean()
    return volume.iloc[-1] >= multiplier * avg_vol


# ============================================================
# Convenience: compute all indicators for a DataFrame
# ============================================================
def compute_indicators(df: pd.DataFrame, ema_periods: list[int],
                       zlsma_length: int = 150,
                       bb_period: int = 20, bb_std: float = 2.0) -> dict:
    """Compute all indicators and return them as a dict."""
    close = df["close"]
    volume = df["volume"]

    emas = calc_all_emas(close, ema_periods)
    zlsma = calc_zlsma(close, zlsma_length)
    vwma = calc_vwma(close, volume)
    alma = calc_alma(close)
    bb = calc_bollinger(close, bb_period, bb_std)

    return {
        "emas": emas,
        "zlsma": zlsma,
        "vwma": vwma,
        "alma": alma,
        "bb": bb,
    }
