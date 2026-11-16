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

APP_BUILD = "SMC-DUAL-MARKET-2026-11-16-R2"

HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SMC Dual Market | Research</title>
<style>
:root{color-scheme:dark;font:14px system-ui,Segoe UI,sans-serif;color:#d7e3f2;background:#0a1220}
*{box-sizing:border-box}body{margin:0}header{padding:20px 26px;background:#111c30;border-bottom:1px solid #28374e}
h1{font-size:23px;margin:0 0 7px}small,.muted{color:#93a4bb}.warn{color:#fbbf24}
main{max-width:1450px;margin:0 auto;padding:20px}#cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:15px}
.card,.panel{padding:16px;border:1px solid #2a3a51;border-radius:12px;background:#101c2e}
.card strong{font-size:25px;display:block;margin:7px 0}.bar{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:14px;align-items:center}
select{background:#17263a;color:#f4f7ff;border:1px solid #415069;padding:8px;border-radius:7px}
canvas{width:100%;height:360px;display:block}h2{font-size:17px}table{border-collapse:collapse;width:100%}
td,th{text-align:left;border-bottom:1px solid #25354b;padding:10px;font-size:12px}th{color:#9aacc3}
#tablewrap{max-height:320px;overflow:auto}.good{color:#44cf8d}.bad{color:#fb7185}
.grid{display:grid;grid-template-columns:minmax(0,2fr) minmax(290px,1fr);gap:15px}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;color:#a7bfdf}
.setup-layout{display:grid;grid-template-columns:minmax(0,2fr) minmax(260px,1fr);gap:14px}
.setup-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px}
.setup-metric{padding:11px;background:#182a40;border-radius:9px;min-height:63px}
.setup-metric b{display:block;font-size:18px;margin-top:5px}
.status{font-size:19px;color:#fbbf24}
@media(max-width:850px){.setup-layout{grid-template-columns:1fr}}
@media(max-width:850px){.grid{grid-template-columns:1fr}}
</style></head>
<body><header><h1>SMC / MARKET RESEARCH TERMINAL</h1>
<small>Build SMC-DUAL-MARKET-2026-11-16-R2 • Local read-only terminal • AUTO-ORDERS DISABLED</small></header>
<main>
<div class="bar" style="align-items:center;padding:12px 15px;background:#17283e;border-radius:12px">
<strong>MARKET</strong> <select id="market" aria-label="Choose NIFTY or SENSEX">
<option value="NIFTY">NIFTY 50</option><option value="SENSEX">SENSEX</option></select>
<button id="allowAlerts" style="background:#295d96;color:white;border:0;border-radius:8px;padding:10px;cursor:pointer">Enable desktop alerts</button>
<strong class="warn" id="marketWarning"></strong></div>
<div id="bigAlert" role="alert" aria-live="assertive" style="display:none;position:fixed;left:3%;right:3%;top:9%;z-index:1000;background:#193750;border:3px solid #f5be51;border-radius:16px;box-shadow:0 10px 60px #000; padding:25px">
<h1 id="bigAlertTitle">SMC RESEARCH CANDIDATE</h1>
<p id="bigAlertBody" style="font-size:21px"></p>
<button id="dismissAlert" style="background:#f5be51;border:0;border-radius:8px;padding:12px 28px;cursor:pointer">Dismiss alert</button></div>
<section class="panel" style="margin-bottom:15px"><h2>LIVE SMC TRADE SETUP · NIFTY / SENSEX</h2>
<div class="setup-layout"><div><div id="setupstate" class="status">WAIT · MARKET DATA NOT VERIFIED</div>
<p id="setupreason" class="muted">Checking source and confirmation stages…</p>
<div class="setup-grid" id="setupmetrics"></div></div>
<div><h2>Confirmation checklist</h2><div id="setupevidence" class="muted"></div>
<p class="warn">INDEX LEVELS ≠ OPTION PREMIUM. NO BROKER ORDERS.</p></div></div></section>
<section class="panel" style="margin-bottom:15px"><h2>LIVE INDEX CANDLES <small>tick-sampled, not certified exchange OHLC</small></h2><canvas id="liveChart"></canvas><small id="liveChartNote">No verified live candles yet.</small></section><section class="panel" style="margin-bottom:15px"><h2>ATM / ITM CE–PE OPTION QUOTES <small>Actual broker bid/ask only</small></h2><p id="optionStatus" class="warn">OPTION QUOTES UNAVAILABLE</p><h2>OPTION MOMENTUM RANKING · OTM INCLUDED</h2><p id="momentumStatus" class="muted">Broker quote history required.</p><div id="momentumRows" style="overflow-x:auto"></div><div id="optionRows" style="overflow-x:auto"></div><small>No inferred option exit prices or premium SL/TP. Greeks may be unavailable, especially SENSEX.</small></section><div id="cards"></div>
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
 if(!a||a.type!=='SMC_RETEST_RESEARCH'||!a.id||live.status!=='RECENT_BAR')return;
 const symbol=a.symbol||'UNKNOWN';
 const key=symbol+'|'+a.id;
 if(observedAlerts.has(key))return;
 observedAlerts.add(key);
 document.getElementById('bigAlertTitle').textContent='SMC RETEST OBSERVED · RESEARCH ONLY';
 document.getElementById('bigAlertBody').textContent=
  symbol+' '+(a.direction||'')+
  ' at '+(a.at||'')+'. No verified Entry / SL / Option strike. NO TRADE AUTHORIZATION.';
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
function draw(bars,canvasId='chart'){
 const cv=document.getElementById(canvasId), r=cv.getBoundingClientRect(), dpr=window.devicePixelRatio||1;
 cv.width=Math.max(100,Math.round(r.width*dpr));cv.height=Math.round(360*dpr);
 const ctx=cv.getContext('2d');ctx.scale(dpr,dpr);const w=r.width,h=360;
 ctx.fillStyle='#101c2e';ctx.fillRect(0,0,w,h); if(!bars.length){ctx.fillStyle='#9eafc6';ctx.font='14px system-ui';ctx.fillText('NO OBSERVED LIVE CANDLES',20,45);return;}
 const view=bars.slice(-110), hi=Math.max(...view.map(x=>x.high)),lo=Math.min(...view.map(x=>x.low));
 const range=Math.max(hi-lo,.01), top=15,bottom=h-30,left=55,right=w-16;
 const y=p=>top+(hi-p)/range*(bottom-top),dx=(right-left)/view.length;
 ctx.font='11px system-ui';ctx.textAlign='right';ctx.strokeStyle='#2a3a51';ctx.fillStyle='#99abc1';
 for(let n=0;n<=4;n++){let p=lo+range*n/4,yp=y(p);ctx.beginPath();ctx.moveTo(left,yp);ctx.lineTo(right,yp);ctx.stroke();ctx.fillText(p.toFixed(1),left-7,yp+4)}
 view.forEach((c,i)=>{let x=left+(i+.5)*dx,bull=c.close>=c.open;
 ctx.strokeStyle=ctx.fillStyle=bull?'#33cb88':'#f7798d';
 ctx.beginPath();ctx.moveTo(x,y(c.high));ctx.lineTo(x,y(c.low));ctx.stroke();
 let a=y(c.open),b=y(c.close);ctx.fillRect(x-Math.max(1,dx*.32),Math.min(a,b),Math.max(2,dx*.64),Math.max(1,Math.abs(a-b)));});
 ctx.textAlign='left';ctx.fillStyle='#a9bad0';ctx.fillText(view[0].timestamp.slice(11,16),left,h-10);
 ctx.textAlign='right';ctx.fillText(view[view.length-1].timestamp.slice(11,16),right,h-10);
}
function renderSetup(live){
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
 '</td><td>'+esc(c.ask)+'</td><td>'+esc(c.spread)+'</td><td>'+esc(c.delta??'UNAVAILABLE')+
 '</td><td>'+esc(c.iv??'UNAVAILABLE')+'</td></tr>').join('')+'</tbody></table>':
 '<p class="muted">No currently verified broker option market depth.</p>';
 const m=live.setup||{}, verified=live.status==='RECENT_BAR';
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
 document.getElementById('setupmetrics').innerHTML=items.map(([name,val])=>
  '<div class="setup-metric"><small>'+esc(name)+'</small><b>'+
  esc(val??'UNAVAILABLE')+'</b></div>').join('');
 const missing=m.missing_evidence||['NO_VERIFIED_LIVE_CANDLE'];
 document.getElementById('setupevidence').innerHTML=missing.map(x=>'<p>○ '+esc(x)+'</p>').join('');
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
 '<p>Last closed candle: '+esc(live.last_candle_close_at||'Unavailable')+'</p>'+
 '<p>Index close: '+esc(live.last_candle_close??'—')+'</p>'+
 '<p>Reason: '+esc(live.reason||'No verified stream yet')+'</p>';
 document.getElementById('risk').innerHTML='<p class="warn">AUTO ORDERS: OFF</p><p>Option premium / Greeks / bid-ask: UNVERIFIED unless separately sourced</p><p>Any ICT sequence is a research observation, not an order permission.</p>';
 document.getElementById('rows').innerHTML=observations.map(o=>'<tr><td>'+esc(o.confirmed_at?.slice(11,19))+'</td>'+
 '<td>'+esc(o.direction)+'</td><td>'+esc(o.ict_sequence?.status||'UNVERIFIED')+'</td>'+
 '<td>'+esc((o.ict_sequence?.missing_stages||[]).join(', '))+'</td>'+
 '<td>'+esc(o.paper_outcome?.entry_open??o.index_entry_close_reference)+'</td>'+
 '<td>'+esc(o.index_stop_reference)+'</td>'+
 '<td>'+esc(o.index_t1_t2_t3_references?.[0]?.price??'—')+'</td>'+
 '<td>'+esc(o.paper_outcome?.exit_reason||'NO QUALIFIED BRACKET')+'</td></tr>').join('');
 document.getElementById('lifecycles').innerHTML=(session?.ict_lifecycles||[])
 .slice(-18).map(x=>'<p><small>'+esc(x.shift_at?.slice(11,19))+'</small> · '+esc(x.structure_kind)+' '+esc(x.direction)+
 ' · <b class="'+(x.state==='RETEST_CONFIRMED_RESEARCH'?'good':'warn')+'">'+esc(x.state)+'</b> · OB '+esc(x.ob_zone?.join('–')||'—')+
 ' · Retest '+esc(x.retest_at?.slice(11,19)||'—')+'</p>').join('')||'<p class="muted">No confirmed structure shifts in selected session.</p>';
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
                try:
                    recorded = datetime.fromisoformat(live["last_candle_close_at"])
                    if recorded > updated and live["status"] in ("RECENT_BAR", "WAIT"):
                        return live
                except (KeyError, ValueError, TypeError):
                    pass
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
                        tape_path: str | Path | None = None) -> dict:
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
    feed["sampled_live_candles"] = (
        event.get("sampled_live_candles", []) if event is not None
        and feed["status"] == "RECENT_BAR" else [])
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
                selected = select_symbol(parse_qs(parsed.query).get("symbol", ["NIFTY"])[0])
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
                                   and selected in live_symbols else None))},
                    allow_nan=False).encode()
                status, mime = 200, "application/json"
            elif path == "/api/live":
                payload = json.dumps(live_screen_payload(
                    live_file,status_file,
                    live_files["options"] if multi_root is not None
                    and selected in live_symbols else None,
                    symbol=selected,
                    tape_path=(live_files["option_tape"] if multi_root is not None
                               and selected in live_symbols else None))).encode()
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
    p.add_argument("--live-seconds", type=int, default=14400)
    p.add_argument("--token", help="Optional verified Angel INDEX token, never a credential")
    args = p.parse_args()
    if not 1024 <= args.port <= 65535:
        p.error("PORT_OUT_OF_RANGE")
    if not 5 <= args.live_seconds <= 14400:
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
                       "--seconds", str(args.live_seconds),
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
