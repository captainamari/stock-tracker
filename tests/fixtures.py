"""Synthetic prices, exclusively for isolated tests and capacity runs."""
import numpy as np
import pandas as pd
from lib.market_calendar import sessions
from lib import db
from lib.pipeline import request_update
from lib.worker import run_once
from tests.test_updates import NOW


def bars(symbol, start='2024-09-01', target='2026-10-20', short=False):
    days = sessions(start,target)
    if short:
        days = days[-25:]
    i = np.arange(len(days))
    slope = .09 if symbol in ('SPY','QQQ','IWM','^VIX') else .35
    close = 45 + i*slope + np.sin(i*.4)*1.3
    return pd.DataFrame({'Open':close-.2,'High':close+1,'Low':close-1,'Close':close,'Volume':1_000_000+(i%17)*1000},index=pd.to_datetime(days))


def seed_watchlist(symbols=('AAA',)):
    db.upsert_watchlist([{'symbol':s,'name':f'SYNTHETIC {s}'} for s in symbols])
    with db.get_db() as conn:
        conn.execute('UPDATE watchlist SET is_public=1')


def update(provider=bars, now=NOW):
    run = request_update('manual',now)
    assert run_once(provider)==run
    return run
