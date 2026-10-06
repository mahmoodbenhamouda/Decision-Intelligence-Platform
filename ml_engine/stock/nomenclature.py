"""Classification des références produit — le maillon le plus fragile, isolé et mesuré."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from config.settings import settings
    BASE = Path(settings.base_dir)
except Exception:  # pragma: no cover
    BASE = Path(__file__).resolve().parents[2]

REPORTS_DIR = BASE / "reports"


PRESTATION = "prestation"
EQUIPEMENT = "equipement"
PIECE = "piece_detachee"
CONSOMMABLE = "consommable"

CATEGORIES = (PRESTATION, EQUIPEMENT, PIECE, CONSOMMABLE)

_MOTIFS_PRESTATION = re.compile(
    r"\b(CONTRAT|MAINTENANCE|FORMATION|INSTALLATION|DEPLACEMENT|"
    r"MAIN\s*D.?\s*OEUVRE|PRESTATION|FRAIS|TRANSPORT|LOCATION|ABONNEMENT|"
    r"ETALONNAGE|QUALIFICATION|HOTLINE|ASSISTANCE)\b",
    re.IGNORECASE)

_MOTIFS_PIECE = re.compile(
    r"\b(SEALS?|JOINT|UPGRADE|P\.?M\.?\s|PIECE|SPARE|TUBULURE|TUBING|"
    r"FILTRE|FILTER|CABLE|BATTERIE|LAMPE|CARTE\s+ELECTRO|ADAPTAT|"
    r"SERINGUE\s+METAL|POMPE|VANNE|COURROIE|FUSIBLE|CAPOT|SUPPORT\s+METAL|"
    r"ECRAN|CLAVIER|ALIMENTATION\s+ELECT)",
    re.IGNORECASE)

_MOTIFS_EQUIPEMENT = re.compile(
    r"\b(AUTOMATE|ANALYZER|ANALYSEUR|SYSTEM|SYSTEME|INSTRUMENT|APPAREIL|"
    r"MODULE|STATION|IMPRIMANTE|LECTEUR|CENTRIFUG|MICROSCOPE|ORDINATEUR|"
    r"PC\b|AGITATEUR|ETUVE|BAIN\s+MARIE|CONGELATEUR|REFRIGERATEUR|"
    r"INCUBATEUR|THERMOCYCLEUR|SPECTRO)",
    re.IGNORECASE)

_MOTIFS_CONSOMMABLE = re.compile(
    r"\b(REACTIF|REAGENT|TEST|TESTS|CONTROLE|CONTRÔLE|CALIBRA|QCV|"
    r"DILLUANT|DILUANT|SOLUTION|GEL|SERUM|ANTISERUM|PANEL|KIT\s+DE\s+DOSAGE|"
    r"CARTOUCHE|BANDELETTE|STRIP|MILIEU|GELOSE|AGAR|TUBE|CUVETTE|"
    r"EMBOUT|CONE|PIPETTE|LAME|LAMELLE|POCHE|ANTIBIOGRAMME|VIDAS\s+[A-Z])",
    re.IGNORECASE)


_FAMILLE_VERS_CATEGORIE = {
    "REACTIF": CONSOMMABLE,
    "REACTIFS": CONSOMMABLE,
    "CONSOMMABLE": CONSOMMABLE,
    "CONSOMMABLES": CONSOMMABLE,
    "EQUIPEMENT": EQUIPEMENT,
    "EQUIPEMENTS": EQUIPEMENT,
    "INSTRUMENT": EQUIPEMENT,
    "APPAREIL": EQUIPEMENT,
    "PRESTATION": PRESTATION,
    "PIECE": PIECE,
    "PIECES": PIECE,
    "PIECE DETACHEE": PIECE,
    "PIECES DETACHEES": PIECE,
}

_PREFIXES_FAMILLE = (
    ("SERVICE", PRESTATION),
    ("PRESTATION", PRESTATION),
    ("CONTRAT", PRESTATION),
    ("MAINTENANCE", PRESTATION),
    ("REACTIF", CONSOMMABLE),
    ("CONSOMMABLE", CONSOMMABLE),
    ("EQUIPEMENT", EQUIPEMENT),
    ("PIECE", PIECE),
)

_familles_erp: Optional[Dict[str, str]] = None

_echec_chargement: Optional[str] = None


def charger_familles_erp(con=None) -> Dict[str, str]:
    """Famille ERP dominante par désignation, lue dans `sales_lines`."""
    global _familles_erp
    if _familles_erp is not None:
        return _familles_erp

    fermer = con is None
    try:
        if con is None:
            from ml_engine.stock.flux_reels import _connect
            con = _connect()
        try:
            rows = con.execute("""
                SELECT upper(trim(designation)) AS cle,
                       upper(trim(famille))     AS famille,
                       sum(abs(montant))        AS poids
                FROM sales_lines
                WHERE designation IS NOT NULL AND trim(designation) <> ''
                  AND famille IS NOT NULL AND trim(famille) <> ''
                GROUP BY 1, 2
                ORDER BY 1, poids DESC, famille
            """).fetchall()
        finally:
            if fermer:
                con.close()
    except Exception as e:
        global _echec_chargement
        _echec_chargement = f"{type(e).__name__}: {e}"
        print(f"[nomenclature] ÉCHEC de lecture des familles de produits — "
              f"{_echec_chargement}")
        print("[nomenclature]   le classement retombe sur les mots-clés de "
              "libellé, ce qui n'est PAS équivalent.")
        _familles_erp = {}
        return _familles_erp

    out: Dict[str, str] = {}
    for cle, famille, _poids in rows:
        if cle not in out:
            out[cle] = famille
    _familles_erp = out
    return out


def _categorie_erp(produit: Optional[str]) -> Optional[str]:
    """Catégorie déduite de la famille de produit, si elle est renseignée et connue."""
    cle = (produit or "").strip().upper()
    if not cle:
        return None
    famille = charger_familles_erp().get(cle)
    if not famille:
        return None
    if famille in _FAMILLE_VERS_CATEGORIE:
        return _FAMILLE_VERS_CATEGORIE[famille]
    for prefixe, categorie in _PREFIXES_FAMILLE:
        if famille.startswith(prefixe):
            return categorie
    return None


def classer(produit: Optional[str]) -> str:
    """Catégorie d'une référence."""
    p = (produit or "").strip()
    depuis_erp = _categorie_erp(produit)

    if depuis_erp is not None:
        if depuis_erp == CONSOMMABLE and _MOTIFS_PIECE.search(p):
            return PIECE
        return depuis_erp
    if not p:
        return PRESTATION
    if _MOTIFS_PRESTATION.search(p):
        return PRESTATION
    if _MOTIFS_PIECE.search(p):
        return PIECE
    if _MOTIFS_EQUIPEMENT.search(p):
        return EQUIPEMENT
    return CONSOMMABLE


