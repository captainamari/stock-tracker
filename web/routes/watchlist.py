from fastapi import APIRouter, Request
from lib.queries import dashboard_data
from web.auth import session
from web.deps import render

router=APIRouter()


@router.get('/watchlist')
def watchlist_page(request: Request,batch: str | None=None):
    from lib import db
    from lib.universe import summary
    private = bool(session(request))
    data = dashboard_data(batch, private)
    with db.get_db() as conn:
        data['universe'] = summary(conn)
    if not private:
        data['universe'].pop('error', None)
    return render(request,'watchlist.html',data)
