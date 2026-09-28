"""
ml_engine/analytics/payment_scenario.py
=======================================
SCÉNARIOS D'ENCAISSEMENT — que se passe-t-il si les clients paient en retard ?

## Pourquoi ce module existe (et ce qu'il n'est PAS)

L'export ERP fournit la date d'émission et la date d'échéance, **jamais la date
de paiement réelle** (colonnes `REG`, `REGTYP`, `MTR3` vides, `ETAT` constant à
`'NR'`). Conséquence directe : le DSO calculé est un **délai accordé**, pas un
délai d'encaissement.

Une IA ne peut pas « prédire » la date de paiement ici : prédire suppose
d'avoir observé la cible pour apprendre, et il n'existe **aucune** date de
paiement dans les données. Un modèle entraîné sans cible ne prédirait rien —
il restituerait l'hypothèse qu'on lui aurait injectée, sous une apparence
savante. Ce serait un chiffre inventé.

Ce module fait donc l'inverse d'une prédiction déguisée : il rend
**l'hypothèse explicite, visible et modifiable**. L'utilisateur (ou le
directeur financier, qui connaît ses clients) fournit un comportement de
paiement — « le secteur public règle en moyenne 45 jours après l'échéance » —
et le module calcule, de façon parfaitement déterministe, ce que cela implique :
DSO réel simulé, encours estimé à une date donnée, décalage de trésorerie.

    Hypothèse assumée + calcul exact  ≠  prédiction inventée présentée comme un fait

C'est la posture scientifiquement défendable : on ne fabrique pas de donnée, on
quantifie l'impact d'hypothèses que l'on affiche.

## Scénarios par défaut

Trois jeux d'hypothèses calibrés sur des ordres de grandeur du secteur (délais
de règlement du secteur public tunisien, usages du B2B médical) — mais ce ne
sont QUE des points de départ, à ajuster avec le client :

    optimiste  : paiement à l'échéance (+0 j),         5 % de retard
    central    : +30 j après échéance,                20 % de retard
    pessimiste : +75 j après échéance,                35 % de retard

Chaque résultat porte son hypothèse en clair. Aucun scénario n'est présenté
comme « la » vérité.

Usage :
    python -m ml_engine.analytics.payment_scenario
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Définition d'un scénario ────────────────────────────────────────────────


@dataclass
class PaymentScenario:
    """Hypothèse de comportement de paiement — un paramètre, pas une prédiction."""
    nom: str
    retard_moyen_jours: int          # jours APRÈS l'échéance
    part_en_retard_pct: float        # % des factures concernées par ce retard
    description: str = ""

    def dso_reel_estime(self, delai_accorde_moyen: float) -> float:
        """DSO simulé = délai accordé + (retard moyen × part concernée)."""
        return delai_accorde_moyen + self.retard_moyen_jours * (self.part_en_retard_pct / 100.0)


SCENARIOS: Dict[str, PaymentScenario] = {
    "optimiste": PaymentScenario(
        "Optimiste", 0, 5.0,
        "Les clients règlent à l'échéance ; 5 % de retards marginaux."),
    "central": PaymentScenario(
        "Central", 30, 20.0,
        "20 % des factures réglées avec ~30 jours de retard — usage courant du B2B médical."),
    "pessimiste": PaymentScenario(
        "Pessimiste", 75, 35.0,
        "35 % des factures réglées avec ~75 jours de retard — tension sur le secteur public."),
}

AVERTISSEMENT = (
    "HYPOTHÈSE, PAS UNE PRÉDICTION. L'ERP ne contient aucune date de paiement "
    "réelle : ces montants découlent du paramètre de retard affiché ci-dessus, "
    "appliqué aux échéances réelles. Ajustez le paramètre avec la connaissance "
    "terrain de vos clients — ou fournissez les règlements (champs REG/REGTYP/"
    "MTR3 de l'ERP) pour obtenir des chiffres constatés."
)


# ── Accès aux données ───────────────────────────────────────────────────────
def _connect(data_dir: Optional[Path] = None):
    import duckdb
    try:
        from ml_engine.analytics.kpi_engine import STORE_PATH
        db = str(STORE_PATH)
    except Exception:
        db = str(Path(__file__).resolve().parents[2] / "output" / "analytics_store.duckdb")
    return duckdb.connect(db, read_only=True)


def _where(filters: Optional[Dict[str, Any]]) -> str:
    try:
        from ml_engine.analytics.kpi_engine import _sales_where
        return _sales_where(filters or {})
    except Exception:
        return "1=1"


# ── Calcul principal ────────────────────────────────────────────────────────
def compute_scenarios(filters: Optional[Dict[str, Any]] = None,
                      scenario_custom: Optional[PaymentScenario] = None,
                      as_of: Optional[date] = None,
                      data_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Calcule l'impact des scénarios de paiement sur le périmètre filtré.

    Args:
        filters: mêmes filtres que le dashboard (isolation client respectée).
        scenario_custom: hypothèse sur mesure fournie par l'utilisateur.
        as_of: date d'observation (défaut : dernière échéance des données).

    Returns:
        dict avec, pour chaque scénario : DSO simulé, encours estimé à `as_of`,
        décalage de trésorerie, et l'hypothèse affichée en clair.
    """
    W = _where(filters)
    try:
        con = _connect(data_dir)
        base = con.execute(f"""
            SELECT avg(payment_delay_days)                      AS delai_moyen,
                   max(date)                                    AS derniere_facture,
                   count(*) FILTER (WHERE echeance IS NOT NULL) AS n_avec_echeance,
                   sum(ttc) FILTER (WHERE echeance IS NOT NULL) AS ca_avec_echeance
            FROM sales WHERE {W}
        """).fetchone()
    except Exception as e:
        return {"error": f"Entrepôt indisponible : {e}", "scenarios": []}

    delai_moyen = float(base[0] or 0)
    derniere_facture = base[1]
    n_ech = int(base[2] or 0)
    ca_ech = float(base[3] or 0)

    if not n_ech:
        con.close()
        return {"error": "Aucune facture avec échéance sur ce périmètre.", "scenarios": []}

    # Date d'observation = dernière FACTURE ÉMISE (= « aujourd'hui » du jeu de
    # données). Volontairement pas `max(echeance)` : cette valeur est une queue
    # de distribution — une seule facture peut avoir une échéance très lointaine
    # et fausser tout le calcul d'encours.
    ref = as_of or (derniere_facture if isinstance(derniere_facture, date) else date.today())

    scenarios_a_calculer = ([scenario_custom] if scenario_custom
                            else list(SCENARIOS.values()))
    resultats: List[Dict[str, Any]] = []

    for sc in scenarios_a_calculer:
        # Encours estimé : factures dont l'échéance + retard simulé dépasse `ref`
        # → elles seraient encore impayées à la date d'observation.
        limite = ref - timedelta(days=sc.retard_moyen_jours)
        row = con.execute(f"""
            SELECT sum(ttc) FILTER (WHERE echeance > DATE '{limite.isoformat()}'
                                      AND echeance <= DATE '{ref.isoformat()}') AS encours_retarde,
                   sum(ttc) FILTER (WHERE echeance > DATE '{ref.isoformat()}')   AS non_echu,
                   count(*) FILTER (WHERE echeance > DATE '{limite.isoformat()}'
                                      AND echeance <= DATE '{ref.isoformat()}') AS n_retarde
            FROM sales WHERE {W} AND echeance IS NOT NULL
        """).fetchone()

        # Part des factures effectivement en retard selon l'hypothèse
        encours_brut = float(row[0] or 0)
        encours_estime = encours_brut * (sc.part_en_retard_pct / 100.0)
        non_echu = float(row[1] or 0)
        n_retarde = int(round((row[2] or 0) * sc.part_en_retard_pct / 100.0))

        dso_sim = sc.dso_reel_estime(delai_moyen)
        resultats.append({
            "scenario": sc.nom,
            "hypothese": (f"{sc.retard_moyen_jours} j de retard sur "
                          f"{sc.part_en_retard_pct:.0f} % des factures"),
            "description": sc.description,
            "retard_moyen_jours": sc.retard_moyen_jours,
            "part_en_retard_pct": sc.part_en_retard_pct,
            "dso_accorde_jours": round(delai_moyen, 1),
            "dso_simule_jours": round(dso_sim, 1),
            "surcout_dso_jours": round(dso_sim - delai_moyen, 1),
            "encours_estime_dt": round(encours_estime, 0),
            "n_factures_estimees": n_retarde,
            "non_echu_dt": round(non_echu, 0),
        })

    con.close()

    # Sensibilité : écart entre le scénario le plus doux et le plus dur
    if len(resultats) > 1:
        dsos = [r["dso_simule_jours"] for r in resultats]
        encours = [r["encours_estime_dt"] for r in resultats]
        sensibilite = {
            "amplitude_dso_jours": round(max(dsos) - min(dsos), 1),
            "amplitude_encours_dt": round(max(encours) - min(encours), 0),
        }
    else:
        sensibilite = {}

    return {
        "date_observation": ref.isoformat() if isinstance(ref, date) else str(ref),
        "n_factures_avec_echeance": n_ech,
        "ca_avec_echeance_dt": round(ca_ech, 0),
        "dso_accorde_jours": round(delai_moyen, 1),
        "scenarios": resultats,
        "sensibilite": sensibilite,
        "avertissement": AVERTISSEMENT,
        "donnees_manquantes": ["REG", "REGTYP", "MTR3", "ETAT", "SOLDEACOMPTE_DEV"],
    }


