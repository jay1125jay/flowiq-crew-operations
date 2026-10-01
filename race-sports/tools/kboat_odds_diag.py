import re,html,urllib.request
from datetime import datetime,timezone,timedelta
KST=timezone(timedelta(hours=9)); UA='Mozilla/5.0 (RACE SPORTS ANALYTICS diag)'
def fetch(u):
 r=urllib.request.Request(u,headers={'User-Agent':UA,'Accept-Language':'ko-KR,ko;q=.9'});return urllib.request.urlopen(r,timeout=15).read().decode('utf-8','ignore')
def textify(s):
 s=re.sub(r'<script[\s\S]*?</script>',' ',s,flags=re.I);s=re.sub(r'<style[\s\S]*?</style>',' ',s,flags=re.I);s=re.sub(r'<br\s*/?\s*>','\n',s,flags=re.I);s=re.sub(r'</(tr|td|th|div|p|li|h1|h2|h3|h4)>','\n',s,flags=re.I);s=re.sub(r'<[^>]+>',' ',s);s=html.unescape(s);s=re.sub(r'[ \t]+',' ',s);s=re.sub(r'\n[ \t]+','\n',s);s=re.sub(r'\n{2,}','\n',s);return s
u='https://www.kboat.or.kr/race/dividendrate/final'
raw=fetch(u); t=textify(raw); i=t.find('단승식')
print('BASE_TEXT','len',len(t),'excerpt',repr(t[max(0,i-120):i+700] if i>=0 else t[:900]))
print('FORMS',re.findall(r'<form[^>]{0,600}>',raw,re.I)[:10])
links=sorted(set(re.findall(r'(?:href|action)=[\"\']([^\"\']*dividendrate/final[^\"\']*)',raw,re.I)))
print('FINAL_LINKS',links[:50])
attrs=re.findall(r'<(?:a|button|input)[^>]{0,800}(?:경정\s*0?[1-9]|경정\s*1[0-7])[^>]{0,800}>',raw,re.I)
print('RACE_CONTROLS',attrs[:20])
for key in ('raceNo','race_no','raceNum','race','searchRace','raceNoSelect','turn','day'):
 vals=re.findall(rf'name=[\"\']{key}[\"\'][^>]{0,300}',raw,re.I)
 if vals: print('NAME',key,vals[:20])
for m in re.finditer(r'(?:raceNo|searchRace|raceNum)',raw,re.I):
 print('SCRIPT_SNIP',repr(raw[max(0,m.start()-250):m.start()+500]));
 if m.start()>0: break
