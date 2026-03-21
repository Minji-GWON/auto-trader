"""
텔레그램 차트 분석 봇.

채널에서 명령을 5분마다 폴링해서 차트 이미지 + 뉴스 요약 전송.

지원 명령:
    /분석 AAPL        — 미국 주식 차트 + 기술분석 + 뉴스
    /분석 005930      — 한국 주식 차트 + 기술분석 + 뉴스
"""

import json
import os
import sys
import io
import requests
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.dates as mdates
from pathlib import Path
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.data_fetcher.fetcher import fetch_ohlcv
from backend.indicators.calculator import add_all_indicators
from backend.strategy.signal import generate_signals, BUY, SELL
from backend.scheduler.finnhub_targets import get_analyst_summary

OFFSET_FILE     = ROOT / ".chart_bot_offset.txt"
TICKER_SEEN_FILE = ROOT / ".chart_bot_ticker_seen.json"
NEWS_SEEN_FILE   = ROOT / ".chart_bot_news_seen.json"
_TICKER_COOLDOWN_MINUTES = 10
_NEWS_MAX_ENTRIES = 200  # 오래된 기사 URL 정리 기준


# ──────────────────────────────────────────
# 티커 쿨다운 (같은 종목 10분 내 재요청 무시)
# ──────────────────────────────────────────

def _ticker_seen_load() -> dict:
    try:
        return json.loads(TICKER_SEEN_FILE.read_text())
    except Exception:
        return {}

def _ticker_seen_save(data: dict):
    TICKER_SEEN_FILE.write_text(json.dumps(data))

def _ticker_is_cooldown(ticker: str) -> bool:
    data = _ticker_seen_load()
    ts = data.get(ticker)
    if not ts:
        return False
    return (datetime.now(timezone.utc) - datetime.fromisoformat(ts)) \
           < timedelta(minutes=_TICKER_COOLDOWN_MINUTES)

def _ticker_mark(ticker: str):
    data = _ticker_seen_load()
    data[ticker] = datetime.now(timezone.utc).isoformat()
    _ticker_seen_save(data)


# ──────────────────────────────────────────
# 뉴스 중복 방지 (이미 보낸 URL 필터링)
# ──────────────────────────────────────────

def _news_seen_load() -> list:
    try:
        return json.loads(NEWS_SEEN_FILE.read_text())
    except Exception:
        return []

def _news_seen_save(urls: list):
    NEWS_SEEN_FILE.write_text(json.dumps(urls[-_NEWS_MAX_ENTRIES:]))

def filter_new_news(articles: list[dict]) -> list[dict]:
    seen = set(_news_seen_load())
    return [a for a in articles if a.get("url", "") not in seen]

def mark_news_seen(articles: list[dict]):
    seen = _news_seen_load()
    for a in articles:
        url = a.get("url", "")
        if url and url not in seen:
            seen.append(url)
    _news_seen_save(seen)


# ──────────────────────────────────────────
# Telegram 유틸
# ──────────────────────────────────────────

def _bot_base(token: str) -> str:
    return f"https://api.telegram.org/bot{token}"


def get_pending_commands(token: str, channel_id: int) -> list[dict]:
    """미처리 /분석 명령어 수집 (getUpdates 폴링)."""
    offset = _load_offset()
    params = {"timeout": 0, "allowed_updates": ["channel_post"]}
    if offset:
        params["offset"] = offset

    try:
        r = requests.get(f"{_bot_base(token)}/getUpdates", params=params, timeout=10)
        if not r.ok:
            return []
        updates = r.json().get("result", [])
    except Exception:
        return []

    commands = []
    max_id = offset or 0

    for upd in updates:
        max_id = max(max_id, upd["update_id"])
        post = upd.get("channel_post", {})
        if post.get("chat", {}).get("id") != channel_id:
            continue
        text = (post.get("text") or "").strip()
        if text.startswith("/분석"):
            parts = text.split(maxsplit=1)
            if len(parts) == 2:
                commands.append({"ticker": parts[1].upper().strip()})

    if updates:
        _save_offset(max_id + 1)

    return commands


