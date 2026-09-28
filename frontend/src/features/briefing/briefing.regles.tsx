/**
 * Model — domaines des agents, ordre des gravités, et l'alerte « compte à
 * signaux multiples » telle qu'elle part en tâche.
 */
import type { ReactNode } from "react";
import {
  FileSignature, Landmark, Percent, Truck, UserMinus, Wallet, Warehouse,
} from "lucide-react";
import type { Origine } from "@/features/taches/taches.types";

export const TECHNIQUE = "Qualité des modèles";

export const DOMAINE: Record<string, { label: string; icone: ReactNode }> = {
  Recouvrement: { label: "Encaissements", icone: <Wallet size={15} /> },
  "Trésorerie": { label: "Trésorerie", icone: <Landmark size={15} /> },
  "Rétention": { label: "Fidélité clients", icone: <UserMinus size={15} /> },
  Stock: { label: "Stock", icone: <Warehouse size={15} /> },
  Commercial: { label: "Ventes", icone: <FileSignature size={15} /> },
  "Rentabilité": { label: "Rentabilité", icone: <Percent size={15} /> },
  Approvisionnement: { label: "Fournisseurs", icone: <Truck size={15} /> },
};
export const DOMAINE_AGENT: Record<string, string> = {
  Recouvrement: "Encaissements", "Risque client": "Fidélité clients",
  Commercial: "Ventes", "Trésorerie": "Trésorerie", Stock: "Stock",
  Approvisionnement: "Fournisseurs",
};
export const ORDRE_SEV: Record<string, number> = { critique: 0, haute: 1, moyenne: 2, faible: 3 };

export function premierePhrase(t: string) {
  const i = t.search(/[.;:](\s|$)/);
  return i > 20 ? t.slice(0, i + 1) : t;
}

/**
 * L'alerte « ce compte cumule plusieurs signaux », telle qu'elle part en tâche.
 *
 * Fabriquée à un seul endroit : son `titre` sert à la fois d'intitulé de
 * l'alerte et de clé pour savoir si elle est déjà confiée. Deux formulations
 * différentes, et le bouton reviendrait sur une action déjà traitée.
 */
export function origineClient(c: { client: string; domaines: string[]; montant_cumule_dt: number }): Origine {
  return {
    titre: `Faire le point avec ${c.client}`,
    categorie: c.domaines[0] || "Clients",
    severite: "haute",
    montant_dt: c.montant_cumule_dt,
    client_nom: c.client,
    details: `Ce compte apparaît dans plusieurs domaines : ${c.domaines
      .map(d => DOMAINE_AGENT[d] || d).join(", ")}.`,
  };
}
