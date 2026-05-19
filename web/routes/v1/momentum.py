"""
API v1: Momentum Endpoints
============================
Provides Momentum V3 data: scores, heatmap, history, relative strength.

Endpoints:
    GET  /api/v1/momentum/scores          — Latest momentum scores (all layers)
    GET  /api/v1/momentum/heatmap         — Heatmap data (Market→Sector→Stock)
    GET  /api/v1/momentum/history/{sym}   — Score history for charting
    GET  /api/v1/momentum/relative        — Relative strength matrix
    POST /api/v1/momentum/refresh         — Trigger momentum pipeline refresh
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from lib.db import (
    get_momentum_scores,
    get_latest_momentum_scores,
    get_score_history,
    get_sector_definitions,
    get_sector_mappings,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/momentum", tags=["momentum"])


# ── Response Models ──

class MomentumScore(BaseModel):
    symbol: str
    date: str
    layer: str
    final_score: Optional[float]
    regime: Optional[str]
    delta_1d: Optional[float]
    delta_5d: Optional[float]
    consecutive_above_65: int = 0
    consecutive_above_70: int = 0
    consecutive_below_60: int = 0
    signals: List[str] = []
    position_advice: Optional[int] = None
    urgency: str = "NONE"
    relative_strength: Dict[str, Any] = {}
    price: Optional[float] = None
    daily_change_pct: Optional[float] = None


class HeatmapItem(BaseModel):
    symbol: str
    name: str
    layer: str
    score: Optional[float]
    regime: Optional[str]
    delta_1d: Optional[float]
    urgency: str = "NONE"
    sector: Optional[str] = None


class HeatmapResponse(BaseModel):
    market: List[HeatmapItem]
    sectors: List[HeatmapItem]
    stocks: List[HeatmapItem]
    date: str


class ScoreHistoryPoint(BaseModel):
    date: str
    score: Optional[float]
    regime: Optional[str] = None


class RelativeStrengthItem(BaseModel):
    symbol: str
    score: Optional[float]
    vs_spy: Optional[float] = None
    vs_sector: Optional[float] = None
    sector_name: Optional[str] = None
    alpha: Optional[bool] = None


# ── Endpoints ──

@router.get("/scores", response_model=List[MomentumScore])
async def get_scores(
    layer: Optional[str] = Query(None, description="Filter by layer: market, sector, stock"),
    date: Optional[str] = Query(None, description="Specific date (YYYY-MM-DD)"),
    urgency_min: Optional[str] = Query(None, description="Minimum urgency: CRITICAL, HIGH, MEDIUM, LOW"),
    limit: int = Query(100, ge=1, le=500),
):
    """Get momentum scores, optionally filtered by layer/date/urgency."""
    if date:
        scores = get_momentum_scores(layer=layer, date_str=date, urgency_min=urgency_min, limit=limit)
    else:
        scores = get_latest_momentum_scores(layer=layer)

    return [
        MomentumScore(
            symbol=s["symbol"],
            date=s["date"],
            layer=s["layer"],
            final_score=s.get("final_score"),
            regime=s.get("regime"),
            delta_1d=s.get("delta_1d"),
            delta_5d=s.get("delta_5d"),
            consecutive_above_65=s.get("consecutive_above_65", 0),
            consecutive_above_70=s.get("consecutive_above_70", 0),
            consecutive_below_60=s.get("consecutive_below_60", 0),
            signals=s.get("signals", []),
            position_advice=s.get("position_advice"),
            urgency=s.get("urgency", "NONE"),
            relative_strength=s.get("relative_strength", {}),
            price=s.get("price"),
            daily_change_pct=s.get("daily_change_pct"),
        )
        for s in scores
    ]


@router.get("/heatmap", response_model=HeatmapResponse)
async def get_heatmap():
    """
    Get three-layer momentum heatmap data.
    Organized as: Market (SPY/QQQ) → Sectors (ETFs) → Stocks.
    """
    all_scores = get_latest_momentum_scores()

    market_items = []
    sector_items = []
    stock_items = []

    # Name mappings
    market_names = {"SPY": "S&P 500", "QQQ": "Nasdaq 100"}

    for s in all_scores:
        item = HeatmapItem(
            symbol=s["symbol"],
            name=market_names.get(s["symbol"], s["symbol"]),
            layer=s["layer"],
            score=s.get("final_score"),
            regime=s.get("regime"),
            delta_1d=s.get("delta_1d"),
            urgency=s.get("urgency", "NONE"),
        )

        if s["layer"] == "market":
            market_items.append(item)
        elif s["layer"] == "sector":
            sector_items.append(item)
        else:
            # Get sector info from relative_strength
            rs = s.get("relative_strength", {})
            item.sector = rs.get("sector_name")
            stock_items.append(item)

    # Sort by score descending
    stock_items.sort(key=lambda x: x.score or 0, reverse=True)

    date = all_scores[0]["date"] if all_scores else ""

    return HeatmapResponse(
        market=market_items,
        sectors=sector_items,
        stocks=stock_items,
        date=date,
    )


@router.get("/history/{symbol}", response_model=List[ScoreHistoryPoint])
async def get_momentum_history(
    symbol: str,
    strategy: str = Query("momentum_v3", description="Strategy name"),
    days: int = Query(60, ge=1, le=365),
):
    """Get score history for a symbol (for charting)."""
    symbol = symbol.upper()
    history = get_score_history(symbol, strategy=strategy, days=days)

    return [
        ScoreHistoryPoint(date=h["date"], score=h.get("score"), regime=h.get("regime"))
        for h in history
    ]


@router.get("/relative", response_model=List[RelativeStrengthItem])
async def get_relative_strength():
    """Get relative strength matrix (all stocks vs SPY and their sectors)."""
    scores = get_latest_momentum_scores(layer="stock")

    items = []
    for s in scores:
        rs = s.get("relative_strength", {})
        items.append(RelativeStrengthItem(
            symbol=s["symbol"],
            score=s.get("final_score"),
            vs_spy=rs.get("vs_spy"),
            vs_sector=rs.get("vs_sector"),
            sector_name=rs.get("sector_name"),
            alpha=rs.get("alpha"),
        ))

    # Sort by score descending
    items.sort(key=lambda x: x.score or 0, reverse=True)
    return items


@router.post("/refresh")
async def refresh_momentum():
    """
    Trigger a full momentum pipeline refresh.
    Runs Market → Sector → Stock computation.
    """
    try:
        from lib.strategy.momentum_v3.runner import run_momentum_pipeline
        summary = run_momentum_pipeline()
        return {
            "status": "ok",
            "summary": {
                "market": summary["market"],
                "sector": summary["sector"],
                "stock": summary["stock"],
                "duration_seconds": summary["duration_seconds"],
                "errors": summary.get("errors", []),
            },
        }
    except Exception as e:
        logger.error(f"Momentum refresh failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
