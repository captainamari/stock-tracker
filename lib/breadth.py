"""Versioned breadth from the run's frozen index union, including absent members."""
import json
from lib.universe import yahoo_symbol


def aggregate(conn, run_id):
    snapshot = conn.execute('''SELECT s.*,r.universe_status FROM update_runs r JOIN universe_snapshots s
        ON s.snapshot_id=r.universe_snapshot WHERE r.run_id=?''', (run_id,)).fetchone()
    members = set()
    if snapshot:
        for index in json.loads(snapshot['payload'])['indices'].values():
            members.update(yahoo_symbol(r['symbol']) for r in index['members'])
    members -= {'SPY', 'QQQ', 'IWM', 'VIX', '^VIX'}
    results = {}
    for row in conn.execute('''SELECT a.yf_ticker,a.status,d.payload FROM run_assets a
        JOIN daily_results d USING(run_id,symbol) WHERE a.run_id=? AND a.role='stock'
        AND d.strategy_id='stage2_us' ORDER BY a.symbol''', (run_id,)):
        symbol = yahoo_symbol(row['yf_ticker'])
        value = json.loads(row['payload'])
        if symbol in members and row['status'] == 'ok' and value['status'] == 'ok':
            results.setdefault(symbol, value)
    ok = list(results.values())
    n = len(ok)
    breadth = dict(membership_status=snapshot['universe_status'] if snapshot else 'unavailable',scope='index_union', version=2, snapshot_id=snapshot['snapshot_id'] if snapshot else None,
                   fetched_at=snapshot['fetched_at'] if snapshot else None, total=len(members), analyzed=n,
                   missing=len(members)-n, coverage=n/len(members)*100 if members else None,
                   stage2_count=sum(bool(r['is_signal']) for r in ok), denominators={})
    checks = {
        'above_sma50_pct': ('price', 'sma50'),
        'above_sma200_pct': ('price', 'sma200'),
        'up_5d_pct': ('chg_5d',),
    }
    for key, fields in checks.items():
        valid = [r['metrics'] for r in ok if all(isinstance(r['metrics'].get(f), (int, float)) for f in fields)]
        breadth['denominators'][key] = len(valid)
        breadth[key] = (sum(m[fields[0]] > (m[fields[1]] if len(fields)==2 else 0) for m in valid)/len(valid)*100) if valid else None
    breadth['denominators']['stage2_pct'] = n
    breadth['stage2_pct'] = breadth['stage2_count']/n*100 if n else None
    breadth['breadth_score'] = (round(breadth['above_sma50_pct']*.35 + breadth['above_sma200_pct']*.25
        + breadth['stage2_pct']*.25 + breadth['up_5d_pct']*.15)
        if all(breadth.get(k) is not None for k in (*checks, 'stage2_pct')) else None)
    return breadth
