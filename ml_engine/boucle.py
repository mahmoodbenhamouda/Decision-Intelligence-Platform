"""Le retour du terrain vers les modèles — la moitié manquante du projet."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

logger = logging.getLogger("boucle")

COLONNES_TACHES = [
    ("id", "INTEGER"), ("client_code", "VARCHAR"), ("origine_categorie", "VARCHAR"),
    ("origine_titre", "VARCHAR"), ("type", "VARCHAR"), ("severite", "VARCHAR"),
    ("montant_en_jeu_dt", "DOUBLE"), ("statut", "VARCHAR"), ("resultat", "VARCHAR"),
    ("gagnee", "INTEGER"), ("montant_obtenu_dt", "DOUBLE"),
    ("delegation_auto", "INTEGER"),
    ("delai_traitement_j", "DOUBLE"),
    ("creee_le", "TIMESTAMP"), ("close_le", "TIMESTAMP"),
]
def _store_path() -> Path:
    from ml_engine.analytics.kpi_engine import STORE_PATH
    return Path(STORE_PATH)


def _lire_base_applicative() -> Dict[str, List[Dict[str, Any]]]:
    """Lit les tâches et leurs résultats dans la base applicative (PostgreSQL)."""
    from sqlalchemy import select

    from api.auth.database import get_db, init_db
    from api.auth.models import RESULTATS_GAGNANTS, Tache

    init_db()
    db = next(get_db())
    try:
        taches = db.execute(select(Tache)).scalars().all()

        lignes_t = []
        for t in taches:
            delai = None
            if t.created_at and t.closed_at:
                delai = round(max(0.0, (t.closed_at - t.created_at).total_seconds() / 86400), 3)
            lignes_t.append({
                "id": int(t.id),
                "client_code": (t.client_code or "").strip() or None,
                "origine_categorie": t.origine_categorie,
                "origine_titre": t.origine_titre,
                "type": t.type,
                "severite": t.severite,
                "montant_en_jeu_dt": float(t.montant_dt or 0),
                "statut": t.statut,
                "resultat": t.resultat,
                "gagnee": 1 if (t.resultat or "") in RESULTATS_GAGNANTS else 0,
                "montant_obtenu_dt": float(t.resultat_montant_dt) if t.resultat_montant_dt is not None else None,
                "delegation_auto": 1 if t.delegation_auto else 0,
                "delai_traitement_j": delai,
                "creee_le": t.created_at,
                "close_le": t.closed_at,
            })

        return {"taches": lignes_t}
    finally:
        db.close()


def _ecrire(con, table: str, colonnes, lignes: List[Dict[str, Any]]) -> int:
    """(Re)crée la table et y insère les lignes."""
    cols = ", ".join(f'"{n}" {t}' for n, t in colonnes)
    con.execute(f"DROP TABLE IF EXISTS {table}")
    con.execute(f"CREATE TABLE {table} ({cols})")
    if not lignes:
        return 0
    noms = [n for n, _ in colonnes]
    marqueurs = ", ".join("?" for _ in noms)
    con.executemany(f"INSERT INTO {table} VALUES ({marqueurs})",
                    [[l.get(n) for n in noms] for l in lignes])
    return len(lignes)


def exporter_retours(verbose: bool = True) -> Dict[str, Any]:
    """Copie les résultats du terrain dans l'entrepôt."""
    resultat: Dict[str, Any] = {"ok": False, "taches": 0}
    try:
        donnees = _lire_base_applicative()
    except Exception as e:
        resultat["motif"] = f"base applicative illisible ({type(e).__name__} : {e})"
        if verbose:
            print(f"[boucle] {resultat['motif']}")
        return resultat

    chemin = _store_path()
    if not chemin.exists():
        resultat["motif"] = f"entrepôt absent ({chemin.name}) — lancez d'abord la construction"
        if verbose:
            print(f"[boucle] {resultat['motif']}")
        return resultat

    try:
        import duckdb
        con = duckdb.connect(str(chemin))
    except Exception as e:
        resultat["motif"] = ("entrepôt occupé par un autre programme "
                             f"({type(e).__name__}) — arrêtez l'API puis relancez")
        if verbose:
            print(f"[boucle] {resultat['motif']}")
        return resultat

    try:
        n_t = _ecrire(con, "retours_taches", COLONNES_TACHES, donnees["taches"])
        con.close()
    except Exception as e:  # pragma: no cover
        try:
            con.close()
        except Exception:
            pass
        resultat["motif"] = f"écriture impossible ({type(e).__name__} : {e})"
        if verbose:
            print(f"[boucle] {resultat['motif']}")
        return resultat

    resultat.update({"ok": True, "taches": n_t, "entrepot": str(chemin)})
    if verbose:
        print(f"[boucle] {n_t} tâche(s) exportée(s) vers l'entrepôt.")
    return resultat


def resume() -> Dict[str, Any]:
    """Ce que le terrain a renvoyé, lu depuis l'entrepôt (lecture seule)."""
    vide = {"disponible": False, "taches": 0, "gagnees": 0, "montant_obtenu_dt": 0.0}
    try:
        import duckdb
        chemin = _store_path()
        if not chemin.exists():
            return {**vide, "motif": "entrepôt absent"}
        con = duckdb.connect(str(chemin), read_only=True)
        tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        if "retours_taches" not in tables:
            con.close()
            return {**vide, "motif": "aucun retour exporté pour l'instant"}
        n, fini, gag, montant, delai = con.execute(
            "SELECT count(*), coalesce(sum(CASE WHEN statut = 'terminee' THEN 1 END),0), "
            "coalesce(sum(gagnee),0), "
            "coalesce(sum(CASE WHEN gagnee = 1 THEN montant_obtenu_dt END),0), "
            "avg(delai_traitement_j) FROM retours_taches").fetchone()
        par_domaine = con.execute(
            "SELECT origine_categorie, count(*), coalesce(sum(gagnee),0) "
            "FROM retours_taches WHERE origine_categorie IS NOT NULL "
            "GROUP BY 1 ORDER BY 2 DESC").fetchall()
        con.close()
        return {
            "disponible": True,
            "taches": int(n),
            "taches_terminees": int(fini),
            "gagnees": int(gag),
            "montant_obtenu_dt": round(float(montant), 2),
            "delai_moyen_j": round(float(delai), 2) if delai is not None else None,
            "par_domaine": [{"domaine": d, "taches": int(c), "gagnees": int(g)}
                            for d, c, g in par_domaine],
        }
    except Exception as e:
        return {**vide, "motif": f"lecture impossible ({type(e).__name__})"}


if __name__ == "__main__":  # pragma: no cover
    # Ce script lit la base d'auth sans émettre de jeton ; la clé n'est posée que
    # pour satisfaire l'import. Longueur conforme au minimum HS256.
    os.environ.setdefault("JWT_SECRET_KEY",
                          "cle-locale-export-sans-emission-de-jeton")
    info = exporter_retours()
    if info.get("ok"):
        r = resume()
        print(f"[boucle] {r['taches']} retour(s), {r['gagnees']} action(s) gagnée(s), "
              f"{r['montant_obtenu_dt']:,.0f} DT obtenus.".replace(",", " "))
