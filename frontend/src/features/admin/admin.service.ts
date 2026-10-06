
import { api, apiEnvoyer } from "@/core/api/client";
import { API_INJOIGNABLE } from "@/core/config";
import type { DonneesAdmin } from "./admin.types";

export interface Reponse { ok: boolean; status: number; data: Record<string, unknown> & { detail?: string } }

async function lire(res: Response): Promise<Reponse> {
  return { ok: res.ok, status: res.status, data: await res.json().catch(() => ({})) };
}

export async function chargerAdmin(): Promise<DonneesAdmin> {
  try {
    const [ru, ra, rr] = await Promise.all([
      api("/api/admin/users"),
      api("/api/admin/audit?limit=60"),
      api("/api/admin/roles-retires"),
    ]);
    return {
      users: ru.ok ? await ru.json() : [],
      audit: ra.ok ? (await ra.json()).audit || [] : [],
      rolesRetires: rr.ok ? Number((await rr.json()).n) || 0 : 0,
      erreur: null,
    };
  } catch {
    return { users: [], audit: [], rolesRetires: 0, erreur: API_INJOIGNABLE };
  }
}

/** Efface définitivement les comptes d'un rôle que la plateforme ne sert plus. */
export async function purgerRolesRetires(): Promise<Reponse> {
  return lire(await apiEnvoyer("/api/admin/purger-roles-retires", {}));
}

export async function creerCompte(corps: Record<string, unknown>): Promise<Reponse> {
  return lire(await apiEnvoyer("/api/admin/users", corps));
}

export async function modifierCompte(id: number, corps: Record<string, unknown>): Promise<Reponse> {
  return lire(await apiEnvoyer(`/api/admin/users/${id}`, corps, "PATCH"));
}

export async function supprimerCompte(id: number, definitif = false): Promise<Reponse> {
  return lire(await api(`/api/admin/users/${id}${definitif ? "?permanent=true" : ""}`, { method: "DELETE" }));
}
