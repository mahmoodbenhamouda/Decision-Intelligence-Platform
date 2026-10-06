"use client";

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
