#!/usr/bin/env python3
"""Browser regression check for the simplified static BTC FLOW dashboard."""
import functools
import http.server
import json
import pathlib
import threading
from playwright.sync_api import sync_playwright

ROOT=pathlib.Path(__file__).resolve().parent
OUT=ROOT/'browser-evidence'
BASE=ROOT.parent

def main():
    OUT.mkdir(exist_ok=True)
    handler=functools.partial(http.server.SimpleHTTPRequestHandler,directory=str(BASE))
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    url=f'http://127.0.0.1:{server.server_port}/btc-flow-monitor/dashboard.html'
    result={}
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch()
            for name,width,height in [('desktop',1440,1000),('mobile',390,844)]:
                page=browser.new_page(viewport={'width':width,'height':height})
                errors=[]; page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(url,wait_until='domcontentloaded')
                page.wait_for_function("document.querySelectorAll('#accountGrid .account-card').length===6")
                # Both cloud legacy positions and PC live positions must show PnL.
                assert page.evaluate("posPnl({side:'LONG',entry:70000,qty:0.1,notional_usd:7000},71000)") == 150000
                assert page.evaluate("posPnl({side:'SHORT',entry_price:70000,notional_usd:7000},69000)") == 150000
                assert page.evaluate("posPnl({side:'LONG',entry:0,qty:0},69000)") is None
                assert '18,000,000원' in page.locator('#totalPnl').inner_text()
                assert page.locator('#modeChip').inner_text().startswith('● 클라우드 5분')
                assert page.locator('#accountGrid .account-card').count()==6
                assert page.locator('#engineState').inner_text()
                page.route('**/trader-discovery/category-paper.json*',lambda route:route.fulfill(status=200,content_type='application/json',body=json.dumps({**json.loads((ROOT/'trader-discovery/category-paper.json').read_text()),'updated_at':'2026-10-01T00:00:00+00:00'})))
                page.get_by_role('button',name='새로고침',exact=True).click()
                page.wait_for_function("document.querySelector('#engineState').textContent.includes('엔진 지연')")
                page.unroute('**/trader-discovery/category-paper.json*')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                assert not errors,errors
                page.screenshot(path=str(OUT/f'{name}.png'),full_page=True)
                page.route('**/trader-discovery/category-paper.json*',lambda route:route.fulfill(status=503,body='unavailable'))
                page.get_by_role('button',name='새로고침',exact=True).click()
                page.wait_for_function("document.querySelector('#engineState').textContent.includes('확인 불가')")
                result[name]={'six_accounts':True,'simple_home':True,'no_overflow':True,'error_state':True,'page_errors':errors}
                page.close()
            browser.close()
    finally:
        server.shutdown()
        (OUT/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('DASHBOARD BROWSER PASS',json.dumps(result))

if __name__=='__main__':main()
