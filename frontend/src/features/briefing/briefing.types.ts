
import type { Execution } from "@/features/taches/taches.types";

export interface ClientMultiSignaux {
  client: string;
  domaines: string[];
  montant_cumule_dt: number;

  categorie?: string | null;
  execution?: Execution | null;
}

export interface Cible {
  nom: string;
  code?: string | null;
  montant_dt: number;
  /** Part de l'« en jeu » de la carte (même pondération) : additionnable avec la carte. */
  enjeu_dt?: number;
  motif: string;
  tache: { type: string; titre: string };
}

export interface Constat {
  agent: string;
  categorie: string;
  severite: string;
  titre: string;
  resume?: string;
  montant_dt: number;
  constat: string;
  action: string;
  rang?: number;

  pourquoi?: { sujet: string; raisons: string[] }[];
  enjeu_court_terme_dt?: number;

  execution?: Execution | null;
  classement?: Constat[];
  clients_multi_signaux?: ClientMultiSignaux[];
  clients_concernes?: Cible[];
  produits_concernes?: Cible[];
}
export interface Briefing {
  findings?: Constat[];
  portee_modeles?: { mode: string; motif: string; n_clients: number };
  error?: string;
}
