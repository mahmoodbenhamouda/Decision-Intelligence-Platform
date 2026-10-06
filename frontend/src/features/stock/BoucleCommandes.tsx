"use client";

import { useState } from "react";
import {
  AlertTriangle, Check, Clock, PackageCheck, RefreshCw, Sparkles, X,
} from "lucide-react";
import { Carte, INK, Vide, fMoney, tronquer } from "@/shared/ui/VisuelKit";
import type { Commande, Proposition, StatutCommande } from "./commandes.types";
import { useCommandes } from "./useCommandes";

const TEINTE: Record<StatutCommande, string> = {
  recommandee: "#2F5BEA",
  validee: "#E0A10F",
  commandee: "#8B5CF6",
  recue: "#0CA30C",
  refusee: INK.muted,
  annulee: INK.muted,
};

const fDate = (d?: string | null) =>
  d ? new Date(d).toLocaleDateString("fr-FR") : "—";

/**
 * La boucle de décision : proposer → valider → commander → réceptionner.
 *
 * Chaque geste crée une donnée que l'ERP n'a pas. La date de commande et la
 * date de réception n'existent dans aucun export : leur écart donne le délai de
 * livraison réel, qui n'était jusqu'ici pas calculable.
 */
export default function BoucleCommandes() {
  const {
    reco, commandes, bilan, chargement, erreur, setErreur, enCours, rafraichir,
    validerProposition, refuserProposition,
  } = useCommandes();

  const [refusEnCours, setRefusEnCours] = useState<string | null>(null);
  const [motifRefus, setMotifRefus] = useState("");

  const propositions = reco?.propositions ?? [];
  const ouvertes = commandes.filter(c => c.ouverte);
  const closes = commandes.filter(c => !c.ouverte).slice(0, 8);
  const delai = bilan?.delai_livraison;

  return (
    <>
      {erreur && (
        <div style={{
          gridColumn: "span 12", padding: "11px 13px", borderRadius: 10,
          background: "rgba(208,59,59,0.07)", borderWidth: 1, borderStyle: "solid",
          borderColor: "rgba(208,59,59,0.25)", display: "flex", gap: 9,
          alignItems: "center", justifyContent: "space-between",
        }}>
          <span style={{ display: "flex", gap: 9, alignItems: "center", fontSize: "0.78rem", color: INK.primary }}>
            <AlertTriangle size={15} style={{ color: "#D03B3B" }} />{erreur}
          </span>
          <button className="vk-bouton-mini" onClick={() => setErreur(null)}>
            <X size={12} /> Fermer
          </button>
        </div>
      )}

      {/* Ce que la boucle a produit — y compris le délai que l'ERP ne porte pas. */}
      {bilan && (
        <Carte span={12} titre="Ce que la boucle a produit" icone={<Sparkles size={15} />}
          sousTitre="Les étapes que l'ERP n'enregistre pas naissent ici, un réassort à la fois"
          droite={<button className="icon-button" onClick={rafraichir} title="Actualiser">
            <RefreshCw size={15} />
          </button>}>
          <div style={{
            display: "grid", gap: 11,
            gridTemplateColumns: "repeat(auto-fit, minmax(185px, 1fr))",
          }}>
            {bilan.par_statut.filter(s => s.n > 0).map(s => (
              <Bloc key={s.statut} titre={s.label} valeur={`${s.n}`}
                couleur={TEINTE[s.statut]} />
            ))}
            {bilan.n_total === 0 && (
              <Bloc titre="Aucune décision encore prise" valeur="—"
                detail="Validez une proposition ci-dessous pour amorcer la boucle" />
            )}
            {bilan.montant_engage_dt > 0 && (
              <Bloc titre="Montant engagé" valeur={fMoney(bilan.montant_engage_dt)}
                detail="validé ou commandé, pas encore reçu" couleur="#E0A10F" />
            )}
            <Bloc titre="Délai de livraison réel"
              valeur={delai?.mesurable ? `${delai.median_j} j` : "pas encore mesurable"}
              detail={delai?.mesurable
                ? `médiane sur ${delai.n_receptions} réception(s), de ${delai.min_j} à ${delai.max_j} j`
                : delai?.motif_si_absent ?? ""}
              couleur={delai?.mesurable ? "#0CA30C" : INK.muted} />
          </div>
          {delai && (
            <p className="muted-note" style={{ marginTop: 10, fontSize: "0.72rem", lineHeight: 1.55 }}>
              <b style={{ color: INK.primary }}>D&apos;où vient ce délai :</b> {delai.origine}
            </p>
          )}
        </Carte>
      )}

      {/* 1. Ce que l'analyse propose. */}
      <Carte span={7} titre="Réassorts proposés par l'analyse" icone={<Sparkles size={15} />}
        sousTitre={reco?.n_deja_traitees
          ? `${propositions.length} en attente de décision · ${reco.n_deja_traitees} déjà traité(s)`
          : `${propositions.length} en attente de votre décision`}>
        {chargement && !reco ? <Vide texte="Analyse en cours…" />
          : !propositions.length ? (
            <Vide texte={reco?.motif
              || "Aucun réassort à décider : toutes les propositions ont été traitées."} />
          ) : (
            <div style={{ display: "grid", gap: 10 }}>
              {propositions.map(p => (
                <LigneProposition key={p.reference} p={p}
                  occupe={enCours === p.reference}
                  enRefus={refusEnCours === p.reference}
                  motif={motifRefus}
                  onMotif={setMotifRefus}
                  onValider={() => void validerProposition(p)}
                  onDemanderRefus={() => { setRefusEnCours(p.reference); setMotifRefus(""); }}
                  onAnnulerRefus={() => setRefusEnCours(null)}
                  onConfirmerRefus={async () => {
                    if (await refuserProposition(p, motifRefus)) setRefusEnCours(null);
                  }} />
              ))}
            </div>
          )}
        {reco?.base_de_la_proposition && (
          <p className="muted-note" style={{ marginTop: 11, fontSize: "0.71rem", lineHeight: 1.55 }}>
            <b style={{ color: INK.primary }}>Base de la quantité proposée :</b>{" "}
            {reco.base_de_la_proposition}
          </p>
        )}
      </Carte>

      {/* 2. Ce que l'équipe exécute. Le directeur suit, il ne saisit pas :
             passer la commande et réceptionner appartiennent à la logistique,
             qui les fait depuis son propre écran. */}
      <Carte span={5} titre="Commandes confiées à l'équipe" icone={<Clock size={15} />}
        sousTitre={`${ouvertes.length} en cours d'exécution par la logistique`}>
        {!ouvertes.length ? <Vide texte="Aucune commande en cours." /> : (
          <div style={{ display: "grid", gap: 9 }}>
            {ouvertes.map(c => <LigneCommande key={c.id} c={c} />)}
          </div>
        )}
      </Carte>

      {closes.length > 0 && (
        <Carte span={12} titre="Décisions passées" icone={<PackageCheck size={15} />}
          sousTitre="Les réceptions alimentent le délai de livraison réel">
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.78rem" }}>
              <thead>
                <tr style={{ textAlign: "left", color: INK.muted, fontSize: "0.69rem" }}>
                  <th style={{ padding: "6px 8px" }}>Produit</th>
                  <th style={{ padding: "6px 8px" }}>Issue</th>
                  <th style={{ padding: "6px 8px" }}>Commandée</th>
                  <th style={{ padding: "6px 8px" }}>Reçue</th>
                  <th style={{ padding: "6px 8px", textAlign: "right" }}>Délai réel</th>
                  <th style={{ padding: "6px 8px" }}>Motif</th>
                </tr>
              </thead>
              <tbody>
                {closes.map(c => (
                  <tr key={c.id} style={{ borderTopWidth: 1, borderTopStyle: "solid", borderTopColor: INK.grid }}>
                    <td style={{ padding: "8px" }}>
                      <div style={{ fontWeight: 600, color: INK.primary }}>
                        {tronquer(c.designation || c.reference, 34)}
                      </div>
                      <div style={{ fontSize: "0.67rem", color: INK.muted }}>{c.reference}</div>
                    </td>
                    <td style={{ padding: "8px" }}>
                      <span style={{
                        background: `${TEINTE[c.statut]}18`, color: TEINTE[c.statut],
                        borderRadius: 6, padding: "3px 8px", fontSize: "0.69rem",
                        fontWeight: 700, whiteSpace: "nowrap",
                      }}>{c.statut_label}</span>
                    </td>
                    <td style={{ padding: "8px", color: INK.secondary }}>{fDate(c.commande_at)}</td>
                    <td style={{ padding: "8px", color: INK.secondary }}>{fDate(c.recue_at)}</td>
                    <td style={{
                      padding: "8px", textAlign: "right", fontWeight: 800,
                      color: c.delai_livraison_j == null ? INK.muted : "#0CA30C",
                    }}>
                      {c.delai_livraison_j == null ? "—" : `${c.delai_livraison_j} j`}
                    </td>
                    <td style={{ padding: "8px", color: INK.muted, fontSize: "0.72rem" }}>
                      {tronquer(c.motif_refus || c.commentaire || "", 40) || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Carte>
      )}
    </>
  );
}

function LigneProposition({
  p, occupe, enRefus, motif, onMotif, onValider, onDemanderRefus,
  onAnnulerRefus, onConfirmerRefus,
}: {
  p: Proposition; occupe: boolean; enRefus: boolean; motif: string;
  onMotif: (v: string) => void;
  onValider: () => void; onDemanderRefus: () => void;
  onAnnulerRefus: () => void; onConfirmerRefus: () => void;
}) {
  return (
    <div style={{
      borderStyle: "solid", borderWidth: "1px 1px 1px 4px",
      borderColor: `${INK.border} ${INK.border} ${INK.border} #2F5BEA`,
      borderRadius: 11, padding: "12px 14px", display: "grid", gap: 7,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
        <span style={{ fontWeight: 800, color: INK.primary, fontSize: "0.86rem" }}
              title={p.designation}>
          {tronquer(p.designation, 38)}
        </span>
        <span style={{ fontWeight: 800, color: INK.primary, fontSize: "0.86rem", whiteSpace: "nowrap" }}>
          {p.qte_proposee ?? "?"} × · {p.montant_estime_dt == null ? "—" : fMoney(p.montant_estime_dt)}
        </span>
      </div>
      <div style={{ fontSize: "0.73rem", color: INK.secondary, lineHeight: 1.5 }}>
        Racheté tous les {p.intervalle_median_j} jours d&apos;habitude, dernier achat
        il y a <b>{p.jours_depuis} jours</b> — soit <b style={{ color: "#D03B3B" }}>
        {p.retard_x}× le rythme</b>. Encore vendu jusqu&apos;au {p.derniere_vente}.
      </div>
      <div style={{ fontSize: "0.69rem", color: INK.muted }}>
        Fournisseur habituel : {p.fournisseur_nom || "non identifié"} · référence {p.reference}
      </div>

      {enRefus ? (
        <div style={{ display: "grid", gap: 7, marginTop: 2 }}>
          {/* `vk-champ` est l'enveloppe du projet, pas une classe d'input. */}
          <label className="vk-champ">
            Motif du refus
            <input value={motif} autoFocus
              placeholder="Pourquoi ce réassort ne se justifie pas"
              onChange={e => onMotif(e.target.value)} />
          </label>
          <div style={{ display: "flex", gap: 7 }}>
            <button className="vk-bouton-mini" disabled={!motif.trim() || occupe}
              onClick={onConfirmerRefus}>
              <X size={12} /> Confirmer le refus
            </button>
            <button className="vk-bouton-mini" onClick={onAnnulerRefus}>Annuler</button>
          </div>
          <span style={{ fontSize: "0.69rem", color: INK.muted }}>
            Le motif est conservé : c&apos;est lui qui apprend à l&apos;analyse ce
            qu&apos;elle a mal jugé.
          </span>
        </div>
      ) : (
        <div style={{ display: "flex", gap: 7, marginTop: 2 }}>
          <button className="vk-bouton-mini" disabled={occupe} onClick={onValider}>
            <Check size={12} /> {occupe ? "…" : "Valider"}
          </button>
          <button className="vk-bouton-mini" disabled={occupe} onClick={onDemanderRefus}>
            <X size={12} /> Refuser
          </button>
        </div>
      )}
    </div>
  );
}

/** Une commande en cours, en lecture seule : son exécution revient à l'équipe. */
function LigneCommande({ c }: { c: Commande }) {
  const ATTENTE: Partial<Record<StatutCommande, string>> = {
    validee: "Chez la logistique, à passer au fournisseur",
    commandee: "Chez la logistique, en attente de livraison",
    recommandee: "En attente de votre décision",
  };
  const attente = ATTENTE[c.statut] ?? c.prochain_geste;
  return (
    <div style={{
      borderStyle: "solid", borderWidth: "1px 1px 1px 4px",
      borderColor: `${INK.border} ${INK.border} ${INK.border} ${TEINTE[c.statut]}`,
      borderRadius: 11, padding: "11px 13px", display: "grid", gap: 6,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "baseline" }}>
        <span style={{ fontWeight: 700, color: INK.primary, fontSize: "0.8rem" }}
              title={c.designation || c.reference}>
          {tronquer(c.designation || c.reference, 26)}
        </span>
        <span style={{
          color: TEINTE[c.statut], fontSize: "0.68rem", fontWeight: 700, whiteSpace: "nowrap",
        }}>{c.statut_label}</span>
      </div>
      <div style={{ fontSize: "0.7rem", color: INK.muted }}>
        {c.qte_proposee} × · {fMoney(c.montant_estime_dt)}
        {c.fournisseur_nom ? ` · ${tronquer(c.fournisseur_nom, 20)}` : ""}
        {c.commande_at ? ` · commandée le ${fDate(c.commande_at)}` : ""}
      </div>
      <span style={{ fontSize: "0.69rem", color: INK.muted }}>{attente}</span>
    </div>
  );
}

function Bloc({ titre, valeur, detail, couleur = INK.primary }: {
  titre: string; valeur: string; detail?: string; couleur?: string;
}) {
  return (
    <div style={{
      borderWidth: 1, borderStyle: "solid", borderColor: INK.border,
      borderRadius: 11, padding: "11px 13px", display: "grid", gap: 3,
    }}>
      <span style={{ fontSize: "0.71rem", fontWeight: 700, color: INK.secondary }}>{titre}</span>
      <span style={{ fontSize: "1.2rem", fontWeight: 800, color: couleur, lineHeight: 1.2 }}>
        {valeur}
      </span>
      {detail && <span style={{ fontSize: "0.68rem", color: INK.muted, lineHeight: 1.45 }}>{detail}</span>}
    </div>
  );
}
