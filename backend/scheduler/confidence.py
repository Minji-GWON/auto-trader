"""
매수/매도 신호의 신뢰도를 0~100점으로 계산.

구성 요소 (각 25점, 합계 100점):
  1. RSI 강도   — 과매도/과매수 얼마나 깊이 진입했는지
  2. 거래량     — 오늘 거래량이 평균 대비 얼마나 많은지
  3. 시장 흐름  — 코스피 전체 방향
  4. 재무 건전성 — PER/PBR 기반 위험도

등급:
  75~100: 🔥 강함   (적극 고려)
  50~74 : ✅ 보통   (신중히 고려)
  25~49 : ⚠️ 약함   (관망 권고)
   0~24 : ❌ 매우약함 (신호 무시 권고)
"""

from backend.strategy.signal import BUY


# ──────────────────────────────────────────
# 점수 계산
# ──────────────────────────────────────────

def calc_confidence(
    signal: str,
    rsi: float,
    rsi_oversold: float,
    rsi_overbought: float,
    vol_grade: str,
    market_status: str,
    f_grade: str,
) -> dict:
    """
    신호 신뢰도 점수를 계산해 반환.

    Returns:
        {
            "score":       int (0~100)
            "grade":       str ("강함" | "보통" | "약함" | "매우약함")
            "icon":        str ("🔥" | "✅" | "⚠️" | "❌")
            "breakdown":   dict  각 항목별 점수
        }
    """
    is_buy = (signal == BUY)

    # 1. RSI 강도 (25점)
    rsi_score = _rsi_score(rsi, rsi_oversold, rsi_overbought, is_buy)

    # 2. 거래량 (25점)
    vol_score = {"강함": 25, "보통": 16, "약함": 5, "미확인": 10}.get(vol_grade, 10)

    # 3. 시장 흐름 (25점)
    if is_buy:
        market_score = {"강세": 25, "중립": 18, "약세": 6, "급락": 0, "알 수 없음": 12}.get(market_status, 12)
    else:
        # 매도 신호는 시장 약세일수록 신뢰도 높음
        market_score = {"강세": 6, "중립": 18, "약세": 25, "급락": 25, "알 수 없음": 12}.get(market_status, 12)

    # 4. 재무 건전성 (25점)
    fund_score = {"저평가": 25, "양호": 20, "주의": 10, "위험": 0, "알 수 없음": 12}.get(f_grade, 12)

    total = rsi_score + vol_score + market_score + fund_score

    if total >= 75:
        grade, icon = "강함", "🔥"
    elif total >= 50:
        grade, icon = "보통", "✅"
    elif total >= 25:
        grade, icon = "약함", "⚠️"
    else:
        grade, icon = "매우약함", "❌"

    return {
        "score": total,
        "grade": grade,
        "icon":  icon,
        "breakdown": {
            "RSI 강도":  rsi_score,
            "거래량":    vol_score,
            "시장 흐름": market_score,
            "재무":      fund_score,
        },
    }


def _rsi_score(rsi: float, oversold: float, overbought: float, is_buy: bool) -> int:
    """RSI가 기준선에서 얼마나 벗어났는지에 따라 0~25점."""
    if is_buy:
        # 과매도: 기준(oversold)보다 낮을수록 점수 높음
        gap = oversold - rsi          # 양수일수록 깊이 과매도
        if gap >= 15:  return 25
        if gap >= 10:  return 20
        if gap >= 5:   return 15
        if gap >= 0:   return 10
        return 5                       # 기준 근처 (신호는 발생했으나 약함)
    else:
        # 과매수: 기준(overbought)보다 높을수록 점수 높음
        gap = rsi - overbought
        if gap >= 15:  return 25
        if gap >= 10:  return 20
        if gap >= 5:   return 15
        if gap >= 0:   return 10
        return 5


# ──────────────────────────────────────────
# 등급 유틸
# ──────────────────────────────────────────

def score_bar(score: int, width: int = 10) -> str:
    """점수를 시각적 바로 표현. 예: '████░░░░░░ 40점'"""
    filled = round(score / 100 * width)
    return "█" * filled + "░" * (width - filled)
