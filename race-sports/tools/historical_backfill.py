import argparse
import html
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

KST = timezone(timedelta(hours=9))
ROOT = Path("race-sports")
DATA_ROOT = ROOT / "data"
STATE_DIR = DATA_ROOT / "historical_state"
BACKFILL_DIR = DATA_ROOT / "backfill"
STATE_FILE = STATE_DIR / "backfill_state.json"
REPORT_FILE = STATE_DIR / "backfill_report.json"

UA = "Mozilla/5.0 (RACE SPORTS ANALYTICS historical-backfill official-readonly)"
KBOAT_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1"

HORSE_DETAIL = (
    "https://race.kra.co.kr/raceScore/ScoretableDetailList.do"
    "?Act=04&Sub=1&meet={meet}&realRcDate={ymd}&realRcNo={race}"
)
CYCLE_CARD = "https://www.kcycle.or.kr/race/card/decision/{year}/{week}/{day}"
CYCLE_RESULT = "https://www.kcycle.or.kr/race/result/general/{year}/{week}/{day}/01"
BOAT_CARD = "https://www.kboat.or.kr/race/card/decision/{year}/{week}/{day}"
BOAT_RESULT = "https://www.kboat.or.kr/race/result/general/{year}/{week}/{day}/01"
BULL_CARD = "https://www.cpc.or.kr/cpc/module/game/gameCard/confirmed/index.do"
BULL_RESULT = "https://www.cpc.or.kr/cpc/module/game/gameResult/view.do"

CAPS = {"horse": 2500, "ksports": 2500, "bull": 4500}
START = {"horse": date(2014,1,1), "cycle": date(2011,1,1), "boat": date(2011,1,1), "bull_year": 2011}


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_tr = False
        self.in_cell = False
        self.cell = []
        self.row = []
        self.rows = []
        self.text_parts = []
        self.selected = False
        self.option = []
        self.selected_options = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs = dict(attrs)
        if tag == "tr":
            self.in_tr = True
            self.row = []
        elif tag in ("td","th") and self.in_tr:
            self.in_cell = True
            self.cell = []
        elif tag == "option":
            self.selected = "selected" in attrs or attrs.get("selected") is not None
            self.option = []
        if tag in ("br","p","div","h1","h2","h3","h4","li"):
            self.text_parts.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("td","th") and self.in_cell:
            self.row.append(clean("".join(self.cell)))
            self.in_cell = False
            self.cell = []
        elif tag == "tr" and self.in_tr:
            if self.row:
                self.rows.append(self.row[:])
            self.in_tr = False
            self.row = []
        elif tag == "option":
            if self.selected:
                self.selected_options.append(clean("".join(self.option)))
            self.selected = False
            self.option = []
        if tag in ("p","div","h1","h2","h3","h4","li","tr"):
            self.text_parts.append("\n")

    def handle_data(self, data):
        if self.in_cell:
            self.cell.append(data)
        if self.selected:
            self.option.append(data)
        self.text_parts.append(data)

    def text(self):
        s = html.unescape("".join(self.text_parts)).replace("\r","")
        s = re.sub(r"[ \t]+"," ",s)
        s = re.sub(r"\n[ \t]+","\n",s)
        return re.sub(r"\n{2,}","\n",s)


def clean(s):
    return re.sub(r"\s+"," ",html.unescape(str(s))).strip()


def decode_body(data, headers=None):
    encs = []
    try:
        c = headers.get_content_charset() if headers is not None else None
        if c:
            encs.append(c)
    except Exception:
        pass
    encs += ["utf-8","euc-kr","cp949"]
    seen = set()
    for enc in encs:
        if enc in seen:
            continue
        seen.add(enc)
        try:
            return data.decode(enc)
        except Exception:
            pass
    return data.decode("utf-8","ignore")


class Budget:
    def __init__(self, state, kst_day, slices, deadline):
        self.state = state
        self.kst_day = kst_day
        self.deadline = deadline
        ledgers = state.setdefault("daily_usage", {})
        ledger = ledgers.setdefault(kst_day, {"horse":0,"ksports":0,"bull":0})
        self.ledger = ledger
        self.slices = slices

    def available(self, group):
        return min(
            max(0, CAPS[group] - int(self.ledger.get(group,0))),
            max(0, int(self.slices.get(group,0))),
        )

    def consume(self, group):
        if self.available(group) <= 0:
            raise RuntimeError("BUDGET_EXHAUSTED:" + group)
        self.ledger[group] = int(self.ledger.get(group,0)) + 1
        self.slices[group] = int(self.slices.get(group,0)) - 1

    def time_left(self):
        return time.monotonic() < self.deadline


