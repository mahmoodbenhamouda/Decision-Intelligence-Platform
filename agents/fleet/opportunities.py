"""
Scan d'opportunités (veille automatisable) :
  scrape les appels d'offres → les classe par pertinence (modèle entraîné) →
  les matche aux clients existants (NLP sémantique) → persiste le résultat
  horodaté dans output/opportunities.json.

Appelé par le scheduler (chaque matin) et lisible via l'API / la flotte.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE = Path(__file__).resolve().parents[2]
OUT = BASE / "output" / "opportunities.json"


def _client_names(limit: int = 500) -> List[str]:
    """Noms de clients (pour le matching sémantique) depuis l'entrepôt DuckDB."""
    try:
        import duckdb
        try:
            from ml_engine.analytics.kpi_engine import STORE_PATH
            db = str(STORE_PATH)
        except Exception:
            db = str(BASE / "output" / "analytics_store.duckdb")
        con = duckdb.connect(db, read_only=True)
        rows = con.execute(
            "SELECT DISTINCT client_name FROM dim_client "
            "WHERE client_name IS NOT NULL LIMIT ?", [limit]
        ).fetchall()
        con.close()
        return [r[0] for r in rows if r[0]]
    except Exception:
        return []


def scan_and_save(max_items: int = 30, threshold: float = 0.5) -> Dict[str, Any]:
    """Exécute le scan complet et sauvegarde le résultat. Renvoie le dict sauvegardé."""
    from agents.fleet.scraper import scrape_tenders
    from ml_engine.nlp.tender_relevance import predict_relevance
    try:
        from ml_engine.nlp.tender_matcher import match_candidates
    except Exception:
        match_candidates = None

    items = scrape_tenders(max_items=max_items)
    probs = predict_relevance([it["title"] for it in items]) if items else []
    clients = _client_names()

    opportunites: List[Dict[str, Any]] = []
    for it, p in zip(items, probs):
        if p >= threshold:
            cli, cs = (None, 0.0)
            if match_candidates and clients:
                cli, cs = match_candidates(it["title"], clients, threshold=0.0)
            opportunites.append({
                "title": it["title"],
                "pertinence": round(float(p), 3),
                "client_match": cli if cs >= 0.35 else None,
                "client_score": round(float(cs), 3),
                "source": it.get("source"),
                "date": it.get("date"),
                "url": it.get("url"),
            })
    opportunites.sort(key=lambda o: o["pertinence"], reverse=True)

    # accuracy du modèle (pour l'afficher côté UI)
    acc = None
    try:
        m = BASE / "reports" / "tender_relevance_metrics.json"
        acc = json.loads(m.read_text(encoding="utf-8")).get("accuracy")
    except Exception:
        pass

    data = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "n_scanned": len(items),
        "n_relevant": len(opportunites),
        "model_accuracy": acc,
        "opportunities": opportunites,
    }
    try:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return data


def load_latest() -> Optional[Dict[str, Any]]:
    """Lecture rapide (sans scraper) du dernier scan sauvegardé."""
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        return None


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    d = scan_and_save()
    print(f"[opportunités] {d['n_relevant']}/{d['n_scanned']} pertinents "
          f"(accuracy {d.get('model_accuracy')}) → {OUT}")
    for o in d["opportunities"][:8]:
        match = f" · client: {o['client_match']} ({o['client_score']})" if o["client_match"] else ""
        print(f"  [{o['pertinence']}] {o['title'][:80]}{match}")
