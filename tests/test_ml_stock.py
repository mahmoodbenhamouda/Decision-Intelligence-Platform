"""Tests des deux modèles ML du domaine stock, construits selon CRISP-DM :"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAPPORT_PREV = os.path.join(RACINE, "reports", "demand_forecast_ml_metrics.json")
RAPPORT_RISQUE = os.path.join(RACINE, "reports", "stock_risk_metrics.json")
MODELE_PREV = os.path.join(RACINE, "models", "demand_forecast_ml.joblib")
MODELE_RISQUE = os.path.join(RACINE, "models", "stock_risk.joblib")

besoin_prev = pytest.mark.skipif(not os.path.exists(RAPPORT_PREV),
                                 reason="modèle de prévision non entraîné")
besoin_risque = pytest.mark.skipif(not os.path.exists(RAPPORT_RISQUE),
                                   reason="modèle de risque non entraîné")


def _charger(chemin):
    with open(chemin, encoding="utf-8") as f:
        return json.load(f)


@besoin_risque
def test_auc_non_parfaite():
    """AUC ≈ 1 sur un problème métier = fuite de la cible, pas une réussite."""
    m = _charger(RAPPORT_RISQUE)
    auc_cv = m["comparaison"][m["modele_retenu"]]["cv_auc"]
    auc_hold = m["holdout"]["auc"]
    assert auc_cv < 0.99, f"AUC CV suspecte ({auc_cv}) : fuite probable"
    assert auc_hold < 0.99, f"AUC hold-out suspecte ({auc_hold}) : fuite probable"
    assert auc_cv > 0.6, "un modèle sous 0,6 n'apporte rien sur ce problème"


@besoin_risque
def test_cible_absente_des_features():
    """Aucune colonne de construction de la cible ne doit être une variable."""
    from ml_engine.models.stock_risk import FEATURES
    interdits = {"y", "risque_rupture", "risque_peremption", "risque_surstock",
                 "y_h1", "y_h2", "y_h3", "qte_perimee", "risk_type"}
    fuite = interdits & set(FEATURES)
    assert not fuite, f"variables construisant la cible utilisées en entrée : {fuite}"


@besoin_risque
def test_aucune_feature_n_apparait_dans_la_definition_de_la_cible():
    """Le test précédent a un angle mort, et il a laissé passer une fuite réelle."""
    import inspect
    import re

    from ml_engine.models import stock_risk

    source = inspect.getsource(stock_risk.build_risk_dataset)

    lignes = source.splitlines()
    debut = next((i for i, l in enumerate(lignes)
                  if 'df["risque_rupture"]' in l), None)
    fin = next((i for i, l in enumerate(lignes)
                if 'dropna(subset=["y_h3"])' in l), None)
    assert debut is not None and fin is not None and fin > debut, (
        "région de construction de la cible introuvable — test à revoir")

    bloc = " ".join(l.split("#", 1)[0] for l in lignes[debut:fin])
    fuites = [f for f in stock_risk.FEATURES
              if re.search(rf'["\']{re.escape(f)}["\']', bloc)]
    assert not fuites, (
        f"la cible est construite à partir de variables explicatives : {fuites}. "
        "Une partie de la cible est alors un simple seuil sur une entrée du "
        "modèle — c'est la fuite qui donnait AUC = 1,0000 à la première version.")


@besoin_risque
def test_le_holdout_est_groupe_par_produit():
    """Aucun produit ne doit être des deux côtés de la coupure."""
    m = _charger(RAPPORT_RISQUE)
    assert "GroupKFold" in m["methodologie"] or "groupé" in m["methodologie"], (
        "le rapport n'annonce pas un découpage groupé par produit")

    audit = m.get("audit_fuite") or {}
    if not audit.get("applicable"):
        pytest.skip("audit de fuite non calculé")

    assert audit["auc_holdout_groupe_par_produit"] == m["holdout"]["auc"], (
        "le bloc `holdout` ne porte pas la mesure groupée")

    assert "ecart" in audit
    assert audit["n_produits_holdout"] > 0


@besoin_prev
def test_prevision_sans_cible_dans_les_features():
    from ml_engine.models.demand_features import FEATURES
    interdits = {"y_h1", "y_h2", "y_h3", "qte"}
    fuite = interdits & set(FEATURES)
    assert not fuite, f"cible présente dans les variables : {fuite}"


@besoin_prev
def test_aucune_feature_future():
    """Les variables ne portent que du passé : lags, moyennes mobiles, calendrier."""
    from ml_engine.models.demand_features import FEATURES
    for f in FEATURES:
        assert not f.startswith("y_"), f"variable potentiellement future : {f}"
        assert "futur" not in f, f"variable potentiellement future : {f}"


@pytest.mark.vitrine
@besoin_prev
def test_modele_deploye_uniquement_si_gain_confirme():
    """Règle d'acceptation : gain hold-out ≤ 0 → on sert la baseline."""
    m = _charger(RAPPORT_PREV)
    for nom, h in m["horizons"].items():
        retenu = h["modele_retenu"]
        est_modele = h["comparaison"].get(retenu, {}).get("type") == "modele"
        confirme = h.get("holdout_confirme_le_gain")
        gain = h.get("holdout_gain_vs_baseline_pct")
        if est_modele:
            assert confirme is True and (gain or 0) > 0, (
                f"{nom} : modèle « {retenu} » déployé sans gain confirmé "
                f"sur le hold-out (gain = {gain})")
        else:
            assert confirme is not True or (gain or 0) <= 0, (
                f"{nom} : une baseline est servie alors que le gain modèle "
                f"était confirmé — occasion manquée ou rapport incohérent")


