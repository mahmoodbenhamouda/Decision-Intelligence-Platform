"use client";

/**
 * ClientSpace — « Mon espace » du portail client.
 *
 * Le client ne se contente plus de REGARDER ses données, il AGIT dessus, au
 * moment où il les regarde :
 *   · sur une facture en retard  → annoncer une date de paiement, ou contester ;
 *   · sur les produits proposés  → dire qu'il est intéressé ;
 *   · sur n'importe quel sujet   → écrire à la direction (formulaire libre).
 *
 * Chaque action crée côté entreprise une tâche à traiter, et le client suit
 * l'avancement dans « Mes demandes » : il voit que son geste a une suite, donc
 * il recommence. C'est la moitié client de la boucle d'action.
 */

import { useState } from "react";
import {
  CheckCircle2, Clock3, FileText, HandCoins, Inbox, MailPlus, Package,
  ReceiptText, RefreshCw, Send, ShieldAlert, ThumbsUp, XCircle,
} from "lucide-react";
import { BLEU, GRAVITE, INK, fMoney } from "@/shared/ui/VisuelKit";
import { dansNJours, dateCourte as fDate } from "@/shared/format";
import type { Invoice } from "./espaceClient.types";
import { useEspaceClient } from "./useEspaceClient";

const TYPE_LABEL: Record<string, string> = {
  echeancier: "Demande d'échéancier", reclamation: "Réclamation",
  devis: "Demande de devis", contact: "Prise de contact", autre: "Autre",
  promesse_paiement: "Paiement annoncé", devis_reponse: "Réponse à un devis",
  interet_produit: "Produit qui m'intéresse", reservation_stock: "Réservation",
};
/** Types proposés dans le formulaire libre (les autres naissent d'un bouton). */
const TYPES_LIBRES = ["echeancier", "reclamation", "devis", "contact", "autre"];

const STATUS_LABEL: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  nouvelle: { label: "Reçue", color: "#2F5BEA", icon: <Inbox size={12} /> },
  en_cours: { label: "En cours de traitement", color: "#E0A10F", icon: <Clock3 size={12} /> },
  traitee: { label: "Traitée", color: "#0CA30C", icon: <CheckCircle2 size={12} /> },
  rejetee: { label: "Refusée", color: "#D03B3B", icon: <XCircle size={12} /> },
};
const STATUT_FACTURE: Record<string, { label: string; color: string }> = {
  a_l_heure: { label: "À l'heure", color: "#0CA30C" },
  retard: { label: "En retard", color: "#E0A10F" },
  critique: { label: "Très en retard", color: "#D03B3B" },
  "n/d": { label: "N/D", color: "#93A0BC" },
};

