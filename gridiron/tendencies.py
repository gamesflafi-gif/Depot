"""Tendenz-Analyse / Scouting-Report (der verkaufbare Kern).

Berechnet aus dem Play-by-Play, *was ein Team in welcher Situation tut* –
transparent per Aggregation (Coaches vertrauen Zählungen mehr als Black Boxes),
inklusive Abweichung vom Liga-Schnitt und der „Tells" (Situationen, in denen
das Team sehr vorhersehbar ist). Rechnet direkt in DuckDB (schnell, RAM-arm).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from gridiron.config import Config
from gridiron.features import DIST_CASE, ZONE_CASE
from gridiron.storage import GridironStore

_PASS = "AVG(CASE WHEN is_pass THEN 1.0 ELSE 0.0 END)"
_SUCC = "AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END)"


@dataclass
class ScoutReport:
    team: str
    season: str = "alle"
    n_plays: int = 0
    pass_rate: float = 0.0
    epa: float = 0.0
    success_rate: float = 0.0
    league_pass_rate: float = 0.0
    by_down_dist: list = field(default_factory=list)
    by_zone: list = field(default_factory=list)
    run_gaps: list = field(default_factory=list)
    pass_locations: list = field(default_factory=list)
    play_action_rate: float = 0.0
    tells: list = field(default_factory=list)


def _where(team: str | None, season: int | None) -> tuple[str, list]:
    conds, params = [], []
    if team:
        conds.append("posteam=?")
        params.append(team)
    if season:
        conds.append("season=?")
        params.append(season)
    return (("WHERE " + " AND ".join(conds)) if conds else ""), params


def scout(cfg: Config, team: str, season: int | None = None,
          min_n: int = 8) -> ScoutReport:
    rep = ScoutReport(team=team, season=str(season) if season else "alle")
    with GridironStore(cfg) as store:
        con = store.con
        w, p = _where(team, season)
        row = con.execute(
            f"SELECT COUNT(*), {_PASS}, AVG(epa), {_SUCC} FROM plays {w}", p).fetchone()
        rep.n_plays = int(row[0] or 0)
        if not rep.n_plays:
            return rep
        rep.pass_rate = float(row[1] or 0)
        rep.epa = float(row[2] or 0)
        rep.success_rate = float(row[3] or 0)

        lw, lp = _where(None, season)
        rep.league_pass_rate = float(con.execute(
            f"SELECT {_PASS} FROM plays {lw}", lp).fetchone()[0] or 0)

        # Liga-Pass-Raten je (down, dist) für den Vergleich
        league = {}
        for r in con.execute(
                f"SELECT down, {DIST_CASE} d, {_PASS} FROM plays {lw} "
                f"GROUP BY down, {DIST_CASE}", lp).fetchall():
            league[(r[0], r[1])] = float(r[2] or 0)

        for r in con.execute(
                f"SELECT down, {DIST_CASE} d, COUNT(*) n, {_PASS} pr, AVG(epa) "
                f"FROM plays {w} GROUP BY down, {DIST_CASE} HAVING COUNT(*)>=? "
                f"ORDER BY down, d", p + [min_n]).fetchall():
            lg = league.get((r[0], r[1]), rep.league_pass_rate)
            rep.by_down_dist.append({
                "down": r[0], "dist": r[1], "n": int(r[2]),
                "pass_rate": float(r[3]), "league_pass_rate": lg,
                "delta": float(r[3]) - lg, "epa": float(r[4] or 0)})

        for r in con.execute(
                f"SELECT {ZONE_CASE} z, COUNT(*) n, {_PASS}, AVG(epa) "
                f"FROM plays {w} GROUP BY {ZONE_CASE} HAVING COUNT(*)>=? "
                f"ORDER BY MIN(yardline_100) DESC", p + [min_n]).fetchall():
            rep.by_zone.append({"zone": r[0], "n": int(r[1]),
                                "pass_rate": float(r[2]), "epa": float(r[3] or 0)})

        rep.run_gaps = [{"gap": r[0], "n": int(r[1])} for r in con.execute(
            f"SELECT run_gap, COUNT(*) FROM plays {w}{' AND' if w else 'WHERE'} "
            f"is_rush AND run_gap IS NOT NULL GROUP BY run_gap ORDER BY 2 DESC",
            p).fetchall()]
        rep.pass_locations = [{"loc": r[0], "n": int(r[1])} for r in con.execute(
            f"SELECT pass_location, COUNT(*) FROM plays {w}{' AND' if w else 'WHERE'} "
            f"is_pass AND pass_location IS NOT NULL GROUP BY pass_location "
            f"ORDER BY 2 DESC", p).fetchall()]
        rep.play_action_rate = float(con.execute(
            f"SELECT AVG(CASE WHEN play_action THEN 1.0 ELSE 0.0 END) "
            f"FROM plays {w}{' AND' if w else 'WHERE'} is_pass", p).fetchone()[0] or 0)

        # Tells: vorhersehbare Situationen (Down+Distanz+Zone)
        for r in con.execute(
                f"SELECT down, {DIST_CASE} d, {ZONE_CASE} z, COUNT(*) n, {_PASS} pr "
                f"FROM plays {w} GROUP BY down, {DIST_CASE}, {ZONE_CASE} "
                f"HAVING COUNT(*)>=? ORDER BY ABS({_PASS}-0.5)*COUNT(*) DESC "
                f"LIMIT 8", p + [min_n]).fetchall():
            pr = float(r[4])
            if pr >= 0.75 or pr <= 0.25:
                rep.tells.append({"down": r[0], "dist": r[1], "zone": r[2],
                                  "n": int(r[3]), "pass_rate": pr})
    return rep


def render(rep: ScoutReport) -> str:
    if not rep.n_plays:
        return f"Keine Daten für Team {rep.team} (Saison {rep.season})."
    pct = lambda x: f"{round(x * 100)}%"  # noqa: E731
    L = [f"Scouting-Report: {rep.team}  (Saison {rep.season})", "=" * 56,
         f"Plays: {rep.n_plays}   Pass {pct(rep.pass_rate)} / Run "
         f"{pct(1 - rep.pass_rate)}   (Liga Pass {pct(rep.league_pass_rate)})",
         f"EPA/Play: {rep.epa:+.2f}   Success-Rate: {pct(rep.success_rate)}",
         f"Play-Action (bei Pässen): {pct(rep.play_action_rate)}"]
    if rep.tells:
        L.append("\nVORHERSEHBAR (Tells):")
        for t in rep.tells:
            tend = f"{pct(t['pass_rate'])} Pass" if t["pass_rate"] >= 0.5 \
                else f"{pct(1 - t['pass_rate'])} Run"
            L.append(f"  • {t['down']}. Down & {t['dist']}, {t['zone']} "
                     f"→ {tend}  (n={t['n']})")
    if rep.by_down_dist:
        L.append("\nNACH DOWN & DISTANZ (Abweichung zur Liga):")
        for r in rep.by_down_dist:
            arrow = "↑Pass" if r["delta"] > 0.05 else "↓Pass" if r["delta"] < -0.05 else "~"
            L.append(f"  {r['down']}. & {r['dist']:<6} "
                     f"Pass {pct(r['pass_rate'])} (Liga {pct(r['league_pass_rate'])}, "
                     f"{r['delta'] * 100:+.0f}pp {arrow})  EPA {r['epa']:+.2f}  n={r['n']}")
    if rep.by_zone:
        L.append("\nNACH FELDZONE:")
        for r in rep.by_zone:
            L.append(f"  {r['zone']:<20} Pass {pct(r['pass_rate'])}  "
                     f"EPA {r['epa']:+.2f}  n={r['n']}")
    if rep.run_gaps:
        L.append("\nLAUF-RICHTUNG: " + ", ".join(
            f"{g['gap']} {g['n']}" for g in rep.run_gaps))
    if rep.pass_locations:
        L.append("PASS-RICHTUNG: " + ", ".join(
            f"{p['loc']} {p['n']}" for p in rep.pass_locations))
    L.append("\nHinweis: deskriptive Analyse echter Plays – keine Garantie.")
    return "\n".join(L)
