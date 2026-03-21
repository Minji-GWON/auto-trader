"""
특정 종목 호재 뉴스 알림 모듈.

Finnhub company-news → Claude 호재 분류 → 한국어 번역 → 텔레그램 전송.
15분마다 실행, URL 기반 중복 방지.
"""

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# ── 상수 ──────────────────────────────────────────────────────────────────────
FINNHUB_BASE  = "https://finnhub.io/api/v1"
SEEN_FILE_TPL = ".stock_news_seen_{ticker}.txt"


# ── 뉴스 수집 ──────────────────────────────────────────────────────────────────
def fetch_recent_news(ticker: str, finnhub_key: str, lookback_minutes: int = 20) -> list[dict]:
    """Finnhub에서 최근 뉴스 조회."""
    if not finnhub_key:
        return []

    now  = datetime.now(timezone.utc)
    from_ = now - timedelta(minutes=lookback_minutes)

    try:
        r = requests.get(
            f"{FINNHUB_BASE}/company-news",
            params={
                "symbol": ticker,
                "from":   from_.strftime("%Y-%m-%d"),
                "to":     now.strftime("%Y-%m-%d"),
                "token":  finnhub_key,
            },
            timeout=10,
        )
        if r.status_code != 200:
            return []
        articles = r.json()
        if not isinstance(articles, list):
            return []

        # lookback_minutes 이내 기사만
        cutoff = from_.timestamp()
        result = []
        for a in articles:
            ts = a.get("datetime", 0)
            if ts >= cutoff and a.get("url") and a.get("headline"):
                result.append({
                    "url":     a["url"],
                    "title":   a["headline"],
                    "summary": a.get("summary", ""),
                    "source":  a.get("source", ""),
                    "time":    datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M"),
                })
        return result
    except Exception:
        return []


# ── 중복 방지 ──────────────────────────────────────────────────────────────────
def load_seen(ticker: str) -> set[str]:
    path = Path(SEEN_FILE_TPL.format(ticker=ticker.lower()))
    if not path.exists():
        return set()
    return set(path.read_text().splitlines())


def save_seen(ticker: str, urls: set[str]) -> None:
    path = Path(SEEN_FILE_TPL.format(ticker=ticker.lower()))
    path.write_text("\n".join(sorted(urls)))


def filter_new(articles: list[dict], ticker: str) -> tuple[list[dict], set[str]]:
    """이미 본 기사 제거. (new_articles, updated_seen_set) 반환."""
    seen = load_seen(ticker)
    new  = [a for a in articles if a["url"] not in seen]
    updated = seen | {a["url"] for a in new}
    return new, updated


# ── Claude 분류 & 번역 ─────────────────────────────────────────────────────────
def _call_claude(prompt: str, api_key: str, max_tokens: int = 2048) -> str:
    """Claude API 단순 호출 (requests 기반, SDK 의존성 없음)."""
    headers = {
        "x-api-key":         api_key,
        "anthropic-version": "2023-06-01",
        "content-type":      "application/json",
    }
    body = {
        "model":      "claude-opus-4-6",
        "max_tokens": max_tokens,
        "messages":   [{"role": "user", "content": prompt}],
    }
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=body,
            timeout=60,
        )
        if r.status_code != 200:
            return ""
        data = r.json()
        blocks = data.get("content", [])
        return next((b["text"] for b in blocks if b.get("type") == "text"), "")
    except Exception:
        return ""


def classify_positive(articles: list[dict], api_key: str) -> list[dict]:
    """
    Claude가 각 기사를 호재/악재/중립으로 분류.
    호재 기사만 반환.
    """
    if not articles or not api_key:
        return []

    items = "\n".join(
        f"[{i+1}] 제목: {a['title']}\n요약: {a['summary'][:300]}"
        for i, a in enumerate(articles)
    )
    prompt = f"""다음 주식 뉴스 기사들을 주가에 미치는 영향 기준으로 분류해주세요.

{items}

각 기사에 대해 아래 형식으로만 답변하세요 (다른 설명 없이):
[번호] 호재
또는
[번호] 악재
또는
[번호] 중립

주가 상승 요인(실적 개선, 신제품, 수주, 파트너십, 규제 완화 등)은 호재,
주가 하락 요인(실적 악화, 소송, 규제 강화, 리콜 등)은 악재,
나머지는 중립으로 분류하세요."""

    response = _call_claude(prompt, api_key, max_tokens=512)
    if not response:
        return []

    positive_indices = set()
    for line in response.splitlines():
        m = re.match(r"\[(\d+)\]\s*호재", line.strip())
        if m:
            positive_indices.add(int(m.group(1)) - 1)

    return [a for i, a in enumerate(articles) if i in positive_indices]


