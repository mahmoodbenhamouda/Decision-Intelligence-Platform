"""Échéancier des factures importées par OCR : ce qu'il faudra PAYER (achats) et ENCAISSER…"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from .importer import _assurer_schema, _connect, _table_existe

DEJA_DANS_ERP = ("rapprochee", "doublon_probable")
DELAI_DEFAUT = 30


def _delais(con) -> Dict[str, Any]:
    """Délais médians : par fournisseur, par client, et globaux."""
    out = {"achat": {}, "vente": {}, "achat_global": None, "vente_global": None}
    for sens, table, code, nom in (("achat", "purchases", "fournisseur_code", "fournisseur"),
                                   ("vente", "sales", "client", "client_name")):
        if not _table_existe(con, table):
            continue
        filtre = "payment_delay_days BETWEEN 0 AND 365"
        for c, n, m in con.execute(f"""SELECT trim({code}), max({nom}), median(payment_delay_days)
                                       FROM {table} WHERE {filtre} GROUP BY 1""").fetchall():
            if c:
                out[sens][c] = int(round(m))
        g = con.execute(f"SELECT median(payment_delay_days) FROM {table} WHERE {filtre}").fetchone()[0]
        out[f"{sens}_global"] = int(round(g)) if g is not None else None
    return out


def _mois(d: date) -> str:
    return d.strftime("%Y-%m")


def echeancier(aujourd_hui: Optional[date] = None, sens: Optional[str] = None,
               client_code: Optional[str] = None) -> Dict[str, Any]:
    """Échéancier des factures OCR non réglées et absentes de l'ERP."""
    auj = aujourd_hui or date.today()
    con = _connect()
    try:
        _assurer_schema(con)
        delais = _delais(con)
        conds = ["reglee_le IS NULL",
                 f"coalesce(rapprochement_statut, 'non_rapprochee') NOT IN {DEJA_DANS_ERP}"]
        args: List[Any] = []
        if sens:
            conds.append("coalesce(sens, 'vente') = ?"); args.append(sens)
        if client_code:
            conds.append("client_code = ?"); args.append(client_code)
        rows = con.execute(f"""
            SELECT id, numero, coalesce(sens, 'vente'), coalesce(fournisseur, client_name),
                   coalesce(fournisseur_code, client_code), date, echeance, ttc, net_a_payer,
                   retenue_source, coalesce(rapprochement_statut, 'non_rapprochee')
            FROM factures_importees WHERE {' AND '.join(conds)}""", args).fetchall()
    finally:
        con.close()

    lignes = []
    for i, num, s, tiers, code, d, ech, ttc, net, rs, rappro in rows:
        montant = float(net if net is not None else (ttc or 0))
        if ech is not None:
            echeance, source, delai = ech, "lue", None
        else:
            delai = delais[s].get((code or "").strip())
            source = "delai_tiers"
            if delai is None:
                delai = delais[f"{s}_global"] or DELAI_DEFAUT
                source = "delai_moyen"
            base = d or auj
            echeance = base + timedelta(days=delai)
            if d is None:
                source += "_sans_date"
        retard = (auj - echeance).days
        lignes.append({
            "id": i, "numero": num, "sens": s, "tiers": tiers, "tiers_code": code,
            "date": d.isoformat() if d else None, "echeance": echeance.isoformat(),
            "source_echeance": source, "delai_jours": delai,
            "montant_dt": round(montant, 3), "retenue_source_dt": rs,
            "rapprochement_statut": rappro,
            "statut": "en_retard" if retard > 0 else "a_venir",
            "jours_de_retard": max(0, retard),
        })
    lignes.sort(key=lambda x: (x["echeance"], x["sens"]))

    par_mois: Dict[str, Dict[str, Any]] = {}
    for l in lignes:
        cle = "en_retard" if l["statut"] == "en_retard" else _mois(date.fromisoformat(l["echeance"]))
        m = par_mois.setdefault(cle, {"periode": cle, "decaissements_dt": 0.0,
                                      "encaissements_dt": 0.0, "n": 0, "n_echeances_deduites": 0})
        m["decaissements_dt" if l["sens"] == "achat" else "encaissements_dt"] += l["montant_dt"]
        m["n"] += 1
        m["n_echeances_deduites"] += l["source_echeance"] != "lue"
    mois = sorted(par_mois.values(), key=lambda m: ("0" if m["periode"] == "en_retard" else "1") + m["periode"])
    for m in mois:
        m["decaissements_dt"] = round(m["decaissements_dt"], 3)
        m["encaissements_dt"] = round(m["encaissements_dt"], 3)
        m["solde_dt"] = round(m["encaissements_dt"] - m["decaissements_dt"], 3)

    tot = lambda s, st=None: round(sum(l["montant_dt"] for l in lignes
                                       if l["sens"] == s and (st is None or l["statut"] == st)), 3)
    return {
        "au": auj.isoformat(),
        "a_payer_dt": tot("achat"), "a_encaisser_dt": tot("vente"),
        "a_payer_en_retard_dt": tot("achat", "en_retard"),
        "a_encaisser_en_retard_dt": tot("vente", "en_retard"),
        "n_factures": len(lignes),
        "n_echeances_deduites": sum(l["source_echeance"] != "lue" for l in lignes),
        "mois": mois, "factures": lignes,
        "note": ("Factures scannées, non réglées, ABSENTES de la comptabilité (celles qu'il contient "
                 "déjà sont exclues pour ne pas les compter deux fois). Montant = net à payer. "
                 "Échéance lue sur la facture, ou déduite du délai habituel du tiers."),
    }


def marquer_reglee(facture_id: int, le: Optional[date] = None,
                   annuler: bool = False) -> Dict[str, Any]:
    """Marque une facture importée comme réglée (ou annule ce marquage)."""
    con = _connect()
    try:
        _assurer_schema(con)
        r = con.execute("SELECT numero FROM factures_importees WHERE id = ?", [facture_id]).fetchone()
        if not r:
            return {"ok": False, "erreur": f"facture {facture_id} introuvable"}
        quand = None if annuler else (le or date.today())
        con.execute("UPDATE factures_importees SET reglee_le = ? WHERE id = ?", [quand, facture_id])
        return {"ok": True, "id": facture_id, "numero": r[0],
                "reglee_le": quand.isoformat() if quand else None}
    finally:
        con.close()
