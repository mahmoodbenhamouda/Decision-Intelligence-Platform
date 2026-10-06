
import type { Origine } from "@/features/taches/taches.types";
import { fMoney } from "@/shared/ui/VisuelKit";
import type { CodeProtocole, DevisLigne, MargeLigne, RecoClient } from "./commercial.types";

const fDate = (d?: string) => (d ? new Date(d).toLocaleDateString("fr-FR") : "—");

/** Couleur et verbe d'action par protocole — mêmes codes que le backend. */
export const PROTOCOLE_STYLE: Record<CodeProtocole, { couleur: string; verbe: string }> = {
  appeler: { couleur: "#0CA30C", verbe: "Appeler" },
  appel_offres: { couleur: "#2F5BEA", verbe: "Suivre le dossier" },
  traiter_en_lot: { couleur: "#E0A10F", verbe: "Rappel groupé" },
  laisser: { couleur: "#93A0BC", verbe: "Sans action" },
};

/** Le titre de la tâche porte le protocole : « relancer » un appel d'offres
 *  n'a pas de sens, et l'employé qui reçoit la tâche doit savoir quoi faire. */
export const origineDevis = (x: DevisLigne): Origine => {
  const style = PROTOCOLE_STYLE[x.protocole] ?? PROTOCOLE_STYLE.appeler;
  return {
    titre: `${style.verbe} — devis ${x.piece_no}, ${x.nom || x.client}`,
    categorie: "Commercial",
    severite: x.protocole === "appeler" ? "haute" : "moyenne",
    montant_dt: x.montant_ht_dt,
    client_code: x.client, client_nom: x.nom || x.client,
    details: `Devis de ${fMoney(x.montant_ht_dt)} émis le ${fDate(x.date)}, `
      + `ouvert depuis ${x.age_j} jours. Chance de signature estimée à `
      + `${Math.round(x.probabilite * 100)} %, soit ${fMoney(x.esperance_dt)} `
      + `de ventes probables.`,
  };
};

export const origineMarge = (x: MargeLigne): Origine => ({
  titre: `Revoir la rentabilité de ${x.nom || x.client}`,
  categorie: "Commercial", severite: "moyenne",
  montant_dt: x.marge_en_jeu_dt,
  client_code: x.client, client_nom: x.nom || x.client,
  details: `Taux de marge à ${x.marge_actuelle_pct.toFixed(1)} % sur 3 mois `
    + `contre ${x.marge_12m_pct.toFixed(1)} % sur 12 mois`
    + (x.seuil_pct != null ? ` (seuil de surveillance : ${x.seuil_pct.toFixed(1)} %)` : "")
    + `. ${fMoney(x.marge_en_jeu_dt)} de marge en jeu`
    + (x.part_equipement_pct != null
      ? `. Part d'équipement dans les achats récents : ${x.part_equipement_pct.toFixed(0)} %.`
      : "."),
});

export const origineReco = (c: RecoClient): Origine => ({
  titre: `Proposer de nouveaux produits à ${c.nom}`,
  categorie: "Commercial", severite: "moyenne",
  montant_dt: c.potentiel_top3_dt,
  client_code: c.client, client_nom: c.nom,
  details: `Produits à proposer : ${c.produits.map(p => p.designation).join(", ")}.`,
});
