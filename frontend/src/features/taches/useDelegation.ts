"use client";

import { useState } from "react";
import { useRequete } from "@/core/hooks/useRequete";
import { chargerDelegation, lancerDelegation, reglerDelegation } from "./taches.service";

export function useDelegation(actif: boolean, apresPassage?: () => void) {
  const r = useRequete(chargerDelegation, "", actif);
  const [enCours, setEnCours] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  const regler = async (corps: { active?: boolean; heure?: string }) => {
    setErreur(null);
    try {
      const etat = await reglerDelegation(corps);
      r.muter(() => etat);
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Réglage impossible.");
    }
  };

  const lancer = async () => {
    setEnCours(true); setErreur(null);
    try {
      await lancerDelegation();
      r.recharger();
      apresPassage?.();
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Passage impossible.");
    } finally { setEnCours(false); }
  };

  return { etat: r.donnees ?? null, chargement: r.chargement, enCours, erreur, regler, lancer };
}
