from pathlib import Path
import sys

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from backend.data_fetcher.fetcher import get_default_csv_path
from backend.indicators.calculator import add_all_indicators
from backend.strategy.signal import generate_signals, BUY, SELL
from backend.stocks import get_name as stocks_get_name, get_market, ALL_STOCKS
from backend.stocks_us import get_us_name, ALL_US_STOCKS
from backend.database import init_db, add_position, get_open_positions, close_position, update_position, delete_position, get_position_history
from tests.backtest import run_backtest


def _is_us(ticker: str) -> bool:
    """티커가 미국 주식인지 판단 (알파벳 → US, 숫자 → KR)."""
    return not ticker.split(".")[0].replace("-", "").isdigit()

init_db()  # positions 테이블 보장

COMMISSION_RATE = 0.00015
SLIPPAGE_RATE = 0.001

st.set_page_config(
    page_title="자동매매 대시보드",
    page_icon="📈",
    layout="wide",
)


# ──────────────────────────────────────────
# 공통 유틸
# ──────────────────────────────────────────

@st.cache_data
def get_ticker_name(ticker: str) -> str:
    """종목명 조회: US 마스터 → KR 마스터 → pykrx 폴백."""
    code = ticker.split(".")[0]
    if _is_us(ticker):
        name = get_us_name(code)
        return name if name != code else ticker
    # 한국 마스터
    name = stocks_get_name(code)
    if name != ticker and name != code:
        return name
    # pykrx 폴백
    try:
        from pykrx import stock
        name = stock.get_market_ticker_name(code)
        return name if name else ticker
    except Exception:
        return ticker


@st.cache_data
def get_stock_volatility(ticker: str) -> float:
    """CSV 데이터 기반 연환산 변동성(%) 계산. 실패 시 0."""
    try:
        csv_path = get_default_csv_path(ticker)
        df = pd.read_csv(csv_path)
        returns = df["close"].pct_change().dropna()
        return round(returns.std() * (252 ** 0.5) * 100, 1)
    except Exception:
        return 0.0


def list_csv_tickers() -> list[str]:
    data_dir = ROOT_DIR / "data"
    if not data_dir.exists():
        return []
    tickers = []
    for path in sorted(data_dir.glob("*.csv")):
        if path.name in ("sample_ohlcv.csv", "SAMPLE.csv"):
            continue
        tickers.append(path.stem.replace("_", "."))
    return tickers


def ticker_label(ticker: str) -> str:
    """'005930 · 삼성전자' 형태로 반환."""
    name = get_ticker_name(ticker)
    if name != ticker:
        return f"{ticker} · {name}"
    return ticker


def load_enriched_data(
    ticker: str,
    rsi_period: int,
    bb_period: int,
    bb_std_dev: float,
    ma_short: int,
    ma_long: int,
    rsi_oversold: float,
    rsi_overbought: float,
    swing_mode: bool = False,
) -> pd.DataFrame:
    csv_path = get_default_csv_path(ticker)
    df = pd.read_csv(csv_path)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    df = add_all_indicators(df, rsi_period=rsi_period, bb_period=bb_period,
                            bb_std_dev=bb_std_dev, ma_short=ma_short, ma_long=ma_long)
    df = generate_signals(df, rsi_oversold=rsi_oversold,
                          rsi_overbought=rsi_overbought, swing_mode=swing_mode)
    return df.dropna().copy()


def build_chart(df: pd.DataFrame) -> go.Figure:
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        vertical_spacing=0.08, row_heights=[0.7, 0.3])
    fig.add_trace(go.Candlestick(x=df.index, open=df["open"], high=df["high"],
                                  low=df["low"], close=df["close"], name="주가"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["bb_upper"], name="BB 상단", line={"width": 1}), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["bb_middle"], name="BB 중간", line={"width": 1}), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["bb_lower"], name="BB 하단", line={"width": 1, "color": "red"}), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["ma_short"], name="단기 이평", line={"width": 2}), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["ma_long"], name="장기 이평", line={"width": 2}), row=1, col=1)

    buy_points = df[df["signal"] == BUY]
    sell_points = df[df["signal"] == SELL]
    fig.add_trace(go.Scatter(x=buy_points.index, y=buy_points["close"], mode="markers",
                              name="매수", marker={"symbol": "triangle-up", "size": 11, "color": "orange"}), row=1, col=1)
    fig.add_trace(go.Scatter(x=sell_points.index, y=sell_points["close"], mode="markers",
                              name="매도", marker={"symbol": "triangle-down", "size": 11, "color": "orange"}), row=1, col=1)

    fig.add_trace(go.Scatter(x=df.index, y=df["rsi"], name="RSI", line={"width": 2, "color": "purple"}), row=2, col=1)
    fig.add_hline(y=30, line_dash="dot", line_color="#2ca02c", row=2, col=1)
    fig.add_hline(y=70, line_dash="dot", line_color="#d62728", row=2, col=1)

    fig.update_layout(height=700, margin={"l": 20, "r": 20, "t": 40, "b": 20})
    fig.update_yaxes(title_text="주가 (원)", row=1, col=1)
    fig.update_yaxes(title_text="RSI", row=2, col=1, range=[0, 100])
    fig.update_xaxes(rangeslider_visible=False)
    return fig


