"""Isolated acceptance: no production DB, provider network or real notification."""
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import pytest
from lib import db, digest, delivery
from lib.cli import main as cli
from lib.symbols import DEFAULT_WATCHLIST
from tests.fixtures import seed_watchlist, update


def config_file(tmp_path, **changes):
    value=dict(version=1,profile='owner',symbols=['AAA'],channel='trading',mode='compact')
    value.update(changes)
    path=tmp_path/'owner.json';path.write_text(json.dumps(value),encoding='utf-8')
    return path,value


class FakeHub:
    def __init__(self,status='sent'):self.calls=[];self.status=status
    def send(self,item,part,total):
        self.calls.append((item,part,total))
        return self.status,{'request_id':'synthetic'},None


def test_http_surface_and_selection_privacy(client):
    seed_watchlist(('AAA','SECRET','BBB'))
    with db.get_db() as conn:conn.execute("UPDATE watchlist SET is_public=0,is_held=1 WHERE symbol='SECRET'")
    run=update()
    for method,path in [('post','/api/tickers'),('delete','/api/tickers/AAA'),('patch','/api/tickers/AAA/visibility'),
        ('patch','/api/interests'),('post','/api/prices/refresh'),('put','/api/settings'),
        ('post','/api/notifications/test'),('post','/api/notifications/x/retry'),('post','/api/notifications/x/resolve')]:
        assert client.request(method,path,json={}).status_code in (404,405)
    for scope in ('following','held','personal'):
        assert client.get('/api/assets',params={'scope':scope}).status_code==404
        assert client.get('/api/assets',params={'report_id':run+'-'+scope}).status_code==404
        assert client.get('/reports/'+run+'-'+scope).status_code==404
    data=client.get('/api/assets',params={'symbols':' aaa,SECRET,AAA,BBB','batch':run}).json()
    assert [a['symbol'] for a in data['items']]==['AAA','SECRET','BBB']
    assert data['items'][1]['status']=='unavailable' and data['items'][1]['price'] is None
    for field in ('is_held','is_followed','input_revision','reason','yf_ticker'):
        assert field not in json.dumps(data)
    assert client.get('/api/assets?symbols=').json()['total']==0
    for symbols in ('A'*16,','.join(['AAA']*101),'<script>'):
        assert client.get('/api/assets',params={'symbols':symbols}).status_code==422
    with db.get_db() as conn:conn.execute("UPDATE watchlist SET is_public=0 WHERE symbol='AAA'")
    for params in ({'batch':run,'symbols':'AAA'},{'report_id':run,'symbols':'AAA'}):
        a=client.get('/api/assets',params=params).json()['items'][0]
        assert a['status']=='unavailable' and a['strategies']=={}
    assert client.get('/api/ticker/AAA',params={'batch':run}).status_code==404


def test_batch_pinning_counts_pending_and_benchmarks(client):
    seed_watchlist(('AAA','BBB'));first=update();second=update()
    for route in ('/','/watchlist','/discover'):
        page=client.get(route,params={'batch':first,'lang':'en'})
        assert page.status_code==200 and f'data-batch="{first}"' in page.text
        assert 'data-symbol="AAA"' not in page.text  # No all-market first paint.
    data=client.get('/api/assets',params={'batch':first,'symbols':'AAA,SPY,QQQ'}).json()
    assert data['batch_id']==first and second!=first
    assert all(x['symbol']=='AAA' for group in data['candidates'].values() for x in group)
    assert all(x['symbol']=='AAA' for x in data['changes'])
    assert all(set(a['strategies'])<={'technical'} for a in data['items'] if a['symbol']!='AAA')
    seed_watchlist(('PENDING',))
    assert client.get('/api/assets?symbols=PENDING').json()['items'][0]['status']=='pending'
    assert client.get('/api/assets?symbols=AAA&search=ZZZ').json()['total']==0
    assert client.get('/api/assets').headers['cache-control']=='no-store'


