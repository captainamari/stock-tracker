"""
纯 JSON API 路由
供前端 JS 动态获取数据（图表刷新等）
"""

import json
import asyncio
import logging
from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
from lib import db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["api"])


# ============================================================
# Ticker 管理 API
# ============================================================
class AddTickerRequest(BaseModel):
    symbol: str
    name: Optional[str] = None
    sector: Optional[str] = None


@router.get("/tickers/check/{symbol}")
async def api_check_ticker(symbol: str):
    """
    验证 ticker 是否合法且可拉取数据。
    返回验证结果，包括自动获取的 name/sector/price 等元数据。
    """
    from lib.pipeline import validate_ticker

    symbol = symbol.strip().upper()

    # 先检查 watchlist 中是否已存在
    existing = db.get_watchlist_item(symbol)
    if existing and existing.get('enabled'):
        return {
            'valid': True,
            'exists': True,
            'enabled': True,
            'symbol': symbol,
            'name': existing.get('name', symbol),
            'sector': existing.get('sector', ''),
            'message': f'"{symbol}" 已在观察列表中',
        }

    if existing and not existing.get('enabled'):
        return {
            'valid': True,
            'exists': True,
            'enabled': False,
            'symbol': symbol,
            'name': existing.get('name', symbol),
            'sector': existing.get('sector', ''),
            'message': f'"{symbol}" 曾被移除，可重新添加',
            'has_price_data': db.get_price_count(symbol) > 0,
        }

    # 不存在，调用 yfinance 验证
    result = validate_ticker(symbol)
    result['exists'] = False
    result['enabled'] = False
    return result


@router.post("/tickers")
async def api_add_ticker(req: AddTickerRequest):
    """
    新增 ticker 到观察列表。
    - 如果已存在且 enabled=0，恢复显示
    - 如果不存在，先验证再添加并运行策略管道
    """
    from lib.pipeline import validate_ticker, run_single_ticker_pipeline

    symbol = req.symbol.strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="请输入 ticker 代码")

    # 检查是否已存在
    existing = db.get_watchlist_item(symbol)

    if existing and existing.get('enabled'):
        raise HTTPException(status_code=409, detail=f'"{symbol}" 已在观察列表中')

    if existing and not existing.get('enabled'):
        # 恢复已禁用的 ticker
        db.set_ticker_enabled(symbol, True)
        logger.info(f"[API] 恢复 ticker: {symbol}")

        # 检查是否已有价格数据
        has_prices = db.get_price_count(symbol) > 0
        if has_prices:
            # 已有数据，无需重新拉取，但仍跑一次策略更新结果
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
                    'message': f'"{symbol}" 已恢复并更新策略计算',
                }
            except Exception as e:
                logger.error(f"[API] 恢复 {symbol} 管道执行失败: {e}")
                return {
                    'success': True,
                    'symbol': symbol,
                    'name': name,
                    'sector': sector,
                    'restored': True,
                    'pipeline': None,
                    'message': f'"{symbol}" 已恢复，但策略计算失败: {str(e)}',
                }
        else:
            # 无价格数据，需要走完整管道
            name = req.name or existing.get('name', symbol)
            sector = req.sector or existing.get('sector', '')

    else:
        # 全新 ticker：先验证
        validation = validate_ticker(symbol)
        if not validation['valid']:
            raise HTTPException(status_code=400, detail=validation['error'])

        # 用验证返回的元数据（如果前端没传）
        name = req.name or validation['name'] or symbol
        sector = req.sector or validation['sector'] or ''

        # 写入 watchlist
        db.upsert_watchlist([{
            'symbol': symbol,
            'name': name,
            'sector': sector,
            'source_type': 'monitored',
            'enabled': True,
        }])
        logger.info(f"[API] 新增 ticker: {symbol} ({name}, {sector})")

    # 运行完整管道
    try:
        pipeline_result = run_single_ticker_pipeline(symbol, name, sector)
        return {
            'success': True,
            'symbol': symbol,
            'name': name,
            'sector': sector,
            'restored': False,
            'pipeline': pipeline_result,
            'message': f'"{symbol}" 已添加并完成策略计算',
        }
    except Exception as e:
        logger.error(f"[API] {symbol} 管道执行失败: {e}")
        return {
            'success': True,
            'symbol': symbol,
            'name': name,
            'sector': sector,
            'restored': False,
            'pipeline': None,
            'message': f'"{symbol}" 已添加，但策略计算失败: {str(e)}',
        }


@router.delete("/tickers/{symbol}")
async def api_remove_ticker(symbol: str):
    """
    软删除 ticker（设置 enabled=0），不物理删除任何数据。
    """
    symbol = symbol.strip().upper()

    existing = db.get_watchlist_item(symbol)
    if not existing:
        raise HTTPException(status_code=404, detail=f'"{symbol}" 不在观察列表中')

    if not existing.get('enabled'):
        raise HTTPException(status_code=409, detail=f'"{symbol}" 已被移除')

    db.set_ticker_enabled(symbol, False)
    logger.info(f"[API] 软删除 ticker: {symbol}")

    return {
        'success': True,
        'symbol': symbol,
        'message': f'"{symbol}" 已从观察列表中移除',
    }


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

    # Fallback: Web 新增的 ticker 策略结果日期可能与 market_pulse 不同
    s2_result = s2[0] if s2 else None
    vcp_result = vcp[0] if vcp else None
    bf_result = bf[0] if bf else None

    if not s2_result:
        fallback = db.get_strategy_results("stage2", symbol=symbol, limit=1)
        s2_result = fallback[0] if fallback else None
    if not vcp_result:
        fallback = db.get_strategy_results("vcp", symbol=symbol, limit=1)
        vcp_result = fallback[0] if fallback else None
    if not bf_result:
        fallback = db.get_strategy_results("bottom_fisher", symbol=symbol, limit=1)
        bf_result = fallback[0] if fallback else None

    return {
        "stage2": s2_result,
        "vcp": vcp_result,
        "bottom_fisher": bf_result,
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


# ============================================================
# 价格全量刷新 API (SSE)
# ============================================================
@router.post("/prices/refresh")
async def api_refresh_prices():
    """
    全量刷新所有 enabled 个股的价格。
    使用 Server-Sent Events (SSE) 推送逐 ticker 进度。

    前端通过 fetch + ReadableStream 读取：
      event: progress  → 单只 ticker 完成
      event: complete  → 全部完成
      event: error     → 出错
    """
    from lib.pipeline import refresh_all_prices

    async def generate():
        try:
            loop = asyncio.get_event_loop()

            # refresh_all_prices() 是同步生成器，逐个 yield
            # 用 run_in_executor 包装以避免阻塞事件循环
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
            logger.error(f"[API] 价格刷新异常: {e}")
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
            "X-Accel-Buffering": "no",  # nginx 代理时禁用缓冲
        },
    )
