"""
Web 层共享依赖：Jinja2 模板引擎、工具函数
"""

from pathlib import Path
from fastapi.templating import Jinja2Templates

# ============================================================
# Jinja2 模板
# ============================================================
TEMPLATES_DIR = Path(__file__).parent / "templates"
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# 注册自定义过滤器
def _fmt_pct(value, decimals=1):
    """格式化百分比"""
    if value is None:
        return "—"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.{decimals}f}%"

def _fmt_price(value):
    """格式化价格"""
    if value is None:
        return "—"
    return f"${value:,.2f}"

def _fmt_score(value):
    """格式化评分"""
    if value is None:
        return "—"
    return f"{value:.0f}"

def _score_color(score):
    """评分对应的 CSS 颜色类"""
    if score is None:
        return "text-dim"
    if score >= 80:
        return "text-green"
    if score >= 60:
        return "text-yellow"
    if score >= 40:
        return "text-orange"
    return "text-red"

def _regime_emoji(regime):
    """市场状态 emoji"""
    mapping = {
        "bullish": "🟢",
        "neutral": "🟡",
        "cautious": "🟠",
        "bearish": "🔴",
    }
    return mapping.get(regime, "⚪")

def _regime_label(regime):
    """市场状态中文标签"""
    mapping = {
        "bullish": "进攻",
        "neutral": "谨慎",
        "cautious": "防御",
        "bearish": "空仓",
    }
    return mapping.get(regime, "未知")

def _change_type_info(change_type):
    """信号变化类型的 emoji + 标签"""
    mapping = {
        "entry": ("🟢", "进入信号"),
        "exit": ("🔴", "退出信号"),
        "new_signal": ("🆕", "新信号"),
        "lost_signal": ("⚪", "失去信号"),
    }
    return mapping.get(change_type, ("❓", change_type))

def _strategy_label(strategy):
    """策略显示名"""
    mapping = {
        "stage2": "Stage 2",
        "vcp": "VCP",
        "bottom_fisher": "Bottom Fisher",
    }
    return mapping.get(strategy, strategy)

def _chg_color(value):
    """涨跌幅颜色"""
    if value is None:
        return "text-dim"
    if value > 0:
        return "text-green"
    if value < 0:
        return "text-red"
    return "text-dim"

# 注册所有过滤器
templates.env.filters["fmt_pct"] = _fmt_pct
templates.env.filters["fmt_price"] = _fmt_price
templates.env.filters["fmt_score"] = _fmt_score
templates.env.filters["score_color"] = _score_color
templates.env.filters["regime_emoji"] = _regime_emoji
templates.env.filters["regime_label"] = _regime_label
templates.env.filters["strategy_label"] = _strategy_label
templates.env.filters["chg_color"] = _chg_color
templates.env.filters["change_type_info"] = _change_type_info
