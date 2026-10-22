"""Private user labels are independent of index membership and public visibility."""
from lib import db


def update(symbols, followed=None, held=None):
    symbols = sorted(set(symbols))
    if not symbols or len(symbols) > 100:
        raise ValueError('Select 1–100 symbols')
    if followed is None and held is None:
        raise ValueError('Choose a label to update')
    with db.get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        placeholders = ','.join('?' for _ in symbols)
        rows = conn.execute(f'SELECT symbol FROM watchlist WHERE symbol IN ({placeholders})', symbols).fetchall()
        if len(rows) != len(symbols):
            raise ValueError('Unknown symbol')
        fields, values = [], []
        for field, value in [('is_followed', followed), ('is_held', held)]:
            if value is not None:
                fields.append(field+'=?')
                values.append(int(value))
        # Retain deliberately followed/held index members if they leave the index.
        # Clearing labels never silently disables collection or deletes history.
        if followed or held:
            fields.append('is_personal=1')
        conn.execute(f'UPDATE watchlist SET {",".join(fields)} WHERE symbol IN ({placeholders})', values+symbols)
