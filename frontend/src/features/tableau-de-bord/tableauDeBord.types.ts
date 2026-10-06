
import type { ReactNode } from "react";

export interface TopClient { client: string; nom?: string; revenue: number; invoices: number; share: number; rank: number; risque?: number; risk_score?: number | null; }
export interface PeriodeReference {
  code: "12m" | "annee" | "tout" | "personnalisee"; libelle: string;
  debut: string | null; fin: string | null;
  evolution_pct?: number | null; libelle_comparaison?: string;
  ca_precedent_dt?: number; clients_precedent?: number;
}
/** Un sens de délai : ce qu'Overlyne accorde, ou ce qu'elle obtient. */
export interface SensDelai {
  moyenne_par_facture_j: number;
  moyenne_ponderee_j: number;
  n_factures: number;
  montant_dt: number;
  sens: string;
}

export interface TrancheDelai {
  code: string; tranche: string; signification: string;
  montant_dt: number; n_factures: number; part_pct: number | null;
}

export interface Delais {
  accorde_aux_clients: SensDelai;
  obtenu_des_fournisseurs: SensDelai;
  ecart_j: number;
  ecart_sens: string;
  ecart_lecture: string;
  tresorerie_cycle_dt: number | null;
  tresorerie_cycle_libelle: string;
  tresorerie_cycle_methode: string;
  repartition: TrancheDelai[];
  nature: string;
  ce_n_est_pas: string;
  seuil_surveillance_j: number;
  part_au_dela_du_seuil_pct: number | null;
}

export interface KPIs {
  periode_reference?: PeriodeReference;
  delais?: Delais;
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
  echelonnement_delais_accordes: { bucket: string; montant: number }[];
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
  factures_delai_sup_90j: number | null; factures_delai_sup_30j: number | null; factures_delai_sup_60j: number | null;
  part_factures_delai_sup_60j_pct: number | null;
  montant_delai_sup_60j_ttc: number | null; montant_delai_sup_90j_ttc: number | null;
  exposition_recente_dt: number | null; exposition_recente_critique_dt: number | null;
  exposition_recente_count: number | null; exposition_recente_periode: string | null;
  hhi_clients: number | null; hhi_fournisseurs: number | null; top_clients_revenue_share: number | null;
  achats_total_ttc: number | null; nb_fournisseurs: number | null; nb_factures_achat: number | null;
  marge_brute: number | null; taux_marge: number | null; marge_quality_score: number | null; marge_note: string;
  nb_devis: number | null; montant_devis_total: number | null; taux_conversion_devis: number | null;
  devis_transformes?: number | null; taux_conversion_note?: string;
  marge_source?: string; marge_ca_reference_dt?: number | null; marge_cout_revient_dt?: number | null;
  marge_lignes_exclues?: number | null; marge_lignes_exclues_pct?: number | null;
  nb_bl: number | null; nb_produits: number | null; anomalies_detectees: number; anomalies_details: string[];
  churn_anticipe?: { servi: boolean; masque?: boolean; motif?: string; n_au_dessus_de_0_5?: number; enjeu_total_dt?: number };
  segmentation?: {
    servi: boolean; masque?: boolean; motif?: string; n_segments?: number; n_clients?: number;
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

export interface FiltresPayload {
  selected_years: number[]; selected_clients: string[]; fidelity_filter: string;
  date_start: string | null; date_end: string | null; payment_modes: string[];
  risk_level: string; min_amount: number | null; max_amount: number | null;
  periode: string;
  [cle: string]: unknown;
}

export interface ReponseTableauDeBord { kpis?: KPIs; filters?: FiltersData; error?: string }

export interface CarteAgrandie { title: string; render: (h: number) => ReactNode }

export interface Jauge { value: number; label: string; color: string }
