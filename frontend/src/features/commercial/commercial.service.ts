
import { api } from "@/core/api/client";
import { qsFiltres } from "@/core/filtres/contexteFiltres";
import type { DonneesCommerciales } from "./commercial.types";

export async function chargerCommercial(filtres: Record<string, unknown> = {}): Promise<DonneesCommerciales> {
  const q = qsFiltres(filtres);
  try {
    // `limit=300` : la liste des devis ouverts se consulte en entier. Un
    // décompte sans liste ne permet aucune action, c'était le manque principal.
    // Les recommandations produits ne sont plus chargées ici : elles ont rejoint
    // l'onglet Produits & achats, où elles chargent elles-mêmes.
    //
    // `limit=100` sur la marge (le plafond serveur) et non 15 : la liste est
    // désormais paginée et triable, et un total de « marge menacée » calculé
    // sur les quinze premiers clients sous-estimait l'enjeu d'un facteur
    // arbitraire. On sert donc tout le portefeuille, et l'écran en montre
    // vingt-cinq à la fois.
    const [rd, rm] = await Promise.all([
      api(`/api/commercial/devis?limit=300&${q}`),
      api(`/api/commercial/marge?limit=100&${q}`),
    ]);
    return { devis: await rd.json(), marge: await rm.json() };
  } catch {
    const hs = { servi: false, motif: "Connexion au serveur impossible." };
    return { devis: hs, marge: hs };
  }
}
