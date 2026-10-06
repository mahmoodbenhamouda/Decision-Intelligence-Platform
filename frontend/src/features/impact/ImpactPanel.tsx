"use client";

import { Fragment, useState } from "react";
import {
  AlertTriangle, BadgeCheck, ChevronDown, ChevronRight, Info, Quote,
  RefreshCw, Target, Wallet,
} from "lucide-react";
import {
  BLEU, Carte, Grille, INK, Legende, RangeeTuiles, TuileChiffre, Vide, fMoney,
  tronquer,
} from "@/shared/ui/VisuelKit";
import type { ImpactPoste } from "./impact.types";
import { useImpact } from "./useImpact";

/** Deux pas d'une même rampe : le récupérable est une PART de l'identifié. */
const C_IDENTIFIE = BLEU[1];
const C_RECUPERABLE = BLEU[3];

const fPct = (t: number) => `${Math.round(t * 100)} %`;

/**
 * Identifié et récupérable, l'un DANS l'autre.
 *
 * Les dessiner côte à côte laisserait croire à deux montants qu'on pourrait
 * additionner. Le récupérable est une part de l'identifié : il est donc
 * imbriqué, dans la même teinte, deux pas plus foncé. L'échelle est commune à
 * tous les postes, sinon deux barres de même longueur mentiraient.
 */
function Barre({ identifie, recuperable, echelle }: {
  identifie: number; recuperable: number; echelle: number;
}) {
  const largeur = echelle > 0 ? (identifie / echelle) * 100 : 0;
  const part = identifie > 0 ? (recuperable / identifie) * 100 : 0;
  return (
    <div style={{ display: "grid", gap: 4, minWidth: 150 }}>
      <div style={{
        position: "relative", height: 15, borderRadius: 4,
        width: `${Math.max(largeur, 1.5)}%`, background: C_IDENTIFIE,
      }}>
        <div style={{
          position: "absolute", inset: "0 auto 0 0", width: `${part}%`,
          minWidth: 3, borderRadius: 4, background: C_RECUPERABLE,
          // 2px de surface entre les deux remplissages : sans cette coupure,
          // la frontière se lit comme un dégradé et la part devient illisible.
          boxShadow: `2px 0 0 0 var(--card-bg, #fff)`,
        }} />
      </div>
      <div style={{ display: "flex", gap: 8, fontSize: "0.7rem", color: INK.muted }}>
        <b style={{ color: INK.primary }}>{fMoney(identifie)}</b>
        <span>dont <b style={{ color: INK.secondary }}>{fMoney(recuperable)}</b></span>
      </div>
    </div>
  );
}

