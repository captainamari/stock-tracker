"""
纯 JSON API 路由
供前端 JS 动态获取数据（图表刷新等）
"""

from fastapi import APIRouter, Query
from typing import Optional
from lib import db

router = APIRouter(tags=["api"])


@router.get("/dashboard")
async def api_dashboard():
    """Dashboard 全量数据"""
    pulse = db.get_latest_market_pulse()
    latest_date = pulse["date"] if pulse else None

    stage2 = db.get_strategy_results("stage2", date_str=latest_date, signal_only=True, limit=50) if latest_date else []
    vcp = db.get_strategy_results("vcp", date_str=latest_date, signal_only=True, limit=50) if latest_date else []
    bf = db.get_strategy_results("bottom_fisher", date_str=latest_date, signal_only=True, limit=50) if latest_date else []
    changes = db.get_signal_changes(limit=20)

    return {
        "pulse": pulse,
        "latest_date": latest_date,
        "stage2_signals": stage2,
        "vcp_signals": vcp,
        "bf_signals": bf,
        "signal_changes": changes,
    }


@router.get("/market-pulse/latest")
async def api_pulse_latest():
    """最新 Market Pulse"""
    return db.get_latest_market_pulse()


@router.get("/market-pulse/history")
async def api_pulse_history(days: int = Query(30, ge=1, le=365)):
    """Market Pulse 历史"""
    data = db.get_market_pulse(limit=days)
    data.reverse()
    return data


@router.get("/signals/recent")
async def api_signals_recent(
    limit: int = Query(20, ge=1, le=100),
    strategy: Optional[str] = Query(None),
):
    """近期信号变化"""
    return db.get_signal_changes(strategy=strategy, limit=limit)


@router.get("/ticker/{symbol}")
async def api_ticker(symbol: str):
    """个股数据"""
    symbol = symbol.upper()
    pulse = db.get_latest_market_pulse()
    latest_date = pulse["date"] if pulse else None

    s2 = db.get_strategy_results("stage2", date_str=latest_date, symbol=symbol) if latest_date else []
    vcp = db.get_strategy_results("vcp", date_str=latest_date, symbol=symbol) if latest_date else []
    bf = db.get_strategy_results("bottom_fisher", date_str=latest_date, symbol=symbol) if latest_date else []

    return {
        "stage2": s2[0] if s2 else None,
        "vcp": vcp[0] if vcp else None,
        "bottom_fisher": bf[0] if bf else None,
        "states": {
            "stage2": db.get_strategy_state(symbol, "stage2"),
            "vcp": db.get_strategy_state(symbol, "vcp"),
            "bottom_fisher": db.get_strategy_state(symbol, "bottom_fisher"),
        },
        "signal_changes": db.get_signal_changes(symbol=symbol, limit=30),
    }


@router.get("/ticker/{symbol}/history")
async def api_ticker_history(
    symbol: str,
    strategy: str = Query("stage2"),
    days: int = Query(30, ge=1, le=365),
):
    """个股策略历史"""
    data = db.get_strategy_history(symbol.upper(), strategy, days=days)
    data.reverse()
    return data
