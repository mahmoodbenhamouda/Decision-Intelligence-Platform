/**
 * Model — tâches confiées, résultats et impact (boucle d'action).
 */

/** L'alerte d'origine d'une tâche, reprise telle quelle dans la fenêtre « Confier ». */
export interface Origine {
  titre: string;
  categorie?: string;
  severite?: string;
  montant_dt?: number;
  client_code?: string;
  client_nom?: string;
  details?: string;
}

/** Collègue proposé dans la fenêtre « Confier » (avec sa charge actuelle). */
export interface EmployeAssignable {
  id: number; nom: string; email: string; poste: string | null; taches_ouvertes: number;
}

/** Ce que le serveur sait d'une alerte déjà confiée. */
export interface Confiee {
  id: number;
  assigne_nom: string | null;
  statut: string;
  echeance: string | null;
}

/* ── Suivi des actions ── */
export interface Tache {
  id: number; client_code: string | null; client_nom: string | null;
  origine_categorie: string | null; origine_titre: string | null;
  venue_du_client: boolean; type: string; type_label: string; titre: string;
  details: string | null; montant_dt: number; severite: string;
  assigne_id: number | null; assigne_nom: string | null; cree_par: string | null;
  echeance: string | null; en_retard: boolean; statut: string;
  resultat: string | null; resultat_label: string | null;
  resultat_montant_dt: number | null; resultat_commentaire: string | null;
  created_at: string | null; closed_at: string | null;
}
export interface Impact {
  taches_total: number; taches_ouvertes: number; taches_en_retard: number;
  taches_terminees: number; en_jeu_dt: number; recupere_dt: number;
  promesses_dt: number; taux_reussite: number | null; delai_moyen_j: number | null;
  par_resultat: { resultat: string; label: string; nombre: number; montant_dt: number }[];
  par_mois: { mois: string; montant_dt: number; nombre: number }[];
}
export interface EmployeCharge { id: number; nom: string; poste: string | null; taches_ouvertes: number }
export interface Boucle {
  disponible: boolean; taches?: number; gagnees?: number; retours_produits?: number;
  resultats_enregistres?: number; en_attente_de_transfert?: number; motif?: string;
}

/** Tout ce que l'onglet « Suivi des actions » charge en une fois. */
export interface DonneesSuivi {
  taches: Tache[];
  impact: Impact | null;
  employes: EmployeCharge[] | null;
  boucle: Boucle | null;
}

/** Corps envoyé à l'API pour créer une tâche. */
export interface NouvelleTache {
  titre: string; type: string; details: string | null;
  client_code: string | null; client_nom: string | null;
  origine_categorie: string | null; origine_titre: string;
  severite: string; montant_dt: number;
  assigne_id: number | null; echeance: string | null;
}
