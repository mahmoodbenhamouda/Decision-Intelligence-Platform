/**
 * Model — accès à l'API du portail client (/api/portal).
 */
import { api, apiEnvoyer } from "@/core/api/client";
import type { DonneesEspace, InvoicesData } from "./espaceClient.types";

export async function chargerEspace(): Promise<DonneesEspace> {
  try {
    const [ri, rr, rp] = await Promise.all([
      api("/api/portal/invoices?limit=30"),
      api("/api/portal/requests"),
      api("/api/portal/recommandations"),
    ]);
    const di: InvoicesData = await ri.json();
    const dr = await rr.json();
    const dp = await rp.json().catch(() => ({ produits: [] }));
    return {
      inv: di.error ? null : di, erreur: di.error ?? null,
      demandes: dr.requests || [], produits: dp.produits || [],
    };
  } catch {
    return { inv: null, erreur: "Service momentanément injoignable.", demandes: [], produits: [] };
  }
}

/** Résultat d'un envoi : `null` si accepté, sinon le message d'erreur à afficher. */
async function envoyer(chemin: string, corps: unknown): Promise<string | null> {
  const r = await apiEnvoyer(chemin, corps);
  if (r.ok) return null;
  const d = await r.json().catch(() => ({}));
  return `Erreur : ${d.detail || r.status}`;
}

/** Action structurée (bouton) — la tâche interne est créée par le serveur. */
export function envoyerActionPortail(corps: Record<string, unknown>): Promise<string | null> {
  return envoyer("/api/portal/actions", corps);
}

/** Demande libre adressée à la direction. */
export function envoyerDemande(corps: { type: string; sujet: string; message: string; invoice_ref: string | null }): Promise<string | null> {
  return envoyer("/api/portal/requests", corps);
}
