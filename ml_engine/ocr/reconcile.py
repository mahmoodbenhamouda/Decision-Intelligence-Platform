"""RAPPROCHEMENT d'une facture scannée avec l'entrepôt analytique (DuckDB)."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

TOL_MONTANT_PCT = 0.01
TOL_MONTANT_ABS = 1.0
FENETRE_JOURS = 45


def _norm(s: str) -> str:
    """Normalise un nom pour la comparaison (accents, ponctuation, casse)."""
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _name_similarity(a: str, b: str) -> float:
    """Similarité 0-1 par mots communs (robuste aux ordres et abréviations)."""
    ta = {w for w in _norm(a).split() if len(w) > 2}
    tb = {w for w in _norm(b).split() if len(w) > 2}
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def _connect():
    import duckdb
    try:
        from ml_engine.analytics.kpi_engine import STORE_PATH
        path = str(STORE_PATH)
    except Exception:
        from pathlib import Path
        path = str(Path(__file__).resolve().parents[2] / "output" / "analytics_store.duckdb")
    return duckdb.connect(path, read_only=True)


SOURCES = {
    "vente": {"table": "sales", "code": "client", "nom": "client_name",
              "numero": "piece_no", "genre": "client"},
    "achat": {"table": "purchases", "code": "fournisseur_code", "nom": "fournisseur",
              "numero": "piece_externe", "genre": "fournisseur"},
}


def _norm_num(s: Optional[str]) -> str:
    """« FA-000975 » ≈ « fa 975 » : sans séparateurs, sans zéros de tête."""
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper()).lstrip("0")


def _fmt(x: float) -> str:
    return f"{x:,.3f}".replace(",", " ")


def reconcile_invoice(fields: Any, client_code: Optional[str] = None,
                      limit: int = 5, sens: str = "vente") -> Dict[str, Any]:
    """Rapproche une facture lue avec l'ERP : ventes (`sales`) ou achats (`purchases`)."""
    f = fields.to_dict() if hasattr(fields, "to_dict") else dict(fields or {})
    sens = sens if sens in SOURCES else "vente"
    cfg = SOURCES[sens]
    ttc = f.get("montant_ttc")
    d_str = f.get("date_facture")
    numero = (f.get("numero") or "").strip()
    tiers = ((f.get("client") or f.get("tiers")) if sens == "vente" else f.get("fournisseur")) or ""

    out: Dict[str, Any] = {
        "statut": "indetermine", "message": "", "candidats": [],
        "sens": sens, "genre_tiers": cfg["genre"],
        "montant_recherche": ttc, "date_recherchee": d_str, "numero_recherche": numero or None,
        "perimetre_client": client_code, "erp_jusqu_au": None, "recherche_par_numero": False,
    }
    if (ttc is None or ttc <= 0) and not _norm_num(numero):
        out["statut"] = "montant_absent"
        out["message"] = ("Ni montant TTC ni numéro exploitables : rapprochement "
                          "impossible. Vérifiez la qualité du scan.")
        return out

    d_ref: Optional[date] = None
    if d_str:
        try:
            d_ref = datetime.fromisoformat(str(d_str)[:10]).date()
        except Exception:
            d_ref = None
    tol = max(TOL_MONTANT_ABS, (ttc or 0) * TOL_MONTANT_PCT)

    try:
        con = _connect()
        t = cfg["table"]
        cols = {r[0] for r in con.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ?", [t]).fetchall()}
        col_num = cfg["numero"] if cfg["numero"] in cols else None
        out["recherche_par_numero"] = bool(col_num)
        fin = con.execute(f"SELECT max(date) FROM {t}").fetchone()[0]
        out["erp_jusqu_au"] = fin.isoformat() if fin else None

        select = (f"SELECT {cfg['code']}, {cfg['nom']}, strftime(date,'%Y-%m-%d'), "
                  f"strftime(echeance,'%Y-%m-%d'), ttc, ht, {col_num or 'NULL'}, piece_no "
                  f"FROM {t} WHERE ")
        portee, p_portee = [], []
        if client_code and sens == "vente":
            portee.append(f"trim({cfg['code']}) = trim(?)"); p_portee.append(client_code)

        lignes: Dict[tuple, tuple] = {}
        if col_num and _norm_num(numero):
            w = portee + [f"ltrim(regexp_replace(upper({col_num}), '[^A-Z0-9]', '', 'g'), '0') = ?"]
            for r in con.execute(select + " AND ".join(w) + " LIMIT 20",
                                 p_portee + [_norm_num(numero)]).fetchall():
                lignes[(r[7], r[0], r[2], r[4])] = r
        elargi = False
        if ttc:
            w = portee + ["ttc BETWEEN ? AND ?"]
            p = p_portee + [ttc - tol, ttc + tol]
            if d_ref:
                trouves = con.execute(select + " AND ".join(w + ["date BETWEEN ? AND ?"])
                                      + f" ORDER BY abs(ttc - {float(ttc)}) LIMIT 50",
                                      p + [d_ref - timedelta(days=FENETRE_JOURS),
                                           d_ref + timedelta(days=FENETRE_JOURS)]).fetchall()
                if not trouves:
                    elargi = True
                    trouves = con.execute(select + " AND ".join(w)
                                          + f" ORDER BY abs(ttc - {float(ttc)}) LIMIT 50", p).fetchall()
            else:
                trouves = con.execute(select + " AND ".join(w)
                                      + f" ORDER BY abs(ttc - {float(ttc)}) LIMIT 50", p).fetchall()
            for r in trouves:
                lignes.setdefault((r[7], r[0], r[2], r[4]), r)
        con.close()
    except Exception as e:
        out["statut"] = "entrepot_indisponible"
        out["message"] = f"Entrepôt analytique inaccessible : {e}"
        return out

    candidats: List[Dict[str, Any]] = []
    for code, nom, dd, ech, r_ttc, r_ht, num_erp, piece in lignes.values():
        ecart = abs(float(r_ttc or 0) - float(ttc or 0)) if ttc else None
        meme_numero = bool(col_num and num_erp and _norm_num(num_erp) == _norm_num(numero))
        score, raisons = 0.0, []
        if meme_numero:
            score += 40
            raisons.append(f"même numéro de facture ({num_erp})")
        if ecart is not None:
            score += 45 * max(0.0, 1 - (ecart / tol if tol else 1))
            raisons.append("montant identique" if ecart < 0.001 else f"écart de montant {ecart:.3f}")
        if d_ref and dd:
            try:
                delta = abs((datetime.fromisoformat(dd).date() - d_ref).days)
                score += 15 * max(0.0, 1 - delta / FENETRE_JOURS)
                raisons.append("même date" if delta == 0 else f"{delta} j d'écart")
            except Exception:
                pass
        sim = _name_similarity(tiers, nom or code or "")
        if sim > 0:
            score += 10 * sim
            raisons.append(f"nom similaire ({sim:.0%})")
        elif tiers and nom:
            raisons.append("autre tiers")
        candidats.append({
            "tiers_code": code, "tiers_nom": nom or code,
            "client_code": code, "client_nom": nom or code,
            "date": dd, "echeance": ech,
            "montant_ttc": float(r_ttc or 0), "montant_ht": float(r_ht or 0),
            "ecart_montant": round(ecart, 3) if ecart is not None else None,
            "numero_erp": piece, "numero_facture_erp": num_erp, "meme_numero": meme_numero,
            "similarite_nom": round(sim, 2),
            "score": round(min(100.0, score), 1),
            "explication": " · ".join(raisons),
        })
    candidats.sort(key=lambda c: c["score"], reverse=True)
    out["candidats"] = candidats[:limit]
    g = cfg["genre"]

    par_numero = [c for c in candidats if c["meme_numero"]]
    if par_numero:
        b = par_numero[0]
        memes = [c for c in par_numero if c["tiers_code"] == b["tiers_code"]]
        identiques = [c for c in memes if c["ecart_montant"] is not None and c["ecart_montant"] < 0.01]
        partage = (f" (le numéro figure sur {len(memes)} pièces de l'ERP)" if len(memes) > 1 else "")
        somme = sum(c["montant_ttc"] for c in memes)
        if len(identiques) >= 2:
            out["statut"] = "doublon_probable"
            out["message"] = (f"Le numéro {numero} figure {len(identiques)} fois en comptabilité chez "
                              f"{b['tiers_nom']} avec le même montant ({_fmt(identiques[0]['montant_ttc'])}) : "
                              "doublon de saisie probable.")
        elif identiques:
            c = identiques[0]
            out["statut"] = "rapprochee"
            out["message"] = (f"Facture retrouvée par son numéro : {c['tiers_nom']}, "
                              f"{_fmt(c['montant_ttc'])} le {c['date']}. Montants identiques." + partage)
        elif len(memes) > 1 and ttc and abs(somme - float(ttc)) < 0.01:
            out["statut"] = "rapprochee"
            out["message"] = (f"Facture retrouvée par son numéro, saisie en {len(memes)} pièces "
                              f"en comptabilité ({' + '.join(_fmt(c['montant_ttc']) for c in memes)} "
                              f"= {_fmt(somme)}).")
        else:
            out["statut"] = "ecart_detecte"
            out["message"] = (f"Même numéro {numero} dans l'ERP ({b['tiers_nom']}, {b['date']}), "
                              f"mais {_fmt(b['montant_ttc'])} dans l'ERP contre "
                              f"{_fmt(float(ttc or 0))} sur le document — litige à instruire." + partage)
        return out

    fin = datetime.fromisoformat(out["erp_jusqu_au"]).date() if out["erp_jusqu_au"] else None
    if d_ref and fin and d_ref > fin:
        out["statut"] = "hors_periode"
        out["candidats"] = []
        out["message"] = (f"Les écritures s'arrêtent au {fin:%d/%m/%Y} : impossible de dire si cette "
                          f"facture du {d_ref:%d/%m/%Y} a été saisie. À revérifier après la "
                          "prochaine mise à jour des écritures.")
        return out

    fiables = [c for c in candidats if not (tiers and c["similarite_nom"] == 0)]
    if not fiables:
        out["statut"] = "introuvable"
        base = f"Aucune facture de {_fmt(float(ttc or 0))} (± {_fmt(tol)})" if ttc else "Aucune facture"
        if sens == "achat":
            out["message"] = (base + f" de « {tiers or '?'} » dans vos achats. "
                              "Facture fournisseur NON SAISIE ? C'est une dette qui ne "
                              "figure pas en comptabilité — ou un montant mal lu.")
        else:
            out["message"] = (base + f" trouvée dans les ventes{' pour ce client' if client_code else ''}. "
                              "Facture non encore saisie, montant mal lu par l'OCR, ou tiers hors périmètre.")
        if candidats:
            out["message"] += (f" (Même montant chez « {candidats[0]['tiers_nom']} », "
                               f"un autre {g} : sans doute une autre facture.)")
        return out

    best = fiables[0]
    doublons = [c for c in fiables[1:]
                if c["ecart_montant"] is not None and c["ecart_montant"] < 0.01
                and c["tiers_code"] == best["tiers_code"]]
    if best["ecart_montant"] is not None and best["ecart_montant"] < 0.01:
        out["statut"] = "doublon_probable" if doublons else "rapprochee"
        out["message"] = (f"Facture retrouvée : {best['tiers_nom']} — {_fmt(best['montant_ttc'])} "
                          f"le {best['date']}. Montants identiques.")
        if doublons:
            out["message"] += (f" ⚠ {len(doublons) + 1} factures identiques ({g}, montant) : "
                               "doublon probable.")
    else:
        out["statut"] = "ecart_detecte"
        out["message"] = (f"Facture proche trouvée ({best['tiers_nom']}, {best['date']}) mais "
                          f"écart de {_fmt(best['ecart_montant'] or 0)} entre le document "
                          f"({_fmt(float(ttc or 0))}) et l'ERP ({_fmt(best['montant_ttc'])}) — à instruire.")
    if elargi:
        out["message"] += " (recherche élargie hors de la fenêtre de dates)"
    return out
