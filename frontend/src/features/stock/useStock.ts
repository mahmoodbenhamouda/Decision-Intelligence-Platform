"use client";

/**
 * ViewModel — onglet « Stock ».
 *
 * Charge le stock réel (éventuellement filtré sur un client) et prépare ce que
 * les graphes affichent : ruptures classées par budget, répartition par
 * urgence, capital immobilisé, pertes probables, produits en fin de vie. La vue
 * ne fait plus aucun calcul.
 */
import { useMemo } from "react";
import { useRequete } from "@/core/hooks/useRequete";
import { tronquer } from "@/shared/ui/VisuelKit";
import { URGENCE } from "./stock.constantes";
import { chargerStock } from "./stock.service";

export function useStock(selectedClient?: string) {
  const r = useRequete(() => chargerStock(selectedClient), selectedClient ?? "");
  const data = r.donnees ?? null;
  const flux = data?.flux_reel;

  const v = useMemo(() => {
    const ruptures = (flux?.ruptures || []).map(r => ({
      ...r, nom: tronquer(r.produit, 26), budget: r.quantite_suggeree * r.cout_unitaire_dt,
    }));
    const parUrgence = Object.entries(URGENCE).map(([cle, u]) => ({
      cle, ...u, n: ruptures.filter(r => r.gravite === cle).length,
    })).filter(x => x.n > 0);
    const capital = (flux?.top || []).slice(0, 10).map(t => ({
      ...t, nom: tronquer(t.produit, 26), dormant: t.mois_couverture > 24,
    }));
    const pertes = (flux?.obsolescence || [])
      .filter(o => o.perte_probable_dt > 0).slice(0, 8)
      .map(o => ({ ...o, nom: tronquer(o.produit, 26), certain: o.gravite === "perte_quasi_certaine" }));
    const finDeVie = (data?.fin_de_vie?.top || [])
      .filter(r => r.capital_expose_dt > 0).slice(0, 8)
      .map(r => ({ ...r, nom: tronquer(r.produit, 26) }));
    return {
      ruptures: [...ruptures].sort((a, b) => b.budget - a.budget).slice(0, 10),
      parUrgence, capital, pertes, finDeVie,
    };
  }, [flux, data]);

  return { data, loading: r.chargement, flux, v, load: r.recharger };
}
