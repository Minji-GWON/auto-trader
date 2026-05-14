"""
프리/애프터마켓 매수/매도 신호 알림.

미장 정규시간 외(프리마켓 04:00~09:30 EST, 애프터마켓 16:00~20:00 EST)에
지정한 종목들에 대해 15분봉 RSI+볼린저 신호 체크.

세션 라벨은 현재 UTC 시간으로 자동 판단:
  - UTC 8~13   → "프리마켓"
  - UTC 20~24  → "애프터마켓"

사용법:
    python tests/semi_extended_hours_alert.py
    python tests/semi_extended_hours_alert.py --dry-run
    python tests/semi_extended_hours_alert.py --tickers MSFT AAPL
"""

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(override=True)

from backend.scheduler.intraday_signal import run

SEEN_FILE = Path(".semi_extended_seen.json")
_DEFAULT_TICKERS = ["MSFT"]


def _session_label() -> str:
    """현재 UTC 시간으로 프리/애프터마켓 라벨 결정."""
    h = datetime.now(timezone.utc).hour
    if 8 <= h < 14:
        return "프리마켓"
    if 20 <= h or h < 1:
        return "애프터마켓"
    return "장외"


def main():
    parser = argparse.ArgumentParser(description="프리/애프터마켓 신호 알림")
    parser.add_argument("--dry-run", action="store_true", help="텔레그램 미전송")
    parser.add_argument("--reset",   action="store_true", help="중복 방지 캐시 초기화")
    parser.add_argument("--tickers", nargs="+", default=_DEFAULT_TICKERS,
                        help="티커 목록 (기본값: MSFT)")
    args = parser.parse_args()

    if args.reset and SEEN_FILE.exists():
        SEEN_FILE.unlink()
        print("캐시 초기화 완료.")

    token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("CHART_BOT_CHANNEL_ID", "")

    if not token or not chat_id:
        print("[경고] TELEGRAM_BOT_TOKEN 또는 CHART_BOT_CHANNEL_ID 미설정")

    label = _session_label()
    print(f"세션: {label} | 종목 {len(args.tickers)}개")

    run(
        tickers=args.tickers,
        token=token,
        chat_id=chat_id,
        dry_run=args.dry_run,
        prepost=True,
        seen_file=SEEN_FILE,
        session_label=label,
    )


if __name__ == "__main__":
    main()
