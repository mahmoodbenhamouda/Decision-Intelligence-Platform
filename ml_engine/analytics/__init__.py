"""Analytics package : moteur de KPIs financiers, lecteur de l'entrepôt DuckDB.

L'entrepôt lui-même est construit par l'ETL (`etl/`, `python -m etl.construire`).
"""
from .kpi_engine import compute_dashboard, get_filter_options  # noqa: F401
