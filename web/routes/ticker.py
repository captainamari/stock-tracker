from fastapi import APIRouter,Request,HTTPException
from lib.queries import ticker_data
from web.auth import session
from web.deps import render

router=APIRouter()


@router.get('/ticker/{symbol}')
def ticker_detail(request: Request,symbol: str,batch: str | None=None):
    data=ticker_data(symbol.upper(),batch,bool(session(request)))
    if data is None:
        raise HTTPException(404)
    from urllib.parse import urlsplit
    back = request.query_params.get('return_to','/watchlist')
    parsed = urlsplit(back)
    data['return_to'] = back if not parsed.netloc and not parsed.scheme and (parsed.path in ('/watchlist','/','/admin') or parsed.path.startswith('/reports/')) else '/watchlist'
    return render(request,'ticker_detail.html',data)
