/**
 * Model — le briefing produit par la flotte d'agents (/api/fleet/briefing).
 */

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
  // Reprise des raisons produites par le modèle qui a signalé ces entités :
  // le briefing dit quoi faire, ceci dit pourquoi eux.
  pourquoi?: { sujet: string; raisons: string[] }[];
  enjeu_court_terme_dt?: number;
  classement?: Constat[];
  clients_multi_signaux?: { client: string; domaines: string[]; montant_cumule_dt: number }[];
}
export interface Briefing {
  findings?: Constat[];
  error?: string;
}
