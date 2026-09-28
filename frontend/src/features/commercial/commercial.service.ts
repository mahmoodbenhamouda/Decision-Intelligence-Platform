/**
 * Model — accès à l'API commerciale (devis, marge, recommandations).
 */
import { api } from "@/core/api/client";
import type { DonneesCommerciales } from "./commercial.types";

export async function chargerCommercial(): Promise<DonneesCommerciales> {
  try {
    const [rd, rm, rr] = await Promise.all([
      api("/api/commercial/devis?limit=20"),
      api("/api/commercial/marge?limit=15"),
      api("/api/commercial/recommandations?limit=12"),
    ]);
    return { devis: await rd.json(), marge: await rm.json(), reco: await rr.json() };
  } catch {
    const hs = { servi: false, motif: "Connexion au serveur impossible." };
    return { devis: hs, marge: hs, reco: hs };
  }
}
