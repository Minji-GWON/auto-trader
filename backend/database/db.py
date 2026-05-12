"""
SQLite 기반 백테스트 결과 영속화 모듈.

DB 파일 위치: 프로젝트 루트 auto_trader.db
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

_DB_PATH = Path(__file__).resolve().parents[2] / "auto_trader.db"

_DDL = """
CREATE TABLE IF NOT EXISTS backtest_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT    NOT NULL,
    start_date      TEXT,
    end_date        TEXT,
    period          TEXT,
    initial_capital REAL,
    rsi_oversold    REAL,
    rsi_overbought  REAL,
    rsi_period      INTEGER,
    bb_period       INTEGER,
    bb_std_dev      REAL,
    ma_short        INTEGER,
    ma_long         INTEGER,
    strategy        TEXT    NOT NULL DEFAULT 'bb_rsi',
    strategy_params TEXT,
    total_return_pct REAL,
    win_rate        REAL,
    mdd_pct         REAL,
    trade_count     INTEGER,
    avg_hold_days   REAL,
    final_capital   REAL,
    run_at          TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS trades (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       INTEGER NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
    entry_date   TEXT    NOT NULL,
    exit_date    TEXT    NOT NULL,
    entry_price  REAL    NOT NULL,
    exit_price   REAL    NOT NULL,
    shares       INTEGER NOT NULL,
    pnl          REAL    NOT NULL,
    pnl_pct      REAL    NOT NULL,
    hold_days    INTEGER NOT NULL,
    exit_reason  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_trades_run_id ON trades(run_id);

CREATE TABLE IF NOT EXISTS parameter_sweep_results (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date         TEXT    NOT NULL,
    ticker           TEXT    NOT NULL,
    rsi_oversold     REAL    NOT NULL,
    rsi_overbought   REAL    NOT NULL,
    ma_short         INTEGER NOT NULL,
    ma_long          INTEGER NOT NULL,
    bb_period        INTEGER NOT NULL,
    total_return_pct REAL    NOT NULL,
    mdd_pct          REAL    NOT NULL,
    win_rate         REAL    NOT NULL,
    trade_count      INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sweep_ticker ON parameter_sweep_results(ticker);

CREATE TABLE IF NOT EXISTS batch_results (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date         TEXT    NOT NULL,
    ticker           TEXT    NOT NULL,
    total_return_pct REAL    NOT NULL,
    mdd_pct          REAL    NOT NULL,
    win_rate         REAL    NOT NULL,
    trade_count      INTEGER NOT NULL,
    avg_hold_days    REAL    NOT NULL,
    final_capital    REAL    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_batch_run_date ON batch_results(run_date);

CREATE TABLE IF NOT EXISTS positions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker       TEXT    NOT NULL,
    name         TEXT,
    entry_price  REAL    NOT NULL,
    shares       INTEGER NOT NULL,
    entry_date   TEXT    NOT NULL,
    stop_loss    REAL,
    take_profit  REAL,
    status       TEXT    NOT NULL DEFAULT 'open',
    exit_price   REAL,
    exit_date    TEXT,
    exit_reason  TEXT,
    memo         TEXT,
    created_at   TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrate_strategy_columns(conn: sqlite3.Connection) -> None:
    """backtest_runs에 strategy / strategy_params 컬럼이 없으면 추가 (기존 row는 'bb_rsi'로 백필).

    SQLite의 ALTER TABLE ADD COLUMN ... DEFAULT 'X' 는 기존 row에도 디폴트값을 채운다.
    """
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(backtest_runs)")}
    if "strategy" not in existing:
        conn.execute(
            "ALTER TABLE backtest_runs ADD COLUMN strategy TEXT NOT NULL DEFAULT 'bb_rsi'"
        )
    if "strategy_params" not in existing:
        conn.execute("ALTER TABLE backtest_runs ADD COLUMN strategy_params TEXT")


def init_db() -> None:
    """테이블과 인덱스를 생성한다 (이미 있으면 건너뜀)."""
    with _connect() as conn:
        conn.executescript(_DDL)
        _migrate_strategy_columns(conn)


def save_backtest_run(
    ticker: str,
    start_date: Optional[str],
    end_date: Optional[str],
    params: dict,
    result_dict: dict,
) -> int:
    """
    백테스트 실행 결과와 개별 거래 내역을 저장하고 run_id를 반환한다.

    Args:
        ticker: 종목 코드
        start_date: 시작일 (ISO-8601 문자열, 없으면 None)
        end_date: 종료일 (ISO-8601 문자열, 없으면 None)
        params: run_backtest() 에 전달한 파라미터 딕셔너리
        result_dict: run_backtest() 반환값

    Returns:
        저장된 backtest_runs.id
    """
    run_at = datetime.now(timezone.utc).isoformat()
    trades_df: pd.DataFrame = result_dict["trades_df"]
    strategy = params.get("strategy", "bb_rsi")
    strategy_params = params.get("strategy_params")
    strategy_params_json = (
        json.dumps(strategy_params, ensure_ascii=False)
        if strategy_params is not None
        else None
    )

    with _connect() as conn:
        cursor = conn.execute(
            """INSERT INTO backtest_runs
               (ticker, start_date, end_date, period, initial_capital,
                rsi_oversold, rsi_overbought, rsi_period, bb_period, bb_std_dev,
                ma_short, ma_long, strategy, strategy_params,
                total_return_pct, win_rate, mdd_pct,
                trade_count, avg_hold_days, final_capital, run_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                ticker,
                start_date,
                end_date,
                params.get("period"),
                params.get("initial_capital"),
                params.get("rsi_oversold"),
                params.get("rsi_overbought"),
                params.get("rsi_period"),
                params.get("bb_period"),
                params.get("bb_std_dev"),
                params.get("ma_short"),
                params.get("ma_long"),
                strategy,
                strategy_params_json,
                result_dict["total_return_pct"],
                result_dict["win_rate"],
                result_dict["mdd_pct"],
                result_dict["trade_count"],
                result_dict["avg_hold_days"],
                result_dict["final_capital"],
                run_at,
            ),
        )
        run_id = cursor.lastrowid

        if not trades_df.empty:
            rows = [
                (
                    run_id,
                    str(row["entry_date"]),
                    str(row["exit_date"]),
                    row["entry_price"],
                    row["exit_price"],
                    int(row["shares"]),
                    row["pnl"],
                    row["pnl_pct"],
                    int(row["hold_days"]),
                    row["exit_reason"],
                )
                for _, row in trades_df.iterrows()
            ]
            conn.executemany(
                """INSERT INTO trades
                   (run_id, entry_date, exit_date, entry_price, exit_price,
                    shares, pnl, pnl_pct, hold_days, exit_reason)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                rows,
            )

    return run_id


def get_backtest_history(ticker: Optional[str] = None) -> list[dict]:
    """
    백테스트 실행 기록을 최신순으로 반환한다 (trades 제외).

    Args:
        ticker: 특정 종목으로 필터링. None이면 전체 반환.
    """
    sql = "SELECT * FROM backtest_runs"
    params: tuple = ()
    if ticker:
        sql += " WHERE ticker = ?"
        params = (ticker,)
    sql += " ORDER BY run_at DESC"

    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def save_parameter_sweep(
    sweep_df: pd.DataFrame,
    run_date: str,
    ticker: str,
) -> None:
    """
    파라미터 스윕 결과 전체를 저장한다.

    Args:
        sweep_df: parameter_sweep.py 의 summary DataFrame
        run_date: 실행 시각 (ISO-8601 UTC 문자열)
        ticker: 대상 종목 코드
    """
    rows = [
        (
            run_date,
            ticker,
            row["rsi_oversold"],
            row["rsi_overbought"],
            int(row["ma_short"]),
            int(row["ma_long"]),
            int(row["bb_period"]),
            row["total_return_pct"],
            row["mdd_pct"],
            row["win_rate"],
            int(row["trade_count"]),
        )
        for _, row in sweep_df.iterrows()
    ]
    with _connect() as conn:
        conn.executemany(
            """INSERT INTO parameter_sweep_results
               (run_date, ticker, rsi_oversold, rsi_overbought, ma_short, ma_long,
                bb_period, total_return_pct, mdd_pct, win_rate, trade_count)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )


def get_best_params(ticker: str) -> Optional[dict]:
    """
    해당 종목의 파라미터 스윕 결과 중 total_return_pct 최고 조합을 반환한다.
    데이터가 없으면 None 반환.
    """
    with _connect() as conn:
        row = conn.execute(
            """SELECT rsi_oversold, rsi_overbought, ma_short, ma_long, bb_period,
                      total_return_pct, mdd_pct, win_rate, trade_count
               FROM parameter_sweep_results
               WHERE ticker = ?
               ORDER BY total_return_pct DESC
               LIMIT 1""",
            (ticker,),
        ).fetchone()
    return dict(row) if row else None


def add_position(
    ticker: str,
    entry_price: float,
    shares: int,
    entry_date: str,
    name: str = "",
    stop_loss: float = None,
    take_profit: float = None,
    memo: str = "",
) -> int:
    """
    매수한 종목을 포지션으로 등록하고 position_id를 반환한다.

    Args:
        ticker: 종목 코드 (6자리)
        entry_price: 매수가
        shares: 매수 수량
        entry_date: 매수일 (YYYY-MM-DD)
        stop_loss: 손절가 (None이면 entry_price * 0.97)
        take_profit: 익절가 (None이면 entry_price * 1.06)
    """
    if stop_loss is None:
        stop_loss = round(entry_price * 0.97, 0)
    if take_profit is None:
        take_profit = round(entry_price * 1.06, 0)

    created_at = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        cursor = conn.execute(
            """INSERT INTO positions
               (ticker, name, entry_price, shares, entry_date,
                stop_loss, take_profit, status, memo, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (ticker, name, entry_price, shares, entry_date,
             stop_loss, take_profit, "open", memo, created_at),
        )
    return cursor.lastrowid


def get_open_positions() -> list[dict]:
    """현재 보유 중인 포지션 목록을 반환한다."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM positions WHERE status = 'open' ORDER BY entry_date DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def close_position(
    position_id: int,
    exit_price: float,
    exit_date: str,
    exit_reason: str = "수동매도",
) -> None:
    """포지션을 청산(매도) 처리한다."""
    with _connect() as conn:
        conn.execute(
            """UPDATE positions
               SET status='closed', exit_price=?, exit_date=?, exit_reason=?
               WHERE id=?""",
            (exit_price, exit_date, exit_reason, position_id),
        )


def update_position(
    position_id: int,
    entry_price: float = None,
    shares: int = None,
    entry_date: str = None,
    stop_loss: float = None,
    take_profit: float = None,
    memo: str = None,
) -> None:
    """보유 포지션의 정보를 수정한다. None인 항목은 변경하지 않음."""
    fields, values = [], []
    if entry_price is not None:
        fields.append("entry_price=?"); values.append(entry_price)
    if shares is not None:
        fields.append("shares=?"); values.append(shares)
    if entry_date is not None:
        fields.append("entry_date=?"); values.append(entry_date)
    if stop_loss is not None:
        fields.append("stop_loss=?"); values.append(stop_loss)
    if take_profit is not None:
        fields.append("take_profit=?"); values.append(take_profit)
    if memo is not None:
        fields.append("memo=?"); values.append(memo)
    if not fields:
        return
    values.append(position_id)
    with _connect() as conn:
        conn.execute(f"UPDATE positions SET {', '.join(fields)} WHERE id=?", values)


def delete_position(position_id: int) -> None:
    """포지션을 DB에서 완전 삭제한다."""
    with _connect() as conn:
        conn.execute("DELETE FROM positions WHERE id=?", (position_id,))


def get_position_history() -> list[dict]:
    """전체 포지션 이력 (open + closed) 을 반환한다."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM positions ORDER BY entry_date DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def save_batch_results(batch_df: pd.DataFrame, run_date: str) -> None:
    """
    일괄 백테스트 결과를 저장한다.

    Args:
        batch_df: batch_backtest.py 의 summary_df DataFrame
        run_date: 실행 시각 (ISO-8601 UTC 문자열)
    """
    rows = [
        (
            run_date,
            row["ticker"],
            row["total_return_pct"],
            row["mdd_pct"],
            row["win_rate"],
            int(row["trade_count"]),
            row["avg_hold_days"],
            row["final_capital"],
        )
        for _, row in batch_df.iterrows()
    ]
    with _connect() as conn:
        conn.executemany(
            """INSERT INTO batch_results
               (run_date, ticker, total_return_pct, mdd_pct, win_rate,
                trade_count, avg_hold_days, final_capital)
               VALUES (?,?,?,?,?,?,?,?)""",
            rows,
        )
