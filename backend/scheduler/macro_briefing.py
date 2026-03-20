"""
매크로 시장 브리핑 모듈

데이터 소스:
- yfinance : VIX, TNX, DXY, Gold, WTI, S&P500 (API 키 불필요)
- CNN      : Fear & Greed Index (API 키 불필요)
- FRED API : MMF 잔고 (FRED_API_KEY 필요)
- NewsAPI  : 글로벌 비즈니스 헤드라인 (NEWS_API_KEY 필요)
"""

from __future__ import annotations

import re
from datetime import date
from typing import Optional

import requests
import yfinance as yf

_TIMEOUT = 8  # seconds

# ---------------------------------------------------------------------------
# MarkdownV2 헬퍼
# ---------------------------------------------------------------------------

def _escape_md(text) -> str:
    """MarkdownV2 특수문자 이스케이프 (telegram.py 패턴 동일)."""
    return re.sub(r'([_\*\[\]()~`>#+\-=|{}.!\\])', r'\\\1', str(text))


def _fmt_change(pct: Optional[float], unit: str = "%") -> str:
    """변화율을 부호 포함 문자열로 포맷. 음수는 unicode minus 사용."""
    if pct is None:
        return "N/A"
    sign = "+" if pct >= 0 else ""
    # unicode minus(−)는 MarkdownV2 특수문자가 아님 → 이스케이프 불필요
    val = f"{pct:+.2f}".replace("-", "−")
    return f"{val}{unit}"


def _vix_label(vix: Optional[float]) -> str:
    if vix is None:
        return ""
    if vix < 15:
        return "✅ 안정"
    if vix < 20:
        return "😐 보통"
    if vix < 30:
        return "⚠️ 불안"
    return "🚨 공포"


def _fg_emoji(score: Optional[float]) -> str:
    if score is None:
        return ""
    if score < 25:
        return "😱"
    if score < 46:
        return "😨"
    if score <= 55:
        return "😐"
    if score <= 75:
        return "😏"
    return "🤑"


def _fg_kr_label(score: Optional[float]) -> str:
    if score is None:
        return "데이터 없음"
    if score < 25:
        return "극단적 공포"
    if score < 46:
        return "공포"
    if score <= 55:
        return "중립"
    if score <= 75:
        return "탐욕"
    return "극단적 탐욕"


def _interpret_market(indicators: dict, fg: dict) -> list[str]:
    """시장 지표를 해석해 1~3개의 한국어 문장 반환."""
    bullets = []

    vix = (indicators.get("vix") or {}).get("value")
    spx_chg = (indicators.get("spx") or {}).get("change_pct")
    gold_chg = (indicators.get("gold") or {}).get("change_pct")
    dxy_chg = (indicators.get("dxy") or {}).get("change_pct")
    oil_chg = (indicators.get("oil") or {}).get("change_pct")
    tnx = (indicators.get("tnx") or {}).get("value")
    fg_score = fg.get("score")

    if vix is not None:
        if vix >= 30:
            bullets.append("🚨 VIX 30 초과 → 극단적 공포 구간, 현금 비중 확대 권장")
        elif vix >= 20:
            bullets.append("⚠️ VIX 20 초과 → 변동성 확대 구간, 신중한 매수 권장")
        elif vix < 15 and spx_chg is not None and spx_chg > 0:
            bullets.append("✅ VIX 저점 + 상승장 → 시장 안정, 추세 추종 유리")

    if gold_chg is not None and dxy_chg is not None:
        if gold_chg > 0.5 and dxy_chg > 0.3:
            bullets.append("🥇 금 상승 + 달러 강세 → 안전자산 선호 심리 강화")
        elif gold_chg > 0.5 and dxy_chg < -0.3:
            bullets.append("🥇 금 상승 + 달러 약세 → 인플레이션 헤지 수요 증가")

    if oil_chg is not None:
        if oil_chg > 2:
            bullets.append(f"🛢 WTI +{oil_chg:.1f}% → 에너지 비용 상승, 인플레이션 압력")
        elif oil_chg < -2:
            bullets.append(f"🛢 WTI {oil_chg:.1f}% → 수요 둔화 우려, 경기 침체 신호 가능")

    if tnx is not None and tnx >= 4.5:
        bullets.append(f"🇺🇸 미 국채 {tnx:.2f}% → 고금리 지속, 성장주 밸류에이션 압박")

    if fg_score is not None:
        if fg_score < 25:
            bullets.append("😱 극단적 공포 구간 → 역발상 매수 기회 점검 권장")
        elif fg_score > 75:
            bullets.append("🤑 극단적 탐욕 구간 → 과열 주의, 차익실현 고려")

    if not bullets:
        bullets.append("📊 특이 신호 없음 — 일반적인 시장 환경")

    return bullets[:3]


