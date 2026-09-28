"""Ajoute ou corrige des annotations (vérité terrain).

Usage : python evaluation_ocr/preparation/annoter.py '{"d115": {"type": "facture", "numero": "F12",
         "date": "2025-12-01", "fournisseur": "...", "client": "...", "devise": "TND",
         "total_ht": 100.0, "total_tva": 19.0, "timbre": 1.0, "total_ttc": 120.0,
         "net_a_payer": 120.0, "manuscrite": false, "certitude": "sure", "note": ""}}'
Documents hors facture : {"type": "ticket_caisse", "exclu": true}
"""
import json, sys, os
F = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "layoutlmv3", "travail", "annotations.json")
a = json.load(open(F)) if os.path.exists(F) else {}
for doc, v in json.loads(sys.argv[1]).items():
    a[doc] = v
json.dump(a, open(F, "w"), ensure_ascii=False, indent=1)
print(len(a), "documents annotés")
