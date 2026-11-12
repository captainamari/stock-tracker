"""Public projections. Never return owner labels or trust client visibility flags."""
import json
from lib import db
from lib.queries import dashboard_data, publication, permitted
from lib.symbols import normalize, resolve
from lib.listing import select, paginate, STRATEGIES, near, score

PRIVATE_FIELDS = {'is_followed','is_held','is_personal','yf_ticker','input_revision','run_id',
                  'reason','error','owner','receipt','source_type','added_at','updated_at'}


def public_value(value):
    if isinstance(value, dict):
        return {k:public_value(v) for k,v in value.items() if k not in PRIVATE_FIELDS}
    if isinstance(value, list):
        return [public_value(v) for v in value]
    return value


def summary(batch=None):
    with db.get_db() as conn:
        from lib.universe import summary as universe_summary
        universe = universe_summary(conn)
        universe.pop('error', None)
        pub = publication(conn, batch)
    return dict(universe=universe,batch_id=pub['batch_id'] if pub else None, latest_date=pub['target_date'] if pub else None,
                published_at=pub['published_at'] if pub else None, pulse=json.loads(pub['pulse']) if pub else None)


def collection(batch=None, symbols=None, report_id=None, **filters):
    with db.get_db() as conn:
        conn.execute('BEGIN')
        chosen = resolve(conn, symbols, public=True) if symbols is not None else None
        if report_id:
            row = conn.execute('''SELECT r.*,d.payload FROM report_snapshots r
                LEFT JOIN report_documents d USING(report_id) WHERE r.report_id=? AND r.public=1''', (report_id,)).fetchone()
            if not row or not row['payload']:
                raise LookupError('Public structured report not found')
            doc = json.loads(row['payload'])
            rows = [a for a in doc['assets'] if permitted(conn,a['symbol'],a)]
            data = dict(batch_id=row['batch_id'],latest_date=row['target_date'],pulse=doc['pulse'],assets=rows,changes=[])
        else:
            data = dashboard_data(batch, include_pending=True)
            rows = data['assets']
            # Changes require two successful adjacent-session evaluations, as in frozen reports.
            saved = conn.execute('SELECT payload FROM report_documents WHERE report_id=?', (data['batch_id'],)).fetchone()
            frozen = {a['symbol']:a for a in json.loads(saved[0])['assets']} if saved else {}
            for a in rows:
                historical = frozen.get(a['symbol'], {})
                a['changes'] = historical.get('changes', [])
                for key, result in a['strategies'].items():
                    result['previous'] = historical.get('strategies', {}).get(key, {}).get('previous')
        mapping = {a['symbol']:a for a in rows}
        if chosen is not None:
            rows = [mapping.get(s,dict(symbol=s,status='unavailable',name='',price=None,actual_date=None,
                change_1d=None,role='stock',strategies={},changes=[])) for s in chosen]
    for a in rows:
        a.setdefault('changes',[])
        if a.get('role')=='benchmark':
            a['strategies'] = {k:v for k,v in a['strategies'].items() if k=='technical'}
            a['changes'] = []
        for key, result in a['strategies'].items():
            result['near'] = near(result,key)
            result['score'] = score(result,key)
    candidates = {key:[dict(symbol=a['symbol'],price=a.get('price'),actual_date=a.get('actual_date')) for a in rows
        if a['strategies'].get(key,{}).get('is_signal') and a['strategies'][key].get('status')=='ok'
        and a.get('role')!='benchmark'] for key in STRATEGIES}
    changes = [dict(symbol=a['symbol'],**c) for a in rows for c in a['changes']]
    comparisons = [a['strategies'].get(key, {}) for a in rows if a.get('role')!='benchmark' for key in STRATEGIES]
    page, size = filters.pop('page',1), filters.pop('size',20)
    sort = filters.get('sort','order')
    selected = select(rows, **filters)
    if sort=='order' and chosen is not None:
        order = {s:i for i,s in enumerate(chosen)}
        selected.sort(key=lambda a:order[a['symbol']])
    result = paginate(selected,page,size)
    # Provenance follows the publication's revision watermark, including old reports.
    with db.get_db() as conn:
        for a in result['items']:
            price = conn.execute('''SELECT p.source,p.basis FROM price_revisions p
                JOIN run_assets r ON r.symbol=p.symbol AND r.run_id=?
                WHERE p.symbol=? AND p.date<=r.actual_date AND p.id<=r.input_revision
                ORDER BY p.date DESC,p.id DESC LIMIT 1''', (data['batch_id'], a['symbol'])).fetchone()
            a['price_source'] = price['source'] if price else None
            a['price_basis'] = price['basis'] if price else None
    return public_value(dict(**result,batch_id=data['batch_id'],latest_date=data['latest_date'],pulse=data['pulse'],
        counts={k:len(v) for k,v in candidates.items()},candidates={k:v[:5] for k,v in candidates.items()},changes=changes,
        comparison_count=sum(r.get('previous') is not None for r in comparisons),
        comparison_missing=sum(r.get('previous') is None for r in comparisons),
        selected_count=len(rows),missing_count=sum(a['status']!='ok' for a in rows)))
