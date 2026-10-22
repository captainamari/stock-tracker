"""Atomic publication pointer, candidate transitions and immutable daily snapshot."""
import json
from lib import db, jobs
from lib.settings import stamp, settings
from lib.strategy_service import compute_pulse, dumps, STRATEGIES


def transition(conn, batch, row, price):
    if row['status'] != 'ok' or row['strategy_id'] not in STRATEGIES:
        return
    symbol, strategy, active = row['symbol'], row['strategy_id'], row['is_signal']
    old = conn.execute('SELECT * FROM candidate_states WHERE symbol=? AND strategy_id=?',(symbol,strategy)).fetchone()
    was_active = bool(old and old['active'])
    entry_date = old['entry_date'] if old else None
    entry_price = old['entry_price'] if old else None
    if active and not was_active:
        entry_date, entry_price = row['actual_date'], price
    if bool(active) != was_active:
        conn.execute('INSERT INTO candidate_changes VALUES (?,?,?,?,?,?)',
                     (batch,symbol,strategy,row['actual_date'],'entry' if active else 'exit',price))
    conn.execute('''INSERT INTO candidate_states VALUES (?,?,?,?,?,?) ON CONFLICT(symbol,strategy_id)
        DO UPDATE SET active=excluded.active,entry_date=excluded.entry_date,entry_price=excluded.entry_price,last_date=excluded.last_date''',
        (symbol,strategy,active,entry_date,entry_price,row['actual_date']))


def report_body(conn, batch, target, pulse):
    assets = [dict(r) for r in conn.execute("SELECT * FROM run_assets WHERE run_id=? AND is_public=1 AND role='stock' ORDER BY symbol",(batch,))]
    rows = conn.execute('''SELECT d.* FROM daily_results d JOIN run_assets a USING(run_id,symbol)
        WHERE d.run_id=? AND a.is_public=1 AND a.role='stock' ORDER BY d.symbol''',(batch,)).fetchall()
    missing = sum(a['status']!='ok' for a in assets)
    strategy_missing = sum(r['status']!='ok' for r in rows if r['strategy_id']!='technical')
    lines = [f'Stock Tracker · 行情日期 / Market date {target}',
             f'行情缺失/失败 Missing/failed: {missing}/{len(assets)}; 策略不可计算 unavailable: {strategy_missing}',
             f'市场背景 Market context: {pulse["regime"] or "数据不足 / insufficient data"}',
             f'公开观察池宽度 Public watchlist breadth: {pulse["breadth"].get("stage2_count",0)}/{pulse["breadth"].get("analyzed",0)} assessed (not whole market)']
    names = dict(zip(STRATEGIES, ('Stage2','收缩候选 / Contraction candidates','逆势观察 / Bottom Fisher','Checklist (score ≠ win probability)')))
    for strategy in STRATEGIES:
        matches = [r['symbol'] for r in rows if r['strategy_id']==strategy and r['status']=='ok' and r['is_signal']]
        lines.append(f'{names[strategy]} ({len(matches)}): '+(', '.join(matches) if matches else '本日无候选 / No candidates'))
    lines.append('实际价格 / Adjusted prices:')
    for a in assets:
        lines.append(f'{a["symbol"]}: {a["price"] if a["price"] is not None else "—"} · {a["actual_date"] or "missing"} · {a["status"]}')
    changes = conn.execute('''SELECT c.* FROM candidate_changes c JOIN run_assets a ON a.run_id=c.batch_id AND a.symbol=c.symbol
        WHERE c.batch_id=? AND a.is_public=1 AND a.role='stock' ''',(batch,)).fetchall()
    lines.append('状态变化 / Changes: '+('; '.join(f'{c["symbol"]} {names[c["strategy_id"]]} {c["change_type"]}' for c in changes) or '无 / None'))
    lines.extend(['周线条件含本周暂态 / Weekly Checklist includes the provisional week.', f'{settings().public_url}/?batch={batch}'])
    return '\n'.join(lines)


def publish(job):
    # Expensive aggregation happens without a write lock.
    with db.get_db() as conn:
        pulse = compute_pulse(conn,job)
    with db.get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        jobs.fence(conn,job)
        latest = conn.execute('SELECT p.target_date FROM publications p JOIN current_publication c ON p.batch_id=c.batch_id WHERE c.id=1').fetchone()
        if latest and job['target_date'] < latest[0]:
            raise ValueError('An older market date cannot replace the current publication')
        count = conn.execute('SELECT COUNT(*) FROM daily_results WHERE run_id=?',(job['run_id'],)).fetchone()[0]
        expected = conn.execute('SELECT COUNT(*) FROM run_assets WHERE run_id=?',(job['run_id'],)).fetchone()[0]*5
        if count != expected:
            raise ValueError('Incomplete result set cannot publish')
        now = stamp()
        conn.execute('INSERT INTO publications VALUES (?,?,?,?)',(job['run_id'],job['target_date'],now,dumps(pulse)))
        rows = conn.execute('''SELECT d.*,a.price FROM daily_results d JOIN run_assets a USING(run_id,symbol) WHERE d.run_id=?''',(job['run_id'],)).fetchall()
        for row in rows:
            transition(conn,job['run_id'],row,row['price'])
        body = report_body(conn,job['run_id'],job['target_date'],pulse)
        conn.execute('INSERT INTO report_snapshots VALUES (?,?,?,?,?,?,1)',(job['run_id'],job['run_id'],job['target_date'],'daily',body,now))
        from lib.daily_reports import build_document, store_document, freeze_private
        store_document(conn, build_document(conn, job['run_id'], job['target_date'], pulse, 'all'))
        freeze_private(conn, job['run_id'], job['target_date'], pulse)
        conn.execute('INSERT INTO current_publication VALUES (1,?) ON CONFLICT(id) DO UPDATE SET batch_id=excluded.batch_id',(job['run_id'],))
        conn.execute("UPDATE update_runs SET status='published',stage='complete',finished_at=? WHERE run_id=?",(now,job['run_id']))
