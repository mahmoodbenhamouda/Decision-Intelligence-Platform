"""La décomposition de la marge doit redonner le total qu'elle explique.

Le risque de ce chantier n'est pas de produire un chiffre faux, c'est d'en
produire un qui CONTREDISE celui affiché juste au-dessus. Un directeur qui voit
« marge brute 73,5 M » puis une somme par catégorie à 76,7 M cesse de croire au
tableau de bord entier, et il a raison.
"""

from __future__ import annotations

import pytest

from ml_engine.analytics import marge_decomposee as md
from ml_engine.analytics.kpi_engine import _connect, compute_dashboard

TOUT = {"periode": "tout"}


@pytest.fixture(scope="module")
def analyse():
    r = md.analyser(TOUT)
    if not r.get("servi"):
        pytest.skip(f"décomposition indisponible : {r.get('motif')}")
    return r


def test_la_somme_des_categories_redonne_la_marge_brute_du_tableau_de_bord(analyse):
    """Le mart par catégorie et le mart par client doivent dire le même total.

    Les deux appliquent la même règle de coût exploitable ; si l'une diverge,
    c'est que la règle a été dupliquée au lieu d'être partagée."""
    k = compute_dashboard(TOUT)
    attendu = k["marge_brute"]
    obtenu = analyse["par_categorie"]["total_marge_dt"]
    assert attendu is not None
    assert abs(obtenu - attendu) <= 1.0, (
        f"décomposition {obtenu:,.0f} contre total {attendu:,.0f}")

    somme = sum(c["marge_dt"] for c in analyse["par_categorie"]["categories"])
    assert abs(somme - obtenu) <= 1.0


def test_le_ca_de_reference_est_celui_du_tableau_de_bord(analyse):
    k = compute_dashboard(TOUT)
    assert abs(analyse["par_categorie"]["total_ca_dt"]
               - k["marge_ca_reference_dt"]) <= 1.0


def test_les_parts_de_ca_et_de_marge_somment_a_cent(analyse):
    cats = analyse["par_categorie"]["categories"]
    assert abs(sum(c["part_du_ca_pct"] for c in cats) - 100) < 0.5
    assert abs(sum(c["part_de_la_marge_pct"] for c in cats) - 100) < 0.5


def test_le_waterfall_est_coherent(analyse):
    """CA − coût = marge, sur les trois étapes publiées."""
    w = {e["etape"]: e["valeur_dt"] for e in analyse["waterfall"]}
    depart = w["Chiffre d'affaires des lignes"]
    cout = w["Coût de revient"]
    total = w["Marge brute"]
    assert cout <= 0, "le coût doit être publié négatif, c'est une déduction"
    assert abs((depart + cout) - total) <= 1.0


def test_reactifs_et_equipement_ont_des_taux_tres_differents(analyse):
    """Le fait métier qui justifie tout ce chantier.

    Overlyne place l'automate presque à prix coûtant et se rémunère sur les
    réactifs qu'il consomme. Si les deux taux se rapprochaient, la
    décomposition par catégorie perdrait son intérêt — autant le vérifier."""
    taux = {c["code"]: c["taux_marge_pct"]
            for c in analyse["par_categorie"]["categories"]}
    if "reactif" not in taux or "equipement" not in taux:
        pytest.skip("catégories absentes sur ce jeu de données")
    assert taux["reactif"] > taux["equipement"], (
        "les réactifs doivent être plus margés que l'équipement")
    assert taux["reactif"] - taux["equipement"] > 10, (
        f"écart de seulement {taux['reactif'] - taux['equipement']:.1f} points")


def test_un_produit_ne_peut_pas_etre_a_la_fois_porteur_et_a_perte(analyse):
    refs_porteurs = {p["reference"] for p in analyse["produits"]["porteurs"]}
    refs_pertes = {p["reference"] for p in analyse["produits"]["pertes"]}
    assert not (refs_porteurs & refs_pertes)


