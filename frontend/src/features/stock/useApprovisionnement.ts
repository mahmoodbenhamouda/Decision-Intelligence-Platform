"use client";

/** ViewModel — carte « approvisionnement » : données, erreur, chargement. */
import { useRequete } from "@/core/hooks/useRequete";
import { chargerApprovisionnement } from "./stock.service";

export function useApprovisionnement() {
  const r = useRequete(chargerApprovisionnement);
  return {
    data: r.donnees?.data ?? null,
    error: r.donnees?.erreur ?? null,
    loading: r.chargement,
    load: r.recharger,
  };
}
