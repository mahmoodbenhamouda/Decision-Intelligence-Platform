"""Prevision d'encaissements par CARNET D'ECHEANCES (methode des facteurs de developpement)."""

from __future__ import annotations

import json
from pathlib import Path
from statistics import median
from typing import Dict, List, Optional, Tuple

REPORTS = Path(__file__).resolve().parents[2] / "reports"
HORIZONS = (1, 2)
PART_MINIMALE_DELAI = 0.05
N_TEST_DEFAULT = 12
SEUIL_MULTIPLICATIF = 0.50


def _cle(annee: int, mois: int) -> int:
    """Index mensuel absolu, pour une arithmetique de mois sans piege."""
    return annee * 12 + (mois - 1)


def _libelle(k: int) -> str:
    a, m = divmod(k, 12)
    return f"{a:04d}-{m + 1:02d}"


def charger_factures(data_dir: Path | None = None) -> List[Tuple[int, int, float]]:
    """Rend (mois d'emission, mois d'echeance, TTC) pour les VENTES."""
    from ml_engine.analytics import kpi_engine
    con = kpi_engine._connect(data_dir)
    rows = con.execute("""
        SELECT year(date), month(date), year(echeance), month(echeance), ttc
        FROM sales
        WHERE date IS NOT NULL AND echeance IS NOT NULL AND NOT est_avoir
          AND year(echeance) BETWEEN 2016 AND 2035
          AND echeance >= date
    """).fetchall()
    con.close()
    return [(_cle(int(r[0]), int(r[1])), _cle(int(r[2]), int(r[3])), float(r[4] or 0))
            for r in rows]


def _acquis(factures, origine: int, cible: int) -> float:
    """Somme deja inscrite au carnet a l'origine, pour le mois cible."""
    return sum(t for em, ech, t in factures if ech == cible and em <= origine)


def _total(factures, cible: int) -> float:
    """Total finalement constate pour le mois cible."""
    return sum(t for em, ech, t in factures if ech == cible)


def _taux_maturite(factures, origine: int, h: int, debut: int) -> Optional[float]:
    """Part du total deja acquise h mois a l'avance, estimee sur le PASSE seul."""
    parts: List[float] = []
    for t_prime in range(debut, origine - h + 1):
        cible = t_prime + h
        tot = _total(factures, cible)
        if tot <= 0:
            continue
        parts.append(_acquis(factures, t_prime, cible) / tot)
    if len(parts) < 3:
        return None
    return median(parts)


def _reste_recent(factures, origine: int, h: int, debut: int,
                  k: int = 6) -> Optional[float]:
    """Part NON acquise, estimee sur les k origines passees les plus recentes."""
    vals: List[float] = []
    for t_prime in range(max(debut, origine - h - k + 1), origine - h + 1):
        cible = t_prime + h
        tot = _total(factures, cible)
        if tot <= 0:
            continue
        vals.append(tot - _acquis(factures, t_prime, cible))
    return median(vals) if vals else None


def _serie_observable(factures, origine: int, debut: int) -> Dict[int, float]:
    """Totaux mensuels CONNUS a l'origine, pour les baselines."""
    return {k: _total(factures, k) for k in range(debut, origine + 1)}


def _baselines(z: Dict[int, float], origine: int, h: int) -> Dict[str, float]:
    """References triviales, evaluees sur la MEME cible et les MEMES origines."""
    dispo = sorted(k for k in z if z[k] > 0)
    if not dispo:
        return {}
    out: Dict[str, float] = {"naif_dernier_mois": z[dispo[-1]]}
    cible_saison = origine + h - 12
    if cible_saison in z and z[cible_saison] > 0:
        out["naif_saisonnier_m12"] = z[cible_saison]
    trois = [z[k] for k in dispo[-3:]]
    out["moyenne_mobile_3m"] = sum(trois) / len(trois)
    six = [z[k] for k in dispo[-6:]]
    out["mediane_mobile_6m"] = median(six)
    return out


