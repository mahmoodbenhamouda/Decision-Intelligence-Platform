"""Le secret de signature des JWT : exigé, mesuré, sans repli.

Le repli précédent tirait un secret aléatoire quand `JWT_SECRET_KEY` manquait.
L'application démarrait, les connexions marchaient, rien ne rougissait — et en
multi-workers chaque processus signait avec un secret différent, donc un jeton
émis par l'un était rejeté par les autres : des 401 intermittents sans message.

Ces tests ne touchent aucune base.
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from api.auth.security import (ConfigurationSecuriteInvalide,  # noqa: E402
                               LONGUEUR_MIN_SECRET, _secret,
                               create_access_token, decode_access_token,
                               verifier_secret)


@pytest.fixture
def sans_cle(monkeypatch):
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.delenv("_JWT_DEV_SECRET", raising=False)


def _cle(n: int) -> str:
    return "x" * n


def test_cle_absente_refusee(sans_cle):
    with pytest.raises(ConfigurationSecuriteInvalide):
        verifier_secret()


def test_cle_vide_ou_blanche_refusee(monkeypatch):
    for valeur in ("", "   ", "\t\n"):
        monkeypatch.setenv("JWT_SECRET_KEY", valeur)
        with pytest.raises(ConfigurationSecuriteInvalide):
            verifier_secret()


def test_frontiere_de_longueur(monkeypatch):
    """La frontière elle-même, pas un cas de part et d'autre."""
    monkeypatch.setenv("JWT_SECRET_KEY", _cle(LONGUEUR_MIN_SECRET - 1))
    with pytest.raises(ConfigurationSecuriteInvalide):
        verifier_secret()

    monkeypatch.setenv("JWT_SECRET_KEY", _cle(LONGUEUR_MIN_SECRET))
    verifier_secret()


def test_minimum_conforme_a_la_rfc_7518():
    """256 bits pour HS256. Abaisser cette constante doit faire échouer un test."""
    assert LONGUEUR_MIN_SECRET >= 32


def test_message_donne_la_longueur_reelle(monkeypatch):
    """Un message qui ne dit pas de combien on est en dessous n'aide pas."""
    monkeypatch.setenv("JWT_SECRET_KEY", _cle(26))
    with pytest.raises(ConfigurationSecuriteInvalide) as err:
        verifier_secret()
    assert "26" in str(err.value)


def test_longueur_mesuree_en_octets_pas_en_caracteres(monkeypatch):
    """Une clé non-ASCII de 31 caractères peut dépasser 32 octets : c'est la
    taille réellement passée à HMAC qui compte."""
    monkeypatch.setenv("JWT_SECRET_KEY", "é" * 20)      # 40 octets
    verifier_secret()


def test_aucun_secret_genere_a_la_volee(sans_cle):
    """`_secret()` lève au lieu d'inventer une clé. C'est le mécanisme exact des
    401 intermittents en multi-workers."""
    with pytest.raises(ConfigurationSecuriteInvalide):
        _secret()
    assert "_JWT_DEV_SECRET" not in os.environ


def test_aucune_generation_dans_le_code_du_secret():
    """Garde-fou contre la réintroduction du repli, au-delà du comportement."""
    source = (RACINE / "api" / "auth" / "security.py").read_text(encoding="utf-8")
    arbre = ast.parse(source)
    fn = next(n for n in ast.walk(arbre)
              if isinstance(n, ast.FunctionDef) and n.name == "_secret")
    appels = [ast.unparse(n.func) for n in ast.walk(fn) if isinstance(n, ast.Call)]
    assert not [a for a in appels if "token_urlsafe" in a or "token_hex" in a], (
        "_secret() ne doit jamais fabriquer de clé : voir docstring du module")


def test_emission_refusee_sans_cle(sans_cle):
    """Le refus porte sur l'émission, pas seulement sur la vérification."""
    with pytest.raises(ConfigurationSecuriteInvalide):
        create_access_token(user_id=1, email="a@b.c", role="admin")


def test_aller_retour_avec_cle_conforme(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", _cle(48))
    jeton = create_access_token(user_id=7, email="a@b.c", role="directeur")
    chargeur = decode_access_token(jeton)
    assert chargeur is not None
    assert chargeur["sub"] == "7"
    assert chargeur["role"] == "directeur"
    assert "client_code" not in chargeur, "le jeton ne porte plus de périmètre client"


def test_jeton_rejete_si_la_cle_change(monkeypatch):
    """Ce que le repli provoquait en multi-workers, rendu explicite."""
    monkeypatch.setenv("JWT_SECRET_KEY", _cle(48))
    jeton = create_access_token(user_id=1, email="a@b.c", role="admin")
    monkeypatch.setenv("JWT_SECRET_KEY", _cle(48).replace("x", "y"))
    assert decode_access_token(jeton) is None


def test_verification_branchee_au_demarrage():
    """Un garde-fou non appelé revient à ne pas l'avoir."""
    arbre = ast.parse((RACINE / "api" / "main.py").read_text(encoding="utf-8"))
    lifespan = next(n for n in ast.walk(arbre)
                    if isinstance(n, ast.AsyncFunctionDef) and n.name == "lifespan")
    appels = {ast.unparse(n.func) for n in ast.walk(lifespan)
              if isinstance(n, ast.Call)}
    assert "verifier_secret" in appels
    # La base est validée au même endroit : les deux exigences vivent ensemble.
    assert "verifier_connexion" in appels


def test_aucune_cle_de_test_sous_le_minimum():
    """Un test qui poserait une clé trop courte serait refusé au démarrage et
    masquerait la cause derrière une erreur de configuration."""
    import re
    motif = re.compile(r'JWT_SECRET_KEY["\']?\s*[,=:]\s*["\']([^"\']+)["\']')
    trop_courtes = []
    for chemin in sorted((RACINE / "tests").glob("*.py")):
        # Ce fichier pose délibérément des clés non conformes pour vérifier
        # qu'elles sont refusées : il est le seul exclu du balayage.
        if chemin.name == Path(__file__).name:
            continue
        for valeur in motif.findall(chemin.read_text(encoding="utf-8")):
            if len(valeur.encode("utf-8")) < LONGUEUR_MIN_SECRET:
                trop_courtes.append(f"{chemin.name}: {len(valeur)} octets")
    assert not trop_courtes, trop_courtes
