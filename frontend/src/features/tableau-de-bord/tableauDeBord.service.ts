
import { apiEnvoyer } from "@/core/api/client";
import type { FiltresPayload, ReponseTableauDeBord } from "./tableauDeBord.types";

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
