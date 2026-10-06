
import type { Raison } from "@/shared/ui/Pourquoi";

export type CodeProtocole = "appeler" | "appel_offres" | "traiter_en_lot" | "laisser";

export interface DevisLigne {
  client: string; nom?: string; piece_no: string; date: string;
  age_j: number;
  montant_ht_dt: number; probabilite: number; esperance_dt: number;
  protocole: CodeProtocole;
  est_client: boolean;
  raisons?: Raison[];
}

export interface Protocole {
  code: CodeProtocole; libelle: string; quoi_faire: string;
  n_devis: number; montant_ouvert_dt: number; esperance_dt: number;
  n_clients: number; age_median_j: number;
}

export interface TrancheConversion {
  tranche: string; n_devis: number; n_signes: number;
  taux_pct: number | null; montant_dt: number;
}

export interface ReperesConversion {
  servi?: boolean;
  par_tranche_de_montant?: TrancheConversion[];
  maturation_mois?: number;
  non_jugeables?: { n_devis: number; montant_dt: number; motif: string };
  lecture?: string;
  source?: string;
}

/** Un groupe de la courbe de calibration : annoncé contre observé. */
export interface CalibrationGroupe {
  groupe: number;
  n_devis: number;
  n_signes: number;
  probabilite_predite_moyenne_pct: number;
  taux_observe_pct: number;
  probabilite_min_pct: number;
  probabilite_max_pct: number;
  ecart_pt: number;
}

/**
 * La calibration du modèle de conversion, mesurée hors période.
 *
 * Ne dépend d'aucun filtre : elle porte sur le test du modèle, pas sur les
 * devis affichés.
 */
export interface CalibrationDevis {
  applicable: boolean;
  motif?: string;
  n_groupes?: number;
  n_devis?: number;
  /** Écart absolu moyen entre probabilité annoncée et taux observé, en points. */
  ece_pt?: number;
  /** Écart signé : positif = modèle optimiste = espérance surestimée. */
  biais_pt?: number;
  sens_du_biais?: string;
  par_groupe?: CalibrationGroupe[];
  lecture?: string;
  pourquoi_hors_periode?: string;
}

export interface DevisData {
  servi: boolean; motif?: string;
  n_devis?: number;
  montant_ouvert_total_dt?: number;
  esperance_totale_dt?: number;
  n_clients_concernes?: number;
  horizon_maturation_mois?: number;
  protocoles?: Protocole[];
  seuils?: { montant_gros_dt: number; chance_haute_pct: number; age_devis_mort_j: number };
  reperes?: ReperesConversion;
  calibration?: CalibrationDevis;
  top?: DevisLigne[];
}

export interface MargeLigne {
  client: string; nom?: string; probabilite: number; marge_actuelle_pct: number;
  marge_12m_pct: number; ca_12m_dt: number; marge_en_jeu_dt: number;
  seuil_pct?: number; mediane_pct?: number; ecart_au_seuil_pct?: number;
  part_equipement_pct?: number; part_reactif_pct?: number;
  deja_sous_le_seuil?: boolean;
  raisons?: Raison[];
}

export interface MargeData {
  servi: boolean; motif?: string;
  horizon_mois?: number;
  seuil_marge_basse_pct?: number;
  marge_mediane_portefeuille_pct?: number;
  menace_definition?: string;
  menace_vis_a_vis_de_qui?: string;
  marge_en_jeu_definition?: string;
  cause_principale?: string;
  top?: MargeLigne[];
}
export interface RecoProduit { designation: string; famille: string; montant_annuel_median_par_acheteur_dt: number; raisons?: Raison[] }
export interface RecoClient { client: string; nom: string; potentiel_top3_dt: number; produits: RecoProduit[] }
export interface RecoData { servi: boolean; motif?: string; horizon_mois?: number; top?: RecoClient[] }

export interface CaClientLigne {
  client: string; nom?: string;
  ca_attendu_dt: number; ca_passe_dt: number; ecart_vs_passe_dt: number;
  /** Les 12 derniers mois ramenés à l'horizon : le rythme de croisière. */
  rythme_habituel_dt?: number;
  /** De combien la fenêtre de comparaison s'écarte de ce rythme, en %. */
  base_vs_rythme_pct?: number;
  raisons?: Raison[];
}

export interface FenetresCa {
  passe_debut: string; passe_fin: string;
  futur_debut: string; futur_fin: string;
  derniere_donnee: string; lecture: string;
}

export interface CaClientData {
  servi: boolean; motif?: string; horizon_mois?: number;
  n_clients?: number; ca_attendu_total_dt?: number;
  fenetres?: FenetresCa;
  mesure?: string;
  top?: CaClientLigne[];
}

export interface Portee { masque?: boolean; portee?: string; n_clients_filtre?: number }

export interface DonneesCommerciales {
  devis: DevisData & Portee; marge: MargeData & Portee;
}
