"""Index membership configuration, separate from personal preferences and prices.

The two publicly maintained constituent tables are metadata sources, not price
providers. Only the update worker refreshes them; GET and enqueue stay offline.
"""
import hashlib
import json
import re
import time
from datetime import datetime
from pathlib import Path
import httpx
from bs4 import BeautifulSoup
from lib import db
from lib.settings import settings, stamp

SOURCES = {
    'sp500': 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies',
    'nasdaq100': 'https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies',
}
LIMITS = {'sp500': (490, 510), 'nasdaq100': (95, 110)}
BUNDLE = Path(__file__).resolve().parents[1] / 'config/index_universe.json'
WEEK = 7 * 86400
RETRY = 86400


def yahoo_symbol(symbol):
    return symbol.strip().upper().replace('.', '-')


def active_clause(alias='w'):
    managed = f'EXISTS (SELECT 1 FROM index_memberships m WHERE m.symbol={alias}.symbol)' if settings().index_universe_enabled else '0'
    return f'{alias}.enabled=1 AND ({alias}.is_personal=1 OR {managed})'


def validate(snapshot):
    if set(snapshot['indices']) != set(SOURCES):
        raise ValueError('Both index lists are required')
    fetched = datetime.fromisoformat(snapshot['fetched_at'])
    if fetched.tzinfo is None or fetched.timestamp() > time.time() + 300:
        raise ValueError('Invalid membership timestamp')
    for index, source in SOURCES.items():
        entry = snapshot['indices'][index]
        if entry['source_url'] != source:
            raise ValueError('Unexpected membership source')
        members = entry['members']
        lo, hi = LIMITS[index]
        if not lo <= len(members) <= hi:
            raise ValueError(f'Unexpected {index} constituent count')
        symbols = set()
        for row in members:
            symbol = row['symbol']
            if not isinstance(symbol, str) or not re.fullmatch(r'[A-Z][A-Z0-9-]{0,14}', symbol):
                raise ValueError('Invalid constituent symbol')
            if symbol in symbols or symbol in ('SPY', 'QQQ', 'IWM', 'VIX'):
                raise ValueError('Duplicate or benchmark in constituent list')
            if not isinstance(row['name'], str) or not 1 <= len(row['name']) <= 200:
                raise ValueError('Invalid constituent name')
            symbols.add(symbol)
    return snapshot


def parse_table(html, index):
    soup = BeautifulSoup(html, 'html.parser')
    table = soup.find('table', id='constituents')
    if table is None:
        raise ValueError('Constituent table missing')
    for note in table.select('sup'):
        note.decompose()
    rows = table.find_all('tr')
    headers = [c.get_text(' ', strip=True) for c in rows[0].find_all(['th', 'td'])]
    wanted = ('Symbol', 'Security') if index == 'sp500' else ('Ticker', 'Company')
    if headers[:2] != list(wanted):
        raise ValueError('Constituent table schema changed')
    members = []
    for row in rows[1:]:
        cells = row.find_all(['td', 'th'], recursive=False)
        if len(cells) != len(headers):
            raise ValueError('Incomplete constituent row')
        members.append({'symbol': yahoo_symbol(cells[0].get_text(' ', strip=True)),
                        'name': cells[1].get_text(' ', strip=True)})
    return sorted(members, key=lambda r:r['symbol'])


def fetch_snapshot():
    indices = {}
    # Honest identification is required by Wikimedia; no cookie/proxy rotation.
    with httpx.Client(timeout=25, follow_redirects=True, headers={
        'User-Agent': 'StockTracker/1.0 (https://github.com/captainamari/stock-tracker; index membership refresh)'
    }) as client:
        for index, url in SOURCES.items():
            with client.stream('GET', url) as response:
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 4_000_000:
                        raise ValueError('Membership response too large')
            indices[index] = {'source_url': url, 'members': parse_table(body.decode('utf-8'), index)}
    return validate({'fetched_at': stamp(), 'indices': indices})


