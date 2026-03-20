"""
오늘 시장 데이터를 받아 매수/매도 신호를 체크하고 텔레그램으로 알림 전송.

사용법:
    python -m backend.scheduler.signal_checker
    python tests/daily_signal_check.py
"""

import sys
from datetime import date, timedelta
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
from backend.scheduler.fundamentals import get_fundamental, grade_fundamental
from backend.scheduler.confidence import calc_confidence, score_bar


# 신호 체크에 필요한 최소 봉 수 (ma_long 기본 40 + 여유)
_MIN_ROWS = 80

# 거래량 비율 기준
_VOL_STRONG  = 1.5   # 평균의 1.5배 이상 → 강한 거래량 확인
_VOL_OK      = 0.8   # 평균의 0.8배 이상 → 정상
_VOL_WEAK    = 0.5   # 평균의 0.5배 미만 → 거래량 부족 경고


# ──────────────────────────────────────────
# 시장 흐름 체크
# ──────────────────────────────────────────

def get_market_trend() -> dict:
    """
    코스피 지수 흐름을 분석해 시장 상태를 반환.
    yfinance로 ^KS11 (KOSPI) 데이터를 가져옴.

    Returns:
        {
            "status":      "강세" | "중립" | "약세" | "급락" | "알 수 없음"
            "change_pct":  당일 등락률 (float)
            "kospi":       현재 코스피 지수 (int)
            "ma5":         5일 이평 (int)
            "ma20":        20일 이평 (int)
            "description": 한 줄 요약 (str)
            "caution":     매수 자제 권고 여부 (bool)
        }
    """
    try:
        # KODEX 200 (069500): KOSPI200 추종 ETF — 지수 직접 조회보다 안정적
        df = fetch_ohlcv(ticker="069500", period="3mo", source="auto")

        if df is None or len(df) < 5:
            return _unknown_trend("데이터 부족")

        closes = df["close"].dropna()
        today_close = float(closes.iloc[-1])
        prev_close  = float(closes.iloc[-2])
        change_pct  = round((today_close / prev_close - 1) * 100, 2)
        ma5  = round(float(closes.tail(5).mean()),  0)
        ma20 = round(float(closes.tail(20).mean()), 0)

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
            "kospi":       int(today_close),
            "ma5":         int(ma5),
            "ma20":        int(ma20),
            "description": f"KODEX200 {today_close:,.0f}원 ({change_pct:+.2f}%) — 코스피 대용",
            "caution":     status in ("급락", "약세"),
        }
    except Exception as e:
        return _unknown_trend(str(e))


def _unknown_trend(reason: str) -> dict:
    return {
        "status": "알 수 없음", "change_pct": 0.0,
        "kospi": 0, "ma5": 0, "ma20": 0,
        "description": f"시장 데이터 조회 실패: {reason}",
        "caution": False,
    }


# ──────────────────────────────────────────
# 거래량 판정
# ──────────────────────────────────────────

def _volume_grade(df: pd.DataFrame) -> tuple[float, str]:
    """
    오늘 거래량 / 20일 평균 거래량 비율과 등급 반환.
    Returns: (ratio, grade)  grade: "강함" | "보통" | "약함" | "미확인"
    """
    try:
        vol_col = "volume" if "volume" in df.columns else "거래량"
        today_vol = float(df[vol_col].iloc[-1])
        avg20_vol = float(df[vol_col].tail(21).iloc[:-1].mean())  # 오늘 제외 20일 평균
        if avg20_vol == 0:
            return 1.0, "미확인"
        ratio = round(today_vol / avg20_vol, 2)
        if ratio >= _VOL_STRONG:
            grade = "강함"
        elif ratio >= _VOL_OK:
            grade = "보통"
        else:
            grade = "약함"
        return ratio, grade
    except Exception:
        return 1.0, "미확인"


# ──────────────────────────────────────────
# 신호 체크
# ──────────────────────────────────────────

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
    market_trend: dict = None,
) -> list[dict]:
    """
    주어진 종목 리스트에 대해 오늘 신호를 체크하고 결과 리스트 반환.
    HOLD 종목은 제외. 거래량 비율/등급 포함.
    """
    results = []

    for ticker in tickers:
        try:
            df = fetch_ohlcv(ticker=ticker, period=data_period, source="auto")
            if len(df) < _MIN_ROWS:
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
            code = ticker.split(".")[0]
            fund = get_fundamental(code)
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
                "ticker":      code,
                "name":        get_name(code),
                "signal":      signal,
                "price":       int(last["close"]),
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


