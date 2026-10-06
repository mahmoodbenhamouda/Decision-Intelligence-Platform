"""Le réveil de la flotte : une tâche de fond qui, chaque minute, demande à la délégation autonome…"""

from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger("planificateur")

INTERVALLE_S = 60


def actif() -> bool:
    return os.environ.get("PLANIFICATEUR", "1") not in ("0", "false", "False")


async def boucle(intervalle: float = INTERVALLE_S) -> None:
    """Tourne jusqu'à l'arrêt de l'API."""
    from api.services.delegation import executer_si_du

    while True:
        try:
            passage = await asyncio.to_thread(executer_si_du)
            if passage:
                logger.info("délégation autonome : %s tâche(s) confiée(s) (%s)",
                            passage.get("n_creees"), passage.get("statut"))
        except asyncio.CancelledError:  # pragma: no cover — arrêt de l'API
            raise
        except Exception:
            logger.exception("planificateur : passage en échec")
        await asyncio.sleep(intervalle)
