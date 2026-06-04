# Synapse — Wissenschafts-Entdeckungsmaschine
### Vollständiges Projekt- & Architekturdokument (Arbeitsstand 1.0)

> **Arbeitstitel:** „Synapse" (Gehirn + Verbindungen zwischen Wissensfeldern).
> **Ziel:** Eine selbst lernende Maschine, die das frei verfügbare Weltwissen der
> Forschung durchsuchbar macht, **Verbindungen zwischen Feldern findet** und
> **mit Quellen belegte** Antworten liefert — maximaler Impact (beschleunigt
> Medizin, Klima, Technik), läuft ehrlich auf dem vorhandenen Server, wächst zu
> einem profitablen, kompound­ierenden Wissens-Asset.
>
> **Dieses Dokument deckt bewusst jede Eventualität ab** (Technik, Daten, Recht,
> Sicherheit, Geld, Betrieb). Es ist die gemeinsame Grundlage — Änderungen werden
> hier versioniert.

---

## 0. Leitprinzipien („sicherer als sicher")

1. **Niemals erfinden.** Jede Aussage der Maschine ist mit einer realen Quelle
   (DOI/Link) belegt. Keine Quelle → keine Behauptung. Halluzination ist der
   Tod des Vertrauens.
2. **Keine Beratung, nur Information + Quellen.** Kein medizinischer/rechtlicher
   Rat. Klarer Disclaimer überall.
3. **Sicherheit & Datenschutz by Design** (DSGVO, gehärteter Server, Backups,
   Least-Privilege).
4. **Ehrliche Grenzen.** Wir versprechen nichts, was der Server nicht kann.
   Skalierung ist eingeplant, nicht erträumt.
5. **Klein & robust starten, messbar wachsen.** Jede Phase hat Abnahmekriterien.

---

## 1. Vision, Scope & Nicht-Ziele

### Was es IST
- Eine **semantische Such- & Entdeckungs-Maschine** über offene Forschungsdaten.
- Findet **ähnliche Arbeiten, Stand der Forschung, und Verbindungen zwischen
  Feldern**, die ein Mensch übersieht.
- Liefert **belegte Zusammenfassungen** (lokales kleines Modell, gecacht).
- Ein **lernendes „Gehirn"**: Relevanz/Ranking verbessert sich aus Feedback.

### Was es (bewusst) NICHT ist
- Kein ChatGPT-Konkurrent, kein Echtzeit-Chat für Tausende parallel.
- Keine eigene große KI / kein Modelltraining von Null.
- Keine medizinische/rechtliche Beratung.
- Keine Bild/Video-Generierung.

---

## 2. Zielgruppen & Wert

| Gruppe | Nutzen | Zahlungsbereitschaft |
|---|---|---|
| Forscher:innen / Doktorand:innen | Literaturüberblick, Verbindungen, Zeitersparnis | mittel (Pro-Abo) |
| R&D in Firmen (Pharma, Energie, Tech) | Stand der Technik, Trends, Whitespace | **hoch** (Team/Enterprise) |
| Wissenschaftsjournalist:innen, Berater | schnelle, belegte Übersichten | mittel |
| Allgemeinheit / Studierende | kostenloser Zugang zu Wissen | gratis (Impact) |

**Geschäftsmodell:** Freemium (Bürger gratis) + Pro-Abo + Team/Enterprise + API.

---

## 3. Datenquellen (frei, lizenzkonform)

| Quelle | Inhalt | Größe | Zugang | Lizenz |
|---|---|---|---|---|
| **OpenAlex** | Metadaten aller Werke, Zitationen, Konzepte | ~250 Mio | Bulk-Snapshot + API | **CC0** (frei) |
| **Semantic Scholar (S2)** | Metadaten + **vorberechnete SPECTER2-Embeddings** | ~200 Mio | Datasets-API | offen, Attribution |
| **Crossref** | DOIs, Metadaten | ~150 Mio | API/Dump | offen |
| **arXiv** | Volltexte (Preprints) | ~2,4 Mio | OAI/S3 | je Paper, meist erlaubt |
| **PubMed/PMC OA** | Biomedizin-Abstracts/Volltext | ~37 Mio | FTP/API | OA-Subset frei |
| **Unpaywall** | Open-Access-Volltext-Links | — | API | frei |

**Strategie:** OpenAlex als Rückgrat (Metadaten/Zitationen, CC0) + **SPECTER2-
Embeddings vorberechnet übernehmen** (spart Wochen CPU). Volltext nur für OA.
**Jede Quelle wird mit Lizenz & Attribution dokumentiert** (Compliance-Register).

---

