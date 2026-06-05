"""Web-Oberfläche & API für Synapse.

Forschungs-Assistent im Browser: Frage stellen -> faktenbasierte Einordnung
(gibt es das? was gibt es? aktiv/reif? Brücken?) + Trefferliste mit Quellen.
Klicks werden protokolliert (Grundlage fürs lernende Ranking). Alles lokal.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from synapse.config import Config, load_config
from synapse.storage import SynapseStore


class ProjectIn(BaseModel):
    title: str
    area: str = ""
    description: str = ""
    owner_name: str = ""
    owner_orcid: str = ""


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
</style></head><body>
<div class="topbar"><div class="topin">
 <div class="brand">Syn<span>apse</span></div>
 <div class="nav"><a href="/">Suche</a><a href="/projekte">Projekte</a></div>
</div></div>
<div class="wrap">
 <div class="lead">Stelle eine Forschungsfrage — Synapse ordnet die Studienlage ein und nennt die Quellen.</div>
 <form id="f"><input id="q" placeholder="z. B. Welche Forschung gibt es zu Schlaf und Gedächtnis?" autofocus>
 <button>Analysieren</button></form>
 <div id="brief"></div>
 <div id="r"></div>
 <details class="contrib"><summary>＋ Eigene Forschung beitragen</summary>
  <div class="cbox">Nur <b>offiziell registrierte</b> Arbeiten mit gültiger DOI
   (geprüft über OpenAlex/Crossref) – so kommt nichts Ungeprüftes hinein.
   <form id="cf"><input id="doi" placeholder="DOI, z.B. 10.1038/s41586-021-03819-2">
   <button>Prüfen & hinzufügen</button></form>
   <div id="cmsg" class="m"></div></div>
 </details>
 <div class="foot">Lokal & quellenbasiert · keine Anlage-/Medizin-/Rechtsberatung</div>
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

document.getElementById('f').addEventListener('submit',async e=>{
 e.preventDefault(); const query=q.value.trim(); if(!query)return;
 br.innerHTML='<div class="empty">Analysiere Forschungslage …</div>'; r.innerHTML='';
 let b; try{b=await(await fetch('/api/ask?q='+encodeURIComponent(query))).json();}
 catch(_){br.innerHTML='<div class="empty">Fehler.</div>';return;}
 renderBrief(b); renderResults(query,b.results);
});

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
 .pill{display:inline-block;background:var(--accsoft);color:#1e40af;font-size:12px;
   padding:3px 10px;border-radius:20px;font-weight:500}
 details summary{cursor:pointer;color:var(--acc);font-weight:500} .ok{color:#1f7a4d} .err{color:#b42323}
 .tokbox{background:#f0fdf4;border:1px solid #bbf7d0;border-radius:10px;padding:11px;margin:8px 0;word-break:break-all}
</style></head><body>
<div class="topbar"><div class="topin">
 <div class="brand">Syn<span>apse</span></div>
 <div class="nav"><a href="/">Suche</a><a href="/projekte">Projekte</a></div>
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
  <textarea id="p_desc" placeholder="Worum geht es? Ziel, Stand, was gesucht wird …"></textarea>
  <div class="row"><input id="p_owner" placeholder="Dein Name" style="flex:1">
   <input id="p_orcid" placeholder="ORCID (optional)" style="flex:1"></div>
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

async function createProject(){
 const body={title:$('p_title').value,area:$('p_area').value,description:$('p_desc').value,
   owner_name:$('p_owner').value,owner_orcid:$('p_orcid').value};
 const d=await (await fetch('/api/projects',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify(body)})).json();
 if(!d.ok){$('p_msg').innerHTML='<span class="err">'+esc(d.message)+'</span>';return;}
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
 let h='<div class="card"><h2>'+esc(p.title)+'</h2><span class="pill">'+esc(p.area||'—')+'</span>'+
  '<p class="mut">'+esc(p.description||'')+'</p><div class="mut">von '+esc(p.owner_name)+
  (p.owner_orcid?(' · ORCID '+esc(p.owner_orcid)):'')+' · Lizenz '+esc(p.license)+'</div>';
 h+='<h3>Beiträge</h3>';
 if(!p.contributions.length)h+='<div class="mut">Noch keine Beiträge.</div>';
 p.contributions.forEach(c=>{
  const flagged=c.status==='flagged'?badge('flagged'):'';
  h+='<div class="card"><b>['+esc(c.kind)+'] '+esc(c.title)+'</b>'+badge(c.trust_level)+flagged+
   '<div class="mut">von '+esc(c.contributor_name)+' · '+(c.created_at||'').slice(0,10)+'</div>'+
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
  '<div class="row"><input id="c_name" placeholder="Dein Name" style="flex:1">'+
  '<input id="c_orcid" placeholder="ORCID (optional)" style="flex:1"></div>'+
  '<button onclick="addContrib(\\''+id+'\\')">Beitrag absenden</button>'+
  '<div class="mut">Stufen: geprüft (DOI) · preprint (Link) · community (unbestätigt).</div>'+
  '<div id="c_msg" class="mut"></div></div></details></div>';
 $('detail').innerHTML=h;
 window.scrollTo(0,$('detail').offsetTop);
}
async function addContrib(id){
 const body={kind:$('c_kind').value,title:$('c_title').value,body:$('c_body').value,
   link:$('c_link').value,evidence_doi:$('c_doi').value,contributor_name:$('c_name').value,
   contributor_orcid:$('c_orcid').value};
 const d=await (await fetch('/api/projects/contribute?id='+encodeURIComponent(id),
   {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();
 $('c_msg').innerHTML=(d.ok?'<span class="ok">':'<span class="err">')+esc(d.message)+'</span>';
 if(d.ok)openProject(id);
}
async function reportC(cid){
 const reason=prompt('Warum meldest du diesen Beitrag?')||''; if(reason===null)return;
 await fetch('/api/contributions/report?id='+encodeURIComponent(cid),
  {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reason})});
 alert('Danke – der Beitrag wurde zur Prüfung markiert.');
}
loadList();
</script></div></body></html>"""


def create_app(cfg: Config | None = None) -> FastAPI:
    cfg = cfg or load_config()
    app = FastAPI(title="Synapse", version="0.2")
    _state: dict = {"engine": None}

    def _engine():
        if _state["engine"] is None:
            from synapse.index import SearchEngine
            _state["engine"] = SearchEngine(cfg)
        return _state["engine"]

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def home():
        return _PAGE

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
    def projects_create(p: ProjectIn):
        from synapse import projects
        r = projects.create_project(cfg, p.title, p.area, p.description,
                                    p.owner_name, p.owner_orcid)
        return {"ok": r.ok, "message": r.message, "data": r.data}

    @app.get("/api/projects/get")
    def projects_get(id: str):
        from synapse import projects
        d = projects.get_project(cfg, id)
        return d or {"error": "nicht gefunden"}

    @app.post("/api/projects/contribute")
    def projects_contribute(id: str, c: ContribIn):
        from synapse import projects
        r = projects.add_contribution(cfg, id, c.kind, c.title, c.body, c.link,
                                      c.evidence_doi, c.contributor_name, c.contributor_orcid)
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

    return app
