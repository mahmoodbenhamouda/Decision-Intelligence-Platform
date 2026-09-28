/**
 * Model — règles de la saisie vérifiée : champs contrôlables avant
 * enregistrement, valeur lue par champ, normalisation pour détecter une
 * correction (chaque correction est conservée pour le réentraînement).
 */
import type { InvoiceFields, TypeChamp } from "./ocr.types";

export const SOURCE_ECHEANCE: Record<string, string> = {
  lue: "lue sur la facture", delai_tiers: "délai habituel du tiers", delai_moyen: "délai moyen",
};

/* Champs vérifiables avant enregistrement. Chaque écart avec la lecture est
   conservé comme correction : c'est la matière du réentraînement. */
export const CHAMPS: { cle: keyof InvoiceFields; label: string; type: TypeChamp }[] = [
  { cle: "numero", label: "N° de facture", type: "texte" },
  { cle: "fournisseur", label: "Fournisseur (émetteur)", type: "texte" },
  { cle: "client", label: "Client (destinataire)", type: "texte" },
  { cle: "date_facture", label: "Date", type: "date" },
  { cle: "date_echeance", label: "Échéance", type: "date" },
  { cle: "montant_ht", label: "Montant HT", type: "montant" },
  { cle: "montant_tva", label: "TVA", type: "montant" },
  { cle: "timbre_fiscal", label: "Timbre fiscal", type: "montant" },
  { cle: "montant_ttc", label: "Montant TTC", type: "montant" },
  { cle: "net_a_payer", label: "Net à payer", type: "montant" },
  { cle: "matricule_fiscal", label: "Matricule fiscal", type: "texte" },
];
export function versSaisie(v: unknown, type: TypeChamp): string {
  if (v == null || v === "") return "";
  if (type === "montant") { const n = Number(v); return Number.isNaN(n) ? String(v) : n.toFixed(3); }
  if (type === "date") return String(v).slice(0, 10);
  return String(v);
}
// Sans LayoutLMv3, les règles ne remplissent que `tiers` (surtout le client).
export function lectureDe(f: InvoiceFields, cle: keyof InvoiceFields): unknown {
  return cle === "client" ? (f.client ?? f.tiers) : f[cle];
}
export function brouillon(f: InvoiceFields): Record<string, string> {
  const s: Record<string, string> = {};
  for (const c of CHAMPS) s[c.cle] = versSaisie(lectureDe(f, c.cle), c.type);
  return s;
}
export function normSaisie(t: string, type: TypeChamp): string {
  const v = t.trim();
  if (!v) return "";
  if (type === "montant") {
    const n = parseFloat(v.replace(/[\s\u202f]/g, "").replace(",", "."));
    return Number.isNaN(n) ? v : n.toFixed(3);
  }
  return v.replace(/\s+/g, " ");
}
