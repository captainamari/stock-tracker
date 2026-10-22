"""Every public read pins one published batch. No provider or evaluator imports."""
import json
from lib import db
from lib.jobs import DEPENDENCIES
from lib.prices import read_prices

STRATEGIES = ('stage2_us','contraction_us','bottom_fisher_us','checklist_us')


def publication(conn, batch=None):
    if batch is None:
        pointer = conn.execute('SELECT batch_id FROM current_publication WHERE id=1').fetchone()
        batch = pointer[0] if pointer else None
    row = conn.execute('SELECT * FROM publications WHERE batch_id=?',(batch,)).fetchone()
    return dict(row) if row else None


def permitted(conn, symbol, asset=None, private=False):
    if private:
        return True
    current = conn.execute('SELECT is_public,enabled FROM watchlist WHERE symbol=?',(symbol,)).fetchone()
    public = bool(current and current['is_public'] and current['enabled']) if current else symbol in DEPENDENCIES
    return public and (asset is None or bool(asset['is_public']))


def dashboard_data(batch=None, private=False, include_pending=False):
    with db.get_db() as conn:
        conn.execute('BEGIN')
        pub = publication(conn,batch)
        assets, results, changes = [], [], []
        if pub:
            assets = [dict(r) for r in conn.execute('SELECT * FROM run_assets WHERE run_id=? ORDER BY symbol',(pub['batch_id'],)) if permitted(conn,r['symbol'],r,private)]
            allowed = {a['symbol'] for a in assets}
            stocks = {a['symbol'] for a in assets if a['role']=='stock'}
            results = [dict(r) for r in conn.execute('SELECT * FROM daily_results WHERE run_id=?',(pub['batch_id'],)) if r['symbol'] in allowed]
            changes = [dict(r) for r in conn.execute('SELECT * FROM candidate_changes WHERE batch_id=?',(pub['batch_id'],)) if r['symbol'] in stocks]
        by_symbol = {a['symbol']:a for a in assets}
        # Pending configurations remain visible independently of strategy matches.
        if batch is None or include_pending:
            from lib.jobs import dependencies
            for r in dependencies(conn):
                if r['symbol'] not in by_symbol and permitted(conn,r['symbol'],private=private):
                    if not private and not r['is_public']:
                        continue
                    assets.append(dict(symbol=r['symbol'],name=r['name'],sector=r['sector'],status='pending',actual_date=None,price=None,change_1d=None,role='benchmark' if r['symbol'] in DEPENDENCIES else 'stock'))
        grouped = {}
        for r in results:
            payload = json.loads(r.pop('payload'))
            grouped.setdefault(r['symbol'],{})[r['strategy_id']] = {**payload,**r}
        for a in assets:
            a['strategies'] = grouped.get(a['symbol'],{})
            if private:
                labels = conn.execute('SELECT is_followed,is_held FROM watchlist WHERE symbol=?', (a['symbol'],)).fetchone()
                a.update(is_followed=bool(labels and labels[0]), is_held=bool(labels and labels[1]))
            if not private:
                for key in ('reason','yf_ticker','input_revision','run_id'):
                    a.pop(key,None)
        pulse = json.loads(pub['pulse']) if pub else None
        counts = {s:sum(a['strategies'].get(s,{}).get('is_signal') is True or a['strategies'].get(s,{}).get('is_signal') == 1 for a in assets if a['role']=='stock') for s in STRATEGIES}
        return dict(batch_id=pub['batch_id'] if pub else None, latest_date=pub['target_date'] if pub else None,
                    published_at=pub['published_at'] if pub else None, assets=assets,pulse=pulse,counts=counts,changes=changes,
                    missing_count=sum(a['status']!='ok' for a in assets),failed_count=sum(a['status']=='failed' for a in assets))


def ticker_data(symbol,batch=None,private=False):
    with db.get_db() as conn:
        conn.execute('BEGIN')
        pub = publication(conn,batch)
        row = conn.execute('SELECT * FROM run_assets WHERE run_id=? AND symbol=?',(pub['batch_id'],symbol)).fetchone() if pub else None
        current = conn.execute('SELECT * FROM watchlist WHERE symbol=?',(symbol,)).fetchone()
        if not (row or current) or not permitted(conn,symbol,row,private):
            return None
        asset = dict(row) if row else {**dict(current),'status':'pending','actual_date':None,'price':None,'change_1d':None,'role':'stock'}
        if private:
            asset.update(is_followed=bool(current and current['is_followed']), is_held=bool(current and current['is_held']))
        else:
            for field in ('is_followed','is_held','is_personal'):
                asset.pop(field, None)
        prices = read_prices(conn,symbol,pub['target_date'],row['input_revision'] or 0) if row else []
        results = {}
        if row:
            for r in conn.execute('SELECT * FROM daily_results WHERE run_id=? AND symbol=?',(pub['batch_id'],symbol)):
                results[r['strategy_id']] = {**json.loads(r['payload']), 'actual_date':r['actual_date'],'rule_version':r['rule_version']}
        if not private:
            for k in ('reason','yf_ticker','input_revision','run_id'):
                asset.pop(k,None)
        return dict(batch_id=pub['batch_id'] if pub else None,target_date=pub['target_date'] if pub else None,
                    asset=asset,prices=prices,strategies=results)


def report_data(report_id, private=False):
    with db.get_db() as conn:
        row = conn.execute('SELECT report_id,batch_id,target_date,kind,body,created_at,public FROM report_snapshots WHERE report_id=?',(report_id,)).fetchone()
        if not row:
            return None
        if not row['public']:
            return dict(row) if private else None
        # Historical text remains immutable; revoke public access if any formerly
        # public constituent has since been made private.
        hidden = conn.execute('''SELECT 1 FROM run_assets a JOIN watchlist w USING(symbol)
            WHERE a.run_id=? AND a.is_public=1 AND w.is_public=0 LIMIT 1''',(row['batch_id'],)).fetchone()
        return None if hidden else dict(row)
