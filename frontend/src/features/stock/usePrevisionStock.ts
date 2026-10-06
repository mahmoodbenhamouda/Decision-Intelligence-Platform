"use client";

import { cleFiltres, useFiltresActifs } from "@/core/filtres/contexteFiltres";
import { useRequete } from "@/core/hooks/useRequete";
import { chargerPrevisionStock } from "./stock.service";

export function usePrevisionStock(limite = 15) {
  const filtres = useFiltresActifs();
  const r = useRequete(() => chargerPrevisionStock(limite, filtres), `${limite}|${cleFiltres(filtres)}`);
  return { data: r.donnees ?? null, loading: r.chargement, load: r.recharger };
}