def _bb_position(row) -> str:
    close, upper, lower, mid = (
        row["close"], row["bb_upper"], row["bb_lower"], row["bb_middle"]
    )
    if close <= lower:   return "하단 이탈"
    if close >= upper:   return "상단 돌파"
    if close < mid:      return "중간 아래"
    return "중간 위"


# ──────────────────────────────────────────
# 텔레그램 전송
# ──────────────────────────────────────────

def send_signal_report(
    results: list[dict],
    market_trend: dict = None,
    notifier: TelegramNotifier = None,
):
    """신호 결과 + 시장 흐름을 텔레그램으로 전송."""
    if notifier is None:
        notifier = TelegramNotifier()

    from backend.notifier.telegram import _escape_md

    today = date.today().strftime("%Y\\-%m\\-%d")
    lines = [f"📡 *일일 신호 체크* \\({today}\\)"]

    # 시장 흐름 헤더
    if market_trend:
        status_emoji = {
            "강세": "🟢", "중립": "⚪", "약세": "🟡", "급락": "🔴"
        }.get(market_trend["status"], "❓")
        desc = _escape_md(market_trend["description"])
        status = _escape_md(market_trend["status"])
        lines.append(f"\n{status_emoji} *시장: {status}*  {desc}")
        if market_trend["caution"]:
            lines.append("⚠️ 시장 약세 — 매수 신호라도 신중하게 판단하세요")

    # 신뢰도 높은 순 정렬
    buy_list  = sorted([r for r in results if r["signal"] == BUY],
                       key=lambda x: x["confidence"]["score"], reverse=True)
    sell_list = sorted([r for r in results if r["signal"] == SELL],
                       key=lambda x: x["confidence"]["score"], reverse=True)

    def _vol_icon(grade: str) -> str:
        return {"강함": "🔥", "보통": "✅", "약함": "⚠️", "미확인": "❓"}.get(grade, "")

    def _naver_url(ticker: str) -> str:
        return f"https://finance.naver.com/item/main.naver?code={ticker.zfill(6)}"

    def _signal_lines(r: dict) -> str:
        vi    = _vol_icon(r["vol_grade"])
        c     = r["confidence"]
        bar   = _escape_md(score_bar(c["score"], width=8))
        score = _escape_md(str(c["score"]))
        price_str = _escape_md(f"{r['price']:,}")
        vol_str   = _escape_md(r["vol_grade"])
        vol_ratio = _escape_md(str(r["vol_ratio"]))
        f_desc    = _escape_md(r["f_desc"])
        name_link = f"[{_escape_md(r['name'])}]({_naver_url(r['ticker'])})"
        return (
            f"• {name_link} \\({_escape_md(r['ticker'])}\\)  "
            f"{c['icon']} *{score}점* `{bar}`\n"
            f"  현재가: {price_str}원  RSI: {_escape_md(str(r['rsi']))}  BB: {_escape_md(r['bb_position'])}\n"
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
# 보유 포지션 모니터링
# ──────────────────────────────────────────

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
    """보유 중인 포지션을 조회해 현재 상태(수익률, 신호, 손절/익절)를 반환."""
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
            entry_price   = pos["entry_price"]
            shares        = pos["shares"]
            pnl_pct = round((current_price / entry_price - 1) * 100, 2)
            pnl_won = int((current_price - entry_price) * shares)

            vol_ratio, vol_grade = _volume_grade(df)

            alert = "정상"
            if current_price <= pos["stop_loss"]:
                alert = "손절"
            elif current_price >= pos["take_profit"]:
                alert = "익절"
            elif last["signal"] == SELL:
                alert = "매도신호"

            results.append({
                "position_id":  pos["id"],
                "ticker":       ticker,
                "name":         pos["name"] or get_name(ticker),
                "entry_price":  int(entry_price),
                "shares":       shares,
                "entry_date":   pos["entry_date"],
                "current_price": current_price,
                "pnl_pct":      pnl_pct,
                "pnl_won":      pnl_won,
                "signal":       last["signal"],
                "rsi":          round(float(last["rsi"]), 1),
                "bb_position":  _bb_position(last),
                "vol_ratio":    vol_ratio,
                "vol_grade":    vol_grade,
                "stop_loss":    int(pos["stop_loss"]),
                "take_profit":  int(pos["take_profit"]),
                "alert":        alert,
                "date":         df.index[-1].strftime("%Y-%m-%d"),
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

    def _pos_naver_url(ticker: str) -> str:
        return f"https://finance.naver.com/item/main.naver?code={ticker.zfill(6)}"

    if urgent:
        lines.append("⚠️ *조치 필요*")
        for r in urgent:
            emoji = {"손절": "🔴", "익절": "🟡", "매도신호": "🔔"}.get(r["alert"], "⚠️")
            sign = "+" if r["pnl_pct"] >= 0 else ""
            vi   = {"강함": "🔥", "보통": "✅", "약함": "⚠️"}.get(r["vol_grade"], "❓")
            pnl_str     = _escape_md(f"{sign}{r['pnl_pct']:.1f}%")
            pnl_won_str = _escape_md(f"{r['pnl_won']:+,}원")
            entry_str   = _escape_md(str(r["entry_price"]))
            cur_str     = _escape_md(str(r["current_price"]))
            name_link   = f"[{_escape_md(r['name'])}]({_pos_naver_url(r['ticker'])})"
            lines.append(
                f"{emoji} *{name_link}* \\({_escape_md(r['ticker'])}\\) "
                f"— {_escape_md(r['alert'])}\n"
                f"  {entry_str}원 → {cur_str}원  "
                f"{pnl_str} \\({pnl_won_str}\\)\n"
                f"  RSI: {_escape_md(str(r['rsi']))}  "
                f"거래량: {vi} {_escape_md(r['vol_grade'])}"
            )

    if normal:
        lines.append("\n📊 *보유 중 \\(관망\\)*")
        for r in normal:
            sign = "+" if r["pnl_pct"] >= 0 else ""
            pnl_str   = _escape_md(f"{sign}{r['pnl_pct']:.1f}%")
            cur_str   = _escape_md(str(r["current_price"]))
            name_link = f"[{_escape_md(r['name'])}]({_pos_naver_url(r['ticker'])})"
            lines.append(
                f"• {name_link}: {cur_str}원 \\({pnl_str}\\)"
            )

    if not results:
        lines.append("보유 종목 없음")

    notifier.send_message("\n".join(lines))


# ──────────────────────────────────────────
# 터미널 출력
# ──────────────────────────────────────────

def print_market_trend(trend: dict):
    status_emoji = {"강세": "🟢", "중립": "⚪", "약세": "🟡", "급락": "🔴"}.get(trend["status"], "❓")
    print(f"\n{status_emoji} 시장 흐름: {trend['status']}  |  {trend['description']}")
    if trend["caution"]:
        print("  ⚠️  시장 약세 — 매수 신호라도 신중하게 판단하세요")


def print_report(results: list[dict]):
    """터미널 출력."""
    today = date.today().strftime("%Y-%m-%d")
    buy_list  = [r for r in results if r["signal"] == BUY]
    sell_list = [r for r in results if r["signal"] == SELL]

    vol_icon = {"강함": "🔥", "보통": "✅", "약함": "⚠️", "미확인": "❓"}

    print(f"\n{'='*65}")
    print(f"  일일 신호 체크 — {today}")
    print(f"{'='*65}")

    def _print_row(r: dict):
        vi = vol_icon.get(r["vol_grade"], "")
        c  = r["confidence"]
        bar = score_bar(c["score"], width=8)
        print(f"  {r['ticker']} {r['name']:12s} | "
              f"신뢰도: {c['icon']}{c['score']:>3}점 [{bar}] | "
              f"현재가: {r['price']:>8,}원 | RSI: {r['rsi']:>5} | "
              f"거래량: {vi}{r['vol_grade']}({r['vol_ratio']}배) | "
              f"재무: {r['f_icon']} {r['f_desc']}")

    if buy_list:
        buy_sorted = sorted(buy_list, key=lambda x: x["confidence"]["score"], reverse=True)
        print(f"\n🟢 매수 신호 {len(buy_list)}개")
        for r in buy_sorted:
            _print_row(r)

    if sell_list:
        sell_sorted = sorted(sell_list, key=lambda x: x["confidence"]["score"], reverse=True)
        print(f"\n🔴 매도 신호 {len(sell_list)}개")
        for r in sell_sorted:
            _print_row(r)

    if not buy_list and not sell_list:
        print("\n  오늘은 신호 없음 (관망)")

    print(f"\n{'='*65}")
