
import { api } from "@/core/api/client";
import { clearSession, redirectToLogin } from "@/core/auth/session";
import { API_URL } from "@/core/config";

export async function serveurEnLigne(signal: AbortSignal): Promise<boolean> {
  const r = await fetch(`${API_URL}/api/health`, { signal });
  return r.ok;
}

export interface ReponseConnexion {
  ok: boolean; status: number;
  data: { detail?: string; role?: string; email?: string; full_name?: string | null };
}

export async function seConnecter(email: string, password: string): Promise<ReponseConnexion> {
  const res = await fetch(`${API_URL}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ email, password }),
  });
  return { ok: res.ok, status: res.status, data: await res.json().catch(() => ({})) };
}

export async function seDeconnecter(): Promise<void> {
  try { await api("/api/auth/logout", { method: "POST" }); } catch { }
  clearSession();
  redirectToLogin();
}
