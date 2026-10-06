
export interface CategorieMarge {
  code: string;
  nom: string;
  role: string;
  ca_dt: number;
  cout_dt: number;
  marge_dt: number;
  taux_marge_pct: number | null;
  part_du_ca_pct: number | null;
  part_de_la_marge_pct: number | null;
  n_lignes: number;
}

export interface ProduitMarge {
  reference: string;
  designation: string;
  categorie: string;
  ca_dt: number;
  cout_dt: number;
  marge_dt: number;
  taux_marge_pct: number | null;
  n_clients: number;
  part_de_la_marge_pct?: number;
}

export interface PointTendance {
  period: string;
  ca_dt: number;
  marge_dt: number;
  taux_marge_pct: number | null;
}

export interface EtapeWaterfall {
  etape: string;
  valeur_dt: number;
  genre: "depart" | "negatif" | "total";
}

export interface LimitesMarge {
  nature?: string;
  ce_qui_est_deduit?: string;
  ce_qui_n_est_pas_deduit?: string;
  lignes_ecartees?: number;
  lignes_ecartees_pct?: number | null;
  lignes_ecartees_motif?: string;
  ca_ecarte_dt?: number;
  lignes_offertes?: number;
  cout_offert_dt?: number;
  lignes_offertes_motif?: string;
  lignes_retour?: number;
  ca_retour_dt?: number;
  lignes_retour_motif?: string;
}

/** L'année en cours n'est pas une année : il y manque des mois. */
export interface Completude {
  annee: number;
  mois_couverts: number;
  mois_dans_l_annee: number;
  dernier_mois: string;
  incomplete: boolean;
  marge_realisee_dt: number;
  ca_realise_dt: number;
  comparaison: {
    annee: number;
    marge_meme_periode_dt: number;
    marge_annee_complete_dt: number;
    part_de_l_annee_pct: number | null;
    evolution_pct: number | null;
  };
  projection_fin_d_annee_dt: number | null;
  projection_methode: string;
  projection_limite: string;
}

export interface MargeDecomposee {
  servi: boolean;
  motif?: string;
  nature?: string;
  periode_reference?: { code: string; libelle: string; debut?: string | null; fin?: string | null };
  completude?: Completude | Record<string, never>;
  par_categorie?: {
    categories: CategorieMarge[];
    total_ca_dt: number;
    total_marge_dt: number;
    taux_ensemble_pct: number | null;
  };
  produits?: {
    porteurs: ProduitMarge[];
    pertes: ProduitMarge[];
    n_references: number;
    perte_totale_dt: number;
    lecture_des_pertes: string;
  };
  tendance?: PointTendance[];
  limites?: LimitesMarge;
  waterfall?: EtapeWaterfall[];
}
