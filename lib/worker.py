"""Independent process; every persistent mutation checks ownership of the lease."""
import threading
import time
from lib import db, jobs
from lib.prices import collect_asset, download
from lib.settings import stamp


def execute(job, provider=download):
    # Keep one idle connection for the run: closing the last SQLite connection
    # forces a WAL checkpoint. This connection holds no transaction or lock.
    keepalive = db.get_connection()
    stop = threading.Event()
    errors = []
    def pulse():
        while not stop.wait(15):
            try:
                jobs.heartbeat(job)
            except Exception as exc:
                errors.append(exc)
                return
    thread = threading.Thread(target=pulse, daemon=True)
    thread.start()
    try:
        with db.get_db() as conn:
            assets = [dict(r) for r in conn.execute('SELECT * FROM run_assets WHERE run_id=? ORDER BY role,symbol', (job['run_id'],))]
        for i, asset in enumerate(assets):
            if errors:
                raise errors[0]
            collect_asset(job, asset, provider)
            jobs.progress(job, 'collect', i+1)
        jobs.progress(job, 'calculate')
        from lib.strategy_service import calculate_run
        from lib.publication import publish
        calculate_run(job)
        publish(job)
    except jobs.LostLease:
        raise
    except Exception as exc:
        with db.get_db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            jobs.fence(conn, job)
            conn.execute("UPDATE update_runs SET status='failed',error=?,finished_at=? WHERE run_id=?", (type(exc).__name__, stamp(), job['run_id']))
        raise
    finally:
        stop.set()
        thread.join(timeout=2)
        keepalive.close()


def run_once(provider=download):
    job = jobs.claim()
    if job:
        execute(job, provider)
        return job['run_id']
    return None


def run_forever():
    import logging
    while True:
        try:
            run_once()
        except Exception:
            logging.exception('Update worker failed; task retained for inspection')
        time.sleep(2)
