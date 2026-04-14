#!/usr/bin/env python3
"""
数据迁移脚本 — 从 workspace/stocks 导入历史数据到 SQLite

迁移内容:
  1. config/tickers.json → watchlist 表
  2. data/prices/*.csv   → stock_prices 表
  3. state/*.json        → strategy_states 表

用法:
  python scripts/migrate_prices.py --source <PATH>
"""

import csv
import json
import sys
import argparse
from pathlib import Path
from datetime import datetime

# 将项目根目录加入 sys.path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from lib.db import (
    init_db, get_db, upsert_prices, get_price_count,
    upsert_strategy_state, upsert_strategy_states_batch,
    get_db_stats,
)
from lib.config import load_config, sync_watchlist


def migrate_config(source_dir: Path):
    """迁移 tickers.json → watchlist 表"""
    config_file = source_dir / "config" / "tickers.json"
    if not config_file.exists():
        print(f"⚠️ 配置文件不存在: {config_file}")
        return

    # 同时复制一份到新项目的 config 目录
    dest_config = PROJECT_ROOT / "config" / "tickers.json"
    dest_config.parent.mkdir(parents=True, exist_ok=True)

    import shutil
    shutil.copy2(config_file, dest_config)
    print(f"📋 已复制配置文件到: {dest_config}")

    # 同步到数据库
    config = load_config(dest_config)
    sync_watchlist(config)


def migrate_prices(source_dir: Path):
    """迁移 data/prices/*.csv → stock_prices 表"""
    prices_dir = source_dir / "data" / "prices"
    if not prices_dir.exists():
        print(f"⚠️ 价格目录不存在: {prices_dir}")
        return

    csv_files = sorted(prices_dir.glob("*.csv"))
    if not csv_files:
        print(f"⚠️ 没有找到 CSV 文件: {prices_dir}")
        return

    print(f"\n📥 开始迁移价格数据: {len(csv_files)} 个文件")

    total_rows = 0
    success = 0
    failed = []

    for csv_file in csv_files:
        symbol = csv_file.stem  # AAPL.csv → AAPL
        try:
            rows = []
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        rows.append({
                            'date': row['Date'].strip(),
                            'open': float(row['Open']),
                            'high': float(row['High']),
                            'low': float(row['Low']),
                            'close': float(row['Close']),
                            'volume': int(float(row.get('Volume', 0) or 0)),
                        })
                    except (ValueError, KeyError) as e:
                        continue  # 跳过格式异常行

            if rows:
                upsert_prices(symbol, rows)
                total_rows += len(rows)
                success += 1
                print(f"  ✅ {symbol:6s} — {len(rows)} 行 ({rows[0]['date']} ~ {rows[-1]['date']})")
            else:
                print(f"  ⚠️ {symbol:6s} — 无有效数据")
                failed.append(symbol)

        except Exception as e:
            print(f"  ❌ {symbol:6s} — 错误: {e}")
            failed.append(symbol)

    print(f"\n✅ 价格迁移完成: {success}/{len(csv_files)} 只成功, 共 {total_rows} 行")
    if failed:
        print(f"❌ 失败: {failed}")


