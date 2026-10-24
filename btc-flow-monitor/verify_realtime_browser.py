"""Browser contract check for the PC runtime dashboard with synthetic PAPER fixtures."""
import copy
import json
import time
from pathlib import Path
from playwright.sync_api import sync_playwright
import realtime_runtime as rt
import category_realtime_server as category_server


def main():
    out=Path(__file__).parent/'browser-evidence'
    out.mkdir(exist_ok=True)
    view=rt.View()
    competition=json.loads((rt.ROOT/'data/adaptive-meta.json').read_text())
    competition['last_observation_at']=rt.iso(time.time())
    for a in competition['accounts'].values(): a['equity_usd']=1234.56
    for decision in competition['decisions'].values(): decision.update(signal='LONG',confidence=50)

    category=json.loads((rt.ROOT/'trader-discovery/category-paper.json').read_text())
    category['updated_at']=rt.iso(time.time())
    assert category.get('paper_only') is True and category.get('real_trading_enabled') is False
    assert category.get('account_count')==6 and len(category.get('accounts',{}))==6
    for a in category['accounts'].values():
        assert a.get('starting_equity_krw')==3000000 and a.get('leverage')==10

    payload=dict(
        paper_only=True,real_trading_enabled=False,healthy=True,status='RUNNING',
        updated_at=rt.iso(time.time()),quote_at=rt.iso(time.time()),source_at=rt.iso(time.time()),
        ticks=123,btc_mid_usd=65000,competition=competition,
        category_mode='PC_REALTIME_6_CATEGORY_PAPER_SEPARATE_FROM_ADAPTIVE',
        category_healthy=True,category_source_at=rt.iso(time.time()),category_source_events=7,
        category_account_count=6,category_initial_capital_krw=3000000,category_leverage=10,
        category_competition=category)
    view.update(payload)
    server=category_server.serve(view,'127.0.0.1',0)
    evidence={}
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch()
            for name,width in [('desktop',1440),('mobile',390)]:
                data=copy.deepcopy(payload)
                data.update(healthy=True,status='RUNNING',updated_at=rt.iso(time.time()),category_healthy=True)
                data['competition']['last_observation_at']=rt.iso(time.time())
                data['category_competition']['updated_at']=rt.iso(time.time())
                view.update(data)
                page=browser.new_page(viewport={'width':width,'height':900})
                errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{server.server_port}/',wait_until='domcontentloaded')

                # Legacy Adaptive remains visible and distinct.
                page.wait_for_function("document.querySelectorAll('#adaptiveRows tr').length===6")
                assert 'LONG · 상승' in page.locator('#adaptiveRows').inner_text()
                assert '1,234.56' in page.locator('#adaptiveRows').inner_text()
                assert page.locator('#localRuntimeNotice').is_visible()

                # New PC realtime six-category competition must render independently.
                page.wait_for_function("document.querySelectorAll('#categoryRealtimeRows tr').length===6")
                assert page.locator('#categoryRealtimePanel').is_visible()
                assert 'PC 6유형 실시간 테스트' in page.locator('#categoryRealtimePanel').inner_text()
                assert 'Adaptive 계좌와 완전 별도 기록' in page.locator('#categoryRealtimePanel').inner_text()
                assert page.locator('#categoryRealtimeRows tr').count()==6
                assert '3,000,000' in page.locator('#categoryRealtimePanel').inner_text()
                assert 'category-paper-realtime.json' in page.locator('#categoryRealtimeMeta').inner_text()

                assert page.locator('#nav button').count()>=11
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                page.screenshot(path=str(out/f'realtime-{name}.png'),full_page=True)

                # Adaptive stale handling must not masquerade as category success.
                data=copy.deepcopy(data);data.update(healthy=False,status='STALE_SOURCE')
                view.update(data)
                page.wait_for_function("!document.querySelector('#adaptiveRows').textContent.includes('LONG · 상승')")
                assert page.locator('#adaptiveRows').inner_text().count('판단 보류')==6
                assert page.locator('#categoryRealtimeRows tr').count()==6

                # Stored GitHub six-category page remains a separate view.
                page.get_by_role('button',name='6유형 PAPER',exact=True).click()
                page.wait_for_function("document.querySelectorAll('#paper6 .card').length===6")
                page.get_by_role('button',name='홈',exact=True).click()

                # Runtime API failure must clear both live tables rather than leave stale success.
                page.route('**/api/status',lambda route:route.fulfill(status=503,body='unavailable'))
                page.wait_for_function("document.querySelectorAll('#adaptiveRows tr').length===0")
                page.wait_for_function("document.querySelectorAll('#categoryRealtimeRows tr').length===0")
                assert not errors,errors
                evidence[name]={
                    'adaptive_separate':True,'pc_six_category_rows':True,'category_3m_10x':True,
                    'six_saved_accounts':True,'stale_separation':True,'error_clears_both':True,
                    'no_overflow':True,'page_errors':errors}
                page.close()
            browser.close()
    finally:
        server.shutdown();server.server_close()
    (out/'realtime-browser.json').write_text(json.dumps(evidence,indent=2))
    print('REALTIME BROWSER PASS',json.dumps(evidence))

if __name__=='__main__':main()