# ---------------------------------------------------------------------------
# 데이터 수집 함수
# ---------------------------------------------------------------------------

def get_market_indicators() -> dict:
    """
    yfinance로 주요 시장 지표 수집.

    반환:
        {
            "spx":  {"value": float, "change_pct": float} | {"value": None, "change_pct": None},
            "vix":  {...},
            "tnx":  {...},
            "dxy":  {...},
            "gold": {...},
            "oil":  {...},
            "error": str | None,
        }
    """
    tickers = ["^GSPC", "^VIX", "^TNX", "DX-Y.NYB", "GC=F", "CL=F"]
    key_map = {
        "^GSPC": "spx",
        "^VIX": "vix",
        "^TNX": "tnx",
        "DX-Y.NYB": "dxy",
        "GC=F": "gold",
        "CL=F": "oil",
    }
    result: dict = {v: {"value": None, "change_pct": None} for v in key_map.values()}
    result["error"] = None

    try:
        df = yf.download(tickers, period="5d", progress=False, auto_adjust=True)
        if df.empty or len(df) < 2:
            result["error"] = "yfinance 데이터 없음"
            return result

        close = df["Close"] if "Close" in df.columns else df.xs("Close", axis=1, level=0)

        for ticker, key in key_map.items():
            try:
                series = close[ticker].dropna()
                if len(series) < 2:
                    continue
                today_val = float(series.iloc[-1])
                prev_val = float(series.iloc[-2])
                chg = (today_val / prev_val - 1) * 100
                result[key] = {"value": today_val, "change_pct": chg}
            except Exception:
                pass

    except Exception as e:
        result["error"] = str(e)

    return result


def _vix_to_fg_score(vix: float) -> float:
    """VIX → Fear & Greed 유사 점수 (0~100) 역변환. VIX 높을수록 공포."""
    # VIX 10 → 90점(극단탐욕), VIX 45 → 5점(극단공포) 선형 매핑
    score = 90 - (vix - 10) * (85 / 35)
    return max(0.0, min(100.0, score))


def get_fear_greed(vix: Optional[float] = None) -> dict:
    """
    Fear & Greed Index 조회.
    1순위: CNN 비공식 엔드포인트
    2순위: VIX 기반 추정값 (CNN 실패 시)

    반환:
        {"score": float | None, "label": str | None, "source": str, "error": str | None}
    """
    url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Referer": "https://edition.cnn.com/markets/fear-and-greed",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        fg = data.get("fear_and_greed", {})
        score = fg.get("score")
        if score is not None:
            score = float(score)
            return {"score": score, "label": _fg_kr_label(score),
                    "source": "CNN", "error": None}
    except Exception:
        pass

    # CNN 실패 → VIX 기반 추정
    if vix is not None:
        score = _vix_to_fg_score(vix)
        return {"score": score, "label": _fg_kr_label(score),
                "source": "VIX 추정", "error": None}

    return {"score": None, "label": None, "source": "", "error": "데이터 없음"}


