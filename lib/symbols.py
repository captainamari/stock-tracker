"""Bounded symbol selections, independent of collection and owner preferences."""
import json
import re
from pathlib import Path
from lib.universe import yahoo_symbol

MAX_SYMBOLS = 100
DEFAULT_WATCHLIST = json.loads((Path(__file__).resolve().parents[1] / 'config/browser-watchlist.json').read_text())


def normalize(values):
    if not isinstance(values, list) or len(values) > MAX_SYMBOLS:
        raise ValueError('Expected at most 100 symbols')
    result = []
    for value in values:
        if not isinstance(value, str) or len(value) > 15 or not re.fullmatch(r'[A-Z^][A-Z0-9.^-]{0,14}', value.strip().upper()):
            raise ValueError('Invalid symbol (maximum 15 characters)')
        value = yahoo_symbol(value)
        if value not in result:
            result.append(value)
    return result


def resolve(conn, values):
    """Resolve aliases to the same canonical row used by collection."""
    from lib.jobs import dependencies
    mapping = {}
    for row in conn.execute('SELECT * FROM watchlist ORDER BY is_personal DESC,is_public,symbol'):
        mapping.setdefault(yahoo_symbol(row['symbol']), row['symbol'])
        mapping.setdefault(yahoo_symbol(row['yf_ticker'] or row['symbol']), row['symbol'])
    for row in dependencies(conn):
        mapping[yahoo_symbol(row['symbol'])] = row['symbol']
        mapping[yahoo_symbol(row['yf_ticker'])] = row['symbol']
    return list(dict.fromkeys(mapping.get(s, s) for s in normalize(values)))
