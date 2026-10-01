$ErrorActionPreference = "Stop"

$ROOT = "C:\RACE_SPORTS_ANALYTICS"
$PY = Join-Path $ROOT ".venv\Scripts\python.exe"
$SCRIPT = Join-Path $ROOT "scripts\horse_build_official_labels.py"

if (!(Test-Path $PY)) {
    Write-Host "PYTHON_NOT_FOUND=$PY"
    exit 1
}

New-Item -ItemType Directory -Force -Path (Join-Path $ROOT "scripts") | Out-Null

$PYCODE = @'
from __future__ import annotations

import html
import json
import re
import time
import urllib.request
from collections import OrderedDict
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(r"C:\RACE_SPORTS_ANALYTICS")
PRE = ROOT / "data" / "curated" / "horse" / "pre_dedup.jsonl"
OUT_DIR = ROOT / "data" / "curated" / "horse"
OUT = OUT_DIR / "labeled_official_v1.jsonl"
CACHE = OUT_DIR / "kra_result_cache_v1.json"
REPORT = ROOT / "HORSE_LABEL_BUILD_REPORT.json"

UA = "Mozilla/5.0 (RACE SPORTS ANALYTICS KRA historical label builder)"
DETAIL_URL = (
    "https://race.kra.co.kr/raceScore/ScoretableDetailList.do"
    "?Act=04&Sub=1&meet={meet}&realRcDate={date}&realRcNo={race_no}"
)
MEET_CODE = {"서울": "1", "제주": "2", "부경": "3", "부산경남": "3", "부산": "3"}

class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_tr = False
        self.in_cell = False
        self.cell = []
        self.row = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "tr":
            self.in_tr = True
            self.row = []
        elif tag in ("td", "th") and self.in_tr:
            self.in_cell = True
            self.cell = []

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("td", "th") and self.in_cell:
            self.row.append(clean("".join(self.cell)))
            self.in_cell = False
            self.cell = []
        elif tag == "tr" and self.in_tr:
            if self.row:
                self.rows.append(self.row[:])
            self.in_tr = False
            self.row = []

    def handle_data(self, data):
        if self.in_cell:
            self.cell.append(data)

def clean(s):
    return re.sub(r"\s+", " ", html.unescape(str(s))).strip()

def decode_body(data: bytes, headers=None) -> str:
    encs = []
    try:
        c = headers.get_content_charset() if headers is not None else None
        if c:
            encs.append(c)
    except Exception:
        pass
    encs += ["utf-8", "euc-kr", "cp949"]
    for enc in encs:
        try:
            return data.decode(enc)
        except Exception:
            pass
    return data.decode("utf-8", "ignore")

def fetch(url: str, timeout=15, retries=3) -> str:
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9", "Cache-Control": "no-cache", "Connection": "close"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return decode_body(r.read(), r.headers)
        except Exception as e:
            last = e
            if i + 1 < retries:
                time.sleep(1.2)
    raise last

def parse_detail(raw: str) -> dict[int, dict]:
    p = TableParser()
    p.feed(raw)
    header = None
    out = {}
    for row in p.rows:
        norm = [clean(x).replace(" ", "") for x in row]
        if "순위" in norm and "마번" in norm:
            header = {"rank": norm.index("순위"), "number": norm.index("마번"), "single": norm.index("단승") if "단승" in norm else None, "place": norm.index("연승") if "연승" in norm else None}
            continue
        if not header:
            continue
        req_idx = [header["rank"], header["number"]]
        if header["single"] is not None:
            req_idx.append(header["single"])
        if header["place"] is not None:
            req_idx.append(header["place"])
        if len(row) <= max(req_idx):
            continue
        rs = clean(row[header["rank"]])
        ns = clean(row[header["number"]])
        if not re.fullmatch(r"\d{1,2}", rs) or not re.fullmatch(r"\d{1,2}", ns):
            continue
        n = int(ns)
        rank = int(rs)
        single = None
        place = None
        if header["single"] is not None:
            try:
                single = float(clean(row[header["single"]]).replace(",", ""))
            except Exception:
                pass
        if header["place"] is not None:
            try:
                place = float(clean(row[header["place"]]).replace(",", ""))
            except Exception:
                pass
        out[n] = {"final_rank": rank, "won": 1 if rank == 1 else 0, "final_odds": single, "final_place_odds": place}
    return out

def normalize_meet(x):
    s = str(x or "").strip()
    if s in MEET_CODE:
        return s
    if "서울" in s:
        return "서울"
    if "제주" in s:
        return "제주"
    if "부경" in s or "부산" in s:
        return "부경"
    return s

def race_key(row):
    r = row.get("row") or {}
    meet = normalize_meet(r.get("meet"))
    try:
        date = str(int(r.get("rcDate")))
        race_no = int(r.get("rcNo"))
        chul_no = int(r.get("chulNo"))
    except Exception:
        return None
    if meet not in MEET_CODE or len(date) != 8:
        return None
    return meet, date, race_no, chul_no

if not PRE.exists():
    raise SystemExit(f"PRE_NOT_FOUND={PRE}")

