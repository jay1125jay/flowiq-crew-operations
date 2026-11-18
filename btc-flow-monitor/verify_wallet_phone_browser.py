"""Mobile direct-ledger refresh and disconnect UI, using explicit synthetic data."""
import json
import time
import shutil
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    html=Path(__file__).with_name('dashboard.html').read_text(encoding='utf-8')
    addresses=['0x'+str(i)*40 for i in range(1,6)]
    ledger=dict(paper_only=True,real_trading_enabled=False,initial_krw=1_000_000,
        leverage=10,updated_at='2026-11-18T13:00:00+00:00',observed_count=5,
        selected_whales=[dict(address=a,net_pnl_usd=100) for a in addresses],
        accounts={a:dict(cash=1_000_000,equity_krw=1_000_000,fill_cursor=1,position=None,
                        closed=[],last_at='2026-11-18T13:00:00+00:00',source_btc_size=0) for a in addresses})
    state={'revision':1,'offline':False,'requests':0}
    errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True, executable_path=shutil.which('google-chrome') or shutil.which('chromium'))
        page=browser.new_page(viewport={'width':390,'height':844},is_mobile=True)
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.add_init_script('window.WebSocket=class {static OPEN=1; readyState=1; send(){} close(){}};')
        def route(request):
            url=request.request.url
            if '/api/status' in url:
                state['requests']+=1
                if state['offline']:
                    request.abort('failed')
                    return
                live=dict(revision=state['revision'],heartbeat_ms=int(time.time()*1000),connected=True,pending=0)
                payload=dict(ledger,pc_live=live)
                if 'since='+str(state['revision']) in url:
                    payload=dict(paper_only=True,real_trading_enabled=False,unchanged=True,pc_live=live)
                request.fulfill(json=payload,headers={'Access-Control-Allow-Origin':'*'})
            elif 'dashboard.html' in url:
                request.fulfill(body=html,content_type='text/html')
            else:
                request.fulfill(json={})
        page.route('**/*',route)
        page.goto('https://phone-test.trycloudflare.com/dashboard.html#pc=https://phone-test.trycloudflare.com&key='+'A'*43)
        page.wait_for_function("document.getElementById('walletEquity').textContent.includes('5,000,000')")
        page.wait_for_function("document.getElementById('ledgerHealth').textContent.includes('PC 직접 연결')")
        ledger['accounts'][addresses[0]]['equity_krw']=1_000_100
        state['revision']=2
        page.wait_for_function("document.getElementById('walletEquity').textContent.includes('5,000,100')",timeout=5000)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile horizontal overflow'
        state['offline']=True
        page.wait_for_function("document.getElementById('ledgerHealth').textContent.includes('연결 끊김')",timeout=5000)
        assert page.locator('#walletEquity').inner_text()=='5,000,100원', 'Last value disappeared'
        assert not errors,errors
        print('PASS: mobile live update, unchanged heartbeat, offline warning, 390px layout')
        browser.close()

if __name__=='__main__': main()
