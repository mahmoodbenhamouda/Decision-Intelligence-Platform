"use client";

import { Bot, Play, Scale } from "lucide-react";
import { dateCourte } from "@/shared/format";
import { BLEU, Carte, GRAVITE, INK, fMoney } from "@/shared/ui/VisuelKit";
import { ORIGINE_LABEL } from "./taches.regles";
import type { Impact, LigneDelegation } from "./taches.types";
import { useDelegation } from "./useDelegation";

const ISSUE: Record<LigneDelegation["issue"], { label: string; couleur: string }> = {
  creee: { label: "Confiée", couleur: GRAVITE.faible.couleur },
  deja_confiee: { label: "Déjà en cours", couleur: BLEU[2] },
  recente: { label: "Traitée récemment", couleur: INK.muted },
};

const DECLENCHEUR: Record<string, string> = {
  planifie: "passage hebdomadaire", manuel: "lancé depuis l'écran", commande: "lancé en ligne de commande",
};

function heureDe(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
}

export default function DelegationPanel({ impact, apresPassage }: {
  impact: Impact | null; apresPassage: () => void;
}) {
  const { etat, enCours, erreur, regler, lancer } = useDelegation(true, apresPassage);
  if (!etat) return null;
  const p = etat.dernier;

  return (
    <Carte titre="Délégation autonome" icone={<Bot size={15} />}
      sousTitre="La flotte d'agents confie elle-même le travail d'exécution ; les décisions qui engagent l'entreprise vous restent"
      droite={
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
          <span className="vk-chip" style={{
            background: etat.active ? GRAVITE.faible.fond : "rgba(26,35,72,0.06)",
          }}>
            {etat.active ? `Activée · chaque lundi à ${etat.heure}` : "Désactivée"}
          </span>
          <label style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: "0.72rem", color: INK.secondary }}>
            Heure
            <input type="time" className="mini" defaultValue={etat.heure} key={etat.heure}
              style={{ border: `1px solid ${INK.border}`, borderRadius: 6, padding: "2px 4px" }}
              onBlur={e => { if (e.target.value && e.target.value !== etat.heure) void regler({ heure: e.target.value }); }} />
          </label>
          <button className="vk-bouton-fantome-mini" onClick={() => void regler({ active: !etat.active })}>
            {etat.active ? "Désactiver" : "Activer"}
          </button>
          <button className="vk-bouton-mini" disabled={enCours} onClick={() => void lancer()}>
            <Play size={12} /> {enCours ? "La flotte analyse…" : "Lancer maintenant"}
          </button>
        </div>
      }>
      <div style={{ fontSize: "0.74rem", color: INK.secondary, lineHeight: 1.55 }}>
        Seules les actions d&apos;exécution de gravité haute ou urgente partent seules, vers
        l&apos;employé du bon métier le moins chargé. Au-delà de {etat.regles.charge_max} tâches
        ouvertes, ou sans employé de ce métier, la tâche vous attend dans « À affecter ». Une
        alerte déjà confiée n&apos;est jamais recréée ; une alerte traitée il y a moins
        de {etat.regles.carence_jours} jours non plus, le temps que les données la reflètent.
        {etat.prochain_passage ? ` Prochain passage : ${dateCourte(etat.prochain_passage)} à ${heureDe(etat.prochain_passage)}.` : ""}
      </div>

      {erreur && <div className="vk-erreur" style={{ marginTop: 8 }}>{erreur}</div>}

      {p && (
        <div style={{ marginTop: 12, borderTop: `1px solid ${INK.border}`, paddingTop: 10 }}>
          <div style={{ fontSize: "0.78rem", color: INK.primary, fontWeight: 700 }}>
            Dernier passage : {dateCourte(p.debut)} à {heureDe(p.debut)}
            <span style={{ fontWeight: 500, color: INK.secondary }}>
              {" "}· {DECLENCHEUR[p.declencheur] || p.declencheur}{p.lance_par ? ` par ${p.lance_par}` : ""}
            </span>
          </div>
          {p.statut === "echec" ? (
            <div className="vk-erreur" style={{ marginTop: 6 }}>Aucune tâche confiée : {p.motif}</div>
          ) : p.statut === "en_cours" ? (
            <div style={{ fontSize: "0.76rem", color: INK.secondary, marginTop: 4 }}>Passage en cours…</div>
          ) : (
            <>
              <div style={{ fontSize: "0.76rem", color: INK.secondary, marginTop: 4 }}>
                <b style={{ color: INK.primary }}>{p.n_creees}</b> tâche(s) confiée(s) ·{" "}
                {p.n_deja_confiees} déjà en cours · {p.n_recentes} traitée(s) récemment ·{" "}
                <b style={{ color: INK.primary }}>{p.n_decisions}</b> décision(s) laissée(s) à la direction
              </div>
              <div style={{ display: "grid", gap: 6, marginTop: 8 }}>
                {p.lignes.map(l => {
                  const issue = ISSUE[l.issue] || ISSUE.recente;
                  return (
                    <div key={`${l.rang}-${l.titre}`} style={{
                      display: "grid", gridTemplateColumns: "22px minmax(0, 1fr) auto", gap: 8,
                      alignItems: "baseline", fontSize: "0.76rem",
                    }}>
                      <span style={{ color: INK.muted, fontWeight: 700 }}>{l.rang}.</span>
                      <span style={{ minWidth: 0 }}>
                        <span style={{ color: INK.primary, fontWeight: 700 }}>{l.titre}</span>
                        <span style={{ color: INK.muted }}> — {l.raison}</span>
                      </span>
                      <span style={{ display: "inline-flex", alignItems: "center", gap: 5, color: INK.secondary, whiteSpace: "nowrap" }}>
                        <span style={{ width: 8, height: 8, borderRadius: 2, background: issue.couleur }} />
                        {l.issue === "creee" ? (l.assigne ? `Confiée à ${l.assigne}` : "À affecter") : issue.label}
                      </span>
                    </div>
                  );
                })}
              </div>
              {p.decisions_direction.length > 0 && (
                <div style={{ marginTop: 10 }}>
                  <div style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: "0.74rem", fontWeight: 700, color: INK.secondary }}>
                    <Scale size={13} /> Laissées à votre décision
                  </div>
                  <ul style={{ margin: "4px 0 0", paddingLeft: 18, fontSize: "0.75rem", color: INK.secondary }}>
                    {p.decisions_direction.map(d => (
                      <li key={d.titre}><b style={{ color: INK.primary }}>{d.titre}</b> — {d.action}</li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {!!impact?.par_origine?.length && (
        <div style={{ marginTop: 12, borderTop: `1px solid ${INK.border}`, paddingTop: 10,
          display: "flex", flexWrap: "wrap", gap: 18, fontSize: "0.74rem", color: INK.secondary }}>
          {impact.par_origine.map(o => (
            <span key={o.origine}>
              <b style={{ color: INK.primary }}>{ORIGINE_LABEL[o.origine] || o.origine}</b> : {o.taches} tâche(s),{" "}
              {o.taux_reussite == null ? "aucune terminée" : `${o.taux_reussite} % abouties`}
              {o.recupere_dt ? ` · ${fMoney(o.recupere_dt)} obtenus` : ""}
            </span>
          ))}
        </div>
      )}
    </Carte>
  );
}
