"use client";

/**
 * ViewModel — onglet « Suivi des actions ».
 *
 * Charge les tâches (filtrables par employé pour le directeur), l'impact
 * mesuré et l'état de la boucle de retour ; prépare les colonnes du tableau de
 * travail et les séries des deux graphes ; expose `patch` pour faire avancer
 * une tâche puis recharger.
 */
import { useMemo, useState } from "react";
import { useRequete } from "@/core/hooks/useRequete";
import { BLEU, GRAVITE } from "@/shared/ui/VisuelKit";
import { COLONNES, RESULTATS, moisCourt } from "./taches.regles";
import { chargerSuivi, modifierTache } from "./taches.service";
import type { EmployeCharge, Tache } from "./taches.types";

const AUCUNE: Tache[] = [];
const PERSONNE: EmployeCharge[] = [];

export function useTaches(role: string) {
  const estDirecteur = role === "directeur";
  const [filtreEmploye, setFiltreEmploye] = useState<number | "">("");
  const r = useRequete(() => chargerSuivi(filtreEmploye, estDirecteur), `${filtreEmploye}|${estDirecteur}`);

  const taches = r.donnees?.taches ?? AUCUNE;
  const impact = r.donnees?.impact ?? null;
  const employes = r.donnees?.employes ?? PERSONNE;
  const boucle = r.donnees?.boucle ?? null;

  const patch = async (id: number, corps: Record<string, unknown>) => {
    const ok = await modifierTache(id, corps);
    if (ok) r.recharger();
    return ok;
  };

  const parStatut = useMemo(() => {
    const m: Record<string, Tache[]> = {};
    COLONNES.forEach(c => { m[c.id] = []; });
    taches.forEach(t => { (m[t.statut] ||= []).push(t); });
    return m;
  }, [taches]);

  const donneesMois = useMemo(
    () => (impact?.par_mois || []).map(m => ({ ...m, label: moisCourt(m.mois) })),
    [impact]);
  const donneesResultat = useMemo(
    () => (impact?.par_resultat || []).map(x => ({
      ...x,
      couleur: RESULTATS.find(y => y.id === x.resultat)?.gain
        ? GRAVITE.faible.couleur : BLEU[1],
    })),
    [impact]);

  return {
    estDirecteur, taches, impact, employes, boucle, loading: r.chargement,
    filtreEmploye, setFiltreEmploye, charger: r.recharger, patch,
    parStatut, donneesMois, donneesResultat,
  };
}
