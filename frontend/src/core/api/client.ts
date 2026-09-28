/**
 * core/api/client.ts — le seul point de contact avec l'API.
 *
 * Toutes les requêtes de l'application passent par ici :
 *   · `credentials: "include"` fait porter le cookie httpOnly (le JWT ne
 *     transite jamais par le JavaScript de la page) ;
 *   · 401 → session invalide, expirée ou révoquée : purge + retour à /login ;
 *   · 403 → renvoyé à l'appelant (accès refusé : l'écran affiche un message).
 *
 * Les services des fonctionnalités (`features/<x>/<x>.service.ts`) n'écrivent
 * jamais d'URL complète ni de `fetch` : ils appellent `api`, `apiJson` ou
 * `apiEnvoyer` avec un chemin relatif.
 */
import { API_URL } from "@/core/config";
import { clearSession, redirectToLogin } from "@/core/auth/session";

export async function authFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const res = await fetch(input, { ...init, credentials: "include" });
  if (res.status === 401) {
    clearSession();
    redirectToLogin();
  }
  return res;
}

/** Requête authentifiée sur un chemin de l'API (`/api/...`). */
export function api(chemin: string, init: RequestInit = {}): Promise<Response> {
  return authFetch(`${API_URL}${chemin}`, init);
}

/** GET (ou autre méthode) et lecture du corps JSON. */
export async function apiJson<T>(chemin: string, init: RequestInit = {}): Promise<T> {
  const res = await api(chemin, init);
  return (await res.json()) as T;
}

/** Envoi d'un corps JSON (POST par défaut) ; renvoie la réponse brute pour
 *  que l'appelant lise le statut (201, 403, 409…) et le corps. */
export function apiEnvoyer(chemin: string, corps: unknown, methode: "POST" | "PATCH" | "PUT" | "DELETE" = "POST"): Promise<Response> {
  return api(chemin, {
    method: methode,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(corps),
  });
}
