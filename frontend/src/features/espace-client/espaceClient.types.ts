/**
 * Model — portail client : factures, demandes, produits proposés.
 */

export interface Invoice {
  date: string; echeance: string | null; montant_ttc: number;
  delai_jours: number | null; mode_reglement: string | null; statut: string;
}
export interface InvoicesData {
  error?: string; client_code?: string; invoices: Invoice[];
  total_factures?: number; total_ttc?: number; encours_retard_ttc?: number;
}
export interface Demande {
  id: number; type: string; sujet: string; message: string;
  invoice_ref: string | null; status: string; reponse: string | null;
  created_at: string | null; updated_at: string | null;
}
export interface Produit { reference: string; designation: string; famille: string | null; deja_signale: boolean }

export interface DonneesEspace {
  inv: InvoicesData | null; erreur: string | null;
  demandes: Demande[]; produits: Produit[];
}

/** Action ouverte sur une facture précise. */
export interface ActionFacture { facture: Invoice; mode: "promesse" | "reclamation" }
