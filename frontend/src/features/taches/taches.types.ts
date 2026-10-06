
export interface Execution { poste: string; type: string }

export interface Origine {
  /** Clé de l'alerte d'origine (déduplication des tâches). */
  titre: string;
  /** Intitulé proposé pour la tâche, quand il diffère de la clé. */
  titre_tache?: string;

  categorie?: string;

  libelle?: string;
  severite?: string;
  montant_dt?: number;
  client_code?: string;
  client_nom?: string;
  details?: string;

  execution?: Execution | null;
}

export interface EmployeAssignable {
  id: number; nom: string; email: string; poste: string | null; taches_ouvertes: number;
}

export interface Confiee {
  id: number;
  assigne_nom: string | null;
  statut: string;
  echeance: string | null;

  par_la_flotte?: boolean;
}

export interface Tache {
  id: number; client_code: string | null; client_nom: string | null;
  origine_categorie: string | null; origine_titre: string | null;
  delegation_auto: boolean;
  type: string; type_label: string; titre: string;
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

  par_origine?: {
    origine: string; taches: number; terminees: number; gagnees: number;
    recupere_dt: number; taux_reussite: number | null;
  }[];
}
export interface EmployeCharge { id: number; nom: string; poste: string | null; taches_ouvertes: number }
export interface Boucle {
  disponible: boolean; taches?: number; gagnees?: number;
  resultats_enregistres?: number; en_attente_de_transfert?: number; motif?: string;
}

export interface DonneesSuivi {
  taches: Tache[];
  impact: Impact | null;
  employes: EmployeCharge[] | null;
  boucle: Boucle | null;
}

export interface NouvelleTache {
  titre: string; type: string; details: string | null;
  client_code: string | null; client_nom: string | null;
  origine_categorie: string | null; origine_titre: string;
  severite: string; montant_dt: number;
  assigne_id: number | null; echeance: string | null;
}

export interface LigneDelegation {
  rang: number; titre: string; categorie: string; poste: string; montant_dt: number;
  motif: string; issue: "creee" | "deja_confiee" | "recente"; tache_id?: number;
  assigne?: string | null; raison: string;
}
export interface PassageDelegation {
  id: number; declencheur: "planifie" | "manuel" | "commande"; lance_par: string | null;
  statut: "en_cours" | "ok" | "echec"; motif: string | null;
  debut: string | null; fin: string | null;
  n_propositions: number; n_creees: number; n_deja_confiees: number;
  n_recentes: number; n_decisions: number; n_ecartees: number;
  lignes: LigneDelegation[];
  decisions_direction: { titre: string; action: string }[];
  ecartes: { titre: string; raison: string }[];
  briefing?: string | null;
}
export interface EtatDelegation {
  active: boolean; heure: string; prochain_passage: string | null;
  regles: { charge_max: number; carence_jours: number };
  dernier: PassageDelegation | null;
  historique: PassageDelegation[];
}
