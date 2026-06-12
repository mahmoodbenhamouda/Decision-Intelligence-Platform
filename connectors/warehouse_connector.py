"""
connectors/warehouse_connector.py
=================================
Connecteur unifié pour le Data Warehouse en étoile.
Utilise un cache en mémoire (Singleton) pour éviter les rechargements coûteux.
"""

from __future__ import annotations

import warnings
from typing import Dict, Optional

import pandas as pd

from config.settings import settings

try:
    from ml_engine.preprocessing.data_preparation import prepare_data_layer
    HAS_PREPARATION = True
except ImportError:
    HAS_PREPARATION = False


class WarehouseConnector:
    """Singleton pour gérer l'accès au Data Warehouse."""
    _instance: Optional[WarehouseConnector] = None
    _warehouse: Optional[Dict[str, pd.DataFrame]] = None

    def __new__(cls) -> WarehouseConnector:
        if cls._instance is None:
            cls._instance = super(WarehouseConnector, cls).__new__(cls)
        return cls._instance

    def load(self, force_reload: bool = False) -> Dict[str, pd.DataFrame]:
        """Charge le warehouse depuis les fichiers de données brutes."""
        if self._warehouse is not None and not force_reload:
            return self._warehouse

        if not HAS_PREPARATION:
            warnings.warn("data_preparation introuvable. Retourne warehouse vide.")
            self._warehouse = {}
            return self._warehouse

        print("[WarehouseConnector] Chargement complet du Data Warehouse...")
        try:
            result = prepare_data_layer(data_dir=settings.data_dir)
            # prepare_data_layer returns a tuple (tables_clean, warehouse_tables)
            if isinstance(result, tuple) and len(result) == 2:
                tables_clean, warehouse_tables = result
                # Merge both: raw cleaned tables + DWH star-schema tables
                self._warehouse = {**tables_clean, **warehouse_tables}
            else:
                # Fallback if signature changes
                self._warehouse = result if isinstance(result, dict) else {}
            print(f"[WarehouseConnector] Warehouse chargé avec succès ({len(self._warehouse)} tables)")
        except Exception as e:
            print(f"[WarehouseConnector] Erreur de chargement : {e}")
            self._warehouse = {}
            
        return self._warehouse

    def get_table(self, table_name: str) -> Optional[pd.DataFrame]:
        """Retourne une table spécifique."""
        if self._warehouse is None:
            self.load()
        return self._warehouse.get(table_name)
        
    def describe(self) -> str:
        """Décrit le schéma du warehouse."""
        if self._warehouse is None:
            self.load()
            
        if not self._warehouse:
            return "Warehouse vide."
            
        lines = ["Schéma du Data Warehouse :"]
        for name, df in self._warehouse.items():
            lines.append(f"- Table '{name}' : {len(df)} lignes, {len(df.columns)} colonnes.")
            cols = list(df.columns[:10])
            if len(df.columns) > 10: cols.append("...")
            lines.append(f"  Colonnes : {', '.join(cols)}")
        return "\n".join(lines)


def get_warehouse(force_reload: bool = False) -> Dict[str, pd.DataFrame]:
    """Helper pour récupérer le warehouse via le singleton."""
    return WarehouseConnector().load(force_reload=force_reload)