def prevoir(factures, origine: int, h: int,
            debut: int) -> Optional[Tuple[float, str, float]]:
    """Prevision pour `origine + h`."""
    taux = _taux_maturite(factures, origine, h, debut)
    acq = _acquis(factures, origine, origine + h)
    if taux is not None and taux >= SEUIL_MULTIPLICATIF:
        return acq / taux, "multiplicatif", taux
    reste = _reste_recent(factures, origine, h, debut)
    if reste is None:
        return None
    return acq + reste, "additif", (taux if taux is not None else 0.0)


def evaluer(n_test: int = N_TEST_DEFAULT,
            horizons=HORIZONS,
            data_dir: Path | None = None) -> Dict:
    factures = charger_factures(data_dir)
    if not factures:
        return {"erreur": "aucune facture"}

    echeances = sorted({ech for _, ech, _ in factures})
    emissions = sorted({em for em, _, _ in factures})
    debut = echeances[0]
    fin_donnees = max(emissions)

    fin_cible = fin_donnees - 1

    n_tot = len(factures)
    part_delai = {}
    for h in horizons:
        part_delai[h] = sum(1 for em, ech, _ in factures if ech - em >= h) / n_tot

    resultats: Dict[str, Dict] = {}
    for h in horizons:
        if part_delai[h] < PART_MINIMALE_DELAI:
            resultats[f"h{h}"] = {
                "refuse": True,
                "part_factures_delai_suffisant_pct": round(part_delai[h] * 100, 2),
                "motif": (
                    f"seules {part_delai[h] * 100:.2f} % des factures ont un délai "
                    f"≥ {h} mois : le carnet est structurellement aveugle à cet "
                    "horizon. Un chiffre obtenu ici reposerait sur quelques "
                    "factures atypiques, pas sur la méthode."),
            }
            continue
        origines = [t for t in range(debut, fin_cible - h + 1)][-n_test:]
        erreurs_pct, erreurs_abs, carres = [], [], []
        detail, methodes, taux_vus = [], [], []
        err_baselines: Dict[str, List[float]] = {}
        for t in origines:
            cible = t + h
            reel = _total(factures, cible)
            if reel <= 0:
                continue
            sortie = prevoir(factures, t, h, debut)
            if sortie is None:
                continue
            pred, methode, taux = sortie
            z = _serie_observable(factures, t, debut)
            for nom, valeur in _baselines(z, t, h).items():
                err_baselines.setdefault(nom, []).append(abs(valeur - reel) / reel)
            err = pred - reel
            erreurs_pct.append(abs(err) / reel)
            erreurs_abs.append(abs(err))
            carres.append(err * err)
            methodes.append(methode)
            taux_vus.append(taux)
            detail.append({"origine": _libelle(t), "cible": _libelle(cible),
                           "reel": round(reel, 2), "prevu": round(pred, 2),
                           "erreur_pct": round(abs(err) / reel * 100, 2),
                           "methode": methode,
                           "taux_maturite": round(taux, 4)})
        if not erreurs_pct:
            resultats[f"h{h}"] = {"erreur": "aucune origine exploitable"}
            continue
        n = len(erreurs_pct)
        resultats[f"h{h}"] = {
            "n_origines": n,
            "mape_pct": round(sum(erreurs_pct) / n * 100, 2),
            "mae_dt": round(sum(erreurs_abs) / n, 2),
            "rmse_dt": round((sum(carres) / n) ** 0.5, 2),
            "taux_maturite_median": round(median(taux_vus), 4),
            "regime": max(set(methodes), key=methodes.count),
            "baselines_mape_pct": {
                nom: round(sum(v) / len(v) * 100, 2)
                for nom, v in sorted(err_baselines.items())
            },
            "detail": detail,
        }
        b = resultats[f"h{h}"]["baselines_mape_pct"]
        if b:
            meilleure = min(b, key=b.get)
            resultats[f"h{h}"]["meilleure_baseline"] = meilleure
            resultats[f"h{h}"]["gain_vs_baseline_pts"] = round(
                b[meilleure] - resultats[f"h{h}"]["mape_pct"], 2)
    return {
        "methode": "carnet d'échéances (facteurs de développement)",
        "principe": "encaissement = acquis au carnet / taux de maturité ; "
                    "seule la part non encore facturée est estimée",
        "n_factures": len(factures),
        "periode_echeances": f"{_libelle(debut)} → {_libelle(fin_cible)}",
        "horizons": resultats,
    }


