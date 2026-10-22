"""Existing GitHub origin + authenticated remote API browser contract. Synthetic values."""
import json
import time
from urllib.parse import urlsplit, urlencode
from playwright.sync_api import sync_playwright
from phone_share import DASHBOARD, ORIGIN
from realtime_runtime import ROOT, iso


def main():
    data=json.loads((ROOT/'data/adaptive-meta.json').read_text())
    for a in data['accounts'].values(): a['equity_usd']=2345.67
    for d in data['decisions'].values(): d.update(signal='LONG',confidence=60)
    token='a'*43
    endpoint='https://btc-test-fixture.trycloudflare.com'
    result={}
    with sync_playwright() as p:
        browser=p.chromium.launch()
        for name,width in [('desktop',1440),('phone',390)]:
            context=browser.new_context(viewport={'width':width,'height':900})
            mode={'value':'healthy'};keys=[]
            def github(route):
                path=urlsplit(route.request.url).path.removeprefix('/flowiq-crew-operations/btc-flow-monitor/')
                target=ROOT/path
                if path not in ('dashboard.html','dashboard-adaptive.js','dashboard-follow.js') and not path.endswith('.json'):
                    route.fulfill(status=404);return
                mime='application/javascript' if path.endswith('.js') else 'application/json' if path.endswith('.json') else 'text/html'
                route.fulfill(status=200,body=target.read_bytes(),content_type=mime+'; charset=utf-8')
            def api(route):
                headers={'Access-Control-Allow-Origin':ORIGIN,'Access-Control-Allow-Headers':'Authorization','Access-Control-Allow-Methods':'GET, OPTIONS'}
                if route.request.method=='OPTIONS':
                    route.fulfill(status=200,headers=headers);return
                keys.append(route.request.headers.get('authorization'))
                data['last_observation_at']=iso(time.time())
                payload=dict(paper_only=True,real_trading_enabled=False,healthy=mode['value']=='healthy',
                    competition=data,btc_mid_usd=65000,ticks=99,quote_at=iso(time.time()),source_at=iso(time.time()))
                route.fulfill(status=503 if mode['value']=='offline' else 200,headers=headers,content_type='application/json',body=json.dumps(payload))
            context.route(ORIGIN+'/**',github)
            context.route(endpoint+'/**',api)
            page=context.new_page();errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(DASHBOARD+'#'+urlencode({'pc':endpoint,'key':token}),wait_until='domcontentloaded')
            page.wait_for_function("document.querySelectorAll('#adaptiveRows tr').length===6")
            assert '2,345.67' in page.locator('#adaptiveRows').inner_text()
            assert 'PC 실시간 연결 정상' in page.locator('#adaptiveStatus').inner_text()
            assert keys and all(k=='Bearer '+token for k in keys)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            mode['value']='stale'
            page.wait_for_function("document.querySelector('#adaptiveRows').textContent.includes('판단 보류')")
            assert page.locator('#adaptiveRows').inner_text().count('판단 보류')==6
            mode['value']='offline'
            page.wait_for_function("document.querySelectorAll('#adaptiveRows tr').length===0")
            assert 'PC 연결 끊김' in page.locator('#adaptiveStatus').inner_text()
            mode['value']='healthy'
            page.wait_for_function("document.querySelectorAll('#adaptiveRows tr').length===6")
            assert '2,345.67' in page.locator('#adaptiveRows').inner_text()
            invalid=context.new_page();before=len(keys)
            invalid.goto(DASHBOARD+'#pc=https://untrusted.example&key=bad',wait_until='domcontentloaded')
            invalid.wait_for_function("document.querySelector('#adaptiveStatus').textContent.includes('잘못된 PC 연결 링크')")
            assert invalid.locator('#adaptiveRows tr').count()==0
            assert not errors,errors
            result[name]={'github_origin':True,'authenticated_remote_equity':True,'stale_wait':True,'offline_clears':True,'reconnects':True,'invalid_link_blocks':True}
            context.close()
        browser.close()
    print('PHONE BROWSER PASS',json.dumps(result))

if __name__=='__main__':main()
