"""
일일 매크로 시장 브리핑 실행 스크립트.

GitHub Actions: UTC 22:00 일~목 = KST 07:00 월~금

사용법:
    python tests/daily_macro_briefing.py            # 텔레그램 전송
    python tests/daily_macro_briefing.py --dry-run  # 터미널만 출력
"""

import argparse
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv()

from backend.scheduler.macro_briefing import (
    build_briefing_message,
    get_fear_greed,
    get_market_indicators,
    get_mmf_data,
    get_top_news,
)
from backend.notifier.telegram import TelegramNotifier


def main() -> None:
    parser = argparse.ArgumentParser(description="일일 매크로 시장 브리핑")
    parser.add_argument("--dry-run", action="store_true",
                        help="텔레그램 미전송, 터미널만 출력")
    parser.add_argument("--news-count", type=int, default=5,
                        help="뉴스 헤드라인 개수 (기본값: 5)")
    args = parser.parse_args()

    fred_api_key = os.getenv("FRED_API_KEY", "")
    news_api_key = os.getenv("NEWS_API_KEY", "")

    print("── 시장 지표 수집 (yfinance) ──")
    indicators = get_market_indicators()
    for k, v in indicators.items():
        if k == "error":
            if v:
                print(f"  [오류] {v}")
        elif isinstance(v, dict) and v.get("value") is not None:
            print(f"  {k}: {v['value']:.2f} ({v['change_pct']:+.2f}%)")

    print("── Fear & Greed Index (CNN / VIX 추정) ──")
    vix_value = (indicators.get("vix") or {}).get("value")
    fg = get_fear_greed(vix=vix_value)
    if fg.get("score") is not None:
        print(f"  점수: {fg['score']:.0f} — {fg['label']}")
    else:
        print(f"  [오류] {fg.get('error')}")

    print("── MMF 잔고 (FRED) ──")
    mmf = get_mmf_data(fred_api_key)
    if mmf.get("value") is not None:
        print(f"  ${mmf['value']:.1f}십억 (전주比 {mmf.get('weekly_change', 0):+.1f}십억)")
    else:
        print(f"  [오류] {mmf.get('error')}")

    print("── 글로벌 뉴스 (NewsAPI) ──")
    news = get_top_news(news_api_key, n=args.news_count)
    for item in news:
        prefix = "  [오류]" if item.get("error") else "  •"
        print(f"{prefix} {item['title']}")

    message = build_briefing_message(
        indicators=indicators,
        mmf=mmf,
        fg=fg,
        news=news,
        today=date.today(),
    )

    print("\n── 브리핑 메시지 미리보기 ──")
    print(message)

    if not args.dry_run:
        notifier = TelegramNotifier()
        notifier.send_message(message)
        print("\n텔레그램 전송 완료.")
    else:
        print("\n(dry-run: 텔레그램 미전송)")


if __name__ == "__main__":
    main()
