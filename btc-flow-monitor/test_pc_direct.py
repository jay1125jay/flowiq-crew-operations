import copy
import json
import sqlite3
import subprocess
import tempfile
from pathlib import Path
from unittest import TestCase, main

import pc_wallet_follow as pc
import wallet_paper as paper


class DirectPaperTests(TestCase):
    def setUp(self):
        self.start = int(paper.now().timestamp()*1000)
        self.account = dict(cash=1_000_000, equity_krw=1_000_000, position=None, closed=[],
                            source_equity_usd=1_000_000, source_size=0, fill_count=0,
                            fill_cursor=self.start-100, peak_krw=1_000_000)
        self.ledger = dict(paper_only=True, real_trading_enabled=False, accounts={'w':self.account})

    def event(self,tid,side,before,size=1,offset=0):
        ms=self.start+offset
        return ('w',dict(coin='BTC',side=side,startPosition=before,sz=size,px=100,time=ms,tid=tid),ms+2)

    def test_round_trip_and_overlap(self):
        for sign in (1,-1):
            ledger=copy.deepcopy(self.ledger)
            enter='B' if sign==1 else 'A'
            exit_side='A' if sign==1 else 'B'
            events=[self.event(1,enter,0,2),self.event(2,exit_side,2*sign),self.event(3,exit_side,sign)]
            for i,event in enumerate(events):
                self.assertEqual(pc.apply_event(ledger,event,paper),'applied')
                self.assertEqual(pc.apply_event(ledger,event,paper),'covered')
                if i==1:
                    self.assertEqual(ledger['accounts']['w']['position']['notional'],5_000_000)
            a=ledger['accounts']['w']
            self.assertIsNone(a['position'])
            self.assertEqual(len(a['closed']),2)
            balance=a['cash']
            paper.process_batch(a,[e[1] for e in reversed(events)],1_000_000,self.start+5,100,paper.now().isoformat())
            self.assertEqual(a['cash'],balance)
            self.assertEqual(a['fill_count'],3)
            self.assertEqual(pc.apply_event(ledger,events[0],paper),'covered')

    def test_gap_and_late_open(self):
        self.assertEqual(pc.apply_event(self.ledger,self.event(1,'A',2),paper),'recover')
        wallet,row,received=self.event(2,'B',0)
        pc.apply_event(self.ledger,(wallet,row,received+60_000),paper)
        self.assertIsNone(self.ledger['accounts']['w']['position'])

    def test_receive_journal_and_git_publish(self):
        with tempfile.TemporaryDirectory() as temp:
            tmp=Path(temp)
            origin=tmp/'origin.git'
            root=tmp/'runner'
            subprocess.run(['git','init','--bare','-b','main',str(origin)],check=True,capture_output=True)
            root.mkdir()
            pc.git(root,'init','-b','main')
            path=root/pc.LEDGER
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(self.ledger))
            pc.git(root,'add','.')
            pc.git(root,'-c','user.name=test','-c','user.email=test@example.com','commit','-m','initial')
            pc.git(root,'remote','add','origin',str(origin))
            pc.git(root,'push','origin','main')
            journal=tmp/'queue.db'
            wallet,row,_=self.event(1,'B',0)
            msg=dict(channel='userFills',data=dict(user=wallet,fills=[row]))
            with sqlite3.connect(journal) as db:
                worker=pc.Observer(root,paper,db)
                worker.receive(msg)
                worker.receive(msg)
                self.assertEqual(len(worker.pending()),1)
                self.assertEqual(worker.ledger['accounts']['w']['position']['side'],1)
            with sqlite3.connect(journal) as db:
                worker=pc.Observer(root,paper,db)
                ledger,done=pc.synchronize(root,worker.pending(),False,paper)
                self.assertEqual(len(done),1)
                self.assertEqual(ledger['accounts']['w']['fill_count'],1)
                ledger,_=pc.synchronize(root,worker.pending(),False,paper)
                self.assertEqual(ledger['accounts']['w']['fill_count'],1)

if __name__=='__main__':
    main()