def _load_offset() -> int:
    try:
        return int(OFFSET_FILE.read_text().strip())
    except Exception:
        return 0


def _save_offset(offset: int) -> None:
    OFFSET_FILE.write_text(str(offset))


def send_photo(token: str, chat_id: int, buf: io.BytesIO, caption: str) -> bool:
    """차트 이미지(메모리 버퍼) + 캡션 전송."""
    try:
        buf.seek(0)
        r = requests.post(
            f"{_bot_base(token)}/sendPhoto",
            data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
            files={"photo": ("chart.png", buf, "image/png")},
            timeout=30,
        )
        return r.ok
    except Exception:
        return False


def send_message(token: str, chat_id: int, text: str) -> bool:
    """텍스트 메시지 전송."""
    try:
        r = requests.post(
            f"{_bot_base(token)}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        return r.ok
    except Exception:
        return False


# ──────────────────────────────────────────
# 차트 생성
# ──────────────────────────────────────────

def generate_chart(ticker: str) -> tuple[io.BytesIO | None, dict | None]:
    """
    캔들차트 + BB + MA + RSI + 매수/매도 마커 이미지 생성.
    Returns: (PNG 버퍼, 분석 결과 dict) 또는 (None, None)
    """
    is_kr = ticker.isdigit()
    source = "auto" if is_kr else "yfinance"
    ticker_yf = f"{ticker}.KS" if is_kr else ticker

    try:
        df = fetch_ohlcv(ticker=ticker_yf if is_kr else ticker,
                         period="3mo", source=source)
        if df is None or len(df) < 30:
            return None, None

        df = add_all_indicators(df, rsi_period=14, bb_period=20,
                                bb_std_dev=1.5, ma_short=20, ma_long=40)
        df = generate_signals(df, rsi_oversold=35, rsi_overbought=65)
        df = df.dropna().tail(60)

        last = df.iloc[-1]
        rsi_val   = round(float(last["rsi"]), 1)
        signal    = last["signal"]
        price     = float(last["close"])
        bb_pos    = _bb_label(last)
        signal_kr = {"BUY": "🟢 매수", "SELL": "🔴 매도"}.get(signal, "⚪ 관망")

        # ── 다크 테마 차트
        BG = "#1a1a2e"
        fig = plt.figure(figsize=(11, 7), facecolor=BG)
        gs  = gridspec.GridSpec(3, 1, height_ratios=[3, 1, 1], hspace=0.06)
        ax1 = fig.add_subplot(gs[0])
        ax2 = fig.add_subplot(gs[1], sharex=ax1)
        ax3 = fig.add_subplot(gs[2], sharex=ax1)

        for ax in (ax1, ax2, ax3):
            ax.set_facecolor(BG)
            ax.tick_params(colors="#888899", labelsize=7)
            for sp in ax.spines.values():
                sp.set_color("#333355")

        dates = df.index
        up   = df["close"] >= df["open"]
        dn   = ~up
        W    = 0.6

        # 캔들스틱
        ax1.bar(dates[up], df["close"][up] - df["open"][up],
                bottom=df["open"][up], color="#26a69a", width=W)
        ax1.bar(dates[dn], df["open"][dn] - df["close"][dn],
                bottom=df["close"][dn], color="#ef5350", width=W)
        ax1.vlines(dates, df["low"], df["high"], colors=["#26a69a" if u else "#ef5350" for u in up],
                   linewidth=0.7)

        # 볼린저 밴드
        ax1.plot(dates, df["bb_upper"],  color="#5588ff", lw=0.8, ls="--", alpha=0.7)
        ax1.plot(dates, df["bb_middle"], color="#888899", lw=0.7, alpha=0.5)
        ax1.plot(dates, df["bb_lower"],  color="#5588ff", lw=0.8, ls="--", alpha=0.7)
        ax1.fill_between(dates, df["bb_upper"], df["bb_lower"],
                         alpha=0.04, color="#5588ff")

        # MA
        ax1.plot(dates, df["ma_short"], color="#ffaa00", lw=1.1, label="MA20")
        ax1.plot(dates, df["ma_long"],  color="#ff6688", lw=1.1, label="MA40")
        ax1.legend(loc="upper left", fontsize=7,
                   facecolor=BG, labelcolor="#aaaaaa", framealpha=0.5)

        # 매수/매도 마커
        buy_idx  = df[df["signal"] == BUY].index
        sell_idx = df[df["signal"] == SELL].index
        if len(buy_idx):
            ax1.scatter(buy_idx,  df.loc[buy_idx,  "low"]  * 0.997,
                        marker="^", color="#26a69a", s=70, zorder=6)
        if len(sell_idx):
            ax1.scatter(sell_idx, df.loc[sell_idx, "high"] * 1.003,
                        marker="v", color="#ef5350", s=70, zorder=6)

        # 거래량
        vol_col = "volume" if "volume" in df.columns else "거래량"
        if vol_col in df.columns:
            vcols = ["#26a69a" if u else "#ef5350" for u in up]
            ax2.bar(dates, df[vol_col], color=vcols, alpha=0.7, width=W)
        ax2.set_ylabel("Vol", color="#888899", fontsize=7)
        ax2.yaxis.set_major_formatter(
            plt.FuncFormatter(lambda x, _: f"{x/1e6:.0f}M" if x >= 1e6 else f"{x:.0f}"))

        # RSI
        ax3.plot(dates, df["rsi"], color="#bb88ff", lw=1.2)
        ax3.axhline(65, color="#ef5350", lw=0.6, ls="--", alpha=0.5)
        ax3.axhline(35, color="#26a69a", lw=0.6, ls="--", alpha=0.5)
        ax3.fill_between(dates, df["rsi"], 35,
                         where=(df["rsi"] < 35), alpha=0.2, color="#26a69a")
        ax3.fill_between(dates, df["rsi"], 65,
                         where=(df["rsi"] > 65), alpha=0.2, color="#ef5350")
        ax3.set_ylim(0, 100)
        ax3.set_yticks([20, 35, 50, 65, 80])
        ax3.set_ylabel("RSI", color="#888899", fontsize=7)

        ax3.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
        ax3.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
        plt.setp(ax1.get_xticklabels(), visible=False)
        plt.setp(ax2.get_xticklabels(), visible=False)
        fig.autofmt_xdate(rotation=0, ha="center")

        price_str = f"{int(price):,}원" if is_kr else f"${price:,.2f}"
        fig.suptitle(f"{ticker}  {price_str}  RSI {rsi_val}  {signal}",
                     color="white", fontsize=11, y=0.99)

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=130,
                    bbox_inches="tight", facecolor=BG)
        plt.close(fig)
        buf.seek(0)

        return buf, {
            "price":      price,
            "price_str":  price_str,
            "rsi":        rsi_val,
            "bb_pos":     bb_pos,
            "signal":     signal,
            "signal_kr":  signal_kr,
            "is_kr":      is_kr,
        }

    except Exception as e:
        print(f"[chart] {ticker} 오류: {e}")
        return None, None


