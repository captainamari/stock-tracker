from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse
from lib.queries import dashboard_data, report_data
from web.auth import session
from web.deps import render

router = APIRouter()


def _build_dashboard_data(batch=None,private=False):
    return dashboard_data(batch,private)


@router.get('/')
def dashboard(request: Request,batch: str | None=None):
    from web.lists import listing
    from lib.listing import STRATEGIES, select, paginate
    private = bool(session(request))
    data = _build_dashboard_data(batch, private)
    selected = listing(request, data['assets'], data['batch_id'], private)
    data.update(selected)
    data['assets'] = selected['selected_assets']
    allowed = {a['symbol'] for a in data['assets']}
    data['changes'] = [c for c in data['changes'] if c['symbol'] in allowed]
    if selected['filters']['strategy'] in STRATEGIES:
        data['changes'] = [c for c in data['changes'] if c['strategy_id'] == selected['filters']['strategy']]
    data['pager'] = paginate(data['changes'], int(request.query_params.get('page', 1)), selected['pager']['size'])
    data['candidates'] = {s:select(data['assets'],strategy=s,match='matched',sort='score',private=private) for s in STRATEGIES}
    data['counts'] = {s:len(rows) for s,rows in data['candidates'].items()}
    return render(request,'dashboard.html',data)


@router.get('/daily')
def latest_daily(request: Request, scope: str | None = None, batch: str | None = None):
    from lib import db
    from lib.queries import publication
    from lib.daily_reports import report_id
    private = bool(session(request))
    scope = scope or ('personal' if private else 'all')
    if scope not in ('all','following','held','personal'):
        raise HTTPException(422,'Invalid scope')
    if scope != 'all' and not private:
        raise HTTPException(401,'Administrator login required')
    with db.get_db() as conn:
        pub = publication(conn,batch)
        exists = conn.execute('SELECT 1 FROM report_snapshots WHERE report_id=?', (report_id(pub['batch_id'],scope),)).fetchone() if pub else None
    if not pub:
        return render(request,'report.html',{'body':'尚无日报 / No report yet','target_date':None,'created_at':None})
    if not exists:
        return render(request,'report.html',{'body':'此范围尚无历史快照；下次数据更新后生成。 / This scope has no snapshot yet; one will be created on the next data update.','target_date':pub['target_date'],'created_at':None})
    return RedirectResponse('/reports/'+report_id(pub['batch_id'],scope)+'?lang='+('en' if request.query_params.get('lang')=='en' else 'zh'),status_code=303)


@router.get('/reports/{report_id}')
def report(request: Request,report_id: str):
    private = bool(session(request))
    data=report_data(report_id,private)
    if data is None:
        raise HTTPException(404)
    from lib import db
    from lib.daily_reports import load_document
    from web.lists import listing
    with db.get_db() as conn:
        document = load_document(conn, report_id)
        if document:
            scope = document['scope']
            neighbors = {}
            for name,op,direction in [('previous','<','DESC'),('next','>','ASC')]:
                row=conn.execute(f'''SELECT r.report_id FROM report_snapshots r JOIN report_documents d USING(report_id)
                    WHERE d.scope=? AND r.target_date{op}? ORDER BY r.target_date {direction},r.created_at DESC LIMIT 1''',
                    (scope,data['target_date'])).fetchone()
                neighbors[name] = row[0] if row else None
            data.update(document=document, neighbors=neighbors)
            data.update(listing(request, document['assets'], None, private and not data['public']))
    return render(request,'report.html',data)
