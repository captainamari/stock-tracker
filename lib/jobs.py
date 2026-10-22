"""Durable singleton queue with lease fencing. Browser lifetime is irrelevant."""
import json
import time
import uuid
from lib import db
from lib.market_calendar import completed_session
from lib.settings import settings, stamp

DEPENDENCIES = {'SPY': 'SPY', 'QQQ': 'QQQ', 'IWM': 'IWM', 'VIX': '^VIX'}


def dependencies(conn):
    from lib.universe import active_clause, yahoo_symbol
    rows = {}
    # One daily-history request per Yahoo ticker, including spelling aliases.
    # Privacy is conservative when two personal entries name the same security.
    for r in conn.execute(f'SELECT * FROM watchlist w WHERE {active_clause()} ORDER BY is_personal DESC,is_public,symbol'):
        if r['symbol'] in DEPENDENCIES:
            continue
        value = dict(r)
        yf = yahoo_symbol(value['yf_ticker'] or value['symbol'])
        value['yf_ticker'] = yf
        if yf in rows:
            rows[yf]['is_public'] = min(rows[yf]['is_public'], value['is_public'])
        else:
            rows[yf] = value
    for symbol, yf_symbol in DEPENDENCIES.items():
        existing = conn.execute('SELECT * FROM watchlist WHERE symbol=?', (symbol,)).fetchone()
        value = dict(existing) if existing else {'symbol': symbol, 'name': symbol, 'sector': '', 'is_public': 1}
        if yf_symbol in rows:
            value['is_public'] = min(value['is_public'], rows[yf_symbol]['is_public'])
        # Strategy benchmarks always use their fixed source mapping.
        value.update(symbol=symbol, yf_ticker=yf_symbol)
        rows[yf_symbol] = value
    return list(rows.values())


def insert_assets(conn, run_id, assets):
    conn.executemany('INSERT INTO run_assets(run_id,symbol,name,sector,yf_ticker,is_public,role) VALUES (?,?,?,?,?,?,?)',
                     [(run_id, a['symbol'], a['name'], a.get('sector') or '', a['yf_ticker'], a['is_public'],
                       'benchmark' if a['symbol'] in DEPENDENCIES else 'stock') for a in assets])


def enqueue(trigger, now=None, conn=None):
    if trigger not in ('manual', 'scheduled'):
        raise ValueError('Only administrator and scheduler may enqueue updates')
    if conn is None:
        with db.get_db() as own:
            own.execute('BEGIN IMMEDIATE')
            return enqueue(trigger, now, own)
    running = conn.execute("SELECT run_id FROM update_runs WHERE status IN ('queued','running')").fetchone()
    if running:
        return running[0]
    from lib.universe import seed
    seed(conn)
    run_id = uuid.uuid4().hex
    assets = dependencies(conn)
    conn.execute('INSERT INTO update_runs(run_id,trigger,target_date,status,created_at,total) VALUES (?,?,?,?,?,?)',
                 (run_id, trigger, completed_session(now), 'queued', stamp(), len(assets)))
    insert_assets(conn, run_id, assets)
    return run_id


def claim(now=None):
    now = time.time() if now is None else now
    with db.get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute("SELECT * FROM update_runs WHERE status='queued' OR (status='running' AND lease_until<?) ORDER BY created_at LIMIT 1", (now,)).fetchone()
        if not row:
            return None
        owner = uuid.uuid4().hex
        conn.execute("UPDATE update_runs SET status='running',owner=?,attempt=attempt+1,started_at=?,heartbeat=?,lease_until=?,stage='collect',completed=0 WHERE run_id=?",
                     (owner, stamp(), now, now+settings().lease_seconds, row['run_id']))
        return dict(conn.execute('SELECT * FROM update_runs WHERE run_id=?', (row['run_id'],)).fetchone())


class LostLease(RuntimeError):
    pass


def fence(conn, job):
    row = conn.execute("SELECT 1 FROM update_runs WHERE run_id=? AND owner=? AND status='running' AND lease_until>?",
                       (job['run_id'], job['owner'], time.time())).fetchone()
    if not row:
        raise LostLease('Worker lease expired or superseded')


def heartbeat(job):
    with db.get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        fence(conn, job)
        now = time.time()
        conn.execute('UPDATE update_runs SET heartbeat=?,lease_until=? WHERE run_id=?', (now, now+settings().lease_seconds, job['run_id']))


def progress(job, stage, completed=None):
    with db.get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        fence(conn, job)
        conn.execute('UPDATE update_runs SET stage=?,completed=COALESCE(?,completed) WHERE run_id=?', (stage, completed, job['run_id']))


def get_run(run_id):
    with db.get_db() as conn:
        row = conn.execute('SELECT run_id,trigger,target_date,status,created_at,finished_at,attempt,stage,completed,total,error FROM update_runs WHERE run_id=?', (run_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result['assets'] = [dict(r) for r in conn.execute('SELECT symbol,status,reason,actual_date,missing_count FROM run_assets WHERE run_id=? ORDER BY symbol', (run_id,))]
        return result
