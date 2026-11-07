"""GitHub dashboard + authenticated remote PC API contract for the simplified MVP."""
import json
import time
from urllib.parse import urlsplit, urlencode
from playwright.sync_api import sync_playwright
from phone_share import DASHBOARD, ORIGIN
from realtime_runtime import ROOT, iso


def main():
    category=json.loads((ROOT/'trader-discovery/category-paper.json').read_text())
    category['updated_at']=iso(time.time())
    token='a'*43; endpoint='https://btc-test-fixture.trycloudflare.com'; result={}
    with sync_playwright() as p:
        browser=p.chromium.launch()
        for name,width in [('desktop',1440),('phone',390)]:
            context=browser.new_context(viewport={'width':width,'height':900}); mode={'value':'healthy'}; keys=[]
            def github(route):
                path=urlsplit(route.request.url).path.removeprefix('/flowiq-crew-operations/btc-flow-monitor/')
                target=ROOT/path
                if path!='dashboard.html' and not path.endswith('.json'):
                    route.fulfill(status=404); return
                mime='application/json' if path.endswith('.json') else 'text/html'
                route.fulfill(status=200,body=target.read_bytes(),content_type=mime+'; charset=utf-8')
            def api(route):
                headers={'Access-Control-Allow-Origin':ORIGIN,'Access-Control-Allow-Headers':'Authorization','Access-Control-Allow-Methods':'GET, OPTIONS'}
                if route.request.method=='OPTIONS': route.fulfill(status=200,headers=headers); return
                keys.append(route.request.headers.get('authorization'))
                payload=dict(paper_only=True,real_trading_enabled=False,healthy=mode['value']=='healthy',status='RUNNING',
                    category_healthy=mode['value']=='healthy',category_competition=category,category_source_at=iso(time.time()),
                    category_gap_recovery={'status':'REPLAYED','replayed_events':5},btc_mid_usd=65000,updated_at=iso(time.time()))
                route.fulfill(status=503 if mode['value']=='offline' else 200,headers=headers,content_type='application/json',body=json.dumps(payload))
            context.route(ORIGIN+'/**',github); context.route(endpoint+'/**',api)
            page=context.new_page(); errors=[]; page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(DASHBOARD+'#'+urlencode({'pc':endpoint,'key':token}),wait_until='domcontentloaded')
            page.wait_for_function("document.querySelectorAll('#accountGrid .account-card').length===6")
            assert 'PC 실시간' in page.locator('#modeChip').inner_text()
            assert '복구 완료 · 5건' in page.locator('#recoveryState').inner_text()
            assert keys and all(k=='Bearer '+token for k in keys)
            assert page.locator('#phoneSharePanel').is_hidden()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            mode['value']='stale'; page.wait_for_function("document.querySelector('#engineState').textContent.includes('대기')")
            mode['value']='offline'; page.wait_for_function("document.querySelector('#engineState').textContent.includes('확인 불가')")
            mode['value']='healthy'; page.wait_for_function("document.querySelectorAll('#accountGrid .account-card').length===6")
            invalid=context.new_page(); before=len(keys); invalid.goto(DASHBOARD+'#pc=https://untrusted.example&key=bad',wait_until='domcontentloaded')
            invalid.wait_for_function("document.querySelector('#engineState').textContent.includes('잘못된 PC 연결 링크')")
            assert len(keys)==before and not errors,errors
            result[name]={'github_origin':True,'authenticated_remote':True,'six_accounts':True,'gap_recovery':True,'stale_state':True,'offline_state':True,'reconnects':True,'invalid_link_blocks':True}
            context.close()
        browser.close()
    print('PHONE BROWSER PASS',json.dumps(result))

if __name__=='__main__':main()
