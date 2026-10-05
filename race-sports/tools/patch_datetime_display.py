from pathlib import Path

p=Path('race-sports/live.html')
s=p.read_text(encoding='utf-8')
old=s

s=s.replace(
    '.head{display:grid;grid-template-columns:64px minmax(0,1fr) auto;',
    '.head{display:grid;grid-template-columns:92px minmax(0,1fr) auto;'
)
s=s.replace(
    '.time{font-size:15px;font-weight:950;white-space:nowrap}',
    '.time{font-size:13px;font-weight:950;white-space:nowrap}'
)
s=s.replace(
    '@media(max-width:420px){.head{grid-template-columns:58px minmax(0,1fr) auto}.time{font-size:14px}',
    '@media(max-width:420px){.head{grid-template-columns:86px minmax(0,1fr) auto}.time{font-size:12px}'
)

old_block="""function dateLabel(e){const d=String(e?.event_date||data?.date||'').trim();return /^\\d{4}-\\d{2}-\\d{2}$/.test(d)?d.slice(5).replace('-','/'):d}
function displayStart(e){
  const t=String(e?.start_time||'').trim();
  const label=String(e?.start_label||'').trim();
  const bad=new Set(['','--:--','시간 미정','TBD']);
  if(!bad.has(t)) return t;
  if(!bad.has(label)) return label;
  if(e?.sport==='BULL' && Number(e?.race_no)>1) return '순차 진행';
  return dateLabel(e)||'날짜 미정'
}
"""
new_block="""function dateLabel(e){const d=String(e?.event_date||data?.date||'').trim();return /^\\d{4}-\\d{2}-\\d{2}$/.test(d)?d.slice(5).replace('-','/'):d}
function displayStart(e){
  const d=dateLabel(e);
  const t=String(e?.start_time||'').trim();
  const label=String(e?.start_label||'').trim();
  const bad=new Set(['','--:--','시간 미정','TBD']);
  const clock=/^(?:[01]\\d|2[0-3]):[0-5]\\d$/;
  if(!bad.has(t) && clock.test(t)) return `${d} ${t}`.trim();
  if(!bad.has(label) && clock.test(label)) return `${d} ${label}`.trim();
  if(e?.sport==='BULL' && Number(e?.race_no)>1) return `${d} 순차 진행`.trim();
  return d?`${d} --:--`:'--/-- --:--'
}
"""
if old_block not in s:
    raise SystemExit('DISPLAY_START_BLOCK_NOT_FOUND')
s=s.replace(old_block,new_block,1)
s=s.replace('${esc(x.e.start_time)} · ${esc(x.e.title)} · ${esc(x.o.name)}','${esc(displayStart(x.e))} · ${esc(x.e.title)} · ${esc(x.o.name)}')

if s==old:
    raise SystemExit('NO_CHANGE')
p.write_text(s,encoding='utf-8')
print('DATETIME_DISPLAY_PATCH=PASS')