def migrate_state(source_dir: Path):
    """迁移 state/*.json → strategy_states 表"""
    state_dir = source_dir / "state"
    if not state_dir.exists():
        print(f"⚠️ 状态目录不存在: {state_dir}")
        return

    print(f"\n📥 开始迁移策略状态")

    # 1. Stage 2 状态
    s2_file = state_dir / "stage2_state.json"
    if s2_file.exists():
        with open(s2_file, 'r', encoding='utf-8') as f:
            s2_state = json.load(f)

        states = []
        for symbol, info in s2_state.items():
            if isinstance(info, dict):
                states.append({
                    'symbol': symbol,
                    'is_active': info.get('is_stage2', False),
                    'entry_date': info.get('entry_date'),
                    'entry_price': info.get('entry_price'),
                    'extra': {},
                })
            else:
                states.append({
                    'symbol': symbol,
                    'is_active': bool(info),
                    'extra': {},
                })

        upsert_strategy_states_batch(states, 'stage2')
        active = sum(1 for s in states if s['is_active'])
        print(f"  ✅ Stage 2: {len(states)} 条 ({active} 活跃)")

    # 2. VCP 状态
    vcp_file = state_dir / "vcp_state.json"
    if vcp_file.exists():
        with open(vcp_file, 'r', encoding='utf-8') as f:
            vcp_state = json.load(f)

        states = []
        for symbol, info in vcp_state.items():
            if isinstance(info, dict):
                states.append({
                    'symbol': symbol,
                    'is_active': info.get('is_vcp', False),
                    'entry_date': info.get('first_detected'),
                    'entry_price': info.get('price_at_detection'),
                    'extra': {'vcp_score': info.get('vcp_score')},
                })

        upsert_strategy_states_batch(states, 'vcp')
        active = sum(1 for s in states if s['is_active'])
        print(f"  ✅ VCP: {len(states)} 条 ({active} 活跃)")

    # 3. Bottom Fisher 状态
    bf_file = state_dir / "bottom_fisher_state.json"
    if bf_file.exists():
        with open(bf_file, 'r', encoding='utf-8') as f:
            bf_state = json.load(f)

        states = []
        for symbol, info in bf_state.items():
            if isinstance(info, dict):
                states.append({
                    'symbol': symbol,
                    'is_active': info.get('is_bottom_signal', False),
                    'entry_date': info.get('first_detected'),
                    'entry_price': info.get('price_at_detection'),
                    'extra': {'bf_score': info.get('bf_score')},
                })

        upsert_strategy_states_batch(states, 'bottom_fisher')
        active = sum(1 for s in states if s['is_active'])
        print(f"  ✅ Bottom Fisher: {len(states)} 条 ({active} 活跃)")

    # 4. Market Pulse 状态
    pulse_file = state_dir / "market_pulse_state.json"
    if pulse_file.exists():
        with open(pulse_file, 'r', encoding='utf-8') as f:
            pulse_state = json.load(f)

        from lib.db import save_market_pulse
        save_market_pulse(
            date_str=pulse_state.get('date', datetime.now().strftime('%Y-%m-%d')),
            regime=pulse_state.get('regime', 'unknown'),
            composite_score=pulse_state.get('composite_score', 0),
            component_scores=pulse_state.get('scores', {}),
            spy_price=pulse_state.get('spy_price'),
            vix_value=pulse_state.get('vix_value'),
        )
        print(f"  ✅ Market Pulse: {pulse_state.get('regime')} ({pulse_state.get('composite_score')}/100)")

    print(f"\n✅ 策略状态迁移完成")


def main():
    parser = argparse.ArgumentParser(description="从 workspace/stocks 迁移数据到 SQLite")
    parser.add_argument(
        "--source",
        type=str,
        required=True,
        help="源数据目录路径 (如 D:/eh/projects/workspace/stocks)",
    )
    parser.add_argument(
        "--skip-prices",
        action="store_true",
        help="跳过价格数据迁移（仅迁移配置和状态）",
    )
    args = parser.parse_args()

    source_dir = Path(args.source)
    if not source_dir.exists():
        print(f"❌ 源目录不存在: {source_dir}")
        sys.exit(1)

    print("=" * 60)
    print("📦 Stock Tracker 数据迁移工具")
    print(f"   源目录: {source_dir}")
    print(f"   目标数据库: {PROJECT_ROOT / 'data' / 'stock_tracker.db'}")
    print("=" * 60)

    # 1. 初始化数据库
    print("\n🔧 初始化数据库...")
    init_db()

    # 2. 迁移配置
    print("\n📋 迁移配置文件...")
    migrate_config(source_dir)

    # 3. 迁移价格数据
    if not args.skip_prices:
        migrate_prices(source_dir)
    else:
        print("\n⏭️ 跳过价格数据迁移")

    # 4. 迁移策略状态
    migrate_state(source_dir)

    # 5. 显示统计
    print("\n" + "=" * 60)
    stats = get_db_stats()
    print("📊 数据库统计:")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print("=" * 60)
    print("\n🎉 迁移完成！")


if __name__ == "__main__":
    main()
