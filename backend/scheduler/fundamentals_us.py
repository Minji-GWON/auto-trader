"""
yfinance를 통해 미국 종목의 P/E(PER) / P/B(PBR) / EPS 조회.
한국 주식 fundamentals.py와 동일한 반환 형식 → grade_fundamental() 재사용 가능.
"""

from functools import lru_cache

import yfinance as yf


# ──────────────────────────────────────────
# 데이터 조회
# ──────────────────────────────────────────

@lru_cache(maxsize=256)
def get_fundamental_us(ticker: str) -> dict:
    """
    yfinance .info에서 P/E / P/B / EPS 조회.
    결과는 프로세스 내 캐시 (종목당 1회만 호출).

    Returns: fundamentals.py의 get_fundamental()과 동일한 형식.
    """
    try:
        info = yf.Ticker(ticker).info

        per = info.get("trailingPE")
        pbr = info.get("priceToBook")
        eps = info.get("trailingEps")

        def _fmt(v, suffix="") -> str:
            if v is None:
                return "N/A"
            return f"{v:.2f}{suffix}"

        return {
            "per":     float(per) if per is not None else None,
            "pbr":     float(pbr) if pbr is not None else None,
            "eps":     float(eps) if eps is not None else None,
            "per_raw": _fmt(per, "배"),
            "pbr_raw": _fmt(pbr, "배"),
            "eps_raw": _fmt(eps),
        }
    except Exception:
        return _empty()


def _empty() -> dict:
    return {"per": None, "pbr": None, "eps": None,
            "per_raw": "N/A", "pbr_raw": "N/A", "eps_raw": "N/A"}
