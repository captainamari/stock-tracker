"""
API v1: Market Overview Endpoints
===================================
Market-level data: pulse, sentiment, sector overview.

Endpoints:
    GET  /api/v1/market/overview     — Combined market overview (pulse + sentiment + sectors)
    GET  /api/v1/market/pulse        — Market Pulse (regime, score, components)
    GET  /api/v1/market/pulse/history — Market Pulse history
    GET  /api/v1/market/sectors      — All sector definitions and current scores
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from lib.db import (
    get_latest_market_pulse,
    get_market_pulse,
    get_latest_momentum_scores,
    get_sector_definitions,
    get_sector_mappings,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/market", tags=["market"])


# ── Response Models ──

class MarketPulseData(BaseModel):
    date: str
    regime: str
    composite_score: float
    component_scores: Dict[str, Any] = {}
    spy_price: Optional[float] = None
    vix_value: Optional[float] = None
    distribution_days: Dict[str, Any] = {}


class SentimentData(BaseModel):
    spy: Optional[Dict[str, Any]] = None
    qqq: Optional[Dict[str, Any]] = None
    mood: str = "N/A"
    tech_vs_broad: Optional[float] = None


class SectorOverview(BaseModel):
    sector_key: str
    sector_name: str
    etf_symbol: Optional[str]
    score: Optional[float] = None
    regime: Optional[str] = None
    delta_1d: Optional[float] = None
    stocks: List[str] = []


class MarketOverviewResponse(BaseModel):
    pulse: Optional[MarketPulseData] = None
    sentiment: SentimentData
    sectors: List[SectorOverview]
    date: str


# ── Endpoints ──

@router.get("/overview", response_model=MarketOverviewResponse)
async def market_overview():
    """
    Combined market overview: Market Pulse + Momentum Sentiment + Sector breakdown.
    Single endpoint for the dashboard hero section.
    """
    import json

    # Market Pulse
    pulse_raw = get_latest_market_pulse()
    pulse = None
    date = ""
    if pulse_raw:
        # component_scores/distribution_days may already be dict or still be JSON string
        def _ensure_dict(val):
            if isinstance(val, dict):
                return val
            if isinstance(val, str):
                try:
                    return json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    return {}
            return {}

        pulse = MarketPulseData(
            date=pulse_raw["date"],
            regime=pulse_raw["regime"],
            composite_score=pulse_raw["composite_score"],
            component_scores=_ensure_dict(pulse_raw.get("component_scores")),
            spy_price=pulse_raw.get("spy_price"),
            vix_value=pulse_raw.get("vix_value"),
            distribution_days=_ensure_dict(pulse_raw.get("distribution_days")),
        )
        date = pulse_raw["date"]

    # Momentum Sentiment (SPY/QQQ from momentum_scores)
    market_scores = get_latest_momentum_scores(layer="market")
    spy_data = None
    qqq_data = None
    mood = "N/A"
    tech_vs_broad = None

    for s in market_scores:
        entry = {
            "symbol": s["symbol"],
            "score": s.get("final_score"),
            "regime": s.get("regime"),
            "delta_1d": s.get("delta_1d"),
            "price": s.get("price"),
            "daily_change_pct": s.get("daily_change_pct"),
        }
        if s["symbol"] == "SPY":
            spy_data = entry
            if not date:
                date = s["date"]
        elif s["symbol"] == "QQQ":
            qqq_data = entry

    # Determine mood
    if spy_data and spy_data.get("score"):
        spy_score = spy_data["score"]
        if spy_score >= 70:
            mood = "RISK-ON"
        elif spy_score >= 60:
            mood = "RISK-ON Leaning"
        elif spy_score >= 40:
            mood = "NEUTRAL"
        else:
            mood = "RISK-OFF"

    # Tech vs Broad
    if spy_data and qqq_data and spy_data.get("score") and qqq_data.get("score"):
        tech_vs_broad = round(qqq_data["score"] - spy_data["score"], 1)

    sentiment = SentimentData(
        spy=spy_data,
        qqq=qqq_data,
        mood=mood,
        tech_vs_broad=tech_vs_broad,
    )

    # Sectors
    try:
        sector_defs = get_sector_definitions(enabled_only=True)
    except Exception:
        sector_defs = []

    try:
        mappings = get_sector_mappings()
    except Exception:
        mappings = []

    sector_scores_raw = get_latest_momentum_scores(layer="sector")
    sector_score_map = {s["symbol"]: s for s in sector_scores_raw}

    sectors = []
    for sd in sector_defs:
        etf = sd.get("etf_symbol", "")
        score_data = sector_score_map.get(etf, {})
        # Find stocks in this sector
        stocks_in_sector = [
            m["stock_symbol"] for m in mappings
            if m.get("sector_key") == sd["sector_key"]
        ]
        sectors.append(SectorOverview(
            sector_key=sd["sector_key"],
            sector_name=sd["sector_name"],
            etf_symbol=etf if etf != "BASKET" else None,
            score=score_data.get("final_score"),
            regime=score_data.get("regime"),
            delta_1d=score_data.get("delta_1d"),
            stocks=stocks_in_sector,
        ))

    return MarketOverviewResponse(
        pulse=pulse,
        sentiment=sentiment,
        sectors=sectors,
        date=date,
    )


@router.get("/pulse", response_model=Optional[MarketPulseData])
async def get_pulse():
    """Get latest Market Pulse data."""
    import json
    pulse_raw = get_latest_market_pulse()
    if not pulse_raw:
        return None

    def _ensure_dict(val):
        if isinstance(val, dict):
            return val
        if isinstance(val, str):
            try:
                return json.loads(val)
            except (json.JSONDecodeError, TypeError):
                return {}
        return {}

    return MarketPulseData(
        date=pulse_raw["date"],
        regime=pulse_raw["regime"],
        composite_score=pulse_raw["composite_score"],
        component_scores=_ensure_dict(pulse_raw.get("component_scores")),
        spy_price=pulse_raw.get("spy_price"),
        vix_value=pulse_raw.get("vix_value"),
        distribution_days=_ensure_dict(pulse_raw.get("distribution_days")),
    )


@router.get("/pulse/history", response_model=List[MarketPulseData])
async def get_pulse_history(days: int = Query(30, ge=1, le=365)):
    """Get Market Pulse history."""
    import json

    def _ensure_dict(val):
        if isinstance(val, dict):
            return val
        if isinstance(val, str):
            try:
                return json.loads(val)
            except (json.JSONDecodeError, TypeError):
                return {}
        return {}

    raw = get_market_pulse(limit=days)
    return [
        MarketPulseData(
            date=p["date"],
            regime=p["regime"],
            composite_score=p["composite_score"],
            component_scores=_ensure_dict(p.get("component_scores")),
            spy_price=p.get("spy_price"),
            vix_value=p.get("vix_value"),
            distribution_days=_ensure_dict(p.get("distribution_days")),
        )
        for p in raw
    ]


@router.get("/sectors", response_model=List[SectorOverview])
async def list_sectors():
    """Get all sector definitions with current momentum scores."""
    try:
        sector_defs = get_sector_definitions(enabled_only=True)
    except Exception:
        sector_defs = []

    try:
        mappings = get_sector_mappings()
    except Exception:
        mappings = []

    sector_scores_raw = get_latest_momentum_scores(layer="sector")
    sector_score_map = {s["symbol"]: s for s in sector_scores_raw}

    sectors = []
    for sd in sector_defs:
        etf = sd.get("etf_symbol", "")
        score_data = sector_score_map.get(etf, {})
        stocks_in_sector = [
            m["stock_symbol"] for m in mappings
            if m.get("sector_key") == sd["sector_key"]
        ]
        sectors.append(SectorOverview(
            sector_key=sd["sector_key"],
            sector_name=sd["sector_name"],
            etf_symbol=etf if etf != "BASKET" else None,
            score=score_data.get("final_score"),
            regime=score_data.get("regime"),
            delta_1d=score_data.get("delta_1d"),
            stocks=stocks_in_sector,
        ))

    return sectors
