"""
Larry Williams 변동성 돌파 — 장중 감시.

룰:
  vb_target = 오늘 시가(일봉) + K * 전일 변동폭(전일 high - 전일 low)
  당일 중 vb_target 가격을 상향 돌파(고가 ≥ target)하면 감지한다.

기존 intraday_signal.py (RSI+BB 15분봉)와 독립적으로 동작한다.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf


# RSI+BB SEEN_FILE과 분리 (같은 날 두 번 출력되지 않도록 cooldown)
VB_SEEN_FILE = Path(".vb_intraday_seen.json")
_VB_COOLDOWN_HOURS = 20  # 1거래일 안에는 같은 종목 중복 처리 금지


def _fetch_daily(ticker: str) -> pd.DataFrame:
    """최근 5일 일봉 OHLCV (오늘 봉 포함). 오늘 봉은 진행 중이라 open만 유효, high는 가변."""
    try:
        raw = yf.download(ticker, period="5d", interval="1d",
                          progress=False, auto_adjust=True)
        if raw is None or raw.empty:
            return pd.DataFrame()
        if isinstance(raw.columns, pd.MultiIndex):
            raw = raw.xs(ticker, axis=1, level=1)
        df = raw.copy()
        df.columns = [c.lower() for c in df.columns]
        df = df.rename(columns={"adj close": "close"})
        return df[["open", "high", "low", "close", "volume"]].dropna()
    except Exception:
        return pd.DataFrame()


def check_vb_breakout(ticker: str, k: float = 0.5) -> dict | None:
    """
    오늘 변동성 돌파 발생 여부 확인.

    Returns:
        {"ticker": ticker, "vb_target": float, "today_high": float,
         "today_open": float, "prev_range": float, "k": float}
        또는 None (데이터 부족 / 아직 돌파 안 함).
    """
    df = _fetch_daily(ticker)
    if df.empty or len(df) < 2:
        return None

    today = df.iloc[-1]
    prev = df.iloc[-2]

    today_open = float(today["open"])
    today_high = float(today["high"])
    prev_range = float(prev["high"] - prev["low"])
    if prev_range <= 0:
        return None

    vb_target = today_open + k * prev_range
    if today_high < vb_target:
        return None  # 아직 돌파 안 함

    return {
        "ticker":     ticker,
        "vb_target":  round(vb_target, 2),
        "today_high": round(today_high, 2),
        "today_open": round(today_open, 2),
        "prev_range": round(prev_range, 2),
        "k":          k,
    }


def _load_seen(seen_file: Path) -> dict:
    if seen_file.exists():
        try:
            return json.loads(seen_file.read_text())
        except Exception:
            pass
    return {}


def _save_seen(seen_file: Path, seen: dict) -> None:
    seen_file.write_text(json.dumps(seen))


def _is_duplicate(ticker: str, seen_file: Path) -> bool:
    seen = _load_seen(seen_file)
    last_str = seen.get(ticker)
    if not last_str:
        return False
    last = datetime.fromisoformat(last_str)
    return (datetime.now(timezone.utc) - last) < timedelta(hours=_VB_COOLDOWN_HOURS)


def _mark_seen(ticker: str, seen_file: Path) -> None:
    seen = _load_seen(seen_file)
    seen[ticker] = datetime.now(timezone.utc).isoformat()
    _save_seen(seen_file, seen)


def run_vb(
    tickers: list[str],
    k: float = 0.5,
    seen_file: Path = VB_SEEN_FILE,
    display_names: dict[str, str] | None = None,
) -> None:
    names = display_names or {}
    for ticker in tickers:
        result = check_vb_breakout(ticker, k=k)
        if result is None:
            print(f"[{ticker}] VB: 돌파 없음 또는 데이터 부족")
            continue

        if _is_duplicate(ticker, seen_file):
            print(f"[{ticker}] VB: 오늘 이미 감지됨, 스킵")
            continue

        name = names.get(ticker, "") or ticker
        print(
            f"[{ticker}] VB 돌파 감지: {name} "
            f"target=${result['vb_target']:,.2f}, "
            f"high=${result['today_high']:,.2f}, "
            f"open=${result['today_open']:,.2f}, "
            f"prev_range=${result['prev_range']:,.2f}, "
            f"k={result['k']}"
        )
        _mark_seen(ticker, seen_file)
