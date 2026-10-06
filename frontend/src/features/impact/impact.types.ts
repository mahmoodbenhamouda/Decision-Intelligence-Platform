
/** Un client qui porte une part du poste — « sur qui appeler demain matin ». */
export interface ImpactClient {
  client: string; nom: string;
  montant_identifie_dt: number;
  montant_recuperable_dt: number;
}

/**
 * Un poste d'enjeu financier.
 *
 * `montant_recuperable_dt` est TOUJOURS une part de `montant_identifie_dt` —
 * jamais un montant à côté. C'est ce qui permet de les dessiner l'un dans
 * l'autre plutôt que côte à côte, et d'interdire qu'on les additionne.
 */
export interface ImpactPoste {
  poste: string;
  cle: string;
  montant_identifie_dt: number;
  montant_recuperable_dt: number;
  hypothese_conversion: number;
  justification_hypothese: string;
  ce_qui_est_mesure: string;
  action_requise: string;
  source_du_chiffre: string;
  reserve: string | null;
  par_client: ImpactClient[];
}

/** Le chiffre qui ne s'additionne à aucun autre : une erreur supprimée. */
export interface ImpactCorrection {
  poste: string;
  montant_dt: number;
  nature: string;
  ce_qui_a_ete_corrige: string;
  pourquoi_isole: string;
  certitude: string;
}

export interface ImpactNonMesurable { apport: string; pourquoi_non_chiffre: string }

export interface ImpactData {
  servi: boolean;
  motif?: string;
  avertissement_principal?: string;
  montant_total_identifie_dt?: number;
  montant_total_recuperable_dt?: number;
  /** Les montants, dits en une phrase chacun — dérivées, jamais écrites en dur. */
  phrases?: string[];
  postes?: ImpactPoste[];
  correction_de_donnees?: ImpactCorrection;
  non_mesurable?: ImpactNonMesurable[];
  comment_verifier?: string;
}
