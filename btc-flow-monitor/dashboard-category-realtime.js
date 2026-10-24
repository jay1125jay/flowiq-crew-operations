(()=>{
  const names={WHALE:'고래',HIGH_WIN_RATE:'고승률',HIGH_PROFIT:'고수익',CONSISTENT:'안정형',SCALPER:'스캘퍼',SWING:'스윙'};
  const fmt=(x,d=2)=>x==null||!Number.isFinite(Number(x))?'—':Number(x).toLocaleString('ko-KR',{maximumFractionDigits:d});
  const local=window.BTC_LOCAL_RUNTIME===true;
  const connection=new URLSearchParams(location.hash.slice(1));
  const remote=!local&&(connection.has('pc')||connection.has('key'));
  const realtime=local||remote;
  if(!realtime)return;
  const endpoint=connection.get('pc')||'',key=connection.get('key')||'';
  const validRemote=/^https:\/\/[a-z0-9-]+\.trycloudflare\.com$/.test(endpoint)&&/^[A-Za-z0-9_-]{43}$/.test(key);
  let busy=false;
  function install(){
    const home=document.getElementById('home');if(!home||document.getElementById('categoryRealtimePanel'))return;
    const p=document.createElement('div');p.className='panel';p.id='categoryRealtimePanel';
    p.innerHTML='<div class="head"><h2>PC 6유형 실시간 테스트 · 각 300만원 · 10X</h2><div class="muted" id="categoryRealtimeStatus">연결 확인 중</div></div><div class="pad"><div class="notice">PAPER ONLY · Adaptive 계좌와 완전 별도 기록 · 가격 평가는 1초 · 진입/반전 판단은 새 트레이더 소스가 들어올 때만 수행</div><div class="tablewrap"><table class="table"><thead><tr><th>유형</th><th>자산</th><th>순손익</th><th>수익률</th><th>MDD</th><th>실질 가용자금</th><th>총 포지션</th><th>오픈</th><th>종료</th><th>승률</th><th>PF</th><th>청산</th></tr></thead><tbody id="categoryRealtimeRows"></tbody></table></div><div class="muted" id="categoryRealtimeMeta"></div></div>';
    const adaptive=document.getElementById('adaptivePanel');if(adaptive&&adaptive.parentNode===home)adaptive.after(p);else home.prepend(p);
    refresh();
  }
  async function refresh(){
    if(busy||!document.getElementById('categoryRealtimeStatus'))return;busy=true;
    const status=document.getElementById('categoryRealtimeStatus');
    try{
      if(remote&&!validRemote)throw Error('잘못된 PC 연결 링크');
      const r=await fetch(remote?endpoint+'/api/status':'/api/status',{cache:'no-store',credentials:'omit',referrerPolicy:'no-referrer',headers:remote?{Authorization:'Bearer '+key}:{},signal:AbortSignal.timeout(4000)});
      if(!r.ok)throw Error('HTTP '+r.status);const payload=await r.json();
      if(payload.paper_only!==true||payload.real_trading_enabled!==false)throw Error('PAPER 안전 플래그 불일치');
      const d=payload.category_competition;if(!d||!d.accounts)throw Error('6유형 계좌 초기 수집 대기');
      if(d.paper_only!==true||d.real_trading_enabled!==false||d.account_count!==6)throw Error('6유형 계좌 검증 실패');
      const rows=Object.entries(d.accounts).filter(([k,a])=>a.leverage===10);
      if(rows.length!==6||rows.some(([k,a])=>a.starting_equity_krw!==3000000))throw Error('300만원·10X 설정 불일치');
      document.getElementById('categoryRealtimeRows').innerHTML=rows.map(([key,a])=>'<tr><td><b>'+(names[a.category]||a.category)+'</b></td><td>'+fmt(a.equity_krw)+'원</td><td class="'+(Number(a.net_pnl_krw)>=0?'green':'red')+'">'+fmt(a.net_pnl_krw)+'원</td><td>'+fmt(a.return_pct)+'%</td><td>'+fmt(a.mdd_pct)+'%</td><td>'+fmt(a.free_equity_krw)+'원</td><td>'+fmt(a.total_notional_krw)+'원</td><td>'+fmt(a.open_count,0)+'</td><td>'+fmt(a.closed_count,0)+'</td><td>'+(a.win_rate_pct==null?'표본 없음':fmt(a.win_rate_pct)+'%')+'</td><td>'+(a.profit_factor==null?'—':fmt(a.profit_factor))+'</td><td>'+fmt(a.liquidations,0)+'</td></tr>').join('');
      const stale=!payload.category_healthy;
      status.textContent=(stale?'PC 6유형 연결 대기':'PC 6유형 실시간 정상')+' · BTC $'+fmt(payload.btc_mid_usd)+' · 평가 '+(d.updated_at?new Date(d.updated_at).toLocaleTimeString('ko-KR'):'—');
      status.className=stale?'red':'muted';
      document.getElementById('categoryRealtimeMeta').textContent='PC 별도 계좌 파일 category-paper-realtime.json · 소스 '+(payload.category_source_at?new Date(payload.category_source_at).toLocaleTimeString('ko-KR'):'대기')+' · 새 소스 반영 '+fmt(payload.category_source_events,0)+'회 · Adaptive 성과와 합산하지 않음';
    }catch(e){status.textContent='PC 6유형 확인 불가: '+e.message;status.className='red';document.getElementById('categoryRealtimeRows').textContent='';document.getElementById('categoryRealtimeMeta').textContent='';}
    finally{busy=false;}
  }
  document.addEventListener('DOMContentLoaded',install);if(document.readyState!=='loading')install();
  setInterval(refresh,1000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
})();
