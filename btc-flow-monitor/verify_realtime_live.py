"""Bounded public-feed smoke test. Disposable accounts, never production state."""
import argparse
from contextlib import closing
import asyncio
import json
from pathlib import Path
import sqlite3
import tempfile
import urllib.request
import pc_runtime as rt

async def main():
    out=Path(__file__).parent/'browser-evidence'
    out.mkdir(exist_ok=True)
    samples=[]
    with tempfile.TemporaryDirectory(prefix='btc-paper-smoke-') as directory:
        import socket
        with socket.socket() as s:
            s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        task=asyncio.create_task(rt.run(argparse.Namespace(state_dir=directory,host='127.0.0.1',port=port,seconds=90)))
        def read():
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/status',timeout=2) as response:
                return json.load(response)
        while not task.done():
            await asyncio.sleep(2)
            try:
                data=await asyncio.to_thread(read)
                row={k:data.get(k) for k in ('healthy','category_healthy','status','ticks','quote_at','source_at','category_source_at','updated_at','category_account_count','error')}
                samples.append(row)
                if len(samples)%10==0:print('SMOKE',json.dumps(row),flush=True)
            except Exception:
                pass
        await task
        with closing(sqlite3.connect(Path(directory)/'paper.sqlite')) as db:
            row=db.execute('SELECT body FROM state WHERE id=1').fetchone()
        adaptive=json.loads(row[0]) if row else {}
        category_path=Path(directory)/'category-paper-realtime.json'
        category_payload=json.loads(category_path.read_text()) if category_path.exists() else {}
        category_state=category_payload.get('state',{})
        category_accounts=category_state.get('accounts',{})
        summary=dict(paper_only=True,real_trading_enabled=False,mode='DISPOSABLE_LIVE_SMOKE',
            ticks=adaptive.get('ticks',0),healthy_samples=sum(bool(x['healthy']) for x in samples),
            category_healthy_samples=sum(bool(x.get('category_healthy')) for x in samples),
            adaptive_engines=len(adaptive.get('competition',{}).get('accounts',{})),
            category_engines=len(category_accounts),
            category_file_separate=category_path.exists() and 'category_competition' not in adaptive,
            category_3m_10x=all(a.get('starting_equity_krw')==3000000 and a.get('leverage')==10 for a in category_accounts.values()),
            samples=samples)
        (out/'realtime-live.json').write_text(json.dumps(summary,indent=2))
        assert summary['ticks']>=10 and summary['healthy_samples']>=3,summary
        assert summary['adaptive_engines']==6 and summary['category_engines']==6,summary
        assert summary['category_healthy_samples']>=3 and summary['category_file_separate'] and summary['category_3m_10x'],summary
        print('REALTIME LIVE PASS',json.dumps({k:v for k,v in summary.items() if k!='samples'}))

if __name__=='__main__':asyncio.run(main())
