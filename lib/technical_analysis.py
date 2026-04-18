"""
Stock Tracker — 技术指标分析模块
================================
整合四大技术指标系统，为每只股票生成完整的技术分析报告：
  1. 均线系统 (Moving Average System)
  2. 动量指标 (Momentum Indicators: RSI, Stochastic, MACD, ADX)
  3. 支撑与阻力 (Support & Resistance)
  4. 斐波那契回调与延伸 (Fibonacci Retracement & Extension)

复用 lib/indicators.py 中已有的基础计算函数。
"""

import numpy as np
import pandas as pd
from typing import Optional, Dict, Any, Tuple
import warnings
warnings.filterwarnings("ignore")

from lib.indicators import sma, ema, rsi, macd, atr, bollinger_bandwidth


# ═══════════════════════════════════════════════════════════════
# 指标一：均线系统 (Moving Average System)
# ═══════════════════════════════════════════════════════════════
def compute_moving_averages(data: pd.DataFrame) -> Dict[str, Any]:
    """
    计算均线系统指标，返回最新信号。
    复用 lib/indicators.py 的 sma() / ema()。

    返回 dict:
      ma_values: {SMA5: float, SMA20: float, ...}
      position: {SMA5: 'above'|'below', ...}
      arrangement: str  (多头排列/空头排列/混合排列)
      golden_cross: bool  (SMA5 上穿 SMA20)
      death_cross: bool  (SMA5 下穿 SMA20)
      ema12, ema26: float
    """
    close = data['Close']
    if len(close) < 50:
        return {}

    periods = [5, 20, 50, 100, 200]
    current_close = float(close.iloc[-1])

    signals = {
        'current_close': current_close,
        'ma_values': {},
        'position': {},
        'arrangement': None,
        'golden_cross': False,
        'death_cross': False,
    }

    for p in periods:
        if len(close) < p:
            continue
        val = float(sma(close, p).iloc[-1])
        if np.isnan(val):
            continue
        key = f'SMA{p}'
        signals['ma_values'][key] = round(val, 2)
        signals['position'][key] = 'above' if current_close > val else 'below'

    # EMA
    if len(close) >= 26:
        signals['ema12'] = round(float(ema(close, 12).iloc[-1]), 2)
        signals['ema26'] = round(float(ema(close, 26).iloc[-1]), 2)

    # 均线排列 (5/20/50)
    ma5_val = signals['ma_values'].get('SMA5')
    ma20_val = signals['ma_values'].get('SMA20')
    ma50_val = signals['ma_values'].get('SMA50')

    if ma5_val and ma20_val and ma50_val:
        if ma5_val > ma20_val > ma50_val:
            signals['arrangement'] = '多头排列 (Bullish)'
            signals['arrangement_type'] = 'bullish'
        elif ma5_val < ma20_val < ma50_val:
            signals['arrangement'] = '空头排列 (Bearish)'
            signals['arrangement_type'] = 'bearish'
        else:
            signals['arrangement'] = '混合排列 (Neutral)'
            signals['arrangement_type'] = 'neutral'

    # 金叉 / 死叉
    if len(close) >= 22:
        sma5_series = sma(close, 5)
        sma20_series = sma(close, 20)
        if len(sma5_series) >= 2 and len(sma20_series) >= 2:
            prev_5 = float(sma5_series.iloc[-2])
            prev_20 = float(sma20_series.iloc[-2])
            curr_5 = float(sma5_series.iloc[-1])
            curr_20 = float(sma20_series.iloc[-1])
            if not any(np.isnan(x) for x in [prev_5, prev_20, curr_5, curr_20]):
                if prev_5 < prev_20 and curr_5 > curr_20:
                    signals['golden_cross'] = True
                if prev_5 > prev_20 and curr_5 < curr_20:
                    signals['death_cross'] = True

    return signals


# ═══════════════════════════════════════════════════════════════
# 指标二：动量指标 (Momentum Indicators)
# ═══════════════════════════════════════════════════════════════
def _compute_stochastic(data: pd.DataFrame, k_period=9, d_period=3, smooth_k=3) -> Tuple:
    """计算随机指标 %K, %D"""
    low_k = data['Low'].rolling(k_period).min()
    high_k = data['High'].rolling(k_period).max()
    fast_k = 100 * (data['Close'] - low_k) / (high_k - low_k).replace(0, np.nan)
    stoch_k = fast_k.rolling(smooth_k).mean()
    stoch_d = stoch_k.rolling(d_period).mean()
    return stoch_k, stoch_d


