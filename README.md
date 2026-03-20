# Auto-Trader

RSI, Bollinger Bands, and a simple trend filter based backtesting starter project.

## Structure

```text
auto-trader/
├─ README.md
├─ dashboard/
│  └─ app.py
├─ data/
│  └─ sample_ohlcv.csv
├─ requirements.txt
├─ .env.example
├─ backend/
│  ├─ data_fetcher/
│  │  └─ fetcher.py
│  ├─ indicators/
│  │  └─ calculator.py
│  ├─ strategy/
│  │  └─ signal.py
│  └─ risk_manager/
│     └─ manager.py
└─ tests/
   ├─ backtest.py
   ├─ batch_backtest.py
   ├─ download_data.py
   └─ parameter_sweep.py
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`ALPHA_VANTAGE_API_KEY`를 넣으면 `auto` 모드에서 Alpha Vantage를 우선 사용합니다.

## Run

```bash
python3 tests/download_data.py --ticker AAPL --period 1y
python3 tests/backtest.py --ticker AAPL --source csv
python3 tests/batch_backtest.py --download-first
streamlit run dashboard/app.py
python3 tests/backtest.py
python3 tests/backtest.py --ticker 035720.KS --period 2y
python3 tests/backtest.py --ticker AAPL --period 1y --source alphavantage
python3 tests/backtest.py --ticker SAMPLE --source csv --csv-path data/sample_ohlcv.csv --ma-short 5 --ma-long 15 --bb-period 10
python3 tests/parameter_sweep.py --source csv --csv-path data/sample_ohlcv.csv
```

권장 흐름은 먼저 `tests/download_data.py`로 데이터를 `data/`에 저장하고, 이후 `--source csv`로 저장본을 기준으로 반복 백테스트하는 방식입니다.
여러 종목을 비교할 때는 `tests/batch_backtest.py --download-first`를 쓰면 추천 5종목을 한 번에 내려받고 요약 결과 CSV까지 저장합니다.
시각적으로 확인하고 싶으면 `streamlit run dashboard/app.py`로 대시보드를 띄우면 됩니다.

## Strategy Summary

- Buy when RSI is oversold, price breaks below the lower Bollinger Band, short MA is above long MA, and the candle closes green.
- Sell on RSI overbought plus upper band breakout, stop loss, take profit, or end of test period.
- Risk settings are loaded from `.env` when present.
- Data source can be switched with `--source`. `auto` uses Alpha Vantage first when an API key is configured, then falls back to `yfinance`.
- `csv` source를 쓰면 외부 API 없이도 백테스트를 반복 실행할 수 있습니다.
