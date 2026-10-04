#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SNAPSHOT=ROOT/"data"/"sports_today.json"

TEAM_KO={
# MLB
"Arizona Diamondbacks":"애리조나 다이아몬드백스","Athletics":"애슬레틱스","Atlanta Braves":"애틀랜타 브레이브스",
"Baltimore Orioles":"볼티모어 오리올스","Boston Red Sox":"보스턴 레드삭스","Chicago Cubs":"시카고 컵스",
"Chicago White Sox":"시카고 화이트삭스","Cincinnati Reds":"신시내티 레즈","Cleveland Guardians":"클리블랜드 가디언스",
"Colorado Rockies":"콜로라도 로키스","Detroit Tigers":"디트로이트 타이거스","Houston Astros":"휴스턴 애스트로스",
"Kansas City Royals":"캔자스시티 로열스","Los Angeles Angels":"LA 에인절스","Los Angeles Dodgers":"LA 다저스",
"Miami Marlins":"마이애미 말린스","Milwaukee Brewers":"밀워키 브루어스","Minnesota Twins":"미네소타 트윈스",
"New York Mets":"뉴욕 메츠","New York Yankees":"뉴욕 양키스","Philadelphia Phillies":"필라델피아 필리스",
"Pittsburgh Pirates":"피츠버그 파이리츠","San Diego Padres":"샌디에이고 파드리스","San Francisco Giants":"샌프란시스코 자이언츠",
"Seattle Mariners":"시애틀 매리너스","St. Louis Cardinals":"세인트루이스 카디널스","Tampa Bay Rays":"탬파베이 레이스",
"Texas Rangers":"텍사스 레인저스","Toronto Blue Jays":"토론토 블루제이스","Washington Nationals":"워싱턴 내셔널스",
# NBA
"Atlanta Hawks":"애틀랜타 호크스","Boston Celtics":"보스턴 셀틱스","Brooklyn Nets":"브루클린 네츠",
"Charlotte Hornets":"샬럿 호네츠","Chicago Bulls":"시카고 불스","Cleveland Cavaliers":"클리블랜드 캐벌리어스",
"Dallas Mavericks":"댈러스 매버릭스","Denver Nuggets":"덴버 너기츠","Detroit Pistons":"디트로이트 피스턴스",
"Golden State Warriors":"골든스테이트 워리어스","Houston Rockets":"휴스턴 로키츠","Indiana Pacers":"인디애나 페이서스",
"LA Clippers":"LA 클리퍼스","Los Angeles Clippers":"LA 클리퍼스","Los Angeles Lakers":"LA 레이커스",
"Memphis Grizzlies":"멤피스 그리즐리스","Miami Heat":"마이애미 히트","Milwaukee Bucks":"밀워키 벅스",
"Minnesota Timberwolves":"미네소타 팀버울브스","New Orleans Pelicans":"뉴올리언스 펠리컨스","New York Knicks":"뉴욕 닉스",
"Oklahoma City Thunder":"오클라호마시티 선더","Orlando Magic":"올랜도 매직","Philadelphia 76ers":"필라델피아 세븐티식서스",
"Phoenix Suns":"피닉스 선스","Portland Trail Blazers":"포틀랜드 트레일블레이저스","Sacramento Kings":"새크라멘토 킹스",
"San Antonio Spurs":"샌안토니오 스퍼스","Toronto Raptors":"토론토 랩터스","Utah Jazz":"유타 재즈",
"Washington Wizards":"워싱턴 위저즈",
# Premier League / England
"Arsenal":"아스널","Aston Villa":"애스턴 빌라","AFC Bournemouth":"본머스","Bournemouth":"본머스",
"Brentford":"브렌트퍼드","Brighton & Hove Albion":"브라이턴","Brighton":"브라이턴","Burnley":"번리",
"Chelsea":"첼시","Crystal Palace":"크리스털 팰리스","Everton":"에버턴","Fulham":"풀럼",
"Leeds United":"리즈 유나이티드","Liverpool":"리버풀","Manchester City":"맨체스터 시티",
"Manchester United":"맨체스터 유나이티드","Newcastle United":"뉴캐슬 유나이티드","Nottingham Forest":"노팅엄 포리스트",
"Sunderland":"선덜랜드","Tottenham Hotspur":"토트넘 홋스퍼","West Ham United":"웨스트햄 유나이티드",
"Wolverhampton Wanderers":"울버햄프턴","Wolverhampton":"울버햄프턴",
# LaLiga
"Alavés":"알라베스","Athletic Club":"아틀레틱 클루브","Athletic Bilbao":"아틀레틱 빌바오","Atlético Madrid":"아틀레티코 마드리드",
"Barcelona":"바르셀로나","Celta Vigo":"셀타 비고","Elche":"엘체","Espanyol":"에스파뇰","Getafe":"헤타페",
"Girona":"지로나","Levante":"레반테","Mallorca":"마요르카","Osasuna":"오사수나","Rayo Vallecano":"라요 바예카노",
"Real Betis":"레알 베티스","Real Madrid":"레알 마드리드","Real Oviedo":"레알 오비에도",
"Real Sociedad":"레알 소시에다드","Sevilla":"세비야","Valencia":"발렌시아","Villarreal":"비야레알",
# Bundesliga
"1. FC Heidenheim 1846":"하이덴하임","Bayer Leverkusen":"바이어 레버쿠젠","Bayern Munich":"바이에른 뮌헨",
"Borussia Dortmund":"보루시아 도르트문트","Borussia Mönchengladbach":"보루시아 묀헨글라트바흐",
"Eintracht Frankfurt":"아인트라흐트 프랑크푸르트","FC Augsburg":"아우크스부르크","FC St. Pauli":"장크트파울리",
"Hamburg SV":"함부르크","Mainz":"마인츠","RB Leipzig":"RB 라이프치히","SC Freiburg":"프라이부르크",
"TSG Hoffenheim":"호펜하임","Union Berlin":"우니온 베를린","VfB Stuttgart":"슈투트가르트",
"VfL Wolfsburg":"볼프스부르크","Werder Bremen":"베르더 브레멘","1. FC Köln":"쾰른","FC Cologne":"쾰른",
# Serie A
"AC Milan":"AC 밀란","AS Roma":"AS 로마","Atalanta":"아탈란타","Bologna":"볼로냐","Cagliari":"칼리아리",
"Como":"코모","Cremonese":"크레모네세","Fiorentina":"피오렌티나","Genoa":"제노아","Hellas Verona":"엘라스 베로나",
"Inter Milan":"인터 밀란","Internazionale":"인터 밀란","Juventus":"유벤투스","Lazio":"라치오","Lecce":"레체",
"Napoli":"나폴리","Parma":"파르마","Pisa":"피사","Sassuolo":"사수올로","Torino":"토리노","Udinese":"우디네세",
# Ligue 1
"Angers":"앙제","Auxerre":"오세르","Brest":"브레스트","Le Havre AC":"르아브르","Lens":"랑스","Lille":"릴",
"Lorient":"로리앙","Lyon":"리옹","Marseille":"마르세유","Metz":"메스","Monaco":"모나코","Nantes":"낭트",
"Nice":"니스","Paris FC":"파리 FC","Paris Saint-Germain":"파리 생제르맹","PSG":"파리 생제르맹",
"Rennes":"렌","Strasbourg":"스트라스부르","Toulouse":"툴루즈",
# National teams
"Argentina":"아르헨티나","Azerbaijan":"아제르바이잔","Belarus":"벨라루스","Bulgaria":"불가리아",
"Burkina Faso":"부르키나파소","Cameroon":"카메룬","Canada":"캐나다","Comoros":"코모로",
"Croatia":"크로아티아","Czechia":"체코","England":"잉글랜드","Estonia":"에스토니아",
"Iceland":"아이슬란드","Ivory Coast":"코트디부아르","Kyrgyz Republic":"키르기스스탄",
"Lebanon":"레바논","Lithuania":"리투아니아","Luxembourg":"룩셈부르크","Mali":"말리",
"Mexico":"멕시코","Namibia":"나미비아","North Macedonia":"북마케도니아","Peru":"페루",
"Russia":"러시아","San Marino":"산마리노","Scotland":"스코틀랜드","Senegal":"세네갈",
"Slovenia":"슬로베니아","Spain":"스페인","Switzerland":"스위스","Tunisia":"튀니지",
"United States":"미국","South Korea":"대한민국","Korea Republic":"대한민국","Japan":"일본",
"China":"중국","Australia":"호주","Saudi Arabia":"사우디아라비아","Qatar":"카타르",
"United Arab Emirates":"아랍에미리트","Iran":"이란","Iraq":"이라크","Uzbekistan":"우즈베키스탄",
# Common Champions League clubs
"Ajax Amsterdam":"아약스","Ajax":"아약스","Benfica":"벤피카","FC Porto":"FC 포르투","Porto":"포르투",
"PSV Eindhoven":"PSV 에인트호번","Sporting CP":"스포르팅 CP","Celtic":"셀틱","Galatasaray":"갈라타사라이",
"Fenerbahce":"페네르바흐체","Fenerbahçe":"페네르바흐체","Olympiacos":"올림피아코스",
"Club Brugge":"클뤼프 브뤼허","Red Bull Salzburg":"잘츠부르크","Salzburg":"잘츠부르크",
"Shakhtar Donetsk":"샤흐타르 도네츠크","Dynamo Kyiv":"디나모 키이우","Slavia Prague":"슬라비아 프라하",
"Sparta Prague":"스파르타 프라하","Red Star Belgrade":"츠르베나 즈베즈다","Bodø/Glimt":"보되/글림트",
# KOVO (already Korean, kept for explicit structure)
"대한항공":"대한항공","현대캐피탈":"현대캐피탈","한국전력":"한국전력","삼성화재":"삼성화재","우리카드":"우리카드",
"KB손해보험":"KB손해보험","OK저축은행":"OK저축은행","흥국생명":"흥국생명","현대건설":"현대건설",
"한국도로공사":"한국도로공사","GS칼텍스":"GS칼텍스","IBK기업은행":"IBK기업은행","정관장":"정관장",
"페퍼저축은행":"페퍼저축은행",
}

