"""
yfinance로 미국 종목의 다음 실적 발표일 조회.
WARNING_DAYS 이내면 경고 반환.
"""

from datetime import date
from functools import lru_cache

import pandas as pd
import yfinance as yf

WARNING_DAYS = 14  # 이내 실적 발표 → 경고


@lru_cache(maxsize=256)
def get_earnings_warning_us(ticker: str) -> dict:
    """
    다음 실적 발표일이 WARNING_DAYS 이내인지 확인.

    Returns:
        {
            "warning": bool
            "days":    int | None
            "date":    str | None   "MM/DD"
            "label":   str | None   텔레그램/터미널 표시용
        }
    """
    try:
        df = yf.Ticker(ticker).earnings_dates
        if df is None or df.empty:
            return _no_warning()

        today = pd.Timestamp.now(tz="UTC").normalize()
        future = df[df.index >= today].sort_index()   # 오름차순 → 가장 가까운 날 first

        if future.empty:
            return _no_warning()

        next_dt = future.index[0]
        days = (next_dt.date() - date.today()).days

        if days < 0 or days > WARNING_DAYS:
            return _no_warning()

        date_str = next_dt.strftime("%m/%d")
        if days == 0:
            label = "📅 오늘 실적 발표!"
        elif days == 1:
            label = f"📅 내일 실적 발표 ({date_str})"
        else:
            label = f"📅 실적 {days}일 후 ({date_str})"

        return {"warning": True, "days": days, "date": date_str, "label": label}
    except Exception:
        return _no_warning()


def _no_warning() -> dict:
    return {"warning": False, "days": None, "date": None, "label": None}
