"""Versioned daily price/volume evidence; independent of strategy eligibility.

No network or writes. Parameters and chronological observations travel with each
saved result. Full-session volume only; no inferred institutional money flows.
"""
import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path

import pandas as pd

from lib.market_calendar import calendar

RULE_VERSION = 'volume-price-v1'
CONFIG = Path(__file__).resolve().parents[1] / 'config' / 'volume-price.json'
KEYS = {'version', 'baseline_sessions', 'window_sessions', 'high_volume', 'low_volume',
        'flat_pct', 'min_side_days', 'min_pattern_days', 'bull_ratio', 'bear_ratio',
        'trend_fast', 'trend_slow', 'slope_sessions'}
LABELS = {'up_high': '放量上涨', 'up_low': '缩量上涨', 'up_normal': '正常量上涨',
          'down_high': '放量下跌', 'down_low': '缩量下跌', 'down_normal': '正常量下跌',
          'flat': '平盘', 'unknown': '量价未知'}


def load_parameters(path=CONFIG):
    p = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(p, dict) or set(p) != KEYS or type(p['version']) is not int or p['version'] != 1:
        raise ValueError('Invalid volume-price configuration/version')
    for key in ('baseline_sessions', 'window_sessions', 'min_side_days', 'min_pattern_days',
                'trend_fast', 'trend_slow', 'slope_sessions'):
        if type(p[key]) is not int or not 1 <= p[key] <= 252:
            raise ValueError('Invalid volume-price integer: '+key)
    for key in ('high_volume', 'low_volume', 'flat_pct', 'bull_ratio', 'bear_ratio'):
        if type(p[key]) not in (float, int) or not math.isfinite(p[key]) or p[key] <= 0:
            raise ValueError('Invalid volume-price threshold: '+key)
    if not (p['low_volume'] < 1 < p['high_volume'] and p['bear_ratio'] < 1 < p['bull_ratio']
            and p['trend_fast'] < p['trend_slow'] and p['flat_pct'] < 100
            and 2*p['min_side_days'] <= p['window_sessions']
            and 2*p['min_pattern_days'] <= p['window_sessions']):
        raise ValueError('Inconsistent volume-price thresholds')
    return p


@lru_cache(maxsize=32)
def session_context(target, count):
    cal = calendar(int(target[:4]))
    end = pd.Timestamp(target)
    days = cal.sessions[cal.sessions <= end][-count:]
    early = set(cal.early_closes.strftime('%Y-%m-%d'))
    return tuple(days.strftime('%Y-%m-%d')), frozenset(early)


