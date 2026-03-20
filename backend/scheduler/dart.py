"""
DART 전자공시 API로 한국 종목의 최근 실적 공시 조회.

API 키 발급: https://opendart.fss.or.kr/ (무료 회원가입)
.env에 DART_API_KEY=발급받은키 추가

조회 범위: 오늘 기준 최근 RECENT_DAYS 이내 공시
대상 공시: 사업보고서 / 분기보고서 / 반기보고서 (정기공시)
DART_API_KEY 없으면 silent no-op.
"""

import os
from datetime import date, timedelta
from functools import lru_cache

import requests

_DART_URL   = "https://opendart.fss.or.kr/api/list.json"
_TIMEOUT    = 5
_RECENT_DAYS = 7   # 최근 N일 이내 공시 확인

# 실적 관련 공시 키워드
_EARNINGS_KEYWORDS = ("사업보고서", "분기보고서", "반기보고서")


# ──────────────────────────────────────────
# 공시 조회
# ──────────────────────────────────────────

@lru_cache(maxsize=256)
def get_earnings_warning_kr(ticker: str) -> dict:
    """
    DART API로 최근 실적 공시 여부 확인.

    Returns:
        {
            "warning": bool
            "report":  str | None   공시 제목 (분기보고서 등)
            "date":    str | None   "MM/DD"
            "label":   str | None   텔레그램/터미널 표시용
        }
    """
    api_key = os.getenv("DART_API_KEY")
    if not api_key:
        return _no_warning()

    code  = ticker.split(".")[0].zfill(6)
    today = date.today()
    start = (today - timedelta(days=_RECENT_DAYS)).strftime("%Y%m%d")
    end   = today.strftime("%Y%m%d")

    try:
        r = requests.get(
            _DART_URL,
            params={
                "crtfc_key":  api_key,
                "stock_code": code,
                "bgn_de":     start,
                "end_de":     end,
                "pblntf_ty":  "A",   # 정기공시
            },
            timeout=_TIMEOUT,
        )
        if not r.ok:
            return _no_warning()

        data = r.json()
        if data.get("status") != "000":
            return _no_warning()

        disclosures = data.get("list", [])
        earnings = [
            d for d in disclosures
            if any(kw in d.get("report_nm", "") for kw in _EARNINGS_KEYWORDS)
        ]

        if not earnings:
            return _no_warning()

        latest    = earnings[0]
        report_nm = latest["report_nm"]
        rcept_dt  = latest["rcept_dt"]          # "YYYYMMDD"
        date_fmt  = f"{rcept_dt[4:6]}/{rcept_dt[6:]}"

        return {
            "warning": True,
            "report":  report_nm,
            "date":    date_fmt,
            "label":   f"📋 최근 공시: {report_nm} ({date_fmt})",
        }

    except Exception:
        return _no_warning()


def _no_warning() -> dict:
    return {"warning": False, "report": None, "date": None, "label": None}
