"use client";

import { cleFiltres, useFiltresActifs } from "@/core/filtres/contexteFiltres";
import { useRequete } from "@/core/hooks/useRequete";
import { chargerDecrochage } from "./churn.service";
import type { ChurnData } from "./churn.types";

export function useChurn(limite = 25): { data: ChurnData | null; loading: boolean } {
  const filtres = useFiltresActifs();
  const r = useRequete(() => chargerDecrochage(limite, filtres), `${limite}|${cleFiltres(filtres)}`);
  return { data: r.donnees ?? null, loading: r.chargement };
}
