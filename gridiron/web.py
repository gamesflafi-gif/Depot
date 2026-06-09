"""Web-Oberfläche & API für Gridiron.

Coach wählt ein Team (+ Saison) und bekommt sofort einen lesbaren
Scouting-Report (Tendenzen, Tells, Down&Distanz, Feldzone, Richtungen) plus
eine Live-Pass/Lauf-Vorhersage für eine konkrete Situation. Alles lokal.
"""
from __future__ import annotations

import logging
from dataclasses import asdict

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from gridiron.config import Config, load_config
from gridiron.storage import GridironStore
from gridiron.tendencies import scout

log = logging.getLogger(__name__)

_STYLE = """
 :root{--bg:#0a0e0d;--panel:#111715;--panel2:#161e1b;--fg:#eaf0ed;--mut:#8d9d97;
   --line:#222b28;--acc:#16c784;--accsoft:#0f2a20;--warn:#e9b949;--bad:#ef5350}
 *{box-sizing:border-box}
 body{margin:0;background:var(--bg);color:var(--fg);-webkit-font-smoothing:antialiased;
   font:15px/1.5 ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
 a{color:var(--acc);text-decoration:none}
 .top{background:rgba(10,14,13,.85);backdrop-filter:blur(10px);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:10}
 .topin{max-width:1040px;margin:0 auto;padding:14px 20px;display:flex;align-items:center;justify-content:space-between}
 .brand{font-size:18px;font-weight:800;letter-spacing:.04em;display:flex;align-items:center;gap:14px}
 .brand .mk{width:4px;height:20px;background:var(--acc);border-radius:1px;
   box-shadow:7px 0 0 0 var(--acc),14px 0 0 0 rgba(22,199,132,.45)}
 .brand b{color:var(--acc);font-weight:800}
 .nav a{margin-left:18px;font-size:13.5px;color:var(--mut);font-weight:500}
 .nav a:hover{color:var(--fg)}
 .wrap{max-width:1040px;margin:0 auto;padding:22px 20px 40px}
 .lead{color:var(--mut);font-size:15px;margin:0 0 18px;max-width:700px}
 .controls{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end}
 label{display:block;font-size:11px;color:var(--mut);margin-bottom:5px;text-transform:uppercase;letter-spacing:.06em;font-weight:600}
 select,input{padding:10px 12px;border-radius:9px;border:1px solid var(--line);background:var(--panel2);
   color:var(--fg);font-size:14.5px;transition:border-color .15s,box-shadow .15s}
 select:hover,input:hover{border-color:#2f3a36}
 select:focus,input:focus{outline:none;border-color:var(--acc);box-shadow:0 0 0 3px var(--accsoft)}
 button{padding:10px 18px;border:0;border-radius:9px;background:var(--acc);color:#03130c;
   font-weight:700;cursor:pointer;font-size:14.5px;transition:filter .12s,transform .04s}
 button:hover{filter:brightness(1.08)} button:active{transform:translateY(1px)}
 button[disabled]{opacity:.35;cursor:not-allowed;filter:none}
 button.ghost{background:transparent;color:var(--mut);border:1px solid var(--line)}
 button.ghost:hover{color:var(--fg);border-color:var(--mut);filter:none}
 .card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin:14px 0;
   box-shadow:0 1px 2px rgba(0,0,0,.25)}
 .big{font-size:25px;font-weight:800;letter-spacing:-.01em}
 .row{display:flex;gap:24px;flex-wrap:wrap}
 .kpi{flex:1;min-width:100px}
 .kpi .l{font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.05em;font-weight:600}
 .kpi .v{font-size:23px;font-weight:800;font-variant-numeric:tabular-nums;margin-top:3px}
 .sec{font-size:11.5px;color:var(--mut);text-transform:uppercase;letter-spacing:.08em;margin:20px 0 10px;font-weight:700}
 table{width:100%;border-collapse:collapse;font-size:14px}
 th,td{text-align:left;padding:8px 9px;border-bottom:1px solid var(--line)}
 th{color:var(--mut);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.04em}
 td{font-variant-numeric:tabular-nums}
 .barwrap{position:relative;background:var(--accsoft);border-radius:5px;height:18px;min-width:120px;overflow:hidden}
 .bar{position:absolute;inset:0 auto 0 0;background:var(--acc);border-radius:5px}
 .barleague{position:absolute;top:0;bottom:0;width:2px;background:#dfe7e3;opacity:.85}
 .tell{padding:10px 13px;border-left:3px solid var(--warn);background:var(--panel2);border-radius:0 8px 8px 0;margin:7px 0;font-size:14px}
 .up{color:var(--acc);font-weight:600} .down{color:var(--bad);font-weight:600}
 .gauge{height:24px;border-radius:7px;background:linear-gradient(90deg,#b4513f,#caa23f 52%,var(--acc));position:relative;overflow:hidden;border:1px solid var(--line)}
 .gmark{position:absolute;top:-2px;bottom:-2px;width:3px;background:#fff;box-shadow:0 0 6px rgba(0,0,0,.55)}
 .pill{display:inline-block;background:var(--panel2);border:1px solid var(--line);color:var(--fg);font-weight:600;
   padding:5px 12px;border-radius:7px;font-size:13px;font-variant-numeric:tabular-nums}
 .mut{color:var(--mut);font-size:13.5px} .foot{color:var(--mut);font-size:12px;text-align:center;margin:34px 0 0;opacity:.85}
 code{background:var(--panel2);padding:1px 6px;border-radius:5px;font-size:13px;border:1px solid var(--line)}
 @media(max-width:560px){.controls{gap:10px} .wrap{padding:18px 14px 32px} .big{font-size:22px}}
"""

