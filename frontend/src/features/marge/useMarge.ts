"use client";

import { useMemo } from "react";
import { cleFiltres, useFiltresActifs } from "@/core/filtres/contexteFiltres";
import { useRequete } from "@/core/hooks/useRequete";
import { chargerMarge } from "./marge.service";

export function useMarge() {
  const filtres = useFiltresActifs();
  const r = useRequete(() => chargerMarge(filtres), cleFiltres(filtres));
  const data = r.donnees ?? null;

  const d = useMemo(() => {
    const cats = data?.par_categorie?.categories ?? [];
    const tendance = data?.tendance ?? [];
    // Les douze derniers points suffisent à montrer une pente ; au-delà,
    // l'axe se tasse et la lecture se perd.
    const tendanceRecente = tendance.slice(-36);
    const porteurs = data?.produits?.porteurs ?? [];
    const pertes = data?.produits?.pertes ?? [];

    // Taux de marge moyen de la série, pour situer le dernier point.
    const caTotal = tendanceRecente.reduce((s, p) => s + p.ca_dt, 0);
    const margeTotale = tendanceRecente.reduce((s, p) => s + p.marge_dt, 0);
    const tauxMoyen = caTotal ? (margeTotale / caTotal) * 100 : null;

    return { cats, tendance: tendanceRecente, porteurs, pertes, tauxMoyen };
  }, [data]);

  return { data, d, loading: r.chargement, recharger: r.recharger };
}