def fetch(url, budget, group, timeout=10, retries=2, mobile=False):
    last = None
    for i in range(retries):
        if not budget.time_left():
            raise RuntimeError("TIME_BUDGET_EXHAUSTED")
        budget.consume(group)
        headers = {
            "User-Agent": KBOAT_UA if mobile else UA,
            "Accept-Language":"ko-KR,ko;q=.9,en;q=.7",
            "Cache-Control":"no-cache",
            "Connection":"close",
        }
        try:
            req = urllib.request.Request(url,headers=headers)
            with urllib.request.urlopen(req,timeout=timeout) as r:
                return decode_body(r.read(),r.headers)
        except Exception as e:
            last = e
            if i+1 < retries and budget.available(group) > 0:
                time.sleep(0.4)
    raise last


def parse_html(raw):
    p = TableParser()
    p.feed(raw)
    return p, p.text()


def selected_date(raw, year_hint=None):
    p, text = parse_html(raw)
    for s in p.selected_options:
        m = re.search(r"(\d{4})[-./](\d{2})[-./](\d{2})",s)
        if m:
            return date(int(m.group(1)),int(m.group(2)),int(m.group(3)))
        m = re.search(r"(\d{2})월\s*(\d{2})일",s)
        if m and year_hint:
            return date(int(year_hint),int(m.group(1)),int(m.group(2)))
    m = re.search(r"(\d{4})년\s*\d+회\s*\d+일차\s*\((\d{2})월\s*(\d{2})일\)",text)
    if m:
        return date(int(m.group(1)),int(m.group(2)),int(m.group(3)))
    m = re.search(r"(\d{4})[-./](\d{2})[-./](\d{2})",text)
    if m:
        return date(int(m.group(1)),int(m.group(2)),int(m.group(3)))
    return None


def as_float(v):
    try:
        s = clean(v).replace(",","").replace("*","")
        m = re.search(r"-?\d+(?:\.\d+)?",s)
        return float(m.group(0)) if m else None
    except Exception:
        return None


def as_int(v):
    try:
        x = as_float(v)
        return int(x) if x is not None else None
    except Exception:
        return None


def load_state():
    STATE_DIR.mkdir(parents=True,exist_ok=True)
    BACKFILL_DIR.mkdir(parents=True,exist_ok=True)
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    else:
        state = {}
    y = datetime.now(KST).date() - timedelta(days=1)
    cp = state.setdefault("checkpoints",{})
    cp.setdefault("horse",{"cursor_date":y.isoformat(),"complete":False})
    cp.setdefault("cycle",{"cursor_date":y.isoformat(),"complete":False})
    cp.setdefault("boat",{"cursor_date":y.isoformat(),"complete":False})
    cp.setdefault("bull",{"year":y.year,"round":60,"day":2,"complete":False})
    state.setdefault("daily_usage",{})
    state["version"] = 1
    return state


def save_state(state):
    days = sorted(state.get("daily_usage",{}))
    for d in days[:-10]:
        state["daily_usage"].pop(d,None)
    STATE_FILE.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding="utf-8")


