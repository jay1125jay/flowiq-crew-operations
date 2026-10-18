(()=>{
const names={WHALE:'고래',HIGH_WIN_RATE:'고승률',HIGH_PROFIT:'고수익',CONSISTENT:'안정형',SCALPER:'스캘퍼',SWING:'스윙'};
const fmt=(n,d=2)=>Number.isFinite(Number(n))?Number(n).toLocaleString('ko-KR',{maximumFractionDigits:d}):'—';
const usd=n=>'$'+fmt(n);const short=a=>a?a.slice(0,8)+'…'+a.slice(-5):'—';
const side=s=>({LONG:'롱',SHORT:'숏',FLAT:'관망'}[s]||s||'미관측');
const time=t=>t?new Date(t).toLocaleString('ko-KR'):'—';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let loading=false;
function install(){
 const nav=document.getElementById('nav'),log=document.getElementById('log');if(!nav||!log)return;
 if(!document.getElementById('follow')){
  const b=document.createElement('button');b.dataset.page='follow';b.textContent='현재 추종';nav.insertBefore(b,[...nav.querySelectorAll('button')].find(x=>x.dataset.page==='log')||null);
  const p=document.createElement('section');p.className='page';p.id='follow';
  p.innerHTML='<div class="panel"><div class="head"><h2>전체 트레이더 현재 추종 · PAPER ONLY</h2><div class="muted" id="followMeta">조회 중</div></div><div class="pad"><div class="grid" id="followSummary"></div><div class="tablewrap"><table class="table"><thead><tr><th>지갑</th><th>유형</th><th>원본 방향</th><th>PAPER 계좌</th><th>진입가</th><th>현재가</th><th>미실현 PnL(추정)</th><th>진입시간</th></tr></thead><tbody id="followRows"></tbody></table></div></div></div>';log.parentNode.insertBefore(p,log);
  b.onclick=()=>{nav.querySelectorAll('button').forEach(x=>x.classList.toggle('active',x===b));document.querySelectorAll('.page').forEach(x=>x.classList.toggle('active',x.id==='follow'));window.scrollTo({top:0,behavior:'smooth'});refresh()};
 }
 if(!document.getElementById('categoryHistory')){
  const p=document.createElement('div');p.id='categoryHistory';p.className='panel';
  p.innerHTML='<div class="head"><h2>6유형 PAPER 종료 거래 기록</h2><div class="muted" id="categoryHistoryMeta">최근 종료 거래 · 수수료 및 슬리피지 반영</div></div><div class="pad"><div class="grid" id="categoryStats"></div><div class="tablewrap"><table class="table"><thead><tr><th>유형</th><th>지갑</th><th>방향</th><th>진입시간</th><th>종료시간</th><th>진입가</th><th>종료가</th><th>종료사유</th><th>순손익</th></tr></thead><tbody id="categoryHistoryRows"></tbody></table></div></div>';
  log.appendChild(p);
 }
 document.getElementById('refreshBtn')?.addEventListener('click',()=>refresh());
 refresh();
}
async function json(p){const r=await fetch(p+'?v='+Date.now(),{cache:'no-store'});if(!r.ok)throw Error(p+' HTTP '+r.status);return r.json()}
async function refresh(){
 if(loading||!document.getElementById('followMeta'))return;loading=true;
 try{
  const [f,c,cp]=await Promise.all([json('./trader-discovery/current-positions.json'),json('./trader-discovery/latest.json'),json('./trader-discovery/category-paper.json')]);
  const ws=c.wallets||[],dirs=f.wallets||{},accounts=cp.accounts||{},mid=Number(f.btc_mid_usd);
  const byWallet={};let positions=0;
  for(const [cat,a] of Object.entries(accounts))for(const [wallet,p] of Object.entries(a.positions||{})){(byWallet[wallet]??=[]).push({cat,p});positions++}
  const counts={LONG:0,SHORT:0,FLAT:0};Object.values(dirs).forEach(x=>{counts[x]=(counts[x]||0)+1});
  document.getElementById('followSummary').innerHTML=[
   ['전체 지갑',f.catalog_wallet_count??ws.length],['관측 성공',f.observed_wallet_count??Object.keys(dirs).length],['API 오류',f.errors?.length||0],['롱 / 숏 / 관망',counts.LONG+' / '+counts.SHORT+' / '+counts.FLAT],['PAPER 추종',Object.keys(byWallet).length+'명 · '+positions+'건']
  ].map(([k,v])=>'<div class="card"><h3>'+k+'</h3><div class="big">'+esc(v)+'</div></div>').join('');
  document.getElementById('followRows').innerHTML=ws.map(w=>{
   const entries=byWallet[w.address]||[],d=dirs[w.address];
   const detail=entries.length?entries.map(({cat,p})=>{
    const price=mid*(p.side==='LONG'?0.9997:1.0003);
    const gross=(price-Number(p.entry))*Number(p.qty)*(p.side==='LONG'?1:-1);
    const est=gross-mid*Number(p.qty)*0.0005-Number(p.fee||0);
    return '<div><b>'+esc(names[cat]||cat)+'</b> '+esc(side(p.side))+' · '+usd(p.entry)+' → '+usd(mid)+' · <span class="'+(est>=0?'green':'red')+'">'+usd(est)+'</span> · '+esc(time(p.entry_at))+'</div>'
   }).join(''):'<span class="muted">'+(d==='FLAT'?'포지션 없음':d?'미추종':'미관측')+'</span>';
   return '<tr><td class="mono">'+esc(short(w.address))+'</td><td>'+esc((w.categories||[]).map(x=>names[x]||x).join(', ')||'관찰')+'</td><td>'+esc(side(d))+'</td><td colspan="5">'+detail+'</td></tr>';
  }).join('');
  document.getElementById('followMeta').textContent='원본 관측 '+time(f.generated_at)+' · PAPER 평가 '+time(cp.updated_at)+' · 원본 API 조회는 주기 실행, 화면 갱신은 60초';
  const trades=Object.entries(accounts).flatMap(([cat,a])=>(a.closed||[]).map(t=>({...t,cat}))).sort((a,b)=>String(b.exit_at).localeCompare(String(a.exit_at)));
  document.getElementById('categoryStats').innerHTML=Object.entries(accounts).map(([cat,a])=>'<div class="card"><h3>'+esc(names[cat]||cat)+'</h3><div class="big '+(a.net_pnl_usd>=0?'green':'red')+'">'+usd(a.net_pnl_usd)+'</div><div class="metric">승률 '+(a.win_rate_pct==null?'표본 없음':fmt(a.win_rate_pct)+'%')+' · 종료 '+fmt(a.closed_count)+'건 · MDD '+fmt(a.mdd_pct)+'% · PF '+(a.profit_factor==null?'—':fmt(a.profit_factor))+'</div></div>').join('');
  document.getElementById('categoryHistoryRows').innerHTML=trades.slice(0,200).map(t=>'<tr><td>'+esc(names[t.cat]||t.cat)+'</td><td class="mono">'+esc(short(t.wallet))+'</td><td>'+esc(side(t.side))+'</td><td>'+esc(time(t.entry_at))+'</td><td>'+esc(time(t.exit_at))+'</td><td>'+ (t.entry_price==null?'기존 기록':usd(t.entry_price))+'</td><td>'+(t.exit_price==null?'기존 기록':usd(t.exit_price))+'</td><td>'+esc(t.reason)+'</td><td class="'+(t.pnl_usd>=0?'green':'red')+'">'+usd(t.pnl_usd)+'</td></tr>').join('');
  document.getElementById('categoryHistoryMeta').textContent='유형별 최대 300건 보존 · 화면 최근 200건 · 총 '+trades.length+'건 · 기존 거래의 진입가/시간은 과거 기록에 없어 복원하지 않음';
 }catch(e){document.getElementById('followMeta').textContent='데이터 조회 실패: '+e.message}
 finally{loading=false}
}
document.addEventListener('DOMContentLoaded',install);if(document.readyState!=='loading')install();setInterval(refresh,60000);window.addEventListener('btcflow:refresh',refresh);
})();