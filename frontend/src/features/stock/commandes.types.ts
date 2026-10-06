
export type StatutCommande =
  | "recommandee" | "validee" | "refusee" | "commandee" | "recue" | "annulee";

export interface Commande {
  id: number;
  reference: string;
  designation: string | null;
  fournisseur_code: string | null;
  fournisseur_nom: string | null;
  origine: "ia" | "manuelle";
  motif: string | null;
  qte_proposee: number;
  qte_recue: number | null;
  montant_estime_dt: number;
  statut: StatutCommande;
  statut_label: string;
  prochain_geste: string;
  motif_refus: string | null;
  commentaire: string | null;
  decide_at: string | null;
  commande_at: string | null;
  recue_at: string | null;
  /** Commande → réception. La donnée que l'ERP ne porte pas. */
  delai_livraison_j: number | null;
  created_at: string | null;
  ouverte: boolean;
}

export interface Proposition {
  reference: string;
  designation: string;
  intervalle_median_j: number;
  n_reappros: number;
  dernier_achat: string | null;
  jours_depuis: number;
  retard_x: number | null;
  derniere_vente: string | null;
  qte_proposee: number | null;
  montant_estime_dt: number | null;
  fournisseur_code: string | null;
  fournisseur_nom: string | null;
}

export interface Recommandations {
  servi: boolean;
  motif?: string;
  propositions?: Proposition[];
  n_proposees?: number;
  n_deja_traitees?: number;
  base_de_la_proposition?: string;
  regle?: string;
}

export interface DelaiLivraison {
  mesurable: boolean;
  n_receptions: number;
  median_j: number | null;
  min_j: number | null;
  max_j: number | null;
  origine: string;
  motif_si_absent: string | null;
}

export interface BilanCommandes {
  par_statut: { statut: StatutCommande; label: string; n: number }[];
  n_total: number;
  n_ouvertes: number;
  montant_engage_dt: number;
  delai_livraison: DelaiLivraison;
}
