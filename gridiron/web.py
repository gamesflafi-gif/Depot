"""Web-Oberfläche & API für Gridiron.

Coach wählt ein Team (+ Saison) und bekommt sofort einen lesbaren
Scouting-Report (Tendenzen, Tells, Down&Distanz, Feldzone, Richtungen) plus
eine Live-Pass/Lauf-Vorhersage für eine konkrete Situation. Alles lokal.
"""
from __future__ import annotations

import logging
from dataclasses import asdict

from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse

from gridiron.config import Config, load_config
from gridiron.storage import GridironStore
from gridiron.tendencies import scout

log = logging.getLogger(__name__)

_BUILD = "v72-fixcam"         # sichtbarer Versions-Marker (Footer + X-Gridiron-Build), zum Prüfen welcher Stand live ist

_STYLE = """
 :root{--bg:#080c0b;--panel:#161f1c;--panel2:#212c28;--tile:#27332e;--fg:#eaf0ed;--mut:#94a49e;
   --line:#33403a;--acc:#16c784;--accsoft:#0f2a20;--warn:#e9b949;--bad:#ef5350}
 *{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
 html{overflow-x:hidden;-webkit-text-size-adjust:100%}
 button,a,.tab,.s,.optbtn,.worldzoom button,select{touch-action:manipulation}
 body{margin:0;background:var(--bg);color:var(--fg);-webkit-font-smoothing:antialiased;
   font:15px/1.5 ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
   width:100%;max-width:100%}
 img,svg,table,pre{max-width:100%}
 a{color:var(--acc);text-decoration:none}
 .top{background:#0d1411;border-bottom:1px solid var(--line);position:sticky;top:0;z-index:10}
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
 button{padding:11px 18px;border:0;border-radius:11px;background:linear-gradient(180deg,#1fd897,#12ac72);color:#02140c;
   font-weight:800;cursor:pointer;font-size:14.5px;letter-spacing:.01em;transition:filter .12s,transform .05s,box-shadow .12s;
   box-shadow:0 2px 0 rgba(6,40,27,.55),0 8px 18px -8px rgba(25,224,143,.6),inset 0 1px 0 rgba(255,255,255,.28)}
 button:hover{filter:brightness(1.05)} button:active{transform:translateY(1px);box-shadow:0 1px 0 rgba(6,40,27,.55),inset 0 1px 0 rgba(255,255,255,.2)}
 button[disabled]{opacity:.32;cursor:not-allowed;filter:saturate(.5);box-shadow:none}
 button.ghost{background:linear-gradient(180deg,#2a352f,#212c28);color:var(--fg);border:1px solid #46544e;box-shadow:0 1px 2px rgba(0,0,0,.35),inset 0 1px 0 rgba(255,255,255,.05)}
 button.ghost:hover{color:var(--acc);border-color:var(--acc);filter:none}
 .card{background:linear-gradient(180deg,#1a2420,#141d1a);border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin:14px 0;
   box-shadow:0 1px 2px rgba(0,0,0,.3),0 10px 30px -22px rgba(0,0,0,.8),inset 0 1px 0 rgba(255,255,255,.035)}
 .big{font-size:25px;font-weight:800;letter-spacing:-.01em}
 .row{display:flex;gap:24px;flex-wrap:wrap}
 .kgrid{display:grid;gap:9px;grid-template-columns:repeat(auto-fit,minmax(100px,1fr))}
 .kpi{background:linear-gradient(180deg,#2a3631,#212d28);border:1px solid var(--line);border-radius:12px;padding:9px 12px;
   display:flex;flex-direction:column;justify-content:center;min-height:58px;min-width:0;box-shadow:inset 0 1px 0 rgba(255,255,255,.05),0 1px 2px rgba(0,0,0,.3)}
 .kpi .l{font-size:9.5px;color:var(--mut);text-transform:uppercase;letter-spacing:.04em;font-weight:700;line-height:1.18}
 .kpi .v{font-size:20px;font-weight:800;font-variant-numeric:tabular-nums;margin-top:3px;line-height:1.04;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 .sec{display:flex;align-items:center;gap:8px;font-size:11.5px;color:var(--fg);text-transform:uppercase;letter-spacing:.08em;margin:20px 0 11px;font-weight:800}
 .sec::before{content:"";width:4px;height:15px;border-radius:2px;background:var(--acc);flex:none}
 /* Positions-Farben & OVR-Tiers (Game-Look) */
 .posb{display:inline-block;min-width:32px;text-align:center;font-weight:800;font-size:11px;padding:3px 6px;border-radius:6px;color:#06140d;letter-spacing:.02em;box-shadow:0 1px 2px rgba(0,0,0,.35),inset 0 1px 0 rgba(255,255,255,.18)}
 .p-QB{background:#f5a524}.p-RB{background:#16c784}.p-WR{background:#3b96ff;color:#fff}.p-OL{background:#b9923a}
 .p-DL{background:#ef5350;color:#fff}.p-LB{background:#9b6be3;color:#fff}.p-DB{background:#13b7c9;color:#04121f}.p-K{background:#e88c2a;color:#241200}
 .ovrb{font-weight:800;font-variant-numeric:tabular-nums;border-radius:8px;padding:5px 9px;min-width:38px;text-align:center;display:inline-block;font-size:15px;box-shadow:0 1px 3px rgba(0,0,0,.4),inset 0 1px 0 rgba(255,255,255,.15)}
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
 .pill{display:inline-block;background:linear-gradient(180deg,#27332e,#1f2a26);border:1px solid var(--line);color:var(--fg);font-weight:600;
   padding:5px 12px;border-radius:8px;font-size:13px;font-variant-numeric:tabular-nums;box-shadow:inset 0 1px 0 rgba(255,255,255,.04)}
 .mut{color:var(--mut);font-size:13.5px} .foot{color:var(--mut);font-size:12px;text-align:center;margin:34px 0 0;opacity:.85}
 code{background:var(--panel2);padding:1px 6px;border-radius:5px;font-size:13px;border:1px solid var(--line)}
 @media(max-width:560px){
  .topin{padding:11px 14px} .brand{font-size:16px;gap:10px} .nav a{margin-left:12px;font-size:12.5px}
  .wrap{padding:14px 12px 30px} .big{font-size:21px} .card{padding:14px}
  .controls{gap:10px}
  /* Tabs & Sub-Navigation: einzeilig, horizontal wischbar */
  .tabs{flex-wrap:nowrap;overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none;touch-action:pan-x}
  .tabs::-webkit-scrollbar{display:none} .tab{white-space:nowrap;padding:11px 13px}
  .subnav{flex-wrap:nowrap;overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none;touch-action:pan-x}
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
  /* Anlagen-Hub: Karte größer nutzen, Ausbau-Button bricht sauber um */
  .hubcard{padding:12px} .hubcard .note{font-size:12px;margin-bottom:4px} .complex{margin-top:8px}
  .facpanel{flex-wrap:wrap;gap:8px;padding:11px 12px} .facpanel>div:last-child{text-align:left;width:100%} .facpanel>div:last-child button{width:100%}
  .worldwrap{width:100vw} .worldview{height:46vh;min-height:240px} .expgrid{grid-template-columns:1fr!important}
  .meetgrid{grid-template-columns:1fr!important}   /* Mobile: Pakete untereinander (Quelltext-Reihenfolge sonst überschrieben) */
  .devnm{font-size:12px} .devst{display:none}
 }
"""

_STYLE2 = """
 .tabs{display:flex;gap:2px;flex-wrap:wrap;border-bottom:1px solid var(--line);margin:0 0 20px}
 .tab{padding:12px 16px;color:var(--mut);cursor:pointer;font-weight:700;font-size:14px;
   border-bottom:2.5px solid transparent;margin-bottom:-1px;transition:color .12s,border-color .12s}
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
 .tbl th.srt{cursor:pointer;white-space:nowrap;user-select:none} .tbl th.srt:hover{color:var(--fg)} .tbl th.srt.on{color:var(--acc)}
 .tbl tr.ltrow{cursor:pointer} .tbl tr.ltrow:hover td{background:rgba(255,255,255,.04)} .tbl tr.ltrow.me:hover td{background:var(--accsoft)}
 .tbl tr.ltrow.po td:first-child{box-shadow:inset 3px 0 0 var(--acc)}
 .tbl tr.ltdrow td{border-bottom:1px solid var(--line)} .ltdrow .scoutbox{margin:0;border-radius:0;border:0}
 .podot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--acc);margin-right:5px;vertical-align:middle;box-shadow:0 0 5px var(--acc)}
 .scroll{overflow-x:auto;touch-action:pan-x;-webkit-overflow-scrolling:touch;overscroll-behavior:contain} .note{color:var(--mut);font-size:13px;margin-top:8px}
 .reco{padding:11px 14px;background:linear-gradient(180deg,#222d28,#1c2622);border:1px solid var(--line);border-radius:10px;margin:7px 0;font-size:14px;
   display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;box-shadow:inset 0 1px 0 rgba(255,255,255,.03)}
 .reco>span:first-child{min-width:0}
 .reco b{font-weight:700} .reco.win{border-color:#1c5a40} .reco.loss{border-color:#5a2a20} .reco.flag{border-color:#e9b949;background:#1d1b11}
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
 .hubcard{background:linear-gradient(160deg,#16201c,var(--panel))}
 .hubgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-top:12px}
 .hubb{background:var(--tile);border:1px solid var(--line);border-radius:12px;padding:10px;display:flex;flex-direction:column;gap:7px;align-items:flex-start}
 .hubb .hbi{width:100%;height:62px;border-radius:9px;background:#0c130f;display:flex;align-items:center;justify-content:center;overflow:hidden}
 .hubb .hbn{font-weight:800;font-size:14px} .hubb .hbe{font-size:11.5px;color:var(--mut);flex:1}
 .hubb button{width:100%;margin-top:2px} .hblvl{font-size:13px;font-weight:800;color:var(--acc)}
 .hblv{display:inline-flex;gap:3px} .hblv i{width:10px;height:10px;border-radius:2px;background:#2c3a34} .hblv i.on{background:var(--acc)}
 @media(max-width:560px){.hubgrid{grid-template-columns:1fr 1fr}}
 .complex{width:100%;height:auto;display:block;border-radius:12px;border:1px solid var(--line);margin-top:12px;background:#0c130f;touch-action:manipulation}
 .facb{transition:opacity .12s} .facb:hover{opacity:.84} .facb.sel{filter:drop-shadow(0 0 7px var(--acc))}
 .tp{transform-box:fill-box;transform-origin:center}
 @keyframes drillA{0%,100%{transform:translate(0,0)}50%{transform:translate(38px,0)}}
 @keyframes drillB{0%,100%{transform:translate(0,0)}50%{transform:translate(0,-22px)}}
 @keyframes drillC{0%{transform:translate(-22px,8px)}50%{transform:translate(22px,-8px)}100%{transform:translate(-22px,8px)}}
 .cz{transform-box:fill-box;transform-origin:center}
 @keyframes walkx{0%{transform:translate(0,0)}50%{transform:translate(54px,27px)}100%{transform:translate(0,0)}}
 @keyframes walky{0%{transform:translate(0,0)}50%{transform:translate(-50px,25px)}100%{transform:translate(0,0)}}
 @keyframes flagw{0%,100%{transform:scaleX(1)}50%{transform:scaleX(.55)}}
 @keyframes glow{0%,100%{opacity:.10}50%{opacity:.28}}
 .flagw{transform-box:fill-box;transform-origin:left center}
 .facpanel{display:flex;align-items:center;gap:12px;background:var(--tile);border:1px solid var(--line);border-radius:11px;padding:12px 14px;margin-top:10px}
 .facpanel .fpn{font-weight:800;font-size:15px}
 /* Vereinswelt-Vorschau + Pop-up */
 .cityview{border:1px solid var(--line);border-radius:12px;overflow:hidden;margin-top:12px;background:#0c130f} .cityview .complex{margin-top:0;border:0;display:block}
 .citypreview{position:relative;cursor:pointer;border-radius:12px;overflow:hidden;border:1px solid var(--line);margin-top:12px;transition:border-color .15s}
 .citypreview:hover{border-color:var(--acc)} .citypreview .complex{margin-top:0;border:0;pointer-events:none}
 .cpbadge{position:absolute;left:50%;bottom:14px;transform:translateX(-50%);background:linear-gradient(180deg,rgba(16,30,22,.92),rgba(9,16,12,.92));border:1px solid rgba(25,224,143,.5);color:#eaf6ef;font-weight:800;font-size:13px;padding:9px 18px;border-radius:999px;box-shadow:0 8px 22px -8px rgba(0,0,0,.7),inset 0 1px 0 rgba(255,255,255,.1);pointer-events:none}
 .citypreview:hover .cpbadge{border-color:var(--acc)}
 .worldwrap{max-width:760px;width:96vw}
 .worldview{position:relative;height:54vh;min-height:300px;overflow:hidden;background:#0a120c;border:1px solid var(--line);border-radius:12px;margin-top:6px;touch-action:none;cursor:grab}
 .worldview:active{cursor:grabbing} .worldcanvas{position:absolute;top:0;left:0;width:100%;transform-origin:0 0;will-change:transform} .worldcanvas .complex{margin-top:0;border:0}
 .worldzoom{position:absolute;right:10px;bottom:10px;display:flex;gap:6px}
 .worldzoom button{width:42px;height:42px;padding:0;font-size:21px;font-weight:800;border-radius:50%;background:rgba(11,20,16,.72);color:#eaf6ef;border:1px solid rgba(255,255,255,.16);box-shadow:0 6px 16px -4px rgba(0,0,0,.6),inset 0 1px 0 rgba(255,255,255,.12)}
 .worldzoom button:hover{border-color:var(--acc);color:var(--acc);filter:none}
 .worldhint{position:absolute;left:10px;bottom:12px;font-size:11px;color:#9fb0a8;background:rgba(8,16,11,.6);padding:4px 9px;border-radius:8px;pointer-events:none}
 .expgrid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
 .exprow{display:flex;align-items:center;gap:10px;padding:10px 12px;border:1px solid var(--line);border-radius:10px;background:var(--tile)}
 .exprow.on{border-color:#1c5a40;background:#10231a} .expic{font-size:16px} .expnm{display:flex;flex-direction:column} .expnm small{color:var(--mut);font-size:11.5px}
 .devlist{display:flex;flex-direction:column;gap:2px}
 .devrow{display:flex;align-items:center;gap:9px;padding:8px 10px;border:1px solid var(--line);border-radius:10px;background:var(--tile)}
 .devrow.me{border-color:#1c5a40;background:#10231a} .devrk{width:18px;text-align:center;font-weight:800;color:var(--mut)}
 .devnm{flex:1;display:flex;flex-direction:column;gap:4px;font-weight:600;font-size:13px} .devbarwrap{height:6px;border-radius:3px;background:#0c1410;overflow:hidden} .devbar{display:block;height:100%}
 .devov{font-weight:800;font-size:15px;text-align:center} .devov small{display:block;font-size:9px;color:var(--mut);font-weight:600}
 .devst{color:#e9b949;font-size:12px;letter-spacing:1px} .ghost.mini{padding:6px 10px;font-size:12px}
 .devdet:empty{display:none} .scoutbox{padding:10px 12px;margin:2px 0 6px;border:1px dashed var(--line);border-radius:9px;background:#0e150f;font-size:13px}
 .schd{display:flex;align-items:center;justify-content:space-between;gap:8px} .schd b{font-size:13.5px}
 .scbadge{font-size:10.5px;font-weight:800;color:#04140c;background:linear-gradient(180deg,#f0c659,#e2a832);border-radius:6px;padding:2px 8px;box-shadow:inset 0 1px 0 rgba(255,255,255,.25)}
 .scrow{display:flex;align-items:center;gap:9px;margin:5px 0} .scl{width:64px;font-size:12px;color:var(--mut)}
 .scbar{position:relative;flex:1;height:8px;border-radius:5px;background:var(--bg);border:1px solid var(--line);overflow:hidden} .scfill{position:absolute;inset:0 auto 0 0}
 .scv{width:64px;text-align:right;font-weight:800;font-variant-numeric:tabular-nums} .scv small{color:var(--mut);font-weight:600;font-size:10px}
 .sctip{margin-top:7px;padding:7px 9px;border-radius:7px;background:var(--accsoft);border:1px solid #1c5a40;color:#bdeed6;font-size:12.5px;font-weight:600}
 .evtcard{border-color:#5a4f20;background:#1d1b11}
 /* Wochen-Meeting */
 .meetcard{border-color:#3a4a6a;background:linear-gradient(180deg,#161f2e,#121826)}
 .meetwrap{max-width:720px}
 .meetgrid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:12px}
 .meetopt{display:flex;flex-direction:column;gap:8px;text-align:left;padding:14px 13px;border:1px solid var(--line);border-radius:13px;background:linear-gradient(180deg,#1a2420,#141d1a);color:var(--fg);cursor:pointer;font:inherit;transition:border-color .12s,transform .05s,box-shadow .12s}
 .meetopt:hover{border-color:var(--acc);transform:translateY(-2px);box-shadow:0 10px 24px -12px rgba(0,0,0,.7)}
 .meetopt:active{transform:translateY(0)}
 .moh{font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.08em;color:var(--mut)}
 .mobuff,.modeb{display:flex;gap:8px;align-items:flex-start;font-size:13px;font-weight:600;line-height:1.35}
 .mobuff{color:#bdeed6} .modeb{color:#eab8b2}
 .mosign{flex:none;width:20px;height:20px;border-radius:6px;display:inline-flex;align-items:center;justify-content:center;font-weight:800;font-size:13px;margin-top:1px}
 .mosign.good{background:var(--accsoft);color:#5fe6ac;border:1px solid #1c5a40} .mosign.bad{background:#2c1414;color:#ef8e84;border:1px solid #5a2a20}
 .mopick{margin-top:auto;text-align:center;font-weight:800;font-size:12.5px;color:#04140c;background:linear-gradient(180deg,#1fd897,#12ac72);border-radius:8px;padding:8px;box-shadow:inset 0 1px 0 rgba(255,255,255,.25)}
 .awrow{display:flex;align-items:center;gap:12px;padding:10px 12px;border:1px solid var(--line);border-radius:11px;margin:8px 0;background:var(--tile)}
 .awlabel{font-size:11px;font-weight:800;color:var(--warn);text-transform:uppercase;letter-spacing:.05em}
 .awname{font-weight:700;margin:2px 0;display:flex;align-items:center;gap:7px}
 .evtgrp{margin:11px 0} .evtlab{font-size:11px;font-weight:800;color:var(--mut);text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px}
 .evtopts{display:grid;grid-template-columns:1fr 1fr;gap:8px}
 .evtopt{padding:10px 12px;border-radius:9px;border:1px solid var(--line);background:var(--tile);color:var(--fg);text-align:left;font-weight:600;cursor:pointer;font-size:12.5px;transition:border-color .12s,box-shadow .12s}
 .evtopt.buff{border-left:3px solid var(--acc)} .evtopt.debuff{border-left:3px solid var(--bad)}
 .evtopt.on{border-color:var(--acc);box-shadow:0 0 0 2px var(--accsoft)}
 .evtopt.debuff.on{border-color:var(--bad);box-shadow:0 0 0 2px #3a1d1d}
 .tag{display:inline-block;background:linear-gradient(180deg,#f0c659,#e2a832);color:#1a1400;font-weight:800;font-size:11px;
   padding:3px 9px;border-radius:6px;letter-spacing:.04em;box-shadow:0 1px 2px rgba(0,0,0,.3),inset 0 1px 0 rgba(255,255,255,.25)}
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
 .fig.sad{animation:sadshake 2.4s ease-in-out infinite}@keyframes sadshake{0%,100%{transform:rotate(-7deg)}50%{transform:rotate(7deg)}}
 .runin{animation:runin 1.7s ease-out both}@keyframes runin{from{transform:translate(var(--rx),var(--ry))}to{transform:translate(0,0)}}
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
 /* Vorspiel-Intro: Teams, Münzwurf, Kickoff */
 .introwrap{min-height:320px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px;padding:26px 6px;text-align:center;position:relative;animation:fade .3s ease}
 .introskip{position:absolute;top:6px;right:6px;padding:5px 10px;font-size:12px}
 .vsrow{display:flex;align-items:stretch;gap:12px;width:100%;justify-content:center}
 .vsteam{flex:1;max-width:210px;display:flex;flex-direction:column;align-items:center;gap:9px;background:var(--panel2);border:1px solid var(--line);border-radius:13px;padding:16px 10px}
 .vsteam .tn{font-weight:800;font-size:15px} .vsmid{display:flex;align-items:center;font-weight:800;font-size:24px;color:var(--mut)}
 .caps{display:flex;gap:7px;justify-content:center;flex-wrap:wrap} .capw{display:flex;flex-direction:column;align-items:center;gap:3px}
 .capn{font-size:10px;color:var(--mut);font-weight:700;max-width:50px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
 .coinwrap{perspective:600px;margin:10px auto 6px;width:100px;height:100px}
 .coinflip{position:relative;width:100px;height:100px;transform-style:preserve-3d;transform:rotateY(0deg)}
 .coinflip.toss{animation:cointumble .9s linear infinite}
 @keyframes cointumble{from{transform:rotateY(0deg)}to{transform:rotateY(360deg)}}
 .cface{position:absolute;inset:0;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:24px;letter-spacing:.04em;color:#3a2a05;backface-visibility:hidden;-webkit-backface-visibility:hidden;background:radial-gradient(circle at 36% 30%,#fceaa0,#e8c45f 45%,#c89a30);border:4px solid #b5862a;box-shadow:0 10px 24px rgba(0,0,0,.5),inset 0 0 0 5px rgba(255,255,255,.15)}
 .cface .cab{background:var(--c);color:#fff;border-radius:9px;padding:5px 9px;box-shadow:0 1px 3px rgba(0,0,0,.4)}
 .cface.cback{transform:rotateY(180deg)}
 .introbig{font-size:22px;font-weight:800} .introsub{color:var(--mut);font-size:14px}
 .kostrip{position:relative;width:100%;max-width:460px;height:30px;border-radius:8px;background:linear-gradient(90deg,#0e4a2d,#1d7a48);border:1px solid #06140d;overflow:hidden}
 .koball{position:absolute;top:50%;transform:translate(-50%,-50%);width:16px;height:16px;border-radius:50%;border:2px solid #fff;transition:left 1s cubic-bezier(.2,.7,.3,1)}
 .tvscore{display:grid;grid-template-columns:1fr auto auto auto 1fr;align-items:center;gap:12px;
   background:radial-gradient(130% 130% at 50% -15%,#19271f,#0a0f0d);border:1px solid var(--line);border-radius:13px;padding:14px 16px;box-shadow:0 8px 22px -12px rgba(0,0,0,.75),inset 0 1px 0 rgba(255,255,255,.05)}
 .tvteam{display:flex;align-items:center;gap:10px}.tvteam.r{justify-content:flex-end}
 .tvteam .ab{font-weight:800;font-size:13px;color:#fff;background:var(--tc);padding:6px 10px;border-radius:7px;letter-spacing:.05em}
 .tvteam .nm{font-weight:700;font-size:15px}
 .tvpts{font-size:34px;font-weight:800;font-variant-numeric:tabular-nums;min-width:50px;text-align:center;text-shadow:0 2px 10px rgba(0,0,0,.55);letter-spacing:-.02em}
 .tvmid{text-align:center;min-width:60px}.tvmid .qn{font-weight:800;font-size:16px}.tvmid .sub{color:var(--mut);font-size:11px}
 .tvmid .clk{font-variant-numeric:tabular-nums;font-weight:700;font-size:13px;color:#cdeede}
 .tvmid .clk.run{color:#16c784}
 .toline{display:flex;justify-content:center;gap:10px;margin-top:3px}
 .toline .tol,.toline .tor{display:inline-flex;gap:2px}
 .todot{width:9px;height:3px;border-radius:2px;background:#16c784;display:inline-block}
 .todot.off{background:#3a463f}
 .optbtn.to{border-color:#d8a23a;background:#2a2516}
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
 .commentary{max-height:230px;overflow-y:auto;margin-top:10px;border:1px solid var(--line);border-radius:9px;touch-action:pan-y;overscroll-behavior:contain;-webkit-overflow-scrolling:touch}
 .cmt{padding:8px 11px;border-bottom:1px solid var(--line);font-size:13.5px;display:flex;gap:10px;align-items:center}
 .cmt:last-child{border-bottom:0}.cmt .q{color:var(--mut);min-width:26px;font-size:11px;font-variant-numeric:tabular-nums}
 .cmt.big{background:var(--accsoft)}
 .pbadge{font-size:10px;font-weight:800;padding:2px 7px;border-radius:5px;min-width:30px;text-align:center;flex:none}
 .pb-td{background:#16c784;color:#04140c}.pb-fg{background:#5fa8ff;color:#04121f}
 .pb-fd{background:#2c3a34;color:#d6efe4}.pb-to{background:#ef5350;color:#240606}.pb-pl{background:#1a221e;color:var(--mut)}
 .pb-fl{background:#e9b949;color:#241c00}
 .obar{display:flex;height:26px;border-radius:7px;overflow:hidden;border:1px solid var(--line);margin-top:2px}
 .oseg{display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:800;color:#06140d;min-width:0}
 .o-ok{background:#16c784}.o-ok2{background:#0e9f6a;color:#eafff5}.o-mid{background:#3a4a44;color:#d6efe4}
 .o-warn{background:#e9b949}.o-bad{background:#ef5350;color:#fff}
 html.noscroll,body.noscroll{overflow:hidden}
 .overlay{position:fixed;inset:0;background:rgba(4,8,6,.84);display:flex;align-items:center;justify-content:center;z-index:50;padding:16px;overscroll-behavior:none;-webkit-overflow-scrolling:touch}
 .modal{background:var(--panel);border:1px solid var(--line);border-radius:14px;max-width:660px;width:100%;max-height:92vh;overflow-y:auto;overflow-x:hidden;padding:18px 20px;touch-action:pan-y;overscroll-behavior:contain;-webkit-overflow-scrolling:touch}
 .modal h3{margin:0;font-size:16px;display:flex;align-items:center;gap:8px}
 .livedot{width:8px;height:8px;border-radius:50%;background:var(--bad);animation:pulse 1s infinite}
 .modalhead{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}
 /* Interaktiver Spielmodus */
 .dd{display:flex;justify-content:space-between;align-items:center;background:#0a0f0d;border:1px solid var(--line);border-radius:9px;padding:10px 14px;margin:10px 0;font-weight:700;font-variant-numeric:tabular-nums}
 .posbanner{padding:11px 14px;border-radius:10px;margin:10px 0;font-weight:800;font-size:14px;border:1px solid transparent;box-shadow:inset 0 1px 0 rgba(255,255,255,.05)}
 .posbanner.off{background:linear-gradient(180deg,#123420,#0d2418);color:#5fe6ac;border-color:#1c5a40}.posbanner.def{background:linear-gradient(180deg,#33220f,#241809);color:#eab483;border-color:#5a3a1c}
 .optgrid{display:grid;gap:8px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));margin:6px 0 4px}
 .optbtn{padding:11px 13px;border:1px solid #46544e;background:var(--tile);color:var(--fg);border-radius:9px;cursor:pointer;text-align:left;font-weight:700;transition:border-color .12s,background .12s;box-shadow:0 1px 2px rgba(0,0,0,.3)}
 .optbtn:hover{border-color:var(--acc);background:#2d3a34} .optbtn .ty{display:block;font-size:11px;color:var(--mut);font-weight:500;margin-top:1px}
 /* Obere Aktionsleiste: Field Goal / Punt (nur 4. Versuch) + Auszeit klein */
 .topacts{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:9px}
 .optbtn.kick{flex:1 1 130px;text-align:center;font-weight:800;border-color:#d8a23a;background:#2a2516;color:#ffd98a}
 .optbtn.kick:hover{border-color:#ffd34d;background:#352d18}
 .optbtn.to.sm{margin-left:auto;flex:0 0 auto;padding:7px 11px;font-size:12px;font-weight:700;text-align:center;border-color:#46544e;background:var(--tile);color:#cdeede}
 .optbtn.philly{border-color:#6f8;background:#16321f}
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
 .pfa{flex:none;line-height:0} .ptr{border-radius:8px;display:block}
 .prow .pname{flex:1;font-weight:600} .ptbadge{background:var(--acc);color:#04140c;font-weight:800;font-size:12px;padding:3px 9px;border-radius:7px}
 /* Depth Chart */
 .dcgrphd{font-size:11.5px;font-weight:800;text-transform:uppercase;letter-spacing:.06em;color:var(--mut);margin:14px 0 4px}
 .dcpos{display:flex;gap:10px;align-items:flex-start;margin:7px 0;flex-wrap:wrap}
 .dchead{flex:none;width:38px;padding-top:8px} .dclist{flex:1;min-width:200px;display:flex;flex-direction:column;gap:5px}
 .dcrow{display:flex;align-items:center;gap:9px;padding:7px 10px;border:1px solid var(--line);border-radius:8px;background:var(--tile);cursor:pointer;transition:border-color .12s}
 .dcrow:hover{border-color:var(--acc)} .dcrow.st{background:linear-gradient(180deg,#13301f,#0f2418);border-color:#1c5a40}
 .dcrow.hurt{opacity:.7} .dcslot{width:24px;text-align:center;font-weight:800;font-size:11px;color:var(--mut)} .dcrow.st .dcslot{color:var(--acc)} .dcn{flex:1;font-weight:600;font-size:13.5px}
 /* Gefahrenbereich */
 details.danger{margin:18px 0 4px;border:1px solid var(--line);border-radius:11px;background:var(--panel2);overflow:hidden}
 details.danger>summary{cursor:pointer;padding:12px 15px;font-weight:700;color:var(--mut);list-style:none;font-size:13.5px} details.danger>summary::-webkit-details-marker{display:none}
 details.danger[open]>summary{border-bottom:1px solid var(--line);color:var(--fg)} .dangerin{padding:14px 15px}
 .danger-btn{border-color:#5a2a20 !important;color:#ef8e84 !important} .danger-btn:hover{border-color:var(--bad) !important;color:var(--bad) !important}
 .card.empty{color:var(--mut);font-size:13.5px;text-align:center;border-style:dashed;background:transparent}
 /* Draft Big Board */
 .needrow{display:flex;gap:8px;flex-wrap:wrap;margin-top:4px} .needtag{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:700;color:var(--mut);background:var(--tile);border:1px solid var(--line);border-radius:8px;padding:5px 10px}
 .prow.prospect{flex-wrap:nowrap} .bbrank{width:22px;text-align:center;font-weight:800;color:var(--mut);font-variant-numeric:tabular-nums;flex:none}
 .tag.tg-need{background:linear-gradient(180deg,#5fa8ff,#3b82e0);color:#04121f}
 .pddet:empty{display:none} .pddet{margin:-2px 0 8px}
 .pddwrap{display:flex;gap:14px;align-items:center;flex-wrap:wrap} .radmini{flex:none;width:120px} .radmini svg{width:120px;height:120px}
 .pcols{display:flex;gap:18px;flex-wrap:wrap;align-items:center;margin-top:12px}
 .radarwrap{flex:none} .attrs{flex:1;min-width:240px}
 .arow{display:flex;align-items:center;gap:10px;margin:7px 0}
 .arow .alab{width:96px;font-size:13px;color:var(--mut)}
 .arow .abar{position:relative;flex:1;height:9px;background:var(--bg);border:1px solid var(--line);border-radius:5px;overflow:hidden}
 .arow .afill{position:absolute;inset:0 auto 0 0;background:var(--acc)}
 .arow .acap{position:absolute;top:-2px;bottom:-2px;width:2px;background:#dfe7e3;opacity:.8}
 .arow .aval{width:26px;text-align:right;font-weight:700;font-variant-numeric:tabular-nums}
 .arow button{padding:4px 11px;border-radius:7px;font-size:15px;line-height:1}
 .arow .aavg{position:absolute;top:0;bottom:0;width:2px;background:#7d93b5;opacity:.9}
 .arow .alab.strong{color:var(--acc)} .arow .aval small{font-size:9.5px;color:var(--mut);margin-left:3px;font-weight:600}
 .chip{padding:6px 12px;border-radius:999px;border:1px solid var(--line);background:linear-gradient(180deg,#27332e,#1f2a26);color:var(--mut);font-weight:700;font-size:12.5px;cursor:pointer;transition:color .12s,border-color .12s,background .12s}
 .chip:hover{color:var(--fg)} .chip.on{background:var(--acc);color:#04140c;border-color:var(--acc);box-shadow:0 1px 6px rgba(22,199,132,.35)} .chip.sm{padding:5px 11px;font-size:12px}
 .kbar{padding:11px 14px} .kbarrow{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin:3px 0}
 .kbl{font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.06em;font-weight:700;min-width:62px}
 .stepsel{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin:4px 0 12px}
 .tag.tg-start{background:linear-gradient(180deg,#1fd897,#12ac72);color:#04140c}
 .tag.tg-inj{background:#3a1d1d;color:#ff8a8a;box-shadow:none}
 .ctraits{margin-top:8px} .ctrait{display:flex;align-items:center;gap:10px;margin:5px 0;font-size:13px}
 .ctrait>span:first-child{width:130px;color:var(--mut)}
 .ctrait .abar{flex:1} .ctrait .aval{width:26px;text-align:right;font-weight:700}
 .traingrid{display:grid;gap:9px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}
 .traincard{display:flex;flex-direction:column;align-items:flex-start;gap:4px;text-align:left;padding:13px;
   border:1px solid var(--line);border-radius:11px;background:var(--panel2);color:var(--fg);cursor:pointer;font:inherit;transition:border-color .12s,transform .04s}
 .traincard:hover{border-color:var(--acc)} .traincard:active{transform:translateY(1px)}
 .traincard .ti{color:var(--acc)} .traincard b{font-size:14px} .traincard .td{font-size:11.5px;color:var(--mut);font-weight:400}
 .traincard .texp{font-size:11px;font-weight:800;color:var(--acc);background:var(--accsoft);border:1px solid #1c5a40;border-radius:6px;padding:2px 7px;margin-top:2px}
 /* Matchup-Analyse */
 .matchup .mvs{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:10px;margin:4px 0 12px}
 .mteam{display:flex;flex-direction:column;align-items:flex-start;gap:4px} .mteam.r{align-items:flex-end;text-align:right} .mteam b{font-size:14px}
 .crest.sm{width:34px;height:34px;border-radius:9px;font-size:12px}
 .mvsmid{text-align:center;display:flex;flex-direction:column;align-items:center;gap:1px} .mvsmid .mut{font-size:10.5px}
 .wpbig{font-size:26px;font-weight:800;font-variant-numeric:tabular-nums;color:var(--acc);text-shadow:0 2px 8px rgba(0,0,0,.4);line-height:1}
 .vsrow{display:flex;align-items:center;gap:10px;margin:7px 0}
 .vsl{flex:1;font-size:12.5px;color:var(--mut)} .vsbar{position:relative;width:88px;height:8px;border-radius:5px;background:#3a2420;overflow:hidden;flex:none}
 .vsmine{position:absolute;inset:0 auto 0 0;background:var(--acc)} .vsv{width:54px;text-align:right;font-weight:800;font-variant-numeric:tabular-nums} .vsv small{color:var(--mut);font-weight:600}
 /* Form-Verlauf */
 .formrow{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px}
 .formchips{display:inline-flex;gap:4px} .formchip{width:22px;height:22px;border-radius:6px;display:inline-flex;align-items:center;justify-content:center;font-weight:800;font-size:11px;color:#04140c}
 .formchip.w{background:linear-gradient(180deg,#1fd897,#12ac72)} .formchip.l{background:#ef5350;color:#240606}
 .spark{display:block;background:#0c130f;border:1px solid var(--line);border-radius:9px;padding:6px}
 #tutspot{position:fixed;inset:0;z-index:60;pointer-events:none}
 .tuthole{position:fixed;border-radius:10px;box-shadow:0 0 0 9999px rgba(0,0,0,.74);border:2px solid var(--acc);transition:all .22s ease;pointer-events:none}
 .tuttip{position:fixed;left:50%;transform:translateX(-50%);max-width:380px;width:calc(100% - 28px);pointer-events:auto;
   background:var(--panel);border:1px solid var(--acc);border-radius:13px;padding:16px 18px;box-shadow:0 10px 34px rgba(0,0,0,.55)}
 .tuttip h4{margin:3px 0 6px;font-size:16px} .tuttip p{margin:0;color:var(--mut);line-height:1.55;font-size:14px}
 .tutnum{font-size:11px;color:var(--acc);font-weight:800;letter-spacing:.04em}
 .tutbtns{display:flex;justify-content:space-between;align-items:center;margin-top:14px;gap:8px}
"""

