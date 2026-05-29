"""
텔레그램 Bot API 기반 알림 모듈.

사용하려면 .env에 다음 두 항목을 설정하세요:
    TELEGRAM_BOT_TOKEN=...
    TELEGRAM_CHAT_ID=...

설정하지 않으면 모든 메서드는 아무것도 하지 않습니다 (silent no-op).
"""

import os
import re
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"
_TIMEOUT = 5  # 초


def _escape_md(text) -> str:
    """MarkdownV2 특수문자 이스케이프."""
    return re.sub(r'([_\*\[\]()~`>#+\-=|{}.!])', r'\\\1', str(text))


_STRATEGY_NAME_KO = {
    "bb_rsi": "BB+RSI",
    "vb": "변동성돌파",
}


def _format_strategy_label(strategy: str, strategy_params: dict = None) -> str:
    """전략 코드 → 알림용 한글 라벨. 핵심 파라미터는 괄호로 부기."""
    base = _STRATEGY_NAME_KO.get(strategy, strategy)
    if not strategy_params:
        return base
    if strategy == "vb":
        k = strategy_params.get("vb_k")
        if k is not None:
            return f"{base} (K={k})"
    return base


class TelegramNotifier:
    """텔레그램으로 백테스트 결과 및 매매 시그널을 전송한다."""

    def __init__(self, chat_id: str = None):
        """
        Args:
            chat_id: 전송할 채널 ID. None이면 .env의 TELEGRAM_CHAT_ID를 사용한다.
                     별도 채널로 보내고 싶을 때 명시적으로 다른 ID를 전달.
        """
        self._token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        env_chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        self._chat_id = (chat_id or env_chat).strip() if (chat_id or env_chat) else ""
        self._enabled = bool(self._token and self._chat_id)
        self._url = _API_BASE.format(token=self._token)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_message(self, text: str) -> None:
        """MarkdownV2 형식의 텍스트를 전송한다. 모든 다른 메서드가 이를 호출한다."""
        if not self._enabled:
            return
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "MarkdownV2",
        }
        try:
            resp = requests.post(self._url, json=payload, timeout=_TIMEOUT)
            if not resp.ok:
                print(
                    f"[TelegramNotifier] WARNING: HTTP {resp.status_code} — {resp.text}",
                    file=sys.stderr,
                )
        except requests.RequestException as exc:
            print(f"[TelegramNotifier] WARNING: request failed — {exc}", file=sys.stderr)

    def send_backtest_result(
        self,
        ticker: str,
        result_dict: dict,
        params: dict = None,
    ) -> None:
        """
        백테스트 결과 요약을 전송한다.

        Args:
            ticker: 종목 코드
            result_dict: run_backtest() 반환값
            params: run_backtest()에 전달한 파라미터 딕셔너리 (period, initial_capital 등)
        """
        if not self._enabled:
            return
        if params is None:
            params = {}

        period = params.get("period", "?")
        initial_capital = params.get("initial_capital", 0)
        strategy = params.get("strategy", "bb_rsi")
        strategy_label = _format_strategy_label(strategy, params.get("strategy_params"))
        total_return_pct = result_dict.get("total_return_pct", 0.0)
        mdd_pct = result_dict.get("mdd_pct", 0.0)
        trade_count = result_dict.get("trade_count", 0)
        win_rate = result_dict.get("win_rate", 0.0)
        final_capital = result_dict.get("final_capital", 0.0)

        ret_str = f"+{total_return_pct:.2f}%" if total_return_pct >= 0 else f"{total_return_pct:.2f}%"
        mdd_str = f"+{mdd_pct:.2f}%" if mdd_pct >= 0 else f"{mdd_pct:.2f}%"

        text = (
            f"📊 *백테스트 결과* — {_escape_md(ticker)}\n"
            f"🎯 전략: {_escape_md(strategy_label)}\n"
            f"기간: {_escape_md(period)}  \\|  초기자본: {_escape_md(f'{initial_capital:,.0f}')}원\n"
            f"\n"
            f"✅ 수익률: {_escape_md(ret_str)}\n"
            f"📉 MDD: {_escape_md(mdd_str)}\n"
            f"🔄 거래횟수: {_escape_md(f'{trade_count}회')}  \\|  승률: {_escape_md(f'{win_rate:.1f}%')}\n"
            f"💰 최종자본: {_escape_md(f'{final_capital:,.0f}')}원"
        )
        self.send_message(text)

    def send_trade_signal(
        self,
        ticker: str,
        signal_type: str,
        price: float,
        reason: str,
    ) -> None:
        """
        매수 또는 매도 시그널을 전송한다.

        Args:
            ticker: 종목 코드
            signal_type: "BUY" 또는 "SELL" (또는 "매수"/"매도")
            price: 체결 가격
            reason: 사유 문자열 (예: "시그널", "익절 (+3.72%)")
        """
        if not self._enabled:
            return

        is_buy = str(signal_type).upper() in ("BUY", "매수")
        icon = "🟢" if is_buy else "🔴"
        label = "매수" if is_buy else "매도"

        text = (
            f"{icon} *{label}* — {_escape_md(ticker)}\n"
            f"가격: {_escape_md(f'{price:,.0f}')}원\n"
            f"사유: {_escape_md(reason)}"
        )
        self.send_message(text)

    def send_daily_report(self, summary_rows: list, strategy: str = None) -> None:
        """
        일괄 백테스트 결과 테이블을 전송한다.

        Args:
            summary_rows: batch_backtest.py 의 summary_rows 리스트
                          각 요소: {ticker, total_return_pct, mdd_pct, trade_count, ...}
            strategy: 전략 코드(bb_rsi/vb). 주어지면 헤더에 표시.
        """
        if not self._enabled:
            return
        if not summary_rows:
            return

        if strategy:
            header = f"📋 *일괄 백테스트 결과* — {_escape_md(_STRATEGY_NAME_KO.get(strategy, strategy))}"
        else:
            header = "📋 *일괄 백테스트 결과*"
        lines = [header, "종목 \\| 수익률 \\| MDD \\| 거래"]
        for row in summary_rows:
            ticker = row.get("ticker", "?")
            ret = row.get("total_return_pct", 0.0)
            mdd = row.get("mdd_pct", 0.0)
            trades = row.get("trade_count", 0)
            ret_str = f"+{ret:.1f}%" if ret >= 0 else f"{ret:.1f}%"
            mdd_str = f"+{mdd:.1f}%" if mdd >= 0 else f"{mdd:.1f}%"
            lines.append(
                f"{_escape_md(ticker)} \\| "
                f"{_escape_md(ret_str)} \\| "
                f"{_escape_md(mdd_str)} \\| "
                f"{_escape_md(f'{trades}회')}"
            )

        self.send_message("\n".join(lines))
