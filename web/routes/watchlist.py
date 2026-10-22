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
    data = dashboard_data(batch, private, include_pending=True)
    from web.lists import listing
    data.update(listing(request, data['assets'], data['batch_id'], private))
    with db.get_db() as conn:
        data['universe'] = summary(conn)
    if not private:
        data['universe'].pop('error', None)
    return render(request,'watchlist.html',data)