def build_chart_us(df: pd.DataFrame) -> go.Figure:
    """미국 주식용 차트 (달러 표기)."""
    fig = build_chart(df)
    fig.update_yaxes(title_text="주가 ($)", row=1, col=1)
    return fig


# ──────────────────────────────────────────
# 사이드바
# ──────────────────────────────────────────

available_tickers = list_csv_tickers()

with st.sidebar:
    st.header("백테스트 설정")

    swing_mode = st.toggle(
        "⚡ 단타/스윙 모드",
        value=False,
        help="ON: RSI+볼린저밴드 2조건만으로 매매 → 거래 자주 발생. OFF: 보수적 4조건 모두 충족 시 매매.",
    )
    if swing_mode:
        st.info("⚡ 단타 모드 ON — 거래 횟수 증가, 수수료 영향 주의!")

    st.divider()
    if available_tickers:
        labels = [ticker_label(t) for t in available_tickers]
        selected_label = st.selectbox("종목", labels,
                                       help="data/ 폴더에 저장된 종목만 표시됩니다.")
        selected_ticker = available_tickers[labels.index(selected_label)]
    else:
        selected_ticker = None

    initial_capital = st.number_input("초기 자본 (원)", min_value=100000,
                                       value=10000000, step=100000,
                                       help="투자 원금. 기본값 1천만원.")

    st.divider()
    st.subheader("📈 RSI 설정")
    st.caption("주식이 얼마나 과열/침체됐는지 나타내는 지표 (0~100)")
    rsi_oversold = st.slider("매수 기준 (RSI 하한)", 10, 50, 45,
                              help="이 값 아래 = '너무 많이 팔렸다' → 매수 신호")
    rsi_overbought = st.slider("매도 기준 (RSI 상한)", 55, 90, 65,
                                help="이 값 위 = '너무 많이 올랐다' → 매도 신호")
    rsi_period = st.slider("RSI 계산 기간 (일)", 5, 30, 14,
                            help="며칠치 데이터로 RSI를 계산할지. 보통 14일.")

    st.divider()
    st.subheader("📊 볼린저밴드 설정")
    st.caption("주가의 정상 범위를 나타내는 위/아래 선")
    bb_period = st.slider("밴드 계산 기간 (일)", 5, 40, 20,
                           help="며칠치 데이터로 밴드를 계산할지. 보통 20일.")
    bb_std_dev = st.slider("밴드 폭 (표준편차)", 1.0, 3.0, 2.0, step=0.1,
                            help="낮을수록 밴드가 좁아져 매수 신호 자주 발생. 1.5~2.0 추천.")

    st.divider()
    st.subheader("📉 이동평균 설정")
    st.caption("주가의 평균 흐름(추세)을 나타내는 선")
    ma_short = st.slider("단기 이동평균 (일)", 3, 40, 10,
                          help="짧은 기간 평균 주가. 장기보다 반드시 작아야 합니다.")
    ma_long = st.slider("장기 이동평균 (일)", 10, 120, 30,
                         help="긴 기간 평균 주가. 단기보다 반드시 커야 합니다.")

if ma_short >= ma_long:
    st.error("단기 이동평균이 장기 이동평균보다 작아야 합니다.")
    st.stop()


# ──────────────────────────────────────────
# 메인 탭
# ──────────────────────────────────────────

st.title("📈 자동매매 백테스트 대시보드")

tab_backtest, tab_screener, tab_portfolio, tab_us = st.tabs(
    ["📊 백테스트", "🔍 단타 종목 추천", "💼 포트폴리오", "🇺🇸 미국 주식"]
)


# ══════════════════════════════════════════
# 탭 1: 백테스트
# ══════════════════════════════════════════

