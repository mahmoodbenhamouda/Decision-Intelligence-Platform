
export type Couverture = true | false | "partielle";

export interface EtapeAppro {
  rang: number;
  code: string;
  couverte: Couverture;
  titre?: string;
  ce_qu_on_voit?: string;
  ce_qui_manque?: string;
  pourquoi_absent?: string;
  /** Ce que la plateforme produit là où l'ERP est muet. */
  comble_par_la_plateforme?: string;
  /** Vrai dès que la boucle a réellement créé cette donnée. */
  comblee_par_la_plateforme?: boolean;
  source?: string;
  chiffres?: Record<string, number | string | null>;
}

export interface LigneFournisseur {
  nom: string; code: string; pays: string;
  montant_dt: number; part_pct: number;
  n_factures: number; n_references: number;
  delai_obtenu_j: number | null;
  dernier_achat: string | null;
}

export interface LignePays {
  pays: string; n_fournisseurs: number; montant_dt: number; part_pct: number;
}

export interface Fournisseurs {
  top: LigneFournisseur[];
  n_fournisseurs: number;
  achats_total_dt: number;
  hhi: number;
  hhi_lecture?: string;
  hhi_methode?: string;
  par_pays: LignePays[];
  dependance: {
    fournisseur: string | null;
    part_pct: number | null;
    critique: boolean;
    seuil_pct: number;
    consequence?: string;
  };
}

export interface MonoSource {
  n_references: number;
  n_mono_source: number;
  part_mono_source_pct: number;
  montant_mono_source_dt: number;
  top: {
    reference: string; designation: string; fournisseur: string;
    montant_dt: number; dernier_achat: string | null;
  }[];
  lecture: string;
}

export interface Reappro {
  intervalle_median_j: number | null;
  intervalle_moyen_j: number | null;
  n_intervalles: number;
  n_references: number;
  derniere_donnee: string | null;
  a_recommander: {
    reference: string; designation: string;
    intervalle_median_j: number; n_reappros: number;
    dernier_achat: string | null; jours_depuis: number;
    retard_x: number | null; derniere_vente: string | null;
  }[];
  regle: string;
  ce_n_est_pas: string;
}

export interface PositionStock {
  n_produits: number;
  n_rapproches: number;
  n_position_negative: number;
  n_avec_consommation: number;
  part_rapprochee_pct: number | null;
  premier_achat: string | null;
  dernier_achat: string | null;
  pourquoi_negatif: string;
}

export interface BoucleAppro {
  n_commandes?: number;
  n_receptions?: number;
  n_ouvertes?: number;
  montant_engage_dt?: number;
}

export interface ProduitConsomme {
  reference: string;
  designation: string;
  quantite: number;
  ca_dt: number;
  mois_actifs: number;
  derniere_vente: string | null;
  dernier_achat: string | null;
  rythme_reassort_j: number | null;
  jours_depuis_achat: number | null;
  approvisionnement_menace: boolean;
}

/** Ce que les clients filtrés consomment, et ce qui risque la rupture. */
export interface ConsommationClient {
  n_clients: number;
  n_produits: number;
  ca_total_dt: number;
  n_produits_menaces: number;
  ca_menace_dt: number;
  part_menacee_pct: number | null;
  produits: ProduitConsomme[];
  menaces: ProduitConsomme[];
  lecture: string;
  periode: string;
}

export interface ProcessusAppro {
  servi: boolean;
  motif?: string;
  boucle?: BoucleAppro;
  consommation_client?: ConsommationClient | Record<string, never>;
  fournisseurs?: Fournisseurs;
  mono_source?: MonoSource;
  reapprovisionnement?: Reappro;
  stock?: PositionStock;
  etapes?: EtapeAppro[];
}