# ── CLI ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    res = compute_scenarios()
    if res.get("error"):
        print(res["error"])
        sys.exit(1)

    print("\n=== SCÉNARIOS D'ENCAISSEMENT ===")
    print(f"Périmètre : {res['n_factures_avec_echeance']:,} factures avec échéance "
          f"({res['ca_avec_echeance_dt']:,.0f} DT)".replace(",", " "))
    print(f"Observation au : {res['date_observation']}")
    print(f"Délai ACCORDÉ moyen (donnée réelle) : {res['dso_accorde_jours']} j\n")

    print(f"{'scénario':<12} {'hypothèse':<38} {'DSO simulé':>11} {'encours estimé':>16}")
    print("-" * 82)
    for s in res["scenarios"]:
        print(f"{s['scenario']:<12} {s['hypothese']:<38} "
              f"{s['dso_simule_jours']:>9} j "
              f"{s['encours_estime_dt']:>14,.0f} DT".replace(",", " "))

    if res["sensibilite"]:
        print(f"\nSensibilité : {res['sensibilite']['amplitude_dso_jours']} j d'écart de DSO, "
              f"{res['sensibilite']['amplitude_encours_dt']:,.0f} DT d'écart d'encours "
              "entre le scénario optimiste et le pessimiste.".replace(",", " "))
    print(f"\n⚠ {res['avertissement']}")
