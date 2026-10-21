"""The only live price writer: explicit adjusted yfinance daily OHLC, native volume.

Immutable revisions retain exact values used by published inputs. A watermark is
captured per asset, allowing old reports/charts to survive later source revisions.
"""
import hashlib
import json
import math
import time
from datetime import date, timedelta
import pandas as pd
from lib import db
from lib.jobs import fence
from lib.market_calendar import sessions
from lib.settings import settings, stamp

BASIS = 'yfinance_auto_adjust_ohlc_native_volume_v1'


def download(symbol, start, target):
    import yfinance as yf
    # Keep the library's cookie/timezone cache inside the configured data directory.
    yf.set_tz_cache_location(str(settings().database.parent / 'yfinance-cache'))
    last_error = None
    for attempt in range(3):
        try:
            data = yf.Ticker(symbol).history(start=start, end=str(date.fromisoformat(target)+timedelta(days=1)),
                interval='1d', auto_adjust=True, back_adjust=False, repair=False, actions=True,
                keepna=True, timeout=20, raise_errors=True)
            if data is None or data.empty:
                raise ValueError('Source returned no daily bars')
            return data
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise RuntimeError(f'yfinance download failed: {type(last_error).__name__}') from last_error


def normalize(frame, target):
    result = []
    if frame is None or frame.empty:
        return result
    days = [idx.date().isoformat() for idx in frame.index]
    allowed = set(sessions(min(days), target)) if min(days) <= target else set()
    for (idx, row), day in zip(frame.iterrows(), days):
        if day not in allowed:
            continue  # Includes unfinished and non-session bars.
        values = []
        for key in ('Open','High','Low','Close','Volume'):
            value = row.get(key)
            values.append(float(value) if value is not None and pd.notna(value) and math.isfinite(float(value)) else None)
        o, h, l, c, v = values
        quality = 'valid'
        if any(x is None or x <= 0 for x in (o,h,l,c)) or not l <= min(o,c) <= max(o,c) <= h:
            quality = 'invalid_ohlc'
        elif v is None or v < 0:
            quality = 'missing_volume'
        result.append({'date': day, 'open': o, 'high': h, 'low': l, 'close': c, 'volume': v, 'quality': quality})
    if len({r['date'] for r in result}) != len(result):
        raise ValueError('Duplicate source session')
    return result


def read_prices(conn, symbol, target, watermark=None):
    sql = '''SELECT p.* FROM price_revisions p JOIN
        (SELECT date,MAX(id) id FROM price_revisions WHERE symbol=? AND date<=? AND id<=? GROUP BY date) v
        ON p.id=v.id ORDER BY p.date'''
    return [dict(r) for r in conn.execute(sql, (symbol, target, watermark if watermark is not None else 9223372036854775807))]


def dataframe(rows):
    if not rows:
        return None
    data = pd.DataFrame(rows).rename(columns={k: k.title() for k in ('open','high','low','close','volume')})
    data.index = pd.to_datetime(data['date'])
    return data[['Open','High','Low','Close','Volume']]