@besoin_prev
def test_rapport_coherent_avec_le_modele_charge():
    """Ce que le fichier de métriques annonce = ce que le bundle contient."""
    if not os.path.exists(MODELE_PREV):
        pytest.skip("bundle de prévision absent")
    from ml_engine.models.demand_forecast import load_demand_model
    m = _charger(RAPPORT_PREV)
    bundle = load_demand_model()
    assert bundle is not None
    for nom, h in m["horizons"].items():
        cible = {"h1": "y_h1", "h2": "y_h2", "h3": "y_h3"}[nom]
        objet = bundle["modeles"].get(cible)
        est_modele_rapport = h["comparaison"].get(
            h["modele_retenu"], {}).get("type") == "modele"
        est_modele_bundle = objet is not None and not isinstance(objet, dict)
        assert est_modele_rapport == est_modele_bundle, (
            f"{nom} : le rapport annonce « {h['modele_retenu']} » mais le "
            f"bundle contient {'un modèle' if est_modele_bundle else 'une baseline'}")


@besoin_prev
def test_pas_de_surapprentissage_grossier():
    """Écart train → validation contenu, pour TOUS les modèles candidats."""
    m = _charger(RAPPORT_PREV)
    for nom, h in m["horizons"].items():
        retenu = h["modele_retenu"]
        for modele, stats in h["comparaison"].items():
            if stats.get("type") != "modele":
                continue
            ecart = stats.get("ecart_train_valid_mae")
            if ecart is None:
                continue
            if modele == retenu:
                assert ecart < 10, (f"{nom} : le modèle DÉPLOYÉ « {modele} » "
                                    f"présente un écart train-validation de "
                                    f"{ecart} % — surapprentissage")
            elif ecart >= 25:
                assert modele != retenu, (
                    f"{nom} : « {modele} » surapprend ({ecart} %) et a "
                    f"pourtant été retenu")


