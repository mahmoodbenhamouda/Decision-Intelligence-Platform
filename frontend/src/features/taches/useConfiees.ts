"use client";

/**
 * ViewModel — les alertes déjà transformées en tâche, relues au SERVEUR.
 *
 * L'information vivait auparavant dans la mémoire de l'onglet : au rechargement
 * de la page, le bouton « Confier » revenait sur une alerte déjà traitée, et la
 * même action pouvait être confiée à deux personnes. La clé est l'intitulé de
 * l'alerte d'origine — la seule valeur stable d'un chargement à l'autre.
 */
import { useRequete } from "@/core/hooks/useRequete";
import { chargerConfiees } from "./taches.service";
import type { Confiee } from "./taches.types";

const AUCUNE: Record<string, Confiee> = {};

export function useConfiees(actif = true) {
  const r = useRequete(chargerConfiees, "", actif);
  return { confiees: r.donnees ?? AUCUNE, recharger: r.recharger };
}