/** Le détail par client : un total ne se décide pas, un nom se rappelle. */
function ParClient({ poste }: { poste: ImpactPoste }) {
  if (!poste.par_client.length) {
    return (
      <p className="muted-note" style={{ fontSize: "0.72rem", padding: "6px 2px" }}>
        Ce poste n&apos;est pas attribuable à des comptes nommés : il porte sur des
        références de stock ou sur l&apos;ensemble des factures, pas sur des clients.
      </p>
    );
  }
  return (
    <div style={{ display: "grid", gap: 7 }}>
      <p style={{ fontSize: "0.72rem", color: INK.secondary, margin: 0 }}>
        Les {poste.par_client.length} comptes qui portent ce poste, du plus lourd au
        plus léger. Le taux de {fPct(poste.hypothese_conversion)} leur est appliqué à
        tous : aucun client n&apos;est supposé convertir mieux qu&apos;un autre.
      </p>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.76rem" }}>
        <thead>
          <tr style={{ textAlign: "left", color: INK.muted, fontSize: "0.68rem" }}>
            <th style={{ padding: "4px 8px" }}>Client</th>
            <th style={{ padding: "4px 8px", textAlign: "right" }}>Identifié</th>
            <th style={{ padding: "4px 8px", textAlign: "right" }}>Récupérable</th>
          </tr>
        </thead>
        <tbody>
          {poste.par_client.map(c => (
            <tr key={c.client} style={{ borderTop: `1px solid ${INK.grid}` }}>
              <td style={{ padding: "5px 8px", color: INK.primary, fontWeight: 600 }}
                title={c.nom}>{tronquer(c.nom, 34)}</td>
              <td style={{ padding: "5px 8px", textAlign: "right", color: INK.secondary }}>
                {fMoney(c.montant_identifie_dt)}
              </td>
              <td style={{ padding: "5px 8px", textAlign: "right", fontWeight: 700, color: INK.primary }}>
                {fMoney(c.montant_recuperable_dt)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function ImpactPanel() {
  const { data, d, loading, load, ouvert, basculer } = useImpact();
  const [toutesPhrases, setToutesPhrases] = useState(false);

  if (loading && !data) {
    return <Grille><div style={{ gridColumn: "span 12" }}><Vide texte="Calcul en cours…" /></div></Grille>;
  }
  if (!data?.servi || !d.postes.length) {
    return (
      <Grille>
        <Carte titre="Enjeu financier identifié">
          <Vide texte={data?.motif || "Aucun poste chiffrable : les modèles ne sont pas servis."} />
        </Carte>
      </Grille>
    );
  }

  const phrases = data.phrases || [];
  const correction = data.correction_de_donnees;

  return (
    <Grille>
      {/* L'avertissement AVANT les chiffres, et non en note de bas de page :
          il change la façon de les lire. */}
      <div style={{
        gridColumn: "span 12", display: "flex", gap: 11, padding: "12px 15px",
        borderRadius: 11, background: "rgba(236,131,90,0.07)",
        border: "1px solid rgba(236,131,90,0.22)",
        fontSize: "0.77rem", color: INK.secondary, lineHeight: 1.55,
      }}>
        <AlertTriangle size={16} style={{ color: "#EC835A", flexShrink: 0, marginTop: 1 }} />
        <span>{data.avertissement_principal}</span>
      </div>

      <RangeeTuiles>
        <TuileChiffre icone={<Target size={16} />} label="Enjeu identifié"
          valeur={fMoney(data.montant_total_identifie_dt)}
          detail={`sur ${d.postes.length} postes, chacun mesuré sur l'entrepôt`}
          accent={C_IDENTIFIE} />
        <TuileChiffre icone={<Wallet size={16} />} label="Récupérable"
          valeur={fMoney(data.montant_total_recuperable_dt)}
          detail="sous les hypothèses déclarées, si les actions sont menées"
          accent={C_RECUPERABLE} />
        {correction && (
          <TuileChiffre icone={<BadgeCheck size={16} />} label="Erreur supprimée"
            valeur={fMoney(correction.montant_dt)}
            detail="ne s'additionne à aucun poste — rien à encaisser"
            accent="#0CA30C" />
        )}
      </RangeeTuiles>

      {/* Ce qu'un directeur répétera. Dérivé des montants, jamais écrit en dur :
          une phrase ne survit pas au poste qui la fonde. */}
      {phrases.length > 0 && (
        <Carte span={12} titre="À dire tel quel" icone={<Quote size={15} />}
          sousTitre="Chaque phrase est calculée depuis les montants ci-dessus — aucune n'est écrite à la main"
          droite={<button className="icon-button" onClick={load} title="Recalculer">
            <RefreshCw size={15} className={loading ? "spin-icon" : ""} />
          </button>}>
          <div style={{ display: "grid", gap: 9 }}>
            {(toutesPhrases ? phrases : phrases.slice(0, 3)).map((p, i) => (
              <p key={i} style={{
                margin: 0, padding: "10px 13px", borderRadius: 9,
                borderLeft: `3px solid ${C_RECUPERABLE}`,
                background: "rgba(47,91,234,0.045)",
                fontSize: "0.81rem", color: INK.primary, lineHeight: 1.6,
              }}>{p}</p>
            ))}
          </div>
          {phrases.length > 3 && (
            <button type="button" onClick={() => setToutesPhrases(v => !v)}
              style={{
                marginTop: 9, background: "none", border: "none", padding: 0,
                cursor: "pointer", font: "inherit", fontSize: "0.74rem",
                fontWeight: 700, color: C_RECUPERABLE,
              }}>
              {toutesPhrases ? "Voir moins" : `Voir les ${phrases.length - 3} autres`}
            </button>
          )}
        </Carte>
      )}

      <Carte span={12} titre="D'où viennent ces montants" icone={<Info size={15} />}
        sousTitre="Un poste par ligne : ce qui est mesuré, le taux supposé, et ce que le chiffre ne dit pas">
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.79rem" }}>
            <thead>
              <tr style={{ textAlign: "left", color: INK.muted, fontSize: "0.7rem" }}>
                <th style={{ padding: "6px 8px" }}>Poste</th>
                <th style={{ padding: "6px 8px", minWidth: 165 }}>Identifié · dont récupérable</th>
                <th style={{ padding: "6px 8px", textAlign: "right" }}>Hypothèse</th>
                <th style={{ padding: "6px 8px" }}>Action à mener</th>
                <th style={{ padding: "6px 8px", width: 34 }} />
              </tr>
            </thead>
            <tbody>
              {d.postes.map(p => {
                const deplie = ouvert === p.cle;
                return (
                  <Fragment key={p.cle}>
                    <tr style={{ borderTop: `1px solid ${INK.grid}` }}>
                      <td style={{ padding: "9px 8px" }}>
                        <div style={{ fontWeight: 700, color: INK.primary }}>{p.poste}</div>
                        <div style={{ fontSize: "0.69rem", color: INK.muted, lineHeight: 1.5, maxWidth: 420 }}>
                          {p.ce_qui_est_mesure}
                        </div>
                        <div style={{ fontSize: "0.67rem", color: INK.muted, marginTop: 3, fontStyle: "italic" }}>
                          source : {p.source_du_chiffre}
                        </div>
                      </td>
                      <td style={{ padding: "9px 8px" }}>
                        <Barre identifie={p.montant_identifie_dt}
                          recuperable={p.montant_recuperable_dt}
                          echelle={d.maxIdentifie} />
                      </td>
                      <td style={{ padding: "9px 8px", textAlign: "right" }}>
                        <span title={p.justification_hypothese} style={{
                          background: `${C_RECUPERABLE}14`, color: C_RECUPERABLE,
                          borderRadius: 6, padding: "3px 8px", fontSize: "0.72rem",
                          fontWeight: 800, whiteSpace: "nowrap", cursor: "help",
                        }}>{fPct(p.hypothese_conversion)}</span>
                      </td>
                      <td style={{ padding: "9px 8px", color: INK.secondary, fontSize: "0.74rem", maxWidth: 220 }}>
                        {p.action_requise}
                      </td>
                      <td style={{ padding: "9px 8px" }}>
                        <button className="icon-button" onClick={() => basculer(p.cle)}
                          title={deplie ? "Replier" : "Voir le détail et la réserve"}>
                          {deplie ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                        </button>
                      </td>
                    </tr>
                    {deplie && (
                      <tr>
                        <td colSpan={5} style={{ padding: "0 8px 14px" }}>
                          <div style={{ display: "grid", gap: 11, padding: "12px 14px", borderRadius: 10,
                            background: "rgba(47,91,234,0.04)", border: `1px solid ${INK.border}` }}>
                            <div style={{ fontSize: "0.75rem", color: INK.secondary, lineHeight: 1.6 }}>
                              <b style={{ color: INK.primary }}>Pourquoi {fPct(p.hypothese_conversion)} ?</b>{" "}
                              {p.justification_hypothese}
                            </div>
                            {p.reserve && (
                              <div style={{ fontSize: "0.75rem", color: INK.secondary, lineHeight: 1.6,
                                paddingLeft: 11, borderLeft: "3px solid #EC835A" }}>
                                <b style={{ color: INK.primary }}>Ce que ce chiffre ne dit pas.</b>{" "}
                                {p.reserve}
                              </div>
                            )}
                            <ParClient poste={p} />
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
        <Legende items={[
          { couleur: C_IDENTIFIE, label: "Montant identifié — mesuré sur l'entrepôt" },
          { couleur: C_RECUPERABLE, label: "Part récupérable — sous l'hypothèse déclarée" },
        ]} />
      </Carte>

      {correction && (
        <Carte span={7} titre={correction.poste} icone={<BadgeCheck size={15} />}
          sousTitre={correction.nature}>
          <div style={{ display: "grid", gap: 9, fontSize: "0.77rem", color: INK.secondary, lineHeight: 1.6 }}>
            <div style={{ fontSize: "1.5rem", fontWeight: 800, color: "#0CA30C" }}>
              {fMoney(correction.montant_dt)}
            </div>
            <span><b style={{ color: INK.primary }}>Ce qui a été corrigé.</b> {correction.ce_qui_a_ete_corrige}</span>
            <span><b style={{ color: INK.primary }}>Pourquoi il est à part.</b> {correction.pourquoi_isole}</span>
            <span><b style={{ color: INK.primary }}>Sa certitude.</b> {correction.certitude}</span>
          </div>
        </Carte>
      )}

      {!!data.non_mesurable?.length && (
        <Carte span={5} titre="Ce qui n'est pas chiffré, et pourquoi"
          sousTitre="Trois apports réels qu'aucune requête ne sait mesurer">
          <div style={{ display: "grid", gap: 10 }}>
            {data.non_mesurable.map(n => (
              <div key={n.apport} style={{ fontSize: "0.75rem", color: INK.secondary, lineHeight: 1.55 }}>
                <b style={{ color: INK.primary }}>{n.apport}.</b> {n.pourquoi_non_chiffre}
              </div>
            ))}
          </div>
        </Carte>
      )}

      {data.comment_verifier && (
        <div style={{
          gridColumn: "span 12", padding: "11px 14px", borderRadius: 10,
          background: "rgba(47,91,234,0.045)", border: `1px solid ${INK.border}`,
          fontSize: "0.74rem", color: INK.secondary, lineHeight: 1.55,
          display: "flex", gap: 9,
        }}>
          <Info size={15} style={{ color: BLEU[3], flexShrink: 0, marginTop: 1 }} />
          <span>{data.comment_verifier}</span>
        </div>
      )}
    </Grille>
  );
}