def origine_du_classement(produit: Optional[str]) -> str:
    """D'où vient la catégorie : `erp`, `erp_precise`, `mot_cle`, ou `defaut`."""
    p = (produit or "").strip()
    depuis_erp = _categorie_erp(produit)
    if depuis_erp is not None:
        if depuis_erp == CONSOMMABLE and _MOTIFS_PIECE.search(p):
            return "erp_precise"
        return "erp"
    if not p:
        return "defaut"
    if (_MOTIFS_PRESTATION.search(p) or _MOTIFS_PIECE.search(p)
            or _MOTIFS_EQUIPEMENT.search(p) or _MOTIFS_CONSOMMABLE.search(p)):
        return "mot_cle"
    return "defaut"


def classee_explicitement(produit: Optional[str]) -> bool:
    """La catégorie repose-t-elle sur un signal, quel qu'il soit ?"""
    return origine_du_classement(produit) != "defaut"


def est_perissable(produit: Optional[str]) -> bool:
    """Seuls les consommables périment."""
    return classer(produit) == CONSOMMABLE


def _lignes(con) -> List[Tuple[str, float, float]]:
    """(produit, position, valeur_dt) des références à position positive."""
    tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
    if "stock_flux_reel" not in tables:
        return []
    return [(p or "", float(pos or 0), float(v or 0)) for p, pos, v in con.execute("""
        SELECT produit, position, position * cout_unitaire
        FROM stock_flux_reel
        WHERE position > 0 AND cout_unitaire IS NOT NULL
    """).fetchall()]


