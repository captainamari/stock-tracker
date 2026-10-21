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
        watchlist=[dict(r) for r in conn.execute('SELECT symbol,name,enabled,is_public FROM watchlist ORDER BY symbol')]
    return render(request,'admin.html',dict(runs=runs,watchlist=watchlist))