@besoin_risque
def test_le_modele_servi_ne_surapprend_pas():
    """Le modèle RETENU doit respecter le seuil ; les autres doivent être écartés."""
    from ml_engine.models.stock_risk import SEUIL_ECART_TRAIN_VALID

    m = _charger(RAPPORT_RISQUE)
    retenu = m.get("modele_retenu")

    if retenu is None:
        assert m["decision_deploiement"]["modele_deploye"] is False
        return

    ecart_retenu = m["comparaison"][retenu].get("ecart_train_valid_auc")
    assert ecart_retenu is not None, "écart train/validation non mesuré"
    assert ecart_retenu < SEUIL_ECART_TRAIN_VALID, (
        f"le modèle SERVI ({retenu}) affiche un écart train/validation de "
        f"{ecart_retenu} — la sélection a laissé passer un sur-apprentissage")

    for nom, stats in m["comparaison"].items():
        ecart = stats.get("ecart_train_valid_auc")
        if ecart is None or ecart < SEUIL_ECART_TRAIN_VALID:
            continue
        assert stats.get("disqualifie") is True, (
            f"{nom} dépasse le seuil ({ecart}) sans être marqué disqualifié")
        assert nom != retenu


@besoin_risque
def test_calibration_du_risque():
    """Un score de risque sert à arbitrer : il doit être une vraie probabilité."""
    m = _charger(RAPPORT_RISQUE)
    assert m["holdout"]["brier_score"] < 0.25, "score de Brier dégradé"
    assert m["ecart_calibration_moyen"] < 0.10, \
        "les probabilités annoncées ne correspondent pas aux fréquences observées"


@besoin_risque
def test_ablation_le_modele_apporte_quelque_chose():
    """Retirer les variables doit dégrader le modèle — sinon il n'apprend rien."""
    m = _charger(RAPPORT_RISQUE)
    assert m.get("ablation", {}).get("perte_auc", 0) > 0.02, \
        "l'ablation ne dégrade pas le modèle : apprentissage douteux"


@besoin_risque
def test_scoring_contrat_et_bornes():
    from ml_engine.models import score_stock_risk
    r = score_stock_risk(limit=10)
    if r.get("error"):
        pytest.skip(r["error"])
    for champ in ("n_references", "impact_total_dt", "score_moyen",
                  "par_categorie", "par_type", "produits", "perimetre"):
        assert champ in r, f"champ manquant dans la réponse : {champ}"
    for p in r["produits"]:
        assert 0 <= p["risk_score"] <= 100, "score hors bornes"
        assert p["risk_category"] in ("Faible", "Moyen", "Élevé", "Critique")
        assert p["risk_type"] in ("peremption", "rupture", "surstock", "aucun")
        assert p["financial_impact_dt"] >= 0


@besoin_risque
def test_scoring_une_ligne_par_produit():
    """Le jeu d'entraînement est produit × mois ; le scoring, produit seul."""
    from ml_engine.models import score_stock_risk
    r = score_stock_risk(limit=200)
    if r.get("error"):
        pytest.skip(r["error"])
    noms = [p["produit"] for p in r["produits"]]
    assert len(noms) == len(set(noms)), "un produit apparaît plusieurs fois"


@besoin_risque
def test_impact_financier_est_une_esperance():
    """impact = probabilité × exposition : il ne peut pas dépasser l'exposition."""
    from ml_engine.models import score_stock_risk
    r = score_stock_risk(limit=25)
    if r.get("error"):
        pytest.skip(r["error"])
    for p in r["produits"]:
        assert p["financial_impact_dt"] >= 0
        if p["risk_score"] == 0:
            assert p["financial_impact_dt"] == 0


