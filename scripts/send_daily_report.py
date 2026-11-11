"""Send one owner digest directly; never collect, calculate, migrate or drain other tasks."""
import argparse
import json
import os
import sqlite3
from lib import digest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=os.getenv('DAILY_REPORT_CONFIG'), help='Private JSON path (or DAILY_REPORT_CONFIG)')
    parser.add_argument('--date', help='Target XNYS trading date; default latest closed session')
    parser.add_argument('--dry-run', action='store_true', help='Validate/render only; no database writes or hub calls')
    parser.add_argument('--manual-reissue', action='store_true', help='Explicit additional delivery; requires --date; original stays frozen')
    args = parser.parse_args(argv)
    if not args.config:
        parser.error('--config or DAILY_REPORT_CONFIG is required')
    if args.manual_reissue and not args.date:
        parser.error('--manual-reissue requires --date and intentionally permits another delivery')
    try:
        target = digest.target_date(args.date)
        with digest.readonly() as conn:
            config = digest.load_config(args.config, conn)
            if args.dry_run:
                batch, body, _ = digest.preview(conn, config, target)
                print(body)
                return 0 if batch else 3
        result = digest.send(config, target, manual=args.manual_reissue)
        print(json.dumps(result))
        if result['status'] not in ('sent','resolved'):
            return 4 if result['status'] in ('unknown','partial','sending') else 5
        return 3 if result['readiness']=='missing' else 0
    except (ValueError, OSError) as exc:
        # Configuration errors are bounded; never print hub tokens or raw request errors.
        print('Configuration/file error: '+(str(exc) if isinstance(exc, ValueError) else type(exc).__name__))
        return 2
    except sqlite3.Error:
        print('Database unavailable or schema not migrated. Check STOCK_DB and run python -m lib.cli init.')
        return 6


if __name__ == '__main__':
    raise SystemExit(main())
