"""
코스피/코스닥 주요 종목을 자동 스캔해 수익률 좋은 종목을 찾는 스크리너.

예시:
    python tests/stock_screener.py
    python tests/stock_screener.py --top 20 --period 2y
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.backtest import run_backtest
from backend.database import init_db, save_batch_results
from backend.notifier import TelegramNotifier
from backend.stocks import KOSPI_MAJOR, KOSDAQ_MAJOR


def main():
    parser = argparse.ArgumentParser(description="Auto-Trader 종목 스크리너")
    parser.add_argument("--period", default="2y", help="데이터 기간 (기본: 2y)")
    parser.add_argument("--capital", type=float, default=10_000_000)
    parser.add_argument("--top", type=int, default=10, help="상위 N개 출력 (기본: 10)")
    parser.add_argument("--min-trades", type=int, default=1, help="최소 거래 횟수 필터 (기본: 1)")
    # 최적 파라미터 (parameter_sweep 결과 기반)
    parser.add_argument("--rsi-oversold", type=float, default=40)
    parser.add_argument("--rsi-overbought", type=float, default=65)
    parser.add_argument("--ma-short", type=int, default=20)
    parser.add_argument("--ma-long", type=int, default=40)
    parser.add_argument("--bb-period", type=int, default=20)
    parser.add_argument("--bb-std-dev", type=float, default=1.5)
    parser.add_argument(
        "--market",
        default="all",
        choices=["all", "kospi", "kosdaq"],
        help="스캔 시장: all(전체) / kospi / kosdaq (기본: all)",
    )
    parser.add_argument("--swing", action="store_true", help="단타/스윙 모드 ON")
    args = parser.parse_args()

    if args.market == "kospi":
        stock_list = KOSPI_MAJOR
    elif args.market == "kosdaq":
        stock_list = KOSDAQ_MAJOR
    else:
        stock_list = KOSPI_MAJOR + KOSDAQ_MAJOR

    print(f"총 {len(stock_list)}개 종목 스캔 시작 (시장: {args.market.upper()}, 기간: {args.period})")
    print(f"파라미터: RSI {args.rsi_oversold}/{args.rsi_overbought}, "
          f"MA {args.ma_short}/{args.ma_long}, BB {args.bb_period}/{args.bb_std_dev}"
          f"{', 스윙모드' if args.swing else ''}")
    print("-" * 60)

    summary_rows = []
    failed = []

    for ticker, name in stock_list:
        try:
            result = run_backtest(
                ticker=ticker,
                period=args.period,
                initial_capital=args.capital,
                rsi_oversold=args.rsi_oversold,
                rsi_overbought=args.rsi_overbought,
                data_source="auto",
                rsi_period=14,
                bb_period=args.bb_period,
                bb_std_dev=args.bb_std_dev,
                ma_short=args.ma_short,
                ma_long=args.ma_long,
                swing_mode=args.swing,
                verbose=False,
            )
            summary_rows.append({
                "ticker": ticker,
                "name": name,
                "total_return_pct": round(result["total_return_pct"], 2),
                "mdd_pct": round(result["mdd_pct"], 2),
                "trade_count": result["trade_count"],
                "win_rate": round(result["win_rate"], 2),
                "avg_hold_days": round(result["avg_hold_days"], 2),
                "final_capital": round(result["final_capital"], 0),
            })
            print(f"  ✓ {ticker} {name:15s} | 수익률: {result['total_return_pct']:+.2f}% "
                  f"| 거래: {result['trade_count']}회 | 승률: {result['win_rate']:.0f}%")
        except Exception as exc:
            failed.append((ticker, name))
            print(f"  ✗ {ticker} {name} — 실패: {exc}")

    if not summary_rows:
        print("\n결과 없음")
        return

    summary_df = pd.DataFrame(summary_rows)

    # 최소 거래 횟수 필터 → 수익률 정렬
    filtered = summary_df[summary_df["trade_count"] >= args.min_trades].sort_values(
        by=["total_return_pct", "win_rate"],
        ascending=[False, False],
    )

    print("\n" + "=" * 60)
    print(f"  [상위 {args.top}개 추천 종목]")
    print("=" * 60)
    display_cols = ["ticker", "name", "total_return_pct", "mdd_pct", "trade_count", "win_rate"]
    print(filtered[display_cols].head(args.top).to_string(index=False))

    # DB 저장
    init_db()
    run_date = datetime.now(timezone.utc).isoformat()
    save_batch_results(
        summary_df[["ticker", "total_return_pct", "mdd_pct", "trade_count",
                     "win_rate", "avg_hold_days", "final_capital"]],
        run_date=run_date,
    )

    # CSV 저장
    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)
    output_path = results_dir / "screener_results.csv"
    filtered.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"\nCSV 저장: {output_path}")

    # 텔레그램 알림
    top_rows = filtered.head(args.top).to_dict("records")
    if top_rows:
        notifier = TelegramNotifier()
        lines = [f"🔍 *종목 스크리너 결과* \\(상위 {args.top}개\\)", "종목 \\| 수익률 \\| 거래 \\| 승률"]
        from backend.notifier.telegram import _escape_md
        for r in top_rows:
            sign = "+" if r["total_return_pct"] >= 0 else ""
            ret_str = f"{sign}{r['total_return_pct']:.1f}%"
            lines.append(
                f"{_escape_md(r['ticker'])} {_escape_md(r['name'])} \\| "
                f"{_escape_md(ret_str)} \\| "
                f"{_escape_md(str(r['trade_count']) + '회')} \\| "
                f"{_escape_md(str(round(r['win_rate'])) + '%')}"
            )
        notifier.send_message("\n".join(lines))

    if failed:
        print(f"\n실패 종목 {len(failed)}개: {', '.join(n for _, n in failed)}")


if __name__ == "__main__":
    main()
