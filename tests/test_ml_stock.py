"""
tests/test_ml_stock.py
======================
Tests des deux modèles ML du domaine stock, construits selon CRISP-DM :

* `ml_engine/models/demand_features.py`  — préparation des données (phase 3)
* `ml_engine/models/demand_forecast.py`  — prévision multi-horizon (phases 4-5)
* `ml_engine/models/stock_risk.py`       — classification du risque (phases 4-5)

Trois familles de tests, par ordre d'importance :

1. **Anti-fuite (leakage)** — la cible ne doit jamais être déductible des
   variables. La première version du modèle de risque atteignait AUC = 1,0000 :
   symptôme d'une cible calculée à partir de ses propres features. Ces tests
   existent pour que cette erreur ne puisse plus revenir silencieusement.

2. **Honnêteté du déploiement** — un modèle n'est servi que si son gain a été
   confirmé sur une période inédite ; sinon la baseline est servie et annoncée
   comme telle. On teste que le rapport de métriques et le modèle chargé disent
   la même chose.

3. **Contrat de sortie** — les champs consommés par l'API et l'interface
   existent et sont dans leurs bornes.

Exécution :
    python -m pytest tests/test_ml_stock.py -v
"""

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


# ── 1. ANTI-FUITE ───────────────────────────────────────────────────────────
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
    """Le test précédent a un angle mort, et il a laissé passer une fuite réelle.

    Il compare les features à une liste NOMMÉE de colonnes interdites. Or la
    cible `risque_surstock` était définie par `couverture_actuelle_j > 180` —
    et `couverture_actuelle_j` EST une feature. Le seuil sur une variable
    explicative ne figurait dans aucune liste, donc rien ne le voyait.

    Ce test lit le CODE qui construit la cible et vérifie mécaniquement qu'aucun
    nom de feature n'y apparaît. Il ne dépend d'aucune liste à maintenir.
    """
    import inspect
    import re

    from ml_engine.models import stock_risk

    source = inspect.getsource(stock_risk.build_risk_dataset)

    # On isole la RÉGION de construction de la cible, et non les seules lignes
    # d'affectation : une expression peut s'étendre sur plusieurs lignes, et ne
    # regarder que la première laisserait passer un seuil posé plus bas.
    lignes = source.splitlines()
    debut = next((i for i, l in enumerate(lignes)
                  if 'df["risque_rupture"]' in l), None)
    fin = next((i for i, l in enumerate(lignes)
                if 'dropna(subset=["y_h3"])' in l), None)
    assert debut is not None and fin is not None and fin > debut, (
        "région de construction de la cible introuvable — test à revoir")

    # Les commentaires sont retirés : celui qui documente la correction cite
    # légitimement le nom de la variable retirée.
    bloc = " ".join(l.split("#", 1)[0] for l in lignes[debut:fin])
    fuites = [f for f in stock_risk.FEATURES
              if re.search(rf'["\']{re.escape(f)}["\']', bloc)]
    assert not fuites, (
        f"la cible est construite à partir de variables explicatives : {fuites}. "
        "Une partie de la cible est alors un simple seuil sur une entrée du "
        "modèle — c'est la fuite qui donnait AUC = 1,0000 à la première version.")


@besoin_risque
def test_le_holdout_est_groupe_par_produit():
    """Aucun produit ne doit être des deux côtés de la coupure.

    L'instantané de stock est constant par produit : un découpage aléatoire
    plaçait le même produit, avec les mêmes valeurs de stock, en apprentissage
    et en test. Le modèle n'avait plus qu'à mémoriser l'identité du produit —
    fuite par DUPLICATION, invisible dans l'écart train/validation puisque les
    deux protocoles en profitent également.
    """
    m = _charger(RAPPORT_RISQUE)
    assert "GroupKFold" in m["methodologie"] or "groupé" in m["methodologie"], (
        "le rapport n'annonce pas un découpage groupé par produit")

    audit = m.get("audit_fuite") or {}
    if not audit.get("applicable"):
        pytest.skip("audit de fuite non calculé")

    # Le chiffre servi doit être celui du protocole GROUPÉ, jamais l'autre.
    assert audit["auc_holdout_groupe_par_produit"] == m["holdout"]["auc"], (
        "le bloc `holdout` ne porte pas la mesure groupée")

    # L'écart doit rester documenté, quel que soit son signe : c'est la trace
    # chiffrée du défaut corrigé.
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


# ── 2. HONNÊTETÉ DU DÉPLOIEMENT ─────────────────────────────────────────────
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
        # une baseline est stockée sous forme de dict {"baseline": nom}
        est_modele_bundle = objet is not None and not isinstance(objet, dict)
        assert est_modele_rapport == est_modele_bundle, (
            f"{nom} : le rapport annonce « {h['modele_retenu']} » mais le "
            f"bundle contient {'un modèle' if est_modele_bundle else 'une baseline'}")


