from concurrent.futures import ThreadPoolExecutor
import threading
import pytest
from lib import db
from lib.pipeline import request_update
from lib.worker import run_once
from lib.queries import dashboard_data,report_data
from tests.fixtures import seed_watchlist,update,bars,NOW


def test_readers_keep_previous_batch_while_new_run_executes(client):
    seed_watchlist()
    first=update()
    original=client.get('/api/ticker/AAA').json()['asset']['price']
    entered=threading.Event()
    release=threading.Event()
    def source(symbol,start,target):
        entered.set()
        assert release.wait(20)
        frame=bars(symbol,start,target)
        frame[['Open','High','Low','Close']]*=.9
        return frame
    second=request_update('manual',NOW)
    with ThreadPoolExecutor(max_workers=1) as pool:
        work=pool.submit(run_once,source)
        try:
            assert entered.wait(20)
            for _ in range(3):
                assert client.get('/api/dashboard').json()['batch_id']==first
                detail=client.get('/api/ticker/AAA').json()
                assert detail['batch_id']==first and detail['asset']['price']==original
                assert client.get('/watchlist').status_code==200
        finally:
            release.set()
        assert work.result(timeout=60)==second
    assert client.get('/api/dashboard').json()['batch_id']==second
    assert client.get('/api/ticker/AAA').json()['asset']['price']!=original


def test_failed_publication_rolls_back_pointer_states_and_report(database,monkeypatch):
    seed_watchlist()
    first=update()
    original=report_data(first)['body']
    with db.get_db() as conn:
        states=[tuple(r) for r in conn.execute('SELECT * FROM candidate_states ORDER BY symbol,strategy_id')]
    def fail(*args):
        raise RuntimeError('Injected report construction failure inside publish transaction')
    monkeypatch.setattr('lib.publication.report_body',fail)
    with pytest.raises(RuntimeError,match='Injected report'):
        update()
    assert dashboard_data()['batch_id']==first
    assert report_data(first)['body']==original
    with db.get_db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM publications').fetchone()[0]==1
        assert conn.execute('SELECT COUNT(*) FROM report_snapshots').fetchone()[0]==1
        assert states==[tuple(r) for r in conn.execute('SELECT * FROM candidate_states ORDER BY symbol,strategy_id')]
        assert conn.execute("SELECT COUNT(*) FROM update_runs WHERE status='failed'").fetchone()[0]==1