def _bb_label(row) -> str:
    c, u, l, m = row["close"], row["bb_upper"], row["bb_lower"], row["bb_middle"]
    if c <= l:  return "BB 하단 이탈"
    if c >= u:  return "BB 상단 돌파"
    if c < m:   return "BB 중간 아래"
    return "BB 중간 위"


# ──────────────────────────────────────────
# 뉴스 수집 + 요약
# ──────────────────────────────────────────

def fetch_company_news(ticker: str, finnhub_key: str, n: int = 3) -> list[dict]:
    """Finnhub company-news 엔드포인트로 최신 뉴스 수집 (미국 주식)."""
    if not finnhub_key:
        return []
    try:
        to_   = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        from_ = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        r = requests.get(
            "https://finnhub.io/api/v1/company-news",
            params={"symbol": ticker, "from": from_, "to": to_, "token": finnhub_key},
            timeout=5,
        )
        if not r.ok:
            return []
        articles = r.json()[:n * 3]
        seen, results = set(), []
        for a in articles:
            title = (a.get("headline") or "").strip()
            if not title or title in seen:
                continue
            seen.add(title)
            results.append({
                "title":   title,
                "summary": (a.get("summary") or "").strip(),
                "source":  a.get("source", ""),
                "url":     a.get("url", ""),
            })
            if len(results) >= n:
                break
        return results
    except Exception:
        return []


