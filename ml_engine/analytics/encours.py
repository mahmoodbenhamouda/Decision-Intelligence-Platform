"""« Qui me doit de l'argent ?"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from config.settings import settings
    BASE = Path(settings.base_dir)
except Exception:  # pragma: no cover
    BASE = Path(__file__).resolve().parents[2]

REPORTS_DIR = BASE / "reports"

FENETRE_MOIS = 18

SILENCE_JOURS = 90


def calculer(data_dir: Optional[Path] = None) -> Dict[str, Any]:
    from ml_engine.analytics.kpi_engine import _connect

    con = _connect(data_dir)
    try:
        ref_ech, ref_act = con.execute("""
            SELECT max(echeance), max(date) FROM sales
            WHERE echeance IS NOT NULL AND date IS NOT NULL
        """).fetchone()
        if ref_ech is None or ref_act is None:
            return {"error": "aucune échéance exploitable"}
        ref = ref_ech

        lignes = con.execute(f"""
            WITH ref AS (SELECT DATE '{ref_ech}' AS d, DATE '{ref_act}' AS a),
            -- Dernière commande de chaque client : sert à savoir s'il est encore
            -- actif après l'échéance de ses factures.
            activite AS (
                SELECT client, max(date) AS derniere_commande
                FROM sales WHERE NOT est_avoir AND date IS NOT NULL
                GROUP BY client
            ),
            echues AS (
                SELECT s.client,
                       any_value(s.client_name)                       AS nom,
                       sum(s.ttc)                                     AS montant_echu,
                       count(*)                                       AS n_factures,
                       min(s.echeance)                                AS plus_ancienne,
                       max(s.echeance)                                AS plus_recente,
                       sum(s.ttc) FILTER (
                           WHERE s.echeance < (SELECT d FROM ref) - INTERVAL 90 DAY
                       )                                             AS montant_90j
                FROM sales s
                WHERE NOT s.est_avoir
                  AND s.echeance IS NOT NULL
                  AND s.echeance < (SELECT d FROM ref)
                  AND s.echeance >= (SELECT d FROM ref) - INTERVAL {FENETRE_MOIS} MONTH
                  AND s.client_name IS NOT NULL
                  AND s.client_name NOT ILIKE '%passager%'
                  AND s.client_name NOT ILIKE '%comptant%'
                GROUP BY s.client
            )
            SELECT e.client, e.nom, e.montant_echu, e.n_factures,
                   e.plus_ancienne, e.montant_90j,
                   a.derniere_commande,
                   -- Silence mesuré depuis la dernière facture ÉMISE, non depuis
                   -- la dernière échéance : sinon tout client paraît inactif.
                   datediff('day', a.derniere_commande, (SELECT a FROM ref)) AS silence_j,
                   datediff('day', e.plus_ancienne, (SELECT d FROM ref))     AS anciennete_j
            FROM echues e
            LEFT JOIN activite a ON a.client = e.client
            WHERE e.montant_echu > 0
            ORDER BY e.montant_echu DESC
        """).fetchall()
    finally:
        con.close()

    if not lignes:
        return {"error": "aucune facture échue sur la fenêtre analysée"}

    clients: List[Dict[str, Any]] = []
    for (code, nom, montant, n, plus_anc, m90, derniere, silence, anc) in lignes:
        silence = int(silence or 0)
        actif = silence <= SILENCE_JOURS

        if not actif and float(m90 or 0) > 0:
            situation = "a_verifier_en_priorite"
            lecture = ("factures échues depuis plus de 90 jours ET client sans "
                       "commande récente — les deux signaux se cumulent")
        elif not actif:
            situation = "a_verifier"
            lecture = "client sans commande récente malgré des factures échues"
        else:
            situation = "probablement_regle"
            lecture = ("le client continue de commander : une ligne de crédit "
                       "ouverte suppose des règlements")

        clients.append({
            "code": code, "nom": nom,
            "montant_echu_dt": round(float(montant or 0), 0),
            "montant_echu_90j_dt": round(float(m90 or 0), 0),
            "n_factures": int(n or 0),
            "plus_ancienne_echeance": str(plus_anc),
            "anciennete_max_jours": int(anc or 0),
            "derniere_commande": str(derniere) if derniere else None,
            "silence_jours": silence,
            "client_encore_actif": actif,
            "situation": situation,
            "lecture": lecture,
        })

    a_verifier = [c for c in clients if not c["client_encore_actif"]]
    prioritaires = [c for c in clients
                    if c["situation"] == "a_verifier_en_priorite"]
    total = sum(c["montant_echu_dt"] for c in clients)
    total_verif = sum(c["montant_echu_dt"] for c in a_verifier)

    metriques = {
        "version": 1,
        "date_reference_echeances": str(ref_ech),
        "date_reference_activite": str(ref_act),
        "pourquoi_deux_dates": (
            "La dernière échéance connue est postérieure de plusieurs mois à la "
            "dernière facture émise — une facture d'avril échoit en septembre. "
            "Mesurer le silence d'un client depuis la dernière échéance ajoutait "
            "donc ce décalage à tous, et 100 % des clients paraissaient inactifs."),
        "fenetre_mois": FENETRE_MOIS,
        "ce_que_ce_chiffre_est": (
            "Somme des factures dont l'échéance CONTRACTUELLE est dépassée à la "
            "date de référence. C'est ce qui aurait dû être encaissé, non ce qui "
            "reste dû : aucune date de règlement n'est enregistrée."),
        "ce_que_ce_chiffre_n_est_pas": (
            "Ce n'est PAS un montant d'impayés. Une grande partie de ces factures "
            "a certainement été réglée — nous ne pouvons simplement pas le "
            "vérifier dans les données disponibles."),
        "pourquoi_18_mois": (
            "Au-delà, une facture échue a vraisemblablement été réglée ou passée "
            "en perte. Cumuler tout l'historique produirait un montant sans "
            "rapport avec la situation du moment."),

        "montant_echu_total_dt": round(total, 0),
        "n_clients": len(clients),

        "a_verifier": {
            "n_clients": len(a_verifier),
            "montant_dt": round(total_verif, 0),
            "part_du_total_pct": round(total_verif / total * 100, 1) if total else 0,
            "critere": (
                f"factures échues ET aucune commande depuis plus de {SILENCE_JOURS} "
                "jours. Un client qui continue d'acheter règle probablement ses "
                "factures : aucune entreprise ne maintient une ligne de crédit "
                "ouverte à un mauvais payeur."),
            "statut_de_cette_inference": (
                "INFÉRENCE, non preuve. Elle ne démontre pas un impayé : elle "
                "désigne les comptes dont la vérification est la plus rentable."),
        },

        "priorite_absolue": {
            "n_clients": len(prioritaires),
            "montant_dt": round(sum(c["montant_echu_dt"] for c in prioritaires), 0),
            "critere": "échéance dépassée de plus de 90 jours ET client silencieux",
        },

        "clients_a_verifier": sorted(
            a_verifier, key=lambda c: -c["montant_echu_dt"])[:60],
        "plus_gros_echus_tous_statuts": clients[:20],
        "action_recommandee": (
            "Confronter la liste « à vérifier » aux relevés bancaires. C'est une "
            "poignée de comptes, pas des milliers de factures — et si la donnée "
            "de règlement était exportée, ce module donnerait une réponse "
            "définitive au lieu d'une inférence."),
    }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json.dump(metriques, open(REPORTS_DIR / "encours_metrics.json", "w",
                              encoding="utf-8"), indent=2, ensure_ascii=False)
    return metriques


def afficher() -> None:
    m = calculer()
    if m.get("error"):
        print(f"\nErreur : {m['error']}\n")
        return

    def dt(v: float) -> str:
        return f"{v:,.0f} DT".replace(",", " ")

    print("\n" + "=" * 78)
    print(f"  ENCOURS CONTRACTUEL — échéances au {m['date_reference_echeances']}")
    print(f"  (activité clients mesurée au {m['date_reference_activite']})")
    print("=" * 78)
    print(f"\n  {m['ce_que_ce_chiffre_est']}")
    print(f"\n  ⚠ {m['ce_que_ce_chiffre_n_est_pas']}")

    print(f"\n  Échéances dépassées ({m['fenetre_mois']} derniers mois) :")
    print(f"    {dt(m['montant_echu_total_dt']):>20}   sur {m['n_clients']} clients")

    av = m["a_verifier"]
    print(f"\n  À VÉRIFIER — client sans commande récente :")
    print(f"    {dt(av['montant_dt']):>20}   sur {av['n_clients']} clients "
          f"({av['part_du_total_pct']} % du total)")

    pr = m["priorite_absolue"]
    print(f"\n  PRIORITÉ — échu > 90 j ET silencieux :")
    print(f"    {dt(pr['montant_dt']):>20}   sur {pr['n_clients']} clients")

    cibles = m.get("clients_a_verifier") or []
    if cibles:
        print(f"\n  Comptes à confronter aux relevés bancaires "
              f"({len(cibles)} affichés sur {av['n_clients']}) :")
        print(f"  {'client':<40}{'échu':>14}{'silence':>11}")
        for c in cibles[:15]:
            print(f"  {(c['nom'] or c['code'])[:38]:<40}"
                  f"{dt(c['montant_echu_dt']):>14}{c['silence_jours']:>8} j")
        if len(cibles) > 15:
            reste = sum(c["montant_echu_dt"] for c in cibles[15:])
            print(f"  {'… et ' + str(len(cibles) - 15) + ' autres comptes':<40}"
                  f"{dt(reste):>14}")

    print(f"\n  {m['action_recommandee']}")
    print("=" * 78 + "\n")


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    afficher()
