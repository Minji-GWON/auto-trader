"""
매일 장 마감 후 실행: 다운로드된 모든 종목의 오늘 신호를 체크하고 텔레그램 알림 전송.

사용법:
    python tests/daily_signal_check.py                  # 전체 종목
    python tests/daily_signal_check.py --market kosdaq  # 코스닥만
    python tests/daily_signal_check.py --dry-run        # 텔레그램 미전송, 터미널만 출력

cron 등록 예시 (평일 16:10 실행):
    10 16 * * 1-5 /path/to/.venv/bin/python /path/to/tests/daily_signal_check.py
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.stocks import KOSPI_MAJOR, KOSDAQ_MAJOR
from backend.scheduler.signal_checker import (
    get_market_trend, print_market_trend,
    check_signals_today, send_signal_report, print_report,
    check_my_positions, send_position_report,
)
from backend.database import init_db
from backend.notifier import TelegramNotifier


def main():
    parser = argparse.ArgumentParser(description="일일 매매 신호 체크")
    parser.add_argument(
        "--market",
        default="all",
        choices=["all", "kospi", "kosdaq"],
        help="체크할 시장 (기본: all)",
    )
    parser.add_argument("--rsi-oversold", type=float, default=35)
    parser.add_argument("--rsi-overbought", type=float, default=65)
    parser.add_argument("--bb-std-dev", type=float, default=1.5)
    parser.add_argument("--ma-short", type=int, default=20)
    parser.add_argument("--ma-long", type=int, default=40)
    parser.add_argument("--no-swing", action="store_true", help="스윙 모드 OFF (기본: ON)")
    parser.add_argument("--dry-run", action="store_true", help="텔레그램 미전송, 터미널만 출력")
    args = parser.parse_args()

    if args.market == "kospi":
        stock_list = KOSPI_MAJOR
    elif args.market == "kosdaq":
        stock_list = KOSDAQ_MAJOR
    else:
        stock_list = KOSPI_MAJOR + KOSDAQ_MAJOR

    tickers = [code for code, _ in stock_list]

    init_db()

    # ── 시장 흐름 체크 (가장 먼저)
    print("── 시장 흐름 체크 ──")
    market_trend = get_market_trend()
    print_market_trend(market_trend)

    params = dict(
        rsi_oversold=args.rsi_oversold,
        rsi_overbought=args.rsi_overbought,
        bb_std_dev=args.bb_std_dev,
        ma_short=args.ma_short,
        ma_long=args.ma_long,
        swing_mode=not args.no_swing,
    )

    # ① 보유 포지션 모니터링 (우선순위 높음)
    print("── 보유 포지션 체크 ──")
    position_results = check_my_positions(**params)
    if position_results:
        for r in position_results:
            alert_icon = {"손절": "🔴", "익절": "🟡", "매도신호": "🔔"}.get(r["alert"], "✅")
            sign = "+" if r["pnl_pct"] >= 0 else ""
            print(f"  {alert_icon} {r['ticker']} {r['name']:12s} | "
                  f"매수 {r['entry_price']:,} → 현재 {r['current_price']:,}원 | "
                  f"{sign}{r['pnl_pct']:.1f}% ({r['pnl_won']:+,}원) | {r['alert']}")
        if not args.dry_run:
            send_position_report(position_results)
    else:
        print("  보유 종목 없음")

    # ② 전체 시장 신호 스캔
    print(f"\n── 신호 스캔 ({args.market.upper()} {len(tickers)}개) ──")
    results = check_signals_today(tickers=tickers, **params)
    print_report(results)

    if not args.dry_run:
        send_signal_report(results, market_trend=market_trend)
        print("텔레그램 알림 전송 완료")
    else:
        print("(dry-run: 텔레그램 미전송)")


if __name__ == "__main__":
    main()
