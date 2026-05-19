"""
API v1: Signal Feed Endpoints
================================
Real-time signal feed sorted by urgency, with filtering.

Endpoints:
    GET  /api/v1/signals/feed        — Sorted signal feed (all strategies)
    GET  /api/v1/signals/recent      — Recent signal changes
    GET  /api/v1/signals/active      — Currently active signals
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from lib.db import (
    get_signal_changes,
    get_strategy_states,
    get_momentum_scores,
    get_latest_momentum_scores,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/signals", tags=["signals"])


# ── Response Models ──

class SignalFeedItem(BaseModel):
    symbol: str
    strategy: str
    urgency: str
    signal_type: str
    message: str
    score: Optional[float] = None
    position_advice: Optional[int] = None
    price: Optional[float] = None
    daily_change_pct: Optional[float] = None
    date: str
    layer: str = "stock"


class SignalChangeItem(BaseModel):
    symbol: str
    date: str
    strategy: str
    change_type: str
    price: Optional[float] = None
    score: Optional[float] = None
    details: Dict[str, Any] = {}


class ActiveSignalItem(BaseModel):
    symbol: str
    strategy: str
    is_active: bool
    entry_date: Optional[str] = None
    entry_price: Optional[float] = None
    extra: Dict[str, Any] = {}


# ── Endpoints ──

@router.get("/feed", response_model=List[SignalFeedItem])
async def signal_feed(
    urgency_min: Optional[str] = Query(None, description="Min urgency: CRITICAL, HIGH, MEDIUM"),
    layer: Optional[str] = Query(None, description="Filter by layer: market, sector, stock"),
    limit: int = Query(50, ge=1, le=200),
):
    """
    Get signal feed sorted by urgency (most urgent first).
    Combines momentum signals from all layers.
    """
    # Get momentum scores with urgency > NONE
    urgency_filter = urgency_min or "LOW"
    scores = get_momentum_scores(
        layer=layer,
        urgency_min=urgency_filter,
        limit=limit,
    )

    # Build feed items
    urgency_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "NONE": 4}
    items = []

    for s in scores:
        signals = s.get("signals", [])
        message = signals[0] if signals else f"Score={s.get('final_score', 0):.1f}"

        # Determine signal type
        urgency = s.get("urgency", "NONE")
        position = s.get("position_advice")
        if position is not None and position == 0:
            signal_type = "exit"
        elif position is not None and position <= 30:
            signal_type = "scale_out"
        elif urgency in ("CRITICAL", "HIGH") and position and position >= 70:
            signal_type = "entry"
        else:
            signal_type = "warning" if urgency != "NONE" else "hold"

        items.append(SignalFeedItem(
            symbol=s["symbol"],
            strategy="momentum_v3",
            urgency=urgency,
            signal_type=signal_type,
            message=message,
            score=s.get("final_score"),
            position_advice=position,
            price=s.get("price"),
            daily_change_pct=s.get("daily_change_pct"),
            date=s["date"],
            layer=s.get("layer", "stock"),
        ))

    # Sort by urgency
    items.sort(key=lambda x: urgency_order.get(x.urgency, 9))
    return items[:limit]


@router.get("/recent", response_model=List[SignalChangeItem])
async def recent_signal_changes(
    strategy: Optional[str] = Query(None),
    symbol: Optional[str] = Query(None),
    limit: int = Query(30, ge=1, le=100),
):
    """Get recent signal changes (entries/exits)."""
    import json

    changes = get_signal_changes(
        strategy=strategy,
        symbol=symbol.upper() if symbol else None,
        limit=limit,
    )

    return [
        SignalChangeItem(
            symbol=c["symbol"],
            date=c["date"],
            strategy=c["strategy"],
            change_type=c["change_type"],
            price=c.get("price"),
            score=c.get("score"),
            details=json.loads(c.get("details") or "{}"),
        )
        for c in changes
    ]


@router.get("/active", response_model=List[ActiveSignalItem])
async def active_signals(
    strategy: Optional[str] = Query(None),
):
    """Get all currently active signals across strategies."""
    import json

    # Get from strategy_states
    strategies_to_check = [strategy] if strategy else [
        "momentum_v3", "stage2", "vcp", "bottom_fisher", "buying_checklist"
    ]

    items = []
    for strat in strategies_to_check:
        states = get_strategy_states(strat, active_only=True)
        for s in states:
            extra = json.loads(s.get("extra") or "{}") if isinstance(s.get("extra"), str) else s.get("extra", {})
            items.append(ActiveSignalItem(
                symbol=s["symbol"],
                strategy=s["strategy"],
                is_active=bool(s.get("is_active")),
                entry_date=s.get("entry_date"),
                entry_price=s.get("entry_price"),
                extra=extra,
            ))

    return items
