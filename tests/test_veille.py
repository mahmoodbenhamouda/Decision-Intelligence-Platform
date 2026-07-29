"""
tests/test_veille.py
====================
Tests unitaires de l'agent de veille externe et de ses enrichissements
décisionnels. Aucune dépendance réseau : la source News est simulée via un
monkeypatch du GET HTTP. Les tests d'enrichissement sur données réelles se
sautent proprement si l'entrepôt DuckDB n'est pas encore construit.

Exécution :
    python -m pytest tests/test_veille.py -v
    (ou, sans pytest : python tests/test_veille.py)
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import veille_agent as va
from ml_engine.analytics import kpi_engine as k


# ── Filtre de pertinence métier ─────────────────────────────────────────────
def test_relevance_rejette_hors_domaine():
    assert not k._opp_is_relevant("DIAGNOSTIC TECHNIQUE AU MUSEE NATIONAL DU BARDO")
    assert not k._opp_is_relevant("HUILE D'OLIVE : ENQUETE NATIONALE SUR LA FILIERE")
    assert not k._opp_is_relevant("CONSTRUCTION D'UNE NOUVELLE ROUTE A TUNIS")


def test_relevance_accepte_domaine():
    assert k._opp_is_relevant("FOURNITURE DE REACTIFS DE LABORATOIRE POUR LE CHU DE SFAX")
    assert k._opp_is_relevant("ACQUISITION D'UN AUTOMATE D'IMMUNOLOGIE HOSPITALIER")
    assert k._opp_is_relevant("DISPOSITIF MEDICAL DE DIAGNOSTIC IN VITRO")


# ── Parsing de date RFC-822 ─────────────────────────────────────────────────
def test_parse_date_valide():
    dt = va._parse_date("Wed, 25 Jun 2026 08:00:00 GMT")
    assert dt is not None and dt.year == 2026 and dt.month == 6 and dt.tzinfo is not None


def test_parse_date_invalide():
    assert va._parse_date("") is None
    assert va._parse_date("pas une date") is None


# ── Source News : dédoublonnage + fraîcheur (réseau simulé) ─────────────────
_FAKE_RSS = """<?xml version='1.0'?><rss><channel>
<item><title>Réactifs labo CHU Sfax - JournalX</title><source>JournalX</source>
<link>http://x/1</link><pubDate>Wed, 25 Jun 2026 08:00:00 GMT</pubDate></item>
<item><title>Réactifs labo CHU Sfax - JournalY</title><source>JournalY</source>
<link>http://x/2</link><pubDate>Thu, 26 Jun 2026 09:00:00 GMT</pubDate></item>
<item><title>Vieux avis immunologie - JournalZ</title><source>JournalZ</source>
<link>http://x/3</link><pubDate>Mon, 01 Jan 2024 09:00:00 GMT</pubDate></item>
<item><title>Automate hematologie hopital - JournalW</title><source>JournalW</source>
<link>http://x/4</link><pubDate>Tue, 30 Jun 2026 09:00:00 GMT</pubDate></item>
</channel></rss>"""


def test_news_dedup_et_fraicheur(monkeypatch):
    # fige la date « maintenant » n'est pas nécessaire : on choisit des pubDate
    # récentes (< 75 j de juillet 2026) et un item ancien (2024) à filtrer.
    monkeypatch.setattr(va, "_http_get", lambda *a, **kw: _FAKE_RSS.encode("utf-8"))
    items = va.NewsSource().fetch()
    titles = [i["title"] for i in items]
    # doublon supprimé, item 2024 écarté par fraîcheur, suffixe " - Source" nettoyé
    assert "Réactifs labo CHU Sfax" in titles
    assert titles.count("Réactifs labo CHU Sfax") == 1
    assert "Vieux avis immunologie" not in titles


# ── HTTP robuste : retry puis succès ────────────────────────────────────────
def test_http_get_retry(monkeypatch):
    calls = {"n": 0}

    def flaky(url, timeout=12):
        calls["n"] += 1
        if calls["n"] < 2:
            raise OSError("coupure transitoire")

        class R:
            def read(self_inner):
                return b"OK"

            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

        return R()

    monkeypatch.setattr(va.urllib.request, "urlopen", flaky)
    monkeypatch.setattr(va.time, "sleep", lambda *_: None)
    assert va._http_get("http://x", retries=2) == b"OK"
    assert calls["n"] == 2  # a bien retenté une fois


# ── Enrichissements sur données réelles (sautés si pas d'entrepôt) ──────────
def _store_ready():
    try:
        con = k._connect()
        con.execute("SELECT 1 FROM purchases LIMIT 1")
        con.close()
        return True
    except Exception:
        return False


def test_fx_sensitivity_reelle():
    if not _store_ready():
        return  # skip silencieux hors environnement de données
    fxs = k.fx_margin_sensitivity({"eur_tnd": 3.365, "eur_tnd_var_pct": 1.8})
    assert fxs and fxs["annual_fx_base_dt"] > 0
    # impact = base * var% : cohérence arithmétique
    assert abs(fxs["var_impact_dt"] - fxs["annual_fx_base_dt"] * 0.018) < 1.0
    assert abs(fxs["impact_per_1pct_dt"] - fxs["annual_fx_base_dt"] * 0.01) < 1.0


def test_macro_context_reelle():
    if not _store_ready():
        return
    mc = k.macro_market_context({"sante_pct_pib": {"value": 7.99, "year": "2023"}})
    assert mc and 0 <= mc["public_ca_share_pct"] <= 100
    assert "budget santé" in mc["note"]


if __name__ == "__main__":  # exécution sans pytest (monkeypatch minimal)
    class _MP:
        def setattr(self, obj, name, val):
            setattr(obj, name, val)

    test_relevance_rejette_hors_domaine()
    test_relevance_accepte_domaine()
    test_parse_date_valide()
    test_parse_date_invalide()
    test_news_dedup_et_fraicheur(_MP())
    test_http_get_retry(_MP())
    test_fx_sensitivity_reelle()
    test_macro_context_reelle()
    print("OK — tous les tests passent")