def collect_asset(job, asset, provider=download):
    cfg = settings()
    target = job['target_date']
    with db.get_db() as conn:
        old = read_prices(conn, asset['symbol'], target)
    floor = str(date.fromisoformat(target)-timedelta(days=cfg.history_days))
    recent = str(date.fromisoformat(target)-timedelta(days=cfg.revision_lookback_days))
    relevant = [r for r in old if r['date'] >= floor]
    holes = set(sessions(relevant[0]['date'], target)) - {r['date'] for r in relevant if r['quality']=='valid'} if relevant else set()
    start = floor if len(relevant) < 252 or holes else max(floor, recent)
    try:
        raw = provider(asset['yf_ticker'], start, target)
        rows = normalize(raw, target)
        if not rows:
            raise ValueError('No closed session in source response')
        old_by_date = {r['date']: r for r in old}
        # Adjusted history revisions or corporate actions require a full window,
        # never splice differently adjusted old and new portions.
        revised = any(r['date'] in old_by_date and old_by_date[r['date']]['close'] is not None and r['close'] is not None and
                      not math.isclose(r['close'], old_by_date[r['date']]['close'], rel_tol=1e-7, abs_tol=1e-7) for r in rows)
        action = any((raw[k].fillna(0) != 0).any() for k in ('Stock Splits','Dividends') if k in raw)
        if start != floor and (revised or action):
            rows = normalize(provider(asset['yf_ticker'], floor, target), target)
            start = floor
            if not rows:
                raise ValueError('Full revision recollection returned no bars')
        # An omitted previously known source day is an explicit tombstone, not
        # a silent use of the former bar as current valid input.
        returned = {r['date'] for r in rows}
        for prior in old:
            if start <= prior['date'] <= target and prior['date'] not in returned:
                rows.append(dict(date=prior['date'], open=None, high=None, low=None, close=None, volume=None, quality='source_missing'))
        # Large unexplained adjusted jumps are retained as invalid observations.
        merged = {r['date']: r for r in old}
        merged.update({r['date']:r for r in rows})
        previous = None
        for day in sorted(merged):
            r = merged[day]
            if r['close'] and previous and r in rows and (r['close']/previous > 2 or r['close']/previous < .5):
                r['quality'] = 'anomalous_jump'
            if r['close']:
                previous = r['close']
        fetched = stamp()
        with db.get_db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            fence(conn, job)
            for row in rows:
                fingerprint = hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
                previous = old_by_date.get(row['date'])
                if not previous or previous['fingerprint'] != fingerprint:
                    conn.execute('''INSERT INTO price_revisions(symbol,date,open,high,low,close,volume,source,basis,fetched_at,quality,fingerprint,run_id)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''', (asset['symbol'], row['date'], row['open'], row['high'], row['low'], row['close'], row['volume'], 'yfinance', BASIS, fetched, row['quality'], fingerprint, job['run_id']))
                if row['close'] is not None:
                    conn.execute('''INSERT INTO stock_prices(symbol,date,open,high,low,close,volume,source,basis,fetched_at,quality) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(symbol,date) DO UPDATE SET open=excluded.open,high=excluded.high,low=excluded.low,close=excluded.close,volume=excluded.volume,source=excluded.source,basis=excluded.basis,fetched_at=excluded.fetched_at,quality=excluded.quality''',
                        (asset['symbol'], row['date'], row['open'], row['high'], row['low'], row['close'], row['volume'], 'yfinance', BASIS, fetched, row['quality']))
            watermark = conn.execute('SELECT MAX(id) FROM price_revisions WHERE symbol=?', (asset['symbol'],)).fetchone()[0]
            stored = read_prices(conn, asset['symbol'], target, watermark)
            valid = [r for r in stored if r['quality']=='valid']
            actual = valid[-1]['date'] if valid else None
            required = sessions(max(floor, stored[0]['date']), target) if stored else []
            missing = len(set(required)-{r['date'] for r in valid})
            status = 'ok' if actual == target and missing == 0 else ('stale' if actual and actual < target else 'insufficient_data')
            conn.execute('UPDATE run_assets SET status=?,reason=?,actual_date=?,input_revision=?,fetched_at=?,missing_count=? WHERE run_id=? AND symbol=?',
                (status, None if status=='ok' else 'missing_or_invalid_sessions', actual, watermark, fetched, missing, job['run_id'], asset['symbol']))
    except Exception as exc:
        from lib.jobs import LostLease
        if isinstance(exc, LostLease):
            raise
        with db.get_db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            fence(conn, job)
            watermark = conn.execute('SELECT MAX(id) FROM price_revisions WHERE symbol=?', (asset['symbol'],)).fetchone()[0]
            actual = next((r['date'] for r in reversed(old) if r['quality']=='valid'), None)
            conn.execute("UPDATE run_assets SET status='failed',reason=?,actual_date=?,input_revision=? WHERE run_id=? AND symbol=?",
                         (f'source_failed:{type(exc).__name__}', actual, watermark, job['run_id'], asset['symbol']))
