"""
오늘 시장 데이터를 받아 매수/매도 신호를 체크하고 텔레그램으로 알림 전송.

사용법:
    python -m backend.scheduler.signal_checker
    python tests/daily_signal_check.py
"""

import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.data_fetcher.fetcher import fetch_ohlcv
from backend.indicators.calculator import add_all_indicators
from backend.strategy.signal import generate_signals, BUY, SELL
from backend.notifier import TelegramNotifier
from backend.stocks import ALL_STOCKS, get_name
from backend.database import get_open_positions


# 신호 체크에 필요한 최소 봉 수 (ma_long 기본 40 + 여유)
_MIN_ROWS = 80


def check_signals_today(
    tickers: list[str],
    rsi_oversold: float = 35,
    rsi_overbought: float = 65,
    rsi_period: int = 14,
    bb_period: int = 20,
    bb_std_dev: float = 1.5,
    ma_short: int = 20,
    ma_long: int = 40,
    swing_mode: bool = True,
    data_period: str = "6mo",
) -> list[dict]:
    """
    주어진 종목 리스트에 대해 오늘 신호를 체크하고 결과 리스트 반환.

    Returns:
        [{"ticker", "name", "signal", "price", "rsi", "date"}, ...]
        signal이 HOLD인 종목은 포함되지 않음.
    """
    results = []

    for ticker in tickers:
        try:
            df = fetch_ohlcv(ticker=ticker, period=data_period, source="auto")
            if len(df) < _MIN_ROWS:
                continue

            df = add_all_indicators(
                df,
                rsi_period=rsi_period,
                bb_period=bb_period,
                bb_std_dev=bb_std_dev,
                ma_short=ma_short,
                ma_long=ma_long,
            )
            df = generate_signals(
                df,
                rsi_oversold=rsi_oversold,
                rsi_overbought=rsi_overbought,
                swing_mode=swing_mode,
            )
            df = df.dropna()
            if df.empty:
                continue

            last = df.iloc[-1]
            signal = last["signal"]
            if signal == "HOLD":
                continue

            code = ticker.split(".")[0]
            results.append({
                "ticker": code,
                "name": get_name(code),
                "signal": signal,
                "price": int(last["close"]),
                "rsi": round(float(last["rsi"]), 1),
                "bb_position": _bb_position(last),
                "date": df.index[-1].strftime("%Y-%m-%d"),
            })
        except Exception:
            pass

    return results


def _bb_position(row) -> str:
    """현재가가 볼린저밴드 어느 위치인지 설명."""
    close = row["close"]
    upper = row["bb_upper"]
    lower = row["bb_lower"]
    mid = row["bb_middle"]
    if close <= lower:
        return "하단 이탈"
    elif close >= upper:
        return "상단 돌파"
    elif close < mid:
        return "중간 아래"
    else:
        return "중간 위"


def send_signal_report(results: list[dict], notifier: TelegramNotifier = None):
    """신호 결과를 텔레그램으로 전송."""
    if notifier is None:
        notifier = TelegramNotifier()

    today = date.today().strftime("%Y\\-%m\\-%d")
    buy_list = [r for r in results if r["signal"] == BUY]
    sell_list = [r for r in results if r["signal"] == SELL]

    lines = [f"📡 *일일 신호 체크* \\({today}\\)"]

    from backend.notifier.telegram import _escape_md

    if buy_list:
        lines.append(f"\n🟢 *매수 신호 {len(buy_list)}개*")
        for r in buy_list:
            price_str = _escape_md(f"{r['price']:,}")
            rsi_str = _escape_md(str(r['rsi']))
            bb_str = _escape_md(r['bb_position'])
            name_str = _escape_md(r['name'])
            ticker_str = _escape_md(r['ticker'])
            lines.append(
                f"• {name_str} \\({ticker_str}\\)\n"
                f"  현재가: {price_str}원  RSI: {rsi_str}  BB: {bb_str}"
            )

    if sell_list:
        lines.append(f"\n🔴 *매도 신호 {len(sell_list)}개*")
        for r in sell_list:
            price_str = _escape_md(f"{r['price']:,}")
            rsi_str = _escape_md(str(r['rsi']))
            bb_str = _escape_md(r['bb_position'])
            name_str = _escape_md(r['name'])
            ticker_str = _escape_md(r['ticker'])
            lines.append(
                f"• {name_str} \\({ticker_str}\\)\n"
                f"  현재가: {price_str}원  RSI: {rsi_str}  BB: {bb_str}"
            )

    if not buy_list and not sell_list:
        lines.append("\n✅ 오늘은 매수/매도 신호 없음 \\(관망\\)")

    notifier.send_message("\n".join(lines))


