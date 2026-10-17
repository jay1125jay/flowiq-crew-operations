import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import WebSocket from 'ws';

const PORT=Number(process.env.PORT||3000);
const WS_URL='wss://api.hyperliquid.xyz/ws';
const INFO='https://api.hyperliquid.xyz/info';
const RANK='https://raw.githubusercontent.com/jay1125jay/flowiq-crew-operations/main/btc-flow-monitor/data/whale-ranking.json';
const DATA_DIR=process.env.DATA_DIR||'/data';
const STATE_FILE=path.join(DATA_DIR,'realtime-paper-state.json');
const LEVS=[2,5,10], START=1000, MARGIN=200, FEE=0.0005, SLIP=0.0003, MAX_POS=3;
fs.mkdirSync(DATA_DIR,{recursive:true});
let state={paper_only:true,mode:'REALTIME_HYPERLIQUID_WS_PAPER',started_at:new Date().toISOString(),updated_at:null,ws_status:'STARTING',wallets:{},accounts:{},events:[],stats:{fills_seen:0,btc_fills:0,signals:0,reconnects:0}};
try{state={...state,...JSON.parse(fs.readFileSync(STATE_FILE,'utf8')),paper_only:true,mode:'REALTIME_HYPERLIQUID_WS_PAPER'};}catch{}
for(const l of LEVS) state.accounts[l] ||= {leverage:l,starting_equity_usd:START,cash_usd:START,realized_net_pnl_usd:0,positions:{},closed_trades:[]};
let ws=null, selected=new Set(), subscriptions=new Set(), lastMid=0, reconnectTimer=null;
const now=()=>new Date().toISOString();
const save=()=>{state.updated_at=now();fs.writeFileSync(STATE_FILE,JSON.stringify(state,null,2));};
const emit=(e)=>{state.events.unshift({at:now(),...e});state.events=state.events.slice(0,200);save();};
async function info(payload){const r=await fetch(INFO,{method:'POST',headers:{'content-type':'application/json','user-agent':'BTC-Flow-Realtime-Paper/1.0'},body:JSON.stringify(payload)});if(!r.ok)throw new Error(`HL ${r.status}`);return r.json();}
function btcSize(ch){for(const x of ch?.assetPositions||[]){const p=x.position||{};if(p.coin==='BTC')return Number(p.szi||0);}return 0;}
function sideOf(n){return n>0?'LONG':n<0?'SHORT':'FLAT';}
function exec(px,side,open){const buy=(side==='LONG')===open;return px*(1+(buy?SLIP:-SLIP));}
function pnl(pos,px){return (px-pos.entry_price)*pos.quantity_btc*(pos.side==='LONG'?1:-1);}
function close(acct,w,px,reason,ratio=1){const p=acct.positions[w];if(!p)return;ratio=Math.max(0,Math.min(1,ratio));const q=p.quantity_btc*ratio, ep=exec(px,p.side,false), gross=(ep-p.entry_price)*q*(p.side==='LONG'?1:-1), fee=Math.abs(ep*q)*FEE, entryFee=p.entry_fee_usd*ratio, net=gross-fee-entryFee;acct.cash_usd+=gross-fee;acct.realized_net_pnl_usd+=net;acct.closed_trades.unshift({wallet:w,side:p.side,leverage:acct.leverage,entry_price:p.entry_price,exit_price:ep,quantity_btc:q,net_pnl_usd:net,reason,exit_at:now()});acct.closed_trades=acct.closed_trades.slice(0,100);if(ratio>=.999999)delete acct.positions[w];else{p.quantity_btc-=q;p.notional_usd*=1-ratio;p.margin_usd*=1-ratio;p.entry_fee_usd*=1-ratio;}}
function open(acct,w,side,px,scale=1){if(!acct.positions[w]&&Object.keys(acct.positions).length>=MAX_POS)return;const addMargin=MARGIN*Math.max(.01,scale), notional=addMargin*acct.leverage, ep=exec(px,side,true), q=notional/ep, fee=notional*FEE;acct.cash_usd-=fee;const p=acct.positions[w];if(p&&p.side===side){const nq=p.quantity_btc+q;p.entry_price=(p.entry_price*p.quantity_btc+ep*q)/nq;p.quantity_btc=nq;p.notional_usd+=notional;p.margin_usd+=addMargin;p.entry_fee_usd+=fee;}else acct.positions[w]={side,entry_price:ep,quantity_btc:q,notional_usd:notional,margin_usd:addMargin,entry_fee_usd:fee,entry_at:now()};}
function mark(){for(const acct of Object.values(state.accounts)){let u=0;for(const p of Object.values(acct.positions))u+=pnl(p,lastMid)-Math.abs(lastMid*p.quantity_btc)*FEE;acct.unrealized_pnl_usd=u;acct.estimated_equity_usd=acct.cash_usd+u;acct.open_positions=Object.keys(acct.positions).length;acct.closed_trade_count=acct.closed_trades.length;}state.btc_mid_usd=lastMid;}
async function refreshMid(){try{lastMid=Number((await info({type:'allMids'})).BTC);mark();save();}catch(e){state.last_error=String(e);}}
async function refreshCandidates(){try{const r=await fetch(RANK+'?t='+Date.now());const j=await r.json();const next=new Set((j.ranked_wallets||[]).filter(x=>x.paper_candidate||x.verified_whale).slice(0,MAX_POS).map(x=>x.address));selected=next;for(const w of selected)await ensureWallet(w);state.selected_wallets=[...selected];save();}catch(e){state.last_error='ranking '+String(e);}}
async function ensureWallet(w){if(!state.wallets[w]){const ch=await info({type:'clearinghouseState',user:w});const sz=btcSize(ch);state.wallets[w]={baseline:true,size_btc:sz,direction:sideOf(sz),last_fill_time:null};emit({type:'BASELINE',wallet:w,size_btc:sz,direction:sideOf(sz)});}subscribe(w);}
function subscribe(w){if(!ws||ws.readyState!==WebSocket.OPEN||subscriptions.has(w))return;ws.send(JSON.stringify({method:'subscribe',subscription:{type:'userFills',user:w}}));subscriptions.add(w);}
async function onFill(w,fill){state.stats.fills_seen++;if(fill.coin!=='BTC')return;state.stats.btc_fills++;const fillTime=Number(fill.time||Date.now()), lag=Math.max(0,Date.now()-fillTime);const prev=state.wallets[w]?.size_btc??0;let current=prev;try{current=btcSize(await info({type:'clearinghouseState',user:w}));}catch{}
const ps=sideOf(prev), ns=sideOf(current);state.wallets[w]={baseline:false,size_btc:current,direction:ns,last_fill_time:new Date(fillTime).toISOString(),last_detected_at:now(),last_lag_ms:lag};if(!selected.has(w)){save();return;}
let action='SIZE_CHANGE';if(ps!==ns)action=ns==='FLAT'?'CLOSE':ps==='FLAT'?'OPEN':'FLIP';else if(Math.abs(current)>Math.abs(prev))action='ADD';else if(Math.abs(current)<Math.abs(prev))action='PARTIAL_CLOSE';
if(!lastMid)await refreshMid();const px=Number(fill.px||lastMid);for(const acct of Object.values(state.accounts)){const p=acct.positions[w];if(action==='FLIP'||action==='CLOSE'){close(acct,w,px,action);}if(action==='OPEN'||action==='FLIP'){open(acct,w,ns,px,1);}else if(action==='ADD'&&p&&p.side===ns&&Math.abs(prev)>0){open(acct,w,ns,px,(Math.abs(current)-Math.abs(prev))/Math.abs(prev));}else if(action==='PARTIAL_CLOSE'&&p&&Math.abs(prev)>0){close(acct,w,px,'WHALE_PARTIAL_CLOSE',(Math.abs(prev)-Math.abs(current))/Math.abs(prev));}}
state.stats.signals++;mark();emit({type:'WHALE_SIGNAL',wallet:w,action,from_size_btc:prev,to_size_btc:current,direction:ns,whale_fill_price:px,whale_fill_time:new Date(fillTime).toISOString(),detected_at:now(),lag_ms:lag,fill_hash:fill.hash||null});}
function connect(){if(ws&&(ws.readyState===WebSocket.OPEN||ws.readyState===WebSocket.CONNECTING))return;subscriptions.clear();ws=new WebSocket(WS_URL);ws.on('open',()=>{state.ws_status='CONNECTED';state.connected_at=now();for(const w of selected)subscribe(w);save();});ws.on('message',async raw=>{try{const m=JSON.parse(raw.toString());if(m.channel==='userFills'&&m.data){const w=m.data.user;for(const f of m.data.fills||[]){if(m.data.isSnapshot)continue;await onFill(w,f);}}}catch(e){state.last_error='message '+String(e);save();}});ws.on('close',()=>{state.ws_status='DISCONNECTED';state.stats.reconnects++;save();clearTimeout(reconnectTimer);reconnectTimer=setTimeout(connect,3000);});ws.on('error',e=>{state.last_error='ws '+String(e);save();});}
setInterval(refreshMid,3000);setInterval(refreshCandidates,60000);setInterval(()=>{if(ws?.readyState===WebSocket.OPEN)ws.send(JSON.stringify({method:'ping'}));},30000);
await refreshMid();await refreshCandidates();connect();
const cors={'access-control-allow-origin':'*','cache-control':'no-store','content-type':'application/json; charset=utf-8'};
http.createServer((req,res)=>{if(req.url==='/health'){res.writeHead(state.ws_status==='CONNECTED'?200:503,cors);return res.end(JSON.stringify({ok:state.ws_status==='CONNECTED',paper_only:true,ws_status:state.ws_status,updated_at:state.updated_at,selected_wallets:state.selected_wallets||[]}));}if(req.url==='/state'||req.url==='/'){mark();res.writeHead(200,cors);return res.end(JSON.stringify(state));}res.writeHead(404,cors);res.end(JSON.stringify({error:'not found'}));}).listen(PORT,'0.0.0.0',()=>console.log(`BTC FLOW realtime PAPER engine :${PORT}`));