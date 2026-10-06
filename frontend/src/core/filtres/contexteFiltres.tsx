"use client";

import { createContext, useContext, type ReactNode } from "react";

/**
 * Filtres du tableau de bord, accessibles à tous les panneaux des modèles sans
 * les faire transiter par chaque composant. Le serveur applique la règle de
 * portée (ml_engine/portee.py) : restreint aux clients filtrés, ou masqué.
 */
const Contexte = createContext<Record<string, unknown>>({});

export function FournisseurFiltres({ valeur, children }: {
  valeur: Record<string, unknown>; children: ReactNode;
}) {
  return <Contexte.Provider value={valeur}>{children}</Contexte.Provider>;
}

export function useFiltresActifs(): Record<string, unknown> {
  return useContext(Contexte);
}

/** Paramètre de requête à ajouter aux routes des modèles. */
export function qsFiltres(filtres: Record<string, unknown>): string {
  return `filtres=${encodeURIComponent(JSON.stringify(filtres || {}))}`;
}

/** Clé de cache stable pour useRequete. */
export function cleFiltres(filtres: Record<string, unknown>): string {
  return JSON.stringify(filtres || {});
}
