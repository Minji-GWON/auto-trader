"""
미국 주식 — 매일 장 마감 후 신호 체크 + 텔레그램 알림.

사용법:
    python tests/daily_signal_check_us.py           # 전체 종목
    python tests/daily_signal_check_us.py --dry-run # 텔레그램 미전송

GitHub Actions 실행 시각:
    미장 마감 EST 16:00 → UTC 21:10 (표준시) / 20:10 (서머타임)
    KST 기준 다음날 06:10
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.stocks_us import US_STOCKS
from backend.scheduler.signal_checker_us import (
    get_market_trend_us, print_market_trend_us,
    check_signals_today_us, send_signal_report_us,
    print_report_us,
)
from backend.database import init_db


def main():
    parser = argparse.ArgumentParser(description="미국 주식 일일 신호 체크")
    # 파라미터 스윕으로 도출한 미장 최적값 (RSI40/65, MA10/30, BB1.5)
    parser.add_argument("--rsi-oversold",  type=float, default=40)
    parser.add_argument("--rsi-overbought", type=float, default=65)
    parser.add_argument("--bb-std-dev",    type=float, default=1.5)
    parser.add_argument("--ma-short",      type=int,   default=10)
    parser.add_argument("--ma-long",       type=int,   default=30)
    parser.add_argument("--no-swing",      action="store_true", help="스윙 모드 OFF")
    parser.add_argument("--dry-run",       action="store_true", help="텔레그램 미전송")
    args = parser.parse_args()

    tickers = [ticker for ticker, _ in US_STOCKS]

    init_db()

    # ── 시장 흐름 (SPY 기준)
    print("── 미국 시장 흐름 체크 (SPY) ──")
    market_trend = get_market_trend_us()
    print_market_trend_us(market_trend)

    params = dict(
        rsi_oversold=args.rsi_oversold,
        rsi_overbought=args.rsi_overbought,
        bb_std_dev=args.bb_std_dev,
        ma_short=args.ma_short,
        ma_long=args.ma_long,
        swing_mode=not args.no_swing,
    )

    # ── 전체 종목 신호 스캔
    print(f"\n── 신호 스캔 (US {len(tickers)}개) ──")
    results = check_signals_today_us(
        tickers=tickers, market_trend=market_trend, **params
    )
    print_report_us(results)

    if not args.dry_run:
        send_signal_report_us(results, market_trend=market_trend)
        print("텔레그램 알림 전송 완료")
    else:
        print("(dry-run: 텔레그램 미전송)")


if __name__ == "__main__":
    main()
