/**
 * Model — accès à l'API d'administration (/api/admin).
 */
import { api, apiEnvoyer } from "@/core/api/client";
import { API_INJOIGNABLE } from "@/core/config";
import type { DonneesAdmin } from "./admin.types";

/** Réponse d'une action : succès, statut HTTP et corps (vide si illisible). */
export interface Reponse { ok: boolean; status: number; data: Record<string, unknown> & { detail?: string } }

async function lire(res: Response): Promise<Reponse> {
  return { ok: res.ok, status: res.status, data: await res.json().catch(() => ({})) };
}

export async function chargerAdmin(): Promise<DonneesAdmin> {
  try {
    const [ru, re, rr, ra] = await Promise.all([
      api("/api/admin/users"),
      api("/api/admin/erp-clients"),
      api("/api/admin/requests"),
      api("/api/admin/audit?limit=60"),
    ]);
    return {
      users: ru.ok ? await ru.json() : [],
      erp: re.ok ? (await re.json()).clients || [] : [],
      requests: rr.ok ? (await rr.json()).requests || [] : [],
      audit: ra.ok ? (await ra.json()).audit || [] : [],
      erreur: null,
    };
  } catch {
    return { users: [], erp: [], requests: [], audit: [], erreur: API_INJOIGNABLE };
  }
}

export async function creerCompte(corps: Record<string, unknown>): Promise<Reponse> {
  return lire(await apiEnvoyer("/api/admin/users", corps));
}

export async function modifierCompte(id: number, corps: Record<string, unknown>): Promise<Reponse> {
  return lire(await apiEnvoyer(`/api/admin/users/${id}`, corps, "PATCH"));
}

/** Désactivation (réversible) ou, avec `definitif`, suppression de la base. */
export async function supprimerCompte(id: number, definitif = false): Promise<Reponse> {
  return lire(await api(`/api/admin/users/${id}${definitif ? "?permanent=true" : ""}`, { method: "DELETE" }));
}

export async function traiterDemande(id: number, status: string, reponse: string | null): Promise<boolean> {
  const res = await apiEnvoyer(`/api/admin/requests/${id}`, { status, reponse }, "PATCH");
  return res.ok;
}
