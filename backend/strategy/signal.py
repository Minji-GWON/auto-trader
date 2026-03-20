import pandas as pd


BUY = "BUY"
SELL = "SELL"
HOLD = "HOLD"


def generate_signals(
    df: pd.DataFrame,
    rsi_oversold: float = 30,
    rsi_overbought: float = 70,
) -> pd.DataFrame:
    """
    RSI + 볼린저밴드 + 추세 필터 기반 시그널 생성.

    BUY 조건 (4가지 모두 충족):
      1. RSI < rsi_oversold (과매도)
      2. close < bb_lower (볼린저 하단 이탈)
      3. ma_short > ma_long (단기 > 장기 → 상승 추세)
      4. close > open (현재 봉 양봉 → 반등 시작 확인)

    SELL 조건:
      - RSI > rsi_overbought AND close > bb_upper

    전제: df에 rsi, bb_upper, bb_lower, ma_short, ma_long, open 컬럼이 있어야 함.
    """
    required = ["rsi", "bb_upper", "bb_lower", "bb_middle", "ma_short", "ma_long", "open", "close"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"지표 컬럼 누락: {missing}. add_all_indicators()를 먼저 실행하세요.")

    buy_condition = (
        (df["rsi"] < rsi_oversold)
        & (df["close"] < df["bb_lower"])
        & (df["ma_short"] > df["ma_long"])
        & (df["close"] > df["open"])
    )

    sell_condition = (
        (df["rsi"] > rsi_overbought)
        & (df["close"] > df["bb_upper"])
    )

    df["signal"] = HOLD
    df.loc[buy_condition, "signal"] = BUY
    df.loc[sell_condition, "signal"] = SELL

    return df
