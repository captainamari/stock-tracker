"""Explicit isolated SYNTHETIC browser fixture. Refuses an existing DB."""
import os
from pathlib import Path
from datetime import datetime,timezone

if __name__=='__main__':
    path=Path(os.environ['STOCK_DB'])
    if path.exists():
        raise SystemExit('Use a NEW isolated database; never mix test prices with real prices')
    from lib.migrations import migrate
    from lib import db
    from web.auth import initialize_admin
    from tests.fixtures import bars,seed_watchlist,update
    migrate()
    seed_watchlist(('SYNOK','SHORT','MISSING','STALE','PRIVATE'))
    with db.get_db() as conn:
        conn.execute("UPDATE watchlist SET is_public=0 WHERE symbol='PRIVATE'")
    def source(symbol,start,target):
        if symbol=='MISSING':
            raise RuntimeError('Isolated browser fault injection')
        result=bars(symbol,start,target,short=symbol=='SHORT')
        return result.iloc[:-1] if symbol=='STALE' else result
    run=update(source,now=datetime(2026,10,20,8,tzinfo=timezone.utc))
    db.upsert_watchlist([{'symbol':'PENDING','name':'SYNTHETIC pending'}])
    with db.get_db() as conn:
        conn.execute("UPDATE watchlist SET is_public=1 WHERE symbol='PENDING'")
    initialize_admin('isolated-browser-validation')
    print(run)
