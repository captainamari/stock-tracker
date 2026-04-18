"""
JSON API routes
Provides data for frontend JS (chart refresh, ticker management, etc.)
"""

import json
import asyncio
import logging
from fastapi import APIRouter, Query, Request, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
from lib import db
from web.i18n import get_language_from_request, get_translator

logger = logging.getLogger(__name__)

router = APIRouter(tags=["api"])


# ============================================================
# Ticker Management API
# ============================================================
class AddTickerRequest(BaseModel):
    symbol: str
    name: Optional[str] = None
    sector: Optional[str] = None


@router.get("/tickers/check/{symbol}")
async def api_check_ticker(request: Request, symbol: str):
    """
    Validate whether a ticker is valid and fetchable.
    Returns validation result including auto-fetched name/sector/price metadata.
    """
    from lib.pipeline import validate_ticker

    lang = get_language_from_request(request)
    t = get_translator(lang)

    symbol = symbol.strip().upper()

    # Check if already in watchlist
    existing = db.get_watchlist_item(symbol)
    if existing and existing.get('enabled'):
        return {
            'valid': True,
            'exists': True,
            'enabled': True,
            'symbol': symbol,
            'name': existing.get('name', symbol),
            'sector': existing.get('sector', ''),
            'message': t('api.already_in_list', symbol=symbol),
        }

    if existing and not existing.get('enabled'):
        return {
            'valid': True,
            'exists': True,
            'enabled': False,
            'symbol': symbol,
            'name': existing.get('name', symbol),
            'sector': existing.get('sector', ''),
            'message': t('api.was_removed', symbol=symbol),
            'has_price_data': db.get_price_count(symbol) > 0,
        }

    # Not found, validate via yfinance
    result = validate_ticker(symbol)
    result['exists'] = False
    result['enabled'] = False
    return result


@router.post("/tickers")
async def api_add_ticker(request: Request, req: AddTickerRequest):
    """
    Add a ticker to the watchlist.
    - If exists and enabled=0, restore display
    - If not found, validate then add and run strategy pipeline
    """
    from lib.pipeline import validate_ticker, run_single_ticker_pipeline

    lang = get_language_from_request(request)
    t = get_translator(lang)

    symbol = req.symbol.strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail=t('api.enter_ticker'))

    # Check if already exists
    existing = db.get_watchlist_item(symbol)

    if existing and existing.get('enabled'):
        raise HTTPException(status_code=409, detail=t('api.already_exists', symbol=symbol))

    if existing and not existing.get('enabled'):
        # Restore disabled ticker
        db.set_ticker_enabled(symbol, True)
        logger.info(f"[API] Restored ticker: {symbol}")

        # Check if price data exists
        has_prices = db.get_price_count(symbol) > 0
        if has_prices:
            name = existing.get('name', symbol)
            sector = existing.get('sector', '')
            try:
                pipeline_result = run_single_ticker_pipeline(symbol, name, sector)
                return {
                    'success': True,
                    'symbol': symbol,
                    'name': name,
                    'sector': sector,
                    'restored': True,
                    'pipeline': pipeline_result,
                    'message': t('api.restored_updated', symbol=symbol),
                }
            except Exception as e:
                logger.error(f"[API] Restore {symbol} pipeline failed: {e}")
                return {
                    'success': True,
                    'symbol': symbol,
                    'name': name,
                    'sector': sector,
                    'restored': True,
                    'pipeline': None,
                    'message': t('api.restored_failed', symbol=symbol, err=str(e)),
                }
        else:
            name = req.name or existing.get('name', symbol)
            sector = req.sector or existing.get('sector', '')

    else:
        # Brand new ticker: validate first
        validation = validate_ticker(symbol)
        if not validation['valid']:
            raise HTTPException(status_code=400, detail=validation['error'])

        name = req.name or validation['name'] or symbol
        sector = req.sector or validation['sector'] or ''

        # Write to watchlist
        db.upsert_watchlist([{
            'symbol': symbol,
            'name': name,
            'sector': sector,
            'source_type': 'monitored',
            'enabled': True,
        }])
        logger.info(f"[API] Added ticker: {symbol} ({name}, {sector})")

    # Run full pipeline
    try:
        pipeline_result = run_single_ticker_pipeline(symbol, name, sector)
        return {
            'success': True,
            'symbol': symbol,
            'name': name,
            'sector': sector,
            'restored': False,
            'pipeline': pipeline_result,
            'message': t('api.added_complete', symbol=symbol),
        }
    except Exception as e:
        logger.error(f"[API] {symbol} pipeline failed: {e}")
        return {
            'success': True,
            'symbol': symbol,
            'name': name,
            'sector': sector,
            'restored': False,
            'pipeline': None,
            'message': t('api.added_failed', symbol=symbol, err=str(e)),
        }


@router.delete("/tickers/{symbol}")
async def api_remove_ticker(request: Request, symbol: str):
    """
    Soft-delete a ticker (set enabled=0), no physical data deletion.
    """
    lang = get_language_from_request(request)
    t = get_translator(lang)

    symbol = symbol.strip().upper()

    existing = db.get_watchlist_item(symbol)
    if not existing:
        raise HTTPException(status_code=404, detail=t('api.not_in_list', symbol=symbol))

    if not existing.get('enabled'):
        raise HTTPException(status_code=409, detail=t('api.already_removed', symbol=symbol))

    db.set_ticker_enabled(symbol, False)
    logger.info(f"[API] Soft-deleted ticker: {symbol}")

    return {
        'success': True,
        'symbol': symbol,
        'message': t('api.removed', symbol=symbol),
    }


