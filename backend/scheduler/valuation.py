"""
기업 가치 평가 + 기술적 과매도 종합 점수.

국장 가치 점수 (0~60):  PER / PBR / EPS
미장 가치 점수 (0~100): PER / PBR / ROE / EPS성장률 / 부채비율

과매도 점수 (0~50): RSI + 볼린저밴드 위치

최종 점수 = 가치점수(50점 환산) + 과매도점수 (0~100)
→ 높을수록 "실적 대비 저평가된 과매도 우량주"

등급:
  75+: 🔥 강력매수 — 저평가 + 심한 과매도
  60+: ✅ 매수유망 — 가치 양호 + 과매도
  45+: 👀 관심종목 — 한 가지 조건 충족
   ~: —  보통
"""

from functools import lru_cache

import yfinance as yf

from backend.scheduler.fundamentals import get_fundamental
from backend.scheduler.fundamentals_us import get_fundamental_us


# ──────────────────────────────────────────
# 국장 가치 점수
# ──────────────────────────────────────────

def score_value_kr(ticker: str) -> dict:
    """PER / PBR / EPS 기반 가치 점수 (0~60)."""
    f   = get_fundamental(ticker)
    per = f.get("per")
    pbr = f.get("pbr")
    eps = f.get("eps")

    # PER (0~25)
    if per is None:        per_s = 8
    elif per <= 0:         per_s = 0   # 적자
    elif per <= 10:        per_s = 25
    elif per <= 15:        per_s = 20
    elif per <= 25:        per_s = 12
    elif per <= 40:        per_s = 6
    else:                  per_s = 2

    # PBR (0~25)
    if pbr is None:        pbr_s = 8
    elif pbr <= 0:         pbr_s = 0   # 자본잠식
    elif pbr <= 0.5:       pbr_s = 25
    elif pbr <= 1.0:       pbr_s = 20
    elif pbr <= 2.0:       pbr_s = 12
    elif pbr <= 4.0:       pbr_s = 6
    else:                  pbr_s = 2

    # EPS (0~10)
    if eps is None:        eps_s = 5
    elif eps > 0:          eps_s = 10
    else:                  eps_s = 0

    total = per_s + pbr_s + eps_s  # 0~60
    return {
        "score": total, "max": 60,
        "breakdown": {"PER": per_s, "PBR": pbr_s, "EPS흑자": eps_s},
        "per": per, "pbr": pbr,
        "per_raw": f.get("per_raw", "N/A"),
        "pbr_raw": f.get("pbr_raw", "N/A"),
        "roe": None, "eps_growth": None, "de_ratio": None,
    }


# ──────────────────────────────────────────
# 미장 가치 점수
# ──────────────────────────────────────────

@lru_cache(maxsize=256)
def _yf_info(ticker: str) -> dict:
    try:
        return yf.Ticker(ticker).info or {}
    except Exception:
        return {}


