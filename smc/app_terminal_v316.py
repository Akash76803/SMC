"""Local SMC research terminal: historical chart, ICT audit and live feed status.

Only localhost HTTP, read-only GET endpoints, no brokerage order routes.
Existing Angel read-only stream can be started as an optional child process.
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .csv_data import read_candles_csv
from .session_reconciliation_v314 import reconcile_sessions
from .live_setup_screen_v317 import build_setup_screen

HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SMC Terminal | Research</title>
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
<small>Local read-only terminal • index candles ≠ option premiums • AUTO-ORDERS DISABLED</small></header>
<main>
<section class="panel" style="margin-bottom:15px"><h2>LIVE SMC TRADE SETUP · NIFTY / SENSEX</h2>
<div class="setup-layout"><div><div id="setupstate" class="status">WAIT · MARKET DATA NOT VERIFIED</div>
<p id="setupreason" class="muted">Checking source and confirmation stages…</p>
<div class="setup-grid" id="setupmetrics"></div></div>
<div><h2>Confirmation checklist</h2><div id="setupevidence" class="muted"></div>
<p class="warn">INDEX LEVELS ≠ OPTION PREMIUM. NO BROKER ORDERS.</p></div></div></section>
<div id="cards"></div>
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
const sel=document.getElementById('day'), direction=document.getElementById('direction');
let snapshot=null;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function draw(bars){
 const cv=document.getElementById('chart'), r=cv.getBoundingClientRect(), dpr=window.devicePixelRatio||1;
 cv.width=Math.max(100,Math.round(r.width*dpr));cv.height=Math.round(360*dpr);
 const ctx=cv.getContext('2d');ctx.scale(dpr,dpr);const w=r.width,h=360;
 ctx.fillStyle='#101c2e';ctx.fillRect(0,0,w,h); if(!bars.length)return;
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
 const m=live.setup||{}, verified=live.status==='RECENT_BAR';
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
  ['Structural SL (verified)',m.structural_stop],
  ['Provisional stop · NOT SL',m.provisional_stop_reference],
  ['Target T1',m.t1],['Target T2',m.t2],['Target T3',m.t3],
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
 try{let r=await fetch('/api/snapshot',{cache:'no-store'}); if(!r.ok)throw new Error('API error');
 let next=await r.json();let prior=sel.value;snapshot=next;
 sel.innerHTML=(snapshot.sessions||[]).map(s=>'<option value="'+esc(s.date)+'">'+esc(s.date)+'</option>').join('');
 if((snapshot.sessions||[]).some(s=>s.date===prior))sel.value=prior;
 render();
 }catch(e){document.getElementById('quality').textContent='DATA NOT AVAILABLE: '+e.message}
}
sel.onchange=render;direction.onchange=render;window.onresize=render;
refresh();setInterval(async()=>{try{let r=await fetch('/api/live',{cache:'no-store'});if(r.ok&&snapshot){snapshot.live=await r.json();render()}}catch(e){}},5000);
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
                        status_path: str | Path | None) -> dict:
    feed=_feed_status(live_path,status_path)
    event=_latest_live_event(live_path)
    feed["setup"]=build_setup_screen(event,live_status=feed["status"])
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
                 status_path: str | None = None):
    historical = build_snapshot(csv_path, report_path)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            # Routine browser polls should not flood PowerShell.
            return

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/":
                payload, mime, status = HTML.encode(), "text/html; charset=utf-8", 200
            elif path == "/api/snapshot":
                payload = json.dumps(
                    {**historical, "live": live_screen_payload(live_path, status_path)},
                    allow_nan=False).encode()
                status, mime = 200, "application/json"
            elif path == "/api/live":
                payload = json.dumps(live_screen_payload(live_path, status_path)).encode()
                status, mime = 200, "application/json"
            else:
                payload, mime, status = b"Not found", "text/plain", 404
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
    p.add_argument("--start-live", action="store_true",
                   help="Start separate read-only Angel stream process with local login")
    p.add_argument("--live-seconds", type=int, default=14400)
    p.add_argument("--token", help="Optional verified Angel INDEX token, never a credential")
    args = p.parse_args()
    if not 1024 <= args.port <= 65535:
        p.error("PORT_OUT_OF_RANGE")
    if not 5 <= args.live_seconds <= 14400:
        p.error("INVALID_STREAM_DURATION")
    try:
        build_snapshot(args.csv, args.report, None)
    except (ValueError, OSError, KeyError, TypeError):
        p.error("REPLAY_REPORT_OR_CSV_MISSING_OR_MISMATCHED")
    child = None
    if args.start_live:
        from .angel_stream_cli_v312 import write_live_status
        write_live_status(args.status_file, "AUTHENTICATION_REQUIRED",
                          "ENTER_TOTP_IN_SEPARATE_BROKER_CONSOLE")
        command = [sys.executable, "-m", "smc.angel_stream_cli_v312",
                   "--symbol", args.symbol, "--seconds", str(args.live_seconds),
                   "--out", args.live_jsonl,
                   "--status-file", args.status_file]
        if args.token:
            command += ["--token", args.token]
        # Never supply login credentials or OTP on command line or in files.
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        child = subprocess.Popen(command, creationflags=flags)
    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port),
        make_handler(args.csv, args.report,
                     args.live_jsonl if args.start_live else None,
                     args.status_file if args.start_live else None))
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
        if child and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
