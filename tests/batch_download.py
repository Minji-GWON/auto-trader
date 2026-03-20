"""
코스피/코스닥 주요 종목을 일괄 다운로드하는 스크립트.

예시:
    python tests/batch_download.py                        # 코스닥 전체
    python tests/batch_download.py --market kospi         # 코스피 전체
    python tests/batch_download.py --market all           # 전체
    python tests/batch_download.py --market kosdaq --period 1y
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.data_fetcher.fetcher import download_and_cache_ohlcv, get_default_csv_path
from backend.stocks import KOSPI_MAJOR, KOSDAQ_MAJOR


def main():
    parser = argparse.ArgumentParser(description="Auto-Trader 일괄 데이터 다운로드")
    parser.add_argument(
        "--market",
        default="kosdaq",
        choices=["all", "kospi", "kosdaq"],
        help="다운로드 시장 (기본: kosdaq)",
    )
    parser.add_argument("--period", default="3y", help="데이터 기간 (기본: 3y)")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="종목 간 요청 간격(초). pykrx 과부하 방지 (기본: 1.0)")
    parser.add_argument("--skip-existing", action="store_true",
                        help="이미 다운로드된 종목은 건너뜀")
    args = parser.parse_args()

    if args.market == "kospi":
        stock_list = KOSPI_MAJOR
    elif args.market == "kosdaq":
        stock_list = KOSDAQ_MAJOR
    else:
        stock_list = KOSPI_MAJOR + KOSDAQ_MAJOR

    print(f"[일괄 다운로드] {args.market.upper()} {len(stock_list)}개 종목 / 기간: {args.period}")
    print("-" * 60)

    success, skipped, failed = [], [], []

    for i, (ticker, name) in enumerate(stock_list, 1):
        csv_path = get_default_csv_path(ticker)

        if args.skip_existing and csv_path.exists():
            print(f"  [{i:2d}/{len(stock_list)}] ⏭  {ticker} {name} — 이미 존재, 건너뜀")
            skipped.append((ticker, name))
            continue

        try:
            saved = download_and_cache_ohlcv(
                ticker=ticker,
                period=args.period,
                interval="1d",
                source="auto",
                csv_path=str(csv_path),
            )
            # 저장된 행 수 확인
            import pandas as pd
            rows = len(pd.read_csv(saved))
            print(f"  [{i:2d}/{len(stock_list)}] ✓  {ticker} {name:15s} — {rows}일치 저장")
            success.append((ticker, name))
        except Exception as exc:
            print(f"  [{i:2d}/{len(stock_list)}] ✗  {ticker} {name} — 실패: {exc}")
            failed.append((ticker, name))

        if i < len(stock_list):
            time.sleep(args.delay)

    print("\n" + "=" * 60)
    print(f"  완료: {len(success)}개  |  건너뜀: {len(skipped)}개  |  실패: {len(failed)}개")
    if failed:
        print(f"  실패 종목: {', '.join(n for _, n in failed)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