with tab_backtest:
    if not available_tickers:
        st.warning("data/ 폴더에 CSV가 없습니다. 먼저 데이터를 다운로드하세요.")
        st.code(".venv/bin/python tests/download_data.py --ticker 005930 --period 3y")
        st.stop()

    try:
        result = run_backtest(
            ticker=selected_ticker,
            initial_capital=initial_capital,
            data_source="csv",
            rsi_oversold=rsi_oversold,
            rsi_overbought=rsi_overbought,
            rsi_period=rsi_period,
            bb_period=bb_period,
            bb_std_dev=bb_std_dev,
            ma_short=ma_short,
            ma_long=ma_long,
            swing_mode=swing_mode,
            verbose=False,
        )
        enriched_df = load_enriched_data(
            ticker=selected_ticker,
            rsi_period=rsi_period, bb_period=bb_period,
            bb_std_dev=bb_std_dev, ma_short=ma_short, ma_long=ma_long,
            rsi_oversold=rsi_oversold, rsi_overbought=rsi_overbought,
            swing_mode=swing_mode,
        )
    except ValueError as exc:
        st.error(str(exc))
        st.stop()

    # 종목명 표시
    st.subheader(f"{selected_ticker} · {get_ticker_name(selected_ticker)}")

    # 결과 지표
    cols = st.columns(5)
    cols[0].metric("총 수익률", f"{result['total_return_pct']:+.2f}%")
    cols[1].metric("최대 손실폭 (MDD)", f"{result['mdd_pct']:+.2f}%")
    cols[2].metric("총 거래 횟수", f"{result['trade_count']}회")
    cols[3].metric("승률", f"{result['win_rate']:.1f}%")
    cols[4].metric("최종 자본", f"{result['final_capital']:,.0f} 원")

    if result["trade_count"] > 0:
        estimated_fee = result["trade_count"] * initial_capital * 0.3 * (COMMISSION_RATE + SLIPPAGE_RATE) * 2
        net_return = result["final_capital"] - initial_capital
        st.caption(
            f"💸 수수료+슬리피지 추정: 약 {estimated_fee:,.0f}원 "
            f"(거래 {result['trade_count']}회 × 편도 0.115%) | "
            f"순수익: {net_return:+,.0f}원"
        )

    st.plotly_chart(build_chart(enriched_df), use_container_width=True)

    trades_df = result["trades_df"]
    left_col, right_col = st.columns([1.2, 1])
    with left_col:
        st.subheader("거래 내역")
        if len(trades_df) > 0:
            st.dataframe(trades_df, use_container_width=True)
        else:
            st.info("현재 조건에서는 거래가 발생하지 않았습니다.")
    with right_col:
        st.subheader("최근 데이터")
        preview_cols = ["open", "high", "low", "close", "volume", "rsi", "signal"]
        st.dataframe(enriched_df[preview_cols].tail(20), use_container_width=True)


# ══════════════════════════════════════════
# 탭 2: 단타 종목 추천 스크리너
# ══════════════════════════════════════════

