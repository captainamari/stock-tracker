#!/usr/bin/env python3
"""
Bottom Fisher v2.0 — 抄底信号扫描器
左侧交易策略：寻找超跌到位、即将反转的股票

v2.0 变更：
  - 从 SQLite DB 读取价格数据和 Stage 2 状态
  - 策略结果/状态/信号变化写入 DB
  - 使用 lib.indicators 共享技术指标库
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

from lib.encoding_fix import ensure_utf8_output
ensure_utf8_output()

from lib.db import (
    init_db, get_prices_as_dataframe,
    save_strategy_results_batch, upsert_strategy_states_batch,
    get_strategy_states, record_signal_change,
)
from lib.config import load_config, get_monitored_tickers
from lib.indicators import (
    sma, rsi, macd, detect_rsi_divergence, detect_macd_divergence, detect_hammer,
)
from lib.report import render_template, save_reports as save_report_files

# 路径
LOGS_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOGS_DIR / "bottom_fisher.log"

# 抄底参数
BF_PARAMS = {
    "price_to_sma200_range": (-15, 10),
    "min_stage2_conditions": 4,
    "min_drawdown_from_52w_high": -15,
    "min_drawdown_from_20d_high": -8,
    "support_proximity_pct": 3.0,
    "rsi_period": 14,
    "rsi_oversold": 35,
    "rsi_divergence_window": 20,
    "vol_ratio_threshold": 0.6,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "hammer_body_ratio": 0.3,
    "hammer_lower_shadow_ratio": 2.0,
    "confirmation_vol_ratio": 1.5,
    "strong_signal_min": 5,
    "near_signal_min": 3,
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


def _detect_volume_confirmation(data):
    """检测次日放量确认"""
    if 'Volume' not in data.columns or len(data) < 2:
        return False, ""
    vol_today = data['Volume'].iloc[-1]
    vol_yesterday = data['Volume'].iloc[-2]
    if vol_yesterday <= 0:
        return False, ""
    ratio = vol_today / vol_yesterday
    if ratio >= BF_PARAMS["confirmation_vol_ratio"]:
        return True, f"当日量 {ratio:.1f}x 前日"
    return False, ""


def analyze_bottom(ticker, ticker_info, data, stage2_states):
    """对单只股票执行完整的抄底分析"""
    params = BF_PARAMS
    close = data['Close']
    volume = data['Volume'] if 'Volume' in data.columns else None
    latest_price = close.iloc[-1]

    conditions = {}
    details = {}
    metrics = {}
    bonuses = {}

    # ============ L1: 质地过滤 ============

    # C1: 价格在 MA200 附近
    if len(data) >= 200:
        sma200_val = sma(close, 200).iloc[-1]
        pct_from_sma200 = (latest_price / sma200_val - 1) * 100
        lo, hi = params["price_to_sma200_range"]
        c1 = bool(lo <= pct_from_sma200 <= hi)
        conditions['C1'] = c1
        metrics['sma200'] = round(sma200_val, 2)
        metrics['pct_from_sma200'] = round(pct_from_sma200, 1)
        if not c1:
            if pct_from_sma200 < lo:
                details['C1'] = f"价格远低于 MA200 ({pct_from_sma200:+.1f}%)"
            else:
                details['C1'] = f"价格远高于 MA200 ({pct_from_sma200:+.1f}%)"
    else:
        conditions['C1'] = None
        metrics['sma200'] = None
        metrics['pct_from_sma200'] = None

    # C2: 质地判断
    s2_info = stage2_states.get(ticker, {})
    is_or_was_stage2 = False
    s2_passed = 0

    if isinstance(s2_info, dict):
        if s2_info.get('is_active', False):
            is_or_was_stage2 = True
            s2_passed = 8
        elif s2_info.get('entry_date'):
            is_or_was_stage2 = True
            s2_passed = params["min_stage2_conditions"]

    if not is_or_was_stage2 and len(data) >= 200:
        sma50_q = sma(close, 50).iloc[-1]
        sma200_q = metrics.get('sma200') or sma(close, 200).iloc[-1]
        quick_checks = [
            latest_price > sma200_q,
            sma50_q > sma200_q,
            latest_price > close.tail(252).min() * 1.25,
            latest_price > close.tail(252).max() * 0.75,
        ]
        s2_passed = sum(quick_checks)

    c2 = bool(is_or_was_stage2 or s2_passed >= params["min_stage2_conditions"])
    conditions['C2'] = c2
    metrics['stage2_quality'] = s2_passed
    if not c2:
        details['C2'] = f"质地不足 (Stage2 条件 {s2_passed}/{params['min_stage2_conditions']})"

    # ============ L2: 跌幅充分 ============

    # C3: 距52周高点回撤
    week52_high = close.tail(252).max()
    week52_low = close.tail(252).min()
    pct_from_52w_high = (latest_price / week52_high - 1) * 100
    c3 = bool(pct_from_52w_high <= params["min_drawdown_from_52w_high"])
    conditions['C3'] = c3
    metrics['pct_from_52w_high'] = round(pct_from_52w_high, 1)
    metrics['week52_high'] = round(week52_high, 2)
    metrics['week52_low'] = round(week52_low, 2)
    if not c3:
        details['C3'] = f"回撤不充分 ({pct_from_52w_high:+.1f}%)"

    # C4: 距20日高点回撤
    high_20d = close.tail(20).max()
    pct_from_20d_high = (latest_price / high_20d - 1) * 100
    c4 = bool(pct_from_20d_high <= params["min_drawdown_from_20d_high"])
    conditions['C4'] = c4
    metrics['pct_from_20d_high'] = round(pct_from_20d_high, 1)
    if not c4:
        details['C4'] = f"近期跌幅不够 ({pct_from_20d_high:+.1f}%)"

    # C5: 价格在关键支撑带
    support_hit = False
    nearest_support = None
    nearest_support_name = None
    support_levels = {}

    if len(data) >= 200:
        sma50_v = sma(close, 50).iloc[-1]
        sma150_v = sma(close, 150).iloc[-1]
        sma200_v = metrics.get('sma200') or sma(close, 200).iloc[-1]
        support_levels = {
            'MA50': round(sma50_v, 2), 'MA150': round(sma150_v, 2), 'MA200': round(sma200_v, 2),
        }
        for name, level in support_levels.items():
            pct_dist = abs(latest_price / level - 1) * 100
            if pct_dist <= params["support_proximity_pct"]:
                support_hit = True
                if nearest_support is None or pct_dist < abs(latest_price / nearest_support - 1) * 100:
                    nearest_support = level
                    nearest_support_name = name

    c5 = support_hit
    conditions['C5'] = c5
    metrics['support_levels'] = support_levels
    metrics['nearest_support'] = nearest_support_name
    if not c5:
        if support_levels:
            dists = {n: f"{(latest_price/v-1)*100:+.1f}%" for n, v in support_levels.items()}
            details['C5'] = f"未靠近关键支撑 ({', '.join(f'{n} {d}' for n, d in dists.items())})"
        else:
            details['C5'] = "数据不足"

    # ============ L3: 底部信号 ============

    # C6: RSI 超卖或底背离
    rsi_series = rsi(close, params["rsi_period"])
    current_rsi = rsi_series.iloc[-1] if not pd.isna(rsi_series.iloc[-1]) else None

    rsi_oversold = False
    rsi_div = False
    rsi_div_detail = ""
    if current_rsi is not None:
        rsi_oversold = bool(current_rsi <= params["rsi_oversold"])
        rsi_div, rsi_div_detail = detect_rsi_divergence(close, rsi_series, params["rsi_divergence_window"])

    c6 = rsi_oversold or rsi_div
    conditions['C6'] = c6
    metrics['rsi'] = round(current_rsi, 1) if current_rsi is not None else None
    metrics['rsi_oversold'] = rsi_oversold
    metrics['rsi_divergence'] = rsi_div
    if not c6:
        rsi_str = f"{current_rsi:.1f}" if current_rsi is not None else "N/A"
        details['C6'] = f"RSI 未超卖且无背离 (RSI={rsi_str})"

    # C7: 成交量萎缩到极值
    if volume is not None and len(data) >= 50:
        vol_10d = volume.tail(10).mean()
        vol_50d = volume.tail(50).mean()
        vol_ratio = vol_10d / vol_50d if vol_50d > 0 else 1.0
        c7 = bool(vol_ratio < params["vol_ratio_threshold"])
        conditions['C7'] = c7
        metrics['vol_ratio'] = round(vol_ratio, 2)
        if not c7:
            details['C7'] = f"卖压尚未枯竭 (量比 {vol_ratio:.2f})"
    else:
        conditions['C7'] = None
        metrics['vol_ratio'] = None

    # C8: MACD 底背离
    macd_line, signal_line, histogram = macd(
        close, params["macd_fast"], params["macd_slow"], params["macd_signal"]
    )
    current_macd = macd_line.iloc[-1] if not pd.isna(macd_line.iloc[-1]) else None
    current_signal_v = signal_line.iloc[-1] if not pd.isna(signal_line.iloc[-1]) else None
    current_hist = histogram.iloc[-1] if not pd.isna(histogram.iloc[-1]) else None
    macd_div, macd_div_detail = detect_macd_divergence(close, histogram)

    c8 = macd_div
    conditions['C8'] = c8
    metrics['macd'] = round(current_macd, 3) if current_macd is not None else None
    metrics['macd_signal'] = round(current_signal_v, 3) if current_signal_v is not None else None
    metrics['macd_histogram'] = round(current_hist, 3) if current_hist is not None else None
    metrics['macd_divergence'] = macd_div
    if not c8:
        details['C8'] = "MACD 无底背离且柱状图未翻正"

    # ============ L4: K线确认（加分项）============

    is_hammer, pattern_name, hammer_detail = detect_hammer(data, params["hammer_body_ratio"], params["hammer_lower_shadow_ratio"])
    bonuses['B1'] = is_hammer
    metrics['candle_pattern'] = pattern_name if is_hammer else ""
    if is_hammer:
        metrics['candle_detail'] = hammer_detail

    vol_confirmed, vol_confirm_detail = _detect_volume_confirmation(data)
    bonuses['B2'] = vol_confirmed
    if vol_confirmed:
        metrics['vol_confirm_detail'] = vol_confirm_detail

    # ============ 综合评分 ============
    valid = {k: v for k, v in conditions.items() if v is not None}
    passed = sum(1 for v in valid.values() if v)
    total = len(valid)
    is_bottom_signal = passed >= params["strong_signal_min"]

    bf_score = 0
    weights = {
        'C1': 8, 'C2': 7, 'C3': 10, 'C4': 10, 'C5': 15,
        'C6': 15, 'C7': 10, 'C8': 10,
    }
    for k, w in weights.items():
        v = conditions.get(k)
        if v is not None and bool(v):
            bf_score += w

    if bonuses.get('B1'):
        bf_score = min(bf_score + 10, 100)
    if bonuses.get('B2'):
        bf_score = min(bf_score + 5, 100)
    if metrics.get('rsi_divergence') and metrics.get('macd_divergence'):
        bf_score = min(bf_score + 10, 100)

    sma50_val = sma(close, 50).iloc[-1] if len(data) >= 50 else None
    sma10_val = sma(close, 10).iloc[-1] if len(data) >= 10 else None
    chg_5d = round((latest_price / close.iloc[-6] - 1) * 100, 1) if len(data) >= 6 else None
    chg_20d = round((latest_price / close.iloc[-21] - 1) * 100, 1) if len(data) >= 21 else None

    name = ticker_info.name if hasattr(ticker_info, 'name') else ticker_info.get('name', ticker)
    sector = ticker_info.sector if hasattr(ticker_info, 'sector') else ticker_info.get('sector', '')

    return {
        'ticker': ticker,
        'name': name,
        'sector': sector,
        'price': round(latest_price, 2),
        'conditions': conditions,
        'condition_details': details,
        'bonuses': bonuses,
        'metrics': metrics,
        'passed': passed,
        'total': total,
        'is_bottom_signal': is_bottom_signal,
        'bf_score': min(int(bf_score), 100),
        'week52_high': round(week52_high, 2),
        'week52_low': round(week52_low, 2),
        'sma50': round(sma50_val, 2) if sma50_val else None,
        'sma200': metrics.get('sma200'),
        'sma10': round(sma10_val, 2) if sma10_val else None,
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
            'is_signal': r['is_bottom_signal'],
            'score': r['bf_score'],
            'passed': r['passed'],
            'total': r['total'],
            'conditions': r['conditions'],
            'condition_details': r.get('condition_details', {}),
            'metrics': {
                'name': r['name'], 'sector': r['sector'], 'price': r['price'],
                'bf_score': r['bf_score'], 'bonuses': r.get('bonuses', {}),
                'week52_high': r['week52_high'], 'week52_low': r['week52_low'],
                'sma50': r.get('sma50'), 'sma200': r.get('sma200'), 'sma10': r.get('sma10'),
                'chg_5d': r.get('chg_5d'), 'chg_20d': r.get('chg_20d'),
                **{k: v for k, v in r.get('metrics', {}).items() if k not in ('support_levels',)},
            },
            'summary': f"{'BF' if r['is_bottom_signal'] else '--'} {r['ticker']} {r['passed']}/{r['total']} Score:{r['bf_score']}",
        })
    if db_results:
        save_strategy_results_batch(db_results, 'bottom_fisher', date_str)
        log(f"  策略结果已写入 DB: {len(db_results)} 条")


def save_states_to_db(current_state):
    states = []
    for ticker, info in current_state.items():
        if isinstance(info, dict):
            states.append({
                'symbol': ticker,
                'is_active': info.get('is_bottom_signal', False),
                'entry_date': info.get('first_detected'),
                'entry_price': info.get('price_at_detection'),
                'extra': {'bf_score': info.get('bf_score', 0)},
            })
        else:
            states.append({'symbol': ticker, 'is_active': False})
    if states:
        upsert_strategy_states_batch(states, 'bottom_fisher')
        log(f"  策略状态已更新: {len(states)} 条")


def save_signal_changes_to_db(changes, date_str):
    for c in changes:
        change_type = 'new_signal' if c['type'] == 'new_signal' else 'lost_signal'
        record_signal_change(
            symbol=c['ticker'], date_str=date_str, strategy='bottom_fisher',
            change_type=change_type, price=c.get('price'), score=c.get('bf_score'),
            details={k: v for k, v in c.items() if k not in ('ticker', 'type', 'price')},
        )
    if changes:
        log(f"  信号变化已记录: {len(changes)} 条")


# ============================================================
# 状态变化检测
# ============================================================
def detect_bf_changes(results, previous_bf_state):
    changes = []
    today = datetime.now().strftime('%Y-%m-%d')
    current_state = {}

    for r in results:
        ticker = r['ticker']
        prev = previous_bf_state.get(ticker, {})
        was_signal = prev.get('is_active', False) or prev.get('is_bottom_signal', False) if isinstance(prev, dict) else False
        is_now = r['is_bottom_signal']

        if is_now and not was_signal:
            changes.append({
                'ticker': ticker, 'type': 'new_signal',
                'name': r['name'], 'sector': r['sector'],
                'price': r['price'], 'bf_score': r['bf_score'],
                'passed': r['passed'], 'total': r['total'],
            })
            current_state[ticker] = {
                'is_bottom_signal': True, 'first_detected': today,
                'price_at_detection': r['price'], 'bf_score': r['bf_score'],
            }
        elif is_now and was_signal:
            current_state[ticker] = {
                'is_bottom_signal': True,
                'first_detected': prev.get('first_detected', prev.get('entry_date', today)),
                'price_at_detection': prev.get('price_at_detection', prev.get('entry_price', r['price'])),
                'bf_score': r['bf_score'],
            }
        elif not is_now and was_signal:
            changes.append({
                'ticker': ticker, 'type': 'lost_signal',
                'name': r['name'], 'price': r['price'],
            })
            current_state[ticker] = {'is_bottom_signal': False}
        else:
            current_state[ticker] = {'is_bottom_signal': False}

    return current_state, changes


def _load_previous_bf_state_from_db():
    states = get_strategy_states('bottom_fisher')
    result = {}
    for s in states:
        result[s['symbol']] = {
            'is_active': bool(s.get('is_active', False)),
            'is_bottom_signal': bool(s.get('is_active', False)),
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
    signal_stocks = sorted([r for r in results if r['is_bottom_signal']],
                           key=lambda x: x['bf_score'], reverse=True)
    near_stocks = sorted([r for r in results if not r['is_bottom_signal'] and r['passed'] >= BF_PARAMS["near_signal_min"]],
                         key=lambda x: x['passed'], reverse=True)

    ctx = dict(
        timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        total_analyzed=len(results),
        signal_stocks=signal_stocks,
        near_stocks=near_stocks,
        changes=changes,
    )

    md_report = render_template('bottom_md.j2', **ctx)
    ctx['timestamp'] = datetime.now().strftime('%m/%d %H:%M')
    tg_report = render_template('bottom_tg.j2', **ctx)

    return md_report, tg_report


# ============================================================
# 主流程
# ============================================================
def parse_args():
    parser = argparse.ArgumentParser(description="Bottom Fisher v2.0")
    parser.add_argument("--cron", action="store_true", help="Cron 模式")
    return parser.parse_args()


def main():
    args = parse_args()
    log("开始执行抄底信号扫描...")

    init_db()

    # 从 DB 加载 Stage 2 状态
    stage2_states_list = get_strategy_states('stage2')
    stage2_states = {s['symbol']: s for s in stage2_states_list}
    previous_bf_state = _load_previous_bf_state_from_db()

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

        result = analyze_bottom(ticker, ticker_info, data, stage2_states)
        results.append(result)
        status = "BF" if result['is_bottom_signal'] else f"  {result['passed']}/{result['total']}"
        log(f"  {ticker}: {status} (Score {result['bf_score']})")

    # 检测变化
    current_bf_state, changes = detect_bf_changes(results, previous_bf_state)

    # 写入 DB
    date_str = datetime.now().strftime('%Y-%m-%d')
    save_results_to_db(results, date_str)
    save_states_to_db(current_bf_state)
    save_signal_changes_to_db(changes, date_str)

    # 生成报告
    md_report, tg_report = generate_reports(results, changes)
    save_report_files(md_report, tg_report, strategy_prefix="_bottom", log_func=log)

    if not args.cron:
        print("\n" + "=" * 50)
        print(tg_report)
        print("=" * 50)

    signal_count = sum(1 for r in results if r['is_bottom_signal'])
    log(f"抄底扫描完成: {signal_count}/{len(results)} 触发信号")

    return changes


if __name__ == "__main__":
    main()
