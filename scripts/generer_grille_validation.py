"""Pré-remplit la grille de validation métier avec les CAS RÉELS de la plateforme."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

REPORTS = BASE / "reports"
SORTIE = REPORTS / "validation_metier.csv"

PAR_GRILLE = 15


def _lire(nom: str) -> Optional[Dict[str, Any]]:
    p = REPORTS / nom
    if not p.exists():
        return None
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return None


def _lignes_churn() -> List[List[str]]:
    """Clients que le modèle juge sur le point de décrocher."""
    try:
        from ml_engine.analytics.kpi_engine import _charger_churn_si_servi
        ch = _charger_churn_si_servi()
    except Exception:
        return []
    if not ch.get("servi"):
        return []

    out = []
    for c in (ch.get("top") or [])[:PAR_GRILLE]:
        proba = c.get("probabilite_decrochage")
        out.append([
            "1 — Décrochage client",
            f"{c.get('nom') or c.get('code')}",
            (f"risque de décrochage {round(float(proba) * 100)} % à 90 jours, "
             f"enjeu {round(float(c.get('enjeu_dt') or 0)):,} DT".replace(",", " ")
             if proba is not None else "signalé à risque"),
            "ce client est-il réellement en train de s'éloigner ?",
            "", "",
        ])
    return out


def _lignes_encours() -> List[List[str]]:
    """Comptes dont la vérification est jugée la plus rentable."""
    m = _lire("encours_metrics.json")
    if not m:
        return []
    out = []
    for c in (m.get("clients_a_verifier") or [])[:PAR_GRILLE]:
        out.append([
            "2 — Recouvrement",
            str(c.get("nom") or c.get("code")),
            (f"{round(float(c.get('montant_echu_dt') or 0)):,} DT échus, "
             f"{c.get('silence_jours')} jours sans commande".replace(",", " ")),
            "ces factures sont-elles réellement impayées à ce jour ?",
            "", "",
        ])
    return out


def _lignes_obsolescence() -> List[List[str]]:
    """Références que la plateforme annonce comme non écoulables."""
    try:
        from ml_engine.stock.flux_reels import detecter_obsolescence
        obs = detecter_obsolescence()
    except Exception:
        return []

    out = []
    for o in obs[:PAR_GRILLE]:
        out.append([
            "3 — Stock non écoulable",
            str(o.get("produit")),
            (f"{o.get('mois_couverture')} mois de stock, perte probable "
             f"{round(float(o.get('perte_probable_dt') or 0)):,} DT".replace(",", " ")),
            ("ce produit périmera-t-il réellement avant d'être vendu ? "
             "(sinon : pourquoi le détenez-vous ?)"),
            "", "",
        ])
    return out


def _lignes_ruptures() -> List[List[str]]:
    """Références que la plateforme annonce comme à commander."""
    try:
        from ml_engine.stock.flux_reels import detecter_ruptures
        rup = detecter_ruptures()
    except Exception:
        return []

    out = []
    for r in rup[:PAR_GRILLE]:
        out.append([
            "4 — Réapprovisionnement",
            str(r.get("produit")),
            (f"{r.get('lecture')} — "
             f"{round(float(r.get('quantite_suggeree') or 0)):,} unités "
             "suggérées".replace(",", " ")),
            "cette référence manque-t-elle réellement aujourd'hui ?",
            "", "",
        ])
    return out


def _lignes_nomenclature() -> List[List[str]]:
    """Classements produit sur lesquels tout le domaine stock repose."""
    try:
        from ml_engine.stock.nomenclature import classee_explicitement, classer
        from ml_engine.stock.flux_reels import _connect
    except Exception:
        return []

    try:
        con = _connect()
        try:
            rows = con.execute("""
                SELECT produit, position * cout_unitaire AS valeur
                FROM stock_flux_reel
                WHERE position > 0 AND cout_unitaire IS NOT NULL
                ORDER BY position * cout_unitaire DESC
                LIMIT 200
            """).fetchall()
        finally:
            con.close()
    except Exception:
        return []

    douteuses = [(p, v) for p, v in rows if not classee_explicitement(p or "")]
    out = []
    for produit, valeur in douteuses[:PAR_GRILLE]:
        cat = classer(produit or "")
        out.append([
            "5 — Classement produit",
            str(produit),
            (f"classé « {cat} » PAR DÉFAUT (aucun mot-clé reconnu), "
             f"{round(float(valeur or 0)):,} DT en stock".replace(",", " ")),
            ("est-ce un consommable qui périme, un équipement, ou une pièce "
             "détachée ? Quelle est sa durée de conservation ?"),
            "", "",
        ])
    return out


def construire() -> Path:
    lignes: List[List[str]] = []
    for fn in (_lignes_churn, _lignes_encours, _lignes_obsolescence,
               _lignes_ruptures, _lignes_nomenclature):
        try:
            lignes.extend(fn())
        except Exception as e:
            print(f"  [!] {fn.__name__} : {type(e).__name__} — grille partielle")

    REPORTS.mkdir(parents=True, exist_ok=True)
    with open(SORTIE, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["grille", "cas", "ce_que_la_plateforme_affirme",
                    "question_posee", "VERDICT_ENTREPRISE", "COMMENTAIRE"])
        for l in lignes:
            w.writerow(l)

        w.writerow([])
        w.writerow(["6 — CE QUE LA PLATEFORME A MANQUÉ", "", "", "", "", ""])
        w.writerow(["", "(à compléter par l'entreprise)",
                    "aucune ligne ne peut être pré-remplie ici",
                    "quels clients, créances ou produits inquiétants "
                    "N'APPARAISSENT PAS dans les listes ci-dessus ?", "", ""])
        for _ in range(10):
            w.writerow(["6 — Manqué", "", "", "", "", ""])

    return SORTIE


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    print("\n" + "=" * 74)
    print("  GRILLE DE VALIDATION MÉTIER — pré-remplissage des cas réels")
    print("=" * 74)
    chemin = construire()
    n = sum(1 for _ in open(chemin, encoding="utf-8-sig")) - 1
    print(f"\n  {n} ligne(s) écrites : {chemin}")
    print("\n  Ce fichier se remplit AVEC l'entreprise, jamais à sa place.")
    print("  La colonne VERDICT_ENTREPRISE est volontairement vide : une grille")
    print("  auto-remplie mesurerait la plateforme contre elle-même.")
    print("\n  La section 6 est la plus importante — elle demande ce que la")
    print("  plateforme a MANQUÉ, que nulle métrique interne ne peut révéler.")
    print("=" * 74 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
