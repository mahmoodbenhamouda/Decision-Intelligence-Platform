import { GRAVITE } from "@/shared/ui/VisuelKit";

export const URGENCE: Record<string, { label: string; couleur: string }> = {
  rupture_probable: { label: "Stock épuisé", couleur: GRAVITE.critique.couleur },
  critique: { label: "Moins d'un mois de stock", couleur: GRAVITE.haute.couleur },
  a_commander: { label: "À commander bientôt", couleur: GRAVITE.moyenne.couleur },
};
