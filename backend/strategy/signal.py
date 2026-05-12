import pandas as pd


BUY = "BUY"
SELL = "SELL"
HOLD = "HOLD"

STRATEGY_BB_RSI = "bb_rsi"
STRATEGY_DONCHIAN = "donchian"
STRATEGY_VB = "vb"  # Larry Williams 변동성 돌파

VALID_STRATEGIES = (STRATEGY_BB_RSI, STRATEGY_DONCHIAN, STRATEGY_VB)


def generate_signals(
    df: pd.DataFrame,
    strategy: str = STRATEGY_BB_RSI,
    # bb_rsi 파라미터
    rsi_oversold: float = 30,
    rsi_overbought: float = 70,
    swing_mode: bool = False,
    # 신규 전략 파라미터
    **kwargs,
) -> pd.DataFrame:
    """
    전략 디스패처. strategy 값에 따라 해당 전략의 시그널 생성 함수를 호출한다.

    Args:
        strategy: "bb_rsi" (기본) | "donchian" | "vb"
        rsi_oversold, rsi_overbought, swing_mode: bb_rsi 전용
        kwargs: 신규 전략용 (donchian/vb 함수가 추가 키워드 사용)

    Returns:
        'signal' 컬럼이 추가된 DataFrame
    """
    if strategy == STRATEGY_BB_RSI:
        return _signals_bb_rsi(
            df,
            rsi_oversold=rsi_oversold,
            rsi_overbought=rsi_overbought,
            swing_mode=swing_mode,
        )
    if strategy == STRATEGY_DONCHIAN:
        return _signals_donchian(df)
    if strategy == STRATEGY_VB:
        return _signals_vb(df)
    raise ValueError(f"알 수 없는 전략: {strategy}. 가능: {VALID_STRATEGIES}")


def _signals_bb_rsi(
    df: pd.DataFrame,
    rsi_oversold: float = 30,
    rsi_overbought: float = 70,
    swing_mode: bool = False,
) -> pd.DataFrame:
    """
    RSI + 볼린저밴드 기반 시그널 생성 (기존 전략).

    [기본 모드] BUY 조건 (4가지 모두 충족):
      1. RSI < rsi_oversold (과매도)
      2. close < bb_lower (볼린저 하단 이탈)
      3. ma_short > ma_long (단기 > 장기 → 상승 추세)
      4. close > open (현재 봉 양봉 → 반등 시작 확인)

    [스윙/단타 모드] BUY 조건 (상승추세 조건 제거, 더 많은 신호):
      1. RSI < rsi_oversold
      2. close < bb_lower

    SELL 조건 (공통):
      - RSI > rsi_overbought OR close > bb_upper (둘 중 하나만 충족해도 매도)

    전제: df에 rsi, bb_upper, bb_lower, ma_short, ma_long, open 컬럼이 있어야 함.
    """
    required = ["rsi", "bb_upper", "bb_lower", "bb_middle", "ma_short", "ma_long", "open", "close"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"지표 컬럼 누락: {missing}. add_all_indicators()를 먼저 실행하세요.")

    if swing_mode:
        # 단타/스윙: 조건 간소화 → 거래 횟수 증가
        buy_condition = (
            (df["rsi"] < rsi_oversold)
            & (df["close"] < df["bb_lower"])
        )
        sell_condition = (
            (df["rsi"] > rsi_overbought)
            | (df["close"] > df["bb_upper"])
        )
    else:
        # 기본(보수적): 4조건 모두 충족
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


def _signals_donchian(df: pd.DataFrame) -> pd.DataFrame:
    """
    돈치안 채널 돌파 시그널 (터틀룰 표준).

      BUY  : close > dc_upper  (직전 20일 최고가 상향 돌파)
      SELL : close < dc_exit_lower  (직전 10일 최저가 하향 이탈)

    전제: df에 dc_upper, dc_exit_lower 컬럼이 있어야 함 (add_donchian()).
    """
    required = ["dc_upper", "dc_exit_lower", "close"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"지표 컬럼 누락: {missing}. add_donchian()을 먼저 실행하세요.")

    buy_condition = df["close"] > df["dc_upper"]
    sell_condition = df["close"] < df["dc_exit_lower"]

    df["signal"] = HOLD
    df.loc[buy_condition, "signal"] = BUY
    df.loc[sell_condition, "signal"] = SELL

    return df


def _signals_vb(df: pd.DataFrame) -> pd.DataFrame:
    """
    Larry Williams 변동성 돌파 시그널.

      BUY  : high >= vb_target  (당일 중 돌파선 터치)
      SELL : 익일 시가 청산 — 시그널 자체로는 BUY만 표시. 청산은 백테스트 루프가 처리.

    전제: df에 vb_target 컬럼이 있어야 함 (add_volatility_breakout()).

    주의: 청산은 "BUY 봉의 다음 봉 시가"이며 SELL 시그널로는 표현되지 않는다.
    backtest.py의 vb 분기 루프가 이 규칙을 처리한다.
    """
    required = ["vb_target", "high"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"지표 컬럼 누락: {missing}. add_volatility_breakout()을 먼저 실행하세요.")

    buy_condition = df["high"] >= df["vb_target"]

    df["signal"] = HOLD
    df.loc[buy_condition, "signal"] = BUY
    return df
