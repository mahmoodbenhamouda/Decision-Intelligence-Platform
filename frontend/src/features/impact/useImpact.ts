"use client";

import { useMemo, useState } from "react";
import { useRequete } from "@/core/hooks/useRequete";
import { chargerImpact } from "./impact.service";

export function useImpact() {
  const r = useRequete(chargerImpact, "impact");
  const data = r.donnees ?? null;

  /** Poste déplié : le détail par client ne s'affiche qu'à la demande. */
  const [ouvert, setOuvert] = useState<string | null>(null);
  const basculer = (cle: string) => setOuvert(o => (o === cle ? null : cle));

  const d = useMemo(() => {
    const postes = (data?.postes || []).slice()
      .sort((a, b) => b.montant_identifie_dt - a.montant_identifie_dt);
    // L'échelle des barres est commune à tous les postes : sans cela, deux
    // barres de même longueur représenteraient des montants différents.
    const maxIdentifie = postes.reduce((m, p) => Math.max(m, p.montant_identifie_dt), 0);
    return { postes, maxIdentifie };
  }, [data]);

  return {
    data, d, loading: r.chargement, load: r.recharger,
    ouvert, basculer,
  };
}
