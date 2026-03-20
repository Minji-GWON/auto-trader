"""
Claude API를 이용한 뉴스 한국어 요약 모듈.

영어 뉴스 헤드라인 리스트를 받아 핵심 내용을 한국어 1줄로 요약.
"""

from __future__ import annotations

import os
from typing import Optional


def summarize_news_kr(
    articles: list[dict],
    api_key: Optional[str] = None,
) -> list[str]:
    """
    영어 뉴스 기사 제목을 한국어 1줄 요약으로 변환.

    Args:
        articles: [{"title": str, "url": str, ...}] 형태의 기사 목록
        api_key: Anthropic API 키 (없으면 ANTHROPIC_API_KEY 환경변수 사용)

    Returns:
        기사 순서와 동일한 한국어 요약 리스트.
        실패 시 빈 리스트 반환 (원본 표시로 폴백).
    """
    key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
    if not key or not articles:
        return []

    try:
        import anthropic
    except ImportError:
        return []

    titles = "\n".join(
        f"{i+1}. {a['title']}" for i, a in enumerate(articles)
    )

    prompt = f"""다음 영어 뉴스 헤드라인을 각각 한국어로 20자 이내의 핵심 1줄로 요약하세요.
번호는 유지하고, 요약만 출력하세요. 다른 설명은 생략하세요.

{titles}"""

    try:
        client = anthropic.Anthropic(api_key=key)
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        text = next(
            (b.text for b in response.content if b.type == "text"), ""
        ).strip()

        summaries = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            # "1. 내용" 형태에서 번호 제거
            if line[0].isdigit() and ". " in line:
                line = line.split(". ", 1)[1].strip()
            summaries.append(line)

        # 기사 수와 맞지 않으면 폴백
        if len(summaries) != len(articles):
            return []

        return summaries

    except Exception as e:
        print(f"[NewsSummarizer] 요약 실패: {e}")
        return []
