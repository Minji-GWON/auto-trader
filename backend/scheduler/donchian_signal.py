"""
돈치안 채널 돌파 신호 체크 — 한국/미국 공통.

터틀룰 표준:
  진입(BUY)  : 직전 20일 최고가 상향 돌파
  청산(SELL) : 직전 10일 최저가 하향 이탈

기존 BB+RSI 흐름과 독립적으로 동작한다. daily_signal_check(_us).py에서
BB+RSI 알림 직후 별도 호출되어 별도 텔레그램 메시지로 전송된다.
"""

from datetime import date

from backend.data_fetcher.fetcher import fetch_ohlcv
from backend.indicators.calculator import add_donchian
from backend.strategy.signal import generate_signals, BUY, SELL, STRATEGY_DONCHIAN
from backend.notifier import TelegramNotifier


_MIN_ROWS = 30  # entry_period(20) + 여유


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

    buy_list = [r for r in results if r["signal"] == BUY]
    sell_list = [r for r in results if r["signal"] == SELL]

    def _price_str(price: float) -> str:
        if is_korean:
            return f"{price:,.0f}원"
        return f"${price:,.2f}"

    if buy_list:
        lines.append(f"\n🟢 *상단 돌파 매수 {len(buy_list)}개*")
        for r in buy_list:
            price_str = _escape_md(_price_str(r["price"]))
            upper_str = _escape_md(_price_str(r["dc_upper"]))
            lines.append(
                f"• {_escape_md(r['name'])} \\({_escape_md(r['ticker'])}\\) — "
                f"{price_str} \\(20일 상단 {upper_str}\\)"
            )

    if sell_list:
        lines.append(f"\n🔴 *하단 이탈 매도 {len(sell_list)}개*")
        for r in sell_list:
            price_str = _escape_md(_price_str(r["price"]))
            lower_str = _escape_md(_price_str(r["dc_lower"]))
            lines.append(
                f"• {_escape_md(r['name'])} \\({_escape_md(r['ticker'])}\\) — "
                f"{price_str} \\(10일 하단 {lower_str}\\)"
            )

    if not buy_list and not sell_list:
        lines.append("\n✅ 돈치안 돌파/이탈 종목 없음")

    notifier.send_message("\n".join(lines))


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
