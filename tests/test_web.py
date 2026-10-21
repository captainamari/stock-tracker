from concurrent.futures import ThreadPoolExecutor
from lib import db
from tests.fixtures import seed_watchlist,update


def test_all_gets_read_only_no_download_or_calculation(client,monkeypatch):
    seed_watchlist()
    run=update()
    def prohibited(*args,**kwargs):
        raise AssertionError('GET caused download or calculation')
    monkeypatch.setattr('lib.prices.download',prohibited)
    monkeypatch.setattr('lib.strategy_service.calculate_run',prohibited)
    monkeypatch.setattr('lib.technical_analysis.compute_technical_indicators',prohibited)
    import yfinance
    monkeypatch.setattr(yfinance,'Ticker',prohibited)
    with db.get_db() as conn:
        before=conn.execute('SELECT COUNT(*) FROM update_runs').fetchone()[0]
    for path in ('/','/watchlist','/ticker/AAA','/api/dashboard','/api/ticker/AAA','/api/tickers/check/NEW','/api/ticker/AAA/prices.csv',f'/reports/{run}'):
        response=client.get(path)
        assert response.status_code==200,(path,response.text[:100])
    with db.get_db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM update_runs').fetchone()[0]==before
    page=client.get('/?lang=en').text
    assert 'Contraction candidates' in page
    assert client.get('/api/dashboard').json()['batch_id']==run


def test_privacy_and_language_isolation(client):
    seed_watchlist(('AAA','SECRET'))
    with db.get_db() as conn:
        conn.execute("UPDATE watchlist SET is_public=0 WHERE symbol='SECRET'")
    update()
    assert 'SECRET' not in client.get('/api/dashboard').text
    assert client.get('/api/ticker/SECRET').status_code==404
    for path in ('/api/runs/anything',):
        assert client.get(path).status_code==401
    assert 'notification-settings' not in client.get('/admin').text
    def read(lang):
        page=client.get('/?lang='+lang).text
        assert ('市场概览' in page) == (lang=='zh')
        assert ('Market overview' in page) == (lang=='en')
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(read,['en','zh']*5))


def test_old_legacy_signals_never_appear_as_latest(client):
    seed_watchlist()
    update()
    db.save_strategy_result(symbol='OLD',date_str='2020-01-01',strategy='vcp',is_signal=True,
                            score=100,passed=6,total=6,conditions={},condition_details={},metrics={})
    from web.routes.dashboard import _build_dashboard_data
    data=_build_dashboard_data()
    assert all(a['symbol']!='OLD' for a in data['assets'])
    assert data['latest_date']=='2026-10-20'


def test_pending_detail_is_readable_before_first_update(client):
    seed_watchlist()
    assert client.get('/ticker/AAA').status_code==200
    data=client.get('/api/ticker/AAA').json()
    assert data['asset']['status']=='pending'
    assert data['asset']['price'] is None
