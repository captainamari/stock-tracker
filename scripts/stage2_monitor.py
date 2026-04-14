#!/usr/bin/env python3
"""
Stage 2 股票监控脚本 v4.0
基于 Stan Weinstein 和 Mark Minervini 的趋势模板理论

v4.0 变更：
  - 从 SQLite DB 读取价格数据（替代 CSV 文件读取 + yfinance 回退）
  - 策略计算结果写入 strategy_results 表
  - 策略状态写入 strategy_states 表（替代 JSON state 文件）
  - 信号变化写入 signal_changes 表
  - 使用 lib.indicators 共享技术指标库
  - 使用 lib.config 加载配置
  - 报告生成逻辑暂时保留（Phase 3 改用 Jinja2 模板）
"""

import pandas as pd
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
from lib.config import load_config, get_monitored_tickers, get_benchmark, sync_watchlist
from lib.indicators import sma, pct_change, pct_from_value, normalize_tz
from lib.report import render_template, save_reports

# 路径
LOGS_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOGS_DIR / "stage2_monitor.log"

# 请求参数（现在只在 yfinance 回退时用到，正常情况不需要网络请求）
REQUEST_DELAY = 2  # 秒

# 内存缓存
_data_cache = {}


def log(message, level="INFO"):
    """记录日志"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"[{timestamp}] [{level}] {message}"
    print(log_entry)
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(log_entry + '\n')
    except Exception:
        pass


def fetch_stock_data(ticker, min_rows=200):
    """
    从 DB 获取股票数据，返回 DataFrame。
    缓存在内存中避免同一次运行重复读取。
    """
    if ticker in _data_cache:
        return _data_cache[ticker]

    df = get_prices_as_dataframe(ticker, min_rows=min_rows)
    if df is not None:
        log(f"  {ticker} 从 DB 加载 {len(df)} 条数据")
        _data_cache[ticker] = df
        return df

    log(f"  {ticker} DB 数据不足 (需 {min_rows} 条)，跳过", "WARNING")
    return None


def check_stage2_conditions(ticker_info):
    """检查 Stage 2 的 8 个条件，并记录每个条件的具体数值差距"""
    ticker = ticker_info.symbol
    log(f"📈 分析 {ticker} ({ticker_info.name})...")

    data = fetch_stock_data(ticker)
    if data is None or len(data) < 200:
        log(f"  {ticker} 数据不足，跳过", "WARNING")
        return None

    close = data['Close']

    # 计算均线
    sma50_series = sma(close, 50)
    sma150_series = sma(close, 150)
    sma200_series = sma(close, 200)

    price = close.iloc[-1]
    sma50_val = sma50_series.iloc[-1]
    sma150_val = sma150_series.iloc[-1]
    sma200_val = sma200_series.iloc[-1]
    sma200_20days_ago = sma200_series.iloc[-20] if len(data) >= 220 else sma200_series.iloc[0]

    week52_high = close.tail(252).max()
    week52_low = close.tail(252).min()

    # ---- 8 个条件 + 每个条件的诊断细节 ----
    conditions = {}
    details = {}

    # C1: 价格 > SMA150 且 > SMA200
    c1 = price > sma150_val and price > sma200_val
    conditions['C1'] = c1
    if not c1:
        gap150 = (price / sma150_val - 1) * 100
        gap200 = (price / sma200_val - 1) * 100
        worst = min(gap150, gap200)
        details['C1'] = f"价格低于长期均线 ({worst:+.1f}%)"

    # C2: SMA150 > SMA200
    c2 = sma150_val > sma200_val
    conditions['C2'] = c2
    if not c2:
        gap = (sma150_val / sma200_val - 1) * 100
        details['C2'] = f"150日均线仍低于200日 ({gap:+.1f}%)"

    # C3: SMA200 上升趋势 (vs 20天前)
    c3 = sma200_val > sma200_20days_ago
    conditions['C3'] = c3
    if not c3:
        gap = (sma200_val / sma200_20days_ago - 1) * 100
        details['C3'] = f"200日均线走平/下行 ({gap:+.1f}%/20d)"

    # C4: SMA50 > SMA150 且 > SMA200
    c4 = sma50_val > sma150_val and sma50_val > sma200_val
    conditions['C4'] = c4
    if not c4:
        gap150 = (sma50_val / sma150_val - 1) * 100
        gap200 = (sma50_val / sma200_val - 1) * 100
        worst = min(gap150, gap200)
        details['C4'] = f"短期均线尚未交叉 ({worst:+.1f}%)"

    # C5: 价格 > SMA50
    c5 = price > sma50_val
    conditions['C5'] = c5
    if not c5:
        gap = (price / sma50_val - 1) * 100
        details['C5'] = f"价格低于50日均线 ({gap:+.1f}%，需涨 ${sma50_val - price:.2f})"

    # C6: 价格 > 52周最低 × 1.25
    c6_threshold = week52_low * 1.25
    c6 = price > c6_threshold
    conditions['C6'] = c6
    if not c6:
        gap = (price / c6_threshold - 1) * 100
        details['C6'] = f"距52周低点涨幅不足25% ({gap:+.1f}%)"

    # C7: 价格 > 52周最高 × 0.75
    c7_threshold = week52_high * 0.75
    c7 = price > c7_threshold
    conditions['C7'] = c7
    if not c7:
        gap = (price / c7_threshold - 1) * 100
        details['C7'] = f"距52周高点回撤过大 ({gap:+.1f}%)"

    # C8: 6个月相对强度 > SPY
    benchmark_ticker = get_benchmark()
    spy_data = fetch_stock_data(benchmark_ticker, min_rows=126)
    stock_return_6m = None
    spy_return_6m = None

    if spy_data is not None and len(spy_data) >= 126 and len(data) >= 126:
        try:
            stock_return_6m = (close.iloc[-1] / close.iloc[-126] - 1) * 100
            spy_return_6m = (spy_data['Close'].iloc[-1] / spy_data['Close'].iloc[-126] - 1) * 100
            conditions['C8'] = stock_return_6m > spy_return_6m
            if not conditions['C8']:
                details['C8'] = f"跑输大盘 (个股 {stock_return_6m:+.1f}% vs SPY {spy_return_6m:+.1f}%)"
        except Exception as e:
            log(f"  {ticker} C8 计算失败: {e}", "WARNING")
            conditions['C8'] = None
    else:
        conditions['C8'] = None

    # ---- 汇总 ----
    valid_conditions = {k: v for k, v in conditions.items() if v is not None}
    is_stage2 = all(valid_conditions.values()) if valid_conditions else False

    # 额外指标
    pct_from_high = (price / week52_high - 1) * 100
    pct_from_low = (price / week52_low - 1) * 100
    pct_above_sma200 = (price / sma200_val - 1) * 100
    pct_above_sma50 = (price / sma50_val - 1) * 100

    # ---- 趋势强度评分 (Trend Power Score, 0-100) ----
    tp_score = 0.0
    # 1) 均线排列分 (0-25)
    if sma50_val > sma150_val > sma200_val:
        spread = (sma50_val / sma200_val - 1) * 100
        tp_score += min(spread * 2.5, 25)
    elif sma50_val > sma200_val:
        tp_score += 10
    # 2) 价格位置分 (0-25)
    if price > sma50_val:
        tp_score += min(pct_above_sma50 * 2.5, 25)
    # 3) 52周位置分 (0-25)
    range_52w = week52_high - week52_low if week52_high != week52_low else 1
    position_pct = (price - week52_low) / range_52w * 100
    tp_score += position_pct * 0.25
    # 4) 相对强度分 (0-25)
    if stock_return_6m is not None and spy_return_6m is not None:
        rs_diff = stock_return_6m - spy_return_6m
        tp_score += max(min(rs_diff * 1.25 + 12.5, 25), 0)
    tp_score = round(min(tp_score, 100), 0)

    # ---- 成交量信号 ----
    vol_signal = ""
    try:
        if 'Volume' in data.columns and len(data) >= 50:
            vol_20 = data['Volume'].tail(20).mean()
            vol_50 = data['Volume'].tail(50).mean()
            vol_today = data['Volume'].iloc[-1]
            if vol_today > vol_50 * 2:
                vol_signal = "放量"
            elif vol_20 > vol_50 * 1.3:
                vol_signal = "缩量上涨" if price > close.iloc[-5] else "放量回调"
            elif vol_20 < vol_50 * 0.7:
                vol_signal = "缩量"
    except Exception:
        pass

    # ---- 近期动量 ----
    chg_5d = round((price / close.iloc[-6] - 1) * 100, 1) if len(data) >= 6 else None
    chg_20d = round((price / close.iloc[-21] - 1) * 100, 1) if len(data) >= 21 else None

    # ---- SMA50 斜率 ----
    sma50_slope = None
    if len(data) >= 70:
        sma50_20d_ago = sma50_series.iloc[-20]
        if sma50_20d_ago > 0:
            sma50_slope = round((sma50_val / sma50_20d_ago - 1) * 100, 2)

    return {
        'ticker': ticker,
        'name': ticker_info.name,
        'sector': ticker_info.sector,
        'price': round(price, 2),
        'sma50': round(sma50_val, 2),
        'sma150': round(sma150_val, 2),
        'sma200': round(sma200_val, 2),
        'week52_high': round(week52_high, 2),
        'week52_low': round(week52_low, 2),
        'pct_from_high': round(pct_from_high, 1),
        'pct_from_low': round(pct_from_low, 1),
        'pct_above_sma200': round(pct_above_sma200, 1),
        'pct_above_sma50': round(pct_above_sma50, 1),
        'stock_return_6m': round(stock_return_6m, 1) if stock_return_6m is not None else None,
        'spy_return_6m': round(spy_return_6m, 1) if spy_return_6m is not None else None,
        'conditions': conditions,
        'condition_details': details,
        'is_stage2': is_stage2,
        'passed': sum(1 for v in valid_conditions.values() if v),
        'total': len(valid_conditions),
        'trend_power': int(tp_score),
        'vol_signal': vol_signal,
        'chg_5d': chg_5d,
        'chg_20d': chg_20d,
        'sma50_slope': sma50_slope,
        'support_sma50': round(sma50_val, 2),
        'support_sma150': round(sma150_val, 2),
        'support_sma200': round(sma200_val, 2),
    }


# ============================================================
# DB 写入
# ============================================================
def save_results_to_db(results, date_str):
    """将所有策略计算结果批量写入 DB"""
    db_results = []
    for r in results:
        if not r:
            continue
        db_results.append({
            'symbol': r['ticker'],
            'is_signal': r['is_stage2'],
            'score': r['trend_power'],
            'passed': r['passed'],
            'total': r['total'],
            'conditions': r['conditions'],
            'condition_details': r.get('condition_details', {}),
            'metrics': {
                'name': r['name'],
                'sector': r['sector'],
                'price': r['price'],
                'sma50': r['sma50'],
                'sma150': r['sma150'],
                'sma200': r['sma200'],
                'week52_high': r['week52_high'],
                'week52_low': r['week52_low'],
                'pct_from_high': r['pct_from_high'],
                'pct_from_low': r['pct_from_low'],
                'pct_above_sma200': r['pct_above_sma200'],
                'pct_above_sma50': r['pct_above_sma50'],
                'trend_power': r['trend_power'],
                'vol_signal': r['vol_signal'],
                'stock_return_6m': r.get('stock_return_6m'),
                'spy_return_6m': r.get('spy_return_6m'),
                'chg_5d': r.get('chg_5d'),
                'chg_20d': r.get('chg_20d'),
                'sma50_slope': r.get('sma50_slope'),
            },
            'summary': f"{'S2' if r['is_stage2'] else '--'} {r['ticker']} {r['passed']}/{r['total']} TP:{r['trend_power']}",
        })

    if db_results:
        save_strategy_results_batch(db_results, 'stage2', date_str)
        log(f"  策略结果已写入 DB: {len(db_results)} 条")


def save_states_to_db(current_state):
    """将策略状态写入 DB"""
    states = []
    for ticker, info in current_state.items():
        if isinstance(info, dict):
            states.append({
                'symbol': ticker,
                'is_active': info.get('is_stage2', False),
                'entry_date': info.get('entry_date'),
                'entry_price': info.get('entry_price'),
                'extra': {k: v for k, v in info.items()
                          if k not in ('is_stage2', 'entry_date', 'entry_price')},
            })
        else:
            states.append({
                'symbol': ticker,
                'is_active': bool(info),
            })

    if states:
        upsert_strategy_states_batch(states, 'stage2')
        log(f"  策略状态已更新: {len(states)} 条")


def save_signal_changes_to_db(changes, date_str):
    """将信号变化写入 DB"""
    for c in changes:
        change_type = 'entry' if c['type'] == 'entry' else 'exit'
        record_signal_change(
            symbol=c['ticker'],
            date_str=date_str,
            strategy='stage2',
            change_type=change_type,
            price=c.get('price'),
            score=c.get('trend_power'),
            details={k: v for k, v in c.items() if k not in ('ticker', 'type', 'price')},
        )
    if changes:
        log(f"  信号变化已记录: {len(changes)} 条")


# ============================================================
# 状态变化检测
# ============================================================
def _detect_changes(results, previous_state):
    """检测状态变化"""
    changes = []
    today = datetime.now().strftime('%Y-%m-%d')

    def _was_stage2(ticker):
        v = previous_state.get(ticker, {})
        if isinstance(v, dict):
            return v.get('is_active', False) or v.get('is_stage2', False)
        return bool(v)

    def _entry_date(ticker):
        v = previous_state.get(ticker, {})
        if isinstance(v, dict):
            return v.get('entry_date')
        return None

    current_state = {}
    for r in results:
        if not r:
            continue
        ticker = r['ticker']
        was = _was_stage2(ticker)
        is_now = r['is_stage2']

        if is_now and not was:
            changes.append({
                'ticker': ticker, 'type': 'entry',
                'name': r['name'], 'sector': r['sector'],
                'price': r['price'], 'trend_power': r.get('trend_power', 0),
                'pct_from_high': r.get('pct_from_high', 0),
                'stock_return_6m': r.get('stock_return_6m'),
            })
            current_state[ticker] = {
                'is_stage2': True, 'entry_date': today,
                'entry_price': r['price'],
            }
        elif not is_now and was:
            entry_date = _entry_date(ticker)
            days_held = 0
            if entry_date:
                try:
                    days_held = (datetime.now() - datetime.strptime(entry_date, '%Y-%m-%d')).days
                except Exception:
                    pass
            failed = [k for k, v in r['conditions'].items() if v is False]
            changes.append({
                'ticker': ticker, 'type': 'exit',
                'name': r['name'], 'sector': r['sector'],
                'price': r['price'], 'days_held': days_held,
                'failed_conditions': failed,
                'condition_details': r.get('condition_details', {}),
            })
            current_state[ticker] = {'is_stage2': False}
        elif is_now and was:
            entry_date = _entry_date(ticker) or today
            prev_info = previous_state.get(ticker, {})
            entry_price = prev_info.get('entry_price', r['price']) if isinstance(prev_info, dict) else r['price']
            current_state[ticker] = {
                'is_stage2': True, 'entry_date': entry_date,
                'entry_price': entry_price,
            }
        else:
            current_state[ticker] = {'is_stage2': False}

    return current_state, changes


def _load_previous_state_from_db():
    """从 DB 加载上一次的策略状态"""
    states = get_strategy_states('stage2')
    result = {}
    for s in states:
        result[s['symbol']] = {
            'is_stage2': bool(s.get('is_active', False)),
            'is_active': bool(s.get('is_active', False)),
            'entry_date': s.get('entry_date'),
            'entry_price': s.get('entry_price'),
            **s.get('extra', {}),
        }
    return result


# ============================================================
# 报告生成（Jinja2 模板）
# ============================================================
def generate_reports(results, previous_state):
    """使用 Jinja2 模板生成 MD 和 Telegram 报告"""
    current_state, changes = _detect_changes(results, previous_state)

    stage2_stocks = sorted(
        [r for r in results if r and r['is_stage2']],
        key=lambda x: x.get('trend_power', 0), reverse=True
    )
    near_stocks = sorted(
        [r for r in results if r and not r['is_stage2'] and r['passed'] >= 5],
        key=lambda x: x['passed'], reverse=True
    )
    total_analyzed = len([r for r in results if r])

    spy_r = None
    for r in results:
        if r and r.get('spy_return_6m') is not None:
            spy_r = r['spy_return_6m']
            break

    # 为 Stage 2 股票添加持仓天数
    for s in stage2_stocks:
        entry_info = current_state.get(s['ticker'], {})
        days_in = 0
        if isinstance(entry_info, dict) and entry_info.get('entry_date'):
            try:
                days_in = (datetime.now() - datetime.strptime(entry_info['entry_date'], '%Y-%m-%d')).days
            except Exception:
                pass
        s['days_in_stage2'] = days_in

    ctx = dict(
        timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        total_analyzed=total_analyzed,
        spy_return_6m=spy_r,
        stage2_stocks=stage2_stocks,
        near_stocks=near_stocks,
        changes=changes,
    )

    md_report = render_template('stage2_md.j2', **ctx)
    # Telegram 用短时间格式
    ctx['timestamp'] = datetime.now().strftime('%m/%d %H:%M')
    tg_report = render_template('stage2_tg.j2', **ctx)

    return md_report, tg_report, current_state, changes


# ============================================================
# 主流程
# ============================================================
def parse_args():
    parser = argparse.ArgumentParser(description="Stage 2 Monitor v4.0")
    parser.add_argument("--cron", action="store_true", help="Cron 模式")
    return parser.parse_args()


def main():
    args = parse_args()
    log("开始执行 Stage 2 分析...")

    # 初始化
    init_db()

    # 加载配置
    tickers = get_monitored_tickers()
    log(f"监控股票数: {len(tickers)}")

    # 加载历史状态（从 DB）
    previous_state = _load_previous_state_from_db()

    # 分析所有股票
    results = []
    for ticker_info in tickers:
        result = check_stage2_conditions(ticker_info)
        if result:
            results.append(result)

    # 日期
    date_str = datetime.now().strftime('%Y-%m-%d')

    # 写入 DB：策略结果
    save_results_to_db(results, date_str)

    # 生成报告 & 检测变化
    md_report, tg_report, current_state, changes = generate_reports(results, previous_state)

    # 写入 DB：策略状态
    save_states_to_db(current_state)

    # 写入 DB：信号变化
    save_signal_changes_to_db(changes, date_str)

    # 保存报告文件（使用 lib.report 共享函数）
    save_reports(md_report, tg_report, strategy_prefix="", log_func=log)

    # 输出 Telegram 报告到 stdout（供 cron wrapper 捕获发送）
    if not args.cron:
        print("\n" + "=" * 50)
        print(tg_report)
        print("=" * 50)

    stage2_count = sum(1 for r in results if r['is_stage2'])
    log(f"分析完成，Stage 2: {stage2_count}/{len(results)}")

    return changes


if __name__ == "__main__":
    main()
