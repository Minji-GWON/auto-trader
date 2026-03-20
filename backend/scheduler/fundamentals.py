"""
네이버 증권 API를 통해 종목의 PER/PBR/EPS 조회 및 재무 위험도 판단.

외부 의존성 없음 (requests는 이미 requirements.txt에 포함).
"""

import re
import time
from functools import lru_cache

import requests

_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
_TIMEOUT = 5


# ──────────────────────────────────────────
# 데이터 조회
# ──────────────────────────────────────────

@lru_cache(maxsize=256)
def get_fundamental(ticker: str) -> dict:
    """
    네이버 증권 API로 PER/PBR/EPS 조회.
    결과는 프로세스 내 캐시 (종목당 1회만 호출).

    Returns:
        {
            "per":    float | None   (N/A or 적자이면 None)
            "pbr":    float | None
            "eps":    int   | None
            "per_raw": str           (원본 문자열, "30.38배")
            "pbr_raw": str
            "eps_raw": str
        }
    """
    code = ticker.split(".")[0].zfill(6)
    try:
        url = f"https://m.stock.naver.com/api/stock/{code}/integration"
        r = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        if not r.ok:
            return _empty()

        raw = {}
        for item in r.json().get("totalInfos", []):
            c = item.get("code", "")
            if c in ("per", "pbr", "eps"):
                raw[c] = item.get("value", "N/A")

        def _parse(s: str) -> float | None:
            if not s or s in ("N/A", "-"):
                return None
            cleaned = re.sub(r"[배원,조억\s]", "", s)
            try:
                return float(cleaned)
            except ValueError:
                return None

        return {
            "per":     _parse(raw.get("per", "N/A")),
            "pbr":     _parse(raw.get("pbr", "N/A")),
            "eps":     _parse(raw.get("eps", "N/A")),
            "per_raw": raw.get("per", "N/A"),
            "pbr_raw": raw.get("pbr", "N/A"),
            "eps_raw": raw.get("eps", "N/A"),
        }
    except Exception:
        return _empty()


def _empty() -> dict:
    return {"per": None, "pbr": None, "eps": None,
            "per_raw": "N/A", "pbr_raw": "N/A", "eps_raw": "N/A"}


# ──────────────────────────────────────────
# 위험도 판정
# ──────────────────────────────────────────

def grade_fundamental(f: dict) -> tuple[str, str, str]:
    """
    PER/PBR 기반 위험도 등급 반환.

    Returns:
        (grade, icon, description)
        grade: "위험" | "주의" | "양호" | "저평가" | "알 수 없음"
    """
    per = f.get("per")
    pbr = f.get("pbr")
    eps = f.get("eps")

    warnings = []

    # EPS 음수 = 적자
    if eps is not None and eps < 0:
        warnings.append("적자기업")

    # PER 판단
    if per is None:
        if eps is not None and eps < 0:
            pass  # 이미 적자로 표시
        else:
            warnings.append("PER 산출불가")
    elif per > 200:
        warnings.append(f"PER 과열 ({per:,.0f}배)")
    elif per > 50:
        warnings.append(f"PER 고평가 ({per:.0f}배)")

    # PBR 판단
    if pbr is None:
        pass
    elif pbr < 0:
        warnings.append("자본잠식")
    elif pbr > 10:
        warnings.append(f"PBR 과열 ({pbr:.1f}배)")
    elif pbr > 5:
        warnings.append(f"PBR 고평가 ({pbr:.1f}배)")

    if not warnings:
        # 저평가 기준
        if per is not None and pbr is not None and per < 15 and pbr < 1:
            grade, icon = "저평가", "🟢"
        else:
            grade, icon = "양호", "✅"
        desc = f"PER {f['per_raw']} / PBR {f['pbr_raw']}"
    elif any(w in ("적자기업", "자본잠식") for w in warnings):
        grade, icon = "위험", "🔴"
        desc = " / ".join(warnings) + f"  (PBR {f['pbr_raw']})"
    else:
        grade, icon = "주의", "⚠️"
        desc = " / ".join(warnings)

    return grade, icon, desc
