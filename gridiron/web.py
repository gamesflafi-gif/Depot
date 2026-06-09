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
 :root{--bg:#080c0b;--panel:#161f1c;--panel2:#212c28;--tile:#27332e;--fg:#eaf0ed;--mut:#94a49e;
   --line:#33403a;--acc:#16c784;--accsoft:#0f2a20;--warn:#e9b949;--bad:#ef5350}
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
 button.ghost{background:var(--tile);color:var(--fg);border:1px solid #46544e;box-shadow:0 1px 2px rgba(0,0,0,.3)}
 button.ghost:hover{color:var(--acc);border-color:var(--acc);filter:none}
 .card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin:14px 0;
   box-shadow:0 1px 2px rgba(0,0,0,.25)}
 .big{font-size:25px;font-weight:800;letter-spacing:-.01em}
 .row{display:flex;gap:24px;flex-wrap:wrap}
 .kgrid{display:grid;gap:9px;grid-template-columns:repeat(auto-fit,minmax(100px,1fr))}
 .kpi{background:var(--tile);border:1px solid var(--line);border-radius:11px;padding:8px 11px;
   display:flex;flex-direction:column;justify-content:center;min-height:56px;min-width:0}
 .kpi .l{font-size:9.5px;color:var(--mut);text-transform:uppercase;letter-spacing:.04em;font-weight:700;line-height:1.18}
 .kpi .v{font-size:20px;font-weight:800;font-variant-numeric:tabular-nums;margin-top:3px;line-height:1.04;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 .sec{display:flex;align-items:center;gap:8px;font-size:11.5px;color:var(--fg);text-transform:uppercase;letter-spacing:.08em;margin:20px 0 11px;font-weight:800}
 .sec::before{content:"";width:4px;height:15px;border-radius:2px;background:var(--acc);flex:none}
 /* Positions-Farben & OVR-Tiers (Game-Look) */
 .posb{display:inline-block;min-width:32px;text-align:center;font-weight:800;font-size:11px;padding:3px 6px;border-radius:5px;color:#06140d;letter-spacing:.02em}
 .p-QB{background:#f5a524}.p-RB{background:#16c784}.p-WR{background:#3b96ff;color:#fff}.p-OL{background:#b9923a}
 .p-DL{background:#ef5350;color:#fff}.p-LB{background:#9b6be3;color:#fff}.p-DB{background:#13b7c9;color:#04121f}
 .ovrb{font-weight:800;font-variant-numeric:tabular-nums;border-radius:8px;padding:5px 9px;min-width:38px;text-align:center;display:inline-block;font-size:15px}
 .ovr-elite{background:linear-gradient(135deg,#f3d27a,#caa23f);color:#231a00}.ovr-good{background:#16c784;color:#04140c}
 .ovr-ok{background:#1f6f53;color:#dffaef}.ovr-avg{background:#2a3530;color:#cfe}.ovr-low{background:#3a2a20;color:#eaa877}
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
 @media(max-width:560px){
  .topin{padding:11px 14px} .brand{font-size:16px;gap:10px} .nav a{margin-left:12px;font-size:12.5px}
  .wrap{padding:14px 12px 30px} .big{font-size:21px} .card{padding:14px}
  .controls{gap:10px}
  /* Tabs & Sub-Navigation: einzeilig, horizontal wischbar */
  .tabs{flex-wrap:nowrap;overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none}
  .tabs::-webkit-scrollbar{display:none} .tab{white-space:nowrap;padding:11px 13px}
  .subnav{flex-wrap:nowrap;overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none}
  .subnav::-webkit-scrollbar{display:none} .subnav .s{flex:0 0 auto;white-space:nowrap;font-size:13px;padding:9px 13px}
  /* Team-Banner: Pills/Buttons unter den Namen */
  .teamhdr{flex-wrap:wrap;gap:10px} .teamhdr .crest{width:46px;height:46px;font-size:15px}
  .teamhdr>div:last-child{margin-left:0 !important;text-align:left !important;width:100%}
  .kgrid{grid-template-columns:repeat(2,1fr);gap:8px} .kgrid.k6{grid-template-columns:repeat(3,1fr)}
  .kpi{min-width:0} .kpi .v{font-size:18px}
  .hero h2{font-size:17px} .hero p{font-size:12.5px}
  /* Spielerkarte: Radar über den Attributen, zentriert */
  .pcols{flex-direction:column} .radarwrap{align-self:center}
  .arow .alab{width:80px;font-size:12px}
  /* Overlays kompakter */
  .overlay{padding:10px} .modal{padding:14px;border-radius:12px}
  .tuttip{max-width:none}
  /* breite Tabellen/Heatmap bleiben wischbar */
  .tbl td,.tbl th{padding:7px 7px}
  /* Spiel-/Broadcast-Overlay kompakt halten (kein seitliches Überlaufen) */
  .modal{overflow-x:hidden}
  .tvscore{gap:6px;padding:9px 8px} .tvscore .nm{display:none} .tvpts{font-size:24px;min-width:38px} .tvteam .ab{font-size:12px;padding:5px 8px}
  .tvmid .qn{font-size:14px} .tvfield{height:58px} .tvfield .ez{width:24px;font-size:10px}
  .optgrid{grid-template-columns:1fr 1fr;gap:7px} .optbtn{padding:9px 10px;font-size:12.5px}
  .dd{padding:9px 11px;font-size:13px} .dd .mut{font-size:11px}
 }
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
   display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}
 .reco>span:first-child{min-width:0}
 .reco b{font-weight:700} .reco.win{border-color:#1c5a40} .reco.loss{border-color:#5a2a20}
 /* College-Scouting: Punkte-Badge, Scouting-Pips, kompakte Prospect-Karten */
 .schead{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
 .scoutpts{display:flex;flex-direction:column;align-items:center;background:var(--accsoft);border:1px solid var(--acc);border-radius:10px;padding:5px 14px;min-width:66px;flex:none}
 .scoutpts .v{font-size:23px;font-weight:800;color:var(--acc);line-height:1;font-variant-numeric:tabular-nums}
 .scoutpts .l{font-size:8.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--mut);font-weight:700;margin-top:2px}
 .sdots{display:inline-flex;gap:4px;align-items:center;vertical-align:middle}
 .sdots i{width:8px;height:8px;border-radius:50%;background:transparent;border:1.5px solid var(--mut);box-sizing:border-box}
 .sdots i.on{background:var(--acc);border-color:var(--acc)}
 .prospect{padding:10px 12px} .prospect .nm{font-weight:700;font-size:14px} .prospect .sub{display:block;font-size:11.5px;margin:2px 0 4px}
 .prospect .act{display:flex;flex-direction:column;gap:5px;flex:none}
 .prospect .act button{min-width:108px;padding:7px 10px;font-size:12.5px}
 .reco.mini{padding:8px 12px;font-size:13px;margin:5px 0}
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
 .fig{transform-box:fill-box;transform-origin:center;filter:drop-shadow(0 1px 1.5px rgba(0,0,0,.5))}
 .fig.pop{animation:pop .4s ease}@keyframes pop{0%{transform:scale(1)}45%{transform:scale(1.6)}100%{transform:scale(1)}}
 .fig.down{animation:tackle .5s ease forwards}@keyframes tackle{0%{transform:rotate(0) scale(1)}55%{transform:rotate(38deg) scale(1.05)}100%{transform:rotate(72deg) scale(.82);opacity:.78}}
 .fig.spin{animation:spinmove .45s ease}@keyframes spinmove{0%{transform:rotate(0)}50%{transform:rotate(180deg)}100%{transform:rotate(360deg)}}
 /* Touchdown-Jubel: 10 verschiedene Tänze/Bewegungen */
 .fig.cel{filter:drop-shadow(0 0 4px rgba(255,211,77,.9))}
 .fig.cel1{animation:cel1 .5s ease-in-out infinite}@keyframes cel1{0%,100%{transform:translateY(0)}50%{transform:translateY(-7px)}}
 .fig.cel2{animation:cel2 .7s linear infinite}@keyframes cel2{to{transform:rotate(360deg)}}
 .fig.cel3{animation:cel3 .35s ease-in-out infinite}@keyframes cel3{0%,100%{transform:rotate(-16deg)}50%{transform:rotate(16deg)}}
 .fig.cel4{animation:cel4 .6s ease-in-out infinite}@keyframes cel4{0%,100%{transform:scaleY(1)}50%{transform:scaleY(.7) translateY(3px)}}
 .fig.cel5{animation:cel5 .45s ease-in-out infinite}@keyframes cel5{0%,100%{transform:translateX(-5px) rotate(-8deg)}50%{transform:translateX(5px) rotate(8deg)}}
 .fig.cel6{animation:cel6 .5s ease-in-out infinite}@keyframes cel6{0%,100%{transform:scale(1)}50%{transform:scale(1.35)}}
 .fig.cel7{animation:cel7 .8s ease-in-out infinite}@keyframes cel7{0%{transform:rotate(0) translateY(0)}40%{transform:rotate(-200deg) translateY(-8px)}100%{transform:rotate(-360deg) translateY(0)}}
 .fig.cel8{animation:cel8 .55s ease-in-out infinite}@keyframes cel8{0%,100%{transform:rotate(0) scale(1)}50%{transform:rotate(25deg) scale(1.2)}}
 .fig.cel9{animation:cel9 .4s ease-in-out infinite}@keyframes cel9{0%,100%{transform:translate(-5px,0)}25%{transform:translate(0,-5px)}50%{transform:translate(5px,0)}75%{transform:translate(0,-5px)}}
 .fig.cel10{animation:cel10 .6s ease-in-out infinite}@keyframes cel10{0%,100%{transform:translateY(0) rotate(0)}30%{transform:translateY(-9px) rotate(8deg)}60%{transform:translateY(2px) rotate(-6deg)}}
 .conf{transform-origin:center;animation-name:confall;animation-iteration-count:infinite;animation-timing-function:linear}
 @keyframes confall{0%{transform:translateY(-30px) rotate(0)}100%{transform:translateY(400px) rotate(560deg)}}
 .tdword{animation:tdword .55s ease}@keyframes tdword{0%{transform:scale(.4);opacity:0}60%{transform:scale(1.12)}100%{transform:scale(1);opacity:1}}
 .pulse{animation:pulse 1.1s ease-in-out infinite}@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
 .fieldlegend{display:flex;gap:16px;flex-wrap:wrap;color:var(--mut);font-size:12px;align-items:center}
 .fieldlegend i.dot{display:inline-block;width:11px;height:11px;border-radius:50%;margin-right:5px;vertical-align:-1px}
 .dot.off{background:#16c784} .dot.tgt{background:#ffd34d} .dot.def{background:#ef5350} .dot.saf{background:#e09b3d}
 /* Manager Team-Identität */
 .teamhdr{display:flex;align-items:center;gap:14px}
 .crest{width:52px;height:52px;border-radius:12px;display:flex;align-items:center;justify-content:center;
   font-weight:800;font-size:17px;color:#fff;flex:none;box-shadow:inset 0 -3px 8px rgba(0,0,0,.3);letter-spacing:.02em}
 .cdot{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:7px;vertical-align:-1px}
 .tlogo{display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;border-radius:7px;
   background:var(--lc);color:#fff;font-weight:800;font-size:9.5px;letter-spacing:.02em;flex:none;vertical-align:middle;
   border:1px solid rgba(255,255,255,.14);box-shadow:inset 0 -3px 6px rgba(0,0,0,.34),0 1px 2px rgba(0,0,0,.4);text-shadow:0 1px 1px rgba(0,0,0,.55)}
 .tlogo.lg{width:34px;height:34px;font-size:12px;border-radius:9px}
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
 .tvmid .clk{font-variant-numeric:tabular-nums;font-weight:700;font-size:13px;color:#cdeede}
 .pclock{display:inline-block;font-weight:800;font-variant-numeric:tabular-nums;background:var(--tile);border:1px solid var(--line);border-radius:8px;padding:4px 11px;font-size:13px;margin:2px 0 7px}
 .pclock.urgent{color:#ef5350;border-color:#ef5350;animation:pulse 1s infinite}
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
 body.noscroll{overflow:hidden}
 .overlay{position:fixed;inset:0;background:rgba(0,0,0,.72);backdrop-filter:blur(3px);display:flex;align-items:center;justify-content:center;z-index:50;padding:16px;overscroll-behavior:contain}
 .modal{background:var(--panel);border:1px solid var(--line);border-radius:14px;max-width:660px;width:100%;max-height:92vh;overflow:auto;padding:18px 20px}
 .modal h3{margin:0;font-size:16px;display:flex;align-items:center;gap:8px}
 .livedot{width:8px;height:8px;border-radius:50%;background:var(--bad);animation:pulse 1s infinite}
 .modalhead{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}
 /* Interaktiver Spielmodus */
 .dd{display:flex;justify-content:space-between;align-items:center;background:#0a0f0d;border:1px solid var(--line);border-radius:9px;padding:10px 14px;margin:10px 0;font-weight:700;font-variant-numeric:tabular-nums}
 .posbanner{padding:10px 13px;border-radius:9px;margin:10px 0;font-weight:700;font-size:14px}
 .posbanner.off{background:var(--accsoft);color:#4be3a0}.posbanner.def{background:#2c1c12;color:#eaa877}
 .optgrid{display:grid;gap:8px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));margin:6px 0 4px}
 .optbtn{padding:11px 13px;border:1px solid #46544e;background:var(--tile);color:var(--fg);border-radius:9px;cursor:pointer;text-align:left;font-weight:700;transition:border-color .12s,background .12s;box-shadow:0 1px 2px rgba(0,0,0,.3)}
 .optbtn:hover{border-color:var(--acc);background:#2d3a34} .optbtn .ty{display:block;font-size:11px;color:var(--mut);font-weight:500;margin-top:1px}
 /* Manager Sub-Navigation & Kader */
 .subnav{display:flex;gap:6px;flex-wrap:wrap;margin:14px 0}
 .subnav{display:flex;gap:6px;flex-wrap:wrap;margin:14px 0;background:var(--panel2);border:1px solid #2c3a34;border-radius:12px;padding:6px;box-shadow:0 2px 10px rgba(0,0,0,.3)}
 .subnav .s{flex:1;display:flex;align-items:center;justify-content:center;gap:7px;padding:11px 14px;border-radius:9px;cursor:pointer;font-weight:700;font-size:13.5px;color:var(--mut);white-space:nowrap;transition:background .12s,color .12s}
 .subnav .s svg{width:16px;height:16px;flex:none}
 .subnav .s{position:relative} .subnav .s:hover{color:var(--fg);background:rgba(255,255,255,.05)} .subnav .s.on{background:var(--acc);color:#04140c;box-shadow:0 1px 6px rgba(22,199,132,.4)}
 .navbadge{display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;border-radius:50%;background:var(--warn);color:#1a1400;font-size:11px;font-weight:800;margin-left:3px}
 .stepcard{border-left:3px solid var(--acc)} .stepnum{display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;border-radius:50%;background:var(--acc);color:#04140c;font-size:11px;font-weight:800;margin-right:6px}
 .tbanner{border-radius:14px;padding:18px 20px;margin:0 0 14px;position:relative;overflow:hidden;border:1px solid var(--line);
   background:linear-gradient(120deg,var(--tc) -10%,#0e1513 60%)}
 .tbanner .crest{box-shadow:0 2px 10px rgba(0,0,0,.4)}
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
 .traingrid{display:grid;gap:9px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}
 .traincard{display:flex;flex-direction:column;align-items:flex-start;gap:4px;text-align:left;padding:13px;
   border:1px solid var(--line);border-radius:11px;background:var(--panel2);color:var(--fg);cursor:pointer;font:inherit;transition:border-color .12s,transform .04s}
 .traincard:hover{border-color:var(--acc)} .traincard:active{transform:translateY(1px)}
 .traincard .ti{color:var(--acc)} .traincard b{font-size:14px} .traincard .td{font-size:11.5px;color:var(--mut);font-weight:400}
 #tutspot{position:fixed;inset:0;z-index:60}
 .tuthole{position:fixed;border-radius:10px;box-shadow:0 0 0 9999px rgba(0,0,0,.74);border:2px solid var(--acc);transition:all .22s ease;pointer-events:none}
 .tuttip{position:fixed;left:50%;transform:translateX(-50%);max-width:380px;width:calc(100% - 28px);
   background:var(--panel);border:1px solid var(--acc);border-radius:13px;padding:16px 18px;box-shadow:0 10px 34px rgba(0,0,0,.55)}
 .tuttip h4{margin:3px 0 6px;font-size:16px} .tuttip p{margin:0;color:var(--mut);line-height:1.55;font-size:14px}
 .tutnum{font-size:11px;color:var(--acc);font-weight:800;letter-spacing:.04em}
 .tutbtns{display:flex;justify-content:space-between;align-items:center;margin-top:14px;gap:8px}
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
function lockBody(){document.body.classList.add('noscroll');}
function unlockBodyIfNone(){if(!document.querySelector('.overlay'))document.body.classList.remove('noscroll');}
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
 let h='<div class="card"><div class="kgrid k6">'+
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
function posBadge(p){return '<span class="posb p-'+p+'">'+p+'</span>';}
function teamLogo(abbr,color,cls){return '<span class="tlogo'+(cls?' '+cls:'')+'" style="--lc:'+esc(color||'#16c784')+'">'+esc(((abbr||'?')+'').slice(0,3))+'</span>';}
function ovrTier(o){return o>=88?'elite':o>=80?'good':o>=72?'ok':o>=62?'avg':'low';}
function ovrBadge(o){return '<span class="ovrb ovr-'+ovrTier(o)+'">'+o+'</span>';}
function devBadge(dev,label){if(!dev||dev==='normal')return '';const c=dev==='superstar'?'#ffd34d':'#5fa8ff';
 return '<span style="border:1px solid '+c+';color:'+c+';border-radius:6px;padding:1px 6px;font-size:10px;font-weight:800;letter-spacing:.3px">'+esc(label||dev)+'</span>';}
function scoutDots(sc,mx){let s='<span class="sdots">';for(let i=0;i<mx;i++)s+='<i class="'+(i<sc?'on':'')+'"></i>';return s+'</span>';}
async function runSim(){
 const c=$('sim_c').value,cov=$('sim_cov').value;
 const qs='concept='+encodeURIComponent(c)+'&coverage='+encodeURIComponent(cov)+'&'+simSit('sim_');
 $('sim_out').innerHTML='<div class="card mut">Simuliere …</div>';
 const r=await (await fetch('/api/sim/run?'+qs)).json();
 if(r.error){$('sim_out').innerHTML='<div class="card">'+esc(r.error)+'</div>';return;}
 let h='<div class="card"><div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">'+
   '<div class="big">'+esc(c)+' <span class="mut" style="font-size:15px">vs '+esc(cov)+'</span></div>'+badge(r)+'</div>'+
   '<div class="kgrid k6" style="margin-top:14px">'+
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

/* ---------- Spielfeld & Animation (wiederverwendbar je SVG) ---------- */
const SVGNS='http://www.w3.org/2000/svg';
let lastDiag=null,lastRes=null;
const _anim={};
const mapX=x=>x*10, mapY=fy=>10+(26-fy)*10;
function el(tag,a){const e=document.createElementNS(SVGNS,tag);for(const k in a)e.setAttribute(k,a[k]);return e;}
function routeLen(pts){let L=0;for(let i=1;i<pts.length;i++)L+=Math.hypot(pts[i][0]-pts[i-1][0],pts[i][1]-pts[i-1][1]);return L;}
function posAlong(pts,frac){if(pts.length<2)return pts[0];const tot=routeLen(pts);let d=frac*tot;for(let i=1;i<pts.length;i++){const seg=Math.hypot(pts[i][0]-pts[i-1][0],pts[i][1]-pts[i-1][1]);if(d<=seg||i===pts.length-1){const t=seg?d/seg:0;return [pts[i-1][0]+(pts[i][0]-pts[i-1][0])*t,pts[i-1][1]+(pts[i][1]-pts[i-1][1])*t];}d-=seg;}return pts[pts.length-1];}
async function drawPlay(concept,coverage,res){
 const d=await (await fetch('/api/sim/diagram?concept='+encodeURIComponent(concept)+'&coverage='+encodeURIComponent(coverage))).json();
 if(d.error)return; lastDiag=d; lastRes=res;
 $('sim_fieldcard').style.display='block';
 $('field_title').textContent=concept+' vs '+coverage.replace(/ —.*/,'');
 renderField($('field'),d,parseInt($('sim_y').value)||10);
 playAnim($('field'),d,{kind:(d.kind==='run')?'run':'complete',yards:res?res.mean_yards:0});
}
function renderField(svg,d,ytg,cols,fpos,preSnap){
 cols=cols||{}; const offC=cols.off||'#16c784', defC=cols.def||'#ef5350';
 const P=svg.id;
 let s='<defs>'+
  '<linearGradient id="turf_'+P+'" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#125433"/><stop offset="1" stop-color="#0b3a22"/></linearGradient>'+
  '<marker id="ah_'+P+'" markerWidth="7" markerHeight="7" refX="4.5" refY="3" orient="auto"><path d="M0 0L6 3L0 6Z" fill="#19e08f"/></marker>'+
  '<marker id="aht_'+P+'" markerWidth="7" markerHeight="7" refX="4.5" refY="3" orient="auto"><path d="M0 0L6 3L0 6Z" fill="#ffd34d"/></marker></defs>';
 s+='<rect x="0" y="0" width="533" height="360" fill="url(#turf_'+P+')"/>';
 for(let i=0;i<8;i++)if(i%2)s+='<rect x="0" y="'+(i*45)+'" width="533" height="45" fill="#ffffff" opacity="0.025"/>';
 // feines 5-Yard-Raster + Hashmarks (Textur)
 for(let fy=-5;fy<=25;fy+=5){const y=mapY(fy).toFixed(1);
  s+='<line x1="0" y1="'+y+'" x2="533" y2="'+y+'" stroke="#cdeede" stroke-width="'+(fy===0?0:1)+'" opacity="0.16"/>';
  [23.58,29.72].forEach(hx=>{s+='<line x1="'+(mapX(hx)-3).toFixed(1)+'" y1="'+y+'" x2="'+(mapX(hx)+3).toFixed(1)+'" y2="'+y+'" stroke="#cdeede" stroke-width="1" opacity="0.30"/>';});}
 if(fpos!=null){
  // Echte Feldposition: Endzone + reale Yard-Linien (Feld scrollt mit dem Ball)
  if(fpos<=26){const ey=mapY(Math.min(fpos,26)),ty=mapY(26);
   s+='<rect x="0" y="'+ty+'" width="533" height="'+(ey-ty).toFixed(1)+'" fill="'+defC+'" opacity="0.22"/>';
   s+='<line x1="0" y1="'+ey+'" x2="533" y2="'+ey+'" stroke="#ffffff" stroke-width="2.5" opacity="0.85"/>';
   s+='<text x="266" y="'+(ty+18)+'" font-size="13" font-weight="800" fill="#ffffff" opacity="0.55" text-anchor="middle" letter-spacing="4">END ZONE</text>';}
  for(let g=0;g<=100;g+=10){const fy=fpos-g; if(fy<-7||fy>26.5)continue; const y=mapY(fy).toFixed(1);
   const lab=(g<=50?g:100-g);
   s+='<line x1="0" y1="'+y+'" x2="533" y2="'+y+'" stroke="#cdeede" stroke-width="1" opacity="0.30"/>';
   if(lab>0){s+='<text x="15" y="'+(parseFloat(y)+4)+'" font-size="11" font-weight="800" fill="#cdeede" opacity="0.45">'+lab+'</text>'+
     '<text x="518" y="'+(parseFloat(y)+4)+'" font-size="11" font-weight="800" fill="#cdeede" opacity="0.45" text-anchor="end">'+lab+'</text>';}}
 }else{
  // Sim-Tool ohne Feldkontext: Abstand vom LOS
  for(let fy=10;fy<=25;fy+=5)if(fy%10===0){const y=mapY(fy).toFixed(1);
   s+='<text x="13" y="'+(parseFloat(y)+4)+'" font-size="11" font-weight="800" fill="#cdeede" opacity="0.4">'+fy+'</text>'+
    '<text x="520" y="'+(parseFloat(y)+4)+'" font-size="11" font-weight="800" fill="#cdeede" opacity="0.4" text-anchor="end">'+fy+'</text>';}
 }
 s+='<line x1="0" y1="'+mapY(0)+'" x2="533" y2="'+mapY(0)+'" stroke="#5fa8ff" stroke-width="2.5" opacity="0.9"/>';
 if(ytg<=24)s+='<line x1="0" y1="'+mapY(ytg)+'" x2="533" y2="'+mapY(ytg)+'" stroke="#ffd34d" stroke-width="2" opacity="0.7" stroke-dasharray="7 5"/>';
 if(!preSnap)d.offense.forEach(o=>{if(o.route&&o.route.length>1){let p='';o.route.forEach((pt,i)=>{p+=(i?'L':'M')+mapX(pt[0]).toFixed(1)+' '+mapY(pt[1]).toFixed(1)+' ';});
  const acc=(o.target||o.carry);s+='<path d="'+p+'" fill="none" stroke="'+(acc?'#ffd34d':'#19e08f')+'" stroke-width="'+(acc?2.4:1.7)+'" opacity="'+(acc?0.95:0.6)+'" marker-end="url(#'+(acc?'aht_':'ah_')+P+')"/>';}});
 svg.innerHTML=s;
 d.defense.forEach((p,i)=>addPlayer(svg,p,defC,'d_'+i));
 d.offense.forEach((o,i)=>addPlayer(svg,o,offC,'o'+i,preSnap?{pos:o.pos}:o));   // Vor-Snap: keine Ziel-Markierung
 const qb=d.offense.find(o=>o.pos==='QB');
 const bx=preSnap?26.65:qb.x, by=preSnap?-0.7:qb.y;   // Vor-Snap: Ball ruht am Spot (Line of Scrimmage)
 svg.appendChild(el('ellipse',{id:P+'_pball',cx:mapX(bx),cy:mapY(by),rx:4,ry:2.5,fill:'#9a5a1e',stroke:'#3a1f08','stroke-width':1,opacity:preSnap?1:0}));
}
const _ppos={};
function addPlayer(svg,p,color,id,o){const P=svg.id;const sx=mapX(p.x),sy=mapY(p.y);
 const g=el('g',{}); g.id=P+'_pl_'+id; g.setAttribute('transform','translate('+sx+' '+sy+')');
 const fig=el('g',{}); fig.setAttribute('class','fig');
 if(o&&o.target){const ring=el('circle',{cx:0,cy:0,r:10.5,fill:'none',stroke:'#ffd34d','stroke-width':1.6,opacity:.9,'class':'pulse'});fig.appendChild(ring);}
 fig.appendChild(el('ellipse',{cx:0,cy:1.5,rx:6,ry:4.2,fill:color,stroke:'#06140d','stroke-width':1.3}));        // Schultern
 fig.appendChild(el('circle',{cx:0,cy:-3.5,r:3.1,fill:color,stroke:'#06140d','stroke-width':1.3}));              // Helm
 fig.appendChild(el('line',{x1:-2,y1:-5,x2:2,y2:-5,stroke:'#06140d','stroke-width':1}));                          // Facemask
 const lbl=(o?(o.pos==='OL'?'':o.pos):p.pos); if(lbl){const t=el('text',{x:0,y:3.5,'text-anchor':'middle','font-size':6.2,fill:'#03130c','font-weight':800});t.textContent=lbl;fig.appendChild(t);}
 g.appendChild(fig); svg.appendChild(g); _ppos[P+id]=[p.x,p.y];
}
function moveP(P,id,x,y){const g=$(P+'_pl_'+id);if(!g)return;g.setAttribute('transform','translate('+mapX(x)+' '+mapY(y)+')');_ppos[P+id]=[x,y];}
function popFig(P,id){const g=$(P+'_pl_'+id);if(!g)return;const f=g.querySelector('.fig');if(f){f.classList.remove('pop');void f.getBBox();f.classList.add('pop');}}
function downFig(P,id){const g=$(P+'_pl_'+id);if(!g)return;const f=g.querySelector('.fig');if(f){f.classList.add('down');}}
function spinFig(P,id){const g=$(P+'_pl_'+id);if(!g)return;const f=g.querySelector('.fig');if(f&&!f.classList.contains('spin')&&!f.classList.contains('down')){f.classList.add('spin');setTimeout(()=>f.classList.remove('spin'),460);}}
function celebrate(P,id){const g=$(P+'_pl_'+id);if(!g)return;const f=g.querySelector('.fig');if(f){f.classList.remove('down','spin');f.classList.add('cel','cel'+(Math.floor(Math.random()*10)+1));}}  // 1 von 10 TD-Jubeln
/* Kino-Jubel: Spiel pausiert, Endzonen-Kamera zeigt den tanzenden Spieler groß im Feldbereich */
function tdCelebration(svg,color,onDone){const P=svg.id;if(_anim[P]){cancelAnimationFrame(_anim[P]);_anim[P]=null;}
 const cel=Math.floor(Math.random()*10)+1;
 let s='<defs>'+
  '<linearGradient id="csky_'+P+'" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0a1622"/><stop offset="1" stop-color="#0f3b25"/></linearGradient>'+
  '<linearGradient id="ctf_'+P+'" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#1a6b40"/><stop offset="1" stop-color="#0c3f25"/></linearGradient></defs>'+
  '<rect x="0" y="0" width="533" height="360" fill="url(#csky_'+P+')"/>'+
  '<rect x="0" y="150" width="533" height="210" fill="url(#ctf_'+P+')"/>';                       // Rasen
 // Ränge/Publikum oben
 for(let r=0;r<3;r++)for(let i=0;i<41;i++){const cx=8+i*13,cy=18+r*13;s+='<circle cx="'+cx+'" cy="'+cy+'" r="2.4" fill="'+((i+r)%5===0?color:'#26313f')+'" opacity="0.8"/>';}
 // Spotlights
 s+='<polygon points="0,0 533,150 0,150" fill="#ffffff" opacity="0.04"/><polygon points="533,0 0,150 533,150" fill="#ffffff" opacity="0.04"/>';
 // Endzone vorne (Kamera steht in der Endzone)
 s+='<rect x="0" y="300" width="533" height="60" fill="'+color+'" opacity="0.30"/>'+
    '<line x1="0" y1="300" x2="533" y2="300" stroke="#ffffff" stroke-width="3" opacity="0.85"/>'+
    '<text x="266" y="338" text-anchor="middle" font-size="15" font-weight="800" fill="#ffffff" opacity="0.45" letter-spacing="7">END ZONE</text>';
 // TOUCHDOWN-Schrift (ohne Emoji)
 s+='<text class="tdword" x="266" y="92" text-anchor="middle" font-size="40" font-weight="800" fill="#ffffff" stroke="#06140d" stroke-width="1" letter-spacing="3" style="transform-box:fill-box;transform-origin:center">TOUCHDOWN</text>';
 // großer tanzender Spieler, zentral im Feldbereich
 s+='<g transform="translate(266 232) scale(6)"><g class="fig cel'+cel+'">'+
    '<rect x="-2.1" y="3.5" width="4.2" height="6" rx="1.4" fill="'+color+'" stroke="#06140d" stroke-width="0.9"/>'+      // Rumpf/Beine
    '<ellipse cx="0" cy="1.5" rx="6.6" ry="4.7" fill="'+color+'" stroke="#06140d" stroke-width="1"/>'+                    // Schultern
    '<circle cx="0" cy="-4.4" r="3.5" fill="'+color+'" stroke="#06140d" stroke-width="1"/>'+                             // Helm
    '<line x1="-2.1" y1="-5.8" x2="2.1" y2="-5.8" stroke="#06140d" stroke-width="0.8"/>'+                                // Facemask
    '</g></g>';
 // Konfetti
 for(let i=0;i<18;i++){const cx=12+i*29,dur=(1.4+(i%5)*0.28).toFixed(2),del=((i*0.21)%1.8).toFixed(2),col=[color,'#ffd34d','#ffffff','#5fa8ff'][i%4];
   s+='<rect class="conf" x="'+cx+'" y="-12" width="5" height="9" rx="1" fill="'+col+'" style="animation-duration:'+dur+'s;animation-delay:'+del+'s"/>';}
 svg.innerHTML=s;
 setTimeout(()=>{if(onDone)onDone();},2800);   // nach dem Tanz weiter (Extra-Punkt/FG)
}
function curPos(P,id){return _ppos[P+id]||null;}
const SPD={QB:7.4,RB:9.0,WR:9.6,TE:8.4,OL:6.0,DL:6.6,DE:6.9,DT:6.0,LB:8.5,CB:9.5,DB:9.4,S:8.9};
function _spd(p){return SPD[p]||8;}
function _toward(o,tx,ty,mx){const dx=tx-o.x,dy=ty-o.y,d=Math.hypot(dx,dy);if(d<=mx||d<1e-6){o.x=tx;o.y=ty;}else{o.x+=dx/d*mx;o.y+=dy/d*mx;}}
function _advance(o,mx){if(!o.route)return;let b=mx;while(b>0&&o.ri<o.route.length){const wp=o.route[o.ri],dx=wp[0]-o.x,dy=wp[1]-o.y,d=Math.hypot(dx,dy);if(d<=b){o.x=wp[0];o.y=wp[1];o.ri++;b-=d;}else{o.x+=dx/d*b;o.y+=dy/d*b;b=0;}}}
function playAnim(svg,d,res,onDone){
 const P=svg.id; if(_anim[P])cancelAnimationFrame(_anim[P]);
 res=res||{}; const kind=res.kind||(d.kind==='run'?'run':'complete');
 const yards=(res.yards!=null?res.yards:(res.mean_yards!=null?res.mean_yards:0));
 const td=!!res.td, vy=(td&&yards>24)?24:yards;   // bei Touchdown sichtbar in der Endzone enden, nicht getackelt
 const isPass=(kind!=='run'),ball=$(P+'_pball'),C=26.65;
 const O=d.offense.map((o,i)=>({i,pos:o.pos,x:o.x,y:o.y,sy:o.y,route:(o.route&&o.route.length>1)?o.route:null,ri:1,target:!!o.target,carry:!!o.carry}));
 const D=d.defense.map((p,i)=>({i,pos:p.pos,x:p.x,y:p.y,role:p.role,cover:p.cover,drop:p.drop}));
 const qb=O.find(o=>o.pos==='QB'),tgt=O.find(o=>o.target||o.carry),ols=O.filter(o=>o.pos==='OL');
 // Ballträger-Route auf den tatsächlichen Raumgewinn kürzen (Completion: Fang dann YAC; Lauf: bis Yards, auch negativ)
 if((kind==='complete'||kind==='run')&&tgt&&tgt.route){const r=tgt.route,rY=r[r.length-1][1];
   const cy=(kind==='complete')?Math.min(rY,Math.max(1,vy)):Math.min(rY,vy);
   const out=[r[0]];for(let k=1;k<r.length;k++){const a=r[k-1],b=r[k];
     if(b[1]<=cy+0.01){out.push(b);}else{const f=Math.max(0,Math.min(1,(cy-a[1])/((b[1]-a[1])||1)));out.push([a[0]+(b[0]-a[0])*f,cy]);break;}}
   tgt.route=out;}
 const catchPt=(tgt&&tgt.route)?tgt.route[tgt.route.length-1]:(d.ball_target||[qb.x,qb.y]);
 const gain=[catchPt[0],(kind==='complete')?Math.max(catchPt[1],vy):vy];   // complete: YAC bis Yards; Lauf: genau Yards
 const runEnd=(!isPass&&tgt)?[catchPt[0],vy]:null;
 let intD=null;if(kind==='int'){let bd=1e9;D.forEach(p=>{const dd=Math.hypot(p.x-catchPt[0],p.y-catchPt[1]);if(dd<bd){bd=dd;intD=p;}});}
 const t0=performance.now();let last=t0,thrown=false,tAt=0,bp=[qb.x,qb.y],arrived=false,caught=false,sacked=false,arrTime=0;
 const flightDur=Math.max(0.35,Math.hypot((intD?intD.x:catchPt[0])-qb.x,(intD?intD.y:catchPt[1])-qb.y)/26);
 function frame(now){const dt=Math.min(0.05,(now-last)/1000);last=now;const el=(now-t0)/1000;const acc=Math.min(1,0.4+el*1.5);const M=p=>_spd(p)*dt*acc;  // Beschleunigung vom Snap weg
  const carrier=(kind==='complete'&&caught)?tgt:(!isPass?tgt:null);
  // QB
  if(isPass&&!sacked){_toward(qb,qb.sy<-3?qb.sy:(qb.sy-2.3),qb.sy-2.3,M('QB')*0.85);qb.x=C;}
  else if(!isPass){_toward(qb,C-0.6,-3.6,M('QB')*0.7);}
  // Offense
  O.forEach(o=>{if(o.pos==='QB')return;
   if(o.pos==='OL'){const idx=ols.indexOf(o),off=idx-(ols.length-1)/2;
     if(isPass){let r=null,bd=1e9;D.forEach(p=>{if(p.role!=='rush')return;const dd=Math.hypot(p.x-o.x,p.y-o.y);if(dd<bd){bd=dd;r=p;}});
       if(r){_toward(o,r.x*0.55+(C+off*1.4)*0.45,Math.max(-2.8,Math.min(-0.4,r.y-0.9)),M('OL'));}  // Blocker stellt sich goalside vor den Rusher
       else _toward(o,C+off*1.7,-2.2,M('OL'));}
     else{const lane=runEnd?runEnd[0]:C;  // Run-Block: nächsten Front-Verteidiger aufnehmen und vom Loch wegtreiben
       let r=null,bd=1e9;D.forEach(p=>{if(p.role==='man'||p.drop)return;const dd=Math.hypot(p.x-o.x,p.y-o.y);if(dd<bd){bd=dd;r=p;}});
       if(r){const side=(r.x<=lane)?0.7:-0.7;_toward(o,r.x+side,Math.max(o.y,r.y-0.3),M('OL')*1.08);}  // an die Lade-Schulter, Verteidiger vom Loch wegdrücken
       else _toward(o,o.x+(lane-o.x)*0.2,Math.min(3.5,o.y+2.4),M('OL'));}
     return;}
   if(o===tgt){
     if(isPass){if(!caught)_advance(o,M(o.pos));else if(kind==='complete')_toward(o,gain[0],gain[1],M(o.pos));}
     else{_advance(o,M(o.pos));if(o.ri>=o.route.length&&runEnd)_toward(o,runEnd[0],runEnd[1],M(o.pos));}
     if(!isPass||caught){const nd=D.reduce((m,q)=>Math.min(m,Math.hypot(q.x-o.x,q.y-o.y)),9);   // Ballträger weicht bei Druck aus
       if(nd<2.4){o.x+=Math.sin(el*16+o.i)*0.5;if(nd<1.5&&!o._spun){o._spun=1;spinFig(P,'o'+o.i);}}}  // Juke + Spin-Move
     return;}
   if(o.route){_advance(o,M(o.pos));
     if(o.ri>=o.route.length&&!caught){o.y+=M(o.pos)*0.45;o.x+=(Math.sin((el+o.i)*2.2))*M(o.pos)*0.25;}}  // weiter freilaufen bis zum Wurf
  });
  // Ball / Wurf
  if(isPass&&kind!=='sack'){
   const tgtDone=tgt&&tgt.ri>=(tgt.route?tgt.route.length:1);
   if(!thrown&&(tgtDone||el>1.7)){thrown=true;tAt=now;bp=[qb.x,qb.y];}
   if(thrown&&!arrived){const dest=intD?[intD.x,intD.y]:catchPt;const o2={x:bp[0],y:bp[1]};_toward(o2,dest[0],dest[1],26*dt);bp=[o2.x,o2.y];
     if(Math.hypot(dest[0]-bp[0],dest[1]-bp[1])<0.5){arrived=true;arrTime=el;if(kind==='complete'){caught=true;popFig(P,'o'+tgt.i);}}}
   else if(arrived){if(kind==='complete'&&caught)bp=[tgt.x,tgt.y];else if(intD)bp=[intD.x,intD.y];}
  }
  // Defense (geschwindigkeitsbasiert)
  D.forEach(p=>{let tx,ty,mx=M(p.pos);
   if(kind==='sack'){tx=qb.x;ty=qb.y;}
   else if(carrier){tx=carrier.x;ty=carrier.y;}                          // Ballträger verfolgen (eigenes Tempo)
   else if(p.role==='rush'){tx=qb.x+Math.sin(el*7+p.i)*0.5;ty=qb.y;mx*=0.92;}  // drückt zum QB – wird von der O-Line geblockt (Kollision)
   else if(p.role==='man'&&p.cover){const r=O.find(o=>o.pos===p.cover);if(r){tx=r.x+(p.x<r.x?-0.8:0.8);ty=r.y+0.7;}else{tx=p.x;ty=p.y;}}
   else if(p.drop){tx=p.drop[0];ty=p.drop[1];                              // Zone: zur Landmarke, dann auf nächsten Receiver in der Zone reagieren
     let bestR=null,bd=8.5;O.forEach(o=>{if(o.pos==='QB'||o.pos==='OL')return;const dd=Math.hypot(o.x-p.drop[0],o.y-p.drop[1]);if(dd<bd){bd=dd;bestR=o;}});
     if(bestR){tx=p.drop[0]+(bestR.x-p.drop[0])*0.45;ty=p.drop[1]+(bestR.y-p.drop[1])*0.30;}mx*=0.85;}
   else{tx=p.x;ty=p.y;}
   _toward(p,tx,ty,mx);
  });
  // Sack: QB wird zurückgedrängt sobald Rusher nah
  if(kind==='sack'){if(D.some(p=>p.role==='rush'&&Math.hypot(p.x-qb.x,p.y-qb.y)<1.4)||el>1.3){sacked=true;qb.y=Math.max(qb.y-M('QB'),yards);}}
  // Kollision: gegnerische Körper durchdringen sich nicht (Offense hält Stand, Verteidiger wird abgedrängt)
  for(let it=0;it<2;it++)O.forEach(o=>{if(o.pos==='QB'&&kind!=='sack')return;
    D.forEach(p=>{const dx=p.x-o.x,dy=p.y-o.y,dist=Math.hypot(dx,dy);
      const mind=(o.pos==='OL')?1.9:(o===carrier?1.0:1.3);
      if(dist<mind&&dist>1e-4){const push=mind-dist,ux=dx/dist,uy=dy/dist;
        if(kind==='sack'&&o.pos==='OL'&&p.role==='rush'){o.x-=ux*push;o.y-=uy*push;}  // Sack: Rusher setzt sich durch
        else{p.x+=ux*push;p.y+=uy*push;}}});});                                        // sonst: Verteidiger wird geblockt
  // schreiben
  O.forEach(o=>moveP(P,'o'+o.i,o.x,o.y));
  D.forEach(p=>moveP(P,'d_'+p.i,p.x,p.y));
  if(ball){
   if(!isPass){if(carrier){ball.setAttribute('opacity',1);ball.setAttribute('cx',mapX(carrier.x));ball.setAttribute('cy',mapY(carrier.y));}else ball.setAttribute('opacity',0);}
   else if(kind==='sack'){ball.setAttribute('opacity',0);}
   else if(thrown){const fp=arrived?1:Math.min(1,(now-tAt)/1000/flightDur);const arc=Math.sin(fp*Math.PI)*14;
     ball.setAttribute('cx',mapX(bp[0]));ball.setAttribute('cy',mapY(bp[1])-arc);
     ball.setAttribute('opacity',(kind==='incomplete'&&arrived)?Math.max(0,1-(el-arrTime)/0.4):1);}
   else ball.setAttribute('opacity',0);
  }
  // Ende: erst wenn der Raumgewinn erreicht ist (Verteidiger treffen dort ein = Tackle), Pass aufgelöst, Sack oder Timeout
  const atGain=carrier&&((kind==='complete'&&Math.hypot(carrier.x-gain[0],carrier.y-gain[1])<0.6)||(!isPass&&runEnd&&Math.hypot(carrier.x-runEnd[0],carrier.y-runEnd[1])<0.6));
  const done=el>6.5 || (kind==='incomplete'&&arrived&&el>arrTime+0.5) || (kind==='int'&&arrived&&el>arrTime+0.8)
    || (kind==='sack'&&sacked&&qb.y<=yards+0.3) || (atGain&&el>1.0);
  if(!done)_anim[P]=requestAnimationFrame(frame);
  else if(td&&carrier){                                                                 // TD: durchgelaufen, Spiel pausiert -> Kino-Jubel
    celebrate(P,'o'+carrier.i);
    showResult(svg,{kind,yards,td,pt:[carrier.x,carrier.y]});
    if(res.celColor)setTimeout(()=>tdCelebration(svg,res.celColor,onDone),750);          // Schwenk auf den tanzenden Spieler
    else if(onDone)setTimeout(onDone,2200);
  }
  else{
    if(kind==='sack')downFig(P,'o'+qb.i);
    else if(carrier&&kind!=='incomplete')downFig(P,'o'+carrier.i);                      // Tackle: Ballträger geht zu Boden
    showResult(svg,{kind,yards,td,pt:(carrier?[carrier.x,carrier.y]:(kind==='sack'?[qb.x,vy]:catchPt))});
    if(onDone)setTimeout(onDone,1100);}
 }
 _anim[P]=requestAnimationFrame(frame);
}
function showResult(svg,res){
 const td=res.td;
 const label=td?'TOUCHDOWN!':res.kind==='incomplete'?'Incomplete':res.kind==='int'?'INTERCEPTION':res.kind==='sack'?('Sack '+Math.round(res.yards)):((res.yards>=0?'+':'')+Number(res.yards).toFixed(res.kind==='run'?0:1)+' Yds');
 const col=td?'#19e08f':(res.kind==='int'||res.kind==='sack')?'#ef5350':res.kind==='incomplete'?'#cdeede':'#ffd34d';
 const pt=res.pt||[26,5],px=mapX(pt[0]),py=mapY(pt[1]),w=td?108:72,x=Math.min(Math.max(px,54),480),y=Math.max(py-16,16);
 const g=el('g',{});
 if(res.kind!=='incomplete'&&!td){g.appendChild(el('circle',{cx:px,cy:py,r:14,fill:'none',stroke:'#fff',opacity:.22,'stroke-width':2}));}  // Tackle-/Endpunkt (beim TD kein Tackle)
 g.appendChild(el('rect',{x:x-w/2,y:y-13,width:w,height:22,rx:6,fill:'#0a0f0d',stroke:col,'stroke-width':td?1.8:1.3}));
 const tx=el('text',{x:x,y:y+2,'text-anchor':'middle','font-size':td?12.5:11,fill:col,'font-weight':800});tx.textContent=label;g.appendChild(tx);svg.appendChild(g);
}
function replayPlay(){renderField($('field'),lastDiag,parseInt($('sim_y').value)||10);playAnim($('field'),lastDiag,{kind:(lastDiag&&lastDiag.kind==='run')?'run':'complete',yards:lastRes?lastRes.mean_yards:0});}
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
function navIcon(k){const I={grid:'<path d="M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z"/>',
 team:'<circle cx="9" cy="8" r="3"/><path d="M3 20a6 6 0 0 1 12 0M16 11a3 3 0 1 0-1-5.8M21 20a5 5 0 0 0-4-4.9"/>',
 chart:'<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',swap:'<path d="M7 7h13l-3-3M17 17H4l3 3"/>',
 tool:'<path d="M14 7a4 4 0 0 1-5 5l-6 6 2 2 6-6a4 4 0 0 1 5-5l-2-2 2-2z"/>'};
 return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'+(I[k]||I.grid)+'</svg>';}
function pill(t){return '<span class="pill">'+esc(t)+'</span>';}
let mgrTab='dash',lastView=null;
function mgrGo(t){mgrTab=t;renderMgr(lastView);}
function renderMgr(v){
 lastView=v;
 const phaseLabel={regular:'Reguläre Saison',playoffs:(v.playoff?v.playoff.round:'Playoffs'),done:'Saison beendet'}[v.phase];
 let h='<div class="tbanner" style="--tc:'+esc(v.color||'#16c784')+'"><div class="teamhdr">'+
   '<div class="crest" style="background:'+esc(v.color||'#16c784')+'">'+esc(v.abbr||'')+'</div>'+
   '<div><div class="big">'+esc(v.team_name)+'</div><div class="mut" style="color:#dfe7e3">Saison '+v.season+' · '+esc(phaseLabel)+'</div></div>'+
   '<div style="margin-left:auto;text-align:right">'+pill('Bilanz '+v.record.w+'–'+v.record.l)+' '+pill('Budget '+v.budget+' Mio')+' '+pill('Punkte '+v.skillpoints)+
   ' <button class="ghost" style="padding:5px 10px" onclick="openTutorial(0)">? Anleitung</button></div></div>'+
   '<div class="kgrid" style="margin-top:14px">'+kpi('Overall',v.ratings.ovr)+kpi('Offense',v.ratings.off)+kpi('Defense',v.ratings.def)+
   kpi('Woche',v.phase==='regular'?(v.week+1)+' / '+v.n_weeks:'—')+'</div>'+
   (v.champion?'<div class="reco champ" style="margin-top:14px"><span><span class="tag">MEISTER</span> <b>'+esc(v.champion)+'</b></span><span class="mut">Saison '+v.season+'</span></div>':'')+
   '</div>';
 // Unter-Navigation
 const tabs=[['dash','Dashboard','grid'],['kader','Kader & Training','team'],['stats','Statistik','chart'],['transfer','Transfermarkt','swap'],['build','Verbesserungen','tool']];
 const needs={dash:(v.phase!=='done'&&!v.week_done&&!v.week_trained),kader:v.skillpoints>0,stats:false,transfer:(v.scout_pts>0),build:false};
 h+='<div class="subnav">'+tabs.map(t=>'<div class="s'+(mgrTab===t[0]?' on':'')+'" data-t="'+t[0]+'" onclick="mgrGo(this.dataset.t)">'+navIcon(t[2])+'<span>'+t[1]+'</span>'+(needs[t[0]]?'<span class="navbadge">!</span>':'')+'</div>').join('')+'</div>';
 h+=(mgrTab==='kader'?secKader(v):mgrTab==='build'?secBuild(v):mgrTab==='transfer'?secTransfer(v):mgrTab==='stats'?secStats(v):secDash(v));
 $('mgr_out').innerHTML=h;
 if(!v.tutorial_seen && !window._tutShown){window._tutShown=true; openTutorial(0);}
}
function trainIcon(k){const I={team:'<circle cx="12" cy="8" r="3"/><path d="M5 20a7 7 0 0 1 14 0"/>',
 off:'<path d="M12 19V5M6 11l6-6 6 6"/>',def:'<path d="M12 3l7 3v6c0 4-3 7-7 9-4-2-7-5-7-9V6z"/>',
 star:'<path d="M12 3l2.6 5.6L21 9.3l-4.5 4.2L17.6 21 12 17.8 6.4 21l1.1-7.5L3 9.3l6.4-.7z"/>',
 heal:'<path d="M10 3h4v7h7v4h-7v7h-4v-7H3v-4h7z"/>',film:'<path d="M5 5h14v14H5zM5 9h14M9 5v14"/>'};
 return '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2">'+(I[k]||I.team)+'</svg>';}
function secDash(v){
 let h='';
 const active=v.phase!=='done'&&!v.week_done;
 // 1) Training zuerst — Pflicht vor dem Spiel
 if(active){h+='<div class="card stepcard"><div class="sec" style="margin-top:0"><span class="stepnum">1</span>Training dieser Woche'+(v.week_trained?'':' <span class="navbadge">!</span>')+'</div>';
   if(v.week_trained)h+='<div class="reco win"><span>Training erledigt ✓</span><span class="mut">weiter zu Schritt 2</span></div>'+(v.game_bonus>0?'<div class="note">Film-Bonus aktiv fürs nächste Spiel.</div>':'');
   else h+='<div class="traingrid">'+v.trainings.map(t=>'<button class="traincard" data-k="'+t.key+'" onclick="trainWeek(this.dataset.k)"><span class="ti">'+trainIcon(t.icon)+'</span><b>'+esc(t.label)+'</b><span class="td">'+esc(t.desc)+'</span></button>').join('')+'</div>';
   h+='</div>';}
 // 2) Spielbetrieb
 h+='<div class="card'+(active?' stepcard':'')+'" id="gamecard"><div class="sec" style="margin-top:0">'+(active?'<span class="stepnum">2</span>':'')+(v.phase==='done'?'Saison beendet':(v.is_bye?'Bye Week':(v.phase==='playoffs'?(v.playoff?v.playoff.round:'Playoffs'):'Woche '+(v.week+1))))+'</div>';
 if(v.phase==='done'){h+='<div class="reco champ"><span>Saison beendet'+(v.champion?' · Meister '+esc(v.champion):'')+'.</span></div><button onclick="newSeason()">Neue Saison starten</button> ';}
 else if(v.week_done){
   h+='<div class="reco win"><span>Woche ausgewertet'+(v.is_bye?' (Bye Week)':'')+'.</span><span class="mut">bereit für die nächste Woche</span></div>'+
     '<button onclick="nextWeek()">Nächste Woche ▶</button> ';
   if(v.has_last_game)h+='<button class="ghost" onclick="watchLast()">Spiel ansehen</button> ';
 }
 else if(!v.week_trained){
   h+='<div class="reco"><span class="mut">Erst das Training dieser Woche absolvieren (Schritt 1).</span></div>'+
     '<button disabled>'+(v.is_bye?'Woche abschließen':'Selbst spielen')+'</button>'+(v.is_bye?'':' <button class="ghost" disabled>Simulieren</button>');
 }
 else if(v.is_bye){h+='<div class="reco"><span><b>Bye Week</b> — diese Woche kein Spiel</span><span class="mut">Training erledigt — Woche abschließen</span></div>'+
   '<button onclick="simWeek()">Woche abschließen</button> ';}
 else{
   if(v.next)h+='<div class="reco"><span style="display:flex;align-items:center;gap:9px">'+teamLogo(v.next.abbr,v.next.color)+
     '<span>Nächstes Spiel: <b>'+(v.next.home?'vs':'@')+' '+esc(v.next.name)+'</b> <span class="mut" style="display:block;font-size:12px">OVR '+v.next.ovr+' · Off: '+esc(v.next.off_scheme)+' · Def: '+esc(v.next.def_scheme)+'</span></span></span></div>';
   if(v.phase==='playoffs'&&v.playoff)h+='<div class="reco"><span><b>'+esc(v.playoff.round)+'</b> — '+
     v.playoff.pairs.map(p=>esc(p[0])+' vs '+esc(p[1])).join(' · ')+'</span></div>';
   if(v.active_game)h+='<button onclick="resumeGame()">Spiel fortsetzen</button> ';
   else h+='<button onclick="startGame()">Selbst spielen</button> <button class="ghost" onclick="simWeek()">Simulieren</button> ';
 }
 if(v.last_result)h+=renderResult(v.last_result,v.team_name);
 h+='</div>';
 // Saison-Ziele (kompakt)
 if(v.goals&&v.goals.length){h+='<div class="card" id="goalcard"><div class="sec" style="margin-top:0">Saison-Ziele</div>'+
   v.goals.map(g=>{const prog=g.key==='wins'?' ('+g.progress+'/'+g.target+')':'';return '<div class="reco mini'+(g.done?' win':'')+'"><span>'+(g.done?'✓ ':'')+esc(g.label)+prog+'</span><span class="mut">'+(g.done?'erfüllt':'+'+g.reward+' Mio')+'</span></div>';}).join('')+'</div>';}
 // Neuigkeiten (kompakt)
 if(v.events&&v.events.length){h+='<div class="card"><div class="sec" style="margin-top:0">Neuigkeiten</div>'+
   v.events.map(e=>'<div class="reco mini '+(e.type==='bad'?'loss':(e.type==='ok'?'win':''))+'"><span>'+esc(e.text)+'</span></div>').join('')+'</div>';}
 const offk=Object.keys(v.off_schemes),defk=Object.keys(v.def_schemes);
 h+='<div class="card"><div class="sec" style="margin-top:0">Team-Schema</div><div class="controls">'+
   '<div><label>Offense-Schema</label><select id="sc_off">'+offk.map(k=>'<option'+(k===v.scheme.off?' selected':'')+'>'+esc(k)+'</option>').join('')+'</select></div>'+
   '<div><label>Defense-Schema</label><select id="sc_def">'+defk.map(k=>'<option'+(k===v.scheme.def?' selected':'')+'>'+esc(k)+'</option>').join('')+'</select></div>'+
   '<button onclick="setScheme()">Übernehmen</button></div>'+
   '<div class="note">Off: '+esc((v.off_schemes[v.scheme.off]||[]).join(', '))+'<br>Def: '+esc((v.def_schemes[v.scheme.def]||[]).join(', '))+'</div></div>';
 h+='<div class="card scroll"><div class="sec" style="margin-top:0">Tabelle</div><table class="tbl"><tr>'+
   '<th class="cn">#</th><th class="cn">Team</th><th>S</th><th>N</th><th>Diff</th><th>OVR</th></tr>';
 v.standings.forEach(t=>{h+='<tr'+(t.user?' class="me"':'')+'><td>'+t.rank+'</td><td class="cn">'+teamLogo(t.abbr,t.color)+' <span style="vertical-align:middle">'+esc(t.name)+'</span>'+
   '</td><td>'+t.w+'</td><td>'+t.l+'</td><td>'+(t.diff>=0?'+':'')+t.diff+'</td><td>'+t.ovr+'</td></tr>';});
 h+='</table></div>';
 h+='<div style="text-align:center;margin:16px 0 4px"><button class="ghost" onclick="resetFr()" style="opacity:.7;font-size:13px">Franchise zurücksetzen</button></div>';
 return h;
}
function secKader(v){
 let h='<div class="card"><div class="sec" style="margin-top:0">Kader-Übersicht</div>'+
   '<div class="kgrid">'+kpi('Skillpunkte',v.skillpoints)+kpi('Equipment','St. '+v.equipment.level)+kpi('Kadergröße',v.roster.length)+kpi('Overall',v.ratings.ovr)+'</div>'+
   (v.skillpoints>0?'<div style="margin-top:12px"><button onclick="allocAll()">Alle Skillpunkte auto-verteilen ('+v.skillpoints+')</button></div>':'')+
   '<div class="note">EXP kommt aus dem Wochen-Training (Dashboard) und aus Spiel-Leistung. Je 100 EXP = 1 Skillpunkt. Klick einen Spieler an, um Punkte auf Attribute zu verteilen.</div></div>';
 [['Offense',['QB','RB','WR','OL']],['Defense',['DL','LB','DB']]].forEach(grp=>{
   h+='<div class="card"><div class="sec" style="margin-top:0">'+grp[0]+'</div>';
   grp[1].forEach(pos=>{const ps=v.roster.filter(p=>p.pos===pos);if(!ps.length)return;
     h+='<div style="margin:12px 0 4px">'+posBadge(pos)+' <span class="mut" style="font-weight:700">'+pos+'</span></div>';
     ps.forEach(p=>{const bar=Math.round(p.ovr/Math.max(p.pot,1)*100);
       h+='<div class="prow" data-i="'+p.id+'" onclick="openPlayer(this.dataset.i)">'+
        ovrBadge(p.ovr)+
        '<span class="pname">'+esc(p.name)+(p.starter?' <span class="tag" style="background:#16c784;color:#04140c">START</span>':'')+(p.inj>0?' <span class="tag" style="background:#3a1d1d;color:#ff8a8a">VERLETZT '+p.inj+'W</span>':'')+
        '<span class="mut" style="display:block;font-size:12px">Alter '+p.age+' · Pot '+p.pot+(p.season&&p.season.games?' · '+p.season.games+' Sp.':'')+'<div class="ovrbar"><div class="ovrfill" style="width:'+bar+'%"></div></div></span></span>'+
        (p.pts>0?'<span class="ptbadge">'+p.pts+' P</span>':'<span class="mut" style="font-size:12px">'+p.exp+'/100</span>')+'</div>';});
   });
   h+='</div>';});
 return h;
}
async function setFocus(){const r=await api('/api/fr/focus?group='+encodeURIComponent($('foc').value),'POST');if(r.view)renderMgr(r.view);}
async function allocAll(){const r=await api('/api/fr/alloc_all','POST');if(r.view)renderMgr(r.view);}
function openPlayer(id){_curPid=id;const p=lastView.roster.find(x=>String(x.id)===String(id));if(!p)return;
 let o=$('playeroverlay');if(!o){o=document.createElement('div');o.className='overlay';o.id='playeroverlay';
   o.addEventListener('click',e=>{if(e.target===o)closePlayer();});document.body.appendChild(o);}lockBody();
 o.innerHTML='<div class="modal" id="playermodal"></div>';renderPlayer(p);
}
function renderPlayer(p){
 let h='<div class="modalhead"><h3 style="display:flex;align-items:center;gap:9px">'+ovrBadge(p.ovr)+posBadge(p.pos)+esc(p.name)+devBadge(p.dev,p.dev_label)+
   '<span class="mut" style="font-weight:600;font-size:13px">'+(p.starter?'Starter':'Bank')+(p.inj>0?' · verletzt '+p.inj+'W':'')+'</span></h3>'+
   '<button class="ghost" onclick="closePlayer()">Schließen</button></div>'+
   '<div class="kgrid">'+kpi('OVR',p.ovr)+kpi('Potenzial',p.pot)+kpi('Alter',p.age)+kpi('Skillpunkte',p.pts)+'</div>';
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
 const sl=statLine(p.season)||'noch keine Einsätze', cl=statLine(p.career)||'—';
 h+='<div class="sec">Statistik</div>'+
   '<div class="reco"><span class="mut">Saison ('+p.season.games+' Sp.)</span><span style="text-align:right">'+esc(sl)+'</span></div>'+
   '<div class="reco"><span class="mut">Karriere ('+p.career.games+' Sp.)</span><span style="text-align:right">'+esc(cl)+'</span></div>';
 h+='<div style="margin-top:12px">'+
   (p.pts>0?'<button onclick="autoAlloc()">Auto-verteilen ('+p.pts+')</button> ':'')+
   '<button class="ghost" onclick="toggleStarter()">'+(p.starter?'Aus Startelf nehmen':'In Startelf setzen')+'</button> '+
   '<button class="ghost" data-i="'+p.id+'" onclick="cutP(this.dataset.i)">Entlassen</button></div>'+
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
function closePlayer(){const o=$('playeroverlay');if(o)o.remove();_curPid=null;unlockBodyIfNone();}
function secTransfer(v){
 const cnt={};v.roster.forEach(p=>cnt[p.pos]=(cnt[p.pos]||0)+1);
 // --- College-Scouting & Draft (Kopf-Feature) ---
 const sp=v.scout_pts||0;
 let h='<div class="card"><div class="schead"><div class="sec" style="margin:0">College-Scouting — Draft</div>'+
   '<div class="scoutpts"><span class="v">'+sp+'</span><span class="l">Punkte</span></div></div>'+
   '<div class="note">Scoute Talente (1 Punkt je Stufe), um Werte, Potenzial &amp; Entwicklungs-Trait aufzudecken — oder direkt draften und auf die Anlage wetten. Jede Woche +3 Punkte.</div></div>';
 const pros=v.prospects||[];
 [['Offense',['QB','RB','WR','OL']],['Defense',['DL','LB','DB']]].forEach(grp=>{
   const ps=pros.filter(p=>grp[1].includes(p.pos));if(!ps.length)return;
   h+='<div class="card"><div class="sec" style="margin-top:0">College · '+grp[0]+'</div>';
   ps.forEach(p=>{const full=(cnt[p.pos]||0)>=v.slots[p.pos];const done=p.scout>=p.scout_max;
     const ovrTxt=(p.ovr!=null)?('OVR '+p.ovr+' · Pot '+p.pot):('OVR '+p.ovr_lo+'–'+p.ovr_hi);
     const dev=(p.ovr!=null)?(' '+devBadge(p.dev,p.dev_label)):'';
     const extra=(p.grade&&p.grade!=='?'?' · '+esc(p.grade):'')+(p.strength?' · '+esc(p.strength):'');
     h+='<div class="reco prospect"><span style="display:flex;align-items:center;gap:9px;flex:1;min-width:0">'+posBadge(p.pos)+
       '<span style="min-width:0"><span class="nm">'+esc(p.name)+'</span>'+dev+
       '<span class="mut sub">'+ovrTxt+' · Alter '+p.age+' · '+esc(p.round)+extra+'</span>'+
       scoutDots(p.scout,p.scout_max)+'</span></span>'+
       '<span class="act">'+
       '<button class="ghost" data-i="'+p.id+'" onclick="scoutP(this.dataset.i)" '+((sp<1||done)?'disabled':'')+'>'+(done?'✓ Komplett':'Scouten (1)')+'</button>'+
       '<button data-i="'+p.id+'" onclick="draftP(this.dataset.i)" '+((v.budget<p.cost||full)?'disabled':'')+'>'+(full?p.pos+' voll':'Draften ('+p.cost+')')+'</button>'+
       '</span></div>';});
   h+='</div>';});
 // --- Free Agents (sofort einsatzbereit, voll sichtbar) ---
 h+='<div class="card"><div class="sec" style="margin-top:0">Free Agents</div>'+
   '<div class="note">Fertige Spieler mit bekannten Werten. Position voll? Erst im Kader jemanden entlassen.</div></div>';
 [['Offense',['QB','RB','WR','OL']],['Defense',['DL','LB','DB']]].forEach(grp=>{
   const ps=v.market_players.filter(p=>grp[1].includes(p.pos));if(!ps.length)return;
   h+='<div class="card"><div class="sec" style="margin-top:0">'+grp[0]+'</div>';
   ps.forEach(p=>{const full=(cnt[p.pos]||0)>=v.slots[p.pos];
     h+='<div class="reco"><span style="display:flex;align-items:center;gap:9px">'+ovrBadge(p.ovr)+posBadge(p.pos)+'<span><b>'+esc(p.name)+'</b> <span class="mut" style="display:block;font-size:12px">Alter '+p.age+' · Pot '+p.pot+'</span></span></span>'+
       '<button data-i="'+p.id+'" onclick="signP(this.dataset.i)" '+((v.budget<p.cost||full)?'disabled':'')+'>'+(full?p.pos+' voll':'Verpflichten ('+p.cost+' Mio)')+'</button></div>';});
   h+='</div>';});
 return h;
}
function secStats(v){
 const R=v.roster;
 const leader=(key,fmt)=>{let best=null;R.forEach(p=>{if(!best||p.season[key]>best.season[key])best=p;});
   return best&&best.season[key]>0?'<div class="reco"><span style="display:flex;align-items:center;gap:9px">'+posBadge(best.pos)+'<b>'+esc(best.name)+'</b></span><span>'+fmt(best.season)+'</span></div>':'';};
 let h='<div class="card"><div class="sec" style="margin-top:0">Saison-Bestenliste (dein Team)</div>'+
   (leader('pass_yds',s=>s.pass_yds+' Pass-Yds, '+s.pass_td+' TD')||'')+
   (leader('rush_yds',s=>s.rush_yds+' Rush-Yds ('+s.rush_att+' Läufe)')||'')+
   (leader('rec_yds',s=>s.rec+' Fänge, '+s.rec_yds+' Yds')||'')+
   (leader('tkl',s=>s.tkl+' Tackles')||'')+
   (leader('sack',s=>s.sack+' Sacks')||'')+
   (leader('intc',s=>s.intc+' Interceptions')||'')+
   '<div class="note">Werte aus gewerteten Spielen dieser Saison.</div></div>';
 // Saison-Statistiktabelle (Spieler mit Einsätzen)
 const played=R.filter(p=>p.season.games>0).sort((a,b)=>b.season.games-a.season.games||playerImpact(b)-playerImpact(a));
 if(played.length){h+='<div class="card scroll"><div class="sec" style="margin-top:0">Saison-Statistik</div>'+
   '<table class="tbl"><tr><th class="cn">Spieler</th><th>Sp</th><th>Pass</th><th>Rush</th><th>Rec</th><th>Tkl</th><th>Sck</th><th>INT</th><th>TD</th></tr>'+
   played.map(p=>'<tr><td class="cn">'+posBadge(p.pos)+' '+esc(p.name)+'</td><td>'+p.season.games+'</td>'+
     '<td>'+p.season.pass_yds+'</td><td>'+p.season.rush_yds+'</td><td>'+p.season.rec_yds+'</td>'+
     '<td>'+p.season.tkl+'</td><td>'+p.season.sack+'</td><td>'+p.season.intc+'</td><td>'+p.season.td+'</td></tr>').join('')+
   '</table></div>';}
 // Meister-Historie
 if(v.history&&v.history.length){h+='<div class="card"><div class="sec" style="margin-top:0">Meister-Historie</div>'+
   v.history.map(x=>'<div class="reco"><span>Saison '+x.season+'</span><span class="mut">'+esc(x.champion)+'</span></div>').join('')+'</div>';}
 return h;
}
function playerImpact(p){const s=p.season;return s.pass_yds/20+s.rush_yds/12+s.rec_yds/12+s.tkl+s.sack*3+s.intc*5+s.td*4;}
async function signP(id){const r=await api('/api/fr/sign?pid='+id,'POST');if(r.result&&r.result.error)alert(r.result.error);if(r.view)renderMgr(r.view);}
async function scoutP(id){const r=await api('/api/fr/scout?pid='+id,'POST');if(r.result&&r.result.error)alert(r.result.error);if(r.view)renderMgr(r.view);}
async function draftP(id){const r=await api('/api/fr/draft?pid='+id,'POST');if(r.result&&r.result.error){alert(r.result.error);return;}if(r.result&&r.result.drafted)alert('Gedraftet: '+r.result.drafted+' (OVR '+r.result.ovr+')');if(r.view)renderMgr(r.view);}
async function cutP(id){if(!confirm('Spieler wirklich entlassen?'))return;const r=await api('/api/fr/cut?pid='+id,'POST');if(r.result&&r.result.error)alert(r.result.error);if(r.view){lastView=r.view;closePlayer();renderMgr(r.view);}}
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
 const kU=(v.units||[]).find(u=>u.key==='K');
 h+='<div class="card"><div class="sec" style="margin-top:0">Anlagen &amp; Special Teams</div>'+
   up('stadium','Stadion','Einnahmen +'+v.stadium.income+'/Wo',v.stadium.level,v.stadium.cost,v.stadium.level>=5,'+1')+
   up('equipment','Trainings-Equipment','+'+v.equipment.exp_week+' EXP/Wo',v.equipment.level,v.equipment.cost,v.equipment.level>=5,'+1')+
   (kU?up('K','Kicker','Field Goals &amp; Extra-Punkte · '+kU.level+' OVR',kU.level,kU.cost,kU.level>=95,'+2'):'')+
   '<div class="note">Ein besserer Kicker trifft Field Goals aus größerer Distanz und Extra-Punkte sicherer. Stadion bringt Einnahmen, Equipment mehr Spieler-EXP.</div></div>';
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
async function simWeek(){const r=await api('/api/fr/sim_week','POST');if(r.result&&r.result.error){alert(r.result.error);return;}if(r.view)renderMgr(r.view);}
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
   '<div class="tvteam">'+teamLogo(AB(g),AC(g),'lg')+'<span class="nm">'+esc(g.away)+'</span></div>'+
   '<div class="tvpts" id="bc_as">0</div>'+
   '<div class="tvmid"><div class="qn" id="bc_q">Q1</div><div class="sub">läuft …</div></div>'+
   '<div class="tvpts" id="bc_hs">0</div>'+
   '<div class="tvteam r"><span class="nm">'+esc(g.home)+'</span>'+teamLogo(HB(g),HC(g),'lg')+'</div>'+
  '</div>'+
  '<div class="tvfield"><div class="ez" style="background:'+esc(AC(g))+'">'+esc(AB(g))+'</div>'+
   '<div class="turf" id="bc_turf">'+turf+'<div class="ball" id="bc_ball" style="left:50%"></div></div>'+
   '<div class="ez" style="background:'+esc(HC(g))+'">'+esc(HB(g))+'</div></div>'+
  '<div style="margin-top:10px"><button class="ghost" onclick="skipBroadcast()">Überspringen ▸</button></div>'+
  boxSection(g)+
  '<div class="commentary" id="bc_feed"></div></div>';
 document.body.appendChild(o);lockBody();
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
function closeBroadcast(){if(bcTimer){clearInterval(bcTimer);bcTimer=null;}bcGame=null;const o=$('overlay');if(o)o.remove();unlockBodyIfNone();}

/* ---------- Interaktiver Spielmodus (selbst Plays callen) ---------- */
let liveG=null, playBusy=false;
/* Spieluhr: 1 Min Echtzeit pro Viertel (4), 15 s zum Play-Callen */
let gameQ=1, gameClock=60, playClock=15, clockIv=null;
function fmtClock(s){s=Math.max(0,s);return Math.floor(s/60)+':'+(s%60<10?'0':'')+(s%60);}
function startClock(){if(!clockIv)clockIv=setInterval(clockTick,1000);}
function stopClock(){if(clockIv){clearInterval(clockIv);clockIv=null;}}
function updateClockUI(){const q=$('gq');if(q)q.textContent='Q'+gameQ;const c=$('clk');if(c)c.textContent=fmtClock(gameClock);
 const p=$('pclk');if(p){p.textContent='⏱ '+Math.max(0,playClock)+'s';p.className='pclock'+(playClock<=5?' urgent':'');}}
function clockTick(){
 if(!liveG||liveG.over||playBusy)return;             // pausiert bei Animation/Spielende
 playClock--; gameClock--;
 if(gameClock<=0){gameQ++; gameClock=60; if(gameQ>4){stopClock(); endGameByClock(); return;}}
 if(playClock<=0)autoPlay();                          // Zeit fürs Play-Call abgelaufen -> Auto-Call
 updateClockUI();
}
function autoPlay(){if(!liveG||playBusy)return;const o=liveG.options||[];if(!o.length)return;gamePlay(o[Math.floor(Math.random()*o.length)].key);}
async function endGameByClock(){const r=await api('/api/fr/game/end','POST');if(r&&r.error)return;if(r.view)renderMgr(r.view);if(r.result)showGameResult(r.result);}
async function startGame(){const r=await api('/api/fr/game/start','POST');if(r.error){alert(r.error);return;}openGame(r.game);}
async function resumeGame(){const r=await api('/api/fr/game/start','POST');if(r.error){alert(r.error);return;}openGame(r.game);}
function openGame(g){closeGame();liveG=g;gameQ=1;gameClock=60;playClock=15;const o=document.createElement('div');o.className='overlay';o.id='gameoverlay';
 o.innerHTML='<div class="modal" id="gamemodal"></div>';document.body.appendChild(o);lockBody();renderGame(g);if(!g.over)startClock();}
function gameTurf(g){let t='';[10,20,30,40,50,60,70,80,90].forEach(p=>{t+='<div class="yl" style="left:'+p+'%"></div>';
 const lab=(p===50?'50':(p<50?p:100-p));t+='<div class="yn" style="left:'+p+'%">'+lab+'</div><div class="yn b" style="left:'+p+'%">'+lab+'</div>';});
 return '<div class="turf">'+t+'<div class="ball" style="left:'+Math.max(1,Math.min(99,g.absx))+'%"></div></div>';}
function renderGame(g,play){
 if(!g.over)playClock=15;                                    // jeder neue Snap: Play-Clock zurücksetzen
 let h='<div class="modalhead"><h3><span class="livedot"></span> Dein Spiel</h3>'+
   '<button class="ghost" onclick="abortGame()">Verlassen</button></div>'+
   '<div class="tvscore">'+
     '<div class="tvteam">'+teamLogo(g.aabbr,g.acolor,'lg')+'<span class="nm">'+esc(g.away)+'</span></div>'+
     '<div class="tvpts">'+g['as']+'</div>'+
     '<div class="tvmid"><div class="qn" id="gq">Q'+gameQ+'</div><div class="sub clk" id="clk">'+fmtClock(gameClock)+'</div></div>'+
     '<div class="tvpts">'+g.hs+'</div>'+
     '<div class="tvteam r"><span class="nm">'+esc(g.home)+'</span>'+teamLogo(g.habbr,g.hcolor,'lg')+'</div>'+
   '</div>'+
   '<div class="tvfield"><div class="ez" style="background:'+esc(g.acolor)+'">'+esc(g.aabbr)+'</div>'+
     gameTurf(g)+'<div class="ez" style="background:'+esc(g.hcolor)+'">'+esc(g.habbr)+'</div></div>'+
   '<div class="dd"><span>'+g.down+'. &amp; '+g.dist+'</span><span class="mut">noch '+g.ytz+' Yd bis TD · Ball: '+esc(g.possession)+'</span></div>'+
   '<div class="fieldwrap" style="margin:10px 0"><svg id="gfield" viewBox="0 0 533 360" style="width:100%;height:auto;display:block"></svg></div>';
 if(play)h+='<div class="reco'+(play.scored?' win':'')+'"><span>'+esc(play.desc)+'</span><span class="mut">'+(play.yards>=0?'+':'')+play.yards+' Yd</span></div>';
 if(g.over){h+='<div class="posbanner off">Spiel vorbei — Endstand '+esc(g.away)+' '+g['as']+' : '+g.hs+' '+esc(g.home)+'</div>'+
   '<button onclick="finishGame()">Ergebnis werten &amp; Woche abschließen</button>';}
 else{const ban=g.awaiting==='pat'?'🏈 Touchdown! Extra-Punkt oder 2-Punkte-Conversion?':(g.user_offense?'Du am Ball — wähle dein Konzept:':'Verteidigung — wähle deine Coverage:');
   h+='<div class="posbanner '+(g.user_offense||g.awaiting==='pat'?'off':'def')+'">'+ban+'</div>'+
   '<div class="pclock'+(playClock<=5?' urgent':'')+'" id="pclk">⏱ '+playClock+'s</div>'+
   '<div class="optgrid">'+g.options.map(o=>'<button class="optbtn" '+(playBusy?'disabled':'')+' data-k="'+esc(o.key)+'" onclick="gamePlay(this.dataset.k)">'+esc(o.label)+'<span class="ty">'+esc(o.type)+'</span></button>').join('')+'</div>'+
   (playBusy?'<div class="note" style="margin-top:6px">Spielzug läuft … nächstes Play wählbar, sobald der Ball wieder liegt.</div>':'')+
   '<div style="margin-top:8px"><button class="ghost" onclick="simDrive()" '+(playBusy?'disabled':'')+'>Drive simulieren</button> <button class="ghost" onclick="simRest()" '+(playBusy?'disabled':'')+'>Spiel zu Ende simulieren</button></div>';}
 h+='<div class="commentary" style="margin-top:10px">'+g.log.map(p=>'<div class="cmt"><span class="q">Q'+p.q+'</span>'+pbadge(p.desc)+'<span class="t">'+esc(p.desc)+'</span></div>').join('')+'</div>';
 $('gamemodal').innerHTML=h;
 if(play&&play.concept)animateGamePlay(play);
 else if(play&&play.kind==='fg')animateFG(play);            // Field Goal / Extra-Punkt mit Kick-Animation
 else {playBusy=false; showFormation(g);}                   // 2PT/Wechsel: sofort wieder spielbar
}
function gameCols(g,userOff){const me=(lastView&&lastView.color)||'#16c784';const opp=g.user_is_home?g.acolor:g.hcolor;return userOff?{off:me,def:opp}:{off:opp,def:me};}
async function showFormation(g){const svg=$('gfield');if(!svg||!g||g.over)return;
 const concept=g.user_offense?((g.options[0]&&g.options[0].key)||'Inside Zone'):'Inside Zone';
 const coverage=g.user_offense?'Cover 2':((g.options[0]&&g.options[0].key)||'Cover 2');
 const d=await (await fetch('/api/sim/diagram?concept='+encodeURIComponent(concept)+'&coverage='+encodeURIComponent(coverage))).json();
 if(!d.error)renderField(svg,d,g.dist||10,gameCols(g,g.user_offense),g.ytz,true);}   // Vor-Snap-Aufstellung, Ball am aktuellen Spot
async function animateGamePlay(play){const svg=$('gfield');if(!svg||!play.concept)return;
 const d=await (await fetch('/api/sim/diagram?concept='+encodeURIComponent(play.concept)+'&coverage='+encodeURIComponent(play.coverage))).json();
 if(d.error)return; renderField(svg,d,play.dist0||10,liveG?gameCols(liveG,play.user_off):null,play.ytz0);  // Animation startet am Spot vor dem Snap
 const cc=liveG?gameCols(liveG,play.user_off).off:'#16c784';
 playAnim(svg,d,{kind:play.kind,yards:play.yards,td:play.td,celColor:cc},()=>{playBusy=false;if(liveG)renderGame(liveG);});}   // Ball liegt -> Aufstellung am neuen Spot, Buttons wieder frei
function _fgFig(x,y,c){return '<g transform="translate('+x+' '+y+')"><ellipse cx="0" cy="2" rx="7" ry="5" fill="'+c+'" stroke="#06140d" stroke-width="1.4"/><circle cx="0" cy="-4" r="3.6" fill="'+c+'" stroke="#06140d" stroke-width="1.4"/></g>';}
function _fgResult(svg,made){const g=el('g',{}),x=266,y=150;
 g.appendChild(el('rect',{x:x-72,y:y-19,width:144,height:34,rx:8,fill:'#0a0f0d',stroke:made?'#19e08f':'#ef5350','stroke-width':2}));
 const t=el('text',{x:x,y:y+5,'text-anchor':'middle','font-size':17,fill:made?'#19e08f':'#ef5350','font-weight':800});t.textContent=made?'GUT! +':'KEIN GUT';g.appendChild(t);svg.appendChild(g);}
function animateFG(play){const svg=$('gfield');if(!svg){playBusy=false;return;}const P=svg.id;if(_anim[P])cancelAnimationFrame(_anim[P]);
 const cols=liveG?gameCols(liveG,play.user_off):{off:'#16c784',def:'#ef5350'};
 const made=!!(play.good!=null?play.good:play.scored), isXP=/Extra/.test(play.desc||''), dist=play.fg_dist||0;
 const gx1=232,gx2=301,cby=86,postTop=22,stemY=106, snapX=266,losY=292,holdX=252,holdY=312,kickX0=234,kickY0=320;
 let s='<defs><linearGradient id="fgt_'+P+'" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0e4a2d"/><stop offset="1" stop-color="#0b3a22"/></linearGradient></defs>'+
  '<rect x="0" y="0" width="533" height="360" fill="url(#fgt_'+P+')"/>'+
  '<rect x="0" y="0" width="533" height="'+(cby+16)+'" fill="'+cols.def+'" opacity="0.18"/>'+
  '<line x1="0" y1="'+(cby+16)+'" x2="533" y2="'+(cby+16)+'" stroke="#ffffff" stroke-width="2" opacity="0.7"/>'+
  '<text x="266" y="44" text-anchor="middle" font-size="15" font-weight="800" fill="#cdeede" opacity="0.9">'+(isXP?'Extra-Punkt':(dist?dist+' Yard Field Goal':'Field Goal'))+'</text>'+
  '<line x1="'+gx1+'" y1="'+cby+'" x2="'+gx2+'" y2="'+cby+'" stroke="#ffd34d" stroke-width="4"/>'+
  '<line x1="'+gx1+'" y1="'+cby+'" x2="'+gx1+'" y2="'+postTop+'" stroke="#ffd34d" stroke-width="4"/>'+
  '<line x1="'+gx2+'" y1="'+cby+'" x2="'+gx2+'" y2="'+postTop+'" stroke="#ffd34d" stroke-width="4"/>'+
  '<line x1="266" y1="'+cby+'" x2="266" y2="'+stemY+'" stroke="#ffd34d" stroke-width="4"/>';
 for(let i=0;i<5;i++)s+=_fgFig(200+i*33,losY,cols.off);                     // O-Line
 s+=_fgFig(186,losY+7,cols.off)+_fgFig(346,losY+7,cols.off);               // Wings
 for(let i=0;i<4;i++)s+=_fgFig(214+i*32,losY-13,cols.def);                 // Rusher
 s+=_fgFig(250,138,cols.def)+_fgFig(holdX,holdY,cols.off);                 // Returner + Holder
 s+='<g id="'+P+'_fgk" transform="translate('+kickX0+' '+kickY0+')">'+_fgFig(0,0,cols.off)+'</g>';
 svg.innerHTML=s;
 const ball=el('ellipse',{id:P+'_pball',cx:snapX,cy:losY,rx:4,ry:2.5,fill:'#9a5a1e',stroke:'#3a1f08','stroke-width':1,opacity:1});svg.appendChild(ball);
 const kg=$(P+'_fgk');
 const endX=made?266:(Math.random()<0.5?gx1-28:gx2+28), shortMiss=!made&&Math.random()<0.34;
 const t0=performance.now();
 function frame(now){const e=(now-t0)/1000;
  if(kg){const t=Math.min(1,e/0.6);kg.setAttribute('transform','translate('+(kickX0+t*(holdX-kickX0-7))+' '+(kickY0+t*(holdY-kickY0-2))+')');}
  let bx=snapX,by=losY;
  if(e<0.32){const t=e/0.32;bx=snapX+(holdX-snapX)*t;by=losY+(holdY-losY)*t;}        // Snap
  else if(e<0.62){bx=holdX;by=holdY;}                                                 // Hold
  else{const t=Math.min(1,(e-0.62)/0.9);bx=holdX+(endX-holdX)*t;
   if(shortMiss){const ap=cby+40;by=holdY+(ap-holdY)*Math.min(1,t*1.7);if(t>0.58)by+=(t-0.58)*150;}
   else{by=holdY+((postTop-34)-holdY)*t-Math.sin(Math.PI*t)*22;}}
  ball.setAttribute('cx',bx);ball.setAttribute('cy',by);
  if(e<=1.9)_anim[P]=requestAnimationFrame(frame);
  else{ball.setAttribute('opacity',0);_fgResult(svg,made);setTimeout(()=>{playBusy=false;if(liveG)renderGame(liveG);},1100);}
 }
 _anim[P]=requestAnimationFrame(frame);
}
async function gamePlay(choice){if(playBusy)return;playBusy=true;const r=await api('/api/fr/game/play?choice='+encodeURIComponent(choice),'POST');if(r.error){playBusy=false;alert(r.error);return;}liveG=r.game;renderGame(r.game,r.play);}
async function finishGame(){const r=await api('/api/fr/game/finish','POST');if(r.error){alert(r.error);return;}if(r.view)renderMgr(r.view);showGameResult(r.result);}
async function simDrive(){if(playBusy)return;const r=await api('/api/fr/game/sim_drive','POST');if(r.error){alert(r.error);return;}
 if(r.result){if(r.view)renderMgr(r.view);showGameResult(r.result);}else renderGame(r.game);}
async function simRest(){if(playBusy)return;const r=await api('/api/fr/game/sim_rest','POST');if(r.error){alert(r.error);return;}if(r.view)renderMgr(r.view);showGameResult(r.result);}
let _resBox=null;
function showGameResult(res){closeGame();_resBox=res.box||[];const o=document.createElement('div');o.className='overlay';o.id='resultoverlay';
 o.addEventListener('click',e=>{if(e.target===o)closeResult();});
 const won=lastView&&res.winner===lastView.team_name;
 o.innerHTML='<div class="modal"><div class="modalhead"><h3>Endstand</h3><button class="ghost" onclick="closeResult()">Schließen</button></div>'+
  '<div class="reco '+(won?'win':'loss')+'"><span><b>'+esc(res.away)+'</b> '+res['as']+' : '+res.hs+' <b>'+esc(res.home)+'</b></span>'+
  '<span class="mut">'+(won?'Sieg':'Niederlage')+'</span></div>'+
  (_resBox.length?'<div style="margin-top:10px"><button class="ghost" onclick="toggleResBox()" id="resbtn">Statistik anzeigen</button></div><div id="resbox"></div>':'')+'</div>';
 document.body.appendChild(o);lockBody();}
function toggleResBox(){const b=$('resbox');if(!b)return;if(b.innerHTML){b.innerHTML='';$('resbtn').textContent='Statistik anzeigen';}
 else{b.innerHTML=boxSection({box:_resBox});$('resbtn').textContent='Statistik ausblenden';}}
function closeResult(){const o=$('resultoverlay');if(o)o.remove();unlockBodyIfNone();}
async function abortGame(){if(confirm('Spiel verlassen? Der Fortschritt geht verloren.')){await api('/api/fr/game/abort','POST');closeGame();loadMgr();}}
function closeGame(){stopClock();const o=$('gameoverlay');if(o)o.remove();liveG=null;playBusy=false;unlockBodyIfNone();}
async function upg(u){const r=await api('/api/fr/upgrade?unit='+u,'POST');if(r.result&&r.result.error)alert(r.result.error);if(r.view)renderMgr(r.view);}
async function setScheme(){const r=await api('/api/fr/scheme?off='+encodeURIComponent($('sc_off').value)+'&deff='+encodeURIComponent($('sc_def').value),'POST');if(r.view)renderMgr(r.view);}
async function trainWeek(kind){const r=await api('/api/fr/train_week?kind='+kind,'POST');if(r.result&&r.result.error)alert(r.result.error);if(r.view)renderMgr(r.view);}
async function nextWeek(){const r=await api('/api/fr/next_week','POST');if(r.error){alert(r.error);return;}if(r.view)renderMgr(r.view);}
/* ---------- Interaktives Tutorial (führt durch die Oberfläche) ---------- */
const TUT=[
 {tab:'dash',sel:'.tbanner',title:'Deine Franchise',text:'Hier oben siehst du dein Team, Bilanz, Budget, Skillpunkte und die Saisonwoche.'},
 {tab:'dash',sel:'.subnav',title:'Bereiche',text:'Über diese Reiter steuerst du alles: Dashboard, Kader & Training, Statistik, Transfermarkt und Verbesserungen.'},
 {tab:'dash',sel:'#goalcard',title:'Saison-Ziele',text:'Das Front-Office gibt dir Ziele vor. Erfüllst du sie, gibt es Budget-Belohnungen.'},
 {tab:'dash',sel:'.traingrid',title:'1× Training pro Woche',text:'Wähle eine Trainingskarte — z. B. Teamtraining, Einzeltraining oder eine Film-Session für einen Spielbonus.'},
 {tab:'dash',sel:'#gamecard',title:'Spiel & Woche',text:'Spiel selbst spielen oder simulieren. Erst danach schaltest du mit „Nächste Woche" weiter — die Woche endet nie von allein.'},
 {tab:'kader',sel:'.prow',title:'Spieler entwickeln',text:'Klicke einen Spieler an, um seine Attribute mit Skillpunkten zu steigern und ihn als Starter zu setzen.'},
 {tab:'transfer',sel:'.card',title:'College-Scouting & Transfermarkt',text:'Scoute College-Talente mit deinen Scouting-Punkten, um Können, Potenzial und Entwicklungs-Trait aufzudecken — dann draften. Darunter findest du fertige Free Agents. Jede Saison: Ruhestand + neuer Jahrgang.'},
 {tab:'stats',sel:'.card',title:'Statistik',text:'Saison- und Karrierewerte sowie Bestenlisten deines Teams.'},
 {tab:'build',sel:'.card',title:'Verbesserungen',text:'Investiere Budget in Trainerstab, Stadion (mehr Geld) und Equipment (mehr EXP). Viel Erfolg!'},
];
let _tutStep=0;
function openTutorial(s){_tutStep=s||0;tutShow();}
function tutShow(){const step=TUT[_tutStep];if(step.tab&&step.tab!==mgrTab)mgrGo(step.tab);
 // erst Bereich rendern lassen, Element ins Bild scrollen, DANN messen
 setTimeout(()=>{const el=step.sel?document.querySelector(step.sel):null;
   if(el)el.scrollIntoView({block:'center',behavior:'auto'});
   setTimeout(()=>tutPlace(el),120);},60);}
function tutPlace(el){const step=TUT[_tutStep],i=_tutStep,last=i===TUT.length-1;
 let host=$('tutspot');if(!host){host=document.createElement('div');host.id='tutspot';document.body.appendChild(host);lockBody();}
 let hole='',top=window.innerHeight/2-90;
 const r=el?el.getBoundingClientRect():null;
 if(r&&r.height&&r.bottom>0&&r.top<window.innerHeight){
   const t0=Math.max(4,r.top-6),h0=Math.min(window.innerHeight-8,r.bottom+6)-t0;
   hole='<div class="tuthole" style="top:'+t0+'px;left:'+Math.max(4,r.left-6)+'px;width:'+(r.width+12)+'px;height:'+h0+'px"></div>';
   top=(r.top<window.innerHeight*0.5)?(r.bottom+14):(r.top-210);
   top=Math.max(8,Math.min(top,window.innerHeight-210));
 }
 host.innerHTML=hole+'<div class="tuttip" style="top:'+top+'px"><div class="tutnum">Schritt '+(i+1)+' / '+TUT.length+'</div>'+
   '<h4>'+esc(step.title)+'</h4><p>'+esc(step.text)+'</p>'+
   '<div class="tutbtns"><button class="ghost" onclick="closeTutorial()">Überspringen</button><span>'+
   (i>0?'<button class="ghost" onclick="openTutorial('+(i-1)+')">Zurück</button> ':'')+
   '<button onclick="'+(last?'closeTutorial()':'openTutorial('+(i+1)+')')+'">'+(last?'Fertig':'Weiter')+'</button></span></div></div>';
}
async function closeTutorial(){const o=$('tutspot');if(o)o.remove();unlockBodyIfNone();await api('/api/fr/tutorial_done','POST');if(lastView)lastView.tutorial_seen=true;}
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

    @app.post("/api/fr/tutorial_done")
    def fr_tutorial_done():
        from gridiron import franchise as F
        st, err = _fr_load_or_404()
        if err:
            return err
        st["tutorial_seen"] = True
        F.save(cfg, st)
        return {"ok": True}

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

    @app.post("/api/fr/next_week")
    def fr_next_week():
        from gridiron import franchise as F
        st, err = _fr_load_or_404()
        if err:
            return err
        return F.next_week(cfg, st)

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

    @app.post("/api/fr/alloc_all")
    def fr_alloc_all():
        from gridiron import franchise as F
        st, err = _fr_load_or_404()
        if err:
            return err
        return {"result": F.alloc_auto_all(cfg, st), "view": F.view(st)}

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

    @app.post("/api/fr/train_week")
    def fr_train_week(kind: str):
        from gridiron import franchise as F
        st, err = _fr_load_or_404()
        if err:
            return err
        return {"result": F.do_training(cfg, st, kind), "view": F.view(st)}

    @app.post("/api/fr/sign")
    def fr_sign(pid: int):
        from gridiron import franchise as F
        st, err = _fr_load_or_404()
        if err:
            return err
        return {"result": F.sign_player(cfg, st, pid), "view": F.view(st)}

    @app.post("/api/fr/cut")
    def fr_cut(pid: int):
        from gridiron import franchise as F
        st, err = _fr_load_or_404()
        if err:
            return err
        return {"result": F.cut_player(cfg, st, pid), "view": F.view(st)}

    @app.post("/api/fr/scout")
    def fr_scout(pid: int):
        from gridiron import franchise as F
        st, err = _fr_load_or_404()
        if err:
            return err
        return {"result": F.scout_prospect(cfg, st, pid), "view": F.view(st)}

    @app.post("/api/fr/draft")
    def fr_draft(pid: int):
        from gridiron import franchise as F
        st, err = _fr_load_or_404()
        if err:
            return err
        return {"result": F.draft_prospect(cfg, st, pid), "view": F.view(st)}

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

    @app.post("/api/fr/game/end")
    def fr_game_end():
        from gridiron import franchise as F
        st, err = _fr_load_or_404()
        if err:
            return err
        return F.end_game(cfg, st)

    @app.post("/api/fr/game/sim_drive")
    def fr_game_sim_drive():
        from gridiron import franchise as F
        st, err = _fr_load_or_404()
        if err:
            return err
        return F.game_sim_drive(cfg, st)

    @app.post("/api/fr/game/sim_rest")
    def fr_game_sim_rest():
        from gridiron import franchise as F
        st, err = _fr_load_or_404()
        if err:
            return err
        return F.game_sim_rest(cfg, st)

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
