"""
Dashboard 首页路由
展示：Market Pulse 状态 + 三策略信号摘要 + 近期信号变化
"""

from fastapi import APIRouter, Request
from lib import db
from web.deps import templates, setup_i18n_context
from web.i18n import get_language_from_request

router = APIRouter(tags=["dashboard"])


def _build_dashboard_data() -> dict:
    """构建 Dashboard 所需的全部数据"""

    # 1. Market Pulse 最新状态
    pulse = db.get_latest_market_pulse()

    # 2. Market Pulse 历史 (30天走势)
    pulse_history = db.get_market_pulse(limit=30)
    pulse_history.reverse()  # 按日期升序

    # 3. 获取最新日期 (从 market_pulse 推断)
    latest_date = pulse["date"] if pulse else None

    # 4. 三个策略的活跃信号
    stage2_signals = []
    vcp_signals = []
    bf_signals = []
    bc_signals = []

    if latest_date:
        stage2_signals = db.get_strategy_results(
            "stage2", date_str=latest_date, signal_only=True, limit=50
        )
        vcp_signals = db.get_strategy_results(
            "vcp", date_str=latest_date, signal_only=True, limit=50
        )
        bf_signals = db.get_strategy_results(
            "bottom_fisher", date_str=latest_date, signal_only=True, limit=50
        )
        bc_signals = db.get_strategy_results(
            "buying_checklist", date_str=latest_date, signal_only=True, limit=50
        )

    # Fallback: 如果按 market_pulse 日期查不到策略结果（日期不一致时），
    # 回退查询最新的信号结果
    if latest_date and not stage2_signals:
        stage2_signals = db.get_strategy_results(
            "stage2", signal_only=True, limit=50
        )
    if latest_date and not vcp_signals:
        vcp_signals = db.get_strategy_results(
            "vcp", signal_only=True, limit=50
        )
    if latest_date and not bf_signals:
        bf_signals = db.get_strategy_results(
            "bottom_fisher", signal_only=True, limit=50
        )
    if latest_date and not bc_signals:
        bc_signals = db.get_strategy_results(
            "buying_checklist", signal_only=True, limit=50
        )

    # 5. 各策略总扫描数 (用于 "12/36 只")
    stage2_total = len(
        db.get_strategy_results("stage2", date_str=latest_date, limit=200)
    ) if latest_date else 0
    vcp_total = len(
        db.get_strategy_results("vcp", date_str=latest_date, limit=200)
    ) if latest_date else 0
    bf_total = len(
        db.get_strategy_results("bottom_fisher", date_str=latest_date, limit=200)
    ) if latest_date else 0
    bc_total = len(
        db.get_strategy_results("buying_checklist", date_str=latest_date, limit=200)
    ) if latest_date else 0

    # Fallback: 总数也回退查询
    if latest_date and stage2_total == 0:
        stage2_total = len(db.get_strategy_results("stage2", limit=200))
    if latest_date and vcp_total == 0:
        vcp_total = len(db.get_strategy_results("vcp", limit=200))
    if latest_date and bf_total == 0:
        bf_total = len(db.get_strategy_results("bottom_fisher", limit=200))
    if latest_date and bc_total == 0:
        bc_total = len(db.get_strategy_results("buying_checklist", limit=200))

    # 6. 近期信号变化
    signal_changes = db.get_signal_changes(limit=20)

    return {
        "pulse": pulse,
        "pulse_history": pulse_history,
        "latest_date": latest_date,
        "stage2_signals": stage2_signals,
        "vcp_signals": vcp_signals,
        "bf_signals": bf_signals,
        "bc_signals": bc_signals,
        "stage2_total": stage2_total,
        "vcp_total": vcp_total,
        "bf_total": bf_total,
        "bc_total": bc_total,
        "signal_changes": signal_changes,
    }


@router.get("/")
async def dashboard(request: Request):
    lang = get_language_from_request(request)
    i18n_ctx = setup_i18n_context(request, lang)
    data = _build_dashboard_data()
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"page": "dashboard", **data, **i18n_ctx},
    )
