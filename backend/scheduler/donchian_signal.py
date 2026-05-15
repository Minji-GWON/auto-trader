"""
돈치안 채널 돌파 신호 체크 — 한국/미국 공통.

터틀룰 표준:
  진입(BUY)  : 직전 20일 최고가 상향 돌파
  청산(SELL) : 직전 10일 최저가 하향 이탈

알림은 두 채널로 나뉜다 (기존 BB+RSI 패턴과 동일):
  - 종합 리포트(send_donchian_report)        → 트레이드 보조지표 채널
  - 개별 매수 알림(send_donchian_buy_alerts) → 차트 분석 채널 (종목당 1메시지)
"""

import os

from datetime import date

from backend.data_fetcher.fetcher import fetch_ohlcv
from backend.indicators.calculator import add_donchian
from backend.strategy.signal import generate_signals, BUY, SELL, STRATEGY_DONCHIAN
from backend.notifier import TelegramNotifier


_MIN_ROWS = 30  # entry_period(20) + 여유

# 텔레그램 종합 메시지에 표시할 매수/매도 종목 최대 개수 (돌파/이탈 강도 상위 N개)
_TELEGRAM_TOP_N = 5


def _buy_strength(r: dict) -> float:
    """매수 강도 = (close - 20일 상단) / 20일 상단. 클수록 강한 돌파."""
    upper = r.get("dc_upper") or 0
    if not upper:
        return 0.0
    return (r["price"] - upper) / upper


def _sell_strength(r: dict) -> float:
    """매도 강도 = (10일 하단 - close) / 10일 하단. 클수록 깊은 이탈."""
    lower = r.get("dc_lower") or 0
    if not lower:
        return 0.0
    return (lower - r["price"]) / lower


def check_donchian_signals(
    tickers: list[str],
    entry_period: int = 20,
    exit_period: int = 10,
    data_period: str = "3mo",
    name_resolver=None,
) -> list[dict]:
    """
    돈치안 채널 돌파 신호 종목만 반환 (HOLD 제외).

    Args:
        name_resolver: ticker -> 종목명 변환 함수. 없으면 ticker를 그대로 사용.
    """
    results = []
    for ticker in tickers:
        try:
            df = fetch_ohlcv(ticker=ticker, period=data_period, source="auto")
            if df is None or len(df) < _MIN_ROWS:
                continue

            df = add_donchian(df, entry_period=entry_period, exit_period=exit_period)
            df = generate_signals(df, strategy=STRATEGY_DONCHIAN)
            df = df.dropna()
            if df.empty:
                continue

            last = df.iloc[-1]
            signal = last["signal"]
            if signal not in (BUY, SELL):
                continue

            code = ticker.split(".")[0]
            name = name_resolver(code) if name_resolver else ticker
            results.append({
                "ticker":   code,
                "name":     name or ticker,
                "signal":   signal,
                "price":    float(last["close"]),
                "dc_upper": float(last["dc_upper"]),
                "dc_lower": float(last["dc_exit_lower"]) if signal == SELL else float(last["dc_lower"]),
                "date":     df.index[-1].strftime("%Y-%m-%d"),
            })
        except Exception:
            pass
    return results


