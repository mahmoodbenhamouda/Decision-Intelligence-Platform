"use client";

/**
 * useSession — garde d'authentification des écrans protégés.
 * Pas de session → écran de connexion. La session n'est lue qu'une fois montée
 * (le stockage local n'existe pas côté serveur).
 */
import { useSyncExternalStore } from "react";
import { getSession, type SessionInfo } from "@/core/auth/session";

let cache: { cle: string; valeur: SessionInfo } | null = null;

function lire(): SessionInfo | null {
  if (typeof window === "undefined") return null;
  const s = getSession();
  const cle = JSON.stringify(s);
  if (!cache || cache.cle !== cle) cache = { cle, valeur: s };
  return cache.valeur;
}

const sAbonner = (f: () => void) => {
  window.addEventListener("storage", f);
  return () => window.removeEventListener("storage", f);
};

export function useSession(): SessionInfo | null {
  return useSyncExternalStore(sAbonner, lire, () => null);
}