def test_les_pertes_sont_bien_negatives_et_les_porteurs_positifs(analyse):
    assert all(p["marge_dt"] > 0 for p in analyse["produits"]["porteurs"])
    assert all(p["marge_dt"] < 0 for p in analyse["produits"]["pertes"])
    assert analyse["produits"]["perte_totale_dt"] <= 0


def test_la_tendance_couvre_tout_l_historique_malgre_un_filtre_d_annee():
    """Une pente ne se lit pas sur douze points : le filtre de période
    restreint les totaux, pas la courbe."""
    complet = md.analyser(TOUT)
    filtre = md.analyser({"selected_years": [2024]})
    if not (complet.get("servi") and filtre.get("servi")):
        pytest.skip("décomposition indisponible")
    assert len(filtre["tendance"]) == len(complet["tendance"])
    # Les totaux, eux, doivent bien avoir diminué.
    assert (filtre["par_categorie"]["total_ca_dt"]
            < complet["par_categorie"]["total_ca_dt"])


def test_la_periode_par_defaut_est_les_douze_derniers_mois():
    """Sans filtre, la décomposition porte sur la même période que le total."""
    r = md.analyser({})
    if not r.get("servi"):
        pytest.skip("décomposition indisponible")
    assert r["periode_reference"]["code"] == "12m"
    k = compute_dashboard({})
    assert abs(r["par_categorie"]["total_marge_dt"] - k["marge_brute"]) <= 1.0


def test_un_filtre_client_restreint_la_decomposition():
    con = _connect()
    try:
        code = con.execute("""
            SELECT client FROM client_margin
            GROUP BY client ORDER BY sum(ca_ligne) DESC NULLS LAST LIMIT 1
        """).fetchone()
    finally:
        con.close()
    if not code:
        pytest.skip("aucun client dans le mart de marge")

    r = md.analyser({"periode": "tout", "selected_clients": [code[0]]})
    if not r.get("servi"):
        pytest.skip(f"indisponible : {r.get('motif')}")
    complet = md.analyser(TOUT)
    assert (r["par_categorie"]["total_ca_dt"]
            < complet["par_categorie"]["total_ca_dt"])


def test_les_produits_portent_la_meme_periode_que_les_totaux():
    """Le défaut le plus insidieux : une liste de produits sur tout
    l'historique sous un total sur douze mois.

    Les deux se contredisaient sans qu'aucun chiffre soit faux. La somme des
    marges produits doit égaler le total de la période, à l'arrondi près.
    """
    for filtres in ({}, {"periode": "tout"}, {"selected_years": [2025]}):
        r = md.analyser(filtres, limite=50)
        if not r.get("servi"):
            continue
        from ml_engine.analytics.kpi_engine import _connect as _c
        con = _c()
        try:
            where = md._clauses({**filtres, **({
                "date_start": r["periode_reference"]["debut"],
                "date_end": r["periode_reference"]["fin"],
            } if r["periode_reference"].get("debut") else {})})
            somme = con.execute(
                f"SELECT sum(marge) FROM margin_product WHERE {where}").fetchone()[0]
        finally:
            con.close()
        total = r["par_categorie"]["total_marge_dt"]
        assert abs(float(somme or 0) - total) <= 1.0, (
            f"filtres {filtres} : produits {somme:,.0f} contre total {total:,.0f}")


def test_une_periode_courte_donne_moins_de_marge_que_tout_l_historique():
    douze = md.analyser({})
    tout = md.analyser(TOUT)
    if not (douze.get("servi") and tout.get("servi")):
        pytest.skip("décomposition indisponible")
    assert (douze["par_categorie"]["total_marge_dt"]
            < tout["par_categorie"]["total_marge_dt"])


