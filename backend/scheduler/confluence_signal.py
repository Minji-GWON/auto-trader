"""
전략 일치(Confluence) 신호 — BB+RSI와 돈치안이 같은 방향을 가리키는 종목 강조.

평균회귀(BB+RSI)와 추세추종(돈치안)은 본질적으로 다른 국면에서 작동한다.
두 전략이 같은 종목에서 같은 방향(매수/매도)을 동시에 가리키는 경우는
시장 국면이 어느 쪽이든 신뢰도가 높은 신호로 해석된다.
"""

from datetime import date

from backend.strategy.signal import BUY, SELL
from backend.notifier import TelegramNotifier


def find_confluence_signals(
    bb_rsi_results: list[dict],
    dc_results: list[dict],
) -> list[dict]:
    """
    BB+RSI 결과와 돈치안 결과를 ticker 기준으로 매칭해 같은 방향 신호만 반환.

    Args:
        bb_rsi_results: signal_checker.check_signals_today() 반환값
        dc_results:     donchian_signal.check_donchian_signals() 반환값

    Returns:
        [{"ticker", "name", "signal", "price", "rsi", "dc_upper", "dc_lower"}]
        signal은 BUY 또는 SELL.
    """
    bb_map = {r["ticker"]: r for r in bb_rsi_results}
    dc_map = {r["ticker"]: r for r in dc_results}

    matches = []
    for ticker in set(bb_map) & set(dc_map):
        bb = bb_map[ticker]
        dc = dc_map[ticker]
        if bb["signal"] != dc["signal"]:
            continue
        matches.append({
            "ticker":   ticker,
            "name":     bb.get("name") or dc.get("name") or ticker,
            "signal":   bb["signal"],
            "price":    bb.get("price") or dc.get("price"),
            "rsi":      bb.get("rsi"),
            "dc_upper": dc.get("dc_upper"),
            "dc_lower": dc.get("dc_lower"),
        })
    return matches


def send_confluence_report(
    matches: list[dict],
    market_label: str,
    is_korean: bool = True,
    notifier: TelegramNotifier = None,
) -> None:
    """일치 신호를 트레이드 보조지표 채널로 한 메시지에 전송."""
    if notifier is None:
        notifier = TelegramNotifier()
    from backend.notifier.telegram import _escape_md

    today = date.today().strftime("%Y\\-%m\\-%d")
    lines = [
        f"⭐ *강한 신호 \\({_escape_md(market_label)}\\)* \\({today}\\)",
        f"_BB\\+RSI \\+ 돈치안 양쪽 일치_",
    ]

    buy_list = [m for m in matches if m["signal"] == BUY]
    sell_list = [m for m in matches if m["signal"] == SELL]

    def _price_str(price) -> str:
        if price is None:
            return "?"
        if is_korean:
            return f"{price:,.0f}원"
        return f"${price:,.2f}"

    def _line(m: dict, ref_key: str, ref_label: str) -> str:
        price_str = _escape_md(_price_str(m["price"]))
        ref_str = _escape_md(_price_str(m.get(ref_key)))
        rsi_part = ""
        if m.get("rsi") is not None:
            rsi_part = f"  \\|  RSI {_escape_md(str(m['rsi']))}"
        return (
            f"• *{_escape_md(m['name'])}* \\({_escape_md(m['ticker'])}\\) — "
            f"{price_str}\n"
            f"  {_escape_md(ref_label)} {ref_str}{rsi_part}"
        )

    if buy_list:
        lines.append(f"\n🟢 *강한 매수 {len(buy_list)}개*")
        for m in buy_list:
            lines.append(_line(m, "dc_upper", "20일 채널 상단"))

    if sell_list:
        lines.append(f"\n🔴 *강한 매도 {len(sell_list)}개*")
        for m in sell_list:
            lines.append(_line(m, "dc_lower", "10일 채널 하단"))

    if not buy_list and not sell_list:
        lines.append("\n✅ 오늘은 양쪽 일치 신호 없음")

    notifier.send_message("\n".join(lines))


def print_confluence_report(matches: list[dict], market_label: str) -> None:
    today = date.today().strftime("%Y-%m-%d")
    buy_list = [m for m in matches if m["signal"] == BUY]
    sell_list = [m for m in matches if m["signal"] == SELL]

    print(f"\n{'='*65}")
    print(f"  강한 신호 (BB+RSI + 돈치안 일치) — {market_label} — {today}")
    print(f"{'='*65}")

    if buy_list:
        print(f"\n🟢 강한 매수 {len(buy_list)}개")
        for m in buy_list:
            rsi = f"RSI {m['rsi']}" if m.get("rsi") is not None else ""
            print(f"  {m['ticker']:8s} {m['name']:20s} | "
                  f"가격: {m['price']:>10,.2f} | 상단: {m.get('dc_upper'):>10,.2f}  {rsi}")

    if sell_list:
        print(f"\n🔴 강한 매도 {len(sell_list)}개")
        for m in sell_list:
            rsi = f"RSI {m['rsi']}" if m.get("rsi") is not None else ""
            print(f"  {m['ticker']:8s} {m['name']:20s} | "
                  f"가격: {m['price']:>10,.2f} | 하단: {m.get('dc_lower'):>10,.2f}  {rsi}")

    if not buy_list and not sell_list:
        print("\n  양쪽 일치 신호 없음")
    print(f"\n{'='*65}")
