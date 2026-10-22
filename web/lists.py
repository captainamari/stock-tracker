from fastapi import HTTPException
from lib.listing import select, paginate, controls


def listing(request, rows, batch=None, private=False):
    q = request.query_params
    scope = q.get('scope', 'all')
    if scope != 'all' and not private:
        raise HTTPException(401, 'Administrator login required')
    try:
        page, size = int(q.get('page', 1)), int(q.get('size', 20))
    except ValueError:
        raise HTTPException(422, 'Invalid page or size')
    filters = dict(scope=scope, search=q.get('search', '')[:100], strategy=q.get('strategy', ''),
                   match=q.get('match', 'all'), sort=q.get('sort', 'symbol'))
    selected = select(rows, private=private, **filters)
    return dict(filters=filters, pager=paginate(selected, page, size), page_url=controls(request, batch),
                selected_assets=selected, return_to=controls(request, batch)())