export default function ClientSpace() {
  const {
    inv, error, demandes, produits, loading, load,
    sending, sent, setSent, type, setType, sujet, setSujet, message, setMessage,
    invoiceRef, setInvoiceRef, action, setAction, envoyerAction, submit,
  } = useEspaceClient();

  const enRetard = (inv?.invoices || []).filter(f => f.statut !== "a_l_heure" && f.statut !== "n/d");

  return (
    <div style={{ gridColumn: "span 12", display: "grid", gridTemplateColumns: "repeat(12, 1fr)", gap: 14 }}>

      {/* ── Mon compte ───────────────────────────────────────────────────── */}
      <div className="chart-card" style={{ gridColumn: "span 12", display: "flex", gap: 22, alignItems: "center", flexWrap: "wrap" }}>
        <span className="card-label" style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <ReceiptText size={17} /> Mon compte
        </span>
        <span><b>{inv?.total_factures ?? "—"}</b> factures</span>
        <span>Total : <b>{fMoney(inv?.total_ttc)}</b></span>
        <span style={{ color: (inv?.encours_retard_ttc || 0) > 0 ? GRAVITE.critique.couleur : GRAVITE.faible.couleur }}>
          <ShieldAlert size={13} style={{ verticalAlign: "-2px" }} /> Reste à régler au-delà de 60 jours : <b>{fMoney(inv?.encours_retard_ttc)}</b>
        </span>
        <button className="icon-button" onClick={load} title="Rafraîchir" style={{ marginLeft: "auto" }}>
          <RefreshCw size={15} className={loading ? "spin-icon" : ""} />
        </button>
      </div>

      {sent && (
        <div className={sent.startsWith("Erreur") ? "vk-erreur" : "vk-succes"} style={{ gridColumn: "span 12" }}>
          {sent}
        </div>
      )}

      {/* ── À régler : la seule zone où le client peut agir en un clic ───── */}
      {enRetard.length > 0 && (
        <div className="chart-card" style={{ gridColumn: "span 12" }}>
          <div className="card-header">
            <span className="card-label"><HandCoins size={16} style={{ verticalAlign: "-3px" }} /> Factures à régler</span>
          </div>
          <p className="muted-note" style={{ marginTop: 0 }}>
            Annoncez une date de paiement : elle est transmise immédiatement et évite une relance.
          </p>
          <div style={{ display: "grid", gap: 10, gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))" }}>
            {enRetard.slice(0, 6).map((f, i) => {
              const st = STATUT_FACTURE[f.statut] || STATUT_FACTURE["n/d"];
              return (
                <div key={i} className="vk-carte-action" style={{ borderLeft: `4px solid ${st.color}` }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
                    <b style={{ color: INK.primary }}>{fMoney(f.montant_ttc)}</b>
                    <span style={{ color: st.color, fontWeight: 700, fontSize: "0.72rem" }}>{st.label}</span>
                  </div>
                  <div style={{ fontSize: "0.74rem", color: INK.secondary }}>
                    Facture du {fDate(f.date)}{f.echeance ? ` · échéance ${fDate(f.echeance)}` : ""}
                  </div>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    <button className="vk-bouton-mini" onClick={() => { setSent(null); setAction({ facture: f, mode: "promesse" }); }}>
                      J&apos;annonce une date
                    </button>
                    <button className="vk-bouton-fantome-mini" onClick={() => { setSent(null); setAction({ facture: f, mode: "reclamation" }); }}>
                      Je conteste
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Produits proposés ────────────────────────────────────────────── */}
      {produits.length > 0 && (
        <div className="chart-card" style={{ gridColumn: "span 7" }}>
          <div className="card-header">
            <span className="card-label"><Package size={16} style={{ verticalAlign: "-3px" }} /> Cela pourrait vous intéresser</span>
          </div>
          <p className="muted-note" style={{ marginTop: 0 }}>
            Produits utilisés par des établissements comme le vôtre. Un clic, et un commercial vous prépare une proposition.
          </p>
          <div style={{ display: "grid", gap: 9, gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))" }}>
            {produits.map(p => (
              <div key={p.reference} className="vk-carte-action">
                <div style={{ fontWeight: 700, color: INK.primary, fontSize: "0.85rem" }}>{p.designation}</div>
                {p.famille && <span className="vk-chip">{p.famille}</span>}
                {p.deja_signale ? (
                  <span style={{ fontSize: "0.74rem", fontWeight: 700, color: GRAVITE.faible.couleur }}>
                    Demande envoyée ✓
                  </span>
                ) : (
                  <button className="vk-bouton-mini" style={{ alignSelf: "flex-start" }} disabled={sending}
                    onClick={() => envoyerAction(
                      { type: "interet_produit", reference: p.reference, libelle: p.designation },
                      `Votre intérêt pour « ${p.designation} » est transmis : un commercial vous recontacte.`)}>
                    <ThumbsUp size={12} /> Ça m&apos;intéresse
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Formulaire libre ─────────────────────────────────────────────── */}
      <div className="chart-card" style={{ gridColumn: produits.length ? "span 5" : "span 5" }}>
        <div className="card-header">
          <span className="card-label"><MailPlus size={16} style={{ verticalAlign: "-3px" }} /> Écrire à votre interlocuteur</span>
        </div>
        <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 9 }}>
          <select className="mini" value={type} onChange={e => setType(e.target.value)}>
            {TYPES_LIBRES.map(k => <option key={k} value={k}>{TYPE_LABEL[k]}</option>)}
          </select>
          <input className="mini" placeholder="Sujet (ex. Échéancier facture de mars)"
            value={sujet} onChange={e => setSujet(e.target.value)} maxLength={200} required />
          <input className="mini" placeholder="Référence facture (facultatif)"
            value={invoiceRef} onChange={e => setInvoiceRef(e.target.value)} maxLength={64} />
          <textarea className="mini" placeholder="Votre message…" rows={4}
            value={message} onChange={e => setMessage(e.target.value)} maxLength={2000} required
            style={{ resize: "vertical", fontFamily: "inherit", padding: 8 }} />
          <button className="login-btn" type="submit" disabled={sending} style={{ padding: 10 }}>
            <Send size={14} /> {sending ? "Envoi…" : "Envoyer"}
          </button>
        </form>
      </div>

      {/* ── Factures ─────────────────────────────────────────────────────── */}
      <div className="chart-card" style={{ gridColumn: "span 12" }}>
        <div className="card-header">
          <span className="card-label"><FileText size={16} style={{ verticalAlign: "-3px" }} /> Mes dernières factures</span>
        </div>
        {error && <p className="muted-note">{error}</p>}
        <div className="data-table" style={{ maxHeight: 360, overflowY: "auto" }}>
          <div className="dt-head" style={{ display: "grid", gridTemplateColumns: "90px 90px 1fr 130px" }}>
            <span>Date</span><span>Échéance</span><span>Montant TTC</span><span>Statut</span>
          </div>
          {(inv?.invoices || []).map((f, i) => {
            const st = STATUT_FACTURE[f.statut] || STATUT_FACTURE["n/d"];
            return (
              <div key={i} className="dt-row" style={{ display: "grid", gridTemplateColumns: "90px 90px 1fr 130px" }}>
                <span>{fDate(f.date)}</span>
                <span>{fDate(f.echeance)}</span>
                <span><b>{fMoney(f.montant_ttc)}</b>{f.mode_reglement ? <em style={{ color: "var(--text-muted)", fontStyle: "normal", fontSize: "0.72rem" }}> · {f.mode_reglement}</em> : null}</span>
                <span style={{ color: st.color, fontWeight: 700, fontSize: "0.76rem" }}>{st.label}</span>
              </div>
            );
          })}
          {!loading && !(inv?.invoices || []).length && !error && (
            <p className="muted-note">Aucune facture sur votre compte.</p>
          )}
        </div>
      </div>

      {/* ── Suivi ────────────────────────────────────────────────────────── */}
      <div className="chart-card" style={{ gridColumn: "span 12" }}>
        <div className="card-header">
          <span className="card-label"><Inbox size={16} style={{ verticalAlign: "-3px" }} /> Mes demandes et leur suivi</span>
        </div>
        {!demandes.length && <p className="muted-note">Aucune demande pour l&apos;instant.</p>}
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {demandes.map(d => {
            const st = STATUS_LABEL[d.status] || STATUS_LABEL.nouvelle;
            return (
              <div key={d.id} style={{ border: `1px solid ${INK.border}`, borderLeft: `4px solid ${st.color}`, borderRadius: 10, padding: "10px 14px" }}>
                <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                  <b>{d.sujet}</b>
                  <span style={{ fontSize: "0.72rem", color: INK.muted }}>
                    {TYPE_LABEL[d.type] || d.type}{d.invoice_ref ? ` · facture ${d.invoice_ref}` : ""} · {fDate(d.created_at)}
                  </span>
                  <span style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 5, color: st.color, fontWeight: 700, fontSize: "0.76rem" }}>
                    {st.icon} {st.label}
                  </span>
                </div>
                <p style={{ margin: "6px 0 0", fontSize: "0.82rem", color: INK.primary }}>{d.message}</p>
                {d.reponse && (
                  <p style={{ margin: "8px 0 0", fontSize: "0.82rem", background: "rgba(12,163,12,0.07)", borderRadius: 8, padding: "8px 10px" }}>
                    <b>Réponse :</b> {d.reponse}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {action && (
        <FenetreAction
          facture={action.facture} mode={action.mode} sending={sending}
          onClose={() => setAction(null)}
          onEnvoyer={async (corps, confirmation) => {
            const ok = await envoyerAction(corps, confirmation);
            if (ok) setAction(null);
          }} />
      )}
    </div>
  );
}

/** Annoncer un paiement ou contester une facture, sans quitter l'écran. */
function FenetreAction({ facture, mode, sending, onClose, onEnvoyer }: {
  facture: Invoice; mode: "promesse" | "reclamation"; sending: boolean;
  onClose: () => void;
  onEnvoyer: (corps: Record<string, unknown>, confirmation: string) => void | Promise<void>;
}) {
  const [date, setDate] = useState(dansNJours(7));
  const [montant, setMontant] = useState(String(Math.round(facture.montant_ttc)));
  const [texte, setTexte] = useState("");
  const promesse = mode === "promesse";

  return (
    <div className="vk-modal-fond" onClick={onClose}>
      <div className="vk-modal" onClick={e => e.stopPropagation()}>
        <div className="vk-modal-tete">
          <span style={{ display: "inline-flex", alignItems: "center", gap: 8, fontWeight: 800, color: INK.primary }}>
            {promesse ? <HandCoins size={17} color={BLEU[3]} /> : <ShieldAlert size={17} color={GRAVITE.haute.couleur} />}
            {promesse ? "Annoncer un paiement" : "Contester cette facture"}
          </span>
          <button className="icon-button" onClick={onClose} aria-label="Fermer">×</button>
        </div>
        <div className="vk-modal-corps">
          <div style={{ fontSize: "0.82rem", color: INK.secondary }}>
            Facture du {fDate(facture.date)} — <b style={{ color: INK.primary }}>{fMoney(facture.montant_ttc)}</b>
          </div>
          {promesse ? (
            <>
              <label className="vk-champ">
                <span>Je paierai le</span>
                <input type="date" value={date} onChange={e => setDate(e.target.value)} />
              </label>
              <label className="vk-champ">
                <span>Montant que je règle (DT)</span>
                <input type="number" min={0} value={montant} onChange={e => setMontant(e.target.value)} />
                <small style={{ color: INK.muted }}>
                  Vous pouvez annoncer un règlement partiel : indiquez alors le montant prévu.
                </small>
              </label>
            </>
          ) : null}
          <label className="vk-champ">
            <span>{promesse ? "Précision (facultatif)" : "Que contestez-vous ?"}</span>
            <textarea rows={3} maxLength={2000} value={texte} onChange={e => setTexte(e.target.value)}
              placeholder={promesse ? "Virement déjà lancé, référence…" : "Quantité, prix, produit non reçu…"} />
          </label>
        </div>
        <div className="vk-modal-pied">
          <button className="vk-bouton-fantome" onClick={onClose}>Annuler</button>
          <button className="vk-bouton" disabled={sending || (!promesse && texte.trim().length < 3)}
            onClick={() => onEnvoyer(
              promesse
                ? { type: "promesse_paiement", reference: facture.date, montant_dt: Number(montant) || 0, date_prevue: date, message: texte.trim() || null }
                : { type: "reclamation", reference: facture.date, montant_dt: facture.montant_ttc, message: texte.trim() },
              promesse
                ? "Votre date de paiement est transmise : aucune relance ne partira d'ici là."
                : "Votre contestation est transmise : elle est traitée en priorité.")}>
            <Send size={14} /> {sending ? "Envoi…" : "Envoyer"}
          </button>
        </div>
      </div>
    </div>
  );
}
