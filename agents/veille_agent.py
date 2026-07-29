"""
agents/veille_agent.py
======================
Agent de VEILLE EXTERNE — collecte des signaux hors de l'ERP pour enrichir la
décision (l'agent finance reste le superviseur ; celui-ci est un agent
spécialisé qu'il peut mobiliser).

Sources (extensibles) :
  - FX    : taux de change TND/EUR–USD (les réactifs sont importés en devise → le
            change impacte directement le coût des achats et la marge).
  - News  : appels d'offres / marchés publics (TUNEPS) du domaine diagnostic.
  - Macro : contexte économique (inflation, budget santé) via la Banque Mondiale.

Conçu pour être EXTENSIBLE : chaque source est une classe `Source` (fetch →
dict). Pour ajouter une source, il suffit d'ajouter une classe et de
l'enregistrer dans `AgentVeille.sources` + `collect()`.

Utilisation :
    python -m agents.veille_agent      # rafraîchit market_intel.json (nécessite Internet)

Le dashboard/superviseur lisent ensuite `output/market_intel.json` (rapide,
sans réseau) via `load_market_intel()`.
"""

from __future__ import annotations

import email.utils
import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _http_get(url: str, timeout: int = 12, retries: int = 2, backoff: float = 1.5) -> bytes:
    """GET robuste : plusieurs tentatives avec back-off exponentiel (résilient aux
    coupures réseau / rate-limits transitoires). Lève la dernière exception si échec."""
    last: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "veille-agent/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt < retries:
                time.sleep(backoff ** attempt)
    raise last if last else RuntimeError("échec HTTP inconnu")


def _parse_date(raw: str) -> Optional[datetime]:
    """Parse une date RFC-822 (flux RSS) en datetime timezone-aware, sinon None."""
    if not raw:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(raw)
        if dt and dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


try:
    from config.settings import settings
    OUTPUT_DIR = Path(settings.output_dir)
except Exception:  # pragma: no cover
    OUTPUT_DIR = Path(__file__).resolve().parents[1] / "output"

MARKET_FILE = OUTPUT_DIR / "market_intel.json"
HISTORY_FILE = OUTPUT_DIR / "market_intel_history.json"


# ─────────────────────────────────────────────────────────────────────────────
# SOURCES (extensibles) — chacune renvoie un petit dict ou None si indisponible
# ─────────────────────────────────────────────────────────────────────────────
class Source:
    name = "source"

    def fetch(self) -> Optional[Dict[str, Any]]:  # pragma: no cover - interface
        raise NotImplementedError


class FXSource(Source):
    """Taux de change : combien de TND pour 1 USD et 1 EUR. API gratuites, sans clé."""
    name = "fx"
    ENDPOINTS = [
        "https://open.er-api.com/v6/latest/USD",
        "https://api.exchangerate.host/latest?base=USD&symbols=TND,EUR",
    ]

    def fetch(self) -> Optional[Dict[str, Any]]:
        for url in self.ENDPOINTS:
            try:
                data = json.loads(_http_get(url).decode("utf-8"))
                rates = data.get("rates") or {}
                if "TND" in rates and "EUR" in rates:
                    usd_tnd = float(rates["TND"])              # base USD → TND par USD
                    eur_tnd = float(rates["TND"]) / float(rates["EUR"])
                    return {"usd_tnd": round(usd_tnd, 4), "eur_tnd": round(eur_tnd, 4),
                            "provider": url.split("/")[2], "official": False}
            except Exception:
                continue
        return None


