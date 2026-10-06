
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

export function api(chemin: string, init: RequestInit = {}): Promise<Response> {
  return authFetch(`${API_URL}${chemin}`, init);
}

export async function apiJson<T>(chemin: string, init: RequestInit = {}): Promise<T> {
  const res = await api(chemin, init);
  return (await res.json()) as T;
}

export function apiEnvoyer(chemin: string, corps: unknown, methode: "POST" | "PATCH" | "PUT" | "DELETE" = "POST"): Promise<Response> {
  return api(chemin, {
    method: methode,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(corps),
  });
}