@router.get("/dashboard")
async def api_dashboard():
    """Dashboard full data"""
    pulse = db.get_latest_market_pulse()
    latest_date = pulse["date"] if pulse else None

    stage2 = db.get_strategy_results("stage2", date_str=latest_date, signal_only=True, limit=50) if latest_date else []
    vcp = db.get_strategy_results("vcp", date_str=latest_date, signal_only=True, limit=50) if latest_date else []
    bf = db.get_strategy_results("bottom_fisher", date_str=latest_date, signal_only=True, limit=50) if latest_date else []
    bc = db.get_strategy_results("buying_checklist", date_str=latest_date, signal_only=True, limit=50) if latest_date else []
    changes = db.get_signal_changes(limit=20)

    return {
        "pulse": pulse,
        "latest_date": latest_date,
        "stage2_signals": stage2,
        "vcp_signals": vcp,
        "bf_signals": bf,
        "bc_signals": bc,
        "signal_changes": changes,
    }


@router.get("/market-pulse/latest")
async def api_pulse_latest():
    """Latest Market Pulse"""
    return db.get_latest_market_pulse()


@router.get("/market-pulse/history")
async def api_pulse_history(days: int = Query(30, ge=1, le=365)):
    """Market Pulse history"""
    data = db.get_market_pulse(limit=days)
    data.reverse()
    return data


@router.get("/signals/recent")
async def api_signals_recent(
    limit: int = Query(20, ge=1, le=100),
    strategy: Optional[str] = Query(None),
):
    """Recent signal changes"""
    return db.get_signal_changes(strategy=strategy, limit=limit)


@router.get("/ticker/{symbol}")
async def api_ticker(symbol: str):
    """Individual stock data"""
    symbol = symbol.upper()
    pulse = db.get_latest_market_pulse()
    latest_date = pulse["date"] if pulse else None

    s2 = db.get_strategy_results("stage2", date_str=latest_date, symbol=symbol) if latest_date else []
    vcp = db.get_strategy_results("vcp", date_str=latest_date, symbol=symbol) if latest_date else []
    bf = db.get_strategy_results("bottom_fisher", date_str=latest_date, symbol=symbol) if latest_date else []
    bc = db.get_strategy_results("buying_checklist", date_str=latest_date, symbol=symbol) if latest_date else []

    # Fallback: newly added tickers may have different dates than market_pulse
    s2_result = s2[0] if s2 else None
    vcp_result = vcp[0] if vcp else None
    bf_result = bf[0] if bf else None
    bc_result = bc[0] if bc else None

    if not s2_result:
        fallback = db.get_strategy_results("stage2", symbol=symbol, limit=1)
        s2_result = fallback[0] if fallback else None
    if not vcp_result:
        fallback = db.get_strategy_results("vcp", symbol=symbol, limit=1)
        vcp_result = fallback[0] if fallback else None
    if not bf_result:
        fallback = db.get_strategy_results("bottom_fisher", symbol=symbol, limit=1)
        bf_result = fallback[0] if fallback else None
    if not bc_result:
        fallback = db.get_strategy_results("buying_checklist", symbol=symbol, limit=1)
        bc_result = fallback[0] if fallback else None

    # Technical indicators (computed in real-time)
    tech = {}
    try:
        from lib.technical_analysis import compute_technical_indicators
        data = db.get_prices_as_dataframe(symbol, min_rows=50)
        if data is not None:
            tech = compute_technical_indicators(data)
    except Exception as e:
        logger.warning(f"[API] {symbol}: technical indicator computation failed: {e}")

    return {
        "stage2": s2_result,
        "vcp": vcp_result,
        "bottom_fisher": bf_result,
        "buying_checklist": bc_result,
        "states": {
            "stage2": db.get_strategy_state(symbol, "stage2"),
            "vcp": db.get_strategy_state(symbol, "vcp"),
            "bottom_fisher": db.get_strategy_state(symbol, "bottom_fisher"),
            "buying_checklist": db.get_strategy_state(symbol, "buying_checklist"),
        },
        "signal_changes": db.get_signal_changes(symbol=symbol, limit=30),
        "technical_indicators": tech,
    }


@router.get("/ticker/{symbol}/history")
async def api_ticker_history(
    symbol: str,
    strategy: str = Query("stage2"),
    days: int = Query(30, ge=1, le=365),
):
    """Individual stock strategy history"""
    data = db.get_strategy_history(symbol.upper(), strategy, days=days)
    data.reverse()
    return data


# ============================================================
# Price refresh API (SSE)
# ============================================================
@router.post("/prices/refresh")
async def api_refresh_prices():
    """
    Full refresh of prices for all enabled tickers.
    Uses Server-Sent Events (SSE) to stream per-ticker progress.

    Frontend reads via fetch + ReadableStream:
      event: progress  → single ticker done
      event: complete  → all done
      event: error     → error occurred
    """
    from lib.pipeline import refresh_all_prices

    async def generate():
        try:
            loop = asyncio.get_event_loop()

            gen = refresh_all_prices()

            while True:
                try:
                    progress = await loop.run_in_executor(None, next, gen)
                except StopIteration:
                    break

                event_type = progress.get('type', 'progress')
                data = json.dumps(progress, ensure_ascii=False)
                yield f"event: {event_type}\ndata: {data}\n\n"

        except Exception as e:
            logger.error(f"[API] Price refresh error: {e}")
            error_data = json.dumps({
                'type': 'error',
                'error': str(e),
            }, ensure_ascii=False)
            yield f"event: error\ndata: {error_data}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
