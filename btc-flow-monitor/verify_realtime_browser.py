"""Browser contract check for the runtime dashboard with explicitly synthetic fixtures."""
import json
import time
from pathlib import Path
from playwright.sync_api import sync_playwright
import realtime_runtime as rt


def main():
    out=Path(__file__).parent/'browser-evidence'
    out.mkdir(exist_ok=True)
    view=rt.View()
    competition=json.loads((rt.ROOT/'data/adaptive-meta.json').read_text())
    competition['last_observation_at']=rt.iso(time.time())
    for a in competition['accounts'].values(): a['equity_usd']=1234.56
    for decision in competition['decisions'].values(): decision.update(signal='LONG',confidence=50)
    view.update(dict(paper_only=True,real_trading_enabled=False,healthy=True,status='RUNNING',
        updated_at=rt.iso(time.time()),quote_at=rt.iso(time.time()),source_at=rt.iso(time.time()),
        ticks=123,btc_mid_usd=65000,competition=competition))
    server=rt.serve(view,'127.0.0.1',0)
    evidence={}
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch()
            for name,width in [('desktop',1440),('mobile',390)]:
                data=view.read();data.update(healthy=True,status='RUNNING',updated_at=rt.iso(time.time()))
                data['competition']['last_observation_at']=rt.iso(time.time())
                view.update(data)
                page=browser.new_page(viewport={'width':width,'height':900})
                errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{server.server_port}/',wait_until='domcontentloaded')
                page.wait_for_function("document.querySelectorAll('#adaptiveRows tr').length===6")
                assert 'LONG · 상승' in page.locator('#adaptiveRows').inner_text()
                assert '1,234.56' in page.locator('#adaptiveRows').inner_text()
                assert page.locator('#localRuntimeNotice').is_visible()
                assert page.locator('#nav button').count()>=11
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                page.screenshot(path=str(out/f'realtime-{name}.png'),full_page=True)
                data.update(healthy=False,status='STALE_SOURCE');view.update(data)
                page.wait_for_function("!document.querySelector('#adaptiveRows').textContent.includes('LONG · 상승')")
                assert page.locator('#adaptiveRows').inner_text().count('판단 보류')==6
                page.get_by_role('button',name='6유형 PAPER',exact=True).click()
                page.wait_for_function("document.querySelectorAll('#paper6 .card').length===12")
                page.get_by_role('button',name='홈',exact=True).click()
                page.route('**/api/status',lambda route:route.fulfill(status=503,body='unavailable'))
                page.wait_for_function("document.querySelectorAll('#adaptiveRows tr').length===0")
                assert not errors,errors
                evidence[name]={'existing_dashboard':True,'live_equity':True,'twelve_saved_accounts':True,'six_rows':True,'stale_wait':True,'error_clears':True,'no_overflow':True}
                page.close()
            browser.close()
    finally:
        server.shutdown();server.server_close()
    (out/'realtime-browser.json').write_text(json.dumps(evidence,indent=2))
    print('REALTIME BROWSER PASS',json.dumps(evidence))

if __name__=='__main__':main()
