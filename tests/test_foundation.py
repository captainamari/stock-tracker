import sqlite3
import pytest
from lib import db
from lib.backup import backup, restore
from lib.migrations import migrate


def test_backup_restore_preserves_legacy(database, tmp_path):
    db.upsert_watchlist([{'symbol': 'OLD', 'name': 'Existing'}])
    with db.get_db() as conn:
        conn.execute("INSERT INTO stock_prices(symbol,date,close) VALUES ('OLD','2020-01-02',123)")
    migrate()
    copy = backup(tmp_path / 'backup.db')
    restored = restore(copy, tmp_path / 'restored.db')
    with sqlite3.connect(restored) as conn:
        assert conn.execute('SELECT close,source,quality FROM stock_prices').fetchone() == (123, 'legacy_unknown', 'legacy_unknown')
        assert conn.execute('SELECT is_public FROM watchlist').fetchone() == (0,)
    with pytest.raises(ValueError):
        restore(copy, database)


@pytest.mark.parametrize('method,path', [('post','/api/tickers'), ('delete','/api/tickers/AAA'), ('post','/api/prices/refresh'), ('post','/api/settings'), ('post','/api/notifications/test')])
def test_anonymous_writes_rejected(client, method, path):
    assert getattr(client, method)(path).status_code == 404


def test_old_cookies_do_not_restore_management(client):
    client.cookies.set('session','legacy-session')
    assert client.post('/api/prices/refresh').status_code==404
    assert client.post('/api/auth/logout').status_code==404
    assert client.get('/api/auth/session').status_code==404



def test_login_routes_removed(client):
    assert client.get('/admin').status_code==404
    assert client.post('/api/auth/login',json={'password':'anything'}).status_code==404
    assert '/admin' not in client.get('/').text
