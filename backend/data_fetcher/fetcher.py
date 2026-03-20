import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

SUPPORTED_SOURCES = {"auto", "alphavantage", "csv", "yfinance", "pykrx"}
ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"
DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def _resolve_date_range(
    start: Optional[str] = None,
    end: Optional[str] = None,
    period: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    if period:
        now = datetime.now()
        if period.endswith("y"):
            start_dt = now - timedelta(days=365 * int(period[:-1]))
        elif period.endswith("mo"):
            start_dt = now - timedelta(days=30 * int(period[:-2]))
        elif period.endswith("d"):
            start_dt = now - timedelta(days=int(period[:-1]))
        else:
            raise ValueError(f"지원하지 않는 period 형식입니다: {period}")

        return start_dt.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d")

    if start is None:
        start = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
    if end is None:
        end = datetime.now().strftime("%Y-%m-%d")
    return start, end


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df.columns = [str(column).lower() for column in df.columns]
    required_columns = ["open", "high", "low", "close", "volume"]
    missing = [column for column in required_columns if column not in df.columns]
    if missing:
        raise ValueError(f"OHLCV 컬럼 누락: {missing}")

    normalized = df[required_columns].copy()
    normalized.index = pd.to_datetime(normalized.index)
    normalized = normalized.sort_index()
    normalized.index.name = "date"
    return normalized


def _fetch_from_yfinance(
    ticker: str,
    start: Optional[str],
    end: Optional[str],
    period: Optional[str],
    interval: str,
) -> pd.DataFrame:
    if period:
        df = yf.download(
            ticker,
            period=period,
            interval=interval,
            progress=False,
            auto_adjust=True,
        )
    else:
        df = yf.download(
            ticker,
            start=start,
            end=end,
            interval=interval,
            progress=False,
            auto_adjust=True,
        )

    return _normalize_ohlcv(df)


def _fetch_from_alpha_vantage(
    ticker: str,
    start: Optional[str],
    end: Optional[str],
    api_key: Optional[str],
) -> pd.DataFrame:
    if not api_key:
        raise ValueError(
            "Alpha Vantage API 키가 없습니다. `.env`에 ALPHA_VANTAGE_API_KEY를 설정하세요."
        )

    params = {
        "function": "TIME_SERIES_DAILY_ADJUSTED",
        "symbol": ticker,
        "outputsize": "full",
        "apikey": api_key,
        "datatype": "json",
    }
    response = requests.get(ALPHA_VANTAGE_URL, params=params, timeout=20)
    response.raise_for_status()
    payload = response.json()

    if "Error Message" in payload:
        raise ValueError(f"Alpha Vantage 오류: {payload['Error Message']}")
    if "Note" in payload:
        raise ValueError(f"Alpha Vantage 제한: {payload['Note']}")

    series = payload.get("Time Series (Daily)")
    if not series:
        raise ValueError("Alpha Vantage에서 일봉 데이터를 찾지 못했습니다.")

    df = pd.DataFrame.from_dict(series, orient="index")
    rename_map = {
        "1. open": "open",
        "2. high": "high",
        "3. low": "low",
        "4. close": "close",
        "6. volume": "volume",
    }
    df = df.rename(columns=rename_map)
    df = df[list(rename_map.values())].apply(pd.to_numeric, errors="coerce")
    df.index = pd.to_datetime(df.index)

    if start:
        df = df[df.index >= pd.Timestamp(start)]
    if end:
        df = df[df.index <= pd.Timestamp(end)]

    return _normalize_ohlcv(df)


def _fetch_from_pykrx(
    ticker: str,
    start: Optional[str],
    end: Optional[str],
) -> pd.DataFrame:
    """pykrx로 한국 주식 OHLCV 수집. ticker는 6자리 숫자 코드 (예: '005930')."""
    from pykrx import stock as krx

    # pykrx는 YYYYMMDD 형식 사용
    start_str = start.replace("-", "") if start else (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
    end_str = end.replace("-", "") if end else datetime.now().strftime("%Y%m%d")

    # .KS, .KQ 접미사 제거
    krx_ticker = ticker.split(".")[0]

    df = krx.get_market_ohlcv_by_date(start_str, end_str, krx_ticker)
    if df.empty:
        raise ValueError(f"pykrx에서 데이터를 찾지 못했습니다: {krx_ticker}")

    df = df.rename(columns={"시가": "open", "고가": "high", "저가": "low", "종가": "close", "거래량": "volume"})
    return _normalize_ohlcv(df)


def _fetch_from_csv(
    csv_path: str,
    start: Optional[str],
    end: Optional[str],
) -> pd.DataFrame:
    if not csv_path:
        raise ValueError("CSV 소스를 사용하려면 csv_path가 필요합니다.")

    df = pd.read_csv(csv_path)
    if "date" not in df.columns:
        raise ValueError("CSV 파일에는 'date' 컬럼이 필요합니다.")

    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")

    if start:
        df = df[df.index >= pd.Timestamp(start)]
    if end:
        df = df[df.index <= pd.Timestamp(end)]

    return _normalize_ohlcv(df)


def get_default_csv_path(ticker: str) -> Path:
    sanitized = ticker.replace("/", "_").replace(".", "_")
    return DEFAULT_DATA_DIR / f"{sanitized}.csv"


def save_ohlcv_to_csv(df: pd.DataFrame, csv_path: str | Path) -> Path:
    output_path = Path(csv_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    export_df = df.reset_index().copy()
    export_df["date"] = pd.to_datetime(export_df["date"]).dt.strftime("%Y-%m-%d")
    export_df.to_csv(output_path, index=False, encoding="utf-8-sig")
    return output_path


def download_and_cache_ohlcv(
    ticker: str,
    period: str = "1y",
    interval: str = "1d",
    source: str = "auto",
    csv_path: str = None,
) -> Path:
    if source == "csv":
        raise ValueError("다운로드 저장에는 source=csv를 사용할 수 없습니다.")


    df = fetch_ohlcv(
        ticker=ticker,
        period=period,
        interval=interval,
        source=source,
    )
    target_path = Path(csv_path) if csv_path else get_default_csv_path(ticker)
    return save_ohlcv_to_csv(df, target_path)


def fetch_ohlcv(
    ticker: str,
    start: str = None,
    end: str = None,
    period: str = None,
    interval: str = "1d",
    source: str = "auto",
    csv_path: str = None,
) -> pd.DataFrame:
    """
    OHLCV 데이터 수집.

    Args:
        ticker: 종목 코드 (예: 'AAPL', 'MSFT')
        start: 시작일 'YYYY-MM-DD'
        end: 종료일 'YYYY-MM-DD'
        period: '1y', '6mo', '90d' 등
        interval: '1d' 기본
        source: 'auto', 'alphavantage', 'csv', 'yfinance'
    """
    source = source.lower().strip()
    if source not in SUPPORTED_SOURCES:
        raise ValueError(
            f"지원하지 않는 source입니다: {source}. "
            f"가능한 값: {', '.join(sorted(SUPPORTED_SOURCES))}"
        )

    if source == "csv" and start is None and end is None:
        start, end = None, None
    else:
        start, end = _resolve_date_range(start=start, end=end, period=period)
    api_key = os.getenv("ALPHA_VANTAGE_API_KEY")

    attempted_sources = []
    last_error = None

    if source == "auto":
        # 6자리 숫자 코드(한국 주식)면 pykrx 우선 시도
        krx_code = ticker.split(".")[0]
        is_korean = krx_code.isdigit() and len(krx_code) == 6
        if is_korean:
            providers = ["pykrx"]
        elif api_key:
            providers = ["alphavantage", "yfinance"]
        else:
            providers = ["yfinance"]
    else:
        providers = [source]

    for provider in providers:
        attempted_sources.append(provider)
        try:
            if provider == "pykrx":
                df = _fetch_from_pykrx(
                    ticker=ticker,
                    start=start,
                    end=end,
                )
            elif provider == "alphavantage":
                if interval != "1d":
                    raise ValueError("Alpha Vantage 어댑터는 현재 일봉(1d)만 지원합니다.")
                df = _fetch_from_alpha_vantage(
                    ticker=ticker,
                    start=start,
                    end=end,
                    api_key=api_key,
                )
            elif provider == "csv":
                df = _fetch_from_csv(
                    csv_path=csv_path,
                    start=start,
                    end=end,
                )
            else:
                effective_period = period if provider == "yfinance" else None
                df = _fetch_from_yfinance(
                    ticker=ticker,
                    start=start,
                    end=end,
                    period=effective_period,
                    interval=interval,
                )

            if not df.empty:
                return df
        except Exception as exc:
            last_error = exc

    requested_range = period if period else f"{start} ~ {end}"
    attempted = ", ".join(attempted_sources)
    raise ValueError(
        f"데이터를 가져오지 못했습니다: {ticker} ({requested_range}). "
        f"시도한 소스: {attempted}. 마지막 오류: {last_error}"
    )
