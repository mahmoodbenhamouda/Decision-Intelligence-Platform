"use client";

import { useCallback, useState } from "react";
import { AlertTriangle, PackageCheck, Send, Truck, X } from "lucide-react";
import { api } from "@/core/api/client";
import { useRequete } from "@/core/hooks/useRequete";
import { Carte, INK, Vide, fMoney, tronquer } from "@/shared/ui/VisuelKit";
import type { Commande } from "./commandes.types";

const fDate = (d?: string | null) =>
  d ? new Date(d).toLocaleDateString("fr-FR") : "—";

/**
 * Les commandes à exécuter, sur l'écran de l'employé.
 *
 * Le directeur valide, il ne saisit pas. Une fois sa décision prise, passer la
 * commande au fournisseur et saisir la réception sont des gestes d'exécution :
 * ils appartiennent à l'équipe logistique, et c'est ici qu'elle les fait.
 *
 * La date de réception saisie ici est celle qui, rapprochée de la date de
 * commande, donne le délai de livraison réel.
 */
export default function MesCommandes() {
  const [version, setVersion] = useState(0);
  const [erreur, setErreur] = useState<string | null>(null);
  const [occupe, setOccupe] = useState<number | null>(null);

  const r = useRequete<Commande[]>(async () => {
    try {
      const rep = await api("/api/commandes?statut=ouvertes&limit=100");
      return await rep.json();
    } catch {
      return [];
    }
  }, `commandes#${version}`);

  const agir = useCallback(async (c: Commande, chemin: string, corps: unknown) => {
    setErreur(null);
    setOccupe(c.id);
    try {
      const rep = await api(`/api/commandes/${c.id}/${chemin}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(corps),
      });
      if (!rep.ok) {
        const t = await rep.json().catch(() => ({}));
        throw new Error(t?.detail || "L'opération a échoué.");
      }
      setVersion(v => v + 1);
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "L'opération a échoué.");
    } finally {
      setOccupe(null);
    }
  }, []);

  // Seules les commandes déjà décidées concernent l'employé : une proposition
  // en attente de validation ne lui appartient pas.
  const aFaire = (r.donnees ?? []).filter(
    c => c.statut === "validee" || c.statut === "commandee");

  if (!aFaire.length) return null;

  return (
    <Carte span={12} titre="Commandes fournisseur à traiter" icone={<Truck size={15} />}
      sousTitre={`${aFaire.length} commande${aFaire.length > 1 ? "s" : ""} validée${aFaire.length > 1 ? "s" : ""} par la direction`}>
      {erreur && (
        <div style={{
          padding: "10px 12px", borderRadius: 10, marginBottom: 11,
          background: "rgba(208,59,59,0.07)", borderWidth: 1, borderStyle: "solid",
          borderColor: "rgba(208,59,59,0.25)", display: "flex", gap: 9,
          alignItems: "center", justifyContent: "space-between",
        }}>
          <span style={{ display: "flex", gap: 8, alignItems: "center", fontSize: "0.78rem", color: INK.primary }}>
            <AlertTriangle size={15} style={{ color: "#D03B3B" }} />{erreur}
          </span>
          <button className="vk-bouton-mini" onClick={() => setErreur(null)}>
            <X size={12} /> Fermer
          </button>
        </div>
      )}

      <div style={{ display: "grid", gap: 10 }}>
        {aFaire.map(c => {
          const aCommander = c.statut === "validee";
          const couleur = aCommander ? "#E0A10F" : "#8B5CF6";
          return (
            <div key={c.id} style={{
              borderStyle: "solid", borderWidth: "1px 1px 1px 4px",
              borderColor: `${INK.border} ${INK.border} ${INK.border} ${couleur}`,
              borderRadius: 11, padding: "12px 14px", display: "grid", gap: 7,
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
                <span style={{ fontWeight: 800, color: INK.primary, fontSize: "0.88rem" }}
                      title={c.designation || c.reference}>
                  {tronquer(c.designation || c.reference, 40)}
                </span>
                <span style={{ fontWeight: 800, color: INK.primary, fontSize: "0.86rem", whiteSpace: "nowrap" }}>
                  {c.qte_proposee} × · {fMoney(c.montant_estime_dt)}
                </span>
              </div>

              <div style={{ fontSize: "0.73rem", color: INK.secondary }}>
                {c.fournisseur_nom || "Fournisseur habituel"} · référence {c.reference}
                {c.commande_at && ` · commandée le ${fDate(c.commande_at)}`}
              </div>

              {c.motif && (
                <div style={{ fontSize: "0.71rem", color: INK.muted, lineHeight: 1.5 }}>
                  {c.motif}
                </div>
              )}

              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <span style={{
                  background: `${couleur}18`, color: couleur, borderRadius: 6,
                  padding: "3px 9px", fontSize: "0.7rem", fontWeight: 700,
                }}>{c.prochain_geste}</span>

                {aCommander ? (
                  <button className="vk-bouton-mini" disabled={occupe === c.id}
                    onClick={() => void agir(c, "commander", { commentaire: "" })}>
                    <Send size={12} /> {occupe === c.id ? "…" : "J'ai passé la commande"}
                  </button>
                ) : (
                  <button className="vk-bouton-mini" disabled={occupe === c.id}
                    onClick={() => void agir(c, "reception", { qte_recue: null, commentaire: "" })}>
                    <PackageCheck size={12} /> {occupe === c.id ? "…" : "J'ai reçu la marchandise"}
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {!aFaire.length && <Vide texte="Aucune commande à traiter." />}
    </Carte>
  );
}
