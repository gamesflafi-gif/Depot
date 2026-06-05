# Synapse — Kollaborative Forschung (Design-Dokument)

> Nutzer legen **Forschungsbereiche/Projekte** an (z.B. „Schlafstörungen"),
> laden **Ergebnisse & Zwischenstände** hoch, andere können darauf **aufbauen
> oder mitforschen**. Vollständig durchdacht – inkl. guter wie schlechter
> Eventualitäten und ihrer Absicherung.

## 1. Leitprinzipien
1. **Klarheit über Vertrauen:** Jeder Beitrag trägt eine sichtbare **Vertrauens-
   Stufe**. Niemand verwechselt einen Zwischenstand mit gesicherter Wissenschaft.
2. **Trennung:** Geprüfte Literatur (DOI-Index) und **community-Beiträge** bleiben
   getrennt – Ungeprüftes verwässert die Suche nicht.
3. **Rückverfolgbarkeit:** Jeder Beitrag hat einen Urheber (Name, optional ORCID)
   und Zeitstempel. Nichts ist anonym-unkontrollierbar.
4. **Keine Beratung:** Forschungsdaten, keine medizinische/rechtliche Beratung –
   überall deutlich.
5. **Du behältst die Kontrolle:** Wer ein Projekt anlegt, kann es kuratieren
   (Beiträge entfernen, archivieren) – per geheimem Owner-Token.

## 2. Vertrauens-Stufen (das Herzstück gegen Müll/Falschinfo)
| Stufe | Bedeutung | Bedingung | Anzeige |
|---|---|---|---|
| **geprüft** | offiziell publiziert | gültige **DOI**, verifiziert bei OpenAlex/Crossref | grün |
| **preprint/daten** | extern hinterlegt | Link zu anerkanntem Repo (Zenodo/OSF/arXiv/Figshare/GitHub) | gelb |
| **community** | reine Eigenangabe | kein externer Beleg | grau, „unbestätigt" |

So darf jeder **Zwischenstände** teilen – aber **ehrlich etikettiert**.

## 3. Datenmodell
- **projects:** id, title, area, description, owner_name, owner_orcid,
  owner_token(gehasht), license, status(active/archived), created_at.
- **contributions:** id, project_id, kind(finding/dataset/progress/question),
  title, body, link(extern), evidence_doi, contributor_name, contributor_orcid,
  trust_level, status(visible/flagged/removed), created_at.
- **reports:** id, target_id, reason, created_at.

## 4. Speicher-Disziplin (8-GB-Server)
- **Keine großen Dateien hosten.** Daten werden **verlinkt** (Zenodo/OSF/…),
  nicht hochgeladen. Synapse speichert nur Metadaten + Text + Links.
- DuckDB trägt zehntausende Projekte/Beiträge mühelos.

## 5. Eventualitäten — gut & schlecht — und ihre Absicherung
| Eventualität | Risiko | Absicherung |
|---|---|---|
| Spam/Müll-Uploads | hoch | Pflicht-Urheber, Rate-Limit, **Melden→Flag→Entfernen**, Stufen-Label |
| Falschinfo (v.a. Medizin) | **kritisch** | „unbestätigt"-Label, **nie** in geprüfte Suche, Disclaimer, Melde-/Entfernfunktion, Sensibel-Themen-Hinweis |
| Plagiat / IP-Diebstahl | mittel | Urheber bestätigt Rechte + wählt **Lizenz**; Takedown auf Meldung |
| Vorgetäuschte Seriosität | mittel | Stufen + optional **ORCID**; höhere Stufe nur mit Beleg/DOI |
| DSGVO / Personendaten | hoch | Datenminimierung, Einwilligung, **Löschung per Owner-Token**, kein Scraping |
| Belästigung/Missbrauch | mittel | Melden + Moderation (Entfernen), später Sperren |
| Datenverlust | hoch | Backups + Versionierung (append-only Beiträge) |
| Vandalismus/Edit-Wars | mittel | Beiträge **append-only**; Owner kuratiert; keine Überschreibung |
| Verwaiste Projekte | gering | Status archiviert; andere können **forken/fortführen** |
| Suche „verschmutzt" | mittel | Community-Beiträge **getrennt** von der geprüften Literatur |
| Haftung | hoch | Disclaimer, Nutzungsbedingungen, Takedown-Prozess |
| Skalierung | gering | DuckDB + Paginierung; Grenzkosten ~0 |
| Identitätsdiebstahl | mittel | Name selbst angegeben + klar etikettiert; ORCID-Verifikation später |

## 6. Abläufe
- **Projekt anlegen:** Titel + Bereich + Beschreibung → erhält geheimen
  **Owner-Token** (zum Kuratieren). Lizenz wählbar (Standard CC-BY 4.0).
- **Beitrag hinzufügen:** Art (Ergebnis/Datensatz/Zwischenstand/Frage), Titel,
  Text, optional Link + DOI + Name/ORCID → automatische Vertrauens-Stufe.
- **Entdecken:** Projekte durchsuchen/auflisten; offene Forschung sichtbar.
- **Mitforschen:** jeder kann Beiträge ergänzen (etikettiert); Owner kuratiert.
- **Melden:** ein Klick → Flag → Owner/Moderation prüft → ggf. entfernt.

## 7. Was v1 ist / später kommt
- **v1 (jetzt):** Projekte, Beiträge, Vertrauens-Stufen, DOI-Verifikation,
  Owner-Token-Kuratierung, Melden/Flag/Entfernen, Web + API + CLI, Disclaimer.
- **später:** echte Nutzerkonten + ORCID-Login, Benachrichtigungen, Versions-
  Historie pro Beitrag, Endorsements, feinere Moderation/Sperren.

*Dieses Dokument wird gemeinsam weiter geschärft.*
