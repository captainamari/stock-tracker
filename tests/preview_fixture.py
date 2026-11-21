"""Explicit isolated SYNTHETIC browser fixture. Refuses an existing DB."""
import os
from pathlib import Path
from datetime import datetime,timezone

if __name__=='__main__':
    os.environ['INDEX_UNIVERSE_ENABLED']='false'
    path=Path(os.environ['STOCK_DB'])
    if path.exists():
        raise SystemExit('Use a NEW isolated database; never mix test prices with real prices')
    from lib.migrations import migrate
    from lib import db
    from tests.fixtures import bars,seed_watchlist,update
    migrate()
    from lib.symbols import DEFAULT_WATCHLIST
    seed_watchlist(tuple(DEFAULT_WATCHLIST['symbols'])+('SYNOK','SYNBUY','SHORT','MISSING','STALE','PRIVATE'))
    with db.get_db() as conn:
        conn.execute("UPDATE watchlist SET is_public=0 WHERE symbol='PRIVATE'")
    def source(symbol,start,target):
        if symbol=='SYNBUY':
            from tests.test_buy import bars as buy_bars
            # One fixed history across both publications: shifting a synthetic
            # window would omit its oldest bar during a revision backfill.
            return buy_bars('2026-10-20').loc[:target]
        if symbol=='MISSING':
            raise RuntimeError('Isolated browser fault injection')
        result=bars(symbol,start,target,short=symbol=='SHORT')
        return result.iloc[:-1] if symbol=='STALE' else result
    run=update(source,now=datetime(2026,10,20,8,tzinfo=timezone.utc))
    run=update(source,now=datetime(2026,10,21,8,tzinfo=timezone.utc))
    with db.get_db() as conn:
        signal=conn.execute("SELECT status,is_signal FROM daily_results WHERE run_id=? AND symbol='SYNBUY' AND strategy_id='buy_us'",(run,)).fetchone()
        assert signal['status']=='ok' and signal['is_signal']==1, 'BUY browser fixture must have a verified signal'
    db.upsert_watchlist([{'symbol':'PENDING','name':'SYNTHETIC pending'}])
    with db.get_db() as conn:
        conn.execute("UPDATE watchlist SET is_public=1 WHERE symbol='PENDING'")
    seed_watchlist(tuple(f'S{i:03}' for i in range(65)))
    print(run)
