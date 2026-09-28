"""
scripts/preflight_demo.py
=========================
CONTRÔLE PRÉ-DÉMO — à lancer 30 minutes avant la soutenance.

Vérifie, un par un, tous les points qui peuvent faire échouer une démo, et
affiche pour chaque problème la commande exacte qui le corrige.

    python scripts/preflight_demo.py

Sortie : rapport coloré, code de retour 0 si tout est vert, 1 sinon.
"""

from __future__ import annotations

import importlib
import json
import os
import socket
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

try:
    from dotenv import load_dotenv
    load_dotenv(BASE / ".env")
except Exception:
    pass

OK, WARN, KO = "OK", "ATTENTION", "BLOQUANT"
_RESULTS: list[tuple[str, str, str, str]] = []   # (statut, titre, detail, correctif)


def check(titre: str, statut: str, detail: str = "", correctif: str = "") -> None:
    _RESULTS.append((statut, titre, detail, correctif))


def _port_libre(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", port)) != 0


# ── 1. Dépendances Python ───────────────────────────────────────────────────
def check_dependances() -> None:
    essentiels = {
        "fastapi": "API", "uvicorn": "serveur", "duckdb": "entrepôt",
        "pandas": "données", "sklearn": "modèles ML", "sqlalchemy": "base auth",
        "jwt": "jetons", "bcrypt": "mots de passe", "joblib": "modèles",
    }
    manquants = [f"{m} ({r})" for m, r in essentiels.items()
                 if importlib.util.find_spec(m) is None]
    if manquants:
        check("Dépendances Python", KO, "manquant : " + ", ".join(manquants),
              "pip install -r requirements.txt")
    else:
        check("Dépendances Python", OK, f"{len(essentiels)} paquets essentiels présents")

    optionnels = {"langgraph": "flotte parallèle (repli séquentiel sinon)",
                  "sentence_transformers": "RAG sémantique (repli TF-IDF sinon)",
                  "torch": "LSTM trésorerie (repli statistique sinon)"}
    absents = [f"{m} → {r}" for m, r in optionnels.items()
               if importlib.util.find_spec(m) is None]
    if absents:
        check("Dépendances optionnelles", WARN, " ; ".join(absents),
              "Fonctionne sans, mais dites-le au jury plutôt que d'être surpris.")
    else:
        check("Dépendances optionnelles", OK, "toutes présentes")


# ── 2. Entrepôt analytique ──────────────────────────────────────────────────
def check_entrepot() -> None:
    store = BASE / "output" / "analytics_store.duckdb"
    if not store.exists():
        check("Entrepôt DuckDB", KO, "output/analytics_store.duckdb absent",
              "python -m ml_engine.analytics.kpi_engine")
        return
    try:
        import duckdb
        con = duckdb.connect(str(store), read_only=True)
        n_sales = con.execute("SELECT count(*) FROM sales").fetchone()[0]
        n_cli = con.execute("SELECT count(DISTINCT client) FROM sales").fetchone()[0]
        periode = con.execute(
            "SELECT strftime(min(date),'%Y-%m'), strftime(max(date),'%Y-%m') "
            "FROM sales").fetchone()
        con.close()
        if n_sales < 100:
            check("Entrepôt DuckDB", KO, f"seulement {n_sales} lignes",
                  "python -m ml_engine.analytics.kpi_engine")
        else:
            check("Entrepôt DuckDB", OK,
                  f"{n_sales:,} factures · {n_cli} clients · {periode[0]} → {periode[1]}"
                  .replace(",", " "))
    except Exception as e:
        check("Entrepôt DuckDB", KO, str(e)[:90], "Reconstruire l'entrepôt.")


# ── 3. Modèles entraînés ────────────────────────────────────────────────────
def check_modeles() -> None:
    attendus = {
        "models/credit_risk_model.joblib": "python -m ml_engine.analytics.credit_risk_model",
    }
    for rel, cmd in attendus.items():
        p = BASE / rel
        if p.exists() and p.stat().st_size > 1000:
            check(f"Modèle {Path(rel).stem}", OK, f"{p.stat().st_size // 1024} Ko")
        else:
            check(f"Modèle {Path(rel).stem}", KO, "absent ou vide", cmd)

    # Compatibilité de version : un modèle entraîné avec une AUTRE version de
    # scikit-learn peut produire des résultats invalides (pas qu'un warning).
    try:
        import warnings as _w
        import joblib
        from sklearn.exceptions import InconsistentVersionWarning
        incompat = []
        for rel in attendus:
            p = BASE / rel
            if not p.exists():
                continue
            with _w.catch_warnings(record=True) as cap:
                _w.simplefilter("always")
                joblib.load(p)
            if any(issubclass(x.category, InconsistentVersionWarning) for x in cap):
                incompat.append(Path(rel).name)
        if incompat:
            check("Version des modèles", KO,
                  "entraînés avec une autre version de scikit-learn : "
                  + ", ".join(incompat),
                  "python scripts/retrain_all.py")
        else:
            check("Version des modèles", OK, "alignés sur scikit-learn installé")
    except Exception:
        pass

    rapports = ["reports/credit_risk_metrics.json",
                "reports/demand_forecast_metrics.json",
                "reports/stock_risk_metrics.json",
                "reports/cashflow_carnet_metrics.json"]
    absents = [r for r in rapports if not (BASE / r).exists()]
    if absents:
        check("Rapports de métriques", WARN, f"{len(absents)} absent(s) : "
              + ", ".join(Path(a).name for a in absents),
              "Relancer les modules concernés (voir reports/METRICS_REPORT.md)")
    else:
        try:
            m = json.loads((BASE / "reports/credit_risk_metrics.json").read_text(encoding="utf-8"))
            check("Rapports de métriques", OK,
                  f"{len(rapports)} rapports · crédit v{m.get('version')} "
                  f"({(m.get('donnees') or {}).get('n_factures_retenues')} factures)")
        except Exception:
            check("Rapports de métriques", OK, f"{len(rapports)} rapports présents")


# ── 4. Base d'authentification & comptes ────────────────────────────────────
def check_auth() -> None:
    url = os.environ.get("AUTH_DATABASE_URL", "")
    cible = "PostgreSQL" if url.startswith("postgresql") else "SQLite (démo)"
    try:
        from api.auth.database import get_db, init_db
        from api.auth.models import ROLE_CLIENT, ROLE_DIRECTEUR, User
        init_db()
        db = next(get_db())
        try:
            dirs = db.query(User).filter(User.role == ROLE_DIRECTEUR,
                                         User.is_active.is_(True)).count()
            clients = db.query(User).filter(User.role == ROLE_CLIENT,
                                            User.is_active.is_(True)).all()
            sans_nom = [c.email for c in clients if not c.full_name]
        finally:
            db.close()
    except Exception as e:
        msg = str(e)[:110]
        if "connection" in msg.lower() or "refused" in msg.lower():
            check(f"Base auth ({cible})", KO, "serveur injoignable",
                  "docker compose -f docker-compose.postgres.yml up -d "
                  "(ou commentez AUTH_DATABASE_URL dans .env pour SQLite)")
        else:
            check(f"Base auth ({cible})", KO, msg, "python -m api.auth.seed")
        return

    if dirs == 0:
        check(f"Base auth ({cible})", KO, "aucun directeur actif",
              "python -m api.auth.seed")
    elif not clients:
        check(f"Base auth ({cible})", KO, "aucun compte client",
              "python -m api.auth.seed")
    else:
        detail = f"{dirs} directeur · {len(clients)} client(s) : " + ", ".join(
            c.email.split("@")[0] for c in clients[:3])
        check(f"Base auth ({cible})", OK, detail)
        if sans_nom:
            check("Noms d'établissement", WARN,
                  f"{len(sans_nom)} compte(s) sans nom affiché",
                  "python -m api.auth.seed  (enrichit les noms depuis l'ERP)")


# ── 5. Secrets & configuration ──────────────────────────────────────────────
def check_config() -> None:
    if not (BASE / ".env").exists():
        check("Fichier .env", WARN, "absent — valeurs par défaut utilisées",
              "copy .env.example .env")
    else:
        check("Fichier .env", OK, "présent")

    if not os.environ.get("JWT_SECRET_KEY"):
        check("Secret JWT", WARN, "non défini → secret éphémère (sessions perdues "
              "à chaque redémarrage de l'API)",
              'python -c "import secrets;print(secrets.token_urlsafe(48))" '
              "puis JWT_SECRET_KEY=... dans .env")
    else:
        check("Secret JWT", OK, "défini")

    if os.environ.get("GROQ_API_KEY"):
        check("Clé LLM (Groq)", OK, "présente → réponses en langage naturel")
    else:
        check("Clé LLM (Groq)", WARN, "absente → replis déterministes chiffrés",
              "C'est défendable en soutenance : montrez que tout marche sans LLM.")


# ── 6. Frontend ─────────────────────────────────────────────────────────────
def check_frontend() -> None:
    fe = BASE / "frontend"
    if not (fe / "node_modules").exists():
        check("Frontend (node_modules)", KO, "dépendances non installées",
              "cd frontend && npm install")
    else:
        three = fe / "node_modules" / "three" / "package.json"
        if three.exists():
            check("Frontend (dépendances)", OK, "node_modules + three présents")
        else:
            check("Frontend (three.js)", KO, "avatar 3D indisponible",
                  "cd frontend && npm install three@0.170.0 @types/three@0.170.0")

    glb = fe / "public" / "avatar" / "finbot.glb"
    if glb.exists() and glb.stat().st_size > 100_000:
        check("Avatar 3D", OK,
              f"GLB local {glb.stat().st_size // 1024} Ko — mode photoréaliste, hors-ligne")
    else:
        check("Avatar 3D", OK,
              "tête 3D procédurale (Three.js, 100 % locale) — aucun réseau requis")

    cache = fe / ".next"
    if cache.exists():
        check("Cache Next.js", WARN, ".next présent — peut se corrompre",
              "En cas d'erreur Turbopack : supprimez frontend\\.next et relancez.")


# ── 7. OCR ──────────────────────────────────────────────────────────────────
def check_ocr() -> None:
    try:
        from ml_engine.ocr.engine import ocr_available
        if ocr_available():
            import pytesseract
            langs = [l for l in pytesseract.get_languages(config="")
                     if l in ("fra", "eng")]
            check("OCR Tesseract", OK,
                  f"v{pytesseract.get_tesseract_version()} · langues : {', '.join(langs)}")
            if "fra" not in langs:
                check("OCR — pack français", WARN, "absent → accents mal reconnus",
                      "python scripts/setup_tesseract_fr.py  "
                      "(installe le pack dans le projet, sans droits admin)")
        else:
            check("OCR Tesseract", WARN, "non installé → onglet OCR limité aux PDF texte",
                  "Voir docs/OCR.md (Windows : installateur UB-Mannheim + PATH)")
    except Exception as e:
        check("OCR Tesseract", WARN, str(e)[:80], "Voir docs/OCR.md")


# ── 8. Ports & tests ────────────────────────────────────────────────────────
def check_ports() -> None:
    for port, usage in ((8000, "API"), (4000, "frontend")):
        if _port_libre(port):
            check(f"Port {port} ({usage})", OK, "libre")
        else:
            check(f"Port {port} ({usage})", WARN, "déjà utilisé",
                  f"Un serveur tourne déjà — parfait s'il s'agit du vôtre. "
                  f"Sinon : netstat -ano | findstr :{port}")


def check_tests() -> None:
    """Compte les tests sans les exécuter (rapide)."""
    tests = list((BASE / "tests").glob("test_*.py"))
    if not tests:
        check("Suite de tests", KO, "aucun fichier de test", "")
        return
    n = sum(len([l for l in t.read_text(encoding="utf-8", errors="ignore").split("\n")
                 if l.startswith("def test_")]) for t in tests)
    check("Suite de tests", OK, f"{len(tests)} fichiers · ~{n} tests",
          "Lancez `python -m pytest tests/ -q` devant le jury si on vous le demande.")


# ── Rapport ─────────────────────────────────────────────────────────────────
def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    print("\n" + "=" * 74)
    print("  CONTRÔLE PRÉ-DÉMO — plateforme d'intelligence décisionnelle Overlyne")
    print("=" * 74)

    for fn in (check_dependances, check_entrepot, check_modeles, check_auth,
               check_config, check_frontend, check_ocr, check_ports, check_tests):
        try:
            fn()
        except Exception as e:                      # un contrôle ne doit jamais tout casser
            check(fn.__name__, WARN, f"contrôle impossible : {e}", "")

    icons = {OK: "[ OK ]", WARN: "[ ~~ ]", KO: "[ !! ]"}
    for statut, titre, detail, _ in _RESULTS:
        print(f"{icons[statut]}  {titre:<32} {detail}")

    bloquants = [r for r in _RESULTS if r[0] == KO]
    warns = [r for r in _RESULTS if r[0] == WARN]

    if bloquants:
        print("\n" + "-" * 74)
        print("  À CORRIGER AVANT LA DÉMO :")
        for _, titre, detail, fix in bloquants:
            print(f"\n  • {titre} — {detail}")
            if fix:
                print(f"    → {fix}")
    if warns:
        print("\n" + "-" * 74)
        print("  POINTS DE VIGILANCE (non bloquants) :")
        for _, titre, detail, fix in warns:
            print(f"\n  • {titre} — {detail}")
            if fix:
                print(f"    → {fix}")

    print("\n" + "=" * 74)
    if bloquants:
        print(f"  RÉSULTAT : {len(bloquants)} point(s) BLOQUANT(s), "
              f"{len(warns)} vigilance(s). Corrigez avant de démarrer.")
    else:
        print(f"  RÉSULTAT : prêt pour la démo ✓  ({len(warns)} point(s) de vigilance)")
    print("=" * 74 + "\n")
    return 1 if bloquants else 0


if __name__ == "__main__":
    sys.exit(main())
