"""
긴급 시장 뉴스 알림 스크립트.

GitHub Actions: 매 15분마다 실행 (cron: */15 * * * *)
최근 20분 이내 긴급 뉴스 감지 + 중복 제거 후 텔레그램 전송.

중복 제거 방식:
  - .breaking_news_seen.txt 에 이미 전송한 기사 URL 저장
  - GitHub Actions cache로 실행 간 유지 (7일 자동 만료)

사용법:
    python tests/breaking_news_alert.py            # 텔레그램 전송
    python tests/breaking_news_alert.py --dry-run  # 터미널만 출력
    python tests/breaking_news_alert.py --lookback 60  # 최근 60분 조회
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv()

from backend.scheduler.breaking_news import fetch_breaking_news, build_alert_message
from backend.notifier.telegram import TelegramNotifier

# 이미 전송한 기사 URL을 저장하는 파일 (GitHub Actions cache로 유지)
SEEN_FILE = ROOT / ".breaking_news_seen.txt"
MAX_SEEN = 500  # 최대 저장 URL 수 (오래된 것부터 제거)


def load_seen_urls() -> set[str]:
    """이미 전송한 URL 목록 로드."""
    if not SEEN_FILE.exists():
        return set()
    lines = SEEN_FILE.read_text(encoding="utf-8").splitlines()
    return set(line.strip() for line in lines if line.strip())


def save_seen_urls(seen: set[str]) -> None:
    """전송한 URL 목록 저장 (최대 MAX_SEEN개 유지)."""
    urls = list(seen)
    if len(urls) > MAX_SEEN:
        urls = urls[-MAX_SEEN:]  # 최신 것 유지
    SEEN_FILE.write_text("\n".join(urls) + "\n", encoding="utf-8")


def filter_new_articles(articles: list[dict], seen_urls: set[str]) -> list[dict]:
    """이미 전송한 기사 제외."""
    return [a for a in articles if a.get("url") and a["url"] not in seen_urls]


def main() -> None:
    parser = argparse.ArgumentParser(description="긴급 시장 뉴스 알림")
    parser.add_argument("--dry-run", action="store_true",
                        help="텔레그램 미전송, 터미널만 출력")
    parser.add_argument("--lookback", type=int, default=20,
                        help="몇 분 이내 기사 조회 (기본값: 20)")
    parser.add_argument("--reset", action="store_true",
                        help="중복 제거 캐시 초기화")
    args = parser.parse_args()

    if args.reset:
        SEEN_FILE.unlink(missing_ok=True)
        print("중복 제거 캐시 초기화 완료.")

    news_api_key = os.getenv("NEWS_API_KEY", "")
    if not news_api_key:
        print("[오류] NEWS_API_KEY 환경변수가 없습니다.")
        sys.exit(1)

    # 이미 전송한 URL 로드
    seen_urls = load_seen_urls()
    print(f"── 기존 전송 기사: {len(seen_urls)}건 ──")

    print(f"── 긴급 뉴스 조회 (최근 {args.lookback}분) ──")
    articles = fetch_breaking_news(news_api_key, lookback_minutes=args.lookback)
    print(f"  감지: {len(articles)}건")

    # 중복 제거
    new_articles = filter_new_articles(articles, seen_urls)
    skipped = len(articles) - len(new_articles)
    if skipped:
        print(f"  중복 제거: {skipped}건 스킵")

    if not new_articles:
        print("새로운 긴급 뉴스 없음 — 전송 생략.")
        return

    print(f"새 긴급 뉴스 {len(new_articles)}건:")
    for a in new_articles:
        print(f"  [{a['category']}] {a['title']} ({a['time_ago']})")

    message = build_alert_message(new_articles)
    print("\n── 메시지 미리보기 ──")
    print(message)

    if not args.dry_run:
        notifier = TelegramNotifier()
        notifier.send_message(message)
        print("\n텔레그램 전송 완료.")

        # 전송 성공 시에만 URL 저장
        for a in new_articles:
            if a.get("url"):
                seen_urls.add(a["url"])
        save_seen_urls(seen_urls)
        print(f"URL {len(new_articles)}개 저장 완료 (누적: {len(seen_urls)}건)")
    else:
        print("\n(dry-run: 텔레그램 미전송, URL 저장 생략)")


if __name__ == "__main__":
    main()
