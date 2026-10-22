"""Isolated SYNTHETIC 5,000-stock capacity exercise, never a live provider test."""
import argparse
import json
import os
from pathlib import Path
import platform
import statistics
import threading
import time
import psutil

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,required=True,help='New, nonexistent disposable database')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--stocks',type=int,default=5000)
    args=parser.parse_args()
    if args.database.exists():
        raise SystemExit('Refusing to overwrite an existing database')
    os.environ['STOCK_DB']=str(args.database.resolve())
    os.environ['COOKIE_SECURE']='false'
    os.environ['INDEX_UNIVERSE_ENABLED']='false'  # This database contains only the labeled synthetic pool.
    from lib import db
    from lib.migrations import migrate
    from lib.pipeline import request_update
    from lib.worker import run_once
    from lib.jobs import get_run
    from lib.queries import dashboard_data,ticker_data
    from tests.fixtures import bars,NOW,seed_watchlist
    from fastapi.testclient import TestClient
    from web.app import app
    migrate()
    seed_watchlist(tuple(f'SYN{i:05}' for i in range(args.stocks)))
    frame=bars('SYN00000').iloc[-252:]
    benchmark=bars('SPY').iloc[-252:]
    def provider(symbol,start,target):
        return (benchmark if symbol in ('SPY','QQQ','IWM','^VIX') else frame).copy()
    samples=[]
    errors=[]
    rss=[]
    done=threading.Event()
    process=psutil.Process()
    def readers():
        with TestClient(app) as client:
            while not done.is_set():
                try:
                    started=time.perf_counter()
                    result=client.get('/watchlist')
                    assert result.status_code==200
                    samples.append(time.perf_counter()-started)
                    rss.append(process.memory_info().rss)
                except Exception as exc:
                    errors.append(type(exc).__name__+': '+str(exc))
                done.wait(2)
    run=request_update('manual',NOW)
    thread=threading.Thread(target=readers)
    thread.start()
    start=time.perf_counter()
    try:
        run_once(provider)
    finally:
        done.set()
        thread.join()
    elapsed=time.perf_counter()-start
    assert get_run(run)['status']=='published'
    query={}
    for name,fn in [('dashboard',dashboard_data),('detail',lambda:ticker_data('SYN00000'))]:
        t=time.perf_counter()
        value=fn()
        query[name+'_seconds']=time.perf_counter()-t
        assert value
    with TestClient(app) as client:
        t=time.perf_counter()
        assert client.get('/watchlist').status_code==200
        query['published_watchlist_http_seconds']=time.perf_counter()-t
    with db.get_db() as conn:
        counts={table:conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in ('price_revisions','daily_results','publications')}
        assert counts['daily_results']==(args.stocks+4)*5
        assert counts['price_revisions']==(args.stocks+4)*252
        assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    result=dict(kind='SYNTHETIC, no live provider verification',stocks=args.stocks,bars_per_asset=252,
        seconds=elapsed,peak_sampled_rss_mb=max(rss)/2**20,database_mb=args.database.stat().st_size/2**20,
        concurrent_http_reads=len(samples),read_p95_seconds=sorted(samples)[int((len(samples)-1)*.95)],
        read_max_seconds=max(samples),read_errors=errors,counts=counts,queries=query,
        environment={'os':platform.platform(),'python':platform.python_version(),'cpu_logical':psutil.cpu_count(),'ram_gb':round(psutil.virtual_memory().total/2**30,2)})
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))
    assert not errors

if __name__=='__main__':
    main()
