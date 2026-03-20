"""
긴급 시장 뉴스 알림 스크립트.

GitHub Actions: 매 15분마다 실행 (cron: */15 * * * *)
최근 20분 이내 긴급 뉴스 감지 시 텔레그램 즉시 전송.

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


def main() -> None:
    parser = argparse.ArgumentParser(description="긴급 시장 뉴스 알림")
    parser.add_argument("--dry-run", action="store_true",
                        help="텔레그램 미전송, 터미널만 출력")
    parser.add_argument("--lookback", type=int, default=20,
                        help="몇 분 이내 기사 조회 (기본값: 20)")
    args = parser.parse_args()

    news_api_key = os.getenv("NEWS_API_KEY", "")
    if not news_api_key:
        print("[오류] NEWS_API_KEY 환경변수가 없습니다.")
        sys.exit(1)

    print(f"── 긴급 뉴스 조회 (최근 {args.lookback}분) ──")
    articles = fetch_breaking_news(news_api_key, lookback_minutes=args.lookback)

    if not articles:
        print("감지된 긴급 뉴스 없음 — 전송 생략.")
        return

    print(f"긴급 뉴스 {len(articles)}건 감지:")
    for a in articles:
        print(f"  [{a['category']}] {a['title']} ({a['time_ago']})")

    message = build_alert_message(articles)
    print("\n── 메시지 미리보기 ──")
    print(message)

    if not args.dry_run:
        notifier = TelegramNotifier()
        notifier.send_message(message)
        print("\n텔레그램 전송 완료.")
    else:
        print("\n(dry-run: 텔레그램 미전송)")


if __name__ == "__main__":
    main()
