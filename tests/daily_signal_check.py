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
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.stocks import KOSPI_MAJOR, KOSDAQ_MAJOR, get_name
from backend.scheduler.signal_checker import (
    get_market_trend, print_market_trend,
    check_signals_today, send_signal_report, print_report,
    check_my_positions, send_position_report,
)
from backend.scheduler.donchian_signal import (
    check_donchian_signals, send_donchian_report, send_donchian_buy_alerts,
    print_donchian_report,
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
    # 파라미터 스윕으로 도출한 국장 최적값 (RSI45/65, MA10/30, BB1.5)
    parser.add_argument("--rsi-oversold", type=float, default=45)
    parser.add_argument("--rsi-overbought", type=float, default=65)
    parser.add_argument("--bb-std-dev", type=float, default=1.5)
    parser.add_argument("--ma-short", type=int, default=10)
    parser.add_argument("--ma-long", type=int, default=30)
    parser.add_argument("--no-swing", action="store_true", help="스윙 모드 OFF (기본: ON)")
    parser.add_argument("--dry-run", action="store_true", help="텔레그램 미전송, 터미널만 출력")
    parser.add_argument("--no-donchian", action="store_true", help="돈치안 채널 신호 체크 OFF (기본: ON)")
    parser.add_argument("--dc-entry-period", type=int, default=20)
    parser.add_argument("--dc-exit-period", type=int, default=10)
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
    results = check_signals_today(tickers=tickers, market_trend=market_trend, **params)
    print_report(results)

    if not args.dry_run:
        send_signal_report(results, market_trend=market_trend)
        print("텔레그램 알림 전송 완료")
    else:
        print("(dry-run: 텔레그램 미전송)")

    # ③ 돈치안 채널 돌파 신호 (BB+RSI와 독립적인 추세추종 전략)
    #    - 종합 리포트 → 트레이드 보조지표 채널 (기본 TELEGRAM_CHAT_ID)
    #    - 개별 매수 신호 → 차트 분석 채널 (CHART_BOT_CHANNEL_ID), 종목당 1메시지
    if not args.no_donchian:
        print(f"\n── 돈치안 채널 스캔 ({args.market.upper()} {len(tickers)}개) ──")
        dc_results = check_donchian_signals(
            tickers=tickers,
            entry_period=args.dc_entry_period,
            exit_period=args.dc_exit_period,
            name_resolver=get_name,
        )
        print_donchian_report(dc_results, market_label="한국")
        if not args.dry_run:
            send_donchian_report(dc_results, market_label="한국", is_korean=True)
            print("돈치안 종합 알림 전송 완료 (보조지표 채널)")

            chart_chat_id = os.getenv("CHART_BOT_CHANNEL_ID", "").strip()
            if chart_chat_id:
                chart_notifier = TelegramNotifier(chat_id=chart_chat_id)
                sent = send_donchian_buy_alerts(
                    dc_results, market_label="한국", is_korean=True,
                    notifier=chart_notifier,
                )
                print(f"돈치안 개별 매수 알림 {sent}건 전송 (차트 분석 채널)")
            else:
                print("[경고] CHART_BOT_CHANNEL_ID 미설정 — 개별 매수 알림 미전송")


if __name__ == "__main__":
    main()
