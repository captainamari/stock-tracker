"""Bilingual display of frozen price/volume evidence. Never calculates signals."""
STATES = {
    'up_high': ('High-volume rise', '放量上涨'), 'up_low': ('Low-volume rise', '缩量上涨'),
    'up_normal': ('Normal-volume rise', '正常量上涨'), 'down_high': ('High-volume decline', '放量下跌'),
    'down_low': ('Low-volume decline', '缩量下跌'), 'down_normal': ('Normal-volume decline', '正常量下跌'),
    'flat': ('Flat', '平盘'), 'unknown': ('Unknown', '未知')}
CONFIRM = {'bullish': ('bullish', '偏多'), 'bearish': ('bearish', '偏空'),
           'mixed': ('mixed', '混合'), 'unknown': ('insufficient sample', '样本不足')}
TREND = {'up': ('up', '上升'), 'down': ('down', '下降'),
         'mixed': ('mixed', '震荡'), 'unknown': ('unknown', '未知')}


def describe(value):
    if not value:
        return dict(summary=[('Not calculated in this batch', '该批次未计算量价')], details=[])
    if value.get('status') in ('insufficient_data', 'unavailable'):
        return dict(summary=[('Price/volume data unavailable', '量价数据不足')], details=[])
    today, p = value.get('today') or {}, value.get('parameters', {})
    state = STATES.get(today.get('state'), STATES['unknown'])
    confirm = CONFIRM.get(value.get('confirmation'), CONFIRM['unknown'])
    trend = TREND.get(value.get('price_trend'), TREND['unknown'])
    rvol = '—' if today.get('rvol') is None else f'{today["rvol"]:.2f}×'
    ratio = '—' if value.get('up_down_volume_ratio') is None else f'{value["up_down_volume_ratio"]:.2f}×'
    window = p.get('window_sessions', '—')
    result = dict(summary=[(f'{state[0]} · RVOL {rvol}', f'{state[1]} · 量比 {rvol}'),
                           (f'{window} sessions: {confirm[0]} · Up/down volume {ratio}',
                            f'近{window}日{confirm[1]} · 涨跌日均量比 {ratio}')], details=[])
    details = result['details']
    details.append((f'Price trend: {trend[0]}', f'价格趋势：{trend[1]}'))
    counts = value.get('counts', {})
    for key, label in STATES.items():
        details.append((f'{label[0]}: {counts.get(key, 0)} sessions', f'{label[1]}：{counts.get(key, 0)}天'))
    details.append((f'Up/down sessions: {value.get("up_days", 0)}/{value.get("down_days", 0)}',
                    f'上涨／下跌样本：{value.get("up_days", 0)}/{value.get("down_days", 0)}天'))
    details.append((f'RVOL: today / preceding {p.get("baseline_sessions", "—")} full-session mean; early closes excluded.',
                    f'量比：当日量／此前{p.get("baseline_sessions", "—")}个完整交易日均量；排除半日。'))
    if value.get('status') == 'partial':
        details.append(('Partial window: early close or missing inputs; no directional confirmation.',
                        '窗口含半日或缺失数据，不确认偏多／偏空。'))
    details.append((f'Rule {value.get("rule_version", "—")} · parameters {value.get("parameter_id", "—")}',
                    f'规则 {value.get("rule_version", "—")} · 参数 {value.get("parameter_id", "—")}'))
    return result
