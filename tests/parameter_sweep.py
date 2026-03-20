"""
파라미터 조합을 반복 실행해 백테스트 결과를 비교하는 스크립트.

예시:
    python tests/parameter_sweep.py --source csv --csv-path data/sample_ohlcv.csv
"""

import argparse
import sys
from datetime import datetime, timezone
from itertools import product
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.backtest import run_backtest
from backend.database import init_db, save_parameter_sweep


def parse_int_list(raw: str) -> list[int]:
    return [int(value.strip()) for value in raw.split(",") if value.strip()]


def parse_float_list(raw: str) -> list[float]:
    return [float(value.strip()) for value in raw.split(",") if value.strip()]


def main():
    parser = argparse.ArgumentParser(description="Auto-Trader 파라미터 스윕")
    parser.add_argument("--ticker", default="SAMPLE")
    parser.add_argument("--period", default="1y")
    parser.add_argument("--capital", type=float, default=10_000_000)
    parser.add_argument("--source", default="csv", choices=["auto", "alphavantage", "csv", "yfinance"])
    parser.add_argument("--csv-path", default="data/sample_ohlcv.csv")
    parser.add_argument("--rsi-oversold-list", default="25,30,35")
    parser.add_argument("--rsi-overbought-list", default="65,70,75")
    parser.add_argument("--ma-short-list", default="5,10")
    parser.add_argument("--ma-long-list", default="15,20")
    parser.add_argument("--bb-period-list", default="10,20")
    args = parser.parse_args()

    rsi_oversold_values = parse_float_list(args.rsi_oversold_list)
    rsi_overbought_values = parse_float_list(args.rsi_overbought_list)
    ma_short_values = parse_int_list(args.ma_short_list)
    ma_long_values = parse_int_list(args.ma_long_list)
    bb_period_values = parse_int_list(args.bb_period_list)

    rows = []
    for rsi_oversold, rsi_overbought, ma_short, ma_long, bb_period in product(
        rsi_oversold_values,
        rsi_overbought_values,
        ma_short_values,
        ma_long_values,
        bb_period_values,
    ):
        if ma_short >= ma_long:
            continue

        result = run_backtest(
            ticker=args.ticker,
            period=args.period,
            initial_capital=args.capital,
            rsi_oversold=rsi_oversold,
            rsi_overbought=rsi_overbought,
            data_source=args.source,
            csv_path=args.csv_path,
            bb_period=bb_period,
            ma_short=ma_short,
            ma_long=ma_long,
            verbose=False,
        )
        rows.append(
            {
                "rsi_oversold": rsi_oversold,
                "rsi_overbought": rsi_overbought,
                "ma_short": ma_short,
                "ma_long": ma_long,
                "bb_period": bb_period,
                "total_return_pct": round(result["total_return_pct"], 2),
                "mdd_pct": round(result["mdd_pct"], 2),
                "trade_count": result["trade_count"],
                "win_rate": round(result["win_rate"], 2),
            }
        )

    summary = pd.DataFrame(rows).sort_values(
        by=["total_return_pct", "win_rate", "trade_count"],
        ascending=[False, False, False],
    )

    init_db()
    run_date = datetime.now(timezone.utc).isoformat()
    save_parameter_sweep(summary, run_date=run_date, ticker=args.ticker)
    print(f"DB 저장 완료 ({len(summary)}건, ticker={args.ticker})")

    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)
    output_path = results_dir / "parameter_sweep_results.csv"
    summary.to_csv(output_path, index=False, encoding="utf-8-sig")

    print("\n[상위 결과]")
    print(summary.head(10).to_string(index=False))
    print(f"\n저장 완료: {output_path}")


if __name__ == "__main__":
    main()
