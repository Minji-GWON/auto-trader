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
from tests.backtest import run_backtest


st.set_page_config(
    page_title="Auto-Trader Dashboard",
    page_icon="chart_with_upwards_trend",
    layout="wide",
)


def list_csv_tickers() -> list[str]:
    data_dir = ROOT_DIR / "data"
    if not data_dir.exists():
        return []
    tickers = []
    for path in sorted(data_dir.glob("*.csv")):
        if path.name == "sample_ohlcv.csv":
            continue
        tickers.append(path.stem.replace("_", "."))
    return tickers


def load_enriched_data(
    ticker: str,
    rsi_period: int,
    bb_period: int,
    bb_std_dev: float,
    ma_short: int,
    ma_long: int,
    rsi_oversold: float,
    rsi_overbought: float,
) -> pd.DataFrame:
    csv_path = get_default_csv_path(ticker)
    df = pd.read_csv(csv_path)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    df = add_all_indicators(
        df,
        rsi_period=rsi_period,
        bb_period=bb_period,
        bb_std_dev=bb_std_dev,
        ma_short=ma_short,
        ma_long=ma_long,
    )
    df = generate_signals(df, rsi_oversold=rsi_oversold, rsi_overbought=rsi_overbought)
    return df.dropna().copy()


def build_chart(df: pd.DataFrame) -> go.Figure:
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.7, 0.3],
    )

    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="Price",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(go.Scatter(x=df.index, y=df["bb_upper"], name="BB Upper", line={"width": 1}), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["bb_middle"], name="BB Mid", line={"width": 1}), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["bb_lower"], name="BB Lower", line={"width": 1}), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["ma_short"], name="MA Short", line={"width": 2}), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["ma_long"], name="MA Long", line={"width": 2}), row=1, col=1)

    buy_points = df[df["signal"] == BUY]
    sell_points = df[df["signal"] == SELL]

    fig.add_trace(
        go.Scatter(
            x=buy_points.index,
            y=buy_points["close"],
            mode="markers",
            name="BUY",
            marker={"symbol": "triangle-up", "size": 11},
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=sell_points.index,
            y=sell_points["close"],
            mode="markers",
            name="SELL",
            marker={"symbol": "triangle-down", "size": 11},
        ),
        row=1,
        col=1,
    )

    fig.add_trace(go.Scatter(x=df.index, y=df["rsi"], name="RSI", line={"width": 2}), row=2, col=1)
    fig.add_hline(y=30, line_dash="dot", line_color="#2ca02c", row=2, col=1)
    fig.add_hline(y=70, line_dash="dot", line_color="#d62728", row=2, col=1)

    fig.update_layout(height=760, margin={"l": 20, "r": 20, "t": 40, "b": 20})
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="RSI", row=2, col=1, range=[0, 100])
    fig.update_xaxes(rangeslider_visible=False)
    return fig


st.title("Auto-Trader Dashboard")
st.caption("저장된 CSV 데이터를 기준으로 백테스트 결과를 빠르게 확인합니다.")

available_tickers = list_csv_tickers()
if not available_tickers:
    st.error("data 폴더에 CSV가 없습니다. 먼저 download_data.py로 데이터를 저장하세요.")
    st.stop()

with st.sidebar:
    st.header("Backtest Controls")
    selected_ticker = st.selectbox("Ticker", available_tickers, index=0)
    initial_capital = st.number_input("Initial Capital", min_value=100000, value=10000000, step=100000)
    rsi_oversold = st.slider("RSI Oversold", min_value=10, max_value=45, value=30)
    rsi_overbought = st.slider("RSI Overbought", min_value=55, max_value=90, value=70)
    rsi_period = st.slider("RSI Period", min_value=5, max_value=30, value=14)
    bb_period = st.slider("BB Period", min_value=5, max_value=40, value=20)
    bb_std_dev = st.slider("BB Std Dev", min_value=1.0, max_value=3.0, value=2.0, step=0.1)
    ma_short = st.slider("MA Short", min_value=3, max_value=40, value=20)
    ma_long = st.slider("MA Long", min_value=10, max_value=120, value=60)

if ma_short >= ma_long:
    st.error("MA Short는 MA Long보다 작아야 합니다.")
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
        verbose=False,
    )
    enriched_df = load_enriched_data(
        ticker=selected_ticker,
        rsi_period=rsi_period,
        bb_period=bb_period,
        bb_std_dev=bb_std_dev,
        ma_short=ma_short,
        ma_long=ma_long,
        rsi_oversold=rsi_oversold,
        rsi_overbought=rsi_overbought,
    )
except ValueError as exc:
    st.error(str(exc))
    st.stop()

metric_cols = st.columns(5)
metric_cols[0].metric("Total Return", f"{result['total_return_pct']:+.2f}%")
metric_cols[1].metric("MDD", f"{result['mdd_pct']:+.2f}%")
metric_cols[2].metric("Trades", f"{result['trade_count']}")
metric_cols[3].metric("Win Rate", f"{result['win_rate']:.1f}%")
metric_cols[4].metric("Final Capital", f"{result['final_capital']:,.0f} KRW")

st.plotly_chart(build_chart(enriched_df), use_container_width=True)

trades_df = result["trades_df"]
left_col, right_col = st.columns([1.2, 1])

with left_col:
    st.subheader("Trade History")
    if len(trades_df) > 0:
        st.dataframe(trades_df, use_container_width=True)
    else:
        st.info("현재 조건에서는 거래가 발생하지 않았습니다.")

with right_col:
    st.subheader("Data Snapshot")
    preview_cols = ["open", "high", "low", "close", "volume", "rsi", "signal"]
    st.dataframe(enriched_df[preview_cols].tail(20), use_container_width=True)

