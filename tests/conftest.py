"""Configuration pytest commune.

Un garde-fou : la suite ne doit pas pouvoir afficher « passed » alors que les
tests d'authentification ont été sautés.

C'est arrivé. `base_postgres` lisait `AUTH_DATABASE_URL` sans charger `.env`, les
cinq modules d'authentification étaient sautés, et la sortie annonçait
« 570 passed, 5 skipped ». Un saut compte comme un succès : rien ne rougissait, et
la régression n'était visible qu'en demandant explicitement les motifs de saut.
"""

from __future__ import annotations

MODULES_CRITIQUES = (
    "test_auth_rbac",
    "test_admin_portal",
    "test_delegation",
    "test_boucle_action",
)


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Signale en fin de session tout module critique entièrement sauté."""
    sautes = terminalreporter.stats.get("skipped", [])
    if not sautes:
        return

    touches = set()
    for rapport in sautes:
        chemin = str(getattr(rapport, "nodeid", "") or "")
        for module in MODULES_CRITIQUES:
            if module in chemin:
                touches.add(module)

    # Les sauts hors modules critiques sont légitimes : dépendances optionnelles,
    # modèles non entraînés. On ne crie que sur l'authentification.
    if not touches:
        return

    ecrire = terminalreporter.write_line
    ecrire("")
    ecrire("=" * 70, red=True, bold=True)
    ecrire("  TESTS D'AUTHENTIFICATION SAUTÉS — la suite ne les a pas exécutés",
           red=True, bold=True)
    ecrire("=" * 70, red=True, bold=True)
    for module in sorted(touches):
        ecrire(f"    · {module}", red=True)
    ecrire("")
    ecrire("  Cause la plus fréquente : PostgreSQL n'est pas joignable, ou",
           red=True)
    ecrire("  AUTH_DATABASE_URL est absent de .env.", red=True)
    ecrire("")
    ecrire("    docker compose -f docker-compose.postgres.yml up -d", red=True)
    ecrire("    python scripts/preparer_bases.py", red=True)
    ecrire("")
    ecrire("  Un saut compte comme un succès : « passed » ci-dessus ne couvre",
           red=True)
    ecrire("  PAS l'authentification, le RBAC ni l'isolation entre clients.",
           red=True)
    ecrire("=" * 70, red=True, bold=True)
