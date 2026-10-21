"""Operational CLI. Market updates originate only in scheduler or admin API."""
import argparse
import getpass
import time
from lib.migrations import migrate


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('init')
    sub.add_parser('init-admin')
    seed=sub.add_parser('seed-watchlist')
    seed.add_argument('--file')
    seed.add_argument('--explicit',action='store_true',help='Explicitly import configuration into an existing watchlist')
    for name in ('worker','notify-worker','scheduler'):
        sub.add_parser(name).add_argument('--once',action='store_true')
    sub.add_parser('backup').add_argument('destination')
    restore=sub.add_parser('restore')
    restore.add_argument('source')
    restore.add_argument('destination')
    args=parser.parse_args()
    if args.command=='backup':
        from lib.backup import backup
        print(backup(args.destination))
        return
    if args.command=='restore':
        from lib.backup import restore
        print(restore(args.source,args.destination))
        return
    migrate()
    if args.command=='init-admin':
        from web.auth import initialize_admin
        password=getpass.getpass('Administrator password (12+ characters): ')
        if password!=getpass.getpass('Repeat password: '):
            raise SystemExit('Passwords do not match')
        initialize_admin(password)
    elif args.command=='seed-watchlist':
        from lib.config import sync_watchlist
        from pathlib import Path
        sync_watchlist(config_path=Path(args.file) if args.file else None,explicit=args.explicit)
    elif args.command in ('worker','notify-worker','scheduler'):
        from lib.worker import run_once as update
        from lib.delivery import run_once as notify
        from lib.schedule import tick
        function={'worker':update,'notify-worker':notify,'scheduler':tick}[args.command]
        while True:
            try:
                result=function()
                if result:
                    print(result,flush=True)
            except Exception:
                if args.once:
                    raise
                import logging
                logging.exception('Service iteration failed')
            if args.once:
                return
            time.sleep(30 if args.command=='scheduler' else 2)


if __name__=='__main__':
    main()
