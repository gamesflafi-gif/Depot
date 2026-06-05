"""Web-Oberfläche & API für Synapse (Phase 1.5).

Schlanke FastAPI-App: eine Suchseite im Browser + JSON-API. Klicks auf Treffer
werden protokolliert – diese Nutzungs-Events sind die Datengrundlage für das
lernende Ranking-„Gehirn" (Phase 2). Keine Fremd-API, alles lokal.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from synapse.config import Config, load_config
from synapse.storage import SynapseStore

log = logging.getLogger(__name__)

_PAGE = """<!doctype html><html lang="de"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Synapse — Wissenschaft entdecken</title>
<style>
 :root{--bg:#0e1726;--card:#16203400;--fg:#e6edf3;--mut:#9fb3c8;--acc:#3ddc84}
 *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--fg);
   font:16px/1.5 -apple-system,Segoe UI,Roboto,sans-serif}
 header{padding:28px 18px 8px;text-align:center}
 h1{margin:0;font-size:26px} h1 span{color:var(--acc)}
 .sub{color:var(--mut);font-size:14px;margin-top:4px}
 .wrap{max-width:820px;margin:0 auto;padding:16px}
 form{display:flex;gap:8px;margin:14px 0}
 input{flex:1;padding:13px 15px;border-radius:12px;border:1px solid #2a3a52;
   background:#0b1422;color:var(--fg);font-size:16px}
 button{padding:13px 18px;border:0;border-radius:12px;background:var(--acc);
   color:#06281a;font-weight:700;font-size:16px;cursor:pointer}
 .hit{padding:14px 16px;border:1px solid #22314a;border-radius:14px;margin:10px 0;
   background:#111a2b;text-decoration:none;display:block;color:inherit}
 .hit:hover{border-color:var(--acc)}
 .t{font-weight:600} .m{color:var(--mut);font-size:13px;margin-top:4px}
 .sc{color:var(--acc);font-variant-numeric:tabular-nums}
 .foot{color:var(--mut);font-size:12px;text-align:center;margin:24px 0}
 .empty{color:var(--mut);text-align:center;margin:30px 0}
 .relbtn{margin-top:9px;font-size:12px;color:var(--acc);background:none;
   border:1px solid #2a3a52;border-radius:8px;padding:4px 10px;cursor:pointer}
 .rel{margin-top:10px;border-top:1px solid #22314a;padding-top:8px}
 .rel a{display:block;color:var(--mut);font-size:13px;padding:5px 0;text-decoration:none}
 .rel a:hover{color:var(--fg)}
 .badge{display:inline-block;background:#13402a;color:#7ef0ad;font-size:11px;
   padding:1px 7px;border-radius:6px;margin-left:6px}
</style></head><body>
<header><h1>Syn<span>apse</span></h1>
<div class="sub">Beschreibe eine Idee oder Frage — finde passende Forschung. Mit Quellen.</div></header>
<div class="wrap">
 <form id="f"><input id="q" placeholder="z.B. graph neural networks for drug discovery" autofocus>
 <button>Suchen</button></form>
 <div id="r"></div>
 <div class="foot">Lokal & quellenbasiert · keine Anlage-/Medizin-/Rechtsberatung</div>
</div>
<script>
const r=document.getElementById('r'), q=document.getElementById('q');
function esc(s){const d=document.createElement('div');d.textContent=s||'';return d.innerHTML;}
document.getElementById('f').addEventListener('submit', async e=>{
 e.preventDefault(); const query=q.value.trim(); if(!query)return;
 r.innerHTML='<div class="empty">Suche …</div>';
 let d;
 try{ d=await (await fetch('/api/search?q='+encodeURIComponent(query)+'&k=15')).json(); }
 catch(_){ r.innerHTML='<div class="empty">Fehler bei der Suche.</div>'; return; }
 if(d.error){ r.innerHTML='<div class="empty">'+esc(d.error)+'</div>'; return; }
 if(!d.results||!d.results.length){ r.innerHTML='<div class="empty">Keine Treffer.</div>'; return; }
 r.innerHTML='';
 d.results.forEach((h,i)=>{
  const url=h.doi?('https://doi.org/'+h.doi):('https://openalex.org/'+h.id);
  const meta=[h.year||'—',h.venue,(h.cited_by_count+' Zit.')].filter(Boolean).join(' · ');
  const card=document.createElement('div'); card.className='hit';
  const a=document.createElement('a'); a.target='_blank'; a.href=url;
  a.style.textDecoration='none'; a.style.color='inherit';
  a.innerHTML='<div class="t">'+(i+1)+'. '+esc(h.title)+'</div>'+
   '<div class="m">'+esc(meta)+' · <span class="sc">'+h.score.toFixed(3)+'</span></div>';
  a.addEventListener('click', ()=>{ fetch('/api/feedback?q='+encodeURIComponent(query)+
     '&work_id='+encodeURIComponent(h.id)+'&rank='+i, {method:'POST'}); });
  card.appendChild(a);
  const btn=document.createElement('button'); btn.className='relbtn';
  btn.textContent='↔ Verbindungen';
  const panel=document.createElement('div'); panel.className='rel'; panel.style.display='none';
  btn.addEventListener('click', async ()=>{
   if(panel.dataset.loaded){ panel.style.display=(panel.style.display==='none'?'block':'none'); return; }
   panel.style.display='block'; panel.innerHTML='<div class="m">lädt …</div>';
   let rd; try{ rd=await (await fetch('/api/related?id='+encodeURIComponent(h.id)+'&k=8')).json(); }
   catch(_){ panel.innerHTML='<div class="m">Fehler.</div>'; return; }
   panel.dataset.loaded='1';
   if(!rd.related||!rd.related.length){ panel.innerHTML='<div class="m">Keine Verbindungen.</div>'; return; }
   panel.innerHTML='<div class="m">Feld: '+esc(rd.field||'—')+' · verwandte Arbeiten:</div>';
   rd.related.forEach(c=>{
    const cu=c.doi?('https://doi.org/'+c.doi):('https://openalex.org/'+c.id);
    const link=document.createElement('a'); link.target='_blank'; link.href=cu;
    link.innerHTML=esc(c.title)+(c.cross_field?('<span class="badge">Brücke → '+esc(c.field)+'</span>'):'');
    panel.appendChild(link);
   });
  });
  card.appendChild(btn); card.appendChild(panel);
  r.appendChild(card);
 });
});
</script></body></html>"""


def create_app(cfg: Config | None = None) -> FastAPI:
    cfg = cfg or load_config()
    app = FastAPI(title="Synapse", version="0.1")
    _state: dict = {"engine": None}

    def _engine():
        if _state["engine"] is None:
            from synapse.index import SearchEngine
            _state["engine"] = SearchEngine(cfg)        # lädt Index in den Speicher
        return _state["engine"]

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def home():
        return _PAGE

    @app.get("/api/search")
    def search(q: str, k: int = 10):
        if not q.strip():
            return {"results": []}
        try:
            hits = _engine().search(q, k=min(max(k, 1), 50))
        except FileNotFoundError:
            return JSONResponse({"error": "Kein Index gefunden. Bitte erst "
                                 "'ingest' + 'index' ausführen."}, status_code=503)
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