_STYLE2 = """
 .tabs{display:flex;gap:2px;flex-wrap:wrap;border-bottom:1px solid var(--line);margin:0 0 20px}
 .tab{padding:12px 16px;color:var(--mut);cursor:pointer;font-weight:600;font-size:14px;
   border-bottom:2px solid transparent;margin-bottom:-1px;transition:color .12s}
 .tab:hover{color:var(--fg)} .tab.on{color:var(--fg);border-bottom-color:var(--acc)}
 .sect{display:none} .sect.on{display:block;animation:fade .2s ease}
 @keyframes fade{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
 .grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(140px,1fr))}
 .badge{display:inline-flex;align-items:center;padding:6px 14px;border-radius:8px;font-weight:700;font-size:14px;border:1px solid transparent}
 .b-top{background:var(--accsoft);color:#4be3a0;border-color:#1c5a40}
 .b-off{background:#13271d;color:#86d9af;border-color:#1c4a36} .b-ev{background:#23230f;color:#e6d480;border-color:#4a4520}
 .b-def{background:#2c1c12;color:#eaa877;border-color:#5a3a20} .b-bad{background:#31170f;color:#f08a7a;border-color:#5a2a20}
 .hbar{display:flex;align-items:center;gap:10px;margin:5px 0;font-size:13px}
 .hbar .lab{width:62px;color:var(--mut);text-align:right}
 .hbar .tr{flex:1;background:var(--bg);border:1px solid var(--line);border-radius:5px;height:16px;overflow:hidden}
 .hbar .fl{height:100%;background:var(--acc);opacity:.92}
 .hbar .vv{width:44px;font-variant-numeric:tabular-nums;color:var(--mut)}
 .heat{border-collapse:separate;border-spacing:3px;font-size:12px;width:100%}
 .heat th,.heat td{padding:6px 7px;text-align:center;white-space:nowrap}
 .heat th{color:var(--mut);font-weight:600} .heat td.cn{text-align:left;color:var(--fg);font-weight:600}
 .heat td.val{color:#06140d;font-weight:700;border-radius:5px;min-width:46px;font-variant-numeric:tabular-nums}
 .tbl td,.tbl th{padding:9px 10px;border-bottom:1px solid var(--line);text-align:right}
 .tbl td.cn,.tbl th.cn{text-align:left} .tbl tr.me td{background:var(--accsoft)}
 .scroll{overflow-x:auto} .note{color:var(--mut);font-size:13px;margin-top:8px}
 .reco{padding:11px 14px;background:var(--panel2);border:1px solid var(--line);border-radius:9px;margin:7px 0;font-size:14px;
   display:flex;justify-content:space-between;align-items:center;gap:10px}
 .reco b{font-weight:700} .reco.win{border-color:#1c5a40} .reco.loss{border-color:#5a2a20}
 .reco.champ{border-color:#5a4f20;background:#23200f}
 .tag{display:inline-block;background:var(--warn);color:#1a1400;font-weight:800;font-size:11px;
   padding:3px 9px;border-radius:6px;letter-spacing:.04em}
 /* Section-Header */
 .hero{display:flex;align-items:center;gap:13px;margin:2px 0 18px}
 .hero .hi{width:40px;height:40px;border-radius:11px;background:var(--accsoft);border:1px solid var(--line);
   display:flex;align-items:center;justify-content:center;flex:none}
 .hero .hi svg{width:22px;height:22px;stroke:var(--acc);fill:none;stroke-width:2}
 .hero h2{margin:0;font-size:19px;letter-spacing:-.01em} .hero p{margin:2px 0 0;color:var(--mut);font-size:13.5px}
 /* Play-Art Feld */
 .fieldwrap{margin:12px 0 10px;border-radius:12px;overflow:hidden;border:1px solid #06140d;box-shadow:inset 0 0 40px rgba(0,0,0,.35)}
 #field{display:block;width:100%;height:auto}
 #field .pl{filter:drop-shadow(0 1.5px 1.5px rgba(0,0,0,.55))}
 .pulse{animation:pulse 1.1s ease-in-out infinite}@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
 .fieldlegend{display:flex;gap:16px;flex-wrap:wrap;color:var(--mut);font-size:12px;align-items:center}
 .fieldlegend i.dot{display:inline-block;width:11px;height:11px;border-radius:50%;margin-right:5px;vertical-align:-1px}
 .dot.off{background:#16c784} .dot.tgt{background:#ffd34d} .dot.def{background:#ef5350} .dot.saf{background:#e09b3d}
 /* Manager Team-Identität */
 .teamhdr{display:flex;align-items:center;gap:14px}
 .crest{width:52px;height:52px;border-radius:12px;display:flex;align-items:center;justify-content:center;
   font-weight:800;font-size:17px;color:#fff;flex:none;box-shadow:inset 0 -3px 8px rgba(0,0,0,.3);letter-spacing:.02em}
 .cdot{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:7px;vertical-align:-1px}
 .swatch{width:30px;height:30px;border-radius:8px;cursor:pointer;border:2px solid transparent}
 .swatch.on{border-color:#fff;box-shadow:0 0 0 2px var(--acc)}
 /* TV-Broadcast */
 .tvscore{display:grid;grid-template-columns:1fr auto auto auto 1fr;align-items:center;gap:12px;
   background:#0a0f0d;border:1px solid var(--line);border-radius:11px;padding:14px 16px}
 .tvteam{display:flex;align-items:center;gap:10px}.tvteam.r{justify-content:flex-end}
 .tvteam .ab{font-weight:800;font-size:13px;color:#fff;background:var(--tc);padding:6px 10px;border-radius:7px;letter-spacing:.05em}
 .tvteam .nm{font-weight:700;font-size:15px}
 .tvpts{font-size:34px;font-weight:800;font-variant-numeric:tabular-nums;min-width:50px;text-align:center}
 .tvmid{text-align:center;min-width:60px}.tvmid .qn{font-weight:800;font-size:16px}.tvmid .sub{color:var(--mut);font-size:11px}
 .tvfield{display:flex;height:78px;margin:14px 0 4px;border-radius:10px;overflow:hidden;border:1px solid #06140d}
 .tvfield .ez{width:30px;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:800;font-size:11px;
   writing-mode:vertical-rl;text-orientation:mixed;letter-spacing:.1em;text-shadow:0 1px 2px rgba(0,0,0,.6)}
 .turf{position:relative;flex:1;background:linear-gradient(180deg,#11502f,#0d3f25);overflow:hidden}
 .turf .yl{position:absolute;top:0;bottom:0;width:1px;background:rgba(255,255,255,.16)}
 .turf .yn{position:absolute;top:6px;transform:translateX(-50%);color:rgba(255,255,255,.45);font-size:10px;font-weight:800}
 .turf .yn.b{bottom:6px;top:auto}
 .ball{position:absolute;top:50%;width:15px;height:15px;margin:-8px 0 0 -8px;border-radius:50%;
   background:radial-gradient(circle at 35% 30%,#ffe486,#e0a813);border:1.5px solid #5e4500;
   box-shadow:0 0 12px rgba(255,211,77,.75);transition:left .17s linear;z-index:2}
 .commentary{max-height:230px;overflow-y:auto;margin-top:10px;border:1px solid var(--line);border-radius:9px}
 .cmt{padding:8px 11px;border-bottom:1px solid var(--line);font-size:13.5px;display:flex;gap:10px;align-items:center}
 .cmt:last-child{border-bottom:0}.cmt .q{color:var(--mut);min-width:26px;font-size:11px;font-variant-numeric:tabular-nums}
 .cmt.big{background:var(--accsoft)}
 .pbadge{font-size:10px;font-weight:800;padding:2px 7px;border-radius:5px;min-width:30px;text-align:center;flex:none}
 .pb-td{background:#16c784;color:#04140c}.pb-fg{background:#5fa8ff;color:#04121f}
 .pb-fd{background:#2c3a34;color:#d6efe4}.pb-to{background:#ef5350;color:#240606}.pb-pl{background:#1a221e;color:var(--mut)}
 .obar{display:flex;height:26px;border-radius:7px;overflow:hidden;border:1px solid var(--line);margin-top:2px}
 .oseg{display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:800;color:#06140d;min-width:0}
 .o-ok{background:#16c784}.o-ok2{background:#0e9f6a;color:#eafff5}.o-mid{background:#3a4a44;color:#d6efe4}
 .o-warn{background:#e9b949}.o-bad{background:#ef5350;color:#fff}
 .overlay{position:fixed;inset:0;background:rgba(0,0,0,.72);backdrop-filter:blur(3px);display:flex;align-items:center;justify-content:center;z-index:50;padding:16px}
 .modal{background:var(--panel);border:1px solid var(--line);border-radius:14px;max-width:660px;width:100%;max-height:92vh;overflow:auto;padding:18px 20px}
 .modal h3{margin:0;font-size:16px;display:flex;align-items:center;gap:8px}
 .livedot{width:8px;height:8px;border-radius:50%;background:var(--bad);animation:pulse 1s infinite}
 .modalhead{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}
 /* Interaktiver Spielmodus */
 .dd{display:flex;justify-content:space-between;align-items:center;background:#0a0f0d;border:1px solid var(--line);border-radius:9px;padding:10px 14px;margin:10px 0;font-weight:700;font-variant-numeric:tabular-nums}
 .posbanner{padding:10px 13px;border-radius:9px;margin:10px 0;font-weight:700;font-size:14px}
 .posbanner.off{background:var(--accsoft);color:#4be3a0}.posbanner.def{background:#2c1c12;color:#eaa877}
 .optgrid{display:grid;gap:8px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));margin:6px 0 4px}
 .optbtn{padding:11px 13px;border:1px solid var(--line);background:var(--panel2);color:var(--fg);border-radius:9px;cursor:pointer;text-align:left;font-weight:700;transition:border-color .12s}
 .optbtn:hover{border-color:var(--acc)} .optbtn .ty{display:block;font-size:11px;color:var(--mut);font-weight:500;margin-top:1px}
 /* Manager Sub-Navigation & Kader */
 .subnav{display:flex;gap:6px;flex-wrap:wrap;margin:14px 0}
 .subnav .s{padding:9px 15px;border:1px solid var(--line);border-radius:9px;cursor:pointer;font-weight:600;font-size:13.5px;color:var(--mut)}
 .subnav .s:hover{color:var(--fg)} .subnav .s.on{background:var(--accsoft);color:var(--acc);border-color:#1c5a40}
 .ovrbar{height:5px;background:var(--bg);border:1px solid var(--line);border-radius:3px;overflow:hidden;margin-top:5px;width:170px;max-width:42vw}
 .ovrfill{height:100%;background:var(--acc)}
 .ovrnum{font-weight:800;font-variant-numeric:tabular-nums;font-size:16px}
 .prow{display:flex;align-items:center;gap:12px;padding:9px 11px;border:1px solid var(--line);border-radius:9px;margin:6px 0;cursor:pointer;transition:border-color .12s}
 .prow:hover{border-color:var(--acc)} .prow .ovrnum{min-width:30px;text-align:center}
 .prow .pname{flex:1;font-weight:600} .ptbadge{background:var(--acc);color:#04140c;font-weight:800;font-size:12px;padding:3px 9px;border-radius:7px}
 .pcols{display:flex;gap:18px;flex-wrap:wrap;align-items:center;margin-top:12px}
 .radarwrap{flex:none} .attrs{flex:1;min-width:240px}
 .arow{display:flex;align-items:center;gap:10px;margin:7px 0}
 .arow .alab{width:96px;font-size:13px;color:var(--mut)}
 .arow .abar{position:relative;flex:1;height:9px;background:var(--bg);border:1px solid var(--line);border-radius:5px;overflow:hidden}
 .arow .afill{position:absolute;inset:0 auto 0 0;background:var(--acc)}
 .arow .acap{position:absolute;top:-2px;bottom:-2px;width:2px;background:#dfe7e3;opacity:.8}
 .arow .aval{width:26px;text-align:right;font-weight:700;font-variant-numeric:tabular-nums}
 .arow button{padding:4px 11px;border-radius:7px;font-size:15px;line-height:1}
 .ctraits{margin-top:8px} .ctrait{display:flex;align-items:center;gap:10px;margin:5px 0;font-size:13px}
 .ctrait>span:first-child{width:130px;color:var(--mut)}
 .ctrait .abar{flex:1} .ctrait .aval{width:26px;text-align:right;font-weight:700}
"""

