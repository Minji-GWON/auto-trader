"""
애널리스트 컨센서스 목표주가 + 투자의견.

목표주가: yfinance (Yahoo Finance) — 무료, API 키 불필요
투자의견 분포: Finnhub 무료 티어 (60 req/min)

환경변수: FINNHUB_API_KEY
"""

import os
import requests

FINNHUB_BASE = "https://finnhub.io/api/v1"


def get_price_target_yf(ticker: str) -> dict:
    """
    yfinance(Yahoo Finance)로 컨센서스 목표주가 조회. API 키 불필요.

    Returns:
        {
            "mean":     float,
            "high":     float,
            "low":      float,
            "analysts": int,
            "rating":   str,   # "strong_buy" | "buy" | "hold" | "sell" | "strong_sell"
            "error":    str|None
        }
    """
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        mean = info.get("targetMeanPrice")
        if not mean:
            return {"error": "데이터 없음"}
        return {
            "mean":     round(float(mean), 2),
            "high":     round(float(info.get("targetHighPrice") or mean), 2),
            "low":      round(float(info.get("targetLowPrice") or mean), 2),
            "analysts": int(info.get("numberOfAnalystOpinions") or 0),
            "rating":   info.get("recommendationKey", ""),
            "error":    None,
        }
    except Exception as e:
        return {"error": str(e)}


def get_price_target(ticker: str, api_key: str = "") -> dict:
    """
    Finnhub 컨센서스 목표주가 조회.

    Returns:
        {
            "mean":     float,   # 평균 목표주가
            "high":     float,   # 최고 목표주가
            "low":      float,   # 최저 목표주가
            "analysts": int,     # 참여 분석가 수
            "error":    str|None
        }
    """
    key = api_key or os.getenv("FINNHUB_API_KEY", "")
    if not key:
        return {"error": "FINNHUB_API_KEY 없음"}

    try:
        r = requests.get(
            f"{FINNHUB_BASE}/stock/price-target",
            params={"symbol": ticker, "token": key},
            timeout=5,
        )
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}"}

        data = r.json()
        mean = data.get("targetMean") or data.get("targetMedian")
        if not mean:
            return {"error": "데이터 없음"}

        return {
            "mean":     round(float(mean), 2),
            "high":     round(float(data.get("targetHigh") or mean), 2),
            "low":      round(float(data.get("targetLow") or mean), 2),
            "analysts": int(data.get("numberOfAnalysts") or 0),
            "error":    None,
        }
    except Exception as e:
        return {"error": str(e)}


def get_recommendation(ticker: str, api_key: str = "") -> dict:
    """
    Finnhub 최근 투자의견 분포 조회.

    Returns:
        {
            "strong_buy":  int,
            "buy":         int,
            "hold":        int,
            "sell":        int,
            "strong_sell": int,
            "period":      str,   # e.g. "2025-03-01"
            "consensus":   str,   # "매수우세" | "중립" | "매도우세"
            "error":       str|None
        }
    """
    key = api_key or os.getenv("FINNHUB_API_KEY", "")
    if not key:
        return {"error": "FINNHUB_API_KEY 없음"}

    try:
        r = requests.get(
            f"{FINNHUB_BASE}/stock/recommendation",
            params={"symbol": ticker, "token": key},
            timeout=5,
        )
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}"}

        data = r.json()
        if not data:
            return {"error": "데이터 없음"}

        latest = data[0]
        sb  = int(latest.get("strongBuy",   0))
        b   = int(latest.get("buy",         0))
        h   = int(latest.get("hold",        0))
        s   = int(latest.get("sell",        0))
        ss  = int(latest.get("strongSell",  0))
        total = sb + b + h + s + ss

        if total == 0:
            consensus = "없음"
        elif (sb + b) / total >= 0.55:
            consensus = "매수우세"
        elif (s + ss) / total >= 0.35:
            consensus = "매도우세"
        else:
            consensus = "중립"

        return {
            "strong_buy":  sb,
            "buy":         b,
            "hold":        h,
            "sell":        s,
            "strong_sell": ss,
            "period":      latest.get("period", ""),
            "consensus":   consensus,
            "error":       None,
        }
    except Exception as e:
        return {"error": str(e)}


def get_analyst_summary(ticker: str, current_price: float, api_key: str = "") -> dict:
    """
    목표주가(yfinance) + 투자의견 분포(Finnhub)를 합쳐서 반환.

    Returns:
        {
            "target_mean":   float | None,
            "target_high":   float | None,
            "target_low":    float | None,
            "analysts":      int,
            "upside_pct":    float | None,
            "strong_buy":    int,
            "buy":           int,
            "hold":          int,
            "sell":          int,
            "strong_sell":   int,
            "consensus":     str,
            "error":         str | None
        }
    """
    pt  = get_price_target_yf(ticker)
    rec = get_recommendation(ticker, api_key)

    if pt.get("error") and rec.get("error"):
        return {"error": pt.get("error")}

    upside = None
    if not pt.get("error") and current_price and current_price > 0:
        upside = round((pt["mean"] / current_price - 1) * 100, 1)

    return {
        "target_mean":  pt.get("mean"),
        "target_high":  pt.get("high"),
        "target_low":   pt.get("low"),
        "analysts":     pt.get("analysts", 0),
        "upside_pct":   upside,
        "strong_buy":   rec.get("strong_buy", 0),
        "buy":          rec.get("buy", 0),
        "hold":         rec.get("hold", 0),
        "sell":         rec.get("sell", 0),
        "strong_sell":  rec.get("strong_sell", 0),
        "consensus":    rec.get("consensus", "없음"),
        "error":        None,
    }