def team_ko(name:str)->str:
    return TEAM_KO.get(str(name or "").strip(),"")

DOMESTIC_CODES={"LG","KT","NC","SSG","KIA"}

def needs_translation(name:str)->bool:
    s=str(name or "").strip()
    return bool(s) and not re.search(r"[가-힣]",s) and s not in DOMESTIC_CODES

def apply(path:Path):
    p=json.loads(path.read_text(encoding="utf-8"))
    translated=0;missing=set()
    for e in p.get("events",[]):
        h=str(e.get("home") or "");a=str(e.get("away") or "")
        hk=team_ko(h);ak=team_ko(a)
        if hk:
            e["home_ko"]=hk;translated+=1
        elif needs_translation(h) and e.get("sport")!="VOLLEYBALL":missing.add(h)
        if ak:
            e["away_ko"]=ak;translated+=1
        elif needs_translation(a) and e.get("sport")!="VOLLEYBALL":missing.add(a)
        for o in e.get("outcomes",[]):
            if o.get("key")=="HOME" and hk:o["name_ko"]=hk
            elif o.get("key")=="AWAY" and ak:o["name_ko"]=ak
            elif o.get("key")=="DRAW":o["name_ko"]="무승부"
    p["team_name_localization"]={
        "language":"ko","translated_fields":translated,
        "missing_team_names":sorted(missing),
    }
    tmp=path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(p,ensure_ascii=False,indent=2),encoding="utf-8")
    tmp.replace(path)
    print(json.dumps({"SPORTS_TEAM_KO":"PASS","translated_fields":translated,"missing":sorted(missing)},ensure_ascii=False))

def self_test():
    assert team_ko("Los Angeles Dodgers")=="LA 다저스"
    assert team_ko("Toronto Raptors")=="토론토 랩터스"
    assert team_ko("Manchester City")=="맨체스터 시티"
    assert team_ko("Real Madrid")=="레알 마드리드"
    print(json.dumps({"SPORTS_TEAM_KO_SELF_TEST":"PASS","teams":len(TEAM_KO)},ensure_ascii=False))

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--self-test",action="store_true");ap.add_argument("--path",default=str(SNAPSHOT));a=ap.parse_args()
    if a.self_test:return self_test()
    apply(Path(a.path))

if __name__=="__main__":
    main()
