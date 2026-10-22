from fastapi import APIRouter,Request,HTTPException
from lib import db
from web.auth import session
from web.deps import render

router=APIRouter()


@router.get('/admin')
def admin_page(request:Request):
    if not session(request):
        return render(request,'admin.html')
    with db.get_db() as conn:
        runs=[dict(r) for r in conn.execute('SELECT run_id,target_date,status,stage,completed,total,created_at FROM update_runs ORDER BY created_at DESC,run_id DESC')]
        from lib.universe import summary, active_clause
        universe = summary(conn)
        watchlist=[dict(r) for r in conn.execute(f'''SELECT w.symbol,w.name,w.enabled,w.is_public,w.is_personal,w.is_followed,w.is_held,
            ({active_clause()}) active, (SELECT GROUP_CONCAT(index_id, ', ') FROM index_memberships m WHERE m.symbol=w.symbol) indices
            FROM watchlist w ORDER BY symbol''')]
    from web.lists import listing
    from lib.listing import paginate
    data=listing(request,watchlist,private=True)
    try:
        run_pager=paginate(runs,int(request.query_params.get('run_page',1)))
    except ValueError:
        raise HTTPException(422,'Invalid history page')
    return render(request,'admin.html',{**data,'runs':run_pager['items'],'run_pager':run_pager,'universe':universe,'management':True})
