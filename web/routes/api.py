"""Read-only published data; configuration writes never fetch or compute."""
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from lib import db
from lib.pipeline import validate_ticker, request_update
from lib.jobs import get_run
from lib.settings import stamp
from web.auth import require_admin, session

router = APIRouter(tags=['api'])


class AddTickerRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    symbol: str
    name: str = Field(default='', max_length=100)
    sector: str = Field(default='', max_length=80)
    yf_ticker: str | None = None
    is_public: bool = False

    @field_validator('symbol', 'yf_ticker')
    @classmethod
    def symbol_valid(cls, value):
        if value is None:
            return value
        result = validate_ticker(value)
        if not result['valid']:
            raise ValueError('Invalid ticker syntax')
        return result['symbol']


@router.get('/tickers/check/{symbol}')
def check(symbol: str):
    return validate_ticker(symbol)


@router.post('/tickers')
def add_ticker(payload: AddTickerRequest):
    with db.get_db() as conn:
        conn.execute('''INSERT INTO watchlist(symbol,name,sector,yf_ticker,is_public,enabled,updated_at)
          VALUES (?,?,?,?,?,1,?) ON CONFLICT(symbol) DO UPDATE SET name=excluded.name,sector=excluded.sector,
          yf_ticker=excluded.yf_ticker,is_public=excluded.is_public,enabled=1,updated_at=excluded.updated_at''',
          (payload.symbol, payload.name or payload.symbol, payload.sector, payload.yf_ticker or payload.symbol.replace('.', '-'), int(payload.is_public), stamp()))
    return {'symbol': payload.symbol, 'status': 'pending', 'message': 'Saved; use Update data to collect market data.'}


@router.delete('/tickers/{symbol}')
def disable(symbol: str):
    db.set_ticker_enabled(symbol.upper(), False)
    return {'status': 'disabled'}


class Visibility(BaseModel):
    model_config = ConfigDict(extra='forbid')
    is_public: bool


@router.patch('/tickers/{symbol}/visibility')
def visibility(symbol: str, payload: Visibility):
    with db.get_db() as conn:
        conn.execute('UPDATE watchlist SET is_public=?,updated_at=? WHERE symbol=?', (int(payload.is_public), stamp(), symbol.upper()))
    return {'status':'saved'}


@router.post('/prices/refresh')
def refresh():
    return {'run_id': request_update('manual')}


@router.get('/runs/{run_id}')
def run_status(request: Request, run_id: str):
    require_admin(request)
    result = get_run(run_id)
    if not result:
        raise HTTPException(404)
    from lib.provider_guard import status
    result['provider'] = status()
    return result


@router.get('/dashboard')
def dashboard(request: Request, batch: str | None = None):
    from lib.queries import dashboard_data
    return dashboard_data(batch, private=bool(session(request)))


@router.get('/ticker/{symbol}')
def ticker(request: Request, symbol: str, batch: str | None = None):
    from lib.queries import ticker_data
    value = ticker_data(symbol.upper(), batch, private=bool(session(request)))
    if value is None:
        raise HTTPException(404)
    return value


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
