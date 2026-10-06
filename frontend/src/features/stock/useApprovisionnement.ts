"use client";

import { cleFiltres, useFiltresActifs } from "@/core/filtres/contexteFiltres";
import { useRequete } from "@/core/hooks/useRequete";
import { chargerApprovisionnement } from "./stock.service";

export function useApprovisionnement() {
  const filtres = useFiltresActifs();
  const r = useRequete(() => chargerApprovisionnement(filtres), cleFiltres(filtres));
  return {
    data: r.donnees?.data ?? null,
    error: r.donnees?.erreur ?? null,
    masque: r.donnees?.masque ?? null,
    loading: r.chargement,
    load: r.recharger,
  };
}
