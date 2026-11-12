"""Real Chromium acceptance against a NEW synthetic local DB; never production."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import httpx
from playwright.sync_api import sync_playwright, expect


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',required=True)
    parser.add_argument('--artifacts',required=True)
    args=parser.parse_args()
    database=Path(args.database).resolve()
    if database.exists():raise SystemExit('Refusing existing database')
    artifacts=Path(args.artifacts).resolve();artifacts.mkdir(parents=True,exist_ok=True)
    database.parent.mkdir(parents=True,exist_ok=True)
    env={**os.environ,'STOCK_DB':str(database),'INDEX_UNIVERSE_ENABLED':'false','NOTIFICATION_API_TOKEN':'',
         'NOTIFICATION_API_URL':'','PYTHONUTF8':'1','COOKIE_SECURE':'false'}
    subprocess.run([sys.executable,'-m','tests.preview_fixture'],env=env,check=True)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    base=f'http://127.0.0.1:{port}'
    log=open(artifacts/'browser-server.log','w',encoding='utf-8')
    server=subprocess.Popen([sys.executable,'-m','uvicorn','web.app:app','--host','127.0.0.1','--port',str(port)],env=env,stdout=log,stderr=log)
    scenarios=[];errors=[]
    try:
        for _ in range(100):
            try:
                if httpx.get(base,timeout=1).status_code==200:break
            except httpx.HTTPError:pass
            time.sleep(.1)
        else:raise RuntimeError('Local server did not start')
        with sync_playwright() as p:
            browser=p.chromium.launch()
            first=browser.new_context(viewport={'width':1440,'height':900},accept_downloads=True)
            second=browser.new_context()
            page=first.new_page();other=second.new_page()
            for tab in (page,other):tab.on('pageerror',lambda error:errors.append(str(error)))
            def ready(tab):expect(tab.locator('#guest-results')).to_have_attribute('aria-busy','false')
            def symbols(tab):return tab.locator('#guest-results tr[data-symbol]').evaluate_all('(rows)=>rows.map(r=>r.dataset.symbol)')
            page.goto(base+'/?lang=en');other.goto(base+'/watchlist?lang=en');ready(page);ready(other)
            defaults=['AAPL','MSFT','AMZN','GOOG','META','NVDA','TSLA','SPY','QQQ']
            assert symbols(page)==defaults and symbols(other)==defaults
            assert not page.locator('a[href^="/admin"]').count()
            page.screenshot(path=str(artifacts/'overview-desktop.png'),full_page=True)
            scenarios.append('Two independent contexts initialize nine favorites; no admin UI')
            page.get_by_role('button',name='Remove favorite AAPL',exact=True).click();ready(page)
            assert 'AAPL' not in symbols(page) and 'AAPL' in symbols(other)
            page.reload();ready(page);assert 'AAPL' not in symbols(page)
            tab=first.new_page();tab.goto(base+'/watchlist?lang=en');ready(tab)
            assert 'AAPL' not in symbols(tab)
            page.get_by_role('button',name='Remove favorite MSFT',exact=True).click()
            expect(tab.locator('[data-symbol="MSFT"]')).to_have_count(0)
            scenarios.append('Remove, refresh, cross-page and same-origin storage event synchronization')
            page.goto(base+'/discover?lang=en');ready(page)
            page.locator('[name=search]').fill('SYNOK');page.get_by_role('button',name='Apply',exact=True).click();ready(page)
            page.get_by_role('button',name='Add favorite SYNOK',exact=True).click();ready(page)
            page.get_by_role('link',name='SYNOK',exact=True).click()
            expect(page.locator('#price-chart')).to_be_visible()
            page.get_by_role('button',name='Remove favorite SYNOK',exact=True).click()
            expect(page.get_by_role('button',name='Add favorite SYNOK',exact=True)).to_have_attribute('aria-pressed','false')
            scenarios.append('Discover by name/code, favorite, navigate to detail and use chart/favorite control')
            page.goto(base+'/watchlist?lang=en');ready(page)
            page.on('dialog',lambda dialog:dialog.accept())
            page.get_by_text('Manage favorites',exact=True).click();page.get_by_role('button',name='Clear favorites',exact=True).click();ready(page)
            assert symbols(page)==[]
            page.reload();ready(page);assert symbols(page)==[]
            expect(page.locator('#list-status')).to_contain_text('No favorites')
            page.get_by_text('Manage favorites',exact=True).click();page.get_by_role('button',name='Restore defaults',exact=True).click();ready(page)
            assert symbols(page)==defaults
            page.get_by_role('button',name='Edit list',exact=True).click();page.get_by_role('button',name='Move down AAPL',exact=True).click();ready(page)
            assert symbols(page)[:2]==['MSFT','AAPL']
            scenarios.append('Explicit empty survives reload, restore defaults confirms, ordering persists')
            with page.expect_download() as pending:page.get_by_role('button',name='Export',exact=True).click()
            download=pending.value;export=artifacts/'browser-export.json';download.save_as(export)
            assert json.loads(export.read_text())['symbols'][:2]==['MSFT','AAPL']
            def upload(value):
                page.locator('#favorites-import').set_input_files({'name':'favorites.json','mimeType':'application/json','buffer':json.dumps(value).encode()})
            upload({'version':1,'symbols':['S064','S030','AAA','AAA']})
            expect(page.locator('#import-result')).to_contain_text('Import rejected')
            upload({'version':1,'symbols':['S064','S030','AAPL','AAPL']})
            expect(page.locator('#import-result')).to_contain_text('Imported 3; duplicates removed 1')
            ready(page);assert symbols(page)==['S064','S030','AAPL']
            page.reload();ready(page);assert symbols(page)==['S064','S030','AAPL']
            upload({'version':1,'symbols':['AAPL']*101})
            expect(page.locator('#import-result')).to_contain_text('Import rejected')
            upload({'version':2,'symbols':['AAPL']})
            expect(page.locator('#import-result')).to_contain_text('Import rejected')
            upload({'version':1,'symbols':['<img src=x onerror=alert(1)>']})
            expect(page.locator('#import-result')).to_contain_text('Import rejected')
            assert symbols(page)==['S064','S030','AAPL']
            scenarios.append('Export/import, duplicates, version/size/unknown/injection rejection; favorites span market pages')
            upload({'version':1,'symbols':['SHORT','MISSING','STALE','PENDING','SPY','QQQ']})
            expect(page.locator('#import-result')).to_contain_text('Imported 6');ready(page)
            expect(page.locator('[data-symbol="SHORT"]')).to_contain_text('Insufficient data')
            expect(page.locator('[data-symbol="MISSING"]')).to_contain_text('Failed')
            expect(page.locator('[data-symbol="STALE"]')).to_contain_text('Stale')
            expect(page.locator('[data-symbol="PENDING"]')).to_contain_text('Pending update')
            expect(page.locator('[data-symbol="SPY"]')).to_contain_text('N/A')
            page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(artifacts/'watchlist-mobile.png'),full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.locator('[name=search]').fill('ZZZNOMATCH');page.locator('[name=search]').press('Enter');ready(page)
            assert symbols(page)==[];expect(page.locator('#list-status')).to_contain_text('No matching')
            scenarios.append('Pending/stale/failed/short-history and benchmark states; keyboard filter; 390px no overflow')
            page.goto(base+'/daily?lang=en');ready(page)
            expect(page.get_by_text('Viewing this session using your current favorites, not your historical favorites.')).to_be_visible()
            assert 'PRIVATE' not in symbols(page)
            page.locator('#report-all').check();ready(page)
            assert 'AAPL' in symbols(page) and 'PRIVATE' not in symbols(page)
            scenarios.append('Frozen report defaults to current favorites; explicit all-public view excludes private stock')
            broken=browser.new_context();broken.add_init_script("localStorage.setItem('stock-tracker-watchlist','broken')")
            broken_page=broken.new_page();broken_page.goto(base+'/watchlist?lang=en');ready(broken_page)
            expect(broken_page.locator('#storage-warning')).to_contain_text('damaged')
            assert symbols(broken_page)==[]
            blocked=browser.new_context();blocked.add_init_script("Object.defineProperty(window,'localStorage',{get(){throw new DOMException('blocked','SecurityError')}})")
            blocked_page=blocked.new_page();blocked_page.goto(base+'/watchlist?lang=en');ready(blocked_page)
            expect(blocked_page.locator('#storage-warning')).to_contain_text('cannot be saved permanently')
            blocked_page.get_by_role('button',name='Remove favorite AAPL',exact=True).click();ready(blocked_page)
            assert len(symbols(blocked_page))==8
            quota=browser.new_context();quota.add_init_script("Storage.prototype.setItem=function(){throw new DOMException('full','QuotaExceededError')}")
            quota_page=quota.new_page();quota_page.goto(base+'/watchlist?lang=en');ready(quota_page)
            expect(quota_page.locator('#storage-warning')).to_contain_text('cannot be saved permanently')
            scenarios.append('Corrupt, forbidden and quota-exceeded localStorage keep usable UI with persistent warning')
            page.goto(base+'/?lang=zh');ready(page);expect(page.locator('h1')).to_have_text('市场概览')
            assert not errors,errors
            from scripts.compact_acceptance import run_compact_checks
            run_compact_checks(browser, base, artifacts)
            browser.close()
        (artifacts/'browser-results.json').write_text(json.dumps(dict(status='passed',scenarios=scenarios,page_errors=errors),ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(dict(status='passed',scenarios=len(scenarios))))
    finally:
        server.terminate();server.wait(timeout=20);log.close()


if __name__=='__main__':main()