with tab_screener:
    st.subheader("🔍 단타/스윙 종목 추천")
    st.caption("다운로드된 종목들을 현재 파라미터로 일괄 백테스트해서 수익률 순으로 추천합니다.")

    if not available_tickers:
        st.warning("data/ 폴더에 종목 데이터가 없습니다. 먼저 여러 종목을 다운로드하세요.")
        st.stop()

    # ── 필터 행 ──
    filter_col1, filter_col2, filter_col3 = st.columns([1.2, 1.2, 2])

    with filter_col1:
        market_filter = st.radio(
            "시장",
            options=["전체", "코스피", "코스닥"],
            horizontal=True,
            help="코스닥은 변동성이 높아 단타/스윙에 유리합니다.",
        )

    with filter_col2:
        min_volatility = st.slider(
            "최소 변동성 (%)",
            min_value=0, max_value=80, value=0, step=5,
            help="연환산 변동성. 높을수록 주가 움직임이 큼. 코스닥 평균 40~60%.",
        )

    with filter_col3:
        search_query = st.text_input(
            "🔎 종목 검색",
            placeholder="종목코드 또는 종목명 (예: 005930, 삼성, HLB)",
            help="비워두면 전체 스캔.",
        )

    # 스캔 대상 필터링
    def _ticker_matches(ticker: str, query: str, market: str) -> bool:
        code = ticker.split(".")[0]
        mkt = get_market(code)  # "KOSPI" / "KOSDAQ" / ""

        if market == "코스피" and mkt != "KOSPI":
            return False
        if market == "코스닥" and mkt != "KOSDAQ":
            return False

        q = query.strip().lower()
        if not q:
            return True
        name = get_ticker_name(ticker).lower()
        return q in code.lower() or q in name

    tickers_to_scan = [
        t for t in available_tickers if _ticker_matches(t, search_query, market_filter)
    ]

    col_a, col_b = st.columns([1, 3])
    with col_a:
        min_trades = st.number_input("최소 거래 횟수", min_value=1, value=2,
                                      help="이 횟수 이상 거래한 종목만 표시합니다.")
        run_screen = st.button("🚀 스크리닝 시작", use_container_width=True)

    with col_b:
        kosdaq_count = sum(1 for t in tickers_to_scan if get_market(t.split(".")[0]) == "KOSDAQ")
        kospi_count = len(tickers_to_scan) - kosdaq_count
        st.info(
            f"📋 스캔 대상: **{len(tickers_to_scan)}개** "
            f"(코스피 {kospi_count} / 코스닥 {kosdaq_count})  |  "
            f"모드: **{'⚡ 단타' if swing_mode else '🐢 보수'}**"
        )

    if not tickers_to_scan:
        st.warning("조건에 맞는 종목이 없습니다. 시장 필터나 검색어를 바꿔보세요.")
    elif run_screen:
        rows = []
        progress = st.progress(0, text="스크리닝 중...")

        for i, ticker in enumerate(tickers_to_scan):
            progress.progress((i + 1) / len(tickers_to_scan), text=f"분석 중: {ticker_label(ticker)}")
            try:
                res = run_backtest(
                    ticker=ticker,
                    initial_capital=initial_capital,
                    data_source="csv",
                    rsi_oversold=rsi_oversold,
                    rsi_overbought=rsi_overbought,
                    rsi_period=rsi_period,
                    bb_period=bb_period,
                    bb_std_dev=bb_std_dev,
                    ma_short=ma_short,
                    ma_long=ma_long,
                    swing_mode=swing_mode,
                    verbose=False,
                )
                code = ticker.split(".")[0]
                rows.append({
                    "시장": get_market(code) or "—",
                    "종목코드": code,
                    "종목명": get_ticker_name(ticker),
                    "변동성 (%)": get_stock_volatility(ticker),
                    "수익률 (%)": round(res["total_return_pct"], 2),
                    "MDD (%)": round(res["mdd_pct"], 2),
                    "거래 횟수": res["trade_count"],
                    "승률 (%)": round(res["win_rate"], 1),
                    "평균 보유일": round(res["avg_hold_days"], 1),
                    "최종 자본 (원)": int(res["final_capital"]),
                })
            except Exception:
                pass

        progress.empty()

        if not rows:
            st.error("결과가 없습니다.")
        else:
            df_result = pd.DataFrame(rows)
            df_filtered = df_result[
                (df_result["거래 횟수"] >= min_trades)
                & (df_result["변동성 (%)"] >= min_volatility)
            ].sort_values("수익률 (%)", ascending=False).reset_index(drop=True)

            st.success(f"✅ {len(tickers_to_scan)}개 종목 스캔 완료 — 조건 충족 {len(df_filtered)}개")

            # 상위 바 차트
            if not df_filtered.empty:
                top = df_filtered.head(15)
                colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in top["수익률 (%)"]]
                fig_bar = go.Figure(go.Bar(
                    x=top["종목명"] + "<br>" + top["종목코드"],
                    y=top["수익률 (%)"],
                    marker_color=colors,
                    text=[f"{v:+.2f}%" for v in top["수익률 (%)"]],
                    textposition="outside",
                ))
                fig_bar.update_layout(
                    title="수익률 상위 종목 (최대 15개)",
                    xaxis_title="종목코드",
                    yaxis_title="수익률 (%)",
                    height=380,
                    margin={"t": 50, "b": 20},
                )
                st.plotly_chart(fig_bar, use_container_width=True)

            # 결과 내 재검색
            result_filter = st.text_input(
                "📌 결과 내 검색",
                placeholder="종목코드 또는 종목명으로 결과 필터링",
                key="result_filter",
            )
            if result_filter.strip():
                q = result_filter.strip().lower()
                df_display = df_filtered[
                    df_filtered["종목코드"].str.lower().str.contains(q)
                    | df_filtered["종목명"].str.lower().str.contains(q)
                ].reset_index(drop=True)
            else:
                df_display = df_filtered

            # 전체 테이블
            st.dataframe(
                df_display.style.format({
                    "변동성 (%)": "{:.1f}",
                    "수익률 (%)": "{:+.2f}",
                    "MDD (%)": "{:+.2f}",
                    "승률 (%)": "{:.1f}",
                    "최종 자본 (원)": "{:,.0f}",
                })
                .background_gradient(subset=["수익률 (%)"], cmap="RdYlGn")
                .background_gradient(subset=["변동성 (%)"], cmap="YlOrRd"),
                use_container_width=True,
            )

            st.caption(
                "💡 **수익률↑ + 거래 횟수↑** = 이 전략에 잘 맞는 종목  |  "
                "**변동성↑** = 주가 움직임이 크다 (코스닥 평균 40~60%)  |  "
                "코스닥 고변동성 종목은 단타/스윙 모드와 함께 사용하세요."
            )


