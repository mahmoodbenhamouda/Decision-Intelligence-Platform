
import { api } from "@/core/api/client";
import { API_INJOIGNABLE } from "@/core/config";
import type { ImpactData } from "./impact.types";

/**
 * L'impact ne prend AUCUN filtre, et c'est volontaire.
 *
 * Un enjeu financier filtré sur trois clients ne veut rien dire : le total
 * porte sur l'entreprise, ou il ne porte sur rien. Le périmètre est donc
 * toujours global, et la carte le dit à l'écran.
 */
export async function chargerImpact(): Promise<ImpactData> {
  try {
    const r = await api("/api/impact");
    if (!r.ok) return { servi: false, motif: `API ${r.status}` };
    return await r.json();
  } catch {
    return { servi: false, motif: API_INJOIGNABLE };
  }
}
