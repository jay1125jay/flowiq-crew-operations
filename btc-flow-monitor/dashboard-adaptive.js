(() => {
  const labels = {WHALE_COPY:'WHALE COPY · 고래 대조군', SMART_MONEY:'SMART MONEY · 우수 트레이더', MARKET_STRUCTURE:'MARKET STRUCTURE · 가격 구조', DERIVATIVES:'DERIVATIVES · 파생시장', FIXED_ENSEMBLE:'FIXED ENSEMBLE · 고정 조합', ADAPTIVE_META:'ADAPTIVE META · 적응형 조합'};
  const fmt = (x,d=2) => x == null || !Number.isFinite(Number(x)) ? '—' : Number(x).toLocaleString('ko-KR',{maximumFractionDigits:d});
  const esc = x => String(x ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const local=window.BTC_LOCAL_RUNTIME===true;
  const connection=new URLSearchParams(location.hash.slice(1));
  const remote=!local&&(connection.has('pc')||connection.has('key'));
  const realtime=local||remote;
  const endpoint=connection.get('pc')||'', key=connection.get('key')||'';
  const validRemote=/^https:\/\/[a-z0-9-]+\.trycloudflare\.com$/.test(endpoint)&&/^[A-Za-z0-9_-]{43}$/.test(key);
  let busy=false, shareBusy=false, sharedUrl='';
  async function phoneLink(){
    if(!local||shareBusy||!document.getElementById('phoneShareStatus'))return;
    shareBusy=true;
    try{
      const r=await fetch('/api/phone-share',{cache:'no-store',signal:AbortSignal.timeout(4000)});
      if(!r.ok)throw Error();
      const d=await r.json();
      const ready=d.status==='LINK_READY'&&typeof d.url==='string'&&d.url.startsWith('https://jay1125jay.github.io/flowiq-crew-operations/btc-flow-monitor/dashboard.html#');
      document.getElementById('phoneShareStatus').textContent=ready?'휴대폰 카메라로 QR을 스캔하세요. PC와 같은 6개 계좌를 기존 대시보드에서 봅니다.':d.status==='STARTING'?'휴대폰 연결 준비 중 · 첫 실행은 연결 프로그램을 내려받습니다.':'휴대폰 연결 없음 · PC를 재실행하세요. 로컬 모의계좌는 계속 작동합니다.';
      document.getElementById('phoneShareLink').hidden=!ready;
      document.getElementById('phoneQr').hidden=!ready;
      if(ready&&sharedUrl!==d.url){sharedUrl=d.url;document.getElementById('phoneShareLink').href=d.url;document.getElementById('phoneQr').src='/api/phone-qr?v='+Date.now();}
      if(!ready)sharedUrl='';
    }catch(e){document.getElementById('phoneShareStatus').textContent='PC 연결 끊김 · 모의거래 상태 확인 필요';document.getElementById('phoneShareLink').hidden=true;document.getElementById('phoneQr').hidden=true;sharedUrl='';}
    finally{shareBusy=false;}
  }

  function install() {
    const home=document.getElementById('home');
    if(!home || document.getElementById('adaptivePanel')) return;
    const panel=document.createElement('div');panel.className='panel';panel.id='adaptivePanel';
    panel.innerHTML='<div class="head"><h2>6개 엔진 독립 모의거래 경쟁</h2><div class="muted" id="adaptiveStatus">데이터 확인 중</div></div><div class="pad"><div class="notice">PAPER ONLY(모의거래 전용) · 수익성 미검증 · 공통 초기자본 $1,000 / 최대 노출 $500 / 비교 계좌 1배 · 기존 5배·10배 계좌 별도 유지</div><div class="tablewrap"><table class="table"><thead><tr><th>엔진</th><th>현재 신호</th><th>신호 강도</th><th>자산</th><th>순손익</th><th>수익률</th><th>PF<br>손익비</th><th>MDD<br>최대낙폭</th><th>승률</th><th>종료 거래</th><th>거래당 기대값</th><th>미실현 손익</th><th>수수료</th></tr></thead><tbody id="adaptiveRows"></tbody></table></div><div class="muted" id="adaptiveWeights"></div><div class="muted" id="adaptiveCadence"></div><div class="muted">신호 강도는 승률 예측이 아닙니다. 비용은 수수료·슬리피지(체결 가격 차이)·추정 펀딩비를 반영합니다. 청산은 관측 가격 기준의 근사치입니다. 시장 전체 청산량·롱/숏 비율은 미수집입니다.</div></div>';
    home.prepend(panel);
    if(realtime){
      const note=document.createElement('div');note.className='notice';note.id='localRuntimeNotice';
      note.textContent='PC 연결 모드 · 홈의 6개 엔진은 PC와 동일한 모의계좌입니다. 나머지 메뉴는 GitHub 저장 기록이며 PC 실시간 계좌가 아닙니다. PC 종료·절전 시 연결이 끊깁니다.';
      document.querySelector('#nav').before(note);
      document.querySelectorAll('.page h2').forEach(h=>{if(!panel.contains(h)&&h.closest('.page').id!=='chart')h.textContent+=' · 저장 기록';});
    }
    if(local){
      const box=document.createElement('div');box.className='panel';box.id='phoneSharePanel';
      box.innerHTML='<div class="head"><h2>폰에서 같은 계좌 보기</h2></div><div class="pad"><div id="phoneShareStatus">연결 준비 중</div><img id="phoneQr" hidden alt="휴대폰 연결 QR" style="width:240px;max-width:100%;background:white;margin:12px 0"><div><a id="phoneShareLink" hidden target="_blank" rel="noreferrer noopener" style="color:#49dca0">휴대폰용 대시보드 열기</a></div><button id="phoneCopy" class="refresh" type="button">연결 링크 복사</button><div class="muted">PC 재실행 시 새 QR 사용 · 링크를 가진 사람은 모의계좌를 조회할 수 있습니다. · 실제 주문 없음</div></div>';
      home.prepend(box);
      document.getElementById('phoneCopy').onclick=async()=>{if(sharedUrl){try{await navigator.clipboard.writeText(sharedUrl);document.getElementById('phoneShareStatus').textContent='연결 링크 복사 완료';}catch(e){document.getElementById('phoneShareStatus').textContent='QR을 스캔하거나 연결 링크를 길게 눌러 복사하세요.';}}};
      phoneLink();setInterval(phoneLink,3000);
    }
    document.getElementById('refreshBtn')?.addEventListener('click',refresh);
    refresh();
  }
  async function refresh() {
    if(busy || !document.getElementById('adaptiveStatus')) return;
    busy=true;
    const status=document.getElementById('adaptiveStatus');
    try {
      if(remote&&!validRemote)throw Error('잘못된 PC 연결 링크 · PC의 새 QR을 스캔하세요');
      const r=await fetch(remote?endpoint+'/api/status':local?'/api/status':'./data/adaptive-meta.json?v='+Date.now(),{cache:'no-store',credentials:'omit',referrerPolicy:'no-referrer',headers:remote?{Authorization:'Bearer '+key}:{},signal:AbortSignal.timeout(4000)});
      if(!r.ok) throw Error('HTTP '+r.status);
      const payload=await r.json();
      if(realtime&&(payload.paper_only!==true||payload.real_trading_enabled!==false)) throw Error('실시간 안전 플래그 불일치');
      const d=realtime?payload.competition:payload;
      if(!d||!d.accounts||Object.keys(d.accounts).length!==6) throw Error('실시간 데이터 수집 대기');
      if(d.paper_only!==true || d.real_trading_enabled!==false) throw Error('모의거래 안전 플래그 불일치');
      if(d.schema_version!==3) throw Error('새 경쟁 계좌 생성 대기 · 이전 형식 데이터');
      const age=(Date.now()-Date.parse(d.last_observation_at))/1000;
      const stale=(realtime&&!payload.healthy)||!Number.isFinite(age)||age<0||age>(realtime?5:900);
      const side={LONG:'LONG · 상승',SHORT:'SHORT · 하락',WAIT:'WAIT · 관망'};
      document.getElementById('adaptiveRows').innerHTML=Object.entries(labels).map(([key,label])=>{
        const a=d.accounts?.[key],s=d.decisions?.[key];
        if(!a||!s) throw Error('계좌 누락: '+key);
        const pf=a.profit_factor_status==='NO_LOSSES'?'손실 표본 없음':fmt(a.profit_factor);
        return '<tr><td>'+label+'</td><td>'+esc(stale?'지연 · 판단 보류':side[s.signal]||s.signal)+'</td><td>'+fmt(stale?null:s.confidence)+(stale?'':'%')+'</td><td>$'+fmt(a.equity_usd)+'</td><td class="'+(a.net_pnl_usd>=0?'green':'red')+'">$'+fmt(a.net_pnl_usd)+'</td><td>'+fmt(a.return_pct)+'%</td><td>'+pf+'</td><td>'+fmt(a.mdd_pct)+'%</td><td>'+fmt(a.win_rate_pct)+(a.win_rate_pct==null?'':'%')+'</td><td>'+fmt(a.closed_count,0)+'</td><td>$'+fmt(a.expectancy_usd)+'</td><td>$'+fmt(a.unrealized_pnl_usd)+'</td><td>$'+fmt(a.fees_usd)+'</td></tr>';
      }).join('');
      status.textContent=(stale?'데이터 지연 · 마지막 저장 결과':'최근 저장 결과')+' · '+new Date(d.last_observation_at).toLocaleString('ko-KR')+' · 시장 국면 '+({TREND_UP:'상승 추세',TREND_DOWN:'하락 추세',RANGE:'횡보',HIGH_VOL:'높은 변동성',LOW_VOL:'낮은 변동성'}[d.regime]||d.regime);
      if(realtime)status.textContent=(stale?'실시간 연결 대기 · 판단 보류':'PC 실시간 연결 정상')+' · BTC $'+fmt(payload.btc_mid_usd)+' · 가격 시각 '+new Date(payload.quote_at).toLocaleTimeString('ko-KR')+' · 트레이더 수집 '+new Date(payload.source_at).toLocaleTimeString('ko-KR');
      status.className=stale?'red':'muted';
      const cadence=d.data_quality?.continuity;
      const cadenceNode=document.getElementById('adaptiveCadence');
      cadenceNode.textContent=cadence ? '수집 간격: 최근 '+fmt(cadence.last_gap_seconds/60)+'분 / 최대 '+fmt(cadence.max_gap_seconds/60)+'분 · 15분 초과 공백 '+fmt(cadence.gap_count,0)+'회 · '+(cadence.status==='GAPPED'?'연속 관측 불충분 · 성과 해석 주의':cadence.status==='WARMUP'?'관측 시작':'최근 관측 간격 정상')+' · 5분 예약은 실행 보장이 아닙니다.' : '수집 간격 검증 대기';
      if(realtime)cadenceNode.textContent='판단 목표 1초 · 트레이더 수집 목표 60초 · 처리 '+fmt(payload.ticks,0)+'회 · 데이터 지연 시 판단 보류 · PC 종료/절전 시 중단';
      cadenceNode.className=cadence?.status==='GAPPED'?'red':'muted';
      document.getElementById('adaptiveWeights').textContent='적응형 비중: '+Object.entries(d.engine_weights).map(([k,v])=>labels[k]+' '+fmt(v*100)+'%').join(' / ')+' · 최소 30건 종료 전 기본 비중 유지 · 경쟁 시작 '+new Date(d.started_at).toLocaleString('ko-KR');
    } catch(e) {
      status.textContent=(realtime?'PC 연결 끊김 또는 준비 중 · 판단 보류: ':'비교표 확인 불가: ')+e.message;status.className='red';
      document.getElementById('adaptiveRows').textContent='';
      document.getElementById('adaptiveWeights').textContent='';
      document.getElementById('adaptiveCadence').textContent='';
    } finally {busy=false;}
  }
  document.addEventListener('DOMContentLoaded',install);
  if(document.readyState!=='loading') install();
  setInterval(refresh,realtime?1000:60000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
})();
