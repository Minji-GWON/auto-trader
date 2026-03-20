"""
추천 종목 여러 개를 한 번에 다운로드하고 백테스트하는 스크립트.

예시:
    python tests/batch_backtest.py --download-first
    python tests/batch_backtest.py --tickers 005930.KS,000660.KS
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.data_fetcher.fetcher import download_and_cache_ohlcv
from tests.backtest import run_backtest
from backend.database import init_db, save_batch_results
from backend.notifier import TelegramNotifier

DEFAULT_TICKERS = [
    "005930.KS",  # 삼성전자
    "000660.KS",  # SK하이닉스
    "035420.KS",  # 네이버
    "035720.KS",  # 카카오
    "005380.KS",  # 현대차
]


def parse_tickers(raw: str | None) -> list[str]:
    if not raw:
        return DEFAULT_TICKERS
    return [ticker.strip() for ticker in raw.split(",") if ticker.strip()]


def main():
    parser = argparse.ArgumentParser(description="Auto-Trader 일괄 백테스트")
    parser.add_argument("--tickers", help="쉼표로 구분한 종목 코드 목록")
    parser.add_argument("--period", default="1y")
    parser.add_argument("--download-source", default="auto", choices=["auto", "alphavantage", "yfinance", "pykrx"])
    parser.add_argument("--download-first", action="store_true", help="백테스트 전에 최신 데이터를 먼저 다운로드")
    parser.add_argument("--capital", type=float, default=10_000_000)
    parser.add_argument("--rsi-oversold", type=float, default=30)
    parser.add_argument("--rsi-overbought", type=float, default=70)
    parser.add_argument("--rsi-period", type=int, default=14)
    parser.add_argument("--bb-period", type=int, default=20)
    parser.add_argument("--bb-std-dev", type=float, default=2.0)
    parser.add_argument("--ma-short", type=int, default=20)
    parser.add_argument("--ma-long", type=int, default=60)
    args = parser.parse_args()

    tickers = parse_tickers(args.tickers)
    summary_rows = []

    for ticker in tickers:
        print(f"\n=== {ticker} ===")

        if args.download_first:
            try:
                saved_path = download_and_cache_ohlcv(
                    ticker=ticker,
                    period=args.period,
                    source=args.download_source,
                )
                print(f"데이터 저장: {saved_path}")
            except ValueError as exc:
                print(f"다운로드 실패: {exc}")
                continue

        try:
            result = run_backtest(
                ticker=ticker,
                period=args.period,
                initial_capital=args.capital,
                rsi_oversold=args.rsi_oversold,
                rsi_overbought=args.rsi_overbought,
                data_source="csv",
                rsi_period=args.rsi_period,
                bb_period=args.bb_period,
                bb_std_dev=args.bb_std_dev,
                ma_short=args.ma_short,
                ma_long=args.ma_long,
                verbose=False,
            )
        except ValueError as exc:
            print(f"백테스트 실패: {exc}")
            continue

        summary_rows.append(
            {
                "ticker": ticker,
                "total_return_pct": round(result["total_return_pct"], 2),
                "mdd_pct": round(result["mdd_pct"], 2),
                "trade_count": result["trade_count"],
                "win_rate": round(result["win_rate"], 2),
                "avg_hold_days": round(result["avg_hold_days"], 2),
                "final_capital": round(result["final_capital"], 0),
            }
        )
        print(
            "수익률 {return_pct:+.2f}% | MDD {mdd:+.2f}% | 거래 {trades}회 | 승률 {win_rate:.1f}%".format(
                return_pct=result["total_return_pct"],
                mdd=result["mdd_pct"],
                trades=result["trade_count"],
                win_rate=result["win_rate"],
            )
        )

    if not summary_rows:
        print("\n요약할 결과가 없습니다.")
        return

    summary_df = pd.DataFrame(summary_rows).sort_values(
        by=["total_return_pct", "win_rate"],
        ascending=[False, False],
    )

    TelegramNotifier().send_daily_report(summary_rows)

    init_db()
    run_date = datetime.now(timezone.utc).isoformat()
    save_batch_results(summary_df, run_date=run_date)
    print(f"DB 저장 완료 ({len(summary_df)}건)")

    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)
    output_path = results_dir / "batch_backtest_summary.csv"
    summary_df.to_csv(output_path, index=False, encoding="utf-8-sig")

    print("\n[일괄 백테스트 결과]")
    print(summary_df.to_string(index=False))
    print(f"\n저장 완료: {output_path}")


if __name__ == "__main__":
    main()
