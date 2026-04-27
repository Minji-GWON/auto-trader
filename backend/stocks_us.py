"""
미국 주요 종목 리스트 (S&P500 / NASDAQ 대형주 + 반도체 섹터).
yfinance 티커 기준.
"""

# (ticker, 한글이름)
US_STOCKS: list[tuple[str, str]] = [
    # ── 테크 / 반도체
    ("AAPL",  "애플"),
    ("MSFT",  "마이크로소프트"),
    ("NVDA",  "엔비디아"),
    ("GOOGL", "알파벳"),
    ("AMZN",  "아마존"),
    ("META",  "메타"),
    ("TSLA",  "테슬라"),
    ("AVGO",  "브로드컴"),
    ("ORCL",  "오라클"),
    ("AMD",   "AMD"),
    ("INTC",  "인텔"),
    ("QCOM",  "퀄컴"),
    ("TXN",   "텍사스인스트루먼트"),
    ("AMAT",  "어플라이드머티리얼즈"),
    ("MU",    "마이크론"),
    ("ASML",  "ASML"),
    ("CRM",   "세일즈포스"),
    ("NOW",   "서비스나우"),
    ("ADBE",  "어도비"),
    ("NFLX",  "넷플릭스"),
    ("PLTR",  "팔란티어"),
    # ── 금융
    ("JPM",   "JP모건"),
    ("BAC",   "뱅크오브아메리카"),
    ("WFC",   "웰스파고"),
    ("GS",    "골드만삭스"),
    ("MS",    "모건스탠리"),
    ("V",     "비자"),
    ("MA",    "마스터카드"),
    ("BRK-B", "버크셔해서웨이"),
    # ── 헬스케어
    ("JNJ",   "존슨앤존슨"),
    ("UNH",   "유나이티드헬스"),
    ("LLY",   "일라이릴리"),
    ("ABBV",  "애브비"),
    ("MRK",   "머크"),
    ("PFE",   "화이자"),
    # ── 소비재 / 유통
    ("WMT",   "월마트"),
    ("COST",  "코스트코"),
    ("HD",    "홈디포"),
    ("MCD",   "맥도날드"),
    ("NKE",   "나이키"),
    ("SBUX",  "스타벅스"),
    ("PG",    "P&G"),
    ("KO",    "코카콜라"),
    ("PEP",   "펩시코"),
    # ── 에너지
    ("XOM",   "엑슨모빌"),
    ("CVX",   "셰브론"),
    # ── ETF (시장/섹터 대용)
    ("SPY",   "S&P500 ETF"),
    ("QQQ",   "나스닥100 ETF"),
    ("SOXX",  "반도체 ETF"),
]

# dict: {ticker: {"name": ..., "sector": ...}}
ALL_US_STOCKS: dict[str, dict] = {ticker: {"name": name} for ticker, name in US_STOCKS}


# 반도체 섹터 (프리/애프터마켓 알림용 — 유동성 높은 종목 위주)
SEMI_TICKERS: list[str] = [
    "NVDA",  # 엔비디아
    "AMD",   # AMD
    "AVGO",  # 브로드컴
    "TSM",   # TSMC (ADR)
    "ASML",  # ASML
    "MU",    # 마이크론
    "AMAT",  # 어플라이드머티리얼즈
    "QCOM",  # 퀄컴
    "INTC",  # 인텔
    "ARM",   # ARM
    "SMCI",  # 슈퍼마이크로
    "MRVL",  # 마벨
    "SOXX",  # iShares 반도체 ETF (SOX 추종, 미장 외엔 거래 없음)
    "SMH",   # VanEck 반도체 ETF
]


# 미국 야간 지수선물 (CME GLOBEX, 미장 마감 후 ~ 다음날 프리마켓 전 거래)
# 필라델피아 반도체 지수(SOX)는 선물이 존재하지 않아 제외 — NQ가 가장 가까운 프록시
OVERNIGHT_FUTURES: dict[str, str] = {
    "YM=F":  "다우 선물",
    "NQ=F":  "나스닥 선물",
    "RTY=F": "러셀2000 선물",
}


def get_us_name(ticker: str) -> str:
    return ALL_US_STOCKS.get(ticker, {}).get("name", ticker)