def analyze(frame, target, parameters=None):
    p = dict(parameters if parameters is not None else load_parameters())
    fingerprint = hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest()[:12]
    result = dict(rule_version=RULE_VERSION, parameter_id=fingerprint, parameters=p,
                  status='insufficient_data', reason='history_or_gaps', date=target,
                  today=None, observations=[], counts={}, confirmation='unknown',
                  price_trend='unknown', sequence='none', up_days=0, down_days=0,
                  up_mean_rvol=None, down_mean_rvol=None, up_down_volume_ratio=None)
    if frame is None or frame.empty:
        return result
    # Calendar alignment prevents a missing bar from becoming a multi-day "daily" move.
    need = max(p['trend_slow']+p['slope_sessions'], p['baseline_sessions']+p['window_sessions']+10)
    dates, early = session_context(target, need)
    data = frame.copy()
    data.index = pd.Index([str(pd.Timestamp(i).date()) for i in data.index])
    if data.index.has_duplicates:
        result['reason'] = 'duplicate_sessions'
        return result
    data = data.reindex(dates)
    close = pd.to_numeric(data['Close'], errors='coerce')
    volume = pd.to_numeric(data['Volume'], errors='coerce')
    close = close.where(close.map(lambda v: pd.notna(v) and math.isfinite(v) and v > 0))
    volume = volume.where(volume.map(lambda v: pd.notna(v) and math.isfinite(v) and v > 0))
    fast = close.rolling(p['trend_fast']).mean()
    slow = close.rolling(p['trend_slow']).mean()
    if close.tail(p['trend_slow']+p['slope_sessions']).notna().all():
        if close.iloc[-1] > fast.iloc[-1] > slow.iloc[-1] and fast.iloc[-1] > fast.iloc[-1-p['slope_sessions']]:
            result['price_trend'] = 'up'
        elif close.iloc[-1] < fast.iloc[-1] < slow.iloc[-1] and fast.iloc[-1] < fast.iloc[-1-p['slope_sessions']]:
            result['price_trend'] = 'down'
        else:
            result['price_trend'] = 'mixed'
    observations = []
    for i in range(len(data)-p['window_sessions'], len(data)):
        day = dates[i]
        item = dict(date=day, state='unknown', change_pct=None, rvol=None, volume=None, reason=None)
        if i < 1 or pd.isna(close.iloc[i]) or pd.isna(close.iloc[i-1]):
            item['reason'] = 'missing_price'
        else:
            change = (close.iloc[i]/close.iloc[i-1]-1)*100
            item['change_pct'] = round(float(change), 4)
            # Exclude early closes rather than multiplying incomplete sessions by time.
            prior = [j for j in range(i) if dates[j] not in early][-p['baseline_sessions']:]
            base = volume.iloc[prior]
            if day in early:
                item['reason'] = 'early_close'
            elif pd.isna(volume.iloc[i]) or len(base) < p['baseline_sessions'] or base.isna().any():
                item['reason'] = 'missing_volume_or_baseline'
            else:
                rvol = float(volume.iloc[i]/base.mean())
                direction = 'up' if change > p['flat_pct'] else 'down' if change < -p['flat_pct'] else 'flat'
                level = 'high' if rvol >= p['high_volume'] else 'low' if rvol <= p['low_volume'] else 'normal'
                item.update(state='flat' if direction == 'flat' else direction+'_'+level,
                            rvol=round(rvol, 4), volume=float(volume.iloc[i]))
        observations.append(item)
    counts = {key: sum(o['state'] == key for o in observations) for key in LABELS}
    ups = [o for o in observations if o['state'].startswith('up_')]
    downs = [o for o in observations if o['state'].startswith('down_')]
    result.update(today=observations[-1], observations=observations, counts=counts,
                  up_days=len(ups), down_days=len(downs),
                  status='ok' if counts['unknown'] == 0 else 'partial',
                  reason=None if counts['unknown'] == 0 else 'excluded_or_missing_sessions')
    if ups:
        result['up_mean_rvol'] = round(sum(o['rvol'] for o in ups)/len(ups), 4)
    if downs:
        result['down_mean_rvol'] = round(sum(o['rvol'] for o in downs)/len(downs), 4)
    enough = len(ups) >= p['min_side_days'] and len(downs) >= p['min_side_days']
    if enough:
        ratio = (sum(o['volume'] for o in ups)/len(ups))/(sum(o['volume'] for o in downs)/len(downs))
        result['up_down_volume_ratio'] = round(ratio, 4)
    else:
        ratio = None
    if result['status'] == 'ok' and enough:
        bull = counts['up_high'] >= p['min_pattern_days'] and counts['down_low'] >= p['min_pattern_days'] and counts['up_high'] > counts['down_high'] and ratio >= p['bull_ratio']
        bear = counts['down_high'] >= p['min_pattern_days'] and counts['up_low'] >= p['min_pattern_days'] and counts['down_high'] > counts['up_high'] and ratio <= p['bear_ratio']
        result['confirmation'] = 'bullish' if bull else 'bearish' if bear else 'mixed'
    # Describe the latest contiguous pullback/rebound only if preceded by the
    # corresponding high-volume move within the same window. No causal claims.
    states = [o['state'] for o in observations]
    for ending, preceding, name in (('down_low', 'up_high', 'pullback'), ('up_low', 'down_high', 'rebound')):
        n = 0
        for state in reversed(states):
            if state != ending:
                break
            n += 1
        if n and preceding in states[:-n] and 'unknown' not in states:
            result.update(sequence=name, sequence_days=n)
    return result


def summary(value):
    """Compact reader-facing evidence, also handles immutable pre-v1 reports."""
    if not value:
        return '量价：旧批次未计算，等待新批次'
    if value.get('status') in ('insufficient_data', 'unavailable'):
        return '量价：数据不足'
    today = value.get('today') or {}
    state = LABELS.get(today.get('state'), '量价未知')
    rvol = today.get('rvol')
    line = f'{state}'+(f' {rvol:.2f}x/{value["parameters"]["baseline_sessions"]}日均量' if rvol is not None else '（半日/数据不足）')
    trend = {'up':'上升', 'down':'下降', 'mixed':'震荡', 'unknown':'未知'}[value['price_trend']]
    confirm = {'bullish':'偏多', 'bearish':'偏空', 'mixed':'混合', 'unknown':'样本不足'}[value['confirmation']]
    return f'{line}｜趋势{trend}·量价{confirm}'
