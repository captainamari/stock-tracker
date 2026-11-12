"""Additional real Chromium behavior checks; called by browser_acceptance only."""
import json
from urllib.parse import urlsplit, parse_qs
from playwright.sync_api import expect


def run_compact_checks(browser, base, artifacts):
    context=browser.new_context(viewport={'width':1440,'height':900},accept_downloads=True)
    page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    def ready():expect(page.locator('#guest-results')).to_have_attribute('aria-busy','false')
    def symbols():return page.locator('tr[data-symbol]').evaluate_all('(rows)=>rows.map(r=>r.dataset.symbol)')
    metrics=[]
    for width in (375,390,768,1024,1440,1920):
        page.set_viewport_size({'width':width,'height':900})
        for route in ('/','/watchlist','/discover','/daily','/ticker/AAPL'):
            page.goto(base+route+'?lang=en')
            if route!='/ticker/AAPL':ready()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,route)
            sizes=page.locator('tr[data-symbol]').evaluate_all('rows=>rows.map(r=>({top:r.getBoundingClientRect().top,bottom:r.getBoundingClientRect().bottom,height:r.getBoundingClientRect().height}))')
            visible=sum(r['top']>=0 and r['bottom']<=900 for r in sizes)
            metrics.append(dict(width=width,route=route,visible_rows=visible,row_height=sizes[0]['height'] if sizes else None))
            if width==1440 and route=='/watchlist':
                assert visible>=8,(visible,sizes)
                assert 48<=sizes[0]['height']<=52,sizes[0]
                page.screenshot(path=str(artifacts/'watchlist-desktop.png'))
            if width==1440 and route=='/':
                assert visible>=2,(visible,sizes)
                page.screenshot(path=str(artifacts/'overview-desktop.png'))
            if width==390 and route in ('/watchlist','/ticker/AAPL'):
                page.screenshot(path=str(artifacts/('watchlist-mobile.png' if route=='/watchlist' else 'detail-mobile.png')))
            if route in ('/watchlist','/discover'):
                wrap=page.locator('.table-wrap')
                if width<700:
                    expect(page.locator('#column-preset')).to_have_value('market')
                    page.locator('.advanced-filters summary').press('Enter')
                    expect(page.locator('[name=strategy]')).to_be_visible()
                    page.locator('.advanced-filters summary').press('Enter')
                    page.locator('#column-preset').select_option('strategy')
                    before=page.locator('tbody .col-identity').first.bounding_box()
                    wrap.evaluate('e=>e.scrollLeft=250')
                    after=page.locator('tbody .col-identity').first.bounding_box()
                    assert abs(before['x']-after['x'])<1
                    assert wrap.evaluate('e=>e.scrollLeft>0')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                if route=='/discover':
                    wrap.evaluate('e=>e.scrollTop=150')
                    header=page.locator('.stock-table thead').bounding_box()
                    th=page.locator('.stock-table th.col-identity').bounding_box()
                    assert th['y']>=wrap.bounding_box()['y']-1,(header,th)
    page.set_viewport_size({'width':1440,'height':900})
    page.goto(base+'/discover?lang=en');ready()
    initial_counts=page.locator('#favorite-summary').inner_text()
    assert not page.locator('[value=order]').count()
    assert page.locator('[value=score]').is_disabled()
    page.locator('[name=search]').fill('AAPL');page.locator('[name=search]').press('Enter');ready()
    assert symbols()==['AAPL']
    assert page.locator('#favorite-summary').inner_text()==initial_counts
    page.locator('[name=search]').fill('');page.locator('[name=search]').press('Enter');ready()
    page.locator('th.col-price button').press('Enter');ready()
    expect(page.locator('[name=sort]')).to_have_value('price')
    expect(page.locator('th.col-price')).to_have_attribute('aria-sort','descending')
    page.locator('th.col-stage2_us button').press('Enter');ready()
    expect(page.locator('[name=strategy]')).to_have_value('stage2_us')
    expect(page.locator('[name=sort]')).to_have_value('score')
    page.locator('[name=strategy]').select_option('');ready()
    expect(page.locator('[name=sort]')).to_have_value('symbol')
    page.locator('[name=size]').select_option('50');ready();assert len(symbols())==50
    page.get_by_role('button',name='Next',exact=True).press('Enter');ready()
    assert parse_qs(urlsplit(page.url).query)['page']==['2']
    page.get_by_role('button',name='Previous',exact=True).press('Enter');ready()
    # A favorite action preserves its DOM node, focus and both scroll positions in Discover.
    star=page.get_by_role('button',name='Remove favorite AAPL',exact=True)
    star.focus();before=page.evaluate('({y:scrollY,x:document.querySelector(".table-wrap").scrollLeft})')
    star.press('Space')
    expect(page.get_by_role('button',name='Add favorite AAPL',exact=True)).to_be_focused()
    assert before==page.evaluate('({y:scrollY,x:document.querySelector(".table-wrap").scrollLeft})')
    page.get_by_role('button',name='Add favorite AAPL',exact=True).press('Space')
    # Existing content remains visible during failure; keyboard retry restores results.
    before=symbols()
    page.route('**/api/assets?*',lambda route:route.fulfill(status=503,body='unavailable'))
    page.locator('[name=search]').fill('MSFT');page.locator('[name=search]').press('Enter');ready()
    assert symbols()==before
    expect(page.locator('#retry-list')).to_be_visible()
    page.unroute('**/api/assets?*');page.locator('#retry-list').press('Enter');ready();assert symbols()==['MSFT']
    # Return links preserve the complete query and scroll; Chart ranges only use saved rows.
    page.locator('[name=search]').fill('');page.locator('[name=search]').press('Enter');ready()
    page.locator('.table-wrap').evaluate('e=>e.scrollTop=70')
    page.get_by_role('link',name='GOOG',exact=True).click()
    expect(page.get_by_role('link',name='← Back to Discover',exact=True)).to_be_visible()
    saved=page.locator('#chart-data').text_content();rows=json.loads(saved)
    for label in ('1M','3M','6M','1Y','All'):
        page.get_by_role('button',name=label,exact=True).press('Enter')
        drawn=page.evaluate('Chart.getChart(document.querySelector("#price-chart")).data')
        assert set(drawn['labels']).issubset({r['date'] for r in rows})
        assert len(drawn['labels'])==len(drawn['datasets'][0]['data'])
    page.get_by_role('link',name='← Back to Discover',exact=True).click();ready()
    expect(page.locator('[name=size]')).to_have_value('50')
    assert page.locator('.table-wrap').evaluate('e=>e.scrollTop')>0
    # Edit mode is disabled for filtered lists, and keyboard management opens a real chooser.
    page.goto(base+'/watchlist?lang=en');ready()
    page.locator('.management summary').press('Enter')
    page.once('dialog',lambda d:d.accept())
    page.get_by_role('button',name='Restore defaults',exact=True).click();ready()
    page.locator('.management summary').press('Enter')
    page.get_by_role('button',name='Edit list',exact=True).press('Enter')
    page.get_by_role('button',name='Move down AAPL',exact=True).press('Enter');ready()
    expect(page.get_by_role('button',name='Move down AAPL',exact=True)).to_be_focused()
    assert symbols()[:2]==['MSFT','AAPL']
    page.locator('[name=search]').fill('AAPL');page.locator('[name=search]').press('Enter');ready()
    expect(page.get_by_role('button',name='Edit list',exact=True)).to_be_disabled()
    assert not page.locator('[data-move]').count()
    page.locator('.management summary').press('Enter')
    with page.expect_file_chooser() as chooser:page.get_by_role('button',name='Import favorites',exact=True).press('Enter')
    page.once('dialog',lambda d:d.dismiss())
    chooser.value.set_files({'name':'empty.json','mimeType':'application/json','buffer':b'{"version":1,"symbols":[]}'})
    # Cancel overwrite must preserve the existing list.
    expect(page.locator('#favorites-import')).to_have_value('')
    page.goto(base+'/daily?lang=en');ready()
    expect(page.locator('.primary-nav [aria-current=page]')).to_contain_text('Daily report')
    page.locator('.history-row summary').first.press('Enter')
    expect(page.locator('.history-row details').first).to_have_attribute('open','')
    newest=page.locator('#guest').get_attribute('data-batch')
    page.get_by_role('link',name='← Previous session',exact=True).click();ready()
    batch=page.locator('#guest').get_attribute('data-batch')
    assert batch!=newest
    historical_date=page.locator('#guest').get_attribute('data-date')
    page.get_by_role('link',name='Next session →',exact=True).click();ready()
    assert page.locator('#guest').get_attribute('data-batch')==newest
    page.get_by_role('link',name='← Previous session',exact=True).click();ready()
    first=page.locator('tr[data-symbol] .symbol-link').first
    first.click()
    assert parse_qs(urlsplit(page.url).query)['batch']==[batch]
    expect(page.get_by_role('link',name='← Back to report',exact=True)).to_be_visible()
    assert max(r['date'] for r in json.loads(page.locator('#chart-data').text_content()))<=historical_date
    page.goto(base+'/ticker/SHORT?lang=en')
    page.get_by_role('button',name='1Y',exact=True).click()
    expect(page.locator('#chart-range-status')).to_contain_text('Limited history')
    page.goto(base+'/ticker/PENDING?lang=en')
    assert page.locator('#price-chart').count()==0
    expect(page.locator('.empty')).to_contain_text('No verified prices')
    # Late old responses ignore cancellation deliberately; request generation must still win.
    race=browser.new_context(viewport={'width':1440,'height':900})
    race.add_init_script('''const originalFetch=window.fetch;window.fetch=async (...args)=>{const response=await originalFetch(...args);if(String(args[0]).includes('search=AAPL'))await new Promise(r=>setTimeout(r,600));return response};''')
    rp=race.new_page();rp.goto(base+'/discover?lang=en');expect(rp.locator('#guest-results')).to_have_attribute('aria-busy','false')
    rp.locator('[name=search]').fill('AAPL');rp.locator('[name=search]').press('Enter')
    expect(rp.locator('#guest-results')).to_have_attribute('aria-busy','true')
    assert rp.locator('tr[data-symbol]').count()>1
    rp.locator('[name=search]').fill('MSFT');rp.locator('[name=search]').press('Enter')
    expect(rp.locator('tr[data-symbol]')).to_have_count(1)
    expect(rp.locator('tr[data-symbol]')).to_have_attribute('data-symbol','MSFT')
    rp.wait_for_timeout(700)
    expect(rp.locator('tr[data-symbol]')).to_have_attribute('data-symbol','MSFT')
    # Zero change, long company name and unavailable strategy states through an isolated HTTP fixture.
    def edge(route):
        response=route.fetch();data=response.json()
        for a in data['items']:
            if a['symbol']=='AAPL':a['change_1d']=0;a['name']='SYNTHETIC '+'Very long company name '*15;a['sparkline']=[1,2,None,3,4]
        route.fulfill(response=response,json=data)
    page.route('**/api/assets?*',edge);page.goto(base+'/watchlist?lang=en');ready()
    expect(page.locator('[data-symbol=AAPL] .col-change')).to_have_text('0.00%')
    expect(page.locator('[data-symbol=AAPL] .col-change')).to_have_class('col-change neutral')
    assert len(page.locator('[data-symbol=AAPL] .identity-text small').get_attribute('title'))>200
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.goto(base+'/daily?lang=en');ready()
    path=page.locator('tr[data-symbol=AAPL] + .history-row .sparkline path').get_attribute('d')
    assert path.count('M')==2,path
    assert not errors,errors
    (artifacts/'compact-results.json').write_text(json.dumps({'status':'passed','viewports':metrics,'page_errors':errors,'scenarios':['six widths and five pages','density, horizontal overflow, sticky identity/header','counts before filters, header sort, score strategy, pagination','favorite focus and scroll','failed request retains content and keyboard retry','detail source query and table scroll restoration','saved chart ranges only','edit order and management keyboard/file chooser','report batch and details','out-of-order responses','zero change and long names']},ensure_ascii=False,indent=2),encoding='utf-8')
    race.close();context.close()