def check_my_positions(
    rsi_oversold: float = 35,
    rsi_overbought: float = 65,
    rsi_period: int = 14,
    bb_period: int = 20,
    bb_std_dev: float = 1.5,
    ma_short: int = 20,
    ma_long: int = 40,
    swing_mode: bool = True,
) -> list[dict]:
    """
    내가 보유 중인 포지션을 조회해 현재 상태(수익률, 신호, 손절/익절 여부)를 반환.

    Returns:
        [{"position_id", "ticker", "name", "entry_price", "shares",
          "entry_date", "current_price", "pnl_pct", "pnl_won",
          "signal", "rsi", "stop_loss", "take_profit",
          "alert": "정상"|"매도신호"|"손절"|"익절", ...}]
    """
    positions = get_open_positions()
    if not positions:
        return []

    results = []
    for pos in positions:
        ticker = pos["ticker"]
        try:
            df = fetch_ohlcv(ticker=ticker, period="6mo", source="auto")
            if len(df) < _MIN_ROWS:
                continue

            df = add_all_indicators(df, rsi_period=rsi_period, bb_period=bb_period,
                                    bb_std_dev=bb_std_dev, ma_short=ma_short, ma_long=ma_long)
            df = generate_signals(df, rsi_oversold=rsi_oversold,
                                  rsi_overbought=rsi_overbought, swing_mode=swing_mode)
            df = df.dropna()
            if df.empty:
                continue

            last = df.iloc[-1]
            current_price = int(last["close"])
            entry_price = pos["entry_price"]
            shares = pos["shares"]
            pnl_pct = round((current_price / entry_price - 1) * 100, 2)
            pnl_won = int((current_price - entry_price) * shares)

            # 알림 판단
            alert = "정상"
            if current_price <= pos["stop_loss"]:
                alert = "손절"
            elif current_price >= pos["take_profit"]:
                alert = "익절"
            elif last["signal"] == SELL:
                alert = "매도신호"

            results.append({
                "position_id": pos["id"],
                "ticker": ticker,
                "name": pos["name"] or get_name(ticker),
                "entry_price": int(entry_price),
                "shares": shares,
                "entry_date": pos["entry_date"],
                "current_price": current_price,
                "pnl_pct": pnl_pct,
                "pnl_won": pnl_won,
                "signal": last["signal"],
                "rsi": round(float(last["rsi"]), 1),
                "bb_position": _bb_position(last),
                "stop_loss": int(pos["stop_loss"]),
                "take_profit": int(pos["take_profit"]),
                "alert": alert,
                "date": df.index[-1].strftime("%Y-%m-%d"),
            })
        except Exception:
            pass

    return results


def send_position_report(results: list[dict], notifier: TelegramNotifier = None):
    """보유 포지션 상태를 텔레그램으로 전송."""
    if notifier is None:
        notifier = TelegramNotifier()

    from backend.notifier.telegram import _escape_md

    today = date.today().strftime("%Y\\-%m\\-%d")
    lines = [f"💼 *보유 종목 현황* \\({today}\\)\n"]

    urgent = [r for r in results if r["alert"] != "정상"]
    normal = [r for r in results if r["alert"] == "정상"]

    # 긴급 알림 먼저
    if urgent:
        lines.append("⚠️ *조치 필요*")
        for r in urgent:
            emoji = {"손절": "🔴", "익절": "🟡", "매도신호": "🔔"}.get(r["alert"], "⚠️")
            sign = "+" if r["pnl_pct"] >= 0 else ""
            pnl_str = _escape_md(f"{sign}{r['pnl_pct']:.1f}%")
            pnl_won_str = _escape_md(f"{r['pnl_won']:+,}원")
            price_str = _escape_md(f"{r['current_price']:,}")
            entry_str = _escape_md(f"{r['entry_price']:,}")
            alert_str = _escape_md(r["alert"])
            name_str = _escape_md(r["name"])
            ticker_str = _escape_md(r["ticker"])
            lines.append(
                f"{emoji} *{name_str}* \\({ticker_str}\\) — {alert_str}\n"
                f"  매수가 {entry_str}원 → 현재 {price_str}원\n"
                f"  수익: {pnl_str} \\({pnl_won_str}\\)  RSI: {_escape_md(str(r['rsi']))}"
            )

    # 일반 보유 종목
    if normal:
        lines.append("\n📊 *보유 중 \\(관망\\)*")
        for r in normal:
            sign = "+" if r["pnl_pct"] >= 0 else ""
            pnl_str = _escape_md(f"{sign}{r['pnl_pct']:.1f}%")
            price_str = _escape_md(f"{r['current_price']:,}")
            name_str = _escape_md(r["name"])
            lines.append(f"• {name_str}: {price_str}원 \\({pnl_str}\\)")

    if not results:
        lines.append("보유 종목 없음")

    notifier.send_message("\n".join(lines))


def print_report(results: list[dict]):
    """터미널 출력."""
    today = date.today().strftime("%Y-%m-%d")
    buy_list = [r for r in results if r["signal"] == BUY]
    sell_list = [r for r in results if r["signal"] == SELL]

    print(f"\n{'='*55}")
    print(f"  일일 신호 체크 — {today}")
    print(f"{'='*55}")

    if buy_list:
        print(f"\n🟢 매수 신호 {len(buy_list)}개")
        for r in buy_list:
            print(f"  {r['ticker']} {r['name']:12s} | 현재가: {r['price']:>8,}원 | RSI: {r['rsi']:>5} | BB: {r['bb_position']}")

    if sell_list:
        print(f"\n🔴 매도 신호 {len(sell_list)}개")
        for r in sell_list:
            print(f"  {r['ticker']} {r['name']:12s} | 현재가: {r['price']:>8,}원 | RSI: {r['rsi']:>5} | BB: {r['bb_position']}")

    if not buy_list and not sell_list:
        print("\n  오늘은 신호 없음 (관망)")

    print(f"\n{'='*55}")
