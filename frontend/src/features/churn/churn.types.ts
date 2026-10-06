
import type { Contrefactuel, Raison } from "@/shared/ui/Pourquoi";

export interface ChurnClient {
  code: string;
  nom?: string;
  probabilite_decrochage: number;
  recence_j: number;
  intervalle_moyen_j: number;
  ca_12m: number;
  freq_12m: number;
  tendance_ca: number;
  enjeu_dt: number;
  raisons?: Raison[];
  contrefactuel?: Contrefactuel | null;
}
export interface ChurnData {
  servi: boolean;
  motif?: string;
  masque?: boolean;
  portee?: string;
  n_clients_filtre?: number;
  n_clients_scores?: number;
  n_au_dessus_de_0_5?: number;
  enjeu_total_dt?: number;
  top?: ChurnClient[];
}
