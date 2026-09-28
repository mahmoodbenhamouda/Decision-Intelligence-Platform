"""
etl/sources.py
==============
Catalogue des sources : les exports CSV de l'ERP, et la façon de les lire.

C'est le seul endroit du projet qui nomme un fichier source. L'ETL lit les CSV
à travers `lecture()` ; les trois modules d'apprentissage qui construisent
encore leur jeu d'entraînement sur la source brute (décrochage, crédit, ancienne
prévision de demande) y prennent leur chemin par `chemin()`.

Lecture défensive : toutes les colonnes arrivent en texte (`all_varchar`), les
lignes illisibles sont ignorées plutôt que de faire échouer l'import, et le
typage est fait explicitement ensuite (`etl/regles.py`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

try:
    from config.settings import settings
    DOSSIER_SOURCES = Path(settings.data_dir)
    DOSSIER_SORTIE = Path(settings.output_dir)
    DOSSIER_RAPPORTS = Path(settings.reports_dir)
except Exception:  # pragma: no cover - hors application
    DOSSIER_SOURCES = Path(__file__).resolve().parents[1] / "data_pfe"
    DOSSIER_SORTIE = Path(__file__).resolve().parents[1] / "output"
    DOSSIER_RAPPORTS = Path(__file__).resolve().parents[1] / "reports"

#: L'entrepôt construit par l'ETL et lu par toute l'application.
ENTREPOT = Path(os.environ.get("ANALYTICS_STORE_PATH",
                               DOSSIER_SORTIE / "analytics_store.duckdb"))


@dataclass(frozen=True)
class Source:
    fichier: str
    description: str
    # Lignes examinées pour détecter le format (séparateur, guillemets).
    # Toutes les colonnes étant lues en texte, ce nombre n'influe pas sur les
    # types ; il est conservé à l'identique de l'historique du projet.
    echantillon: int = 8000


SOURCES: Dict[str, Source] = {
    "ventes_entetes": Source("Facture_vente_ent_v.csv",
                             "factures et avoirs de vente : client, dates, HT/TTC, mode de règlement"),
    "ventes_lignes": Source("ZZ_Facture_vente_mouv.csv",
                            "lignes des factures de vente : produit, quantité, montant, coût de revient"),
    "achats_entetes": Source("Facture_achat_ent_v.csv",
                             "factures d'achat : fournisseur, dates, HT/TVA/TTC"),
    "achats_lignes": Source("Facture_achat_mouv_v.csv",
                            "lignes des factures d'achat : produit, quantité, indicateur de mouvement de stock",
                            echantillon=20000),
    "devis": Source("Devis_vente_ent_vv.csv", "devis de vente et leur état ERP"),
    "livraisons": Source("Gsl_vente_bl_entete.csv", "bons de livraison"),
    "gsl_factures": Source("Gsl_vente_fa_entete.csv",
                           "référentiel commercial : noms et villes des clients, dépôts"),
    "fournisseurs": Source("Fournisseurs_v.csv", "référentiel des fournisseurs"),
}


def chemin(role: str, dossier: Path | None = None) -> Path:
    """Chemin du fichier d'une source."""
    return Path(dossier or DOSSIER_SOURCES) / SOURCES[role].fichier


def lecture(role: str, dossier: Path | None = None) -> str:
    """Expression SQL DuckDB qui lit une source, toutes colonnes en texte."""
    s = SOURCES[role]
    p = chemin(role, dossier).as_posix()
    return (f"read_csv_auto('{p}', sample_size={s.echantillon}, "
            f"ignore_errors=true, all_varchar=true)")


def sources_presentes(dossier: Path | None = None) -> bool:
    return any(chemin(r, dossier).exists() for r in SOURCES)