def apply_snapshot(conn, snapshot):
    """Caller owns an IMMEDIATE transaction. Never rewrite personal preferences."""
    validate(snapshot)
    previous = {i:{r[0] for r in conn.execute('''SELECT COALESCE(w.yf_ticker,w.symbol) FROM index_memberships m
        JOIN watchlist w USING(symbol) WHERE index_id=?''', (i,))} for i in SOURCES}
    for index, entry in snapshot['indices'].items():
        old = {yahoo_symbol(s) for s in previous[index]}
        new = {r['symbol'] for r in entry['members']}
        if old and len(old ^ new) > len(old) * .2:
            raise ValueError('Unexpected large constituent change; keep last known list')
    payload = json.dumps(snapshot, sort_keys=True, ensure_ascii=False)
    identifier = hashlib.sha256(payload.encode()).hexdigest()
    conn.execute('INSERT OR IGNORE INTO universe_snapshots VALUES (?,?,?)', (identifier, snapshot['fetched_at'], payload))
    # Prefer existing personal rows and retain their names, Yahoo mappings,
    # public/private flags and disabled state. BRK.B and BRK-B share one source.
    existing = {}
    for row in conn.execute('SELECT * FROM watchlist ORDER BY is_personal DESC,is_public,symbol'):
        existing.setdefault(yahoo_symbol(row['yf_ticker'] or row['symbol']), row['symbol'])
    memberships = []
    for index, entry in snapshot['indices'].items():
        for member in entry['members']:
            yf = member['symbol']
            symbol = existing.get(yf, yf)
            conflict = conn.execute('SELECT yf_ticker FROM watchlist WHERE symbol=?', (symbol,)).fetchone()
            if conflict and yahoo_symbol(conflict[0] or symbol) != yf:
                raise ValueError('Existing symbol mapping conflicts with index constituent')
            conn.execute('''INSERT OR IGNORE INTO watchlist(symbol,name,source_type,yf_ticker,is_public,is_personal,updated_at)
                VALUES (?,?,'index',?,1,0,?)''', (symbol, member['name'], yf, stamp()))
            existing[yf] = symbol
            memberships.append((index, symbol))
    conn.execute('DELETE FROM index_memberships')
    conn.executemany('INSERT INTO index_memberships VALUES (?,?)', memberships)
    conn.execute('''INSERT INTO universe_state(id,snapshot_id) VALUES (1,?)
        ON CONFLICT(id) DO UPDATE SET snapshot_id=excluded.snapshot_id,last_error=NULL''', (identifier,))
    return identifier


def seed(conn):
    if settings().index_universe_enabled and not conn.execute('SELECT 1 FROM universe_state').fetchone():
        apply_snapshot(conn, json.loads(BUNDLE.read_text(encoding='utf-8')))


def initialize():
    if not settings().index_universe_enabled:
        return
    from lib.config import sync_watchlist
    sync_watchlist()  # Existing database entries remain authoritative.
    with db.get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        seed(conn)


def prepare_run(job, fetcher=None):
    """Refresh at most weekly before freezing this run; restart reuses its set."""
    from lib import jobs
    fetcher = fetcher or fetch_snapshot
    with db.get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        jobs.fence(conn, job)
        run = conn.execute('SELECT * FROM update_runs WHERE run_id=?', (job['run_id'],)).fetchone()
        if run['universe_prepared']:
            return
        # Preserve jobs already collecting when this additive migration lands.
        if run['completed'] or run['stage'] == 'calculate':
            conn.execute('UPDATE update_runs SET universe_prepared=1 WHERE run_id=?', (job['run_id'],))
            return
        seed(conn)
        state = conn.execute('''SELECT u.*,s.fetched_at FROM universe_state u
            JOIN universe_snapshots s USING(snapshot_id)''').fetchone()
        now = time.time()
        due = bool(settings().index_universe_enabled and state and
                   now - datetime.fromisoformat(state['fetched_at']).timestamp() >= WEEK and
                   now - state['last_attempt'] >= RETRY)
        if due:
            conn.execute('UPDATE universe_state SET last_attempt=? WHERE id=1', (now,))
    if due:
        try:
            snapshot = fetcher()  # No SQLite transaction while using network.
            with db.get_db() as conn:
                conn.execute('BEGIN IMMEDIATE')
                jobs.fence(conn, job)
                apply_snapshot(conn, snapshot)
        except jobs.LostLease:
            raise
        except Exception as exc:
            with db.get_db() as conn:
                conn.execute('BEGIN IMMEDIATE')
                jobs.fence(conn, job)
                conn.execute('UPDATE universe_state SET last_error=? WHERE id=1', (type(exc).__name__,))
    with db.get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        jobs.fence(conn, job)
        assets = jobs.dependencies(conn)
        conn.execute('DELETE FROM run_assets WHERE run_id=?', (job['run_id'],))
        jobs.insert_assets(conn, job['run_id'], assets)
        state = conn.execute('SELECT snapshot_id FROM universe_state').fetchone()
        conn.execute('UPDATE update_runs SET total=?,universe_snapshot=?,universe_prepared=1 WHERE run_id=?',
                     (len(assets), state[0] if state and settings().index_universe_enabled else None, job['run_id']))


def summary(conn):
    row = conn.execute('''SELECT u.last_error,s.fetched_at FROM universe_state u
        JOIN universe_snapshots s USING(snapshot_id)''').fetchone()
    counts = dict(conn.execute('SELECT index_id,COUNT(*) FROM index_memberships GROUP BY index_id'))
    return dict(enabled=settings().index_universe_enabled, counts=counts,
                unique=conn.execute('SELECT COUNT(DISTINCT symbol) FROM index_memberships').fetchone()[0],
                fetched_at=row['fetched_at'] if row else None, error=row['last_error'] if row else None,
                stale=bool(row and time.time()-datetime.fromisoformat(row['fetched_at']).timestamp() >= WEEK))
