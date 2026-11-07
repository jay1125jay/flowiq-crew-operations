"""Browser contract check for the simplified PC realtime BTC FLOW dashboard."""
import copy
import json
import time
from pathlib import Path
from playwright.sync_api import sync_playwright
import realtime_runtime as rt
import category_realtime_server as category_server


def main():
    out=Path(__file__).parent/'browser-evidence'; out.mkdir(exist_ok=True)
    view=rt.View()
    category=json.loads((rt.ROOT/'trader-discovery/category-paper.json').read_text())
    category['updated_at']=rt.iso(time.time())
    assert category.get('paper_only') is True and category.get('real_trading_enabled') is False
    assert category.get('account_count')==6 and len(category.get('accounts',{}))==6
    for a in category['accounts'].values():
        assert a.get('starting_equity_krw')==3000000 and a.get('leverage')==10
    payload=dict(
        paper_only=True,real_trading_enabled=False,healthy=True,status='RUNNING',
        updated_at=rt.iso(time.time()),quote_at=rt.iso(time.time()),source_at=rt.iso(time.time()),
        ticks=123,btc_mid_usd=65000,
        category_mode='PC_REALTIME_6_CATEGORY_PAPER_SEPARATE_FROM_ADAPTIVE',
        category_healthy=True,category_source_at=rt.iso(time.time()),category_source_events=7,
        category_gap_recovery={'status':'REPLAYED','replayed_events':3},
        category_account_count=6,category_initial_capital_krw=3000000,category_leverage=10,
        category_competition=category)
    view.update(payload)
    class FixturePhone:
        def snapshot(self):
            from phone_share import DASHBOARD
            from urllib.parse import urlencode
            return {'status': 'LINK_READY', 'url': DASHBOARD+'#'+urlencode({
                'pc': 'https://btc-test-fixture.trycloudflare.com', 'key': 'a'*43})}
        def qr(self):
            return b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>'
    server=category_server.serve(view,'127.0.0.1',0,phone=FixturePhone()); evidence={}
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch()
            for name,width in [('desktop',1440),('mobile',390)]:
                data=copy.deepcopy(payload); data.update(healthy=True,status='RUNNING',updated_at=rt.iso(time.time()),category_healthy=True)
                data['category_competition']['updated_at']=rt.iso(time.time()); view.update(data)
                page=browser.new_page(viewport={'width':width,'height':900}); errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{server.server_port}/',wait_until='domcontentloaded')
                page.wait_for_function("document.querySelectorAll('#accountGrid .account-card').length===6")
                assert 'PC 실시간' in page.locator('#modeChip').inner_text()
                assert '복구 완료 · 3건' in page.locator('#recoveryState').inner_text()
                assert page.locator('#accountGrid .account-card').count()==6
                page.wait_for_function("document.querySelector('#phoneShareCopy').disabled===false")
                assert page.locator('#phoneSharePanel').is_visible()
                assert page.locator('#phoneShareQr').is_visible()
                assert 'https://jay1125jay.github.io' in page.locator('#phoneShareLink').input_value()
                assert '실제 주문 없음' in page.locator('body').inner_text()
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                page.screenshot(path=str(out/f'realtime-{name}.png'),full_page=True)
                data=copy.deepcopy(data); data.update(healthy=False,status='STALE_SOURCE',category_healthy=False); view.update(data)
                page.wait_for_function("document.querySelector('#engineState').textContent.includes('대기')")
                page.route('**/api/status*',lambda route:route.fulfill(status=503,body='unavailable'))
                page.wait_for_function("document.querySelector('#engineState').textContent.includes('확인 불가')")
                assert not errors,errors
                evidence[name]={'pc_realtime':True,'six_accounts':True,'gap_recovery':True,'stale_state':True,'offline_state':True,'no_overflow':True,'page_errors':errors}
                page.close()
            browser.close()
    finally:
        server.shutdown(); server.server_close()
    (out/'realtime-browser.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    print('REALTIME BROWSER PASS',json.dumps(evidence))

if __name__=='__main__':main()
