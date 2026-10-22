"""Frozen, structured daily reports. Reads saved measurements; never computes prices."""
import json
from datetime import date, timedelta
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from lib.listing import STRATEGIES, in_scope, score, near
from lib.settings import settings, stamp

NAMES = dict(zip(STRATEGIES, ('Stage 2 趋势 / Trend', '收缩候选 / Contraction',
                            '逆势观察 / Countertrend', 'Checklist 条件清单')))
SCOPES = ('following', 'held', 'personal')


def report_id(batch, scope):
    return batch if scope == 'all' else f'{batch}-{scope}'


def build_document(conn, batch, target, pulse, scope):
    assets = []
    from lib.market_calendar import calendar
    previous_date = calendar(int(target[:4])).previous_session(target).date().isoformat()
    from lib.market_calendar import sessions
    chart_dates = sessions(str(date.fromisoformat(target)-timedelta(days=45)), target)[-20:]
    prior = conn.execute('SELECT batch_id FROM publications WHERE target_date=? ORDER BY published_at DESC,batch_id DESC LIMIT 1', (previous_date,)).fetchone()
    previous = {}
    if prior:
        previous = {(r['symbol'], r['strategy_id']): json.loads(r['payload']) for r in conn.execute('SELECT symbol,strategy_id,payload FROM daily_results WHERE run_id=?', (prior[0],))}
    saved = {}
    for row in conn.execute('SELECT symbol,strategy_id,payload FROM daily_results WHERE run_id=?', (batch,)):
        saved.setdefault(row['symbol'], {})[row['strategy_id']] = json.loads(row['payload'])
    for row in conn.execute('''SELECT a.*,w.is_followed,w.is_held FROM run_assets a
                              LEFT JOIN watchlist w USING(symbol) WHERE run_id=? AND role='stock' ORDER BY symbol''', (batch,)):
        a = dict(row)
        if not (a['is_public'] if scope == 'all' else in_scope(a, scope)):
            continue
        if scope == 'all':
            a.pop('is_followed', None)
            a.pop('is_held', None)
        a['strategies'] = saved.get(a['symbol'], {})
        a['changes'] = []
        for key in STRATEGIES:
            r = a['strategies'].get(key, {})
            old = previous.get((a['symbol'], key))
            r['score'] = score(r, key)
            r['near'] = near(r, key)
            r['previous'] = None
            if old and old.get('status') == 'ok' and r.get('status') == 'ok':
                r['previous'] = dict(passed=old.get('passed'), score=score(old, key), is_signal=old.get('is_signal'))
                if bool(old.get('is_signal')) != bool(r.get('is_signal')):
                    a['changes'].append(dict(strategy=key, change='entry' if r['is_signal'] else 'exit'))
            # Missing/failed previous evaluation is not a confirmed entry or exit.
        technical = a['strategies'].get('stage2_us', {}).get('metrics', {})
        a['change_5d'] = technical.get('chg_5d')
        a['change_20d'] = technical.get('chg_20d')
        for r in a['strategies'].values():
            raw = r.get('metrics', {})
            r['details'] = raw.get('condition_details', {})
        # Use the input revision pinned by this publication, not the latest DB prices.
        from lib.prices import read_prices
        history = read_prices(conn, a['symbol'], target, a['input_revision'] or 0)
        closes = {r['date']:r['close'] for r in history if r['quality']=='valid'}
        a['sparkline'] = [closes.get(day) for day in chart_dates]
        assets.append(a)
    assets.sort(key=lambda a: (not a.get('is_held'), not bool(a['changes']), a['symbol']))
    return dict(version=1, batch_id=batch, target_date=target, scope=scope, assets=assets, pulse=pulse,
                report_id=report_id(batch, scope), previous_batch=prior[0] if prior else None, previous_date=previous_date,
                followed=sum(bool(a.get('is_followed')) for a in assets), held=sum(bool(a.get('is_held')) for a in assets),
                missing=sum(a['status'] != 'ok' for a in assets),
                strategy_missing=sum(any(a['strategies'].get(s,{}).get('status') != 'ok' for s in STRATEGIES) for a in assets),
                changes=sum(len(a['changes']) for a in assets),
                url=f'{settings().public_url}/reports/{report_id(batch, scope)}')


def store_document(conn, document):
    conn.execute('INSERT INTO report_documents VALUES (?,1,?,?)',
                 (document['report_id'], document['scope'], json.dumps(document, ensure_ascii=False, allow_nan=False)))


def freeze_private(conn, batch, target, pulse):
    for scope in SCOPES:
        document = build_document(conn, batch, target, pulse, scope)
        conn.execute('INSERT INTO report_snapshots VALUES (?,?,?,?,?,?,0)',
                     (document['report_id'], batch, target, 'personal', notification_text(document), stamp()))
        store_document(conn, document)


def load_document(conn, identifier):
    row = conn.execute('SELECT payload FROM report_documents WHERE report_id=?', (identifier,)).fetchone()
    return json.loads(row[0]) if row else None


def notification_text(document, mode='standard'):
    env = Environment(loader=FileSystemLoader(str(Path(__file__).resolve().parents[1] / 'templates')),
                      undefined=StrictUndefined, autoescape=False, trim_blocks=True, lstrip_blocks=True)
    def fmt(value, percent=False):
        return '—' if value is None else f'{value:+.1f}%' if percent else f'{value:,.2f}'
    def clean(value):
        # Provider names/condition descriptions are text, never HTML or control codes.
        return ' '.join(str(value).split())
    groups = {}
    for strategy in STRATEGIES:
        matched, nearby = [], []
        for a in document['assets']:
            r = a['strategies'].get(strategy, {})
            if r.get('is_signal'):
                matched.append(a)
            elif r.get('near'):
                nearby.append(a)
        key = lambda a: (not a.get('is_held'), not bool(a['changes']), -(a['strategies'][strategy].get('score') or 0), a['symbol'])
        groups[strategy] = dict(matched=sorted(matched, key=key), near=sorted(nearby, key=key))
    return env.get_template('daily_notification.txt.j2').render(d=document, names=NAMES, groups=groups,
                compact=mode == 'compact', fmt=fmt, clean=clean).strip()


def notification_preview(conn, target, scope='personal', mode='standard'):
    publication = conn.execute('SELECT batch_id FROM publications WHERE target_date=? ORDER BY published_at DESC LIMIT 1', (target,)).fetchone()
    document = load_document(conn, report_id(publication[0], scope)) if publication else None
    if document:
        return document['report_id'], notification_text(document, mode)
    return None, (f'Stock Tracker · 延迟/缺失 / Delayed or missing\n目标行情日期 / Expected market date: {target}\n'
                  '该日期暂无此范围的私人日报；不会以公开日报或旧日报代替。\n'
                  'No private report for this session and scope. An older report is not substituted.')
