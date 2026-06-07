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
 :root{--bg:#0f1714;--panel:#16211c;--fg:#e7efe9;--mut:#8aa597;--line:#26352e;
   --acc:#21c074;--accsoft:#143226;--warn:#f0b429;--bad:#ef5d5d}
 *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--fg);
   font:16px/1.55 ui-sans-serif,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
 a{color:var(--acc)}
 .top{background:var(--panel);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}
 .topin{max-width:980px;margin:0 auto;padding:13px 18px;display:flex;align-items:center;justify-content:space-between}
 .brand{font-size:20px;font-weight:800;letter-spacing:-.01em}
 .brand b{color:var(--acc)} .nav a{margin-left:16px;font-size:14px;color:var(--mut);text-decoration:none}
 .wrap{max-width:980px;margin:0 auto;padding:20px 18px}
 .lead{color:var(--mut);margin:2px 0 16px}
 .controls{display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end}
 label{display:block;font-size:12px;color:var(--mut);margin-bottom:4px;text-transform:uppercase;letter-spacing:.04em}
 select,input{padding:11px 12px;border-radius:10px;border:1px solid var(--line);
   background:var(--panel);color:var(--fg);font-size:15px}
 select:focus,input:focus{outline:none;border-color:var(--acc)}
 button{padding:11px 18px;border:0;border-radius:10px;background:var(--acc);color:#04140c;
   font-weight:700;cursor:pointer;font-size:15px} button:hover{filter:brightness(1.07)}
 .card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin:14px 0}
 .big{font-size:28px;font-weight:800} .row{display:flex;gap:22px;flex-wrap:wrap}
 .kpi{flex:1;min-width:120px} .kpi .l{font-size:12px;color:var(--mut);text-transform:uppercase}
 .kpi .v{font-size:22px;font-weight:700}
 .sec{font-size:12px;color:var(--mut);text-transform:uppercase;letter-spacing:.06em;margin:18px 0 8px;font-weight:700}
 table{width:100%;border-collapse:collapse;font-size:14px} th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line)}
 th{color:var(--mut);font-weight:600;font-size:12px;text-transform:uppercase}
 .barwrap{position:relative;background:var(--accsoft);border-radius:6px;height:18px;min-width:120px;overflow:hidden}
 .bar{position:absolute;inset:0 auto 0 0;background:var(--acc);border-radius:6px}
 .barleague{position:absolute;top:0;bottom:0;width:2px;background:#fff;opacity:.7}
 .tell{padding:9px 12px;border-left:3px solid var(--warn);background:#1d2419;border-radius:8px;margin:7px 0;font-size:14px}
 .up{color:var(--acc)} .down{color:var(--bad)}
 .gauge{height:26px;border-radius:13px;background:linear-gradient(90deg,#2b7d52,#21c074);position:relative;overflow:hidden;border:1px solid var(--line)}
 .gmark{position:absolute;top:-3px;bottom:-3px;width:3px;background:#fff}
 .pill{display:inline-block;background:var(--accsoft);color:var(--acc);font-weight:700;
   padding:3px 11px;border-radius:20px;font-size:13px}
 .mut{color:var(--mut);font-size:13px} .foot{color:var(--mut);font-size:12px;text-align:center;margin:26px 0}
 @media(max-width:560px){.controls{flex-direction:column;align-items:stretch} select,input,button{width:100%}}
"""

_PAGE = """<!doctype html><html lang="de"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Gridiron — NFL-Scouting</title><style>""" + _STYLE + """</style></head><body>
<div class="top"><div class="topin">
 <div class="brand">Grid<b>iron</b></div>
 <div class="nav"><a href="/">Scouting</a><a href="/report" target="_blank">Druck-Report</a></div>
</div></div>
<div class="wrap">
 <div class="lead">Wähle ein Team — Gridiron liefert Tendenzen, „Tells" und die Live-Pass/Lauf-Vorhersage.</div>
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
 <div class="foot">Deskriptive/prognostische Analyse echter Plays — keine Garantie auf Ausgänge.</div>
</div>
<script>
const $=id=>document.getElementById(id);
function esc(s){const d=document.createElement('div');d.textContent=(s==null?'':s);return d.innerHTML;}
const pct=x=>Math.round(x*100)+'%';

async function init(){
 const d=await (await fetch('/api/teams')).json();
 $('team').innerHTML=d.teams.map(t=>'<option>'+esc(t)+'</option>').join('');
 $('season').innerHTML='<option value="">alle</option>'+d.seasons.map(s=>'<option>'+s+'</option>').join('');
 if(d.teams.length){loadScout();}
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

    return app
