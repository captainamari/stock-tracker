#!/usr/bin/env python3
"""
Market Pulse v3.0 — 市场宏观温度计
每日收盘后运行，输出市场整体状态

v3.0 变更：
  - 从 SQLite DB 读取价格数据和 Stage 2 状态
  - 结果写入 market_pulse 表
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
    save_market_pulse, get_latest_market_pulse,
    get_strategy_states,
)
from lib.config import load_config, get_monitored_tickers
from lib.indicators import sma, ema, rsi, macd, atr, consecutive_streak
from lib.report import render_template, save_reports as save_report_files

# 路径
LOGS_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOGS_DIR / "market_pulse.log"


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


# ============================================================
# 核心分析模块
# ============================================================
def analyze_index(ticker, data):
    """分析单个指数/ETF 的趋势状态 (v2.0)"""
    if data is None or len(data) < 50:
        return None

    close = data['Close']
    latest_price = close.iloc[-1]
    result = {'ticker': ticker, 'price': round(latest_price, 2)}

    # 经典均线
    sma50 = sma(close, 50).iloc[-1] if len(data) >= 50 else None
    sma200 = sma(close, 200).iloc[-1] if len(data) >= 200 else None
    result['sma50'] = round(sma50, 2) if sma50 else None
    result['sma200'] = round(sma200, 2) if sma200 else None

    if sma50:
        result['pct_vs_sma50'] = round((latest_price / sma50 - 1) * 100, 2)
    if sma200:
        result['pct_vs_sma200'] = round((latest_price / sma200 - 1) * 100, 2)

    if sma50 and sma200:
        result['ma_cross'] = 'golden' if sma50 > sma200 else 'death'
    else:
        result['ma_cross'] = None

    if len(data) >= 220:
        sma200_20d_ago = sma(close, 200).iloc[-20]
        result['sma200_rising'] = bool(sma200 > sma200_20d_ago)
        result['sma200_slope'] = round((sma200 / sma200_20d_ago - 1) * 100, 2)
    else:
        result['sma200_rising'] = None
        result['sma200_slope'] = None

    # EMA65/EMA170 — 模拟周线趋势
    ema65 = None
    ema170 = None
    if len(data) >= 65:
        ema65_series = ema(close, 65)
        ema65 = ema65_series.iloc[-1]
        result['ema65'] = round(ema65, 2)
        result['pct_vs_ema65'] = round((latest_price / ema65 - 1) * 100, 2)
        result['ema65_rising'] = bool(ema65 > ema65_series.iloc[-6]) if len(ema65_series) >= 6 else None
    else:
        result['ema65'] = None
        result['pct_vs_ema65'] = None
        result['ema65_rising'] = None

    if len(data) >= 170:
        ema170_series = ema(close, 170)
        ema170 = ema170_series.iloc[-1]
        result['ema170'] = round(ema170, 2)
        result['pct_vs_ema170'] = round((latest_price / ema170 - 1) * 100, 2)
        result['ema170_rising'] = bool(ema170 > ema170_series.iloc[-21]) if len(ema170_series) >= 21 else None
    else:
        result['ema170'] = None
        result['pct_vs_ema170'] = None
        result['ema170_rising'] = None

    if ema65 is not None and ema170 is not None:
        result['weekly_aligned'] = bool(ema65 > ema170)
    else:
        result['weekly_aligned'] = None

    # EMA8/EMA21 短期
    if len(data) >= 21:
        ema8 = ema(close, 8).iloc[-1]
        ema21 = ema(close, 21).iloc[-1]
        result['ema8'] = round(ema8, 2)
        result['ema21'] = round(ema21, 2)
        result['short_term_aligned'] = bool(ema8 > ema21)
        result['pct_ema8_vs_ema21'] = round((ema8 / ema21 - 1) * 100, 2)
    else:
        result['ema8'] = None
        result['ema21'] = None
        result['short_term_aligned'] = None
        result['pct_ema8_vs_ema21'] = None

    # MACD
    if len(data) >= 35:
        macd_line, signal_line, histogram = macd(close)
        macd_val = macd_line.iloc[-1]
        hist_val = histogram.iloc[-1]
        hist_prev = histogram.iloc[-2]
        result['macd'] = round(macd_val, 4)
        result['macd_signal'] = round(signal_line.iloc[-1], 4)
        result['macd_hist'] = round(hist_val, 4)
        result['macd_hist_prev'] = round(hist_prev, 4)
        result['macd_positive'] = bool(macd_val > 0)
        result['macd_hist_rising'] = bool(hist_val > hist_prev)
    else:
        for k in ['macd', 'macd_signal', 'macd_hist', 'macd_hist_prev', 'macd_positive', 'macd_hist_rising']:
            result[k] = None

    # RSI
    rsi_series = rsi(close)
    current_rsi = rsi_series.iloc[-1]
    result['rsi'] = round(current_rsi, 1) if not pd.isna(current_rsi) else None

    # ATR
    atr_series = atr(data)
    current_atr = atr_series.iloc[-1]
    result['atr'] = round(current_atr, 2) if not pd.isna(current_atr) else None
    if not pd.isna(current_atr) and latest_price > 0:
        result['atr_pct'] = round(current_atr / latest_price * 100, 2)
    else:
        result['atr_pct'] = None

    # 涨跌幅
    result['chg_1d'] = round((latest_price / close.iloc[-2] - 1) * 100, 2) if len(data) >= 2 else None
    result['chg_5d'] = round((latest_price / close.iloc[-6] - 1) * 100, 2) if len(data) >= 6 else None
    result['chg_20d'] = round((latest_price / close.iloc[-21] - 1) * 100, 2) if len(data) >= 21 else None

    # 连涨/连跌
    streak_str, streak_days = consecutive_streak(close)
    result['streak'] = streak_str
    result['streak_days'] = streak_days

    # 52周
    w52_high = close.tail(252).max() if len(data) >= 252 else close.max()
    w52_low = close.tail(252).min() if len(data) >= 252 else close.min()
    result['pct_from_52w_high'] = round((latest_price / w52_high - 1) * 100, 1)
    result['pct_from_52w_low'] = round((latest_price / w52_low - 1) * 100, 1)

    # 趋势评分 v2.0 (0-100)
    score = 0
    # 位置类 45 分
    if sma50 and latest_price > sma50: score += 10
    if sma200 and latest_price > sma200: score += 10
    if result.get('ma_cross') == 'golden': score += 10
    if result.get('sma200_rising'): score += 5
    if ema65 is not None and latest_price > ema65: score += 5
    if result.get('weekly_aligned'): score += 5
    # 动量类 30 分
    if result.get('macd_positive'): score += 8
    if result.get('macd_hist_rising'): score += 7
    if result.get('short_term_aligned'): score += 5
    if result.get('chg_5d') is not None:
        c5 = result['chg_5d']
        if c5 > 2: score += 10
        elif c5 > 0: score += 7
        elif c5 > -2: score += 3
    # 确认类 25 分
    if result.get('rsi'):
        r = result['rsi']
        if 40 <= r <= 70: score += 10
        elif 30 <= r < 40 or 70 < r <= 80: score += 5
    pct_hi = result.get('pct_from_52w_high', -100)
    if pct_hi > -5: score += 10
    elif pct_hi > -10: score += 7
    elif pct_hi > -20: score += 3
    if result.get('ema170_rising'): score += 5

    result['trend_score'] = min(score, 100)
    return result


def analyze_vix(data):
    """分析 VIX"""
    if data is None or len(data) < 10:
        return None
    close = data['Close']
    latest = close.iloc[-1]
    result = {'ticker': 'VIX', 'value': round(latest, 2)}

    if latest < 15:
        result['zone'], result['zone_label'], result['zone_emoji'] = 'low', '极度乐观', '😎'
    elif latest < 20:
        result['zone'], result['zone_label'], result['zone_emoji'] = 'normal', '正常', '😐'
    elif latest < 25:
        result['zone'], result['zone_label'], result['zone_emoji'] = 'elevated', '偏高', '😟'
    elif latest < 30:
        result['zone'], result['zone_label'], result['zone_emoji'] = 'high', '恐慌', '😨'
    else:
        result['zone'], result['zone_label'], result['zone_emoji'] = 'extreme', '极度恐慌', '🤯'

    result['chg_1d'] = round((latest / close.iloc[-2] - 1) * 100, 1) if len(data) >= 2 else None
    result['chg_5d'] = round((latest / close.iloc[-6] - 1) * 100, 1) if len(data) >= 6 else None

    if len(data) >= 20:
        sma20 = close.rolling(20).mean().iloc[-1]
        result['sma20'] = round(sma20, 2)
        result['vs_sma20'] = round((latest / sma20 - 1) * 100, 1)
    else:
        result['sma20'] = None
        result['vs_sma20'] = None

    if latest < 12: result['score'] = 100
    elif latest < 15: result['score'] = 85
    elif latest < 18: result['score'] = 70
    elif latest < 22: result['score'] = 55
    elif latest < 25: result['score'] = 40
    elif latest < 30: result['score'] = 25
    elif latest < 35: result['score'] = 10
    else: result['score'] = 0

    return result


def analyze_breadth(stage2_states):
    """分析内部市场宽度（基于监控股票池）"""
    tickers = get_monitored_tickers()
    total = len(tickers)
    if total == 0:
        return None

    above_sma50 = 0
    above_sma200 = 0
    stage2_count = 0
    up_5d = 0
    up_20d = 0
    analyzed = 0
    sector_scores = {}

    for t in tickers:
        ticker = t.symbol
        data = get_prices_as_dataframe(ticker, min_rows=50)
        if data is None:
            continue

        close = data['Close']
        latest = close.iloc[-1]
        analyzed += 1

        if len(data) >= 50:
            sma50_v = sma(close, 50).iloc[-1]
            if latest > sma50_v:
                above_sma50 += 1

        if len(data) >= 200:
            sma200_v = sma(close, 200).iloc[-1]
            if latest > sma200_v:
                above_sma200 += 1

        s2_info = stage2_states.get(ticker, {})
        is_s2 = isinstance(s2_info, dict) and s2_info.get('is_active', False)
        if is_s2:
            stage2_count += 1

        if len(data) >= 6 and latest > close.iloc[-6]:
            up_5d += 1
        if len(data) >= 21 and latest > close.iloc[-21]:
            up_20d += 1

        sector = t.sector or 'Other'
        sector_scores.setdefault(sector, []).append(is_s2)

    if analyzed == 0:
        return None

    result = {
        'total': total, 'analyzed': analyzed,
        'above_sma50': above_sma50,
        'above_sma50_pct': round(above_sma50 / analyzed * 100, 0),
        'above_sma200': above_sma200,
        'above_sma200_pct': round(above_sma200 / analyzed * 100, 0),
        'stage2_count': stage2_count,
        'stage2_pct': round(stage2_count / analyzed * 100, 0),
        'up_5d': up_5d,
        'up_5d_pct': round(up_5d / analyzed * 100, 0),
        'up_20d': up_20d,
        'up_20d_pct': round(up_20d / analyzed * 100, 0),
    }

    sector_ranking = []
    for sector, s2_list in sector_scores.items():
        cnt = len(s2_list)
        s2_cnt = sum(s2_list)
        sector_ranking.append({
            'sector': sector, 'total': cnt, 'stage2': s2_cnt,
            'pct': round(s2_cnt / cnt * 100, 0) if cnt > 0 else 0,
        })
    sector_ranking.sort(key=lambda x: x['pct'], reverse=True)
    result['sector_ranking'] = sector_ranking

    score = 0
    score += min(result['above_sma50_pct'] * 0.35, 35)
    score += min(result['above_sma200_pct'] * 0.25, 25)
    score += min(result['stage2_pct'] * 0.25, 25)
    score += min(result['up_5d_pct'] * 0.15, 15)
    result['breadth_score'] = round(min(score, 100), 0)

    return result


def calculate_composite_score(spy_result, qqq_result, iwm_result, vix_result, breadth_result):
    scores = {}
    weights = {}
    if spy_result: scores['SPY'], weights['SPY'] = spy_result['trend_score'], 0.30
    if qqq_result: scores['QQQ'], weights['QQQ'] = qqq_result['trend_score'], 0.15
    if iwm_result: scores['IWM'], weights['IWM'] = iwm_result['trend_score'], 0.10
    if vix_result: scores['VIX'], weights['VIX'] = vix_result['score'], 0.25
    if breadth_result: scores['Breadth'], weights['Breadth'] = breadth_result['breadth_score'], 0.20
    if not weights:
        return 50, scores
    total_weight = sum(weights.values())
    composite = sum(scores[k] * weights[k] / total_weight for k in scores)
    return round(composite, 0), scores


def determine_regime(composite_score, spy_result, vix_result):
    if composite_score >= 70:
        regime, emoji, label, hint = 'bullish', '🟢', 'BULLISH', '趋势强劲，积极寻找入场机会'
    elif composite_score >= 50:
        regime, emoji, label, hint = 'neutral', '🟡', 'NEUTRAL', '方向不明，控制仓位'
    elif composite_score >= 35:
        regime, emoji, label, hint = 'cautious', '🟠', 'CAUTIOUS', '弱势市场，减少新仓'
    else:
        regime, emoji, label, hint = 'bearish', '🔴', 'BEARISH', '下行趋势，现金为王'

    if vix_result:
        if vix_result['value'] >= 30 and regime != 'bearish':
            regime, emoji, label, hint = 'bearish', '🔴', 'BEARISH (VIX极端)', '恐慌指数飙升，暂停买入'
        elif vix_result['value'] < 13 and regime == 'bullish':
            hint += ' ⚠️ VIX极低'

    if spy_result and spy_result.get('pct_vs_sma200') is not None:
        if spy_result['pct_vs_sma200'] < -3 and regime not in ('bearish', 'cautious'):
            regime, emoji, label, hint = 'cautious', '🟠', 'CAUTIOUS (SPY<MA200)', 'SPY 跌破200日均线'

    return regime, emoji, label, hint


# ============================================================
# 报告生成（Jinja2 模板）
# ============================================================
def generate_reports(composite, scores, regime_info, spy, qqq, iwm, vix, breadth, prev_state):
    """使用 Jinja2 模板生成 MD 和 Telegram 报告"""
    regime, regime_emoji, regime_label, hint = regime_info
    prev_regime = prev_state.get('regime', 'unknown') if prev_state else 'unknown'
    prev_regime_emojis = {'bullish': '🟢', 'neutral': '🟡', 'cautious': '🟠', 'bearish': '🔴'}
    regime_changed = prev_regime != regime and prev_regime != 'unknown'

    indices = [spy, qqq, iwm]
    hot_sectors = []
    if breadth:
        hot_sectors = [s for s in breadth.get('sector_ranking', []) if s['stage2'] > 0]

    ctx = dict(
        timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        composite=composite,
        scores=scores,
        regime=regime,
        regime_emoji=regime_emoji,
        regime_label=regime_label,
        hint=hint,
        regime_changed=regime_changed,
        prev_regime=prev_regime,
        prev_regime_emoji=prev_regime_emojis.get(prev_regime, '❓'),
        indices=indices,
        vix=vix,
        breadth=breadth,
        hot_sectors=hot_sectors,
    )

    md_report = render_template('pulse_md.j2', **ctx)
    ctx['timestamp'] = datetime.now().strftime('%m/%d %H:%M')
    tg_report = render_template('pulse_tg.j2', **ctx)

    return md_report, tg_report


# ============================================================
# 主流程
# ============================================================
def parse_args():
    parser = argparse.ArgumentParser(description="Market Pulse v3.0")
    parser.add_argument("--cron", action="store_true", help="Cron 模式")
    return parser.parse_args()


def main():
    args = parse_args()
    log("开始执行 Market Pulse 分析...")

    init_db()

    # 从 DB 加载 Stage 2 状态
    stage2_states_list = get_strategy_states('stage2')
    stage2_states = {s['symbol']: s for s in stage2_states_list}

    # 获取上次状态
    prev_pulse = get_latest_market_pulse()
    prev_state = prev_pulse if prev_pulse else {}

    # 加载指数数据
    log("加载指数数据...")
    spy_data = get_prices_as_dataframe('SPY', min_rows=50)
    qqq_data = get_prices_as_dataframe('QQQ', min_rows=20)
    iwm_data = get_prices_as_dataframe('IWM', min_rows=20)
    vix_data = get_prices_as_dataframe('VIX', min_rows=10)

    # 分析
    log("分析指数趋势...")
    spy_result = analyze_index('SPY', spy_data)
    qqq_result = analyze_index('QQQ', qqq_data)
    iwm_result = analyze_index('IWM', iwm_data)

    if spy_result: log(f"  SPY: ${spy_result['price']} · Score {spy_result['trend_score']}/100")
    else: log("  SPY: 数据不可用", "WARNING")
    if qqq_result: log(f"  QQQ: ${qqq_result['price']} · Score {qqq_result['trend_score']}/100")
    if iwm_result: log(f"  IWM: ${iwm_result['price']} · Score {iwm_result['trend_score']}/100")

    log("分析 VIX...")
    vix_result = analyze_vix(vix_data)
    if vix_result: log(f"  VIX: {vix_result['value']} {vix_result['zone_emoji']}")

    log("分析内部宽度...")
    breadth_result = analyze_breadth(stage2_states)
    if breadth_result:
        log(f"  >MA50: {breadth_result['above_sma50_pct']:.0f}% · Stage2: {breadth_result['stage2_pct']:.0f}%")

    # 综合评分
    composite, scores = calculate_composite_score(
        spy_result, qqq_result, iwm_result, vix_result, breadth_result
    )
    regime_info = determine_regime(composite, spy_result, vix_result)
    regime, emoji, label, hint = regime_info
    log(f"综合评分: {composite}/100 · {label}")

    # 写入 DB: market_pulse 表
    date_str = datetime.now().strftime('%Y-%m-%d')
    save_market_pulse(
        date_str=date_str,
        regime=regime,
        composite_score=composite,
        component_scores=scores,
        spy_price=spy_result['price'] if spy_result else None,
        vix_value=vix_result['value'] if vix_result else None,
        index_data={
            'SPY': spy_result if spy_result else {},
            'QQQ': qqq_result if qqq_result else {},
            'IWM': iwm_result if iwm_result else {},
            'VIX': vix_result if vix_result else {},
        },
        breadth_data=breadth_result if breadth_result else {},
    )
    log("  Market Pulse 已写入 DB")

    # 生成报告
    md_report, tg_report = generate_reports(
        composite, scores, regime_info,
        spy_result, qqq_result, iwm_result, vix_result, breadth_result, prev_state
    )
    save_report_files(md_report, tg_report, strategy_prefix="_pulse", log_func=log)

    if not args.cron:
        print("\n" + "=" * 50)
        print(tg_report)
        print("=" * 50)

    log(f"Market Pulse 完成: {emoji} {regime.upper()} ({composite}/100)")
    return regime_info


if __name__ == "__main__":
    main()
