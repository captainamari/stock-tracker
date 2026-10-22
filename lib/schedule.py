"""Shared settings and timezone-aware due checks. No network or calculation."""
import json
import re
from datetime import datetime, time
from zoneinfo import ZoneInfo
from lib import db
from lib.settings import settings, utcnow
from lib.market_calendar import is_trading_day, completed_session
from lib.pipeline import request_update


def get_schedule(conn=None):
    if conn is None:
        with db.get_db() as own:
            return get_schedule(own)
    defaults=dict(update_time=settings().update_time,notify_time=settings().notify_time,channel='trading',enabled=False)
    row=conn.execute("SELECT value FROM settings WHERE key='schedule'").fetchone()
    return {**defaults,**(json.loads(row[0]) if row else {})}


def save_schedule(value):
    if set(value)!= {'update_time','notify_time','channel','enabled'}:
        raise ValueError('Unknown configuration field')
    for field in ('update_time','notify_time'):
        if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',value[field]):
            raise ValueError('Time must be HH:MM')
    if not re.fullmatch(r'[a-z0-9_-]{1,50}',value['channel']):
        raise ValueError('Use a hub channel alias, not a recipient or credential')
    with db.get_db() as conn:
        conn.execute("INSERT INTO settings VALUES ('schedule',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(value),))


def tick(now=None):
    now=now or utcnow()
    if now.tzinfo is None:
        raise ValueError('Clock must be timezone-aware')
    local=now.astimezone(ZoneInfo(settings().market_timezone))
    if not is_trading_day(local.date()):
        return []
    fired=[]
    with db.get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        config=get_schedule(conn)
        for kind, clock in [('update',config['update_time']),('notify',config['notify_time'])]:
            if kind=='notify' and not config['enabled']:
                continue
            due=datetime.combine(local.date(),time.fromisoformat(clock),tzinfo=local.tzinfo)
            if local<due or conn.execute('SELECT 1 FROM schedule_fires WHERE kind=? AND local_date=?',(kind,str(local.date()))).fetchone():
                continue
            if kind=='update':
                identifier=request_update('scheduled',due,conn)
            else:
                from lib.delivery import queue_daily
                identifier=queue_daily(conn,completed_session(due),str(local.date()),config['channel'])
            conn.execute('INSERT INTO schedule_fires VALUES (?,?,?)',(kind,str(local.date()),identifier))
            fired.append((kind,identifier))
    return fired
