/**
 * Model — devis à relancer, marge menacée, produits à proposer.
 */
import type { Raison } from "@/shared/ui/Pourquoi";

export interface DevisLigne {
  client: string; nom?: string; piece_no: string; date: string;
  montant_ht_dt: number; probabilite: number; esperance_dt: number; est_client: boolean;
  raisons?: Raison[];
}
export interface DevisData { servi: boolean; motif?: string; n_devis?: number; esperance_totale_dt?: number; top?: DevisLigne[] }
export interface MargeLigne {
  client: string; nom?: string; probabilite: number; marge_actuelle_pct: number;
  marge_12m_pct: number; ca_12m_dt: number; marge_en_jeu_dt: number;
  raisons?: Raison[];
}
export interface MargeData { servi: boolean; motif?: string; top?: MargeLigne[] }
export interface RecoProduit { designation: string; famille: string; montant_annuel_median_par_acheteur_dt: number; raisons?: Raison[] }
export interface RecoClient { client: string; nom: string; potentiel_top3_dt: number; produits: RecoProduit[] }
export interface RecoData { servi: boolean; motif?: string; horizon_mois?: number; top?: RecoClient[] }

export interface DonneesCommerciales { devis: DevisData; marge: MargeData; reco: RecoData }
