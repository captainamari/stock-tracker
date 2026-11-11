"""Server-only administration. No public HTTP management or notification worker."""
import argparse
import json
import time
from pathlib import Path
from lib import db


def output(value):
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('init',help='Apply additive migrations and seed missing collection metadata')
    seed=sub.add_parser('seed-watchlist',help='Explicitly import collection configuration, never prices')
    seed.add_argument('--file'); seed.add_argument('--explicit',action='store_true')
    for name in ('worker','scheduler'):
        sub.add_parser(name).add_argument('--once',action='store_true')
    sub.add_parser('backup').add_argument('destination')
    restore=sub.add_parser('restore');restore.add_argument('source');restore.add_argument('destination')
    sub.add_parser('assets',help='Inspect collection configuration and default-browser visibility conflicts')
    add=sub.add_parser('asset-add',help='Add/retain an extra collection asset; private unless explicitly public')
    add.add_argument('symbol');add.add_argument('--name');add.add_argument('--yahoo');add.add_argument('--public',action='store_true')
    for action in ('asset-public','asset-private','asset-disable','asset-enable'):
        sub.add_parser(action).add_argument('symbol')
    sub.add_parser('update',help='Queue a market update, without notifications')
    run=sub.add_parser('runs',help='Inspect durable market tasks');run.add_argument('--id')
    schedule=sub.add_parser('update-schedule',help='Inspect/set market update time in America/New_York')
    schedule.add_argument('--time')
    export=sub.add_parser('export-digest',help='Export old owner labels without sending or enabling a task')
    export.add_argument('--scope',choices=('following','held','personal'),default='personal')
    export.add_argument('--output',required=True);export.add_argument('--profile',default='owner');export.add_argument('--channel',default='trading')
    sub.add_parser('deliveries',help='Inspect existing deliveries; never sends').add_argument('--id',help='Show per-part attempts, safe error code and receipt request ID')
    for action in ('delivery-confirm','delivery-retry'):
        sub.add_parser(action,help='Acknowledge without resend' if action=='delivery-confirm' else 'Explicitly retry and send only this delivery').add_argument('id')
    args=parser.parse_args(argv)
    if args.command in ('backup','restore'):
        from lib.backup import backup,restore
        print(backup(args.destination) if args.command=='backup' else restore(args.source,args.destination));return
    if args.command=='init':
        from lib.migrations import migrate
        from lib.universe import initialize
        migrate();initialize()
        print('Migration complete. Run assets to inspect default visibility conflicts.');return
    if args.command=='seed-watchlist':
        from lib.config import sync_watchlist
        sync_watchlist(config_path=Path(args.file) if args.file else None,explicit=args.explicit);return
    if args.command in ('worker','scheduler'):
        if args.command=='worker':
            from lib.worker import run_once as function
        else:
            from lib.schedule import tick as function
        while True:
            try:
                result=function()
                if result: output(result)
            except Exception:
                if args.once: raise
                import logging
                logging.exception('Service iteration failed')
            if args.once:return
            time.sleep(30 if args.command=='scheduler' else 2)
    elif args.command=='assets':
        from lib.jobs import dependencies
        from lib.symbols import DEFAULT_WATCHLIST
        from lib.queries import permitted
        with db.get_db() as conn:
            rows=[dict(r) for r in conn.execute('SELECT * FROM watchlist ORDER BY symbol')]
            conflicts=[s for s in DEFAULT_WATCHLIST['symbols'] if not permitted(conn,s)]
            output(dict(configuration=rows,collection=[r['symbol'] for r in dependencies(conn)],default_conflicts=conflicts,
                explicit_commands=['python -m lib.cli asset-public '+s for s in conflicts]))
    elif args.command.startswith('asset-'):
        from lib.symbols import normalize,resolve
        from lib.settings import stamp
        symbol=normalize([args.symbol])[0]
        with db.get_db() as conn:
            symbol=resolve(conn,[symbol])[0]
            if args.command=='asset-add':
                yahoo=normalize([args.yahoo or symbol])[0]
                conn.execute('''INSERT INTO watchlist(symbol,name,yf_ticker,is_public,is_personal,enabled,is_followed,updated_at)
                    VALUES (?,?,?,?,1,1,1,?) ON CONFLICT(symbol) DO UPDATE SET is_personal=1,enabled=1,updated_at=excluded.updated_at''',
                    (symbol,args.name or symbol,yahoo,int(args.public),stamp()))
                print('Saved. Existing visibility/mapping preserved; use asset-public explicitly if required.')
            else:
                field,value={'asset-public':('is_public',1),'asset-private':('is_public',0),'asset-enable':('enabled',1),'asset-disable':('enabled',0)}[args.command]
                changed=conn.execute(f'UPDATE watchlist SET {field}=?,updated_at=? WHERE symbol=?',(value,stamp(),symbol)).rowcount
                if not changed:raise ValueError('Unknown configured asset; add it first')
    elif args.command=='update':
        from lib.pipeline import request_update
        print(request_update('manual'))
    elif args.command=='runs':
        from lib.jobs import get_run
        with db.get_db() as conn:
            output(get_run(args.id) if args.id else [dict(r) for r in conn.execute('SELECT * FROM update_runs ORDER BY created_at DESC LIMIT 100')])
    elif args.command=='update-schedule':
        from lib.schedule import get_schedule,save_schedule
        value=get_schedule()
        if args.time:value['update_time']=args.time;save_schedule(value)
        output(dict(update_time=value['update_time'],timezone='America/New_York',notification_scheduler='disabled; use independent timer'))
    elif args.command=='export-digest':
        from lib.listing import in_scope
        from lib.symbols import normalize
        with db.get_db() as conn:
            symbols=normalize([r['symbol'] for r in conn.execute('SELECT * FROM watchlist ORDER BY symbol') if in_scope(dict(r),args.scope)])
        value=dict(version=1,profile=args.profile,symbols=symbols,channel=args.channel,mode='compact')
        # Refuse overwriting an existing private configuration.
        with open(args.output,'x',encoding='utf-8') as file:json.dump(value,file,ensure_ascii=False,indent=2)
        print('Exported without enabling or sending. Inspect and validate using send_daily_report --dry-run.')
    elif args.command=='deliveries':
        from lib.delivery import list_deliveries,inspect
        output(inspect(args.id) if args.id else list_deliveries(limit=-1))
    elif args.command=='delivery-confirm':
        from lib.delivery import resolve
        resolve(args.id);print('Acknowledged without resend')
    elif args.command=='delivery-retry':
        from lib.delivery import retry,run_once,list_deliveries
        retry(args.id);run_once(delivery_id=args.id)
        output([r for r in list_deliveries(limit=-1) if r['delivery_id']==args.id])


if __name__=='__main__':
    try: main()
    except (ValueError,OSError) as exc: raise SystemExit(str(exc))
