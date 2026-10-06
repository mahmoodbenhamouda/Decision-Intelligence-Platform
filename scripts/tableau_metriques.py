"""Tableau comparatif de TOUS les modules, lu dans les rapports — jamais recopié."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _pct(v):
    return "—" if v is None else f"{v * 100:.1f} %"


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    from ml_engine import passerelle as pw

    print("| Module | Nature | Statut | Métrique hors période | Accuracy | Classe majoritaire "
          "| Balanced accuracy | F1 | MCC |")
    print("|---|---|---|---|---|---|---|---|---|")
    for c in pw.tableau_des_modeles():
        cl = c.get("classification") or {}
        m = c.get("metrique")
        met = (f"{c.get('metrique_nom')} {m:.4f}" if isinstance(m, float) and m <= 1
               else f"{c.get('metrique_nom')} {m}" if m is not None else "—")
        statut = "servi" if c.get("servi") else "retiré" if c.get("retire") else "refusé"
        print(f"| {c.get('libelle')} | {c.get('nature')} | {statut} | {met} | "
              f"{_pct(cl.get('accuracy'))} | {_pct(cl.get('accuracy_classe_majoritaire'))} | "
              f"{_pct(cl.get('balanced_accuracy'))} | "
              f"{'—' if cl.get('f1') is None else format(cl['f1'], '.3f')} | "
              f"{'—' if cl.get('mcc') is None else format(cl['mcc'], '.3f')} |")


if __name__ == "__main__":
    main()
