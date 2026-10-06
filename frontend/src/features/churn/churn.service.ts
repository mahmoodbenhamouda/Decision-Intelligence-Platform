
import { apiJson } from "@/core/api/client";
import { qsFiltres } from "@/core/filtres/contexteFiltres";
import type { ChurnData } from "./churn.types";

export async function chargerDecrochage(limite = 25, filtres: Record<string, unknown> = {}): Promise<ChurnData> {
  try {
    return await apiJson<ChurnData>(`/api/churn?limite=${limite}&${qsFiltres(filtres)}`);
  } catch {
    return { servi: false, motif: "service momentanément indisponible" };
  }
}
