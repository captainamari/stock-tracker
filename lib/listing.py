"""Filter and paginate the entire visible collection, with stable tie breaking."""
from math import ceil
from urllib.parse import urlencode

SCOPES = ('all', 'following', 'held', 'personal')
STRATEGIES = ('stage2_us', 'contraction_us', 'bottom_fisher_us', 'checklist_us')
SCORES = dict(zip(STRATEGIES, ('trend_power', 'vcp_score', 'bf_score', 'bc_score')))


def score(result, strategy):
    if not result or result.get('status') != 'ok':
        return None
    return result.get('metrics', {}).get(SCORES.get(strategy))


def in_scope(asset, scope):
    return (scope == 'all' or scope == 'following' and asset.get('is_followed')
            or scope == 'held' and asset.get('is_held')
            or scope == 'personal' and (asset.get('is_followed') or asset.get('is_held')))


def paginate(rows, page=1, size=20):
    size = size if size in (20, 50, 100) else 20
    pages = max(1, ceil(len(rows) / size))
    page = max(1, min(page, pages))
    start = (page - 1) * size
    return dict(items=rows[start:start+size], page=page, size=size, pages=pages,
                total=len(rows), start=start+1 if rows else 0, end=min(start+size, len(rows)))


def select(rows, *, scope='all', search='', strategy='', match='all', sort='symbol', private=False):
    # Never allow public callers to infer personal memberships through filtering.
    scope = scope if private and scope in SCOPES else 'all'
    result = [a for a in rows if in_scope(a, scope)
              and search.casefold() in (a['symbol']+' '+a.get('name', '')).casefold()]
    if match == 'changed':
        result = [a for a in result if any(strategy not in STRATEGIES or c['strategy']==strategy for c in a.get('changes',[]))]
    if strategy in STRATEGIES:
        result = [a for a in result if a.get('role') != 'benchmark']
    if match in ('matched','near'):
        keys = (strategy,) if strategy in STRATEGIES else STRATEGIES
        def matches(asset):
            for key in keys:
                r = asset.get('strategies', {}).get(key, {})
                matched = (r.get('status')=='ok' and r.get('is_signal')) if match=='matched' else near(r,key)
                if matched:
                    return True
            return False
        result = [a for a in result if a.get('role') != 'benchmark' and matches(a)]
    result.sort(key=lambda a: a['symbol'])
    if sort in ('price', 'change', 'score'):
        def value(a):
            return score(a.get('strategies', {}).get(strategy), strategy) if sort == 'score' else a.get('price' if sort == 'price' else 'change_1d')
        result.sort(key=lambda a: (value(a) is None, -(value(a) or 0)))
    return result


def near(result, strategy):
    minimum = {'stage2_us': 5, 'contraction_us': 3, 'bottom_fisher_us': 3, 'checklist_us': 5}
    return (result.get('status') == 'ok' and not result.get('is_signal')
            and result.get('passed', 0) >= minimum.get(strategy, 999))


def controls(request, batch=None):
    params = dict(request.query_params)
    if batch:
        params['batch'] = batch
    def link(**changes):
        return request.url.path + '?' + urlencode({**params, **changes})
    return link
