
import type { AvatarMood } from "@/shared/avatar/FinBotAvatar";
import type { Msg, RadarCard } from "./copilote.types";

export const MESSAGE_ACCUEIL: Msg = {
  role: "assistant",
  text:
    "Bonjour, Je suis **FinBot**, votre copilote financier expert.\n\n" +
    "Je suis spécialisé dans :\n" +
    "- 📋 **Recouvrement** — priorisation des relances et aging des créances\n" +
    "- 💰 **Trésorerie** — DSO, DPO, cycle de conversion cash\n" +
    "- 📊 **Rentabilité** — marge brute réelle par client, analyse des coûts\n" +
    "- 📉 **Risque client** — concentration, clients qui décrochent\n" +
    "- 📦 **Stock** — ruptures, surstock, péremption\n\n",
  via: "regles",
};

export const GLOSSARY_TOOLTIPS: Record<string, string> = {
  "DSO": "Days Sales Outstanding — délai moyen d'encaissement client (jours)",
  "DPO": "Days Payable Outstanding — délai moyen de paiement fournisseur",
  "BFR": "Besoin en Fonds de Roulement = Créances + Stocks - Dettes fournisseurs",
  "FRNG": "Fonds de Roulement Net Global — excédent des ressources stables",
  "VaR": "Value at Risk — perte maximale estimée sur le portefeuille de change",
  "EBITDA": "Résultat avant intérêts, impôts, dépréciations et amortissements",
  "HHI": "Indice de concentration du portefeuille clients (>0.25 = risque élevé)",
  "FOREX": "Marché des changes — impact sur le coût des achats importés",
  "TND": "Dinar Tunisien — monnaie nationale (DT)",
  "Factoring": "Cession de créances à un factor pour encaissement immédiat",
  "TUNEPS": "Portail officiel des marchés publics tunisiens",
  "Pareto": "Loi 80/20 — 20% des clients génèrent 80% du CA",
};

export const GLOBAL_SUGGESTIONS = [
  "Quelles sont mes priorités de recouvrement ?",
  "Quel est mon échéancier du mois prochain ?",
  "Quels clients décrochent ?",
  "Où en est ma concentration client ?",
  "C'est quoi le DSO et comment l'améliorer ?",
  "Analyse ma marge commerciale",
];

export const CLIENT_SUGGESTIONS = (clientName: string) => [
  `Quel est le risque crédit de ${clientName} ?`,
  `Quelle est l'exposition de ${clientName} en retard ?`,
  `Historique de paiement de ${clientName}`,
  `Quelle action prendre sur ${clientName} ?`,
];

const ALERT_WORDS = ["🔴", "très urgent", "tres urgent", "risque élevé", "risque eleve", "alerte", "danger", "impayé", "impaye", "grave"];
const CONCERN_WORDS = ["retard critique", "attention", "vigilance", "détérior", "deterior", "perte", "litige", "décrochage", "decrochage"];
const HAPPY_WORDS = ["opportunité", "opportunite", "gain", "amélior", "amelior", "excellent", "positif", "hausse", "croissance", "félicit", "felicit", "bonne nouvelle", "économie", "economie", "solide", "bonne santé", "bonne sante"];

export function detectMood(text: string, radar: RadarCard[]): AvatarMood {
  const t = text.toLowerCase();
  const radarSev = radar.map(r => (r.severite || "").toLowerCase());
  const hits = (words: string[]) => words.filter(w => t.includes(w)).length;

  if (radarSev.some(s => s === "critique") && hits(ALERT_WORDS) >= 1) return "alert";
  if (hits(ALERT_WORDS) >= 2) return "alert";

  if (hits(CONCERN_WORDS) + hits(ALERT_WORDS) >= 2) return "concerned";
  if (hits(HAPPY_WORDS) >= 1) return "happy";
  return "neutral";
}
