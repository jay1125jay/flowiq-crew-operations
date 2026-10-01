import re,html,urllib.request
u='https://www.kboat.or.kr/rankingpredict'
r=urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0 (RACE SPORTS ANALYTICS probe)','Accept-Language':'ko-KR,ko;q=.9'})
raw=urllib.request.urlopen(r,timeout=20).read().decode('utf-8','ignore')
s=re.sub(r'<script[\s\S]*?</script>',' ',raw,flags=re.I);s=re.sub(r'<style[\s\S]*?</style>',' ',s,flags=re.I);s=re.sub(r'<br\s*/?\s*>','\n',s,flags=re.I);s=re.sub(r'</(tr|td|th|div|p|li|h1|h2|h3|h4)>','\n',s,flags=re.I);s=re.sub(r'<[^>]+>',' ',s);s=html.unescape(s);s=re.sub(r'[ \t]+',' ',s);s=re.sub(r'\n[ \t]+','\n',s);s=re.sub(r'\n{2,}','\n',s)
print('LEN_RAW',len(raw),'LEN_TEXT',len(s))
for term in ['순위예측','AI 예측','AI예측','예측 확률','경정01','경정 01','2026-10-01']:
 print('TERM',term,'COUNT',len(re.findall(re.escape(term),s,re.I)))
for term in ['AI 예측','AI예측','경정 01','경정01']:
 m=re.search(re.escape(term),s,re.I)
 if m: print('SNIP',term,repr(s[max(0,m.start()-1200):m.start()+7000]))
