/**
 * Model — règles métier des tâches : types d'action, suggestions à partir du
 * domaine de l'alerte, délais par gravité, étapes et issues possibles.
 */
import {
  AlarmClock, CheckCircle2, ClipboardList, Inbox, Repeat,
} from "lucide-react";

export const TYPES: { id: string; label: string }[] = [
  { id: "appel", label: "Appeler le client" },
  { id: "relance_devis", label: "Relancer le devis" },
  { id: "echeancier", label: "Proposer un échéancier" },
  { id: "visite", label: "Passer voir le client" },
  { id: "commande", label: "Commander / réserver du stock" },
  { id: "reclamation", label: "Traiter une réclamation" },
  { id: "autre", label: "Autre action" },
];

/** Action la plus probable selon le domaine de l'alerte. */
export function typeSuggere(categorie?: string): string {
  const c = (categorie || "").toLowerCase();
  if (c.includes("recouvrement") || c.includes("trésorerie") || c.includes("tresorerie")) return "echeancier";
  if (c.includes("commercial") || c.includes("vente")) return "relance_devis";
  if (c.includes("stock") || c.includes("approvisionnement") || c.includes("fournisseur")) return "commande";
  if (c.includes("risque") || c.includes("rétention") || c.includes("retention")) return "appel";
  return "appel";
}

/** Poste le plus proche du domaine — simple proposition de tri, jamais un filtre. */
export function posteSuggere(categorie?: string): string | null {
  const c = (categorie || "").toLowerCase();
  if (c.includes("recouvrement") || c.includes("trésorerie") || c.includes("tresorerie")) return "recouvrement";
  if (c.includes("stock") || c.includes("approvisionnement") || c.includes("fournisseur")) return "logistique";
  if (c.includes("commercial") || c.includes("vente") || c.includes("rétention")) return "commercial";
  return null;
}

/** Échéance proposée selon la gravité de l'alerte (en jours). */
export const DELAI: Record<string, number> = { critique: 2, haute: 5, moyenne: 10, faible: 20 };

export const COLONNES = [
  { id: "a_affecter", label: "À affecter", icone: <Inbox size={14} /> },
  { id: "a_faire", label: "À faire", icone: <ClipboardList size={14} /> },
  { id: "en_cours", label: "En cours", icone: <Repeat size={14} /> },
  { id: "bloquee", label: "Bloquée", icone: <AlarmClock size={14} /> },
  { id: "terminee", label: "Terminée", icone: <CheckCircle2 size={14} /> },
];

export const RESULTATS = [
  { id: "paye", label: "Payé", gain: true },
  { id: "promesse", label: "Promesse de paiement", gain: false },
  { id: "devis_signe", label: "Devis signé", gain: true },
  { id: "devis_refuse", label: "Devis refusé", gain: false },
  { id: "commande_passee", label: "Commande passée", gain: true },
  { id: "client_retenu", label: "Client retenu", gain: true },
  { id: "client_perdu", label: "Client perdu", gain: false },
  { id: "sans_reponse", label: "Sans réponse", gain: false },
  { id: "autre", label: "Autre", gain: false },
];

export function moisCourt(m: string) {
  const [a, mo] = m.split("-");
  const noms = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août",
                "sept.", "oct.", "nov.", "déc."];
  return `${noms[Number(mo) - 1] || m} ${a.slice(2)}`;
}
