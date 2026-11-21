"""BUY v1: prior consolidation/quiet volume, volume expansion, upward close.

Closed daily bars only. No orders, intraday quotes, or future-bar inputs.
Exact parameters and evidence travel with every saved result.
"""
import hashlib
import json
import math
from pathlib import Path

import pandas as pd
from lib.volume_price import session_context

RULE_VERSION = 'buy-v1'
CONFIG = Path(__file__).resolve().parents[1] / 'config' / 'buy.json'
KEYS = {'version', 'sideways_sessions', 'max_range_pct', 'quiet_sessions',
        'quiet_reference_sessions', 'max_quiet_ratio', 'volume_sessions', 'min_volume_multiple'}


def load_parameters(path=CONFIG):
    p = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(p, dict) or set(p) != KEYS or type(p['version']) is not int or p['version'] != 1:
        raise ValueError('Invalid BUY configuration/version')
    for key in ('sideways_sessions', 'quiet_sessions', 'quiet_reference_sessions', 'volume_sessions'):
        if type(p[key]) is not int or not 2 <= p[key] <= 252:
            raise ValueError('Invalid BUY session count: ' + key)
    for key in ('max_range_pct', 'max_quiet_ratio', 'min_volume_multiple'):
        if type(p[key]) not in (int, float) or not math.isfinite(p[key]) or p[key] <= 0:
            raise ValueError('Invalid BUY threshold: ' + key)
    if not (p['max_range_pct'] < 100 and p['max_quiet_ratio'] < 1 and p['min_volume_multiple'] > 1):
        raise ValueError('Inconsistent BUY thresholds')
    return p


def analyze(frame, target, parameters=None):
    p = dict(parameters if parameters is not None else load_parameters())
    result = dict(rule_version=RULE_VERSION, parameters=p,
                  parameter_id=hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest()[:12],
                  status='insufficient_data', reason='history_or_gaps', date=target,
                  conditions={f'C{i}': None for i in range(1, 4)}, is_buy=False,
                  buy_score=None, in_buy_pool=None, reference_price=None)
    if frame is None or frame.empty or not {'Open', 'High', 'Low', 'Close', 'Volume'} <= set(frame.columns):
        return result
    need = max(p['sideways_sessions'], p['quiet_sessions'] + p['quiet_reference_sessions'],
               p['volume_sessions']) + 30
    dates, early = session_context(target, need)
    if not dates or dates[-1] != target:
        result['reason'] = 'not_a_session'
        return result
    data = frame.copy()
    data.index = pd.Index([str(pd.Timestamp(i).date()) for i in data.index])
    if data.index.has_duplicates:
        result['reason'] = 'duplicate_sessions'
        return result
    data = data.reindex(dates).apply(pd.to_numeric, errors='coerce')
    price = data[['Open', 'High', 'Low', 'Close']]
    valid_price = price.map(lambda v: pd.notna(v) and math.isfinite(v) and v > 0).all(axis=1)
    valid_price &= (data.Low <= data[['Open', 'Close']].min(axis=1)) & (data.High >= data[['Open', 'Close']].max(axis=1))
    volume = data.Volume.where(data.Volume.map(lambda v: pd.notna(v) and math.isfinite(v) and v > 0))
    prior_full = [day for day in dates[:-1] if day not in early]
    q, b = p['quiet_sessions'], p['quiet_reference_sessions']
    quiet_dates, reference_dates = prior_full[-q:], prior_full[-q-b:-q]
    baseline_dates = prior_full[-p['volume_sessions']:]
    sideways_dates = dates[-p['sideways_sessions']-1:-1]
    required_prices = set(sideways_dates) | {dates[-1], dates[-2]}
    if (len(sideways_dates) != p['sideways_sessions'] or len(reference_dates) != b
            or len(quiet_dates) != q or len(baseline_dates) != p['volume_sessions']
            or not valid_price.loc[list(required_prices)].all()
            or volume.loc[quiet_dates + reference_dates + baseline_dates + [target]].isna().any()):
        return result
    if target in early:
        result['reason'] = 'early_close'
        return result
    prior = data.loc[list(sideways_dates)]
    range_pct = float((prior.High.max() / prior.Low.min() - 1) * 100)
    quiet_mean, old_mean = float(volume.loc[quiet_dates].mean()), float(volume.loc[reference_dates].mean())
    base_mean = float(volume.loc[baseline_dates].mean())
    quiet_ratio = quiet_mean / old_mean
    multiple = float(volume.loc[target] / base_mean)
    today, previous = data.iloc[-1], data.iloc[-2]
    within_range = range_pct <= p['max_range_pct'] or math.isclose(range_pct, p['max_range_pct'], rel_tol=1e-12)
    conditions = dict(C1=bool(within_range and quiet_ratio <= p['max_quiet_ratio']),
                      C2=bool(multiple >= p['min_volume_multiple']),
                      C3=bool(today.Close > today.Open and today.Close > previous.Close))
    signal = all(conditions.values())
    result.update(status='ok', reason=None, conditions=conditions, is_buy=signal,
                  in_buy_pool=conditions['C1'], buy_score=round(sum(conditions.values()) / 3 * 100, 2),
                  range_pct=range_pct, quiet_volume_ratio=quiet_ratio, buy_volume_multiple=multiple,
                  quiet_mean_volume=quiet_mean, reference_mean_volume=old_mean, baseline_mean_volume=base_mean,
                  signal_volume=float(today.Volume), signal_open=float(today.Open), signal_close=float(today.Close),
                  previous_close=float(previous.Close), reference_price=float(today.Close) if signal else None)
    return result
