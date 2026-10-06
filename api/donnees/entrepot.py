"""Les quelques lectures directes que l'API fait dans l'entrepôt DuckDB, toutes en LECTURE SEULE."""

from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple

import duckdb


def _connexion() -> duckdb.DuckDBPyConnection:
    from ml_engine.analytics import kpi_engine
    return duckdb.connect(str(kpi_engine.STORE_PATH), read_only=True)


def codes_clients() -> Set[str]:
    """Codes clients présents dans les ventes, normalisés (sans espaces, en majuscules)."""
    con = _connexion()
    try:
        rows = con.execute("SELECT DISTINCT trim(client) FROM sales "
                           "WHERE client IS NOT NULL").fetchall()
    finally:
        con.close()
    return {str(r[0]).strip().upper() for r in rows}


def clients_principaux(limite: int = 100) -> List[Dict[str, Any]]:
    """Clients réels, par chiffre d'affaires décroissant."""
    con = _connexion()
    try:
        rows = con.execute(
            "SELECT client, max(client_name) nom, sum(ttc) ca, count(*) n "
            "FROM sales WHERE client IS NOT NULL GROUP BY client "
            "ORDER BY ca DESC LIMIT ?", [limite]).fetchall()
    finally:
        con.close()
    return [{"code": str(r[0]), "nom": str(r[1] or r[0]).strip(),
             "ca": float(r[2] or 0), "factures": int(r[3] or 0)} for r in rows]


def factures_client(code: str, limite: int) -> Tuple[List[tuple], tuple]:
    """Factures d'un client, les plus récentes d'abord, et ses totaux."""
    con = _connexion()
    try:
        rows = con.execute(
            "SELECT strftime(date,'%Y-%m-%d') date, strftime(echeance,'%Y-%m-%d') echeance, "
            "ttc, payment_delay_days, mode_regl "
            "FROM sales WHERE trim(client) = trim(?) AND date IS NOT NULL "
            "ORDER BY date DESC, piece_no DESC, ent_id DESC LIMIT ?", [code, limite]).fetchall()
        totaux = con.execute(
            "SELECT count(*), coalesce(sum(ttc),0), "
            "coalesce(sum(CASE WHEN payment_delay_days > 60 THEN ttc END),0) "
            "FROM sales WHERE trim(client) = trim(?)", [code]).fetchone()
    finally:
        con.close()
    return rows, totaux
