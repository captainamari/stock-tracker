from fastapi import APIRouter, Request, HTTPException
from lib.queries import dashboard_data, report_data
from web.auth import session
from web.deps import render

router = APIRouter()


def _build_dashboard_data(batch=None,private=False):
    return dashboard_data(batch,private)


@router.get('/')
def dashboard(request: Request,batch: str | None=None):
    return render(request,'dashboard.html',_build_dashboard_data(batch,bool(session(request))))


@router.get('/reports/{report_id}')
def report(request: Request,report_id: str):
    data=report_data(report_id)
    if data is None:
        raise HTTPException(404)
    return render(request,'report.html',data)
