"""
Stock Tracker — 配置加载 & 观察列表同步
从 tickers.json 读取配置，同步到数据库 watchlist 表。

用法:
  from lib.config import load_config, sync_watchlist

  config = load_config()               # 读取 JSON
  sync_watchlist(config)               # 同步到 DB
  tickers = get_enabled_tickers()      # 获取启用的 ticker 列表
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any

# 确保项目根目录在 sys.path 中（支持 python lib/config.py 直接运行）
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lib.db import upsert_watchlist, get_watchlist, init_db
from lib.models import TickerInfo

# 配置文件路径
CONFIG_DIR = Path(__file__).parent.parent / "config"
TICKERS_CONFIG = CONFIG_DIR / "tickers.json"


def load_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    加载 tickers.json 配置文件。
    返回原始 dict，包含 monitored, yfinance_only, benchmark 等字段。
    """
    path = config_path or TICKERS_CONFIG
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"❌ 配置文件不存在: {path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"❌ 配置文件 JSON 解析失败: {e}")
        sys.exit(1)


def parse_tickers(config: Dict) -> List[TickerInfo]:
    """
    将配置 dict 解析为 TickerInfo 列表。
    合并 monitored 和 yfinance_only 两组。
    """
    tickers = []

    # monitored 组
    for item in config.get('monitored', []):
        t = TickerInfo.from_json(item)
        t.source_type = 'monitored'
        tickers.append(t)

    # yfinance_only 组
    for item in config.get('yfinance_only', []):
        t = TickerInfo.from_json(item)
        t.source_type = 'yfinance_only'
        tickers.append(t)

    return tickers


def sync_watchlist(config: Optional[Dict] = None, config_path: Optional[Path] = None):
    """
    将 tickers.json 同步到数据库 watchlist 表。
    幂等操作：存在则更新，不存在则插入。
    """
    if config is None:
        config = load_config(config_path)

    tickers = parse_tickers(config)
    db_records = [t.to_db_dict() for t in tickers]
    upsert_watchlist(db_records)
    print(f"✅ Watchlist 已同步: {len(db_records)} 只股票")


def get_enabled_tickers(source_type: Optional[str] = None) -> List[TickerInfo]:
    """
    从数据库获取启用的 ticker 列表。
    source_type: 'monitored' | 'yfinance_only' | None (全部)
    """
    rows = get_watchlist(enabled_only=True, source_type=source_type)
    return [
        TickerInfo(
            symbol=r['symbol'],
            name=r['name'],
            sector=r['sector'],
            enabled=bool(r['enabled']),
            source_type=r['source_type'],
            yf_ticker=r.get('yf_ticker'),
        )
        for r in rows
    ]


def get_monitored_tickers() -> List[TickerInfo]:
    """获取 monitored 组的启用 ticker"""
    return get_enabled_tickers(source_type='monitored')


def get_yfinance_tickers() -> List[TickerInfo]:
    """获取 yfinance_only 组的启用 ticker"""
    return get_enabled_tickers(source_type='yfinance_only')


def get_benchmark(config: Optional[Dict] = None) -> str:
    """获取基准 ticker (默认 SPY)"""
    if config is None:
        config = load_config()
    return config.get('benchmark', 'SPY')


# ============================================================
# CLI 入口
# ============================================================
if __name__ == "__main__":
    print("📋 加载配置并同步 watchlist...")
    init_db()
    config = load_config()
    sync_watchlist(config)

    tickers = parse_tickers(config)
    monitored = [t for t in tickers if t.source_type == 'monitored']
    yf_only = [t for t in tickers if t.source_type == 'yfinance_only']

    print(f"\n📊 配置摘要:")
    print(f"  Monitored: {len(monitored)} 只")
    print(f"  YFinance Only: {len(yf_only)} 只")
    print(f"  Benchmark: {get_benchmark(config)}")
    print(f"\n  Monitored 列表:")
    for t in monitored:
        status = "✅" if t.enabled else "❌"
        print(f"    {status} {t.symbol:6s} {t.name:30s} [{t.sector}]")
    print(f"\n  YFinance Only 列表:")
    for t in yf_only:
        print(f"    ✅ {t.symbol:6s} {t.name:30s} [{t.sector}]")