def _compute_adx(data: pd.DataFrame, period=14) -> Tuple:
    """计算 ADX 及 DI+/DI-"""
    high, low, close = data['High'], data['Low'], data['Close']
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = close.shift(1)

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)

    dm_plus = np.where((high - prev_high) > (prev_low - low),
                       np.maximum(high - prev_high, 0), 0)
    dm_minus = np.where((prev_low - low) > (high - prev_high),
                        np.maximum(prev_low - low, 0), 0)

    tr_s = pd.Series(tr.values, index=data.index).ewm(com=period - 1, adjust=False).mean()
    dmp_s = pd.Series(dm_plus, index=data.index, dtype=float).ewm(com=period - 1, adjust=False).mean()
    dmm_s = pd.Series(dm_minus, index=data.index, dtype=float).ewm(com=period - 1, adjust=False).mean()

    di_plus = 100 * dmp_s / tr_s.replace(0, np.nan)
    di_minus = 100 * dmm_s / tr_s.replace(0, np.nan)
    dx = 100 * (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, np.nan)
    adx = dx.ewm(com=period - 1, adjust=False).mean()

    return adx, di_plus, di_minus


def compute_momentum(data: pd.DataFrame) -> Dict[str, Any]:
    """
    计算动量指标：RSI, Stochastic, MACD, ADX, HV30。

    返回 dict:
      rsi6, rsi14: {value, label}
      stoch: {K, D, label}
      macd: {line, signal, histogram, direction, expanding, cross}
      adx: {ADX, DI_Plus, DI_Minus, strength, direction}
      hv30: float
    """
    close = data['Close']
    if len(close) < 50:
        return {}

    def rsi_label(val):
        if val >= 80: return '极度超买'
        if val >= 70: return '超买'
        if val <= 20: return '极度超卖'
        if val <= 30: return '超卖'
        return '中性'

    def adx_label(val):
        if val >= 50: return '极强趋势'
        if val >= 25: return '有明确趋势'
        if val >= 15: return '趋势形成中'
        return '无明确趋势'

    # RSI (复用 lib/indicators.py)
    rsi6 = rsi(close, 6)
    rsi14 = rsi(close, 14)
    rsi6_val = round(float(rsi6.iloc[-1]), 1) if not np.isnan(rsi6.iloc[-1]) else None
    rsi14_val = round(float(rsi14.iloc[-1]), 1) if not np.isnan(rsi14.iloc[-1]) else None

    # Stochastic
    stoch_k, stoch_d = _compute_stochastic(data)
    stoch_k_val = round(float(stoch_k.iloc[-1]), 1) if not np.isnan(stoch_k.iloc[-1]) else None
    stoch_d_val = round(float(stoch_d.iloc[-1]), 1) if not np.isnan(stoch_d.iloc[-1]) else None

    # MACD (复用 lib/indicators.py)
    macd_line, macd_signal, macd_hist = macd(close)
    macd_val = round(float(macd_line.iloc[-1]), 4) if not np.isnan(macd_line.iloc[-1]) else None
    signal_val = round(float(macd_signal.iloc[-1]), 4) if not np.isnan(macd_signal.iloc[-1]) else None
    hist_val = round(float(macd_hist.iloc[-1]), 4) if not np.isnan(macd_hist.iloc[-1]) else None

    # MACD 柱状图扩大/收缩
    hist_prev = float(macd_hist.iloc[-2]) if len(macd_hist) >= 2 else 0
    macd_expanding = abs(hist_val or 0) > abs(hist_prev) if hist_val is not None else False

    # ADX
    adx_series, di_plus, di_minus = _compute_adx(data)
    adx_val = round(float(adx_series.iloc[-1]), 1) if not np.isnan(adx_series.iloc[-1]) else None
    dip_val = round(float(di_plus.iloc[-1]), 1) if not np.isnan(di_plus.iloc[-1]) else None
    dim_val = round(float(di_minus.iloc[-1]), 1) if not np.isnan(di_minus.iloc[-1]) else None

    # HV30 (30日年化波动率)
    log_ret = np.log(close / close.shift(1))
    hv30 = round(float(log_ret.rolling(30).std().iloc[-1] * np.sqrt(252) * 100), 1) if len(close) >= 32 else None

    signals = {
        'rsi6': {'value': rsi6_val, 'label': rsi_label(rsi6_val) if rsi6_val else '—'},
        'rsi14': {'value': rsi14_val, 'label': rsi_label(rsi14_val) if rsi14_val else '—'},
        'stoch': {
            'K': stoch_k_val, 'D': stoch_d_val,
            'label': '超买' if (stoch_k_val or 0) >= 80 else ('超卖' if (stoch_k_val or 0) <= 20 else '中性'),
        },
        'macd': {
            'line': macd_val,
            'signal': signal_val,
            'histogram': hist_val,
            'direction': '多头' if (hist_val or 0) > 0 else '空头',
            'expanding': macd_expanding,
            'cross': '金叉' if (macd_val or 0) > (signal_val or 0) else '死叉',
        },
        'adx': {
            'ADX': adx_val,
            'DI_Plus': dip_val,
            'DI_Minus': dim_val,
            'strength': adx_label(adx_val) if adx_val else '—',
            'direction': '多头主导' if (dip_val or 0) > (dim_val or 0) else '空头主导',
        },
        'hv30': hv30,
    }
    return signals