def test_dry_run_is_readonly_and_uses_real_entry(database,tmp_path,monkeypatch,capsys):
    from scripts.send_daily_report import main
    seed_watchlist();update();path,_=config_file(tmp_path)
    def forbidden(*args,**kwargs):raise AssertionError('forbidden side effect')
    monkeypatch.setattr('lib.delivery.HubClient.send',forbidden)
    monkeypatch.setattr('lib.pipeline.request_update',forbidden)
    monkeypatch.setattr('lib.universe.fetch_snapshot',forbidden)
    monkeypatch.setattr('lib.strategy_service.calculate_run',forbidden)
    monkeypatch.setattr('lib.prices.download',forbidden)
    with sqlite3.connect(database) as conn:before=list(conn.iterdump())
    assert main(['--config',str(path),'--date','2026-10-20','--dry-run'])==0
    assert 'AAA' in capsys.readouterr().out
    with sqlite3.connect(database) as conn:assert list(conn.iterdump())==before
    assert main(['--config',str(path),'--date','2026-10-21','--dry-run'])==3


def test_concurrent_freeze_and_config_changes_cannot_bypass_dedupe(database,tmp_path):
    seed_watchlist(('AAA','BBB'));run=update();_,config=config_file(tmp_path)
    with ThreadPoolExecutor(max_workers=6) as pool:
        ids=list(pool.map(lambda _:digest.freeze(config,'2026-10-20'),range(12)))
    assert len(set(ids))==1
    with db.get_db() as conn:
        before=[tuple(r) for r in conn.execute('SELECT * FROM delivery_parts')]
        assert conn.execute('SELECT batch_id FROM digest_runs').fetchone()[0]==run
    update()
    assert digest.freeze({**config,'symbols':['BBB','AAA'],'mode':'standard'},'2026-10-20')==ids[0]
    with db.get_db() as conn:assert [tuple(r) for r in conn.execute('SELECT * FROM delivery_parts')]==before
    hub=FakeHub()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _:digest.send(config,'2026-10-20',hub),range(4)))
    assert len({p['part'] for _,p,_ in hub.calls})==len(hub.calls)
    assert digest.send(config,'2026-10-20',hub)['status']=='sent'


def test_sender_does_not_drain_legacy_queue_or_compute(database,tmp_path,monkeypatch):
    seed_watchlist();update();_,config=config_file(tmp_path)
    legacy=delivery.queue_test()
    def forbidden(*args,**kwargs):raise AssertionError('digest must only read saved results')
    monkeypatch.setattr('lib.prices.download',forbidden)
    monkeypatch.setattr('lib.strategy_service.calculate_run',forbidden)
    monkeypatch.setattr('lib.universe.fetch_snapshot',forbidden)
    monkeypatch.setattr('lib.pipeline.request_update',forbidden)
    hub=FakeHub();result=digest.send(config,'2026-10-20',hub)
    assert result['status']=='sent' and hub.calls
    assert all(item['delivery_id']!=legacy for item,_,_ in hub.calls)
    assert next(r for r in delivery.list_deliveries() if r['delivery_id']==legacy)['status']=='queued'


def test_missing_report_frozen_without_automatic_late_resend(database,tmp_path):
    seed_watchlist();_,config=config_file(tmp_path)
    hub=FakeHub();first=digest.send(config,'2026-10-20',hub)
    assert first['readiness']=='missing' and 'Delayed or missing' in hub.calls[0][1]['body']
    calls=len(hub.calls);update()
    assert digest.send(config,'2026-10-20',hub)==first and len(hub.calls)==calls
    manual=digest.send(config,'2026-10-20',hub,manual=True)
    assert manual['delivery_id']!=first['delivery_id'] and manual['readiness']=='ready'


