"""Database-only computation, one context per run and one evaluation per strategy.

Existing business thresholds are retained. Weekly Checklist uses the current
provisional week (the old rule), explicitly disclosed rather than called confirmed.
"""
import json
import math
from types import SimpleNamespace
import numpy as np
from lib import db, jobs
from lib.prices import read_prices, dataframe
from lib.settings import stamp
from scripts.stage2_monitor import check_stage2_conditions
from scripts.vcp_scanner import analyze_vcp
from scripts.bottom_fisher import analyze_bottom
from scripts.buying_checklist import analyze_buying_checklist
from scripts import market_pulse
from lib.technical_analysis import compute_technical_indicators

STRATEGIES = ('stage2_us','contraction_us','bottom_fisher_us','checklist_us')
RULE_VERSION = 'v1'
TOTALS = dict(zip(STRATEGIES, (8,6,8,11)))


def clean(value):
    if isinstance(value, dict):
        return {k:clean(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)):
        return [clean(v) for v in value]
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def dumps(value):
    return json.dumps(clean(value), ensure_ascii=False, allow_nan=False)


def outcome(strategy, status, reason=None, raw=None, signal=False):
    value = clean(raw or {})
    conditions = value.get('conditions', {f'C{i}':None for i in range(1,TOTALS.get(strategy,0)+1)})
    if status == 'ok' and any(v is None for v in conditions.values()):
        status, reason = 'insufficient_data', 'missing_condition'
    return dict(status=status, is_signal=bool(signal) if status=='ok' else None,
                reason=reason, conditions=conditions, total=TOTALS.get(strategy,0),
                passed=sum(v is True for v in conditions.values()),
                metrics=value, weekly_mode='provisional' if strategy=='checklist_us' else None)


def evaluate_asset(asset, frame, spy, prior, target):
    values = {}
    source_status = asset['status']
    if source_status != 'ok':
        return {s: outcome(s, source_status if source_status in ('failed','stale') else 'insufficient_data', asset['reason']) for s in (*STRATEGIES,'technical')}
    if frame is None or len(frame) < 252:
        values = {s:outcome(s,'insufficient_data','history_below_252_sessions') for s in STRATEGIES}
    else:
        symbol = asset['symbol']
        def loader(ticker, min_rows=0):
            data = frame if ticker == symbol else spy if ticker=='SPY' else None
            return data if data is not None and len(data)>=min_rows else None
        try:
            raw = check_stage2_conditions(SimpleNamespace(**asset), loader=loader)
            values['stage2_us'] = outcome('stage2_us', raw.get('status','ok'), raw=raw, signal=raw['is_stage2'])
        except Exception as exc:
            values['stage2_us'] = outcome('stage2_us','failed',f'calculation:{type(exc).__name__}')
        s2 = values['stage2_us']
        old = prior.get((symbol,'stage2_us'), {})
        stage_state = {symbol: {'is_active': s2['is_signal'] is True, 'entry_date':old.get('entry_date'), 'entry_price':old.get('entry_price')}}
        if s2['status'] != 'ok':
            values['contraction_us'] = outcome('contraction_us', s2['status'], 'stage2_unavailable')
        elif not s2['is_signal']:
            values['contraction_us'] = outcome('contraction_us','ok','outside_stage2_pool',raw={'conditions':{}},signal=False)
        else:
            try:
                raw = analyze_vcp(symbol, asset, frame, stage_state[symbol])
                values['contraction_us'] = outcome('contraction_us','ok',raw=raw,signal=raw['is_vcp'])
            except Exception as exc:
                values['contraction_us'] = outcome('contraction_us','failed',f'calculation:{type(exc).__name__}')
        # Bottom quality may use a historically verified entry, but cannot treat
        # today's failed Stage2 evaluation as a current confirmed match.
        try:
            raw = analyze_bottom(symbol, asset, frame, stage_state)
            if s2['status'] != 'ok' and not old.get('entry_date'):
                raw['conditions']['C2'] = None
            values['bottom_fisher_us'] = outcome('bottom_fisher_us','ok',raw=raw,signal=raw['is_bottom_signal'])
        except Exception as exc:
            values['bottom_fisher_us'] = outcome('bottom_fisher_us','failed',f'calculation:{type(exc).__name__}')
        try:
            raw = analyze_buying_checklist(symbol, asset, frame, stage_state, {})
            if s2['status'] != 'ok':
                raw['conditions']['C11'] = None
            values['checklist_us'] = outcome('checklist_us','ok',raw=raw,signal=raw['is_bc_signal'])
        except Exception as exc:
            values['checklist_us'] = outcome('checklist_us','failed',f'calculation:{type(exc).__name__}')
    try:
        values['technical'] = outcome('technical','ok',raw=compute_technical_indicators(frame)) if frame is not None and len(frame)>=50 else outcome('technical','insufficient_data','history_below_50_sessions')
    except Exception as exc:
        values['technical'] = outcome('technical','failed',f'calculation:{type(exc).__name__}')
    return values


