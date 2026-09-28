"use client";

/**
 * TachesPanel — onglet « Suivi des actions ».
 *
 * C'est l'écran qui manquait au projet : le tableau de bord disait ce qui
 * n'allait pas, celui-ci dit QUI s'en occupe et CE QUE ÇA A DONNÉ.
 *
 * Trois niveaux de lecture, du plus court au plus détaillé :
 *   1. quatre chiffres clés (en jeu, récupéré, en retard, réussite) ;
 *   2. « Ce que les actions ont rapporté » — deux graphes : le montant obtenu
 *      mois par mois, et la répartition des issues ;
 *   3. le tableau de travail, une colonne par étape, une carte par tâche.
 *
 * Le même écran sert au directeur et à l'employé : l'API ne renvoie à un
 * employé que ses propres tâches, donc la vue se réduit d'elle-même sans
 * qu'aucun filtre d'affichage n'ait à être « oublié ».
 */

import { useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import {
  AlarmClock, CheckCircle2, Coins, RefreshCw, Repeat,
  Target, UserPlus, Wallet,
} from "lucide-react";
import {
  BLEU, BadgeGravite, Carte, GRAVITE, Grille, INFOBULLE, INK, Legende,
  RangeeTuiles, TuileChiffre, Vide, fAxe, fMoney,
} from "@/shared/ui/VisuelKit";
import { dateCourte as fDate } from "@/shared/format";
import { COLONNES, RESULTATS } from "./taches.regles";
import type { Tache } from "./taches.types";
import { useTaches } from "./useTaches";

export default function TachesPanel({ role }: { role: string }) {
  const {
    estDirecteur, taches, impact, employes, boucle, loading,
    filtreEmploye, setFiltreEmploye, charger, patch, parStatut, donneesMois, donneesResultat,
  } = useTaches(role);
  const [cloture, setCloture] = useState<Tache | null>(null);

  if (loading && !taches.length && !impact) {
    return <div style={{ gridColumn: "span 12" }}><Vide texte="Chargement du suivi…" /></div>;
  }

  return (
    <Grille>
      {/* ── Chiffres clés ──────────────────────────────────────────────── */}
      <RangeeTuiles>
        <TuileChiffre icone={<Wallet size={16} />} label="En jeu, en cours de traitement"
          valeur={fMoney(impact?.en_jeu_dt ?? 0)}
          detail={`${impact?.taches_ouvertes ?? 0} action(s) ouverte(s)`} />
        <TuileChiffre icone={<Coins size={16} />} label="Récupéré grâce aux actions"
          valeur={fMoney(impact?.recupere_dt ?? 0)} accent={GRAVITE.faible.couleur}
          detail={impact?.promesses_dt ? `${fMoney(impact.promesses_dt)} promis en plus` : "encaissé, signé ou commandé"} />
        <TuileChiffre icone={<AlarmClock size={16} />} label="En retard"
          valeur={`${impact?.taches_en_retard ?? 0}`} accent={GRAVITE.critique.couleur}
          detail="échéance dépassée" />
        <TuileChiffre icone={<Target size={16} />} label="Actions qui aboutissent"
          valeur={impact?.taux_reussite == null ? "—" : `${impact.taux_reussite} %`}
          detail={impact?.delai_moyen_j == null ? `${impact?.taches_terminees ?? 0} terminée(s)`
            : `traitées en ${impact.delai_moyen_j} jour(s) en moyenne`} />
      </RangeeTuiles>

      {/* ── Ce que les actions ont rapporté ────────────────────────────── */}
      {donneesMois.length > 0 && (
        <Carte span={7} titre="Ce que les actions ont rapporté"
          sousTitre="Montant réellement obtenu, mois par mois">
          <ResponsiveContainer width="100%" height={230}>
            <BarChart data={donneesMois} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid stroke={INK.grid} vertical={false} />
              <XAxis dataKey="label" tick={{ fill: INK.secondary, fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis tickFormatter={fAxe} tick={{ fill: INK.secondary, fontSize: 11 }} axisLine={false} tickLine={false} />
              <Tooltip cursor={{ fill: "rgba(47,91,234,0.05)" }} contentStyle={INFOBULLE}
                formatter={(v, _n, p) => [`${fMoney(Number(v))} · ${(p?.payload as { nombre?: number })?.nombre ?? 0} action(s)`, "Obtenu"]} />
              <Bar dataKey="montant_dt" name="Obtenu" fill={GRAVITE.faible.couleur} barSize={26} radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
          <Legende items={[{ couleur: GRAVITE.faible.couleur, label: "Montant obtenu" }]} />
        </Carte>
      )}

      {donneesResultat.length > 0 && (
        <Carte span={5} titre="Comment se terminent les actions"
          sousTitre="Nombre d'actions par issue">
          <ResponsiveContainer width="100%" height={Math.max(200, donneesResultat.length * 38)}>
            <BarChart layout="vertical" data={donneesResultat}
              margin={{ top: 4, right: 40, left: 0, bottom: 0 }} barCategoryGap={8}>
              <XAxis type="number" hide allowDecimals={false} />
              <YAxis type="category" dataKey="label" width={150}
                tick={{ fill: INK.primary, fontSize: 12 }} axisLine={false} tickLine={false} />
              <Tooltip cursor={{ fill: "rgba(47,91,234,0.05)" }} contentStyle={INFOBULLE}
                formatter={(v) => [`${v} action(s)`, "Nombre"]} />
              <Bar dataKey="nombre" barSize={16} radius={[0, 4, 4, 0]}
                label={{ position: "right", fill: INK.secondary, fontSize: 11 }}>
                {donneesResultat.map((r, i) => <Cell key={i} fill={r.couleur} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <Legende items={[
            { couleur: GRAVITE.faible.couleur, label: "Issue gagnante" },
            { couleur: BLEU[1], label: "Autre issue" },
          ]} />
        </Carte>
      )}

      {/* ── Retour vers les modèles ────────────────────────────────────── */}
      {estDirecteur && boucle && (
        <div className="chart-card" style={{ gridColumn: "span 12", padding: "12px 16px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", fontSize: "0.8rem", color: INK.secondary }}>
            <Repeat size={15} color={BLEU[3]} />
            {boucle.disponible ? (
              <span>
                <b style={{ color: INK.primary }}>{boucle.taches ?? 0} résultat(s)</b> sont
                déjà repartis vers les prévisions, dont <b style={{ color: INK.primary }}>{boucle.retours_produits ?? 0}</b> retour(s)
                sur les produits proposés.
                {boucle.en_attente_de_transfert ? ` ${boucle.en_attente_de_transfert} attendent le prochain transfert.` : ""}
              </span>
            ) : (
              <span>
                Les résultats sont enregistrés ({boucle.resultats_enregistres ?? 0} action(s) terminée(s))
                et repartiront vers les prévisions au prochain transfert.
              </span>
            )}
          </div>
        </div>
      )}

      {/* ── Tableau de travail ─────────────────────────────────────────── */}
      <Carte
        titre={estDirecteur ? "Qui fait quoi" : "Mes actions"}
        sousTitre={estDirecteur
          ? "Chaque carte est une action confiée à quelqu'un, du premier contact au résultat"
          : "Les actions qui vous sont confiées, les plus urgentes d'abord"}
        droite={
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {estDirecteur && employes.length > 0 && (
              <select className="mini" value={filtreEmploye}
                onChange={e => setFiltreEmploye(e.target.value === "" ? "" : Number(e.target.value))}>
                <option value="">Toute l&apos;équipe</option>
                {employes.map(e => <option key={e.id} value={e.id}>{e.nom}</option>)}
              </select>
            )}
            <button className="icon-button" onClick={charger} title="Actualiser">
              <RefreshCw size={15} className={loading ? "spin-icon" : ""} />
            </button>
          </div>
        }>
        {!taches.length ? (
          <Vide texte={estDirecteur
            ? "Aucune action confiée pour l'instant. Utilisez le bouton « Confier » depuis l'onglet Priorités."
            : "Aucune action ne vous est confiée pour le moment."} />
        ) : (
          <div className="vk-tableau">
            {COLONNES.map(col => (
              <div key={col.id} className="vk-colonne">
                <div className="vk-colonne-tete">
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                    {col.icone}{col.label}
                  </span>
                  <span className="vk-compteur">{parStatut[col.id]?.length || 0}</span>
                </div>
                <div className="vk-colonne-corps">
                  {(parStatut[col.id] || []).map(t => (
                    <div key={t.id} className="vk-carte-tache"
                      style={{ borderLeft: `3px solid ${(GRAVITE[t.severite] || GRAVITE.moyenne).couleur}` }}>
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 6, alignItems: "flex-start" }}>
                        <span style={{ fontWeight: 800, fontSize: "0.83rem", color: INK.primary, lineHeight: 1.3 }}>
                          {t.titre}
                        </span>
                        {t.en_retard && <span className="vk-retard">En retard</span>}
                      </div>
                      {t.client_nom && <div className="vk-chip">{t.client_nom}</div>}
                      <div style={{ fontSize: "0.72rem", color: INK.secondary }}>
                        {t.type_label}
                        {t.montant_dt ? ` · ${fMoney(t.montant_dt)} en jeu` : ""}
                      </div>
                      {t.details && <div className="vk-clamp-2" style={{ fontSize: "0.73rem", color: INK.muted }}>{t.details}</div>}
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 6, fontSize: "0.7rem", color: INK.muted }}>
                        <span>{t.assigne_nom || "à affecter"}</span>
                        <span>{t.statut === "terminee" ? fDate(t.closed_at) : `pour le ${fDate(t.echeance)}`}</span>
                      </div>
                      {t.venue_du_client && (
                        <span className="vk-chip" style={{ background: "rgba(12,163,12,0.10)" }}>
                          Demande du client
                        </span>
                      )}

                      {t.statut === "terminee" ? (
                        <div style={{ fontSize: "0.74rem", color: INK.secondary, borderTop: `1px solid ${INK.border}`, paddingTop: 6 }}>
                          <b style={{ color: INK.primary }}>{t.resultat_label || "Terminée"}</b>
                          {t.resultat_montant_dt ? ` · ${fMoney(t.resultat_montant_dt)}` : ""}
                          {t.resultat_commentaire ? <div className="vk-clamp-2">{t.resultat_commentaire}</div> : null}
                        </div>
                      ) : (
                        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                          {t.statut === "a_affecter" && estDirecteur && (
                            <select className="mini" defaultValue=""
                              onChange={e => e.target.value && patch(t.id, { assigne_id: Number(e.target.value) })}>
                              <option value="" disabled>Confier à…</option>
                              {employes.map(e => (
                                <option key={e.id} value={e.id}>{e.nom} ({e.taches_ouvertes})</option>
                              ))}
                            </select>
                          )}
                          {t.statut === "a_faire" && (
                            <button className="vk-bouton-mini" onClick={() => patch(t.id, { statut: "en_cours" })}>
                              Je m&apos;en occupe
                            </button>
                          )}
                          {(t.statut === "en_cours" || t.statut === "bloquee") && (
                            <button className="vk-bouton-mini" onClick={() => setCloture(t)}>
                              Noter le résultat
                            </button>
                          )}
                          {t.statut === "en_cours" && (
                            <button className="vk-bouton-fantome-mini" onClick={() => patch(t.id, { statut: "bloquee" })}>
                              Bloquée
                            </button>
                          )}
                          {t.statut === "bloquee" && (
                            <button className="vk-bouton-fantome-mini" onClick={() => patch(t.id, { statut: "en_cours" })}>
                              Reprendre
                            </button>
                          )}
                        </div>
                      )}
                      <BadgeGravite severite={t.severite} />
                    </div>
                  ))}
                  {!(parStatut[col.id] || []).length && (
                    <div style={{ fontSize: "0.73rem", color: INK.muted, padding: "8px 2px" }}>—</div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </Carte>

      {cloture && (
        <FenetreResultat tache={cloture} onClose={() => setCloture(null)}
          onValider={async (corps) => { const ok = await patch(cloture.id, corps); if (ok) setCloture(null); }} />
      )}
    </Grille>
  );
}

/** Clôture d'une action : c'est ICI que se fabrique la mesure d'impact. */
function FenetreResultat({ tache, onClose, onValider }: {
  tache: Tache; onClose: () => void;
  onValider: (corps: Record<string, unknown>) => void | Promise<void>;
}) {
  const [resultat, setResultat] = useState("paye");
  const [montant, setMontant] = useState<string>(
    tache.montant_dt ? String(Math.round(tache.montant_dt)) : "");
  const [commentaire, setCommentaire] = useState("");
  const gagnant = RESULTATS.find(r => r.id === resultat)?.gain;

  return (
    <div className="vk-modal-fond" onClick={onClose}>
      <div className="vk-modal" onClick={e => e.stopPropagation()}>
        <div className="vk-modal-tete">
          <span style={{ display: "inline-flex", alignItems: "center", gap: 8, fontWeight: 800, color: INK.primary }}>
            <CheckCircle2 size={17} color={GRAVITE.faible.couleur} /> Résultat de l&apos;action
          </span>
          <button className="icon-button" onClick={onClose}>×</button>
        </div>
        <div className="vk-modal-corps">
          <div style={{ fontSize: "0.85rem", fontWeight: 700, color: INK.primary }}>{tache.titre}</div>
          <label className="vk-champ">
            <span>Qu&apos;est-ce que ça a donné ?</span>
            <select value={resultat} onChange={e => setResultat(e.target.value)}>
              {RESULTATS.map(r => <option key={r.id} value={r.id}>{r.label}</option>)}
            </select>
          </label>
          <label className="vk-champ">
            <span>{gagnant ? "Montant obtenu (DT)" : "Montant concerné (DT)"}</span>
            <input type="number" min={0} value={montant} onChange={e => setMontant(e.target.value)} />
            <small style={{ color: INK.muted }}>
              {gagnant
                ? "Ce montant alimente « récupéré grâce aux actions »."
                : "Conservé pour comprendre ce qui a été perdu, sans compter comme un gain."}
            </small>
          </label>
          <label className="vk-champ">
            <span>Ce qu&apos;il faut retenir</span>
            <textarea rows={3} value={commentaire} maxLength={2000}
              placeholder="Ce que le client a répondu, la date promise…"
              onChange={e => setCommentaire(e.target.value)} />
          </label>
        </div>
        <div className="vk-modal-pied">
          <button className="vk-bouton-fantome" onClick={onClose}>Annuler</button>
          <button className="vk-bouton" onClick={() => onValider({
            statut: "terminee", resultat,
            resultat_montant_dt: Number(montant) || 0,
            resultat_commentaire: commentaire.trim() || null,
          })}>
            <UserPlus size={14} /> Clôturer
          </button>
        </div>
      </div>
    </div>
  );
}
