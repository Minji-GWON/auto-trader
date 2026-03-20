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
from tests.backtest import run_backtest

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
    """종목명 조회: stocks 마스터 → pykrx 폴백."""
    code = ticker.split(".")[0]
    # 마스터 데이터 우선
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
    rsi_oversold = st.slider("매수 기준 (RSI 하한)", 10, 45, 30,
                              help="이 값 아래 = '너무 많이 팔렸다' → 매수 신호")
    rsi_overbought = st.slider("매도 기준 (RSI 상한)", 55, 90, 70,
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
    ma_short = st.slider("단기 이동평균 (일)", 3, 40, 20,
                          help="짧은 기간 평균 주가. 장기보다 반드시 작아야 합니다.")
    ma_long = st.slider("장기 이동평균 (일)", 10, 120, 60,
                         help="긴 기간 평균 주가. 단기보다 반드시 커야 합니다.")

if ma_short >= ma_long:
    st.error("단기 이동평균이 장기 이동평균보다 작아야 합니다.")
    st.stop()


# ──────────────────────────────────────────
# 메인 탭
# ──────────────────────────────────────────

st.title("📈 자동매매 백테스트 대시보드")

tab_backtest, tab_screener = st.tabs(["📊 백테스트", "🔍 단타 종목 추천"])


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
