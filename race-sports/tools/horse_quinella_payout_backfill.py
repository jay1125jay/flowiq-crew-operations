#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import os
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

import validate_horse_model as hv

OUT = Path('race-sports/data/model_state/horse_quinella_payouts.json')
KST = timezone(timedelta(hours=9))
MAX_NEW = int(os.getenv('HORSE_QUINELLA_MAX_NEW', '500'))
WORKERS = int(os.getenv('HORSE_QUINELLA_WORKERS', '8'))
UA = 'Mozilla/5.0 (RaceIQ official KRA payout research; read-only)'
CIRCLED = {c: i for i, c in enumerate('①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳', 1)}

class TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.parts=[]
    def handle_data(self, data): self.parts.append(data)
    def text(self): return re.sub(r'\s+', ' ', html.unescape(' '.join(self.parts))).strip()

def event_url(e):
    u=e.get('source_url')
    if u: return u
    m=re.match(r'HORSE-(\d{8})-M(\d+)-(\d+)$', str(e.get('id') or ''))
    if not m: return None
    ymd,meet,race=m.groups()
    return f'https://race.kra.co.kr/raceScore/ScoretableDetailList.do?Act=04&Sub=1&meet={meet}&realRcDate={ymd}&realRcNo={int(race)}'

def actual_pair(e):
    rows=[]
    for o in e.get('outcomes') or []:
        try: rank=int(o.get('final_rank')); num=int(o.get('number'))
        except Exception: continue
        if rank in (1,2): rows.append((rank,num))
    rows.sort(); return [x[1] for x in rows] if len(rows)==2 else None

def parse_pair(token):
    nums=[CIRCLED[c] for c in token if c in CIRCLED]
    if len(nums)>=2: return nums[:2]
    plain=[int(x) for x in re.findall(r'\d+',token)]
    return plain[:2] if len(plain)>=2 else None

def parse_payout(raw):
    p=TextParser(); p.feed(raw); text=p.text()
    pos=text.find('배당률의 정보를 제공하는 표')
    if pos<0: pos=text.find('배당률')
    section=text[pos:] if pos>=0 else text
    stops=[section.find(x) for x in ('펄롱타임','통과순위','심판위원') if section.find(x)>0]
    if stops: section=section[:min(stops)]
    m=re.search(r'복승식\s*:\s*([^|]{0,40}?)\s+([0-9]+(?:\.[0-9]+)?)\s*(?:\||쌍승식|복연승식|삼복승식|삼쌍승식|$)',section)
    if not m: return None
    pair=parse_pair(m.group(1)); odds=float(m.group(2))
    return (pair,odds) if pair and odds>0 else None

def fetch_one(e):
    url=event_url(e)
    if not url: return e.get('id'),None,'NO_URL'
    try:
        req=urllib.request.Request(url,headers={'User-Agent':UA,'Accept-Language':'ko-KR,ko;q=.9'})
        with urllib.request.urlopen(req,timeout=8) as r:
            raw=r.read().decode(r.headers.get_content_charset() or 'utf-8','replace')
        parsed=parse_payout(raw)
        if not parsed: return e.get('id'),None,'PAYOUT_PARSE_MISS'
        pair,odds=parsed; expected=actual_pair(e)
        if expected and set(pair)!=set(expected): return e.get('id'),None,'PAIR_MISMATCH'
        return e.get('id'),{'event_id':e.get('id'),'event_date':e.get('event_date'),'official_pair':pair,'quinella_odds':odds,'source':'KRA_SCORETABLE_DETAIL_OFFICIAL','source_url':url,'fetched_at':datetime.now(KST).isoformat(timespec='seconds')},None
    except Exception as ex:
        return e.get('id'),None,type(ex).__name__

def main():
    races=hv.records(); eligible=[e for e,_,is_oos in hv.walk_forward_predictions(races) if is_oos]
    if OUT.exists():
        try: doc=json.loads(OUT.read_text(encoding='utf-8'))
        except Exception: doc={}
    else: doc={}
    records=doc.get('records') if isinstance(doc.get('records'),dict) else {}
    missing=[e for e in eligible if e.get('id') and e.get('id') not in records][:MAX_NEW]
    errors={}; added=0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for fut in as_completed([pool.submit(fetch_one,e) for e in missing]):
            eid,rec,err=fut.result()
            if rec: records[eid]=rec; added+=1
            elif eid: errors[err or 'UNKNOWN']=errors.get(err or 'UNKNOWN',0)+1
    eligible_ids={e['id'] for e in eligible}
    covered=len(eligible_ids.intersection(records))
    doc={'version':'HORSE_QUINELLA_PAYOUT_BACKFILL_V2_EXACT_COHORT','generated_at':datetime.now(KST).isoformat(timespec='seconds'),'source':'KRA_SCORETABLE_DETAIL_OFFICIAL','policy':'OFFICIAL_FINAL_TOTE_PAYOUT_ONLY; EXACT_EVENT_ID; OFFICIAL_1ST_2ND_PAIR_MUST_MATCH; NO_SYNTHETIC_ODDS','eligible_walk_forward_races':len(eligible),'stored':len(records),'covered_eligible':covered,'complete':covered==len(eligible_ids),'added_this_run':added,'requested_this_run':len(missing),'remaining_estimate':len(eligible_ids)-covered,'errors_this_run':errors,'records':records}
    OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in doc.items() if k!='records'},ensure_ascii=False))

if __name__=='__main__': main()
