"""Web-Oberfläche & API für Synapse.

Forschungs-Assistent im Browser: Frage stellen -> faktenbasierte Einordnung
(gibt es das? was gibt es? aktiv/reif? Brücken?) + Trefferliste mit Quellen.
Klicks werden protokolliert (Grundlage fürs lernende Ranking). Alles lokal.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from synapse.config import Config, load_config
from synapse.storage import SynapseStore

log = logging.getLogger(__name__)

_PAGE = """<!doctype html><html lang="de"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Synapse — Forschungs-Assistent</title>
<style>
 :root{--bg:#0e1726;--fg:#e6edf3;--mut:#9fb3c8;--acc:#3ddc84}
 *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--fg);
   font:16px/1.5 -apple-system,Segoe UI,Roboto,sans-serif}
 header{padding:26px 18px 6px;text-align:center}
 h1{margin:0;font-size:26px} h1 span{color:var(--acc)}
 .sub{color:var(--mut);font-size:14px;margin-top:4px}
 .wrap{max-width:820px;margin:0 auto;padding:16px}
 form{display:flex;gap:8px;margin:14px 0}
 input{flex:1;padding:13px 15px;border-radius:12px;border:1px solid #2a3a52;
   background:#0b1422;color:var(--fg);font-size:16px}
 button{padding:13px 18px;border:0;border-radius:12px;background:var(--acc);
   color:#06281a;font-weight:700;font-size:16px;cursor:pointer}
 .brief{border:1px solid #244; border-left:4px solid var(--acc);border-radius:14px;
   background:#0f1e30;padding:16px 18px;margin:6px 0 16px}
 .verdict{font-size:17px;font-weight:600}
 .act{color:var(--mut);font-size:14px;margin-top:4px}
 .chips{margin:10px 0 2px} .chip{display:inline-block;background:#13283f;color:#cfe6ff;
   font-size:12px;padding:3px 9px;border-radius:20px;margin:3px 4px 3px 0}
 .blk{margin-top:10px} .blk b{font-size:13px;color:var(--mut)}
 .blk a{display:block;color:#cfe0f0;font-size:14px;text-decoration:none;padding:3px 0}
 .blk a:hover{color:#fff}
 .sech{color:var(--mut);font-size:13px;margin:18px 0 6px;text-transform:uppercase;letter-spacing:.05em}
 .hit{padding:14px 16px;border:1px solid #22314a;border-radius:14px;margin:10px 0;background:#111a2b}
 .hit:hover{border-color:var(--acc)}
 .t{font-weight:600} .m{color:var(--mut);font-size:13px;margin-top:4px}
 .sc{color:var(--acc);font-variant-numeric:tabular-nums}
 .relbtn{margin-top:9px;font-size:12px;color:var(--acc);background:none;
   border:1px solid #2a3a52;border-radius:8px;padding:4px 10px;cursor:pointer}
 .rel{margin-top:10px;border-top:1px solid #22314a;padding-top:8px}
 .rel a{display:block;color:var(--mut);font-size:13px;padding:5px 0;text-decoration:none}
 .rel a:hover{color:var(--fg)}
 .badge{display:inline-block;background:#13402a;color:#7ef0ad;font-size:11px;
   padding:1px 7px;border-radius:6px;margin-left:6px}
 .foot{color:var(--mut);font-size:12px;text-align:center;margin:24px 0}
 .empty{color:var(--mut);text-align:center;margin:30px 0}
</style></head><body>
<header><h1>Syn<span>apse</span></h1>
<div class="sub">Frag deine Forschung — bekomme direkt eine Einordnung mit Quellen.</div></header>
<div class="wrap">
 <form id="f"><input id="q" placeholder="z.B. Gibt es Forschung zu Schlaf und Gedächtnis?" autofocus>
 <button>Fragen</button></form>
 <div id="brief"></div>
 <div id="r"></div>
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
</script></body></html>"""


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

    return app