def test_une_categorie_peut_etre_negative_sans_casser_les_parts():
    """Sur douze mois, l'équipement est vendu à perte dans ces données.

    Une « part de la marge » devient alors supérieure à 100 % pour les autres
    catégories : c'est arithmétiquement juste, et la somme doit rester à 100.
    L'interface affiche des dinars signés plutôt que ces parts, mais le calcul
    ne doit pas pour autant devenir incohérent."""
    r = md.analyser({})
    if not r.get("servi"):
        pytest.skip("décomposition indisponible")
    cats = r["par_categorie"]["categories"]
    assert abs(sum(c["part_de_la_marge_pct"] for c in cats) - 100) < 0.5
    somme = sum(c["marge_dt"] for c in cats)
    assert abs(somme - r["par_categorie"]["total_marge_dt"]) <= 1.0


def test_l_annee_en_cours_declare_qu_elle_est_incomplete():
    """« Année en cours » s'arrête à la dernière facture de l'entrepôt.

    Afficher quatre mois de marge sous le mot « année » laisse croire à un
    effondrement face à l'exercice précédent, alors qu'il ne manque que du
    temps. C'est le défaut que ce bloc corrige."""
    r = md.analyser({"periode": "annee"})
    if not r.get("servi"):
        pytest.skip("décomposition indisponible")
    c = r["completude"]
    assert c, "aucun bloc de complétude sur l'année en cours"
    assert 1 <= c["mois_couverts"] <= 12
    assert c["incomplete"] == (c["mois_couverts"] < 12)
    assert c["dernier_mois"].startswith(str(c["annee"]))
    assert abs(c["marge_realisee_dt"]
               - r["par_categorie"]["total_marge_dt"]) <= 1.0


def test_la_comparaison_porte_sur_la_meme_fenetre_de_l_annee_precedente():
    """Comparer quatre mois à douze serait la faute inverse."""
    r = md.analyser({"periode": "annee"})
    if not r.get("servi") or not r["completude"]:
        pytest.skip("décomposition indisponible")
    c = r["completude"]
    cm = c["comparaison"]
    assert cm["annee"] == c["annee"] - 1
    assert cm["marge_meme_periode_dt"] <= cm["marge_annee_complete_dt"]
    if cm["part_de_l_annee_pct"] is not None:
        assert 0 < cm["part_de_l_annee_pct"] <= 100


def test_la_projection_depasse_le_realise_et_declare_sa_methode():
    r = md.analyser({"periode": "annee"})
    if not r.get("servi") or not r["completude"]:
        pytest.skip("décomposition indisponible")
    c = r["completude"]
    if c["projection_fin_d_annee_dt"] is None:
        pytest.skip("projection non calculable")
    assert c["projection_fin_d_annee_dt"] >= c["marge_realisee_dt"], (
        "une année complète ne peut pas valoir moins que ses premiers mois")
    assert "saisonnalité constatée" in c["projection_methode"].lower()
    assert "pas un modèle appris" in c["projection_methode"].lower()
    assert "suppose" in c["projection_limite"].lower()


def test_pas_de_bloc_de_completude_hors_annee_en_cours():
    """12 derniers mois et tout l'historique sont des fenêtres complètes par
    construction : y afficher une projection n'aurait aucun sens."""
    for filtres in ({}, {"periode": "tout"}, {"selected_years": [2024]}):
        r = md.analyser(filtres)
        if r.get("servi"):
            assert not r["completude"], f"bloc inattendu pour {filtres}"


def test_les_limites_sont_publiees_en_donnees(analyse):
    """« Ce que ce chiffre ne dit pas » doit porter des nombres, pas un
    avertissement vague : c'est ce qui le rend vérifiable."""
    lim = analyse["limites"]
    for cle in ("lignes_ecartees", "lignes_offertes", "cout_offert_dt",
                "lignes_retour", "ca_retour_dt"):
        assert cle in lim, f"{cle} absent des limites"
    assert lim["lignes_ecartees"] >= 0
    assert lim["cout_offert_dt"] >= 0
    assert "salaires" in lim["ce_qui_n_est_pas_deduit"].lower()