_PAGE = """<!doctype html><html lang="de"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Gridiron — NFL-Analyseplattform</title><style>""" + _STYLE + _STYLE2 + """</style></head><body>
<div class="top"><div class="topin">
 <div class="brand"><span class="mk"></span> GRID<b>IRON</b></div>
 <div class="nav"><a href="/report" target="_blank">Druck-Report</a></div>
</div></div>
<div class="wrap">
 <div class="tabs">
  <div class="tab on" data-s="scout" onclick="tab('scout')">Scouting</div>
  <div class="tab" data-s="sim" onclick="tab('sim')">Play-Simulator</div>
  <div class="tab" data-s="matrix" onclick="tab('matrix')">Matchup-Matrix</div>
  <div class="tab" data-s="mgr" onclick="tab('mgr')">Manager</div>
 </div>

 <!-- ============ SCOUTING ============ -->
 <div class="sect on" id="s-scout">
 <div class="hero"><div class="hi"><svg viewBox="0 0 24 24"><path d="M4 20V10M10 20V4M16 20v-8M22 20H2"/></svg></div>
  <div><h2>Scouting</h2><p>Gegner-Tendenzen, „Tells" und die Live-Pass/Lauf-Vorhersage.</p></div></div>
 <div class="controls">
  <div><label>Team</label><select id="team"></select></div>
  <div><label>Saison</label><select id="season"></select></div>
  <button onclick="loadScout()">Report erstellen</button>
 </div>
 <div id="rep"></div>
 <div class="card">
  <div class="sec" style="margin-top:0">Live-Vorhersage: Pass oder Lauf?</div>
  <div class="controls">
   <div><label>Down</label><select id="p_down"><option>1</option><option>2</option><option selected>3</option><option>4</option></select></div>
   <div><label>Yards to go</label><input id="p_ytg" type="number" value="8" style="width:90px"></div>
   <div><label>Yards z. EZ</label><input id="p_yl" type="number" value="65" style="width:90px"></div>
   <div><label>Viertel</label><select id="p_qtr"><option>1</option><option selected>2</option><option>3</option><option>4</option></select></div>
   <div><label>Score-Diff</label><input id="p_sd" type="number" value="0" style="width:80px"></div>
   <div><label>Shotgun</label><select id="p_sg"><option value="0">nein</option><option value="1" selected>ja</option></select></div>
   <button onclick="predict()">Vorhersagen</button>
  </div>
  <div id="pred"></div>
 </div>
 </div>

 <!-- ============ SIMULATOR ============ -->
 <div class="sect" id="s-sim">
 <div class="hero"><div class="hi"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 3v18M3 12h18"/></svg></div>
  <div><h2>Play-Simulator</h2><p>Konzept gegen Coverage durchspielen — animiert auf dem Feld, mit voller Ertragsverteilung.</p></div></div>
 <div class="card">
  <div class="controls">
   <div><label>Konzept (Offense)</label><select id="sim_c" style="min-width:190px"></select></div>
   <div><label>Coverage (Defense)</label><select id="sim_cov" style="min-width:220px"></select></div>
  </div>
  <div class="controls" style="margin-top:10px">
   <div><label>Down</label><select id="sim_d"><option>1</option><option selected>2</option><option>3</option><option>4</option></select></div>
   <div><label>Distanz</label><input id="sim_y" type="number" value="8" style="width:80px"></div>
   <div><label>Yards z. EZ</label><input id="sim_yl" type="number" value="55" style="width:90px"></div>
   <div><label>Personnel</label><select id="sim_p"><option>11</option><option>12</option><option>21</option><option>13</option><option>10</option></select></div>
   <div><label>Box (optional)</label><input id="sim_box" type="number" value="" placeholder="auto" style="width:90px"></div>
   <button onclick="runSim()">Simulieren</button>
  </div>
 </div>
 <div class="card" id="sim_fieldcard" style="display:none">
  <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
   <div class="sec" style="margin:0">Spielzug</div>
   <div><span id="field_title" class="mut"></span> &nbsp;<button class="ghost" id="replayBtn" onclick="replayPlay()">▶ Abspielen</button></div>
  </div>
  <div class="fieldwrap"><svg id="field" viewBox="0 0 533 360" preserveAspectRatio="xMidYMid meet"></svg></div>
  <div class="fieldlegend"><span><i class="dot off"></i>Offense</span><span><i class="dot tgt"></i>Anspielziel</span>
   <span><i class="dot def"></i>Defense</span><span><i class="dot saf"></i>Safety (tief)</span></div>
 </div>
 <div id="sim_out"></div>
 <div class="grid" style="grid-template-columns:1fr 1fr">
  <div class="card"><div class="sec" style="margin-top:0">Beste Antwort auf diese Coverage</div><div id="sim_best" class="mut">—</div></div>
  <div class="card"><div class="sec" style="margin-top:0">Was stoppt dieses Konzept?</div><div id="sim_stop" class="mut">—</div></div>
 </div>
 </div>

 <!-- ============ MATRIX ============ -->
 <div class="sect" id="s-matrix">
 <div class="hero"><div class="hi"><svg viewBox="0 0 24 24"><path d="M3 3h18v18H3zM3 9h18M3 15h18M9 3v18M15 3v18"/></svg></div>
  <div><h2>Matchup-Matrix</h2><p>Erwartetes EPA für jedes Konzept × jede Coverage. Grün = Offense, Rot = Defense.</p></div></div>
 <div class="card">
  <div class="controls">
   <div><label>Down</label><select id="m_d"><option selected>1</option><option>2</option><option>3</option><option>4</option></select></div>
   <div><label>Distanz</label><input id="m_y" type="number" value="10" style="width:80px"></div>
   <div><label>Yards z. EZ</label><input id="m_yl" type="number" value="60" style="width:90px"></div>
   <div><label>Personnel</label><select id="m_p"><option>11</option><option>12</option><option>21</option></select></div>
   <button onclick="runMatrix()">Matrix berechnen</button>
  </div>
 </div>
 <div id="matrix_out"></div>
 </div>

 <!-- ============ MANAGER / FRANCHISE ============ -->
 <div class="sect" id="s-mgr">
 <div class="hero"><div class="hi"><svg viewBox="0 0 24 24"><path d="M6 3h12v4a6 6 0 0 1-12 0zM4 5h2M18 5h2M9 13h6v3H9zM8 21h8M12 16v5"/></svg></div>
  <div><h2>Franchise-Manager</h2><p>Eigenes Team aufbauen, Liga-Saison spielen, Spiele live ansehen und den Titel holen.</p></div></div>
 <div id="mgr_out" class="mut">Lade …</div>
 </div>

 <div class="foot">Simulation = echte Liga-Basisraten × kalibrierte Football-Matchup-Logik. Wahrscheinlichkeiten, keine Garantie.</div>
</div>
<script>
const $=id=>document.getElementById(id);
function esc(s){const d=document.createElement('div');d.textContent=(s==null?'':s);return d.innerHTML;}
const pct=x=>Math.round(x*100)+'%';
const sgn=x=>(x>=0?'+':'')+x.toFixed(2);

function tab(s){document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('on',t.dataset.s===s));
 document.querySelectorAll('.sect').forEach(e=>e.classList.remove('on'));$('s-'+s).classList.add('on');
 if(s==='sim'&&!simReady)initSim(); if(s==='matrix'&&!$('matrix_out').dataset.done)runMatrix();
 if(s==='mgr')loadMgr();}

async function init(){
 const d=await (await fetch('/api/teams')).json();
 if(!d.teams.length){
  $('team').innerHTML='<option>— keine Daten —</option>';
  $('season').innerHTML='<option value="">—</option>';
  $('rep').innerHTML='<div class="card">Noch <b>keine Daten</b> im Lake. <b>Play-Simulator</b> und '+
   '<b>🏈 Manager</b> (Tabs oben) funktionieren sofort — probier sie aus!<br>'+
   '<span class="mut">Für Scouting Daten laden: <code>python -m gridiron.cli ingest</code> '+
   '(im Sample-Modus passiert das beim Serverstart automatisch).</span></div>';
  return;
 }
 $('team').innerHTML=d.teams.map(t=>'<option>'+esc(t)+'</option>').join('');
 $('season').innerHTML='<option value="">alle</option>'+d.seasons.map(s=>'<option>'+s+'</option>').join('');
 loadScout();
}
async function loadScout(){
 const team=$('team').value, season=$('season').value;
 $('rep').innerHTML='<div class="card mut">Analysiere …</div>';
 const r=await (await fetch('/api/scout?team='+encodeURIComponent(team)+'&season='+encodeURIComponent(season))).json();
 if(!r.n_plays){$('rep').innerHTML='<div class="card">Keine Daten für '+esc(team)+'.</div>';return;}
 let h='<div class="card"><div class="row">'+
  '<div class="kpi"><div class="l">Plays</div><div class="v">'+r.n_plays+'</div></div>'+
  '<div class="kpi"><div class="l">Pass</div><div class="v">'+pct(r.pass_rate)+'</div></div>'+
  '<div class="kpi"><div class="l">Run</div><div class="v">'+pct(1-r.pass_rate)+'</div></div>'+
  '<div class="kpi"><div class="l">Liga Pass</div><div class="v">'+pct(r.league_pass_rate)+'</div></div>'+
  '<div class="kpi"><div class="l">EPA/Play</div><div class="v">'+(r.epa>=0?'+':'')+r.epa.toFixed(2)+'</div></div>'+
  '<div class="kpi"><div class="l">Play-Action</div><div class="v">'+pct(r.play_action_rate)+'</div></div>'+
  '</div></div>';
 if(r.tells.length){h+='<div class="card"><div class="sec" style="margin-top:0">Vorhersehbar (Tells)</div>';
  r.tells.forEach(t=>{const lab=t.pass_rate>=0.5?pct(t.pass_rate)+' Pass':pct(1-t.pass_rate)+' Run';
   h+='<div class="tell">'+t.down+'. &amp; '+esc(t.dist)+', '+esc(t.zone)+' → <b>'+lab+'</b> <span class="mut">(n='+t.n+')</span></div>';});
  h+='</div>';}
 h+='<div class="card"><div class="sec" style="margin-top:0">Nach Down &amp; Distanz (vs. Liga)</div>'+
  '<table><tr><th>Situation</th><th>Pass</th><th>vs. Liga</th><th>EPA</th><th>n</th></tr>';
 r.by_down_dist.forEach(x=>{const w=Math.round(x.pass_rate*100);const lw=Math.round(x.league_pass_rate*100);
  const dcl=x.delta>0.05?'up':x.delta<-0.05?'down':'';
  h+='<tr><td>'+x.down+'. &amp; '+esc(x.dist)+'</td>'+
   '<td><div class="barwrap"><div class="bar" style="width:'+w+'%"></div>'+
   '<div class="barleague" style="left:'+lw+'%"></div></div></td>'+
   '<td class="'+dcl+'">'+(x.delta>=0?'+':'')+Math.round(x.delta*100)+'pp</td>'+
   '<td>'+(x.epa>=0?'+':'')+x.epa.toFixed(2)+'</td><td>'+x.n+'</td></tr>';});
 h+='</table><div class="mut" style="margin-top:6px">Balken = Pass-Rate des Teams · weiße Linie = Liga-Schnitt</div></div>';
 if(r.by_zone.length){h+='<div class="card"><div class="sec" style="margin-top:0">Nach Feldzone</div><table><tr><th>Zone</th><th>Pass</th><th>EPA</th><th>n</th></tr>';
  r.by_zone.forEach(z=>h+='<tr><td>'+esc(z.zone)+'</td><td>'+pct(z.pass_rate)+'</td><td>'+(z.epa>=0?'+':'')+z.epa.toFixed(2)+'</td><td>'+z.n+'</td></tr>');
  h+='</table></div>';}
 const dirs=[];
 if(r.run_gaps.length)dirs.push('<b>Lauf:</b> '+r.run_gaps.map(g=>esc(g.gap)+' '+g.n).join(' · '));
 if(r.pass_locations.length)dirs.push('<b>Pass:</b> '+r.pass_locations.map(p=>esc(p.loc)+' '+p.n).join(' · '));
 if(dirs.length)h+='<div class="card"><div class="sec" style="margin-top:0">Richtungen</div>'+dirs.join('<br>')+'</div>';
 $('rep').innerHTML=h;
}
async function predict(){
 const team=$('team').value;
 const qs='team='+encodeURIComponent(team)+'&down='+$('p_down').value+'&ydstogo='+$('p_ytg').value+
  '&yardline='+$('p_yl').value+'&qtr='+$('p_qtr').value+'&score_diff='+$('p_sd').value+'&shotgun='+$('p_sg').value;
 const r=await (await fetch('/api/predict?'+qs)).json();
 if(r.error){$('pred').innerHTML='<div class="mut" style="margin-top:10px">'+esc(r.error)+'</div>';return;}
 const w=Math.round(r.pass_prob*100);
 $('pred').innerHTML='<div style="margin-top:14px"><div class="gauge"><div class="gmark" style="left:'+w+'%"></div></div>'+
  '<div class="row" style="margin-top:10px">'+
  '<div class="kpi"><div class="l">Pass</div><div class="v">'+pct(r.pass_prob)+'</div></div>'+
  '<div class="kpi"><div class="l">Lauf</div><div class="v">'+pct(r.run_prob)+'</div></div>'+
  '<div class="kpi"><div class="l">Erwartet</div><div class="v"><span class="pill">'+esc(r.likely)+'</span></div></div>'+
  '<div class="kpi"><div class="l">Vorhersehbarkeit</div><div class="v">'+pct(r.predictability)+'</div></div>'+
  '</div></div>';
}

/* ===================== SIMULATOR ===================== */
let simReady=false;
function badge(v){const e=v.expected_epa;let c='b-ev';
 if(e>=0.20)c='b-top';else if(e>=0.07)c='b-off';else if(e>=-0.05)c='b-ev';else if(e>=-0.18)c='b-def';else c='b-bad';
 return '<span class="badge '+c+'">'+esc(v.verdict)+'  ('+sgn(e)+' EPA)</span>';}
function simSit(pfx){return 'down='+$(pfx+'d').value+'&ydstogo='+$(pfx+'y').value+'&yardline='+$(pfx+'yl').value+
 '&personnel='+$(pfx+'p').value+'&box='+(pfx==='sim_'?($('sim_box').value||0):0);}
async function initSim(){
 const m=await (await fetch('/api/sim/meta')).json();
 const pass=m.concepts.filter(c=>c.type==='Pass'),run=m.concepts.filter(c=>c.type==='Lauf');
 $('sim_c').innerHTML='<optgroup label="Pass">'+pass.map(c=>'<option value="'+esc(c.key)+'">'+esc(c.label)+'</option>').join('')+
  '</optgroup><optgroup label="Lauf">'+run.map(c=>'<option value="'+esc(c.key)+'">'+esc(c.label)+'</option>').join('')+'</optgroup>';
 $('sim_cov').innerHTML=m.coverages.map(c=>'<option value="'+esc(c.key)+'">'+esc(c.label)+'</option>').join('');
 simReady=true; runSim();
}
function kpi(l,v){return '<div class="kpi"><div class="l">'+l+'</div><div class="v">'+v+'</div></div>';}
function segCol(cls){return {ok:'#16c784',ok2:'#0e9f6a',mid:'#3a4a44',warn:'#e9b949',bad:'#ef5350'}[cls]||'#3a4a44';}
async function runSim(){
 const c=$('sim_c').value,cov=$('sim_cov').value;
 const qs='concept='+encodeURIComponent(c)+'&coverage='+encodeURIComponent(cov)+'&'+simSit('sim_');
 $('sim_out').innerHTML='<div class="card mut">Simuliere …</div>';
 const r=await (await fetch('/api/sim/run?'+qs)).json();
 if(r.error){$('sim_out').innerHTML='<div class="card">'+esc(r.error)+'</div>';return;}
 let h='<div class="card"><div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">'+
   '<div class="big">'+esc(c)+' <span class="mut" style="font-size:15px">vs '+esc(cov)+'</span></div>'+badge(r)+'</div>'+
   '<div class="grid" style="margin-top:14px">'+
   kpi('Ø Yards',r.mean_yards.toFixed(1))+kpi('Erfolgsrate',pct(r.success_rate))+
   kpi('Big Play',pct(r.explosive_rate))+kpi('Touchdown',pct(r.td_rate))+
   kpi('Turnover',pct(r.turnover_rate))+kpi('Sack',pct(r.sack_rate))+
   (r.is_pass?kpi('Completion',pct(r.completion_rate))+kpi('Interception',pct(r.int_rate)):kpi('Ø EPA',sgn(r.expected_epa)))+
   kpi('Matchup','×'+r.matchup_factor.toFixed(2))+
   '</div>';
 // Ergebnis-Wahrscheinlichkeiten (Stacked Bar)
 h+='<div class="sec">Ergebnis-Wahrscheinlichkeiten</div><div class="obar">';
 r.outcomes.forEach(o=>{if(o.pct>0.004)h+='<div class="oseg o-'+o.cls+'" style="width:'+(o.pct*100)+'%">'+(o.pct>=0.09?Math.round(o.pct*100)+'%':'')+'</div>';});
 h+='</div><div class="fieldlegend" style="margin-top:7px">'+
   r.outcomes.map(o=>'<span><i class="dot" style="background:'+segCol(o.cls)+'"></i>'+esc(o.label)+' '+pct(o.pct)+'</span>').join('')+'</div>';
 h+='<div class="sec">Ertragsverteilung (Yards)</div>';
 const mx=Math.max(...r.hist.map(b=>b.pct))||1;
 r.hist.forEach(b=>{h+='<div class="hbar"><div class="lab">'+esc(b.label)+'</div>'+
   '<div class="tr"><div class="fl" style="width:'+(b.pct/mx*100)+'%"></div></div>'+
   '<div class="vv">'+pct(b.pct)+'</div></div>';});
 h+='<div class="note">'+esc(r.note)+'</div></div>';
 $('sim_out').innerHTML=h;
 drawPlay(c,cov,r); loadBest(cov); loadStop(c);
}

/* ---------- Spielfeld & Animation ---------- */
const SVGNS='http://www.w3.org/2000/svg';
let lastDiag=null,lastRes=null,animReq=null;
const mapX=x=>x*10, mapY=fy=>10+(26-fy)*10;
function el(tag,a){const e=document.createElementNS(SVGNS,tag);for(const k in a)e.setAttribute(k,a[k]);return e;}
function routeLen(pts){let L=0;for(let i=1;i<pts.length;i++)L+=Math.hypot(pts[i][0]-pts[i-1][0],pts[i][1]-pts[i-1][1]);return L;}
function posAlong(pts,frac){if(pts.length<2)return pts[0];const tot=routeLen(pts);let d=frac*tot;for(let i=1;i<pts.length;i++){const seg=Math.hypot(pts[i][0]-pts[i-1][0],pts[i][1]-pts[i-1][1]);if(d<=seg||i===pts.length-1){const t=seg?d/seg:0;return [pts[i-1][0]+(pts[i][0]-pts[i-1][0])*t,pts[i-1][1]+(pts[i][1]-pts[i-1][1])*t];}d-=seg;}return pts[pts.length-1];}
async function drawPlay(concept,coverage,res){
 const d=await (await fetch('/api/sim/diagram?concept='+encodeURIComponent(concept)+'&coverage='+encodeURIComponent(coverage))).json();
 if(d.error)return; lastDiag=d; lastRes=res;
 $('sim_fieldcard').style.display='block';
 $('field_title').textContent=concept+' vs '+coverage.replace(/ —.*/,'');
 renderField(d); playAnim();
}
function renderField(d){
 const svg=$('field'); const ytg=parseInt($('sim_y').value)||10;
 let s='<defs>'+
  '<linearGradient id="turf" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#125433"/><stop offset="1" stop-color="#0b3a22"/></linearGradient>'+
  '<marker id="ah" markerWidth="7" markerHeight="7" refX="4.5" refY="3" orient="auto"><path d="M0 0L6 3L0 6Z" fill="#19e08f"/></marker>'+
  '<marker id="aht" markerWidth="7" markerHeight="7" refX="4.5" refY="3" orient="auto"><path d="M0 0L6 3L0 6Z" fill="#ffd34d"/></marker></defs>';
 s+='<rect x="0" y="0" width="533" height="360" fill="url(#turf)"/>';
 for(let i=0;i<8;i++)if(i%2)s+='<rect x="0" y="'+(i*45)+'" width="533" height="45" fill="#ffffff" opacity="0.025"/>';
 for(let fy=-5;fy<=25;fy+=5){const y=mapY(fy).toFixed(1);
  s+='<line x1="0" y1="'+y+'" x2="533" y2="'+y+'" stroke="#cdeede" stroke-width="'+(fy===0?0:1)+'" opacity="0.22"/>';
  [23.58,29.72].forEach(hx=>{s+='<line x1="'+(mapX(hx)-3).toFixed(1)+'" y1="'+y+'" x2="'+(mapX(hx)+3).toFixed(1)+'" y2="'+y+'" stroke="#cdeede" stroke-width="1" opacity="0.32"/>';});
  if(fy>0&&fy%10===0){s+='<text x="13" y="'+(parseFloat(y)+4)+'" font-size="11" font-weight="800" fill="#cdeede" opacity="0.4">'+fy+'</text>'+
    '<text x="520" y="'+(parseFloat(y)+4)+'" font-size="11" font-weight="800" fill="#cdeede" opacity="0.4" text-anchor="end">'+fy+'</text>';}}
 s+='<line x1="0" y1="'+mapY(0)+'" x2="533" y2="'+mapY(0)+'" stroke="#5fa8ff" stroke-width="2.5" opacity="0.9"/>';
 if(ytg<=24)s+='<line x1="0" y1="'+mapY(ytg)+'" x2="533" y2="'+mapY(ytg)+'" stroke="#ffd34d" stroke-width="2" opacity="0.7" stroke-dasharray="7 5"/>';
 d.offense.forEach(o=>{if(o.route&&o.route.length>1){let p='';o.route.forEach((pt,i)=>{p+=(i?'L':'M')+mapX(pt[0]).toFixed(1)+' '+mapY(pt[1]).toFixed(1)+' ';});
  const acc=(o.target||o.carry);s+='<path d="'+p+'" fill="none" stroke="'+(acc?'#ffd34d':'#19e08f')+'" stroke-width="'+(acc?2.4:1.7)+'" opacity="'+(acc?0.95:0.6)+'" marker-end="url(#'+(acc?'aht':'ah')+')"/>';}});
 svg.innerHTML=s;
 d.defense.forEach((p,i)=>addPlayer(svg,p,p.deep?'#e09b3d':'#ef5350','d_'+i));
 d.offense.forEach((o,i)=>addPlayer(svg,o,o.target?'#ffd34d':(o.pos==='OL'?'#0c8f5d':'#16c784'),'o'+i,o));
 const qb=d.offense.find(o=>o.pos==='QB');
 svg.appendChild(el('circle',{id:'pball',cx:mapX(qb.x),cy:mapY(qb.y),r:3.8,fill:'#fff',opacity:0}));
}
function addPlayer(svg,p,color,id,o){
 const g=el('g',{});
 if(o&&o.target){const ring=el('circle',{cx:mapX(p.x),cy:mapY(p.y),r:11.5,fill:'none',stroke:'#ffd34d','stroke-width':1.6,opacity:.85,'class':'pulse'});ring.id='rg_'+id;g.appendChild(ring);}
 const c=el('circle',{cx:mapX(p.x),cy:mapY(p.y),r:7.5,fill:color,stroke:'#06140d','stroke-width':1.5,'class':'pl'});c.id='pl_'+id;
 g.appendChild(c);
 const lbl=(o?(o.pos==='OL'?'':o.pos):p.pos); if(lbl){const t=el('text',{x:mapX(p.x),y:mapY(p.y)+2.8,'text-anchor':'middle','font-size':7.5,fill:'#03130c','font-weight':800});t.textContent=lbl;t.id='tx_'+id;g.appendChild(t);}
 svg.appendChild(g);
}
function moveP(id,x,y){const c=$('pl_'+id);if(!c)return;c.setAttribute('cx',mapX(x));c.setAttribute('cy',mapY(y));
 const t=$('tx_'+id);if(t){t.setAttribute('x',mapX(x));t.setAttribute('y',mapY(y)+2.8);}
 const r=$('rg_'+id);if(r){r.setAttribute('cx',mapX(x));r.setAttribute('cy',mapY(y));}}
function curPos(id){const c=$('pl_'+id);return c?[parseFloat(c.getAttribute('cx'))/10,26-(parseFloat(c.getAttribute('cy'))-10)/10]:null;}
function playAnim(){
 if(!lastDiag)return; cancelAnimationFrame(animReq);
 const d=lastDiag,T=2200,t0=performance.now();
 const qbi=d.offense.findIndex(o=>o.pos==='QB'),qb=d.offense[qbi];
 const tgt=d.ball_target,isPass=d.kind==='pass',throwAt=.55,ball=$('pball');
 const ease=t=>1-Math.pow(1-t,2);
 function frame(now){const t=Math.min(1,(now-t0)/T),te=ease(t);
  // Offense entlang der Routen, Positionen merken
  const sp={};
  d.offense.forEach((o,i)=>{if(o.route&&o.route.length>1){const pp=posAlong(o.route,te);moveP('o'+i,pp[0],pp[1]);if(o.pos)sp[o.pos]=pp;}else if(o.pos)sp[o.pos]=[o.x,o.y];});
  // QB-Drop (Shotgun -> kurzer Drop)
  const qy=qb.y-1.4*Math.min(1,t*2.2); moveP('o'+qbi,qb.x,qy); sp['QB']=[qb.x,qy];
  // Defense nach Rolle
  d.defense.forEach((p,i)=>{const id='d_'+i,cur=curPos(id)||[p.x,p.y];let tx,ty,k;
   if(p.role==='rush'){tx=qb.x+(p.x-qb.x)*0.12;ty=qy+0.8;k=0.09;}
   else if(p.role==='man'&&sp[p.cover]){const r=sp[p.cover];tx=r[0]+(p.x<r[0]?-0.7:0.7);ty=r[1]+0.8;k=0.20;}  // trailt knapp dahinter
   else if(p.drop){tx=p.drop[0];ty=p.drop[1];                                  // Zone: zur Landmarke, leicht auf nächsten Receiver reagieren
     let best=null,bd=99;for(const key in sp){if(key==='QB')continue;const r=sp[key];const dd=Math.hypot(r[0]-tx,r[1]-ty);if(dd<bd){bd=dd;best=r;}}
     if(best&&bd<11){tx+=(best[0]-tx)*0.32;ty+=(best[1]-ty)*0.16;} k=0.10;}
   else {tx=p.x;ty=p.y;k=0.1;}
   moveP(id,cur[0]+(tx-cur[0])*k,cur[1]+(ty-cur[1])*k);
  });
  if(isPass&&ball&&t>=throwAt){const tt=(t-throwAt)/(1-throwAt);ball.setAttribute('opacity',1);
    ball.setAttribute('cx',mapX(qb.x+(tgt[0]-qb.x)*tt));ball.setAttribute('cy',mapY(qy+(tgt[1]-qy)*tt-Math.sin(tt*Math.PI)*1.3));}
  if(t<1)animReq=requestAnimationFrame(frame); else showResult();
 }
 animReq=requestAnimationFrame(frame);
}
function showResult(){const svg=$('field');if(!lastRes||!lastDiag)return;const tgt=lastDiag.ball_target;
 const g=el('g',{}); const x=Math.min(Math.max(mapX(tgt[0]),40),493),y=Math.max(mapY(tgt[1])-14,16);
 g.appendChild(el('rect',{x:x-26,y:y-13,width:52,height:20,rx:5,fill:'#0a0f0d',stroke:'#ffd34d','stroke-width':1.2}));
 const t=el('text',{x:x,y:y+1,'text-anchor':'middle','font-size':11,fill:'#ffd34d','font-weight':800});
 t.textContent=(lastRes.mean_yards>=0?'+':'')+lastRes.mean_yards.toFixed(1)+' Yds'; g.appendChild(t); svg.appendChild(g);}
function replayPlay(){renderField(lastDiag);playAnim();}
async function loadBest(cov){
 const r=await (await fetch('/api/sim/best?coverage='+encodeURIComponent(cov)+'&'+simSit('sim_'))).json();
 $('sim_best').innerHTML=r.items.map(x=>'<div class="reco"><span><b>'+esc(x.concept)+'</b> <span class="mut">'+
  (x.is_pass?'Pass':'Lauf')+'</span></span><span>'+sgn(x.expected_epa)+' EPA · '+pct(x.success_rate)+'</span></div>').join('');
}
async function loadStop(c){
 const r=await (await fetch('/api/sim/stop?concept='+encodeURIComponent(c)+'&'+simSit('sim_'))).json();
 if(r.error){$('sim_stop').innerHTML=esc(r.error);return;}
 $('sim_stop').innerHTML=r.items.slice(0,5).map(x=>'<div class="reco"><span><b>'+esc(x.coverage)+'</b></span>'+
  '<span>'+sgn(x.expected_epa)+' EPA (Offense)</span></div>').join('');
}

/* ===================== MATRIX ===================== */
function heatColor(e){const v=Math.max(-0.45,Math.min(0.45,e));const t=(v+0.45)/0.9; // 0=rot..1=grün
 const hue=t*130; return 'hsl('+hue+',62%,'+(48+18*Math.abs(t-0.5))+'%)';}
async function runMatrix(){
 $('matrix_out').innerHTML='<div class="card mut">Berechne Matrix (tausende Simulationen) …</div>';
 const qs='down='+$('m_d').value+'&ydstogo='+$('m_y').value+'&yardline='+$('m_yl').value+'&personnel='+$('m_p').value;
 const r=await (await fetch('/api/sim/matrix?'+qs)).json();
 let h='<div class="card scroll"><table class="heat"><tr><th class="cn">Konzept</th>';
 r.coverages.forEach(c=>h+='<th>'+esc(c.replace(/ —.*/,'').replace(/ [(].*/,''))+'</th>');
 h+='</tr>';
 r.rows.forEach(row=>{h+='<tr><td class="cn">'+esc(row.label)+' <span class="mut">'+row.type+'</span></td>';
  row.epa.forEach(e=>h+='<td class="val" style="background:'+heatColor(e)+'">'+sgn(e)+'</td>');h+='</tr>';});
 h+='</table><div class="note">Quelle Basisraten: '+esc(r.source)+'</div></div>';
 $('matrix_out').innerHTML=h; $('matrix_out').dataset.done='1';
}

/* ===================== MANAGER / FRANCHISE ===================== */
let mgrMeta=null;
async function api(path,method){return (await fetch(path,{method:method||'GET'})).json();}
async function loadMgr(){
 if(!mgrMeta)mgrMeta=await api('/api/fr/meta');
 const s=await api('/api/fr/state');
 if(!s.exists){renderNewTeam();return;}
 renderMgr(s.view);
}
let ntColor=null;
function renderNewTeam(){
 ntColor=mgrMeta.colors[0];
 $('mgr_out').innerHTML='<div class="card"><div class="sec" style="margin-top:0">Neue Franchise gründen</div>'+
  '<div class="controls"><div><label>Teamname</label><input id="nt_name" value="Mein Team" style="width:200px"></div>'+
  '<div><label>Liga-Größe</label><select id="nt_n"><option>6</option><option selected>8</option><option>10</option><option>12</option></select></div>'+
  '<div><label>Schwierigkeit</label><select id="nt_diff">'+mgrMeta.difficulties.map(d=>'<option'+(d==='normal'?' selected':'')+'>'+d+'</option>').join('')+'</select></div>'+
  '</div>'+
  '<div style="margin-top:12px"><label>Teamfarbe</label><div id="nt_colors" style="display:flex;gap:9px;flex-wrap:wrap">'+
   mgrMeta.colors.map((c,i)=>'<div class="swatch'+(i===0?' on':'')+'" data-c="'+c+'" style="background:'+c+'" onclick="pickColor(this)"></div>').join('')+'</div></div>'+
  '<div style="margin-top:14px"><button onclick="newTeam()">Franchise starten</button></div>'+
  '<div class="note">Du startest mit einem Budget, baust dein Team auf und spielst um den Titel.</div></div>';
}
function pickColor(e){ntColor=e.dataset.c;document.querySelectorAll('#nt_colors .swatch').forEach(s=>s.classList.toggle('on',s===e));}
async function newTeam(){
 const qs='team='+encodeURIComponent($('nt_name').value)+'&teams='+$('nt_n').value+'&difficulty='+$('nt_diff').value+'&color='+encodeURIComponent(ntColor||'');
 renderMgr(await api('/api/fr/new?'+qs,'POST'));
}
function pill(t){return '<span class="pill">'+esc(t)+'</span>';}
let mgrTab='dash',lastView=null;
function mgrGo(t){mgrTab=t;renderMgr(lastView);}
function renderMgr(v){
 lastView=v;
 const phaseLabel={regular:'Reguläre Saison',playoffs:(v.playoff?v.playoff.round:'Playoffs'),done:'Saison beendet'}[v.phase];
 let h='<div class="card"><div class="teamhdr">'+
   '<div class="crest" style="background:'+esc(v.color||'#16c784')+'">'+esc(v.abbr||'')+'</div>'+
   '<div><div class="big">'+esc(v.team_name)+'</div><div class="mut">Saison '+v.season+' · '+esc(phaseLabel)+'</div></div>'+
   '<div style="margin-left:auto;text-align:right">'+pill('Bilanz '+v.record.w+'–'+v.record.l)+' '+pill('Budget '+v.budget+' Mio')+' '+pill('Punkte '+v.skillpoints)+'</div></div>'+
   '<div class="grid" style="margin-top:14px">'+kpi('Overall',v.ratings.ovr)+kpi('Offense',v.ratings.off)+kpi('Defense',v.ratings.def)+
   kpi('Woche',v.phase==='regular'?(v.week+1)+' / '+v.n_weeks:'—')+'</div>';
 if(v.champion)h+='<div class="reco champ" style="margin-top:14px"><span><span class="tag">MEISTER</span> <b>'+esc(v.champion)+'</b></span><span class="mut">Saison '+v.season+'</span></div>';
 h+='</div>';
 // Unter-Navigation
 const tabs=[['dash','Dashboard'],['kader','Kader & Training'],['build','Verbesserungen']];
 h+='<div class="subnav">'+tabs.map(t=>'<div class="s'+(mgrTab===t[0]?' on':'')+'" data-t="'+t[0]+'" onclick="mgrGo(this.dataset.t)">'+t[1]+'</div>').join('')+'</div>';
 h+=(mgrTab==='kader'?secKader(v):mgrTab==='build'?secBuild(v):secDash(v));
 $('mgr_out').innerHTML=h;
}
function secDash(v){
 let h='<div class="card"><div class="sec" style="margin-top:0">Spielbetrieb</div>';
 if(v.phase==='regular'&&v.next){h+='<div class="reco"><span><span class="cdot" style="background:'+esc(v.next.color||'#ef5350')+'"></span>'+
   'Nächstes Spiel: <b>'+(v.next.home?'vs':'@')+' '+esc(v.next.name)+'</b> <span class="mut">OVR '+v.next.ovr+' · Off: '+esc(v.next.off_scheme)+' · Def: '+esc(v.next.def_scheme)+'</span></span></div>';}
 if(v.phase==='playoffs'&&v.playoff){h+='<div class="reco"><span><b>'+esc(v.playoff.round)+'</b> — '+
   v.playoff.pairs.map(p=>esc(p[0])+' vs '+esc(p[1])).join(' · ')+'</span></div>';}
 if(v.active_game)h+='<button onclick="resumeGame()">Spiel fortsetzen</button> ';
 else if(v.phase!=='done'){h+='<button onclick="startGame()">Selbst spielen</button> '+
   '<button class="ghost" onclick="simWeek()">Simulieren</button> ';}
 else h+='<button onclick="newSeason()">Neue Saison</button> ';
 if(v.has_last_game)h+='<button class="ghost" onclick="watchLast()">Letztes Spiel ansehen</button> ';
 h+='<button class="ghost" onclick="resetFr()">Zurücksetzen</button>';
 if(v.last_result)h+=renderResult(v.last_result,v.team_name);
 h+='</div>';
 if(v.events&&v.events.length){h+='<div class="card"><div class="sec" style="margin-top:0">Neuigkeiten der Woche</div>'+
   v.events.map(e=>'<div class="reco '+(e.type==='bad'?'loss':(e.type==='ok'?'win':''))+'"><span>'+esc(e.text)+'</span></div>').join('')+'</div>';}
 const offk=Object.keys(v.off_schemes),defk=Object.keys(v.def_schemes);
 h+='<div class="card"><div class="sec" style="margin-top:0">Team-Schema</div><div class="controls">'+
   '<div><label>Offense-Schema</label><select id="sc_off">'+offk.map(k=>'<option'+(k===v.scheme.off?' selected':'')+'>'+esc(k)+'</option>').join('')+'</select></div>'+
   '<div><label>Defense-Schema</label><select id="sc_def">'+defk.map(k=>'<option'+(k===v.scheme.def?' selected':'')+'>'+esc(k)+'</option>').join('')+'</select></div>'+
   '<button onclick="setScheme()">Übernehmen</button></div>'+
   '<div class="note">Off: '+esc((v.off_schemes[v.scheme.off]||[]).join(', '))+'<br>Def: '+esc((v.def_schemes[v.scheme.def]||[]).join(', '))+'</div></div>';
 h+='<div class="card scroll"><div class="sec" style="margin-top:0">Tabelle</div><table class="tbl"><tr>'+
   '<th class="cn">#</th><th class="cn">Team</th><th>S</th><th>N</th><th>Diff</th><th>OVR</th></tr>';
 v.standings.forEach(t=>{h+='<tr'+(t.user?' class="me"':'')+'><td>'+t.rank+'</td><td class="cn"><span class="cdot" style="background:'+esc(t.color||'#16c784')+'"></span>'+esc(t.name)+
   '</td><td>'+t.w+'</td><td>'+t.l+'</td><td>'+(t.diff>=0?'+':'')+t.diff+'</td><td>'+t.ovr+'</td></tr>';});
 return h+'</table></div>';
}
function secKader(v){
 const foc=v.training_focus||'';
 let h='<div class="card"><div class="sec" style="margin-top:0">Trainingszentrum</div>'+
   '<div class="grid">'+kpi('Skillpunkte',v.skillpoints)+kpi('Equipment','St. '+v.equipment.level)+kpi('EXP / Woche','+'+v.equipment.exp_week)+kpi('Kadergröße',v.roster.length)+'</div>'+
   '<div class="controls" style="margin-top:12px"><div><label>Trainings-Fokus (Woche)</label>'+
   '<select id="foc"><option value="">kein Fokus</option>'+v.focus_options.map(o=>'<option value="'+o.key+'"'+(o.key===foc?' selected':'')+'>'+esc(o.label)+'</option>').join('')+'</select></div>'+
   '<button onclick="setFocus()">Fokus setzen</button></div>'+
   '<div class="note">Spieler sammeln jede Woche EXP (Training, Fokus-Gruppe extra, Starter + Siege mehr). Je 100 EXP = 1 Skillpunkt. Klick einen Spieler an, um Punkte zu verteilen.</div></div>';
 [['Offense',['QB','RB','WR','OL']],['Defense',['DL','LB','DB']]].forEach(grp=>{
   h+='<div class="card"><div class="sec" style="margin-top:0">'+grp[0]+'</div>';
   grp[1].forEach(pos=>{const ps=v.roster.filter(p=>p.pos===pos);if(!ps.length)return;
     h+='<div class="mut" style="font-weight:700;letter-spacing:.04em;margin:10px 0 2px">'+pos+'</div>';
     ps.forEach(p=>{const bar=Math.round(p.ovr/Math.max(p.pot,1)*100);
       h+='<div class="prow" data-i="'+p.id+'" onclick="openPlayer(this.dataset.i)">'+
        '<span class="ovrnum">'+p.ovr+'</span>'+
        '<span class="pname">'+esc(p.name)+(p.starter?' <span class="tag" style="background:#2c3a34;color:#cfe">START</span>':'')+(p.inj>0?' <span class="tag" style="background:#3a1d1d;color:#ff8a8a">VERLETZT '+p.inj+'W</span>':'')+
        '<span class="mut" style="display:block;font-size:12px">Alter '+p.age+' · Pot '+p.pot+'<div class="ovrbar"><div class="ovrfill" style="width:'+bar+'%"></div></div></span></span>'+
        (p.pts>0?'<span class="ptbadge">'+p.pts+' P</span>':'<span class="mut" style="font-size:12px">'+p.exp+'/100</span>')+'</div>';});
   });
   h+='</div>';});
 return h;
}
async function setFocus(){const r=await api('/api/fr/focus?group='+encodeURIComponent($('foc').value),'POST');if(r.view)renderMgr(r.view);}
function openPlayer(id){_curPid=id;const p=lastView.roster.find(x=>String(x.id)===String(id));if(!p)return;
 let o=$('playeroverlay');if(!o){o=document.createElement('div');o.className='overlay';o.id='playeroverlay';
   o.addEventListener('click',e=>{if(e.target===o)closePlayer();});document.body.appendChild(o);}
 o.innerHTML='<div class="modal" id="playermodal"></div>';renderPlayer(p);
}
function renderPlayer(p){
 let h='<div class="modalhead"><h3>'+esc(p.name)+' <span class="mut" style="font-weight:600">'+p.pos+' · '+p.ovr+' OVR'+(p.starter?' · Starter':'')+(p.inj>0?' · <span style="color:#ff8a8a">verletzt '+p.inj+'W</span>':'')+'</span></h3>'+
   '<button class="ghost" onclick="closePlayer()">Schließen</button></div>'+
   '<div class="grid" style="grid-template-columns:repeat(4,1fr)">'+kpi('OVR',p.ovr)+kpi('Potenzial',p.pot)+kpi('Alter',p.age)+kpi('Skillpunkte',p.pts)+'</div>';
 h+='<div class="pcols">';
 // Radar
 h+='<div class="radarwrap">'+radarSVG(p.attrs)+'</div>';
 // Attribut-Balken mit +
 h+='<div class="attrs">';
 p.attrs.forEach(a=>{const pc=Math.round(a.val/99*100),cap=Math.round(a.cap/99*100);const full=a.val>=a.cap;
   h+='<div class="arow"><span class="alab">'+esc(a.label)+'</span>'+
     '<span class="abar"><span class="afill" style="width:'+pc+'%"></span><span class="acap" style="left:'+cap+'%"></span></span>'+
     '<span class="aval">'+a.val+'</span>'+
     '<button data-k="'+a.key+'" onclick="allocAttr(this.dataset.k)" '+((p.pts<=0||full)?'disabled':'')+'>+</button></div>';});
 h+='</div></div>';
 h+='<div style="margin-top:12px">'+
   (p.pts>0?'<button onclick="autoAlloc()">Auto-verteilen ('+p.pts+')</button> ':'')+
   '<button class="ghost" onclick="toggleStarter()">'+(p.starter?'Aus Startelf nehmen':'In Startelf setzen')+'</button></div>'+
   '<div class="note">Weiße Linie = Potenzial-Limit des Attributs. Skillpunkte bekommst du über EXP.</div>';
 $('playermodal').innerHTML=h;
}
function radarSVG(attrs){const n=attrs.length,cx=85,cy=85,R=62;let pts='',axes='';
 for(let i=0;i<n;i++){const ang=-Math.PI/2+i*2*Math.PI/n;const rr=R*Math.max(.12,attrs[i].val/99);
   const x=cx+Math.cos(ang)*rr,y=cy+Math.sin(ang)*rr;pts+=x.toFixed(1)+','+y.toFixed(1)+' ';
   const ex=cx+Math.cos(ang)*R,ey=cy+Math.sin(ang)*R;
   axes+='<line x1="'+cx+'" y1="'+cy+'" x2="'+ex.toFixed(1)+'" y2="'+ey.toFixed(1)+'" stroke="#26352e"/>'+
     '<text x="'+(cx+Math.cos(ang)*(R+10)).toFixed(1)+'" y="'+(cy+Math.sin(ang)*(R+10)+3).toFixed(1)+'" font-size="8" fill="#8d9d97" text-anchor="middle">'+esc(attrs[i].key)+'</text>';}
 return '<svg viewBox="0 0 170 170" width="170" height="170">'+
   '<polygon points="'+pts.trim()+'" fill="rgba(22,199,132,.25)" stroke="#16c784" stroke-width="2"/>'+axes+'</svg>';
}
async function allocAttr(k){const p=curPlayer();const r=await api('/api/fr/alloc?pid='+p+'&attr='+k,'POST');if(r.result&&r.result.error)alert(r.result.error);afterPlayer(r);}
async function autoAlloc(){const r=await api('/api/fr/alloc_auto?pid='+curPlayer(),'POST');afterPlayer(r);}
async function toggleStarter(){const r=await api('/api/fr/starter?pid='+curPlayer(),'POST');if(r.result&&r.result.error)alert(r.result.error);afterPlayer(r);}
let _curPid=null;
function curPlayer(){return _curPid;}
function afterPlayer(r){if(r.view){lastView=r.view;renderMgr(r.view);const p=r.view.roster.find(x=>String(x.id)===String(_curPid));if(p)renderPlayer(p);}}
function closePlayer(){const o=$('playeroverlay');if(o)o.remove();_curPid=null;}
function secBuild(v){
 const up=(key,label,sub,level,cost,maxed,plus)=>'<div class="reco"><span><b>'+esc(label)+'</b> '+(sub?'<span class="mut">'+esc(sub)+'</span> ':'')+'— Stufe '+level+'</span>'+
   '<button data-u="'+esc(key)+'" onclick="upg(this.dataset.u)" '+(v.budget<cost||maxed?'disabled':'')+'>'+plus+' ('+cost+' Mio)</button></div>';
 // Trainerstab als Karten mit Stärken/Schwächen + Markt
 let h='<div class="sec">Trainerstab</div>';
 v.coaches.forEach(c=>{const mk=v.coach_market[c.role]||[];
   h+='<div class="card"><div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">'+
     '<div><b>'+esc(c.label)+'</b> · '+esc(c.name)+' <span class="mut">'+c.rating+' OVR</span></div>'+
     '<button data-r="'+c.role+'" onclick="improveCoach(this.dataset.r)" '+(v.budget<c.improve_cost?'disabled':'')+'>Verbessern ('+c.improve_cost+' Mio)</button></div>'+
     '<div class="ctraits">'+c.traits.map(t=>'<div class="ctrait"><span>'+esc(t.label)+'</span><span class="abar"><span class="afill" style="width:'+Math.round(t.val/99*100)+'%"></span></span><span class="aval">'+t.val+'</span></div>').join('')+'</div>';
   if(mk.length){h+='<div class="note" style="margin-top:8px">Verfügbar:</div>';
     mk.forEach(cd=>{h+='<div class="reco"><span>'+esc(cd.name)+' <span class="mut">'+cd.rating+' · '+cd.traits.map(t=>t.label[0]+t.val).join(' ')+'</span></span>'+
       '<button data-r="'+c.role+'" data-i="'+cd.idx+'" onclick="hireCoach(this.dataset.r,this.dataset.i)" '+(v.budget<cd.cost?'disabled':'')+'>Anheuern ('+cd.cost+' Mio)</button></div>';});}
   h+='</div>';});
 h+='<div class="card"><div class="sec" style="margin-top:0">Anlagen</div>'+
   up('stadium','Stadion','Einnahmen +'+v.stadium.income+'/Wo',v.stadium.level,v.stadium.cost,v.stadium.level>=5,'+1')+
   up('equipment','Trainings-Equipment','+'+v.equipment.exp_week+' EXP/Wo',v.equipment.level,v.equipment.cost,v.equipment.level>=5,'+1')+
   '<div class="note">Stadion bringt mehr Wocheneinnahmen, Equipment mehr Spieler-EXP. Trainer-Stärken heben Ratings und EXP der jeweiligen Gruppe.</div></div>';
 return h;
}
async function improveCoach(role){const r=await api('/api/fr/improve_coach?role='+encodeURIComponent(role),'POST');if(r.result&&r.result.error)alert(r.result.error);if(r.view)renderMgr(r.view);}
async function hireCoach(role,idx){const r=await api('/api/fr/hire_coach?role='+encodeURIComponent(role)+'&idx='+idx,'POST');if(r.result&&r.result.error)alert(r.result.error);if(r.view)renderMgr(r.view);}
function renderResult(res,me){
 if(!res||!res.games)return '';
 let h='<div style="margin-top:12px"><div class="sec">Ergebnisse '+(typeof res.week==='number'?'Woche '+res.week:esc(res.week))+'</div>';
 res.games.forEach(g=>{const mine=(g.home===me||g.away===me);const won=g.winner===me;
   const cls=mine?(won?' win':' loss'):'';
   h+='<div class="reco'+cls+'"><span>'+esc(g.away)+' <b>'+g['as']+'</b> &nbsp;@&nbsp; '+esc(g.home)+' <b>'+g.hs+'</b></span>'+
   '<span class="mut">'+(mine?(won?'Sieg':'Niederlage'):esc(g.winner))+'</span></div>';});
 return h+'</div>';
}
async function simWeek(){const r=await api('/api/fr/sim_week','POST');if(r.view)renderMgr(r.view);
 if(r.result&&r.result.user_game)openBroadcast(r.result.user_game);}
async function newSeason(){renderMgr(await api('/api/fr/new_season','POST'));}
async function resetFr(){if(confirm('Franchise wirklich löschen?')){await api('/api/fr/reset','POST');loadMgr();}}
async function watchLast(){const r=await api('/api/fr/last_game');if(r.game)openBroadcast(r.game);}

/* ---------- Spiel-Übertragung (TV) ---------- */
let bcTimer=null,bcGame=null;
const AC=g=>g.acolor||'#ef5350', HC=g=>g.hcolor||'#16c784', AB=g=>g.aabbr||g.away.slice(0,3).toUpperCase(), HB=g=>g.habbr||g.home.slice(0,3).toUpperCase();
function pbadge(desc){let c='pb-pl',t='PLAY';
 if(/TOUCHDOWN/.test(desc)){c='pb-td';t='TD';}else if(/Field Goal gut/.test(desc)){c='pb-fg';t='FG';}
 else if(/First Down/.test(desc)){c='pb-fd';t='1ST';}else if(/Interception|Fumble/.test(desc)){c='pb-to';t='TO';}
 return '<span class="pbadge '+c+'">'+t+'</span>';}
function cmtRow(p){const big=/TOUCHDOWN|Field Goal gut|Interception|Fumble/.test(p.desc);
 const c=document.createElement('div');c.className='cmt'+(big?' big':'');
 c.innerHTML='<span class="q">Q'+p.q+'</span>'+pbadge(p.desc)+'<span class="t">'+esc(p.desc)+'</span>';return c;}
function bcBallLeft(x){return Math.max(1,Math.min(99,x))+'%';}
function statLine(s){const o=[];
 if(s.pass_yds||s.pass_td)o.push(s.pass_yds+' Pass-Yds'+(s.pass_td?', '+s.pass_td+' TD':''));
 if(s.rush_att)o.push(s.rush_att+' Läufe, '+s.rush_yds+' Yds');
 if(s.rec)o.push(s.rec+' Fänge, '+s.rec_yds+' Yds');
 const d=[];if(s.tkl)d.push(s.tkl+' Tkl');if(s.sack)d.push(s.sack+' Sack');if(s.intc)d.push(s.intc+' INT');
 if(d.length)o.push(d.join(', '));return o.join(' · ');}
function boxSection(g){if(!g.box||!g.box.length)return '';
 return '<div class="sec">Statistik · dein Team</div><div style="border:1px solid var(--line);border-radius:9px;overflow:hidden">'+
   g.box.map(s=>'<div class="cmt"><span class="t"><b>'+esc(s.name)+'</b> <span class="mut">'+s.pos+'</span></span><span class="mut" style="text-align:right">'+esc(statLine(s))+'</span></div>').join('')+'</div>';}
function openBroadcast(g){
 closeBroadcast(); bcGame=g;
 let turf='';[10,20,30,40,50,60,70,80,90].forEach(p=>{turf+='<div class="yl" style="left:'+p+'%"></div>';
  const lab=(p===50?'50':(p<50?p:100-p));turf+='<div class="yn" style="left:'+p+'%">'+lab+'</div><div class="yn b" style="left:'+p+'%">'+lab+'</div>';});
 const o=document.createElement('div');o.className='overlay';o.id='overlay';
 o.innerHTML='<div class="modal">'+
  '<div class="modalhead"><h3><span class="livedot"></span> LIVE · Spiel-Übertragung</h3>'+
   '<button class="ghost" onclick="closeBroadcast()">Schließen</button></div>'+
  '<div class="tvscore">'+
   '<div class="tvteam" style="--tc:'+esc(AC(g))+'"><span class="ab">'+esc(AB(g))+'</span><span class="nm">'+esc(g.away)+'</span></div>'+
   '<div class="tvpts" id="bc_as">0</div>'+
   '<div class="tvmid"><div class="qn" id="bc_q">Q1</div><div class="sub">läuft …</div></div>'+
   '<div class="tvpts" id="bc_hs">0</div>'+
   '<div class="tvteam r" style="--tc:'+esc(HC(g))+'"><span class="nm">'+esc(g.home)+'</span><span class="ab">'+esc(HB(g))+'</span></div>'+
  '</div>'+
  '<div class="tvfield"><div class="ez" style="background:'+esc(AC(g))+'">'+esc(AB(g))+'</div>'+
   '<div class="turf" id="bc_turf">'+turf+'<div class="ball" id="bc_ball" style="left:50%"></div></div>'+
   '<div class="ez" style="background:'+esc(HC(g))+'">'+esc(HB(g))+'</div></div>'+
  '<div style="margin-top:10px"><button class="ghost" onclick="skipBroadcast()">Überspringen ▸</button></div>'+
  boxSection(g)+
  '<div class="commentary" id="bc_feed"></div></div>';
 document.body.appendChild(o);
 o.addEventListener('click',e=>{if(e.target===o)closeBroadcast();});
 bcPlay(g);
}
function bcPlay(g){let i=0;const feed=$('bc_feed');
 bcTimer=setInterval(()=>{if(i>=g.plays.length){clearInterval(bcTimer);bcTimer=null;return;}
  const p=g.plays[i++];$('bc_ball').style.left=bcBallLeft(p.x);
  $('bc_hs').textContent=p.hs;$('bc_as').textContent=p['as'];$('bc_q').textContent='Q'+p.q;
  feed.insertBefore(cmtRow(p),feed.firstChild);
 },170);}
function skipBroadcast(){if(bcTimer){clearInterval(bcTimer);bcTimer=null;}const g=bcGame;if(!g)return;
 $('bc_hs').textContent=g.hs;$('bc_as').textContent=g['as'];$('bc_q').textContent='Q4';
 if(g.plays.length)$('bc_ball').style.left=bcBallLeft(g.plays[g.plays.length-1].x);
 const feed=$('bc_feed');feed.innerHTML='';g.plays.slice().reverse().forEach(p=>feed.appendChild(cmtRow(p)));}
function closeBroadcast(){if(bcTimer){clearInterval(bcTimer);bcTimer=null;}bcGame=null;const o=$('overlay');if(o)o.remove();}

/* ---------- Interaktiver Spielmodus (selbst Plays callen) ---------- */
let liveG=null;
async function startGame(){const r=await api('/api/fr/game/start','POST');if(r.error){alert(r.error);return;}openGame(r.game);}
async function resumeGame(){const r=await api('/api/fr/game/start','POST');if(r.error){alert(r.error);return;}openGame(r.game);}
function openGame(g){closeGame();liveG=g;const o=document.createElement('div');o.className='overlay';o.id='gameoverlay';
 o.innerHTML='<div class="modal" id="gamemodal"></div>';document.body.appendChild(o);renderGame(g);}
function gameTurf(g){let t='';[10,20,30,40,50,60,70,80,90].forEach(p=>{t+='<div class="yl" style="left:'+p+'%"></div>';
 const lab=(p===50?'50':(p<50?p:100-p));t+='<div class="yn" style="left:'+p+'%">'+lab+'</div><div class="yn b" style="left:'+p+'%">'+lab+'</div>';});
 return '<div class="turf">'+t+'<div class="ball" style="left:'+Math.max(1,Math.min(99,g.absx))+'%"></div></div>';}
function renderGame(g,play){
 let h='<div class="modalhead"><h3><span class="livedot"></span> Dein Spiel</h3>'+
   '<button class="ghost" onclick="abortGame()">Verlassen</button></div>'+
   '<div class="tvscore">'+
     '<div class="tvteam" style="--tc:'+esc(g.acolor)+'"><span class="ab">'+esc(g.aabbr)+'</span><span class="nm">'+esc(g.away)+'</span></div>'+
     '<div class="tvpts">'+g['as']+'</div>'+
     '<div class="tvmid"><div class="qn">Q'+g.q+'</div><div class="sub">Drive '+g.drive+'/'+g.max_drives+'</div></div>'+
     '<div class="tvpts">'+g.hs+'</div>'+
     '<div class="tvteam r" style="--tc:'+esc(g.hcolor)+'"><span class="nm">'+esc(g.home)+'</span><span class="ab">'+esc(g.habbr)+'</span></div>'+
   '</div>'+
   '<div class="tvfield"><div class="ez" style="background:'+esc(g.acolor)+'">'+esc(g.aabbr)+'</div>'+
     gameTurf(g)+'<div class="ez" style="background:'+esc(g.hcolor)+'">'+esc(g.habbr)+'</div></div>'+
   '<div class="dd"><span>'+g.down+'. &amp; '+g.dist+'</span><span class="mut">noch '+g.ytz+' Yd bis TD · Ball: '+esc(g.possession)+'</span></div>';
 if(play)h+='<div class="reco'+(play.scored?' win':'')+'"><span>'+esc(play.desc)+'</span><span class="mut">'+(play.yards>=0?'+':'')+play.yards+' Yd</span></div>';
 if(g.over){h+='<div class="posbanner off">Spiel vorbei — Endstand '+esc(g.away)+' '+g['as']+' : '+g.hs+' '+esc(g.home)+'</div>'+
   '<button onclick="finishGame()">Ergebnis werten &amp; Woche abschließen</button>';}
 else{h+='<div class="posbanner '+(g.user_offense?'off':'def')+'">'+(g.user_offense?'Du am Ball — wähle dein Konzept:':'Verteidigung — wähle deine Coverage:')+'</div>'+
   '<div class="optgrid">'+g.options.map(o=>'<button class="optbtn" data-k="'+esc(o.key)+'" onclick="gamePlay(this.dataset.k)">'+esc(o.label)+'<span class="ty">'+esc(o.type)+'</span></button>').join('')+'</div>';}
 h+='<div class="commentary" style="margin-top:10px">'+g.log.map(p=>'<div class="cmt"><span class="q">Q'+p.q+'</span>'+pbadge(p.desc)+'<span class="t">'+esc(p.desc)+'</span></div>').join('')+'</div>';
 $('gamemodal').innerHTML=h;
}
async function gamePlay(choice){const r=await api('/api/fr/game/play?choice='+encodeURIComponent(choice),'POST');if(r.error){alert(r.error);return;}liveG=r.game;renderGame(r.game,r.play);}
async function finishGame(){const r=await api('/api/fr/game/finish','POST');if(r.error){alert(r.error);return;}closeGame();if(r.view)renderMgr(r.view);}
async function abortGame(){if(confirm('Spiel verlassen? Der Fortschritt geht verloren.')){await api('/api/fr/game/abort','POST');closeGame();loadMgr();}}
function closeGame(){const o=$('gameoverlay');if(o)o.remove();liveG=null;}
async function upg(u){const r=await api('/api/fr/upgrade?unit='+u,'POST');if(r.result&&r.result.error)alert(r.result.error);if(r.view)renderMgr(r.view);}
async function setScheme(){const r=await api('/api/fr/scheme?off='+encodeURIComponent($('sc_off').value)+'&deff='+encodeURIComponent($('sc_def').value),'POST');if(r.view)renderMgr(r.view);}
init();
</script></body></html>"""