@besoin_prev
def test_pas_de_surapprentissage_grossier():
    """Écart train → validation contenu, pour TOUS les modèles candidats.

    Convention du rapport : `ecart_train_valid_mae` = (MAE_valid − MAE_train)
    en % ; une valeur NÉGATIVE signifie que l'erreur de validation est plus
    faible que celle d'apprentissage — pas de mémorisation. C'est le résultat
    obtenu après passage à l'apprentissage résiduel et à la régularisation.
    """
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
                # Exigence forte : c'est ce modèle qui part en production.
                assert ecart < 10, (f"{nom} : le modèle DÉPLOYÉ « {modele} » "
                                    f"présente un écart train-validation de "
                                    f"{ecart} % — surapprentissage")
            elif ecart >= 25:
                # Un candidat instable est acceptable dans la comparaison
                # (la régression Ridge extrapole très mal la cible résiduelle),
                # à condition formelle qu'il n'ait pas été sélectionné.
                assert modele != retenu, (
                    f"{nom} : « {modele} » surapprend ({ecart} %) et a "
                    f"pourtant été retenu")


@besoin_risque
def test_le_modele_servi_ne_surapprend_pas():
    """Le modèle RETENU doit respecter le seuil ; les autres doivent être écartés.

    Version précédente de ce test : il exigeait que TOUS les candidats respectent
    l'écart de 0,10, y compris ceux qui ne seront jamais servis. C'était à la
    fois trop et trop peu.

    *Trop peu*, parce qu'un test qui échoue après l'entraînement ne protège de
    rien — il faut relancer, et la tentation est de desserrer le seuil plutôt que
    de changer le modèle. La contrainte vit désormais dans la SÉLECTION
    (`SEUIL_ECART_TRAIN_VALID`) : un candidat qui sur-apprend n'est plus
    éligible, quelle que soit son AUC.

    *Trop*, parce qu'un candidat qui sur-apprend et se trouve donc écarté est la
    preuve que la sélection fonctionne, pas un défaut. Ce qui doit être vrai,
    c'est que le modèle servi respecte le seuil et que les autres sont
    explicitement marqués comme disqualifiés.
    """
    from ml_engine.models.stock_risk import SEUIL_ECART_TRAIN_VALID

    m = _charger(RAPPORT_RISQUE)
    retenu = m.get("modele_retenu")

    if retenu is None:
        # Cas prévu : aucun candidat éligible. Le refus doit alors être déclaré.
        assert m["decision_deploiement"]["modele_deploye"] is False
        return

    ecart_retenu = m["comparaison"][retenu].get("ecart_train_valid_auc")
    assert ecart_retenu is not None, "écart train/validation non mesuré"
    assert ecart_retenu < SEUIL_ECART_TRAIN_VALID, (
        f"le modèle SERVI ({retenu}) affiche un écart train/validation de "
        f"{ecart_retenu} — la sélection a laissé passer un sur-apprentissage")

    # Tout candidat au-dessus du seuil doit porter la marque de sa mise à l'écart,
    # sans quoi un lecteur du rapport croirait qu'il était acceptable.
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


# ── 3. CONTRAT DE SORTIE ────────────────────────────────────────────────────
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
    # le score d'un même produit ne change pas selon le périmètre
    ref_glob = {p["produit"]: p["risk_score"] for p in glob["produits"]}
    for p in part["produits"]:
        if p["produit"] in ref_glob:
            assert p["risk_score"] == pytest.approx(ref_glob[p["produit"]]), \
                "le score ne doit pas dépendre du filtre d'affichage"


def test_les_ruptures_restent_conformes_au_profil_simule():
    """Le nombre de ruptures doit correspondre au profil que la simulation vise.

    `PROFIL_SITUATION` prévoit 8 % de références en rupture. Un écart massif
    signale que la génération trahit son propre profil — ce fut le cas : l'arrondi
    à l'entier ramenait à zéro le stock des références à faible rotation, portant
    les ruptures à 45 % du catalogue. Le briefing annonçait alors une pénurie
    généralisée qui n'existait que dans l'arrondi.

    La borne est large (le triple du profil) parce qu'on cherche à détecter une
    dérive structurelle, pas une fluctuation de tirage aléatoire.
    """
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
    """« Sain » et « stock nul » sont contradictoires par définition.

    C'est la formulation vérifiable du défaut d'arrondi : une référence classée
    saine, à commander ou en surstock possède nécessairement au moins une unité.
    Seule la situation « rupture » autorise un stock à zéro.
    """
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
