"""La délégation autonome sans l'API : la flotte tourne, puis confie elle-même le travail…"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _resume(p: dict) -> str:
    lignes = [f"[délégation] passage {p['declencheur']} · {p['statut']}"
              + (f" · {p['motif']}" if p.get("motif") else "")]
    for x in p.get("lignes", []):
        qui = x.get("assigne") or "à affecter"
        issue = {"creee": f"confiée → {qui}", "deja_confiee": "déjà en cours",
                 "recente": "traitée récemment"}.get(x.get("issue"), x.get("issue"))
        lignes.append(f"  {x['rang']}. {x['titre'][:60]:60} {issue} ({x.get('raison', '')})")
    for d in p.get("decisions_direction", []):
        lignes.append(f"  · décision de direction : {d['titre']}")
    return "\n".join(lignes)


def main() -> int:
    ap = argparse.ArgumentParser(description="Délégation autonome de la flotte d'agents")
    ap.add_argument("--si-du", action="store_true",
                    help="seulement si le passage planifié du jour est dû")
    args = ap.parse_args()

    from api.auth.database import get_db, init_db
    from api.services.delegation import executer, executer_si_du

    init_db()
    if args.si_du:
        p = executer_si_du()
        if p is None:
            print("[délégation] rien à faire : désactivée, pas encore l'heure, "
                  "ou passage du jour déjà effectué.")
            return 0
    else:
        db = next(get_db())
        try:
            p = executer(db, declencheur="commande")
        finally:
            db.close()
    print(_resume(p))
    return 0 if p["statut"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
