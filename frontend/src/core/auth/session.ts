"use client";

/**
 * core/auth/session.ts — session côté navigateur.
 *
 * - Le jeton est stocké en localStorage (envoyé UNIQUEMENT en en-tête
 *   `Authorization` — jamais dans l'URL). L'isolation des données reste
 *   garantie CÔTÉ SERVEUR : même un jeton manipulé ne donne accès qu'au
 *   périmètre du compte (le `client_code` est forcé par l'API).
 * - `authFetch` ajoute le jeton et gère 401 (session expirée → /login).
 */

/**
 * SÉCURITÉ : le JWT vit dans un cookie httpOnly posé par l'API (inaccessible
 * au JavaScript → protégé du vol par XSS). localStorage ne garde que des
 * informations d'AFFICHAGE non sensibles (rôle, nom, email) + un drapeau de
 * session. Toutes les garanties restent côté serveur.
 */
const LOGGED_KEY = "finbot_logged_in";
const ROLE_KEY = "finbot_role";
const EMAIL_KEY = "finbot_email";
const CLIENT_KEY = "finbot_client_code";
const NAME_KEY = "finbot_full_name";

export interface SessionInfo {
  loggedIn: boolean;
  role: "directeur" | "employe" | "client" | null;
  email: string | null;
  clientCode: string | null;
  fullName: string | null;
}

export function getSession(): SessionInfo {
  if (typeof window === "undefined") {
    return { loggedIn: false, role: null, email: null, clientCode: null, fullName: null };
  }
  return {
    loggedIn: localStorage.getItem(LOGGED_KEY) === "1",
    role: (localStorage.getItem(ROLE_KEY) as SessionInfo["role"]) || null,
    email: localStorage.getItem(EMAIL_KEY),
    clientCode: localStorage.getItem(CLIENT_KEY),
    fullName: localStorage.getItem(NAME_KEY),
  };
}

export function saveSession(s: { role: string; email: string; client_code?: string | null; full_name?: string | null }) {
  // Le JWT n'est PAS stocké ici : il est dans le cookie httpOnly posé par l'API.
  localStorage.setItem(LOGGED_KEY, "1");
  localStorage.setItem(ROLE_KEY, s.role);
  localStorage.setItem(EMAIL_KEY, s.email);
  if (s.client_code) localStorage.setItem(CLIENT_KEY, s.client_code);
  else localStorage.removeItem(CLIENT_KEY);
  if (s.full_name) localStorage.setItem(NAME_KEY, s.full_name);
  else localStorage.removeItem(NAME_KEY);
}

export function clearSession() {
  [LOGGED_KEY, ROLE_KEY, EMAIL_KEY, CLIENT_KEY, NAME_KEY].forEach(k => localStorage.removeItem(k));
}

export function isLoggedIn(): boolean {
  return getSession().loggedIn;
}

/** Redirige vers l'écran de connexion (session absente ou expirée). */
export function redirectToLogin() {
  if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
    window.location.href = "/login";
  }
}
