"""Ouvre l'interface web de DuckDB sur l'entrepôt, en LECTURE SEULE."""
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