def get_mmf_data(fred_api_key: str) -> dict:
    """
    FRED API에서 Money Market Fund 잔고 조회 (series: WRMFSL, 단위: 십억달러).

    반환:
        {
            "value": float | None,
            "prev_value": float | None,
            "weekly_change": float | None,
            "date": str | None,
            "error": str | None,
        }
    """
    if not fred_api_key:
        return {"value": None, "prev_value": None, "weekly_change": None,
                "date": None, "error": "FRED_API_KEY 없음"}

    url = (
        "https://api.stlouisfed.org/fred/series/observations"
        f"?series_id=WRMFSL&api_key={fred_api_key}"
        "&sort_order=desc&limit=3&file_type=json"
    )
    try:
        resp = requests.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        obs = resp.json().get("observations", [])
        if not obs:
            return {"value": None, "prev_value": None, "weekly_change": None,
                    "date": None, "error": "FRED 데이터 없음"}

        # "." 값(미발표) 건너뜀
        valid = [o for o in obs if o.get("value", ".") != "."]
        if len(valid) < 1:
            return {"value": None, "prev_value": None, "weekly_change": None,
                    "date": None, "error": "유효한 FRED 데이터 없음"}

        cur = float(valid[0]["value"])
        prev = float(valid[1]["value"]) if len(valid) >= 2 else None
        chg = (cur - prev) if prev is not None else None
        return {
            "value": cur,
            "prev_value": prev,
            "weekly_change": chg,
            "date": valid[0].get("date"),
            "error": None,
        }
    except Exception as e:
        return {"value": None, "prev_value": None, "weekly_change": None,
                "date": None, "error": str(e)}


def get_top_news(news_api_key: str, n: int = 5) -> list[dict]:
    """
    NewsAPI에서 비즈니스 헤드라인 조회.

    반환:
        [{"title": str, "source": str}]
        오류 시: [{"title": "...", "source": "", "error": True}]
    """
    if not news_api_key:
        return [{"title": "NEWS_API_KEY 없음 — 뉴스 생략", "source": "", "error": True}]

    url = (
        "https://newsapi.org/v2/top-headlines"
        f"?category=business&language=en&pageSize={n}&apiKey={news_api_key}"
    )
    try:
        resp = requests.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        articles = resp.json().get("articles", [])
        result = []
        for a in articles[:n]:
            title = a.get("title", "")
            # "Title text - Source Name" 형태에서 소스명 제거
            if " - " in title:
                title = title.rsplit(" - ", 1)[0]
            source = (a.get("source") or {}).get("name", "")
            url = a.get("url", "")
            result.append({"title": title, "source": source, "url": url})
        return result if result else [{"title": "뉴스 없음", "source": "", "error": True}]
    except Exception as e:
        return [{"title": f"뉴스 조회 실패: {e}", "source": "", "error": True}]


# ---------------------------------------------------------------------------
# 메시지 빌드
# ---------------------------------------------------------------------------

