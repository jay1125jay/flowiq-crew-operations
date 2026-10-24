#!/usr/bin/env python3
"""Browser regression check of the actual static dashboard and persisted main data."""
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
                errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(url,wait_until='domcontentloaded')
                page.wait_for_function("document.querySelectorAll('#adaptiveRows tr').length === 6")
                assert page.locator('#adaptiveCadence').inner_text()
                assert page.locator('#adaptiveRows').inner_text().count('ADAPTIVE META')==1
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                assert not errors,errors
                page.screenshot(path=str(OUT/f'{name}.png'),full_page=True)
                # Existing six accounts must still render on their own tab.
                page.get_by_role('button',name='6유형 PAPER',exact=True).click()
                page.wait_for_function("document.querySelectorAll('#paper6 .card').length === 6")
                # Error response must clear the table instead of showing stale success.
                page.route('**/data/adaptive-meta.json*',lambda route:route.fulfill(status=503,body='unavailable'))
                page.get_by_role('button',name='홈',exact=True).click()
                page.get_by_role('button',name='↻ 새로고침',exact=True).click()
                page.wait_for_function("document.querySelector('#adaptiveStatus').textContent.includes('확인 불가')")
                assert page.locator('#adaptiveRows tr').count()==0
                result[name]={'six_engines':True,'six_cohort_accounts':True,'no_document_overflow':True,'error_state':True,'page_errors':errors}
                page.close()
            browser.close()
    finally:
        server.shutdown()
        (OUT/'result.json').write_text(json.dumps(result,indent=2))
    print('DASHBOARD BROWSER PASS',json.dumps(result))
if __name__=='__main__':main()
