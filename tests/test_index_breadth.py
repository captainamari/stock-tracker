import json
from lib import db, universe
from lib.breadth import aggregate
from lib.strategy_service import compute_pulse
from tests.fixtures import seed_watchlist, update


def bind_snapshot(monkeypatch, members):
    original=universe.prepare_run
    def prepare(job,fetcher=None):
        original(job,fetcher)
        payload=dict(indices={key:dict(members=[dict(symbol=s) for s in symbols]) for key,symbols in members.items()})
        with db.get_db() as conn:
            conn.execute('INSERT OR IGNORE INTO universe_snapshots VALUES (?,?,?)',('synthetic-union','2026-10-20T00:00:00+00:00',json.dumps(payload)))
            conn.execute('UPDATE update_runs SET universe_snapshot=? WHERE run_id=?',('synthetic-union',job['run_id']))
    monkeypatch.setattr(universe,'prepare_run',prepare)


def test_frozen_union_deduplicates_aliases_counts_missing_and_ignores_privacy(database,monkeypatch):
    seed_watchlist(('AAA','BRK.B','GOOG','GOOGL','DISABLED','EXTRA'))
    with db.get_db() as conn:
        conn.execute("UPDATE watchlist SET enabled=0 WHERE symbol='DISABLED'")
        conn.execute("UPDATE watchlist SET yf_ticker='BRK-B' WHERE symbol='BRK.B'")
        conn.execute("UPDATE watchlist SET is_public=0 WHERE symbol='GOOG'")
    bind_snapshot(monkeypatch,dict(sp500=['AAA','BRK.B','GOOG','DISABLED','MISSING','SPY'],nasdaq100=['AAA','BRK-B','GOOG','GOOGL','QQQ','IWM','^VIX']))
    run=update()
    with db.get_db() as conn:
        b=aggregate(conn,run)
        assert b['total']==6 and b['analyzed']==4 and b['missing']==2
        assert b['coverage']==4/6*100 and set(b['denominators'].values())=={4}
        pulse=compute_pulse(conn,dict(run_id=run,target_date='2026-10-20'))
        assert pulse['regime'] is None and pulse['status']=='insufficient_data'
        saved=json.loads(conn.execute('SELECT pulse FROM publications WHERE batch_id=?',(run,)).fetchone()[0])
        assert saved['breadth']==b
        conn.execute('UPDATE watchlist SET is_public=1-is_public,is_followed=1,is_held=1')
        conn.execute('DELETE FROM index_memberships')
        assert aggregate(conn,run)==b
        assert json.loads(conn.execute('SELECT pulse FROM publications WHERE batch_id=?',(run,)).fetchone()[0])==saved


def test_all_missing_no_false_zero_and_metric_specific_denominators(database,monkeypatch):
    seed_watchlist(('AAA',))
    bind_snapshot(monkeypatch,dict(sp500=['AAA','ABSENT'],nasdaq100=['AAA']))
    run=update()
    with db.get_db() as conn:
        row=conn.execute("SELECT payload FROM daily_results WHERE run_id=? AND symbol='AAA' AND strategy_id='stage2_us'",(run,)).fetchone()
        value=json.loads(row[0]);value['metrics']['chg_5d']=None
        conn.execute("UPDATE daily_results SET payload=? WHERE run_id=? AND symbol='AAA' AND strategy_id='stage2_us'",(json.dumps(value),run))
        b=aggregate(conn,run)
        assert b['analyzed']==1 and b['denominators']['up_5d_pct']==0
        assert b['up_5d_pct'] is None and b['breadth_score'] is None
        conn.execute("UPDATE run_assets SET status='failed' WHERE run_id=?",(run,))
        b=aggregate(conn,run)
        assert b['total']==2 and b['analyzed']==0 and b['missing']==2
        assert b['stage2_pct'] is None and b['above_sma50_pct'] is None
        pulse=compute_pulse(conn,dict(run_id=run,target_date='2026-10-20'))
        assert pulse['regime'] is None and pulse['score'] is None


def test_old_report_scope_label_is_not_rewritten(client):
    seed_watchlist();run=update()
    with db.get_db() as conn:
        row=conn.execute('SELECT pulse FROM publications WHERE batch_id=?',(run,)).fetchone()
        pulse=json.loads(row[0]);pulse['breadth'].pop('version');pulse['breadth'].pop('scope')
        conn.execute('UPDATE publications SET pulse=? WHERE batch_id=?',(json.dumps(pulse),run))
    page=client.get('/reports/'+run+'?lang=en').text
    assert 'Legacy public watchlist breadth' in page and 'S&amp;P 500' not in page