class NewsSource(Source):
    """Veille commerciale : appels d'offres / actualités du marché diagnostic via flux RSS.
    Utilise Google News RSS (gratuit, sans clé, conçu pour être consommé).
    Requête configurable via la variable d'env VEILLE_NEWS_QUERY."""
    name = "news"
    # Requête affinée : marchés publics tunisiens (TUNEPS) dans le domaine du
    # diagnostic médical. Surchargée via VEILLE_NEWS_QUERY si besoin.
    DEFAULT_QUERY = (
        '(TUNEPS OR "appel d\'offres" OR "marché public" OR "consultation") '
        '(diagnostic OR réactif OR laboratoire OR biologie OR "matériel médical" OR hospitalier) '
        'Tunisie')

    MAX_AGE_DAYS = 75  # on écarte les annonces trop anciennes (appel d'offres périmé)
    DOMAIN_TERMS = (
        "REACTIF", "REACTIFS", "LABORATOIRE", "BIOLOGIE", "BIOCHIMIE", "IMMUNOLOG",
        "HEMATOLOG", "PCR", "ELISA", "AUTOMATE", "ANALYSEUR", "DIAGNOSTIC IN VITRO",
        "DISPOSITIF MEDICAL", "EQUIPEMENT MEDICAL", "CONSOMMABLE MEDICAL", "CHU", "HOSPITALIER",
    )

    FALLBACK_OPPORTUNITIES = [
        {
            "title": "TUNEPS - Fourniture de reactifs de laboratoire pour etablissements hospitaliers",
            "link": "https://www.tuneps.tn/",
            "source": "TUNEPS",
            "date": "",
            "date_iso": None,
            "fallback": True,
        },
        {
            "title": "TUNEPS - Acquisition d'automates d'hematologie et consommables de diagnostic in vitro",
            "link": "https://www.tuneps.tn/",
            "source": "TUNEPS",
            "date": "",
            "date_iso": None,
            "fallback": True,
        },
        {
            "title": "TUNEPS - Consultation pour equipements de biologie medicale et reactifs hospitaliers",
            "link": "https://www.tuneps.tn/",
            "source": "TUNEPS",
            "date": "",
            "date_iso": None,
            "fallback": True,
        },
    ]

    def fetch(self) -> Optional[List[Dict[str, Any]]]:
        query = os.environ.get("VEILLE_NEWS_QUERY", self.DEFAULT_QUERY)
        try:
            q = urllib.parse.quote(query)
            url = f"https://news.google.com/rss/search?q={q}&hl=fr&gl=TN&ceid=TN:fr"
            root = ET.fromstring(_http_get(url).decode("utf-8"))
        except Exception:
            return [dict(item) for item in self.FALLBACK_OPPORTUNITIES]
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.MAX_AGE_DAYS)
        items: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for it in root.findall(".//item"):
            title = (it.findtext("title") or "").strip()
            source = (it.findtext("source") or "").strip()
            if source and title.endswith(f" - {source}"):
                title = title[: -(len(source) + 3)].strip()
            if not title:
                continue
            # dédoublonnage sur titre normalisé
            key = re.sub(r"[^a-z0-9]+", "", title.lower())[:60]
            if key in seen:
                continue
            # filtre de fraîcheur (les avis trop vieux sont clos)
            dt = _parse_date(it.findtext("pubDate") or "")
            if dt and dt < cutoff:
                continue
            seen.add(key)
            items.append({
                "title": title,
                "link": (it.findtext("link") or "").strip(),
                "date": (it.findtext("pubDate") or "").strip(),
                "date_iso": dt.isoformat() if dt else None,
                "source": source,
            })
            if len(items) >= 12:
                break
        relevant = [item for item in items if any(term in item["title"].upper() for term in self.DOMAIN_TERMS)]
        return relevant or [dict(item) for item in self.FALLBACK_OPPORTUNITIES]


class MacroSource(Source):
    """Contexte macro-économique (API officielle Banque Mondiale, gratuite, sans clé).
    Deux indicateurs pertinents pour un distributeur de diagnostics :
      - inflation (prix à la consommation, %)
      - dépense courante de santé (% du PIB) → proxy du budget santé public."""
    name = "macro"
    COUNTRY = "TUN"
    INDICATORS = {
        "inflation": "FP.CPI.TOTL.ZG",
        "sante_pct_pib": "SH.XPD.CHEX.GD.ZS",
    }

    def fetch(self) -> Optional[Dict[str, Any]]:
        out: Dict[str, Any] = {}
        for key, code in self.INDICATORS.items():
            url = (f"https://api.worldbank.org/v2/country/{self.COUNTRY}"
                   f"/indicator/{code}?format=json&per_page=10")
            try:
                data = json.loads(_http_get(url).decode("utf-8"))
                series = data[1] if isinstance(data, list) and len(data) > 1 else []
                for row in series:  # trié du plus récent au plus ancien
                    if row.get("value") is not None:
                        out[key] = {"value": round(float(row["value"]), 2), "year": row.get("date")}
                        break
            except Exception:
                continue
        if out:
            out["provider"] = "api.worldbank.org"
            out["official"] = True
        return out or None


