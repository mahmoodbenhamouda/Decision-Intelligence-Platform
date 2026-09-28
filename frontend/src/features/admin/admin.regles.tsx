/**
 * Model — règles de l'administration : statuts des demandes et adresse de
 * connexion dérivée du nom de l'établissement.
 */
import type { ReactNode } from "react";
import { CheckCircle2, Clock3, Inbox, XCircle } from "lucide-react";

export const STATUS_META: Record<string, { label: string; color: string; icon: ReactNode }> = {
  nouvelle: { label: "Nouvelle", color: "#2F5BEA", icon: <Inbox size={12} /> },
  en_cours: { label: "En cours", color: "#F59E0B", icon: <Clock3 size={12} /> },
  traitee: { label: "Traitée", color: "#10B981", icon: <CheckCircle2 size={12} /> },
  rejetee: { label: "Rejetée", color: "#EF4444", icon: <XCircle size={12} /> },
};

/* Adresse de connexion dérivée du NOM de l'établissement — même règle que
   le backend (api/auth/emails.py) : accents retirés, "C.H.U." → "chu",
   ponctuation en tirets, 40 caractères max coupés sur un tiret. */
export function emailFromName(nom: string, code: string): string {
  let s = (nom || "").trim().toLowerCase();
  s = s.normalize("NFKD").replace(/[\u0300-\u036f]/g, "");   // accents
  s = s.replace(/\bc[.\s]*h[.\s]*u\b\.?/g, "chu");
  s = s.replace(/['’]/g, " ");
  s = s.replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").replace(/-{2,}/g, "-");
  if (s.length > 40) s = s.slice(0, 40).replace(/-[^-]*$/, "");
  if (!s) s = (code || "client").toLowerCase().replace(/[^a-z0-9]+/g, "-");
  return `${s}@overlyne.tn`;
}