def calculate_run(job):
    with db.get_db() as conn:
        assets = [dict(r) for r in conn.execute('SELECT * FROM run_assets WHERE run_id=? ORDER BY symbol',(job['run_id'],))]
        prior = {(r['symbol'],r['strategy_id']):dict(r) for r in conn.execute('SELECT * FROM candidate_states')}
        spy_asset = next((a for a in assets if a['symbol']=='SPY'), None)
        spy = dataframe(read_prices(conn,'SPY',job['target_date'],spy_asset['input_revision'])) if spy_asset and spy_asset['status']=='ok' else None
    for i, asset in enumerate(assets):
        with db.get_db() as conn:
            rows = read_prices(conn, asset['symbol'], job['target_date'], asset['input_revision'] or 0)
        frame = dataframe(rows)
        results = evaluate_asset(asset, frame, spy, prior, job['target_date'])
        with db.get_db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            jobs.fence(conn,job)
            valid = [r for r in rows if r['quality']=='valid']
            price = valid[-1]['close'] if valid else None
            change = (valid[-1]['close']/valid[-2]['close']-1)*100 if len(valid)>1 and valid[-1]['date']==asset['actual_date'] else None
            conn.execute('UPDATE run_assets SET price=?,change_1d=? WHERE run_id=? AND symbol=?',(price,change,job['run_id'],asset['symbol']))
            for strategy, result in results.items():
                conn.execute('''INSERT OR REPLACE INTO daily_results VALUES (?,?,?,?,?,?,?,?,?,?)''',
                    (job['run_id'],asset['symbol'],strategy,RULE_VERSION,asset['actual_date'],asset['input_revision'],result['status'],result['is_signal'],dumps(result),stamp()))
        jobs.progress(job,'calculate',i+1)


def compute_pulse(conn, job):
    """Aggregate only this run; public breadth includes public stocks only."""
    indices, distributions = {}, {}
    for symbol in ('SPY','QQQ','IWM','VIX'):
        asset = conn.execute('SELECT * FROM run_assets WHERE run_id=? AND symbol=?',(job['run_id'],symbol)).fetchone()
        if not asset or asset['status'] != 'ok':
            indices[symbol] = None
            continue
        frame = dataframe(read_prices(conn,symbol,job['target_date'],asset['input_revision']))
        indices[symbol] = market_pulse.analyze_vix(frame) if symbol=='VIX' else market_pulse.analyze_index(symbol,frame) if len(frame)>=252 else None
        if symbol in ('SPY','QQQ'):
            distributions[symbol] = market_pulse.analyze_distribution_days(symbol,frame)
    rows = conn.execute('''SELECT d.payload FROM daily_results d JOIN run_assets a USING(run_id,symbol)
        WHERE d.run_id=? AND d.strategy_id='stage2_us' AND a.is_public=1 AND a.role='stock' ''',(job['run_id'],)).fetchall()
    results = [json.loads(r[0]) for r in rows]
    ok = [r for r in results if r['status']=='ok']
    breadth = dict(total=len(results), analyzed=len(ok), stage2_count=sum(r['is_signal'] for r in ok))
    if ok:
        n = len(ok)
        breadth['above_sma50_pct'] = sum(r['metrics']['price']>r['metrics']['sma50'] for r in ok)/n*100
        breadth['above_sma200_pct'] = sum(r['metrics']['price']>r['metrics']['sma200'] for r in ok)/n*100
        breadth['stage2_pct'] = breadth['stage2_count']/n*100
        breadth['up_5d_pct'] = sum((r['metrics'].get('chg_5d') or 0)>0 for r in ok)/n*100
        breadth['breadth_score'] = round(breadth['above_sma50_pct']*.35+breadth['above_sma200_pct']*.25+breadth['stage2_pct']*.25+breadth['up_5d_pct']*.15)
    complete = all(indices.values()) and len(ok)==len(results) and bool(ok)
    score, components = market_pulse.calculate_composite_score(indices['SPY'],indices['QQQ'],indices['IWM'],indices['VIX'],breadth if ok else None)
    regime = market_pulse.determine_regime(score,indices['SPY'],indices['VIX'],distributions)[0] if complete else None
    return clean(dict(status='ok' if complete else 'insufficient_data', date=job['target_date'], regime=regime,
                      score=score if complete else None, indices=indices, breadth=breadth, distribution_days=distributions))
