
import { api } from "@/core/api/client";
import { qsFiltres } from "@/core/filtres/contexteFiltres";
import type { MargeDecomposee } from "./marge.types";

export async function chargerMarge(
  filtres: Record<string, unknown> = {},
): Promise<MargeDecomposee> {
  try {
    const r = await api(`/api/commercial/marge-decomposee?limit=15&${qsFiltres(filtres)}`);
    return await r.json();
  } catch {
    return { servi: false, motif: "Connexion au serveur impossible." };
  }
}
