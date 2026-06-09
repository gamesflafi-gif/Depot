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
 .fieldwrap{margin:12px 0 8px;border-radius:10px;overflow:hidden;border:1px solid var(--line)}
 #field{display:block;width:100%;height:auto;background:#0c2a18}
 .fieldlegend{display:flex;gap:16px;flex-wrap:wrap;color:var(--mut);font-size:12px;align-items:center}
 .fieldlegend i.dot{display:inline-block;width:11px;height:11px;border-radius:50%;margin-right:5px;vertical-align:-1px}
 .dot.off{background:#16c784} .dot.tgt{background:#ffd34d} .dot.def{background:#ef5350} .dot.saf{background:#e09b3d}
 /* Broadcast (Manager) */
 .bcast{background:linear-gradient(180deg,#0c2a18,#0a2114);border:1px solid var(--line);border-radius:12px;padding:14px;margin:12px 0}
 .scoreboard{display:flex;align-items:center;justify-content:space-between;background:#0a0f0d;border:1px solid var(--line);
   border-radius:10px;padding:10px 16px;font-variant-numeric:tabular-nums}
 .sb-team{font-weight:700;font-size:15px} .sb-score{font-size:30px;font-weight:800;letter-spacing:.02em}
 .sb-mid{text-align:center;color:var(--mut);font-size:12px}
 .fieldbar{position:relative;height:30px;margin:14px 2px;border-radius:6px;
   background:repeating-linear-gradient(90deg,#11432a 0 9.7px,#0e3b25 9.7px 10px)}
 .endz{position:absolute;top:0;bottom:0;width:10%;background:#0a2d1c;display:flex;align-items:center;justify-content:center;
   font-size:9px;color:#3f7a5c;font-weight:700}
 .endz.l{left:0;border-right:1px solid #1c5a3a} .endz.r{right:0;border-left:1px solid #1c5a3a}
 .ball{position:absolute;top:50%;width:14px;height:14px;margin:-7px 0 0 -7px;border-radius:50%;
   background:#ffd34d;box-shadow:0 0 8px rgba(255,211,77,.6);transition:left .6s ease}
 .firstline{position:absolute;top:-3px;bottom:-3px;width:2px;background:#ffd34d;opacity:.55}
 .commentary{max-height:230px;overflow-y:auto;margin-top:10px}
 .cmt{padding:7px 11px;border-bottom:1px solid var(--line);font-size:13.5px;display:flex;gap:9px}
 .cmt .q{color:var(--mut);min-width:54px;font-variant-numeric:tabular-nums} .cmt.score{background:var(--accsoft)}
 .cmt.score .t{color:#4be3a0;font-weight:600}
 .overlay{position:fixed;inset:0;background:rgba(0,0,0,.66);display:flex;align-items:center;justify-content:center;z-index:50;padding:16px}
 .modal{background:var(--panel);border:1px solid var(--line);border-radius:14px;max-width:640px;width:100%;max-height:92vh;overflow:auto;padding:18px 20px}
 .modal h3{margin:0 0 4px;font-size:17px} .modalhead{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}
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
 <div class="lead">Wähle ein Team — Tendenzen, „Tells" und Live-Pass/Lauf-Vorhersage.</div>
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
 <div class="lead">Spiel ein <b>Konzept</b> gegen eine <b>Coverage</b> durch — tausende Simulationen liefern die Ertragsverteilung.</div>
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
 <div class="lead">Erwartetes <b>EPA</b> für jedes Konzept × jede Coverage. Grün = Vorteil Offense, Rot = Vorteil Defense.</div>
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
 <div class="lead">Baue dein Team, spiele die Liga-Saison und gewinne den Titel. Verbessere mit deinem Budget die Einheiten und wähle dein Playbook.</div>
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
   kpi('Ø EPA',sgn(r.expected_epa))+kpi('Matchup-Faktor','×'+r.matchup_factor.toFixed(2))+
   '</div><div class="sec">Ertragsverteilung (Yards)</div>';
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
 const svg=$('field'); svg.innerHTML='';
 const ytg=parseInt($('sim_y').value)||10;
 // Rasen + Yard-Linien
 for(let fy=-5;fy<=25;fy+=5){const y=mapY(fy);
  svg.appendChild(el('line',{x1:0,y1:y,x2:533,y2:y,stroke:'#1c5a3a','stroke-width':fy===0?0:1,opacity:.5}));
  // Hash-Marks
  [23.58,29.72].forEach(hx=>svg.appendChild(el('line',{x1:mapX(hx)-3,y1:y,x2:mapX(hx)+3,y2:y,stroke:'#2e7d52','stroke-width':1})));
 }
 svg.appendChild(el('line',{x1:0,y1:mapY(0),x2:533,y2:mapY(0),stroke:'#5fa8ff','stroke-width':2,opacity:.85}));
 if(ytg<=25)svg.appendChild(el('line',{x1:0,y1:mapY(ytg),x2:533,y2:mapY(ytg),stroke:'#ffd34d','stroke-width':2,opacity:.7,'stroke-dasharray':'6 5'}));
 // Routen (blass)
 d.offense.forEach(o=>{if(o.route&&o.route.length>1){let p='M';o.route.forEach((pt,i)=>{p+=(i?' L':' ')+mapX(pt[0]).toFixed(1)+' '+mapY(pt[1]).toFixed(1);});
  svg.appendChild(el('path',{d:p,fill:'none',stroke:o.target?'#ffd34d':(o.carry?'#ffd34d':'#16c784'),'stroke-width':o.target||o.carry?2:1.3,opacity:.35,'stroke-dasharray':'4 4'}));}});
 // Spieler (Defense zuerst, dann Offense oben)
 d.defense.forEach((p,i)=>addPlayer(svg,p,p.deep?'#e09b3d':'#ef5350','d_'+i));
 d.offense.forEach((o,i)=>addPlayer(svg,o,o.target?'#ffd34d':(o.pos==='OL'?'#0f9e68':'#16c784'),'o'+i,o));
 // Ball
 const qb=d.offense.find(o=>o.pos==='QB');
 svg.appendChild(el('circle',{id:'pball',cx:mapX(qb.x),cy:mapY(qb.y),r:3.5,fill:'#fff',opacity:0}));
}
function addPlayer(svg,p,color,id,o){
 const g=el('g',{}); g.setAttribute('data-id',id);
 const c=el('circle',{cx:mapX(p.x),cy:mapY(p.y),r:7,fill:color,stroke:'#06140d','stroke-width':1.4});
 c.setAttribute('data-px',p.x); c.setAttribute('data-py',p.y); c.id='pl_'+id;
 g.appendChild(c);
 const lbl=(o?(o.pos==='OL'?'':o.pos):p.pos); if(lbl){const t=el('text',{x:mapX(p.x),y:mapY(p.y)+3,'text-anchor':'middle','font-size':7.5,fill:'#03130c','font-weight':700});t.textContent=lbl;t.id='tx_'+id;g.appendChild(t);}
 svg.appendChild(g);
}
function moveP(id,x,y){const c=$('pl_'+id);if(!c)return;c.setAttribute('cx',mapX(x));c.setAttribute('cy',mapY(y));const t=$('tx_'+id);if(t){t.setAttribute('x',mapX(x));t.setAttribute('y',mapY(y)+3);}}
function playAnim(){
 if(!lastDiag)return; cancelAnimationFrame(animReq);
 const d=lastDiag,T=2100,t0=performance.now();
 const qb=d.offense.find(o=>o.pos==='QB');
 const tgt=d.ball_target, isPass=d.kind==='pass', throwAt=.5;
 const ball=$('pball');
 function frame(now){const t=Math.min(1,(now-t0)/T);
  d.offense.forEach((o,i)=>{if(o.route&&o.route.length>1){const pp=posAlong(o.route,t);moveP('o'+i,pp[0],pp[1]);}});
  d.defense.forEach((p,i)=>{if(p.drop){moveP('d_'+i,p.x+(p.drop[0]-p.x)*t,p.y+(p.drop[1]-p.y)*t);}});
  if(isPass&&ball){if(t>=throwAt){const tt=(t-throwAt)/(1-throwAt);ball.setAttribute('opacity',1);
    ball.setAttribute('cx',mapX(qb.x+(tgt[0]-qb.x)*tt));ball.setAttribute('cy',mapY(qb.y+(tgt[1]-qb.y)*tt-Math.sin(tt*Math.PI)*1.2));}}
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
function renderNewTeam(){
 $('mgr_out').innerHTML='<div class="card"><div class="sec" style="margin-top:0">Neue Franchise gründen</div>'+
  '<div class="controls"><div><label>Teamname</label><input id="nt_name" value="Mein Team" style="width:200px"></div>'+
  '<div><label>Liga-Größe</label><select id="nt_n"><option>6</option><option selected>8</option><option>10</option><option>12</option></select></div>'+
  '<div><label>Schwierigkeit</label><select id="nt_diff">'+mgrMeta.difficulties.map(d=>'<option'+(d==='normal'?' selected':'')+'>'+d+'</option>').join('')+'</select></div>'+
  '<button onclick="newTeam()">Franchise starten</button></div>'+
  '<div class="note">Du startest mit einem Budget, baust dein Team auf und spielst um den Titel.</div></div>';
}
async function newTeam(){
 const qs='team='+encodeURIComponent($('nt_name').value)+'&teams='+$('nt_n').value+'&difficulty='+$('nt_diff').value;
 renderMgr(await api('/api/fr/new?'+qs,'POST'));
}
function pill(t){return '<span class="pill">'+esc(t)+'</span>';}
function renderMgr(v){
 const phaseLabel={regular:'Reguläre Saison',playoffs:(v.playoff?v.playoff.round:'Playoffs'),done:'Saison beendet'}[v.phase];
 let h='<div class="card"><div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:10px;align-items:center">'+
   '<div class="big">'+esc(v.team_name)+' <span class="mut" style="font-size:14px">Saison '+v.season+' · '+esc(phaseLabel)+'</span></div>'+
   '<div>'+pill('Bilanz '+v.record.w+'–'+v.record.l)+' '+pill('Budget '+v.budget+' Mio')+'</div></div>'+
   '<div class="grid" style="margin-top:14px">'+kpi('Overall',v.ratings.ovr)+kpi('Offense',v.ratings.off)+kpi('Defense',v.ratings.def)+
   kpi('Woche',v.phase==='regular'?(v.week+1)+' / '+v.n_weeks:'—')+'</div>';
 if(v.champion)h+='<div class="reco champ" style="margin-top:14px"><span><span class="tag">MEISTER</span> <b>'+esc(v.champion)+'</b></span><span class="mut">Saison '+v.season+'</span></div>';
 h+='</div>';

 // Nächstes Spiel / Aktionen
 h+='<div class="card"><div class="sec" style="margin-top:0">Spielbetrieb</div>';
 if(v.phase==='regular'&&v.next){h+='<div class="reco"><span>Nächstes Spiel: <b>'+(v.next.home?'vs':'@')+' '+esc(v.next.name)+
   '</b> <span class="mut">OVR '+v.next.ovr+' · spielt '+esc(v.next.coverage)+'</span></span></div>';}
 if(v.phase==='playoffs'&&v.playoff){h+='<div class="reco"><span><b>'+esc(v.playoff.round)+'</b> — '+
   v.playoff.pairs.map(p=>esc(p[0])+' vs '+esc(p[1])).join(' · ')+'</span></div>';}
 if(v.phase!=='done')h+='<button onclick="simWeek()">Woche simulieren</button> ';
 else h+='<button onclick="newSeason()">Neue Saison</button> ';
 if(v.has_last_game)h+='<button class="ghost" onclick="watchLast()">Letztes Spiel ansehen</button> ';
 h+='<button class="ghost" onclick="resetFr()">Zurücksetzen</button>';
 if(v.last_result)h+=renderResult(v.last_result,v.team_name);
 h+='</div>';

 // Team-Aufbau
 h+='<div class="grid" style="grid-template-columns:1fr 1fr">';
 h+='<div class="card"><div class="sec" style="margin-top:0">Kader verbessern (Budget: '+v.budget+' Mio)</div>';
 v.units.forEach(u=>{h+='<div class="reco"><span><b>'+esc(u.label)+'</b> <span class="mut">'+u.side+'</span> — Stufe '+u.level+'</span>'+
   '<button data-u="'+esc(u.key)+'" onclick="upg(this.dataset.u)" '+(v.budget<u.cost||u.level>=95?'disabled':'')+'>+2 ('+u.cost+' Mio)</button></div>';});
 h+='</div>';
 // Playbook
 h+='<div class="card"><div class="sec" style="margin-top:0">Playbook</div><div class="controls">'+
   '<div><label>Offense-Konzept</label><select id="pb_c">'+mgrMeta.concepts.map(c=>'<option value="'+esc(c.key)+'"'+(c.key===v.playbook.concept?' selected':'')+'>'+esc(c.label)+'</option>').join('')+'</select></div>'+
   '<div><label>Defense-Coverage</label><select id="pb_cov">'+mgrMeta.coverages.map(c=>'<option value="'+esc(c.key)+'"'+(c.key===v.playbook.coverage?' selected':'')+'>'+esc(c.label)+'</option>').join('')+'</select></div>'+
   '<button onclick="setPb()">Übernehmen</button></div>'+
   '<div class="note">Dein Konzept trifft im Spiel auf die Coverage des Gegners — gute Matchups bringen Punkte.</div></div>';
 h+='</div>';

 // Tabelle
 h+='<div class="card scroll"><div class="sec" style="margin-top:0">Tabelle</div><table class="tbl"><tr>'+
   '<th class="cn">#</th><th class="cn">Team</th><th>S</th><th>N</th><th>Diff</th><th>OVR</th></tr>';
 v.standings.forEach(t=>{h+='<tr'+(t.user?' class="me"':'')+'><td>'+t.rank+'</td><td class="cn">'+esc(t.name)+
   '</td><td>'+t.w+'</td><td>'+t.l+'</td><td>'+(t.diff>=0?'+':'')+t.diff+'</td><td>'+t.ovr+'</td></tr>';});
 h+='</table></div>';
 $('mgr_out').innerHTML=h;
}
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

/* ---------- Spiel-Übertragung ---------- */
let bcTimer=null,bcGame=null;
function openBroadcast(g){
 closeBroadcast(); bcGame=g;
 const o=document.createElement('div');o.className='overlay';o.id='overlay';
 o.innerHTML='<div class="modal"><div class="modalhead"><h3>Spiel-Übertragung</h3>'+
  '<button class="ghost" onclick="closeBroadcast()">Schließen</button></div>'+
  '<div class="bcast"><div class="scoreboard">'+
   '<div><div class="sb-team">'+esc(g.away)+'</div><div class="sb-score" id="bc_as">0</div></div>'+
   '<div class="sb-mid"><div id="bc_q">Q1</div><div>Endstand '+g['as']+'–'+g.hs+'</div></div>'+
   '<div style="text-align:right"><div class="sb-team">'+esc(g.home)+'</div><div class="sb-score" id="bc_hs">0</div></div>'+
  '</div>'+
  '<div class="fieldbar"><div class="endz l">'+esc(g.away.slice(0,3).toUpperCase())+'</div>'+
   '<div class="endz r">'+esc(g.home.slice(0,3).toUpperCase())+'</div>'+
   '<div class="ball" id="bc_ball" style="left:50%"></div></div>'+
  '</div>'+
  '<div><button id="bc_skip" class="ghost" onclick="skipBroadcast()">Überspringen</button></div>'+
  '<div class="commentary" id="bc_feed"></div></div>';
 document.body.appendChild(o);
 o.addEventListener('click',e=>{if(e.target===o)closeBroadcast();});
 bcPlay(g);
}
function bcBallLeft(x){return (10+x*0.8)+'%';}
function bcPlay(g){
 let i=0; const feed=$('bc_feed');
 bcTimer=setInterval(()=>{
  if(i>=g.plays.length){clearInterval(bcTimer);bcTimer=null;return;}
  const p=g.plays[i++];
  $('bc_ball').style.left=bcBallLeft(p.x);
  $('bc_hs').textContent=p.hs; $('bc_as').textContent=p.as; $('bc_q').textContent='Q'+p.q;
  const c=document.createElement('div');c.className='cmt'+(p.score?' score':'');
  c.innerHTML='<span class="q">Q'+p.q+'</span><span class="t">'+esc(p.desc)+'</span>';
  feed.insertBefore(c,feed.firstChild);
 },180);
}
function skipBroadcast(){if(bcTimer){clearInterval(bcTimer);bcTimer=null;}const g=bcGame;if(!g)return;
 $('bc_hs').textContent=g.hs;$('bc_as').textContent=g['as'];$('bc_ball').style.left=bcBallLeft(g.plays.length?g.plays[g.plays.length-1].x:50);
 const feed=$('bc_feed');feed.innerHTML='';g.plays.slice().reverse().forEach(p=>{const c=document.createElement('div');
  c.className='cmt'+(p.score?' score':'');c.innerHTML='<span class="q">Q'+p.q+'</span><span class="t">'+esc(p.desc)+'</span>';feed.appendChild(c);});}
function closeBroadcast(){if(bcTimer){clearInterval(bcTimer);bcTimer=null;}bcGame=null;const o=$('overlay');if(o)o.remove();}
async function upg(u){const r=await api('/api/fr/upgrade?unit='+u,'POST');if(r.result&&r.result.error)alert(r.result.error);if(r.view)renderMgr(r.view);}
async function setPb(){const r=await api('/api/fr/playbook?concept='+encodeURIComponent($('pb_c').value)+'&coverage='+encodeURIComponent($('pb_cov').value),'POST');if(r.view)renderMgr(r.view);}
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
                "difficulties": ["leicht", "normal", "schwer"]}

    @app.post("/api/fr/new")
    def fr_new(team: str, teams: int = 8, difficulty: str = "normal"):
        from gridiron import franchise as F
        st = F.new_franchise(cfg, team, n_teams=teams, difficulty=difficulty)
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

    @app.post("/api/fr/playbook")
    def fr_playbook(concept: str = "", coverage: str = ""):
        from gridiron import franchise as F
        st, err = _fr_load_or_404()
        if err:
            return err
        res = F.set_playbook(cfg, st, concept or None, coverage or None)
        return {"result": res, "view": F.view(st)}

    @app.get("/api/fr/last_game")
    def fr_last_game():
        from gridiron import franchise as F
        st = F.load(cfg)
        return {"game": (st.get("last_user_game") if st else None)}

    @app.post("/api/fr/reset")
    def fr_reset():
        from gridiron import franchise as F
        F.delete(cfg)
        return {"ok": True}

    return app
