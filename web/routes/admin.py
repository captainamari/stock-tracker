from fastapi import APIRouter,Request
from lib import db
from web.auth import session
from web.deps import render

router=APIRouter()


@router.get('/admin')
def admin_page(request:Request):
    if not session(request):
        return render(request,'admin.html')
    with db.get_db() as conn:
        runs=[dict(r) for r in conn.execute('SELECT run_id,target_date,status,stage,completed,total,created_at FROM update_runs ORDER BY created_at DESC LIMIT 20')]
        from lib.universe import summary, active_clause
        universe = summary(conn)
        watchlist=[dict(r) for r in conn.execute(f'''SELECT w.symbol,w.name,w.enabled,w.is_public,w.is_personal,
            ({active_clause()}) active, (SELECT GROUP_CONCAT(index_id, ', ') FROM index_memberships m WHERE m.symbol=w.symbol) indices
            FROM watchlist w ORDER BY symbol''')]
    return render(request,'admin.html',dict(runs=runs,watchlist=watchlist,universe=universe))