def fetch_kr_news(company_name: str, news_api_key: str, n: int = 3) -> list[dict]:
    """NewsAPI로 한국 종목 관련 영문 뉴스 수집."""
    if not news_api_key:
        return []
    try:
        r = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": company_name,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": n * 2,
                "apiKey": news_api_key,
            },
            timeout=5,
        )
        if not r.ok:
            return []
        results = []
        for a in r.json().get("articles", []):
            title = (a.get("title") or "").split(" - ")[0].strip()
            if not title or "[Removed]" in title:
                continue
            results.append({
                "title":  title,
                "source": (a.get("source") or {}).get("name", ""),
                "url":    a.get("url", ""),
            })
            if len(results) >= n:
                break
        return results
    except Exception:
        return []


def summarize_to_korean(articles: list[dict], api_key: str) -> list[dict]:
    """
    Claude API로 뉴스 제목 + 본문 요약을 한국어로 번역.
    Returns: [{"title_kr": str, "summary_kr": str}, ...]
    """
    fallback = [{"title_kr": a["title"], "summary_kr": a.get("summary", "")}
                for a in articles]
    if not articles or not api_key:
        return fallback
    try:
        import anthropic
        items = []
        for i, a in enumerate(articles):
            body = f"제목: {a['title']}"
            if a.get("summary"):
                body += f"\n내용: {a['summary']}"
            items.append(f"[{i+1}]\n{body}")
        prompt = (
            "다음 영어 뉴스를 각각 한국어로 번역하세요.\n"
            "출력 형식: 번호, 제목(한 줄), 내용(2~3줄) 순서로, 다른 설명 없이.\n"
            "예시:\n[1]\n제목: 엔비디아 실적 급등\n내용: 엔비디아가 예상을 웃도는 실적을 발표했다. AI 수요 증가가 주요 원인이다.\n\n"
            + "\n\n".join(items)
        )
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        return _parse_kr_response(resp.content[0].text, len(articles), fallback)
    except Exception:
        return fallback


def _parse_kr_response(text: str, n: int, fallback: list) -> list:
    """Claude 응답에서 [번호] 제목/내용 파싱."""
    import re
    results = []
    blocks = re.split(r"\[(\d+)\]", text.strip())
    # blocks: ['', '1', '...content...', '2', '...content...', ...]
    pairs = [(blocks[i], blocks[i+1]) for i in range(1, len(blocks)-1, 2)]
    for _, content in pairs:
        lines = [l.strip() for l in content.strip().splitlines() if l.strip()]
        title_kr = ""
        summary_lines = []
        for line in lines:
            if line.startswith("제목:"):
                title_kr = line[3:].strip()
            elif line.startswith("내용:"):
                summary_lines.append(line[3:].strip())
            elif summary_lines:
                summary_lines.append(line)
        results.append({
            "title_kr":   title_kr,
            "summary_kr": " ".join(summary_lines),
        })
    return results if len(results) == n else fallback


# ──────────────────────────────────────────
# 메시지 포맷
# ──────────────────────────────────────────

def build_caption(ticker: str, analysis: dict, analyst: dict | None) -> str:
    """차트 이미지 캡션 — 기술분석 + 애널리스트 (HTML)."""
    today = datetime.now().strftime("%Y-%m-%d")
    a = analysis
    lines = [
        f"<b>📊 {ticker} 분석</b>  {today}",
        f"\n<b>현재가</b> {a['price_str']}  <b>RSI</b> {a['rsi']}  <b>{a['bb_pos']}</b>",
        f"<b>신호</b> {a['signal_kr']}",
    ]
    if analyst and not analyst.get("error"):
        if analyst.get("target_mean"):
            upside = analyst.get("upside_pct")
            upside_str = f" ({upside:+.1f}%)" if upside is not None else ""
            lines.append(
                f"🎯 목표주가 ${analyst['target_mean']:,.2f}{upside_str}  "
                f"분석가 {analyst['analysts']}명  {analyst['consensus']}"
            )
        elif analyst.get("consensus") not in ("없음", ""):
            sb = analyst.get("strong_buy", 0) + analyst.get("buy", 0)
            h  = analyst.get("hold", 0)
            s  = analyst.get("sell", 0) + analyst.get("strong_sell", 0)
            lines.append(f"🎯 {analyst['consensus']}  매수 {sb} · 중립 {h} · 매도 {s}")
    return "\n".join(lines)


