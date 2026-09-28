/**
 * Model — accès à l'API des tâches (/api/taches).
 */
import { api, apiEnvoyer } from "@/core/api/client";
import type { Confiee, DonneesSuivi, EmployeAssignable, NouvelleTache } from "./taches.types";

/** Alertes déjà confiées, indexées par l'intitulé de l'alerte d'origine.
 *  `null` si le compte n'y a pas accès (compte client) : jamais bloquant. */
export async function chargerConfiees(): Promise<Record<string, Confiee> | null> {
  try {
    const r = await api("/api/taches/confiees");
    if (!r.ok) return null;
    const d = await r.json();
    return d.confiees || {};
  } catch {
    return null;
  }
}

export async function chargerEmployesAssignables(): Promise<EmployeAssignable[]> {
  try {
    const d = await (await api("/api/taches/employes")).json();
    return d.employes || [];
  } catch {
    return [];
  }
}

/** Crée la tâche ; lève une erreur portant le message de l'API en cas de refus. */
export async function creerTache(t: NouvelleTache): Promise<void> {
  const r = await apiEnvoyer("/api/taches", t);
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || "La tâche n'a pas pu être créée.");
  }
}

/** Tâches (éventuellement d'un seul employé), impact et, pour le directeur,
 *  la charge de chaque employé et l'état de la boucle de retour. */
export async function chargerSuivi(filtreEmploye: number | "", estDirecteur: boolean): Promise<DonneesSuivi> {
  try {
    const url = "/api/taches" + (filtreEmploye === "" ? "" : `?assigne_id=${filtreEmploye}`);
    const appels = [api(url), api("/api/taches/impact")];
    if (estDirecteur) {
      appels.push(api("/api/taches/employes"));
      appels.push(api("/api/taches/boucle"));
    }
    const res = await Promise.all(appels);
    const [dt, di, de, db] = await Promise.all(res.map(r => r.json()));
    return { taches: dt.taches || [], impact: di, employes: de ? de.employes || [] : null, boucle: db ?? null };
  } catch {
    return { taches: [], impact: null, employes: null, boucle: null };
  }
}

/** Modifie une tâche (statut, affectation, résultat). Renvoie vrai si accepté. */
export async function modifierTache(id: number, corps: Record<string, unknown>): Promise<boolean> {
  const r = await apiEnvoyer(`/api/taches/${id}`, corps, "PATCH");
  return r.ok;
}
