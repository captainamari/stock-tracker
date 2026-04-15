"""
Watchlist 观察列表路由
展示：全部监控股票的多策略状态横向对照表
"""

from fastapi import APIRouter, Request, Query
from typing import Optional
from lib import db
from web.deps import templates

router = APIRouter(tags=["watchlist"])


def _build_watchlist_data(sector: Optional[str] = None,
                          signal_only: bool = False,
                          search: Optional[str] = None) -> dict:
    """构建 Watchlist 页面数据"""

    # 1. 获取观察列表
    tickers = db.get_watchlist(enabled_only=True, source_type="monitored")

    # 2. 获取最新的策略结果日期
    pulse = db.get_latest_market_pulse()
    latest_date = pulse["date"] if pulse else None

    # 3. 获取三个策略的当前状态
    stage2_states = {s["symbol"]: s for s in db.get_strategy_states("stage2")}
    vcp_states = {s["symbol"]: s for s in db.get_strategy_states("vcp")}
    bf_states = {s["symbol"]: s for s in db.get_strategy_states("bottom_fisher")}

    # 4. 获取最新策略结果 (用于 score 和 metrics)
    stage2_results = {}
    vcp_results = {}
    bf_results = {}
    if latest_date:
        for r in db.get_strategy_results("stage2", date_str=latest_date, limit=200):
            stage2_results[r["symbol"]] = r
        for r in db.get_strategy_results("vcp", date_str=latest_date, limit=200):
            vcp_results[r["symbol"]] = r
        for r in db.get_strategy_results("bottom_fisher", date_str=latest_date, limit=200):
            bf_results[r["symbol"]] = r

    # 5. 组装每只股票的综合数据行
    rows = []
    for t in tickers:
        sym = t["symbol"]
        s2 = stage2_results.get(sym, {})
        vcp = vcp_results.get(sym, {})
        bf = bf_results.get(sym, {})
        s2_state = stage2_states.get(sym, {})
        vcp_state = vcp_states.get(sym, {})
        bf_state = bf_states.get(sym, {})

        metrics = s2.get("metrics", {}) or bf.get("metrics", {}) or {}
        price = metrics.get("price")
        chg_5d = metrics.get("chg_5d")
        chg_20d = metrics.get("chg_20d")

        row = {
            "symbol": sym,
            "name": t.get("name", sym),
            "sector": t.get("sector", ""),
            "price": price,
            "chg_5d": chg_5d,
            "chg_20d": chg_20d,
            # Stage 2
            "s2_active": s2_state.get("is_active", 0),
            "s2_score": s2.get("score"),
            "s2_passed": s2.get("passed", 0),
            "s2_total": s2.get("total", 0),
            "s2_trend_power": (s2.get("metrics") or {}).get("trend_power"),
            # VCP
            "vcp_active": vcp_state.get("is_active", 0),
            "vcp_score": vcp.get("score"),
            "vcp_passed": vcp.get("passed", 0),
            "vcp_total": vcp.get("total", 0),
            # Bottom Fisher
            "bf_active": bf_state.get("is_active", 0),
            "bf_score": bf.get("score"),
            "bf_passed": bf.get("passed", 0),
            "bf_total": bf.get("total", 0),
        }
        rows.append(row)

    # 6. 过滤
    if sector:
        rows = [r for r in rows if r["sector"] == sector]
    if search:
        q = search.upper()
        rows = [r for r in rows if q in r["symbol"].upper() or q in r["name"].upper()]
    if signal_only:
        rows = [r for r in rows if r["s2_active"] or r["vcp_active"] or r["bf_active"]]

    # 7. 默认按 Stage2 score 倒序
    rows.sort(key=lambda r: (r["s2_score"] or 0), reverse=True)

    # 8. 提取所有板块 (用于筛选下拉框)
    all_sectors = sorted({t.get("sector", "") for t in tickers if t.get("sector")})

    return {
        "rows": rows,
        "all_sectors": all_sectors,
        "latest_date": latest_date,
        "pulse": pulse,
        "filter_sector": sector or "",
        "filter_signal_only": signal_only,
        "filter_search": search or "",
    }


@router.get("/watchlist")
async def watchlist_page(
    request: Request,
    sector: Optional[str] = Query(None),
    signal_only: bool = Query(False),
    search: Optional[str] = Query(None),
):
    data = _build_watchlist_data(sector=sector, signal_only=signal_only, search=search)
    return templates.TemplateResponse(
        request=request,
        name="watchlist.html",
        context={"page": "watchlist", **data},
    )
