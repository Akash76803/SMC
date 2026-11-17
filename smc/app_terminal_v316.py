"""Local SMC research terminal: historical chart, ICT audit and live feed status.

Only localhost HTTP, read-only GET endpoints, no brokerage order routes.
Existing Angel read-only stream can be started as an optional child process.
"""
from __future__ import annotations
import argparse
import json
import socket
import subprocess
import sys
from collections import Counter
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from .csv_data import read_candles_csv
from .session_reconciliation_v314 import reconcile_sessions
from .live_setup_screen_v317 import build_setup_screen
from .angel_option_live_v318 import read_option_snapshot
from .option_quote_tape_v319 import live_momentum
from .premium_paper_plan_v319 import create_paper_plan
from .multi_strategy_terminal import multi_strategy_payload

APP_BUILD = "SMC-OPTION-MOMENTUM-2026-11-16-R3"

HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SMC Dual Market | Research</title>
<style>
:root{color-scheme:dark;font:14px Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#e2e8f0;background:#0b0f19;--line:#334155;--green:#10b981;--red:#ef4444;--amber:#f59e0b}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 0 0,#16223966,transparent 50%),#0b0f19;line-height:1.5}
header{position:sticky;top:0;z-index:50;background:rgba(17,24,39,.9);backdrop-filter:blur(18px);border-bottom:1px solid var(--line);box-shadow:0 4px 20px rgba(0,0,0,.3)}
.header-inner{max-width:1800px;margin:auto;padding:17px 24px;display:flex;align-items:center;justify-content:space-between;gap:18px;flex-wrap:wrap}
.eyebrow{font-size:10px;letter-spacing:.2em;font-weight:700;color:#94a3b8;margin-bottom:4px}h1{font-size:19px;letter-spacing:-.035em;margin:0 0 4px;font-weight:700}
small,.muted{color:#94a3b8}.warn{color:var(--amber)}.good{color:var(--green)}.bad{color:var(--red)}
main{max-width:1800px;margin:0 auto;padding:24px}.panel,.card{min-width:0;padding:22px;border:1px solid #334155a6;border-radius:10px;background:#111827;box-shadow:0 4px 20px rgba(0,0,0,.3)}
h2{font-size:14px;letter-spacing:.04em;margin:0 0 14px;font-weight:700}h2 small{display:inline;font-size:11px;letter-spacing:0;font-weight:400}h3{margin:0 0 12px}
.bar{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:14px;align-items:center}.toolbar{display:flex;align-items:center;gap:14px;flex-wrap:wrap}.toolbar .bar{margin:0}
button,select{font:inherit;border:1px solid var(--line);background:#1e293b;color:#e2e8f0;border-radius:7px;padding:9px 12px;cursor:pointer;transition:background .15s,border-color .15s,transform .15s}
button:hover{background:#293b55;border-color:#64748b}button:active{transform:translateY(1px)}button:focus-visible,select:focus-visible,summary:focus-visible{outline:2px solid #60a5fa;outline-offset:3px}
.market-tabs{display:flex;gap:4px;padding:4px;background:#0b0f19;border:1px solid var(--line);border-radius:9px}.market-tabs button{border:0;background:transparent;color:#94a3b8;font-size:12px;font-weight:700;padding:8px 18px}.market-tabs button[aria-pressed="true"]{background:#334155;color:#fff;box-shadow:0 2px 6px #0004}
.market-select{position:absolute;width:1px;height:1px;padding:0;overflow:hidden;clip-path:inset(50%)}.market-select:focus{position:static;width:auto;height:auto;clip-path:none}
#marketWarning{font-size:11px;max-width:220px}#allowAlerts{font-size:12px}#cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:18px}#cards .card{padding:15px;color:#94a3b8;font-size:12px}#cards strong{display:block;font-size:22px;color:#f1f5f9;margin-top:7px}
canvas{width:100%;height:360px;display:block;border-radius:8px}table{border-collapse:collapse;width:100%}td,th{text-align:left;border-bottom:1px solid #33415580;padding:11px;font-size:12px;white-space:nowrap}th{color:#94a3b8;font-weight:500;background:#111827}tbody tr:hover{background:#1e293b80}#tablewrap{max-height:320px;overflow:auto}
.grid{display:grid;grid-template-columns:minmax(0,2fr) minmax(290px,1fr);gap:16px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px;color:#94a3b8}
.setup-layout{display:grid;grid-template-columns:minmax(0,3fr) minmax(260px,1fr);gap:24px}.setup-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px}.setup-metric{padding:12px;background:#1e293b66;border:1px solid #33415566;border-radius:8px;min-width:0}.setup-metric small{font-size:11px}.setup-metric b{display:block;font-size:15px;font-variant-numeric:tabular-nums;margin-top:4px;overflow-wrap:anywhere;font-weight:600}
.status{font-size:16px;color:var(--amber);font-weight:600}#setupreason{font-size:12px;overflow-wrap:anywhere}#setupmetrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));align-items:start;gap:16px}.metric-group{min-width:0}.metric-group h3{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:#94a3b8;border-bottom:1px solid var(--line);padding-bottom:10px}.metric-row{display:flex;align-items:baseline;justify-content:space-between;gap:10px;padding:8px 0;border-bottom:1px solid #33415540;font-size:11px}.metric-row span{color:#94a3b8}.metric-row b{font-size:12px;font-weight:500;text-align:right;font-variant-numeric:tabular-nums;overflow-wrap:anywhere;min-width:0}.metric-row.is-waiting b,.is-waiting b{color:#64748b;font-weight:400}
.check-row{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:9px 0;border-bottom:1px solid #33415540;font-size:12px}.check-state{font-size:10px;white-space:nowrap;border-radius:5px;padding:3px 6px}.check-state.waiting{color:#94a3b8;background:#33415555}.check-state.passed{color:#34d399;background:#10b98116}.check-state.not-met{color:#f87171;background:#ef444416}
.smc-context{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin:12px 0;color:#94a3b8;font-size:12px}.setup-type{display:inline-block;padding:5px 10px;border-radius:6px;border:1px solid #334155;font-size:11px;font-weight:700}.setup-type.pro{color:#34d399;border-color:#10b98166;background:#10b98115}.setup-type.counter{color:#fbbf24;border-color:#f59e0b66;background:#f59e0b15}
#multiStrategyCards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin-top:20px}.strategy-card{padding:18px;background:linear-gradient(155deg,#1e293b88,#111827);border:1px solid var(--line);border-radius:10px;min-width:0}.strategy-heading{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:14px}.strategy-heading h3{font-size:16px;margin:0;letter-spacing:-.02em}.strategy-market{font-size:10px;color:#94a3b8;letter-spacing:.1em}.direction-pill{display:inline-flex;align-items:center;gap:6px;padding:5px 10px;border-radius:20px;font-size:11px;font-weight:700;letter-spacing:.03em}.direction-pill.bullish{background:#10b98119;color:#34d399;border:1px solid #10b98144}.direction-pill.bearish{background:#ef444419;color:#f87171;border:1px solid #ef444444}.direction-pill.neutral{background:#33415555;color:#94a3b8;border:1px solid #47556980}
.strategy-status{font-size:10px;color:#94a3b8;margin:12px 0 5px;overflow-wrap:anywhere}.strategy-context{font-size:11px;color:#94a3b8;margin:8px 0}.strike-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:16px}.strike-box{position:relative;border:1px solid var(--line);border-radius:8px;padding:12px 10px;background:#0b0f1980;min-width:0}.strike-box.recommended{border-color:#f59e0b88;background:linear-gradient(180deg,#f59e0b0b,#0b0f1980)}.strike-kind{font-size:10px;letter-spacing:.12em;color:#94a3b8;font-weight:700}.recommendation{display:block;font-size:9px;color:#fbbf24;margin:5px 0;min-height:28px;line-height:1.4}.strike-price{display:block;font-size:clamp(15px,1.2vw,21px);font-weight:700;letter-spacing:-.035em;white-space:nowrap;margin:5px 0;color:#f1f5f9;font-variant-numeric:tabular-nums}.strike-expiry{font-size:9px;color:#94a3b8;display:block;margin-bottom:10px}
.price-grid{display:grid;gap:7px;margin:12px 0}.price-row{display:flex;align-items:baseline;justify-content:space-between;gap:4px;font-size:10px}.price-row span{color:#94a3b8}.price-row b{font-size:12px;font-weight:600;font-variant-numeric:tabular-nums}.price-row.stop b{color:var(--red)}.price-row.target b{color:var(--green)}.price-row b.missing{color:#64748b}
.timing-badge{padding:9px 10px;margin:12px 0 5px;border:1px solid #334155;border-radius:6px;background:#1e293b80;color:#cbd5e1;font-size:10px;font-weight:500;line-height:1.6}.time-stop-note{display:block;margin:6px 0;color:#d9a855;font-size:10px;line-height:1.6}.strike-box .timing-badge{padding:7px 5px;font-size:9px}.strike-box .time-stop-note{font-size:9px}.copy-button{width:100%;margin-top:12px;border:1px solid #475569;border-radius:6px;padding:8px 5px;background:#1e293b;color:#e2e8f0;font-size:10px;font-weight:600;min-height:36px}.copy-button.copied{background:#10b98122;border-color:var(--green);color:#34d399}.copy-fallback{width:100%;min-height:110px;margin-top:8px;background:#0b0f19;color:#cbd5e1;border:1px solid #475569;padding:8px;border-radius:6px;font:11px monospace}.empty-strikes{border:1px dashed #334155;border-radius:8px;color:#64748b;text-align:center;padding:28px 12px;font-size:12px;margin-top:16px}
@media(max-width:1250px){#multiStrategyCards{grid-template-columns:1fr}.strike-box{padding:16px}.price-grid{grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.price-row{flex-direction:column}.price-row b{font-size:17px}.strike-price{font-size:24px}.recommendation{min-height:15px}.strike-box .timing-badge{font-size:11px}.strike-box .time-stop-note{font-size:10px}.copy-button{font-size:12px}.setup-layout{grid-template-columns:1fr}}
@media(max-width:850px){.grid{grid-template-columns:1fr}.header-inner{padding:13px 16px;gap:10px}h1{font-size:16px}main{padding:14px}.panel{padding:16px}#setupmetrics{grid-template-columns:1fr}.metric-group h3{margin-top:12px}.toolbar{gap:8px}.header-inner small{font-size:10px}}
@media(max-width:520px){.strike-grid{grid-template-columns:1fr}.strike-box{padding:16px}.recommendation{min-height:0}.strike-price{font-size:26px}.price-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.toolbar{width:100%;justify-content:space-between}.market-tabs button{padding:8px 13px}#allowAlerts{font-size:10px;padding:8px}#marketWarning{max-width:none;width:100%}.strategy-card{padding:14px}.header-inner .eyebrow{display:none}.grid canvas{height:320px}}
@media(prefers-reduced-motion:reduce){*{transition:none!important;scroll-behavior:auto!important}}
</style></head>
<body><header><div class="header-inner"><div><div class="eyebrow">INTRADAY RESEARCH / DECISION SUPPORT</div><h1>SMC / MARKET RESEARCH TERMINAL</h1>
<small>Build SMC-OPTION-MOMENTUM-2026-11-16-R3 • Local read-only terminal • AUTO-ORDERS DISABLED</small></div>
<div class="toolbar"><div class="market-tabs" role="group" aria-label="Select market">
<button type="button" data-market="NIFTY" aria-pressed="true">NIFTY 50</button><button type="button" data-market="SENSEX" aria-pressed="false">SENSEX</button></div>
<select id="market" class="market-select" aria-label="Choose NIFTY or SENSEX"><option value="NIFTY">NIFTY 50</option><option value="SENSEX">SENSEX</option></select>
<button id="allowAlerts" type="button">Enable desktop alerts</button><strong class="warn" id="marketWarning"></strong></div></div></header>
<main>
<section class="panel" style="margin-bottom:15px" aria-label="Multi-strategy research">
<h2>MULTI-STRATEGY SIGNALS · S&R + VWAP / ORB / OI TRAP</h2>
<p class="muted">Research observations · Fixed-delta premium estimates · Manual mobile execution only</p>
<small class="muted">Timing windows are configured research heuristics, not measured statistics or guaranteed safe holding limits. Minutes are measured from manual entry.</small>
<div id="multiStrategyCards" class="setup-grid" aria-live="polite">Checking recorded data…</div>
</section>
<div id="bigAlert" role="alert" aria-live="assertive" style="display:none;position:fixed;left:3%;right:3%;top:9%;z-index:1000;background:#193750;border:3px solid #f5be51;border-radius:16px;box-shadow:0 10px 60px #000; padding:25px">
<h1 id="bigAlertTitle">SMC RESEARCH CANDIDATE</h1>
<p id="bigAlertBody" style="font-size:21px"></p>
<button id="dismissAlert" style="background:#f5be51;border:0;border-radius:8px;padding:12px 28px;cursor:pointer">Dismiss alert</button></div>
<section class="panel" style="margin-bottom:15px"><h2>LIVE SMC TRADE SETUP · NIFTY / SENSEX</h2>
<div class="smc-context"><span id="smcTradeType" class="setup-type">HTF setup classification waiting</span><span id="htfDealingRange">HTF range: —</span><span id="smcOptionPricing">Option pricing: unavailable · separate from index setup</span></div>
<div class="setup-layout"><div><div id="setupstate" class="status">WAIT · MARKET DATA NOT VERIFIED</div>
<p id="setupreason" class="muted">Checking source and confirmation stages…</p>
<div class="setup-grid" id="setupmetrics"></div></div>
<div><h2>Gwaidier 3-Confluence Matrix</h2><div id="setupevidence" class="muted"></div>
<p class="warn">INDEX LEVELS ≠ OPTION PREMIUM. NO BROKER ORDERS.</p></div></div></section>
<section class="panel" style="margin-bottom:15px"><h2>LIVE INDEX CANDLES <small>tick-sampled, not certified exchange OHLC</small></h2><canvas id="liveChart"></canvas><small id="liveChartNote">No verified live candles yet.</small></section><section class="panel" style="margin-bottom:15px"><h2>ATM / ITM CE–PE OPTION QUOTES <small>Actual broker bid/ask only</small></h2><p id="optionStatus" class="warn">OPTION QUOTES UNAVAILABLE</p><h2>OPTION MOMENTUM RANKING · OTM INCLUDED</h2><p id="momentumStatus" class="muted">Broker quote history required.</p><div id="momentumRows" style="overflow-x:auto"></div><div id="optionRows" style="overflow-x:auto"></div><small>No inferred option exit prices or premium SL/TP. Greeks may be unavailable, especially SENSEX.</small></section><section class="panel" style="margin-bottom:15px">
<h2>PREMIUM ENTRY / STOP LOSS / TARGET · PAPER ONLY</h2>
<p id="premiumPlanStatus" class="warn">WAIT · No verified premium plan</p>
<div id="premiumPlanMetrics" class="setup-grid"></div>
<small>Paper prices use observed ASK reference and a training-only premium bracket. They are NOT observed fill/exit prices or instructions to buy options.</small>
</section>
<section class="panel" style="margin-bottom:15px">
<h2>SELF-LEARNING / WALK-FORWARD PAPER RESEARCH</h2>
<p id="learningStatus" class="warn">INSUFFICIENT EVIDENCE — no automated strategy promotion</p>
<div id="learningMetrics" class="setup-grid"></div>
<small>Strategy is selected on older quote observations and checked on untouched later sessions. Any positive historical score is NOT proof of future profit. No real-money orders.</small>
</section><div id="cards"></div>
<div class="bar"><label>Session <select id="day"></select></label>
<label>Direction <select id="direction"><option>ALL</option><option>BULLISH</option><option>BEARISH</option></select></label>
<span class="warn" id="quality"></span></div>
<div class="grid"><section class="panel"><h2>Closed 1-minute index candles</h2><canvas id="chart"></canvas>
<small>Chart uses only recorded candles; extra broker terminal records are quarantined.</small></section>
<section class="panel"><h2>Broker read-only live stream</h2><div id="live"></div>
<h2>Strategy gating</h2><div id="risk"></div></section></div>
<section class="panel" style="margin-top:15px"><h2>ICT / SMC evidence (decision-time only)</h2>
<div id="tablewrap"><table><thead><tr><th>Time</th><th>Direction</th><th>ICT</th><th>Missing evidence</th><th>Entry ref</th><th>SL ref</th><th>T1</th><th>Paper exit</th></tr></thead><tbody id="rows"></tbody></table></div>
</section>
<section class="panel" style="margin-top:15px"><h2>Independent ICT lifecycle (not order signals)</h2>
<div id="lifecycles"></div></section></main>
<script>
const sel=document.getElementById('day'), direction=document.getElementById('direction'),
      market=document.getElementById('market');
function syncMarketTabs(){document.querySelectorAll('[data-market]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.market===market.value)))}
document.querySelectorAll('[data-market]').forEach(button=>button.addEventListener('click',()=>{
 if(market.value===button.dataset.market)return;
 market.value=button.dataset.market;market.dispatchEvent(new Event('change'));
}));
market.addEventListener('change',syncMarketTabs);
let lastAlertId=null; const observedAlerts=new Set();
document.getElementById('dismissAlert').onclick=()=>{document.getElementById('bigAlert').style.display='none'};
document.getElementById('allowAlerts').onclick=async()=>{
 if(!('Notification' in window)){alert('Desktop notification not supported; in-app alerts remain enabled');return}
 try{const state=await Notification.requestPermission();
 document.getElementById('allowAlerts').textContent='Desktop alerts: '+state}
 catch(e){document.getElementById('allowAlerts').textContent='Desktop alerts unavailable'}
};
function notifyIfNew(live){
 const a=live.alert;
 if(!a||!['SMC_RETEST_RESEARCH','PREMIUM_PAPER_PLAN'].includes(a.type)||!a.id||live.status!=='RECENT_BAR')return;
 const symbol=a.symbol||'UNKNOWN';
 const key=symbol+'|'+a.id;
 if(observedAlerts.has(key))return;
 observedAlerts.add(key);
 document.getElementById('bigAlertTitle').textContent=
  a.type==='PREMIUM_PAPER_PLAN'?'PREMIUM PLAN · PAPER RESEARCH ONLY':
  'SMC RETEST OBSERVED · RESEARCH ONLY';
 document.getElementById('bigAlertBody').textContent=
  symbol+' '+(a.direction||'')+
  ' at '+(a.at||'')+'. '+(a.type==='PREMIUM_PAPER_PLAN'?
  'Observed momentum and hypothetical premium entry/SL/target are on the dashboard. PAPER ONLY.':
  'No verified Entry / SL / Option strike. NO TRADE AUTHORIZATION.');
 document.getElementById('bigAlert').style.display='block';
 if('Notification' in window && Notification.permission==='granted'){
   new Notification('SMC retest observed — research only',{
     body:document.getElementById('bigAlertBody').textContent,
     tag:key
   });
 }
}
let snapshot=null;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const isMissing=value=>value==null||value===''||['UNAVAILABLE','UNVERIFIED','NONE','NULL'].includes(String(value).toUpperCase());
const formatIST=value=>{if(isMissing(value))return '—';const date=new Date(value);return Number.isNaN(date.getTime())?'—':new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(date)+' IST'};
const formatISTDateTime=value=>{if(isMissing(value))return '—';const date=new Date(value);return Number.isNaN(date.getTime())?'—':new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Kolkata',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(date)+' IST'};
function displayValue(value){
 if(isMissing(value))return '—';
 if(typeof value==='number')return Number.isFinite(value)?value.toLocaleString('en-IN',{maximumFractionDigits:2}):'—';
 if(/^\d{4}-\d{2}-\d{2}T/.test(String(value)))return formatIST(value);
 return String(value);
}
const metricTile=(name,value)=>'<div class="setup-metric'+(isMissing(value)?' is-waiting':'')+'"><small>'+esc(name)+'</small><b>'+esc(displayValue(value))+'</b></div>';
function draw(bars,canvasId='chart'){
 const cv=document.getElementById(canvasId), r=cv.getBoundingClientRect(), dpr=window.devicePixelRatio||1;
 cv.width=Math.max(100,Math.round(r.width*dpr));cv.height=Math.round(360*dpr);
 const ctx=cv.getContext('2d');ctx.scale(dpr,dpr);const w=r.width,h=360;
 ctx.fillStyle='#111827';ctx.fillRect(0,0,w,h); if(!bars.length){ctx.fillStyle='#64748b';ctx.font='13px system-ui';ctx.fillText('Waiting for observed candles',20,45);return;}
 const view=bars.slice(-110), hi=Math.max(...view.map(x=>x.high)),lo=Math.min(...view.map(x=>x.low));
 const range=Math.max(hi-lo,.01), top=15,bottom=h-30,left=55,right=w-16;
 const y=p=>top+(hi-p)/range*(bottom-top),dx=(right-left)/view.length;
 ctx.font='11px system-ui';ctx.textAlign='right';ctx.strokeStyle='#2a3a51';ctx.fillStyle='#99abc1';
 for(let n=0;n<=4;n++){let p=lo+range*n/4,yp=y(p);ctx.beginPath();ctx.moveTo(left,yp);ctx.lineTo(right,yp);ctx.stroke();ctx.fillText(p.toFixed(1),left-7,yp+4)}
 view.forEach((c,i)=>{let x=left+(i+.5)*dx,bull=c.close>=c.open;
 ctx.strokeStyle=ctx.fillStyle=bull?'#10b981':'#ef4444';
 ctx.beginPath();ctx.moveTo(x,y(c.high));ctx.lineTo(x,y(c.low));ctx.stroke();
 let a=y(c.open),b=y(c.close);ctx.fillRect(x-Math.max(1,dx*.32),Math.min(a,b),Math.max(2,dx*.64),Math.max(1,Math.abs(a-b)));});
 ctx.textAlign='left';ctx.fillStyle='#a9bad0';ctx.fillText(view[0].timestamp.slice(11,16),left,h-10);
 ctx.textAlign='right';ctx.fillText(view[view.length-1].timestamp.slice(11,16),right,h-10);
}
function renderSetup(live){
 const learning=live.learning||{status:'INSUFFICIENT_EVIDENCE',reason:'NO_OBSERVED_BROKER_HISTORY'};
 document.getElementById('learningStatus').textContent=
  'LEARNING: '+learning.status+' — '+(learning.reason||'NO_VERIFIED_HISTORY');
 const learnItems=[
  ['Recorded SMC signals',learning.recorded_signals],
  ['Observed premium quotes',learning.observed_quote_samples],
  ['Train days',learning.train_days],['Validation days',learning.validation_days],
  ['Train expectancy / unit',learning.train?.expectancy_per_unit],
  ['Holdout expectancy / unit',learning.validation?.expectancy_per_unit],
  ['Holdout win rate',learning.validation?.win_rate],
  ['Holdout max drawdown',learning.validation?.max_drawdown_premium_points],
  ['Premium target (paper)',learning.selected?.target_premium_points],
  ['Premium SL (paper)',learning.selected?.stop_premium_points],
  ['Max hold (minutes)',learning.selected?.holding_minutes],
  ['Auto order permission',learning.promotion_allowed===true?'REJECTED':'DISABLED']
 ];
 document.getElementById('learningMetrics').innerHTML=learnItems.map(([k,v])=>metricTile(k,v)).join('');
 const paper=live.paper_plan||{status:'WAIT',reason:'PREMIUM_PLAN_UNVERIFIED'};
 document.getElementById('premiumPlanStatus').textContent=
   'PAPER PREMIUM PLAN: '+paper.status+' | '+(paper.reason||'NO VERIFIED PLAN');
 document.getElementById('premiumPlanMetrics').innerHTML=[
  ['Option contract',paper.contract],['Side / Moneyness',paper.side?(paper.side+' '+(paper.moneyness||'')):null],
  ['Entry ASK · PAPER',paper.entry_ask_reference],
  ['Stop · PAPER',paper.premium_stop_reference],
  ['Target · PAPER',paper.premium_target_reference],
  ['Net R:R · PAPER',paper.net_rr_reference],
  ['Momentum observed',paper.bid_change_pct!=null?paper.bid_change_pct+'%':null],
  ['Source quote at',paper.quote_at]
 ].map(([k,v])=>metricTile(k,v)).join('');
 const q=live.options||{status:'UNAVAILABLE',contracts:[]};
 const mom=live.momentum||{status:'NO_VERIFIED_OPTION_TAPE',candidates:[]};
 document.getElementById('momentumStatus').textContent=
  'Observed quote samples: '+(mom.observed_samples||0)+' | '+mom.status+
  ' · Momentum is research only, NOT an entry authorization.';
 document.getElementById('momentumRows').innerHTML=(mom.candidates||[]).length?
 '<table><thead><tr><th>Contract</th><th>Side</th><th>OTM steps</th><th>Momentum</th><th>Volume Δ</th><th>Bid</th><th>Entry Ask ref</th><th>Spread %</th><th>Status</th></tr></thead><tbody>'+
 mom.candidates.map(c=>'<tr><td>'+esc(c.trading_symbol)+'</td><td>'+esc(c.side)+'</td><td>'+esc(c.otm_steps)+
 '</td><td>'+esc(c.bid_change_pct)+'%</td><td>'+esc(c.volume_growth)+'</td><td>'+esc(c.last_bid)+
 '</td><td>'+esc(c.entry_ask_reference)+'</td><td>'+esc(c.spread_pct)+
 '</td><td>RESEARCH · NO TRADE</td></tr>').join('')+'</tbody></table>':
 '<p class="muted">Need at least 3 recent observed premium quotes with increasing bid, volume and acceptable spread.</p>';
 document.getElementById('optionStatus').textContent=
  'OPTION DATA: '+(q.status||'UNAVAILABLE')+' | '+(q.reason||'NO FRESH QUOTES');
 document.getElementById('optionRows').innerHTML=(q.contracts||[]).length?
 '<table><thead><tr><th>Contract</th><th>Expiry</th><th>ATM/ITM</th><th>Side</th><th>Bid</th><th>Ask</th><th>Spread</th><th>Delta</th><th>IV</th></tr></thead><tbody>'+
 q.contracts.map(c=>'<tr><td>'+esc(c.trading_symbol)+'</td><td>'+esc(c.expiry)+
 '</td><td>'+esc(c.moneyness)+'</td><td>'+esc(c.side)+'</td><td>'+esc(c.bid)+
 '</td><td>'+esc(c.ask)+'</td><td>'+esc(c.spread)+'</td><td>'+esc(displayValue(c.delta))+
 '</td><td>'+esc(displayValue(c.iv))+'</td></tr>').join('')+'</tbody></table>':
 '<p class="muted">No currently verified broker option market depth.</p>';
 const m=live.setup||{}, verified=live.status==='RECENT_BAR';
 const type=document.getElementById('smcTradeType');
 type.textContent=m.setup_type==='PRO_TREND'?'PRO-TREND (BOS TARGET)':m.setup_type==='COUNTER_PULLBACK'?'COUNTER-PULLBACK (50% EQ TARGET)':'HTF setup classification waiting';
 type.className='setup-type '+(m.setup_type==='PRO_TREND'?'pro':m.setup_type==='COUNTER_PULLBACK'?'counter':'');
 const context=m.htf_context||{};
 document.getElementById('htfDealingRange').textContent='HTF '+(context.timeframe||'—')+' · High '+displayValue(context.high)+' · Low '+displayValue(context.low)+' · 50% Eq '+displayValue(context.equilibrium)+' · '+(context.position||'Waiting');
 document.getElementById('smcOptionPricing').textContent='Option pricing: '+(q.contracts?.length?'observed quotes':'unavailable')+' · separate from index setup';
 draw(live.sampled_live_candles||[],'liveChart');
 document.getElementById('liveChartNote').textContent=verified?
 'Tick-sampled candles. Full exchange market coverage NOT VERIFIED.':
 'Live feed: '+(live.status||'NOT_CONNECTED')+' — live chart unavailable';
 const ready=m.status==='RESEARCH_SEQUENCE_OBSERVED'&&verified;
 document.getElementById('setupstate').textContent=(ready?'RESEARCH CANDIDATE':'WAIT / NO TRADE')+
   ' · '+(m.market||snapshot?.symbol||'NIFTY')+
   ' · '+(m.bias||'BIAS UNVERIFIED')+
   (m.instrument_side?' ('+m.instrument_side+' BIAS)':'');
 document.getElementById('setupreason').textContent=
   'Feed: '+(live.status||'NOT_CONNECTED')+' | Setup: '+(m.setup_state||'UNVERIFIED')+
   ' | '+(m.no_trade_reason||live.reason||'RESEARCH ONLY');
 const items=[
  ['Observed index close',m.observed_index_close],
  ['Candle close time',m.candle_at],
  ['ATR (14m)',m.atr14!=null?m.atr14+' pts':null],
  ['Min Target (dynamic)',m.min_target_required!=null?m.min_target_required+' pts':null],
  ['Liquidity sweep',m.sweep_level],
  ['IDM reference',m.idm_level],
  ['Order Block',m.order_block?.join(' – ')],
  ['FVG',m.fvg?.join(' – ')],
  ['Entry (verified)',m.entry],
  ['Entry CLOSE · RESEARCH',m.index_research_entry],
  ['Structural SL (verified)',m.structural_stop],
  ['Stop · RESEARCH',m.index_research_stop],
  ['Provisional stop · NOT SL',m.provisional_stop_reference],
  ['Target T1 (verified)',m.t1],['Target T2 (verified)',m.t2],['Target T3 (verified)',m.t3],
  ['T1 · RESEARCH',m.index_research_targets?.[0]],
  ['T2 · RESEARCH',m.index_research_targets?.[1]],
  ['T3 · RESEARCH',m.index_research_targets?.[2]],
  ['Index bracket state',m.index_research_bracket_status],
  ['Index R:R',m.index_rr],['Option strike',m.option_strike],
  ['Option bid / ask',(m.option_bid!=null&&m.option_ask!=null)?m.option_bid+' / '+m.option_ask:null],
  ['Option delta / IV',(m.option_delta!=null&&m.option_iv!=null)?m.option_delta+' / '+m.option_iv:null],
  ['Premium SL',m.option_premium_stop],['Premium target',m.option_premium_target]
 ];
 const metricGroups=[['Structure & Key Levels',[...items.slice(0,8)]],
  ['Execution Bracket',[...items.slice(8,21)]],
  ['Option Pricing',[...items.slice(21),['Premium Entry · ASK ref',m.option_ask]]]];
 document.getElementById('setupmetrics').innerHTML=metricGroups.map(([title,metrics])=>
  '<section class="metric-group"><h3>'+esc(title)+'</h3>'+metrics.map(([name,value])=>
  '<div class="metric-row'+(isMissing(value)?' is-waiting':'')+'"><span>'+esc(name)+'</span><b'+
  (/SL|Stop|stop/.test(name)?' class="bad"':/Target|^T[123]/.test(name)?' class="good"':'')+'>'+esc(displayValue(value))+'</b></div>').join('')+'</section>').join('');
 const missing=m.missing_evidence||['NO_VERIFIED_LIVE_CANDLE'];
 const checks=[['HTF_POI_VALIDATED','HTF Zone & POI (Decisional / Extreme / Sweep)',m.confluences?.HTF_POI_VALIDATED===true],
  ['DISPLACEMENT_CONFIRMED','LTF Displacement (MSS + FVG / Volume Imbalance)',m.confluences?.DISPLACEMENT_CONFIRMED===true],
  ['MITIGATION_RETEST','Mitigation Retest & Bracket',m.confluences?.MITIGATION_RETEST===true]];
 document.getElementById('setupevidence').innerHTML=checks.map(([key,label,observed])=>{
  const passed=verified&&observed&&!missing.includes(key), notMet=verified&&m.setup_state&&m.setup_state!=='UNVERIFIED'&&!passed;
  const state=passed?'passed':notMet?'not-met':'waiting', text=passed?'🟢 Passed':notMet?'🔴 Not Met':'⚪ Waiting';
  return '<div class="check-row"><span>'+esc(label)+'</span><span class="check-state '+state+'">'+text+'</span></div>';
 }).join('');
}
function render(){
 if(!snapshot)return;let d=sel.value, session=(snapshot.sessions||[]).find(x=>x.date===d);
 if(!session){session=(snapshot.sessions||[]).at(-1); if(session)sel.value=session.date}
 const live=snapshot.live||{}, observations=(session?.observations||[]).filter(o=>direction.value==='ALL'||o.direction===direction.value);
 renderSetup(live);
 document.getElementById('cards').innerHTML=[
 ['Historical sessions',snapshot.sessions.length],['Observations',snapshot.observation_count],
 ['ICT complete',snapshot.ict_complete],['Paper brackets',snapshot.index_brackets],['Lifecycle retests',snapshot.retest_confirmed],
 ['Live state',live.status||'NOT_CONNECTED']
 ].map(x=>'<div class="card">'+esc(x[0])+'<strong>'+esc(x[1])+'</strong></div>').join('');
 document.getElementById('marketWarning').textContent=snapshot.historical_available===false?'AUDITED HISTORY UNAVAILABLE FOR '+snapshot.symbol:'';
 document.getElementById('quality').textContent='Source audit: '+snapshot.excluded_count+' excluded • '+snapshot.quarantined_count+' quarantined extra bars';
 document.getElementById('live').innerHTML='<p>Status: <b class="'+(live.status==='RECENT_BAR'?'good':'warn')+'">'+esc(live.status)+'</b></p>'+
 '<p>Last closed candle: '+esc(formatIST(live.last_candle_close_at))+'</p>'+
 '<p>Index close: '+esc(live.last_candle_close??'—')+'</p>'+
 '<p>Reason: '+esc(live.reason||'No verified stream yet')+'</p>';
 document.getElementById('risk').innerHTML='<p class="warn">AUTO ORDERS: OFF</p><p>Option premium / Greeks / bid-ask: UNVERIFIED unless separately sourced</p><p>Any ICT sequence is a research observation, not an order permission.</p>';
 document.getElementById('rows').innerHTML=observations.map(o=>'<tr><td>'+esc(formatIST(o.confirmed_at))+'</td>'+
 '<td>'+esc(o.direction)+'</td><td>'+esc(o.ict_sequence?.status||'UNVERIFIED')+'</td>'+
 '<td>'+esc((o.ict_sequence?.missing_stages||[]).join(', '))+'</td>'+
 '<td>'+esc(o.paper_outcome?.entry_open??o.index_entry_close_reference)+'</td>'+
 '<td>'+esc(o.index_stop_reference)+'</td>'+
 '<td>'+esc(o.index_t1_t2_t3_references?.[0]?.price??'—')+'</td>'+
 '<td>'+esc(o.paper_outcome?.exit_reason||'NO QUALIFIED BRACKET')+'</td></tr>').join('');
 document.getElementById('lifecycles').innerHTML=(session?.ict_lifecycles||[])
 .slice(-25).map(x=>{
  const isBull=x.direction==='BULLISH';
  let sl=null;
  if(Array.isArray(x.ob_zone)&&x.ob_zone.length===2){
   sl=isBull?Math.min(x.ob_zone[0],x.sweep_level??x.ob_zone[0]):Math.max(x.ob_zone[1],x.sweep_level??x.ob_zone[1]);
  }
  const slStr=sl!=null?sl.toFixed(1):'—';
  const tgtStr=x.target_reference!=null?Number(x.target_reference).toFixed(1):'—';
  const typeLabel=x.setup_type?' · <b>['+esc(x.setup_type)+']</b>':'';
  const poiLabel=x.poi_category?' · <small class="muted">'+esc(x.poi_category)+'</small>':'';
  const retestStr=x.retest_at?' · Retest <b>'+esc(formatIST(x.retest_at))+'</b>':'';
  const slTgt=x.state==='RETEST_CONFIRMED_RESEARCH'?' · <span class="bad">SL: '+slStr+'</span> · <span class="good">Target: '+tgtStr+'</span>':'';
  return '<p><small>'+esc(formatISTDateTime(x.shift_at))+'</small> · '+esc(x.structure_kind)+' '+esc(x.direction)+
   typeLabel+poiLabel+' · <b class="'+(x.state==='RETEST_CONFIRMED_RESEARCH'?'good':'warn')+'">'+esc(x.state)+'</b>'+
   ' · OB '+esc(x.ob_zone?.map(v=>Number(v).toFixed(1)).join('–')||'—')+
   slTgt+retestStr+'</p>';
 }).join('')||'<p class="muted">No confirmed structure shifts in selected session.</p>';
 draw(session?.candles||[]);
}
async function refresh(){
 const desired=market.value;
 try{let r=await fetch('/api/snapshot?symbol='+encodeURIComponent(desired),{cache:'no-store'}); if(!r.ok)throw new Error('API error');
 let next=await r.json();if(market.value!==desired)return;
 let prior=sel.value;snapshot=next;
 sel.innerHTML=(snapshot.sessions||[]).map(s=>'<option value="'+esc(s.date)+'">'+esc(s.date)+'</option>').join('');
 if((snapshot.sessions||[]).some(s=>s.date===prior))sel.value=prior;
 render();
 }catch(e){document.getElementById('quality').textContent='DATA NOT AVAILABLE: '+e.message}
}
market.onchange=()=>{snapshot=null;sel.innerHTML='';document.getElementById('bigAlert').style.display='none';refresh()};
sel.onchange=render;direction.onchange=render;window.onresize=render;
refresh();
async function pollMarkets(){
 for(const symbol of ['NIFTY','SENSEX']){
  try{
   const r=await fetch('/api/live?symbol='+symbol,{cache:'no-store'});
   if(!r.ok)continue;
   const feed=await r.json();
   notifyIfNew(feed);
   if(snapshot && market.value===symbol && snapshot.symbol===symbol){
    snapshot.live=feed;render();
   }
  }catch(e){}
 }
}
pollMarkets();setInterval(pollMarkets,5000);
let multiBusy=false;
function appendStrategyTiming(parent,timing){
 if(!timing)return;
 const badge=document.createElement('p');badge.className='timing-badge';
 badge.textContent='⏱️ Target Expected: '+timing.expected_duration+' | Max Safe Hold: '+timing.max_hold;
 const note=document.createElement('small');note.className='time-stop-note';
 note.textContent='⚠️ Time-SL: '+timing.advice;
 parent.append(badge,note);
}
async function pollMultiStrategies(){
 if(multiBusy)return;
 multiBusy=true;const desired=market.value, container=document.getElementById('multiStrategyCards');
 try{
  const response=await fetch('/api/multi_strategy_status?market='+encodeURIComponent(desired),{cache:'no-store'});
  if(!response.ok)throw new Error('Data unavailable');
  const data=await response.json();if(market.value!==desired)return;
  container.replaceChildren();
  for(const [key,title] of [['snr_vwap','S&R + VWAP'],['orb','15m ORB'],['oi_trap','OI Trap']]){
   const state=data.strategies[key], card=document.createElement('article');card.className='strategy-card';
   const headingWrap=document.createElement('div');headingWrap.className='strategy-heading';
   const heading=document.createElement('h3');heading.textContent=title;
   const marketName=document.createElement('span');marketName.className='strategy-market';marketName.textContent=desired;
   headingWrap.append(heading,marketName);card.append(headingWrap);
   const bias=document.createElement('span');
   bias.textContent=state.direction==='BULLISH'?'🟢 BULLISH (CE)':state.direction==='BEARISH'?'🔴 BEARISH (PE)':'⚪ NEUTRAL / Waiting';
   bias.className='direction-pill '+(state.direction==='BULLISH'?'bullish':state.direction==='BEARISH'?'bearish':'neutral');card.append(bias);
   const status=document.createElement('p');status.className='strategy-status';status.textContent=state.status.replaceAll('_',' ')+' · '+state.reason.replaceAll('_',' ');card.append(status);
   if(state.signal?.timestamp){const observed=document.createElement('p');observed.className='strategy-context';observed.textContent='Observed '+formatIST(state.signal.timestamp);card.append(observed)}
   appendStrategyTiming(card,state.timing);
   if(key==='orb'){const p=document.createElement('p');p.className='strategy-context';p.textContent='Range: '+displayValue(state.range.orb_low)+' / '+displayValue(state.range.orb_high);card.append(p)}
   if(key==='oi_trap'){const p=document.createElement('p');p.className='strategy-context';p.textContent='PCR: '+displayValue(state.pcr)+' · Call wall: '+displayValue(state.walls.max_call_oi_strike)+' · Put wall: '+displayValue(state.walls.max_put_oi_strike);card.append(p)}
   const strikeGrid=document.createElement('div');strikeGrid.className='strike-grid';
   for(const kind of ['ITM','ATM','OTM']){
    const strike=state.strikes[kind];if(!strike)continue;
    const box=document.createElement('div');box.className='strike-box'+(kind==='ATM'?' recommended':'');
    const kindLabel=document.createElement('span');kindLabel.className='strike-kind';kindLabel.textContent=kind;box.append(kindLabel);
    const recommendation=document.createElement('span');recommendation.className='recommendation';recommendation.textContent=kind==='ATM'?'⭐ Recommended Momentum':'\u00a0';box.append(recommendation);
    const contract=document.createElement('b');contract.className='strike-price';contract.textContent=displayValue(strike.strike)+' '+strike.side;box.append(contract);
    const expiry=document.createElement('small');expiry.className='strike-expiry';expiry.textContent='Expiry '+displayValue(strike.expiry);box.append(expiry);
    const prices=document.createElement('div');prices.className='price-grid';
    for(const [label,value,cls] of [['Entry',strike.premium_entry,'entry'],['SL',strike.premium_sl,'stop'],['Target',strike.premium_target,'target']]){
     const row=document.createElement('div');row.className='price-row '+cls;
     const name=document.createElement('span');name.textContent=label;
     const amount=document.createElement('b');amount.textContent=value==null?'—':'₹'+Number(value).toFixed(2);
     if(value==null)amount.className='missing';row.append(name,amount);prices.append(row);
    }
    box.append(prices);
    const timing=strike.timing||state.timing;
    appendStrategyTiming(box,timing);
    const price=v=>v==null?'— (unverified)':Number(v).toFixed(2);
    const text=desired+' '+kind+' '+strike.strike+' '+strike.side+' | Expiry '+(strike.expiry??'UNAVAILABLE')+
      ' | Premium Entry ₹'+price(strike.premium_entry)+' | SL ₹'+price(strike.premium_sl)+' | Target ₹'+price(strike.premium_target)+
      (timing?' | Target Expected: '+timing.expected_duration+' | Max Safe Hold: '+timing.max_hold+' | Time-SL: '+timing.advice:'')+
      ' | DELTA ESTIMATE · RESEARCH ONLY | Timing: configured research heuristic, measured from manual entry';
    const copy=document.createElement('button');copy.type='button';copy.className='copy-button';copy.textContent='📋 Copy for Angel One';copy.setAttribute('aria-label','Copy '+desired+' '+kind+' strike and premium estimates');
    copy.onclick=async()=>{
     try{await navigator.clipboard.writeText(text);copy.textContent='Copied! ✓';copy.classList.add('copied')}
     catch(e){let fallback=box.querySelector('textarea');if(!fallback){fallback=document.createElement('textarea');fallback.className='copy-fallback';fallback.readOnly=true;fallback.value=text;fallback.setAttribute('aria-label','Strike recommendation text to copy');box.append(fallback)}fallback.focus();fallback.select();copy.textContent='Select text to copy'}
    };
    box.append(copy);strikeGrid.append(box);
   }
   if(strikeGrid.childElementCount){card.append(strikeGrid)}else{const waiting=document.createElement('div');waiting.className='empty-strikes';waiting.textContent='Waiting for a confirmed setup';card.append(waiting)}
   container.append(card);
  }
 }catch(e){if(market.value===desired)container.textContent='Multi-strategy data unavailable. Waiting for recorded candles and quotes.'}
 finally{multiBusy=false}
}
market.addEventListener('change',()=>{document.getElementById('multiStrategyCards').textContent='Checking selected market…';pollMultiStrategies()});
pollMultiStrategies();setInterval(pollMultiStrategies,2500);
</script></body></html>"""


def _tail_live(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {"status": "NOT_CONNECTED", "reason": "LIVE_STREAM_NOT_STARTED"}
    # Only inspect a bounded tail; a partially written last line is ignored.
    with path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(0, size-131072))
        blob = handle.read().decode("utf-8", "replace")
    lines = blob.splitlines()
    for line in reversed(lines[-30:]):
        try:
            data = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(data, dict) or not data.get("research_only", False):
            continue
        at = data.get("last_candle_close_at")
        quality = data.get("stream_quality") or {}
        if quality.get("quality_blocked", True):
            return {"status": "WAIT", "reason": "STREAM_CONTINUITY_UNVERIFIED",
                    "last_candle_close_at": at}
        try:
            age = (datetime.now().astimezone() -
                   datetime.fromisoformat(at)).total_seconds()
        except (TypeError, ValueError):
            return {"status": "WAIT", "reason": "INVALID_CANDLE_TIMESTAMP"}
        if not 0 <= age <= 120:
            return {"status": "STALE", "reason": "LAST_CLOSED_BAR_NOT_FRESH",
                    "last_candle_close_at": at}
        if data.get("status") != "RESEARCH_ONLY":
            return {"status": "WAIT",
                    "reason": data.get("reason", "ANALYSIS_NOT_READY"),
                    "last_candle_close_at": at}
        return {"status": "RECENT_BAR", "reason": "RECENT_DATA_NOT_PROOF_WEBSOCKET_CONNECTED",
                "last_candle_close_at": at,
                "last_candle_close": data.get("last_candle_close")}
    return {"status": "WAIT", "reason": "NO_VERIFIED_COMPLETE_CANDLE"}


def _feed_status(live_path: str | Path | None,
                 status_path: str | Path | None) -> dict:
    if status_path is not None:
        try:
            state = json.loads(Path(status_path).read_text(encoding="utf-8"))
            updated = datetime.fromisoformat(state["updated_at"])
            age = (datetime.now().astimezone() - updated).total_seconds()
            if age < 0 or age > 14500:
                return {"status": "DISCONNECTED", "reason": "FEED_STATE_TOO_OLD"}
            state_name = state.get("status")
            if state_name == "SUBSCRIBING":
                live = _tail_live(Path(live_path) if live_path else None)
                if live.get("status") in ("RECENT_BAR", "WAIT") and live.get("last_candle_close_at"):
                    return live
            if state_name in ("AUTHENTICATION_REQUIRED", "AUTHENTICATED",
                              "SUBSCRIBING", "STREAM_STOPPED", "DISCONNECTED",
                              "CANCELLED", "ERROR"):
                return {"status": state_name, "reason": state.get("reason", "")}
        except (OSError, ValueError, TypeError, KeyError):
            pass
    return _tail_live(Path(live_path) if live_path else None)


def _latest_live_event(path: str | Path | None) -> dict | None:
    if path is None:
        return None
    target=Path(path)
    try:
        with target.open("rb") as stream:
            stream.seek(0, 2)
            length=stream.tell()
            stream.seek(max(0,length-131072))
            data=stream.read().decode("utf-8","replace")
    except OSError:
        return None
    for row in reversed(data.splitlines()[-30:]):
        try:
            event=json.loads(row)
        except (ValueError, TypeError):
            continue
        if isinstance(event, dict) and event.get("research_only") is True:
            return event
    return None


def live_screen_payload(live_path: str | Path | None,
                        status_path: str | Path | None,
                        option_path: str | Path | None = None,
                        symbol: str | None = None,
                        tape_path: str | Path | None = None,
                        learning_path: str | Path | None = None) -> dict:
    feed=_feed_status(live_path,status_path)
    event=_latest_live_event(live_path)
    feed["setup"]=build_setup_screen(event,live_status=feed["status"])
    feed["alert"] = None
    if feed["status"] == "RECENT_BAR" and isinstance(event,dict):
        active = event.get("ict_active_lifecycles") or []
        current = event.get("last_candle_close_at")
        for setup in reversed(active):
            if (setup.get("state") == "RETEST_CONFIRMED_RESEARCH"
                and setup.get("retest_at") == current and current):
                feed["alert"] = {
                    "type":"SMC_RETEST_RESEARCH",
                    "id":setup.get("setup_id") or current,
                    "direction":setup.get("direction"),
                    "at":current,
                    "symbol":event.get("symbol"),
                    "order_eligible":False,
                    "message":"RETEST OBSERVED — NOT A TRADE SIGNAL"
                }
                break
    selected=symbol or (event.get("symbol") if isinstance(event,dict) else None)
    if selected not in ("NIFTY","SENSEX"):
        selected="NIFTY"
    feed["options"]=read_option_snapshot(
        option_path if feed["status"]=="RECENT_BAR" else None,
        symbol=selected)
    feed["momentum"] = {
        "symbol":selected,"status":"LIVE_OPTION_HISTORY_UNVERIFIED",
        "candidates":[],"observed_samples":0,
        "research_only":True,"orders_enabled":False,
    }
    if (feed["status"]=="RECENT_BAR" and isinstance(event,dict)
        and isinstance(event.get("last_candle_close"),(float,int))
        and tape_path is not None):
        feed["momentum"]=live_momentum(
            tape_path,symbol=selected,
            spot=float(event["last_candle_close"]),
            now=datetime.now().astimezone())
    feed["learning"]={
        "status":"INSUFFICIENT_EVIDENCE","reason":"NO_OBSERVED_OPTION_TAPE",
        "promotion_allowed":False,"orders_enabled":False,
        "research_only":True,
    }
    if learning_path is not None:
        try:
            learning=json.loads(Path(learning_path).read_text(encoding="utf-8"))
            if (learning.get("symbol")==selected
                and learning.get("orders_enabled") is False
                and learning.get("research_only") is True
                and learning.get("promotion_allowed") is False):
                feed["learning"]=learning
        except (ValueError,OSError,TypeError,KeyError):
            pass
    feed["paper_plan"]=create_paper_plan(
        feed["setup"],feed["momentum"],feed["learning"])
    if feed["paper_plan"]["status"]=="READY_FOR_PAPER_OBSERVATION":
        paper=feed["paper_plan"]
        feed["alert"]={
            "type":"PREMIUM_PAPER_PLAN",
            "id":paper["contract"]+"@"+paper["quote_at"],
            "symbol":selected,"direction":feed["setup"].get("bias"),
            "at":paper["quote_at"],"order_eligible":False,
            "message":"SMC PREMIUM PAPER PLAN OBSERVED — NOT A TRADE INSTRUCTION",
        }
    feed["sampled_live_candles"] = (
        event.get("sampled_live_candles", []) if event is not None
        and feed["status"] in ("RECENT_BAR", "SUBSCRIBING") else [])
    return feed


def build_snapshot(csv_path: str | Path, report_path: str | Path,
                   live_path: str | Path | None = None) -> dict:
    all_bars = read_candles_csv(csv_path)
    by_day, audit = reconcile_sessions(all_bars)
    report = json.loads(Path(report_path).read_text(encoding="utf-8-sig"))
    if report.get("research_only") is not True or report.get("orders_enabled") is not False:
        raise ValueError("REPORT_NOT_MARKED_RESEARCH_ONLY")
    if len(report.get("days", [])) != len(by_day):
        raise ValueError("SESSION_REPORT_MISMATCH_REPLAY_REQUIRED")
    if {x["date"] for x in report["days"]} != set(by_day):
        raise ValueError("SESSION_DATES_MISMATCH_REPLAY_REQUIRED")
    observed = 0
    brackets = 0
    complete = 0
    retest_confirmed = 0
    lifecycle_states = Counter()
    sessions = []
    for day in report["days"]:
        rows = day["brackets"]["observations"]
        observed += len(rows)
        brackets += sum(bool(o["index_bracket_qualified"]) for o in rows)
        complete += sum(bool(o.get("ict_sequence_observed")) for o in rows)
        lifecycles = day.get("ict_lifecycles", [])
        lifecycle_states.update(x["state"] for x in lifecycles)
        retest_confirmed += sum(x["state"] == "RETEST_CONFIRMED_RESEARCH" for x in lifecycles)
        sessions.append({
            "date": day["date"],
            "ict_lifecycles": lifecycles,
            "candles": [{"timestamp": c.timestamp.isoformat(), "open": c.open,
                         "high": c.high, "low": c.low, "close": c.close}
                        for c in by_day[day["date"]]],
            "observations": rows,
        })
    return {
        "research_only": True, "orders_enabled": False,
        "symbol": report["symbol"], "observation_count": observed,
        "index_brackets": brackets, "ict_complete": complete,
        "retest_confirmed": retest_confirmed,
        "lifecycle_states": dict(lifecycle_states),
        "excluded_count": sum(x["status"] == "EXCLUDED" for x in audit),
        "quarantined_count": sum(len(x["quarantined_timestamps"]) for x in audit),
        "sessions": sessions, "live": _tail_live(Path(live_path) if live_path else None),
    }


def make_handler(csv_path: str, report_path: str, live_path: str | None,
                 status_path: str | None = None,
                 multi_root: str | Path | None = None,
                 live_symbols: tuple[str, ...] = ()):

    if multi_root is not None:
        from .dual_market_v318 import get_historical_snapshots
        historical_by_symbol = get_historical_snapshots(multi_root)
    else:
        historical = build_snapshot(csv_path, report_path)
        historical_by_symbol = {historical["symbol"]: historical}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            # Routine browser polls should not flood PowerShell.
            return

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path
            from .dual_market_v318 import select_symbol, market_paths
            try:
                query = parse_qs(parsed.query)
                selected = select_symbol(query.get("market" if path == "/api/multi_strategy_status" else "symbol", ["NIFTY"])[0])
            except ValueError:
                payload, mime, status = b'{"error":"INVALID_MARKET_SYMBOL"}', "application/json", 400
                self._respond(status, mime, payload)
                return
            if multi_root is not None:
                live_files = market_paths(multi_root, selected)
                live_file = live_files["live"] if selected in live_symbols else None
                status_file = live_files["status"] if selected in live_symbols else None
            else:
                live_file, status_file = live_path, status_path
            if path == "/":
                payload, mime, status = HTML.encode(), "text/html; charset=utf-8", 200
            elif path == "/api/version":
                payload = json.dumps({"build": APP_BUILD, "dual_market": multi_root is not None,
                                      "orders_enabled": False}).encode()
                status, mime = 200, "application/json"
            elif path == "/api/snapshot":
                chosen = historical_by_symbol.get(selected)
                if chosen is None:
                    from .dual_market_v318 import unavailable_snapshot
                    chosen = unavailable_snapshot(selected, "HISTORY_NOT_LOADED")
                payload = json.dumps(
                    {**chosen, "live": live_screen_payload(
                        live_file,status_file,
                        live_files["options"] if multi_root is not None
                        and selected in live_symbols else None,
                        symbol=selected,
                        tape_path=(live_files["option_tape"] if multi_root is not None
                                   and selected in live_symbols else None),
                        learning_path=(live_files["learning"] if multi_root is not None
                                       else None))},
                    allow_nan=False).encode()
                status, mime = 200, "application/json"
            elif path == "/api/multi_strategy_status":
                root = (Path(multi_root) / "results" if multi_root is not None else
                        Path(live_path).parent if live_path else Path("results"))
                payload = json.dumps(multi_strategy_payload(root, selected), allow_nan=False).encode()
                status, mime = 200, "application/json"
            elif path == "/api/live":
                payload = json.dumps(live_screen_payload(
                    live_file,status_file,
                    live_files["options"] if multi_root is not None
                    and selected in live_symbols else None,
                    symbol=selected,
                    tape_path=(live_files["option_tape"] if multi_root is not None
                               and selected in live_symbols else None),
                    learning_path=(live_files["learning"] if multi_root is not None
                                   else None))).encode()
                status, mime = 200, "application/json"
            else:
                payload, mime, status = b"Not found", "text/plain", 404
            self._respond(status, mime, payload)

        def _respond(self, status, mime, payload):
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                             "connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(payload)

    return Handler


def main() -> int:
    p = argparse.ArgumentParser(description="Local read-only SMC browser terminal")
    p.add_argument("--symbol", choices=("NIFTY", "SENSEX"), default="NIFTY")
    p.add_argument("--csv", default="data/nifty_angel_historical_raw.csv")
    p.add_argument("--report", default="results/v315_nifty_report.json")
    p.add_argument("--live-jsonl", default="results/live_nifty.jsonl")
    p.add_argument("--status-file", default="results/live_feed_status.json")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--open-browser", action="store_true")
    p.add_argument("--multi", action="store_true", help="Both NIFTY and SENSEX on one screen")
    p.add_argument("--root", default=".", help="Local research data root")
    p.add_argument("--nifty-token", help="Verified index token, never a credential")
    p.add_argument("--sensex-token", help="Verified index token, never a credential")
    p.add_argument("--start-live", action="store_true",
                   help="Start separate read-only Angel stream process with local login")
    p.add_argument("--live-seconds", type=int, default=28800)
    p.add_argument("--token", help="Optional verified Angel INDEX token, never a credential")
    args = p.parse_args()
    if not 1024 <= args.port <= 65535:
        p.error("PORT_OUT_OF_RANGE")
    if not 5 <= args.live_seconds <= 28800:
        p.error("INVALID_STREAM_DURATION")
    # Block before spawning broker auth: never connect to an old dashboard.
    try:
        with socket.create_connection(("127.0.0.1", args.port), timeout=0.4):
            p.error("PORT_ALREADY_IN_USE_STOP_OLD_SMC_SERVER")
    except (ConnectionRefusedError, TimeoutError, OSError):
        pass
    children = []
    if args.multi:
        # The second market may not have historical data yet; never fill
        # SENSEX with NIFTY candles or misrepresent unavailable history.
        from .dual_market_v318 import market_paths, SYMBOLS
        if args.start_live:
            from .angel_stream_cli_v312 import write_live_status
            for symbol in SYMBOLS:
                path = market_paths(args.root, symbol)
                write_live_status(str(path["status"]), "AUTHENTICATION_REQUIRED",
                                  "ENTER_TOTP_IN_SEPARATE_BROKER_CONSOLE")
            command = [sys.executable, "-m", "smc.angel_dual_stream_v318",
                       "--root", args.root, "--seconds", str(args.live_seconds)]
            if args.nifty_token:
                command += ["--nifty-token",args.nifty_token]
            if args.sensex_token:
                command += ["--sensex-token",args.sensex_token]
            flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            children.append(subprocess.Popen(command, creationflags=flags))
        handler = make_handler(args.csv, args.report, None,
                               multi_root=args.root,
                               live_symbols=SYMBOLS if args.start_live else ())
    else:
        try:
            build_snapshot(args.csv, args.report, None)
        except (ValueError, OSError, KeyError, TypeError):
            p.error("REPLAY_REPORT_OR_CSV_MISSING_OR_MISMATCHED")
        if args.start_live:
            from .angel_stream_cli_v312 import write_live_status
            write_live_status(args.status_file, "AUTHENTICATION_REQUIRED",
                              "ENTER_TOTP_IN_SEPARATE_BROKER_CONSOLE")
            command = [sys.executable, "-m", "smc.angel_stream_cli_v312",
                       "--symbol", args.symbol,
                       "--seconds", str(min(args.live_seconds,14400)),
                       "--out", args.live_jsonl,
                       "--status-file", args.status_file]
            if args.token:
                command += ["--token", args.token]
            flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            children.append(subprocess.Popen(command, creationflags=flags))
        handler = make_handler(
            args.csv, args.report,
            args.live_jsonl if args.start_live else None,
            args.status_file if args.start_live else None)
    server = ThreadingHTTPServer(("127.0.0.1",args.port), handler)
    print(f"LOCAL_SMC_TERMINAL: http://127.0.0.1:{args.port}")
    print("LOCALHOST_ONLY | RESEARCH_ONLY | NO_ORDERS")
    if args.open_browser:
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{args.port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        for child in children:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
