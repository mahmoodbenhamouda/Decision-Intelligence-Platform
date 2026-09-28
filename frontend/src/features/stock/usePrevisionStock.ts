"use client";

/** ViewModel — volumes à prévoir par produit. */
import { useRequete } from "@/core/hooks/useRequete";
import { chargerPrevisionStock } from "./stock.service";

export function usePrevisionStock(limite = 15) {
  const r = useRequete(() => chargerPrevisionStock(limite), String(limite));
  return { data: r.donnees ?? null, loading: r.chargement, load: r.recharger };
}
