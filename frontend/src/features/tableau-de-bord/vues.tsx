/**
 * Model — les onglets du tableau de bord et leur visibilité selon le rôle.
 */
import {
  Bot, Boxes, ClipboardList, FileSignature, FileText, LayoutDashboard, ScanLine,
  ShieldAlert, Target, TrendingUp, UserMinus, Users, Warehouse,
} from "lucide-react";
import type { OngletDef } from "@/shared/ui/BarreLaterale";

/** Vues où le bandeau financier n'apporte rien : elles ne parlent pas d'argent. */
export const SANS_KPI = ["taches", "copilot", "ocr", "admin", "espace"];

export const VIEWS: OngletDef[] = [
  { id: "synthese", label: "Synthèse", icon: <LayoutDashboard size={16} /> },
  { id: "priorites", label: "Priorités", icon: <Target size={16} /> },
  // Le prolongement des priorités : ce qui a été confié, à qui, et ce que ça a
  // donné. Réservé à l'équipe interne (directeur et employés).
  { id: "taches", label: "Suivi des actions", icon: <ClipboardList size={16} /> },
  { id: "performance", label: "Performance", icon: <TrendingUp size={16} /> },
  { id: "risque", label: "Risque crédit", icon: <ShieldAlert size={16} /> },
  { id: "clients", label: "Clients", icon: <Users size={16} /> },
  { id: "retention", label: "Rétention", icon: <UserMinus size={16} /> },
  // Cycle commercial et rentabilité : devis à relancer et marge qui s'érode. Deux
  // modèles appris, servis uniquement si le registre les autorise.
  { id: "commercial", label: "Devis & marge", icon: <FileSignature size={16} /> },
  { id: "produits", label: "Produits & achats", icon: <Boxes size={16} /> },
  { id: "stock", label: "Stock", icon: <Warehouse size={16} /> },            // directeur

  { id: "copilot", label: "Copilote IA", icon: <Bot size={16} /> },
  { id: "ocr", label: "Documents & OCR", icon: <ScanLine size={16} /> },     // tous rôles
  { id: "espace", label: "Mon espace", icon: <FileText size={16} /> },       // client
  { id: "admin", label: "Administration", icon: <Users size={16} /> },       // directeur
];

/** Onglets visibles selon le rôle : un client ne voit ni produits, ni
 *  administration, ni stock, ni devis, ni tâches ; l'équipe interne ne voit pas
 *  « Mon espace ». */
export function ongletsPourRole(estClient: boolean): OngletDef[] {
  return VIEWS.filter(v => estClient
    ? !["produits", "admin", "stock", "commercial", "taches"].includes(v.id)
    : v.id !== "espace");
}
