"""Publish current rules against the latest frozen inputs, without downloads/sends."""
import threading
import time
import uuid
from lib import db, jobs
from lib.settings import settings, stamp


def latest():
    from lib.strategy_service import calculate_run
    from lib.publication import publish
    with db.get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute("SELECT 1 FROM update_runs WHERE status IN ('queued','running')").fetchone():
            raise ValueError('An update is active; wait before recalculating')
        source = conn.execute('''SELECT r.* FROM update_runs r JOIN current_publication p
            ON p.batch_id=r.run_id WHERE p.id=1''').fetchone()
        if not source:
            raise ValueError('No published batch to recalculate')
        run_id, owner, now = uuid.uuid4().hex, uuid.uuid4().hex, time.time()
        conn.execute('''INSERT INTO update_runs(run_id,trigger,target_date,status,created_at,total,
            owner,attempt,started_at,heartbeat,lease_until,stage,universe_prepared,universe_snapshot,universe_status)
            VALUES (?,'manual',?,'running',?,?,?,1,?,?,?,'calculate',1,?,?)''',
            (run_id,source['target_date'],stamp(),source['total'],owner,stamp(),now,
             now+settings().lease_seconds,source['universe_snapshot'],source['universe_status']))
        # Copy exactly the frozen asset metadata and input revision watermarks.
        columns=[row['name'] for row in conn.execute('PRAGMA table_info(run_assets)') if row['name']!='run_id']
        fields=','.join(columns)
        conn.execute(f'INSERT INTO run_assets(run_id,{fields}) SELECT ?,{fields} FROM run_assets WHERE run_id=?',
                     (run_id,source['run_id']))
        job=dict(conn.execute('SELECT * FROM update_runs WHERE run_id=?',(run_id,)).fetchone())
    stop=threading.Event()
    def heartbeat():
        while not stop.wait(15):
            try: jobs.heartbeat(job)
            except jobs.LostLease: return
    thread=threading.Thread(target=heartbeat,daemon=True)
    thread.start()
    keepalive=db.get_connection()
    try:
        calculate_run(job)
        publish(job)
    except Exception as exc:
        with db.get_db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            jobs.fence(conn,job)
            conn.execute("UPDATE update_runs SET status='failed',error=?,finished_at=? WHERE run_id=?",
                         (type(exc).__name__,stamp(),run_id))
        raise
    finally:
        stop.set();thread.join(timeout=2);keepalive.close()
    return dict(batch_id=run_id,source_batch=source['run_id'],target_date=source['target_date'],
                downloaded=False,notifications_sent=False)
