"use client";

/**
 * ConfierTache — la fenêtre qui transforme une alerte en travail confié.
 *
 * Elle s'ouvre depuis n'importe quel écran (Priorités, Devis & marge, Stock) et
 * arrive PRÉ-REMPLIE : l'intitulé de l'alerte, le domaine, le client et le
 * montant en jeu sont repris tels quels. Le directeur n'a donc qu'à choisir la
 * personne et, s'il le souhaite, la date — c'est ce qui fait la différence
 * entre un tableau de bord qu'on regarde et un tableau de bord qui fait agir.
 *
 * Le type d'action est proposé automatiquement à partir du domaine de l'alerte
 * (un impayé appelle une relance, une rupture appelle une commande), mais reste
 * modifiable : la machine suggère, l'humain décide.
 */

import { CheckCircle2, Send, UserPlus, X } from "lucide-react";
import { BLEU, GRAVITE, INK, fMoney } from "@/shared/ui/VisuelKit";
import { TYPES } from "./taches.regles";
import type { Confiee, Origine } from "./taches.types";
import { useConfierTache } from "./useConfierTache";

/** Ce qui remplace le bouton une fois l'action confiée. */
export function BadgeConfiee({ info, compact = false }: { info: Confiee; compact?: boolean }) {
  const qui = info.assigne_nom || "un responsable à désigner";
  const quand = info.echeance
    ? new Date(info.echeance).toLocaleDateString("fr-FR") : null;
  return (
    <span className="vk-confiee" title={quand ? `À traiter avant le ${quand}` : undefined}>
      <CheckCircle2 size={12} />
      {compact ? "Confiée" : `Confiée à ${qui}`}
    </span>
  );
}

export default function ConfierTache({ origine, onClose, onCree }: {
  origine: Origine; onClose: () => void; onCree?: () => void;
}) {
  const {
    classes, assigne, setAssigne, type, setType, titre, setTitre, details, setDetails,
    echeance, setEcheance, montant, setMontant, envoi, erreur, envoyer,
  } = useConfierTache(origine, onClose, onCree);

  const g = GRAVITE[origine.severite || "moyenne"] || GRAVITE.moyenne;

  return (
    <div className="vk-modal-fond" onClick={onClose}>
      <div className="vk-modal" onClick={e => e.stopPropagation()}>
        <div className="vk-modal-tete">
          <span style={{ display: "inline-flex", alignItems: "center", gap: 8, fontWeight: 800, color: INK.primary }}>
            <UserPlus size={17} color={BLEU[3]} /> Confier cette action
          </span>
          <button className="icon-button" onClick={onClose} aria-label="Fermer"><X size={16} /></button>
        </div>

        <div className="vk-modal-corps">
          <div style={{
            borderLeft: `4px solid ${g.couleur}`, background: "rgba(47,91,234,0.045)",
            borderRadius: 10, padding: "10px 12px",
          }}>
            <div style={{ fontSize: "0.72rem", fontWeight: 700, color: INK.secondary }}>
              {origine.categorie || "Alerte"}{origine.client_nom ? ` · ${origine.client_nom}` : ""}
            </div>
            <div style={{ fontSize: "0.88rem", fontWeight: 700, color: INK.primary, marginTop: 2 }}>
              {origine.titre}
            </div>
            {origine.montant_dt ? (
              <div style={{ fontSize: "0.76rem", color: INK.secondary, marginTop: 2 }}>
                {fMoney(origine.montant_dt)} en jeu
              </div>
            ) : null}
          </div>

          <label className="vk-champ">
            <span>Qui s&apos;en occupe</span>
            <select value={assigne} onChange={e => setAssigne(e.target.value === "" ? "" : Number(e.target.value))}>
              <option value="">— à affecter plus tard —</option>
              {classes.map(e => (
                <option key={e.id} value={e.id}>
                  {e.nom}{e.poste ? ` · ${e.poste}` : ""} — {e.taches_ouvertes} tâche(s) en cours
                </option>
              ))}
            </select>
            {!classes.length && (
              <small style={{ color: INK.muted }}>
                Aucun employé enregistré : créez des comptes dans Administration.
              </small>
            )}
          </label>

          <div className="vk-champs-2">
            <label className="vk-champ">
              <span>Quoi faire</span>
              <select value={type} onChange={e => setType(e.target.value)}>
                {TYPES.map(t => <option key={t.id} value={t.id}>{t.label}</option>)}
              </select>
            </label>
            <label className="vk-champ">
              <span>Pour quand</span>
              <input type="date" value={echeance} onChange={e => setEcheance(e.target.value)} />
            </label>
          </div>

          <label className="vk-champ">
            <span>Intitulé de la tâche</span>
            <input value={titre} maxLength={200} onChange={e => setTitre(e.target.value)} />
          </label>

          <div className="vk-champs-2">
            <label className="vk-champ">
              <span>Montant en jeu (DT)</span>
              <input type="number" min={0} value={montant} onChange={e => setMontant(e.target.value)} />
            </label>
            <div />
          </div>

          <label className="vk-champ">
            <span>Consignes (facultatif)</span>
            <textarea rows={3} maxLength={2000} value={details}
              placeholder="Ce qu'il faut dire, ce qu'on accepte de négocier…"
              onChange={e => setDetails(e.target.value)} />
          </label>

          {erreur && <div className="vk-erreur">{erreur}</div>}
        </div>

        <div className="vk-modal-pied">
          <button className="vk-bouton-fantome" onClick={onClose}>Annuler</button>
          <button className="vk-bouton" disabled={envoi || titre.trim().length < 3} onClick={envoyer}>
            <Send size={14} /> {envoi ? "Envoi…" : "Confier la tâche"}
          </button>
        </div>
      </div>
    </div>
  );
}
