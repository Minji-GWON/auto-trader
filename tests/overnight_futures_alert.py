"""
미국 야간 지수선물(다우, 나스닥) 매수/매도 신호 알림.

미장 마감(EDT 16:00) ~ 다음날 프리마켓 시작(EDT 04:00) 사이의 약 12시간 동안
CME GLOBEX에서 거의 24시간 거래되는 지수선물에 대해 15분봉 RSI+볼린저 신호 체크.

워크플로 cron이 KST 09:00~17:00 (UTC 0~8)에만 트리거되므로
이 스크립트가 실행되는 시간 = "미국 야간" 시간대.

NYSE 휴장일에는 알림 스킵.

사용법:
    python tests/overnight_futures_alert.py
    python tests/overnight_futures_alert.py --dry-run
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(override=True)

from backend.scheduler.intraday_signal import run
from backend.scheduler.holidays import is_us_market_holiday
from backend.stocks_us import OVERNIGHT_FUTURES

SEEN_FILE = Path(".overnight_futures_seen.json")


def main():
    parser = argparse.ArgumentParser(description="미국 야간 지수선물 신호 알림")
    parser.add_argument("--dry-run", action="store_true", help="텔레그램 미전송")
    parser.add_argument("--reset",   action="store_true", help="중복 방지 캐시 초기화")
    parser.add_argument("--ignore-holiday", action="store_true",
                        help="휴장일 체크 무시 (테스트용)")
    args = parser.parse_args()

    if not args.ignore_holiday and is_us_market_holiday():
        print("[스킵] 오늘은 NYSE 휴장일")
        return

    if args.reset and SEEN_FILE.exists():
        SEEN_FILE.unlink()
        print("캐시 초기화 완료.")

    token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("CHART_BOT_CHANNEL_ID", "")

    if not token or not chat_id:
        print("[경고] TELEGRAM_BOT_TOKEN 또는 CHART_BOT_CHANNEL_ID 미설정")

    tickers = list(OVERNIGHT_FUTURES.keys())
    print(f"세션: 야간선물 | 종목 {len(tickers)}개 ({', '.join(tickers)})")

    run(
        tickers=tickers,
        token=token,
        chat_id=chat_id,
        dry_run=args.dry_run,
        prepost=False,
        seen_file=SEEN_FILE,
        session_label="야간",
        display_names=OVERNIGHT_FUTURES,
    )


if __name__ == "__main__":
    main()
