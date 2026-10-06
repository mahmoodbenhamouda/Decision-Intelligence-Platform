
import type { Raison } from "@/shared/ui/Pourquoi";

export interface Supplier { fournisseur: string; part_pct: number; achats_dt: number; n_factures: number }
export interface Forecast {
  period: string; qte: number;
  bas?: number | null; haut?: number | null; fiabilite?: string;
}
export interface SupplyData {
  demande_mape?: number | null;
  demande_methode?: string;
  demande_prevision?: Forecast[];
  /** Vrai tant que l'erreur reste sous le seuil déclaré d'exploitabilité. */
  demande_exploitable?: boolean;
  demande_seuil_mape?: number;
  demande_reserve?: string;
  /** Motif quand l'historique du périmètre filtré est trop court. */
  demande_motif?: string;
  perimetre?: { n_clients: number; libelle: string };
  fournisseurs_nb?: number;
  fournisseurs_hhi?: number;
  fournisseur_top1_pct?: number;
  fournisseurs_top3_pct?: number;
  fournisseurs_top?: Supplier[];
  dependance_fournisseur?: string;
  error?: string;
}

export interface Prevision {
  produit: string; derniere_periode: string;
  demande_observee_dernier_mois: number; moyenne_3m: number;
  prevision_30j: number; prevision_60j: number; prevision_90j: number;
}
export interface ForecastData {
  error?: string; previsions?: Prevision[];
}

export interface Obsolescence {
  produit: string; position: number; conso_mensuelle: number; mois_couverture: number;
  valeur_stock_dt: number; perte_probable_dt: number; gravite: string;
}
export interface RuptureReelle {
  produit: string; conso_mensuelle: number; mois_sans_approvisionnement: number;
  cout_unitaire_dt: number; quantite_suggeree: number; gravite: string;
}
export interface FluxReel {
  disponible: boolean; motif?: string;
  n_references_accumulees?: number; valeur_immobilisee_dt?: number;
  n_references_plus_de_2_ans?: number; n_ruptures?: number; n_ruptures_critiques?: number;
  budget_commandes_dt?: number; ruptures?: RuptureReelle[]; obsolescence?: Obsolescence[];
  n_obsoletes_certains?: number; perte_quasi_certaine_dt?: number;
  top?: { produit: string; position: number; valeur_dt: number; conso_mensuelle: number; mois_couverture: number }[];
}
export interface FinDeVie {
  servi: boolean; capital_expose_total_dt?: number;
  top?: { produit: string; valeur_stock_dt: number; capital_expose_dt: number;
          n_clients_12m: number; mois_sans_vente: number; raisons?: Raison[] }[];
}
export interface StockData { error?: string; masque?: boolean; flux_reel?: FluxReel; fin_de_vie?: FinDeVie }
