"""
报告生成共享工具 — lib/report.py

提供 Jinja2 模板渲染、Telegram 消息分割、报告文件保存等通用功能。
所有策略脚本通过此模块生成报告，避免重复代码。
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from jinja2 import Environment, FileSystemLoader, select_autoescape

# ============================================================
# 路径常量
# ============================================================
PROJECT_ROOT = Path(__file__).parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"
REPORTS_DIR = PROJECT_ROOT / "reports"


# ============================================================
# Jinja2 环境
# ============================================================
def _create_env() -> Environment:
    """创建并配置 Jinja2 Environment"""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=False,  # MD 和 Telegram HTML 都手动控制转义
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    # 注册自定义过滤器
    env.filters['tg_escape'] = tg_escape
    env.filters['score_emoji_tp'] = score_emoji_tp
    env.filters['score_emoji_vcp'] = score_emoji_vcp
    env.filters['score_emoji_bf'] = score_emoji_bf
    env.filters['chg_emoji'] = chg_emoji
    env.filters['score_bar'] = score_bar
    env.filters['progress_bar'] = progress_bar
    env.filters['fmt_pct'] = fmt_pct
    env.filters['fmt_price'] = fmt_price
    env.filters['fmt_val'] = fmt_val
    return env


_env: Optional[Environment] = None


def get_env() -> Environment:
    """获取 Jinja2 Environment 单例"""
    global _env
    if _env is None:
        _env = _create_env()
    return _env


def render_template(template_name: str, **context) -> str:
    """渲染指定模板，返回字符串"""
    env = get_env()
    tmpl = env.get_template(template_name)
    return tmpl.render(**context)


# ============================================================
# Jinja2 自定义过滤器
# ============================================================
def tg_escape(text) -> str:
    """Telegram HTML 转义"""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def score_emoji_tp(score) -> str:
    """Trend Power 评分 → emoji"""
    score = score or 0
    if score >= 80:
        return "🔥🔥🔥"
    elif score >= 60:
        return "🔥🔥"
    elif score >= 40:
        return "🔥"
    elif score >= 20:
        return "🌤"
    else:
        return "❄️"


def score_emoji_vcp(score) -> str:
    """VCP 评分 → emoji"""
    score = score or 0
    if score >= 80:
        return "🔴🔴🔴"
    elif score >= 60:
        return "🔴🔴"
    elif score >= 40:
        return "🔴"
    elif score >= 20:
        return "🟡"
    else:
        return "⚪"


def score_emoji_bf(score) -> str:
    """Bottom Fisher 评分 → emoji"""
    score = score or 0
    if score >= 80:
        return "🟢🟢🟢"
    elif score >= 60:
        return "🟢🟢"
    elif score >= 40:
        return "🟢"
    elif score >= 20:
        return "🟡"
    else:
        return "⚪"


def chg_emoji(pct) -> str:
    """涨跌幅 → emoji"""
    if pct is None:
        return ""
    if pct > 1:
        return "📈"
    elif pct < -1:
        return "📉"
    else:
        return "➡️"


def score_bar(score, width=10) -> str:
    """评分 → ▓░ 进度条"""
    score = score or 0
    filled = round(score / 100 * width)
    return "▓" * filled + "░" * (width - filled)


def progress_bar(passed, total) -> str:
    """条件通过数 → ▓░ 进度条"""
    passed = passed or 0
    total = total or 1
    return "▓" * passed + "░" * (total - passed)


def fmt_pct(value, plus_sign=True) -> str:
    """格式化百分比"""
    if value is None:
        return "N/A"
    if plus_sign:
        return f"{value:+.1f}%"
    return f"{value:.1f}%"


def fmt_price(value) -> str:
    """格式化价格"""
    if value is None:
        return "N/A"
    return f"${value}"


def fmt_val(value, fmt=".1f", default="N/A") -> str:
    """通用格式化"""
    if value is None:
        return default
    return f"{value:{fmt}}"


# ============================================================
# Telegram 消息分割
# ============================================================
def split_telegram_message(text: str, max_len: int = 4000) -> List[str]:
    """将长消息按段落边界分割为多段"""
    if len(text) <= max_len:
        return [text]

    paragraphs = text.split('\n\n')
    parts: List[str] = []
    current = ""
    for para in paragraphs:
        test = current + ("\n\n" if current else "") + para
        if len(test) > max_len and current:
            parts.append(current)
            current = para
        else:
            current = test
    if current:
        parts.append(current)

    # 处理单段超长的情况
    final: List[str] = []
    for p in parts:
        while len(p) > max_len:
            cut = p[:max_len].rfind('\n')
            if cut < max_len // 2:
                cut = max_len
            final.append(p[:cut])
            p = p[cut:].lstrip('\n')
        if p:
            final.append(p)

    return final


# ============================================================
# 报告文件保存
# ============================================================
def save_reports(
    md_report: str,
    tg_report: str,
    strategy_prefix: str = "",
    log_func=None,
) -> Dict[str, Any]:
    """
    统一的报告保存逻辑。

    参数:
        md_report: Markdown 报告内容
        tg_report: Telegram HTML 报告内容
        strategy_prefix: 文件名前缀，如 "_vcp", "_bottom", "_pulse"
                         空字符串表示 stage2（默认）
        log_func: 日志函数 (可选)

    返回:
        {'md_file': Path, 'tg_parts': int, 'tg_files': [Path]}
    """
    date_str = datetime.now().strftime('%Y-%m-%d')
    report_dir = REPORTS_DIR / "daily"
    report_dir.mkdir(parents=True, exist_ok=True)

    result = {'tg_files': []}

    # MD 报告
    md_file = report_dir / f"{date_str}{strategy_prefix}.md"
    try:
        with open(md_file, 'w', encoding='utf-8') as f:
            f.write(md_report)
        result['md_file'] = md_file
        if log_func:
            log_func(f"MD 报告已保存: {md_file}")
    except Exception as e:
        if log_func:
            log_func(f"MD 报告保存失败: {e}", "ERROR")

    # Telegram 报告（自动分段）
    TG_MAX = 4000
    parts = split_telegram_message(tg_report, TG_MAX)
    for i, part in enumerate(parts):
        suffix = "" if len(parts) == 1 else f"_part{i+1}"
        tg_file = report_dir / f"{date_str}{strategy_prefix}_telegram{suffix}.html"
        try:
            with open(tg_file, 'w', encoding='utf-8') as f:
                f.write(part)
            result['tg_files'].append(tg_file)
        except Exception as e:
            if log_func:
                log_func(f"TG 报告保存失败: {e}", "ERROR")

    # Manifest
    manifest = report_dir / f"{date_str}{strategy_prefix}_telegram_manifest.txt"
    try:
        with open(manifest, 'w', encoding='utf-8') as f:
            f.write(str(len(parts)))
        result['tg_parts'] = len(parts)
        if log_func:
            log_func(f"Telegram 报告已保存: {len(parts)} 段")
    except Exception:
        pass

    return result
