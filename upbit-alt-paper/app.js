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
    render(await res.json());
  }catch(err){
    document.getElementById('statusStrip').innerHTML = `<div class="status-item"><span>데이터</span><strong class="bad">불러오기 실패</strong></div>`;
    console.error(err);
  }
}

function render(s){
  const a = s.account || {};
  const e = s.engine || {};
  const r = s.risk || {};
  const p = s.performance || {};
  const positions = s.positions || [];
  const trades = [...(s.trades || [])].reverse().slice(0,8);
  const candidates = s.candidates || [];
  const entryBlocked = r.daily_stop || r.btc_entry_gate === false;

  document.getElementById('statusStrip').innerHTML = `
    <div class="status-item"><span>업비트 KRW 스캔</span><strong class="${statusClass(e.status)}">${e.status || 'INIT'}</strong></div>
    <div class="status-item"><span>진입전략</span><strong>${s.strategy_version || 'v1_LEGACY'}</strong></div>
    <div class="status-item"><span>신규진입</span><strong class="${entryBlocked ? 'bad':'ok'}">${r.daily_stop ? '일손실차단' : r.btc_entry_gate === false ? 'BTC위험차단' : '허용'}</strong></div>
    <div class="status-item"><span>리스크모드</span><strong class="${r.defensive_mode ? 'warn':'ok'}">${r.defensive_mode ? 'DEFENSIVE 50%' : 'NORMAL'}</strong></div>
    <div class="status-item"><span>오픈리스크</span><strong>${fmtWon(r.open_risk_krw || 0)} / ${Number(r.max_open_risk_pct || 0).toFixed(1)}%</strong></div>
    <div class="status-item"><span>최종 갱신</span><strong>${shortTime(s.updated_at)}</strong></div>`;

  document.getElementById('metrics').innerHTML = `
    <article class="metric"><div class="metric-label">전체 PAPER 자산</div><strong>${fmtWon(a.equity)}</strong><small class="${a.return_pct >= 0 ? 'positive':'negative'}">${fmtPct(a.return_pct)} · 구전략 포함</small></article>
    <article class="metric"><div class="metric-label">현 전략 순손익</div><strong class="${Number(p.net_pnl || 0) >= 0 ? 'positive':'negative'}">${fmtWon(p.net_pnl || 0)}</strong><small>${p.closed_trades || 0}회 · 승률 ${Number(p.win_rate || 0).toFixed(1)}%</small></article>
    <article class="metric"><div class="metric-label">Profit Factor</div><strong>${Number(p.profit_factor || 0).toFixed(2)}</strong><small>기대값 ${fmtWon(p.expectancy_krw || 0)} / 거래 · 평균 ${Number(p.avg_r || 0).toFixed(2)}R</small></article>
    <article class="metric"><div class="metric-label">현 전략 MDD</div><strong>${Number(p.max_drawdown_pct || 0).toFixed(2)}%</strong><small>${p.sample_ready ? '표본 평가 활성' : `${p.closed_trades || 0}/20 · 표본 수집 중`} · 포지션 ${positions.length}</small></article>`;

  document.getElementById('candidateTable').innerHTML = `
    <thead><tr><th>#</th><th>코인</th><th>현재가</th><th>24H</th><th>거래대금</th><th>거래량배수</th><th>RSI</th><th>점수</th><th>상태</th><th>진입확인</th><th>손절 / 목표</th></tr></thead>
    <tbody>${candidates.map((c,i)=>`<tr>
      <td>${i+1}</td><td class="symbol">${c.symbol}<small>${c.korean_name || ''}</small></td><td>${fmtPrice(c.price)}</td>
      <td class="${c.change_pct >= 0 ? 'positive':'negative'}">${fmtPct(c.change_pct)}</td><td>${fmtTradeValue(c.trade_value_24h)}</td>
      <td>${Number(c.volume_ratio).toFixed(2)}x</td><td>${Number(c.rsi14).toFixed(1)}</td><td><b class="score">${c.score}</b></td>
      <td><span class="badge ${String(c.status).toLowerCase()}">${c.status}</span>${c.upper_wick_risk || c.collapse_risk ? '<div class="risk">위험감지</div>':''}</td>
      <td><b>${signalHint(c)}</b><div class="risk">돌파 ${c.breakout_confirmed ? '✓':'×'} · 거래량 ${c.breakout_volume_confirmed ? '✓':'×'} · 손절폭 ${c.stop_valid === false ? '×':'✓'} · 추격 ${c.overextended ? '×':'✓'}</div></td>
      <td>${fmtPrice(c.proposed_stop || c.support_price)} / ${fmtPrice(c.proposed_target || c.breakout_price)}<div class="risk">${Number(c.stop_distance_pct || 0).toFixed(2)}% risk · ${Number(c.target_r || 0).toFixed(1)}R</div></td></tr>`).join('') || '<tr><td colspan="11" class="empty">현재 기대값 조건을 통과한 후보가 없습니다.</td></tr>'}</tbody>`;

  document.getElementById('positions').innerHTML = positions.map(pos=>`<div class="position">
    <div class="position-top"><div><strong>${pos.symbol}/KRW</strong><small>${pos.korean_name || ''} · 진입점수 ${pos.entry_score} · ${pos.strategy_version || 'v1_LEGACY'}</small></div><b class="${pos.pnl_pct >= 0 ? 'positive':'negative'}">${fmtPct(pos.pnl_pct)}</b></div>
    <div class="position-grid"><span>진입가<b>${fmtPrice(pos.entry_price)}</b></span><span>현재가<b>${fmtPrice(pos.current_price)}</b></span><span>손절선<b>${fmtPrice(pos.stop_price)}</b></span><span>목표가<b>${fmtPrice(pos.target_price || pos.highest_price)}</b></span></div>
    ${pos.risk_amount ? `<div class="risk">계좌 위험 ${fmtWon(pos.risk_amount)} · ${Number(pos.risk_pct_equity || 0).toFixed(2)}% · 최고 ${Number(pos.max_r || 0).toFixed(2)}R</div>` : ''}
  </div>`).join('') || '<div class="empty">현재 가상 보유 포지션 없음</div>';

  document.getElementById('trades').innerHTML = trades.map(t=>`<div class="trade"><time>${shortTime(t.time)}</time><div><strong>${t.symbol} · ${t.side}</strong><span>${t.reason} · ${t.strategy_version || 'v1_LEGACY'}${t.r_multiple != null ? ` · ${Number(t.r_multiple).toFixed(2)}R` : ''}</span></div><b class="${t.pnl_pct > 0 ? 'positive': t.pnl_pct < 0 ? 'negative':''}">${t.side === 'SELL' ? fmtPct(t.pnl_pct) : fmtWon(t.gross_value)}</b></div>`).join('') || '<div class="empty">아직 PAPER 거래 기록이 없습니다.</div>';
}

load();