_REPORT_PAGE = """<!doctype html><html lang="de"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Gridiron — Druck-Report</title><style>
 body{font:13px/1.5 Georgia,'Times New Roman',serif;color:#111;margin:0;background:#fff}
 .p{max-width:760px;margin:0 auto;padding:28px}
 h1{font-size:22px;margin:0 0 2px} .sub{color:#555;margin-bottom:14px}
 h2{font-size:14px;text-transform:uppercase;letter-spacing:.05em;border-bottom:2px solid #111;padding-bottom:3px;margin:18px 0 8px}
 table{width:100%;border-collapse:collapse} th,td{text-align:left;padding:5px 7px;border-bottom:1px solid #ccc}
 th{font-size:11px;text-transform:uppercase;color:#444}
 .tell{margin:4px 0} .controls{margin-bottom:14px}
 select{padding:7px;font-size:14px} button{padding:7px 12px;cursor:pointer}
 @media print{.controls{display:none} .p{padding:0}}
</style></head><body><div class="p">
 <div class="controls">
  Team <select id="team"></select> Saison <select id="season"></select>
  <button onclick="go()">Laden</button> <button onclick="window.print()">Drucken / PDF</button>
 </div>
 <div id="out"></div>
</div>
<script>
const $=id=>document.getElementById(id);const pct=x=>Math.round(x*100)+'%';
function esc(s){const d=document.createElement('div');d.textContent=(s==null?'':s);return d.innerHTML;}
async function init(){const d=await (await fetch('/api/teams')).json();
 $('team').innerHTML=d.teams.map(t=>'<option>'+esc(t)+'</option>').join('');
 $('season').innerHTML='<option value="">alle</option>'+d.seasons.map(s=>'<option>'+s+'</option>').join('');
 const u=new URLSearchParams(location.search); if(u.get('team'))$('team').value=u.get('team');
 if(u.get('season'))$('season').value=u.get('season'); go();}
async function go(){const team=$('team').value,season=$('season').value;
 const r=await (await fetch('/api/scout?team='+encodeURIComponent(team)+'&season='+encodeURIComponent(season))).json();
 if(!r.n_plays){$('out').innerHTML='<p>Keine Daten.</p>';return;}
 let h='<h1>Scouting-Report: '+esc(team)+'</h1><div class="sub">Saison '+esc(r.season)+
  ' · '+r.n_plays+' Plays · Pass '+pct(r.pass_rate)+' / Run '+pct(1-r.pass_rate)+
  ' (Liga Pass '+pct(r.league_pass_rate)+') · EPA/Play '+(r.epa>=0?'+':'')+r.epa.toFixed(2)+
  ' · Play-Action '+pct(r.play_action_rate)+'</div>';
 if(r.tells.length){h+='<h2>Vorhersehbar (Tells)</h2>';r.tells.forEach(t=>{
  const lab=t.pass_rate>=0.5?pct(t.pass_rate)+' Pass':pct(1-t.pass_rate)+' Run';
  h+='<div class="tell">• '+t.down+'. &amp; '+esc(t.dist)+', '+esc(t.zone)+' → <b>'+lab+'</b> (n='+t.n+')</div>';});}
 h+='<h2>Nach Down &amp; Distanz</h2><table><tr><th>Situation</th><th>Pass</th><th>Liga</th><th>Δ</th><th>EPA</th><th>n</th></tr>';
 r.by_down_dist.forEach(x=>h+='<tr><td>'+x.down+'. &amp; '+esc(x.dist)+'</td><td>'+pct(x.pass_rate)+'</td><td>'+pct(x.league_pass_rate)+
  '</td><td>'+(x.delta>=0?'+':'')+Math.round(x.delta*100)+'pp</td><td>'+(x.epa>=0?'+':'')+x.epa.toFixed(2)+'</td><td>'+x.n+'</td></tr>');
 h+='</table>';
 if(r.by_zone.length){h+='<h2>Nach Feldzone</h2><table><tr><th>Zone</th><th>Pass</th><th>EPA</th><th>n</th></tr>';
  r.by_zone.forEach(z=>h+='<tr><td>'+esc(z.zone)+'</td><td>'+pct(z.pass_rate)+'</td><td>'+(z.epa>=0?'+':'')+z.epa.toFixed(2)+'</td><td>'+z.n+'</td></tr>');h+='</table>';}
 if(r.run_gaps.length||r.pass_locations.length){h+='<h2>Richtungen</h2>';
  if(r.run_gaps.length)h+='<div>Lauf: '+r.run_gaps.map(g=>esc(g.gap)+' '+g.n).join(' · ')+'</div>';
  if(r.pass_locations.length)h+='<div>Pass: '+r.pass_locations.map(p=>esc(p.loc)+' '+p.n).join(' · ')+'</div>';}
 $('out').innerHTML=h;document.title='Gridiron Report '+team;}
init();
</script></body></html>"""


