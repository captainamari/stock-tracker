"""Behavioral regression for the compact public projection and safe return links."""
from urllib.parse import urlencode
from bs4 import BeautifulSoup
from lib import db
from tests.fixtures import seed_watchlist, update


def test_complete_scope_counts_sort_and_provenance(client):
    seed_watchlist(tuple(f'S{i:03}' for i in range(24)))
    batch = update()
    scope = client.get('/api/assets', params={'batch': batch, 'size': 100}).json()
    filtered = client.get('/api/assets', params={'batch': batch, 'search': 'S023', 'strategy': 'stage2_us', 'sort': 'score'}).json()
    assert filtered['counts'] == scope['counts']
    assert filtered['selected_count'] == scope['selected_count']
    assert filtered['pulse'] == scope['pulse']
    assert filtered['total'] == 1
    assert filtered['comparison_missing'] > 0 and filtered['comparison_count'] == 0
    selected = client.get('/api/assets', params={'batch': batch, 'symbols': 'S023,S000'}).json()
    assert [a['symbol'] for a in selected['items']] == ['S023', 'S000']
    assert selected['pulse'] == scope['pulse']
    assert selected['selected_count'] == 2
    assert selected['items'][0]['price_source'] == 'synthetic_test'
    assert selected['items'][0]['strategies']['stage2_us']['score'] is not None
    all_sorted = client.get('/api/assets', params={'batch': batch, 'sort': 'price', 'size': 100}).json()['items']
    pages = []
    for page in (1, 2):
        pages += client.get('/api/assets', params={'batch': batch, 'sort': 'price', 'size': 20, 'page': page}).json()['items']
    assert [a['symbol'] for a in pages] == [a['symbol'] for a in all_sorted]


def test_return_links_allow_only_internal_list_routes(client):
    seed_watchlist()
    for target, label in [('/discover?search=AAA&page=2','Back to Discover'),('/watchlist?sort=price','Back to my watchlist'),('/reports/abc?all=1','Back to report'),('/daily?batch=abc','Back to report'),('/','Back to overview')]:
        html=BeautifulSoup(client.get('/ticker/AAA?'+urlencode({'lang':'en','return_to':target})).text,'html.parser')
        back=html.select_one('.heading > a')
        assert back['href']==target and label in back.text
    for target in ['https://example.com','//example.com','/\\example.com','/%5cexample.com','/reports/../../admin','/discover\x00','/reports//example.com','http://[invalid']:
        response=client.get('/ticker/AAA',params={'return_to':target})
        assert response.status_code==200
        assert BeautifulSoup(response.text,'html.parser').select_one('.heading > a')['href']=='/watchlist'


def test_navigation_and_script_order(client):
    for path in ('/', '/watchlist','/discover'):
        soup=BeautifulSoup(client.get(path).text,'html.parser')
        assert soup.select_one('.primary-nav [aria-current=page]')['href'].split('?')[0]==path
        scripts=[s.get('src','') for s in soup.select('script[src]')]
        assert 'watchlist.js' in scripts[0] and 'stock-table.js' in scripts[1] and 'main.js' in scripts[2]
    assert 'Favorite order' not in client.get('/discover?lang=en').text


def test_frozen_report_provenance_does_not_follow_new_revisions(client):
    seed_watchlist()
    batch=update()
    before=client.get('/api/assets',params={'report_id':batch,'symbols':'AAA'}).json()
    # Existing revision is immutable; add a later revision like a subsequent source repair.
    with db.get_db() as conn:
        row=dict(conn.execute("SELECT * FROM price_revisions WHERE symbol='AAA' ORDER BY id DESC LIMIT 1").fetchone())
        row.pop('id');row['source']='future_source';row['close']+=100
        columns=','.join(row);marks=','.join('?' for _ in row)
        conn.execute(f'INSERT INTO price_revisions ({columns}) VALUES ({marks})',tuple(row.values()))
    after=client.get('/api/assets',params={'report_id':batch,'symbols':'AAA'}).json()
    assert after==before
