"""Ouvre l'interface web de DuckDB sur l'entrepôt, en LECTURE SEULE.

    python scripts/voir_base.py

Puis http://localhost:4213 — les tables sont sous la base « erp »
(ex. SELECT * FROM erp.factures_importees).

La base est rattachée à une connexion en mémoire : l'interface peut y écrire
son propre état (_duckdb_ui) sans jamais pouvoir modifier l'entrepôt, et l'API
peut continuer à enregistrer des factures pendant la consultation.
"""
from pathlib import Path

import duckdb

BASE = Path(__file__).resolve().parents[1] / "output" / "analytics_store.duckdb"

con = duckdb.connect()
con.execute(f"ATTACH '{BASE.as_posix()}' AS erp (READ_ONLY)")
con.execute("USE erp")
con.execute("CALL start_ui()")
print(f"Base : {BASE}")
print("Interface : http://localhost:4213  (tables sous « erp »)")
input("Entrée pour fermer l'interface... ")