_PAGE = """<!doctype html><html lang="de"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Cache-Control" content="no-store, no-cache, must-revalidate"><meta http-equiv="Pragma" content="no-cache"><meta http-equiv="Expires" content="0">
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

 <div class="foot">Simulation = echte Liga-Basisraten × kalibrierte Football-Matchup-Logik. Wahrscheinlichkeiten, keine Garantie. · Build """ + _BUILD + """</div>
</div>
<script>
const $=id=>document.getElementById(id);
function esc(s){const d=document.createElement('div');d.textContent=(s==null?'':s);return d.innerHTML;}
function lockBody(){document.documentElement.classList.add('noscroll');document.body.classList.add('noscroll');}
function _releaseBody(){document.documentElement.classList.remove('noscroll');document.body.classList.remove('noscroll');document.body.style.top='';}
function unlockBodyIfNone(){if(!document.querySelector('.overlay')&&!$('tutspot'))_releaseBody();}   // nur sperren solange wirklich ein Overlay offen ist
const pct=x=>Math.round(x*100)+'%';
const sgn=x=>(x>=0?'+':'')+x.toFixed(2);

function closeAllOverlays(){['tutspot','gameoverlay','overlay','resultoverlay','playeroverlay','awoverlay','worldoverlay','meetingoverlay'].forEach(id=>{const o=$(id);if(o)o.remove();});
 stopClock();liveG=null;playBusy=false;_releaseBody();}   // nichts darf den Bildschirm blockieren
function tab(s){closeAllOverlays();                                                     // beim Tab-Wechsel offene Overlays/Sperren lösen
 document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('on',t.dataset.s===s));
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
function _hash(s){s=''+s;let h=2166136261;for(let i=0;i<s.length;i++){h^=s.charCodeAt(i);h=Math.imul(h,16777619);}return h>>>0;}
function portrait(p,sz,teamColor){sz=sz||38;const h=_hash((p.id!=null?p.id:0)+'_'+(p.name||''));
 const id='pt'+h.toString(36)+'_'+sz;
 const SK=[['#f6d3ad','#e3b98e'],['#ecbf94','#d3a072'],['#d3a06e','#b98453'],['#b07a48','#925d32'],['#8a5a32','#6e4424'],['#5f3c22','#472b17']][h%6];
 const skin=SK[0],sh=SK[1];
 const hairC=['#1a130d','#2e1d12','#5b3a1e','#0b0b0b','#3a3a3a','#caa24a','#7a4a22'][(h>>>4)%7];
 const tc=teamColor||'#3a4750';
 const bg0=teamColor?'#1c2823':['#1d2a40','#243038','#291f3e','#1b3329'][(h>>>7)%4];
 const hstyle=(h>>>10)%5, beardT=(h>>>13)%5, eyeblack=((h>>>17)%3===0);
 const W=sz,Hh=Math.round(sz*1.08);
 let s='<svg class="ptr" viewBox="0 0 40 44" width="'+W+'" height="'+Hh+'" preserveAspectRatio="xMidYMid meet">';
 s+='<defs><radialGradient id="'+id+'" cx="0.5" cy="0.3" r="0.9"><stop offset="0" stop-color="'+bg0+'"/><stop offset="1" stop-color="#0c130f"/></radialGradient></defs>';
 s+='<rect width="40" height="44" rx="10" fill="url(#'+id+')"/>';
 // Trikot/Schultern + Kragen
 s+='<path d="M3 44 Q4 32 14 29 L26 29 Q36 32 37 44 Z" fill="'+tc+'"/>';
 s+='<path d="M3 44 Q4 32 14 29 L20 33 L9 40 Z" fill="#000" opacity=".12"/>';
 s+='<path d="M15.5 29.5 L20 34 L24.5 29.5 L23 28 L17 28 Z" fill="#ffffff" opacity=".88"/>';
 // Hals mit Schatten
 s+='<path d="M16 24 h8 v6 q-4 3 -8 0 Z" fill="'+skin+'"/><path d="M16 28 q4 3 8 0 v1.6 q-4 3 -8 0 Z" fill="'+sh+'" opacity=".7"/>';
 // Kopf + Wangenschatten + Ohren
 s+='<path d="M11 18 Q11 8.5 20 8.5 Q29 8.5 29 18 Q29 25.6 24 28 Q20 29.7 16 28 Q11 25.6 11 18 Z" fill="'+skin+'"/>';
 s+='<path d="M20 8.5 Q29 8.5 29 18 Q29 25.6 24 28 L22.4 27.1 Q26 24.2 26 17.4 Q26 11.2 20 10.6 Z" fill="'+sh+'" opacity=".4"/>';
 s+='<circle cx="11" cy="19.5" r="1.9" fill="'+skin+'"/><circle cx="29" cy="19.5" r="1.9" fill="'+sh+'"/>';
 // Haar (5 Stile)
 if(hstyle===0)s+='<path d="M10.5 17 Q10 6 20 6 Q30 6 29.5 17 Q26 9.5 20 9.5 Q14 9.5 10.5 17 Z" fill="'+hairC+'"/>';
 else if(hstyle===1)s+='<path d="M10.8 16 Q11 7 20 7 Q29 7 29.2 16 L29.2 13 Q20 9.5 10.8 13 Z" fill="'+hairC+'"/>';
 else if(hstyle===2)s+='<path d="M12 13.2 Q13 7.6 20 7.6 Q27 7.6 28 13.2 Q20 10.9 12 13.2 Z" fill="'+hairC+'"/>';
 else if(hstyle===3)s+='<ellipse cx="20" cy="11" rx="11" ry="8.6" fill="'+hairC+'"/>';
 else s+='<path d="M10.5 16 Q10 6.5 20 6.5 Q30 6.5 29.5 16 L29.5 12 Q20 9 10.5 12 Z" fill="'+hairC+'"/><rect x="9.6" y="12" width="20.8" height="3" rx="1.5" fill="#e7e7e7" opacity=".85"/>';
 // Brauen + Augen
 s+='<path d="M14.4 16.5 Q16.4 15.5 18.3 16.4" stroke="'+hairC+'" stroke-width="1.2" fill="none" stroke-linecap="round"/><path d="M21.7 16.4 Q23.6 15.5 25.6 16.5" stroke="'+hairC+'" stroke-width="1.2" fill="none" stroke-linecap="round"/>';
 s+='<ellipse cx="16.6" cy="19" rx="1.7" ry="1.5" fill="#fbfbfb"/><ellipse cx="23.4" cy="19" rx="1.7" ry="1.5" fill="#fbfbfb"/>';
 s+='<circle cx="16.8" cy="19.1" r="1" fill="#2a1c12"/><circle cx="23.2" cy="19.1" r="1" fill="#2a1c12"/>';
 if(eyeblack)s+='<rect x="15" y="21.1" width="3" height="1.4" rx="0.6" fill="#161616"/><rect x="22" y="21.1" width="3" height="1.4" rx="0.6" fill="#161616"/>';
 // Nase + Mund
 s+='<path d="M20 19.6 Q19 22 18.4 23 Q20 23.8 21.6 23 Q21 22 20 19.6 Z" fill="'+sh+'" opacity=".55"/>';
 s+='<path d="M17.4 25 Q20 26.4 22.6 25" stroke="#8a4034" stroke-width="1.1" fill="none" stroke-linecap="round"/>';
 // Bart (4 Varianten)
 if(beardT===1)s+='<path d="M13 22 Q20 31 27 22 Q26.5 27.5 20 28.7 Q13.5 27.5 13 22 Z" fill="'+hairC+'" opacity=".92"/>';
 else if(beardT===2)s+='<path d="M16.4 25 Q20 26.6 23.6 25 L23.6 26.4 Q20 28 16.4 26.4 Z" fill="'+hairC+'" opacity=".9"/>';
 else if(beardT===3)s+='<g fill="'+hairC+'" opacity=".3"><circle cx="15" cy="24" r=".5"/><circle cx="17" cy="25.5" r=".5"/><circle cx="19" cy="26.3" r=".5"/><circle cx="21" cy="26.3" r=".5"/><circle cx="23" cy="25.5" r=".5"/><circle cx="25" cy="24" r=".5"/><circle cx="16" cy="22.6" r=".5"/><circle cx="24" cy="22.6" r=".5"/></g>';
 // Glanzkante
 s+='<path d="M11 18 Q11 8.5 20 8.5" stroke="#ffffff" stroke-opacity=".12" stroke-width="1.2" fill="none"/>';
 return s+'</svg>';}
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
 // Welt-Höhe: bei echter Feldposition bis hinter die Endzone (Kamera kann mitfahren)
 const goalY=(fpos!=null)?mapY(fpos):0, ezTopY=(fpos!=null)?mapY(fpos+10):0;
 const topY=(fpos!=null)?Math.min(0,ezTopY-4):0, botY=(fpos!=null)?Math.max(360,mapY(-9)):360, wH=botY-topY;
 s+='<rect x="0" y="'+topY.toFixed(1)+'" width="533" height="'+wH.toFixed(1)+'" fill="url(#turf_'+P+')"/>';
 // 5-Yard-Raster + Hashmarks über die ganze Welt-Höhe
 const hiFy=(fpos!=null)?Math.ceil(fpos)+1:25;
 for(let fy=-5;fy<=hiFy;fy+=5){const y=mapY(fy).toFixed(1);
  s+='<line x1="0" y1="'+y+'" x2="533" y2="'+y+'" stroke="#cdeede" stroke-width="'+(fy===0?0:1)+'" opacity="0.16"/>';
  [23.58,29.72].forEach(hx=>{s+='<line x1="'+(mapX(hx)-3).toFixed(1)+'" y1="'+y+'" x2="'+(mapX(hx)+3).toFixed(1)+'" y2="'+y+'" stroke="#cdeede" stroke-width="1" opacity="0.30"/>';});}
 if(fpos!=null){
  // Endzone hinter der Torlinie (immer gezeichnet; Kamera enthüllt sie bei langen Läufen)
  s+='<rect x="0" y="'+ezTopY.toFixed(1)+'" width="533" height="'+(goalY-ezTopY).toFixed(1)+'" fill="'+defC+'" opacity="0.22"/>';
  s+='<line x1="0" y1="'+goalY.toFixed(1)+'" x2="533" y2="'+goalY.toFixed(1)+'" stroke="#ffffff" stroke-width="2.5" opacity="0.85"/>';
  s+='<text x="266" y="'+(ezTopY+(goalY-ezTopY)/2+5).toFixed(1)+'" font-size="13" font-weight="800" fill="#ffffff" opacity="0.5" text-anchor="middle" letter-spacing="4">END ZONE</text>';
  for(let g=0;g<=100;g+=10){const fy=fpos-g; if(fy<-7||fy>fpos+0.1)continue; const y=mapY(fy);
   const lab=(g<=50?g:100-g);
   s+='<line x1="0" y1="'+y.toFixed(1)+'" x2="533" y2="'+y.toFixed(1)+'" stroke="#cdeede" stroke-width="1" opacity="0.30"/>';
   if(lab>0){s+='<text x="15" y="'+(y+4).toFixed(1)+'" font-size="11" font-weight="800" fill="#cdeede" opacity="0.45">'+lab+'</text>'+
     '<text x="518" y="'+(y+4).toFixed(1)+'" font-size="11" font-weight="800" fill="#cdeede" opacity="0.45" text-anchor="end">'+lab+'</text>';}}
 }else{
  for(let fy=10;fy<=25;fy+=5)if(fy%10===0){const y=mapY(fy).toFixed(1);
   s+='<text x="13" y="'+(parseFloat(y)+4)+'" font-size="11" font-weight="800" fill="#cdeede" opacity="0.4">'+fy+'</text>'+
    '<text x="520" y="'+(parseFloat(y)+4)+'" font-size="11" font-weight="800" fill="#cdeede" opacity="0.4" text-anchor="end">'+fy+'</text>';}
 }
 s+='<line x1="0" y1="'+mapY(0)+'" x2="533" y2="'+mapY(0)+'" stroke="#5fa8ff" stroke-width="2.5" opacity="0.9"/>';
 if(ytg<=24)s+='<line x1="0" y1="'+mapY(ytg)+'" x2="533" y2="'+mapY(ytg)+'" stroke="#ffd34d" stroke-width="2" opacity="0.7" stroke-dasharray="7 5"/>';
 // Aus-Bereiche + weiße Seitenlinien über die ganze Welt-Höhe
 s+='<rect x="0" y="'+topY.toFixed(1)+'" width="12" height="'+wH.toFixed(1)+'" fill="#06110a" opacity="0.6"/><rect x="521" y="'+topY.toFixed(1)+'" width="12" height="'+wH.toFixed(1)+'" fill="#06110a" opacity="0.6"/>'+
   '<line x1="12" y1="'+topY.toFixed(1)+'" x2="12" y2="'+botY.toFixed(1)+'" stroke="#eef6f0" stroke-width="3" opacity="0.92"/><line x1="521" y1="'+topY.toFixed(1)+'" x2="521" y2="'+botY.toFixed(1)+'" stroke="#eef6f0" stroke-width="3" opacity="0.92"/>';
 if(fpos!=null){const gy=goalY,by=ezTopY;   // Pylonen + Endlinie an der echten Torlinie
   [12,521].forEach(px=>{s+='<rect x="'+(px-2.5)+'" y="'+(gy-3).toFixed(1)+'" width="5" height="7" rx="1" fill="#ff7a1a"/><rect x="'+(px-2.5)+'" y="'+(by-3).toFixed(1)+'" width="5" height="7" rx="1" fill="#ff7a1a"/>';});
   s+='<line x1="12" y1="'+by.toFixed(1)+'" x2="521" y2="'+by.toFixed(1)+'" stroke="#eef6f0" stroke-width="2" opacity="0.7"/>';}
 // Kettencrew (Heim-Seitenlinie) + Schiedsrichter auf dem Feld
 s+=_chainGang(ytg)+_refsOnField(d);
 if(!preSnap)d.offense.forEach(o=>{if(o.route&&o.route.length>1){let p='';o.route.forEach((pt,i)=>{p+=(i?'L':'M')+mapX(pt[0]).toFixed(1)+' '+mapY(pt[1]).toFixed(1)+' ';});
  const acc=(o.target||o.carry);s+='<path d="'+p+'" fill="none" stroke="'+(acc?'#ffd34d':'#19e08f')+'" stroke-width="'+(acc?2.4:1.7)+'" opacity="'+(acc?0.95:0.6)+'" marker-end="url(#'+(acc?'aht_':'ah_')+P+')"/>';}});
 svg.innerHTML=s;
 d.defense.forEach((p,i)=>addPlayer(svg,p,defC,'d_'+i,null,cols.defAbbr));
 d.offense.forEach((o,i)=>addPlayer(svg,o,offC,'o'+i,preSnap?{pos:o.pos}:o,cols.offAbbr));   // Vor-Snap: keine Ziel-Markierung
 const qb=d.offense.find(o=>o.pos==='QB');
 const bx=preSnap?26.65:qb.x, by=preSnap?-0.7:qb.y;   // Vor-Snap: Ball ruht am Spot (Line of Scrimmage)
 svg.appendChild(el('ellipse',{id:P+'_pball',cx:mapX(bx),cy:mapY(by),rx:4,ry:2.5,fill:'#9a5a1e',stroke:'#3a1f08','stroke-width':1,opacity:preSnap?1:0}));
}
const _ppos={};
// Hex-Farbe aufhellen/abdunkeln (für plastische Schattierung ohne Verläufe)
function _shade(c,a){c=(''+(c||'#888888')).replace('#','');if(c.length===3)c=c[0]+c[0]+c[1]+c[1]+c[2]+c[2];
 const f=i=>{const v=Math.max(0,Math.min(255,parseInt(c.substr(i,2),16)+a));return v.toString(16).padStart(2,'0');};
 return '#'+f(0)+f(2)+f(4);}
// Realistische Rückennummer je Position (deterministisch pro Spieler)
const _NUMRANGE={QB:[1,12],RB:[20,34],FB:[40,46],WR:[80,89],X:[10,19],Z:[80,88],SL:[11,18],TE:[83,89],OL:[60,79],
 DE:[90,99],DT:[71,98],LB:[40,59],CB:[20,39],S:[20,39],DB:[20,39],K:[1,9]};
function _jersey(pos,i){const r=_NUMRANGE[pos]||[1,99];return r[0]+((i*7+5)%(r[1]-r[0]+1));}
/* Detaillierte Spielerfigur (Top-Down): Schulterpolster mit Plastik-Schattierung, Arme & Handschuhe,
   Helm mit Glanz, Mittelstreifen und Facemask-Käfig, Cleats. Figur zeigt immer nach oben; die
   .face-Gruppe dreht sie in Laufrichtung (Defense im Stand um 180° gedreht). */
function addPlayer(svg,p,color,id,o,abbr){const P=svg.id;const sx=mapX(p.x),sy=mapY(p.y);
 const side=(id&&id[0]==='d')?-1:1;const idx=parseInt((''+(id||'0')).replace(/\D/g,''))||0;const pos=(o&&o.pos)||p.pos;
 const edge=_shade(color,-92),hel=_shade(color,-26),sleeve=_shade(color,-14),glove=_shade(color,92),stripe=_shade(color,104),cleat=_shade(color,-40),fm='#10191333';
 const g=el('g',{}); g.id=P+'_pl_'+id; g.setAttribute('transform','translate('+sx+' '+sy+')');
 g.appendChild(el('ellipse',{cx:0,cy:5.2,rx:8.0,ry:2.8,fill:'#03100a',opacity:.34}));   // Schatten bleibt flach (an größere Figur angepasst)
 const fc=el('g',{}); fc.setAttribute('class','face'); fc.setAttribute('transform','rotate('+(side<0?180:0)+')');   // Blickrichtung
 const fig=el('g',{}); fig.setAttribute('class','fig');                                  // Animations-Gruppe (pop/spin/down/cel)
 if(o&&o.target)fig.appendChild(el('circle',{cx:0,cy:0,r:10.8,fill:'none',stroke:'#ffd34d','stroke-width':1.6,opacity:.9,'class':'pulse'}));
 fig.appendChild(el('ellipse',{cx:-1.9,cy:4.7,rx:1.05,ry:1.7,fill:cleat,stroke:edge,'stroke-width':.5}));          // Cleats (hinten)
 fig.appendChild(el('ellipse',{cx:1.9,cy:4.7,rx:1.05,ry:1.7,fill:cleat,stroke:edge,'stroke-width':.5}));
 fig.appendChild(el('ellipse',{cx:-5.7,cy:1.1,rx:1.95,ry:3.15,fill:sleeve,stroke:edge,'stroke-width':.7}));        // Arme/Ärmel
 fig.appendChild(el('ellipse',{cx:5.7,cy:1.1,rx:1.95,ry:3.15,fill:sleeve,stroke:edge,'stroke-width':.7}));
 fig.appendChild(el('path',{d:'M-6.2 2.3 C-6.7 -1.3 -4.2 -3.0 0 -3.0 C4.2 -3.0 6.7 -1.3 6.2 2.3 C6.0 4.6 3.2 5.2 0 5.2 C-3.2 5.2 -6.0 4.6 -6.2 2.3 Z',fill:color,stroke:edge,'stroke-width':1.2}));   // Schulterpolster
 fig.appendChild(el('ellipse',{cx:0,cy:-0.7,rx:3.7,ry:2.0,fill:'#ffffff',opacity:.17}));                          // Brust-Highlight
 fig.appendChild(el('ellipse',{cx:0,cy:3.5,rx:4.9,ry:1.7,fill:'#000000',opacity:.20}));                           // Rücken-Schatten
 fig.appendChild(el('path',{d:'M-3.6 -2.1 Q0 -1.1 3.6 -2.1',fill:'none',stroke:edge,'stroke-width':.7,opacity:.5}));   // Pad-Trennung
 fig.appendChild(el('line',{x1:0,y1:-1.0,x2:0,y2:4.6,stroke:edge,'stroke-width':.6,opacity:.4}));                 // Mittelnaht
 fig.appendChild(el('ellipse',{cx:-5.1,cy:-1.9,rx:1.25,ry:1.5,fill:glove,stroke:edge,'stroke-width':.5}));        // Handschuhe (vorne)
 fig.appendChild(el('ellipse',{cx:5.1,cy:-1.9,rx:1.25,ry:1.5,fill:glove,stroke:edge,'stroke-width':.5}));
 fig.appendChild(el('ellipse',{cx:0,cy:-2.5,rx:1.8,ry:1.2,fill:hel,stroke:edge,'stroke-width':.5}));              // Hals
 fig.appendChild(el('circle',{cx:0,cy:-4.4,r:3.5,fill:hel,stroke:edge,'stroke-width':1.2}));                      // Helm
 fig.appendChild(el('ellipse',{cx:-1.1,cy:-5.6,rx:1.5,ry:1.0,fill:'#ffffff',opacity:.5}));                        // Helm-Glanz
 fig.appendChild(el('path',{d:'M0 -7.8 L0 -1.7',fill:'none',stroke:stripe,'stroke-width':1.0,opacity:.85}));      // Mittelstreifen
 fig.appendChild(el('path',{d:'M-2.6 -6.1 Q0 -8.5 2.6 -6.1',fill:'none',stroke:fm,'stroke-width':.9}));           // Facemask: Querbügel
 fig.appendChild(el('path',{d:'M-2.1 -5.0 Q0 -7.1 2.1 -5.0',fill:'none',stroke:fm,'stroke-width':.8}));
 fig.appendChild(el('line',{x1:0,y1:-7.7,x2:0,y2:-4.7,stroke:fm,'stroke-width':.8}));                             // Facemask: Streben
 fig.appendChild(el('line',{x1:-1.45,y1:-7.1,x2:-1.45,y2:-4.85,stroke:fm,'stroke-width':.7}));
 fig.appendChild(el('line',{x1:1.45,y1:-7.1,x2:1.45,y2:-4.85,stroke:fm,'stroke-width':.7}));
 if(abbr){const t=el('text',{x:0,y:-3.4,'text-anchor':'middle','font-size':3.2,fill:stripe,'font-weight':800,stroke:edge,'stroke-width':.45,'paint-order':'stroke'});t.textContent=(''+abbr)[0];fig.appendChild(t);}   // Team-Logo (Helm-Buchstabe)
 const sc=el('g',{}); sc.setAttribute('transform','scale(1.2)'); sc.appendChild(fig); fc.appendChild(sc); g.appendChild(fc);   // Figur etwas größer (besser sichtbar)
 if(pos!=='OL'&&pos!=='DT'){const num=_jersey(pos,idx);const t=el('text',{x:0,y:3.6,'text-anchor':'middle','font-size':6.2,fill:'#ffffff','font-weight':800,stroke:'#0a140f','stroke-width':.85,'paint-order':'stroke'});t.textContent=num;g.appendChild(t);}   // Rückennummer (aufrecht, lesbar)
 svg.appendChild(g); _ppos[P+id]=[p.x,p.y];
}
// Figur dreht weich in ihre Laufrichtung (alle Figuren zeichnen nach oben -> einheitliche Formel)
function faceP(P,id,vx,vy,o){if(Math.hypot(vx,vy)<0.7)return;
 const a=Math.atan2(-vy,vx)*180/Math.PI+90;
 if(o._fa==null)o._fa=a;else{const dd=((a-o._fa+540)%360)-180;o._fa+=dd*0.3;}
 const g=$(P+'_pl_'+id);if(!g)return;const fcel=g.querySelector('.face');if(fcel)fcel.setAttribute('transform','rotate('+o._fa.toFixed(1)+')');}
// Kleine 2D-Figur (Sideline-Crew / Schiedsrichter)
function _crewFig(x,y,vest,acc){return '<g transform="translate('+x.toFixed(1)+' '+y.toFixed(1)+')"><ellipse cy="3" rx="2.6" ry="1.4" fill="#06140d" fill-opacity=".3"/><ellipse cy="1" rx="2.3" ry="3" fill="'+vest+'" stroke="#06140d" stroke-width=".6"/><circle cy="-2.4" r="1.6" fill="#e7c39c" stroke="#06140d" stroke-width=".5"/>'+(acc||'')+'</g>';}
function _refFig(x,y){return '<g transform="translate('+x.toFixed(1)+' '+y.toFixed(1)+')"><ellipse cy="3" rx="2.6" ry="1.4" fill="#06140d" fill-opacity=".3"/><ellipse cy="1" rx="2.4" ry="3.1" fill="#1c1c1c" stroke="#06140d" stroke-width=".5"/><rect x="-2.3" y="-0.9" width="4.6" height="1" fill="#f4f4f4"/><rect x="-2.3" y="1.1" width="4.6" height="1" fill="#f4f4f4"/><circle cy="-2.5" r="1.6" fill="#caa07a" stroke="#06140d" stroke-width=".5"/></g>';}
// Kettencrew exakt an Line-of-Scrimmage und First-Down-Linie (Heim-Seitenlinie links)
function _chainGang(ytg){const sx=4,losY=mapY(0);let g='';
 g+=_crewFig(sx,losY+9,'#e08b1a','<rect x="-1.6" y="-9.5" width="3.2" height="5" rx=".6" fill="#ff7a1a" stroke="#06140d" stroke-width=".4"/>');   // Down-Box-Mann
 g+=_crewFig(sx+5,losY,'#ff7a1a','<line x1="0" y1="-3" x2="0" y2="-12" stroke="#ffb15a" stroke-width="1.6"/>');                                  // Stab an der LOS
 if(ytg<=24){const fdY=mapY(ytg);
   g+='<line x1="'+(sx+5)+'" y1="'+(losY-7).toFixed(1)+'" x2="'+(sx+5)+'" y2="'+(fdY-7).toFixed(1)+'" stroke="#ffd34d" stroke-width="1" stroke-dasharray="3 2" opacity=".85"/>'+  // 10-Yard-Kette
     _crewFig(sx+5,fdY,'#ff7a1a','<line x1="0" y1="-3" x2="0" y2="-12" stroke="#ffb15a" stroke-width="1.6"/>');}                                  // Stab an der First-Down-Linie
 return g;}
function _refsOnField(d){const qb=d.offense.find(o=>o.pos==='QB');const bx=qb?mapX(qb.x):266,by=qb?mapY(qb.y):270;
 return _refFig(bx+44,by-6)+_refFig(486,mapY(7));}   // Referee hinter dem QB + Side Judge nahe rechter Seitenlinie
function moveP(P,id,x,y){const g=$(P+'_pl_'+id);if(!g)return;g.setAttribute('transform','translate('+mapX(x)+' '+mapY(y)+')');_ppos[P+id]=[x,y];}
function popFig(P,id){const g=$(P+'_pl_'+id);if(!g)return;const f=g.querySelector('.fig');if(f){f.classList.remove('pop');void f.getBBox();f.classList.add('pop');}}
function downFig(P,id){const g=$(P+'_pl_'+id);if(!g)return;const f=g.querySelector('.fig');if(f){f.classList.add('down');}}
function spinFig(P,id){const g=$(P+'_pl_'+id);if(!g)return;const f=g.querySelector('.fig');if(f&&!f.classList.contains('spin')&&!f.classList.contains('down')){f.classList.add('spin');setTimeout(()=>f.classList.remove('spin'),460);}}
function celebrate(P,id){const g=$(P+'_pl_'+id);if(!g)return;const f=g.querySelector('.fig');if(f){f.classList.remove('down','spin');f.classList.add('cel','cel'+(Math.floor(Math.random()*10)+1));}}  // 1 von 10 TD-Jubeln
/* Kino-Jubel: Spiel pausiert, Endzonen-Kamera mit Stadion, Feld, traurigen Gegnern & herbeieilendem Team */
function _celFig(color,cls,extra){return '<g class="fig '+(cls||'')+'"'+(extra||'')+'>'+
   '<rect x="-2.1" y="3.4" width="4.2" height="5.8" rx="1.3" fill="'+color+'" stroke="#06140d" stroke-width="0.9"/>'+   // Rumpf/Beine
   '<ellipse cx="0" cy="1.4" rx="6.4" ry="4.6" fill="'+color+'" stroke="#06140d" stroke-width="1"/>'+                  // Schultern
   '<circle cx="0" cy="-4.4" r="3.4" fill="'+color+'" stroke="#06140d" stroke-width="1"/>'+                           // Helm
   '<line x1="-2" y1="-5.7" x2="2" y2="-5.7" stroke="#06140d" stroke-width="0.8"/></g>';}                              // Facemask
function tdCelebration(svg,color,defColor,onDone){const P=svg.id;if(_anim[P]){cancelAnimationFrame(_anim[P]);_anim[P]=null;}
 defColor=defColor||'#ef5350';const cel=Math.floor(Math.random()*10)+1;
 let s='<defs>'+
  '<linearGradient id="csky_'+P+'" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0a1622"/><stop offset="1" stop-color="#14243a"/></linearGradient>'+
  '<linearGradient id="ctf_'+P+'" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#1d7a48"/><stop offset="1" stop-color="#0b3a23"/></linearGradient></defs>'+
  '<rect x="0" y="0" width="533" height="360" fill="url(#csky_'+P+')"/>';
 // --- Tribünen (mehrere Ränge mit Geländer + Flutlichtmasten) ---
 s+='<rect x="0" y="0" width="533" height="118" fill="#0c141f"/>';
 ['#101b29','#0c151f','#0a1018'].forEach((bg,r)=>{const y0=8+r*34;s+='<rect x="0" y="'+y0+'" width="533" height="32" fill="'+bg+'"/>';
   for(let i=0;i<60;i++){const cx=6+i*9,cy=y0+8+(i%3)*8,pal=[defColor,'#dfe7e3','#5a6b7a',color,'#c9a23a'];s+='<circle cx="'+cx+'" cy="'+cy+'" r="2" fill="'+pal[(i+r)%5]+'" opacity="0.85"/>';}
   s+='<line x1="0" y1="'+(y0+32)+'" x2="533" y2="'+(y0+32)+'" stroke="#060b10" stroke-width="2"/>';});
 [70,266,463].forEach(mx=>{s+='<rect x="'+(mx-2)+'" y="0" width="4" height="14" fill="#3a444f"/><rect x="'+(mx-16)+'" y="-2" width="32" height="7" rx="2" fill="#cfe3ff" opacity="0.85"/>';});
 // --- Feld mit Linien/Perspektive ---
 s+='<rect x="0" y="118" width="533" height="242" fill="url(#ctf_'+P+')"/>';
 for(let i=0;i<10;i++)if(i%2)s+='<rect x="'+(i*55)+'" y="118" width="55" height="242" fill="#ffffff" opacity="0.03"/>';   // Mähstreifen
 [140,166,196,232,274,300].forEach(y=>{s+='<line x1="0" y1="'+y+'" x2="533" y2="'+y+'" stroke="#dfeee6" stroke-width="'+(y===300?3:1.2)+'" opacity="'+(y===300?0.9:0.28)+'"/>';
   if(y<300)[150,383].forEach(hx=>{s+='<rect x="'+hx+'" y="'+(y-1)+'" width="14" height="2" fill="#dfeee6" opacity="0.3"/>';});});
 // Endzone vorne (Kamera in der Endzone)
 s+='<rect x="0" y="300" width="533" height="60" fill="'+color+'" opacity="0.34"/>'+
    '<text x="266" y="342" text-anchor="middle" font-size="15" font-weight="800" fill="#ffffff" opacity="0.5" letter-spacing="8">END ZONE</text>';
 // Spotlight-Strahlen
 s+='<polygon points="70,14 300,300 -40,300" fill="#ffffff" opacity="0.04"/><polygon points="463,14 600,300 250,300" fill="#ffffff" opacity="0.04"/>';
 // --- traurige Gegner im Hintergrund (an ihren Positionen, Kopf gesenkt/Schütteln) ---
 [[110,150],[205,140],[300,146],[395,152],[470,138]].forEach((p,i)=>{
   s+='<g transform="translate('+p[0]+' '+p[1]+') scale(1.7)">'+_celFig(defColor,'sad',' style="animation-delay:'+(i*0.3).toFixed(1)+'s"')+'</g>';});
 // --- dein Team läuft langsam von seinen Positionen herbei und stellt sich um dich ---
 [[150,250,-150,90],[372,250,150,80],[200,300,-120,-40],[330,300,120,-40]].forEach((p,i)=>{
   s+='<g transform="translate('+p[0]+' '+p[1]+')"><g class="runin" style="--rx:'+p[2]+'px;--ry:'+p[3]+'px;animation-delay:'+(0.2+i*0.15).toFixed(2)+'s"><g transform="scale(2.4)">'+_celFig(color,'cel'+((i%10)+1))+'</g></g></g>';});
 // --- großer tanzender Torschütze, zentral ---
 s+='<g transform="translate(266 248) scale(6)">'+_celFig(color,'cel'+cel)+'</g>';
 // TOUCHDOWN-Schrift (ohne Emoji)
 s+='<text class="tdword" x="266" y="96" text-anchor="middle" font-size="40" font-weight="800" fill="#ffffff" stroke="#06140d" stroke-width="1" letter-spacing="3" style="transform-box:fill-box;transform-origin:center">TOUCHDOWN</text>';
 // Konfetti
 for(let i=0;i<20;i++){const cx=10+i*26,dur=(1.4+(i%5)*0.28).toFixed(2),del=((i*0.19)%1.8).toFixed(2),col=[color,'#ffd34d','#ffffff',defColor][i%4];
   s+='<rect class="conf" x="'+cx+'" y="-12" width="5" height="9" rx="1" fill="'+col+'" style="animation-duration:'+dur+'s;animation-delay:'+del+'s"/>';}
 svg.innerHTML=s;
 setTimeout(()=>{if(onDone)onDone();},2800);   // 2,8 s Limit -> danach Extra-Punkt/FG, dann weiter
}
function curPos(P,id){return _ppos[P+id]||null;}
const SPD={QB:7.4,RB:9.0,WR:9.6,TE:8.4,OL:6.0,DL:6.6,DE:6.9,DT:6.0,LB:8.5,CB:9.5,DB:9.4,S:8.9};
function _spd(p){return SPD[p]||8;}
function _toward(o,tx,ty,mx){const dx=tx-o.x,dy=ty-o.y,d=Math.hypot(dx,dy);if(d<=mx||d<1e-6){o.x=tx;o.y=ty;}else{o.x+=dx/d*mx;o.y+=dy/d*mx;}}
// Geschwindigkeits-basiertes Steuern: beschleunigt/dreht weich auf das Ziel zu (Impuls -> keine ruckartigen Knicke)
function steer(o,tx,ty,maxspd,dt,resp){const dx=tx-o.x,dy=ty-o.y,d=Math.hypot(dx,dy);
 let dvx=0,dvy=0;if(d>1e-4){const s=Math.min(maxspd,d/dt);dvx=dx/d*s;dvy=dy/d*s;}
 const k=Math.min(1,(resp||8)*dt);o.vx=(o.vx||0)+(dvx-(o.vx||0))*k;o.vy=(o.vy||0)+(dvy-(o.vy||0))*k;
 o.x+=o.vx*dt;o.y+=o.vy*dt;}
// Route weich ablaufen (an jedem Break abbremsen/cutten) und danach in Endrichtung weiter, ohne ins Aus
function routeStep(o,mx,dt,rp){if(!o.route)return;
 if(o.ri<o.route.length){const wp=o.route[o.ri];steer(o,wp[0],wp[1],mx(o.pos),dt,rp(o.pos));if(Math.hypot(wp[0]-o.x,wp[1]-o.y)<0.7)o.ri++;}
 else{if(!o._dir){const r=o.route,n=r.length,a=r[Math.max(0,n-2)],b=r[n-1];let dx=b[0]-a[0],dy=b[1]-a[1],dd=Math.hypot(dx,dy);if(dd<0.05){dx=0;dy=1;dd=1;}o._dir=[dx/dd,dy/dd];}
   let dx=o._dir[0],dy=Math.max(o._dir[1],0.25);   // nie rückwärts weiterlaufen (kein Lauf in die eigene Endzone)
   if((o.x<6&&dx<0)||(o.x>47.3&&dx>0)){dx=(o.x>26.65?-0.3:0.3);dy=Math.abs(dy)+0.7;}
   const dd=Math.hypot(dx,dy)||1;steer(o,o.x+dx/dd*5,o.y+dy/dd*5,mx(o.pos),dt,rp(o.pos));}}
function _advance(o,mx){if(!o.route)return;let b=mx;while(b>0&&o.ri<o.route.length){const wp=o.route[o.ri],dx=wp[0]-o.x,dy=wp[1]-o.y,d=Math.hypot(dx,dy);if(d<=b){o.x=wp[0];o.y=wp[1];o.ri++;b-=d;}else{o.x+=dx/d*b;o.y+=dy/d*b;b=0;}}}
// läuft die Route ab UND danach in deren Endrichtung weiter (kein Stehenbleiben am letzten Wegpunkt)
function _routeRun(o,mx,fwd){if(!o.route)return;_advance(o,mx);
 if(o.ri>=o.route.length){if(!o._dir){const r=o.route,n=r.length,a=r[Math.max(0,n-2)],b=r[n-1];let dx=b[0]-a[0],dy=b[1]-a[1],dd=Math.hypot(dx,dy);if(dd<0.05){dx=0;dy=1;dd=1;}o._dir=[dx/dd,dy/dd];}
   let dx=o._dir[0],dy=o._dir[1];
   // nicht ins Aus laufen: nahe der Seitenlinie zur Mitte & nach vorne (upfield) drehen
   if((o.x<6&&dx<0)||(o.x>47.3&&dx>0)){dx=(o.x>26.65?-0.25:0.25);dy=Math.abs(dy)+0.7;}
   const dd=Math.hypot(dx,dy)||1;
   o.x+=dx/dd*mx*(fwd||1);o.y+=dy/dd*mx*(fwd||1);
   o.x=Math.max(2,Math.min(51.3,o.x));}}
function playAnim(svg,d,res,onDone){
 const P=svg.id; if(_anim[P])cancelAnimationFrame(_anim[P]);
 res=res||{}; const kind=res.kind||(d.kind==='run'?'run':'complete');
 const yards=(res.yards!=null?res.yards:(res.mean_yards!=null?res.mean_yards:0));
 const cam=(res.fpos!=null);                              // Kamera fährt bei echter Feldposition mit
 const td=!!res.td, vy=cam?yards:((td&&yards>24)?24:yards);   // mit Kamera bis zur echten Endzone laufen; sonst (Sim-Tool) begrenzt
 const yMax=cam?(res.fpos+2):25.5;                        // Feld-Obergrenze (Welt-Höhe)
 let camY=0;
 const fumble=!!res.fumble&&(kind==='run'||kind==='complete')&&!td;   // Fumble (Ballverlust) bei Lauf/Fang
 const isPass=(kind!=='run'),ball=$(P+'_pball'),C=26.65;
 const SP=res.spd||{off:1,def:1};                              // Tempo aus Spielerwerten (Offense-Skill / Defense-Coverage)
 const OFFSK={X:1,Z:1,SL:1,TE:1,RB:1,FB:1},DEFCV={CB:1,S:1,DB:1};
 const sf=pos=>OFFSK[pos]?SP.off:(DEFCV[pos]?SP.def:1);
 let handoffDone=isPass;                                       // bei Läufen erst nach dem Handoff trägt der RB den Ball
 const O=d.offense.map((o,i)=>({i,pos:o.pos,x:o.x,y:o.y,sy:o.y,route:(o.route&&o.route.length>1)?o.route:null,ri:1,target:!!o.target,carry:!!o.carry,_fa:0}));
 const D=d.defense.map((p,i)=>({i,pos:p.pos,x:p.x,y:p.y,role:p.role,cover:p.cover,drop:p.drop,_fa:180}));
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
 let intD=null,swatD=null;if(kind==='int'||kind==='incomplete'){let bd=1e9,best=null;D.forEach(p=>{const dd=Math.hypot(p.x-catchPt[0],p.y-catchPt[1]);if(dd<bd){bd=dd;best=p;}});if(kind==='int')intD=best;else swatD=best;}
 let swatted=false;
 const BALLSPD=23;                                  // Ballgeschwindigkeit (Yd/s) — Flug sichtbar, Receiver fängt im Lauf
 const TS=0.58;                                     // Spiel-Zeitlupe: Play läuft langsamer & lesbarer ab (real bleibt die Logik)
 const t0=performance.now();let last=t0,pt=0,thrown=false,tAt=0,bp=[qb.x,qb.y],arrived=false,caught=false,sacked=false,arrTime=0,oob=false,throwAng=0,gainT=-1,hoT=-1;
 let fumbled=false,recovered=false,fumT=-1,recT=-1,fumbleSpot=null,recoverer=null;
 const flightDur=Math.max(0.35,Math.hypot(catchPt[0]-qb.x,catchPt[1]-qb.y)/BALLSPD);
 const RESP={QB:8,RB:10,WR:10.5,TE:8.5,OL:6,FB:8.5,DE:7.5,DT:6.5,LB:8.5,CB:10.5,DB:10,S:9};   // Wendigkeit je Position
 const rp=pos=>RESP[pos]||8;
 const rushers=D.filter(p=>p.role==='rush');
 const olsX=ols.slice().sort((a,b)=>a.x-b.x);
 if(isPass){const rs=rushers.slice().sort((a,b)=>a.x-b.x);     // Pass-Schutz: jeder Blocker nimmt einen Rusher (Überzahl = freier Rusher = Druck)
   rs.forEach((r,i)=>{const o=olsX[i];if(o){r._ol=o;o._asg=r;}});}
 function frame(now){const rdt=Math.min(0.05,(now-last)/1000);last=now;const dt=rdt*TS;pt+=dt;const el=pt;   // el = Spielzeit (verlangsamt)
  const ramp=Math.min(1,0.22+el*0.95);                         // realistischer Antritt: Tempo über ~0.8s aufbauen
  const mx=pos=>_spd(pos)*sf(pos)*ramp;                        // Maximaltempo (Yd/s) dieses Frames
  if(!isPass&&!handoffDone&&tgt&&(Math.hypot(tgt.x-qb.x,tgt.y-qb.y)<1.6||el>1.0)){handoffDone=true;hoT=el;}   // Handoff am Mesh-Punkt
  const carrier=(kind==='complete'&&caught)?tgt:(!isPass?(handoffDone?tgt:null):null);
  const picked=(kind==='int'&&arrived);                        // nach Interception: Rollen drehen (Defense returnt)
  const pressure=isPass&&rushers.some(r=>(!r._ol||el>1.6)&&Math.hypot(r.x-qb.x,r.y-qb.y)<2.3);   // freier/durchgebrochener Rusher
  // ---- QB: Drop in die Pocket, Schritt nach vorn beim Wurf ----
  if(isPass&&!sacked){const ty=thrown?qb.y+1.4:(pressure?qb.y+0.5:qb.sy-2.0);steer(qb,C,Math.max(-7.0,ty),mx('QB')*0.95,dt,rp('QB'));}
  else if(!isPass){steer(qb,C-0.4,-3.4,mx('QB')*0.7,dt,rp('QB'));}
  // ---- Offense: Blocker (Pocket/Run-Block), Ballträger, Routen ----
  O.forEach(o=>{if(o.pos==='QB')return;
   if(picked){steer(o,intD.x,intD.y,mx(o.pos),dt,rp(o.pos));return;}   // nach INT: Offense jagt den Interceptor
   if((o.pos==='X'||o.pos==='Z'||o.pos==='SL'||o.pos==='TE')&&el<0.4&&!o._rel){o._rel=1;o.vx=(o.vx||0)+((o.i%2)?1.1:-1.1);}   // Release/Stem am Snap
   if(o.pos==='OL'){
     if(isPass){const r=o._asg;
       if(r){const dx=qb.x-r.x,dy=qb.y-r.y,dd=Math.hypot(dx,dy)||1;steer(o,r.x+dx/dd*0.85,Math.max(-3.4,Math.min(-0.2,r.y+dy/dd*0.85)),mx('OL'),dt,rp('OL'));}  // goalside vor dem Rusher -> Wall
       else{const slot=C+(olsX.indexOf(o)-(olsX.length-1)/2)*1.7;steer(o,slot,-1.9,mx('OL'),dt,rp('OL'));}}               // unbeschäftigt -> Pocket füllen
     else{const lane=runEnd?runEnd[0]:C;let r=null,bd=1e9;D.forEach(p=>{if(p.role==='man'||p.drop)return;const dd=Math.hypot(p.x-o.x,p.y-o.y);if(dd<bd){bd=dd;r=p;}});
       if(r){const toLane=(r.x<=lane)?0.6:-0.6;steer(o,r.x+toLane,Math.max(o.y,r.y+0.3),mx('OL')*1.05,dt,rp('OL'));}     // an die lochnahe Schulter -> Verteidiger vom Loch wegtreiben
       else steer(o,o.x+(lane-o.x)*0.25,Math.min(4.5,o.y+2.6),mx('OL'),dt,rp('OL'));}                                   // frei -> zum Second Level
     return;}
   if(o===tgt){if(fumbled){o.vx=o.vy=0;return;}   // nach Fumble bleibt der Ballträger liegen
     if(isPass){if(!caught)routeStep(o,mx,dt,rp);else steer(o,gain[0],gain[1]+2.0,mx(o.pos),dt,rp(o.pos));}   // Fang -> upfield (YAC), läuft durch bis zum Tackle
     else{   // Lauf: dem Loch folgen, aber um Verteidiger im Weg herum improvisieren (kein Stehenbleiben)
       let tx,ty;
       if(o.route&&o.ri<o.route.length){const wp=o.route[o.ri];tx=wp[0];ty=wp[1];if(Math.hypot(wp[0]-o.x,wp[1]-o.y)<0.8)o.ri++;}
       else{tx=runEnd?runEnd[0]:C;ty=(runEnd?runEnd[1]:6)+2.0;}   // etwas über den Spot hinaus -> läuft weiter, wird getackelt
       let block=null,bd=3.0;D.forEach(q=>{if(q.y<o.y+0.4)return;const dd=Math.hypot(q.x-o.x,(q.y-o.y)*0.6);if(dd<bd){bd=dd;block=q;}});  // Verteidiger im Weg nach vorn
       if(block){const open=(block.x>=o.x)?-1:1;tx=Math.max(2,Math.min(51,o.x+open*2.4));ty=Math.max(ty,o.y+1.8);if(!o._spun&&bd<1.8){o._spun=1;spinFig(P,'o'+o.i);}}  // zur freien Seite cutten
       steer(o,tx,ty,mx(o.pos),dt,rp(o.pos));}
     return;}
   if(o.route&&!caught)routeStep(o,mx,dt,rp);   // Mitläufer/FB-Lead laufen ihre Wege
  });
  // Ball / Wurf — fester Fangpunkt, Release so getimt, dass Ball und Receiver zusammen ankommen
  if(isPass&&kind!=='sack'){
   const dest=catchPt;                                                      // fester Zielpunkt — auch bei INT bricht der Verteidiger dorthin (kein homing auf einen wegrennenden Spieler)
   if(!thrown){
     const ballTime=Math.hypot(dest[0]-qb.x,dest[1]-qb.y)/BALLSPD;          // Flugzeit des Balls zum Punkt
     const recvTime=tgt?Math.hypot(dest[0]-tgt.x,dest[1]-tgt.y)/Math.max(4,_spd(tgt.pos)):0;  // Zeit des Receivers zum Punkt
     const qbPressed=D.some(q=>q.role==='rush'&&Math.hypot(q.x-qb.x,q.y-qb.y)<1.7);
     const timed=tgt&&el>0.5&&recvTime<=ballTime+0.05;                      // jetzt werfen -> Receiver läuft den Ball an
     if(timed||(qbPressed&&el>0.6)||el>2.4){thrown=true;tAt=el;bp=[qb.x,qb.y];throwAng=Math.atan2(-(dest[1]-qb.y),(dest[0]-qb.x))*180/Math.PI;}   // Ball zeigt in Flugrichtung
   }
   if(thrown&&!arrived){const o2={x:bp[0],y:bp[1]};_toward(o2,dest[0],dest[1],BALLSPD*dt);bp=[o2.x,o2.y];
     if(Math.hypot(dest[0]-bp[0],dest[1]-bp[1])<0.6){arrived=true;arrTime=el;if(kind==='complete'){caught=true;popFig(P,'o'+tgt.i);}else if(kind==='int'&&intD)popFig(P,'d_'+intD.i);}}   // INT-Fang
   else if(arrived){if(kind==='complete'&&caught)bp=[tgt.x,tgt.y];else if(intD)bp=[bp[0]+(intD.x-bp[0])*0.3,bp[1]+(intD.y-bp[1])*0.3];}   // INT: Ball gleitet weich zum Eroberer (kein Sprung)
  }
  if(kind==='incomplete'&&arrived&&!swatted&&swatD){swatted=true;popFig(P,'d_'+swatD.i);}   // DB verteidigt den Pass (Reaktion)
  // ---- Defense: Rush / Mann / Zone / Verfolgung (alles weich gesteuert) ----
  D.forEach(p=>{const sp=mx(p.pos);
   if(picked){if(p===intD)steer(p,intD.x,Math.max(intD.y-11,-5.5),sp,dt,rp(p.pos));else steer(p,p.x+(intD.x-p.x)*0.05,p.y,sp*0.6,dt,rp(p.pos));return;}   // INT-Return: Interceptor läuft zurück, Rest begleitet
   if(kind==='int'&&p===intD){steer(p,catchPt[0],catchPt[1],sp*1.05,dt,rp(p.pos));return;}   // Interceptor bricht auf den Ball (sitzt am Fangpunkt)
   if(kind==='sack'){steer(p,qb.x,qb.y,sp,dt,rp(p.pos));return;}
   if(carrier){const dest=(!isPass?runEnd:gain)||[carrier.x,carrier.y];                              // Verfolgungswinkel: leicht vor den Läufer
     const ahead=Math.min(0.42,Math.max(0,(carrier.y-p.y))/16);steer(p,carrier.x+(dest[0]-carrier.x)*ahead,carrier.y+(dest[1]-carrier.y)*ahead,sp,dt,rp(p.pos));return;}
   if(p.role==='rush'){steer(p,qb.x+Math.sin(el*6+p.i)*0.6,qb.y,sp*(p._ol?0.9:1.0),dt,rp(p.pos));return;}   // zum QB – Hand-Fight, von der O-Line geblockt
   if(p.role==='man'&&p.cover){const r=O.find(o=>o.pos===p.cover);if(r){const trail=Math.min(2.6,0.7+el*0.85);steer(p,r.x+(p.x<r.x?-0.4:0.4),r.y-trail,sp*0.97,dt,rp(p.pos));}else steer(p,p.x,p.y,sp,dt,rp(p.pos));return;}
   if(p.drop){let bestR=null,bd=8.5;O.forEach(o=>{if(o.pos==='QB'||o.pos==='OL')return;const dd=Math.hypot(o.x-p.drop[0],o.y-p.drop[1]);if(dd<bd){bd=dd;bestR=o;}});  // Zone: Landmarke, dann auf den nächsten Receiver brechen
     const tx=bestR?p.drop[0]+(bestR.x-p.drop[0])*0.5:p.drop[0],ty=bestR?p.drop[1]+(bestR.y-p.drop[1])*0.32:p.drop[1];steer(p,tx,ty,sp*0.9,dt,rp(p.pos));return;}
   steer(p,p.x,p.y,sp,dt,rp(p.pos));
  });
  // Sack: QB wird zurückgedrängt, sobald ein Rusher durch ist
  if(kind==='sack'){if(rushers.some(p=>Math.hypot(p.x-qb.x,p.y-qb.y)<1.4)||el>1.3){sacked=true;qb.y=Math.max(qb.y-mx('QB')*dt,yards);}}
  // Kollision: Körper durchdringen sich nicht. Blocker hält/treibt, freier oder durchbrechender Rusher setzt sich durch.
  for(let it=0;it<2;it++)O.forEach(o=>{if(o.pos==='QB'&&kind!=='sack')return;
    D.forEach(p=>{const dx=p.x-o.x,dy=p.y-o.y,dist=Math.hypot(dx,dy);
      const mind=(o.pos==='OL')?1.95:(o.pos==='FB'?1.7:(o===carrier?1.05:1.3));
      if(dist<mind&&dist>1e-4){const push=mind-dist,ux=dx/dist,uy=dy/dist;
        const rusherWins=(kind==='sack'&&p.role==='rush')||(isPass&&o.pos==='OL'&&p.role==='rush'&&!p._ol);   // Sack / freier Blitzer bricht durch
        if(rusherWins){o.x-=ux*push*0.5;o.y-=uy*push*0.5;p.x+=ux*push*0.5;p.y+=uy*push*0.5;}
        else{p.x+=ux*push;p.y+=uy*push;p.vx=(p.vx||0)*0.35;p.vy=(p.vy||0)*0.35;}}});});                       // Verteidiger wird geblockt (Tempo bricht)
  // Out of bounds: Ballträger an der Seitenlinie -> Play tot am Spot (wie im echten Football)
  const LO=1.2,HI=52.1;
  if(carrier){if(carrier.x<LO){carrier.x=LO;oob=true;}else if(carrier.x>HI){carrier.x=HI;oob=true;}}
  O.forEach(o=>{o.x=Math.max(1.5,Math.min(51.8,o.x));o.y=Math.max(-7.5,Math.min(yMax,o.y));});   // im Feld bleiben (Welt-Höhe)
  D.forEach(p=>{p.x=Math.max(1.5,Math.min(51.8,p.x));p.y=Math.max(-7.5,Math.min(yMax,p.y));});
  // Kamera: folgt dem Ball/Ballträger downfield (lange Läufe, Pässe, INT-Returns)
  if(cam){let fy=qb.y;if(carrier)fy=carrier.y;else if(picked&&intD)fy=intD.y;else if(thrown)fy=bp[1];
   const tv=Math.min(0,mapY(fy)-185);camY+=(tv-camY)*Math.min(1,dt*6);
   svg.setAttribute('viewBox','0 '+camY.toFixed(1)+' 533 360');}
  // schreiben
  O.forEach(o=>{moveP(P,'o'+o.i,o.x,o.y);faceP(P,'o'+o.i,o.vx||0,o.vy||0,o);});
  D.forEach(p=>{moveP(P,'d_'+p.i,p.x,p.y);faceP(P,'d_'+p.i,p.vx||0,p.vy||0,p);});
  if(ball){
   if(fumbled){const fb=(recovered&&recoverer)?[recoverer.x,recoverer.y]:fumbleSpot;const fx=mapX(fb[0]),fy=mapY(fb[1]);   // loser Ball trudelt, dann beim Eroberer
     ball.setAttribute('opacity',1);ball.setAttribute('cx',fx);ball.setAttribute('cy',fy);ball.setAttribute('transform','rotate('+((el*780)%360).toFixed(0)+' '+fx+' '+fy+')');}
   else if(!isPass){
     if(!handoffDone){ball.setAttribute('opacity',1);ball.setAttribute('cx',mapX(qb.x));ball.setAttribute('cy',mapY(qb.y));ball.setAttribute('transform','');}   // Ball in QB-Hand bis zum Handoff
     else if(carrier){const ho=Math.min(1,(el-hoT)/0.16);                                    // kurzer Handoff-Übergang QB -> RB
       const bxv=qb.x+(carrier.x-qb.x)*ho,byv=qb.y+(carrier.y-qb.y)*ho;
       const cbx=mapX(bxv),cby=mapY(byv),ca=Math.atan2(-(carrier.vy||0),(carrier.vx||0))*180/Math.PI;   // getragen: zeigt in Laufrichtung, kein Trudeln
       ball.setAttribute('opacity',1);ball.setAttribute('cx',cbx);ball.setAttribute('cy',cby);ball.setAttribute('transform','rotate('+ca.toFixed(0)+' '+cbx+' '+cby+')');}
     else ball.setAttribute('opacity',0);}
   else if(kind==='sack'){ball.setAttribute('opacity',1);ball.setAttribute('cx',mapX(qb.x));ball.setAttribute('cy',mapY(qb.y));ball.setAttribute('transform','');}   // Ball bleibt beim bedrängten QB
   else if(thrown){const fp=arrived?1:Math.min(1,(el-tAt)/flightDur);const arc=Math.sin(fp*Math.PI)*14;
     const bx=mapX(bp[0]),by=mapY(bp[1])-arc;ball.setAttribute('cx',bx);ball.setAttribute('cy',by);
     ball.setAttribute('transform','rotate('+(throwAng+Math.sin(fp*26)*4).toFixed(1)+' '+bx+' '+by+')');   // zeigt in Flugrichtung + feiner Spiral-Wobble
     ball.setAttribute('opacity',(kind==='incomplete'&&arrived)?Math.max(0,1-(el-arrTime)/0.4):1);}
   else {ball.setAttribute('opacity',1);ball.setAttribute('cx',mapX(qb.x));ball.setAttribute('cy',mapY(qb.y));ball.setAttribute('transform','');}   // Pass: Ball in QB-Hand bis zum Wurf
  }
  // Ende: Lauf/Fang endet bei ECHTEM Kontakt am Raumgewinn-Spot (kein Phantom-Tackle); sonst Pass/Sack/Aus/Timeout
  const atGain=carrier&&((kind==='complete'&&Math.hypot(carrier.x-gain[0],carrier.y-gain[1])<0.9)||(!isPass&&runEnd&&Math.abs(carrier.y-runEnd[1])<0.9));
  if(atGain&&gainT<0)gainT=el;
  const contact=carrier&&D.some(p=>Math.hypot(p.x-carrier.x,p.y-carrier.y)<1.45);     // Verteidiger wirklich am Ballträger?
  // Fumble: am Kontaktpunkt springt der Ball los, der nächste Verteidiger erobert ihn
  if(fumble&&carrier&&!fumbled&&atGain&&(contact||el>gainT+1.0)){fumbled=true;fumT=el;
    fumbleSpot=[Math.max(2,Math.min(51,carrier.x+(carrier.i%2?1:-1)*0.9)),carrier.y+0.6];
    downFig(P,'o'+carrier.i);                                                          // Ballträger geht zu Boden
    let bd=1e9;D.forEach(p=>{const dd=Math.hypot(p.x-fumbleSpot[0],p.y-fumbleSpot[1]);if(dd<bd){bd=dd;recoverer=p;}});}
  if(fumbled&&!recovered&&recoverer){steer(recoverer,fumbleSpot[0],fumbleSpot[1],mx(recoverer.pos),dt,rp(recoverer.pos));
    if(Math.hypot(recoverer.x-fumbleSpot[0],recoverer.y-fumbleSpot[1])<0.9){recovered=true;recT=el;}}
  const tackled=!fumble&&atGain&&(contact||el>gainT+0.35);                             // Tackle bei Kontakt; sonst kurz danach (kein langes Stehen)
  const done=el>6.8 || (kind==='incomplete'&&arrived&&el>arrTime+0.6) || (kind==='int'&&arrived&&(el>arrTime+1.6||(intD&&intD.y<=-4.5)))
    || (kind==='sack'&&sacked&&qb.y<=yards+0.3) || (td&&atGain) || tackled || (oob&&!td&&el>0.8&&(caught||!isPass))
    || (fumble&&((recovered&&el>recT+0.7)||(fumbled&&el>fumT+3.0)));
  if(!done)_anim[P]=requestAnimationFrame(frame);
  else if(td&&carrier){                                                                 // TD: durchgelaufen, Spiel pausiert -> Kino-Jubel
    if(cam)svg.setAttribute('viewBox','0 0 533 360');                                    // Kamera zurücksetzen für die Jubel-Szene
    celebrate(P,'o'+carrier.i);
    if(!cam)showResult(svg,{kind,yards,td,pt:[carrier.x,carrier.y]});
    if(res.celColor)setTimeout(()=>tdCelebration(svg,res.celColor,res.celDef,onDone),750);          // Schwenk auf den tanzenden Spieler
    else if(onDone)setTimeout(onDone,2200);
  }
  else{
    if(kind==='sack'){downFig(P,'o'+qb.i);D.filter(p=>p.role==='rush'&&Math.hypot(p.x-qb.x,p.y-qb.y)<1.9).sort((a,b)=>Math.hypot(a.x-qb.x,a.y-qb.y)-Math.hypot(b.x-qb.x,b.y-qb.y)).slice(0,2).forEach(p=>downFig(P,'d_'+p.i));}
    else if(kind==='int'&&intD){const hit=O.map(o=>[o,Math.hypot(o.x-intD.x,o.y-intD.y)]).filter(a=>a[1]<1.9).sort((a,b)=>a[1]-b[1]);   // Interceptor wird gestellt
      if(hit.length){downFig(P,'d_'+intD.i);hit.slice(0,2).forEach(a=>downFig(P,'o'+a[0].i));}}
    else if(carrier&&kind!=='incomplete'&&!oob&&!fumble){const near=D.map(p=>[p,Math.hypot(p.x-carrier.x,p.y-carrier.y)]).sort((a,b)=>a[1]-b[1]);
      downFig(P,'o'+carrier.i);const gang=near.filter(a=>a[1]<2.8).slice(0,2);   // Tackle: Ballträger + beteiligte Verteidiger
      if(gang.length)gang.forEach(a=>downFig(P,'d_'+a[0].i));
      else if(near[0]){moveP(P,'d_'+near[0][0].i,carrier.x+0.8,carrier.y-0.5);downFig(P,'d_'+near[0][0].i);}}   // immer ein Tackler (nächster Verfolger) – kein Stehenbleiben/Allein-Flippen
    if(!res.noResult)showResult(svg,{kind,yards,td,fum:fumble,pt:(fumble&&fumbleSpot?fumbleSpot:(carrier?[carrier.x,carrier.y]:(kind==='int'&&intD?[intD.x,intD.y]:(kind==='sack'?[qb.x,vy]:catchPt))))});
    if(onDone)setTimeout(onDone,res.noResult?800:1050);}
 }
 _anim[P]=requestAnimationFrame(frame);
}
function showResult(svg,res){
 const td=res.td;
 const label=res.fum?'FUMBLE! Ball verloren':td?'TOUCHDOWN!':res.kind==='incomplete'?'Incomplete':res.kind==='int'?'INTERCEPTION':res.kind==='sack'?('Sack '+Math.round(res.yards)):((res.yards>=0?'+':'')+Number(res.yards).toFixed(res.kind==='run'?0:1)+' Yds');
 const col=res.fum?'#ef5350':td?'#19e08f':(res.kind==='int'||res.kind==='sack')?'#ef5350':res.kind==='incomplete'?'#cdeede':'#ffd34d';
 const pt=res.pt||[26,5],px=mapX(pt[0]),py=mapY(pt[1]),w=td?108:72,x=Math.min(Math.max(px,54),480),y=py-20;   // Karte direkt am Ballträger (folgt der Kamera)
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
function curProfile(){return localStorage.getItem('gi_profile')||'';}
async function api(path,method){const pr=curProfile();
 if(pr)path+=(path.indexOf('?')>=0?'&':'?')+'profile='+encodeURIComponent(pr);
 return (await fetch(path,{method:method||'GET'})).json();}
async function loadMgr(){
 if(!curProfile()){renderProfile();return;}                 // erst Profil anlegen
 if(!mgrMeta)mgrMeta=await api('/api/fr/meta');
 const s=await api('/api/fr/state');
 if(!s.exists){renderNewTeam();return;}
 renderMgr(s.view);
}
function renderProfile(){
 $('mgr_out').innerHTML='<div class="card"><div class="sec" style="margin-top:0">Profil erstellen</div>'+
  '<div class="note">Spiel dich mit deinem Namen ein — dein Spielstand wird darunter gespeichert. So könnt ihr getrennt spielen und jederzeit weitermachen.</div>'+
  '<div class="controls" style="margin-top:14px"><div><label>Dein Name</label><input id="pf_name" placeholder="z. B. Max" style="width:220px" onkeydown="if(event.keyCode===13)saveProfile()"></div>'+
  '<button onclick="saveProfile()">Weiter ▶</button></div></div>';
 setTimeout(()=>{const i=$('pf_name');if(i)i.focus();},60);
}
function saveProfile(){const n=($('pf_name').value||'').trim();if(!n){alert('Bitte einen Namen eingeben.');return;}localStorage.setItem('gi_profile',n);mgrMeta=null;lastView=null;loadMgr();}
function switchProfile(){if(confirm('Profil wechseln? Dein Spielstand bleibt unter „'+curProfile()+'" gespeichert.')){localStorage.removeItem('gi_profile');mgrMeta=null;lastView=null;loadMgr();}}
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
 tool:'<path d="M14 7a4 4 0 0 1-5 5l-6 6 2 2 6-6a4 4 0 0 1 5-5l-2-2 2-2z"/>',
 train:'<circle cx="12" cy="13" r="7"/><path d="M12 13V8M9 3h6"/>'};
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
   ' <button class="ghost" style="padding:5px 10px" onclick="switchProfile()">👤 '+esc(curProfile())+'</button>'+
   ' <button class="ghost" style="padding:5px 10px" onclick="openTutorial(0)">? Anleitung</button></div></div>'+
   '<div class="kgrid" style="margin-top:14px">'+kpi('Overall',v.ratings.ovr)+kpi('Offense',v.ratings.off)+kpi('Defense',v.ratings.def)+
   kpi('Woche',v.phase==='regular'?(v.week+1)+' / '+v.n_weeks:'—')+'</div>'+
   (v.champion?'<div class="reco champ" style="margin-top:14px"><span><span class="tag">MEISTER</span> <b>'+esc(v.champion)+'</b></span><span class="mut">Saison '+v.season+'</span></div>':'')+
   '</div>';
 // Unter-Navigation
 const tabs=[['dash','Übersicht','grid'],['kader','Team','team'],['train','Training','train'],['liga','Liga','chart'],['transfer','Transfermarkt','swap'],['build','Anlagen','tool']];
 const active=v.phase!=='done'&&!v.week_done;
 const needs={dash:(active&&v.meeting),kader:v.skillpoints>0,train:(active&&!v.week_trained),liga:false,transfer:(v.scout_pts>0),build:false};
 h+='<div class="subnav">'+tabs.map(t=>'<div class="s'+(mgrTab===t[0]?' on':'')+'" data-t="'+t[0]+'" onclick="mgrGo(this.dataset.t)">'+navIcon(t[2])+'<span>'+t[1]+'</span>'+(needs[t[0]]?'<span class="navbadge">!</span>':'')+'</div>').join('')+'</div>';
 h+=(mgrTab==='kader'?secKader(v):mgrTab==='train'?secTraining(v):mgrTab==='liga'?secLiga(v):mgrTab==='build'?secBuild(v):mgrTab==='transfer'?secTransfer(v):secOverview(v));
 $('mgr_out').innerHTML=h;
 if(!document.querySelector('.overlay')&&!$('tutspot'))_releaseBody();   // Sicherheitsnetz: Seite immer scrollbar, wenn kein Overlay offen ist
 if(!v.tutorial_seen && !window._tutShown){window._tutShown=true; openTutorial(0);}   // Meeting öffnet NICHT mehr automatisch — nur per Button im Dashboard
}
function trainIcon(k){const I={team:'<circle cx="12" cy="8" r="3"/><path d="M5 20a7 7 0 0 1 14 0"/>',
 off:'<path d="M12 19V5M6 11l6-6 6 6"/>',def:'<path d="M12 3l7 3v6c0 4-3 7-7 9-4-2-7-5-7-9V6z"/>',
 star:'<path d="M12 3l2.6 5.6L21 9.3l-4.5 4.2L17.6 21 12 17.8 6.4 21l1.1-7.5L3 9.3l6.4-.7z"/>',
 heal:'<path d="M10 3h4v7h7v4h-7v7h-4v-7H3v-4h7z"/>',film:'<path d="M5 5h14v14H5zM5 9h14M9 5v14"/>'};
 return '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2">'+(I[k]||I.team)+'</svg>';}
function secOverview(v){
 let h='';
 // Spielbetrieb
 h+='<div class="card" id="gamecard"><div class="sec" style="margin-top:0">'+(v.phase==='done'?'Saison beendet':(v.is_bye?'Bye Week':(v.phase==='playoffs'?(v.playoff?v.playoff.round:'Playoffs'):'Woche '+(v.week+1))))+'</div>';
 if(v.phase==='done'){h+='<div class="reco champ"><span>Saison beendet'+(v.champion?' · Meister '+esc(v.champion):'')+'.</span></div>'+
   (v.awards&&v.awards.length?'<button onclick="showAwards()">🏆 Award-Show</button> ':'')+'<button class="ghost" onclick="newSeason()">Neue Saison starten</button> ';}
 else if(v.week_done){
   h+='<div class="reco win"><span>Woche ausgewertet'+(v.is_bye?' (Bye Week)':'')+'.</span><span class="mut">bereit für die nächste Woche</span></div>'+
     '<button onclick="nextWeek()">Nächste Woche ▶</button> ';
   if(v.has_last_game)h+='<button class="ghost" onclick="watchLast()">Spiel ansehen</button> ';
 }
 else if(!v.week_trained){
   h+='<div class="reco"><span class="mut">Erst das Wochen-Training absolvieren.</span></div>'+
     '<button data-t="train" onclick="mgrGo(this.dataset.t)">Zum Training ▶</button>';
 }
 else if(v.is_bye){h+='<div class="reco"><span><b>Bye Week</b> — diese Woche kein Spiel</span><span class="mut">Training erledigt — Woche abschließen</span></div>'+
   '<button onclick="simWeek()">Woche abschließen</button> ';}
 else{
   if(v.next)h+='<div class="reco"><span style="display:flex;align-items:center;gap:9px">'+teamLogo(v.next.abbr,v.next.color)+
     '<span>Nächstes Spiel: <b>'+(v.next.home?'vs':'@')+' '+esc(v.next.name)+'</b> <span class="mut" style="display:block;font-size:12px">OVR '+v.next.ovr+' · Off: '+esc(v.next.off_scheme)+' · Def: '+esc(v.next.def_scheme)+'</span></span></span></div>';
   if(v.phase==='playoffs'&&v.playoff)h+='<div class="reco"><span><b>'+esc(v.playoff.round)+'</b> — '+
     v.playoff.pairs.map(p=>esc(p[0])+' vs '+esc(p[1])).join(' · ')+'</span></div>';
   if(v.active_game)h+='<button onclick="resumeGame()">Spiel fortsetzen</button> ';
   else if(v.meeting)h+='<div class="reco"><span class="mut">📋 Erst das Vereinsmeeting abschließen, dann geht es ins Spiel.</span></div><button onclick="openMeeting()">📋 Meeting öffnen</button>';
   else h+='<button onclick="startGame()">Selbst spielen</button> <button class="ghost" onclick="simWeek()">Simulieren</button> ';
 }
 if(v.last_result)h+=renderResult(v.last_result,v.team_name);
 h+='</div>';
 // Wochen-Meeting (offen) – prominent
 if(v.meeting)h+='<div class="card meetcard"><div class="sec" style="margin-top:0">📋 '+esc(v.meeting.title)+' offen</div>'+
   '<div class="note" style="margin-top:0">Wähle dein Wochen-Paket — ein Vorteil plus ein Nachteil.</div>'+
   '<div style="margin-top:10px"><button onclick="openMeeting()">Meeting öffnen</button></div></div>';
 // Matchup-Analyse, Form & Verletzungen
 if(v.phase!=='done'&&!v.is_bye)h+=matchupCard(v);
 h+=formStrip(v);
 h+=injuryCard(v);
 h+=financeCard(v);
 // Saison-Ziele (kompakt)
 if(v.goals&&v.goals.length){h+='<div class="card" id="goalcard"><div class="sec" style="margin-top:0">Saison-Ziele</div>'+
   v.goals.map(g=>{const prog=g.key==='wins'?' ('+g.progress+'/'+g.target+')':'';return '<div class="reco mini'+(g.done?' win':'')+'"><span>'+(g.done?'✓ ':'')+esc(g.label)+prog+'</span><span class="mut">'+(g.done?'erfüllt':'+'+g.reward+' Mio')+'</span></div>';}).join('')+'</div>';}
 // Neuigkeiten (kompakt)
 if(v.events&&v.events.length){h+='<div class="card"><div class="sec" style="margin-top:0">Neuigkeiten</div>'+
   v.events.map(e=>'<div class="reco mini '+(e.type==='bad'?'loss':(e.type==='ok'?'win':''))+'"><span>'+esc(e.text)+'</span></div>').join('')+'</div>';}
 h+='<details class="danger"><summary>⚙️ Einstellungen &amp; Gefahrenbereich</summary><div class="dangerin"><div class="mut" style="margin-bottom:8px">Unwiderrufliche Aktion — der gesamte Franchise-Fortschritt geht verloren.</div><button class="ghost danger-btn" onclick="resetFr()">Franchise zurücksetzen</button></div></details>';
 return h;
}
function secTraining(v){
 const active=v.phase!=='done'&&!v.week_done;
 let h='<div class="card"><div class="sec" style="margin-top:0">Wochen-Training'+(active&&!v.week_trained?' <span class="navbadge">!</span>':'')+'</div>';
 if(!active)h+='<div class="note">Diese Woche ist abgeschlossen — das nächste Training gibt es in der neuen Woche.</div>';
 else if(v.week_trained)h+='<div class="reco win"><span>Training erledigt ✓</span>'+(v.game_bonus>0?'<span class="mut">Film-Bonus aktiv fürs nächste Spiel</span>':'')+'</div>';
 else h+='<div class="note" style="margin-top:0">Wähle <b>ein</b> Training für diese Woche.</div><div class="traingrid">'+v.trainings.map(t=>'<button class="traincard" data-k="'+t.key+'" onclick="trainWeek(this.dataset.k)"><span class="ti">'+trainIcon(t.icon)+'</span><b>'+esc(t.label)+'</b><span class="td">'+esc(t.desc)+'</span>'+(t.exp?'<span class="texp">+'+t.exp+' EXP · '+esc(t.group)+'</span>':(t.group?'<span class="texp">'+esc(t.group)+'</span>':''))+'</button>').join('')+'</div>';
 h+='</div>';
 // Team-Schema
 const offk=Object.keys(v.off_schemes),defk=Object.keys(v.def_schemes);
 h+='<div class="card"><div class="sec" style="margin-top:0">Team-Schema</div><div class="controls">'+
   '<div><label>Offense-Schema</label><select id="sc_off">'+offk.map(k=>'<option'+(k===v.scheme.off?' selected':'')+'>'+esc(k)+'</option>').join('')+'</select></div>'+
   '<div><label>Defense-Schema</label><select id="sc_def">'+defk.map(k=>'<option'+(k===v.scheme.def?' selected':'')+'>'+esc(k)+'</option>').join('')+'</select></div>'+
   '<button onclick="setScheme()">Übernehmen</button></div>'+
   '<div class="note">Off: '+esc((v.off_schemes[v.scheme.off]||[]).join(', '))+'<br>Def: '+esc((v.def_schemes[v.scheme.def]||[]).join(', '))+'</div></div>';
 // Trainerstab
 h+='<div class="sec">Trainerstab</div>';
 v.coaches.forEach(c=>{const mk=v.coach_market[c.role]||[];
   h+='<div class="card"><div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">'+
     '<div><b>'+esc(c.label)+'</b> · '+esc(c.name)+' <span class="mut">'+c.rating+' OVR</span></div>'+
     '<button data-r="'+c.role+'" onclick="improveCoach(this.dataset.r)" '+(v.budget<c.improve_cost?'disabled':'')+'>Verbessern ('+c.improve_cost+' Mio)</button></div>'+
     '<div class="ctraits">'+c.traits.map(t=>'<div class="ctrait"><span>'+esc(t.label)+'</span><span class="abar"><span class="afill" style="width:'+Math.round(t.val/99*100)+'%"></span></span><span class="aval">'+t.val+'</span></div>').join('')+'</div>';
   if(mk.length){h+='<div class="note" style="margin-top:8px">Verfügbar:</div>';
     mk.forEach(cd=>{h+='<div class="reco"><span>'+esc(cd.name)+' <span class="mut">'+cd.rating+' · '+cd.traits.map(t=>t.label[0]+t.val).join(' ')+'</span></span>'+
       '<button data-r="'+c.role+'" data-i="'+cd.idx+'" onclick="hireCoach(this.dataset.r,this.dataset.i)" '+(v.budget<cd.cost?'disabled':'')+'>Anheuern ('+cd.cost+' Mio)</button></div>';});}
   h+='</div>';});
 return h;
}
function secLiga(v){return leagueTable(v)+secStats(v);}
let _ltSort='rank';
function ltSort(c){_ltSort=c;renderMgr(lastView);}
function leagueTable(v){const rows=(v.standings||[]).slice();if(!rows.length)return '';
 const asc={rank:1,l:1,pa:1},key=({rank:'rank',w:'w',l:'l',diff:'diff',pf:'pf',pa:'pa',ovr:'ovr'})[_ltSort]||'rank';
 rows.sort((a,b)=>asc[_ltSort]?(a[key]-b[key]):(b[key]-a[key]));
 const th=(c,lbl)=>'<th data-c="'+c+'" onclick="ltSort(this.dataset.c)" class="srt'+(_ltSort===c?' on':'')+'">'+lbl+(_ltSort===c?' ▾':'')+'</th>';
 let h='<div class="card scroll"><div class="sec" style="margin-top:0">Liga-Tabelle <span class="mut" style="font-weight:600;font-size:11px;text-transform:none;letter-spacing:0">· Spalte = sortieren · Team = scouten</span></div>'+
  '<table class="tbl lt"><tr><th class="cn">#</th><th class="cn">Team</th>'+th('w','S')+th('l','N')+th('diff','Diff')+th('pf','PF')+th('pa','PA')+th('ovr','OVR')+'</tr>';
 rows.forEach(t=>{const po=t.rank<=4;
   h+='<tr class="ltrow'+(t.user?' me':'')+(po?' po':'')+'" data-a="'+esc(t.abbr)+'" onclick="scoutTeamRow(this.dataset.a)">'+
     '<td>'+(po?'<span class="podot" title="Playoff-Platz"></span>':'')+t.rank+'</td>'+
     '<td class="cn">'+teamLogo(t.abbr,t.color)+' <span style="vertical-align:middle">'+esc(t.name)+'</span></td>'+
     '<td>'+t.w+'</td><td>'+t.l+'</td><td>'+(t.diff>=0?'+':'')+t.diff+'</td><td>'+t.pf+'</td><td>'+t.pa+'</td><td><b>'+t.ovr+'</b></td></tr>'+
     '<tr class="ltdrow"><td colspan="8" style="padding:0;border:0"><div id="ltd_'+esc(t.abbr)+'"></div></td></tr>';});
 h+='</table><div class="note"><span class="podot"></span> Playoff-Platz (Top 4)</div></div>';
 return h;
}
function scoutReportHTML(t,sv){sv=sv||lastView||{};const all=(sv.standings||[]),me=sv.ratings||{},N=all.length||1;
 const offRank=all.slice().sort((a,b)=>b.off-a.off).findIndex(x=>x.abbr===t.abbr)+1;
 const defRank=all.slice().sort((a,b)=>b.def-a.def).findIndex(x=>x.abbr===t.abbr)+1;
 const offs=all.map(x=>x.off),defs=all.map(x=>x.def);
 const omin=offs.length?Math.min(...offs):t.off,omax=offs.length?Math.max(...offs):t.off;
 const dmin=defs.length?Math.min(...defs):t.def,dmax=defs.length?Math.max(...defs):t.def;
 const pc=(v,lo,hi)=>Math.round((v-lo)/((hi-lo)||1)*100);
 const bar=(lbl,val,rank,p,acc)=>'<div class="scrow"><span class="scl">'+lbl+'</span><span class="scbar"><span class="scfill" style="width:'+Math.max(7,p)+'%;background:'+acc+'"></span></span><span class="scv">'+val+' <small>#'+rank+'/'+N+'</small></span></div>';
 const tier=t.ovr>=84?'Titelkandidat':t.ovr>=76?'Playoff-Team':t.ovr>=68?'Mittelfeld':'Aufbau-Team';
 let tip='';if(me.def!=null&&me.off!=null){const offThreat=t.off-me.def,defThreat=t.def-me.off;
   tip=offThreat>defThreat+3?'Ihre Offense ist die größere Gefahr → stärke deine Defense, wähle sichere Coverages.'
     :defThreat>offThreat+3?'Ihre Defense ist stark → setze auf Lauf-Balance und kurze, sichere Pässe.'
     :'Ausgeglichener Gegner — Schema-Disziplin entscheidet.';}
 return '<div class="scoutbox"><div class="schd"><b>Scouting · '+esc(t.name)+'</b><span class="scbadge">'+tier+'</span></div>'+
   '<div class="mut" style="margin:1px 0 7px">Bilanz '+t.w+'–'+t.l+' · '+t.pf+':'+t.pa+' Pkt · '+t.ovr+' OVR'+(t.user?'':(me.ovr!=null?' · dein Vorsprung '+(me.ovr-t.ovr>=0?'+':'')+(me.ovr-t.ovr):''))+'</div>'+
   bar('Offense',t.off,offRank,pc(t.off,omin,omax),'#19e08f')+
   bar('Defense',t.def,defRank,pc(t.def,dmin,dmax),'#5fa8ff')+
   '<div class="mut" style="margin-top:5px">Schema: Off '+esc(t.off_scheme||'?')+' · Def '+esc(t.def_scheme||'?')+'</div>'+
   (tip&&!t.user?'<div class="sctip">▸ '+tip+'</div>':'')+'</div>';}
function scoutTeamRow(abbr){const d=$('ltd_'+abbr);if(!d)return;if(d.innerHTML){d.innerHTML='';return;}
 const t=((lastView&&lastView.standings)||[]).find(x=>x.abbr===abbr);if(!t)return;
 d.innerHTML=scoutReportHTML(t,lastView);}
function _winProb(my,opp,home){let p=1/(1+Math.pow(10,(opp-my)/14));if(home)p+=0.05;return Math.max(.05,Math.min(.95,p));}
function _vsbar(label,mine,opp){const t=(mine+opp)||1,mp=Math.round(mine/t*100);
 return '<div class="vsrow"><span class="vsl">'+esc(label)+'</span><span class="vsbar"><span class="vsmine" style="width:'+mp+'%"></span></span><span class="vsv">'+mine+'<small>:'+opp+'</small></span></div>';}
function matchupCard(v){const n=v.next;if(!n)return '';const me=v.ratings,wp=Math.round(_winProb(me.ovr,n.ovr,n.home)*100),edge=me.ovr-n.ovr;
 return '<div class="card matchup"><div class="sec" style="margin-top:0">⚔️ Matchup-Analyse</div>'+
  '<div class="mvs">'+
    '<div class="mteam"><div class="crest sm" style="background:'+esc(v.color)+'">'+esc(v.abbr)+'</div><b>Du</b><span class="mut">OVR '+me.ovr+'</span></div>'+
    '<div class="mvsmid"><span class="mut">'+(n.home?'Heim vs':'Auswärts @')+'</span><div class="wpbig">'+wp+'%</div><span class="mut">Sieg-Chance</span></div>'+
    '<div class="mteam r"><span style="display:flex;align-items:center;gap:8px;flex-direction:row-reverse">'+teamLogo(n.abbr,n.color,'lg')+'<b>'+esc(n.name)+'</b></span><span class="mut">OVR '+n.ovr+'</span></div>'+
  '</div>'+
  _vsbar('Deine Offense → ihre Defense',me.off,n.def)+
  _vsbar('Deine Defense → ihre Offense',me.def,n.off)+
  '<div class="note">Ihr Schema: Off '+esc(n.off_scheme)+', Def '+esc(n.def_scheme)+' · '+(edge>=6?'Du bist Favorit.':edge<=-6?'Außenseiter — du brauchst einen guten Plan.':'Ausgeglichenes Spiel.')+'</div></div>';}
function formStrip(v){const f=v.form||[];if(!f.length)return '';
 const chips=f.map(g=>'<span class="formchip '+(g.won?'w':'l')+'" title="W'+g.week+' '+(g.home?'vs ':'@ ')+esc(g.opp)+' '+g.pf+':'+g.pa+'">'+(g.won?'S':'N')+'</span>').join('');
 const wins=f.filter(g=>g.won).length,W=160,H=34,mx=Math.max(10,...f.map(g=>Math.max(g.pf,g.pa)));
 const line=(key,col)=>{let d='';f.forEach((g,i)=>{const x=f.length>1?i/(f.length-1)*W:0,y=H-g[key]/mx*H;d+=(i?'L':'M')+x.toFixed(1)+' '+y.toFixed(1)+' ';});return '<path d="'+d+'" fill="none" stroke="'+col+'" stroke-width="2"/>';};
 return '<div class="card"><div class="sec" style="margin-top:0">📈 Form & Verlauf</div>'+
  '<div class="formrow"><span class="formchips">'+chips+'</span><span class="mut">'+wins+'–'+(f.length-wins)+' (letzte '+f.length+')</span></div>'+
  '<svg class="spark" viewBox="0 0 '+W+' '+H+'" width="100%" height="42" preserveAspectRatio="none">'+line('pf','#19e08f')+line('pa','#ef5350')+'</svg>'+
  '<div class="note"><span style="color:#19e08f">●</span> erzielt · <span style="color:#ef5350">●</span> kassiert</div></div>';}
function injuryCard(v){const inj=(v.roster||[]).filter(p=>p.inj>0).sort((a,b)=>b.inj-a.inj);if(!inj.length)return '';
 return '<div class="card"><div class="sec" style="margin-top:0">🩹 Verletzungs-Report ('+inj.length+')</div>'+
  inj.map(p=>'<div class="reco mini" data-i="'+p.id+'" onclick="openPlayer(this.dataset.i)" style="cursor:pointer"><span style="display:flex;align-items:center;gap:8px">'+posBadge(p.pos)+esc(p.name)+'</span><span class="tag tg-inj">noch '+p.inj+' Wo</span></div>').join('')+
  '<div class="note">„Regeneration"-Training verkürzt Ausfälle um 1 Woche.</div></div>';}
function financeCard(v){const inc=(v.stadium&&v.stadium.income)||0;
 const remain=(v.phase==='regular'&&v.n_weeks!=null)?Math.max(0,v.n_weeks-(v.week+1)):0;
 const proj=v.budget+inc*remain;
 return '<div class="card"><div class="sec" style="margin-top:0">💰 Finanzen</div>'+
  '<div class="kgrid">'+kpi('Budget',v.budget+' Mio')+kpi('Einnahmen/Wo','+'+inc+' Mio')+kpi('Stadion-Stufe',v.stadium.level)+kpi('Prognose Saisonende',proj+' Mio')+'</div>'+
  '<div class="note">Stadion ausbauen steigert die Wocheneinnahmen ('+(remain>0?remain+' Wochen verbleiben':'Saison läuft aus')+'). Budget fließt in Ausbauten, Coaches & Transfers.</div></div>';}
let _kSort='ovr',_kFilter='all';
function kSort(s){_kSort=s;renderMgr(lastView);}
function kFilter(f){_kFilter=f;renderMgr(lastView);}
function _kApply(ps){let a=ps.slice();
 if(_kFilter==='starter')a=a.filter(p=>p.starter);
 else if(_kFilter==='bench')a=a.filter(p=>!p.starter);
 else if(_kFilter==='injured')a=a.filter(p=>p.inj>0);
 else if(_kFilter==='dev')a=a.filter(p=>p.ovr<p.pot);
 const key={ovr:p=>p.ovr,pot:p=>p.pot,age:p=>-p.age,form:p=>playerImpact(p)}[_kSort]||(p=>p.ovr);
 return a.sort((x,y)=>key(y)-key(x));}
let _kView='list';
function kView(x){_kView=x;renderMgr(lastView);}
function depthChart(v){let h='<div class="card"><div class="sec" style="margin-top:0">Aufstellung (Depth Chart)</div><div class="note" style="margin-top:0">Pro Position: Starter (ST) zuoberst, danach die Backups nach OVR. Tippe einen Spieler an.</div>';
 [['Offense',['QB','RB','WR','OL']],['Defense',['DL','LB','DB']],['Special Teams',['K']]].forEach(grp=>{
   h+='<div class="dcgrphd">'+grp[0]+'</div>';
   grp[1].forEach(pos=>{const ps=v.roster.filter(p=>p.pos===pos).sort((a,b)=>(b.starter-a.starter)||(b.ovr-a.ovr));if(!ps.length)return;
     h+='<div class="dcpos"><div class="dchead">'+posBadge(pos)+'</div><div class="dclist">'+
       ps.map((p,i)=>'<div class="dcrow'+(p.starter?' st':'')+(p.inj>0?' hurt':'')+'" data-i="'+p.id+'" onclick="openPlayer(this.dataset.i)">'+
         '<span class="dcslot">'+(p.starter?'ST':(i+1))+'</span>'+ovrBadge(p.ovr)+
         '<span class="dcn">'+esc(p.name)+(p.inj>0?' <span class="tag tg-inj">'+p.inj+'W</span>':'')+'</span>'+
         '<span class="mut" style="font-size:12px">'+p.age+'J · Pot '+p.pot+'</span></div>').join('')+
       '</div></div>';});});
 return h+'</div>';}
function secKader(v){
 const total=v.roster.length,starters=v.roster.filter(p=>p.starter).length,inj=v.roster.filter(p=>p.inj>0).length;
 const avgAge=total?Math.round(v.roster.reduce((s,p)=>s+p.age,0)/total):0;
 let h='<div class="card"><div class="sec" style="margin-top:0">Kader-Übersicht</div>'+
   '<div class="kgrid">'+kpi('Skillpunkte',v.skillpoints)+kpi('Overall',v.ratings.ovr)+kpi('Starter',starters)+kpi('Ø Alter',avgAge)+kpi('Verletzt',inj)+kpi('Kader',total)+'</div>'+
   (v.skillpoints>0?'<div style="margin-top:12px"><button onclick="allocAll()">Alle Skillpunkte auto-verteilen ('+v.skillpoints+')</button></div>':'')+
   '<div class="note">Je 100 EXP = 1 Skillpunkt (aus Wochen-Training & Spiel-Leistung). Tippe einen Spieler an, um Punkte auf Attribute zu verteilen.</div></div>';
 // Ansicht-/Sortier-/Filter-Leiste
 h+='<div class="card kbar"><div class="kbarrow"><span class="kbl">Ansicht</span>'+
   [['list','Liste'],['depth','Aufstellung']].map(x=>'<button class="chip'+(_kView===x[0]?' on':'')+'" data-v="'+x[0]+'" onclick="kView(this.dataset.v)">'+x[1]+'</button>').join('')+'</div>'+
   (_kView==='list'?('<div class="kbarrow"><span class="kbl">Sortieren</span>'+
     [['ovr','OVR'],['pot','Potenzial'],['age','Alter'],['form','Form']].map(s=>'<button class="chip'+(_kSort===s[0]?' on':'')+'" data-s="'+s[0]+'" onclick="kSort(this.dataset.s)">'+s[1]+'</button>').join('')+'</div>'+
     '<div class="kbarrow"><span class="kbl">Filter</span>'+
     [['all','Alle'],['starter','Starter'],['bench','Bank'],['injured','Verletzt'],['dev','Entwicklung']].map(f=>'<button class="chip'+(_kFilter===f[0]?' on':'')+'" data-f="'+f[0]+'" onclick="kFilter(this.dataset.f)">'+f[1]+'</button>').join('')+'</div>'):'')+'</div>';
 if(_kView==='depth')return h+depthChart(v);
 [['Offense',['QB','RB','WR','OL']],['Defense',['DL','LB','DB']],['Special Teams',['K']]].forEach(grp=>{
   let body='';
   grp[1].forEach(pos=>{const ps=_kApply(v.roster.filter(p=>p.pos===pos));if(!ps.length)return;
     body+='<div style="margin:12px 0 4px">'+posBadge(pos)+' <span class="mut" style="font-weight:700">'+pos+'</span> <span class="mut" style="font-size:11px">· '+ps.length+'</span></div>';
     ps.forEach(p=>{const bar=Math.round(p.ovr/Math.max(p.pot,1)*100);
       body+='<div class="prow" data-i="'+p.id+'" onclick="openPlayer(this.dataset.i)">'+
        '<span class="pfa">'+portrait(p,38,v.color)+'</span>'+ovrBadge(p.ovr)+
        '<span class="pname">'+esc(p.name)+(p.starter?' <span class="tag tg-start">START</span>':'')+(p.inj>0?' <span class="tag tg-inj">VERLETZT '+p.inj+'W</span>':'')+
        '<span class="mut" style="display:block;font-size:12px">Alter '+p.age+' · Pot '+p.pot+(p.season&&p.season.games?' · '+p.season.games+' Sp.':'')+'<div class="ovrbar"><div class="ovrfill" style="width:'+bar+'%"></div></div></span></span>'+
        (p.pts>0?'<span class="ptbadge">'+p.pts+' P</span>':'<span class="mut" style="font-size:12px">'+p.exp+'/100</span>')+'</div>';});
   });
   if(body)h+='<div class="card"><div class="sec" style="margin-top:0">'+grp[0]+'</div>'+body+'</div>';});
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
 const tc=(lastView&&lastView.color)||'#16c784';
 const peak=p.age<25?'Aufsteigend':(p.age<=29?'Im Peak':'Routinier');
 // Positions-Schnitt je Attribut (aus dem eigenen Kader)
 const peers=(lastView&&lastView.roster||[]).filter(x=>x.pos===p.pos);
 const avg={};peers.forEach(x=>(x.attrs||[]).forEach(a=>{(avg[a.key]=avg[a.key]||[]).push(a.val);}));
 const avgOf=k=>avg[k]&&avg[k].length?Math.round(avg[k].reduce((s,n)=>s+n,0)/avg[k].length):null;
 // Stärken (Top 2 Attribute)
 const strong=new Set(p.attrs.slice().sort((a,b)=>b.val-a.val).slice(0,2).map(a=>a.key));
 let h='<div class="modalhead"><h3 style="display:flex;align-items:center;gap:10px"><span class="pfa">'+portrait(p,46,tc)+'</span>'+ovrBadge(p.ovr)+posBadge(p.pos)+esc(p.name)+devBadge(p.dev,p.dev_label)+
   '<span class="mut" style="font-weight:600;font-size:13px">'+(p.starter?'Starter':'Bank')+(p.inj>0?' · verletzt '+p.inj+'W':'')+'</span></h3>'+
   '<button class="ghost" onclick="closePlayer()">Schließen</button></div>'+
   '<div class="kgrid">'+kpi('OVR',p.ovr)+kpi('Potenzial',p.pot)+kpi('Alter',p.age+' · '+peak)+kpi('Skillpunkte',p.pts)+'</div>';
 if(p.pts>0)h+='<div class="stepsel"><span class="kbl">Punkte pro Klick</span>'+[1,5].map(n=>'<button class="chip sm'+(_allocStep===n?' on':'')+'" data-n="'+n+'" onclick="setStep(this.dataset.n)">×'+n+'</button>').join('')+'<button class="chip sm" onclick="autoAlloc()">Auto</button></div>';
 h+='<div class="pcols">';
 // Radar (Teamfarbe)
 h+='<div class="radarwrap">'+radarSVG(p.attrs,tc)+'</div>';
 // Attribut-Balken mit Positions-Schnitt-Marker + Stärke-Markierung
 h+='<div class="attrs">';
 p.attrs.forEach(a=>{const pc=Math.round(a.val/99*100),cap=Math.round(a.cap/99*100);const full=a.val>=a.cap;
   const av=avgOf(a.key),avp=av!=null?Math.round(av/99*100):null,st=strong.has(a.key);
   h+='<div class="arow"><span class="alab'+(st?' strong':'')+'">'+(st?'★ ':'')+esc(a.label)+'</span>'+
     '<span class="abar"><span class="afill" style="width:'+pc+'%"></span><span class="acap" style="left:'+cap+'%"></span>'+
     (avp!=null?'<span class="aavg" style="left:'+avp+'%" title="Positions-Schnitt '+av+'"></span>':'')+'</span>'+
     '<span class="aval">'+a.val+(av!=null?'<small>'+(a.val>=av?'+':'')+(a.val-av)+'</small>':'')+'</span>'+
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
function _rgba(hex,a){hex=(hex||'#16c784').replace('#','');if(hex.length===3)hex=hex.split('').map(c=>c+c).join('');const n=parseInt(hex,16);return 'rgba('+((n>>16)&255)+','+((n>>8)&255)+','+(n&255)+','+a+')';}
function radarSVG(attrs,col){col=col||'#16c784';const n=attrs.length,cx=85,cy=85,R=62;let pts='',axes='',rings='';
 [0.33,0.66,1].forEach(f=>{let rp='';for(let i=0;i<n;i++){const ang=-Math.PI/2+i*2*Math.PI/n;rp+=(cx+Math.cos(ang)*R*f).toFixed(1)+','+(cy+Math.sin(ang)*R*f).toFixed(1)+' ';}rings+='<polygon points="'+rp.trim()+'" fill="none" stroke="#26352e" stroke-width="1"/>';});
 for(let i=0;i<n;i++){const ang=-Math.PI/2+i*2*Math.PI/n;const rr=R*Math.max(.12,attrs[i].val/99);
   const x=cx+Math.cos(ang)*rr,y=cy+Math.sin(ang)*rr;pts+=x.toFixed(1)+','+y.toFixed(1)+' ';
   const ex=cx+Math.cos(ang)*R,ey=cy+Math.sin(ang)*R;
   axes+='<line x1="'+cx+'" y1="'+cy+'" x2="'+ex.toFixed(1)+'" y2="'+ey.toFixed(1)+'" stroke="#26352e"/>'+
     '<text x="'+(cx+Math.cos(ang)*(R+10)).toFixed(1)+'" y="'+(cy+Math.sin(ang)*(R+10)+3).toFixed(1)+'" font-size="8" fill="#8d9d97" text-anchor="middle">'+esc(attrs[i].key)+'</text>';}
 return '<svg viewBox="0 0 170 170" width="170" height="170">'+rings+axes+
   '<polygon points="'+pts.trim()+'" fill="'+_rgba(col,.28)+'" stroke="'+col+'" stroke-width="2"/></svg>';
}
let _allocStep=1;
function setStep(n){_allocStep=+n;const p=lastView&&lastView.roster.find(x=>String(x.id)===String(_curPid));if(p)renderPlayer(p);}
async function allocAttr(k){const p=curPlayer();let r=null;
 for(let i=0;i<_allocStep;i++){r=await api('/api/fr/alloc?pid='+p+'&attr='+k,'POST');
   if(r.result&&r.result.error){if(i===0)alert(r.result.error);break;}
   const pl=r.view&&r.view.roster&&r.view.roster.find(x=>String(x.id)===String(p));
   if(pl&&pl.pts<=0)break;}                                  // keine Punkte mehr -> stoppen
 afterPlayer(r);}
async function autoAlloc(){const r=await api('/api/fr/alloc_auto?pid='+curPlayer(),'POST');afterPlayer(r);}
async function toggleStarter(){const r=await api('/api/fr/starter?pid='+curPlayer(),'POST');if(r.result&&r.result.error)alert(r.result.error);afterPlayer(r);}
let _curPid=null;
function curPlayer(){return _curPid;}
function afterPlayer(r){if(r.view){lastView=r.view;renderMgr(r.view);const p=r.view.roster.find(x=>String(x.id)===String(_curPid));if(p)renderPlayer(p);}}
function closePlayer(){const o=$('playeroverlay');if(o)o.remove();_curPid=null;unlockBodyIfNone();}
let _dSort='proj',_dFilter='all';
function dSort(s){_dSort=s;renderMgr(lastView);}
function dFilter(f){_dFilter=f;renderMgr(lastView);}
function _needOpen(v){const cnt={};(v.roster||[]).forEach(p=>cnt[p.pos]=(cnt[p.pos]||0)+1);const need={};
 Object.keys(v.slots||{}).forEach(pos=>{need[pos]=Math.max(0,(v.slots[pos]||0)-(cnt[pos]||0));});return need;}
function scoutDetail(pid){const d=$('pd_'+pid);if(!d)return;if(d.innerHTML){d.innerHTML='';return;}
 const p=((lastView&&lastView.prospects)||[]).find(x=>String(x.id)===String(pid));if(!p)return;
 const next=p.scout<1?'Stufe 1 deckt den Namen auf.':p.scout<2?'Stufe 2 zeigt Wertung, größte Stärke & Risiko.':p.scout<3?'Stufe 3 verengt die Spanne und deckt den Entwicklungs-Trait auf.':'Voll gescoutet — Restunsicherheit bleibt: der echte Wert zeigt sich erst im Team.';
 let h='<div class="scoutbox"><div class="schd"><b>Scouting-Bericht · '+esc(p.name)+'</b>'+(p.grade&&p.grade!=='?'?'<span class="scbadge">'+esc(p.grade)+'</span>':'')+'</div>'+
   '<div class="mut" style="margin:2px 0 6px">'+esc(p.round)+' · Alter '+p.age+' · gescoutet '+p.scout+'/'+p.scout_max+'</div>'+
   '<div class="scrow"><span class="scl">OVR-Spanne</span><span class="scbar"><span class="scfill" style="width:'+Math.round((p.ovr_hi-50)/49*100)+'%;background:#19e08f"></span></span><span class="scv">'+p.ovr_lo+'–'+p.ovr_hi+'</span></div>'+
   '<div class="scrow"><span class="scl">Ceiling</span><span class="scbar"><span class="scfill" style="width:'+Math.round((p.pot_hi-50)/49*100)+'%;background:#5fa8ff"></span></span><span class="scv">'+p.pot_lo+'–'+p.pot_hi+'</span></div>';
 if(p.strength)h+='<div class="mut" style="margin-top:5px">Größte Stärke: '+esc(p.strength)+(p.dev?' · Trait: '+esc(p.dev_label||''):'')+'</div>';
 if(p.risk)h+='<div class="sctip">▸ '+esc(p.risk)+' — Draften bleibt eine Wette innerhalb der Spanne.</div>';
 else h+='<div class="mut" style="margin-top:5px">'+next+'</div>';
 d.innerHTML=h+'</div>';}
function secTransfer(v){
 const cnt={};v.roster.forEach(p=>cnt[p.pos]=(cnt[p.pos]||0)+1);
 const _fneed=_needOpen(v);
 // --- College-Scouting & Draft (Kopf-Feature) ---
 const sp=v.scout_pts||0;
 let h='<div class="card"><div class="schead"><div class="sec" style="margin:0">College-Scouting — Draft</div>'+
   '<div class="scoutpts"><span class="v">'+sp+'</span><span class="l">Punkte</span></div></div>'+
   '<div class="note">Scouting (1 Punkt/Stufe) <b>verengt nur die Spanne</b> und deckt Profil &amp; Risiko auf — den exakten Wert siehst du nie, Draften bleibt eine Wette. Punkte sind knapp (ca. +1/Woche, max. 12) — priorisiere deine Wunsch-Talente.</div></div>';
 const pros=v.prospects||[];const need=_needOpen(v);
 const needList=Object.keys(need).filter(p=>need[p]>0);
 if(needList.length)h+='<div class="card"><div class="sec" style="margin-top:0">Kaderbedarf</div><div class="needrow">'+needList.sort((a,b)=>need[b]-need[a]).map(p=>'<span class="needtag">'+posBadge(p)+' '+need[p]+' frei</span>').join('')+'</div></div>';
 if(!pros.length)h+='<div class="card empty">🎓 Aktuell keine College-Prospects verfügbar — der Draft-Pool füllt sich zur nächsten Saison.</div>';
 else{
   h+='<div class="card kbar"><div class="kbarrow"><span class="kbl">Big Board</span>'+
     [['proj','Projektion'],['grade','Wertung'],['scout','Gescoutet']].map(s=>'<button class="chip'+(_dSort===s[0]?' on':'')+'" data-s="'+s[0]+'" onclick="dSort(this.dataset.s)">'+s[1]+'</button>').join('')+'</div>'+
     '<div class="kbarrow"><span class="kbl">Filter</span>'+
     [['all','Alle'],['need','Bedarf'],['unsc','Ungescoutet'],['full','Fertig']].map(f=>'<button class="chip'+(_dFilter===f[0]?' on':'')+'" data-f="'+f[0]+'" onclick="dFilter(this.dataset.f)">'+f[1]+'</button>').join('')+'</div></div>';
   let board=pros.slice();
   if(_dFilter==='need')board=board.filter(p=>need[p.pos]>0);
   else if(_dFilter==='unsc')board=board.filter(p=>p.scout<p.scout_max);
   else if(_dFilter==='full')board=board.filter(p=>p.scout>=p.scout_max);
   const projOf=p=>((p.pot_lo+p.pot_hi)/2);
   const skey={proj:projOf,grade:p=>(p.ovr_lo+p.ovr_hi)/2,scout:p=>p.scout}[_dSort]||projOf;
   board.sort((a,b)=>skey(b)-skey(a));
   h+='<div class="card"><div class="sec" style="margin-top:0">Draft Big Board ('+board.length+') <span class="mut" style="font-weight:600;font-size:11px;text-transform:none;letter-spacing:0">· Zeile tippen = Bericht</span></div>';
   board.forEach((p,rank)=>{const full=(cnt[p.pos]||0)>=v.slots[p.pos];const done=p.scout>=p.scout_max;
     const ovrTxt='OVR '+p.ovr_lo+'–'+p.ovr_hi+' · Pot '+p.pot_lo+'–'+p.pot_hi;
     const dev=(p.dev?' '+devBadge(p.dev,p.dev_label):'');
     const extra=(p.grade&&p.grade!=='?'?' · '+esc(p.grade):'')+(p.risk?' · '+esc(p.risk):'');
     h+='<div class="prow prospect" data-i="'+p.id+'" onclick="scoutDetail(this.dataset.i)">'+
       '<span class="bbrank">'+(rank+1)+'</span><span class="pfa">'+portrait(p,34,v.color)+'</span>'+posBadge(p.pos)+
       '<span class="pname"><span class="nm">'+esc(p.name)+'</span>'+dev+(need[p.pos]>0?' <span class="tag tg-need">BEDARF</span>':'')+
       '<span class="mut" style="display:block;font-size:12px">'+ovrTxt+' · '+esc(p.round)+extra+'</span>'+scoutDots(p.scout,p.scout_max)+'</span>'+
       '<span class="act" onclick="event.stopPropagation()">'+
       '<button class="ghost" data-i="'+p.id+'" onclick="scoutP(this.dataset.i)" '+((sp<1||done)?'disabled':'')+'>'+(done?'✓':'Scouten')+'</button>'+
       '<button data-i="'+p.id+'" onclick="draftP(this.dataset.i)" '+((v.budget<p.cost||full)?'disabled':'')+'>'+(full?'voll':'Draft '+p.cost)+'</button>'+
       '</span></div><div class="pddet" id="pd_'+p.id+'"></div>';});
   h+='</div>';}
 // --- Free Agents (sofort einsatzbereit, voll sichtbar) ---
 h+='<div class="card"><div class="sec" style="margin-top:0">Free Agents</div>'+
   '<div class="note">Fertige Spieler mit bekannten Werten. Position voll? Erst im Kader jemanden entlassen.</div></div>';
 [['Offense',['QB','RB','WR','OL']],['Defense',['DL','LB','DB']],['Special Teams',['K']]].forEach(grp=>{
   const ps=v.market_players.filter(p=>grp[1].includes(p.pos));if(!ps.length)return;
   h+='<div class="card"><div class="sec" style="margin-top:0">'+grp[0]+'</div>';
   ps.forEach(p=>{const full=(cnt[p.pos]||0)>=v.slots[p.pos];
     h+='<div class="reco"><span style="display:flex;align-items:center;gap:9px"><span class="pfa">'+portrait(p,34,v.color)+'</span>'+ovrBadge(p.ovr)+posBadge(p.pos)+'<span><b>'+esc(p.name)+'</b>'+(_fneed[p.pos]>0?' <span class="tag tg-need">BEDARF</span>':'')+' <span class="mut" style="display:block;font-size:12px">Alter '+p.age+' · Pot '+p.pot+'</span></span></span>'+
       '<button data-i="'+p.id+'" onclick="signP(this.dataset.i)" '+((v.budget<p.cost||full)?'disabled':'')+'>'+(full?p.pos+' voll':'Verpflichten ('+p.cost+' Mio)')+'</button></div>';});
   h+='</div>';});
 return h;
}
function leagueLeaders(v){const s=(v.standings||[]);if(!s.length)return '';
 const top=(cmp)=>s.slice().sort(cmp)[0];
 const byPF=top((a,b)=>b.pf-a.pf),byPA=top((a,b)=>a.pa-b.pa),byRec=top((a,b)=>(b.w-b.l)-(a.w-a.l)||b.diff-a.diff),byOvr=top((a,b)=>b.ovr-a.ovr);
 const row=(lbl,t,val)=>'<div class="reco"><span style="display:flex;align-items:center;gap:9px">'+teamLogo(t.abbr,t.color)+'<b>'+esc(t.name)+'</b>'+(t.user?' <span class="tag tg-start">DU</span>':'')+'</span><span class="mut">'+lbl+' · <b style="color:var(--fg)">'+val+'</b></span></div>';
 return '<div class="card"><div class="sec" style="margin-top:0">🏆 Liga-Spitze</div>'+
   row('Beste Offense',byPF,byPF.pf+' Pkt')+row('Beste Defense',byPA,byPA.pa+' kassiert')+
   row('Beste Bilanz',byRec,byRec.w+'–'+byRec.l)+row('Stärkster Kader',byOvr,byOvr.ovr+' OVR')+'</div>';}
function secStats(v){
 const R=v.roster;
 let h0=leagueLeaders(v);
 const leader=(key,fmt)=>{let best=null;R.forEach(p=>{if(!best||p.season[key]>best.season[key])best=p;});
   return best&&best.season[key]>0?'<div class="reco"><span style="display:flex;align-items:center;gap:9px">'+posBadge(best.pos)+'<b>'+esc(best.name)+'</b></span><span>'+fmt(best.season)+'</span></div>':'';};
 let h=h0+'<div class="card"><div class="sec" style="margin-top:0">Saison-Bestenliste (dein Team)</div>'+
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
 else h+='<div class="card empty">📊 Noch keine Spiele gewertet — spiele oder simuliere eine Woche, dann erscheinen hier die Saison-Statistiken.</div>';
 // Hall of Fame / Historie
 if(v.history&&v.history.length){h+='<div class="card"><div class="sec" style="margin-top:0">🏆 Hall of Fame / Historie</div>'+
   v.history.slice().reverse().map(x=>'<div class="reco"><span><span class="tag">S'+x.season+'</span> Meister: <b>'+esc(x.champion)+'</b></span><span class="mut">'+(x.mvp?'MVP '+esc(x.mvp):'')+'</span></div>').join('')+'</div>';}
 if(v.phase==='done'&&v.awards&&v.awards.length){h+='<div style="margin-top:8px"><button onclick="showAwards()">🏆 Award-Show ansehen</button></div>';}
 return h;
}
function playerImpact(p){const s=p.season;return s.pass_yds/20+s.rush_yds/12+s.rec_yds/12+s.tkl+s.sack*3+s.intc*5+s.td*4;}
async function signP(id){const r=await api('/api/fr/sign?pid='+id,'POST');if(r.result&&r.result.error)alert(r.result.error);if(r.view)renderMgr(r.view);}
async function scoutP(id){const r=await api('/api/fr/scout?pid='+id,'POST');if(r.result&&r.result.error)alert(r.result.error);if(r.view)renderMgr(r.view);}
async function draftP(id){const r=await api('/api/fr/draft?pid='+id,'POST');if(r.result&&r.result.error){alert(r.result.error);return;}if(r.result&&r.result.drafted)alert('Gedraftet: '+r.result.drafted+' (OVR '+r.result.ovr+')');if(r.view)renderMgr(r.view);}
async function cutP(id){if(!confirm('Spieler wirklich entlassen?'))return;const r=await api('/api/fr/cut?pid='+id,'POST');if(r.result&&r.result.error)alert(r.result.error);if(r.view){lastView=r.view;closePlayer();renderMgr(r.view);}}
let _selFac='stadium';
const _OX=300,_OY=72;
function _iso(gx,gy){return [(gx-gy)*30+_OX,(gx+gy)*15+_OY];}
function _pp(a){return a.map(p=>p[0].toFixed(1)+','+p[1].toFixed(1)).join(' ');}
function _dots(lvl,max){let s='<span class="hblv">';for(let i=0;i<max;i++)s+='<i class="'+(i<lvl?'on':'')+'"></i>';return s+'</span>';}
function _facList(v){const F=v.facilities||{};const kU=(v.units||[]).find(u=>u.key==='K');
 const a=[{key:'stadium',k:'stadium',name:'Stadion',lvl:v.stadium.level,cost:v.stadium.cost,maxed:v.stadium.level>=5,plus:'+1',eff:'Einnahmen +'+v.stadium.income+'/Woche',gx:3.05,gy:0.3,w:2.7,d:1.7},
  {key:'equipment',k:'field',name:'Trainingsgelände',lvl:v.equipment.level,cost:v.equipment.cost,maxed:v.equipment.level>=5,plus:'+1',eff:'+'+v.equipment.exp_week+' Trainings-EXP/Woche',gx:2.5,gy:3.15,w:3.2,d:1.85}];
 if(F.medical)a.push({key:'medical',k:'medical',name:'Medizinzentrum',lvl:F.medical.level,cost:F.medical.cost,maxed:F.medical.level>=5,plus:'+1',eff:F.medical.effect,gx:0.5,gy:0.7,w:1.3,d:1.1});
 if(F.athletic)a.push({key:'athletic',k:'athletic',name:'Athletik-Center',lvl:F.athletic.level,cost:F.athletic.cost,maxed:F.athletic.level>=5,plus:'+1',eff:F.athletic.effect,gx:7.0,gy:0.7,w:1.3,d:1.1});
 if(F.scouting_fac)a.push({key:'scouting_fac',k:'scouting',name:'Scouting-Akademie',lvl:F.scouting_fac.level,cost:F.scouting_fac.cost,maxed:F.scouting_fac.level>=5,plus:'+1',eff:F.scouting_fac.effect,gx:0.5,gy:3.2,w:1.2,d:1.1});
 if(F.youth)a.push({key:'youth',k:'youth',name:'Jugend-Akademie',lvl:F.youth.level,cost:F.youth.cost,maxed:F.youth.level>=5,plus:'+1',eff:F.youth.effect,gx:7.0,gy:3.3,w:1.3,d:1.1});
 return a;}   // Kicker ist jetzt eine Kaderposition (kein Anlagen-Gebäude mehr)
const _BPAL={medical:['#5a6770','#414d55','#2c353b','#7a8990'],athletic:['#46587e','#33415f','#26314a','#6076a0'],scouting:['#445a7e','#33455f','#26344a','#5f78a0'],youth:['#46714f','#345740','#26402f','#5e9468'],generic:['#56636d','#3e4951','#2c343a','#76858f']};
const _ACC={medical:'#ef5350',athletic:'#5fa8ff',scouting:'#5fa8ff',youth:'#19e08f'};
function _icon(k,x,y){const c='#ffffff';
 if(k==='medical')return '<rect x="'+(x-1.6)+'" y="'+(y-5)+'" width="3.2" height="10" fill="'+c+'"/><rect x="'+(x-5)+'" y="'+(y-1.6)+'" width="10" height="3.2" fill="'+c+'"/>';
 if(k==='athletic')return '<line x1="'+(x-5)+'" y1="'+y+'" x2="'+(x+5)+'" y2="'+y+'" stroke="'+c+'" stroke-width="2"/><circle cx="'+(x-5)+'" cy="'+y+'" r="2.6" fill="'+c+'"/><circle cx="'+(x+5)+'" cy="'+y+'" r="2.6" fill="'+c+'"/>';
 if(k==='scouting')return '<circle cx="'+(x-2.8)+'" cy="'+y+'" r="2.8" fill="none" stroke="'+c+'" stroke-width="1.6"/><circle cx="'+(x+2.8)+'" cy="'+y+'" r="2.8" fill="none" stroke="'+c+'" stroke-width="1.6"/>';
 if(k==='youth')return '<path d="M'+x+' '+(y+4)+' q-6 -2 -6 -8 q6 1 6 8 Z" fill="'+c+'"/>';
 return '';}
// Schatten der Grundfläche, leicht nach vorn versetzt
function _shadow(gx,gy,w,d){const o=0.22;
 return '<polygon points="'+_pp([_iso(gx+o,gy+o),_iso(gx+w+o+0.3,gy+o),_iso(gx+w+o+0.3,gy+d+o+0.3),_iso(gx+o,gy+d+o+0.3)])+'" fill="#040c07" fill-opacity=".34"/>';}
// Fensterraster auf eine geneigte Wandfläche (Basiskante p0->p1, Höhe h nach oben)
function _winGrid(p0,p1,h,cols,rows){const ex=(p1[0]-p0[0])/cols,ey=(p1[1]-p0[1])/cols,ry=h/rows;let s='';
 for(let c=0;c<cols;c++)for(let r=0;r<rows;r++){const bx=p0[0]+ex*(c+0.26),by=p0[1]+ey*(c+0.26)-ry*(r+0.24);
   const wx=ex*0.48,wy=ey*0.48,wh=ry*0.5,lit=((c*5+r*3)%4===0);
   s+='<polygon points="'+_pp([[bx,by],[bx+wx,by+wy],[bx+wx,by+wy-wh],[bx,by-wh]])+'" fill="'+(lit?'#ffe6a0':'#a7cee0')+'" fill-opacity="'+(lit?'.9':'.46')+'"/>';}
 return s;}
function _isoBuilding(f){const L=f.lvl,h=11+L*6,pal=_BPAL[f.k]||_BPAL.generic;
 const A=_iso(f.gx,f.gy),B=_iso(f.gx+f.w,f.gy),Cc=_iso(f.gx+f.w,f.gy+f.d),D=_iso(f.gx,f.gy+f.d),u=p=>[p[0],p[1]-h];
 let g=_shadow(f.gx,f.gy,f.w,f.d);
 // drei Wandflächen
 g+='<polygon points="'+_pp([B,Cc,u(Cc),u(B)])+'" fill="'+pal[2]+'"/>'+
    '<polygon points="'+_pp([D,Cc,u(Cc),u(D)])+'" fill="'+pal[1]+'"/>'+
    '<polygon points="'+_pp([u(A),u(B),u(Cc),u(D)])+'" fill="'+pal[0]+'"/>';
 // Sockel etwas heller
 g+='<polygon points="'+_pp([B,Cc,[Cc[0],Cc[1]-4],[B[0],B[1]-4]])+'" fill="#0c1116" fill-opacity=".4"/>';
 // Fenster auf beiden Frontflächen
 const cols=Math.max(2,Math.round(f.w*2.4)),rows=Math.max(2,L+1);
 g+=_winGrid(B,Cc,h-3,cols,rows)+_winGrid(D,Cc,h-3,Math.max(2,Math.round(f.d*2.4)),rows);
 // Etagenbänder
 for(let i=1;i<=L;i++){const y=h*i/(L+1);
   g+='<line x1="'+B[0].toFixed(1)+'" y1="'+(B[1]-y).toFixed(1)+'" x2="'+Cc[0].toFixed(1)+'" y2="'+(Cc[1]-y).toFixed(1)+'" stroke="#0a0f14" stroke-opacity=".4"/>'+
      '<line x1="'+D[0].toFixed(1)+'" y1="'+(D[1]-y).toFixed(1)+'" x2="'+Cc[0].toFixed(1)+'" y2="'+(Cc[1]-y).toFixed(1)+'" stroke="#0a0f14" stroke-opacity=".4"/>';}
 // Dachkante + Dachaufbauten (Lüfter, Antenne, Tank)
 g+='<polygon points="'+_pp([u(A),u(B),u(Cc),u(D)])+'" fill="none" stroke="#0a0f14" stroke-opacity=".5"/>';
 const ru=p=>[p[0],p[1]-h],rc=ru([(A[0]+Cc[0])/2,(A[1]+Cc[1])/2]);
 g+='<rect x="'+(rc[0]-10).toFixed(1)+'" y="'+(rc[1]-7).toFixed(1)+'" width="9" height="6" rx="1" fill="#2a323a" stroke="#0a0f14" stroke-width=".6"/>'+
    '<rect x="'+(rc[0]+2).toFixed(1)+'" y="'+(rc[1]-5).toFixed(1)+'" width="6" height="4" rx="1" fill="#39424b"/>'+
    '<line x1="'+(rc[0]+7).toFixed(1)+'" y1="'+(rc[1]-5).toFixed(1)+'" x2="'+(rc[0]+11).toFixed(1)+'" y2="'+(rc[1]-16).toFixed(1)+'" stroke="#7a8990" stroke-width="1"/><circle cx="'+(rc[0]+11).toFixed(1)+'" cy="'+(rc[1]-16).toFixed(1)+'" r="1.4" fill="#ef5350"/>';
 // schwebendes Icon-Badge
 const cx=(A[0]+Cc[0])/2,cy=(A[1]+Cc[1])/2-h-17;
 g+='<line x1="'+cx.toFixed(1)+'" y1="'+(cy+11).toFixed(1)+'" x2="'+cx.toFixed(1)+'" y2="'+(cy+17).toFixed(1)+'" stroke="#06140d" stroke-opacity=".5"/>'+
    '<circle cx="'+cx.toFixed(1)+'" cy="'+cy.toFixed(1)+'" r="11.5" fill="'+(_ACC[f.k]||'#8aa2a8')+'" stroke="#06140d" stroke-width="1.5"/><circle cx="'+cx.toFixed(1)+'" cy="'+cy.toFixed(1)+'" r="11.5" fill="none" stroke="#ffffff" stroke-opacity=".25"/>'+_icon(f.k,cx,cy);
 return g;}
function _isoStadium(f){const L=f.lvl,c=_iso(f.gx+f.w/2,f.gy+f.d/2),cx=c[0],cy=c[1],h=11+L*3,rx=f.w*27,ry=f.d*17;
 let g='<ellipse cx="'+(cx+12)+'" cy="'+(cy+7)+'" rx="'+(rx+7)+'" ry="'+(ry+5)+'" fill="#040c07" fill-opacity=".32"/>';
 // Außenwand (unten dunkel) -> sichtbare Frontmauer als Sichel
 g+='<ellipse cx="'+cx+'" cy="'+cy+'" rx="'+rx+'" ry="'+ry+'" fill="#10161b"/>';
 // Wandstützen an der Front
 for(let i=1;i<14;i++){const a=Math.PI*(i/14),ex=cx+Math.cos(a)*rx*0.99;
   g+='<line x1="'+ex.toFixed(1)+'" y1="'+(cy+Math.sin(a)*ry*0.99).toFixed(1)+'" x2="'+ex.toFixed(1)+'" y2="'+(cy-h+Math.sin(a)*ry*0.99).toFixed(1)+'" stroke="#05090c" stroke-opacity=".35"/>';}
 // oberer Ring + Sitzränge
 g+='<ellipse cx="'+cx+'" cy="'+(cy-h)+'" rx="'+rx+'" ry="'+ry+'" fill="#46525c"/>'+
    '<ellipse cx="'+cx+'" cy="'+(cy-h)+'" rx="'+(rx*0.9).toFixed(1)+'" ry="'+(ry*0.9).toFixed(1)+'" fill="#5d6b76"/>'+
    '<ellipse cx="'+cx+'" cy="'+(cy-h)+'" rx="'+(rx*0.74).toFixed(1)+'" ry="'+(ry*0.74).toFixed(1)+'" fill="#39434c"/>'+
    '<ellipse cx="'+cx+'" cy="'+(cy-h)+'" rx="'+(rx*0.6).toFixed(1)+'" ry="'+(ry*0.6).toFixed(1)+'" fill="#222b32"/>';
 // Zuschauer-Tupfen auf dem oberen Rang
 const crowd=['#d8dde2','#e0b07a','#c98a8a','#8aa0c0'];for(let i=0;i<60;i++){const a=i/60*Math.PI*2,rr=0.82+((i*7)%5)*0.018;
   g+='<circle cx="'+(cx+Math.cos(a)*rx*rr).toFixed(1)+'" cy="'+(cy-h+Math.sin(a)*ry*rr).toFixed(1)+'" r="1" fill="'+crowd[i%4]+'" fill-opacity=".8"/>';}
 // Spielfeld
 g+='<ellipse cx="'+cx+'" cy="'+(cy-h)+'" rx="'+(rx*0.5).toFixed(1)+'" ry="'+(ry*0.5).toFixed(1)+'" fill="#1d7a48"/>'+
    '<ellipse cx="'+cx+'" cy="'+(cy-h)+'" rx="'+(rx*0.5).toFixed(1)+'" ry="'+(ry*0.5).toFixed(1)+'" fill="none" stroke="#eaf6ef" stroke-opacity=".4"/>'+
    '<line x1="'+cx+'" y1="'+(cy-h-ry*0.5).toFixed(1)+'" x2="'+cx+'" y2="'+(cy-h+ry*0.5).toFixed(1)+'" stroke="#eaf6ef" stroke-opacity=".3"/>';
 // Flutlichtmasten mit Lichtkegel
 const ang=[[-1,-1],[1,-1],[-1,1],[1,1],[0,-1.18]];
 for(let i=0;i<L&&i<5;i++){const lx=cx+ang[i][0]*rx*0.86,ly=cy-h+ang[i][1]*ry*0.86;
   g+='<ellipse cx="'+lx.toFixed(1)+'" cy="'+(ly-19).toFixed(1)+'" rx="11" ry="7" fill="#fff6c8"><animate attributeName="opacity" values=".1;.26;.1" dur="3.5s" repeatCount="indefinite"/></ellipse>'+
      '<line x1="'+lx.toFixed(1)+'" y1="'+ly.toFixed(1)+'" x2="'+lx.toFixed(1)+'" y2="'+(ly-17).toFixed(1)+'" stroke="#46525c" stroke-width="2"/><rect x="'+(lx-5).toFixed(1)+'" y="'+(ly-21).toFixed(1)+'" width="10" height="4.5" rx="1" fill="#fff6c8"/>';}
 // Videowürfel (ab Stufe 3)
 if(L>=3){const by=cy-h-ry*0.92;g+='<line x1="'+cx+'" y1="'+(by+2)+'" x2="'+cx+'" y2="'+(by+9)+'" stroke="#46525c" stroke-width="2"/><rect x="'+(cx-13)+'" y="'+(by-12)+'" width="26" height="12" rx="1.5" fill="#0c1116" stroke="#46525c"/><rect x="'+(cx-11)+'" y="'+(by-10)+'" width="22" height="8" fill="#2d6cc0"/><text x="'+cx+'" y="'+(by-3.5)+'" text-anchor="middle" font-size="6" font-weight="800" fill="#eaf6ef">HOME</text>';}
 // Fahnen am Ringrand (ab Stufe 2)
 if(L>=2){const fc=['#e25b5b','#5fa8ff','#19e08f','#e9b949'];for(let i=0;i<8;i++){const a=i/8*Math.PI*2,fx=cx+Math.cos(a)*rx*0.99,fy=cy-h+Math.sin(a)*ry*0.99;
   g+='<line x1="'+fx.toFixed(1)+'" y1="'+fy.toFixed(1)+'" x2="'+fx.toFixed(1)+'" y2="'+(fy-10).toFixed(1)+'" stroke="#c8d2da" stroke-width="1"/><path class="flagw" style="animation:flagw '+(1.3+i*0.1).toFixed(1)+'s ease-in-out infinite" d="M'+fx.toFixed(1)+' '+(fy-10).toFixed(1)+' l6 1.8 l-6 1.8 Z" fill="'+fc[i%4]+'"/>';}}
 // Dachring (ab Stufe 4)
 if(L>=4)g+='<ellipse cx="'+cx+'" cy="'+(cy-h-3)+'" rx="'+(rx+4)+'" ry="'+(ry+3)+'" fill="none" stroke="#66737d" stroke-width="2.5"/>';
 return g;}
function _isoField(f){const A=_iso(f.gx,f.gy),B=_iso(f.gx+f.w,f.gy),Cc=_iso(f.gx+f.w,f.gy+f.d),D=_iso(f.gx,f.gy+f.d);
 const lerp=(p,q,t)=>[p[0]+(q[0]-p[0])*t,p[1]+(q[1]-p[1])*t];
 // gemähte Streifen + Endzonen
 const n=10;let g='';
 for(let i=0;i<n;i++){const t0=i/n,t1=(i+1)/n,ez=(i===0||i===n-1);
   g+='<polygon points="'+_pp([lerp(A,B,t0),lerp(A,B,t1),lerp(D,Cc,t1),lerp(D,Cc,t0)])+'" fill="'+(ez?'#15532f':(i%2?'#1c7546':'#1a6b40'))+'"/>';}
 // Yardlinien + Mittellinie
 for(let i=1;i<n;i++){const t=i/n;const p0=lerp(A,B,t),p1=lerp(D,Cc,t);
   g+='<line x1="'+p0[0].toFixed(1)+'" y1="'+p0[1].toFixed(1)+'" x2="'+p1[0].toFixed(1)+'" y2="'+p1[1].toFixed(1)+'" stroke="#eaf6ef" stroke-opacity="'+(i===5?'.7':'.45')+'" stroke-width="'+(i===5?'1.6':'1.1')+'"/>';}
 // Hashmarks
 for(let i=1;i<n;i++){const t=i/n;[0.4,0.6].forEach(s=>{const a=lerp(lerp(A,B,t),lerp(D,Cc,t),s);g+='<rect x="'+(a[0]-0.8).toFixed(1)+'" y="'+(a[1]-0.8).toFixed(1)+'" width="2.4" height="1.6" fill="#eaf6ef" fill-opacity=".5"/>';});}
 // Seitenlinien-Rahmen
 g+='<polygon points="'+_pp([A,B,Cc,D])+'" fill="none" stroke="#eaf6ef" stroke-opacity=".8" stroke-width="1.6"/>';
 // Tore an beiden Enden
 const gp=(p)=>'<line x1="'+(p[0]-8).toFixed(1)+'" y1="'+p[1].toFixed(1)+'" x2="'+(p[0]-8).toFixed(1)+'" y2="'+(p[1]-13).toFixed(1)+'" stroke="#ffd34d" stroke-width="2"/><line x1="'+(p[0]+8).toFixed(1)+'" y1="'+p[1].toFixed(1)+'" x2="'+(p[0]+8).toFixed(1)+'" y2="'+(p[1]-13).toFixed(1)+'" stroke="#ffd34d" stroke-width="2"/><line x1="'+(p[0]-8).toFixed(1)+'" y1="'+(p[1]-8).toFixed(1)+'" x2="'+(p[0]+8).toFixed(1)+'" y2="'+(p[1]-8).toFixed(1)+'" stroke="#ffd34d" stroke-width="2"/>';
 g+=gp(lerp(A,D,0.5))+gp(lerp(B,Cc,0.5));
 g+=_trainPlayers(f);return g;}
function _isoGoal(f){const L=f.lvl,p=_iso(f.gx,f.gy),s=12+L*3,x=p[0],y=p[1];
 return _shadow(f.gx-0.1,f.gy-0.1,0.4,0.4)+'<line x1="'+(x-9)+'" y1="'+y+'" x2="'+(x-9)+'" y2="'+(y-s)+'" stroke="#ffd34d" stroke-width="3"/><line x1="'+(x+9)+'" y1="'+y+'" x2="'+(x+9)+'" y2="'+(y-s)+'" stroke="#ffd34d" stroke-width="3"/><line x1="'+(x-9)+'" y1="'+(y-s*0.62).toFixed(1)+'" x2="'+(x+9)+'" y2="'+(y-s*0.62).toFixed(1)+'" stroke="#ffd34d" stroke-width="3"/><rect x="'+(x-2)+'" y="'+(y-s)+'" width="4" height="'+s+'" fill="#ffd34d" fill-opacity=".25"/>';}
function _trainPlayers(f){const c=_iso(f.gx+f.w/2,f.gy+f.d/2),ps=[[-46,-6,'A',0],[-18,8,'B',.5],[12,-8,'C',.9],[36,6,'A',.3],[58,-3,'B',.7],[-66,7,'C',1.1]];
 // Trainingsschlitten + Hütchen
 let extra='<rect x="'+(c[0]-78).toFixed(1)+'" y="'+(c[1]-4).toFixed(1)+'" width="14" height="7" rx="1.5" fill="#c2452f"/>';
 [[-60,12],[-40,14],[-20,12],[0,14]].forEach(o=>{extra+='<path d="M'+(c[0]+o[0])+' '+(c[1]+o[1])+' l3 5 l-6 0 Z" fill="#e9b949"/>';});
 const jer=['#19e08f','#5fa8ff','#e9b949','#e25b5b','#b66be0','#19e08f'];
 return extra+ps.map((p,i)=>{const col=jer[i%jer.length];
   return '<g transform="translate('+(c[0]+p[0]).toFixed(1)+' '+(c[1]+p[1]).toFixed(1)+')"><ellipse cy="3" rx="3" ry="1.6" fill="#06140d" fill-opacity=".3"/><g class="tp" style="animation:drill'+p[2]+' '+(2.1+p[3]).toFixed(1)+'s ease-in-out infinite '+p[3]+'s">'+
     '<ellipse cx="-2.3" cy="1.2" rx=".9" ry="1.5" fill="'+col+'"/><ellipse cx="2.3" cy="1.2" rx=".9" ry="1.5" fill="'+col+'"/>'+   // Arme
     '<ellipse cy="1" rx="2.7" ry="2" fill="'+col+'" stroke="#06140d" stroke-width=".6"/>'+                                          // Trikot/Schultern
     '<ellipse cy="0.2" rx="2" ry=".9" fill="#ffffff" fill-opacity=".18"/>'+                                                        // Glanz
     '<circle cy="-2" r="1.6" fill="#e7c39c" stroke="#06140d" stroke-width=".5"/>'+                                                  // Helm/Kopf
     '<path d="M-1.4 -2.7 Q0 -3.9 1.4 -2.7" fill="none" stroke="#06140d" stroke-width=".5"/>'+                                       // Facemask
     '</g></g>';}).join('');}
function _isoTree(gx,gy){const p=_iso(gx,gy);return '<ellipse cx="'+(p[0]+2).toFixed(1)+'" cy="'+(p[1]+1).toFixed(1)+'" rx="9" ry="3.4" fill="#040c07" fill-opacity=".3"/><rect x="'+(p[0]-1.5).toFixed(1)+'" y="'+(p[1]-10).toFixed(1)+'" width="3" height="10" fill="#5a3a1e"/><ellipse cx="'+p[0].toFixed(1)+'" cy="'+(p[1]-15).toFixed(1)+'" rx="9" ry="10" fill="#1d6b3f"/><ellipse cx="'+(p[0]-3).toFixed(1)+'" cy="'+(p[1]-18).toFixed(1)+'" rx="6" ry="7" fill="#2aa257"/><ellipse cx="'+(p[0]+4).toFixed(1)+'" cy="'+(p[1]-13).toFixed(1)+'" rx="4.5" ry="5" fill="#22864a"/>';}
function _isoLamp(gx,gy){const p=_iso(gx,gy);return '<rect x="'+(p[0]-1).toFixed(1)+'" y="'+(p[1]-16).toFixed(1)+'" width="2" height="16" fill="#46525c"/><circle cx="'+p[0].toFixed(1)+'" cy="'+(p[1]-17).toFixed(1)+'" r="6.5" fill="#ffe9a8" fill-opacity=".18"/><circle cx="'+p[0].toFixed(1)+'" cy="'+(p[1]-17).toFixed(1)+'" r="2.6" fill="#ffe9a8"/>';}
function _isoBush(gx,gy){const p=_iso(gx,gy);return '<ellipse cx="'+p[0].toFixed(1)+'" cy="'+(p[1]-2).toFixed(1)+'" rx="6" ry="4.4" fill="#1d6b3f"/><ellipse cx="'+(p[0]-2.5).toFixed(1)+'" cy="'+(p[1]-4).toFixed(1)+'" rx="4" ry="3.2" fill="#2aa257"/>';}
function _isoBench(gx,gy){const p=_iso(gx,gy);return '<rect x="'+(p[0]-5).toFixed(1)+'" y="'+(p[1]-3).toFixed(1)+'" width="10" height="2.4" rx="1" fill="#6b4a2a"/><rect x="'+(p[0]-5).toFixed(1)+'" y="'+(p[1]-6.5).toFixed(1)+'" width="10" height="2" rx="1" fill="#7d5832"/>';}
function _isoFountain(gx,gy){const p=_iso(gx,gy);return '<ellipse cx="'+p[0]+'" cy="'+p[1]+'" rx="14" ry="7" fill="#2a3a44" stroke="#46606e" stroke-width="2"/><ellipse cx="'+p[0]+'" cy="'+p[1]+'" rx="10" ry="4.8" fill="#3d8fb0"/><ellipse cx="'+p[0]+'" cy="'+(p[1]-0.5)+'" rx="2.4" ry="1.4" fill="#bfe6f2"/><rect x="'+(p[0]-1)+'" y="'+(p[1]-10)+'" width="2" height="9" fill="#46606e"/>';}
function _isoFlowers(gx,gy){const p=_iso(gx,gy),cols=['#e25b9a','#e9b949','#e25b5b','#b66be0'];let s='<ellipse cx="'+p[0]+'" cy="'+p[1]+'" rx="9" ry="5" fill="#274a2c"/>';
 for(let i=0;i<8;i++){const a=i*0.85;s+='<circle cx="'+(p[0]+Math.cos(a)*5.5).toFixed(1)+'" cy="'+(p[1]+Math.sin(a)*2.8).toFixed(1)+'" r="1.5" fill="'+cols[i%4]+'"/>';}return s;}
function _isoBus(gx,gy){const p=_iso(gx,gy);return '<ellipse cx="'+p[0]+'" cy="'+(p[1]+2)+'" rx="18" ry="4" fill="#040c07" fill-opacity=".3"/><rect x="'+(p[0]-16)+'" y="'+(p[1]-13)+'" width="32" height="13" rx="2.5" fill="#e5b73b"/><rect x="'+(p[0]-13)+'" y="'+(p[1]-10)+'" width="26" height="4.5" fill="#243038"/><rect x="'+(p[0]-15)+'" y="'+(p[1]-3)+'" width="30" height="2" fill="#b5892a"/><circle cx="'+(p[0]-9)+'" cy="'+p[1]+'" r="2.6" fill="#1a1a1a"/><circle cx="'+(p[0]+9)+'" cy="'+p[1]+'" r="2.6" fill="#1a1a1a"/>';}
function _isoPerson(gx,gy,col,anim){const p=_iso(gx,gy);
 return '<g'+(anim?' class="cz" style="animation:'+anim+'"':'')+'><ellipse cx="'+p[0].toFixed(1)+'" cy="'+(p[1]+1).toFixed(1)+'" rx="2.6" ry="1.4" fill="#06140d" fill-opacity=".3"/><rect x="'+(p[0]-1.5).toFixed(1)+'" y="'+(p[1]-6).toFixed(1)+'" width="3" height="6" rx="1.3" fill="'+col+'"/><circle cx="'+p[0].toFixed(1)+'" cy="'+(p[1]-7.6).toFixed(1)+'" r="1.7" fill="#e8c9a8"/></g>';}
function _road(gx,gy,w,d,col){let s='<polygon points="'+_pp([_iso(gx,gy),_iso(gx+w,gy),_iso(gx+w,gy+d),_iso(gx,gy+d)])+'" fill="'+(col||'#2b332e')+'"/>';
 // Mittelstreifen entlang der längeren Achse
 if(w>=d){for(let i=0;i*0.6<w;i++){const a=_iso(gx+i*0.6+0.18,gy+d/2),b=_iso(gx+i*0.6+0.42,gy+d/2);s+='<line x1="'+a[0].toFixed(1)+'" y1="'+a[1].toFixed(1)+'" x2="'+b[0].toFixed(1)+'" y2="'+b[1].toFixed(1)+'" stroke="#cdb23a" stroke-opacity=".55" stroke-width="1.2"/>';}}
 else{for(let i=0;i*0.6<d;i++){const a=_iso(gx+w/2,gy+i*0.6+0.18),b=_iso(gx+w/2,gy+i*0.6+0.42);s+='<line x1="'+a[0].toFixed(1)+'" y1="'+a[1].toFixed(1)+'" x2="'+b[0].toFixed(1)+'" y2="'+b[1].toFixed(1)+'" stroke="#cdb23a" stroke-opacity=".55" stroke-width="1.2"/>';}}
 return s;}
function _parking(gx,gy){let s='<polygon points="'+_pp([_iso(gx,gy),_iso(gx+2.2,gy),_iso(gx+2.2,gy+1.5),_iso(gx,gy+1.5)])+'" fill="#2f372f"/>';
 // Markierungen
 for(let i=1;i<5;i++){const a=_iso(gx+i*0.44,gy+0.1),b=_iso(gx+i*0.44,gy+1.4);s+='<line x1="'+a[0].toFixed(1)+'" y1="'+a[1].toFixed(1)+'" x2="'+b[0].toFixed(1)+'" y2="'+b[1].toFixed(1)+'" stroke="#eaf6ef" stroke-opacity=".25"/>';}
 const cars=[['#e25b5b',gx+0.45,gy+0.45],['#5fa8ff',gx+0.95,gy+0.5],['#e9b949',gx+1.45,gy+0.5],['#9ad17a',gx+0.7,gy+1.05],['#d8dde2',gx+1.7,gy+1.0]];
 cars.forEach(c=>{const p=_iso(c[1],c[2]);s+='<ellipse cx="'+p[0].toFixed(1)+'" cy="'+(p[1]-1).toFixed(1)+'" rx="8" ry="3" fill="#040c07" fill-opacity=".3"/><rect x="'+(p[0]-6).toFixed(1)+'" y="'+(p[1]-9).toFixed(1)+'" width="12" height="7" rx="2" fill="'+c[0]+'"/><rect x="'+(p[0]-4).toFixed(1)+'" y="'+(p[1]-8).toFixed(1)+'" width="8" height="2.6" rx="1" fill="#1c252b" fill-opacity=".6"/>';});return s;}
function _facBuilding(f){const sel=(_selFac===f.key);let g;
 if(f.k==='field')g=_isoField(f);else if(f.k==='stadium')g=_isoStadium(f);else if(f.k==='kick')g=_isoGoal(f);else g=_isoBuilding(f);
 return '<g class="facb'+(sel?' sel':'')+'" data-k="'+f.key+'" onclick="selFac(this.dataset.k)" style="cursor:pointer">'+g+'</g>';}
// Beschriftung getrennt — wird ganz oben gezeichnet, damit kein Gebäude sie verdeckt
function _shortName(n){const M={'Trainingsgelände':'Training','Medizinzentrum':'Medizin','Scouting-Akademie':'Scouting','Athletik-Center':'Athletik','Jugend-Akademie':'Jugend','Kicker-Akademie':'Kicker','Fan-Zone & Museum':'Fan-Zone','Analyse-Labor':'Analyse','Indoor-Halle':'Indoor'};return M[n]||String(n).split(/[ –—\-]/)[0];}
function _facLabel(f){const lp=_iso(f.gx+f.w/2,f.gy+f.d),nm=_shortName(f.name),sel=(_selFac===f.key);
 const ac=_ACC[f.k]||'#cfe0d8',sub=(f.rating?f.rating:f.lvl)+'';
 const w=Math.round(38+nm.length*6.4),L=lp[0]-w/2,cy=lp[1]+15;
 return '<g data-k="'+f.key+'" onclick="selFac(this.dataset.k)" style="cursor:pointer">'+
   '<rect x="'+L.toFixed(1)+'" y="'+(lp[1]+5).toFixed(1)+'" width="'+w+'" height="20" rx="10" fill="#0b1410" fill-opacity="'+(sel?'.97':'.86')+'" stroke="'+(sel?ac:'#04100a')+'" stroke-opacity="'+(sel?'.95':'.55')+'" stroke-width="'+(sel?'1.4':'1')+'"/>'+
   '<circle cx="'+(L+12).toFixed(1)+'" cy="'+cy.toFixed(1)+'" r="7" fill="'+ac+'" fill-opacity="'+(sel?'.3':'.16')+'" stroke="'+ac+'" stroke-opacity=".65"/>'+
   '<text x="'+(L+12).toFixed(1)+'" y="'+(cy+3).toFixed(1)+'" text-anchor="middle" font-size="9" font-weight="800" fill="'+ac+'">'+sub+'</text>'+
   '<text x="'+(L+24).toFixed(1)+'" y="'+(cy+3.4).toFixed(1)+'" font-size="10.5" font-weight="700" fill="#e3ece7" style="paint-order:stroke" stroke="#04100a" stroke-width="2.2">'+esc(nm)+'</text></g>';}
function _complexSVG(v,opts){const world=!!(opts&&opts.world);
 // Boden mit Verlauf + Plaza-Wege + Parkplatz
 let s='<defs><linearGradient id="gsky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0c1810"/><stop offset="1" stop-color="#0a120c"/></linearGradient><radialGradient id="ggrass" cx="0.5" cy="0.42" r="0.7"><stop offset="0" stop-color="#1c4029"/><stop offset="1" stop-color="#143020"/></radialGradient></defs>'+
   '<rect x="0" y="0" width="600" height="380" fill="url(#gsky)"/>'+
   '<polygon points="'+_pp([_iso(-.6,-.6),_iso(9.6,-.6),_iso(9.6,7.6),_iso(-.6,7.6)])+'" fill="#0e1912"/>'+
   '<polygon points="'+_pp([_iso(0,0),_iso(9,0),_iso(9,7),_iso(0,7)])+'" fill="url(#ggrass)"/>'+
   '<polygon points="'+_pp([_iso(0,0),_iso(9,0),_iso(9,7),_iso(0,7)])+'" fill="none" stroke="#0a1c12" stroke-width="2"/>'+
   _road(0.5,2.4,8,0.5)+_road(5.5,5.15,2.4,0.55)+_parking(5.9,5.35);
 // Zaun entlang des Geländerandes
 let fence='';for(let i=0;i<=18;i++){const t=i/18;
   const a=_iso(t*9,0);fence+='<line x1="'+a[0].toFixed(1)+'" y1="'+a[1].toFixed(1)+'" x2="'+a[0].toFixed(1)+'" y2="'+(a[1]-5).toFixed(1)+'" stroke="#3a4630" stroke-width="1"/>';
   const b=_iso(0,t*7);fence+='<line x1="'+b[0].toFixed(1)+'" y1="'+b[1].toFixed(1)+'" x2="'+b[0].toFixed(1)+'" y2="'+(b[1]-5).toFixed(1)+'" stroke="#3a4630" stroke-width="1"/>';}
 s+=fence;
 let dr=[];const push=(dep,svg)=>dr.push([dep,svg]);
 const list=_facList(v);
 list.forEach(f=>push(f.gx+f.gy+f.d,_facBuilding(f)));
 // Bäume entlang der Ränder (nicht auf Gebäuden)
 [[0.25,0.25],[8.65,0.3],[0.3,6.7],[8.5,6.6],[8.65,2.6],[0.25,2.6],[2.0,6.6],[5.3,6.6],[6.8,6.5],[8.65,4.8]].forEach(t=>push(t[0]+t[1],_isoTree(t[0],t[1])));
 // Laternen rund um Plaza & Bodenbereich
 [[1.2,2.35],[7.7,2.35],[1.3,5.0],[7.5,5.2],[4.4,5.25]].forEach(t=>push(t[0]+t[1]-0.05,_isoLamp(t[0],t[1])));
 // Büsche/Hecken an den Wegrändern
 [[2.2,2.6],[5.9,2.6],[1.0,4.2],[8.0,4.2],[2.0,5.9],[6.2,5.95]].forEach(t=>push(t[0]+t[1],_isoBush(t[0],t[1])));
 // Brunnen mittig auf der Plaza + Bänke & Blumenbeete
 push(4.4+2.55,_isoFountain(4.4,2.55));
 [[3.3,2.5],[5.5,2.5]].forEach(t=>push(t[0]+t[1],_isoBench(t[0],t[1])));
 [[3.8,2.55],[5.0,2.55],[1.5,2.5],[7.2,2.5],[2.6,5.95],[5.5,5.95]].forEach(t=>push(t[0]+t[1],_isoFlowers(t[0],t[1])));
 // Mannschaftsbus am Parkplatz
 push(6.3+5.0,_isoBus(6.3,5.0));
 // Spaziergänger (animiert) auf Plaza & unten
 push(2.6+2.6,_isoPerson(2.6,2.6,'#5fa8ff','walkx 7s ease-in-out infinite'));
 push(5.8+2.6,_isoPerson(5.8,2.6,'#e9b949','walky 8s ease-in-out infinite'));
 push(3.4+5.85,_isoPerson(3.4,5.9,'#e25b5b','walky 9s ease-in-out infinite 1s'));
 push(4.9+5.85,_isoPerson(4.9,5.9,'#9ad17a','walkx 8s ease-in-out infinite .5s'));
 // Welt-Ansicht: Bauplätze für freischaltbare Erweiterungen
 let lockLabels='';
 if(world){const lf=_lockedFacs(v);lf.forEach(f=>push(f.gx+f.gy+f.d,_isoLockedPlot(f)));
   lockLabels=lf.map(_lockedLabel).join('');}
 dr.sort((a,b)=>a[0]-b[0]);
 // Labels zuletzt, von hinten nach vorne, immer über den Gebäuden
 const labels=list.slice().sort((a,b)=>(a.gy+a.d)-(b.gy+b.d)).map(_facLabel).join('');
 const vb=world?'90 24 464 318':'92 30 460 300';
 return '<svg class="complex'+(world?' worldsvg':'')+'" viewBox="'+vb+'" preserveAspectRatio="xMidYMid meet">'+s+dr.map(x=>x[1]).join('')+labels+lockLabels+'</svg>';}
// Freischaltbare Erweiterungen (Bauplätze) – Status aus den vorhandenen Anlagen-Stufen
function _lockedFacs(v){const F=v.facilities||{};
 const eq=(v.equipment&&v.equipment.level)||1,sc=(F.scouting_fac&&F.scouting_fac.level)||1,me=(F.medical&&F.medical.level)||1,st=(v.stadium&&v.stadium.level)||1;
 return [
  {key:'indoor',name:'Indoor-Halle',gx:0.7,gy:5.45,w:1.5,d:1.05,reqL:4,reqcur:eq,reqname:'Trainingsgelände',unlocked:eq>=4},
  {key:'analytics',name:'Analyse-Labor',gx:2.55,gy:6.05,w:1.4,d:0.95,reqL:3,reqcur:sc,reqname:'Scouting-Akademie',unlocked:sc>=3},
  {key:'fanzone',name:'Fan-Zone & Museum',gx:8.0,gy:5.55,w:1.2,d:0.95,reqL:4,reqcur:st,reqname:'Stadion',unlocked:st>=4}
 ];}
function _isoLockedPlot(f){const A=_iso(f.gx,f.gy),B=_iso(f.gx+f.w,f.gy),Cc=_iso(f.gx+f.w,f.gy+f.d),D=_iso(f.gx,f.gy+f.d);
 const cx=(A[0]+Cc[0])/2,cy=(A[1]+Cc[1])/2,col=f.unlocked?'#19e08f':'#8a99a2';
 let g='<polygon points="'+_pp([A,B,Cc,D])+'" fill="#0b130d" fill-opacity=".55" stroke="'+col+'" stroke-width="1.6" stroke-dasharray="6 4"/>';
 // Eckpfosten
 [A,B,Cc,D].forEach(p=>{g+='<line x1="'+p[0].toFixed(1)+'" y1="'+p[1].toFixed(1)+'" x2="'+p[0].toFixed(1)+'" y2="'+(p[1]-6).toFixed(1)+'" stroke="'+col+'" stroke-width="1.4"/>';});
 // Schild mit Schloss/Haken
 g+='<line x1="'+cx+'" y1="'+(cy-2)+'" x2="'+cx+'" y2="'+(cy-22)+'" stroke="#5a6770" stroke-width="2"/>'+
    '<circle cx="'+cx+'" cy="'+(cy-29)+'" r="9.5" fill="'+(f.unlocked?'#19e08f':'#39444c')+'" stroke="#06140d" stroke-width="1.5"/>';
 g+=f.unlocked?'<path d="M'+(cx-3.5)+' '+(cy-29)+' l2.5 3 l4.5 -6" stroke="#06140d" stroke-width="2" fill="none"/>'
   :'<rect x="'+(cx-3)+'" y="'+(cy-30)+'" width="6" height="5" rx="1" fill="#d4dbe0"/><path d="M'+(cx-2)+' '+(cy-30)+' a2 2 0 0 1 4 0" stroke="#d4dbe0" stroke-width="1.3" fill="none"/>';
 return g;}
function _lockedLabel(f){const lp=_iso(f.gx+f.w/2,f.gy+f.d),nm=_shortName(f.name),col=f.unlocked?'#19e08f':'#9fb0a8';
 const w=Math.round(38+nm.length*6.4),L=lp[0]-w/2,cy=lp[1]+15;
 return '<g style="pointer-events:none"><rect x="'+L.toFixed(1)+'" y="'+(lp[1]+5).toFixed(1)+'" width="'+w+'" height="20" rx="10" fill="#0b1410" fill-opacity=".86" stroke="'+col+'" stroke-opacity=".45" stroke-dasharray="'+(f.unlocked?'0':'4 3')+'"/>'+
   '<text x="'+(L+11).toFixed(1)+'" y="'+(cy+3.4).toFixed(1)+'" text-anchor="middle" font-size="10" fill="'+col+'">'+(f.unlocked?'✓':'🔒')+'</text>'+
   '<text x="'+(L+22).toFixed(1)+'" y="'+(cy+3.4).toFixed(1)+'" font-size="10.5" font-weight="700" fill="'+col+'" style="paint-order:stroke" stroke="#04100a" stroke-width="2.2">'+esc(nm)+'</text></g>';}
function _facPanelHTML(v){const list=_facList(v);const f=list.find(x=>x.key===_selFac)||list[0];if(!f)return '';
 return '<div class="facpanel"><div style="flex:1"><div class="fpn">'+esc(f.name)+'</div><div class="hbe">'+esc(f.eff)+'</div></div>'+
   '<div style="text-align:right;flex:none">'+(f.rating?'<span class="hblvl">'+f.rating+' OVR</span>':_dots(f.lvl,5))+
   '<div style="margin-top:7px"><button data-u="'+esc(f.key)+'" onclick="upg(this.dataset.u)" '+(v.budget<f.cost||f.maxed?'disabled':'')+'>'+(f.maxed?'Ausgebaut':'Ausbauen '+f.plus+' ('+f.cost+' Mio)')+'</button></div></div></div>';}
function selFac(k){_selFac=k;document.querySelectorAll('.facb').forEach(e=>e.classList.toggle('sel',e.dataset.k===k));
 ['facpanel','worldpanel'].forEach(id=>{const p=$(id);if(p&&lastView)p.innerHTML=_facPanelHTML(lastView);});}
/* ---------- Vereinswelt (großes, bewegbares Pop-up) ---------- */
let _wx=0,_wy=0,_ws=1,_wptr={},_wpd=0;
function _devStars(ovr){return Math.max(1,Math.min(5,Math.round((ovr-58)/8)));}
function _devList(v){const list=_facList(v);let lvl=0,mx=0;list.forEach(f=>{lvl+=(f.rating?Math.max(1,Math.round((f.rating-50)/10)):f.lvl);mx+=5;});return Math.round(lvl/mx*100);}
function openWorld(){const v=lastView;if(!v)return;closeWorld();
 const o=document.createElement('div');o.className='overlay';o.id='worldoverlay';o.addEventListener('click',e=>{if(e.target===o)closeWorld();});
 const lf=_lockedFacs(v);
 const ranking=(v.standings||[]).slice().sort((a,b)=>b.ovr-a.ovr).map((t,i)=>{
   const stars='★★★★★'.slice(0,_devStars(t.ovr))+'☆☆☆☆☆'.slice(0,5-_devStars(t.ovr));
   return '<div class="devrow'+(t.user?' me':'')+'"><span class="devrk">'+(i+1)+'</span>'+teamLogo(t.abbr,t.color)+
     '<span class="devnm">'+esc(t.name)+(t.user?' <span class="tag" style="background:#16c784;color:#04140c">DU</span>':'')+
     '<span class="devbarwrap"><span class="devbar" style="width:'+Math.round((t.ovr-50)/49*100)+'%;background:'+esc(t.color)+'"></span></span></span>'+
     '<span class="devov">'+t.ovr+'<small>OVR</small></span><span class="devst">'+stars+'</span>'+
     (t.user?'':'<button class="ghost mini" data-a="'+esc(t.abbr)+'" onclick="scoutTeam(this.dataset.a)">Scouten</button>')+
     '</div><div class="devdet" id="dev_'+esc(t.abbr)+'"></div>';}).join('');
 const exp=lf.map(f=>'<div class="exprow'+(f.unlocked?' on':'')+'"><span class="expic">'+(f.unlocked?'✓':'🔒')+'</span>'+
   '<span class="expnm"><b>'+esc(f.name)+'</b><small>'+(f.unlocked?'Bauplatz bereit – bald baubar':'Benötigt '+esc(f.reqname)+' Stufe '+f.reqL+' (aktuell '+f.reqcur+')')+'</small></span></div>').join('');
 o.innerHTML='<div class="modal worldwrap"><div class="modalhead"><h3>🌍 Vereinswelt — '+esc(v.team_name)+'</h3><button class="ghost" onclick="closeWorld()">Schließen</button></div>'+
   '<div class="worldview" id="worldview"><div class="worldcanvas" id="worldcanvas">'+_complexSVG(v,{world:true})+'</div>'+
   '<div class="worldzoom"><button data-d="1" onclick="worldZoomBtn(1)">+</button><button data-d="-1" onclick="worldZoomBtn(-1)">−</button><button onclick="worldReset()">⟳</button></div>'+
   '<div class="worldhint">Ziehen zum Bewegen · Scrollen/Zwei-Finger zum Zoomen</div></div>'+
   '<div id="worldpanel">'+_facPanelHTML(v)+'</div>'+
   '<div class="sec">🏗️ Erweiterungen freischalten</div><div class="expgrid">'+exp+'</div>'+
   '<div class="sec">📊 Liga-Entwicklung — wie stark sind die anderen Klubs?</div><div class="devlist">'+ranking+'</div>'+
   '</div>';
 document.body.appendChild(o);lockBody();_wx=0;_wy=0;_ws=1;_wapply();_wbind();}
function closeWorld(){const o=$('worldoverlay');if(o)o.remove();unlockBodyIfNone();}
function _wapply(){const c=$('worldcanvas');if(c)c.style.transform='translate('+_wx.toFixed(1)+'px,'+_wy.toFixed(1)+'px) scale('+_ws.toFixed(3)+')';}
function _wzoom(f,cx,cy){const ns=Math.max(0.7,Math.min(3.4,_ws*f)),k=ns/_ws;_wx=cx-(cx-_wx)*k;_wy=cy-(cy-_wy)*k;_ws=ns;_wapply();}
function worldZoomBtn(d){const v=$('worldview'),r=v?v.getBoundingClientRect():{width:320,height:320};_wzoom(d>0?1.28:0.78,r.width/2,r.height/2);}
function worldReset(){_wx=0;_wy=0;_ws=1;_wapply();}
function _wbind(){const v=$('worldview');if(!v)return;
 v.onpointerdown=e=>{v.setPointerCapture(e.pointerId);_wptr[e.pointerId]={x:e.clientX,y:e.clientY};};
 v.onpointermove=e=>{if(!_wptr[e.pointerId])return;const ids=Object.keys(_wptr);
   if(ids.length>=2){const r=v.getBoundingClientRect();_wptr[e.pointerId]={x:e.clientX,y:e.clientY};
     const a=_wptr[ids[0]],b=_wptr[ids[1]],nd=Math.hypot(a.x-b.x,a.y-b.y);
     if(_wpd)_wzoom(nd/_wpd,(a.x+b.x)/2-r.left,(a.y+b.y)/2-r.top);_wpd=nd;return;}
   const p=_wptr[e.pointerId];_wx+=e.clientX-p.x;_wy+=e.clientY-p.y;_wptr[e.pointerId]={x:e.clientX,y:e.clientY};_wapply();};
 const up=e=>{delete _wptr[e.pointerId];_wpd=0;};v.onpointerup=up;v.onpointercancel=up;v.onpointerleave=up;
 v.onwheel=e=>{e.preventDefault();const r=v.getBoundingClientRect();_wzoom(e.deltaY<0?1.12:0.9,e.clientX-r.left,e.clientY-r.top);};}
function scoutTeam(abbr){const d=$('dev_'+abbr);if(!d)return;if(d.innerHTML){d.innerHTML='';return;}
 const t=((lastView&&lastView.standings)||[]).find(x=>x.abbr===abbr);if(!t)return;
 d.innerHTML=scoutReportHTML(t,lastView);}
function secBuild(v){
 // Anlagen-Gelände: anklickbare Karte direkt im Tab (kein Pop-up), mit Ausbau-Panel & Erweiterungen
 let h='<div class="card hubcard"><div class="sec" style="margin-top:0">🏟️ Vereinsgelände</div>'+
   '<div class="note" style="margin-top:0">Budget: '+v.budget+' Mio. — tippe ein Gebäude an und bau es aus. Jede Stufe verändert es sichtbar.</div>'+
   '<div class="cityview">'+_complexSVG(v,{world:true})+'</div>'+
   '<div id="facpanel">'+_facPanelHTML(v)+'</div></div>';
 const lf=_lockedFacs(v);
 h+='<div class="card"><div class="sec" style="margin-top:0">🏗️ Erweiterungen freischalten</div><div class="note" style="margin-top:0">Neue Bauplätze auf dem Gelände — schalte sie über die passenden Anlagen-Stufen frei.</div>'+
   '<div class="expgrid" style="margin-top:10px">'+lf.map(f=>'<div class="exprow'+(f.unlocked?' on':'')+'"><span class="expic">'+(f.unlocked?'✓':'🔒')+'</span>'+
     '<span class="expnm"><b>'+esc(f.name)+'</b><small>'+(f.unlocked?'Bauplatz bereit — bald baubar':'Benötigt '+esc(f.reqname)+' Stufe '+f.reqL+' (aktuell '+f.reqcur+')')+'</small></span></div>').join('')+'</div></div>';
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
function showAwards(){const v=lastView;if(!v||!v.awards||!v.awards.length)return;
 const o=document.createElement('div');o.className='overlay';o.id='awoverlay';o.addEventListener('click',e=>{if(e.target===o)closeAwards();});
 o.innerHTML='<div class="modal"><div class="modalhead"><h3>🏆 Award-Show — Saison '+v.season+'</h3><button class="ghost" onclick="closeAwards()">Schließen</button></div>'+
   (v.champion?'<div class="reco champ"><span><span class="tag">MEISTER</span> <b>'+esc(v.champion)+'</b></span><span class="mut">Saison '+v.season+'</span></div>':'')+
   v.awards.map(a=>'<div class="awrow"><span class="pfa">'+portrait({id:a.id,name:a.name},48,v.color)+'</span><div class="awtxt"><div class="awlabel">'+esc(a.award)+'</div><div class="awname">'+posBadge(a.pos)+' <b>'+esc(a.name)+'</b></div><div class="mut" style="font-size:12px">'+esc(a.line)+'</div></div></div>').join('')+
   '</div>';document.body.appendChild(o);lockBody();}
function closeAwards(){const o=$('awoverlay');if(o)o.remove();unlockBodyIfNone();}
async function newSeason(){closeAwards();renderMgr(await api('/api/fr/new_season','POST'));}
async function resetFr(){if(confirm('Franchise wirklich löschen?')){await api('/api/fr/reset','POST');loadMgr();}}
async function watchLast(){const r=await api('/api/fr/last_game');if(r.game)openBroadcast(r.game);}

/* ---------- Spiel-Übertragung (TV) ---------- */
let bcTimer=null,bcGame=null;
const AC=g=>g.acolor||'#ef5350', HC=g=>g.hcolor||'#16c784', AB=g=>g.aabbr||g.away.slice(0,3).toUpperCase(), HB=g=>g.habbr||g.home.slice(0,3).toUpperCase();
function pbadge(desc){let c='pb-pl',t='PLAY';
 if(/🚩|Strafe|Holding|False Start|Offside|Interference|Face Mask|Roughing|Encroachment|Delay of Game|Formation|Neutral Zone|Unnecessary/.test(desc)){c='pb-fl';t='FLAG';}
 else if(/TOUCHDOWN/.test(desc)){c='pb-td';t='TD';}else if(/Field Goal gut/.test(desc)){c='pb-fg';t='FG';}
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
/* Echte Spieluhr: Viertelzeit kommt vom Backend und läuft pro Spielzug ab (kein Echtzeit-Ticker). */
let gameQ=1, gameClock=360;
function fmtClock(s){s=Math.max(0,Math.round(s));return Math.floor(s/60)+':'+(s%60<10?'0':'')+(s%60);}
function qLabel(q){q=q||gameQ;return q>4?('OT'+(q>5?(q-4):'')):('Q'+q);}
function toDots(n){let s='';for(let i=0;i<3;i++)s+='<span class="todot'+(i<n?'':' off')+'"></span>';return s;}
function startClock(){}                               // Uhr ist backend-gesteuert (Stubs für Kompatibilität)
function stopClock(){}
async function startGame(){const r=await api('/api/fr/game/start','POST');if(r.error){alert(r.error);return;}openGame(r.game);}
async function resumeGame(){const r=await api('/api/fr/game/start','POST');if(r.error){alert(r.error);return;}openGame(r.game);}
function openGame(g){closeGame();liveG=g;gameQ=g.quarter||1;gameClock=(g.clock!=null?g.clock:360);const o=document.createElement('div');o.className='overlay';o.id='gameoverlay';
 o.innerHTML='<div class="modal" id="gamemodal"></div>';document.body.appendChild(o);lockBody();
 const go=()=>{if(!liveG)return;renderGame(liveG);};
 if(g.log&&g.log.length===0){gameIntro(g,go);}else go();}   // frisches Spiel: Intro -> Münzwurf -> Kickoff
function gameIntro(g,done){let fin=false;const end=()=>{if(fin)return;fin=true;clearTimeout(window._introT);done();};
 window.introSkip=end;const M=$('gamemodal');if(!M){end();return;}
 const uName=(lastView&&lastView.team_name)||(g.user_is_home?g.home:g.away);
 const uColor=(lastView&&lastView.color)||'#16c784',uAbbr=(lastView&&lastView.abbr)||(g.user_is_home?g.habbr:g.aabbr);
 const oName=g.user_is_home?g.away:g.home,oColor=g.user_is_home?g.acolor:g.hcolor,oAbbr=g.user_is_home?g.aabbr:g.habbr;
 const short=n=>{const t=(''+n).split(' ');return t.length>1?t[0][0]+'. '+t[t.length-1]:n;};
 const uCaps=(lastView&&lastView.roster?lastView.roster.slice().sort((a,b)=>b.ovr-a.ovr).slice(0,3):[]);
 const oCaps=[0,1,2].map(i=>({id:'o'+oAbbr+i,name:oAbbr+' '+(10+i*11)}));
 const capCol=(arr,col,real)=>'<div class="caps">'+arr.map(p=>'<div class="capw"><span class="pfa">'+portrait(p,44,col)+'</span><span class="capn">'+esc(real?short(p.name):'C')+'</span></div>').join('')+'</div>';
 const teamCol=(nm,ab,col,caps,real)=>'<div class="vsteam" style="border-color:'+esc(col)+'66"><div class="tlogo lg" style="--lc:'+esc(col)+'">'+esc(ab)+'</div><div class="tn">'+esc(nm)+'</div>'+capCol(caps,col,real)+'</div>';
 const skip='<button class="ghost introskip" onclick="introSkip()">Überspringen ▸</button>';
 function s1(){M.innerHTML='<div class="introwrap">'+skip+'<div class="introsub">Heute im Spiel</div>'+
   '<div class="vsrow">'+teamCol(uName,uAbbr,uColor,uCaps,true)+'<div class="vsmid">VS</div>'+teamCol(oName,oAbbr,oColor,oCaps,false)+'</div>'+
   '<div class="introsub" style="font-size:12px">Kapitäne ohne Helm</div></div>';
   window._introT=setTimeout(s2,2600);}
 function s2(){const userWins=!!(g.coin&&g.coin.user_receives),recv=userWins?uName:oName;
   const endDeg=1980+(userWins?0:180);   // viele Umdrehungen; Vorderseite (Nutzer)=Vielfaches von 360, Rückseite (Gegner)=+180
   M.innerHTML='<div class="introwrap">'+skip+'<div class="introbig">Münzwurf</div>'+
     '<div class="coinwrap"><div class="coinflip" id="coinflip" style="transform:rotateY(0deg)">'+
       '<div class="cface cfront"><span class="cab" style="--c:'+esc(uColor)+'">'+esc(uAbbr)+'</span></div>'+
       '<div class="cface cback"><span class="cab" style="--c:'+esc(oColor)+'">'+esc(oAbbr)+'</span></div>'+
     '</div></div><div class="introsub" id="cointxt">Die Münze fliegt …</div></div>';
   const cf=$('coinflip');
   setTimeout(()=>{if(cf){cf.style.transition='transform 2s cubic-bezier(.16,.62,.18,1)';cf.style.transform='rotateY('+endDeg+'deg)';}},70);
   setTimeout(()=>{const t=$('cointxt');if(t)t.innerHTML='<b style="color:var(--acc)">'+esc(recv)+'</b> gewinnt den Münzwurf und bekommt den Ball';},2150);
   window._introT=setTimeout(s3,2900);}
 function s3(){const k=g.kickoff||{return_to:25,td:false};const recvCol=(g.coin&&g.coin.user_receives)?uColor:oColor;
   const endX=k.td?96:Math.max(8,Math.min(92,k.return_to));
   M.innerHTML='<div class="introwrap">'+skip+'<div class="introbig">Kickoff</div>'+
   '<div class="kostrip"><div class="koball" id="koball" style="left:6%;background:'+esc(recvCol)+'"></div></div>'+
   '<div class="introsub" id="kotxt">Return läuft …</div></div>';
   setTimeout(()=>{const b=$('koball');if(b)b.style.left=endX+'%';},60);
   setTimeout(()=>{const t=$('kotxt');if(t)t.innerHTML=k.td?'<b style="color:var(--acc)">RETURN-TOUCHDOWN!</b>':'Return bis zur eigenen <b>'+k.return_to+'</b>';},1100);
   window._introT=setTimeout(end,2500);}
 s1();}
function gameTurf(g){let t='';[10,20,30,40,50,60,70,80,90].forEach(p=>{t+='<div class="yl" style="left:'+p+'%"></div>';
 const lab=(p===50?'50':(p<50?p:100-p));t+='<div class="yn" style="left:'+p+'%">'+lab+'</div><div class="yn b" style="left:'+p+'%">'+lab+'</div>';});
 return '<div class="turf">'+t+'<div class="ball" style="left:'+Math.max(1,Math.min(99,g.absx))+'%"></div></div>';}
let _preG=null;
function renderGame(g,play){
 const willAnimate=!!(play&&(play.concept||play.kind==='fg'||play.kind==='punt'||play.penalty));   // läuft eine Snap-/Kick-/Flaggen-Animation?
 if(!willAnimate)playBusy=false;                            // Penalty/2PT/Wechsel: Buttons sofort wieder aktiv rendern
 // Während der Animation das Spielfeld/Anzeige im Vor-Snap-Zustand zeigen — das Ergebnis (Score, Down, Spot, Uhr, Kommentar) erst NACH der Animation
 const disp=(willAnimate&&_preG)?_preG:g;
 if(!willAnimate)_preG=null;
 gameQ=disp.quarter||disp.q||1; gameClock=(disp.clock!=null?disp.clock:0);   // Spieluhr aus dem Backend-Stand
 const tos=disp.timeouts||[3,3];
 let h='<div class="modalhead"><h3><span class="livedot"></span> Dein Spiel</h3>'+
   '<button class="ghost" onclick="abortGame()">Verlassen</button></div>'+
   '<div class="tvscore">'+
     '<div class="tvteam">'+teamLogo(disp.aabbr,disp.acolor,'lg')+'<span class="nm">'+esc(disp.away)+'</span></div>'+
     '<div class="tvpts">'+disp['as']+'</div>'+
     '<div class="tvmid"><div class="qn" id="gq">'+qLabel(gameQ)+'</div><div class="sub clk'+(disp.clock_running?' run':'')+'" id="clk">'+fmtClock(gameClock)+'</div>'+
       '<div class="toline"><span class="tol">'+toDots(tos[1])+'</span><span class="tor">'+toDots(tos[0])+'</span></div></div>'+
     '<div class="tvpts">'+disp.hs+'</div>'+
     '<div class="tvteam r"><span class="nm">'+esc(disp.home)+'</span>'+teamLogo(disp.habbr,disp.hcolor,'lg')+'</div>'+
   '</div>'+
   '<div class="tvfield"><div class="ez" style="background:'+esc(disp.acolor)+'">'+esc(disp.aabbr)+'</div>'+
     gameTurf(disp)+'<div class="ez" style="background:'+esc(disp.hcolor)+'">'+esc(disp.habbr)+'</div></div>'+
   '<div class="dd"><span>'+disp.down+'. &amp; '+disp.dist+'</span><span class="mut">noch '+disp.ytz+' Yd bis TD · Ball: '+esc(disp.possession)+'</span></div>'+
   '<div class="fieldwrap" style="margin:10px 0"><svg id="gfield" viewBox="0 0 533 360" style="width:100%;height:auto;display:block"></svg></div>';
 if(play&&!willAnimate)h+='<div class="reco'+(play.scored?' win':'')+(play.penalty?' flag':'')+'"><span>'+esc(play.desc)+'</span>'+(play.penalty?'<span class="mut">Strafe</span>':'<span class="mut">'+(play.yards>=0?'+':'')+play.yards+' Yd</span>')+'</div>';
 else if(willAnimate)h+='<div class="reco"><span class="mut">Spielzug läuft …</span></div>';
 if(disp.over){h+='<div class="posbanner off">Spiel vorbei — Endstand '+esc(disp.away)+' '+disp['as']+' : '+disp.hs+' '+esc(disp.home)+'</div>'+
   '<button onclick="finishGame()">Ergebnis werten &amp; Woche abschließen</button>';}
 else{const ban=disp.awaiting==='pat'?'🏈 Touchdown! Extra-Punkt oder 2-Punkte-Conversion?':disp.awaiting==='2pt'?'🏈 2-Punkte-Versuch — wähle deinen Spielzug von der 3:':(disp.user_offense?'Du am Ball — wähle dein Konzept:':'Verteidigung — wähle deine Coverage:');
   const opts=disp.options||[],dis=playBusy?'disabled':'';
   const to=opts.find(o=>o.key==='__TIMEOUT__');                        // Auszeit -> klein oben rechts
   const kicks=opts.filter(o=>o.key==='__FG__'||o.key==='__PUNT__');    // FG/Punt -> nur 4. Versuch, ganz oben
   const plays=opts.filter(o=>o.key!=='__TIMEOUT__'&&o.key!=='__FG__'&&o.key!=='__PUNT__');
   const pbtn=o=>'<button class="optbtn'+(o.key==='__PHILLY__'?' philly':'')+'" '+dis+' data-k="'+esc(o.key)+'" onclick="gamePlay(this.dataset.k)">'+esc(o.label)+'<span class="ty">'+esc(o.type)+'</span></button>';
   h+='<div class="posbanner '+(disp.user_offense||disp.awaiting==='pat'||disp.awaiting==='2pt'?'off':'def')+'">'+ban+'</div>';
   if(kicks.length||to)h+='<div class="topacts">'+
     kicks.map(o=>'<button class="optbtn kick" '+dis+' data-k="'+esc(o.key)+'" onclick="gamePlay(this.dataset.k)">'+(o.key==='__FG__'?'🥅 ':'🦵 ')+esc(o.label)+'</button>').join('')+
     (to?'<button class="optbtn to sm" '+dis+' data-k="__TIMEOUT__" onclick="gamePlay(this.dataset.k)">⏱ '+esc(to.label)+'</button>':'')+
     '</div>';
   h+='<div class="optgrid">'+plays.map(pbtn).join('')+'</div>'+
   (playBusy?'<div class="note" style="margin-top:6px">Spielzug läuft … nächstes Play wählbar, sobald der Ball wieder liegt.</div>':'')+
   '<div style="margin-top:8px"><button class="ghost" onclick="simDrive()" '+dis+'>Drive simulieren</button> <button class="ghost" onclick="simRest()" '+dis+'>Spiel zu Ende simulieren</button></div>';}
 h+='<div class="commentary" style="margin-top:10px">'+disp.log.map(p=>'<div class="cmt"><span class="q">'+qLabel(p.q)+'</span>'+pbadge(p.desc)+'<span class="t">'+esc(p.desc)+'</span></div>').join('')+'</div>';
 $('gamemodal').innerHTML=h;
 if(play&&play.concept)animateGamePlay(play);
 else if(play&&play.kind==='fg')animateFG(play);           // Field Goal / Extra-Punkt — Kick-Animation
 else if(play&&play.kind==='punt')animatePunt(play);       // Punt — hoher Bogen, danach Ballwechsel
 else if(play&&play.penalty)animatePenalty(play);          // Flagge — Schiedsrichter wirft, dann Ergebnis
 else {playBusy=false; showFormation(g);}                   // 2PT/Wechsel: sofort wieder spielbar
}
/* Flagge fliegt aus der Hand eines Refs in hohem Bogen aufs Feld (eigene Animationsschleife). */
let _flagIv={};
function _throwFlag(svg,sx,sy,ex,ey){const P=svg.id;if(_flagIv[P])cancelAnimationFrame(_flagIv[P]);
 const flag=el('rect',{id:P+'_flag',x:sx-3.5,y:sy-3.5,width:7,height:7,rx:1.5,fill:'#ffd34d',stroke:'#b9930a','stroke-width':1});svg.appendChild(flag);
 const t0=performance.now(),dur=0.72;
 function fr(now){const t=Math.min(1,(now-t0)/1000/dur);
  const x=sx+(ex-sx)*t,y=sy+(ey-sy)*t-Math.sin(Math.PI*t)*46;
  flag.setAttribute('x',(x-3.5).toFixed(1));flag.setAttribute('y',(Math.max(8,y)-3.5).toFixed(1));
  flag.setAttribute('transform','rotate('+(t*560).toFixed(0)+' '+x.toFixed(1)+' '+Math.max(8,y).toFixed(1)+')');
  if(t<1)_flagIv[P]=requestAnimationFrame(fr);}
 _flagIv[P]=requestAnimationFrame(fr);}
/* Strafen-Karte: zeigt erst NACH dem Play, welche Strafe es war und wie die Yards verrechnet werden. */
function _penaltyCard(svg,play){const x=266,y=148,name=play.pen_name||'Strafe';
 let eff=(play.desc||'').replace(/^🚩\s*/,'');if(eff.length>48){const m=eff.split('—');eff=(m[1]||eff).trim();}
 const g=el('g',{});
 g.appendChild(el('rect',{x:x-156,y:y-34,width:312,height:70,rx:11,fill:'#0a0f0d',stroke:'#ffd34d','stroke-width':2}));
 const t0=el('text',{x:x,y:y-12,'text-anchor':'middle','font-size':12,fill:'#ffd34d','font-weight':800,'letter-spacing':2});t0.textContent='🚩 FLAGGE';
 const t1=el('text',{x:x,y:y+6,'text-anchor':'middle','font-size':15,fill:'#fff','font-weight':800});t1.textContent=name;
 const t2=el('text',{x:x,y:y+24,'text-anchor':'middle','font-size':10.5,fill:'#cdeede'});t2.textContent=eff;
 g.appendChild(t0);g.appendChild(t1);g.appendChild(t2);svg.appendChild(g);}
async function animatePenalty(play){const svg=$('gfield');if(!svg){playBusy=false;return;}const P=svg.id;if(_anim[P])cancelAnimationFrame(_anim[P]);
 const cont=()=>{setTimeout(()=>{playBusy=false;if(liveG)renderGame(liveG);},1500);};   // danach normaler Folgesnap
 const cols=liveG?gameCols(liveG,play.user_off):{off:'#16c784',def:'#ef5350'};
 let d=null;
 if(play.concept){try{d=await (await fetch('/api/sim/diagram?concept='+encodeURIComponent(play.concept)+'&coverage='+encodeURIComponent(play.coverage))).json();}catch(e){d=null;}}
 if(play.pre_snap||!d||d.error){                          // Vor-Snap-Foul: kein Snap, sofort Pfiff
   if(d&&!d.error)renderField(svg,d,play.dist0||10,cols,play.ytz0,true);
   else{let s='<rect width="533" height="360" fill="#0e4a2d"/>';for(let i=1;i<8;i++)s+='<line x1="0" y1="'+(i*44)+'" x2="533" y2="'+(i*44)+'" stroke="#dfeee6" stroke-width="1" opacity="0.16"/>';s+=_refFig(258,250);svg.innerHTML=s;}
   setTimeout(()=>_throwFlag(svg,250,120,292,250),250);
   setTimeout(()=>_penaltyCard(svg,play),1300);
   cont();return;}
 // Post-Snap: das echte Play läuft, der Ref wirft früh die Flagge, danach erscheint die Strafe
 renderField(svg,d,play.dist0||10,cols,play.ytz0);
 setTimeout(()=>{if(_anim[P])_throwFlag(svg,250,118,300,255);},520);   // Ref wirft, während der Spielzug läuft
 playAnim(svg,d,{kind:play.play_kind||'run',yards:play.play_yards||0,td:false,noResult:true},
   ()=>{_penaltyCard(svg,play);cont();});                 // erst Tackle, dann Flaggen-Info, dann Strafe
 return;
}
function gameCols(g,userOff){const me=(lastView&&lastView.color)||'#16c784';const opp=g.user_is_home?g.acolor:g.hcolor;
 const myAb=(lastView&&lastView.abbr)||(g.user_is_home?g.habbr:g.aabbr),opAb=g.user_is_home?g.aabbr:g.habbr;
 return userOff?{off:me,def:opp,offAbbr:myAb,defAbbr:opAb}:{off:opp,def:me,offAbbr:opAb,defAbbr:myAb};}
async function showFormation(g){const svg=$('gfield');if(!svg||!g||g.over)return;
 const concept=g.user_offense?((g.options[0]&&g.options[0].key)||'Inside Zone'):'Inside Zone';
 const coverage=g.user_offense?'Cover 2':((g.options[0]&&g.options[0].key)||'Cover 2');
 const d=await (await fetch('/api/sim/diagram?concept='+encodeURIComponent(concept)+'&coverage='+encodeURIComponent(coverage))).json();
 if(!d.error)renderField(svg,d,g.dist||10,gameCols(g,g.user_offense),g.ytz,true);}   // Vor-Snap-Aufstellung, Ball am aktuellen Spot
/* Snap-Count: Cadence (Down … Set … HUT!), dann fliegt der Ball aus der Center-Hand zum QB. */
function _snapSequence(svg,d,onDone){const P=svg.id;if(_anim[P])cancelAnimationFrame(_anim[P]);
 const qb=d.offense.find(o=>o.pos==='QB');const ball=$(P+'_pball');
 const losX=mapX(26.65),losY=mapY(-0.3),qbX=qb?mapX(qb.x):losX,qbY=qb?mapY(qb.y):losY;
 const cap=el('text',{id:P+'_cad',x:266,y:42,'text-anchor':'middle','font-size':20,'font-weight':800,fill:'#ffd34d'});cap.textContent='DOWN …';svg.appendChild(cap);
 if(ball){ball.setAttribute('opacity',1);ball.setAttribute('cx',losX);ball.setAttribute('cy',losY);ball.setAttribute('transform','');}
 const t0=performance.now();
 function fr(now){const e=(now-t0)/1000;
  if(cap)cap.textContent=e<0.45?'DOWN …':e<0.85?'SET …':'HUT!';
  if(e>=0.85&&ball){const t=Math.min(1,(e-0.85)/0.2);ball.setAttribute('cx',losX+(qbX-losX)*t);ball.setAttribute('cy',losY+(qbY-losY)*t);}   // Snap zum QB
  if(e<1.08)_anim[P]=requestAnimationFrame(fr);
  else{if(cap&&cap.remove)cap.remove();onDone();}
 }
 _anim[P]=requestAnimationFrame(fr);}
async function animateGamePlay(play){const svg=$('gfield');if(!svg||!play.concept)return;
 const variant=Math.floor(Math.random()*5);                  // Formation pro Snap mischen (auch Shotgun/FB)
 const d=await (await fetch('/api/sim/diagram?concept='+encodeURIComponent(play.concept)+'&coverage='+encodeURIComponent(play.coverage)+'&variant='+variant)).json();
 if(d.error)return; renderField(svg,d,play.dist0||10,liveG?gameCols(liveG,play.user_off):null,play.ytz0);  // Vor-Snap-Aufstellung am Spot
 const cl=liveG?gameCols(liveG,play.user_off):{off:'#16c784',def:'#ef5350'};
 const res={kind:play.kind,yards:play.yards,td:play.td,celColor:cl.off,celDef:cl.def,spd:play.spd,fumble:play.turnover,fpos:play.ytz0};
 _snapSequence(svg,d,()=>playAnim(svg,d,res,()=>{playBusy=false;if(liveG)renderGame(liveG);}));}   // Cadence + Snap, dann das Play
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
function animatePunt(play){const svg=$('gfield');if(!svg){playBusy=false;return;}const P=svg.id;if(_anim[P])cancelAnimationFrame(_anim[P]);
 const cols=liveG?gameCols(liveG,play.user_off):{off:'#16c784',def:'#ef5350'};const net=play.punt_net||40;
 let s='<defs><linearGradient id="pt_'+P+'" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0e4a2d"/><stop offset="1" stop-color="#0b3a22"/></linearGradient></defs>'+
  '<rect x="0" y="0" width="533" height="360" fill="url(#pt_'+P+')"/>'+
  '<text x="266" y="38" text-anchor="middle" font-size="15" font-weight="800" fill="#cdeede">Punt — '+net+' Yard'+(play.touchback?' · Touchback':'')+'</text>';
 for(let i=1;i<8;i++)s+='<line x1="0" y1="'+(i*44)+'" x2="533" y2="'+(i*44)+'" stroke="#dfeee6" stroke-width="1" opacity="0.16"/>';
 for(let i=0;i<5;i++)s+=_fgFig(200+i*33,300,cols.off);                 // Schutzwall
 s+=_fgFig(266,324,cols.off);                                          // Punter
 for(let i=0;i<3;i++)s+=_fgFig(214+i*52,150,cols.def);                 // Return-Team
 svg.innerHTML=s;
 const ball=el('ellipse',{id:P+'_pball',cx:266,cy:318,rx:4,ry:2.5,fill:'#9a5a1e',stroke:'#3a1f08','stroke-width':1,opacity:1});svg.appendChild(ball);
 const t0=performance.now();
 function frame(now){const e=(now-t0)/1000,t=Math.min(1,e/1.45);
  const by=318-t*250-Math.sin(Math.PI*t)*64,bx=266+Math.sin(t*2.4)*8;
  ball.setAttribute('cx',bx.toFixed(1));ball.setAttribute('cy',by.toFixed(1));
  ball.setAttribute('transform','rotate('+(t*760).toFixed(0)+' '+bx.toFixed(1)+' '+by.toFixed(1)+')');
  if(e<=1.7)_anim[P]=requestAnimationFrame(frame);
  else{ball.setAttribute('opacity',0);setTimeout(()=>{playBusy=false;if(liveG)renderGame(liveG);},650);}
 }
 _anim[P]=requestAnimationFrame(frame);
}
async function gamePlay(choice){if(playBusy)return;playBusy=true;_preG=liveG;const r=await api('/api/fr/game/play?choice='+encodeURIComponent(choice),'POST');if(r.error){playBusy=false;_preG=null;alert(r.error);return;}liveG=r.game;renderGame(r.game,r.play);}
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
let _evt={b0:0,b1:0,d:0};
function evtPick(b){const g=b.dataset.g;_evt[g]=+b.dataset.i;
 document.querySelectorAll('.evtopt[data-g="'+g+'"]').forEach(x=>x.classList.toggle('on',x===b));}
async function resolveEvent(){const r=await api('/api/fr/resolve_event?b0='+_evt.b0+'&b1='+_evt.b1+'&d='+_evt.d,'POST');
 if(r.error){alert(r.error);return;}_evt={b0:0,b1:0,d:0};if(r.view)renderMgr(r.view);}
/* ---------- Wochen-Meeting (jede Woche ein Paket aus 1 Buff + 1 Debuff wählen) ---------- */
function openMeeting(){const v=lastView;if(!v||!v.meeting)return;closeMeeting();const m=v.meeting;
 const o=document.createElement('div');o.className='overlay';o.id='meetingoverlay';
 o.addEventListener('click',e=>{if(e.target===o)closeMeeting();});
 o.innerHTML='<div class="modal meetwrap"><div class="modalhead"><h3>📋 '+esc(m.title)+'</h3><button class="ghost" onclick="closeMeeting()">Später</button></div>'+
   '<div class="note" style="margin-top:0">Wähle genau <b>ein</b> Paket. Jedes bringt einen Vorteil — und einen Nachteil.</div>'+
   '<div class="meetgrid">'+m.options.map((opt,i)=>'<button class="meetopt" data-i="'+i+'" onclick="resolveMeeting(this.dataset.i)">'+
     '<div class="moh">Paket '+(i+1)+'</div>'+
     '<div class="mobuff"><span class="mosign good">＋</span>'+esc(opt.buff)+'</div>'+
     '<div class="modeb"><span class="mosign bad">－</span>'+esc(opt.debuff)+'</div>'+
     '<div class="mopick">Dieses Paket wählen</div></button>').join('')+'</div></div>';
 document.body.appendChild(o);lockBody();}
function closeMeeting(){const o=$('meetingoverlay');if(o)o.remove();unlockBodyIfNone();}
async function resolveMeeting(i){const r=await api('/api/fr/resolve_meeting?idx='+i,'POST');if(r.error){alert(r.error);return;}closeMeeting();if(r.view)renderMgr(r.view);}
async function nextWeek(){const r=await api('/api/fr/next_week','POST');if(r.error){alert(r.error);return;}if(r.view)renderMgr(r.view);}
/* ---------- Interaktives Tutorial (führt durch die Oberfläche) ---------- */
const TUT=[
 {tab:'dash',sel:'.tbanner',title:'Deine Franchise',text:'Hier oben siehst du dein Team, Bilanz, Budget, Skillpunkte und die Saisonwoche.'},
 {tab:'dash',sel:'.subnav',title:'Bereiche',text:'Über diese Reiter steuerst du alles: Dashboard, Kader & Training, Statistik, Transfermarkt und Verbesserungen.'},
 {tab:'dash',sel:'#goalcard',title:'Saison-Ziele',text:'Das Front-Office gibt dir Ziele vor. Erfüllst du sie, gibt es Budget-Belohnungen.'},
 {tab:'dash',sel:'#gamecard',title:'Spiel & Woche',text:'Spiel selbst spielen oder simulieren. Erst danach schaltest du mit „Nächste Woche" weiter — die Woche endet nie von allein.'},
 {tab:'train',sel:'.traingrid',title:'Training',text:'Wähle 1× pro Woche ein Training (Team, Einzel, Film-Session …). Hier verwaltest du auch dein Schema und den Trainerstab.'},
 {tab:'kader',sel:'.prow',title:'Spieler entwickeln',text:'Klicke einen Spieler an, um seine Attribute mit Skillpunkten zu steigern und ihn als Starter zu setzen.'},
 {tab:'transfer',sel:'.card',title:'College-Scouting & Transfermarkt',text:'Scoute College-Talente mit deinen Scouting-Punkten, um Können, Potenzial und Entwicklungs-Trait aufzudecken — dann draften. Darunter findest du fertige Free Agents. Jede Saison: Ruhestand + neuer Jahrgang.'},
 {tab:'liga',sel:'.card',title:'Liga',text:'Tabelle, Liga-Spitze, deine Saison-Bestenliste und Gegner-Scouting an einem Ort.'},
 {tab:'build',sel:'.card',title:'Anlagen',text:'Deine Vereinswelt: Stadion (mehr Geld), Trainingsgelände (mehr EXP) und freischaltbare Erweiterungen. Viel Erfolg!'},
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

    async def _bind_profile(profile: str = "default"):
        from gridiron import franchise as F          # Spielstand pro Profilname trennen
        F.set_profile(profile)

    app = FastAPI(title="Gridiron", version="0.1", dependencies=[Depends(_bind_profile)])
    _state: dict = {"predictor": None}

    @app.middleware("http")
    async def _headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["X-Gridiron-Build"] = _BUILD
        # HTML nie cachen -> Handy lädt immer die aktuelle Version (kein „tote Seite" durch alten Cache)
        if "text/html" in resp.headers.get("content-type", ""):
            resp.headers["Cache-Control"] = "no-store, must-revalidate"
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
    def sim_diagram(concept: str, coverage: str, variant: int = 0):
        from gridiron.playviz import diagram
        try:
            return diagram(concept, coverage, variant)
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

    @app.post("/api/fr/resolve_event")
    def fr_resolve_event(b0: int = 0, b1: int = 0, d: int = 0):
        from gridiron import franchise as F
        st, err = _fr_load_or_404()
        if err:
            return err
        return F.resolve_event(cfg, st, b0, b1, d)

    @app.post("/api/fr/resolve_meeting")
    def fr_resolve_meeting(idx: int = 0):
        from gridiron import franchise as F
        st, err = _fr_load_or_404()
        if err:
            return err
        return F.resolve_meeting(cfg, st, idx)

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
