const fmtWon = n => `${Math.round(Number(n || 0)).toLocaleString('ko-KR')}원`;
const fmtPct = n => `${Number(n || 0) >= 0 ? '+' : ''}${Number(n || 0).toFixed(2)}%`;
const fmtPrice = n => Number(n || 0).toLocaleString('ko-KR', {maximumFractionDigits: 8});
const fmtTradeValue = n => `${(Number(n || 0) / 100000000).toFixed(1)}억`;
const shortTime = iso => {
  if (!iso) return '-';
  const d = new Date(iso);
  return d.toLocaleString('ko-KR', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});
};

function statusClass(status){ return status === 'PASS' ? 'ok' : status === 'PARTIAL' ? 'warn' : 'bad'; }
function signalHint(c){
  if(c.overextended) return '추격금지';
  if(!c.breakout_confirmed) return '돌파대기';
  if(!c.breakout_volume_confirmed) return '거래량대기';
  if(!c.price_holds_breakout) return '지지확인중';
  if(c.stop_valid === false) return '손익비불가';
  return c.status === 'TRIGGER' ? '진입조건완료' : '점수대기';
}

async function load(){
  try{
    const res = await fetch(`./data/state.json?t=${Date.now()}`, {cache:'no-store'});
    if(!res.ok) throw new Error(`state ${res.status}`);
    const s = await res.json();
    render(s);
  }catch(err){
    document.getElementById('statusStrip').innerHTML = `<div class="status-item"><span>데이터</span><strong class="bad">불러오기 실패</strong></div>`;
    console.error(err);
  }
}

function render(s){
  const a = s.account || {};
  const e = s.engine || {};
  const r = s.risk || {};
  const positions = s.positions || [];
  const trades = [...(s.trades || [])].reverse().slice(0,8);
  const candidates = s.candidates || [];

  document.getElementById('statusStrip').innerHTML = `
    <div class="status-item"><span>업비트 KRW 스캔</span><strong class="${statusClass(e.status)}">${e.status || 'INIT'}</strong></div>
    <div class="status-item"><span>진입전략</span><strong>${s.strategy_version || 'v1_LEGACY'}</strong></div>
    <div class="status-item"><span>신규진입</span><strong class="${r.daily_stop || r.btc_entry_gate === false ? 'bad':'ok'}">${r.daily_stop ? '일손실차단' : r.btc_entry_gate === false ? 'BTC위험차단' : '허용'}</strong></div>
    <div class="status-item"><span>오픈리스크</span><strong>${fmtWon(r.open_risk_krw || 0)} / ${Number(r.max_open_risk_pct || 0).toFixed(1)}%</strong></div>
    <div class="status-item"><span>최종 갱신</span><strong>${shortTime(s.updated_at)}</strong></div>`;

  document.getElementById('metrics').innerHTML = `
    <article class="metric"><div class="metric-label">현재자산</div><strong>${fmtWon(a.equity)}</strong><small class="${a.return_pct >= 0 ? 'positive':'negative'}">${fmtPct(a.return_pct)}</small></article>
    <article class="metric"><div class="metric-label">실현손익</div><strong class="${a.realized_pnl >= 0 ? 'positive':'negative'}">${fmtWon(a.realized_pnl)}</strong><small>오늘 ${fmtWon(r.today_realized_pnl || 0)}</small></article>
    <article class="metric"><div class="metric-label">승률</div><strong>${Number(a.win_rate || 0).toFixed(1)}%</strong><small>${a.wins || 0}승 ${a.losses || 0}패 · ${a.trades || 0}회</small></article>
    <article class="metric"><div class="metric-label">오픈 포지션</div><strong>${positions.length}</strong><small>스캔 ${e.markets_scanned || 0}개 · 후보 ${e.candidates_found || 0}개</small></article>`;

  document.getElementById('candidateTable').innerHTML = `
    <thead><tr><th>#</th><th>코인</th><th>현재가</th><th>24H</th><th>거래대금</th><th>거래량배수</th><th>RSI</th><th>점수</th><th>상태</th><th>진입확인</th><th>손절 / 목표</th></tr></thead>
    <tbody>${candidates.map((c,i)=>`<tr>
      <td>${i+1}</td><td class="symbol">${c.symbol}<small>${c.korean_name || ''}</small></td><td>${fmtPrice(c.price)}</td>
      <td class="${c.change_pct >= 0 ? 'positive':'negative'}">${fmtPct(c.change_pct)}</td><td>${fmtTradeValue(c.trade_value_24h)}</td>
      <td>${Number(c.volume_ratio).toFixed(2)}x</td><td>${Number(c.rsi14).toFixed(1)}</td><td><b class="score">${c.score}</b></td>
      <td><span class="badge ${String(c.status).toLowerCase()}">${c.status}</span>${c.upper_wick_risk || c.collapse_risk ? '<div class="risk">위험감지</div>':''}</td>
      <td><b>${signalHint(c)}</b><div class="risk">돌파 ${c.breakout_confirmed ? '✓':'×'} · 거래량 ${c.breakout_volume_confirmed ? '✓':'×'} · 손절폭 ${c.stop_valid === false ? '×':'✓'} · 추격 ${c.overextended ? '×':'✓'}</div></td>
      <td>${fmtPrice(c.proposed_stop || c.support_price)} / ${fmtPrice(c.proposed_target || c.breakout_price)}<div class="risk">${Number(c.stop_distance_pct || 0).toFixed(2)}% risk · ${Number(c.target_r || 0).toFixed(1)}R</div></td></tr>`).join('') || '<tr><td colspan="11" class="empty">현재 기대값 조건을 통과한 후보가 없습니다.</td></tr>'}</tbody>`;

  document.getElementById('positions').innerHTML = positions.map(p=>`<div class="position">
    <div class="position-top"><div><strong>${p.symbol}/KRW</strong><small>${p.korean_name || ''} · 진입점수 ${p.entry_score} · ${p.strategy_version || 'v1_LEGACY'}</small></div><b class="${p.pnl_pct >= 0 ? 'positive':'negative'}">${fmtPct(p.pnl_pct)}</b></div>
    <div class="position-grid"><span>진입가<b>${fmtPrice(p.entry_price)}</b></span><span>현재가<b>${fmtPrice(p.current_price)}</b></span><span>손절선<b>${fmtPrice(p.stop_price)}</b></span><span>목표가<b>${fmtPrice(p.target_price || p.highest_price)}</b></span></div>
    ${p.risk_amount ? `<div class="risk">계좌 위험 ${fmtWon(p.risk_amount)} · ${Number(p.risk_pct_equity || 0).toFixed(2)}% · 최고 ${Number(p.max_r || 0).toFixed(2)}R</div>` : ''}
  </div>`).join('') || '<div class="empty">현재 가상 보유 포지션 없음</div>';

  document.getElementById('trades').innerHTML = trades.map(t=>`<div class="trade"><time>${shortTime(t.time)}</time><div><strong>${t.symbol} · ${t.side}</strong><span>${t.reason} · ${t.strategy_version || 'v1_LEGACY'}</span></div><b class="${t.pnl_pct > 0 ? 'positive': t.pnl_pct < 0 ? 'negative':''}">${t.side === 'SELL' ? fmtPct(t.pnl_pct) : fmtWon(t.gross_value)}</b></div>`).join('') || '<div class="empty">아직 PAPER 거래 기록이 없습니다.</div>';
}

load();