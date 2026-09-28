/**
 * Model — indicateurs du tableau de bord et filtres (/api/dashboard).
 */
import type { ReactNode } from "react";

export interface TopClient { client: string; nom?: string; revenue: number; invoices: number; share: number; rank: number; risque?: number; risk_score?: number | null; }
export interface KPIs {
  ca_total_ttc: number | null; ca_total_ht: number | null; nb_clients: number | null;
  nb_factures_vente: number | null; panier_moyen: number | null; dso_jours: number | null;
  dpo_jours: number | null; cash_conversion_cycle: number | null;
  monthly_sales: { period: string; revenue: number }[];
  forecast_next: { period: string; montant: number }[];
  yoy_comparison: { current_year: number | null; previous_year: number | null; delta_pct: number | null; data: { month: string; courante: number | null; precedente: number | null }[] };
  waterfall: { step: string; value: number; kind: string }[];
  yearly_sales: { year: number; revenue: number }[];
  seasonality: { month: string; revenue: number }[];
  sales_vs_purchases: { period: string; ventes: number; achats: number }[];
  monthly_margin: { period: string; marge: number }[];
  aging_creances: { bucket: string; montant: number }[];
  payment_mix: { mode: string; montant: number; count: number }[];
  client_pareto: { pct_clients: number; pct_ca: number }[];
  cash_forecast: { period: string; montant: number }[];
  amount_distribution: { tranche: string; count: number }[];
  top_clients: TopClient[];
  top_fournisseurs: { fournisseur: string; montant: number; share: number; rank: number }[];
  top_produits: { produit: string; ca: number; qte: number }[];
  top_familles: { famille: string; ca: number }[];
  clients_a_risque: { client: string; nom?: string; montant_risque: number; factures: number; risk_score?: number | null }[];
  risk_ranking: { client: string; nom?: string; score: number; exposure: number; avg_delay: number; priority: number }[];
  nb_clients_risque_predit: number | null; exposition_risque_ponderee: number | null; risk_model_active?: boolean;
  funnel: { etape: string; valeur: number }[];
  mom_growth: number | null; yoy_growth: number | null; ttm_revenue: number | null; tendance: string;
  retards_critiques: number | null; retards_30j: number | null; retards_60j: number | null;
  paiements_a_risque_pct: number | null; paiements_a_risque_count: number | null;
  montant_risque_ttc: number | null; montant_critique_ttc: number | null;
  exposition_recente_dt: number | null; exposition_recente_critique_dt: number | null;
  exposition_recente_count: number | null; exposition_recente_periode: string | null;
  ca_retard_historique_ttc: number | null;
  hhi_clients: number | null; hhi_fournisseurs: number | null; top_clients_revenue_share: number | null;
  achats_total_ttc: number | null; nb_fournisseurs: number | null; nb_factures_achat: number | null;
  marge_brute: number | null; taux_marge: number | null; marge_quality_score: number | null; marge_note: string;
  nb_devis: number | null; montant_devis_total: number | null; taux_conversion_devis: number | null;
  devis_transformes?: number | null; taux_conversion_note?: string;
  marge_source?: string; marge_ca_reference_dt?: number | null; marge_cout_revient_dt?: number | null;
  marge_lignes_exclues?: number | null; marge_lignes_exclues_pct?: number | null;
  nb_bl: number | null; nb_produits: number | null; anomalies_detectees: number; anomalies_details: string[];
  churn_anticipe?: { servi: boolean; n_au_dessus_de_0_5?: number; enjeu_total_dt?: number };
  segmentation?: {
    servi: boolean; n_segments?: number; n_clients?: number;
    segments?: {
      segment: number; nom: string; caracterisation: string;
      n_clients: number; part_clients_pct: number;
      ca_total_dt: number; part_ca_pct: number;
      panier_median_dt: number; commandes_medianes: number;
      part_menacee_pct?: number | null; ca_menace_dt?: number | null;
    }[];
  };
}
export interface FiltersData {
  available_years: number[]; available_clients: string[]; client_names?: Record<string, string>;
  fidelity_options: string[]; available_payment_modes: string[]; risk_levels: string[]; max_amount_possible: number;
}

/** Filtres envoyés à l'API (et partagés avec le briefing et le copilote). */
export interface FiltresPayload {
  selected_years: number[]; selected_clients: string[]; fidelity_filter: string;
  date_start: string | null; date_end: string | null; payment_modes: string[];
  risk_level: string; min_amount: number | null; max_amount: number | null;
  [cle: string]: unknown;
}

/** Réponse de /api/dashboard. */
export interface ReponseTableauDeBord { kpis?: KPIs; filters?: FiltersData; error?: string }

/** Graphe ouvert en grand (« spotlight »). */
export interface CarteAgrandie { title: string; render: (h: number) => ReactNode }

/** Jauge de santé financière. */
export interface Jauge { value: number; label: string; color: string }
