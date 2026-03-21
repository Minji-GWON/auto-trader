"""
장중 15분봉 매수/매도 신호 알림.

- yfinance 15분봉 데이터 (최근 5일)
- RSI + 볼린저밴드 신호
- 동일 방향 신호 60분 내 중복 발송 방지
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

from backend.indicators.calculator import add_all_indicators
from backend.strategy.signal import generate_signals, BUY, SELL

SEEN_FILE = Path(".intraday_signal_seen.json")
_COOLDOWN_MINUTES = 60


# ── 데이터 수집 ────────────────────────────────────────────

def fetch_15min(ticker: str) -> pd.DataFrame:
    """15분봉 OHLCV 조회 (최근 5거래일)."""
    try:
        raw = yf.download(ticker, period="5d", interval="15m",
                          progress=False, auto_adjust=True)
        if raw is None or raw.empty:
            return pd.DataFrame()

        # 단일 티커: columns 단순 / 복수: MultiIndex
        if isinstance(raw.columns, pd.MultiIndex):
            raw = raw.xs(ticker, axis=1, level=1)

        df = raw.copy()
        df.columns = [c.lower() for c in df.columns]
        df = df.rename(columns={"adj close": "close"})
        df = df[["open", "high", "low", "close", "volume"]].dropna()
        return df
    except Exception:
        return pd.DataFrame()


# ── 중복 방지 ──────────────────────────────────────────────

def _load_seen() -> dict:
    if SEEN_FILE.exists():
        try:
            return json.loads(SEEN_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_seen(seen: dict):
    SEEN_FILE.write_text(json.dumps(seen))


def _is_duplicate(ticker: str, signal: str) -> bool:
    """같은 방향 신호가 cooldown 내에 이미 발송됐으면 True."""
    seen = _load_seen()
    key = f"{ticker}_{signal}"
    last_str = seen.get(key)
    if not last_str:
        return False
    last = datetime.fromisoformat(last_str)
    return (datetime.now(timezone.utc) - last) < timedelta(minutes=_COOLDOWN_MINUTES)


def _mark_seen(ticker: str, signal: str):
    seen = _load_seen()
    seen[f"{ticker}_{signal}"] = datetime.now(timezone.utc).isoformat()
    _save_seen(seen)


# ── 신호 체크 ──────────────────────────────────────────────

def check_intraday_signal(
    ticker: str,
    rsi_oversold: float = 35,
    rsi_overbought: float = 65,
    rsi_period: int = 14,
    bb_period: int = 20,
    bb_std_dev: float = 2.0,
    ma_short: int = 10,
    ma_long: int = 20,
) -> dict | None:
    """
    15분봉 기준 매수/매도 신호 확인.

    Returns:
        {"signal": "BUY"|"SELL", "price": float, "rsi": float,
         "bb_position": str, "candle_time": str}
        또는 None (신호 없음 / 오류)
    """
    df = fetch_15min(ticker)
    if df.empty or len(df) < max(rsi_period, bb_period, ma_long) + 5:
        return None

    df = add_all_indicators(
        df,
        rsi_period=rsi_period,
        bb_period=bb_period,
        bb_std_dev=bb_std_dev,
        ma_short=ma_short,
        ma_long=ma_long,
    )
    df = generate_signals(
        df,
        rsi_oversold=rsi_oversold,
        rsi_overbought=rsi_overbought,
        swing_mode=True,
    )
    df = df.dropna()
    if df.empty:
        return None

    last = df.iloc[-1]
    signal = last["signal"]
    if signal == "HOLD":
        return None

    close = float(last["close"])
    upper = float(last["bb_upper"])
    lower = float(last["bb_lower"])
    mid   = float(last["bb_middle"])

    if close <= lower:      bb_pos = "하단 이탈"
    elif close >= upper:    bb_pos = "상단 돌파"
    elif close < mid:       bb_pos = "중간 아래"
    else:                   bb_pos = "중간 위"

    candle_time = df.index[-1]
    if hasattr(candle_time, "strftime"):
        candle_time = candle_time.strftime("%H:%M")
    else:
        candle_time = str(candle_time)

    return {
        "signal":      signal,
        "price":       round(close, 2),
        "rsi":         round(float(last["rsi"]), 1),
        "bb_position": bb_pos,
        "candle_time": candle_time,
    }


# ── 메시지 빌드 ────────────────────────────────────────────

def build_alert(ticker: str, result: dict) -> str:
    signal  = result["signal"]
    price   = result["price"]
    rsi     = result["rsi"]
    bb_pos  = result["bb_position"]
    t       = result["candle_time"]

    if signal == BUY:
        icon  = "🟢"
        label = "매수 신호"
        tip   = "RSI 과매도 + 볼린저 하단 — 반등 구간"
    else:
        icon  = "🔴"
        label = "매도 신호"
        tip   = "RSI 과매수 + 볼린저 상단 — 조정 구간"

    return (
        f"{icon} <b>{ticker} {label}</b>  <code>{t} (EST)</code>\n"
        f"현재가: <b>${price:,.2f}</b>  RSI: {rsi}  BB: {bb_pos}\n"
        f"<i>{tip}</i>"
    )


# ── 텔레그램 전송 ──────────────────────────────────────────

def _send(token: str, chat_id: str, text: str):
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
        timeout=10,
    )


# ── 메인 ──────────────────────────────────────────────────

def run(
    tickers: list[str],
    token: str,
    chat_id: str,
    dry_run: bool = False,
):
    for ticker in tickers:
        result = check_intraday_signal(ticker)
        if result is None:
            print(f"[{ticker}] 신호 없음")
            continue

        signal = result["signal"]
        if _is_duplicate(ticker, signal):
            print(f"[{ticker}] {signal} — 중복 (60분 내 발송됨), 스킵")
            continue

        msg = build_alert(ticker, result)
        print(f"[{ticker}] {signal} 신호 발송:\n{msg}\n")

        if not dry_run:
            _send(token, chat_id, msg)
            _mark_seen(ticker, signal)
