"""
백테스트 실행 스크립트.

사용법:
    python tests/backtest.py
    python tests/backtest.py --ticker 035720.KS --period 2y
"""

import sys
import argparse
from pathlib import Path
import pandas as pd

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.data_fetcher.fetcher import fetch_ohlcv, get_default_csv_path
from backend.indicators.calculator import add_all_indicators
from backend.strategy.signal import generate_signals, BUY, SELL, HOLD
from backend.risk_manager.manager import RiskManager
from backend.database import init_db, save_backtest_run

# 거래 비용 (편도)
COMMISSION_RATE = 0.00015   # 증권사 수수료 0.015%
SLIPPAGE_RATE = 0.001       # 슬리피지 0.1%
TOTAL_COST_RATE = COMMISSION_RATE + SLIPPAGE_RATE  # 매수/매도 각각 적용


def run_backtest(
    ticker: str,
    period: str = "1y",
    initial_capital: float = 10_000_000,
    rsi_oversold: float = 30,
    rsi_overbought: float = 70,
    data_source: str = "auto",
    csv_path: str = None,
    rsi_period: int = 14,
    bb_period: int = 20,
    bb_std_dev: float = 2.0,
    ma_short: int = 20,
    ma_long: int = 60,
    swing_mode: bool = False,
    verbose: bool = True,
) -> dict:
    """
    백테스트 실행 후 결과 딕셔너리 반환.

    Returns:
        {
            total_return_pct, win_rate, mdd_pct,
            trade_count, avg_hold_days,
            final_capital, trades_df
        }
    """
    risk = RiskManager()
    resolved_csv_path = resolve_csv_path(ticker, data_source, csv_path)

    # 1. 데이터 수집
    if verbose:
        print(f"\n[1/4] 데이터 수집: {ticker} ({period}, source={data_source})")
    df = fetch_ohlcv(
        ticker=ticker,
        period=period,
        source=data_source,
        csv_path=resolved_csv_path,
    )
    if verbose:
        print(f"      {len(df)}개 봉 수집 완료 ({df.index[0].date()} ~ {df.index[-1].date()})")

    # 2. 지표 계산
    if verbose:
        print("[2/4] 지표 계산 중...")
    df = add_all_indicators(
        df,
        rsi_period=rsi_period,
        bb_period=bb_period,
        bb_std_dev=bb_std_dev,
        ma_short=ma_short,
        ma_long=ma_long,
    )
    df = generate_signals(df, rsi_oversold=rsi_oversold, rsi_overbought=rsi_overbought, swing_mode=swing_mode)
    df = df.dropna()
    if df.empty:
        raise ValueError(
            "지표 계산 후 사용할 데이터가 없습니다. "
            "기간을 늘리거나 지표 기간(ma_long, bb_period 등)을 더 짧게 설정하세요."
        )

    # 3. 백테스트 시뮬레이션
    if verbose:
        print("[3/4] 백테스트 시뮬레이션 중...")
    capital = initial_capital
    position = 0          # 보유 주식 수
    entry_price = 0.0
    entry_date = None
    daily_loss = 0.0
    last_date = None

    trades = []
    equity_curve = [initial_capital]

    for date, row in df.iterrows():
        price = row["close"]
        signal = row["signal"]

        # 날짜 바뀌면 일일 손실 리셋
        if last_date is None or date.date() != last_date:
            daily_loss = 0.0
            last_date = date.date()

        current_equity = capital + position * price
        equity_curve.append(current_equity)

        # --- 포지션 없을 때: 매수 검토 ---
        if position == 0 and signal == BUY:
            if risk.check_daily_limit(daily_loss):
                continue  # 일일 한도 초과 → 매수 안 함

            shares = risk.position_size(capital, price)
            if shares == 0:
                continue

            cost = shares * price * (1 + TOTAL_COST_RATE)
            if cost > capital:
                shares = int(capital / (price * (1 + TOTAL_COST_RATE)))
                cost = shares * price * (1 + TOTAL_COST_RATE)

            if shares > 0:
                capital -= cost
                position = shares
                entry_price = price
                entry_date = date

        # --- 포지션 있을 때: 매도 검토 ---
        elif position > 0:
            should_sell = False
            exit_reason = ""

            if risk.check_stop_loss(entry_price, price):
                should_sell = True
                exit_reason = "손절"
            elif risk.check_take_profit(entry_price, price):
                should_sell = True
                exit_reason = "익절"
            elif signal == SELL:
                should_sell = True
                exit_reason = "시그널"

            if should_sell:
                proceeds = position * price * (1 - TOTAL_COST_RATE)
                pnl = proceeds - (position * entry_price * (1 + TOTAL_COST_RATE))
                daily_loss += min(pnl, 0)
                capital += proceeds

                hold_days = (date - entry_date).days
                trades.append({
                    "entry_date": entry_date,
                    "exit_date": date,
                    "entry_price": round(entry_price, 2),
                    "exit_price": round(price, 2),
                    "shares": position,
                    "pnl": round(pnl, 0),
                    "pnl_pct": round((price / entry_price - 1) * 100, 2),
                    "hold_days": hold_days,
                    "exit_reason": exit_reason,
                })

                position = 0
                entry_price = 0.0
                entry_date = None

    # 미청산 포지션 강제 청산 (마지막 종가)
    if position > 0:
        last_price = df["close"].iloc[-1]
        last_date_dt = df.index[-1]
        proceeds = position * last_price * (1 - TOTAL_COST_RATE)
        pnl = proceeds - (position * entry_price * (1 + TOTAL_COST_RATE))
        capital += proceeds
        hold_days = (last_date_dt - entry_date).days
        trades.append({
            "entry_date": entry_date,
            "exit_date": last_date_dt,
            "entry_price": round(entry_price, 2),
            "exit_price": round(last_price, 2),
            "shares": position,
            "pnl": round(pnl, 0),
            "pnl_pct": round((last_price / entry_price - 1) * 100, 2),
            "hold_days": hold_days,
            "exit_reason": "기간종료",
        })

    # 4. 결과 계산
    trades_df = pd.DataFrame(trades)
    final_capital = capital
    total_return_pct = (final_capital / initial_capital - 1) * 100

    if len(trades_df) > 0:
        win_rate = (trades_df["pnl"] > 0).mean() * 100
        avg_hold_days = trades_df["hold_days"].mean()
    else:
        win_rate = 0.0
        avg_hold_days = 0.0

    # MDD 계산
    equity_series = pd.Series(equity_curve, dtype="float64")
    rolling_max = equity_series.cummax()
    drawdown = (equity_series - rolling_max) / rolling_max
    mdd_pct = drawdown.min() * 100 if not drawdown.empty else 0.0

    return {
        "total_return_pct": total_return_pct,
        "win_rate": win_rate,
        "mdd_pct": mdd_pct,
        "trade_count": len(trades_df),
        "avg_hold_days": avg_hold_days,
        "final_capital": final_capital,
        "trades_df": trades_df,
    }