# ══════════════════════════════════════════
# 탭 3: 포트폴리오 관리
# ══════════════════════════════════════════

with tab_portfolio:
    st.subheader("💼 내 포트폴리오")

    # ── 섹션 1: 보유 포지션 ──────────────────
    st.markdown("### 보유 종목")

    positions = get_open_positions()

    if positions:
        from datetime import date as _date
        total_invested = sum(p["entry_price"] * p["shares"] for p in positions)
        st.caption(f"총 {len(positions)}개 종목 보유 중 | 총 투자금: {total_invested:,.0f}원")

        for p in positions:
            with st.container(border=True):
                # 상단: 종목 정보
                info_col, action_col = st.columns([3, 2])
                with info_col:
                    cost = p["entry_price"] * p["shares"]
                    us = _is_us(p["ticker"])
                    if us:
                        price_fmt  = f"${p['entry_price']:,.2f}"
                        cost_fmt   = f"${cost:,.2f}"
                        sl_fmt     = f"${p['stop_loss']:,.2f}"
                        tp_fmt     = f"${p['take_profit']:,.2f}"
                    else:
                        price_fmt  = f"{p['entry_price']:,.0f}원"
                        cost_fmt   = f"{cost:,.0f}원"
                        sl_fmt     = f"{p['stop_loss']:,.0f}원"
                        tp_fmt     = f"{p['take_profit']:,.0f}원"
                    st.markdown(f"**{p['name'] or p['ticker']}** `{p['ticker']}`  |  매수일: {p['entry_date']}")
                    st.markdown(
                        f"매수가 **{price_fmt}** × {p['shares']}주 = **{cost_fmt}**  |  "
                        f"손절 `{sl_fmt}`  익절 `{tp_fmt}`"
                    )
                    if p["memo"]:
                        st.caption(f"메모: {p['memo']}")

                with action_col:
                    btn1, btn2, btn3 = st.columns(3)
                    show_sell = btn1.button("매도", key=f"open_sell_{p['id']}", type="primary", use_container_width=True)
                    show_edit = btn2.button("수정", key=f"open_edit_{p['id']}", use_container_width=True)
                    show_del  = btn3.button("삭제", key=f"open_del_{p['id']}", use_container_width=True)

                # 매도 폼
                if show_sell:
                    st.session_state[f"mode_{p['id']}"] = "sell"
                if show_edit:
                    st.session_state[f"mode_{p['id']}"] = "edit"
                if show_del:
                    st.session_state[f"mode_{p['id']}"] = "delete"

                mode = st.session_state.get(f"mode_{p['id']}")

                if mode == "sell":
                    with st.form(key=f"sell_form_{p['id']}"):
                        sc1, sc2 = st.columns(2)
                        sell_price = sc1.number_input("매도가 (원)", min_value=1,
                            value=int(p["entry_price"]), step=100)
                        sell_reason = sc2.selectbox("매도 사유",
                            ["수동매도", "매도신호", "익절", "손절"])
                        ok, cancel = st.columns(2)
                        if ok.form_submit_button("확인", type="primary", use_container_width=True):
                            close_position(p["id"], sell_price, _date.today().isoformat(), sell_reason)
                            pnl = (sell_price - p["entry_price"]) * p["shares"]
                            pnl_pct = (sell_price / p["entry_price"] - 1) * 100
                            st.session_state.pop(f"mode_{p['id']}", None)
                            st.success(f"매도 완료! 손익: {pnl:+,.0f}원 ({pnl_pct:+.1f}%)")
                            st.rerun()
                        if cancel.form_submit_button("취소", use_container_width=True):
                            st.session_state.pop(f"mode_{p['id']}", None)
                            st.rerun()

                elif mode == "edit":
                    with st.form(key=f"edit_form_{p['id']}"):
                        ec1, ec2, ec3 = st.columns(3)
                        new_price = ec1.number_input("매수가 (원)", min_value=1,
                            value=int(p["entry_price"]), step=100)
                        new_shares = ec2.number_input("수량 (주)", min_value=1,
                            value=int(p["shares"]), step=1)
                        new_entry_date = ec3.date_input("매수일",
                            value=pd.to_datetime(p["entry_date"]).date())
                        ed1, ed2, ed3 = st.columns(3)
                        new_sl = ed1.number_input("손절가 (원)", min_value=1,
                            value=int(p["stop_loss"]), step=100)
                        new_tp = ed2.number_input("익절가 (원)", min_value=1,
                            value=int(p["take_profit"]), step=100)
                        new_memo = ed3.text_input("메모", value=p["memo"] or "")
                        ok, cancel = st.columns(2)
                        if ok.form_submit_button("저장", type="primary", use_container_width=True):
                            update_position(p["id"],
                                entry_price=float(new_price),
                                shares=int(new_shares),
                                entry_date=new_entry_date.isoformat(),
                                stop_loss=float(new_sl),
                                take_profit=float(new_tp),
                                memo=new_memo,
                            )
                            st.session_state.pop(f"mode_{p['id']}", None)
                            st.success("수정 완료!")
                            st.rerun()
                        if cancel.form_submit_button("취소", use_container_width=True):
                            st.session_state.pop(f"mode_{p['id']}", None)
                            st.rerun()

                elif mode == "delete":
                    st.warning(f"**{p['name'] or p['ticker']}** 포지션을 삭제합니다. 복구할 수 없습니다.")
                    dc1, dc2 = st.columns(2)
                    if dc1.button("삭제 확인", key=f"del_confirm_{p['id']}", type="primary", use_container_width=True):
                        delete_position(p["id"])
                        st.session_state.pop(f"mode_{p['id']}", None)
                        st.success("삭제 완료!")
                        st.rerun()
                    if dc2.button("취소", key=f"del_cancel_{p['id']}", use_container_width=True):
                        st.session_state.pop(f"mode_{p['id']}", None)
                        st.rerun()
    else:
        st.info("보유 중인 종목이 없습니다.")

    st.divider()

    # ── 섹션 2: 매수 등록 ──────────────────
    st.markdown("### 매수 등록")

    with st.form("add_position_form"):
        mkt_col, ticker_col = st.columns([1, 2])
        with mkt_col:
            pos_market = st.radio("시장", ["국장 🇰🇷", "미장 🇺🇸"], horizontal=True)
        with ticker_col:
            if pos_market == "국장 🇰🇷":
                new_ticker = st.text_input("종목코드", placeholder="예: 086900", max_chars=6)
            else:
                new_ticker = st.text_input("티커", placeholder="예: AAPL", max_chars=10)

        is_us_pos = (pos_market == "미장 🇺🇸")
        price_unit = "$" if is_us_pos else "원"
        price_step = 0.01 if is_us_pos else 100
        price_default = 150.0 if is_us_pos else 50000

        c2, c3 = st.columns(2)
        with c2:
            new_price = st.number_input(f"매수가 ({price_unit})", min_value=0.01,
                value=float(price_default), step=float(price_step))
        with c3:
            new_shares = st.number_input("수량 (주)", min_value=1, value=10, step=1)

        c4, c5, c6 = st.columns(3)
        with c4:
            new_date = st.date_input("매수일", value=_date.today())
        with c5:
            new_sl = st.number_input(
                f"손절가 ({price_unit})", min_value=0.01,
                value=round(new_price * 0.97, 2), step=float(price_step),
                help="기본: 매수가 -3%"
            )
        with c6:
            new_tp = st.number_input(
                f"익절가 ({price_unit})", min_value=0.01,
                value=round(new_price * 1.06, 2), step=float(price_step),
                help="기본: 매수가 +6%"
            )

        new_memo = st.text_input("메모 (선택)", placeholder="예: 텔레그램 신호 매수")

        submitted = st.form_submit_button("매수 등록", use_container_width=True, type="primary")
        if submitted:
            if not new_ticker.strip():
                st.error("종목코드를 입력하세요.")
            else:
                if is_us_pos:
                    ticker = new_ticker.strip().upper()
                else:
                    ticker = new_ticker.strip().zfill(6)
                name = get_ticker_name(ticker)
                pos_id = add_position(
                    ticker=ticker,
                    entry_price=float(new_price),
                    shares=int(new_shares),
                    entry_date=new_date.isoformat(),
                    name=name,
                    stop_loss=float(new_sl),
                    take_profit=float(new_tp),
                    memo=new_memo,
                )
                cost = new_price * new_shares
                cost_str = f"${cost:,.2f}" if is_us_pos else f"{cost:,.0f}원"
                price_str = f"${new_price:,.2f}" if is_us_pos else f"{new_price:,}원"
                st.success(
                    f"등록 완료! {name} {new_shares}주 × {price_str} = {cost_str} (ID: {pos_id})"
                )
                st.rerun()

    st.divider()

    # ── 섹션 3: 거래 이력 ──────────────────
    with st.expander("거래 이력 (청산 완료)", expanded=False):
        history = get_position_history()
        closed = [p for p in history if p["status"] == "closed"]
        if closed:
            rows = []
            for p in closed:
                pnl_pct = (p["exit_price"] / p["entry_price"] - 1) * 100 if p["exit_price"] else 0
                pnl_won = (p["exit_price"] - p["entry_price"]) * p["shares"] if p["exit_price"] else 0
                rows.append({
                    "종목명": p["name"] or p["ticker"],
                    "종목코드": p["ticker"],
                    "매수가": p["entry_price"],
                    "매도가": p["exit_price"],
                    "수량": p["shares"],
                    "손익 (%)": round(pnl_pct, 2),
                    "손익 (원)": int(pnl_won),
                    "사유": p["exit_reason"],
                    "매수일": p["entry_date"],
                    "매도일": p["exit_date"],
                })
            df_hist = pd.DataFrame(rows)
            total_pnl = df_hist["손익 (원)"].sum()
            st.caption(f"총 {len(closed)}건 | 누적 손익: {total_pnl:+,.0f}원")
            st.dataframe(
                df_hist.style.format({
                    "매수가": "{:,.0f}",
                    "매도가": "{:,.0f}",
                    "손익 (%)": "{:+.2f}",
                    "손익 (원)": "{:+,.0f}",
                }).background_gradient(subset=["손익 (%)"], cmap="RdYlGn"),
                use_container_width=True,
            )
        else:
            st.info("청산된 포지션이 없습니다.")