def build_briefing_message(
    indicators: dict,
    mmf: dict,
    fg: dict,
    news: list[dict],
    today: Optional[date] = None,
    summaries: Optional[list[str]] = None,
) -> str:
    """
    모든 데이터를 MarkdownV2 형식의 텔레그램 메시지로 조립.
    """
    if today is None:
        today = date.today()

    lines: list[str] = []

    # ── 헤더 ──────────────────────────────────────────────
    date_str = _escape_md(today.strftime("%Y-%m-%d"))
    lines.append(f"🌍 *매크로 시장 브리핑* \\({date_str}\\)")
    lines.append("")

    # ── 주요 지표 ─────────────────────────────────────────
    lines.append("💵 *주요 지표*")

    spx = indicators.get("spx") or {}
    if spx.get("value") is not None:
        v = _escape_md(f"{spx['value']:,.0f}")
        c = _escape_md(_fmt_change(spx.get("change_pct")))
        lines.append(f"  📈 S&P 500: {v} \\({c}\\)")

    vix = indicators.get("vix") or {}
    if vix.get("value") is not None:
        v = _escape_md(f"{vix['value']:.1f}")
        label = _escape_md(_vix_label(vix["value"]))
        lines.append(f"  😱 VIX: {v}  {label}")

    tnx = indicators.get("tnx") or {}
    if tnx.get("value") is not None:
        v = _escape_md(f"{tnx['value']:.2f}%")
        c = _escape_md(_fmt_change(tnx.get("change_pct"), unit="%p"))
        lines.append(f"  🇺🇸 미 10년 국채: {v} \\({c}\\)")

    dxy = indicators.get("dxy") or {}
    if dxy.get("value") is not None:
        v = _escape_md(f"{dxy['value']:.1f}")
        c = _escape_md(_fmt_change(dxy.get("change_pct")))
        lines.append(f"  💵 달러 인덱스: {v} \\({c}\\)")

    gold = indicators.get("gold") or {}
    if gold.get("value") is not None:
        v = _escape_md(f"${gold['value']:,.0f}")
        c = _escape_md(_fmt_change(gold.get("change_pct")))
        lines.append(f"  🥇 금: {v} \\({c}\\)")

    oil = indicators.get("oil") or {}
    if oil.get("value") is not None:
        v = _escape_md(f"${oil['value']:.1f}")
        c = _escape_md(_fmt_change(oil.get("change_pct")))
        lines.append(f"  🛢 WTI 원유: {v} \\({c}\\)")

    if indicators.get("error"):
        lines.append(f"  _\\({_escape_md(indicators['error'])}\\)_")

    lines.append("")

    # ── MMF 자금 흐름 ──────────────────────────────────────
    lines.append("💰 *자금 흐름*")
    if mmf.get("value") is not None:
        # 단위: 십억 달러 → 조 달러로 표시
        val_t = mmf["value"] / 1000
        val_str = _escape_md(f"${val_t:.2f}조")
        if mmf.get("weekly_change") is not None:
            chg_b = mmf["weekly_change"]
            arrow = "↑" if chg_b >= 0 else "↓"
            sign = "+" if chg_b >= 0 else "−"
            chg_str = _escape_md(f"{sign}${abs(chg_b):.1f}십억 {arrow}")
            lines.append(f"  MMF 잔고: {val_str} \\(전주比 {chg_str}\\)")
        else:
            lines.append(f"  MMF 잔고: {val_str}")
    else:
        err = _escape_md(mmf.get("error") or "데이터 없음")
        lines.append(f"  MMF 잔고: _{err}_")

    lines.append("")

    # ── 투자 심리 ─────────────────────────────────────────
    lines.append("🎭 *투자 심리*")
    if fg.get("score") is not None:
        score = fg["score"]
        emoji = _fg_emoji(score)
        label = _escape_md(_fg_kr_label(score))
        score_str = _escape_md(f"{score:.0f}")
        source = fg.get("source", "")
        suffix = f" _\\({_escape_md(source)}\\)_" if source and source != "CNN" else ""
        lines.append(f"  Fear \\& Greed: {score_str}점 {emoji} {label}{suffix}")
    else:
        err = _escape_md(fg.get("error") or "데이터 없음")
        lines.append(f"  Fear \\& Greed: _{err}_")

    lines.append("")

    # ── 글로벌 뉴스 ───────────────────────────────────────
    lines.append("📰 *글로벌 주요 뉴스*")
    for i, item in enumerate(news):
        url = item.get("url", "")
        if item.get("error"):
            title = _escape_md(item.get("title", ""))
            lines.append(f"  _• {title}_")
        elif summaries and i < len(summaries):
            kr = _escape_md(summaries[i])
            if url:
                lines.append(f"  • [{kr}]({url})")
            else:
                lines.append(f"  • {kr}")
        else:
            title = _escape_md(item.get("title", ""))
            if url:
                lines.append(f"  • [{title}]({url})")
            else:
                lines.append(f"  • {title}")

    lines.append("")

    # ── 시장 해석 ─────────────────────────────────────────
    lines.append("📊 *시장 해석*")
    for bullet in _interpret_market(indicators, fg):
        lines.append(f"  {_escape_md(bullet)}")

    return "\n".join(lines)
