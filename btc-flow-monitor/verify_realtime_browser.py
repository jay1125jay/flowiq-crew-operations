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
    view.update(dict(healthy=True,status='RUNNING',updated_at=rt.iso(time.time()),
        quote_at=rt.iso(time.time()),source_at=rt.iso(time.time()),reconnects=0,
        rows=[dict(engine=k,signal='LONG',confidence=50,equity_usd=1000,net_pnl_usd=0,
            profit_factor=None,mdd_pct=0,win_rate_pct=None,closed_count=0) for k in rt.engine.ENGINES]))
    server=rt.serve(view,'127.0.0.1',0)
    evidence={}
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch()
            for name,width in [('desktop',1440),('mobile',390)]:
                data=view.read();data.update(healthy=True,status='RUNNING',updated_at=rt.iso(time.time()))
                for row in data['rows']:row.update(signal='LONG',confidence=50)
                view.update(data)
                page=browser.new_page(viewport={'width':width,'height':900})
                errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{server.server_port}/')
                page.wait_for_function("document.querySelectorAll('#rows tr').length===6")
                assert '매수 방향' in page.locator('#rows').inner_text()
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                page.screenshot(path=str(out/f'realtime-{name}.png'),full_page=True)
                data.update(healthy=False,status='STALE_SOURCE');view.update(data)
                page.wait_for_function("!document.querySelector('#rows').textContent.includes('매수 방향')")
                assert page.locator('#rows').inner_text().count('관망')==6
                page.route('**/api/status',lambda route:route.fulfill(status=503,body='unavailable'))
                page.wait_for_function("document.querySelectorAll('#rows tr').length===0")
                assert not errors,errors
                evidence[name]={'six_rows':True,'stale_wait':True,'error_clears':True,'no_overflow':True}
                page.close()
            browser.close()
    finally:
        server.shutdown();server.server_close()
    (out/'realtime-browser.json').write_text(json.dumps(evidence,indent=2))
    print('REALTIME BROWSER PASS',json.dumps(evidence))

if __name__=='__main__':main()
