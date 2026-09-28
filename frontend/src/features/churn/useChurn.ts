"use client";

/**
 * ViewModel — état du panneau de décrochage : les données et le chargement.
 * La vue ne sait pas d'où viennent les chiffres.
 */
import { useRequete } from "@/core/hooks/useRequete";
import { chargerDecrochage } from "./churn.service";
import type { ChurnData } from "./churn.types";

export function useChurn(limite = 25): { data: ChurnData | null; loading: boolean } {
  const r = useRequete(() => chargerDecrochage(limite), String(limite));
  return { data: r.donnees ?? null, loading: r.chargement };
}
