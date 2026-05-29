import pandas as pd
import numpy as np


def add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """RSI 계산 후 'rsi' 컬럼 추가."""
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()

    rs = avg_gain / avg_loss
    df["rsi"] = 100 - (100 / (1 + rs))
    return df


def add_bollinger_bands(
    df: pd.DataFrame, period: int = 20, std_dev: float = 2.0
) -> pd.DataFrame:
    """볼린저 밴드 계산 후 bb_upper, bb_middle, bb_lower 컬럼 추가."""
    df["bb_middle"] = df["close"].rolling(window=period).mean()
    rolling_std = df["close"].rolling(window=period).std()
    df["bb_upper"] = df["bb_middle"] + std_dev * rolling_std
    df["bb_lower"] = df["bb_middle"] - std_dev * rolling_std
    return df


def add_moving_averages(
    df: pd.DataFrame, short: int = 20, long: int = 60
) -> pd.DataFrame:
    """단기/장기 이동평균 계산 후 ma_short, ma_long 컬럼 추가 (추세 필터용)."""
    df["ma_short"] = df["close"].rolling(window=short).mean()
    df["ma_long"] = df["close"].rolling(window=long).mean()
    return df


def add_volatility_breakout(df: pd.DataFrame, k: float = 0.5) -> pd.DataFrame:
    """
    Larry Williams 변동성 돌파 계산 후 vb_range, vb_target 컬럼 추가.

      vb_range  = 전일 high - 전일 low
      vb_target = 당일 open + k * vb_range  (당일 중 이 값 돌파 시 매수)
    """
    prev_high = df["high"].shift(1)
    prev_low = df["low"].shift(1)
    df["vb_range"] = prev_high - prev_low
    df["vb_target"] = df["open"] + k * df["vb_range"]
    return df


def add_all_indicators(
    df: pd.DataFrame,
    rsi_period: int = 14,
    bb_period: int = 20,
    bb_std_dev: float = 2.0,
    ma_short: int = 20,
    ma_long: int = 60,
) -> pd.DataFrame:
    """기본(BB+RSI) 전략용 보조지표 한번에 추가."""
    df = add_rsi(df, period=rsi_period)
    df = add_bollinger_bands(df, period=bb_period, std_dev=bb_std_dev)
    df = add_moving_averages(df, short=ma_short, long=ma_long)
    return df
