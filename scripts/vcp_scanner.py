#!/usr/bin/env python3
"""
VCP Scanner v2.0 — Volatility Contraction Pattern 扫描器
基于 Mark Minervini 的 VCP 形态识别理论

v2.0 变更：
  - 从 SQLite DB 读取价格数据和 Stage 2 状态
  - 策略计算结果写入 strategy_results 表
  - 策略状态写入 strategy_states 表
  - 信号变化写入 signal_changes 表
  - 使用 lib.indicators 共享技术指标库
  - 使用 lib.config 加载配置

设计原则：
  - VCP 是 Stage 2 之上的"择时策略"，用于寻找即将突破的股票
  - 读取 DB strategy_states 表，仅分析已确认 Stage 2 的股票
  - 复用 DB 中的价格数据，零重复拉取
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
import sys
import argparse
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from lib.db import (
    init_db, get_prices_as_dataframe,
    save_strategy_results_batch, upsert_strategy_states_batch,
    get_strategy_states, get_strategy_state, record_signal_change,
)
from lib.config import load_config, parse_tickers
from lib.indicators import sma, bollinger_bandwidth, bbw_percentile
from lib.report import render_template, save_reports as save_report_files

# 路径
LOGS_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOGS_DIR / "vcp_scanner.log"

# ============================================================
# VCP 参数
# ============================================================
VCP_PARAMS = {
    "max_drawdown_from_52w_high": -25,
    "max_drawdown_from_20d_high": -10,
    "bbw_percentile_threshold": 25,
    "bbw_lookback": 120,
    "bb_period": 20,
    "bb_std": 2.0,
    "vol_ratio_threshold": 0.75,
    "vol_dry_days": 5,
    "vol_dry_min_count": 4,
    "sma50_slope_min": 0.0,
    "price_to_sma10_max_dev": 3.0,
    "strong_signal_min": 4,
}


def log(message, level="INFO"):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"[{timestamp}] [{level}] {message}"
    print(log_entry)
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(log_entry + '\n')
    except Exception:
        pass


def analyze_vcp(ticker, ticker_info, data, stage2_entry_info):
    """对单只股票执行完整的 VCP 分析"""
    params = VCP_PARAMS
    close = data['Close']
    volume = data['Volume'] if 'Volume' in data.columns else None
    latest_price = close.iloc[-1]

    conditions = {}
    details = {}
    metrics = {}

    # C1: 距52周高点回撤
    week52_high = close.tail(252).max()
    pct_from_52w_high = (latest_price / week52_high - 1) * 100
    c1 = bool(pct_from_52w_high >= params["max_drawdown_from_52w_high"])
    conditions['C1'] = c1
    metrics['pct_from_52w_high'] = round(pct_from_52w_high, 1)
    if not c1:
        details['C1'] = f"距52周高点回撤过大 ({pct_from_52w_high:+.1f}%)"

    # C2: 距20日最高价回撤
    high_20d = close.tail(20).max()
    pct_from_20d_high = (latest_price / high_20d - 1) * 100
    c2 = bool(pct_from_20d_high >= params["max_drawdown_from_20d_high"])
    conditions['C2'] = c2
    metrics['pct_from_20d_high'] = round(pct_from_20d_high, 1)
    if not c2:
        details['C2'] = f"近期回撤过大 ({pct_from_20d_high:+.1f}%)"

    # C3: 布林带挤压
    bbw = bollinger_bandwidth(close, params["bb_period"], params["bb_std"])
    current_bbw = bbw.iloc[-1]
    lookback = min(params["bbw_lookback"], len(bbw.dropna()))
    if lookback >= 20:
        bbw_history = bbw.tail(lookback).dropna()
        bbw_pctile = (bbw_history < current_bbw).sum() / len(bbw_history) * 100 if len(bbw_history) > 0 else 50
    else:
        bbw_pctile = 50

    c3 = bool(bbw_pctile <= params["bbw_percentile_threshold"])
    conditions['C3'] = c3
    metrics['bbw'] = round(current_bbw, 2)
    metrics['bbw_percentile'] = round(bbw_pctile, 0)
    if not c3:
        details['C3'] = f"波动率未收缩 (BBW {current_bbw:.1f}, P{bbw_pctile:.0f}%)"

    # C4: 成交量枯竭
    if volume is not None and len(data) >= 50:
        vol_10d = volume.tail(10).mean()
        vol_50d = volume.tail(50).mean()
        vol_ratio = vol_10d / vol_50d if vol_50d > 0 else 1.0
        c4_ratio = bool(vol_ratio < params["vol_ratio_threshold"])
        recent_vol = volume.tail(params["vol_dry_days"])
        days_below_avg = int((recent_vol < vol_50d).sum())
        c4_sustained = bool(days_below_avg >= params["vol_dry_min_count"])
        c4 = c4_ratio and c4_sustained
        conditions['C4'] = c4
        metrics['vol_ratio'] = round(vol_ratio, 2)
        metrics['vol_dry_days'] = int(days_below_avg)
        if not c4:
            parts = []
            if not c4_ratio:
                parts.append(f"量比 {vol_ratio:.2f}")
            if not c4_sustained:
                parts.append(f"仅 {days_below_avg}/{params['vol_dry_days']} 天缩量")
            details['C4'] = "成交量未枯竭: " + "; ".join(parts)
    else:
        conditions['C4'] = None
        metrics['vol_ratio'] = None

    # C5: SMA50 斜率为正
    if len(data) >= 70:
        sma50 = close.rolling(50).mean()
        sma50_now = sma50.iloc[-1]
        sma50_20d_ago = sma50.iloc[-20]
        sma50_slope = (sma50_now / sma50_20d_ago - 1) * 100 if sma50_20d_ago > 0 else 0
        c5 = bool(sma50_slope > params["sma50_slope_min"])
        conditions['C5'] = c5
        metrics['sma50_slope'] = round(sma50_slope, 2)
        if not c5:
            details['C5'] = f"50日均线走平/下行 ({sma50_slope:+.2f}%/20d)"
    else:
        conditions['C5'] = None
        metrics['sma50_slope'] = None

    # C6: 价格靠近 SMA10
    sma10 = close.rolling(10).mean().iloc[-1]
    pct_from_sma10 = (latest_price / sma10 - 1) * 100
    c6 = bool(abs(pct_from_sma10) <= params["price_to_sma10_max_dev"])
    conditions['C6'] = c6
    metrics['pct_from_sma10'] = round(pct_from_sma10, 1)
    metrics['sma10'] = round(sma10, 2)
    if not c6:
        details['C6'] = f"偏离SMA10过远 ({pct_from_sma10:+.1f}%)"

    # 综合评分
    valid = {k: v for k, v in conditions.items() if v is not None}
    passed = sum(1 for v in valid.values() if v)
    total = len(valid)
    is_vcp = passed >= params["strong_signal_min"]

    vcp_score = 0
    weights = {'C1': 15, 'C2': 20, 'C3': 25, 'C4': 20, 'C5': 10, 'C6': 10}
    for k, w in weights.items():
        v = conditions.get(k)
        if v is not None and bool(v):
            vcp_score += w

    if bool(conditions.get('C3')) and metrics.get('bbw_percentile', 50) <= 10:
        vcp_score = min(vcp_score + 10, 100)
    if bool(conditions.get('C4')) and metrics.get('vol_dry_days', 0) >= params["vol_dry_days"]:
        vcp_score = min(vcp_score + 5, 100)

    # Stage 2 持续天数
    days_in_stage2 = 0
    entry_price = None
    if isinstance(stage2_entry_info, dict):
        entry_date = stage2_entry_info.get('entry_date')
        entry_price = stage2_entry_info.get('entry_price')
        if entry_date:
            try:
                days_in_stage2 = (datetime.now() - datetime.strptime(entry_date, '%Y-%m-%d')).days
            except Exception:
                pass

    # 关键价位
    sma50_val = close.rolling(50).mean().iloc[-1]
    sma150_val = close.rolling(150).mean().iloc[-1] if len(data) >= 150 else None
    week52_low = close.tail(252).min()

    chg_5d = round((latest_price / close.iloc[-6] - 1) * 100, 1) if len(data) >= 6 else None
    chg_20d = round((latest_price / close.iloc[-21] - 1) * 100, 1) if len(data) >= 21 else None

    return {
        'ticker': ticker,
        'name': ticker_info.get('name', ticker) if isinstance(ticker_info, dict) else getattr(ticker_info, 'name', ticker),
        'sector': ticker_info.get('sector', '') if isinstance(ticker_info, dict) else getattr(ticker_info, 'sector', ''),
        'price': round(latest_price, 2),
        'conditions': conditions,
        'condition_details': details,
        'metrics': metrics,
        'passed': passed,
        'total': total,
        'is_vcp': is_vcp,
        'vcp_score': min(int(vcp_score), 100),
        'days_in_stage2': days_in_stage2,
        'entry_price': entry_price,
        'week52_high': round(week52_high, 2),
        'week52_low': round(week52_low, 2),
        'sma50': round(sma50_val, 2),
        'sma150': round(sma150_val, 2) if sma150_val else None,
        'sma10': round(sma10, 2),
        'chg_5d': chg_5d,
        'chg_20d': chg_20d,
    }


# ============================================================
# DB 写入
# ============================================================
def save_results_to_db(results, date_str):
    db_results = []
    for r in results:
        db_results.append({
            'symbol': r['ticker'],
            'is_signal': r['is_vcp'],
            'score': r['vcp_score'],
            'passed': r['passed'],
            'total': r['total'],
            'conditions': r['conditions'],
            'condition_details': r.get('condition_details', {}),
            'metrics': {
                'name': r['name'], 'sector': r['sector'], 'price': r['price'],
                'vcp_score': r['vcp_score'], 'days_in_stage2': r['days_in_stage2'],
                'entry_price': r.get('entry_price'),
                'week52_high': r['week52_high'], 'week52_low': r['week52_low'],
                'sma50': r['sma50'], 'sma150': r.get('sma150'), 'sma10': r['sma10'],
                'chg_5d': r.get('chg_5d'), 'chg_20d': r.get('chg_20d'),
                **r.get('metrics', {}),
            },
            'summary': f"{'VCP' if r['is_vcp'] else '--'} {r['ticker']} {r['passed']}/{r['total']} Score:{r['vcp_score']}",
        })
    if db_results:
        save_strategy_results_batch(db_results, 'vcp', date_str)
        log(f"  策略结果已写入 DB: {len(db_results)} 条")


def save_states_to_db(current_state):
    states = []
    for ticker, info in current_state.items():
        if isinstance(info, dict):
            states.append({
                'symbol': ticker,
                'is_active': info.get('is_vcp', False),
                'entry_date': info.get('first_detected'),
                'entry_price': info.get('price_at_detection'),
                'extra': {'vcp_score': info.get('vcp_score', 0)},
            })
        else:
            states.append({'symbol': ticker, 'is_active': False})
    if states:
        upsert_strategy_states_batch(states, 'vcp')
        log(f"  策略状态已更新: {len(states)} 条")


def save_signal_changes_to_db(changes, date_str):
    for c in changes:
        change_type = 'new_signal' if c['type'] == 'new_vcp' else 'lost_signal'
        record_signal_change(
            symbol=c['ticker'], date_str=date_str, strategy='vcp',
            change_type=change_type, price=c.get('price'),
            score=c.get('vcp_score'),
            details={k: v for k, v in c.items() if k not in ('ticker', 'type', 'price')},
        )
    if changes:
        log(f"  信号变化已记录: {len(changes)} 条")


# ============================================================
# 状态变化检测
# ============================================================
def detect_vcp_changes(results, previous_vcp_state):
    changes = []
    today = datetime.now().strftime('%Y-%m-%d')
    current_state = {}

    for r in results:
        ticker = r['ticker']
        prev = previous_vcp_state.get(ticker, {})
        was_vcp = prev.get('is_active', False) or prev.get('is_vcp', False) if isinstance(prev, dict) else False
        is_now = r['is_vcp']

        if is_now and not was_vcp:
            changes.append({
                'ticker': ticker, 'type': 'new_vcp',
                'name': r['name'], 'sector': r['sector'],
                'price': r['price'], 'vcp_score': r['vcp_score'],
                'passed': r['passed'], 'total': r['total'],
            })
            current_state[ticker] = {
                'is_vcp': True, 'first_detected': today,
                'price_at_detection': r['price'], 'vcp_score': r['vcp_score'],
            }
        elif is_now and was_vcp:
            current_state[ticker] = {
                'is_vcp': True,
                'first_detected': prev.get('first_detected', prev.get('entry_date', today)),
                'price_at_detection': prev.get('price_at_detection', prev.get('entry_price', r['price'])),
                'vcp_score': r['vcp_score'],
            }
        elif not is_now and was_vcp:
            changes.append({
                'ticker': ticker, 'type': 'lost_vcp',
                'name': r['name'], 'price': r['price'],
            })
            current_state[ticker] = {'is_vcp': False}
        else:
            current_state[ticker] = {'is_vcp': False}

    return current_state, changes


def _load_previous_vcp_state_from_db():
    states = get_strategy_states('vcp')
    result = {}
    for s in states:
        result[s['symbol']] = {
            'is_active': bool(s.get('is_active', False)),
            'is_vcp': bool(s.get('is_active', False)),
            'entry_date': s.get('entry_date'),
            'first_detected': s.get('entry_date'),
            'entry_price': s.get('entry_price'),
            'price_at_detection': s.get('entry_price'),
            **s.get('extra', {}),
        }
    return result


# ============================================================
# 报告生成（Jinja2 模板）
# ============================================================
def generate_reports(results, changes):
    """使用 Jinja2 模板生成 MD 和 Telegram 报告"""
    vcp_stocks = sorted([r for r in results if r['is_vcp']],
                        key=lambda x: x['vcp_score'], reverse=True)
    near_vcp = sorted([r for r in results if not r['is_vcp'] and r['passed'] >= 3],
                      key=lambda x: x['passed'], reverse=True)

    ctx = dict(
        timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        total_analyzed=len(results),
        vcp_stocks=vcp_stocks,
        near_vcp=near_vcp,
        changes=changes,
    )

    md_report = render_template('vcp_md.j2', **ctx)
    ctx['timestamp'] = datetime.now().strftime('%m/%d %H:%M')
    tg_report = render_template('vcp_tg.j2', **ctx)

    return md_report, tg_report


# ============================================================
# 主流程
# ============================================================
def parse_args():
    parser = argparse.ArgumentParser(description="VCP Scanner v2.0")
    parser.add_argument("--cron", action="store_true", help="Cron 模式")
    return parser.parse_args()


def main():
    args = parse_args()
    log("开始执行 VCP 扫描...")

    init_db()
    config = load_config()

    # 从 DB 加载 Stage 2 状态
    stage2_states = get_strategy_states('stage2')
    stage2_tickers = {
        s['symbol']: s for s in stage2_states
        if s.get('is_active', False)
    }

    previous_vcp_state = _load_previous_vcp_state_from_db()

    if not stage2_tickers:
        log("当前无 Stage 2 股票，VCP 扫描终止")
        tg_report = "<b>🎯 VCP Scanner</b>\n⚠️ No Stage 2 stocks. Run stage2_monitor.py first."
        save_report_files("# VCP 扫描报告\n\n⚠️ 当前无 Stage 2 股票\n", tg_report, strategy_prefix="_vcp", log_func=log)
        save_states_to_db({})
        if not args.cron:
            print("\n" + "=" * 50)
            print(tg_report)
            print("=" * 50)
        return []

    log(f"Stage 2 股票数: {len(stage2_tickers)}")

    # 构建 ticker_info 映射
    ticker_info_map = {}
    for t in parse_tickers(config):
        ticker_info_map[t.symbol] = {'name': t.name, 'sector': t.sector, 'symbol': t.symbol}

    # 逐只分析
    results = []
    for ticker, s2_info in stage2_tickers.items():
        t_info = ticker_info_map.get(ticker, {'symbol': ticker, 'name': ticker, 'sector': ''})
        data = get_prices_as_dataframe(ticker, min_rows=200)
        if data is None:
            log(f"  {ticker} 数据不足，跳过", "WARNING")
            continue

        result = analyze_vcp(ticker, t_info, data, s2_info)
        results.append(result)
        status = "VCP" if result['is_vcp'] else f"  {result['passed']}/{result['total']}"
        log(f"  {ticker}: {status} (Score {result['vcp_score']})")

    # 检测变化
    current_vcp_state, changes = detect_vcp_changes(results, previous_vcp_state)

    # 写入 DB
    date_str = datetime.now().strftime('%Y-%m-%d')
    save_results_to_db(results, date_str)
    save_states_to_db(current_vcp_state)
    save_signal_changes_to_db(changes, date_str)

    # 生成报告
    md_report, tg_report = generate_reports(results, changes)
    save_report_files(md_report, tg_report, strategy_prefix="_vcp", log_func=log)

    if not args.cron:
        print("\n" + "=" * 50)
        print(tg_report)
        print("=" * 50)

    vcp_count = sum(1 for r in results if r['is_vcp'])
    log(f"VCP 扫描完成: {vcp_count}/{len(results)} 触发信号")

    return changes


if __name__ == "__main__":
    main()
