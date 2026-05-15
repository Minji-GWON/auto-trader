"""
NVDA 장중 15분봉 매수/매도 신호 알림 실행 스크립트.

사용법:
    python tests/nvda_intraday_alert.py             # 실제 전송
    python tests/nvda_intraday_alert.py --dry-run   # 터미널만 출력
    python tests/nvda_intraday_alert.py --reset      # 중복 방지 캐시 초기화
    python tests/nvda_intraday_alert.py --tickers NVDA TSLA AAPL
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(override=True)

from backend.scheduler.intraday_signal import SEEN_FILE, run
from backend.scheduler.vb_intraday import VB_SEEN_FILE, run_vb


def main():
    parser = argparse.ArgumentParser(description="NVDA 장중 신호 알림")
    parser.add_argument("--dry-run",  action="store_true", help="텔레그램 미전송")
    parser.add_argument("--reset",    action="store_true", help="중복 방지 캐시 초기화")
    parser.add_argument("--tickers",  nargs="+", default=["NVDA"],
                        help="티커 목록 (기본값: NVDA)")
    parser.add_argument("--no-vb",    action="store_true",
                        help="변동성 돌파 신호 OFF (기본: ON)")
    parser.add_argument("--vb-k",     type=float, default=0.5,
                        help="변동성 돌파 K값 (기본: 0.5)")
    args = parser.parse_args()

    if args.reset:
        if SEEN_FILE.exists():
            SEEN_FILE.unlink()
        if VB_SEEN_FILE.exists():
            VB_SEEN_FILE.unlink()
        print("캐시 초기화 완료.")

    token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("CHART_BOT_CHANNEL_ID", "")

    if not token or not chat_id:
        print("[경고] TELEGRAM_BOT_TOKEN 또는 CHART_BOT_CHANNEL_ID 미설정")

    # ① 기존 RSI+BB 15분봉 신호
    run(
        tickers=args.tickers,
        token=token,
        chat_id=chat_id,
        dry_run=args.dry_run,
    )

    # ② Larry Williams 변동성 돌파 (일봉 기준 진입 알림)
    if not args.no_vb:
        run_vb(
            tickers=args.tickers,
            token=token,
            chat_id=chat_id,
            k=args.vb_k,
            dry_run=args.dry_run,
        )


if __name__ == "__main__":
    main()