# ═══════════════════════════════════════════════════════════════
# 指标三：支撑与阻力 (Support & Resistance)
# ═══════════════════════════════════════════════════════════════
def compute_support_resistance(data: pd.DataFrame) -> Dict[str, Any]:
    """
    计算支撑与阻力：布林带、VWAP、Swing Points、统计区间、52周高低。

    返回 dict:
      bollinger: {upper, mid, lower, width_pct, position}
      vwap20: float
      vwap_signal: str
      stat_levels: {'+1σ': float, '-1σ': float, '+2σ': float, '-2σ': float}
      52week: {high, low, pct_from_high, pct_from_low}
      key_supports: [float]
      key_resistances: [float]
    """
    close = data['Close']
    if len(close) < 30:
        return {}

    current = float(close.iloc[-1])

    # 布林带
    period = 20
    mid = sma(close, period)
    std = close.rolling(period).std()
    bb_upper = float((mid + 2 * std).iloc[-1])
    bb_mid = float(mid.iloc[-1])
    bb_lower = float((mid - 2 * std).iloc[-1])
    bb_width = round((bb_upper - bb_lower) / bb_mid * 100, 1) if bb_mid else 0

    bb_position = '中轨以上' if current > bb_mid else '中轨以下'
    if current >= bb_upper:
        bb_position = '触碰上轨（超买阻力）'
    elif current <= bb_lower:
        bb_position = '触碰下轨（超卖支撑）'

    # VWAP (20日)
    typical = (data['High'] + data['Low'] + data['Close']) / 3
    vol = data['Volume']
    cum_tpv = (typical * vol).rolling(period).sum()
    cum_vol = vol.rolling(period).sum()
    vwap20 = round(float((cum_tpv / cum_vol).iloc[-1]), 2)
    vwap_signal = '高于VWAP（多头）' if current > vwap20 else '低于VWAP（空头）'

    # 统计区间 (30日)
    mean30 = sma(close, 30)
    std30 = close.rolling(30).std()
    stat_upper1 = round(float((mean30 + std30).iloc[-1]), 2)
    stat_lower1 = round(float((mean30 - std30).iloc[-1]), 2)
    stat_upper2 = round(float((mean30 + 2 * std30).iloc[-1]), 2)
    stat_lower2 = round(float((mean30 - 2 * std30).iloc[-1]), 2)

    # 52周高低
    w52_high = round(float(data['High'].max()), 2)
    w52_low = round(float(data['Low'].min()), 2)
    pct_from_high = round((current / w52_high - 1) * 100, 1)
    pct_from_low = round((current / w52_low - 1) * 100, 1)

    # 关键支撑阻力归纳
    all_supports = [bb_lower, stat_lower1, w52_low]
    if current > vwap20:
        all_supports.append(vwap20)
    all_resistances = [bb_upper, stat_upper1, w52_high]
    if current < vwap20:
        all_resistances.append(vwap20)

    key_supports = sorted(set(round(x, 2) for x in all_supports if x < current), reverse=True)[:3]
    key_resistances = sorted(set(round(x, 2) for x in all_resistances if x > current))[:3]

    return {
        'current_close': round(current, 2),
        'bollinger': {
            'upper': round(bb_upper, 2),
            'mid': round(bb_mid, 2),
            'lower': round(bb_lower, 2),
            'width_pct': bb_width,
            'position': bb_position,
        },
        'vwap20': vwap20,
        'vwap_signal': vwap_signal,
        'stat_levels': {
            '+1σ': stat_upper1, '-1σ': stat_lower1,
            '+2σ': stat_upper2, '-2σ': stat_lower2,
        },
        '52week': {
            'high': w52_high, 'low': w52_low,
            'pct_from_high': pct_from_high, 'pct_from_low': pct_from_low,
        },
        'key_supports': key_supports,
        'key_resistances': key_resistances,
    }