def score_value_us(ticker: str) -> dict:
    """PER / PBR / ROE / EPS성장 / 부채비율 기반 가치 점수 (0~100)."""
    info = _yf_info(ticker)
    f    = get_fundamental_us(ticker)

    per         = f.get("per")
    pbr         = f.get("pbr")
    forward_pe  = info.get("forwardPE")
    roe         = info.get("returnOnEquity")       # 소수 (0.25 = 25%)
    eps_growth  = info.get("earningsGrowth")       # 소수
    rev_growth  = info.get("revenueGrowth")
    de_ratio    = info.get("debtToEquity")         # 숫자 (100 이상 = 높음)

    use_pe = forward_pe if (forward_pe and forward_pe > 0) else per

    # PER (0~25)
    if use_pe is None or use_pe <= 0: per_s = 8
    elif use_pe <= 12:  per_s = 25
    elif use_pe <= 18:  per_s = 20
    elif use_pe <= 25:  per_s = 13
    elif use_pe <= 40:  per_s = 6
    else:               per_s = 2

    # PBR (0~20)
    if pbr is None:     pbr_s = 7
    elif pbr <= 0:      pbr_s = 0
    elif pbr <= 1.5:    pbr_s = 20
    elif pbr <= 3.0:    pbr_s = 13
    elif pbr <= 6.0:    pbr_s = 6
    else:               pbr_s = 2

    # ROE (0~25)
    if roe is None:     roe_s = 8
    elif roe <= 0:      roe_s = 0
    elif roe >= 0.30:   roe_s = 25
    elif roe >= 0.20:   roe_s = 20
    elif roe >= 0.10:   roe_s = 13
    elif roe >= 0.05:   roe_s = 6
    else:               roe_s = 2

    # EPS/매출 성장 (0~20)
    g = eps_growth if eps_growth is not None else rev_growth
    if g is None:       grow_s = 7
    elif g >= 0.30:     grow_s = 20
    elif g >= 0.15:     grow_s = 15
    elif g >= 0.05:     grow_s = 10
    elif g >= 0:        grow_s = 5
    else:               grow_s = 0

    # 부채비율 (0~10)
    if de_ratio is None:    de_s = 4
    elif de_ratio <= 30:    de_s = 10
    elif de_ratio <= 80:    de_s = 7
    elif de_ratio <= 150:   de_s = 4
    else:                   de_s = 0

    total = per_s + pbr_s + roe_s + grow_s + de_s  # 0~100
    return {
        "score": total, "max": 100,
        "breakdown": {
            "PER": per_s, "PBR": pbr_s,
            "ROE": roe_s, "성장률": grow_s, "부채비율": de_s,
        },
        "per": round(use_pe, 1) if use_pe else None,
        "pbr": round(pbr, 2) if pbr else None,
        "per_raw": f"{use_pe:.1f}배" if use_pe else "N/A",
        "pbr_raw": f"{pbr:.2f}배" if pbr else "N/A",
        "roe":        round(roe * 100, 1) if roe else None,
        "eps_growth": round(eps_growth * 100, 1) if eps_growth else None,
        "de_ratio":   round(de_ratio, 1) if de_ratio else None,
    }


# ──────────────────────────────────────────
# 과매도 점수 (기술적)
# ──────────────────────────────────────────

def score_oversold(rsi: float, bb_position: str) -> dict:
    """RSI + BB 위치 기반 과매도 점수 (0~50)."""
    if rsi <= 20:       rsi_s = 30
    elif rsi <= 30:     rsi_s = 25
    elif rsi <= 40:     rsi_s = 18
    elif rsi <= 50:     rsi_s = 10
    else:               rsi_s = 3

    bb_s = {"하단 이탈": 20, "중간 아래": 10, "중간 위": 4, "상단 돌파": 0}.get(bb_position, 5)

    return {"score": rsi_s + bb_s, "max": 50, "rsi_score": rsi_s, "bb_score": bb_s}


# ──────────────────────────────────────────
# 종합 점수
# ──────────────────────────────────────────

def value_opportunity_score(fundamental: dict, oversold: dict) -> dict:
    """
    가치 점수(50점 환산) + 과매도 점수(50점) = 100점 만점.
    높을수록 '실적 대비 저평가된 과매도 우량주'.
    """
    f_norm   = round(fundamental["score"] / fundamental["max"] * 50)
    combined = f_norm + oversold["score"]  # 0~100

    if combined >= 75:   grade, icon = "강력매수", "🔥"
    elif combined >= 60: grade, icon = "매수유망", "✅"
    elif combined >= 45: grade, icon = "관심종목", "👀"
    else:                grade, icon = "보통",     "—"

    return {
        "score":       combined,
        "grade":       grade,
        "icon":        icon,
        "f_score":     fundamental["score"],
        "f_max":       fundamental["max"],
        "o_score":     oversold["score"],
        "breakdown":   fundamental.get("breakdown", {}),
    }
