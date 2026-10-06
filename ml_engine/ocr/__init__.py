"""Service OCR transversal de la plateforme."""

from .engine import OCRResult, ocr_document, ocr_available  # noqa: F401
from .importer import (factures_importees, importer_facture,  # noqa: F401
                       rapprocher_client, rapprocher_fournisseur, stats_import,
                       nettoyer_saisie, comparer, rerapprocher_imports)
from .entreprise import identite, enregistrer_identite, detecter_sens  # noqa: F401
from .echeancier import echeancier, marquer_reglee  # noqa: F401
from .apprentissage import mesure_production  # noqa: F401
from .invoice import InvoiceFields, parse_invoice  # noqa: F401
from .reconcile import reconcile_invoice  # noqa: F401

__all__ = [
    "OCRResult", "ocr_document", "ocr_available",
    "InvoiceFields", "parse_invoice", "reconcile_invoice",
    "importer_facture", "rapprocher_client", "factures_importees", "stats_import",
    "rapprocher_fournisseur", "nettoyer_saisie", "comparer",
    "identite", "enregistrer_identite", "detecter_sens",
]
