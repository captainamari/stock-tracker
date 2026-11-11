from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse
from lib import db
from lib.guest import summary
from lib.queries import dashboard_data, report_data, publication
from web.deps import render
router=APIRouter()


def _build_dashboard_data(batch=None,private=False):
    return dashboard_data(batch,False)


@router.get('/')
def dashboard(request: Request,batch: str | None=None):
    return render(request,'guest.html',dict(**summary(batch),view='overview'))


@router.get('/daily')
def latest_daily(request: Request, scope: str='all', batch: str | None=None):
    if scope!='all':
        raise HTTPException(404)
    with db.get_db() as conn:
        pub=publication(conn,batch)
    if not pub:
        return render(request,'guest.html',dict(**summary(batch),view='report',report_id=''))
    return RedirectResponse('/reports/'+pub['batch_id']+'?lang='+('en' if request.query_params.get('lang')=='en' else 'zh'),status_code=303)


@router.get('/reports/{report_id}')
def report(request: Request,report_id: str):
    from lib.daily_reports import load_document
    with db.get_db() as conn:
        row=conn.execute('SELECT * FROM report_snapshots WHERE report_id=? AND public=1',(report_id,)).fetchone()
        if not row:
            raise HTTPException(404)
        document=load_document(conn,report_id)
        neighbors={}
        for key,op,direction in [('previous','<','DESC'),('next','>','ASC')]:
            other=conn.execute(f"SELECT report_id FROM report_snapshots WHERE public=1 AND target_date{op}? ORDER BY target_date {direction},created_at DESC LIMIT 1",(row['target_date'],)).fetchone()
            neighbors[key]=other[0] if other else None
    if document:
        return render(request,'guest.html',dict(**summary(row['batch_id']),view='report',report_id=report_id,neighbors=neighbors))
    # Legacy text cannot be selectively filtered: explicit full-public view only.
    data=report_data(report_id)
    if data is None:
        raise HTTPException(404)
    return render(request,'legacy_report.html',data)
