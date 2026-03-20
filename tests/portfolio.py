"""
내 보유 포지션을 등록/조회/청산하는 CLI.

사용법:
    # 매수 등록
    python tests/portfolio.py add --ticker 086900 --price 107600 --shares 10

    # 보유 목록 조회
    python tests/portfolio.py list

    # 매도(청산) 처리
    python tests/portfolio.py sell --id 1 --price 115000

    # 전체 이력 (청산 포함)
    python tests/portfolio.py history
"""

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.database import init_db, add_position, get_open_positions, close_position, get_position_history
from backend.stocks import get_name


def cmd_add(args):
    init_db()
    name = get_name(args.ticker)
    pos_id = add_position(
        ticker=args.ticker,
        entry_price=args.price,
        shares=args.shares,
        entry_date=args.date or date.today().isoformat(),
        name=name,
        stop_loss=args.stop_loss,
        take_profit=args.take_profit,
        memo=args.memo or "",
    )
    cost = args.price * args.shares
    sl = args.stop_loss or round(args.price * 0.97)
    tp = args.take_profit or round(args.price * 1.06)
    print(f"\n✅ 포지션 등록 완료 (ID: {pos_id})")
    print(f"   종목  : {args.ticker} {name}")
    print(f"   매수가: {args.price:,}원 × {args.shares}주 = {cost:,}원")
    print(f"   손절가: {sl:,}원  익절가: {tp:,}원")


def cmd_list(args):
    init_db()
    positions = get_open_positions()
    if not positions:
        print("보유 포지션 없음")
        return

    print(f"\n{'ID':>3} {'종목':>10} {'종목명':<12} {'매수가':>9} {'수량':>5} {'매수일':>12} {'손절가':>9} {'익절가':>9}")
    print("-" * 80)
    for p in positions:
        print(f"{p['id']:>3} {p['ticker']:>10} {(p['name'] or ''):12s} "
              f"{p['entry_price']:>9,.0f} {p['shares']:>5} {p['entry_date']:>12} "
              f"{p['stop_loss']:>9,.0f} {p['take_profit']:>9,.0f}")


def cmd_sell(args):
    init_db()
    positions = {p["id"]: p for p in get_open_positions()}
    if args.id not in positions:
        print(f"ID {args.id}에 해당하는 열린 포지션이 없습니다.")
        sys.exit(1)

    pos = positions[args.id]
    exit_date = args.date or date.today().isoformat()
    close_position(args.id, args.price, exit_date, args.reason or "수동매도")

    entry_cost = pos["entry_price"] * pos["shares"]
    exit_proceeds = args.price * pos["shares"]
    pnl = exit_proceeds - entry_cost
    pnl_pct = (args.price / pos["entry_price"] - 1) * 100
    print(f"\n✅ 매도 처리 완료 (ID: {args.id})")
    print(f"   종목  : {pos['ticker']} {pos['name'] or ''}")
    print(f"   매수가: {pos['entry_price']:,}원 → 매도가: {args.price:,}원")
    print(f"   손익  : {pnl:+,.0f}원 ({pnl_pct:+.2f}%)")


def cmd_history(args):
    init_db()
    positions = get_position_history()
    if not positions:
        print("포지션 이력 없음")
        return

    print(f"\n{'ID':>3} {'상태':>6} {'종목':>8} {'종목명':<12} {'매수가':>9} {'매도가':>9} {'손익':>12} {'매수일':>12}")
    print("-" * 85)
    for p in positions:
        pnl_str = ""
        if p["exit_price"]:
            pnl = (p["exit_price"] / p["entry_price"] - 1) * 100
            pnl_str = f"{pnl:+.1f}%"
        print(f"{p['id']:>3} {p['status']:>6} {p['ticker']:>8} {(p['name'] or ''):12s} "
              f"{p['entry_price']:>9,.0f} {(p['exit_price'] or 0):>9,.0f} "
              f"{pnl_str:>12} {p['entry_date']:>12}")


def main():
    parser = argparse.ArgumentParser(description="포트폴리오 관리")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # add
    p_add = sub.add_parser("add", help="매수 등록")
    p_add.add_argument("--ticker", required=True, help="종목코드 (6자리)")
    p_add.add_argument("--price", type=float, required=True, help="매수가")
    p_add.add_argument("--shares", type=int, required=True, help="수량")
    p_add.add_argument("--date", help="매수일 (기본: 오늘, YYYY-MM-DD)")
    p_add.add_argument("--stop-loss", type=float, help="손절가 (기본: 매수가×0.97)")
    p_add.add_argument("--take-profit", type=float, help="익절가 (기본: 매수가×1.06)")
    p_add.add_argument("--memo", help="메모")

    # list
    sub.add_parser("list", help="보유 목록")

    # sell
    p_sell = sub.add_parser("sell", help="매도 처리")
    p_sell.add_argument("--id", type=int, required=True, help="포지션 ID")
    p_sell.add_argument("--price", type=float, required=True, help="매도가")
    p_sell.add_argument("--date", help="매도일 (기본: 오늘)")
    p_sell.add_argument("--reason", help="매도 사유 (기본: 수동매도)")

    # history
    sub.add_parser("history", help="전체 이력")

    args = parser.parse_args()
    {"add": cmd_add, "list": cmd_list, "sell": cmd_sell, "history": cmd_history}[args.cmd](args)


if __name__ == "__main__":
    main()
