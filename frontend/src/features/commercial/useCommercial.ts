"use client";

/**
 * ViewModel — onglet « Devis & marge ».
 *
 * Charge les trois classements, prépare les séries des graphes (noms courts,
 * chances en %, produits les plus recommandés, totaux) et gère la fenêtre
 * « Confier » avec les alertes déjà confiées, relues au serveur.
 */
import { useMemo, useState } from "react";
import { useRequete } from "@/core/hooks/useRequete";
import { useConfiees } from "@/features/taches/useConfiees";
import type { Origine } from "@/features/taches/taches.types";
import { tronquer } from "@/shared/ui/VisuelKit";
import { chargerCommercial } from "./commercial.service";

export function useCommercial() {
  const r = useRequete(chargerCommercial);
  const devis = r.donnees?.devis ?? null;
  const marge = r.donnees?.marge ?? null;
  const reco = r.donnees?.reco ?? null;
  const [confier, setConfier] = useState<Origine | null>(null);
  // Relu au serveur : une relance confiée hier ne se repropose pas aujourd'hui.
  const { confiees, recharger: rechargerConfiees } = useConfiees();

  const d = useMemo(() => {
    const devisTop = (devis?.top || []).map(x => ({
      ...x, nomCourt: tronquer(x.nom || x.client, 24), chance: Math.round(x.probabilite * 100),
    }));
    const margeTop = (marge?.top || []).map(x => ({ ...x, nomCourt: tronquer(x.nom || x.client, 24) }));
    const margeTotale = margeTop.reduce((s, x) => s + x.marge_en_jeu_dt, 0);
    const clientsReco = reco?.top || [];
    const compte: Record<string, number> = {};
    clientsReco.forEach(c => c.produits.forEach(p => { compte[p.designation] = (compte[p.designation] || 0) + 1; }));
    const produits = Object.entries(compte)
      .map(([produit, n]) => ({ produit: tronquer(produit, 28), complet: produit, n }))
      .sort((a, b) => b.n - a.n).slice(0, 8);
    const potentiel = clientsReco.reduce((s, c) => s + c.potentiel_top3_dt, 0);
    return { devisTop, margeTop, margeTotale, clientsReco, produits, potentiel };
  }, [devis, marge, reco]);

  return {
    devis, marge, reco, loading: r.chargement, load: r.recharger, d,
    confier, setConfier, confiees, rechargerConfiees,
  };
}
