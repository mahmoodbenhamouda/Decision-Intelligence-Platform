"""
etl/construire.py
=================
Construction de l'entrepôt : une seule commande, quatre couches, un contrôle.

    python -m etl.construire             # reconstruit si une source a changé
    python -m etl.construire --forcer    # reconstruit dans tous les cas
    python -m etl.construire --verifier  # dit seulement si l'entrepôt est à jour

Déroulement, dans UNE transaction :

    staging        sources CSV projetées et typées (tables temporaires)
      → faits      règles métier, grain déclaré
      → dimensions conformes, membres déduits des faits
      → marts      agrégats matérialisés
      → présentation vues aux noms lus par l'application
      → contrôles  une erreur annule tout : l'entrepôt précédent reste intact

La construction se fait EN PLACE : les tables écrites par l'application
(factures importées par OCR, retours de la boucle d'action) et les magasins
dérivés des modules de stock vivent dans le même fichier et ne sont jamais
touchés. Seuls les objets de l'ETL sont remplacés.

Reconstruction automatique : `assurer_a_jour()` compare la signature des
sources (taille et date de chaque CSV, version du schéma) à celle de la
dernière construction ; le moteur d'indicateurs l'appelle avant de lire.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

import duckdb

from etl import dimensions, faits, marts, presentation, qualite, staging
from etl.sources import (DOSSIER_RAPPORTS, DOSSIER_SOURCES, ENTREPOT, SOURCES, chemin,
                         sources_presentes)

#: Version du modèle de l'entrepôt. À incrémenter à chaque changement des
#: règles de construction : la signature change, l'entrepôt est reconstruit
#: au prochain accès même si aucun CSV n'a bougé.
VERSION_SCHEMA = "etoile-1"

RAPPORT = DOSSIER_RAPPORTS / "etl_construction.json"


def signature(dossier: Optional[Path] = None) -> str:
    parts = [f"schema:{VERSION_SCHEMA}"]
    for role in SOURCES:
        p = chemin(role, dossier)
        if p.exists():
            st = p.stat()
            parts.append(f"{p.name}:{st.st_size}:{int(st.st_mtime)}")
    return "|".join(sorted(parts))


def signature_construite(entrepot: Path) -> Optional[str]:
    """Signature de la dernière construction réussie (None si inconnue)."""
    if not entrepot.exists():
        return None
    try:
        con = duckdb.connect(str(entrepot), read_only=True)
        try:
            row = con.execute("SELECT signature FROM etl_execution LIMIT 1").fetchone()
        finally:
            con.close()
        return row[0] if row else None
    except Exception:
        return None


def construire(entrepot: Optional[Path] = None, dossier: Optional[Path] = None,
               rapport: Optional[Path] = RAPPORT) -> Dict[str, Any]:
    """Construit l'entrepôt ; lève une exception si un contrôle d'erreur échoue."""
    entrepot = Path(entrepot or ENTREPOT)
    dossier = Path(dossier or DOSSIER_SOURCES)
    entrepot.parent.mkdir(parents=True, exist_ok=True)
    debut = time.time()
    sig = signature(dossier)

    con = duckdb.connect(str(entrepot))
    try:
        con.execute("SET threads=4")
        con.execute("BEGIN TRANSACTION")
        try:
            etapes = {}
            for nom, etape in (("staging", lambda: staging.construire(con, dossier)),
                               ("faits", lambda: faits.construire(con)),
                               ("dimensions", lambda: dimensions.construire(con)),
                               ("marts", lambda: marts.construire(con)),
                               ("presentation", lambda: presentation.construire(con))):
                t = time.time()
                etape()
                etapes[nom] = round(time.time() - t, 2)
            controles = qualite.controler(con)
            en_erreur = qualite.erreurs(controles)
            if en_erreur:
                raise RuntimeError("contrôles de l'entrepôt en échec : " + "; ".join(
                    f"{c['controle']} = {c['valeur']:g}" for c in en_erreur))
            qualite.enregistrer(con, controles)
            volumes = {t: int(con.execute(f"SELECT count(*) FROM {t}").fetchone()[0])
                       for t in (*qualite.FAITS, "rejet_ligne_vente",
                                 *(d for d, _ in qualite.CLES))}
            duree = round(time.time() - debut, 2)
            # Heure locale sans fuseau : un TIMESTAMP WITH TIME ZONE ne se relit
            # en Python qu'avec pytz (absent de requirements.txt).
            con.execute("""CREATE OR REPLACE TABLE etl_execution AS
                           SELECT ? AS signature, ? AS version_schema,
                                  CAST(now() AS TIMESTAMP) AS construit_le,
                                  ? AS duree_s""",
                        [sig, VERSION_SCHEMA, duree])
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()

    resultat = {"entrepot": str(entrepot), "version_schema": VERSION_SCHEMA,
                "duree_s": duree, "etapes_s": etapes, "volumes": volumes,
                "controles": controles}
    if rapport is not None:
        try:
            Path(rapport).parent.mkdir(parents=True, exist_ok=True)
            Path(rapport).write_text(json.dumps(resultat, indent=2, ensure_ascii=False,
                                                default=str), encoding="utf-8")
        except Exception:
            pass
    return resultat


def assurer_a_jour(entrepot: Optional[Path] = None, dossier: Optional[Path] = None,
                   forcer: bool = False) -> Path:
    """Reconstruit l'entrepôt s'il est absent ou périmé, puis renvoie son chemin.

    * Sans les CSV (conteneur, poste de démonstration, CI), l'entrepôt déjà
      construit est la seule source : il est servi tel quel, jamais écrasé.
    * Si un autre processus tient l'entrepôt ouvert (l'API pendant qu'un script
      tourne), la reconstruction est remise au prochain accès : l'entrepôt
      actuel reste servi.
    """
    entrepot = Path(entrepot or ENTREPOT)
    dossier = Path(dossier or DOSSIER_SOURCES)
    if entrepot.exists() and not forcer:
        if not sources_presentes(dossier):
            return entrepot
        if signature_construite(entrepot) == signature(dossier):
            return entrepot
    try:
        construire(entrepot, dossier)
    except duckdb.IOException:
        if entrepot.exists():
            return entrepot
        raise
    return entrepot


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Construit l'entrepôt de données.")
    ap.add_argument("--forcer", action="store_true", help="reconstruire même si à jour")
    ap.add_argument("--verifier", action="store_true", help="dire seulement s'il est à jour")
    ap.add_argument("--entrepot", type=Path, default=None)
    ap.add_argument("--sources", type=Path, default=None)
    a = ap.parse_args(argv)

    entrepot = Path(a.entrepot or ENTREPOT)
    a_jour = signature_construite(entrepot) == signature(a.sources)
    if a.verifier:
        print(f"{entrepot} : {'à jour' if a_jour else 'à reconstruire'}")
        return 0 if a_jour else 1
    if a_jour and not a.forcer:
        print(f"{entrepot} : à jour, rien à faire (--forcer pour reconstruire).")
        return 0

    r = construire(entrepot, a.sources)
    print(f"Entrepôt construit en {r['duree_s']} s → {r['entrepot']}")
    for etape, s in r["etapes_s"].items():
        print(f"  {etape:<13} {s:>6} s")
    print("Volumes :")
    for t, n in r["volumes"].items():
        print(f"  {t:<22} {n:>9}")
    alertes = [c for c in r["controles"] if c["statut"] == "alerte"]
    print(f"Contrôles : {len(r['controles'])} exécutés, 0 erreur, {len(alertes)} alerte(s)")
    for c in alertes:
        print(f"  ! {c['controle']} = {c['valeur']:g} — {c['description']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
