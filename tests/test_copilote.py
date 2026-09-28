"""
tests/test_copilote.py
======================
Le graphe du copilote (agents/copilote/) : ordre des nœuds, choix de la source
de réponse, et honnêteté du champ `via`. Indicateurs et modèle de langage sont
remplacés par des doublures : aucun entrepôt, aucun appel réseau.
"""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("langgraph")

from agents.copilote import documents, graph, llm, noeuds, outils  # noqa: E402

KPIS = {"ca_total_ttc": 1_000_000.0, "nb_clients": 12, "dso_jours": 45.0, "yoy_growth": 3.0,
        "monthly_sales": [{"period": f"2025-{m:02d}", "revenue": 1000.0 * m} for m in range(1, 13)],
        "exposition_recente_dt": 250_000.0, "exposition_recente_critique_dt": 100_000.0,
        "exposition_recente_count": 7, "anomalies_detectees": 2, "clients_relance": [
            {"nom": "HOPITAL A", "montant_risque": 120_000.0, "factures": 3}]}


@pytest.fixture(autouse=True)
def doublures(monkeypatch):
    monkeypatch.setattr(outils, "indicateurs", lambda f: dict(KPIS))
    monkeypatch.setattr(outils, "radar", lambda f: [])
    monkeypatch.setattr(documents, "reponse_documentaire", lambda q: None)
    monkeypatch.setattr(noeuds, "reponse_documentaire", lambda q: None)
    monkeypatch.setattr(llm, "cle_disponible", lambda: False)


def _outils(r):
    return [t["tool"] for t in r["trace"]]


def test_tableau_de_bord_chaine_d_outils_et_identite():
    r = graph.copilote.tableau_de_bord({"selected_clients": ["C1"]})
    assert _outils(r) == ["router", "sql_kpis", "router", "ml_risque", "prevision",
                          "anomalies", "synthese"]
    assert (r["mode"], r["scope"]) == ("dashboard", "client")
    assert len(r["kpis"]["forecast_next"]) == 3
    assert r["meta"]["name"] == "Agent Finance"


def test_sans_modele_de_langage_le_repli_repond():
    r = graph.copilote.repondre({}, question="Qui dois-je relancer ?")
    assert r["via"] == "regles" and r["meta"]["moteur"] == "langgraph"
    assert _outils(r)[-3:] == ["aiguillage", "redaction", "repli"]
    assert "HOPITAL A" in r["text"]


def test_le_prefixe_doc_passe_par_la_base_documentaire(monkeypatch):
    monkeypatch.setattr(noeuds, "reponse_documentaire",
                        lambda q: f"extrait pour « {q} »")
    r = graph.copilote.repondre({}, question="doc: procédure de relance")
    assert r["via"] == "rag" and r["text"] == "extrait pour « procédure de relance »"
    assert _outils(r)[-2:] == ["aiguillage", "documents"]      # ni LLM, ni repli


def _llm_factice(monkeypatch, reponse):
    import config.settings  # noqa: F401
    cs = sys.modules["config.settings"]
    monkeypatch.setattr(llm, "cle_disponible", lambda: True)
    monkeypatch.setattr(cs, "get_llm", lambda model=None: SimpleNamespace(
        invoke=lambda prompt: SimpleNamespace(content=reponse)))


def test_reponse_du_modele_retenue_quand_ses_montants_sont_sources(monkeypatch):
    _llm_factice(monkeypatch, "250.0 K DT en retard de plus de 60 jours : relancer HOPITAL A.")
    r = graph.copilote.repondre({}, question="Qui dois-je relancer ?")
    assert r["via"] == "llm" and r["text"].endswith("relancer HOPITAL A.")


@pytest.mark.vitrine
def test_via_dit_d_ou_vient_la_reponse(monkeypatch):
    """Un montant inventé fait écarter la réponse du modèle : c'est alors la
    règle qui répond, et `via` le dit (il annonçait « llm » dès qu'une clé
    existait, même quand la réponse affichée venait des règles)."""
    _llm_factice(monkeypatch, "Exposition secteur public : 30 396 136 DT.")
    r = graph.copilote.repondre({}, question="Qui dois-je relancer ?")
    assert r["via"] == "regles"
    assert "30 396 136" not in r["text"]
    assert _outils(r)[-2:] == ["redaction", "repli"]


@pytest.mark.parametrize("question", ["Qui dois-je relancer ?", "doc: contrat",
                                      "Quelle est la capitale de la France ?", ""])
def test_le_repli_sequentiel_suit_le_meme_chemin_que_le_graphe(question):
    init = {"filters": {}, "question": question or graph.QUESTION_PAR_DEFAUT,
            "history": [], "trace": []}
    a = graph.build_graph().invoke(dict(init))
    b = graph._run_sequential(dict(init))
    assert a["texte"] == b["texte"] and a["via"] == b["via"]
    assert [t["tool"] for t in a["trace"]] == [t["tool"] for t in b["trace"]]


def test_le_copilote_ne_depend_pas_de_l_api():
    import ast
    import glob
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for chemin in glob.glob(os.path.join(racine, "agents", "copilote", "*.py")):
        arbre = ast.parse(open(chemin, encoding="utf-8").read())
        modules = [n.module for n in ast.walk(arbre) if isinstance(n, ast.ImportFrom) and n.module]
        modules += [a.name for n in ast.walk(arbre) if isinstance(n, ast.Import) for a in n.names]
        assert not [m for m in modules if m.split(".")[0] in ("api", "fastapi")], chemin
