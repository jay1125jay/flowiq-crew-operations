"""Prospective AI TOP1 single-win paper ledger. Never places real bets."""
import json, math
from datetime import datetime,timedelta,timezone
from pathlib import Path
KST=timezone(timedelta(hours=9));STAKE=100000
SPORTS=('HORSE','CYCLE','BOAT','BULL')
SOURCES={'HORSE':{'KRA_SCORETABLE_OFFICIAL','KRA_SCORETABLE_DETAIL_OFFICIAL'},'CYCLE':{'KCYCLE_RESULT_OFFICIAL'},'BOAT':{'KBOAT_RESULT_OFFICIAL'},'BULL':{'CPC_RESULT_OFFICIAL'}}
ROOT=Path('race-sports/data');OUT=ROOT/'model_state/racing_paper.json'

def num(x):
    try:
        n=float(x);return n if math.isfinite(n) else None
    except (TypeError,ValueError):return None

def stamp(s):
    try:
        d=datetime.fromisoformat(str(s).replace('Z','+00:00'));return d if d.tzinfo else d.replace(tzinfo=KST)
    except ValueError:return None

def summary(records):
    rows=list(records);done=[r for r in rows if isinstance(r.get('hit'),bool)];settled=[r for r in done if r.get('settlement')=='SETTLED']
    stake=len(settled)*STAKE;ret=sum(r['return_krw'] for r in settled)
    return {'picks':len(rows),'evaluated':len(done),'hits':sum(r['hit'] for r in done),'hit_rate':sum(r['hit'] for r in done)/len(done) if done else None,'pending':sum(r.get('settlement')=='PENDING' for r in rows),'void':sum(r.get('settlement')=='VOID' for r in rows),'settled':len(settled),'excluded_no_odds':sum(r.get('settlement')=='NO_OFFICIAL_ODDS' for r in done),'stake_krw':stake,'return_krw':ret,'net_krw':ret-stake,'roi':(ret-stake)/stake if stake else None}

def settle(rec,e):
    if rec.get('settlement') in ('SETTLED','VOID'):return
    if e.get('sport')!=rec['sport'] or e.get('event_date')!=rec['date']:return
    if e.get('status') in ('CANCELLED','CANCELED','VOID'):
        rec['settlement']='VOID';return
    result=e.get('result') or {};sport=rec['sport']
    if e.get('status')!='FINAL' or result.get('official') is not True or result.get('status')!='CONFIRMED' or result.get('source') not in SOURCES[sport]:return
    if sport=='BULL':win=(result.get('winner') or {}).get('key')
    else:
        first=[str(x.get('number')) for x in result.get('top3',[]) if x.get('rank')==1]
        if len(first)==1:win='N'+first[0]
        elif result.get('winner_number') is not None:win='N'+str(result['winner_number'])
        else:return
    if win not in rec['runner_keys']:return
    odds=None
    for m in result.get('markets',[]):
        if m.get('market') not in ('단승','단승식'):continue
        w=str(m.get('winner','')).strip()
        expected=win[1:] if win.startswith('N') else {'RED':'홍','BLUE':'청','DRAW':'무'}.get(win)
        if w==expected:odds=num(m.get('odds'));break
    if sport=='BULL' and odds is None:
        o=next((o for o in e.get('outcomes',[]) if o.get('key')==win),{})
        if o.get('odds_source')=='CPC_FINAL_SINGLE_AUTO':odds=num(o.get('odds'))
    rec.update(hit=rec['pick_key']==win,winner_key=win,result_source=result['source'],result_url=result.get('source_url'),settlement='NO_OFFICIAL_ODDS')
    if odds is not None and 1<=odds<9999:
        rec.update(settlement='SETTLED',official_win_odds=odds,return_krw=round(STAKE*odds) if rec['hit'] else 0)
        rec['net_krw']=rec['return_krw']-STAKE

def update(ledger,snapshot,history,now):
    records=ledger.setdefault('records',{})
    for doc in [*history,snapshot]:
        for e in doc.get('events',[]):
            if e.get('id') in records:settle(records[e['id']],e)
    generated=stamp(snapshot.get('generated_at'));fresh=generated and -120<=(now-generated).total_seconds()<=1200
    skipped={}
    for e in snapshot.get('events',[]):
        eid=e.get('id');sport=e.get('sport')
        if sport not in SPORTS or not eid or eid in records:continue
        reason=None;start=stamp(str(e.get('event_date'))+'T'+str(e.get('start_time')))
        outs=e.get('outcomes') or [];ps=[num(o.get('model_p')) for o in outs]
        if not fresh or e.get('data_state') not in (None,'FRESH'):reason='STALE_SNAPSHOT'
        elif e.get('status')!='SCHEDULED' or e.get('result'):reason='ALREADY_STARTED_OR_FINAL'
        elif not start:reason='UNKNOWN_START_TIME'
        elif start<=now:reason='ALREADY_STARTED_OR_FINAL'
        elif len(ps)<2 or any(p is None or p<=0 or p>1 for p in ps) or abs(sum(ps)-1)>.025:reason='INVALID_PROBABILITIES'
        elif len({o.get('key') for o in outs})!=len(outs) or any(not o.get('key') for o in outs):reason='INVALID_RUNNER_KEYS'
        if reason:
            skipped[reason]=skipped.get(reason,0)+1;continue
        pick=max(outs,key=lambda o:o['model_p'])
        records[eid]={'id':eid,'sport':sport,'date':e['event_date'],'title':e.get('competition','')+' '+e.get('title',''),'start_at':start.isoformat(),'locked_at':now.isoformat(timespec='seconds'),'snapshot_at':snapshot['generated_at'],'pick_key':pick['key'],'pick_name':pick.get('name',pick['key']),'model_p':pick['model_p'],'model_source':pick.get('model_source',e.get('model_source')),'runner_keys':[o['key'] for o in outs],'stake_per_pick_krw':STAKE,'settlement':'PENDING','source_url':e.get('source_url')}
    ledger.update(version='RACING_PAPER_V1',updated_at=now.isoformat(timespec='seconds'),paper_only=True,real_betting=False,auto_betting=False,policy='PRESTART_LOCKED_AI_TOP1_SINGLE_WIN_100K_OFFICIAL_FINAL_TOTE_SETTLEMENT_NO_RETROSPECTIVE_PICKS',skipped_current=skipped)
    ledger['summary']={'overall':summary(records.values()),'by_sport':{s:summary(r for r in records.values() if r['sport']==s) for s in SPORTS}}
    return ledger

def main():
    ledger=json.loads(OUT.read_text()) if OUT.exists() else {'records':{}}
    dates={r['date'] for r in ledger['records'].values() if r.get('settlement') not in ('SETTLED','VOID')}
    history=[]
    for d in sorted(dates):
        p=ROOT/'history'/f'{d}.json'
        if p.exists():history.append(json.loads(p.read_text()))
    update(ledger,json.loads((ROOT/'today.json').read_text()),history,datetime.now(KST))
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(ledger,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'RACING_PAPER':'PASS','summary':ledger['summary'],'skipped':ledger['skipped_current']},ensure_ascii=False))
if __name__=='__main__':main()
