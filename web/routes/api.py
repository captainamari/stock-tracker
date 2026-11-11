"""Public HTTP has read-only routes only. Administration is server CLI only."""
from fastapi import APIRouter, Request, HTTPException
from lib import db
from lib.guest import collection, public_value
from lib.symbols import normalize, resolve
router = APIRouter(tags=['public'])


def selection(symbols):
    if symbols is None:
        return None
    if len(symbols) > 1600:
        raise HTTPException(422, 'Too many symbols')
    try:
        return normalize(symbols.split(',') if symbols else [])
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get('/assets')
@router.get('/dashboard')
def assets(request: Request, batch: str | None = None, symbols: str | None = None,
           report_id: str | None = None, page: int = 1, size: int = 20, scope: str = 'all',
           search: str = '', strategy: str = '', match: str = 'all', sort: str = 'order'):
    if scope != 'all':
        raise HTTPException(404, 'Private scopes are not available')
    try:
        return collection(batch, selection(symbols), report_id, page=page,size=size,search=search[:100],strategy=strategy,match=match,sort=sort)
    except LookupError:
        raise HTTPException(404) from None


@router.get('/tickers/check/{symbol}')
def check(symbol: str):
    chosen = selection(symbol)
    result = collection(symbols=chosen)
    return {'symbol': chosen[0], 'covered': bool(result['items'] and result['items'][0]['status']!='unavailable')}


@router.get('/ticker/{symbol}')
def ticker(request: Request, symbol: str, batch: str | None = None):
    from lib.queries import ticker_data
    with db.get_db() as conn:
        symbol = resolve(conn, selection(symbol))[0]
    value = ticker_data(symbol,batch)
    if value is None:
        raise HTTPException(404)
    if value['asset'].get('role')=='benchmark':
        value['strategies'] = {k:v for k,v in value['strategies'].items() if k=='technical'}
    return public_value(value)


@router.get('/ticker/{symbol}/prices.csv')
def export(request: Request, symbol: str, batch: str | None = None, start: str | None = None, end: str | None = None):
    import csv
    import io
    from fastapi.responses import Response
    value = ticker(request, symbol, batch)
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['date','open','high','low','close','volume','source','basis','quality'])
    for r in value['prices']:
        if (not start or r['date'] >= start) and (not end or r['date'] <= end):
            writer.writerow([r.get(k) for k in ('date','open','high','low','close','volume','source','basis','quality')])
    return Response(output.getvalue(), media_type='text/csv', headers={'Content-Disposition':'attachment; filename="prices.csv"'})
