"""
Ticker Detail 个股详情路由
展示：策略状态卡片 + 条件明细 + 关键指标 + 信号历史 + Score 走势
"""

from fastapi import APIRouter, Request, HTTPException
from lib import db
from web.deps import templates

router = APIRouter(tags=["ticker"])


def _build_ticker_data(symbol: str) -> dict:
    """构建个股详情页数据"""

    symbol = symbol.upper()

    # 1. 获取观察列表信息
    all_tickers = db.get_watchlist(enabled_only=False)
    ticker_info = None
    for t in all_tickers:
        if t["symbol"] == symbol:
            ticker_info = t
            break

    if not ticker_info:
        return None

    # 2. 获取最新日期
    pulse = db.get_latest_market_pulse()
    latest_date = pulse["date"] if pulse else None

    # 3. 三个策略的当前状态
    s2_state = db.get_strategy_state(symbol, "stage2")
    vcp_state = db.get_strategy_state(symbol, "vcp")
    bf_state = db.get_strategy_state(symbol, "bottom_fisher")
    bc_state = db.get_strategy_state(symbol, "buying_checklist")

    # 4. 最新策略结果
    #    先按 market_pulse latest_date 查；查不到则 fallback 查该 ticker 最新一条
    #    （Web 新增的 ticker 策略结果日期可能与批量 market_pulse 日期不同）
    s2_result = None
    vcp_result = None
    bf_result = None
    bc_result = None
    if latest_date:
        s2_results = db.get_strategy_results("stage2", date_str=latest_date, symbol=symbol)
        s2_result = s2_results[0] if s2_results else None
        vcp_results = db.get_strategy_results("vcp", date_str=latest_date, symbol=symbol)
        vcp_result = vcp_results[0] if vcp_results else None
        bf_results = db.get_strategy_results("bottom_fisher", date_str=latest_date, symbol=symbol)
        bf_result = bf_results[0] if bf_results else None
        bc_results = db.get_strategy_results("buying_checklist", date_str=latest_date, symbol=symbol)
        bc_result = bc_results[0] if bc_results else None

    # Fallback: 按 latest_date 查不到时，回退查该 ticker 最新一条策略结果
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

    # 5. 信号变化历史
    signal_changes = db.get_signal_changes(symbol=symbol, limit=30)

    # 6. 策略历史 (Score 走势)
    s2_history = db.get_strategy_history(symbol, "stage2", days=30)
    s2_history.reverse()  # 按日期升序
    vcp_history = db.get_strategy_history(symbol, "vcp", days=30)
    vcp_history.reverse()
    bf_history = db.get_strategy_history(symbol, "bottom_fisher", days=30)
    bf_history.reverse()
    bc_history = db.get_strategy_history(symbol, "buying_checklist", days=30)
    bc_history.reverse()

    # 7. 提取关键指标 (从 metrics)
    metrics = {}
    if s2_result and s2_result.get("metrics"):
        metrics = s2_result["metrics"]
    elif bf_result and bf_result.get("metrics"):
        metrics = bf_result["metrics"]

    # 8. 计算入场天数
    s2_days = None
    if s2_state and s2_state.get("is_active") and s2_state.get("entry_date") and latest_date:
        from datetime import datetime
        try:
            entry = datetime.strptime(s2_state["entry_date"], "%Y-%m-%d")
            current = datetime.strptime(latest_date, "%Y-%m-%d")
            s2_days = (current - entry).days
        except (ValueError, TypeError):
            pass

    return {
        "ticker": ticker_info,
        "symbol": symbol,
        "latest_date": latest_date,
        "pulse": pulse,
        "metrics": metrics,
        # 策略状态
        "s2_state": s2_state,
        "vcp_state": vcp_state,
        "bf_state": bf_state,
        "bc_state": bc_state,
        # 策略结果
        "s2_result": s2_result,
        "vcp_result": vcp_result,
        "bf_result": bf_result,
        "bc_result": bc_result,
        # 入场天数
        "s2_days": s2_days,
        # 信号变化
        "signal_changes": signal_changes,
        # 历史 (用于图表)
        "s2_history": s2_history,
        "vcp_history": vcp_history,
        "bf_history": bf_history,
        "bc_history": bc_history,
    }


@router.get("/ticker/{symbol}")
async def ticker_detail(request: Request, symbol: str):
    data = _build_ticker_data(symbol)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Ticker {symbol.upper()} not found")
    return templates.TemplateResponse(
        request=request,
        name="ticker_detail.html",
        context={"page": "ticker", **data},
    )