# ══════════════════════════════════════════
# 탭 4: 미국 주식
# ══════════════════════════════════════════

with tab_us:
    st.subheader("🇺🇸 미국 주식")

    us_tickers = [t for t in available_tickers if _is_us(t)]

    # ── 미장 전용 파라미터 (스윕 최적값: RSI40/65, MA10/30, BB1.5) ──
    with st.expander("⚙️ 미장 파라미터 설정", expanded=False):
        st.caption("파라미터 스윕으로 도출한 미장 최적값이 기본 적용됩니다.")
        uc1, uc2, uc3 = st.columns(3)
        us_rsi_os  = uc1.slider("RSI 매수 기준", 10, 55, 40, key="us_rsi_os")
        us_rsi_ob  = uc2.slider("RSI 매도 기준", 55, 90, 65, key="us_rsi_ob")
        us_bb_std  = uc3.slider("BB 표준편차", 1.0, 3.0, 1.5, step=0.1, key="us_bb_std")
        ud1, ud2, ud3 = st.columns(3)
        us_ma_s    = ud1.slider("MA 단기 (일)", 3, 40, 10, key="us_ma_s")
        us_ma_l    = ud2.slider("MA 장기 (일)", 10, 120, 30, key="us_ma_l")
        us_rsi_p   = ud3.slider("RSI 기간 (일)", 5, 30, 14, key="us_rsi_p")
        us_bb_p    = ud1.slider("BB 기간 (일)", 5, 40, 20, key="us_bb_p")

    # ── 백테스트 ──────────────────────────
    st.markdown("### 📊 백테스트")

    if not us_tickers:
        st.warning("미국 주식 CSV 데이터가 없습니다. 먼저 데이터를 다운로드하세요.")
        st.code(".venv/bin/python tests/download_data.py --ticker AAPL --period 2y")
    else:
        us_labels = [ticker_label(t) for t in us_tickers]
        us_selected_label  = st.selectbox("종목 선택", us_labels, key="us_bt_ticker")
        us_selected_ticker = us_tickers[us_labels.index(us_selected_label)]
        us_capital = st.number_input("초기 자본 ($)", min_value=1000,
                                     value=10000, step=1000, key="us_capital")

        try:
            us_result = run_backtest(
                ticker=us_selected_ticker,
                initial_capital=us_capital,
                data_source="csv",
                rsi_oversold=us_rsi_os,
                rsi_overbought=us_rsi_ob,
                rsi_period=us_rsi_p,
                bb_period=us_bb_p,
                bb_std_dev=us_bb_std,
                ma_short=us_ma_s,
                ma_long=ma_long,
                swing_mode=swing_mode,
                verbose=False,
            )
            us_df = load_enriched_data(
                ticker=us_selected_ticker,
                rsi_period=us_rsi_p, bb_period=us_bb_p,
                bb_std_dev=us_bb_std, ma_short=us_ma_s, ma_long=us_ma_l,
                rsi_oversold=us_rsi_os, rsi_overbought=us_rsi_ob,
                swing_mode=swing_mode,
            )

            st.subheader(f"{us_selected_ticker} · {get_ticker_name(us_selected_ticker)}")
            cols = st.columns(5)
            cols[0].metric("총 수익률",   f"{us_result['total_return_pct']:+.2f}%")
            cols[1].metric("MDD",         f"{us_result['mdd_pct']:+.2f}%")
            cols[2].metric("거래 횟수",   f"{us_result['trade_count']}회")
            cols[3].metric("승률",        f"{us_result['win_rate']:.1f}%")
            cols[4].metric("최종 자본",   f"${us_result['final_capital']:,.2f}")

            us_fig = build_chart(us_df)
            us_fig.update_yaxes(title_text="주가 ($)", row=1, col=1)
            st.plotly_chart(us_fig, use_container_width=True)

            if len(us_result["trades_df"]) > 0:
                st.dataframe(us_result["trades_df"], use_container_width=True)
            else:
                st.info("현재 조건에서는 거래가 발생하지 않았습니다.")

        except ValueError as exc:
            st.error(str(exc))

    st.divider()

    # ── 단타 종목 추천 ─────────────────────
    st.markdown("### 🔍 단타 종목 추천")

    if not us_tickers:
        st.info("다운로드된 미국 종목이 없어 스캔할 수 없습니다.")
    else:
        us_search = st.text_input("🔎 종목 검색", placeholder="예: AAPL, 엔비디아",
                                   key="us_search")
        us_min_trades = st.number_input("최소 거래 횟수", min_value=1, value=2, key="us_min_trades")
        us_run = st.button("🚀 미국 종목 스캔", use_container_width=True)

        q = us_search.strip().lower()
        us_scan = [
            t for t in us_tickers
            if not q or q in t.lower() or q in get_ticker_name(t).lower()
        ]

        st.info(f"📋 스캔 대상: **{len(us_scan)}개** | 모드: **{'⚡ 단타' if swing_mode else '🐢 보수'}**")

        if us_run:
            us_rows = []
            us_prog = st.progress(0, text="스캔 중...")
            for i, t in enumerate(us_scan):
                us_prog.progress((i + 1) / len(us_scan), text=f"분석 중: {ticker_label(t)}")
                try:
                    r = run_backtest(
                        ticker=t, initial_capital=10000, data_source="csv",
                        rsi_oversold=us_rsi_os, rsi_overbought=us_rsi_ob,
                        rsi_period=us_rsi_p, bb_period=us_bb_p, bb_std_dev=us_bb_std,
                        ma_short=us_ma_s, ma_long=us_ma_l, swing_mode=swing_mode, verbose=False,
                    )
                    us_rows.append({
                        "티커":       t,
                        "종목명":     get_ticker_name(t),
                        "수익률 (%)": round(r["total_return_pct"], 2),
                        "MDD (%)":    round(r["mdd_pct"], 2),
                        "거래 횟수":  r["trade_count"],
                        "승률 (%)":   round(r["win_rate"], 1),
                        "최종 자본($)": round(r["final_capital"], 2),
                    })
                except Exception:
                    pass
            us_prog.empty()

            if us_rows:
                us_df_result = pd.DataFrame(us_rows)
                us_df_filtered = us_df_result[
                    us_df_result["거래 횟수"] >= us_min_trades
                ].sort_values("수익률 (%)", ascending=False).reset_index(drop=True)

                st.success(f"✅ {len(us_scan)}개 스캔 완료 — 조건 충족 {len(us_df_filtered)}개")

                if not us_df_filtered.empty:
                    top = us_df_filtered.head(15)
                    colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in top["수익률 (%)"]]
                    us_fig_bar = go.Figure(go.Bar(
                        x=top["종목명"] + "<br>" + top["티커"],
                        y=top["수익률 (%)"],
                        marker_color=colors,
                        text=[f"{v:+.2f}%" for v in top["수익률 (%)"]],
                        textposition="outside",
                    ))
                    us_fig_bar.update_layout(title="수익률 상위 (최대 15개)",
                                             height=350, margin={"t": 50, "b": 20})
                    st.plotly_chart(us_fig_bar, use_container_width=True)

                st.dataframe(
                    us_df_filtered.style.format({
                        "수익률 (%)":  "{:+.2f}",
                        "MDD (%)":     "{:+.2f}",
                        "승률 (%)":    "{:.1f}",
                        "최종 자본($)": "{:,.2f}",
                    }).background_gradient(subset=["수익률 (%)"], cmap="RdYlGn"),
                    use_container_width=True,
                )
