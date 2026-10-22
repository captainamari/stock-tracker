"""Compatibility calendar helper; old subprocess/Telegram pipeline is retired."""
from lib.market_calendar import is_trading_day as _is_trading_day
from lib.settings import utcnow

def is_trading_day(date=None):
    value=date or utcnow()
    return _is_trading_day(value.date().isoformat() if hasattr(value,'date') else str(value))

if __name__=='__main__':
    raise SystemExit('Retired: use python -m lib.cli scheduler and independent worker/notify-worker. See DEPLOY.md.')
