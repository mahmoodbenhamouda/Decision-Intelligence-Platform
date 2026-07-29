"""
Agent Scraper — récupération RÉELLE d'appels d'offres / signaux du secteur.

Sources (par ordre d'essai) :
  1. Google News RSS (requêtes ciblées marchés publics / diagnostic) — fiable, légal.
  2. (extensible) portail TUNEPS / agrégateurs — à brancher selon accès.
Repli automatique : un échantillon embarqué, pour que la démo tourne HORS LIGNE.

Sortie : liste de dicts {title, source, date, url}.
Chaque titre est ensuite classé par `ml_engine.nlp.tender_relevance` (pertinence)
et matché aux clients par `ml_engine.nlp.tender_matcher`.
"""

from __future__ import annotations

import ssl
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Dict, List

_UA = "Mozilla/5.0 (compatible; FinBotScraper/1.0)"
_TIMEOUT = 12

# Requêtes ciblées sur le domaine (diagnostic / labo / marchés publics santé)
_QUERIES = [
    "appel d'offres réactifs laboratoire Tunisie",
    "marché public diagnostic médical Tunisie",
    "appel d'offres CHU hôpital équipement laboratoire",
    "acquisition automate analyses médicales appel d'offres",
]

# Repli hors-ligne (titres réalistes ; utilisé si aucun réseau)
_FALLBACK: List[Dict[str, Any]] = [
    {"title": "Acquisition de réactifs de biochimie pour le CHU Farhat Hached", "source": "échantillon", "date": "", "url": ""},
    {"title": "Fourniture d'un automate d'hématologie avec consommables", "source": "échantillon", "date": "", "url": ""},
    {"title": "Marché de réactifs d'immuno-analyse pour l'hôpital régional de Gabès", "source": "échantillon", "date": "", "url": ""},
    {"title": "Acquisition de tests PCR et extraction d'acides nucléiques", "source": "échantillon", "date": "", "url": ""},
    {"title": "Travaux de réfection de la voirie municipale", "source": "échantillon", "date": "", "url": ""},
    {"title": "Fourniture de mobilier de bureau pour la direction régionale", "source": "échantillon", "date": "", "url": ""},
    {"title": "Acquisition de tubes de prélèvement pour la banque du sang", "source": "échantillon", "date": "", "url": ""},
    {"title": "Marché de nettoyage des locaux administratifs", "source": "échantillon", "date": "", "url": ""},
]


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        ctx = ssl.create_default_context()
        return urllib.request.urlopen(req, timeout=_TIMEOUT, context=ctx).read()
    except Exception:
        # Repli : contexte SSL non vérifié (certains environnements Windows)
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return urllib.request.urlopen(req, timeout=_TIMEOUT, context=ctx).read()


def _scrape_google_news(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=fr&gl=TN&ceid=TN:fr"
    root = ET.fromstring(_http_get(url).decode("utf-8", errors="replace"))
    items: List[Dict[str, Any]] = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        if not title:
            continue
        items.append({
            "title": title,
            "source": "Google News",
            "date": (it.findtext("pubDate") or "").strip(),
            "url": (it.findtext("link") or "").strip(),
        })
        if len(items) >= limit:
            break
    return items


def scrape_tenders(max_items: int = 25) -> List[Dict[str, Any]]:
    """Récupère des appels d'offres / actus du secteur. Repli hors-ligne si besoin."""
    seen = set()
    out: List[Dict[str, Any]] = []
    for q in _QUERIES:
        try:
            for it in _scrape_google_news(q):
                key = it["title"].lower()[:80]
                if key not in seen:
                    seen.add(key)
                    out.append(it)
        except Exception:
            continue
        if len(out) >= max_items:
            break
    if not out:                      # aucun réseau → démo hors ligne
        out = list(_FALLBACK)
    return out[:max_items]


# ── CLI ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    items = scrape_tenders()
    print(f"[scraper] {len(items)} élément(s) — {datetime.now():%Y-%m-%d %H:%M}\n")
    for it in items:
        print(f"  · ({it['source']}) {it['title'][:90]}")
