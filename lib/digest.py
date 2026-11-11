"""Independent owner digest: saved publications in, scoped outbox delivery out."""
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from lib import db, delivery
from lib.settings import settings, stamp
from lib.symbols import normalize, resolve
from lib.market_calendar import completed_session, is_trading_day
from lib.daily_reports import build_document, notification_text


@contextmanager
def readonly():
    conn = sqlite3.connect(settings().database.resolve().as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        yield conn
    finally:
        conn.close()


def load_config(path, conn):
    path = Path(path)
    if path.stat().st_size > 20000:
        raise ValueError('Configuration is too large')
    config = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(config, dict) or set(config) != {'version','profile','symbols','channel','mode'}:
        raise ValueError('Expected version, profile, symbols, channel and mode only')
    if type(config['version']) is not int or config['version'] != 1:
        raise ValueError('Unsupported configuration version')
    for key in ('profile','channel'):
        if not isinstance(config[key], str) or not re.fullmatch(r'[a-z0-9_-]{1,50}', config[key]):
            raise ValueError(f'{key} must be a stable alias (a-z, 0-9, underscore, hyphen)')
    if config['mode'] not in ('standard','compact'):
        raise ValueError('mode must be standard or compact')
    config['symbols'] = resolve(conn, normalize(config['symbols']))
    if not config['symbols']:
        raise ValueError('symbols must not be empty; no all-market fallback')
    from lib.jobs import dependencies
    covered = {r['symbol'] for r in dependencies(conn)}
    unknown = [s for s in config['symbols'] if s not in covered]
    if unknown:
        raise ValueError('Not covered: '+', '.join(unknown)+'. Add separately with python -m lib.cli asset-add SYMBOL')
    return config


def target_date(value=None, now=None):
    if value is None:
        return completed_session(now)
    try:
        day = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError('date must be YYYY-MM-DD') from None
    if day.isoformat() != value or not is_trading_day(day):
        raise ValueError('date must be an XNYS trading session in YYYY-MM-DD format')
    return value


def preview(conn, config, target):
    pub = conn.execute('''SELECT p.* FROM publications p JOIN update_runs r ON r.run_id=p.batch_id
        WHERE p.target_date=? AND r.status='published' ORDER BY p.published_at DESC,p.batch_id DESC LIMIT 1''', (target,)).fetchone()
    if pub is None:
        body = (f'Stock Tracker · 延迟/缺失 / Delayed or missing\n目标行情日期 / Expected market date: {target}\n'
                '目标交易日尚无完整发布；不以旧日替代，不自动补发。\n'
                'No complete publication for this session; no automatic later replacement.\n'
                '缺失名单 / Missing: '+', '.join(config['symbols']))
        return None, body, None
    doc = build_document(conn, pub['batch_id'], target, json.loads(pub['pulse']), 'owner', config['symbols'])
    by_symbol = {a['symbol']:a for a in doc['assets']}
    doc['assets'] = [by_symbol.get(s, dict(symbol=s,name=s,price=None,change_1d=None,actual_date=None,
        status='pending',strategies={},changes=[],role='stock')) for s in config['symbols']]
    doc.update(missing=sum(a['status']!='ok' for a in doc['assets']),
               strategy_missing=sum(a['role']!='benchmark' and any(a['strategies'].get(k,{}).get('status')!='ok'
                   for k in ('stage2_us','contraction_us','bottom_fisher_us','checklist_us')) for a in doc['assets']),
               url=settings().public_url+'/', config=config)
    return pub['batch_id'], notification_text(doc, config['mode']), doc


def freeze(config, target, manual=False):
    """IMMEDIATE transaction plus database uniqueness serializes competing invocations."""
    with db.get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        old = conn.execute('SELECT delivery_id FROM digest_runs WHERE profile=? AND target_date=? AND channel=?',
                           (config['profile'],target,config['channel'])).fetchone()
        if old and not manual:
            return old[0]
        batch, body, doc = preview(conn, config, target)
        identifier = 'owner-'+uuid.uuid4().hex
        conn.execute('INSERT INTO report_snapshots VALUES (?,?,?,?,?,?,0)',
                     (identifier,batch,target,'owner' if batch else 'missing',body,stamp()))
        # Freeze selected membership/configuration even for a missing-data notice.
        payload = doc or dict(config=config, symbols=config['symbols'], batch_id=None, target_date=target)
        conn.execute('INSERT INTO report_documents VALUES (?,1,?,?)', (identifier,'owner',json.dumps(payload,ensure_ascii=False)))
        key = ('manual:'+identifier if manual else 'owner:'+config['profile']+':'+target+':'+config['channel'])
        item = delivery.queue_report(conn,identifier,target,config['channel'],key,body)
        if not manual:
            conn.execute('INSERT INTO digest_runs VALUES (?,?,?,?,?,?,?)',
                (config['profile'],target,config['channel'],item,json.dumps(config),batch,'ready' if batch else 'missing'))
        return item


def send(config, target, client=None, manual=False):
    identifier = freeze(config, target, manual)
    delivery.run_once(client, delivery_id=identifier)
    with db.get_db() as conn:
        row = conn.execute('''SELECT d.status,r.kind FROM deliveries d JOIN report_snapshots r USING(report_id)
            WHERE d.delivery_id=?''', (identifier,)).fetchone()
    return dict(delivery_id=identifier, status=row['status'], readiness='missing' if row['kind']=='missing' else 'ready')
