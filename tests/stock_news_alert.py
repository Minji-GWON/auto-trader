"""
종목별 호재 뉴스 알림 실행 스크립트.

GitHub Actions: 15분마다 실행.

사용법:
    python tests/stock_news_alert.py              # 실제 전송
    python tests/stock_news_alert.py --dry-run    # 터미널 출력만
    python tests/stock_news_alert.py --reset      # seen 캐시 초기화
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(override=True)

from backend.scheduler.stock_news_alert import run, SEEN_FILE_TPL

# 알림 받을 종목 목록
TICKERS = ["MSFT"]


def main() -> None:
    parser = argparse.ArgumentParser(description="종목 호재 뉴스 알림")
    parser.add_argument("--dry-run", action="store_true", help="텔레그램 미전송")
    parser.add_argument("--reset",   action="store_true", help="seen 캐시 초기화")
    parser.add_argument("--lookback", type=int, default=20, help="몇 분 전까지 뉴스 조회 (기본: 20)")
    args = parser.parse_args()

    if args.reset:
        for ticker in TICKERS:
            p = Path(SEEN_FILE_TPL.format(ticker=ticker.lower()))
            p.unlink(missing_ok=True)
            print(f"  {ticker} seen 캐시 초기화 완료")

    token         = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id       = int(os.getenv("CHART_BOT_CHANNEL_ID", "-1003841992656"))
    finnhub_key   = os.getenv("FINNHUB_API_KEY", "")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")

    if not token:
        print("[오류] TELEGRAM_BOT_TOKEN 없음")
        return

    run(
        tickers          = TICKERS,
        token            = token,
        chat_id          = chat_id,
        finnhub_key      = finnhub_key,
        anthropic_key    = anthropic_key,
        lookback_minutes = args.lookback,
        dry_run          = args.dry_run,
    )


if __name__ == "__main__":
    main()
