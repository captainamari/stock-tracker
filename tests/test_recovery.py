"""Actual process interruption, followed by recovery through the real worker."""
import os
from pathlib import Path
import subprocess
import sys
import time
from lib import db,jobs
from lib.pipeline import request_update
from lib.worker import run_once
from tests.fixtures import bars,seed_watchlist,NOW


def test_worker_process_death_then_lease_recovery(database,tmp_path):
    seed_watchlist()
    identifier=request_update('manual',NOW)
    ready=tmp_path/'provider-started'
    program='''
from pathlib import Path
import sys,time,os
from lib.worker import run_once
def source(*args):
    Path(sys.argv[1]).write_text(str(os.getpid()))
    time.sleep(300)
run_once(source)
'''
    child=subprocess.Popen([sys.executable,'-c',program,str(ready)],env=os.environ.copy(),stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        deadline=time.monotonic()+20
        while not ready.exists() and time.monotonic()<deadline:
            if child.poll() is not None:
                raise AssertionError(child.stderr.read().decode())
            time.sleep(.05)
        assert ready.exists()
        assert jobs.get_run(identifier)['status']=='running'
        # Windows venv executables may launch an interpreter child. Terminate
        # the actual worker PID, not only that forwarding launcher.
        import psutil
        psutil.Process(int(ready.read_text())).kill()
        child.wait(timeout=10)
        # Fast-forward only the expired lease; production recovery uses real time.
        with db.get_db() as conn:
            conn.execute('UPDATE update_runs SET lease_until=? WHERE run_id=?',(time.time()-1,identifier))
        assert run_once(bars)==identifier
        assert jobs.get_run(identifier)['status']=='published'
        assert jobs.get_run(identifier)['attempt']==2
        with db.get_db() as conn:
            assert conn.execute('SELECT COUNT(*) FROM publications').fetchone()[0]==1
            assert conn.execute('SELECT COUNT(*) FROM daily_results').fetchone()[0]==25
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
        child.stderr.close()
