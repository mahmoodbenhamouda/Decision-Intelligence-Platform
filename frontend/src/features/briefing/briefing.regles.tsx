
import type { ReactNode } from "react";
import {
  FileSignature, Landmark, Percent, Truck, UserMinus, Wallet, Warehouse,
} from "lucide-react";
import type { Origine } from "@/features/taches/taches.types";
import type { Cible, ClientMultiSignaux, Constat } from "./briefing.types";

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

/** Clé stable d'une tâche issue d'une ligne de constat — même règle que la flotte
 * (agents/fleet/delegation.py::origine_cible) : une même ligne n'est jamais confiée deux fois. */
export function cleCible(titreConstat: string, nom: string): string {
  return `${titreConstat} — ${nom}`.slice(0, 255);
}

export function origineCible(a: Constat, c: Cible, estClient: boolean): Origine {
  return {
    titre: cleCible(a.titre, c.nom),
    titre_tache: c.tache.titre,
    categorie: a.categorie,
    libelle: DOMAINE[a.categorie]?.label,
    severite: a.severite,
    montant_dt: c.enjeu_dt ?? c.montant_dt,
    client_nom: estClient ? c.nom : undefined,
    client_code: estClient ? (c.code || undefined) : undefined,
    details: `${c.motif}. Contexte : ${a.titre}.`,
    execution: a.execution ? { poste: a.execution.poste, type: c.tache.type } : null,
  };
}

export function origineClient(c: ClientMultiSignaux): Origine {
  const categorie = c.categorie || c.domaines[0] || "Clients";
  return {
    titre: `Faire le point avec ${c.client}`,
    categorie,
    libelle: DOMAINE[categorie]?.label,
    execution: c.execution,
    severite: "haute",
    montant_dt: c.montant_cumule_dt,
    client_nom: c.client,
    details: `Ce compte apparaît dans plusieurs domaines : ${c.domaines
      .map(d => DOMAINE_AGENT[d] || d).join(", ")}.`,
  };
}
