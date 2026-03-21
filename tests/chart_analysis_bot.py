"""
텔레그램 차트 분석 봇 실행 스크립트.

GitHub Actions: 5분마다 실행, 채널의 /분석 명령 처리.

사용법:
    python tests/chart_analysis_bot.py              # 실제 전송
    python tests/chart_analysis_bot.py --dry-run    # 터미널 출력만
    python tests/chart_analysis_bot.py --test AAPL  # 특정 종목 강제 테스트
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(override=True)

from backend.scheduler.chart_bot import (
    generate_chart, fetch_company_news, fetch_kr_news,
    summarize_to_korean, build_caption, build_news_message,
    send_photo, send_message, get_pending_commands, run,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="차트 분석 봇")
    parser.add_argument("--dry-run", action="store_true", help="텔레그램 미전송")
    parser.add_argument("--test",    type=str, default="", help="강제 테스트 종목 (예: AAPL)")
    parser.add_argument("--reset",   action="store_true", help="offset 캐시 초기화")
    args = parser.parse_args()

    token         = os.getenv("TELEGRAM_BOT_TOKEN", "")
    channel_id    = int(os.getenv("CHART_BOT_CHANNEL_ID", "-1003841992656"))
    finnhub_key   = os.getenv("FINNHUB_API_KEY", "")
    news_api_key  = os.getenv("NEWS_API_KEY", "")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")

    if args.reset:
        from backend.scheduler.chart_bot import OFFSET_FILE
        OFFSET_FILE.unlink(missing_ok=True)
        print("offset 캐시 초기화 완료.")

    if args.test:
        ticker = args.test.upper()
        print(f"── 강제 테스트: {ticker} ──")
        buf, analysis = generate_chart(ticker)
        if buf is None:
            print(f"  [오류] {ticker} 차트 생성 실패")
            return

        analyst = None
        if not analysis["is_kr"]:
            from backend.scheduler.finnhub_targets import get_analyst_summary
            analyst = get_analyst_summary(ticker, analysis["price"], finnhub_key)
            print(f"  애널리스트: {analyst}")

        if analysis["is_kr"]:
            from backend.stocks import get_name
            news = fetch_kr_news(get_name(ticker), news_api_key, n=3)
        else:
            news = fetch_company_news(ticker, finnhub_key, n=3)
        print(f"  뉴스 {len(news)}건: {[n['title'][:40] for n in news]}")

        summaries = summarize_to_korean(news, anthropic_key) if news else []
        print(f"  번역: {summaries}")

        caption = build_caption(ticker, analysis, analyst)
        print(f"\n── 차트 캡션 ({len(caption)}자) ──")
        print(caption)

        if news:
            news_msg = build_news_message(ticker, news, summaries)
            print(f"\n── 뉴스 메시지 ({len(news_msg)}자) ──")
            print(news_msg)

        if not args.dry_run:
            ok = send_photo(token, channel_id, buf, caption)
            print(f"\n차트 전송: {'완료' if ok else '실패'}")
            if news:
                ok2 = send_message(token, channel_id, news_msg)
                print(f"뉴스 전송: {'완료' if ok2 else '실패'}")
        else:
            print("\n(dry-run: 전송 생략)")
        return

    # 일반 실행: 채널 폴링
    if not token:
        print("[오류] TELEGRAM_BOT_TOKEN 없음")
        return

    if args.dry_run:
        cmds = get_pending_commands(token, channel_id)
        print(f"미처리 명령: {cmds}")
    else:
        run(token, channel_id,
            finnhub_key=finnhub_key,
            news_api_key=news_api_key,
            anthropic_key=anthropic_key)


if __name__ == "__main__":
    main()
