
import {
  Bot, Boxes, ClipboardList, Coins, FileSignature, LayoutDashboard, Percent,
  ScanLine, ShieldAlert, Target, TrendingUp, UserMinus, Users, Warehouse,
} from "lucide-react";
import type { GroupeDef, OngletDef } from "@/shared/ui/BarreLaterale";

//: L'onglet Marge porte ses propres tuiles, qui détaillent le calcul au lieu
//: de le résumer : le bandeau générique ferait doublon.
export const SANS_KPI = ["taches", "copilot", "ocr", "admin", "marge", "impact"];

//: Vues dont les chiffres ne portent sur aucune période : le sélecteur n'y a
//: rien à régler. Marge n'en fait PAS partie — sa décomposition suit la
//: période choisie, comme le total qu'elle explique.
//: `impact` s'y ajoute : un enjeu financier filtré sur trois clients ne veut
//: rien dire. Le total porte sur l'entreprise, ou il ne porte sur rien.
export const SANS_PERIODE = ["taches", "copilot", "ocr", "admin", "priorites",
                             "impact"];

/**
 * La navigation suit le CYCLE DE L'ARGENT, pas l'organigramme.
 *
 * Quatorze onglets à plat obligeaient à connaître l'application pour s'y
 * retrouver. Regroupés par étape du cycle — on vend, on marge, on encaisse, on
 * réapprovisionne — ils racontent l'entreprise plutôt que le logiciel, et le
 * lien entre une marge qui baisse et un fournisseur unique cesse d'être une
 * découverte.
 *
 * L'ordre des groupes est celui du chemin que suit un dinar : il entre par une
 * vente, laisse une marge, se transforme en encaissement, et repart en achats.
 */
export const GROUPES: GroupeDef[] = [
  {
    titre: "Piloter",
    aide: "Où j'en suis, et ce qui demande une décision aujourd'hui",
    onglets: [
      { id: "synthese", label: "Synthèse", icon: <LayoutDashboard size={16} /> },
      { id: "impact", label: "Enjeu financier", icon: <Coins size={16} /> },
      { id: "priorites", label: "Priorités", icon: <Target size={16} /> },
      { id: "taches", label: "Suivi des actions", icon: <ClipboardList size={16} /> },
    ],
  },
  {
    titre: "Vendre",
    aide: "Qui achète, qui hésite, qui s'en va",
    onglets: [
      { id: "clients", label: "Clients", icon: <Users size={16} /> },
      { id: "commercial", label: "Devis", icon: <FileSignature size={16} /> },
      { id: "retention", label: "Rétention", icon: <UserMinus size={16} /> },
    ],
  },
  {
    titre: "Gagner",
    aide: "Ce que les ventes laissent réellement",
    onglets: [
      { id: "performance", label: "Performance", icon: <TrendingUp size={16} /> },
      { id: "marge", label: "Marge", icon: <Percent size={16} /> },
    ],
  },
  {
    titre: "Encaisser",
    aide: "Quand l'argent rentre, et ce qui tarde",
    onglets: [
      { id: "risque", label: "Risque crédit", icon: <ShieldAlert size={16} /> },
    ],
  },
  {
    titre: "Approvisionner",
    aide: "Ce qu'il faut racheter pour continuer à vendre",
    onglets: [
      { id: "stock", label: "Stock & achats", icon: <Warehouse size={16} /> },
      { id: "produits", label: "Catalogue", icon: <Boxes size={16} /> },
    ],
  },
  {
    titre: "Outils",
    aide: "",
    onglets: [
      { id: "copilot", label: "Copilote IA", icon: <Bot size={16} /> },
      { id: "ocr", label: "Documents", icon: <ScanLine size={16} /> },
      { id: "admin", label: "Administration", icon: <Users size={16} /> },
    ],
  },
];

//: Liste à plat, pour tout ce qui raisonne par identifiant de vue.
export const VIEWS: OngletDef[] = GROUPES.flatMap(g => g.onglets);
