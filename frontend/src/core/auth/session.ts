"use client";

const LOGGED_KEY = "finbot_logged_in";
const ROLE_KEY = "finbot_role";
const EMAIL_KEY = "finbot_email";
const NAME_KEY = "finbot_full_name";

export interface SessionInfo {
  loggedIn: boolean;
  role: "directeur" | "employe" | null;
  email: string | null;
  fullName: string | null;
}

export function getSession(): SessionInfo {
  if (typeof window === "undefined") {
    return { loggedIn: false, role: null, email: null, fullName: null };
  }
  return {
    loggedIn: localStorage.getItem(LOGGED_KEY) === "1",
    role: (localStorage.getItem(ROLE_KEY) as SessionInfo["role"]) || null,
    email: localStorage.getItem(EMAIL_KEY),
    fullName: localStorage.getItem(NAME_KEY),
  };
}

export function saveSession(s: { role: string; email: string; full_name?: string | null }) {

  localStorage.setItem(LOGGED_KEY, "1");
  localStorage.setItem(ROLE_KEY, s.role);
  localStorage.setItem(EMAIL_KEY, s.email);
  if (s.full_name) localStorage.setItem(NAME_KEY, s.full_name);
  else localStorage.removeItem(NAME_KEY);
}

export function clearSession() {
  [LOGGED_KEY, ROLE_KEY, EMAIL_KEY, NAME_KEY, "finbot_client_code"].forEach(k => localStorage.removeItem(k));
}

export function isLoggedIn(): boolean {
  return getSession().loggedIn;
}

export function redirectToLogin() {
  if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
    window.location.href = "/login";
  }
}
