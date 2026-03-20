"""
긴급 시장 뉴스 모니터링 모듈

NewsAPI /everything 엔드포인트로 15분마다 긴급 키워드 검색.
최근 20분 이내 발행된 기사 중 매칭 시 텔레그램 즉시 전송.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional



import requests

_TIMEOUT = 8

# ---------------------------------------------------------------------------
# 긴급 키워드 (카테고리별)
# ---------------------------------------------------------------------------

KEYWORDS: dict[str, list[str]] = {
    "전쟁/지정학": [
        "war", "invasion", "nuclear", "missile", "sanctions",
    ],
    "금융위기": [
        "market crash", "circuit breaker", "bank collapse", "financial crisis",
    ],
    "연준/금리": [
        "emergency rate", "rate hike", "rate cut", "fed emergency",
    ],
    "관세/무역": [
        "tariff", "trade war", "export control",
    ],
    "재난/팬데믹": [
        "pandemic", "earthquake", "explosion",
    ],
}

# NewsAPI 쿼리용 단일 OR 문자열 (500자 이내로 유지)
_QUERY = " OR ".join(
    f'"{kw}"' if " " in kw else kw
    for kws in KEYWORDS.values()
    for kw in kws
)


def _escape_md(text) -> str:
    return re.sub(r'([_\*\[\]()~`>#+\-=|{}.!\\])', r'\\\1', str(text))


def _category_of(title: str, description: str) -> str:
    """기사 제목/설명에서 매칭된 카테고리 반환."""
    text = (title + " " + (description or "")).lower()
    for cat, kws in KEYWORDS.items():
        for kw in kws:
            if kw.lower() in text:
                return cat
    return "긴급"


def _time_ago(published_at: str) -> str:
    """'2026-03-20T07:32:00Z' → '3분 전' 형태로 변환."""
    try:
        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        diff = datetime.now(timezone.utc) - dt
        mins = int(diff.total_seconds() / 60)
        if mins < 1:
            return "방금 전"
        if mins < 60:
            return f"{mins}분 전"
        return f"{mins // 60}시간 전"
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# 데이터 수집
# ---------------------------------------------------------------------------

def fetch_breaking_news(
    news_api_key: str,
    lookback_minutes: int = 20,
    max_articles: int = 5,
) -> list[dict]:
    """
    최근 lookback_minutes 이내 발행된 긴급 뉴스 기사 반환.

    반환:
        [{"title": str, "source": str, "url": str,
          "published_at": str, "time_ago": str, "category": str}]
    """
    if not news_api_key:
        return []

    from_time = (datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes))
    from_str = from_time.strftime("%Y-%m-%dT%H:%M:%SZ")

    # 무료 플랜: /everything은 24시간 딜레이 → /top-headlines 사용 후 키워드 후처리
    url = "https://newsapi.org/v2/top-headlines"
    params = {
        "category": "business",
        "language": "en",
        "pageSize": 30,
        "apiKey": news_api_key,
    }

    try:
        resp = requests.get(url, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        articles = resp.json().get("articles", [])
    except Exception as e:
        print(f"[BreakingNews] 조회 실패: {e}")
        return []

    # 모든 키워드 소문자 목록
    all_kws = [kw.lower() for kws in KEYWORDS.values() for kw in kws]

    # 최근 lookback_minutes 이내 + 키워드 매칭 필터
    from_dt = datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)
    result = []
    seen_titles: set[str] = set()

    for a in articles:
        title = (a.get("title") or "").strip()
        if not title or title in seen_titles or title == "[Removed]":
            continue
        seen_titles.add(title)

        # 발행 시각 필터
        published_at = a.get("publishedAt") or ""
        try:
            pub_dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            if pub_dt < from_dt:
                continue
        except Exception:
            pass  # 시각 파싱 실패 시 포함

        # 키워드 매칭 필터
        description = a.get("description") or ""
        text = (title + " " + description).lower()
        if not any(kw in text for kw in all_kws):
            continue

        source = (a.get("source") or {}).get("name", "")
        article_url = a.get("url", "")
        category = _category_of(title, description)

        result.append({
            "title": title,
            "source": source,
            "url": article_url,
            "published_at": published_at,
            "time_ago": _time_ago(published_at),
            "category": category,
        })

        if len(result) >= max_articles:
            break

    return result


# ---------------------------------------------------------------------------
# 메시지 빌드
# ---------------------------------------------------------------------------

def build_alert_message(
    articles: list[dict],
    summaries: Optional[list[str]] = None,
) -> str:
    """긴급 뉴스 텔레그램 MarkdownV2 메시지 조립."""
    now_str = _escape_md(datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
    count = len(articles)

    lines = [
        f"🚨 *긴급 시장 알림* \\({now_str}\\)",
        f"_{_escape_md(f'최근 20분 내 긴급 뉴스 {count}건 감지')}_",
        "",
    ]

    for i, a in enumerate(articles):
        source = _escape_md(a["source"])
        time_ago = _escape_md(a["time_ago"])
        category = _escape_md(a["category"])
        url = a["url"]

        lines.append(f"*{i+1}\\. {category}*")

        if summaries and i < len(summaries):
            # 한국어 요약 + 링크
            kr = _escape_md(summaries[i])
            if url:
                lines.append(f"📰 [{kr}]({url})")
            else:
                lines.append(f"📰 {kr}")
        else:
            # 폴백: 영어 원문
            title = _escape_md(a["title"])
            if url:
                lines.append(f"📰 [{title}]({url})")
            else:
                lines.append(f"📰 {title}")

        lines.append(f"   출처: {source} \\| {time_ago}")
        lines.append("")

    lines.append("⚠️ _즉각적인 시장 변동성 확대 가능\\. 포지션 점검 권장_")
    return "\n".join(lines)