def send_donchian_report(
    results: list[dict],
    market_label: str,
    is_korean: bool = True,
    notifier: TelegramNotifier = None,
) -> None:
    """돈치안 신호를 텔레그램으로 전송 (BB+RSI 알림과 별도 메시지)."""
    if notifier is None:
        notifier = TelegramNotifier()
    from backend.notifier.telegram import _escape_md

    today = date.today().strftime("%Y\\-%m\\-%d")
    lines = [f"🐢 *돈치안 채널 \\({_escape_md(market_label)}\\)* \\({today}\\)"]

    # 돌파/이탈 강도 강한 순으로 정렬
    buy_list = sorted(
        [r for r in results if r["signal"] == BUY],
        key=_buy_strength, reverse=True,
    )
    sell_list = sorted(
        [r for r in results if r["signal"] == SELL],
        key=_sell_strength, reverse=True,
    )

    def _price_str(price: float) -> str:
        if is_korean:
            return f"{price:,.0f}원"
        return f"${price:,.2f}"

    if buy_list:
        total = len(buy_list)
        header = f"\n🟢 *상단 돌파 매수 {total}개*"
        if total > _TELEGRAM_TOP_N:
            header += f"  \\(상위 {_TELEGRAM_TOP_N}개\\)"
        lines.append(header)
        for r in buy_list[:_TELEGRAM_TOP_N]:
            price_str = _escape_md(_price_str(r["price"]))
            upper_str = _escape_md(_price_str(r["dc_upper"]))
            lines.append(
                f"• {_escape_md(r['name'])} \\({_escape_md(r['ticker'])}\\) — "
                f"{price_str} \\(20일 상단 {upper_str}\\)"
            )

    if sell_list:
        total = len(sell_list)
        header = f"\n🔴 *하단 이탈 매도 {total}개*"
        if total > _TELEGRAM_TOP_N:
            header += f"  \\(상위 {_TELEGRAM_TOP_N}개\\)"
        lines.append(header)
        for r in sell_list[:_TELEGRAM_TOP_N]:
            price_str = _escape_md(_price_str(r["price"]))
            lower_str = _escape_md(_price_str(r["dc_lower"]))
            lines.append(
                f"• {_escape_md(r['name'])} \\({_escape_md(r['ticker'])}\\) — "
                f"{price_str} \\(10일 하단 {lower_str}\\)"
            )

    if not buy_list and not sell_list:
        lines.append("\n✅ 돈치안 돌파/이탈 종목 없음")

    notifier.send_message("\n".join(lines))


def send_donchian_buy_alerts(
    results: list[dict],
    market_label: str,
    is_korean: bool = True,
    notifier: TelegramNotifier = None,
) -> int:
    """
    매수 신호(BUY) 종목만 골라 종목당 한 개씩 개별 메시지로 전송.
    차트 분석 채널 (CHART_BOT_CHANNEL_ID) 용도.

    Returns:
        실제 전송된 메시지 개수.
    """
    buy_list = [r for r in results if r["signal"] == BUY]
    if not buy_list:
        return 0

    if notifier is None:
        chart_chat_id = os.getenv("CHART_BOT_CHANNEL_ID", "").strip()
        if not chart_chat_id:
            return 0
        notifier = TelegramNotifier(chat_id=chart_chat_id)

    from backend.notifier.telegram import _escape_md

    def _price_str(price: float) -> str:
        if is_korean:
            return f"{price:,.0f}원"
        return f"${price:,.2f}"

    sent = 0
    for r in buy_list:
        price_str = _escape_md(_price_str(r["price"]))
        upper_str = _escape_md(_price_str(r["dc_upper"]))
        text = (
            f"🐢 *돈치안 매수 신호* \\({_escape_md(market_label)}\\)\n"
            f"*{_escape_md(r['name'])}* \\({_escape_md(r['ticker'])}\\)\n"
            f"가격: {price_str}\n"
            f"20일 채널 상단 {upper_str} 돌파\n"
            f"📅 {_escape_md(r['date'])}"
        )
        notifier.send_message(text)
        sent += 1
    return sent


def print_donchian_report(results: list[dict], market_label: str) -> None:
    """터미널 출력."""
    today = date.today().strftime("%Y-%m-%d")
    buy_list = [r for r in results if r["signal"] == BUY]
    sell_list = [r for r in results if r["signal"] == SELL]

    print(f"\n{'='*65}")
    print(f"  돈치안 채널 — {market_label} — {today}")
    print(f"{'='*65}")

    if buy_list:
        print(f"\n🟢 상단 돌파 {len(buy_list)}개")
        for r in buy_list:
            print(f"  {r['ticker']:8s} {r['name']:20s} | "
                  f"가격: {r['price']:>10,.2f} | 20일 상단: {r['dc_upper']:>10,.2f}")

    if sell_list:
        print(f"\n🔴 하단 이탈 {len(sell_list)}개")
        for r in sell_list:
            print(f"  {r['ticker']:8s} {r['name']:20s} | "
                  f"가격: {r['price']:>10,.2f} | 10일 하단: {r['dc_lower']:>10,.2f}")

    if not buy_list and not sell_list:
        print("\n  돈치안 돌파/이탈 종목 없음")
    print(f"\n{'='*65}")
