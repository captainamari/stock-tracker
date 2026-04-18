"""
Web 层共享依赖：Jinja2 模板引擎、工具函数、i18n 集成
"""

from pathlib import Path
from fastapi.templating import Jinja2Templates

from web.i18n import get_translator, DEFAULT_LANGUAGE

# ============================================================
# Jinja2 模板
# ============================================================
TEMPLATES_DIR = Path(__file__).parent / "templates"
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# ============================================================
# 自定义过滤器（纯格式化，语言无关）
# ============================================================
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
    """市场状态标签 — i18n 版本，从 Jinja2 全局 _lang 读取当前语言"""
    # 这个过滤器会被 _regime_label_i18n 工厂替换
    mapping = {
        "bullish": "Offensive",
        "neutral": "Cautious",
        "cautious": "Defensive",
        "bearish": "Cash",
    }
    return mapping.get(regime, "Unknown")

def _change_type_info(change_type):
    """信号变化类型的 emoji + 标签 — 默认英文"""
    mapping = {
        "entry": ("🟢", "Entry Signal"),
        "exit": ("🔴", "Exit Signal"),
        "new_signal": ("🆕", "New Signal"),
        "lost_signal": ("⚪", "Lost Signal"),
    }
    return mapping.get(change_type, ("❓", change_type))

def _strategy_label(strategy):
    """策略显示名"""
    mapping = {
        "stage2": "Stage 2",
        "vcp": "VCP",
        "bottom_fisher": "Bottom Fisher",
        "buying_checklist": "Buying Checklist",
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


# ============================================================
# i18n-aware 过滤器工厂
# ============================================================
def make_regime_label_filter(t):
    """创建绑定到翻译函数的 regime_label 过滤器"""
    def _filter(regime):
        return t(f"regime.{regime}") if regime else t("common.unknown")
    return _filter


def make_change_type_info_filter(t):
    """创建绑定到翻译函数的 change_type_info 过滤器"""
    def _filter(change_type):
        emoji = t(f"change_type.{change_type}.emoji") if change_type else "❓"
        label = t(f"change_type.{change_type}.label") if change_type else change_type
        # If key not found, translate() returns the key itself
        if emoji.startswith("change_type."):
            emoji = "❓"
        if label.startswith("change_type."):
            label = change_type
        return (emoji, label)
    return _filter


# ============================================================
# 注册所有过滤器（语言无关的静态过滤器）
# ============================================================
templates.env.filters["fmt_pct"] = _fmt_pct
templates.env.filters["fmt_price"] = _fmt_price
templates.env.filters["fmt_score"] = _fmt_score
templates.env.filters["score_color"] = _score_color
templates.env.filters["regime_emoji"] = _regime_emoji
templates.env.filters["regime_label"] = _regime_label
templates.env.filters["strategy_label"] = _strategy_label
templates.env.filters["chg_color"] = _chg_color
templates.env.filters["change_type_info"] = _change_type_info


def setup_i18n_context(request, lang: str) -> dict:
    """
    创建 i18n 模板上下文变量。
    在路由中调用，将翻译函数和语言信息注入模板。

    返回一个 dict，合并到 TemplateResponse context 中。
    同时会动态覆盖 i18n 相关的 Jinja2 过滤器。
    """
    import json as _json
    from web.i18n.core import _load_pack

    t = get_translator(lang)

    # 动态替换 i18n 相关过滤器为当前语言版本
    templates.env.filters["regime_label"] = make_regime_label_filter(t)
    templates.env.filters["change_type_info"] = make_change_type_info_filter(t)

    # 获取语言包 JSON 字符串供前端 JS 使用
    pack = _load_pack(lang)
    i18n_json = _json.dumps(pack, ensure_ascii=False)

    return {
        "_t": t,              # 翻译函数 _t("key", param=val)
        "_lang": lang,        # 当前语言 "en" / "zh"
        "_i18n_json": i18n_json,  # 完整语言包 JSON 字符串
    }