def existing_ids(sport):
    out = set()
    d = BACKFILL_DIR / sport
    if not d.exists():
        return out
    for p in d.glob("*.jsonl"):
        try:
            with p.open("r",encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        x=json.loads(line)
                        if x.get("id"):
                            out.add(x["id"])
                    except Exception:
                        pass
        except Exception:
            pass
    return out


def append_record(sport, event):
    d = BACKFILL_DIR / sport
    d.mkdir(parents=True,exist_ok=True)
    yr = str(event.get("event_date") or "")[:4] or "unknown"
    p = d / f"{yr}.jsonl"
    with p.open("a",encoding="utf-8") as f:
        f.write(json.dumps(event,ensure_ascii=False,separators=(",",":"))+"\n")


def parse_horse_detail(raw, meet, d, race_no):
    p, text = parse_html(raw)
    header = None
    rows = []
    race_info = {}
    m = re.search(
        r"(\d{4})년\s*(\d{2})월\s*(\d{2})일.*?제\s*(\d+)경주\s+([^\s|]+).*?\|\s*[^|]*\|\s*([^|]*)\|\s*([^|]*)\|\s*(\d{1,2}:\d{2})",
        text, re.S
    )
    if m:
        race_info = {"start_time":m.group(8),"weather":clean(m.group(6)),"track":clean(m.group(7))}
    for row in p.rows:
        norm = [clean(x).replace(" ","") for x in row]
        if all(k in norm for k in ("순위","마번","마명","기수명","조교사명","단승")):
            def idx(k):
                try:return norm.index(k)
                except ValueError:return None
            header = {"rank":idx("순위"),"number":idx("마번"),"horse_name":idx("마명"),"origin":idx("산지"),"sex":idx("성별"),"age":idx("연령"),"weight":idx("중량"),"rating":idx("레이팅"),"jockey":idx("기수명"),"trainer":idx("조교사명"),"owner":idx("마주명"),"body_weight":idx("마체중"),"single":idx("단승"),"place":idx("연승")}
            continue
        if not header:
            continue
        req=[header["rank"],header["number"],header["horse_name"]]
        if any(x is None for x in req) or len(row)<=max(req):
            continue
        rank=as_int(row[header["rank"]]); num=as_int(row[header["number"]])
        if not rank or not num or not 1<=num<=20:
            continue
        def val(k):
            i=header.get(k)
            return clean(row[i]) if i is not None and i<len(row) else None
        outcome={"key":f"N{num}","number":num,"horse_name":val("horse_name"),"name":f"{num} {val('horse_name')}","origin":val("origin"),"sex":val("sex"),"age":as_int(val("age")),"assigned_weight":as_float(val("weight")),"rating":as_float(val("rating")),"jockey":val("jockey"),"trainer":val("trainer"),"owner":val("owner"),"final_rank":rank,"won":rank==1,"final_odds":as_float(val("single")),"final_place_odds":as_float(val("place"))}
        rows.append(outcome)
    if not rows:
        return None
    meet_name={"1":"서울","2":"제주","3":"부경","4":"영천"}.get(str(meet),str(meet))
    return {"id":f"HORSE-{d.strftime('%Y%m%d')}-M{meet}-{race_no:02d}","sport":"HORSE","provider":"KRA","competition":f"{meet_name} 경마","event_date":d.isoformat(),"race_no":race_no,"status":"FINAL","start_time":race_info.get("start_time"),"market_type":"RUNNERS","outcomes":rows,"result":{"official":True,"status":"CONFIRMED","winner_number":next((x["number"] for x in rows if x["final_rank"]==1),None),"source":"KRA_SCORETABLE_DETAIL_OFFICIAL"},"feature_contract":{"allowed_prerace_fields":["horse_name","origin","sex","age","assigned_weight","rating","jockey","trainer","owner"],"blocked_postrace_fields":["final_rank","won","final_odds","final_place_odds"],"source_note":"stable race-entry fields read from official final scoretable; labels kept separately"},"source_url":HORSE_DETAIL.format(meet=meet,ymd=d.strftime("%Y%m%d"),race=race_no)}


def advance_day(cp,key,start):
    d=date.fromisoformat(cp[key]["cursor_date"]) - timedelta(days=1)
    cp[key]["cursor_date"]=d.isoformat()
    if d < start:
        cp[key]["complete"]=True


def backfill_horse(state,budget,seen,stats):
    cp=state["checkpoints"]["horse"]
    while not cp.get("complete") and budget.available("horse")>0 and budget.time_left():
        d=date.fromisoformat(cp["cursor_date"])
        if d < START["horse"]:
            cp["complete"]=True;break
        if d.weekday() not in (4,5,6):
            advance_day(state["checkpoints"],"horse",START["horse"]);continue
        date_failed=False
        for meet in ("1","2","3","4"):
            if budget.available("horse")<=0 or not budget.time_left(): break
            try:raw=fetch(HORSE_DETAIL.format(meet=meet,ymd=d.strftime("%Y%m%d"),race=1),budget,"horse",timeout=10,retries=1)
            except Exception as e:
                stats["errors"].append(f"HORSE {d} M{meet} R1 {type(e).__name__}:{e}"[:220]);date_failed=True;break
            first=parse_horse_detail(raw,meet,d,1)
            if not first:continue
            if first["id"] not in seen:
                append_record("horse",first);seen.add(first["id"]);stats["horse_records"]+=1
            empty=0
            for race_no in range(2,17):
                if budget.available("horse")<=0 or not budget.time_left():break
                try:raw=fetch(HORSE_DETAIL.format(meet=meet,ymd=d.strftime("%Y%m%d"),race=race_no),budget,"horse",timeout=10,retries=1)
                except Exception as e:
                    stats["errors"].append(f"HORSE {d} M{meet} R{race_no} {type(e).__name__}:{e}"[:220]);date_failed=True;break
                event=parse_horse_detail(raw,meet,d,race_no)
                if not event:
                    empty+=1
                    if empty>=2:break
                    continue
                empty=0
                if event["id"] not in seen:
                    append_record("horse",event);seen.add(event["id"]);stats["horse_records"]+=1
            if date_failed:break
        if date_failed:break
        stats["horse_dates"]+=1
        advance_day(state["checkpoints"],"horse",START["horse"]);save_state(state)


def parse_cycle_card(raw,d):
    _,text=parse_html(raw);out={}
    hs=list(re.finditer(r"(광명|창원|부산)\s*(\d{2})경주\s*\(([^)]*?)(\d{1,2}:\d{2})\)",text))
    for i,a in enumerate(hs):
        seg=text[a.start():(hs[i+1].start() if i+1<len(hs) else min(len(text),a.start()+12000))]
        rr={}
        for m in re.finditer(r"(?:^|\s)([1-7])\s+([가-힣]{2,5})\s+\d{1,2}기",seg):rr.setdefault(int(m.group(1)),m.group(2))
        if rr:out[(a.group(1),int(a.group(2)))]={"start_time":a.group(4),"runners":rr}
    return out


def parse_cycle_results(raw):
    p,_=parse_html(raw);out={};markets=["단승식","연승식","쌍승식","복승식","삼복승식","쌍복승식","삼쌍승식"]
    for row in p.rows:
        if len(row)<4:continue
        m=re.search(r"(광명|창원|부산)\s*0?(\d{1,2})",row[0])
        if not m:continue
        top=[]
        for x in row[1:4]:
            q=re.search(r"([1-7])\s*([가-힣]{2,5})",clean(x))
            if q:top.append({"number":int(q.group(1)),"name":q.group(2)})
        if len(top)!=3:continue
        pays=[]
        for i,cell in enumerate(row[4:11]):
            if i>=len(markets):break
            for winner,odd in re.findall(r"\(([^)]+)\)\s*(\d+(?:\.\d+)?)",clean(cell)):pays.append({"market":markets[i],"winner":winner.replace(" ",""),"odds":float(odd)})
        out[(m.group(1),int(m.group(2)))]={"top3":[{"rank":i+1,**top[i]} for i in range(3)],"markets":pays}
    return out


def backfill_cycle(state,budget,seen,stats,call_limit=None):
    cp=state["checkpoints"]["cycle"];start_calls=int(budget.ledger.get("ksports",0))
    def room(n=1):
        used=int(budget.ledger.get("ksports",0))-start_calls
        return (call_limit is None or used+n<=call_limit) and budget.available("ksports")>=n
    while not cp.get("complete") and room(2) and budget.time_left():
        d=date.fromisoformat(cp["cursor_date"])
        if d<START["cycle"]:cp["complete"]=True;break
        if d.weekday() not in (4,5,6):advance_day(state["checkpoints"],"cycle",START["cycle"]);continue
        iso=d.isocalendar();day={4:1,5:2,6:3}[d.weekday()]
        try:
            card_url=CYCLE_CARD.format(year=iso.year,week=iso.week,day=day);result_url=CYCLE_RESULT.format(year=iso.year,week=iso.week,day=day)
            card_raw=fetch(card_url,budget,"ksports",timeout=10,retries=1);result_raw=fetch(result_url,budget,"ksports",timeout=10,retries=1)
        except Exception as e:
            stats["errors"].append(f"CYCLE {d} {type(e).__name__}:{e}"[:220]);break
        card=parse_cycle_card(card_raw,d);results=parse_cycle_results(result_raw)
        for key,meta in card.items():
            r=results.get(key)
            if not r:continue
            venue,race_no=key;eid=f"CYCLE-{d.strftime('%Y%m%d')}-{venue}-{race_no:02d}"
            if eid in seen:continue
            top_by={x["number"]:x["rank"] for x in r["top3"]};outs=[]
            for n,name in sorted(meta["runners"].items()):outs.append({"key":f"N{n}","number":n,"name":f"{n} {name}","rider_name":name,"final_rank":top_by.get(n),"won":top_by.get(n)==1})
            event={"id":eid,"sport":"CYCLE","provider":"KCYCLE","competition":venue+" 경륜","event_date":d.isoformat(),"start_time":meta["start_time"],"race_no":race_no,"status":"FINAL","market_type":"RUNNERS","outcomes":outs,"result":{"official":True,"status":"CONFIRMED","top3":r["top3"],"markets":r["markets"],"source":"KCYCLE_RESULT_OFFICIAL"},"source_url":result_url}
            append_record("cycle",event);seen.add(eid);stats["cycle_records"]+=1
        stats["cycle_dates"]+=1;advance_day(state["checkpoints"],"cycle",START["cycle"]);save_state(state)


def textify(raw):
    s=re.sub(r"<script[\s\S]*?</script>"," ",raw,flags=re.I);s=re.sub(r"<style[\s\S]*?</style>"," ",s,flags=re.I);s=re.sub(r"<br\s*/?\s*>","\n",s,flags=re.I);s=re.sub(r"</(tr|td|th|div|p|li|h1|h2|h3|h4|option)>","\n",s,flags=re.I);s=re.sub(r"<[^>]+>"," ",s);s=html.unescape(s).replace("\r","");s=re.sub(r"[ \t]+"," ",s);s=re.sub(r"\n[ \t]+","\n",s);return re.sub(r"\n{2,}","\n",s)


def parse_boat_card(raw,d):
    t=textify(raw);hs=list(re.finditer(r"제\s*(\d{2})경주\s*\(출발시간\s*(\d{1,2}:\d{2})\)",t));out={}
    for i,a in enumerate(hs):
        seg=t[a.start():(hs[i+1].start() if i+1<len(hs) else min(len(t),a.start()+12000))];rr={}
        for m in re.finditer(r"(?:^|\s)([1-6])\s+([가-힣]{2,5})\s+\d{1,2}기/",seg):rr.setdefault(int(m.group(1)),m.group(2))
        if rr:out[int(a.group(1))]={"start_time":a.group(2),"runners":rr}
    return out


def parse_boat_results(raw):
    t=textify(raw);marker=t.find("경주결과");t=t[marker:] if marker>=0 else t;ms=list(re.finditer(r"(?:^|\n)(\d{2})R\s*\n",t));out={}
    for i,m in enumerate(ms):
        rn=int(m.group(1));seg=t[m.start():(ms[i+1].start() if i+1<len(ms) else len(t))];lines=[x.strip() for x in seg.split("\n") if x.strip()]
        try:ri=lines.index(f"{rn:02d}R")
        except ValueError:continue
        if len(lines)<ri+7:continue
        try:top3=[{"rank":1,"number":int(lines[ri+1]),"name":lines[ri+2]},{"rank":2,"number":int(lines[ri+3]),"name":lines[ri+4]},{"rank":3,"number":int(lines[ri+5]),"name":lines[ri+6]}]
        except Exception:continue
        out[rn]={"top3":top3}
    return out


def backfill_boat(state,budget,seen,stats,call_limit=None):
    cp=state["checkpoints"]["boat"];start_calls=int(budget.ledger.get("ksports",0))
    def room(n=1):
        used=int(budget.ledger.get("ksports",0))-start_calls
        return (call_limit is None or used+n<=call_limit) and budget.available("ksports")>=n
    while not cp.get("complete") and room(2) and budget.time_left():
        d=date.fromisoformat(cp["cursor_date"])
        if d<START["boat"]:cp["complete"]=True;break
        iso=d.isocalendar()
        for day in (1,2,3):
            if not room(1):break
            try:
                card_url=BOAT_CARD.format(year=iso.year,week=iso.week,day=day);raw=fetch(card_url,budget,"ksports",timeout=10,retries=1,mobile=True)
            except Exception as e:
                stats["errors"].append(f"BOAT {d} card d{day} {type(e).__name__}:{e}"[:220]);continue
            pd=selected_date(raw,d.year)
            if pd!=d:continue
            card=parse_boat_card(raw,d)
            if not card:continue
            if not room(1):break
            try:
                result_url=BOAT_RESULT.format(year=iso.year,week=iso.week,day=day);rraw=fetch(result_url,budget,"ksports",timeout=10,retries=1,mobile=True)
            except Exception as e:
                stats["errors"].append(f"BOAT {d} result d{day} {type(e).__name__}:{e}"[:220]);break
            results=parse_boat_results(rraw)
            for race_no,meta in card.items():
                r=results.get(race_no)
                if not r:continue
                eid=f"BOAT-{d.strftime('%Y%m%d')}-{iso.week}-{day}-{race_no:02d}"
                if eid in seen:continue
                top_by={x["number"]:x["rank"] for x in r["top3"]};outs=[{"key":f"N{n}","number":n,"name":f"{n} {name}","racer_name":name,"final_rank":top_by.get(n),"won":top_by.get(n)==1} for n,name in sorted(meta["runners"].items())]
                event={"id":eid,"sport":"BOAT","provider":"KBOAT","competition":f"미사리 경정 {iso.week}회차 {day}일차","event_date":d.isoformat(),"start_time":meta["start_time"],"race_no":race_no,"status":"FINAL","market_type":"RUNNERS","outcomes":outs,"result":{"official":True,"status":"CONFIRMED","top3":r["top3"],"source":"KBOAT_RESULT_OFFICIAL"},"source_url":result_url}
                append_record("boat",event);seen.add(eid);stats["boat_records"]+=1
            break
        stats["boat_dates"]+=1;advance_day(state["checkpoints"],"boat",START["boat"]);save_state(state)


def bull_url(base,year,rnd,day,race=None):
    q={"menu_idx":"52" if "gameCard" in base else "54","searchDayOrd":str(day),"searchStndYear":str(year),"searchTms":f"{rnd:02d}"}
    if race is not None:q["searchGameNo"]=f"{race:02d}"
    return base+"?"+urllib.parse.urlencode(q)


def bull_header(text):
    m=re.search(r"(\d{4})년도\s*(\d+)회차\s*(\d+)일차\s*\((\d{2})월\s*(\d{2})일\)표",text)
    if not m:return None
    return {"year":int(m.group(1)),"round":int(m.group(2)),"day":int(m.group(3)),"date":f"{m.group(1)}-{m.group(4)}-{m.group(5)}"}


def parse_bull_result(raw):
    t=textify(raw);hm=bull_header(t)
    if "경기확정" not in t:return hm,None
    red=re.search(r"(?:^|\n)\s*홍\s+([^\s\n]+)\s+\[(승|패|무)\]",t);blue=re.search(r"(?:^|\n)\s*청\s+([^\s\n]+)\s+\[(승|패|무)\]",t)
    if not red or not blue:
        red=re.search(r"홍\s+([^\s\n]+)\s+\[(승|패|무)\]",t);blue=re.search(r"청\s+([^\s\n]+)\s+\[(승|패|무)\]",t)
    if not red or not blue:return hm,None
    if red.group(2)=="승":winner="RED"
    elif blue.group(2)=="승":winner="BLUE"
    elif red.group(2)=="무" or blue.group(2)=="무":winner="DRAW"
    else:return hm,None
    return hm,{"winner":winner,"red":red.group(1),"blue":blue.group(1),"red_decision":red.group(2),"blue_decision":blue.group(2)}


def step_bull(cp):
    if cp["day"]==2:cp["day"]=1
    else:
        cp["day"]=2;cp["round"]-=1
        if cp["round"]<1:cp["year"]-=1;cp["round"]=60
    if cp["year"]<START["bull_year"]:cp["complete"]=True


def backfill_bull(state,budget,seen,stats):
    cp=state["checkpoints"]["bull"]
    while not cp.get("complete") and budget.available("bull")>0 and budget.time_left():
        year=int(cp["year"]);rnd=int(cp["round"]);day=int(cp["day"])
        try:raw=fetch(bull_url(BULL_CARD,year,rnd,day),budget,"bull",timeout=10,retries=1)
        except Exception as e:
            stats["errors"].append(f"BULL {year}-{rnd}-{day} card {type(e).__name__}:{e}"[:220]);break
        hm=bull_header(textify(raw))
        if not hm or hm["year"]!=year or hm["round"]!=rnd or hm["day"]!=day:
            step_bull(cp);save_state(state);continue
        d=hm["date"]
        for race in range(1,13):
            if budget.available("bull")<=0 or not budget.time_left():break
            ru=bull_url(BULL_RESULT,year,rnd,day,race)
            try:rraw=fetch(ru,budget,"bull",timeout=8,retries=1)
            except Exception as e:
                stats["errors"].append(f"BULL {year}-{rnd}-{day}-{race} {type(e).__name__}:{e}"[:220]);continue
            rh,res=parse_bull_result(rraw)
            if not res or not rh or rh.get("date")!=d:continue
            eid=f"BULL-{d.replace('-','')}-{rnd}-{day}-{race}"
            if eid in seen:continue
            outs=[{"key":"RED","name":res["red"],"decision":res["red_decision"],"won":res["winner"]=="RED"},{"key":"DRAW","name":"무승부","won":res["winner"]=="DRAW"},{"key":"BLUE","name":res["blue"],"decision":res["blue_decision"],"won":res["winner"]=="BLUE"}]
            event={"id":eid,"sport":"BULL","provider":"CPC","competition":f"청도 소싸움 {rnd}회차 {day}일차","event_date":d,"race_no":race,"status":"FINAL","market_type":"THREE_WAY","left":res["red"],"right":res["blue"],"outcomes":outs,"result":{"official":True,"status":"CONFIRMED","winner":{"key":res["winner"],"label":{"RED":"홍","DRAW":"무","BLUE":"청"}[res["winner"]]},"source":"CPC_RESULT_OFFICIAL"},"source_url":ru}
            append_record("bull",event);seen.add(eid);stats["bull_records"]+=1
        stats["bull_cards"]+=1;step_bull(cp);save_state(state)


def main():
    ap=argparse.ArgumentParser();ap.add_argument("--horse-slice",type=int,default=625);ap.add_argument("--ksports-slice",type=int,default=625);ap.add_argument("--bull-slice",type=int,default=1125);ap.add_argument("--max-seconds",type=int,default=720);ap.add_argument("--self-test",action="store_true");args=ap.parse_args()
    if args.self_test:
        fixture="""<table><tr><th>순위</th><th>마번</th><th>마명</th><th>산지</th><th>성별</th><th>연령</th><th>중량</th><th>레이팅</th><th>기수명</th><th>조교사명</th><th>마주명</th><th>도착차</th><th>마체중</th><th>단승</th><th>연승</th></tr><tr><td>1</td><td>7</td><td>가라가라가</td><td>한</td><td>수</td><td>3세</td><td>56</td><td>32</td><td>안토니오</td><td>강환민</td><td>서창식</td><td></td><td>457</td><td>5.0</td><td>1.9</td></tr></table>"""
        e=parse_horse_detail(fixture,"1",date(2018,7,8),4);assert e and e["outcomes"][0]["horse_name"]=="가라가라가" and e["outcomes"][0]["won"]
        print("HISTORICAL_BACKFILL_SELF_TEST=PASS");return
    state=load_state();today=datetime.now(KST).date().isoformat();deadline=time.monotonic()+max(60,args.max_seconds);budget=Budget(state,today,{"horse":args.horse_slice,"ksports":args.ksports_slice,"bull":args.bull_slice},deadline);seen={s:existing_ids(s) for s in ("horse","cycle","boat","bull")};stats={"horse_records":0,"horse_dates":0,"cycle_records":0,"cycle_dates":0,"boat_records":0,"boat_dates":0,"bull_records":0,"bull_cards":0,"errors":[]};before=dict(budget.ledger)
    backfill_horse(state,budget,seen["horse"],stats)
    ks_avail=budget.available("ksports");cycle_limit=(ks_avail+1)//2;boat_limit=ks_avail-cycle_limit
    if budget.time_left() and cycle_limit>=2:backfill_cycle(state,budget,seen["cycle"],stats,cycle_limit)
    if budget.time_left() and boat_limit>=2:backfill_boat(state,budget,seen["boat"],stats,boat_limit)
    if budget.time_left() and budget.available("bull")>0:backfill_bull(state,budget,seen["bull"],stats)
    save_state(state)
    report={"generated_at":datetime.now(KST).isoformat(timespec="seconds"),"mode":"OFFICIAL_READONLY_HISTORICAL_BACKFILL","caps":CAPS,"usage_today":budget.ledger,"usage_before_run":before,"checkpoints":state["checkpoints"],"new":stats,"records_total":{s:len(seen[s]) for s in seen},"quota_policy":"daily hard caps; four scheduled slices per KST day; KCYCLE and KBOAT split the shared KSPORTS slice"}
    REPORT_FILE.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8");print(json.dumps({"HISTORICAL_BACKFILL":"PASS",**report},ensure_ascii=False))


if __name__=="__main__":main()