# ─────────────────────────────────────────────────────────────────────────────
# AGENT
# ─────────────────────────────────────────────────────────────────────────────
class AgentVeille:
    name = "Agent Veille externe"
    version = "2.0"

    def __init__(self) -> None:
        self.sources: List[Source] = [FXSource(), NewsSource(), MacroSource()]

    def _load_history(self) -> List[Dict[str, Any]]:
        if HISTORY_FILE.exists():
            try:
                return json.load(open(HISTORY_FILE, encoding="utf-8"))
            except Exception:
                return []
        return []

    def collect(self) -> Dict[str, Any]:
        """Interroge les sources, calcule des signaux décisionnels, persiste le résultat."""
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        out: Dict[str, Any] = {"timestamp": ts, "as_of": ts, "agent_version": self.version,
                               "fx": None, "signals": [], "sources_status": {}}
        history = self._load_history()

        # ── Source FX ────────────────────────────────────────────────────────
        fx = FXSource().fetch()
        out["sources_status"]["fx"] = "ok" if fx else "offline"
        if fx:
            prev_fx = None
            for h in reversed(history):
                if h.get("fx"):
                    prev_fx = h["fx"]
                    break
            if prev_fx and prev_fx.get("eur_tnd"):
                var = (fx["eur_tnd"] - prev_fx["eur_tnd"]) / prev_fx["eur_tnd"] * 100
                fx["eur_tnd_var_pct"] = round(var, 2)
                if var > 0.5:
                    out["signals"].append(
                        f"Dinar en baisse face à l'euro (+{var:.1f}%) → hausse du coût des achats, marge sous pression.")
                elif var < -0.5:
                    out["signals"].append(
                        f"Dinar en hausse face à l'euro ({var:.1f}%) → coût des achats allégé, marge favorisée.")
                else:
                    out["signals"].append("Change EUR/TND stable → pas d'effet notable sur la marge.")
            else:
                out["signals"].append("Taux de change collectés (référence initiale enregistrée).")
            out["fx"] = fx
            history.append({"timestamp": ts, "fx": fx})
            json.dump(history[-365:], open(HISTORY_FILE, "w", encoding="utf-8"), ensure_ascii=False)
        else:
            out["signals"].append("Données de change indisponibles (hors ligne ou API injoignable).")

        # ── Source Veille commerciale (appels d'offres / actualités marché) ──
        news = NewsSource().fetch()
        has_fallback = bool(news and any(n.get("fallback") for n in news))
        out["sources_status"]["news"] = "degraded" if has_fallback else ("ok" if news else "offline")
        if news:
            out["news"] = news
            if has_fallback:
                out["signals"].append(
                    f"{len(news)} piste(s) commerciale(s) de repli chargée(s) pour garder la veille exploitable ; source externe à rafraîchir.")
            else:
                out["signals"].append(
                    f"{len(news)} actualité(s)/opportunité(s) détectée(s) sur le marché diagnostic (appels d'offres).")
        else:
            out["news"] = []

        # ── Source Macro (contexte économique / budget santé — Banque Mondiale) ──
        macro = MacroSource().fetch()
        out["sources_status"]["macro"] = "ok" if macro else "offline"
        if macro:
            out["macro"] = macro
            parts: List[str] = []
            if macro.get("inflation"):
                parts.append(f"inflation {macro['inflation']['value']}% ({macro['inflation']['year']})")
            if macro.get("sante_pct_pib"):
                parts.append(
                    f"dépense de santé {macro['sante_pct_pib']['value']}% du PIB ({macro['sante_pct_pib']['year']})")
            if parts:
                out["signals"].append("Contexte macro : " + " · ".join(parts) + ".")
        else:
            out["macro"] = None

        json.dump(out, open(MARKET_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        return out


def load_market_intel() -> Optional[Dict[str, Any]]:
    """Lecture rapide (sans réseau) du dernier résultat de veille, pour le dashboard."""
    if MARKET_FILE.exists():
        try:
            return json.load(open(MARKET_FILE, encoding="utf-8"))
        except Exception:
            return [dict(item) for item in self.FALLBACK_OPPORTUNITIES]
    return None


veille_agent = AgentVeille()


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print("[veille] Collecte des signaux externes...")
    res = veille_agent.collect()
    print(f"[veille] FX : {res.get('fx')}")
    for s in res.get("signals", []):
        print(f"[veille] Signal : {s}")
    print(f"[veille] Ecrit dans : {MARKET_FILE}")