# ═══════════════════════════════════════════════════════════════
# 指标四：斐波那契回调与延伸 (Fibonacci Retracement & Extension)
# ═══════════════════════════════════════════════════════════════
def compute_fibonacci(data: pd.DataFrame, lookback: int = 60) -> Dict[str, Any]:
    """
    计算斐波那契回调与延伸目标位。

    返回 dict:
      swing_low: {date, price}
      swing_high: {date, price}
      trend_direction: str
      retracement_levels: {ratio_label: {price, distance_pct, role}}
      extension_targets: {ratio_label: {price, upside_pct}}
      current_zone: {support, resistance}
    """
    if len(data) < lookback:
        lookback = len(data)
    if lookback < 10:
        return {}

    recent = data.tail(lookback)
    current = float(data['Close'].iloc[-1])

    swing_low_price = float(recent['Low'].min())
    swing_low_date = str(recent['Low'].idxmin().date()) if hasattr(recent['Low'].idxmin(), 'date') else str(recent['Low'].idxmin())
    swing_high_price = float(recent['High'].max())
    swing_high_date = str(recent['High'].idxmax().date()) if hasattr(recent['High'].idxmax(), 'date') else str(recent['High'].idxmax())
    range_size = swing_high_price - swing_low_price

    if range_size <= 0:
        return {}

    is_uptrend = recent['Low'].idxmin() < recent['High'].idxmax()

    retrace_ratios = [0.0, 0.236, 0.382, 0.500, 0.618, 0.786, 1.0]
    extension_ratios = [1.0, 1.272, 1.618, 2.0, 2.618]

    retracement_levels = {}
    for r in retrace_ratios:
        if is_uptrend:
            price = swing_high_price - r * range_size
        else:
            price = swing_low_price + r * range_size
        price = round(price, 2)
        distance_pct = round((price / current - 1) * 100, 1) if current else 0
        if abs(distance_pct) < 1:
            role = '当前附近'
        elif price > current:
            role = '阻力'
        else:
            role = '支撑'
        label = f'{r:.1%}'
        retracement_levels[label] = {
            'price': price,
            'distance_pct': distance_pct,
            'role': role,
        }

    extension_targets = {}
    for e in extension_ratios:
        if is_uptrend:
            price = swing_low_price + e * range_size
        else:
            price = swing_high_price - (e - 1) * range_size
        price = round(price, 2)
        if price > current:
            upside_pct = round((price / current - 1) * 100, 1) if current else 0
            extension_targets[f'{e:.3%}'] = {
                'price': price,
                'upside_pct': upside_pct,
            }

    # 当前区间
    sorted_levels = sorted(retracement_levels.items(), key=lambda x: x[1]['price'])
    zone_below = None
    zone_above = None
    for label, info in sorted_levels:
        if info['price'] <= current:
            zone_below = f"Fib {label} = ${info['price']:.2f}"
        else:
            zone_above = f"Fib {label} = ${info['price']:.2f}"
            break

    return {
        'swing_low': {'date': swing_low_date, 'price': swing_low_price},
        'swing_high': {'date': swing_high_date, 'price': swing_high_price},
        'trend_direction': '上升趋势' if is_uptrend else '下降趋势',
        'is_uptrend': is_uptrend,
        'current_price': current,
        'retracement_levels': retracement_levels,
        'extension_targets': extension_targets,
        'current_zone': {
            'support': zone_below or '无',
            'resistance': zone_above or '无',
        },
    }


# ═══════════════════════════════════════════════════════════════
# 综合分析入口
# ═══════════════════════════════════════════════════════════════
def compute_technical_indicators(data: pd.DataFrame) -> Dict[str, Any]:
    """
    一键计算全部四大技术指标系统。

    参数:
      data: OHLCV DataFrame

    返回 dict:
      moving_averages: 均线系统
      momentum: 动量指标
      support_resistance: 支撑阻力
      fibonacci: 斐波那契
    """
    result = {}

    try:
        result['moving_averages'] = compute_moving_averages(data)
    except Exception:
        result['moving_averages'] = {}

    try:
        result['momentum'] = compute_momentum(data)
    except Exception:
        result['momentum'] = {}

    try:
        result['support_resistance'] = compute_support_resistance(data)
    except Exception:
        result['support_resistance'] = {}

    try:
        result['fibonacci'] = compute_fibonacci(data)
    except Exception:
        result['fibonacci'] = {}

    return result
