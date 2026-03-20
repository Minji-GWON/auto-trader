import os
from dotenv import load_dotenv

load_dotenv()


class RiskManager:
    def __init__(
        self,
        stop_loss_pct: float = None,
        take_profit_pct: float = None,
        daily_loss_limit: float = None,
        max_position_size: float = None,
    ):
        self.stop_loss_pct = stop_loss_pct or float(os.getenv("STOP_LOSS_PCT", 0.03))
        self.take_profit_pct = take_profit_pct or float(os.getenv("TAKE_PROFIT_PCT", 0.06))
        self.daily_loss_limit = daily_loss_limit or float(os.getenv("DAILY_LOSS_LIMIT", 300000))
        self.max_position_size = max_position_size or float(os.getenv("MAX_POSITION_SIZE", 0.3))

    def check_stop_loss(self, entry_price: float, current_price: float) -> bool:
        """손절 조건 충족 여부 (entry 대비 하락률 초과)."""
        loss_pct = (current_price - entry_price) / entry_price
        return loss_pct <= -self.stop_loss_pct

    def check_take_profit(self, entry_price: float, current_price: float) -> bool:
        """익절 조건 충족 여부 (entry 대비 상승률 초과)."""
        profit_pct = (current_price - entry_price) / entry_price
        return profit_pct >= self.take_profit_pct

    def check_daily_limit(self, daily_loss: float) -> bool:
        """일일 손실 한도 초과 여부 (daily_loss는 음수 손실금액)."""
        return daily_loss <= -self.daily_loss_limit

    def position_size(self, capital: float, price: float) -> int:
        """
        매수 가능 주식 수 계산.
        자본의 max_position_size 비율 이내에서 최대 주수 반환.
        """
        budget = capital * self.max_position_size
        shares = int(budget // price)
        return max(shares, 0)
