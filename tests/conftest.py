import pytest
from lib import db
from lib.migrations import migrate


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = tmp_path / 'isolated-synthetic.db'
    monkeypatch.setattr(db, 'DB_PATH', path)
    monkeypatch.setenv('STOCK_DB', str(path))
    monkeypatch.setenv('COOKIE_SECURE', 'false')
    migrate()
    return path


@pytest.fixture
def client(database):
    from fastapi.testclient import TestClient
    from web.app import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin(client):
    from web.auth import initialize_admin
    initialize_admin('isolated-test-password')
    csrf = client.get('/api/auth/session').json()['csrf']
    response = client.post('/api/auth/login', json={'password': 'isolated-test-password'}, headers={'x-csrf-token': csrf})
    assert response.status_code == 200
    client.headers['x-csrf-token'] = response.json()['csrf']
    return client