## 4. Systemarchitektur

```
 [Quellen: OpenAlex/S2/Crossref/arXiv/PubMed]
        │  (Batch-ETL, nachts/inkrementell)
        ▼
 [Ingestion & Normalisierung] → [Daten-Lake: Parquet auf Disk]
        │                              │
        ▼                              ▼
 [Metadaten-DB: DuckDB/Postgres]  [Vektor-Index: Qdrant, quantisiert, on-disk]
        │                              │
        └──────────────┬───────────────┘
                       ▼
     [Such-/Ranking-Engine: Hybrid (BM25 + Vektor) + Learning-to-Rank "Gehirn"]
                       │
        ┌──────────────┼───────────────┐
        ▼              ▼                ▼
 [Verbindungs-     [Lokales LLM 3B:   [Zitations-/
  Entdeckung:       Zusammenfassung,   Faktenprüfung:
  Graph + Vektor]   gecacht, belegt]   "nur mit Quelle"]
                       │
                       ▼
        [API (FastAPI)] → [Web-Frontend] + [Telegram] + [Public API]
                       │
        [Betrieb: Scheduler, Monitoring, Backups, Security]
```

---

## 5. Komponenten im Detail

### 5.1 Ingestion / ETL
- Inkrementelle Updates über OpenAlex „updated_date"-Snapshots (täglich Delta).
- Idempotent (Wiederanlauf nach Absturz ohne Duplikate; Checkpoints).
- Dead-Letter-Queue für fehlerhafte Datensätze (kein stiller Datenverlust).
- Rate-Limits & Backoff je Quelle; Caching der Rohdaten (Wiederholbarkeit).

### 5.2 Speicher
- **Parquet-Lake** (Rohdaten, spaltenweise, komprimiert) auf Disk.
- **DuckDB** für analytische Abfragen/Joins (kein Server, RAM-schonend);
  später **Postgres** für transaktionale App-Daten (Konten, Feedback).
- **Qdrant** als Vektor-DB: **on-disk + Quantisierung (int8/PQ)**, HNSW-Index.

### 5.3 Embeddings
- **Primär: vorberechnete SPECTER2-Vektoren** (kein CPU-Embedding nötig).
- Für Quellen ohne Vektoren: lokales CPU-Embedding (bge-small/MiniLM), **nur im
  Batch nachts**, Durchsatz-budgetiert.

