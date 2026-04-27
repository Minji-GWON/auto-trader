"""
미국 NYSE 휴장일 (full-day closure).
선물(CME)은 일부 휴장일에도 거래되지만, 본 프로젝트는 NYSE 기준으로 알림 스킵.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

# NYSE 정규 휴장일 (full close). 조기마감 반차일은 포함하지 않음.
US_MARKET_HOLIDAYS: set[str] = {
    # 2026
    "2026-01-01",  # New Year's Day
    "2026-01-19",  # MLK Day
    "2026-02-16",  # Presidents Day
    "2026-04-03",  # Good Friday
    "2026-05-25",  # Memorial Day
    "2026-06-19",  # Juneteenth
    "2026-07-03",  # Independence Day (observed, Jul 4 is Sat)
    "2026-09-07",  # Labor Day
    "2026-11-26",  # Thanksgiving
    "2026-12-25",  # Christmas
    # 2027
    "2027-01-01",  # New Year's Day
    "2027-01-18",  # MLK Day
    "2027-02-15",  # Presidents Day
    "2027-03-26",  # Good Friday
    "2027-05-31",  # Memorial Day
    "2027-06-18",  # Juneteenth (observed, Jun 19 is Sat)
    "2027-07-05",  # Independence Day (observed, Jul 4 is Sun)
    "2027-09-06",  # Labor Day
    "2027-11-25",  # Thanksgiving
    "2027-12-24",  # Christmas (observed, Dec 25 is Sat)
}


def is_us_market_holiday(now: datetime | None = None) -> bool:
    """미 동부시간 기준 오늘이 NYSE 휴장일이면 True."""
    et = (now or datetime.now(ZoneInfo("America/New_York")))
    return et.strftime("%Y-%m-%d") in US_MARKET_HOLIDAYS
