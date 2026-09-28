/**
 * Model — accès à l'API du stock, de l'approvisionnement et de la prévision.
 */
import { api, apiJson } from "@/core/api/client";
import { API_INJOIGNABLE } from "@/core/config";
import type { ForecastData, StockData, SupplyData } from "./stock.types";

/** Résultat de /api/supply : les données, ou le message à afficher. */
export interface ResultatApprovisionnement { data: SupplyData | null; erreur: string | null }

export async function chargerApprovisionnement(): Promise<ResultatApprovisionnement> {
  try {
    const res = await api("/api/supply");
    if (res.status === 403) return { data: null, erreur: "Analyse réservée au directeur." };
    const d: SupplyData = await res.json();
    return d.error ? { data: null, erreur: d.error } : { data: d, erreur: null };
  } catch {
    return { data: null, erreur: API_INJOIGNABLE };
  }
}

export async function chargerPrevisionStock(limite = 15): Promise<ForecastData> {
  try {
    return await apiJson<ForecastData>(`/api/stock/forecast?limit=${limite}`);
  } catch {
    return { error: "indisponible" };
  }
}

export async function chargerStock(client?: string): Promise<StockData> {
  try {
    const q = client ? `?client=${encodeURIComponent(client)}` : "";
    return await apiJson<StockData>(`/api/stock${q}`);
  } catch {
    return { error: "Connexion au serveur impossible." };
  }
}
