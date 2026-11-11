import pytest
from lib import db
from lib.migrations import migrate


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = tmp_path / 'isolated-synthetic.db'
    monkeypatch.setattr(db, 'DB_PATH', path)
    monkeypatch.setenv('STOCK_DB', str(path))
    monkeypatch.setenv('COOKIE_SECURE', 'false')
    monkeypatch.setenv('INDEX_UNIVERSE_ENABLED', 'false')  # Small deterministic fixtures; universe tests opt in.
    migrate()
    return path


@pytest.fixture
def client(database):
    from fastapi.testclient import TestClient
    from web.app import app
    with TestClient(app) as c:
        yield c
