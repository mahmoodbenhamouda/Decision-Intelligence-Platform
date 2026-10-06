
export type Mode = "facture" | "texte" | "rag";

export interface OcrMeta {
  text: string; confidence: number; source: string; pages: number;
  engine: string; quality: string; warnings: string[];
}
export interface InvoiceFields {
  numero: string | null; date_facture: string | null; date_echeance: string | null;
  montant_ht: number | null; montant_tva: number | null; montant_ttc: number | null;
  taux_tva: number | null; timbre_fiscal: number | null; net_a_payer: number | null;
  devise: string; tiers: string | null; matricule_fiscal: string | null;
  fournisseur?: string | null; client?: string | null;
  champs_confiance: Record<string, string>; coherence: string | null;
  avertissements: string[]; is_invoice: boolean;
}
export interface Candidate {
  client_code: string; client_nom: string; date: string; echeance: string | null;
  montant_ttc: number; ecart_montant: number; score: number; explication: string;
}
export interface Reconciliation {
  statut: string; message: string; candidats: Candidate[];
  sens?: Sens; genre_tiers?: string; erp_jusqu_au?: string | null;
}
export interface InvoiceResponse {
  filename: string; ocr: OcrMeta; facture: InvoiceFields; rapprochement: Reconciliation | null;
  moteur?: string;
  lecture_id?: string;
  sens?: { sens: "achat" | "vente" | "inconnu"; confiance: string | null; motif: string };
  entreprise?: { configuree: boolean; nom: string | null };
}
export interface ImportResult {
  ok?: boolean; numero?: string; client_code?: string; client_name?: string;
  statut_client?: string; motif_rattachement?: string; montant_ttc?: number;
  net_a_payer?: number; n_factures_client?: number; total_importe_client_dt?: number;
  message?: string; erreur?: string; action_requise?: string;
  candidats?: { code: string; nom: string; score: number }[];
  sens?: Sens; tiers_code?: string; tiers_nom?: string; genre_tiers?: string;
  n_factures_tiers?: number; total_importe_tiers_dt?: number;
  statut_validation?: string; n_corrections?: number;
}

export type Sens = "achat" | "vente";
export interface LigneEcheance {
  id: number; numero: string; sens: Sens; tiers: string | null; echeance: string;
  source_echeance: string; montant_dt: number; statut: "a_venir" | "en_retard";
  jours_de_retard: number; rapprochement_statut: string;
}
export interface Echeancier {
  a_payer_dt: number; a_encaisser_dt: number; a_payer_en_retard_dt: number;
  a_encaisser_en_retard_dt: number; n_factures: number; n_echeances_deduites: number;
  mois: { periode: string; decaissements_dt: number; encaissements_dt: number; solde_dt: number; n: number }[];
  factures: LigneEcheance[]; note: string;
}

export type TypeChamp = "texte" | "date" | "montant";

export interface EtatMoteur { ok: boolean; info: string; motif: string; cause: string }

export interface Reponse<T = Record<string, unknown>> { ok: boolean; status: number; data: T }