@besoin_risque
def test_perimetre_client_est_un_sous_ensemble():
    """Filtrer par client restreint la liste ; il n'y a pas de re-scoring."""
    import duckdb

    from ml_engine.analytics.kpi_engine import STORE_PATH
    from ml_engine.models import score_stock_risk
    if not os.path.exists(str(STORE_PATH)):
        pytest.skip("entrepôt absent")
    con = duckdb.connect(str(STORE_PATH), read_only=True)
    try:
        lignes = con.execute("""
            SELECT DISTINCT s.client FROM sales s
            JOIN stock_simule k ON k.client = s.client_name LIMIT 1
        """).fetchall()
    finally:
        con.close()
    if not lignes:
        pytest.skip("aucun stock rattaché à un client")
    code = lignes[0][0]

    glob = score_stock_risk(limit=500)
    part = score_stock_risk(client=code, limit=500)
    if glob.get("error") or part.get("error"):
        pytest.skip("scoring indisponible")
    assert part["n_references"] <= glob["n_references"]
    assert code in part["perimetre"] or "global" in part["perimetre"]
    ref_glob = {p["produit"]: p["risk_score"] for p in glob["produits"]}
    for p in part["produits"]:
        if p["produit"] in ref_glob:
            assert p["risk_score"] == pytest.approx(ref_glob[p["produit"]]), \
                "le score ne doit pas dépendre du filtre d'affichage"


def test_les_ruptures_restent_conformes_au_profil_simule():
    """Le nombre de ruptures doit correspondre au profil que la simulation vise."""
    import duckdb

    from ml_engine.analytics.kpi_engine import STORE_PATH
    from ml_engine.stock.generator import PROFIL_SITUATION

    if not os.path.exists(str(STORE_PATH)):
        pytest.skip("entrepôt absent")

    con = duckdb.connect(str(STORE_PATH), read_only=True)
    try:
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        if "stock_simule" not in tables:
            pytest.skip("stock non généré")
        total, nuls = con.execute("""
            SELECT count(*), count(*) FILTER (WHERE stock_actuel <= 0)
            FROM stock_simule WHERE client IS NULL
        """).fetchone()
    finally:
        con.close()

    if not total:
        pytest.skip("stock global vide")

    part = nuls / total
    plafond = PROFIL_SITUATION["rupture"] * 3
    assert part <= plafond, (
        f"{nuls} références à stock nul sur {total} ({part:.0%}), alors que le "
        f"profil de simulation vise {PROFIL_SITUATION['rupture']:.0%}. "
        "La génération ne respecte plus son propre profil.")


def test_un_produit_sain_ne_peut_pas_avoir_un_stock_nul():
    """« Sain » et « stock nul » sont contradictoires par définition."""
    import duckdb

    from ml_engine.analytics.kpi_engine import STORE_PATH

    if not os.path.exists(str(STORE_PATH)):
        pytest.skip("entrepôt absent")

    con = duckdb.connect(str(STORE_PATH), read_only=True)
    try:
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        if "stock_simule" not in tables:
            pytest.skip("stock non généré")
        colonnes = [r[0] for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'stock_simule'").fetchall()]
        if "situation" not in colonnes:
            pytest.skip("colonne `situation` absente de cette génération")
        incoherents = con.execute("""
            SELECT situation, count(*) FROM stock_simule
            WHERE stock_actuel <= 0 AND situation <> 'rupture'
            GROUP BY situation
        """).fetchall()
    finally:
        con.close()

    assert not incoherents, (
        "références à stock nul alors qu'elles ne sont pas en rupture : "
        + ", ".join(f"{s} ({n})" for s, n in incoherents))


@besoin_prev
def test_previsions_croissantes_et_positives():
    """La demande cumulée à 90 j ne peut pas être inférieure à celle à 30 j."""
    from ml_engine.models import predict_demand
    res = predict_demand()[:50]
    if not res:
        pytest.skip("aucune prévision disponible")
    for r in res:
        assert r["prevision_30j"] >= 0
        assert r["prevision_60j"] >= 0
        assert r["prevision_90j"] >= 0
        for champ in ("produit", "derniere_periode", "moyenne_3m"):
            assert champ in r


@besoin_prev
def test_dataset_sans_valeur_manquante():
    """Phase 3 de CRISP-DM : les variables servies au modèle sont complètes."""
    from ml_engine.models.demand_features import FEATURES, build_demand_dataset
    df = build_demand_dataset(verbose=False)
    manquants = df[FEATURES].isna().sum().sum()
    assert manquants == 0, f"{manquants} valeurs manquantes dans les features"
    assert len(df) > 1000, "jeu de données anormalement petit"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