def print_report(ticker: str, result: dict, initial_capital: float):
    print("\n" + "=" * 55)
    print(f"  백테스트 결과: {ticker}")
    print("=" * 55)
    print(f"  초기 자본      : {initial_capital:>15,.0f} 원")
    print(f"  최종 자본      : {result['final_capital']:>15,.0f} 원")
    print(f"  총 수익률      : {result['total_return_pct']:>+14.2f} %")
    print(f"  최대 낙폭(MDD) : {result['mdd_pct']:>+14.2f} %")
    print(f"  총 거래 횟수   : {result['trade_count']:>15} 회")
    print(f"  승률           : {result['win_rate']:>14.1f} %")
    print(f"  평균 보유기간  : {result['avg_hold_days']:>14.1f} 일")
    print("=" * 55)

    trades_df = result["trades_df"]
    if len(trades_df) > 0:
        print("\n[거래 내역]")
        display_cols = ["entry_date", "exit_date", "entry_price", "exit_price", "pnl_pct", "exit_reason"]
        print(trades_df[display_cols].to_string(index=False))

        # CSV 저장
        results_dir = Path(__file__).parent / "results"
        results_dir.mkdir(exist_ok=True)
        csv_path = results_dir / f"trades_{ticker.replace('.', '_')}.csv"
        trades_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        print(f"\n거래 내역 저장: {csv_path}")
    else:
        print("\n거래 없음 (조건 미충족)")