### 5.4 Such- & Ranking-Engine
- **Hybrid-Retrieval:** BM25 (Stichwort, exakt) + Vektor (semantisch) → fusion.
- **Learning-to-Rank (das „Gehirn"):** LightGBM-Ranker, lernt aus Klicks,
  Verweildauer, „hilfreich/nicht"-Feedback. Startet mit sinnvollen Default-
  Gewichten, wird mit Nutzung besser.
- **Re-Ranking** der Top-N für Präzision; Filter (Jahr, Feld, OA, Zitationen).

### 5.5 Verbindungs-Entdeckung (das Alleinstellungsmerkmal)
- Zitations-Graph (OpenAlex) + semantische Nähe → findet **Brücken zwischen
  Feldern** („Methode aus Feld A löst Problem in Feld B").
- Erkennt aufstrebende Themen (Zitations-Beschleunigung), Forschungslücken.

### 5.6 Lokale LLM-Schicht (sparsam, sicher)
- Kleines Modell (3B, quantisiert, via Ollama/llama.cpp) **nur** für: belegte
  Zusammenfassung der Top-Treffer.
- **Anti-Halluzination:** Modell darf **ausschließlich aus den gelieferten
  Quelltexten** zusammenfassen (RAG, strikt), jede Aussage → Quelle. Ohne Beleg
  → „nicht belegt".
- Ergebnisse **gecacht** (gleiche Frage = keine erneute Rechenlast).

### 5.7 API & Frontend
- **FastAPI** (REST), OpenAPI-Doku, Versionierung.
- Web-Frontend (schlank, schnell), später Telegram-Bot + Public API.
- Alles **stateless** wo möglich (Skalierung).

---

## 6. Das „Gehirn, das wir zusammen antrainieren"
- **Feedback-Loop:** jede Suche + Klick + Bewertung wird (datenschutzkonform,
  pseudonymisiert) gespeichert.
- **Wöchentliches Re-Training** des LTR-Rankers auf diesem Feedback.
- **Du als Co-Trainer:** ein internes Bewertungs-Interface, in dem wir
  Trefferqualität bewerten → fließt als starkes Lernsignal ein.
- **Ehrliche Messung:** Offline-Metriken (nDCG, MRR) + Live-Klickrate; jede
  Modellversion muss die alte messbar schlagen, sonst Rollback.

---

## 7. SICHERHEIT (sicherer als sicher)

### 7.1 Server-Härtung
- SSH nur per Key, Root-Login aus, Fail2ban, UFW-Firewall (nur 80/443/SSH).
- Automatische Sicherheits-Updates (unattended-upgrades).
- Dienste in **Docker** isoliert, Least-Privilege, keine Secrets im Image.
- Secrets in `.env`/Secret-Store, nie im Repo (Pre-Commit-Scan gegen Leaks).

### 7.2 Anwendungs-Sicherheit
- HTTPS (Let's Encrypt), HSTS, sichere Header.
- Input-Validierung, Rate-Limiting, Bot-/Missbrauchs-Schutz.
- Auth: gehashte Passwörter (argon2) oder OAuth; Sessions/JWT sauber.
- Dependency-Scanning (pip-audit), Lockfiles, regelmäßige Updates.

### 7.3 Wissenschaftliche Sicherheit (Korrektheit)
- **Quellenzwang** (keine Aussage ohne DOI/Link).
- Klare Trennung „Originaltext-Zitat" vs „Zusammenfassung".
- **Keine** Diagnose/Beratung; prominente Disclaimer.
- Prüfschicht: Stichproben-Audit der Zusammenfassungen gegen Quellen.

### 7.4 Datenintegrität & Betrieb
- **Backups:** tägliche DB-Backups + wöchentliches Voll-Snapshot, **off-site**,
  regelmäßig **Restore getestet** (ein ungetestetes Backup ist kein Backup).
- **Disaster Recovery:** dokumentierter Wiederherstellungsablauf, Ziel RTO < 24h.
- **Monitoring/Alerting:** Health-Checks, Ressourcen, Fehlerrate → Telegram-Alarm.
- **Graceful Degradation:** fällt das LLM aus → Suche funktioniert weiter; fällt
  Qdrant aus → BM25-Fallback.

---

## 8. Datenschutz & Recht (DSGVO, Deutschland)
- Datenminimierung; Nutzerdaten pseudonymisiert; AVV mit Hostern.
- Datenschutzerklärung, Impressum, Cookie/Consent.
- **Datenlizenzen** je Quelle eingehalten (CC0/OA), Attribution sichtbar.
- Keine Speicherung urheberrechtlich geschützter Volltexte ohne Erlaubnis
  (nur Metadaten/Abstracts + OA-Volltext + Links).
- Klare Nutzungsbedingungen + Haftungsausschluss.

---

## 9. Performance-Budget auf 4 Kernen / 8 GB / 240 GB

| Ressource | Budget | Engpass zuerst? | Maßnahme |
|---|---|---|---|
| RAM 8 GB | OS ~1 GB · Qdrant-Cache ~3 GB · App ~1,5 GB · LLM(3B) ~2,5 GB | **Ja** | LLM nur on-demand laden / oder weglassen, Qdrant mmap |
| CPU 4 Kerne | Suche ms-schnell; Batch nachts | bei LLM-Generierung | Generierung cachen/batchen, sparsam |
| Disk 240 GB | 10–30 Mio Werke (quantisiert) + Metadaten + Backups | bei Wachstum | Quantisierung, Subset wachsen lassen, Cleanup |
| Durchsatz | **Hunderttausende Suchen/Tag** machbar | Generierung limitiert Nutzerzahl | Suche gratis, Generierung im Pro-Tier |

**Kapazitäts-Start:** 5–10 Mio hochwertige Werke (zitationsstark + aktuell +
Fokusfelder Medizin/Energie/Tech). Wachstum messbar steuern.

---

## 10. Skalierungspfad (Zukunft)
1. **Heute (1 Server):** Suche + kleines LLM + Subset-Index.
2. **Wachstum:** Index-Subset vergrößern, Qdrant-Tuning, CDN fürs Frontend.
3. **Skalierung:** zweite Maschine (Worker/Index getrennt), Managed Postgres.
4. **GPU-Stufe:** separate GPU-Box nur für bessere Zusammenfassungen/Embeddings
   — **gleiche Architektur**, nur stärkerer „Denk"-Knoten.

---

## 11. Monetarisierung (kompound­ierend)
| Tier | Preis (Idee) | Inhalt |
|---|---|---|
| Free | 0 € | Suche, begrenzte Zusammenfassungen, Werbung/Attribution |
| Pro | 9–19 €/Monat | unbegrenzte Zusammenfassungen, Alerts, Export, Verbindungs-Karten |
| Team/Enterprise | ab 99 €/Monat | mehrere Sitze, private Sammlungen, Trend-Reports |
| API | nutzungsbasiert | Entwickler/Integrationen |

**Unit Economics:** Grenzkosten pro Suche ≈ 0 (eigener Server). Margen hoch,
sobald Reichweite da ist. Reichweite = Hauptarbeit (Content/SEO/Community).

---

## 12. KPIs je Phase
- Technik: Index-Größe, Such-Latenz (<300 ms), Uptime (>99 %).
- Qualität: nDCG/MRR offline, Klick-/„hilfreich"-Rate live, 0 unbelegte Aussagen.
- Geschäft: Nutzer, Wiederkehr, Free→Pro-Konversion, MRR.

---

## 13. Roadmap (Phasen mit Abnahmekriterien)

| Phase | Inhalt | Abnahme |
|---|---|---|
| **0 Fundament** (1–2 Wo) | Repo neu, Server-Härtung, Docker, Daten-Lake, OpenAlex-Subset laden, DuckDB | Daten liegen lokal, reproduzierbar, Server gehärtet |
| **1 Suche** (2–4 Wo) | SPECTER2-Vektoren laden, Qdrant-Index, Hybrid-Suche, API + Mini-Frontend | belegte semantische Suche live, <300 ms |
| **2 Gehirn** (Monat 2) | Feedback-Loop, LTR-Ranker, Co-Trainer-Interface, Eval | Ranking schlägt Baseline messbar (nDCG) |
| **3 Entdeckung** (Monat 3) | Verbindungs-Findung, Trends/Lücken, belegte Zusammenfassungen (LLM, RAG-streng) | „Brücken zwischen Feldern" + 0 Halluzination im Audit |
| **4 Produkt** (Monat 4+) | Konten, Tiers, Alerts, Public API, Härtung, Launch | zahlende Nutzer, stabiler Betrieb |

---

## 14. Risiko-Register (Eventualitäten)

| Risiko | Auswirkung | Wahrsch. | Gegenmaßnahme |
|---|---|---|---|
| Embedding aller Werke unmöglich | hoch | sicher | vorberechnete Vektoren + Subset (eingeplant) |
| RAM-Engpass (8 GB) | mittel | hoch | LLM optional/on-demand, Qdrant on-disk, Budget §9 |
| Halluzinationen | **kritisch** | mittel | Quellenzwang, strenges RAG, Audit, „nicht belegt" |
| Datenlizenz-Verstoß | hoch | gering | nur CC0/OA, Attribution, Compliance-Register |
| Server-Ausfall/Datenverlust | hoch | gering | Backups off-site + getestete Restores, DR-Plan |
| Sicherheitslücke/Angriff | hoch | mittel | Härtung §7, Updates, Scans, Rate-Limit, Monitoring |
| DSGVO-Verstoß | hoch | gering | Datenschutz §8, Datenminimierung, Doku |
| Keine Reichweite/Umsatz | hoch | mittel | früh Bürger-Gratis-Nutzen + SEO/Community, B2B-Vertrieb |
| Konkurrenz (Google Scholar, Consensus, Elicit) | mittel | hoch | Fokus: lokal/günstig + Verbindungs-Entdeckung + Nische |
| Quelle ändert API/Zugang | mittel | mittel | mehrere Quellen, Caching, lose Kopplung |
| Kosten laufen davon | mittel | gering | alles self-hosted, Grenzkosten ~0, Budget-Alarme |

---

## 15. Tech-Stack
Python 3.12 · Polars/DuckDB · Parquet · Qdrant · LightGBM/scikit-learn ·
FastAPI · Ollama/llama.cpp (3B) · Docker Compose · Nginx · Let's Encrypt ·
Prometheus/Grafana (light) oder einfache Health-Checks + Telegram-Alerts.

---

## 16. Offene Entscheidungen (brauche dein OK)
1. **Fokusfelder zuerst** (für das Start-Subset): Medizin · Energie/Klima ·
   Informatik/KI · Materialwissenschaft — welche 1–2?
2. **LLM-Zusammenfassung ab Phase 1 oder erst Phase 3?** (Phase 3 = sicherer
   starten, erst Suche perfektionieren.)
3. **Altes Aktien-KI-Projekt:** ins Archiv (`legacy/`-Branch) verschieben und
   Repo für Synapse frei machen? (Nichts wird gelöscht, nur archiviert.)
4. **Projektname:** „Synapse" ok, oder anderer Name?

---

*Dieses Dokument ist v1.0 und wird gemeinsam weiter geschärft. Nichts wird
gebaut, bevor die offenen Entscheidungen geklärt sind.*
