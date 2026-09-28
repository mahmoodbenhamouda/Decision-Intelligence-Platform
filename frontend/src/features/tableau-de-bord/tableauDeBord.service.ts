/**
 * Model — accès aux indicateurs du tableau de bord.
 */
import { apiEnvoyer } from "@/core/api/client";
import type { FiltresPayload, ReponseTableauDeBord } from "./tableauDeBord.types";

/** Indicateurs et listes de filtres pour le périmètre demandé. Une erreur de
 *  l'API est levée : l'écran garde alors ce qu'il affichait. */
export async function chargerTableauDeBord(filtres: FiltresPayload): Promise<ReponseTableauDeBord> {
  try {
    const data: ReponseTableauDeBord = await (await apiEnvoyer("/api/dashboard", filtres)).json();
    if (data.error) throw new Error(data.error);
    return data;
  } catch (e) {
    console.error(e);
    throw e;
  }
}