def create_app(cfg: Config | None = None) -> FastAPI:
    cfg = cfg or load_config()
    app = FastAPI(title="Gridiron", version="0.1")
    _state: dict = {"predictor": None}

    @app.middleware("http")
    async def _headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        return resp

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def home():
        return _PAGE

    @app.get("/report", response_class=HTMLResponse)
    def report():
        return _REPORT_PAGE

    @app.get("/api/teams")
    def teams():
        with GridironStore(cfg) as store:
            return {"teams": store.teams(), "seasons": store.seasons()}

    @app.get("/api/scout")
    def api_scout(team: str, season: str = ""):
        s = int(season) if season.strip().isdigit() else None
        return asdict(scout(cfg, team.upper(), season=s))

    @app.get("/api/predict")
    def api_predict(team: str, down: int = 1, ydstogo: int = 10, yardline: int = 50,
                    qtr: int = 1, score_diff: int = 0, shotgun: int = 0,
                    gsr: int = 1800):
        from gridiron.model import Predictor
        if _state["predictor"] is None:
            try:
                _state["predictor"] = Predictor(cfg)
            except FileNotFoundError:
                return JSONResponse({"error": "Kein Modell – bitte erst 'train' ausführen."},
                                    status_code=503)
        sit = {"team": team.upper(), "down": down, "ydstogo": ydstogo,
               "yardline_100": yardline, "score_differential": score_diff,
               "qtr": qtr, "game_seconds_remaining": gsr, "shotgun": bool(shotgun),
               "no_huddle": False}
        return _state["predictor"].assess(sit)

    # ---- Play-Simulator ------------------------------------------------- #
    def _sit(down, ydstogo, yardline, personnel, box):
        return {"down": down, "ydstogo": ydstogo, "yardline_100": yardline,
                "personnel": personnel, "box": box or None}

    @app.get("/api/sim/meta")
    def sim_meta():
        from gridiron import simulator as S
        return {"concepts": S.list_concepts(), "coverages": S.list_coverages()}

    @app.get("/api/sim/run")
    def sim_run(concept: str, coverage: str, down: int = 1, ydstogo: int = 10,
                yardline: int = 60, personnel: str = "11", box: int = 0):
        from gridiron.simulator import simulate
        try:
            r = simulate(cfg, concept, coverage, _sit(down, ydstogo, yardline, personnel, box))
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return asdict(r)

    @app.get("/api/sim/best")
    def sim_best(coverage: str, down: int = 1, ydstogo: int = 10, yardline: int = 60,
                 personnel: str = "11", box: int = 0):
        from gridiron.simulator import best_concepts
        return {"items": [asdict(r) for r in
                          best_concepts(cfg, coverage, _sit(down, ydstogo, yardline, personnel, box))]}

    @app.get("/api/sim/stop")
    def sim_stop(concept: str, down: int = 1, ydstogo: int = 10, yardline: int = 60,
                 personnel: str = "11", box: int = 0):
        from gridiron.simulator import stopping_coverages
        try:
            items = stopping_coverages(cfg, concept, _sit(down, ydstogo, yardline, personnel, box))
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return {"items": [asdict(r) for r in items]}

    @app.get("/api/sim/matrix")
    def sim_matrix(down: int = 1, ydstogo: int = 10, yardline: int = 60,
                   personnel: str = "11", box: int = 0):
        from gridiron.simulator import matrix
        return matrix(cfg, _sit(down, ydstogo, yardline, personnel, box))

    @app.get("/api/sim/diagram")
    def sim_diagram(concept: str, coverage: str):
        from gridiron.playviz import diagram
        try:
            return diagram(concept, coverage)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    # ---- Franchise / Team-Manager -------------------------------------- #
    def _fr_load_or_404():
        from gridiron import franchise as F
        st = F.load(cfg)
        if st is None:
            return None, JSONResponse({"error": "Keine Franchise — bitte neu starten."}, status_code=404)
        return st, None

    @app.get("/api/fr/state")
    def fr_state():
        from gridiron import franchise as F
        st = F.load(cfg)
        return {"exists": st is not None, "view": (F.view(st) if st else None)}

    @app.get("/api/fr/meta")
    def fr_meta():
        from gridiron import franchise as F
        from gridiron.simulator import list_concepts, list_coverages
        return {"concepts": list_concepts(), "coverages": list_coverages(),
                "difficulties": ["leicht", "normal", "schwer"], "colors": F.USER_COLORS}

    @app.post("/api/fr/new")
    def fr_new(team: str, teams: int = 8, difficulty: str = "normal", color: str = ""):
        from gridiron import franchise as F
        st = F.new_franchise(cfg, team, n_teams=teams, difficulty=difficulty, color=color or None)
        return F.view(st)

    @app.post("/api/fr/sim_week")
    def fr_sim_week():
        from gridiron import franchise as F
        st, err = _fr_load_or_404()
        if err:
            return err
        res = F.sim_week(cfg, st)
        return {"result": res, "view": F.view(st)}

    @app.post("/api/fr/new_season")
    def fr_new_season():
        from gridiron import franchise as F
        st, err = _fr_load_or_404()
        if err:
            return err
        return F.view(F.new_season(cfg, st))

    @app.post("/api/fr/upgrade")
    def fr_upgrade(unit: str):
        from gridiron import franchise as F
        st, err = _fr_load_or_404()
        if err:
            return err
        res = F.upgrade_unit(cfg, st, unit)
        return {"result": res, "view": F.view(st)}

    @app.post("/api/fr/alloc")
    def fr_alloc(pid: int, attr: str):
        from gridiron import franchise as F
        st, err = _fr_load_or_404()
        if err:
            return err
        return {"result": F.alloc(cfg, st, pid, attr), "view": F.view(st)}

    @app.post("/api/fr/alloc_auto")
    def fr_alloc_auto(pid: int):
        from gridiron import franchise as F
        st, err = _fr_load_or_404()
        if err:
            return err
        return {"result": F.alloc_auto(cfg, st, pid), "view": F.view(st)}

    @app.post("/api/fr/starter")
    def fr_starter(pid: int):
        from gridiron import franchise as F
        st, err = _fr_load_or_404()
        if err:
            return err
        return {"result": F.depth_toggle(cfg, st, pid), "view": F.view(st)}

    @app.post("/api/fr/focus")
    def fr_focus(group: str = ""):
        from gridiron import franchise as F
        st, err = _fr_load_or_404()
        if err:
            return err
        return {"result": F.set_focus(cfg, st, group or None), "view": F.view(st)}

    @app.post("/api/fr/hire_coach")
    def fr_hire_coach(role: str, idx: int):
        from gridiron import franchise as F
        st, err = _fr_load_or_404()
        if err:
            return err
        return {"result": F.hire_coach(cfg, st, role, idx), "view": F.view(st)}

    @app.post("/api/fr/improve_coach")
    def fr_improve_coach(role: str):
        from gridiron import franchise as F
        st, err = _fr_load_or_404()
        if err:
            return err
        return {"result": F.improve_coach(cfg, st, role), "view": F.view(st)}

    @app.post("/api/fr/scheme")
    def fr_scheme(off: str = "", deff: str = ""):
        from gridiron import franchise as F
        st, err = _fr_load_or_404()
        if err:
            return err
        res = F.set_scheme(cfg, st, off or None, deff or None)
        return {"result": res, "view": F.view(st)}

    @app.get("/api/fr/last_game")
    def fr_last_game():
        from gridiron import franchise as F
        st = F.load(cfg)
        return {"game": (st.get("last_user_game") if st else None)}

    @app.post("/api/fr/game/start")
    def fr_game_start():
        from gridiron import franchise as F
        st, err = _fr_load_or_404()
        if err:
            return err
        return F.start_game(cfg, st)

    @app.post("/api/fr/game/play")
    def fr_game_play(choice: str):
        from gridiron import franchise as F
        st, err = _fr_load_or_404()
        if err:
            return err
        return F.game_play(cfg, st, choice)

    @app.post("/api/fr/game/finish")
    def fr_game_finish():
        from gridiron import franchise as F
        st, err = _fr_load_or_404()
        if err:
            return err
        return F.finish_game(cfg, st)

    @app.post("/api/fr/game/abort")
    def fr_game_abort():
        from gridiron import franchise as F
        st, err = _fr_load_or_404()
        if err:
            return err
        return F.abort_game(cfg, st)

    @app.post("/api/fr/reset")
    def fr_reset():
        from gridiron import franchise as F
        F.delete(cfg)
        return {"ok": True}

    return app
