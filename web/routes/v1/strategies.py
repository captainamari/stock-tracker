"""
API v1: Strategy Endpoints
============================
Provides strategy discovery, configuration, and execution APIs.

Endpoints:
    GET  /api/v1/strategies/           — List all registered strategies
    GET  /api/v1/strategies/{name}     — Get strategy details + config schema
    POST /api/v1/strategies/{name}/run — Run strategy on specified symbols
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from lib.db import get_prices_as_dataframe, get_watchlist
from lib.strategy.loader import load_all_strategies
from lib.strategy import registry

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/strategies", tags=["strategies"])

# Ensure strategies are loaded
load_all_strategies()


# ── Response Models ──

class StrategyInfo(BaseModel):
    name: str
    display_name: str
    version: str
    layer: str
    description: str
    requires_market_data: bool
    requires_sector_data: bool
    min_data_points: int
    config_schema: Dict[str, Any] = {}


class StrategyListResponse(BaseModel):
    strategies: List[StrategyInfo]
    total: int


class RunStrategyRequest(BaseModel):
    symbols: List[str] = Field(..., min_length=1, max_length=50)
    config: Optional[Dict[str, Any]] = None


class SignalOutput(BaseModel):
    signal_type: str
    urgency: str
    message: str
    position_advice: Optional[int] = None
    score: Optional[float] = None
    details: Dict[str, Any] = {}


class StrategyResultOutput(BaseModel):
    symbol: str
    date: str
    strategy: str
    is_signal: bool
    score: Optional[float] = None
    passed: int = 0
    total: int = 0
    conditions: Dict[str, bool] = {}
    metrics: Dict[str, Any] = {}
    signals: List[SignalOutput] = []
    summary: str = ""


class RunStrategyResponse(BaseModel):
    results: Dict[str, StrategyResultOutput]
    errors: List[str] = []


# ── Endpoints ──

@router.get("/", response_model=StrategyListResponse)
async def list_strategies():
    """List all registered strategies with metadata."""
    metadata = registry.list_metadata()
    return StrategyListResponse(
        strategies=[StrategyInfo(**m) for m in metadata],
        total=len(metadata),
    )


@router.get("/{name}", response_model=StrategyInfo)
async def get_strategy(name: str):
    """Get detailed information about a specific strategy."""
    strategy = registry.get(name)
    if not strategy:
        raise HTTPException(status_code=404, detail=f"Strategy '{name}' not found")

    return StrategyInfo(
        name=strategy.name,
        display_name=strategy.display_name,
        version=strategy.version,
        layer=strategy.layer.value,
        description=strategy.description,
        requires_market_data=strategy.requires_market_data,
        requires_sector_data=strategy.requires_sector_data,
        min_data_points=strategy.min_data_points,
        config_schema=strategy.get_config_schema(),
    )


@router.post("/{name}/run", response_model=RunStrategyResponse)
async def run_strategy(name: str, req: RunStrategyRequest):
    """
    Run a strategy on specified symbols.

    Returns computed results for each symbol.
    """
    strategy = registry.get(name)
    if not strategy:
        raise HTTPException(status_code=404, detail=f"Strategy '{name}' not found")

    results = {}
    errors = []

    for symbol in req.symbols:
        symbol = symbol.upper()
        try:
            prices_df = get_prices_as_dataframe(symbol, min_rows=strategy.min_data_points)
            if prices_df is None or prices_df.empty:
                errors.append(f"{symbol}: insufficient price data")
                continue

            result = registry.run(name, symbol, prices_df, context=req.config)
            if result:
                results[symbol] = StrategyResultOutput(
                    symbol=result.symbol,
                    date=result.date,
                    strategy=result.strategy,
                    is_signal=result.is_signal,
                    score=result.score,
                    passed=result.passed,
                    total=result.total,
                    conditions=result.conditions,
                    metrics=result.metrics,
                    signals=[
                        SignalOutput(
                            signal_type=s.signal_type.value,
                            urgency=s.urgency.value,
                            message=s.message,
                            position_advice=s.position_advice,
                            score=s.score,
                            details=s.details,
                        )
                        for s in result.signals
                    ],
                    summary=result.summary,
                )
            else:
                errors.append(f"{symbol}: computation returned no result")

        except Exception as e:
            logger.error(f"Error running {name} on {symbol}: {e}")
            errors.append(f"{symbol}: {str(e)}")

    return RunStrategyResponse(results=results, errors=errors)


@router.post("/run-all")
async def run_all_strategies(
    symbols: List[str] = Query(None),
    layer: Optional[str] = Query(None),
):
    """
    Run all strategies on specified symbols (or full watchlist).
    Useful for batch refresh.
    """
    if not symbols:
        watchlist = get_watchlist(enabled_only=True, source_type="monitored")
        symbols = [item["symbol"] for item in watchlist]

    all_results = {}
    errors = []

    for symbol in symbols[:20]:  # Limit to 20 symbols per request
        symbol = symbol.upper()
        try:
            prices_df = get_prices_as_dataframe(symbol, min_rows=30)
            if prices_df is None or prices_df.empty:
                continue

            results = registry.run_all(symbol, prices_df, layer=layer)
            all_results[symbol] = {
                name: {
                    "score": r.score,
                    "is_signal": r.is_signal,
                    "summary": r.summary,
                    "signals": [s.message for s in r.signals],
                }
                for name, r in results.items()
            }
        except Exception as e:
            errors.append(f"{symbol}: {str(e)}")

    return {"results": all_results, "symbols_processed": len(all_results), "errors": errors}