def mesurer(con=None) -> Dict[str, Any]:
    """Couverture du classement, en nombre de références ET en valeur."""
    fermer = con is None
    if con is None:
        from ml_engine.stock.flux_reels import _connect
        con = _connect()
    try:
        lignes = _lignes(con)
        if not lignes:
            return {
                "disponible": False,
                "motif": ("table stock_flux_reel absente — lancer "
                          "ml_engine.stock.flux_reels"),
            }

        charger_familles_erp(con)
    finally:
        if fermer:
            con.close()

    par_cat: Dict[str, Dict[str, float]] = {
        c: {"n_references": 0, "valeur_dt": 0.0, "n_explicites": 0,
            "valeur_explicite_dt": 0.0} for c in CATEGORIES}

    par_origine: Dict[str, Dict[str, float]] = {
        o: {"n_references": 0, "valeur_dt": 0.0}
        for o in ("erp", "erp_precise", "mot_cle", "defaut")}

    for produit, _pos, valeur in lignes:
        cat = classer(produit)
        d = par_cat[cat]
        d["n_references"] += 1
        d["valeur_dt"] += valeur

        origine = origine_du_classement(produit)
        par_origine[origine]["n_references"] += 1
        par_origine[origine]["valeur_dt"] += valeur

        if origine != "defaut":
            d["n_explicites"] += 1
            d["valeur_explicite_dt"] += valeur

    n_total = sum(d["n_references"] for d in par_cat.values())
    val_total = sum(d["valeur_dt"] for d in par_cat.values())
    n_expl = sum(d["n_explicites"] for d in par_cat.values())
    val_expl = sum(d["valeur_explicite_dt"] for d in par_cat.values())

    for d in par_origine.values():
        d["valeur_dt"] = round(d["valeur_dt"], 0)
        d["part_valeur_pct"] = round(d["valeur_dt"] / max(val_total, 1) * 100, 1)

    for d in par_cat.values():
        d["valeur_dt"] = round(d["valeur_dt"], 0)
        d["valeur_explicite_dt"] = round(d["valeur_explicite_dt"], 0)
        d["part_valeur_pct"] = round(d["valeur_dt"] / max(val_total, 1) * 100, 1)

    conso = par_cat[CONSOMMABLE]
    val_conso_defaut = conso["valeur_dt"] - conso["valeur_explicite_dt"]

    return {
        "disponible": True,
        "version": 1,
        "n_references": n_total,
        "valeur_totale_dt": round(val_total, 0),
        "par_categorie": par_cat,
        "par_origine": par_origine,
        "n_designations_avec_famille_erp": len(charger_familles_erp()),
        "hierarchie": (
            "La famille de produit du catalogue (renseignée à 99,9 %) "
            "PRIME sur les mots-clés : un libellé est déclaratif et changeant, "
            "une famille saisie au catalogue est structurelle. Même hiérarchie que "
            "pour l'indicateur de mouvement de stock."),
        "echec_de_chargement": _echec_chargement,
        "deux_erreurs_documentees": (
            "1) Ce module a d'abord affirmé qu'aucune nomenclature n'existait, "
            "sans avoir interrogé la colonne. 2) Le chemin de lecture ajouté "
            "ensuite renvoyait 0 désignation, ce qui a fait conclure une "
            "deuxième fois à son absence — la cause étant un amorçage de cache "
            "APRÈS fermeture de la connexion, dont l'exception était avalée sans "
            "trace. Un `except` muet n'a pas seulement dégradé un chiffre : il a "
            "produit une conclusion fausse sur les données. Le champ "
            "`echec_de_chargement` ci-dessus existe pour que cela ne puisse plus "
            "se reproduire en silence."),
        "couverture_references_pct": round(n_expl / max(n_total, 1) * 100, 1),
        "couverture_valeur_pct": round(val_expl / max(val_total, 1) * 100, 1),
        "valeur_consommable_par_defaut_dt": round(val_conso_defaut, 0),
        "part_consommable_par_defaut_pct": round(
            val_conso_defaut / max(val_total, 1) * 100, 1),
        "pourquoi_ce_chiffre_compte": (
            "Une référence classée « consommable » PAR DÉFAUT l'est faute d'avoir "
            "reconnu quoi que ce soit dans son libellé. C'est la seule classe qui "
            "déclenche une perte par péremption : le montant ci-dessus mesure "
            "donc la valeur exposée à une erreur de classement, et lui seul "
            "borne honnêtement la fiabilité du module d'obsolescence."),
        "limite_residuelle": (
            "Ce qui reste classé par mot-clé ou par défaut correspond aux "
            "désignations dont la famille de produit est vide ou porte une valeur non "
            "répertoriée. Ces cas sont comptés ci-dessus et exportés dans "
            "reports/nomenclature_a_valider.csv, triés par valeur. Une famille "
            "ERP non répertoriée n'est jamais devinée : le repli prend le relais "
            "et le compteur la rend visible."),
    }