def build_news_message(ticker: str, news: list[dict], summaries: list[dict]) -> str:
    """뉴스 본문 번역 별도 메시지 (HTML)."""
    lines = [f"<b>📰 {ticker} 관련 뉴스</b>"]
    for article, kr in zip(news, summaries):
        url        = article.get("url", "")
        src        = article.get("source", "")
        src_tag    = f" <i>({src})</i>" if src else ""
        title_kr   = kr.get("title_kr")   or article["title"]
        summary_kr = kr.get("summary_kr") or ""
        if url:
            lines.append(f"\n• <a href=\"{url}\"><b>{title_kr}</b></a>{src_tag}")
        else:
            lines.append(f"\n• <b>{title_kr}</b>{src_tag}")
        if summary_kr:
            lines.append(f"  {summary_kr}")
    return "\n".join(lines)


# ──────────────────────────────────────────
# 메인 실행
# ──────────────────────────────────────────

def run(token: str, channel_id: int,
        finnhub_key: str = "", news_api_key: str = "", anthropic_key: str = "") -> None:
    """채널의 미처리 /분석 명령을 처리하고 결과 전송."""
    commands = get_pending_commands(token, channel_id)
    if not commands:
        print("새 명령 없음.")
        return

    # 같은 티커 중복 요청 → 마지막 1개만 처리
    seen_tickers: dict[str, dict] = {}
    for cmd in commands:
        seen_tickers[cmd["ticker"]] = cmd
    commands = list(seen_tickers.values())

    for cmd in commands:
        ticker = cmd["ticker"]

        # 10분 내 동일 티커 재요청 → 스킵
        if _ticker_is_cooldown(ticker):
            print(f"[{ticker}] 쿨다운 중 (10분 내 이미 처리됨), 스킵")
            continue

        print(f"[분석] {ticker} ...")

        # 1) 차트 생성
        buf, analysis = generate_chart(ticker)
        if buf is None:
            send_message(token, channel_id,
                         f"⚠️ <b>{ticker}</b> 데이터를 찾을 수 없습니다.\n"
                         f"티커를 확인해주세요. (예: AAPL, 005930)")
            continue

        # 2) 애널리스트 목표주가 (미국만)
        analyst = None
        if not analysis["is_kr"]:
            try:
                analyst = get_analyst_summary(ticker, analysis["price"], finnhub_key)
            except Exception:
                pass

        # 3) 뉴스 수집 + 중복 필터 + 번역
        if analysis["is_kr"]:
            try:
                from backend.stocks import get_name
                company = get_name(ticker)
            except Exception:
                company = ticker
            raw_news = fetch_kr_news(company, news_api_key, n=5)
        else:
            raw_news = fetch_company_news(ticker, finnhub_key, n=5)

        news = filter_new_news(raw_news)
        if not news:
            news = raw_news[:3]  # 모두 중복이면 최신 3개 표시

        summaries = summarize_to_korean(news[:3], anthropic_key) if news else []

        # 4) 전송 — 차트(캡션) + 뉴스(별도 메시지)
        caption = build_caption(ticker, analysis, analyst)
        ok = send_photo(token, channel_id, buf, caption)
        print(f"  → 차트 {'전송 완료' if ok else '전송 실패'}")

        if news:
            news_msg = build_news_message(ticker, news[:3], summaries)
            ok2 = send_message(token, channel_id, news_msg)
            print(f"  → 뉴스 {'전송 완료' if ok2 else '전송 실패'}")

        if ok:
            _ticker_mark(ticker)       # 쿨다운 시작
            mark_news_seen(raw_news)   # 이번에 수집한 기사 URL 저장
