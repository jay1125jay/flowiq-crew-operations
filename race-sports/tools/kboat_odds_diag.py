import re,html,urllib.request
from datetime import datetime,timezone,timedelta
KST=timezone(timedelta(hours=9)); UA='Mozilla/5.0 (RACE SPORTS ANALYTICS diag)'
def fetch(u):
 r=urllib.request.Request(u,headers={'User-Agent':UA,'Accept-Language':'ko-KR,ko;q=.9'});return urllib.request.urlopen(r,timeout=15).read().decode('utf-8','ignore')
def textify(s):
 s=re.sub(r'<script[\s\S]*?</script>',' ',s,flags=re.I);s=re.sub(r'<style[\s\S]*?</style>',' ',s,flags=re.I);s=re.sub(r'<br\s*/?\s*>','\n',s,flags=re.I);s=re.sub(r'</(tr|td|th|div|p|li|h1|h2|h3|h4)>','\n',s,flags=re.I);s=re.sub(r'<[^>]+>',' ',s);s=html.unescape(s);s=re.sub(r'[ \t]+',' ',s);s=re.sub(r'\n[ \t]+','\n',s);s=re.sub(r'\n{2,}','\n',s);return s
z=datetime.now(KST);y=z.year;w=z.isocalendar().week
for rn in (3,4,5):
 u=f'https://www.kboat.or.kr/race/dividendrate/final/{y}/{w}/2/{rn}'
 try:
  t=textify(fetch(u));i=t.find('단승식');
  print('ODDS_DIAG',rn,'len',len(t),'has_single',i>=0,'excerpt',repr(t[max(0,i-100):i+900] if i>=0 else t[:900]))
 except Exception as e:print('ODDS_DIAG',rn,'ERROR',repr(e))
