import re
from fastapi import APIRouter,Request,HTTPException
from web.deps import render

router=APIRouter()


@router.get('/ticker/{symbol}')
def ticker_detail(request: Request,symbol: str,batch: str | None=None):
    from web.routes.api import ticker
    data=ticker(request,symbol,batch)
    if data is None:
        raise HTTPException(404)
    from urllib.parse import urlsplit, unquote
    back = request.query_params.get('return_to','/watchlist')
    decoded = unquote(back)
    try:
        parsed = urlsplit(decoded)
        safe = (not parsed.netloc and not parsed.scheme and '\\' not in decoded
                and not any(ord(c) < 32 for c in decoded)
                and (parsed.path in ('/watchlist','/','/discover','/daily')
                     or re.fullmatch(r'/reports/[a-zA-Z0-9-]+', parsed.path)))
    except ValueError:
        safe = False
    data['return_to'] = back if safe else '/watchlist'
    path = urlsplit(data['return_to']).path
    data['active_path'] = '/daily' if path.startswith('/reports/') else path
    labels = ('Back to Discover', '返回发现股票') if path=='/discover' else ('Back to report','返回日报') if path=='/daily' or path.startswith('/reports/') else ('Back to overview','返回概览') if path=='/' else ('Back to my watchlist','返回我的关注')
    from web.i18n import get_language_from_request
    data['return_label'] = labels[1 if get_language_from_request(request)=='zh' else 0]
    return render(request,'ticker_detail.html',data)
