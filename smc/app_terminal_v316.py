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
from datetime import datetime, time
from zoneinfo import ZoneInfo
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

IST = ZoneInfo('Asia/Kolkata')
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
.strat-category-bar{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0 10px;padding:4px;background:#0f172a;border:1px solid #1e293b;border-radius:10px;width:fit-content}
.strat-filter-btn{background:transparent;color:#94a3b8;border:1px solid transparent;padding:7px 14px;border-radius:7px;font-size:12px;font-weight:600;cursor:pointer;transition:all .15s ease}
.strat-filter-btn:hover{color:#f1f5f9;background:#1e293b80}
.strat-filter-btn.active{background:#1e293b;color:#38bdf8;border-color:#38bdf866;box-shadow:0 2px 8px rgba(56,189,248,.15)}
#multiStrategyCards{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:18px;margin-top:16px}
.strategy-card{padding:18px 20px;background:linear-gradient(165deg,#1e293b99 0%,#0f172a 100%);border:1px solid #334155;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,.35);min-width:0;display:flex;flex-direction:column}
.strategy-card.is-active-target{border:2px solid #10b981;box-shadow:0 0 25px rgba(16,185,129,.35);background:linear-gradient(165deg,#064e3b38 0%,#0f172a 100%)}
.active-target-banner{display:flex;align-items:center;justify-content:space-between;background:#10b98126;border:1px solid #10b98188;color:#34d399;padding:6px 12px;border-radius:8px;font-size:12px;font-weight:700;margin-bottom:12px;letter-spacing:.04em}
.live-pulse-badge{display:inline-flex;align-items:center;gap:6px;background:#10b98133;padding:2px 8px;border-radius:12px;font-size:11px;color:#a7f3d0}
.master-trend-banner{background:linear-gradient(135deg,#0f172a 0%,#1e293b 100%);border:1px solid #334155;border-radius:12px;padding:16px 20px;margin-bottom:16px;box-shadow:0 4px 20px rgba(0,0,0,.4)}
.mtf-header{display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap;margin-bottom:12px;border-bottom:1px solid #33415580;padding-bottom:12px}
.mtf-title{display:flex;flex-direction:column;gap:3px}
.mtf-eyebrow{font-size:10px;letter-spacing:.15em;font-weight:700;color:#94a3b8}
.mtf-title h3{margin:0;font-size:17px;font-weight:700;letter-spacing:-.02em}
.mtf-action-box{display:flex;align-items:center;gap:10px;padding:8px 16px;border-radius:8px;font-weight:700}
.mtf-action-box.good-bg{background:#10b98122;border:1.5px solid #10b98188;color:#34d399}
.mtf-action-box.bad-bg{background:#ef444422;border:1.5px solid #ef444488;color:#f87171}
.mtf-action-box.warn-bg{background:#f59e0b22;border:1.5px solid #f59e0b88;color:#fbbf24}
.mtf-action-box span{font-size:11px;color:#94a3b8;letter-spacing:.05em}
.mtf-action-box strong{font-size:13px;letter-spacing:.03em}
.mtf-pills-row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.tf-chip{font-size:11px;font-weight:600;padding:4px 10px;border-radius:6px;display:inline-flex;align-items:center;gap:4px}
.tf-chip.chip-bull{background:#10b98118;color:#34d399;border:1px solid #10b98155}
.tf-chip.chip-bear{background:#ef444418;color:#f87171;border:1px solid #ef444455}
.tf-chip.chip-neutral{background:#33415540;color:#94a3b8;border:1px solid #47556955}
.tf-alignment-badge{font-size:11px;font-weight:800;color:#fbbf24;background:#f59e0b1a;border:1px solid #f59e0b66;padding:4px 10px;border-radius:6px;margin-left:auto}
.trade-status-bar{display:flex;gap:8px;margin-bottom:12px;background:#0b0f19;padding:5px;border-radius:10px;border:1px solid #334155}
.trade-tab-btn{flex:1;background:transparent;border:0;color:#94a3b8;font-size:13px;font-weight:700;padding:9px 14px;border-radius:7px;cursor:pointer;transition:all .15s;display:flex;align-items:center;justify-content:center;gap:6px}
.trade-tab-btn:hover{color:#f1f5f9;background:#1e293b80}
.trade-tab-btn.active{background:#1e293b;color:#38bdf8;box-shadow:0 2px 8px rgba(0,0,0,.35)}
.trade-tab-btn span{background:#334155;color:#e2e8f0;padding:2px 7px;border-radius:10px;font-size:11px}
.trade-tab-btn.active span{background:#0284c7;color:#fff}
.counter-trend-warning{font-size:10px;color:#f87171;background:#ef444418;border:1px solid #ef444455;padding:3px 8px;border-radius:4px;font-weight:700;display:inline-flex;align-items:center;gap:4px}
.duration-chip{display:inline-flex;align-items:center;gap:4px;font-size:10px;font-weight:700;color:#38bdf8;background:#0284c718;border:1px solid #0284c744;padding:2px 6px;border-radius:4px}
.confirmed-hero-wrapper{margin:16px 0 20px}
.stage2-notification{display:flex;align-items:center;gap:10px;padding:9px 16px;background:#064e3b18;border:1px solid #10b98155;border-radius:9px;font-size:12px;color:#a7f3d0;margin-bottom:12px;line-height:1.5}
.stage2-notification strong{color:#34d399}
.info-circle{display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;border-radius:50%;background:#10b98133;color:#34d399;font-size:11px;font-weight:800;flex-shrink:0}
.confirmed-hero-card{background:linear-gradient(165deg,#0c1622 0%,#090d16 100%);border:1.5px solid #10b98188;box-shadow:0 6px 30px rgba(0,0,0,.5),0 0 25px rgba(16,185,129,.15);border-radius:12px;padding:20px 24px}
.confirmed-hero-card.bearish-theme{border-color:#ef444488;box-shadow:0 6px 30px rgba(0,0,0,.5),0 0 25px rgba(239,68,68,.15)}
.hero-top-row{display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap;margin-bottom:16px}
.hero-contract-info{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.hero-side-pill{padding:6px 14px;border-radius:6px;font-size:12px;font-weight:800;letter-spacing:.04em}
.hero-side-pill.pill-ce{background:#059669;color:#fff}
.hero-side-pill.pill-pe{background:#dc2626;color:#fff}
.hero-contract-title{font-size:19px;font-weight:700;color:#f8fafc;margin:0;letter-spacing:-.02em}
.hero-contract-title small{color:#94a3b8;font-size:13px;font-weight:400;margin-left:4px}
.hero-rr-badge{background:#1e293b;border:1px solid #334155;color:#f1f5f9;padding:5px 12px;border-radius:6px;font-size:12px;font-weight:700;letter-spacing:.02em}
.hero-metrics-grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:12px;margin:16px 0}
@media(max-width:1250px){.hero-metrics-grid{grid-template-columns:repeat(3,1fr)}}
@media(max-width:650px){.hero-metrics-grid{grid-template-columns:repeat(2,1fr)}}
.hero-metric-box{background:#111827;border:1px solid #334155;border-radius:8px;padding:12px 14px;display:flex;flex-direction:column;gap:3px;min-width:0}
.hero-metric-box.box-entry{background:#064e3b14;border:1.5px solid #10b98188}
.hero-metric-box.box-sl{background:#450a0a14;border:1.5px solid #ef444488}
.hero-metric-box.box-tgt{background:#064e3b10;border:1px solid #10b98166}
.metric-lbl{font-size:11px;color:#94a3b8;font-weight:600}
.metric-val{font-size:16px;font-weight:700;color:#f8fafc;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.metric-val.val-green{color:#34d399}
.metric-val.val-red{color:#f87171}
.metric-sub{font-size:10px;color:#64748b}
.hero-do-not-chase{display:flex;align-items:center;gap:8px;padding:10px 16px;background:#fef3c70d;border:1px solid #f59e0b66;border-radius:8px;color:#fbbf24;font-size:12px;margin:14px 0}
.hero-do-not-chase strong{font-size:12px;letter-spacing:.02em}
.hero-conditions-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px}
@media(max-width:850px){.hero-conditions-grid{grid-template-columns:1fr}}
.hero-condition-box{border-radius:8px;padding:14px 16px;display:flex;flex-direction:column;gap:6px}
.hero-condition-box.cond-entry{background:#064e3b12;border:1px solid #10b98144}
.hero-condition-box.cond-exit{background:#450a0a12;border:1px solid #ef444444}
.cond-header{display:flex;align-items:center;gap:6px;font-size:12px;font-weight:700}
.cond-header.hdr-entry{color:#34d399}
.cond-header.hdr-exit{color:#f87171}
.cond-text{font-size:12px;color:#e2e8f0;margin:2px 0;line-height:1.5}
.cond-footer{font-size:10px;color:#94a3b8;margin-top:4px}
.hero-copy-btn{margin-top:14px;background:#0284c722;border:1px solid #38bdf888;color:#38bdf8;padding:10px 18px;border-radius:8px;font-size:12px;font-weight:700;cursor:pointer;width:100%;text-align:center;transition:all .15s ease}
.hero-copy-btn:hover{background:#0284c744;color:#fff}
.hero-copy-btn.copied{background:#10b98126;border-color:#10b981;color:#34d399}
.strategy-heading{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:10px}
.strategy-heading h3{font-size:17px;font-weight:700;margin:0;letter-spacing:-.02em;color:#f8fafc}
.strategy-market{font-size:11px;color:#38bdf8;background:#0284c71a;border:1px solid #0284c744;padding:2px 8px;border-radius:4px;font-weight:600;letter-spacing:.05em}
.strategy-badges{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:10px}
.direction-pill{display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:20px;font-size:11px;font-weight:700;letter-spacing:.03em}
.direction-pill.bullish{background:#10b98119;color:#34d399;border:1px solid #10b98144}
.direction-pill.bearish{background:#ef444419;color:#f87171;border:1px solid #ef444444}
.direction-pill.neutral{background:#33415555;color:#94a3b8;border:1px solid #47556980}
.confluence-pill{background:#f59e0b20;color:#fbbf24;border:1px solid #f59e0b88;box-shadow:0 0 10px #f59e0b22;font-weight:800}.confluence-pill::before{content:'🔥 '}
.outcome-badge{display:inline-flex;align-items:center;gap:5px;padding:3px 8px;border-radius:6px;font-size:10px;font-weight:800;letter-spacing:.04em}
.outcome-badge.outcome-target{background:#10b98122;color:#34d399;border:1px solid #10b98188;box-shadow:0 0 10px rgba(16,185,129,.25)}
.outcome-badge.outcome-sl{background:#ef444422;color:#f87171;border:1px solid #ef444488;box-shadow:0 0 10px rgba(239,68,68,.25)}
.outcome-badge.outcome-active{background:#f59e0b22;color:#fbbf24;border:1px solid #f59e0b88}
.outcome-badge.outcome-eod{background:#38bdf822;color:#38bdf8;border:1px solid #38bdf888}
.strategy-status{font-size:10px;color:#94a3b8;margin:6px 0;overflow-wrap:anywhere}
.strategy-context{font-size:11px;color:#94a3b8;margin:4px 0}
.index-summary-box{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px;background:#090d16;border:1px solid #1e293b;border-radius:8px;padding:8px 10px;margin:10px 0}
.index-summary-item{display:flex;flex-direction:column;gap:2px}
.index-summary-item span{font-size:9px;text-transform:uppercase;color:#94a3b8;letter-spacing:.05em}
.index-summary-item b{font-size:12px;font-weight:700;color:#f5be51;font-variant-numeric:tabular-nums}
.index-summary-item.sl b{color:#f87171}
.index-summary-item.tgt b{color:#34d399}
.index-summary-item.rr b{color:#38bdf8}
.paper-portfolio-container{background:linear-gradient(135deg,#0c1322 0%,#1e293b 100%);border:1px solid #334155;border-radius:12px;padding:16px 20px;margin-bottom:16px;box-shadow:0 4px 20px rgba(0,0,0,.4)}
.portfolio-header{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;border-bottom:1px solid #33415580;padding-bottom:10px;margin-bottom:12px}
.portfolio-title{display:flex;align-items:center;gap:8px}
.portfolio-title h3{margin:0;font-size:15px;font-weight:700;color:#f8fafc}
.portfolio-badge{font-size:10px;font-weight:700;color:#38bdf8;background:#0284c722;border:1px solid #0284c766;padding:2px 8px;border-radius:4px;letter-spacing:.05em}
.portfolio-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:12px}
@media(max-width:850px){.portfolio-grid{grid-template-columns:repeat(2,1fr)}}
.port-stat-card{background:#0b1120;border:1px solid #334155;border-radius:8px;padding:10px 14px}
.port-stat-lbl{font-size:11px;font-weight:600;color:#94a3b8;margin-bottom:3px}
.port-stat-val{font-size:16px;font-weight:800;color:#f8fafc;font-variant-numeric:tabular-nums}
.port-stat-val.val-green{color:#34d399}
.port-stat-val.val-red{color:#f87171}
.port-stat-sub{font-size:10px;color:#64748b;margin-top:2px}
.active-pos-banner{background:#064e3b18;border:1.5px solid #10b98166;border-radius:8px;padding:12px 16px;display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap;margin-bottom:10px}
.active-pos-banner.in-loss{background:#450a0a18;border-color:#ef444466}
.passbook-details summary{font-size:12px;font-weight:700;color:#94a3b8;cursor:pointer;padding:6px 0}
.passbook-table{width:100%;border-collapse:collapse;font-size:11px;margin-top:8px}
.passbook-table th,.passbook-table td{padding:6px 10px;text-align:left;border-bottom:1px solid #33415566}
.passbook-table th{color:#94a3b8;font-weight:700}
.strike-tab-bar{display:flex;gap:6px;margin:12px 0 8px;background:#080c14;padding:4px;border-radius:8px;border:1px solid #1e293b}
.strike-tab-btn{flex:1;background:transparent;border:1px solid transparent;color:#94a3b8;padding:6px 8px;border-radius:6px;font-size:11px;font-weight:600;cursor:pointer;text-align:center;transition:all .15s ease}
.strike-tab-btn:hover{color:#f1f5f9;background:#1e293b66}
.strike-tab-btn.active{background:#1e293b;color:#f8fafc;border-color:#475569}
.strike-tab-btn.is-atm{color:#fbbf24}
.strike-tab-btn.is-atm.active{background:#f59e0b18;border-color:#f59e0b88;color:#fbbf24}
.strike-grid{display:block;margin-top:4px}
.strike-box{display:none;position:relative;border:1px solid #334155;border-radius:10px;padding:14px;background:#080c16;box-shadow:inset 0 1px 0 rgba(255,255,255,.04)}
.strike-box.active{display:block}
.strike-box.recommended{border-color:#f59e0b88;background:linear-gradient(180deg,#f59e0b0d,#080c16)}
.strike-hero-header{display:flex;align-items:baseline;justify-content:space-between;gap:10px;margin-bottom:10px;border-bottom:1px solid #1e293b;padding-bottom:8px}
.strike-price{font-size:20px;font-weight:700;color:#f8fafc;letter-spacing:-.02em}
.strike-expiry{font-size:11px;color:#94a3b8}
.recommendation{font-size:11px;font-weight:600;color:#fbbf24}
.price-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:12px 0;background:#0f172a80;border:1px solid #1e293b;border-radius:8px;padding:8px 12px}
.price-row{display:flex;flex-direction:column;gap:3px;font-size:10px}
.price-row span{color:#94a3b8;text-transform:uppercase;font-size:9px}
.price-row b{font-size:14px;font-weight:700;font-variant-numeric:tabular-nums}
.price-row.entry b{color:#f8fafc}
.price-row.stop b{color:#f87171}
.price-row.target b{color:#34d399}
.price-row b.missing{color:#64748b;font-size:11px}
.timing-badge{padding:9px 10px;margin:12px 0 5px;border:1px solid #334155;border-radius:6px;background:#1e293b80;color:#cbd5e1;font-size:10px;font-weight:500;line-height:1.6}.time-stop-note{display:block;margin:6px 0;color:#d9a855;font-size:10px;line-height:1.6}.strike-box .timing-badge{padding:7px 5px;font-size:9px}.strike-box .time-stop-note{font-size:9px}.copy-button{width:100%;margin-top:12px;border:1px solid #38bdf866;border-radius:8px;padding:9px 14px;background:#0284c722;color:#38bdf8;font-size:11px;font-weight:700;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:6px;transition:all .15s ease}.copy-button:hover{background:#0284c744;border-color:#38bdf8;color:#f0f9ff}.copy-button.copied{background:#10b98126;border-color:#10b981;color:#34d399}.copy-fallback{width:100%;min-height:110px;margin-top:8px;background:#0b0f19;color:#cbd5e1;border:1px solid #475569;padding:8px;border-radius:6px;font:11px monospace}.empty-strikes{border:1px dashed #334155;border-radius:8px;color:#64748b;text-align:center;padding:28px 12px;font-size:12px;margin-top:16px}
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
<h2>MULTI-STRATEGY SIGNALS</h2>
<p class="muted">Research observations · Fixed-delta premium estimates · Manual mobile execution only</p>
<small class="muted">Timing windows are configured research heuristics, not measured statistics or guaranteed safe holding limits. Minutes are measured from manual entry.</small>
<div id="confirmedHeroSection"></div>
<div id="paperPortfolioSection" class="paper-portfolio-container" style="display:none"></div>
<div id="masterTrendBanner" class="master-trend-banner">Checking Multi-Timeframe Trend…</div>
<div class="trade-status-bar" role="tablist" aria-label="Trade Status Filter">
<button type="button" class="trade-tab-btn active" data-tab="active">⚡ ACTIVE SETUPS (<span id="activeCount">0</span>)</button>
<button type="button" class="trade-tab-btn" data-tab="quality">⭐ A+ QUALITY (Trend-Aligned) (<span id="qualityCount">0</span>)</button>
<button type="button" class="trade-tab-btn" data-tab="resolved">🎯 RESOLVED TRADES (History) (<span id="resolvedCount">0</span>)</button>
<button type="button" class="trade-tab-btn" data-tab="all">📋 ALL STRATEGIES</button>
</div>
<div class="strat-category-bar" role="tablist" aria-label="Strategy Category Filter">
<button type="button" class="strat-filter-btn active" data-cat="ALL">All Categories</button>
<button type="button" class="strat-filter-btn" data-cat="SMC">SMC Institutional (5)</button>
<button type="button" class="strat-filter-btn" data-cat="PA">Price Action (2)</button>
<button type="button" class="strat-filter-btn" data-cat="MOM">Momentum & Flow (3)</button>
</div>
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
 ['Live state',live.status==='MARKET_CLOSED'?'MARKET_CLOSED (Review)':live.status||'NOT_CONNECTED']
 ].map(x=>'<div class="card">'+esc(x[0])+'<strong>'+esc(x[1])+'</strong></div>').join('');
 document.getElementById('marketWarning').textContent=snapshot.historical_available===false?'AUDITED HISTORY UNAVAILABLE FOR '+snapshot.symbol:'';
 document.getElementById('quality').textContent='Source audit: '+snapshot.excluded_count+' excluded • '+snapshot.quarantined_count+' quarantined extra bars';
 document.getElementById('live').innerHTML='<p>Status: <b class="'+(live.status==='RECENT_BAR'||live.status==='MARKET_CLOSED'?'good':'warn')+'">'+esc(live.status)+'</b></p>'+
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
  const isDir=x.target_is_directional!==false;
  let tgtDisplay='';
  if(x.target_reference!=null){
   const tgtVal=Number(x.target_reference).toFixed(1);
   tgtDisplay=isDir?' · <span class="good">Target: '+tgtVal+'</span>':' · <span class="bad">Target: '+tgtVal+' (NON-DIR ⚠️ behind entry)</span>';
  }
  const typeLabel=x.setup_type?' · <b>['+esc(x.setup_type)+(isDir?'':' · WRONG SIDE OF EQ')+']</b>':'';
  const poiLabel=x.poi_category?' · <small class="muted">'+esc(x.poi_category)+'</small>':'';
  const retestStr=x.retest_at?' · Retest <b>'+esc(formatIST(x.retest_at))+'</b>':'';
  const stateCls=(x.state==='RETEST_CONFIRMED_RESEARCH'&&isDir)?'good':'warn';
  const stateTxt=(x.state==='RETEST_CONFIRMED_RESEARCH'&&!isDir)?'RETEST_OBSERVED (NON-DIR TARGET)':x.state;
  const slTgt=x.state==='RETEST_CONFIRMED_RESEARCH'?' · <span class="bad">SL: '+slStr+'</span>'+tgtDisplay:'';
  return '<p><small>'+esc(formatISTDateTime(x.shift_at))+'</small> · '+esc(x.structure_kind)+' '+esc(x.direction)+
   typeLabel+poiLabel+' · <b class="'+stateCls+'">'+esc(stateTxt)+'</b>'+
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
let currentStratCat='ALL', currentTradeTab='active';
document.querySelectorAll('.trade-tab-btn').forEach(btn=>{
 btn.onclick=()=>{
  document.querySelectorAll('.trade-tab-btn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');currentTradeTab=btn.dataset.tab;pollMultiStrategies();
 };
});
const strategyTitles={
 snr_vwap:'S&R + VWAP',orb:'15m ORB',candlestick:'Candlestick Price Action',oi_trap:'OI Trap',
 smc_sweep:'Liquidity Sweep',smc_mss:'Market Structure Shift',smc_fvg:'Fair Value Gap',
 smc_ob:'Order Block Retest',smc_fib:'Fibonacci OTE Golden Pocket',pdh_pdl:'Previous Day High / Low'
};
const strategyCategories={
 smc_sweep:'SMC',smc_mss:'SMC',smc_fvg:'SMC',smc_ob:'SMC',smc_fib:'SMC',
 candlestick:'PA',pdh_pdl:'PA',
 snr_vwap:'MOM',orb:'MOM',oi_trap:'MOM'
};
document.querySelectorAll('.strat-filter-btn').forEach(btn=>{
 btn.onclick=()=>{
  document.querySelectorAll('.strat-filter-btn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');currentStratCat=btn.dataset.cat;pollMultiStrategies();
 };
});
async function pollMultiStrategies(){
 if(multiBusy)return;
 multiBusy=true;const desired=market.value, container=document.getElementById('multiStrategyCards');
 try{
  const response=await fetch('/api/multi_strategy_status?market='+encodeURIComponent(desired),{cache:'no-store'});
  if(!response.ok)throw new Error('Data unavailable');
  const data=await response.json();if(market.value!==desired)return;
  container.replaceChildren();
  const heroBox=document.getElementById('confirmedHeroSection');
  if(heroBox&&data.confirmed_hero){
   const h=data.confirmed_hero;
   const isCe=h.side==='CE';
   const copyTxt=h.contract+' | Bracket '+h.entry_bracket+' | SL '+h.stop_loss+' | Target '+h.target_1+' | DO NOT CHASE > '+h.do_not_chase;
   heroBox.innerHTML='<div class="confirmed-hero-wrapper">'+
    '<div class="stage2-notification"><span class="info-circle">ⓘ</span><span><strong>'+h.stage+':</strong> '+h.stage_note+'</span></div>'+
    '<div class="confirmed-hero-card '+(isCe?'':'bearish-theme')+'">'+
    '<div class="hero-top-row"><div class="hero-contract-info">'+
    '<span class="hero-side-pill '+(isCe?'pill-ce':'pill-pe')+'">'+h.side_label+'</span>'+
    (h.strategy?'<span class="hero-strategy-pill" style="margin-left:8px;font-size:11px;font-weight:700;color:#38bdf8;background:#0369a133;padding:4px 8px;border-radius:6px;border:1px solid #0284c7">⚡ '+(h.strategy)+(h.pattern?' · '+h.pattern:'')+'</span>':'')+
    '<h2 class="hero-contract-title">'+h.contract+' <small>('+h.expiry+')</small></h2>'+
    '</div><div class="hero-rr-badge">R:R '+h.rr_ratio+'</div></div>'+
    '<div class="hero-metrics-grid">'+
    '<div class="hero-metric-box"><div class="metric-lbl">Live Market LTP</div><div class="metric-val">₹'+h.ltp+'</div><div class="metric-sub">Angel One NFO Live</div></div>'+
    '<div class="hero-metric-box box-entry"><div class="metric-lbl">Suggested Entry</div><div class="metric-val val-green">'+h.entry_bracket+'</div><div class="metric-sub">Planned bracket</div></div>'+
    '<div class="hero-metric-box box-sl"><div class="metric-lbl">Stop-Loss (SL)</div><div class="metric-val val-red">₹'+h.stop_loss+'</div><div class="metric-sub">Strict invalidation</div></div>'+
    '<div class="hero-metric-box box-tgt"><div class="metric-lbl">Target 1 (Primary)</div><div class="metric-val val-green">₹'+h.target_1+'</div><div class="metric-sub">Book 50% lot</div></div>'+
    '<div class="hero-metric-box box-tgt"><div class="metric-lbl">Target 2 (Runner)</div><div class="metric-val val-green">₹'+h.target_2+'</div><div class="metric-sub">Runner target</div></div>'+
    '<div class="hero-metric-box box-tgt"><div class="metric-lbl">Target 3 (Stretch)</div><div class="metric-val val-green">₹'+h.target_3+'</div><div class="metric-sub">Trend stretch</div></div>'+
    '</div>'+
    '<div class="hero-do-not-chase"><span class="info-circle" style="background:#f59e0b33;color:#fbbf24">ⓘ</span><span><strong>DO-NOT-CHASE THRESHOLD: ₹'+h.do_not_chase+'</strong> (If premium gaps above this, setup is EXPIRED / DO NOT CHASE)</span></div>'+
    '<div class="hero-conditions-grid">'+
    '<div class="hero-condition-box cond-entry"><div class="cond-header hdr-entry"><span>✓</span> Entry Confirmation Condition</div><p class="cond-text">'+h.entry_condition+'</p><div class="cond-footer">Holding Horizon: '+h.holding_horizon+'</div></div>'+
    '<div class="hero-condition-box cond-exit"><div class="cond-header hdr-exit"><span>ⓘ</span> Invalidating Condition (Immediate Exit)</div><p class="cond-text">'+h.invalidating_condition+'</p><div class="cond-footer">Underlying Trigger: '+h.underlying_trigger+'</div></div>'+
    '</div>'+
    '<button type="button" class="hero-copy-btn" id="heroCopyBtn">📋 Copy Confirmed '+h.side+' Strike for Angel One Order</button>'+
    '</div></div>';
   const hBtn=document.getElementById('heroCopyBtn');
   if(hBtn){
    hBtn.onclick=()=>{
     if(navigator.clipboard&&navigator.clipboard.writeText){
      navigator.clipboard.writeText(copyTxt).then(()=>{
       hBtn.textContent='Copied to Clipboard! ✓';
       hBtn.classList.add('copied');
      }).catch(()=>{});
     }
    };
   }
  }
  const portBox=document.getElementById('paperPortfolioSection');
  if(portBox&&data.paper_portfolio){
   const p=data.paper_portfolio;
   const real=p.realized_pnl||0;
   const unrl=p.unrealized_mtm||0;
   const pos=p.open_position;
   let posHtml='';
   if(pos){
    const posPnl=pos.unrealized_pnl||0;
    const pnlCls=posPnl>0?'val-green':posPnl<0?'val-red':'';
    posHtml='<div class="active-pos-banner '+(posPnl<0?'in-loss':'')+'">'+
     '<div><div style="font-size:11px;font-weight:700;color:#38bdf8;margin-bottom:2px">⚡ ACTIVE VIRTUAL POSITION · '+(pos.strategy||'')+(pos.pattern?' ('+pos.pattern+')':'')+'</div>'+
     '<div style="font-size:14px;font-weight:700;color:#f8fafc">'+pos.contract+' &nbsp;<span style="font-size:11px;color:#94a3b8">('+pos.lots+' Lot / '+pos.qty+' Qty @ ₹'+pos.entry_price+')</span></div></div>'+
     '<div style="text-align:right"><div style="font-size:11px;color:#94a3b8">Current LTP: <strong>₹'+(pos.current_ltp||pos.entry_price)+'</strong></div>'+
     '<div style="font-size:16px;font-weight:800" class="'+pnlCls+'">'+(posPnl>=0?'+':'')+'₹'+posPnl.toFixed(2)+' ('+(pos.pnl_percent>=0?'+':'')+pos.pnl_percent+'%)</div></div>'+
     '<div><span style="font-size:11px;color:#f87171">SL: ₹'+pos.stop_loss+'</span> &nbsp;|&nbsp; <span style="font-size:11px;color:#34d399">T1: ₹'+pos.target_1+'</span></div>'+
     '</div>';
   }
   let histRows='';
   if(p.trade_history&&p.trade_history.length){
    histRows='<details class="passbook-details"><summary>📖 View Completed Paper Trades Passbook ('+p.trade_history.length+' Trades)</summary>'+
     '<table class="passbook-table"><thead><tr><th>Time</th><th>Contract</th><th>Side</th><th>Entry</th><th>Exit</th><th>P&L (pts)</th><th>Net Cash</th><th>Reason</th></tr></thead><tbody>'+
     p.trade_history.slice().reverse().map(t=>'<tr><td>'+(t.exit_time?t.exit_time.substring(11,19):'—')+'</td><td>'+t.contract+'</td><td>'+t.side+'</td><td>₹'+t.entry_price+'</td><td>₹'+t.exit_price+'</td><td class="'+(t.pnl_pts>0?'val-green':'val-red')+'">'+(t.pnl_pts>0?'+':'')+t.pnl_pts+'</td><td class="'+(t.realized_pnl>0?'val-green':'val-red')+'" style="font-weight:700">'+(t.realized_pnl>0?'+':'')+'₹'+t.realized_pnl+'</td><td>'+t.exit_reason+'</td></tr>').join('')+
     '</tbody></table></details>';
   }
   portBox.style.display='block';
   portBox.innerHTML='<div class="portfolio-header"><div class="portfolio-title"><h3>💼 AUTONOMOUS PAPER TRADING ACCOUNT (Virtual Passbook)</h3><span class="portfolio-badge">VIRTUAL SIMULATOR</span></div>'+
    '<div style="font-size:11px;color:#94a3b8">Initial Capital: <strong>₹'+Number(p.initial_capital||100000).toLocaleString('en-IN')+'</strong></div></div>'+
    '<div class="portfolio-grid">'+
    '<div class="port-stat-card"><div class="port-stat-lbl">Virtual Wallet Balance</div><div class="port-stat-val">₹'+Number(p.current_balance||100000).toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2})+'</div><div class="port-stat-sub">Realized capital</div></div>'+
    '<div class="port-stat-card"><div class="port-stat-lbl">Today\'s Realized P&L</div><div class="port-stat-val '+(real>0?'val-green':real<0?'val-red':'')+'">'+(real>=0?'+':'')+'₹'+real.toFixed(2)+'</div><div class="port-stat-sub">'+(p.wins||0)+' Wins / '+(p.losses||0)+' Losses</div></div>'+
    '<div class="port-stat-card"><div class="port-stat-lbl">Live Open MTM</div><div class="port-stat-val '+(unrl>0?'val-green':unrl<0?'val-red':'')+'">'+(unrl>=0?'+':'')+'₹'+unrl.toFixed(2)+'</div><div class="port-stat-sub">'+(pos?'1 Position Active':'No Open Position')+'</div></div>'+
    '<div class="port-stat-card"><div class="port-stat-lbl">Paper Win Rate</div><div class="port-stat-val val-green">'+(p.win_rate||'0.0%')+'</div><div class="port-stat-sub">Score: '+(p.total_trades||0)+' Closed Trades</div></div>'+
    '</div>'+posHtml+histRows;
  }
  const bannerBox=document.getElementById('masterTrendBanner');
  if(bannerBox&&data.mtf_trend){
   const mtf=data.mtf_trend;
   const isBull=mtf.master_bias==='BULLISH';
   const isBear=mtf.master_bias==='BEARISH';
   const biasText=isBull?'🟢 STRONG BULLISH (CE Bias)':isBear?'🔴 STRONG BEARISH (PE Bias)':'⚪ NEUTRAL / Choppy Range';
   const actionCls=isBull?'good-bg':isBear?'bad-bg':'warn-bg';
   const reg=mtf.market_regime||'EXPANSION';
   const regDesc=mtf.regime_desc||reg;
   const regIcon=reg==='EXPANSION'?'🚀':reg==='RETRACEMENT'?'🔄':reg==='REVERSAL'?'⚠️':'📦';
   const regCls=reg==='EXPANSION'?(isBull?'chip-bull':'chip-bear'):reg==='RETRACEMENT'?'chip-neutral':reg==='REVERSAL'?'chip-bear':'chip-neutral';
   const pdhTxt=mtf.pdh!=null?'₹'+Number(mtf.pdh).toFixed(1):'—';
   const pdlTxt=mtf.pdl!=null?'₹'+Number(mtf.pdl).toFixed(1):'—';
   const pdcTxt=mtf.pdc!=null?'₹'+Number(mtf.pdc).toFixed(1):'—';

   bannerBox.innerHTML='<div class="mtf-header"><div class="mtf-title">'+
    '<span class="mtf-eyebrow">TOP-DOWN MULTI-TIMEFRAME TREND CONFIRMATION (DAILY ➡️ 5M)</span>'+
    '<h3>🧭 Master Bias: <strong class="'+(isBull?'good':isBear?'bad':'warn')+'">'+biasText+'</strong></h3>'+
    '<div style="margin-top:6px;display:flex;align-items:center;gap:8px;flex-wrap:wrap">'+
    '<span class="tf-chip '+regCls+'" style="font-size:12px;font-weight:800;letter-spacing:.02em;padding:4px 10px">⚡ MARKET STATE: '+regIcon+' '+reg+' ('+regDesc+')</span>'+
    '<span style="font-size:11px;color:#94a3b8;background:#0f172a88;border:1px solid #334155;border-radius:6px;padding:3px 9px">📍 <strong>PDH:</strong> '+pdhTxt+' &nbsp;|&nbsp; <strong>PDL:</strong> '+pdlTxt+' &nbsp;|&nbsp; <strong>PDC:</strong> '+pdcTxt+'</span>'+
    '</div></div>'+
    '<div class="mtf-action-box '+actionCls+'"><span>PERMITTED ACTION:</span><strong>'+(mtf.action_permitted||'HIGH CONFLUENCE')+'</strong></div></div>'+
    '<div class="mtf-pills-row">'+
    ['daily','4h','1h','45m','30m','15m','5m'].map(tf=>'<span class="tf-chip '+(mtf[tf]==='BULLISH'?'chip-bull':mtf[tf]==='BEARISH'?'chip-bear':'chip-neutral')+'">'+tf.toUpperCase()+': '+(mtf[tf]||'—')+'</span>').join('')+
    '<span class="tf-alignment-badge">'+(mtf.score||'ALIGNED')+'</span></div>';
  }
  const confluenceIds=new Set((data.confluences||[]).flatMap(group=>group.setup_ids));
  const allCards=Object.entries(data.strategies).flatMap(([key,state])=>
   (state.cards?.length?state.cards:[state]).map(setup=>({key,state,setup})));

  let actCount=0, resCount=0, qualCount=0;
  for(const item of allCards){
   const sig=item.setup?.signal||(item.setup?.entry!=null?item.setup:null)||item.state?.signal;
   const out=sig?.outcome||item.setup?.outcome||{};
   if(sig?.entry!=null){
    if(out.status==='ACTIVE') actCount++;
    else if(out.status==='TARGET_ACHIEVED'||out.status==='SL_HIT'||out.status==='EOD_EXIT') resCount++;
    const isTrendAligned = !data.mtf_trend?.master_bias || (sig.direction === data.mtf_trend.master_bias);
    const isPreCutoff = !sig.timestamp || sig.timestamp.slice(11, 16) < '15:00';
    if(isTrendAligned && isPreCutoff) qualCount++;
   }
  }
  const acEl=document.getElementById('activeCount'); if(acEl) acEl.textContent=actCount;
  const rcEl=document.getElementById('resolvedCount'); if(rcEl) rcEl.textContent=resCount;
  const qcEl=document.getElementById('qualityCount'); if(qcEl) qcEl.textContent=qualCount;

  const cards=allCards.filter(item=>{
   if(currentStratCat!=='ALL'&&strategyCategories[item.key]!==currentStratCat) return false;
   const sig=item.setup?.signal||(item.setup?.entry!=null?item.setup:null)||item.state?.signal;
   const out=sig?.outcome||item.setup?.outcome||{};
   const hasSig=sig?.entry!=null;
   if(currentTradeTab==='active') return hasSig&&out.status==='ACTIVE';
   if(currentTradeTab==='quality'){
    const isTrendAligned = !data.mtf_trend?.master_bias || (sig?.direction === data.mtf_trend.master_bias);
    const isPreCutoff = !sig?.timestamp || sig.timestamp.slice(11, 16) < '15:00';
    return hasSig && isTrendAligned && isPreCutoff;
   }
   if(currentTradeTab==='resolved') return hasSig&&(out.status==='TARGET_ACHIEVED'||out.status==='SL_HIT'||out.status==='EOD_EXIT');
   return true;
  });

  cards.sort((a,b)=>{
   const getSig=x=>x.setup?.signal||(x.setup?.entry!=null?x.setup:null)||x.state?.signal;
   const getOut=x=>getSig(x)?.outcome||x.setup?.outcome||x.state?.signal?.outcome||{};
   const sigA=getSig(a), sigB=getSig(b);
   const outA=getOut(a), outB=getOut(b);
   const hasA=sigA?.entry!=null, hasB=sigB?.entry!=null;
   const isActA=hasA&&(outA.status==='ACTIVE');
   const isActB=hasB&&(outB.status==='ACTIVE');
   if(isActA!==isActB) return isActA?-1:1;
   const isResA=hasA&&(outA.status==='TARGET_ACHIEVED'||outA.status==='SL_HIT');
   const isResB=hasB&&(outB.status==='TARGET_ACHIEVED'||outB.status==='SL_HIT');
   if(isResA!==isResB) return isResA?-1:1;
   if(hasA!==hasB) return hasA?-1:1;
   const timeA=sigA?.timestamp||'';
   const timeB=sigB?.timestamp||'';
   return timeB.localeCompare(timeA);
  });

  if(currentTradeTab==='active'&&cards.length===0){
   const empty=document.createElement('div');empty.className='panel';
   empty.style.gridColumn='1 / -1';empty.style.textAlign='center';empty.style.padding='36px 20px';
   const allowed=data.mtf_trend?.action_permitted||'CALL (CE) ONLY';
   empty.innerHTML='<h3 style="color:#38bdf8;font-size:18px;margin-bottom:8px">⚡ Scanning 10 Strategies for Next Trend-Aligned Entry</h3>'+
    '<p class="muted" style="font-size:13px;max-width:600px;margin:auto">Currently no active trade position open. The scanner is actively monitoring for setups aligned with <strong>'+allowed+'</strong>.</p>'+
    '<p style="font-size:12px;color:#94a3b8;margin-top:14px">👉 Click <strong>🎯 RESOLVED TRADES (History)</strong> above to see completed targets and past trade durations.</p>';
   container.append(empty);
  }
  if(currentTradeTab==='quality'&&cards.length===0){
   const empty=document.createElement('div');empty.className='panel';
   empty.style.gridColumn='1 / -1';empty.style.textAlign='center';empty.style.padding='36px 20px';
   empty.innerHTML='<h3 style="color:#fbbf24;font-size:18px;margin-bottom:8px">⭐ A+ Quality Filter Active</h3>'+
    '<p class="muted" style="font-size:13px;max-width:600px;margin:auto">No trend-aligned setups matching the strict 3:00 PM cut-off. Counter-trend traps have been blocked to protect capital.</p>';
   container.append(empty);
  }

  for(const {key,state,setup} of cards){
   if(currentStratCat!=='ALL'&&strategyCategories[key]!==currentStratCat)continue;
   const card=document.createElement('article');card.className='strategy-card';
   const title=strategyTitles[key]||key.replaceAll('_',' ');
   const {signal:sig,strikes}=setup;
   const dir=sig?.direction||state.direction;
   const out=sig?.outcome||setup.outcome;
   const isActTarget = (sig?.entry!=null) && (out?.status==='ACTIVE');
   if(isActTarget){
    card.classList.add('is-active-target');
    const banner=document.createElement('div');banner.className='active-target-banner';
    banner.innerHTML='<span>⚡ <strong>LIVE ACTIVE TARGET</strong></span><span class="live-pulse-badge">RUNNING: '+displayValue(out.label||'+0.0 pts')+'</span>';
    card.append(banner);
   }

   const headingWrap=document.createElement('div');headingWrap.className='strategy-heading';
   const heading=document.createElement('h3');heading.textContent=title;
   const marketName=document.createElement('span');marketName.className='strategy-market';marketName.textContent=desired;
   headingWrap.append(heading,marketName);card.append(headingWrap);

   const badgeWrap=document.createElement('div');badgeWrap.className='strategy-badges';
   const bias=document.createElement('span');
   bias.textContent=dir==='BULLISH'?'🟢 BULLISH (CE)':dir==='BEARISH'?'🔴 BEARISH (PE)':'⚪ NEUTRAL / Waiting';
   bias.className='direction-pill '+(dir==='BULLISH'?'bullish':dir==='BEARISH'?'bearish':'neutral');badgeWrap.append(bias);
   if(confluenceIds.has(setup.setup_id)){
    const badge=document.createElement('span');badge.className='direction-pill confluence-pill';
    badge.textContent='High confluence';badgeWrap.append(badge);
   }
   const mtfBias=data.mtf_trend?.master_bias;
   const isCounter=(mtfBias==='BULLISH'&&dir==='BEARISH')||(mtfBias==='BEARISH'&&dir==='BULLISH');
   if(isCounter){
    const counterBadge=document.createElement('span');counterBadge.className='counter-trend-warning';
    counterBadge.textContent='⚠️ COUNTER-TREND (High Risk)';badgeWrap.append(counterBadge);
   }
   if(out&&out.status!=='UNKNOWN'&&out.status!=='PENDING'){
    const outBadge=document.createElement('span');
    const isTgt=out.status==='TARGET_ACHIEVED';
    const isSl=out.status==='SL_HIT';
    const isEod=out.status==='EOD_EXIT';
    outBadge.className='outcome-badge '+(isTgt?'outcome-target':isSl?'outcome-sl':isEod?'outcome-eod':'outcome-active');
    const durText=out.duration_label?' · ⏱️ '+out.duration_label:'';
    outBadge.textContent=(isTgt?'🎯 ':isSl?'🛑 ':isEod?'🏁 ':'⚡ ')+out.label+durText;
    badgeWrap.append(outBadge);
   }
   card.append(badgeWrap);

   const status=document.createElement('p');status.className='strategy-status';
   status.textContent=state.status.replaceAll('_',' ')+' · '+state.reason.replaceAll('_',' ');
   card.append(status);

   if(sig?.timestamp){
    const observed=document.createElement('p');observed.className='strategy-context';observed.textContent=[sig.pattern_or_trigger||sig.pattern||sig.signal_type||sig.setup,
      'Observed '+formatIST(sig.timestamp)].filter(Boolean).join(' · ').replaceAll('_',' ');card.append(observed);
    if(sig?.entry!=null){
      const idxBox=document.createElement('div');idxBox.className='index-summary-box';
      const rrVal=sig.risk_reward!=null?sig.risk_reward:'2.0';
      idxBox.innerHTML='<div class="index-summary-item"><span>Entry</span><b>'+displayValue(sig.entry)+'</b></div>'+
       '<div class="index-summary-item sl"><span>Stop Loss</span><b>'+displayValue(sig.stop_loss)+'</b></div>'+
       '<div class="index-summary-item tgt"><span>Target</span><b>'+displayValue(sig.target)+'</b></div>'+
       '<div class="index-summary-item rr"><span>R:R</span><b>1:'+displayValue(rrVal)+'</b></div>';
      card.append(idxBox);
      const idxLvl=document.createElement('p');idxLvl.className='strategy-context';
      idxLvl.style.display='none';
      idxLvl.textContent='Index: Entry '+displayValue(sig.entry)+' · SL '+displayValue(sig.stop_loss)+' · Target '+displayValue(sig.target)+' · R:R 1:'+displayValue(sig.risk_reward);
      card.append(idxLvl);
    }
    if(setup.trade_plan){
      const plan=setup.trade_plan;
      const levels=document.createElement('p');levels.className='strategy-context';
      levels.textContent='Target 2 '+displayValue(plan.target_2)+' · ATR (10, 2) trailing stop '+displayValue(plan.trailing_stop);
      card.append(levels);
    }
   }
   appendStrategyTiming(card,state.timing);
   if(key==='orb'){const p=document.createElement('p');p.className='strategy-context';p.textContent='Range: '+displayValue(state.range.orb_low)+' / '+displayValue(state.range.orb_high);card.append(p)}
   if(key==='oi_trap'){const p=document.createElement('p');p.className='strategy-context';p.textContent='PCR: '+displayValue(state.pcr)+' · Call wall: '+displayValue(state.walls.max_call_oi_strike)+' · Put wall: '+displayValue(state.walls.max_put_oi_strike);card.append(p)}

   const strikeGrid=document.createElement('div');strikeGrid.className='strike-grid';
   const tabGroup=document.createElement('div');tabGroup.className='strike-tab-bar';
   const kinds=['ITM','ATM','OTM'].filter(k=>strikes[k]);
   const defaultKind=strikes['ATM']?'ATM':(kinds[0]||null);

   for(const kind of ['ITM','ATM','OTM']){
    const strike=strikes[kind];if(!strike)continue;
    const isDef=kind===defaultKind;

    const tabBtn=document.createElement('button');tabBtn.type='button';
    tabBtn.className='strike-tab-btn'+(kind==='ATM'?' is-atm':'')+(isDef?' active':'');
    tabBtn.textContent=(kind==='ATM'?'⭐ ATM ':kind+' ')+displayValue(strike.strike)+(kind==='ATM'?' (Rec)':'');
    tabGroup.append(tabBtn);

    const box=document.createElement('div');box.className='strike-box'+(kind==='ATM'?' recommended':'')+(isDef?' active':'');
    const heroHdr=document.createElement('div');heroHdr.className='strike-hero-header';
    const heroTitle=document.createElement('div');heroTitle.style.display='flex';heroTitle.style.alignItems='baseline';heroTitle.style.gap='8px';
    const contract=document.createElement('b');contract.className='strike-price';contract.textContent=displayValue(strike.strike)+' '+strike.side;
    const kindLabel=document.createElement('span');kindLabel.className='strike-kind';kindLabel.textContent=kind;
    const expiry=document.createElement('small');expiry.className='strike-expiry';expiry.textContent='Expiry '+displayValue(strike.expiry);
    heroTitle.append(contract,kindLabel,expiry);
    const recommendation=document.createElement('span');recommendation.className='recommendation';
    recommendation.textContent=kind==='ATM'?'⭐ Recommended Momentum':'\u00a0';
    heroHdr.append(heroTitle,recommendation);box.append(heroHdr);

    const prices=document.createElement('div');prices.className='price-grid';
    for(const [label,value,cls] of [['Entry',strike.premium_entry,'entry'],['SL',strike.premium_sl,'stop'],['Target',strike.premium_target,'target']]){
     const row=document.createElement('div');row.className='price-row '+cls;
     const name=document.createElement('span');name.textContent=label;
     const amount=document.createElement('b');
     if(value!=null){amount.textContent='₹'+Number(value).toFixed(2);}
     else if(label==='SL'&&strike.premium_sl_pts!=null){amount.textContent='-'+strike.premium_sl_pts+' pts';}
     else if(label==='Target'&&strike.premium_target_pts!=null){amount.textContent='+'+strike.premium_target_pts+' pts';}
     else{amount.textContent='— (Quote pending)';}
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
    const copy=document.createElement('button');copy.type='button';copy.className='copy-button';copy.textContent='📋 Copy for Angel One ('+kind+' '+displayValue(strike.strike)+')';copy.setAttribute('aria-label','Copy '+desired+' '+kind+' strike and premium estimates');
    copy.onclick=async()=>{
     try{await navigator.clipboard.writeText(text);copy.textContent='Copied! ✓';copy.classList.add('copied')}
     catch(e){let fallback=box.querySelector('textarea');if(!fallback){fallback=document.createElement('textarea');fallback.className='copy-fallback';fallback.readOnly=true;fallback.value=text;fallback.setAttribute('aria-label','Strike recommendation text to copy');box.append(fallback)}fallback.focus();fallback.select();copy.textContent='Select text to copy'}
    };
    box.append(copy);strikeGrid.append(box);

    tabBtn.onclick=()=>{
     tabGroup.querySelectorAll('.strike-tab-btn').forEach(b=>b.classList.remove('active'));
     tabBtn.classList.add('active');
     strikeGrid.querySelectorAll('.strike-box').forEach(b=>b.classList.remove('active'));
     box.classList.add('active');
    };
   }
   if(kinds.length>1){card.append(tabGroup)}
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
            if state_name in ("STREAM_STOPPED", "SESSION_CLOSED", "DISCONNECTED"):
                now_ist = datetime.now().astimezone(IST)
                if now_ist.time() >= time(15, 30) or now_ist.time() < time(9, 0) or now_ist.weekday() >= 5:
                    live = _tail_live(Path(live_path) if live_path else None)
                    return {
                        "status": "MARKET_CLOSED",
                        "reason": "SESSION_CLOSED_HISTORICAL_REVIEW",
                        "last_candle_close_at": live.get("last_candle_close_at"),
                        "last_candle_close": live.get("last_candle_close")
                    }
            if state_name in ("AUTHENTICATION_REQUIRED", "AUTHENTICATED",
                              "SUBSCRIBING", "STREAM_STOPPED", "SESSION_CLOSED",
                              "DISCONNECTED", "CANCELLED", "ERROR"):
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
                has_feed = selected in live_symbols or live_files["live"].exists()
                live_file = live_files["live"] if has_feed else None
                status_file = live_files["status"] if (selected in live_symbols or live_files["status"].exists()) else None
                options_file = live_files["options"] if (selected in live_symbols or live_files["options"].exists()) else None
                tape_file = live_files["option_tape"] if (selected in live_symbols or live_files["option_tape"].exists()) else None
            else:
                live_file, status_file = live_path, status_path
                options_file, tape_file = None, None
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
                        live_file, status_file, options_file,
                        symbol=selected,
                        tape_path=tape_file,
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
                    live_file, status_file, options_file,
                    symbol=selected,
                    tape_path=tape_file,
                    learning_path=(live_files["learning"] if multi_root is not None
                                   else None))).encode()
                status, mime = 200, "application/json"
            else:
                payload, mime, status = b"Not found", "text/plain", 404
            self._respond(status, mime, payload)

        def _respond(self, status, mime, payload):
            try:
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
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                pass

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
