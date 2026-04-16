#!/usr/bin/env python3
"""
Buying Checklist v1.0 — 多维度买入检查清单
综合趋势、动量、成交量和技术形态的买入决策辅助策略

检查维度:
  L1: 趋势确认（周线 Elder Impulse + 日线均线排列）
  L2: 动量健康（RSI 区间 + MACD 方向）
  L3: 价格结构（距高低点位置 + 支撑确认）
  L4: 成交量确认（量价配合 + 突破放量）
  L5: 综合加分（多策略共振 + K线形态）

v1.0:
  - 从 SQLite DB 读取价格数据和策略状态
  - 策略结果/状态/信号变化写入 DB
  - 使用 lib.indicators 共享技术指标库（含周线 Elder Impulse）
  - 使用 lib.config 加载配置
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
    get_strategy_states, record_signal_change,
)
from lib.config import load_config, get_monitored_tickers
from lib.indicators import (
    sma, ema, rsi, macd, atr, consecutive_streak,
    elder_impulse_weekly, pct_change, pct_from_value,
)
from lib.report import render_template, save_reports as save_report_files

# 路径
LOGS_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOGS_DIR / "buying_checklist.log"

# 策略参数
BC_PARAMS = {
    # L1: 趋势确认
    "weekly_impulse_required": "green",      # 周线 Elder Impulse 要求
    "daily_ema_fast": 10,                    # 日线快速 EMA
    "daily_ema_slow": 21,                    # 日线慢速 EMA
    "sma50_above_sma200": True,              # SMA50 > SMA200 (黄金交叉)

    # L2: 动量健康
    "rsi_period": 14,
    "rsi_healthy_low": 40,                   # RSI 下限（避免超卖陷阱）
    "rsi_healthy_high": 70,                  # RSI 上限（避免追高）
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,

    # L3: 价格结构
    "max_pct_from_52w_high": -25,            # 距52周高点最大回撤
    "min_pct_from_52w_low": 10,              # 距52周低点最小涨幅
    "price_above_sma50": True,               # 价格须在 SMA50 上方
    "price_above_sma200": True,              # 价格须在 SMA200 上方

    # L4: 成交量确认
    "vol_ratio_threshold": 1.0,              # 10日均量 / 50日均量 ≥ 1.0
    "vol_expansion_days": 3,                 # 近 N 天有放量

    # 综合
    "strong_signal_min": 7,                  # 强信号最少通过条件数
    "near_signal_min": 5,                    # 准信号最少通过条件数
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


def analyze_buying_checklist(ticker, ticker_info, data, stage2_states, bf_states):
    """对单只股票执行完整的买入检查清单分析"""
    params = BC_PARAMS
    close = data['Close']
    volume = data['Volume'] if 'Volume' in data.columns else None
    latest_price = close.iloc[-1]

    conditions = {}
    details = {}
    metrics = {}

    # ============ L1: 趋势确认 ============

    # C1: 周线 Elder Impulse 为 Green（多头冲量）
    elder_info = elder_impulse_weekly(data)
    weekly_impulse = elder_info['weekly_impulse']
    c1 = (weekly_impulse == params["weekly_impulse_required"])
    conditions['C1'] = c1
    metrics['weekly_impulse'] = weekly_impulse
    metrics['weekly_ema13'] = elder_info['weekly_ema13']
    metrics['weekly_macd_hist'] = elder_info['weekly_macd_hist']
    metrics['weekly_trend'] = elder_info['weekly_trend']
    metrics['impulse_streak'] = elder_info['impulse_streak']
    if not c1:
        details['C1'] = f"周线 Impulse 为 {weekly_impulse}（需要 green）"

    # C2: 日线 EMA10 > EMA21（短期上升趋势）
    if len(data) >= params["daily_ema_slow"]:
        ema_fast_val = ema(close, params["daily_ema_fast"]).iloc[-1]
        ema_slow_val = ema(close, params["daily_ema_slow"]).iloc[-1]
        c2 = bool(ema_fast_val > ema_slow_val)
        conditions['C2'] = c2
        metrics['ema10'] = round(float(ema_fast_val), 2)
        metrics['ema21'] = round(float(ema_slow_val), 2)
        if not c2:
            details['C2'] = f"EMA10 ({ema_fast_val:.2f}) ≤ EMA21 ({ema_slow_val:.2f})"
    else:
        conditions['C2'] = None

    # C3: SMA50 > SMA200（长期趋势向上 / 黄金交叉）
    if len(data) >= 200:
        sma50_val = sma(close, 50).iloc[-1]
        sma200_val = sma(close, 200).iloc[-1]
        c3 = bool(sma50_val > sma200_val)
        conditions['C3'] = c3
        metrics['sma50'] = round(float(sma50_val), 2)
        metrics['sma200'] = round(float(sma200_val), 2)
        if not c3:
            details['C3'] = f"SMA50 ({sma50_val:.2f}) ≤ SMA200 ({sma200_val:.2f})，死叉状态"
    else:
        conditions['C3'] = None
        metrics['sma50'] = round(float(sma(close, 50).iloc[-1]), 2) if len(data) >= 50 else None
        metrics['sma200'] = None

    # ============ L2: 动量健康 ============

    # C4: RSI 在健康区间 (40-70)
    rsi_series = rsi(close, params["rsi_period"])
    current_rsi = float(rsi_series.iloc[-1]) if not pd.isna(rsi_series.iloc[-1]) else None
    if current_rsi is not None:
        c4 = bool(params["rsi_healthy_low"] <= current_rsi <= params["rsi_healthy_high"])
        conditions['C4'] = c4
        metrics['rsi'] = round(current_rsi, 1)
        if not c4:
            if current_rsi < params["rsi_healthy_low"]:
                details['C4'] = f"RSI {current_rsi:.1f} 低于健康区间下限 {params['rsi_healthy_low']}"
            else:
                details['C4'] = f"RSI {current_rsi:.1f} 高于健康区间上限 {params['rsi_healthy_high']}"
    else:
        conditions['C4'] = None
        metrics['rsi'] = None

    # C5: MACD 柱状图上升（动量增强）
    macd_line, signal_line, histogram = macd(
        close, params["macd_fast"], params["macd_slow"], params["macd_signal"]
    )
    current_hist = float(histogram.iloc[-1]) if not pd.isna(histogram.iloc[-1]) else None
    prev_hist = float(histogram.iloc[-2]) if len(histogram) >= 2 and not pd.isna(histogram.iloc[-2]) else None

    if current_hist is not None and prev_hist is not None:
        c5 = bool(current_hist > prev_hist)
        conditions['C5'] = c5
        metrics['macd_histogram'] = round(current_hist, 3)
        metrics['macd_hist_prev'] = round(prev_hist, 3)
        if not c5:
            details['C5'] = f"MACD 柱状图下降 {prev_hist:.3f}→{current_hist:.3f}"
    else:
        conditions['C5'] = None
        metrics['macd_histogram'] = round(current_hist, 3) if current_hist else None

    # ============ L3: 价格结构 ============

    # C6: 价格在 SMA50 上方
    sma50_v = metrics.get('sma50') or (round(float(sma(close, 50).iloc[-1]), 2) if len(data) >= 50 else None)
    if sma50_v is not None:
        c6 = bool(latest_price > sma50_v)
        conditions['C6'] = c6
        if not c6:
            pct = (latest_price / sma50_v - 1) * 100
            details['C6'] = f"价格 ${latest_price:.2f} 低于 SMA50 ${sma50_v:.2f} ({pct:+.1f}%)"
    else:
        conditions['C6'] = None

    # C7: 距52周高点回撤不超过 25%（仍在趋势中）
    week52_high = float(close.tail(252).max())
    week52_low = float(close.tail(252).min())
    pct_from_52w_high = (latest_price / week52_high - 1) * 100
    c7 = bool(pct_from_52w_high >= params["max_pct_from_52w_high"])
    conditions['C7'] = c7
    metrics['week52_high'] = round(week52_high, 2)
    metrics['week52_low'] = round(week52_low, 2)
    metrics['pct_from_52w_high'] = round(pct_from_52w_high, 1)
    if not c7:
        details['C7'] = f"距52周高点回撤 {pct_from_52w_high:.1f}%，超过 {params['max_pct_from_52w_high']}% 阈值"

    # C8: 距52周低点已涨 ≥ 10%（确认脱离底部）
    pct_from_52w_low = (latest_price / week52_low - 1) * 100
    c8 = bool(pct_from_52w_low >= params["min_pct_from_52w_low"])
    conditions['C8'] = c8
    metrics['pct_from_52w_low'] = round(pct_from_52w_low, 1)
    if not c8:
        details['C8'] = f"距52周低点仅涨 {pct_from_52w_low:.1f}%，未充分脱离底部"

    # ============ L4: 成交量确认 ============

    # C9: 近10日均量 ≥ 50日均量（资金关注度）
    if volume is not None and len(data) >= 50:
        vol_10d = float(volume.tail(10).mean())
        vol_50d = float(volume.tail(50).mean())
        vol_ratio = vol_10d / vol_50d if vol_50d > 0 else 0
        c9 = bool(vol_ratio >= params["vol_ratio_threshold"])
        conditions['C9'] = c9
        metrics['vol_ratio'] = round(vol_ratio, 2)
        metrics['vol_10d'] = int(vol_10d)
        metrics['vol_50d'] = int(vol_50d)
        if not c9:
            details['C9'] = f"量比 {vol_ratio:.2f} 低于阈值 {params['vol_ratio_threshold']}"
    else:
        conditions['C9'] = None
        metrics['vol_ratio'] = None

    # C10: 近3天至少有1天成交量 > 50日均量的1.5倍（突破放量）
    if volume is not None and len(data) >= 50:
        vol_50d_v = float(volume.tail(50).mean())
        recent_vols = volume.tail(params["vol_expansion_days"])
        has_expansion = bool((recent_vols > vol_50d_v * 1.5).any())
        c10 = has_expansion
        conditions['C10'] = c10
        if not c10:
            details['C10'] = f"近 {params['vol_expansion_days']} 天无放量突破 (需 > {vol_50d_v*1.5:.0f})"
    else:
        conditions['C10'] = None

    # ============ L5: 综合加分（作为额外条件）============

    # C11: Stage 2 趋势确认（跨策略共振）
    s2_info = stage2_states.get(ticker, {})
    c11 = bool(isinstance(s2_info, dict) and s2_info.get('is_active', False))
    conditions['C11'] = c11
    metrics['stage2_active'] = c11
    if not c11:
        details['C11'] = "未处于 Stage 2 趋势中"

    # ============ 综合评分 ============
    valid = {k: v for k, v in conditions.items() if v is not None}
    passed = sum(1 for v in valid.values() if v)
    total = len(valid)
    is_bc_signal = passed >= params["strong_signal_min"]

    # 加权评分
    bc_score = 0
    weights = {
        'C1': 12, 'C2': 8, 'C3': 10,           # L1 趋势 (30)
        'C4': 8, 'C5': 7,                        # L2 动量 (15)
        'C6': 10, 'C7': 8, 'C8': 7,              # L3 价格 (25)
        'C9': 8, 'C10': 7,                        # L4 成交量 (15)
        'C11': 10,                                # L5 共振 (10)
    }
    for k, w in weights.items():
        v = conditions.get(k)
        if v is not None and bool(v):
            bc_score += w

    # 额外加分：周线连续 green ≥ 2 周
    if elder_info['impulse_streak'] >= 2:
        bc_score = min(bc_score + 5, 100)

    sma10_val = round(float(sma(close, 10).iloc[-1]), 2) if len(data) >= 10 else None
    chg_5d = round((latest_price / float(close.iloc[-6]) - 1) * 100, 1) if len(data) >= 6 else None
    chg_20d = round((latest_price / float(close.iloc[-21]) - 1) * 100, 1) if len(data) >= 21 else None

    name = ticker_info.name if hasattr(ticker_info, 'name') else ticker_info.get('name', ticker)
    sector = ticker_info.sector if hasattr(ticker_info, 'sector') else ticker_info.get('sector', '')

    return {
        'ticker': ticker,
        'name': name,
        'sector': sector,
        'price': round(latest_price, 2),
        'conditions': conditions,
        'condition_details': details,
        'metrics': metrics,
        'passed': passed,
        'total': total,
        'is_bc_signal': is_bc_signal,
        'bc_score': min(int(bc_score), 100),
        'weekly_impulse': weekly_impulse,
        'weekly_trend': elder_info['weekly_trend'],
        'impulse_streak': elder_info['impulse_streak'],
        'week52_high': round(week52_high, 2),
        'week52_low': round(week52_low, 2),
        'sma50': metrics.get('sma50'),
        'sma200': metrics.get('sma200'),
        'sma10': sma10_val,
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
            'is_signal': r['is_bc_signal'],
            'score': r['bc_score'],
            'passed': r['passed'],
            'total': r['total'],
            'conditions': r['conditions'],
            'condition_details': r.get('condition_details', {}),
            'metrics': {
                'name': r['name'], 'sector': r['sector'], 'price': r['price'],
                'bc_score': r['bc_score'],
                'weekly_impulse': r['weekly_impulse'],
                'weekly_trend': r['weekly_trend'],
                'impulse_streak': r['impulse_streak'],
                'week52_high': r['week52_high'], 'week52_low': r['week52_low'],
                'sma50': r.get('sma50'), 'sma200': r.get('sma200'), 'sma10': r.get('sma10'),
                'chg_5d': r.get('chg_5d'), 'chg_20d': r.get('chg_20d'),
                **{k: v for k, v in r.get('metrics', {}).items()
                   if k not in ('support_levels',)},
            },
            'summary': f"{'BC' if r['is_bc_signal'] else '--'} {r['ticker']} {r['passed']}/{r['total']} Score:{r['bc_score']}",
        })
    if db_results:
        save_strategy_results_batch(db_results, 'buying_checklist', date_str)
        log(f"  策略结果已写入 DB: {len(db_results)} 条")


def save_states_to_db(current_state):
    states = []
    for ticker, info in current_state.items():
        if isinstance(info, dict):
            states.append({
                'symbol': ticker,
                'is_active': info.get('is_bc_signal', False),
                'entry_date': info.get('first_detected'),
                'entry_price': info.get('price_at_detection'),
                'extra': {'bc_score': info.get('bc_score', 0)},
            })
        else:
            states.append({'symbol': ticker, 'is_active': False})
    if states:
        upsert_strategy_states_batch(states, 'buying_checklist')
        log(f"  策略状态已更新: {len(states)} 条")


def save_signal_changes_to_db(changes, date_str):
    for c in changes:
        change_type = 'new_signal' if c['type'] == 'new_signal' else 'lost_signal'
        record_signal_change(
            symbol=c['ticker'], date_str=date_str, strategy='buying_checklist',
            change_type=change_type, price=c.get('price'), score=c.get('bc_score'),
            details={k: v for k, v in c.items() if k not in ('ticker', 'type', 'price')},
        )
    if changes:
        log(f"  信号变化已记录: {len(changes)} 条")


# ============================================================
# 状态变化检测
# ============================================================
def detect_bc_changes(results, previous_bc_state):
    changes = []
    today = datetime.now().strftime('%Y-%m-%d')
    current_state = {}

    for r in results:
        ticker = r['ticker']
        prev = previous_bc_state.get(ticker, {})
        was_signal = prev.get('is_active', False) or prev.get('is_bc_signal', False) if isinstance(prev, dict) else False
        is_now = r['is_bc_signal']

        if is_now and not was_signal:
            changes.append({
                'ticker': ticker, 'type': 'new_signal',
                'name': r['name'], 'sector': r['sector'],
                'price': r['price'], 'bc_score': r['bc_score'],
                'passed': r['passed'], 'total': r['total'],
                'weekly_impulse': r['weekly_impulse'],
            })
            current_state[ticker] = {
                'is_bc_signal': True, 'first_detected': today,
                'price_at_detection': r['price'], 'bc_score': r['bc_score'],
            }
        elif is_now and was_signal:
            current_state[ticker] = {
                'is_bc_signal': True,
                'first_detected': prev.get('first_detected', prev.get('entry_date', today)),
                'price_at_detection': prev.get('price_at_detection', prev.get('entry_price', r['price'])),
                'bc_score': r['bc_score'],
            }
        elif not is_now and was_signal:
            changes.append({
                'ticker': ticker, 'type': 'lost_signal',
                'name': r['name'], 'price': r['price'],
            })
            current_state[ticker] = {'is_bc_signal': False}
        else:
            current_state[ticker] = {'is_bc_signal': False}

    return current_state, changes


def _load_previous_bc_state_from_db():
    states = get_strategy_states('buying_checklist')
    result = {}
    for s in states:
        result[s['symbol']] = {
            'is_active': bool(s.get('is_active', False)),
            'is_bc_signal': bool(s.get('is_active', False)),
            'entry_date': s.get('entry_date'),
            'first_detected': s.get('entry_date'),
            'entry_price': s.get('entry_price'),
            'price_at_detection': s.get('entry_price'),
            **s.get('extra', {}),
        }
    return result


# ============================================================
# 报告生成
# ============================================================
def generate_reports(results, changes):
    """生成文本摘要报告"""
    signal_stocks = sorted([r for r in results if r['is_bc_signal']],
                           key=lambda x: x['bc_score'], reverse=True)
    near_stocks = sorted([r for r in results if not r['is_bc_signal'] and r['passed'] >= BC_PARAMS["near_signal_min"]],
                         key=lambda x: x['passed'], reverse=True)

    lines = []
    lines.append(f"📋 Buying Checklist Report — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"分析 {len(results)} 只股票\n")

    if signal_stocks:
        lines.append(f"🟢 买入信号 ({len(signal_stocks)} 只):")
        for s in signal_stocks:
            imp = {'green': '🟢', 'red': '🔴', 'blue': '🔵'}.get(s['weekly_impulse'], '⚪')
            lines.append(f"  {s['ticker']:6s} {s['name'][:20]:20s} Score:{s['bc_score']:3d}  "
                         f"{s['passed']}/{s['total']}  {imp} ${s['price']:.2f}")
    else:
        lines.append("❌ 暂无买入信号")

    if near_stocks:
        lines.append(f"\n⏳ 接近信号 ({len(near_stocks)} 只):")
        for s in near_stocks[:10]:
            lines.append(f"  {s['ticker']:6s} {s['name'][:20]:20s} {s['passed']}/{s['total']}  "
                         f"Score:{s['bc_score']}")

    if changes:
        lines.append(f"\n🔔 信号变化 ({len(changes)} 条):")
        for c in changes:
            emoji = '🆕' if c['type'] == 'new_signal' else '⚪'
            lines.append(f"  {emoji} {c['ticker']} — {c['type']}")

    md_report = "\n".join(lines)
    tg_report = md_report  # 简化版本，TG 共用
    return md_report, tg_report


# ============================================================
# 主流程
# ============================================================
def parse_args():
    parser = argparse.ArgumentParser(description="Buying Checklist v1.0")
    parser.add_argument("--cron", action="store_true", help="Cron 模式")
    return parser.parse_args()


def main():
    args = parse_args()
    log("开始执行买入检查清单扫描...")

    init_db()

    # 从 DB 加载策略状态
    stage2_states_list = get_strategy_states('stage2')
    stage2_states = {s['symbol']: s for s in stage2_states_list}
    bf_states_list = get_strategy_states('bottom_fisher')
    bf_states = {s['symbol']: s for s in bf_states_list}
    previous_bc_state = _load_previous_bc_state_from_db()

    # 获取所有 monitored 股票
    tickers = get_monitored_tickers()
    log(f"监控股票数: {len(tickers)}")

    # 逐只分析
    results = []
    for ticker_info in tickers:
        ticker = ticker_info.symbol
        data = get_prices_as_dataframe(ticker, min_rows=200)
        if data is None:
            log(f"  {ticker} 数据不足，跳过", "WARNING")
            continue

        result = analyze_buying_checklist(ticker, ticker_info, data, stage2_states, bf_states)
        results.append(result)
        imp_emoji = {'green': '🟢', 'red': '🔴', 'blue': '🔵'}.get(result['weekly_impulse'], '⚪')
        status = f"BC {imp_emoji}" if result['is_bc_signal'] else f"   {result['passed']}/{result['total']}"
        log(f"  {ticker}: {status} (Score {result['bc_score']})")

    # 检测变化
    current_bc_state, changes = detect_bc_changes(results, previous_bc_state)

    # 写入 DB
    date_str = datetime.now().strftime('%Y-%m-%d')
    save_results_to_db(results, date_str)
    save_states_to_db(current_bc_state)
    save_signal_changes_to_db(changes, date_str)

    # 生成报告
    md_report, tg_report = generate_reports(results, changes)

    if not args.cron:
        print("\n" + "=" * 50)
        print(tg_report)
        print("=" * 50)

    signal_count = sum(1 for r in results if r['is_bc_signal'])
    log(f"买入检查清单扫描完成: {signal_count}/{len(results)} 触发信号")

    return changes


if __name__ == "__main__":
    main()
