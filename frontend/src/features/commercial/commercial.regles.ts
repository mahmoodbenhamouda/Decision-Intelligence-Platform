/**
 * Model — les deux alertes que l'écran commercial sait confier.
 */
import type { Origine } from "@/features/taches/taches.types";
import { fMoney } from "@/shared/ui/VisuelKit";
import type { DevisLigne, RecoClient } from "./commercial.types";

const fDate = (d?: string) => (d ? new Date(d).toLocaleDateString("fr-FR") : "—");

/* Les deux alertes que cet écran sait confier. Chacune est fabriquée à un seul
   endroit : son `titre` est aussi la clé qui dit si elle est déjà confiée. */
export const origineDevis = (x: DevisLigne): Origine => ({
  titre: `Relancer le devis ${x.piece_no} — ${x.nom || x.client}`,
  categorie: "Commercial", severite: "haute",
  montant_dt: x.montant_ht_dt,
  client_code: x.client, client_nom: x.nom || x.client,
  details: `Devis de ${fMoney(x.montant_ht_dt)} émis le ${fDate(x.date)}.`,
});

export const origineReco = (c: RecoClient): Origine => ({
  titre: `Proposer de nouveaux produits à ${c.nom}`,
  categorie: "Commercial", severite: "moyenne",
  montant_dt: c.potentiel_top3_dt,
  client_code: c.client, client_nom: c.nom,
  details: `Produits à proposer : ${c.produits.map(p => p.designation).join(", ")}.`,
});
