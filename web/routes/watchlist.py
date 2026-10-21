from fastapi import APIRouter, Request
from lib.queries import dashboard_data
from web.auth import session
from web.deps import render

router=APIRouter()


@router.get('/watchlist')
def watchlist_page(request: Request,batch: str | None=None):
    return render(request,'watchlist.html',dashboard_data(batch,bool(session(request))))
