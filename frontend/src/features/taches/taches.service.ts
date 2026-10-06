
import { api, apiEnvoyer } from "@/core/api/client";
import type {
  Confiee, DonneesSuivi, EmployeAssignable, EtatDelegation, NouvelleTache, PassageDelegation,
} from "./taches.types";

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

export async function creerTache(t: NouvelleTache): Promise<void> {
  const r = await apiEnvoyer("/api/taches", t);
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || "La tâche n'a pas pu être créée.");
  }
}

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

export async function modifierTache(id: number, corps: Record<string, unknown>): Promise<boolean> {
  const r = await apiEnvoyer(`/api/taches/${id}`, corps, "PATCH");
  return r.ok;
}

export async function chargerDelegation(): Promise<EtatDelegation | null> {
  try {
    const r = await api("/api/taches/delegation");
    return r.ok ? await r.json() : null;
  } catch {
    return null;
  }
}

async function lireErreur(r: Response, defaut: string): Promise<never> {
  const d = await r.json().catch(() => ({}));
  throw new Error(typeof d.detail === "string" ? d.detail : defaut);
}

export async function reglerDelegation(corps: { active?: boolean; heure?: string }): Promise<EtatDelegation> {
  const r = await apiEnvoyer("/api/taches/delegation", corps, "PUT");
  if (!r.ok) return lireErreur(r, "Le réglage n'a pas pu être enregistré.");
  return r.json();
}

export async function lancerDelegation(): Promise<PassageDelegation> {
  const r = await apiEnvoyer("/api/taches/delegation/lancer", {});
  if (!r.ok) return lireErreur(r, "Le passage n'a pas pu être lancé.");
  return r.json();
}
