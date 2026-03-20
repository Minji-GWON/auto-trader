"""
미국 주식 신호 체크 + 텔레그램 알림.

사용법:
    python tests/daily_signal_check_us.py
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
from backend.stocks_us import get_us_name
from backend.scheduler.fundamentals_us import get_fundamental_us
from backend.scheduler.fundamentals import grade_fundamental     # 동일한 등급 로직 재사용
from backend.scheduler.confidence import calc_confidence, score_bar
from backend.scheduler.signal_checker import _volume_grade, _bb_position  # 공통 유틸 재사용


_MIN_ROWS = 80


# ──────────────────────────────────────────
# 시장 흐름 (SPY 기준)
# ──────────────────────────────────────────

def get_market_trend_us() -> dict:
    """
    SPY ETF로 S&P500 흐름 분석.

    Returns:
        {
            "status":      "강세" | "중립" | "약세" | "급락" | "알 수 없음"
            "change_pct":  당일 등락률 (float)
            "description": 한 줄 요약 (str)
            "caution":     매수 자제 권고 여부 (bool)
        }
    """
    try:
        df = fetch_ohlcv(ticker="SPY", period="3mo", source="yfinance")

        if df is None or len(df) < 5:
            return _unknown_trend("데이터 부족")

        closes = df["close"].dropna()
        today_close = float(closes.iloc[-1])
        prev_close  = float(closes.iloc[-2])
        change_pct  = round((today_close / prev_close - 1) * 100, 2)
        ma5  = round(float(closes.tail(5).mean()),  2)
        ma20 = round(float(closes.tail(20).mean()), 2)

        if change_pct <= -2.5:
            status = "급락"
        elif change_pct <= -1.0 or today_close < ma20:
            status = "약세"
        elif change_pct >= 1.0 and today_close > ma5:
            status = "강세"
        else:
            status = "중립"

        return {
            "status":      status,
            "change_pct":  change_pct,
            "spy":         round(today_close, 2),
            "ma5":         ma5,
            "ma20":        ma20,
            "description": f"SPY ${today_close:,.2f} ({change_pct:+.2f}%) — S&P500 대용",
            "caution":     status in ("급락", "약세"),
        }
    except Exception as e:
        return _unknown_trend(str(e))


def _unknown_trend(reason: str) -> dict:
    return {
        "status": "알 수 없음", "change_pct": 0.0,
        "spy": 0, "ma5": 0, "ma20": 0,
        "description": f"시장 데이터 조회 실패: {reason}",
        "caution": False,
    }


# ──────────────────────────────────────────
# 신호 체크
# ──────────────────────────────────────────

def check_signals_today_us(
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
    market_trend: dict = None,
) -> list[dict]:
    """미국 종목 신호 체크. 반환 형식은 한국 버전과 동일."""
    results = []

    for ticker in tickers:
        try:
            df = fetch_ohlcv(ticker=ticker, period=data_period, source="yfinance")
            if df is None or len(df) < _MIN_ROWS:
                continue

            df = add_all_indicators(
                df, rsi_period=rsi_period, bb_period=bb_period,
                bb_std_dev=bb_std_dev, ma_short=ma_short, ma_long=ma_long,
            )
            df = generate_signals(
                df, rsi_oversold=rsi_oversold,
                rsi_overbought=rsi_overbought, swing_mode=swing_mode,
            )
            df = df.dropna()
            if df.empty:
                continue

            last = df.iloc[-1]
            signal = last["signal"]
            if signal == "HOLD":
                continue

            vol_ratio, vol_grade = _volume_grade(df)
            fund = get_fundamental_us(ticker)
            f_grade, f_icon, f_desc = grade_fundamental(fund)
            mkt_status = (market_trend or {}).get("status", "알 수 없음")
            confidence = calc_confidence(
                signal=signal,
                rsi=round(float(last["rsi"]), 1),
                rsi_oversold=rsi_oversold,
                rsi_overbought=rsi_overbought,
                vol_grade=vol_grade,
                market_status=mkt_status,
                f_grade=f_grade,
            )
            results.append({
                "ticker":      ticker,
                "name":        get_us_name(ticker),
                "signal":      signal,
                "price":       round(float(last["close"]), 2),
                "rsi":         round(float(last["rsi"]), 1),
                "bb_position": _bb_position(last),
                "vol_ratio":   vol_ratio,
                "vol_grade":   vol_grade,
                "fund":        fund,
                "f_grade":     f_grade,
                "f_icon":      f_icon,
                "f_desc":      f_desc,
                "confidence":  confidence,
                "date":        df.index[-1].strftime("%Y-%m-%d"),
            })
        except Exception:
            pass

    return results


# ──────────────────────────────────────────
# 텔레그램 전송
# ──────────────────────────────────────────

def send_signal_report_us(
    results: list[dict],
    market_trend: dict = None,
    notifier: TelegramNotifier = None,
):
    """미국 주식 신호 결과를 텔레그램으로 전송."""
    if notifier is None:
        notifier = TelegramNotifier()

    from backend.notifier.telegram import _escape_md

    today = date.today().strftime("%Y\\-%m\\-%d")
    lines = [f"🇺🇸 *미국 주식 신호 체크* \\({today}\\)"]

    if market_trend:
        status_emoji = {
            "강세": "🟢", "중립": "⚪", "약세": "🟡", "급락": "🔴"
        }.get(market_trend["status"], "❓")
        desc   = _escape_md(market_trend["description"])
        status = _escape_md(market_trend["status"])
        lines.append(f"\n{status_emoji} *시장: {status}*  {desc}")
        if market_trend["caution"]:
            lines.append("⚠️ 시장 약세 — 매수 신호라도 신중하게 판단하세요")

    buy_list  = sorted([r for r in results if r["signal"] == BUY],
                       key=lambda x: x["confidence"]["score"], reverse=True)
    sell_list = sorted([r for r in results if r["signal"] == SELL],
                       key=lambda x: x["confidence"]["score"], reverse=True)

    def _vol_icon(grade: str) -> str:
        return {"강함": "🔥", "보통": "✅", "약함": "⚠️", "미확인": "❓"}.get(grade, "")

    def _yahoo_url(ticker: str) -> str:
        return f"https://finance.yahoo.com/quote/{ticker}"

    def _signal_lines(r: dict) -> str:
        vi    = _vol_icon(r["vol_grade"])
        c     = r["confidence"]
        bar   = _escape_md(score_bar(c["score"], width=8))
        score = _escape_md(str(c["score"]))
        price_str = _escape_md(f"${r['price']:,.2f}")
        vol_str   = _escape_md(r["vol_grade"])
        vol_ratio = _escape_md(str(r["vol_ratio"]))
        f_desc    = _escape_md(r["f_desc"])
        name_link = f"[{_escape_md(r['name'])}]({_yahoo_url(r['ticker'])})"
        return (
            f"• {name_link} \\({_escape_md(r['ticker'])}\\)  "
            f"{c['icon']} *{score}점* `{bar}`\n"
            f"  현재가: {price_str}  RSI: {_escape_md(str(r['rsi']))}  BB: {_escape_md(r['bb_position'])}\n"
            f"  거래량: {vi} {vol_str} \\({vol_ratio}배\\)  재무: {r['f_icon']} {f_desc}"
        )

    if buy_list:
        lines.append(f"\n🟢 *매수 신호 {len(buy_list)}개*")
        for r in buy_list:
            lines.append(_signal_lines(r))

    if sell_list:
        lines.append(f"\n🔴 *매도 신호 {len(sell_list)}개*")
        for r in sell_list:
            lines.append(_signal_lines(r))

    if not buy_list and not sell_list:
        lines.append("\n✅ 오늘은 매수/매도 신호 없음 \\(관망\\)")

    notifier.send_message("\n".join(lines))


# ──────────────────────────────────────────
# 터미널 출력
# ──────────────────────────────────────────

def print_market_trend_us(trend: dict):
    status_emoji = {"강세": "🟢", "중립": "⚪", "약세": "🟡", "급락": "🔴"}.get(trend["status"], "❓")
    print(f"\n{status_emoji} 시장 흐름: {trend['status']}  |  {trend['description']}")
    if trend["caution"]:
        print("  ⚠️  시장 약세 — 매수 신호라도 신중하게 판단하세요")


def print_report_us(results: list[dict]):
    today = date.today().strftime("%Y-%m-%d")
    buy_list  = [r for r in results if r["signal"] == BUY]
    sell_list = [r for r in results if r["signal"] == SELL]
    vol_icon  = {"강함": "🔥", "보통": "✅", "약함": "⚠️", "미확인": "❓"}

    print(f"\n{'='*70}")
    print(f"  미국 주식 신호 체크 — {today}")
    print(f"{'='*70}")

    def _print_row(r: dict):
        vi  = vol_icon.get(r["vol_grade"], "")
        c   = r["confidence"]
        bar = score_bar(c["score"], width=8)
        print(f"  {r['ticker']:<6} {r['name']:18s} | "
              f"신뢰도: {c['icon']}{c['score']:>3}점 [{bar}] | "
              f"현재가: ${r['price']:>8,.2f} | RSI: {r['rsi']:>5} | "
              f"거래량: {vi}{r['vol_grade']}({r['vol_ratio']}배) | "
              f"재무: {r['f_icon']} {r['f_desc']}")

    if buy_list:
        print(f"\n🟢 매수 신호 {len(buy_list)}개")
        for r in sorted(buy_list, key=lambda x: x["confidence"]["score"], reverse=True):
            _print_row(r)

    if sell_list:
        print(f"\n🔴 매도 신호 {len(sell_list)}개")
        for r in sorted(sell_list, key=lambda x: x["confidence"]["score"], reverse=True):
            _print_row(r)

    if not buy_list and not sell_list:
        print("\n  오늘은 신호 없음 (관망)")

    print(f"\n{'='*70}")