def resolve_csv_path(ticker: str, data_source: str, csv_path: str = None) -> str | None:
    if csv_path:
        return csv_path
    if data_source != "csv":
        return None

    default_path = get_default_csv_path(ticker)
    if default_path.exists():
        return str(default_path)
    raise ValueError(
        f"CSV 파일을 찾을 수 없습니다: {default_path}. "
        "먼저 데이터를 다운로드하거나 --csv-path를 지정하세요."
    )


def validate_inputs(period: str, capital: float, ma_short: int, ma_long: int):
    if capital <= 0:
        raise ValueError("초기 자본은 0보다 커야 합니다.")
    if not period.strip():
        raise ValueError("기간(period)을 비워둘 수 없습니다.")
    if ma_short <= 0 or ma_long <= 0:
        raise ValueError("이동평균 기간은 0보다 커야 합니다.")
    if ma_short >= ma_long:
        raise ValueError("ma_short는 ma_long보다 작아야 합니다.")


def main():
    parser = argparse.ArgumentParser(description="Auto-Trader 백테스트")
    parser.add_argument("--ticker", default="005930.KS", help="종목 코드 (기본: 삼성전자)")
    parser.add_argument("--period", default="1y", help="기간 (기본: 1y)")
    parser.add_argument("--capital", type=float, default=10_000_000, help="초기 자본 (기본: 1천만원)")
    parser.add_argument("--rsi-oversold", type=float, default=30)
    parser.add_argument("--rsi-overbought", type=float, default=70)
    parser.add_argument("--rsi-period", type=int, default=14)
    parser.add_argument("--bb-period", type=int, default=20)
    parser.add_argument("--bb-std-dev", type=float, default=2.0)
    parser.add_argument("--ma-short", type=int, default=20)
    parser.add_argument("--ma-long", type=int, default=60)
    parser.add_argument("--csv-path", help="source=csv 일 때 사용할 OHLCV CSV 경로")
    parser.add_argument(
        "--source",
        default="auto",
        choices=["auto", "alphavantage", "csv", "yfinance", "pykrx"],
        help="데이터 소스 (기본: auto)",
    )
    args = parser.parse_args()

    validate_inputs(args.period, args.capital, args.ma_short, args.ma_long)

    try:
        result = run_backtest(
            ticker=args.ticker,
            period=args.period,
            initial_capital=args.capital,
            rsi_oversold=args.rsi_oversold,
            rsi_overbought=args.rsi_overbought,
            data_source=args.source,
            csv_path=args.csv_path,
            rsi_period=args.rsi_period,
            bb_period=args.bb_period,
            bb_std_dev=args.bb_std_dev,
            ma_short=args.ma_short,
            ma_long=args.ma_long,
        )
    except ValueError as exc:
        print(f"\n백테스트 실행 실패: {exc}")
        sys.exit(1)

    init_db()
    params = {
        "period": args.period,
        "initial_capital": args.capital,
        "rsi_oversold": args.rsi_oversold,
        "rsi_overbought": args.rsi_overbought,
        "rsi_period": args.rsi_period,
        "bb_period": args.bb_period,
        "bb_std_dev": args.bb_std_dev,
        "ma_short": args.ma_short,
        "ma_long": args.ma_long,
    }
    run_id = save_backtest_run(
        ticker=args.ticker,
        start_date=None,
        end_date=None,
        params=params,
        result_dict=result,
    )
    print(f"DB 저장 완료 (run_id={run_id})")

    from backend.notifier import TelegramNotifier
    TelegramNotifier().send_backtest_result(args.ticker, result, params)

    print_report(args.ticker, result, args.capital)


if __name__ == "__main__":
    main()