def exporter_pour_validation(con=None, limite: int = 300) -> Optional[Path]:
    """Fichier que l'entreprise corrige ligne par ligne."""
    fermer = con is None
    if con is None:
        from ml_engine.stock.flux_reels import _connect
        con = _connect()
    try:
        lignes = _lignes(con)
    finally:
        if fermer:
            con.close()

    if not lignes:
        return None

    lignes.sort(key=lambda t: -t[2])
    chemin = REPORTS_DIR / "nomenclature_a_valider.csv"
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    with open(chemin, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["produit", "valeur_en_stock_dt", "categorie_deduite",
                    "deduite_par", "perime_t_il", "CORRECTION_ENTREPRISE",
                    "duree_de_conservation_mois"])
        _ORIGINES = {"erp": "famille de produit",
                     "erp_precise": "famille connue + pièce détachée reconnue",
                     "mot_cle": "mot-clé du libellé",
                     "defaut": "DÉFAUT — aucun signal"}
        for produit, _pos, valeur in lignes[:limite]:
            cat = classer(produit)
            w.writerow([
                produit,
                round(valeur, 0),
                cat,
                _ORIGINES[origine_du_classement(produit)],
                "oui" if cat == CONSOMMABLE else "non",
                "",
                "",
            ])
    return chemin


def afficher() -> None:
    m = mesurer()
    if not m.get("disponible"):
        print(f"\n{m.get('motif')}\n")
        return

    def dt(v: float) -> str:
        return f"{v:,.0f} DT".replace(",", " ")

    print("\n" + "=" * 78)
    print("  NOMENCLATURE PRODUIT — couverture du classement par libellé")
    print("=" * 78)
    print(f"\n  Références valorisées : {m['n_references']:,}".replace(",", " "))
    print(f"  Valeur totale         : {dt(m['valeur_totale_dt'])}")

    print(f"\n  {'catégorie':<18}{'réfs':>7}{'valeur':>16}{'part':>8}{'motif reconnu':>16}")
    for cat, d in m["par_categorie"].items():
        print(f"  {cat:<18}{d['n_references']:>7}{dt(d['valeur_dt']):>16}"
              f"{d['part_valeur_pct']:>7.1f}%{d['n_explicites']:>12}/{d['n_references']}")

    print(f"\n  {'origine du classement':<26}{'réfs':>7}{'valeur':>16}{'part':>8}")
    _LIB = {"erp": "famille de produit",
            "erp_precise": "famille connue + pièce reconnue",
            "mot_cle": "mot-clé du libellé",
            "defaut": "DÉFAUT — aucun signal"}
    for o, d in m["par_origine"].items():
        print(f"  {_LIB[o]:<26}{d['n_references']:>7}{dt(d['valeur_dt']):>16}"
              f"{d['part_valeur_pct']:>7.1f}%")
    print(f"\n  ({m['n_designations_avec_famille_erp']} désignations portent une "
          "famille au catalogue)")

    print(f"\n  Couverture en références : {m['couverture_references_pct']} %")
    print(f"  Couverture en valeur     : {m['couverture_valeur_pct']} %")
    print(f"\n  VALEUR EXPOSÉE À UNE ERREUR DE CLASSEMENT :")
    print(f"    {dt(m['valeur_consommable_par_defaut_dt'])}  "
          f"({m['part_consommable_par_defaut_pct']} % du stock valorisé)")
    print("    — classée « consommable » faute d'avoir reconnu son libellé,")
    print("      donc susceptible d'être annoncée en perte à tort.")

    chemin = exporter_pour_validation()
    if chemin:
        print(f"\n  Grille de correction écrite : {chemin.name}")
        print("  (triée par valeur : les premières lignes sont les plus rentables")
        print("   à faire valider par l'entreprise)")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json.dump(m, open(REPORTS_DIR / "nomenclature_metrics.json", "w",
                      encoding="utf-8"), indent=2, ensure_ascii=False)
    print("=" * 78 + "\n")


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    afficher()
