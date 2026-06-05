"""Web-Oberfläche & API für Synapse.

Forschungs-Assistent im Browser: Frage stellen -> faktenbasierte Einordnung
(gibt es das? was gibt es? aktiv/reif? Brücken?) + Trefferliste mit Quellen.
Klicks werden protokolliert (Grundlage fürs lernende Ranking). Alles lokal.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from synapse.config import Config, load_config
from synapse.storage import SynapseStore

_COOKIE = "sid"
_COOKIE_MAXAGE = 30 * 24 * 3600


class RegisterIn(BaseModel):
    username: str
    password: str
    name: str = ""
    email: str = ""
    orcid: str = ""
    affiliation: str = ""
    bio: str = ""
    account_type: str = "other"


class LoginIn(BaseModel):
    username: str
    password: str


class ProfileIn(BaseModel):
    name: str = ""
    affiliation: str = ""
    orcid: str = ""
    bio: str = ""
    account_type: str = ""


class ProjectIn(BaseModel):
    title: str
    area: str = ""
    description: str = ""
    owner_name: str = ""
    owner_orcid: str = ""
    ptype: str = "research"


class ContribIn(BaseModel):
    kind: str = "finding"
    title: str
    body: str = ""
    link: str = ""
    evidence_doi: str = ""
    contributor_name: str = ""
    contributor_orcid: str = ""


class ReportIn(BaseModel):
    reason: str = ""


class ModerateIn(BaseModel):
    project_id: str
    owner_token: str
    contribution_id: str
    action: str


class PasswordIn(BaseModel):
    old_password: str
    new_password: str

log = logging.getLogger(__name__)

_PAGE = """<!doctype html><html lang="de"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Synapse — Forschungs-Assistent</title>
<style>
 :root{--bg:#f5f7fb;--surface:#fff;--fg:#1f2a37;--mut:#64748b;--border:#e2e8f0;
   --acc:#1d4ed8;--accsoft:#eef3ff}
 *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--fg);
   font:16px/1.6 ui-sans-serif,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
 a{color:var(--acc)}
 .topbar{background:var(--surface);border-bottom:1px solid var(--border);position:sticky;top:0;z-index:5}
 .topin{max-width:860px;margin:0 auto;padding:13px 18px;display:flex;align-items:center;justify-content:space-between}
 .brand{font-size:20px;font-weight:700;letter-spacing:-.01em} .brand span{color:var(--acc)}
 .nav a{margin-left:18px;font-size:14px;text-decoration:none;color:var(--mut)} .nav a:hover{color:var(--fg)}
 .wrap{max-width:860px;margin:0 auto;padding:22px 18px}
 .lead{color:var(--mut);font-size:15px;margin:2px 0 14px}
 form{display:flex;gap:8px;margin:8px 0 4px}
 input{flex:1;padding:13px 15px;border-radius:10px;border:1px solid var(--border);
   background:var(--surface);color:var(--fg);font-size:16px}
 input:focus{outline:none;border-color:var(--acc);box-shadow:0 0 0 3px var(--accsoft)}
 button{padding:13px 18px;border:0;border-radius:10px;background:var(--acc);
   color:#fff;font-weight:600;font-size:15px;cursor:pointer} button:hover{filter:brightness(1.06)}
 .brief{border:1px solid var(--border);border-left:4px solid var(--acc);border-radius:12px;
   background:var(--surface);padding:18px 20px;margin:12px 0 18px;box-shadow:0 1px 2px rgba(16,24,40,.04)}
 .verdict{font-size:17px;font-weight:600;line-height:1.45}
 .act{color:var(--mut);font-size:14px;margin-top:6px}
 .chips{margin:12px 0 2px} .chip{display:inline-block;background:var(--accsoft);color:#1e40af;
   font-size:12px;padding:4px 10px;border-radius:20px;margin:3px 6px 3px 0;font-weight:500}
 .trendwrap{margin:14px 0 4px}
 .trendlabel{font-size:13px;color:var(--fg);font-weight:600}
 .trendlabel .tl{font-weight:700}
 .bars{display:flex;align-items:flex-end;gap:4px;height:46px;margin:8px 0 2px}
 .bar{flex:1;min-width:6px;background:var(--accsoft);border-radius:3px 3px 0 0;position:relative}
 .bar i{position:absolute;inset:0;background:var(--acc);border-radius:3px 3px 0 0;opacity:.85}
 .byrs{display:flex;gap:4px;color:var(--mut);font-size:10px}
 .byrs span{flex:1;text-align:center}
 .gap{border-left:3px solid #f59e0b;background:#fffbeb;color:#92600c;font-size:13.5px;
   padding:9px 13px;border-radius:8px;margin:10px 0}
 .blk{margin-top:14px} .blk b{font-size:12px;color:var(--mut);text-transform:uppercase;letter-spacing:.04em}
 .blk a{display:block;color:var(--fg);font-size:14px;text-decoration:none;padding:5px 0;border-bottom:1px solid #f1f4f8}
 .blk a:hover{color:var(--acc)}
 .sech{color:var(--mut);font-size:12px;margin:22px 0 8px;text-transform:uppercase;letter-spacing:.06em;font-weight:600}
 .hit{padding:15px 17px;border:1px solid var(--border);border-radius:12px;margin:10px 0;background:var(--surface)}
 .hit:hover{border-color:#c7d2fe}
 .t{font-weight:600;line-height:1.35} .m{color:var(--mut);font-size:13px;margin-top:5px}
 .sc{color:var(--acc);font-variant-numeric:tabular-nums;font-weight:600}
 .relbtn{margin-top:10px;font-size:12px;color:var(--acc);background:#fff;
   border:1px solid var(--border);border-radius:8px;padding:5px 11px;cursor:pointer} .relbtn:hover{border-color:var(--acc)}
 .rel{margin-top:10px;border-top:1px solid var(--border);padding-top:8px}
 .rel a{display:block;color:var(--mut);font-size:13px;padding:5px 0;text-decoration:none} .rel a:hover{color:var(--fg)}
 .badge{display:inline-block;background:#e7f6ee;color:#1f7a4d;font-size:11px;
   padding:2px 8px;border-radius:6px;margin-left:6px;font-weight:600}
 .foot{color:var(--mut);font-size:12px;text-align:center;margin:28px 0}
 .empty{color:var(--mut);text-align:center;margin:30px 0}
 .contrib{margin:24px 0 6px;border:1px solid var(--border);border-radius:12px;padding:10px 16px;background:var(--surface)}
 .contrib summary{cursor:pointer;color:var(--acc);font-size:14px;font-weight:500}
 .cbox{color:var(--mut);font-size:13px;margin-top:10px} .cbox form{margin:8px 0 4px}
 .exrow{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:10px 0 6px}
 .exlbl{color:var(--mut);font-size:13px;width:100%;margin-bottom:2px}
 .exchip{background:var(--surface);border:1px solid var(--border);color:var(--fg);
   font-size:14px;padding:9px 14px;border-radius:22px;cursor:pointer;line-height:1}
 .exchip:active,.exchip:hover{border-color:var(--acc);color:var(--acc);background:var(--accsoft)}
 .how{margin:18px 0 4px;display:grid;gap:10px}
 .how div{display:flex;gap:10px;align-items:flex-start;color:var(--mut);font-size:13.5px}
 .how b{color:var(--fg);font-weight:600} .how span{color:var(--acc);font-weight:700}
 @media(max-width:520px){
   form{flex-direction:column} form button{width:100%;padding:14px}
   .topin{padding:12px 16px} .nav a{margin-left:14px}
   .wrap{padding:18px 16px} .lead{font-size:16px}
 }
</style></head><body>
<div class="topbar"><div class="topin">
 <div class="brand">Syn<span>apse</span></div>
 <div class="nav"><a href="/">Suche</a><a href="/projekte">Projekte</a><a href="/konto">Konto</a></div>
</div></div>
<div class="wrap">
 <div class="lead">Stelle eine Forschungsfrage — Synapse ordnet die Studienlage ein und nennt die Quellen.</div>
 <form id="f"><input id="q" placeholder="z. B. Schlaf und Gedächtnis" autofocus>
 <button>Analysieren</button></form>
 <div id="examples" class="exrow">
  <span class="exlbl">Zum Ausprobieren:</span>
  <button type="button" class="exchip" onclick="runEx('Schlaf und Gedächtnis')">Schlaf und Gedächtnis</button>
  <button type="button" class="exchip" onclick="runEx('Künstliche Intelligenz in der Medizin')">KI in der Medizin</button>
  <button type="button" class="exchip" onclick="runEx('Mikroplastik und Gesundheit')">Mikroplastik & Gesundheit</button>
  <button type="button" class="exchip" onclick="runEx('CRISPR Genom-Editierung')">CRISPR Genom-Editierung</button>
  <button type="button" class="exchip" onclick="runEx('Klimawandel und Landwirtschaft')">Klima & Landwirtschaft</button>
 </div>
 <div id="how" class="how">
  <div><span>1</span><div><b>Einordnung statt Linkliste.</b> Gibt es dazu Forschung? Wie viel, wie aktuell, aktives Feld oder Lücke?</div></div>
  <div><span>2</span><div><b>Immer mit Quellen.</b> Einflussreichste und neueste Arbeiten – direkt zur DOI verlinkt.</div></div>
  <div><span>3</span><div><b>Brücken zwischen Feldern.</b> Synapse zeigt verwandte Arbeiten aus anderen Disziplinen.</div></div>
 </div>
 <div id="brief"></div>
 <div id="r"></div>
 <details class="contrib"><summary>＋ Eigene Forschung beitragen</summary>
  <div class="cbox">Nur <b>offiziell registrierte</b> Arbeiten mit gültiger DOI
   (geprüft über OpenAlex/Crossref) – so kommt nichts Ungeprüftes hinein.
   <form id="cf"><input id="doi" placeholder="DOI, z.B. 10.1038/s41586-021-03819-2">
   <button>Prüfen & hinzufügen</button></form>
   <div id="cmsg" class="m"></div></div>
 </details>
 <div class="foot">Lokal & quellenbasiert · keine Anlage-/Medizin-/Rechtsberatung<br>
  <a href="/impressum">Impressum</a> · <a href="/datenschutz">Datenschutz</a> ·
  <a href="/nutzungsbedingungen">Nutzungsbedingungen</a></div>
</div>
<script>
const r=document.getElementById('r'), br=document.getElementById('brief'), q=document.getElementById('q');
function esc(s){const d=document.createElement('div');d.textContent=(s==null?'':s);return d.innerHTML;}
function link(w){return w.doi?('https://doi.org/'+w.doi):('https://openalex.org/'+w.id);}

function renderBrief(b){
 if(b.error){br.innerHTML='<div class="empty">'+esc(b.error)+'</div>';return;}
 let h='<div class="brief"><div class="verdict">'+esc(b.verdict)+'</div>';
 if(b.activity)h+='<div class="act">Einordnung: '+esc(b.activity)+
   (b.year_min?(' · Zeitraum '+b.year_min+'–'+b.year_max):'')+'</div>';
 if(b.themes&&b.themes.length){h+='<div class="chips">';
   b.themes.forEach(t=>h+='<span class="chip">'+esc(t)+'</span>');h+='</div>';}
 if(b.trend_label){
   h+='<div class="trendwrap"><div class="trendlabel">Trend: <span class="tl">'+esc(b.trend_label)+'</span></div>';
   if(b.trend&&b.trend.length){
     const mx=Math.max(1,...b.trend.map(t=>t.count));
     h+='<div class="bars">'+b.trend.map(t=>'<div class="bar" title="'+t.year+': '+t.count+
       '"><i style="top:'+(100-Math.round(t.count/mx*100))+'%"></i></div>').join('')+'</div>';
     h+='<div class="byrs">'+b.trend.map(t=>'<span>'+(String(t.year).slice(2))+'</span>').join('')+'</div>';
   }
   h+='</div>';
 }
 if(b.emerging&&b.emerging.length){h+='<div class="chips">Aufkommend: ';
   b.emerging.forEach(t=>h+='<span class="chip">'+esc(t)+'</span>');h+='</div>';}
 if(b.gap)h+='<div class="gap">'+esc(b.gap)+'</div>';
 if(b.top_works&&b.top_works.length){h+='<div class="blk"><b>Einflussreichste Arbeiten</b>';
   b.top_works.forEach(w=>h+='<a target="_blank" href="'+link(w)+'">'+esc(w.title)+
     ' ('+(w.year||'—')+', '+w.cited_by_count+' Zit.)</a>');h+='</div>';}
 if(b.recent_works&&b.recent_works.length){h+='<div class="blk"><b>Neueste Arbeiten</b>';
   b.recent_works.forEach(w=>h+='<a target="_blank" href="'+link(w)+'">'+esc(w.title)+
     ' ('+(w.year||'—')+')</a>');h+='</div>';}
 if(b.bridges&&b.bridges.length){h+='<div class="blk"><b>Brücken in andere Felder</b>';
   b.bridges.forEach(c=>h+='<a target="_blank" href="'+link(c)+'">'+esc(c.title)+
     '<span class="badge">→ '+esc(c.field)+'</span></a>');h+='</div>';}
 h+='</div>';
 br.innerHTML=h;
}

function renderResults(query,results){
 if(!results||!results.length){r.innerHTML='';return;}
 r.innerHTML='<div class="sech">Alle Treffer</div>';
 results.forEach((h,i)=>{
  const card=document.createElement('div'); card.className='hit';
  const meta=[h.year||'—',h.venue,(h.cited_by_count+' Zit.')].filter(Boolean).join(' · ');
  const a=document.createElement('a'); a.target='_blank'; a.href=link(h);
  a.style.textDecoration='none'; a.style.color='inherit';
  a.innerHTML='<div class="t">'+(i+1)+'. '+esc(h.title)+'</div>'+
   '<div class="m">'+esc(meta)+' · <span class="sc">'+h.score.toFixed(3)+'</span></div>';
  a.addEventListener('click',()=>{fetch('/api/feedback?q='+encodeURIComponent(query)+
    '&work_id='+encodeURIComponent(h.id)+'&rank='+i,{method:'POST'});});
  card.appendChild(a);
  const btn=document.createElement('button'); btn.className='relbtn'; btn.textContent='↔ Verbindungen';
  const panel=document.createElement('div'); panel.className='rel'; panel.style.display='none';
  btn.addEventListener('click',async()=>{
   if(panel.dataset.loaded){panel.style.display=(panel.style.display==='none'?'block':'none');return;}
   panel.style.display='block'; panel.innerHTML='<div class="m">lädt …</div>';
   let rd; try{rd=await(await fetch('/api/related?id='+encodeURIComponent(h.id)+'&k=8')).json();}
   catch(_){panel.innerHTML='<div class="m">Fehler.</div>';return;}
   panel.dataset.loaded='1';
   if(!rd.related||!rd.related.length){panel.innerHTML='<div class="m">Keine Verbindungen.</div>';return;}
   panel.innerHTML='<div class="m">Feld: '+esc(rd.field||'—')+' · verwandte Arbeiten:</div>';
   rd.related.forEach(c=>{const lk=document.createElement('a');lk.target='_blank';lk.href=link(c);
    lk.innerHTML=esc(c.title)+(c.cross_field?('<span class="badge">Brücke → '+esc(c.field)+'</span>'):'');
    panel.appendChild(lk);});
  });
  card.appendChild(btn); card.appendChild(panel); r.appendChild(card);
 });
}

async function doSearch(query){
 query=(query||'').trim(); if(!query)return;
 const ex=document.getElementById('examples'), how=document.getElementById('how');
 if(ex)ex.style.display='none'; if(how)how.style.display='none';   // Intro ausblenden
 br.innerHTML='<div class="empty">Analysiere Forschungslage …</div>'; r.innerHTML='';
 let b; try{b=await(await fetch('/api/ask?q='+encodeURIComponent(query))).json();}
 catch(_){br.innerHTML='<div class="empty">Fehler.</div>';return;}
 renderBrief(b); renderResults(query,b.results);
}
function runEx(t){q.value=t; doSearch(t);}
document.getElementById('f').addEventListener('submit',e=>{e.preventDefault(); doSearch(q.value);});

const cf=document.getElementById('cf'), cmsg=document.getElementById('cmsg'), doi=document.getElementById('doi');
cf.addEventListener('submit',async e=>{
 e.preventDefault(); const v=doi.value.trim(); if(!v)return;
 cmsg.textContent='Prüfe DOI …';
 let d; try{d=await(await fetch('/api/submit?doi='+encodeURIComponent(v),{method:'POST'})).json();}
 catch(_){cmsg.textContent='Fehler.';return;}
 cmsg.textContent=(d.ok?('✓ '+esc(d.title)+' — '+d.message):('✗ '+d.message));
 if(d.ok)doi.value='';
});
</script></body></html>"""


_PROJECTS_PAGE = """<!doctype html><html lang="de"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Synapse — Offene Forschung</title>
<style>
 :root{--bg:#f5f7fb;--surface:#fff;--fg:#1f2a37;--mut:#64748b;--border:#e2e8f0;
   --acc:#1d4ed8;--accsoft:#eef3ff}
 *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--fg);
   font:16px/1.6 ui-sans-serif,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
 a{color:var(--acc);text-decoration:none}
 .topbar{background:var(--surface);border-bottom:1px solid var(--border)}
 .topin{max-width:860px;margin:0 auto;padding:13px 18px;display:flex;align-items:center;justify-content:space-between}
 .brand{font-size:20px;font-weight:700} .brand span{color:var(--acc)}
 .nav a{margin-left:18px;font-size:14px;color:var(--mut)} .nav a:hover{color:var(--fg)}
 .wrap{max-width:860px;margin:0 auto;padding:22px 18px}
 h1{font-size:22px;margin:6px 0} h2{font-size:19px;margin:4px 0} h3{font-size:14px;
   text-transform:uppercase;letter-spacing:.05em;color:var(--mut);margin:18px 0 6px}
 input,textarea,select{width:100%;padding:11px 13px;border-radius:10px;border:1px solid var(--border);
   background:var(--surface);color:var(--fg);font-size:15px;margin:6px 0}
 input:focus,textarea:focus,select:focus{outline:none;border-color:var(--acc);box-shadow:0 0 0 3px var(--accsoft)}
 textarea{min-height:96px} button{padding:11px 16px;border:0;border-radius:10px;
   background:var(--acc);color:#fff;font-weight:600;cursor:pointer} button:hover{filter:brightness(1.06)}
 .card{border:1px solid var(--border);border-radius:12px;background:var(--surface);
   padding:15px 17px;margin:10px 0;box-shadow:0 1px 2px rgba(16,24,40,.04)}
 .mut{color:var(--mut);font-size:13px} .row{display:flex;gap:8px;flex-wrap:wrap}
 .badge{font-size:11px;padding:2px 9px;border-radius:7px;margin-left:6px;font-weight:600}
 .verified{background:#e7f6ee;color:#1f7a4d} .preprint{background:#fdf3e0;color:#9a6a12}
 .community{background:#eef1f5;color:#5b6776} .flagged{background:#fdeaea;color:#b42323}
 .student{background:#eef3ff;color:#1e40af} .researcher{background:#eef1f5;color:#5b6776}
 .lbl{font-size:12px;color:var(--mut);font-weight:600;margin-top:6px}
 .pill{display:inline-block;background:var(--accsoft);color:#1e40af;font-size:12px;
   padding:3px 10px;border-radius:20px;font-weight:500}
 details summary{cursor:pointer;color:var(--acc);font-weight:500} .ok{color:#1f7a4d} .err{color:#b42323}
 .tokbox{background:#f0fdf4;border:1px solid #bbf7d0;border-radius:10px;padding:11px;margin:8px 0;word-break:break-all}
</style></head><body>
<div class="topbar"><div class="topin">
 <div class="brand">Syn<span>apse</span></div>
 <div class="nav"><a href="/">Suche</a><a href="/projekte">Projekte</a><a href="/konto">Konto</a></div>
</div></div>
<div class="wrap">
<h1>Offene Forschung</h1>
<p class="mut">Lege einen Forschungsbereich an und teile Ergebnisse & Zwischenstände –
andere können darauf aufbauen. Jeder Beitrag trägt eine Vertrauens-Stufe.
<b>Keine medizinische/rechtliche Beratung.</b></p>

<details><summary>＋ Neuen Forschungsbereich anlegen</summary>
 <div class="card">
  <input id="p_title" placeholder="Titel, z.B. Forschung zu Schlafstörungen">
  <input id="p_area" placeholder="Bereich/Schlagworte, z.B. Neurowissenschaften, Schlaf">
  <div class="lbl">Projekt-Typ</div>
  <select id="p_type"><option value="research">Forschung</option>
   <option value="student">Studienprojekt / Lehre (Uni)</option></select>
  <textarea id="p_desc" placeholder="Worum geht es? Ziel, Stand, was gesucht wird …"></textarea>
  <div class="mut">Wird unter deinem Profil angelegt. <a href="/konto">Konto</a> nötig.
   Studienprojekte sind ausdrücklich willkommen – sie werden klar gekennzeichnet.</div>
  <button onclick="createProject()">Projekt anlegen</button>
  <div id="p_msg" class="mut"></div>
 </div>
</details>

<div class="row" style="margin:14px 0"><input id="q" placeholder="Projekte durchsuchen …" style="flex:1">
 <button onclick="loadList()">Suchen</button></div>
<div id="list"></div>
<div id="detail"></div>

<script>
const $=id=>document.getElementById(id);
function esc(s){const d=document.createElement('div');d.textContent=(s==null?'':s);return d.innerHTML;}
function badge(t){return '<span class="badge '+t+'">'+t+'</span>';}
// Ehrliches Identitäts-Abzeichen je Beitrag: ORCID > Student:in > Forscher:in.
function authorBadge(c){
 if(c.author_verified)return ' <span class="badge verified">ORCID ✓</span>';
 if(c.author_type==='student')return ' <span class="badge student">Student:in'+
   (c.author_affiliation?(' · '+esc(c.author_affiliation)):'')+'</span>';
 if(c.author_type==='researcher')return ' <span class="badge researcher">Forscher:in'+
   (c.author_affiliation?(' · '+esc(c.author_affiliation)):'')+'</span>';
 return '';
}

async function createProject(){
 const body={title:$('p_title').value,area:$('p_area').value,description:$('p_desc').value,
   ptype:$('p_type').value};
 const d=await (await fetch('/api/projects',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify(body)})).json();
 if(!d.ok){$('p_msg').innerHTML='<span class="err">'+esc(d.message)+' <a href="/konto">→ anmelden</a></span>';return;}
 $('p_msg').innerHTML='<div class="ok">'+esc(d.message)+'</div>'+
  '<div class="tokbox"><b>Owner-Token (jetzt sichern!):</b><br>'+esc(d.data.owner_token)+'</div>';
 loadList(); openProject(d.data.id);
}
async function loadList(){
 const q=encodeURIComponent($('q').value||'');
 const d=await (await fetch('/api/projects?q='+q)).json();
 $('list').innerHTML=d.projects.map(p=>'<div class="card"><a href="#" onclick="openProject(\\''+p.id+
  '\\');return false"><b>'+esc(p.title)+'</b></a> <span class="pill">'+esc(p.area||'—')+'</span>'+
  (p.status==='archived'?' <span class="badge flagged">archiviert</span>':'')+
  '<div class="mut">'+p.contributions+' Beiträge · von '+esc(p.owner_name)+'</div></div>').join('')
  || '<div class="mut">Noch keine Projekte – leg das erste an.</div>';
}
async function openProject(id){
 const p=await (await fetch('/api/projects/get?id='+encodeURIComponent(id))).json();
 if(p.error){$('detail').innerHTML='';return;}
 const tlabel=p.ptype==='student'?'Studienprojekt':'Forschung';
 let h='<div class="card"><h2>'+esc(p.title)+'</h2><span class="pill">'+esc(p.area||'—')+'</span>'+
  ' <span class="badge '+(p.ptype==='student'?'student':'researcher')+'">'+tlabel+'</span>'+
  '<p class="mut">'+esc(p.description||'')+'</p><div class="mut">von '+esc(p.owner_name)+
  (p.owner_orcid?(' · ORCID '+esc(p.owner_orcid)):'')+' · Lizenz '+esc(p.license)+'</div>';
 h+='<h3>Beiträge</h3>';
 if(!p.contributions.length)h+='<div class="mut">Noch keine Beiträge.</div>';
 p.contributions.forEach(c=>{
  const flagged=c.status==='flagged'?badge('flagged'):'';
  h+='<div class="card"><b>['+esc(c.kind)+'] '+esc(c.title)+'</b>'+badge(c.trust_level)+flagged+
   '<div class="mut">von '+esc(c.contributor_name)+authorBadge(c)+' · '+(c.created_at||'').slice(0,10)+'</div>'+
   '<div>'+esc(c.body)+'</div>'+
   (c.link?('<div class="mut">Daten/Quelle: <a target="_blank" href="'+esc(c.link)+'">'+esc(c.link)+'</a></div>'):'')+
   (c.evidence_doi?('<div class="mut">DOI: '+esc(c.evidence_doi)+'</div>'):'')+
   '<button onclick="reportC(\\''+c.id+'\\')" style="background:none;border:1px solid #43324a;color:#ff9b9b;font-size:12px;margin-top:6px">melden</button></div>';
 });
 // Beitrag-Formular
 h+='<details><summary>＋ Beitrag hinzufügen (mitforschen)</summary><div class="card">'+
  '<select id="c_kind"><option value="finding">Ergebnis</option><option value="progress">Zwischenstand</option>'+
  '<option value="dataset">Datensatz</option><option value="question">offene Frage</option></select>'+
  '<input id="c_title" placeholder="Titel des Beitrags">'+
  '<textarea id="c_body" placeholder="Beschreibung / Ergebnis / Methode …"></textarea>'+
  '<input id="c_link" placeholder="Link zu Daten/Preprint (Zenodo/OSF/arXiv …) – optional">'+
  '<input id="c_doi" placeholder="DOI (falls publiziert) – wird geprüft → Stufe geprüft">'+
  '<button onclick="addContrib(\\''+id+'\\')">Beitrag absenden</button>'+
  '<div class="mut">Wird unter deinem Profil veröffentlicht (<a href="/konto">Konto</a> nötig). '+
  'Stufen: geprüft (DOI) · preprint (Link) · community (unbestätigt).</div>'+
  '<div id="c_msg" class="mut"></div></div></details></div>';
 $('detail').innerHTML=h;
 window.scrollTo(0,$('detail').offsetTop);
}
async function addContrib(id){
 const body={kind:$('c_kind').value,title:$('c_title').value,body:$('c_body').value,
   link:$('c_link').value,evidence_doi:$('c_doi').value};
 const d=await (await fetch('/api/projects/contribute?id='+encodeURIComponent(id),
   {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();
 $('c_msg').innerHTML=(d.ok?'<span class="ok">'+esc(d.message)+'</span>':
   '<span class="err">'+esc(d.message)+' <a href="/konto">→ anmelden</a></span>');
 if(d.ok)openProject(id);
}
async function reportC(cid){
 const reason=prompt('Warum meldest du diesen Beitrag?')||''; if(reason===null)return;
 await fetch('/api/contributions/report?id='+encodeURIComponent(cid),
  {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reason})});
 alert('Danke – der Beitrag wurde zur Prüfung markiert.');
}
loadList();
</script>
<p class="mut" style="text-align:center;margin-top:26px">
 <a href="/impressum">Impressum</a> · <a href="/datenschutz">Datenschutz</a> ·
 <a href="/nutzungsbedingungen">Nutzungsbedingungen</a></p>
</div></body></html>"""


_ACCOUNT_PAGE = """<!doctype html><html lang="de"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Synapse — Konto</title>
<style>
 :root{--bg:#f5f7fb;--surface:#fff;--fg:#1f2a37;--mut:#64748b;--border:#e2e8f0;
   --acc:#1d4ed8;--accsoft:#eef3ff}
 *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--fg);
   font:16px/1.6 ui-sans-serif,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
 a{color:var(--acc);text-decoration:none}
 .topbar{background:var(--surface);border-bottom:1px solid var(--border)}
 .topin{max-width:560px;margin:0 auto;padding:13px 18px;display:flex;justify-content:space-between;align-items:center}
 .brand{font-size:20px;font-weight:700} .brand span{color:var(--acc)}
 .nav a{margin-left:18px;font-size:14px;color:var(--mut)} .nav a:hover{color:var(--fg)}
 .wrap{max-width:560px;margin:0 auto;padding:22px 18px}
 h1{font-size:21px} h2{font-size:16px;margin:18px 0 8px}
 input,textarea,select{width:100%;padding:11px 13px;border-radius:10px;border:1px solid var(--border);
   background:var(--surface);color:var(--fg);font-size:15px;margin:6px 0}
 input:focus,textarea:focus,select:focus{outline:none;border-color:var(--acc);box-shadow:0 0 0 3px var(--accsoft)}
 button{padding:11px 16px;border:0;border-radius:10px;background:var(--acc);color:#fff;
   font-weight:600;cursor:pointer} button:hover{filter:brightness(1.06)}
 .card{border:1px solid var(--border);border-radius:12px;background:var(--surface);padding:16px 18px;margin:12px 0;
   box-shadow:0 1px 2px rgba(16,24,40,.04)}
 .mut{color:var(--mut);font-size:13px} .ok{color:#1f7a4d} .err{color:#b42323}
 .lbl{font-size:12px;color:var(--mut);font-weight:600;margin-top:8px}
 .note{background:var(--accsoft);color:#1e40af;font-size:12.5px;border-radius:9px;padding:9px 12px;margin:8px 0}
 .badge{display:inline-block;background:#e7f6ee;color:#1f7a4d;font-size:11px;padding:2px 9px;border-radius:7px;font-weight:600}
 .badge.student{background:#eef3ff;color:#1e40af} .badge.other{background:#eef1f5;color:#5b6776}
</style></head><body>
<div class="topbar"><div class="topin"><div class="brand">Syn<span>apse</span></div>
 <div class="nav"><a href="/">Suche</a><a href="/projekte">Projekte</a><a href="/konto">Konto</a></div></div></div>
<div class="wrap"><h1>Konto</h1>
<p class="mut">Mit einem offiziellen Profil sind deine Beiträge nachvollziehbar.
Eine <b>ORCID</b> macht dich als Forscher:in verifizierbar.</p>
<div id="view"></div></div>
<script>
const $=id=>document.getElementById(id);
function esc(s){const d=document.createElement('div');d.textContent=(s==null?'':s);return d.innerHTML;}
// Ehrliches Identitäts-Abzeichen: ORCID schlägt alles, sonst akadem. Status.
function idBadge(m){
 if(m.orcid_verified)return ' <span class="badge">ORCID ✓ verifiziert</span>';
 if(m.account_type==='student')return ' <span class="badge student">Student:in'+
   (m.affiliation?(' · '+esc(m.affiliation)):'')+'</span>';
 if(m.account_type==='researcher')return ' <span class="badge other">Forscher:in'+
   (m.affiliation?(' · '+esc(m.affiliation)):'')+'</span>';
 return '';
}
function typeSel(id,cur){
 const o=(v,t)=>'<option value="'+v+'"'+(cur===v?' selected':'')+'>'+t+'</option>';
 return '<div class="lbl">Konto-Typ (ehrlich gekennzeichnet)</div><select id="'+id+'">'+
  o('student','Student:in (Uni-Projekt, ohne ORCID)')+
  o('researcher','Forscher:in')+o('other','Andere')+'</select>';
}
const ORCID_NOTE='<div class="note">Kein ORCID? Kein Problem – Studierende können ohne '+
 'mitforschen. Beiträge werden dann als „Student:in" gekennzeichnet (ehrlich, nicht '+
 'zweitklassig). Eine <a href="https://orcid.org" target="_blank">ORCID ist kostenlos</a> '+
 'und macht dich zusätzlich verifizierbar.</div>';
async function load(){
 const m=(await (await fetch('/api/me')).json()).user;
 if(m){ $('view').innerHTML=
  '<div class="card"><h2>Angemeldet als '+esc(m.username)+'</h2>'+
  '<div class="mut">'+esc(m.name)+idBadge(m)+'</div>'+
  '<h2>Profil bearbeiten</h2>'+
  '<input id="p_name" placeholder="Anzeigename" value="'+esc(m.name)+'">'+
  typeSel('p_type',m.account_type||'other')+
  '<input id="p_aff" placeholder="Institution/Universität" value="'+esc(m.affiliation||'')+'">'+
  '<input id="p_orcid" placeholder="ORCID (0000-0000-0000-0000)" value="'+esc(m.orcid||'')+'">'+
  ORCID_NOTE+
  '<textarea id="p_bio" placeholder="Kurzprofil">'+esc(m.bio||'')+'</textarea>'+
  '<button onclick="saveProfile()">Speichern</button> '+
  '<button onclick="logout()" style="background:#64748b">Abmelden</button> '+
  '<button onclick="logoutAll()" style="background:#9a3636">Auf allen Geräten abmelden</button>'+
  '<div id="p_msg" class="mut"></div></div>'+
  '<div class="card"><h2>Passwort ändern</h2>'+
  '<input id="pw_old" type="password" placeholder="Aktuelles Passwort">'+
  '<input id="pw_new" type="password" placeholder="Neues Passwort (min. 10 Zeichen)">'+
  '<div class="mut">Nach dem Ändern werden alle anderen Geräte/Sitzungen abgemeldet.</div>'+
  '<button onclick="changePw()">Passwort ändern</button>'+
  '<div id="pw_msg" class="mut"></div></div>'; return; }
 $('view').innerHTML=
  '<div class="card"><h2>Anmelden</h2>'+
  '<input id="l_user" placeholder="Nutzername"><input id="l_pw" type="password" placeholder="Passwort">'+
  '<button onclick="login()">Anmelden</button><div id="l_msg" class="mut"></div></div>'+
  '<div class="card"><h2>Neues Konto</h2>'+
  '<input id="r_user" placeholder="Nutzername (3–32 Zeichen)"><input id="r_pw" type="password" placeholder="Passwort (min. 10 Zeichen)">'+
  '<input id="r_name" placeholder="Dein Name">'+
  typeSel('r_type','student')+
  '<input id="r_aff" placeholder="Institution/Universität (optional)">'+
  '<input id="r_orcid" placeholder="ORCID (optional, verifiziert dich)">'+
  ORCID_NOTE+
  '<button onclick="register()">Registrieren</button><div id="r_msg" class="mut"></div></div>';
}
async function post(url,body){return (await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();}
async function login(){const d=await post('/api/login',{username:$('l_user').value,password:$('l_pw').value});
 $('l_msg').innerHTML=(d.ok?'<span class="ok">':'<span class="err">')+esc(d.message)+'</span>'; if(d.ok)load();}
async function register(){const d=await post('/api/register',{username:$('r_user').value,password:$('r_pw').value,
  name:$('r_name').value,orcid:$('r_orcid').value,affiliation:$('r_aff').value,account_type:$('r_type').value});
 $('r_msg').innerHTML=(d.ok?'<span class="ok">':'<span class="err">')+esc(d.message)+'</span>'; if(d.ok)load();}
async function saveProfile(){const d=await post('/api/profile',{name:$('p_name').value,affiliation:$('p_aff').value,
  orcid:$('p_orcid').value,bio:$('p_bio').value,account_type:$('p_type').value});
 $('p_msg').innerHTML=(d.ok?'<span class="ok">':'<span class="err">')+esc(d.message)+'</span>'; if(d.ok)load();}
async function changePw(){const d=await post('/api/password',{old_password:$('pw_old').value,new_password:$('pw_new').value});
 $('pw_msg').innerHTML=(d.ok?'<span class="ok">':'<span class="err">')+esc(d.message)+'</span>';
 if(d.ok){$('pw_old').value='';$('pw_new').value='';}}
async function logout(){await post('/api/logout',{}); load();}
async function logoutAll(){if(!confirm('Wirklich auf allen Geräten abmelden?'))return;
 await post('/api/logout-all',{}); load();}
load();
</script>
<div class="wrap" style="padding-top:0"><p class="mut" style="text-align:center">
 <a href="/impressum">Impressum</a> · <a href="/datenschutz">Datenschutz</a> ·
 <a href="/nutzungsbedingungen">Nutzungsbedingungen</a></p></div>
</body></html>"""


# --------------------------------------------------------------------------- #
# Rechtliche Pflichtseiten (DE/DSGVO). Platzhalter in [[…]] vor Launch füllen.
def _legal_page(title: str, body_html: str) -> str:
    return f"""<!doctype html><html lang="de"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Synapse — {title}</title>
<style>
 :root{{--bg:#f5f7fb;--surface:#fff;--fg:#1f2a37;--mut:#64748b;--border:#e2e8f0;--acc:#1d4ed8}}
 *{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--fg);
   font:16px/1.65 ui-sans-serif,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}}
 a{{color:var(--acc)}}
 .topbar{{background:var(--surface);border-bottom:1px solid var(--border)}}
 .topin{{max-width:760px;margin:0 auto;padding:13px 18px;display:flex;justify-content:space-between;align-items:center}}
 .brand{{font-size:20px;font-weight:700}} .brand span{{color:var(--acc)}}
 .nav a{{margin-left:18px;font-size:14px;color:var(--mut);text-decoration:none}}
 .wrap{{max-width:760px;margin:0 auto;padding:24px 18px}}
 h1{{font-size:23px}} h2{{font-size:17px;margin-top:26px}} .mut{{color:var(--mut)}}
 .ph{{background:#fff7ed;border:1px solid #fed7aa;border-radius:8px;padding:2px 6px}}
</style></head><body>
<div class="topbar"><div class="topin"><div class="brand">Syn<span>apse</span></div>
 <div class="nav"><a href="/">Suche</a><a href="/projekte">Projekte</a><a href="/konto">Konto</a></div></div></div>
<div class="wrap">{body_html}
<p class="mut" style="margin-top:30px"><a href="/">← zurück zur Suche</a></p></div>
</body></html>"""


_IMPRESSUM = _legal_page("Impressum", """
<h1>Impressum</h1>
<p>Angaben gemäß § 5 DDG (ehemals § 5 TMG):</p>
<p><span class="ph">[[Vorname Nachname / Firma]]</span><br>
<span class="ph">[[Straße Nr.]]</span><br>
<span class="ph">[[PLZ Ort]]</span><br>
Deutschland</p>
<h2>Kontakt</h2>
<p>E-Mail: <span class="ph">[[kontakt@deine-domain.de]]</span></p>
<h2>Verantwortlich für den Inhalt (§ 18 Abs. 2 MStV)</h2>
<p><span class="ph">[[Name, Anschrift wie oben]]</span></p>
<p class="mut">Hinweis: Diese Vorlage ersetzt keine Rechtsberatung. Bitte vor dem
Online-Gang von einer fachkundigen Person prüfen lassen.</p>
""")


_DATENSCHUTZ = _legal_page("Datenschutz", """
<h1>Datenschutzerklärung</h1>
<p>Wir nehmen den Schutz deiner Daten ernst. Verarbeitung nur, soweit nötig
(Datenminimierung, Art. 5 DSGVO).</p>
<h2>Verantwortlicher</h2>
<p><span class="ph">[[Name, Anschrift, E-Mail – siehe Impressum]]</span></p>
<h2>Welche Daten wir verarbeiten</h2>
<ul>
<li><b>Konto:</b> Nutzername, (optional) Name/E-Mail/Affiliation/ORCID, Passwort
   (nur als scrypt-Hash – nie im Klartext).</li>
<li><b>Sitzungen:</b> ein technisch notwendiges Cookie (<code>sid</code>,
   HttpOnly); in der Datenbank liegt nur dessen Hash.</li>
<li><b>Sicherheit:</b> Login-Fehlversuche inkl. IP-Adresse zur Abwehr von
   Brute-Force-Angriffen (berechtigtes Interesse, Art. 6 Abs. 1 f DSGVO),
   automatische Löschung nach kurzer Zeit.</li>
<li><b>Nutzung:</b> Suchanfragen/Klicks zur Verbesserung des Rankings –
   ohne Personenbezug, sofern nicht angemeldet.</li>
</ul>
<h2>Keine Weitergabe an Dritte</h2>
<p>Es werden keine personenbezogenen Daten an Werbe-/Tracking-Dienste übermittelt.
Es laufen keine Fremd-Skripte/CDNs. Bei ORCID-Verifikation wird die von dir
eingegebene ORCID einmalig an die öffentliche ORCID-API gesendet.</p>
<h2>Deine Rechte</h2>
<p>Auskunft, Berichtigung, Löschung, Einschränkung, Datenübertragbarkeit,
Widerspruch sowie Beschwerde bei einer Aufsichtsbehörde (Art. 15–21, 77 DSGVO).
Kontakt: <span class="ph">[[kontakt@deine-domain.de]]</span></p>
<p class="mut">Vorlage – bitte vor Launch fachkundig prüfen lassen.</p>
""")


_NUTZUNG = _legal_page("Nutzungsbedingungen", """
<h1>Nutzungsbedingungen</h1>
<h2>1. Was Synapse ist</h2>
<p>Synapse ist eine quellenbasierte Wissenschafts-Suche und eine Plattform für
offene Forschung. Es werden Metadaten/Abstracts und Verweise auf Originalquellen
angezeigt.</p>
<h2>2. Keine Beratung</h2>
<p>Inhalte sind reine Information mit Quellen – <b>keine medizinische, rechtliche
oder finanzielle Beratung</b>. Entscheidungen triffst du eigenverantwortlich.</p>
<h2>3. Beiträge der Community</h2>
<p>Hochgeladene Beiträge tragen eine sichtbare Vertrauens-Stufe (geprüft/preprint/
community). Du sicherst zu, nur Inhalte beizutragen, an denen du die nötigen Rechte
hast. Geprüfte Literatur und unbestätigte Beiträge bleiben klar getrennt.</p>
<h2>4. Pflichten der Nutzenden</h2>
<p>Kein Missbrauch, kein Spam, keine rechtswidrigen oder irreführenden Inhalte,
keine automatisierten Massenzugriffe ohne Absprache.</p>
<h2>5. Haftung</h2>
<p>Bereitstellung „wie besehen", ohne Gewähr für Vollständigkeit/Richtigkeit
externer Quellen. Haftung nur bei Vorsatz/grober Fahrlässigkeit im gesetzlichen
Rahmen.</p>
<p class="mut">Vorlage – bitte vor Launch fachkundig prüfen lassen.</p>
""")


def create_app(cfg: Config | None = None) -> FastAPI:
    cfg = cfg or load_config()
    app = FastAPI(title="Synapse", version="0.2")
    _state: dict = {"engine": None}

    # Sicherheits-Header auf jeder Antwort (Clickjacking-/MIME-/Referrer-Schutz).
    # CSP erlaubt nur eigene Quellen; Inline-Skripte/-Styles der Seiten sind
    # zugelassen (keine Fremd-CDNs), Framing ist komplett verboten.
    _CSP = ("default-src 'self'; img-src 'self' data:; "
            "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
            "form-action 'self'")

    @app.middleware("http")
    async def _security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        resp.headers["Content-Security-Policy"] = _CSP
        if cfg.https:
            resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return resp

    # Globales Rate-Limiting (je IP, gleitendes 60-s-Fenster) + Größenlimit.
    # Schützt schreibende Endpunkte vor Massen-/Spam-Zugriffen; In-Memory reicht
    # für einen Prozess (uvicorn), kein externer Dienst nötig.
    _WRITE_PER_MIN = 90
    _MAX_BODY = 256 * 1024            # 256 KB pro Anfrage
    _hits: dict[str, list[float]] = {}

    @app.middleware("http")
    async def _rate_limit(request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            clen = request.headers.get("content-length")
            if clen and clen.isdigit() and int(clen) > _MAX_BODY:
                return JSONResponse({"ok": False, "message": "Anfrage zu groß."},
                                    status_code=413)
            import time
            ip = request.client.host if request.client else "?"
            now = time.monotonic()
            recent = [t for t in _hits.get(ip, []) if now - t < 60.0]
            if len(recent) >= _WRITE_PER_MIN:
                return JSONResponse({"ok": False, "message": "Zu viele Anfragen – "
                                     "bitte kurz warten."}, status_code=429)
            recent.append(now)
            _hits[ip] = recent
            if len(_hits) > 5000:                       # Speicher begrenzen
                _hits.clear()
        return await call_next(request)

    def _set_session(response: Response, token: str) -> None:
        # HttpOnly (kein JS-Zugriff), SameSite=Lax (CSRF-Schutz), Secure bei HTTPS.
        response.set_cookie(_COOKIE, token, httponly=True, samesite="lax",
                            secure=cfg.https, max_age=_COOKIE_MAXAGE, path="/")

    def _client_ip(request: Request) -> str:
        return request.client.host if request.client else ""

    def _engine():
        if _state["engine"] is None:
            from synapse.index import SearchEngine
            _state["engine"] = SearchEngine(cfg)
        return _state["engine"]

    def _user(request: Request):
        from synapse import accounts
        return accounts.session_user(cfg, request.cookies.get(_COOKIE, ""))

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/status")
    def status():
        # Leichtgewichtiger Betriebs-Status für Monitoring/Watchdog.
        try:
            from pathlib import Path
            with SynapseStore(cfg) as store:
                works = store.count_works()
            index_ready = (Path(cfg.data_dir) / "index" / "index.json").exists()
            return {"status": "ok", "works": works, "https": cfg.https,
                    "index": bool(index_ready)}
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"status": "error", "detail": str(exc)[:200]},
                                status_code=500)

    @app.get("/", response_class=HTMLResponse)
    def home():
        return _PAGE

    @app.get("/impressum", response_class=HTMLResponse)
    def impressum():
        return _IMPRESSUM

    @app.get("/datenschutz", response_class=HTMLResponse)
    def datenschutz():
        return _DATENSCHUTZ

    @app.get("/nutzungsbedingungen", response_class=HTMLResponse)
    def nutzungsbedingungen():
        return _NUTZUNG

    @app.get("/api/ask")
    def ask(q: str):
        if not q.strip():
            return {"results": []}
        from synapse import assistant
        try:
            b = assistant.analyze(cfg, q)
        except FileNotFoundError:
            return JSONResponse({"error": "Kein Index gefunden. Bitte erst "
                                 "'ingest' + 'index' ausführen."}, status_code=503)
        with SynapseStore(cfg) as store:
            store.log_event("search", query=q)
        return b.__dict__

    @app.get("/api/search")
    def search(q: str, k: int = 10):
        if not q.strip():
            return {"results": []}
        try:
            hits = _engine().search(q, k=min(max(k, 1), 50))
        except FileNotFoundError:
            return JSONResponse({"error": "Kein Index."}, status_code=503)
        with SynapseStore(cfg) as store:
            store.log_event("search", query=q)
        return {"query": q, "results": [h.__dict__ for h in hits]}

    @app.post("/api/submit")
    def submit(doi: str):
        from synapse.ingest import submit_doi
        res = submit_doi(cfg, doi)
        if res.ok:
            _state["engine"] = None        # Index neu laden (neuer Eintrag)
        return {"ok": res.ok, "message": res.message, "title": res.title, "id": res.id}

    @app.post("/api/feedback")
    def feedback(q: str, work_id: str, rank: int = 0):
        with SynapseStore(cfg) as store:
            store.log_event("click", query=q, work_id=work_id, rank=rank)
        return {"ok": True}

    @app.get("/api/related")
    def related(id: str, k: int = 8):
        try:
            res = _engine().connections(id, k=min(max(k, 1), 20))
        except FileNotFoundError:
            return JSONResponse({"error": "Kein Index."}, status_code=503)
        if res is None:
            return {"field": "", "related": []}
        seed_field, conns = res
        return {"field": seed_field, "related": [c.__dict__ for c in conns]}

    # --- Kollaborative Forschung: Projekte & Beiträge --------------------- #
    @app.get("/projekte", response_class=HTMLResponse)
    def projekte():
        return _PROJECTS_PAGE

    @app.get("/api/projects")
    def projects_list(q: str = ""):
        from synapse import projects
        return {"projects": projects.list_projects(cfg, q=q)}

    @app.post("/api/projects")
    def projects_create(p: ProjectIn, request: Request):
        u = _user(request)
        if not u:
            return JSONResponse({"ok": False, "message": "Bitte zuerst anmelden, "
                                 "um ein Projekt anzulegen."}, status_code=401)
        from synapse import projects
        r = projects.create_project(cfg, p.title, p.area, p.description,
                                    owner_name=u["name"], owner_orcid=u.get("orcid", ""),
                                    owner_user_id=u["id"], ptype=p.ptype)
        return {"ok": r.ok, "message": r.message, "data": r.data}

    @app.get("/api/projects/get")
    def projects_get(id: str):
        from synapse import projects
        d = projects.get_project(cfg, id)
        return d or {"error": "nicht gefunden"}

    @app.post("/api/projects/contribute")
    def projects_contribute(id: str, c: ContribIn, request: Request):
        u = _user(request)
        if not u:
            return JSONResponse({"ok": False, "message": "Bitte zuerst anmelden, "
                                 "um beizutragen."}, status_code=401)
        from synapse import projects
        r = projects.add_contribution(cfg, id, c.kind, c.title, c.body, c.link,
                                      c.evidence_doi, contributor_name=u["name"],
                                      contributor_orcid=u.get("orcid", ""),
                                      contributor_user_id=u["id"])
        return {"ok": r.ok, "message": r.message, "data": r.data}

    @app.post("/api/contributions/report")
    def contributions_report(id: str, rep: ReportIn):
        from synapse import projects
        r = projects.report(cfg, id, rep.reason)
        return {"ok": r.ok, "message": r.message}

    @app.post("/api/projects/moderate")
    def projects_moderate(m: ModerateIn):
        from synapse import projects
        r = projects.moderate(cfg, m.project_id, m.owner_token, m.contribution_id, m.action)
        return {"ok": r.ok, "message": r.message}

    # --- Konten / offizielle Profile ------------------------------------- #
    @app.get("/konto", response_class=HTMLResponse)
    def konto():
        return _ACCOUNT_PAGE

    @app.get("/api/me")
    def me(request: Request):
        return {"user": _user(request)}

    @app.post("/api/register")
    def api_register(p: RegisterIn, response: Response):
        from synapse import accounts
        r = accounts.register(cfg, p.username, p.password, p.name, p.email,
                              p.orcid, p.affiliation, p.bio, p.account_type)
        if not r.ok:
            return JSONResponse({"ok": False, "message": r.message}, status_code=400)
        _set_session(response, accounts.create_session(cfg, r.data["user_id"]))
        return {"ok": True, "message": r.message}

    @app.post("/api/login")
    def api_login(p: LoginIn, request: Request, response: Response):
        from synapse import accounts
        # Brute-Force-Schutz: zählt Fehlversuche je Konto + IP, sperrt kurzzeitig.
        res = accounts.attempt_login(cfg, p.username, p.password, _client_ip(request))
        if not res.ok:
            return JSONResponse({"ok": False, "message": res.message}, status_code=401)
        _set_session(response, accounts.create_session(cfg, res.data["user_id"]))
        return {"ok": True, "message": res.message}

    @app.post("/api/logout")
    def api_logout(request: Request, response: Response):
        from synapse import accounts
        accounts.destroy_session(cfg, request.cookies.get(_COOKIE, ""))
        response.delete_cookie(_COOKIE, path="/")
        return {"ok": True}

    @app.post("/api/logout-all")
    def api_logout_all(request: Request, response: Response):
        u = _user(request)
        if not u:
            return JSONResponse({"ok": False, "message": "Bitte anmelden."}, status_code=401)
        from synapse import accounts
        accounts.destroy_user_sessions(cfg, u["id"])      # auch die aktuelle
        response.delete_cookie(_COOKIE, path="/")
        return {"ok": True, "message": "Auf allen Geräten abgemeldet."}

    @app.post("/api/profile")
    def api_profile(p: ProfileIn, request: Request):
        u = _user(request)
        if not u:
            return JSONResponse({"ok": False, "message": "Bitte anmelden."}, status_code=401)
        from synapse import accounts
        r = accounts.update_profile(cfg, u["id"], p.name, p.affiliation, p.orcid,
                                    p.bio, p.account_type)
        return {"ok": r.ok, "message": r.message}

    @app.post("/api/password")
    def api_password(p: PasswordIn, request: Request):
        u = _user(request)
        if not u:
            return JSONResponse({"ok": False, "message": "Bitte anmelden."}, status_code=401)
        from synapse import accounts
        # Aktuelle Sitzung behalten, alle anderen werden abgemeldet.
        r = accounts.change_password(cfg, u["id"], p.old_password, p.new_password,
                                     keep_token=request.cookies.get(_COOKIE, ""))
        code = 200 if r.ok else 400
        return JSONResponse({"ok": r.ok, "message": r.message}, status_code=code)

    return app
