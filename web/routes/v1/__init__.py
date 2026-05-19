"""
API v1 Router Package
======================
New versioned API layer for the trading platform.

Endpoints:
    /api/v1/strategies/*   — Strategy registry (list, config, run)
    /api/v1/momentum/*     — Momentum V3 data (scores, heatmap, history)
    /api/v1/market/*       — Market overview (pulse, sentiment, sectors)
    /api/v1/signals/*      — Signal feed (real-time, filtered)
    /api/v1/ws             — WebSocket for real-time updates
"""

from fastapi import APIRouter

from web.routes.v1.strategies import router as strategies_router
from web.routes.v1.momentum import router as momentum_router
from web.routes.v1.market import router as market_router
from web.routes.v1.signals import router as signals_router
from web.routes.v1.websocket import router as ws_router

router = APIRouter(prefix="/v1", tags=["v1"])

router.include_router(strategies_router)
router.include_router(momentum_router)
router.include_router(market_router)
router.include_router(signals_router)
router.include_router(ws_router)
