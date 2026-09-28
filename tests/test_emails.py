"""
tests/test_emails.py
====================
Tests de la génération d'adresses « nom d'hôpital » et de la migration seed.

Exécution :
    python -m pytest tests/test_emails.py -v
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.auth.emails import email_for_client, slugify_name


# ── Slugification : les cas réels de l'ERP ──────────────────────────────────
def test_slug_hopital_militaire():
    assert slugify_name("HOPITAL MILITAIRE DE TUNIS") == "hopital-militaire-de-tunis"


def test_slug_chu_avec_points():
    assert slugify_name("C.H.U. CHARLES NICOLLE") == "chu-charles-nicolle"
    assert slugify_name("C.H.U. HABIB BOURGUIBA") == "chu-habib-bourguiba"


def test_slug_accents_et_apostrophes():
    assert slugify_name("Hôpital d'Enfants Béchir Hamza") == "hopital-d-enfants-bechir-hamza"
    assert slugify_name("Clinique El Amâne") == "clinique-el-amane"


def test_slug_longueur_bornee():
    long = "Établissement Hospitalier Universitaire Régional de la Circonscription Nord"
    s = slugify_name(long)
    assert len(s) <= 40 and not s.endswith("-")


def test_slug_vide_ou_bizarre():
    assert slugify_name("") == ""
    assert slugify_name("***") == ""


# ── email_for_client : repli et collisions ──────────────────────────────────
def test_email_nominal():
    assert email_for_client("C.H.U. CHARLES NICOLLE", "CE000017") == \
        "chu-charles-nicolle@overlyne.tn"


def test_email_nom_vide_replie_sur_le_code():
    assert email_for_client("", "CE000099") == "ce000099@overlyne.tn"


def test_email_collision_suffixe_code():
    taken = {"chu-charles-nicolle@overlyne.tn"}
    e = email_for_client("C.H.U. CHARLES NICOLLE", "CE000042", taken)
    assert e == "chu-charles-nicolle-ce000042@overlyne.tn"
    assert e not in taken


def test_email_insensible_a_la_casse_pour_les_collisions():
    taken = {"CHU-CHARLES-NICOLLE@OVERLYNE.TN"}
    e = email_for_client("C.H.U. Charles Nicolle", "X1", taken)
    assert "x1" in e


# ── Migration seed : renommage idempotent, mot de passe conservé ────────────
def test_seed_migre_les_anciennes_adresses(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="emailmig_")
    url = f"sqlite:///{Path(tmp).as_posix()}/mig.db"
    from api.auth.database import reset_for_tests, get_db
    from api.auth.models import User
    from api.auth.security import hash_password, verify_password
    from api.auth import seed as seed_mod

    reset_for_tests(url)
    # Un compte à l'ANCIEN schéma, avec un mot de passe connu
    db = next(get_db())
    db.add(User(email="client.ce000016@overlyne.tn",
                password_hash=hash_password("Client#20261"),
                role="client", client_code="CE000016",
                full_name="HOPITAL MILITAIRE DE TUNIS"))
    db.commit()
    db.close()

    # L'entrepôt est simulé : un seul client
    monkeypatch.setattr(seed_mod, "top_client_codes",
                        lambda n=3: [("CE000016", "HOPITAL MILITAIRE DE TUNIS", 1000.0)])
    seed_mod.seed(1, verbose=False)

    db = next(get_db())
    try:
        u = db.query(User).filter(User.client_code == "CE000016").one()
        assert u.email == "hopital-militaire-de-tunis@overlyne.tn"
        assert verify_password("Client#20261", u.password_hash), \
            "le mot de passe doit survivre au renommage"
        # Idempotence : un second seed ne change plus rien et ne duplique pas
        seed_mod.seed(1, verbose=False)
        n = db.query(User).filter(User.client_code == "CE000016").count()
        assert n == 1
    finally:
        db.close()


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