def rapport_console(res: Dict) -> str:
    if "erreur" in res:
        return f"[carnet] {res['erreur']}"
    lignes = ["", "=== Prévision par CARNET D'ÉCHÉANCES (walk-forward) ===",
              f"    {res['n_factures']:,} factures · échéances {res['periode_echeances']}"
              .replace(",", " "), ""]
    lignes.append(f"    {'horizon':<9}{'MAPE':>8}{'MAE (DT)':>14}"
                  f"{'RMSE (DT)':>14}{'maturité':>10}{'régime':>15}{'n':>4}")
    for cle, m in res["horizons"].items():
        if m.get("refuse"):
            lignes.append(f"    {cle:<9}HORIZON REFUSÉ — "
                          f"{m['part_factures_delai_suffisant_pct']:.2f} % des "
                          "factures seulement atteignent ce délai")
            continue
        if "erreur" in m:
            lignes.append(f"    {cle:<9}{m['erreur']}")
            continue
        lignes.append(
            f"    {cle:<9}{m['mape_pct']:>7.1f}%{m['mae_dt']:>14,.0f}"
            f"{m['rmse_dt']:>14,.0f}{m['taux_maturite_median']:>10.1%}"
            f"{m['regime']:>15}{m['n_origines']:>4}".replace(",", " "))
    lignes += ["", "    Références évaluées sur la MÊME cible et les MÊMES origines :"]
    for cle, m in res["horizons"].items():
        if "erreur" in m or m.get("refuse"):
            continue
        lignes.append(f"      {cle} —")
        for nom, val in m.get("baselines_mape_pct", {}).items():
            marque = "  ← meilleure" if nom == m.get("meilleure_baseline") else ""
            lignes.append(f"        {nom:<24}{val:>7.1f}%{marque}")
        gain = m.get("gain_vs_baseline_pts")
        if gain is not None:
            verdict = ("le carnet apporte un gain réel"
                       if gain > 1 else
                       "AUCUN GAIN : le carnet n'apporte rien à cet horizon")
            lignes.append(f"        → gain du carnet : {gain:+.1f} pts — {verdict}")
    lignes += [
        "",
        "    LECTURE. Le taux de maturité est la part du mois déjà inscrite au",
        "    carnet à l'origine. À h=1 il frôle 100 % : les encaissements du mois",
        "    suivant ne sont pas à prévoir, ils sont à LIRE. Le résidu correspond",
        "    aux ventes au comptant émises dans le mois même.",
        "",
        "    L'HORIZON EST BORNÉ PAR LES CONDITIONS DE PAIEMENT. 99,0 % des",
        "    factures ont un délai de 0 à 2 mois ; seules 0,98 % atteignent 3 mois.",
        "    Le carnet ne peut donc RIEN voir au-delà de deux mois — ce n'est pas",
        "    une limite de la méthode mais une propriété du métier. Les horizons",
        "    non soutenus sont refusés explicitement plutôt que servis.",
        "",
        "    PORTÉE. Cette cible est un ÉCHÉANCIER CONTRACTUEL, pas de la",
        "    trésorerie encaissée : aucune date de paiement n'est enregistrée",
        "    réelle. Ce module dit quand les créances deviennent exigibles, pas",
        "    quand le client paiera.",
    ]
    return "\n".join(lignes)


def main() -> int:
    res = evaluer()
    print(rapport_console(res))
    REPORTS.mkdir(exist_ok=True)
    sortie = REPORTS / "cashflow_carnet_metrics.json"
    sortie.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n    → {sortie}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