def test_single_missing_symbol_retained_and_config_validation(database,tmp_path):
    seed_watchlist();update();seed_watchlist(('PENDING',))
    path,config=config_file(tmp_path,symbols=['AAA','PENDING','AAA','SPY'])
    with digest.readonly() as conn:
        loaded=digest.load_config(path,conn)
        assert loaded['symbols']==['AAA','PENDING','SPY']
        _,body,doc=digest.preview(conn,loaded,'2026-10-20')
        assert 'PENDING' in body and doc['missing']==1 and '/reports/' not in body
    for changes in ({'symbols':[]},{'symbols':['UNKNOWN']},{'version':True},{'version':2},{'symbols':['X'*16]},
        {'mode':'html'},{'channel':'token@secret'},{'profile':'random space'},{'symbols':'AAA'},{'extra':1}):
        path,_=config_file(tmp_path,**changes)
        with digest.readonly() as conn,pytest.raises(ValueError):digest.load_config(path,conn)


@pytest.mark.parametrize('instant,target',[
    ('2026-10-23T21:00:00+00:00','2026-10-23'),('2026-10-24T10:00:00+00:00','2026-10-23'),
    ('2026-10-26T10:00:00+00:00','2026-10-23'),('2026-12-25T11:00:00+00:00','2026-12-24'),
    ('2026-03-09T10:00:00+00:00','2026-03-06'),('2026-11-02T11:00:00+00:00','2026-10-30'),
    ('2026-11-27T17:59:00+00:00','2026-11-25'),('2026-11-27T18:01:00+00:00','2026-11-27')])
def test_digest_calendar(instant,target):
    assert digest.target_date(now=datetime.fromisoformat(instant))==target


@pytest.mark.parametrize('value',['2026-12-25','2026-10-24','bad','20261020'])
def test_explicit_date_rejects_holidays_and_bad_format(value):
    with pytest.raises(ValueError):digest.target_date(value)


def test_cli_export_management_and_no_sends(database,tmp_path,capsys):
    cli(['asset-add','AAA','--public']);cli(['asset-add','SECRET'])
    cli(['asset-disable','AAA']);cli(['asset-enable','AAA']);cli(['asset-private','AAA']);cli(['asset-public','AAA'])
    path=tmp_path/'private.json';cli(['export-digest','--output',str(path)])
    assert json.loads(path.read_text())['symbols']==['AAA','SECRET']
    with pytest.raises(FileExistsError):cli(['export-digest','--output',str(path)])
    cli(['update-schedule','--time','03:30']);cli(['assets']);cli(['runs']);cli(['deliveries'])
    assert delivery.list_deliveries()==[]
    cli(['update'])
    with db.get_db() as conn:assert conn.execute('SELECT COUNT(*) FROM update_runs').fetchone()[0]==1


def test_digest_fault_does_not_block_publication_or_web(client,tmp_path):
    seed_watchlist();update();_,config=config_file(tmp_path)
    result=digest.send(config,'2026-10-20',FakeHub('unknown'))
    assert result['status']=='unknown'
    with pytest.raises(ValueError):delivery.retry(result['delivery_id'])
    assert digest.send(config,'2026-10-20',FakeHub())['status']=='unknown'
    delivery.resolve(result['delivery_id'])
    run=update()
    assert client.get('/api/assets?symbols=AAA').json()['batch_id']==run


def test_migration_preserves_old_snapshots_delivery_and_private_defaults(database,monkeypatch):
    from lib.migrations import migrate
    from lib.universe import initialize
    seed_watchlist(('AAPL',));run=update();item=delivery.queue_test()
    with db.get_db() as conn:
        conn.execute("UPDATE watchlist SET is_public=0 WHERE symbol='AAPL'")
        conn.execute('DROP TABLE digest_runs')
        conn.execute('ALTER TABLE update_runs DROP COLUMN universe_status')
        conn.execute("DELETE FROM schema_migrations WHERE version='008_independent_digest.sql'")
        old={table:[tuple(r) for r in conn.execute('SELECT * FROM '+table)] for table in
             ('stock_prices','price_revisions','report_snapshots','report_documents','deliveries','delivery_parts')}
    migrate();migrate()
    monkeypatch.setenv('INDEX_UNIVERSE_ENABLED','true');initialize()
    with db.get_db() as conn:
        assert not conn.execute("SELECT is_public FROM watchlist WHERE symbol='AAPL'").fetchone()[0]
        for table,rows in old.items():assert rows==[tuple(r) for r in conn.execute('SELECT * FROM '+table)]


