"""
인터넷에서 시세 데이터를 내려받아 data/ 폴더에 저장하는 스크립트.

예시:
    python tests/download_data.py --ticker AAPL --period 2y
    python tests/download_data.py --ticker 005930.KS --period 1y --source yfinance
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.data_fetcher.fetcher import download_and_cache_ohlcv, get_default_csv_path


def main():
    parser = argparse.ArgumentParser(description="Auto-Trader 데이터 다운로드")
    parser.add_argument("--ticker", required=True, help="종목 코드")
    parser.add_argument("--period", default="1y", help="다운로드 기간 (기본: 1y)")
    parser.add_argument("--interval", default="1d", help="봉 간격 (기본: 1d)")
    parser.add_argument(
        "--source",
        default="auto",
        choices=["auto", "alphavantage", "yfinance"],
        help="다운로드 소스 (기본: auto)",
    )
    parser.add_argument("--output", help="저장할 CSV 경로")
    args = parser.parse_args()

    output_path = args.output or str(get_default_csv_path(args.ticker))

    try:
        saved_path = download_and_cache_ohlcv(
            ticker=args.ticker,
            period=args.period,
            interval=args.interval,
            source=args.source,
            csv_path=output_path,
        )
    except ValueError as exc:
        print(f"\n데이터 다운로드 실패: {exc}")
        sys.exit(1)

    print(f"\n다운로드 완료: {saved_path}")


if __name__ == "__main__":
    main()