def translate_articles(articles: list[dict], api_key: str) -> list[dict]:
    """
    Claude가 제목 + 요약을 한국어로 번역.
    각 기사에 title_kr, summary_kr 키 추가 후 반환.
    """
    if not articles or not api_key:
        return [dict(a, title_kr=a["title"], summary_kr=a["summary"]) for a in articles]

    items = "\n".join(
        f"[{i+1}]\n제목: {a['title']}\n본문: {a['summary'][:400]}"
        for i, a in enumerate(articles)
    )
    prompt = f"""다음 주식 뉴스 기사들을 자연스러운 한국어로 번역해주세요.
투자자가 읽기 쉽도록 명확하게 번역하세요.

{items}

각 기사에 대해 아래 형식으로만 답변하세요:
[번호]
제목: (한국어 제목)
본문: (한국어 본문 요약, 3~5문장)"""

    response = _call_claude(prompt, api_key, max_tokens=2048)
    if not response:
        return [dict(a, title_kr=a["title"], summary_kr=a["summary"]) for a in articles]

    result = []
    for i, a in enumerate(articles):
        pattern = rf"\[{i+1}\]\s*\n제목:\s*(.+?)\n본문:\s*(.+?)(?=\[\d+\]|$)"
        m = re.search(pattern, response, re.DOTALL)
        if m:
            result.append(dict(
                a,
                title_kr   = m.group(1).strip(),
                summary_kr = m.group(2).strip(),
            ))
        else:
            result.append(dict(a, title_kr=a["title"], summary_kr=a["summary"]))
    return result


# ── 메시지 빌드 ───────────────────────────────────────────────────────────────
def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_alert_message(ticker: str, articles: list[dict]) -> str:
    """HTML 포맷 텔레그램 메시지 빌드."""
    now_kst = datetime.now(timezone.utc) + timedelta(hours=9)
    lines = [f"🚀 <b>{ticker} 호재 뉴스</b> ({now_kst.strftime('%m/%d %H:%M')} KST)\n"]

    for i, a in enumerate(articles, 1):
        title_kr   = _escape_html(a.get("title_kr",   a["title"]))
        summary_kr = _escape_html(a.get("summary_kr", a["summary"]))
        url        = a["url"]
        source     = _escape_html(a.get("source", ""))
        t          = a.get("time", "")

        lines.append(
            f"<b>{i}. {title_kr}</b>\n"
            f"{summary_kr}\n"
            f"<a href=\"{url}\">🔗 원문 ({source}, {t})</a>"
        )

    return "\n\n".join(lines)


# ── 전송 ──────────────────────────────────────────────────────────────────────
def send_alert(token: str, chat_id: int, message: str) -> bool:
    """텔레그램 HTML 메시지 전송."""
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id":    chat_id,
                "text":       message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        return r.status_code == 200
    except Exception:
        return False


# ── 메인 ──────────────────────────────────────────────────────────────────────
def run(
    tickers:          list[str],
    token:            str,
    chat_id:          int,
    finnhub_key:      str = "",
    anthropic_key:    str = "",
    lookback_minutes: int = 20,
    dry_run:          bool = False,
) -> None:
    """
    각 ticker에 대해:
      1. 최근 뉴스 수집
      2. 신규 기사 필터
      3. 호재 분류
      4. 한국어 번역
      5. 텔레그램 전송
    """
    for ticker in tickers:
        print(f"\n[{ticker}] 뉴스 수집 중...")
        articles = fetch_recent_news(ticker, finnhub_key, lookback_minutes)
        print(f"  수집: {len(articles)}건")

        if not articles:
            continue

        new_articles, updated_seen = filter_new(articles, ticker)
        print(f"  신규: {len(new_articles)}건")

        if not new_articles:
            continue

        # 호재 분류
        positives = classify_positive(new_articles, anthropic_key)
        print(f"  호재: {len(positives)}건")

        if not positives:
            save_seen(ticker, updated_seen)
            continue

        # 한국어 번역
        translated = translate_articles(positives, anthropic_key)

        # 메시지 빌드
        msg = build_alert_message(ticker, translated)
        print(f"\n{msg}\n")

        # 전송
        if not dry_run:
            ok = send_alert(token, chat_id, msg)
            print(f"  전송: {'완료' if ok else '실패'}")
        else:
            print("  (dry-run: 전송 생략)")

        save_seen(ticker, updated_seen)
        time.sleep(1)  # API rate limit