def test_real_module_entry_sends_to_local_hub_and_exits(database,tmp_path):
    import os
    import subprocess
    import sys
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    symbols=['AAA','BBB','CCC','DDD','EEE','FFF','GGG','HHH']
    seed_watchlist(tuple(symbols));update()
    path,_=config_file(tmp_path,symbols=symbols,mode='standard')
    calls=[]
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            assert self.path=='/api/v1/notify'
            payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append(payload)
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
            self.wfile.write(json.dumps(dict(request_id='local-test',status='sent',channel='trading',delivered_to=['synthetic'],failed={},skipped=[])).encode())
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    env={**os.environ,'STOCK_DB':str(database),'NOTIFICATION_API_URL':f'http://127.0.0.1:{server.server_port}',
         'NOTIFICATION_API_TOKEN':'synthetic-only-token','NO_PROXY':'127.0.0.1','PYTHONUTF8':'1'}
    command=[sys.executable,'-m','scripts.send_daily_report','--config',str(path),'--date','2026-10-20']
    try:
        result=subprocess.run(command,env=env,capture_output=True,text=True,timeout=60)
        assert result.returncode==0,(result.stdout,result.stderr)
        assert len(calls)>1 and all(r['channel']=='trading' for r in calls)
        assert all(len(r['message'])<=3000 for r in calls)
        assert 'AAA' in ''.join(r['message'] for r in calls) and 'BBB' in ''.join(r['message'] for r in calls)
        n=len(calls)
        repeated=subprocess.run(command,env=env,capture_output=True,text=True,timeout=60)
        assert repeated.returncode==0 and len(calls)==n
        assert 'synthetic-only-token' not in result.stdout+result.stderr
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)


def test_fresh_defaults_are_public_and_private_alias_revokes_history(database,client,monkeypatch):
    from lib.universe import initialize
    from lib.queries import permitted
    monkeypatch.setenv('INDEX_UNIVERSE_ENABLED','true');initialize()
    with db.get_db() as conn:
        assert all(permitted(conn,s) for s in DEFAULT_WATCHLIST['symbols'])
    monkeypatch.setenv('INDEX_UNIVERSE_ENABLED','false')
    seed_watchlist(('BRK.B',))
    with db.get_db() as conn:
        conn.execute("UPDATE watchlist SET enabled=0 WHERE symbol NOT IN ('SPY','QQQ','IWM','VIX')")
        conn.execute("UPDATE watchlist SET enabled=1,yf_ticker='BRK-B' WHERE symbol='BRK.B'")
    run=update()
    assert client.get('/api/ticker/BRK-B',params={'batch':run}).status_code==200
    from lib.queries import report_data
    assert report_data(run) is not None
    db.upsert_watchlist([dict(symbol='PRIVATEALIAS',name='Secret',yf_ticker='BRK-B')])
    assert client.get('/api/ticker/BRK.B',params={'batch':run}).status_code==404
    response=client.get('/api/assets',params={'symbols':'BRK-B','batch':run})
    assert response.json()['items'][0]['symbol']=='BRK-B'
    assert 'PRIVATEALIAS' not in response.text
    # Legacy plain text cannot safely remove a revoked alias; withhold the text.
    with db.get_db() as conn:conn.execute('DELETE FROM report_documents WHERE report_id=?',(run,))
    assert client.get('/reports/'+run).status_code==404


def test_cli_delivery_review_is_explicit_and_preserves_records(database,capsys):
    identifier=delivery.queue_test()
    cli(['deliveries','--id',identifier])
    assert 'attempts' in capsys.readouterr().out
    cli(['delivery-confirm',identifier])
    assert delivery.inspect(identifier)['status']=='resolved'
    assert delivery.inspect(identifier)['parts'][0]['attempts']==0
    with pytest.raises(ValueError):delivery.retry('absent')
    with pytest.raises(ValueError):delivery.resolve('absent')
