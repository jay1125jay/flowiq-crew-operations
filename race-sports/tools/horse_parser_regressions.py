"""Replay official response excerpts without new provider requests."""
import json
from copy import deepcopy
from datetime import date
from pathlib import Path
import historical_backfill as hb
import historical_backfill_hardening as hardening
from backfill_quality_guard import validate_horse
FIXTURE=Path(__file__).parent/'fixtures'/'horse_parser_official_regressions.json'

def events():
    out=[]
    for r in json.loads(FIXTURE.read_text(encoding='utf-8'))['records']:
        d=date.fromisoformat(r['date'])
        assert r['source_url']==hb.HORSE_DETAIL.format(meet=r['meet'],ymd=d.strftime('%Y%m%d'),race=r['race_no'])
        e=hardening._parse_horse_detail(hb,r['html'],r['meet'],d,r['race_no'])
        assert e and validate_horse(e)[0]
        e['parser_revision']='KRA_RESULT_TABLE_BOUNDARY_V2'
        e['source_evidence']={'raw_sha256':r['raw_sha256'],'retrieved_date':'2026-10-24','fixture':FIXTURE.name}
        out.append(e)
    return out

def recover(state,seen):
    verified=events();added=[]
    for e in verified:
        if e['id'] not in seen:
            hb.append_record('horse',e);seen.add(e['id']);added.append(e['id'])
    queue=state.setdefault('retry_queue',{}).setdefault('horse',[])
    def pending(item):
        try:eid=f"HORSE-{date.fromisoformat(item['date']):%Y%m%d}-M{item['meet']}-{int(item['race_no']):02d}"
        except (KeyError,ValueError,TypeError):return True
        return eid not in seen
    state['retry_queue']['horse']=[x for x in queue if pending(x)]
    state['horse_parser_snapshot_recovery']={'revision':'KRA_RESULT_TABLE_BOUNDARY_V2','verified_ids':[e['id'] for e in verified],'added_this_run':added}
    return added

def self_test():
    es=events()
    assert [len(e['outcomes']) for e in es]==[12,11,10]
    assert all(sum(o['won'] for o in e['outcomes'])==1 for e in es)
    assert all(o['final_odds'] is None for o in es[1]['outcomes'])
    dnf=next(o for o in es[2]['outcomes'] if o['number']==4)
    assert dnf['finish_status']=='DNF' and dnf['final_rank'] is None and dnf['won'] is False
    assert all(':' not in o['horse_name'] for e in es for o in e['outcomes'])
    bad=deepcopy(es[0])
    for o in bad['outcomes']:
        if o['final_rank']==3:o['official_dead_heat']=False
    assert not validate_horse(bad)[0]
    for o in bad['outcomes']:
        if o['final_rank']==3:o['final_rank']=2;o['official_dead_heat']=True
    assert not validate_horse(bad)[0]
    r=json.loads(FIXTURE.read_text(encoding='utf-8'))['records'][0]
    assert hardening._parse_horse_detail(hb,r['html'],'1',date(2020,11,23),10) is None
    assert hardening._parse_horse_detail(hb,'<table></table>','1',date(2020,11,22),10) is None
    old=hb.append_record;saved=[];hb.append_record=lambda s,e:saved.append(e)
    try:
        state={'retry_queue':{'horse':[{'date':'2021-08-06','meet':'2','race_no':9},{'date':'2020-01-01','meet':'1','race_no':1}]}}
        seen=set();assert len(recover(state,seen))==3
        assert not recover(state,seen) and len(saved)==3
        assert len(state['retry_queue']['horse'])==1
    finally:hb.append_record=old
    print('HORSE_PARSER_OFFICIAL_REGRESSION=PASS fixtures=3 negative_checks=4 replay_idempotent=TRUE')
if __name__=='__main__':self_test()
