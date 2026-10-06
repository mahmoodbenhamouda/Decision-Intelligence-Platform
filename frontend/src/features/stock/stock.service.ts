
import { api, apiJson } from "@/core/api/client";
import { API_INJOIGNABLE } from "@/core/config";
import { qsFiltres } from "@/core/filtres/contexteFiltres";
import type { ForecastData, StockData, SupplyData } from "./stock.types";

export interface ResultatApprovisionnement { data: SupplyData | null; erreur: string | null; masque?: string }

export async function chargerApprovisionnement(filtres: Record<string, unknown> = {}): Promise<ResultatApprovisionnement> {
  try {
    const res = await api(`/api/supply?${qsFiltres(filtres)}`);
    if (res.status === 403) return { data: null, erreur: "Analyse réservée au directeur." };
    const d: SupplyData & { masque?: boolean } = await res.json();
    if (d.masque) return { data: null, erreur: null, masque: d.error };
    return d.error ? { data: null, erreur: d.error } : { data: d, erreur: null };
  } catch {
    return { data: null, erreur: API_INJOIGNABLE };
  }
}

export async function chargerPrevisionStock(limite = 15, filtres: Record<string, unknown> = {}): Promise<ForecastData> {
  try {
    return await apiJson<ForecastData>(`/api/stock/forecast?limit=${limite}&${qsFiltres(filtres)}`);
  } catch {
    return { error: "indisponible" };
  }
}

export async function chargerStock(filtres: Record<string, unknown> = {}): Promise<StockData> {
  try {
    return await apiJson<StockData>(`/api/stock?${qsFiltres(filtres)}`);
  } catch {
    return { error: "Connexion au serveur impossible." };
  }
}
