"use client";

import { useRequete } from "@/core/hooks/useRequete";
import { chargerConfiees } from "./taches.service";
import type { Confiee } from "./taches.types";

const AUCUNE: Record<string, Confiee> = {};

export function useConfiees(actif = true) {
  const r = useRequete(chargerConfiees, "", actif);
  return { confiees: r.donnees ?? AUCUNE, recharger: r.recharger };
}
