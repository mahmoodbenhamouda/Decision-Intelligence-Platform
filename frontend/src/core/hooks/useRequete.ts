"use client";

/**
 * useRequete — brique commune des ViewModels qui chargent des données.
 *
 * Elle remplace le motif répété dans chaque panneau
 *     useEffect(() => { setLoading(true); fetch… }, [])
 * qui modifiait l'état de façon synchrone dans l'effet (rendus en cascade,
 * signalés par ESLint). Ici :
 *   · `chargement` est DÉDUIT : vrai tant que la réponse ne correspond pas à la
 *     clé courante — aucun setState synchrone ;
 *   · les données précédentes restent affichées pendant un rechargement ;
 *   · une réponse arrivée après un changement de clé est ignorée ;
 *   · `recharger()` relance la requête, `muter()` corrige localement les
 *     données après une action (mise à jour optimiste).
 */
import { useCallback, useEffect, useEffectEvent, useState } from "react";

export interface Requete<T> {
  donnees: T | undefined;
  chargement: boolean;
  erreur: unknown;
  recharger: () => void;
  muter: (f: (d: T | undefined) => T | undefined) => void;
}

export function useRequete<T>(charger: () => Promise<T>, cle = "", actif = true): Requete<T> {
  const [version, setVersion] = useState(0);
  const cleCourante = `${cle}#${version}`;
  const [etat, setEtat] = useState<{ cle: string | null; donnees?: T; erreur?: unknown }>({ cle: null });
  const lancer = useEffectEvent(charger);

  useEffect(() => {
    if (!actif) return;
    let annule = false;
    lancer().then(
      d => { if (!annule) setEtat({ cle: cleCourante, donnees: d }); },
      e => { if (!annule) setEtat(p => ({ cle: cleCourante, donnees: p.donnees, erreur: e ?? "erreur" })); },
    );
    return () => { annule = true; };
  }, [cleCourante, actif]);

  const recharger = useCallback(() => setVersion(v => v + 1), []);
  const muter = useCallback((f: (d: T | undefined) => T | undefined) =>
    setEtat(p => ({ ...p, donnees: f(p.donnees) })), []);

  return {
    donnees: etat.donnees,
    chargement: actif && etat.cle !== cleCourante,
    erreur: etat.cle === cleCourante ? etat.erreur : undefined,
    recharger,
    muter,
  };
}
