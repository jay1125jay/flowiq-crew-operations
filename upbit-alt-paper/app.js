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
  const positions = s.positions || [];
  const trades = [...(s.trades || [])].reverse().slice(0,8);
  const candidates = s.candidates || [];

  document.getElementById('statusStrip').innerHTML = `
    <div class="status-item"><span>업비트 KRW 스캔</span><strong class="${statusClass(e.status)}">${e.status || 'INIT'}</strong></div>
    <div class="status-item"><span>실거래 주문</span><strong class="warn">잠금 · PAPER ONLY</strong></div>
    <div class="status-item"><span>최종 갱신</span><strong>${shortTime(s.updated_at)}</strong></div>`;

  document.getElementById('metrics').innerHTML = `
    <article class="metric"><div class="metric-label">현재자산</div><strong>${fmtWon(a.equity)}</strong><small class="${a.return_pct >= 0 ? 'positive':'negative'}">${fmtPct(a.return_pct)}</small></article>
    <article class="metric"><div class="metric-label">실현손익</div><strong class="${a.realized_pnl >= 0 ? 'positive':'negative'}">${fmtWon(a.realized_pnl)}</strong><small>현금 ${fmtWon(a.cash)}</small></article>
    <article class="metric"><div class="metric-label">승률</div><strong>${Number(a.win_rate || 0).toFixed(1)}%</strong><small>${a.wins || 0}승 ${a.losses || 0}패 · ${a.trades || 0}회</small></article>
    <article class="metric"><div class="metric-label">오픈 포지션</div><strong>${positions.length}</strong><small>스캔 ${e.markets_scanned || 0}개 · 후보 ${e.candidates_found || 0}개</small></article>`;

  document.getElementById('candidateTable').innerHTML = `
    <thead><tr><th>#</th><th>코인</th><th>현재가</th><th>24H</th><th>거래대금</th><th>거래량배수</th><th>RSI</th><th>점수</th><th>상태</th><th>돌파 / 지지</th></tr></thead>
    <tbody>${candidates.map((c,i)=>`<tr>
      <td>${i+1}</td><td class="symbol">${c.symbol}<small>${c.korean_name || ''}</small></td><td>${fmtPrice(c.price)}</td>
      <td class="${c.change_pct >= 0 ? 'positive':'negative'}">${fmtPct(c.change_pct)}</td><td>${fmtTradeValue(c.trade_value_24h)}</td>
      <td>${Number(c.volume_ratio).toFixed(2)}x</td><td>${Number(c.rsi14).toFixed(1)}</td><td><b class="score">${c.score}</b></td>
      <td><span class="badge ${String(c.status).toLowerCase()}">${c.status}</span>${c.upper_wick_risk || c.collapse_risk ? '<div class="risk">위험감지</div>':''}</td>
      <td>${fmtPrice(c.breakout_price)} / ${fmtPrice(c.support_price)}</td></tr>`).join('') || '<tr><td colspan="10" class="empty">현재 조건을 통과한 급등 후보가 없습니다.</td></tr>'}</tbody>`;

  document.getElementById('positions').innerHTML = positions.map(p=>`<div class="position">
    <div class="position-top"><div><strong>${p.symbol}/KRW</strong><small>${p.korean_name || ''} · 진입점수 ${p.entry_score}</small></div><b class="${p.pnl_pct >= 0 ? 'positive':'negative'}">${fmtPct(p.pnl_pct)}</b></div>
    <div class="position-grid"><span>진입가<b>${fmtPrice(p.entry_price)}</b></span><span>현재가<b>${fmtPrice(p.current_price)}</b></span><span>손절선<b>${fmtPrice(p.stop_price)}</b></span><span>최고가<b>${fmtPrice(p.highest_price)}</b></span></div>
  </div>`).join('') || '<div class="empty">현재 가상 보유 포지션 없음</div>';

  document.getElementById('trades').innerHTML = trades.map(t=>`<div class="trade"><time>${shortTime(t.time)}</time><div><strong>${t.symbol} · ${t.side}</strong><span>${t.reason}</span></div><b class="${t.pnl_pct > 0 ? 'positive': t.pnl_pct < 0 ? 'negative':''}">${t.side === 'SELL' ? fmtPct(t.pnl_pct) : fmtWon(t.gross_value)}</b></div>`).join('') || '<div class="empty">아직 PAPER 거래 기록이 없습니다.</div>';
}

load();