OUT_DIR.mkdir(parents=True, exist_ok=True)
runner_rows = OrderedDict()
pre_rows = 0
bad_rows = 0
with PRE.open("r", encoding="utf-8") as f:
    for line in f:
        if not line.strip():
            continue
        pre_rows += 1
        try:
            obj = json.loads(line)
        except Exception:
            bad_rows += 1
            continue
        k = race_key(obj)
        if not k:
            bad_rows += 1
            continue
        if k not in runner_rows:
            runner_rows[k] = obj

races = sorted({(k[0], k[1], k[2]) for k in runner_rows})
print(f"PRE_ROWS={pre_rows}")
print(f"UNIQUE_RUNNERS={len(runner_rows)}")
print(f"UNIQUE_RACES={len(races)}")

cache = {}
if CACHE.exists():
    try:
        cache = json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:
        cache = {}

probe_targets = [rk for rk in races if "|".join(map(str, rk)) not in cache][:3]
probe_ok = 0
for meet, date, race_no in probe_targets:
    url = DETAIL_URL.format(meet=MEET_CODE[meet], date=date, race_no=race_no)
    raw = fetch(url)
    parsed = parse_detail(raw)
    print(f"PROBE={meet}-{date}-{race_no} RUNNERS={len(parsed)}")
    if parsed:
        probe_ok += 1
    time.sleep(0.2)
if probe_targets and probe_ok == 0:
    raise SystemExit("KRA_RESULT_PROBE=FAIL")
print("KRA_RESULT_PROBE=PASS")

fetched = 0
failed = []
for idx, (meet, date, race_no) in enumerate(races, 1):
    ck = "|".join(map(str, (meet, date, race_no)))
    if ck in cache and isinstance(cache[ck], dict) and cache[ck].get("runners"):
        continue
    url = DETAIL_URL.format(meet=MEET_CODE[meet], date=date, race_no=race_no)
    try:
        parsed = parse_detail(fetch(url))
        if parsed:
            cache[ck] = {"meet": meet, "date": date, "race_no": race_no, "source": "KRA_SCORETABLE_DETAIL_OFFICIAL", "source_url": url, "runners": {str(k): v for k, v in parsed.items()}}
            fetched += 1
        else:
            failed.append({"race": ck, "reason": "PARSE_EMPTY"})
    except Exception as e:
        failed.append({"race": ck, "reason": type(e).__name__, "detail": str(e)[:160]})
    if idx % 25 == 0:
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"PROGRESS={idx}/{len(races)} CACHE_RACES={len(cache)} FAILED={len(failed)}")
    time.sleep(0.2)
CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

labeled = 0
winners = 0
race_labeled = set()
with OUT.open("w", encoding="utf-8") as out:
    for (meet, date, race_no, chul_no), obj in runner_rows.items():
        ck = "|".join(map(str, (meet, date, race_no)))
        c = cache.get(ck) or {}
        rr = (c.get("runners") or {}).get(str(chul_no))
        if not rr:
            continue
        record = dict(obj)
        record["label"] = {"final_rank": rr.get("final_rank"), "won": rr.get("won"), "final_odds": rr.get("final_odds"), "final_place_odds": rr.get("final_place_odds"), "source": "KRA_SCORETABLE_DETAIL_OFFICIAL", "source_url": c.get("source_url")}
        out.write(json.dumps(record, ensure_ascii=False) + "\n")
        labeled += 1
        winners += int(rr.get("won") == 1)
        race_labeled.add((meet, date, race_no))

coverage = (labeled / len(runner_rows)) if runner_rows else 0.0
report = {"generated_at": datetime.now().isoformat(timespec="seconds"), "root": str(ROOT), "paper_only": True, "pre_rows": pre_rows, "bad_rows": bad_rows, "unique_runner_rows": len(runner_rows), "unique_races": len(races), "cache_races": len(cache), "newly_fetched_races": fetched, "labeled_runner_rows": labeled, "labeled_races": len(race_labeled), "winner_rows": winners, "runner_label_coverage": coverage, "failed_races": failed[:200], "output": str(OUT), "cache": str(CACHE), "source": "KRA_SCORETABLE_DETAIL_OFFICIAL", "next": "LEAKAGE_AUDIT_THEN_TIME_ORDERED_WALK_FORWARD"}
REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print("")
print("HORSE_LABEL_BUILD=PASS")
print(f"LABELED_RUNNERS={labeled}")
print(f"LABELED_RACES={len(race_labeled)}")
print(f"COVERAGE={coverage:.6f}")
print(f"OUTPUT={OUT}")
print(f"REPORT={REPORT}")
'@

$PYCODE | Set-Content -LiteralPath $SCRIPT -Encoding UTF8
Write-Host "SCRIPT_CREATED=$SCRIPT"
& $PY $SCRIPT
$code = $LASTEXITCODE
if ($code -ne 0) {
    Write-Host "HORSE_LABEL_BUILD=FAIL"
    exit $code
}
$REPORT = Join-Path $ROOT "HORSE_LABEL_BUILD_REPORT.json"
if (Test-Path $REPORT) {
    Start-Process explorer.exe -ArgumentList "/select,`"$REPORT`""
    Start-Process notepad.exe -ArgumentList "`"$REPORT`""
}
