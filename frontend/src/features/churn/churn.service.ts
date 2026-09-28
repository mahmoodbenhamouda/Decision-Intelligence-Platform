/**
 * Model — accès à l'API du décrochage client.
 */
import { apiJson } from "@/core/api/client";
import type { ChurnData } from "./churn.types";

export async function chargerDecrochage(limite = 25): Promise<ChurnData> {
  try {
    return await apiJson<ChurnData>(`/api/churn?limite=${limite}`);
  } catch {
    return { servi: false, motif: "service momentanément indisponible" };
  }
}
