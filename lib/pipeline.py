"""One update entrypoint, shared by the scheduler and administrator endpoint."""
import re
from lib.jobs import enqueue


def validate_ticker(symbol):
    symbol = symbol.strip().upper()
    return {'valid': bool(re.fullmatch(r'[A-Z^][A-Z0-9.^-]{0,14}', symbol)), 'symbol': symbol,
            'validation': 'syntax_only', 'message': 'Market availability is checked by the next update.'}


def request_update(trigger, now=None, conn=None):
    return enqueue(trigger, now=now, conn=conn)
