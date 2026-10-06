"use client";

import {
  Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import {
  Flag, Layers, RefreshCw, Scale, UserPlus, Users, Wallet,
} from "lucide-react";
import ConfierTache, { BadgeConfiee } from "@/features/taches/ConfierTache";
import PanneauMasque, { BadgeFiltreClients } from "@/shared/ui/PanneauMasque";
import { Raisons } from "@/shared/ui/Pourquoi";
import {
  BLEU, BadgeGravite, Carte, GRAVITE, Grille, INFOBULLE, INK, Legende, RangeeTuiles,
  TuileChiffre, Vide, fAxe, fMoney, tronquer,
} from "@/shared/ui/VisuelKit";
import { DOMAINE, DOMAINE_AGENT, ORDRE_SEV, cleCible, origineCible, origineClient, premierePhrase } from "./briefing.regles";
import type { Cible, Constat } from "./briefing.types";
import type { Confiee, Origine } from "@/features/taches/taches.types";

/** Liste des clients (ou produits) d'un constat : chaque ligne est une tâche précise. */
function ListeCibles({ a, peutConfier, confiees, onConfier }: {
  a: Constat; peutConfier: boolean; confiees: Record<string, Confiee>;
  onConfier: (o: Origine) => void;
}) {
  const estClient = !!(a.clients_concernes || []).length;
  const cibles: Cible[] = estClient ? a.clients_concernes! : (a.produits_concernes || []);
  if (!cibles.length) return null;
  const delegable = peutConfier && a.execution != null;
  const enJeu = (c: Cible) => c.enjeu_dt ?? c.montant_dt;
  const sommeLignes = cibles.reduce((s, c) => s + (enJeu(c) || 0), 0);
  const totalCarte = a.enjeu_court_terme_dt || a.montant_dt;
  return (
    <div style={{ borderTop: `1px solid ${INK.border}`, paddingTop: 8 }}>
      <div style={{ fontSize: "0.72rem", fontWeight: 700, color: INK.muted, marginBottom: 6 }}>
        {estClient ? `${cibles.length} client(s) à traiter` : `${cibles.length} produit(s) à commander`}
        {delegable ? " — une tâche par ligne" : ""}
        {sommeLignes > 0 && totalCarte ? (
          <span style={{ fontWeight: 500 }}>
            {" "}· {fMoney(sommeLignes)} sur les {fMoney(totalCarte)} en jeu
          </span>
        ) : null}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {cibles.map((c, i) => {
          const deja = confiees[cleCible(a.titre, c.nom)];
          return (
            <div key={`${c.nom}-${i}`} style={{
              display: "grid", gridTemplateColumns: "1fr auto", gap: 8, alignItems: "center",
              padding: "6px 8px", borderRadius: 8, background: "rgba(47,91,234,0.04)",
            }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                  <b style={{ fontSize: "0.78rem", color: INK.primary, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                     title={c.nom}>{c.nom}</b>
                  {enJeu(c) ? <span style={{ fontSize: "0.76rem", fontWeight: 700, color: INK.primary, whiteSpace: "nowrap" }}>{fMoney(enJeu(c))}</span> : null}
                </div>
                <div style={{ fontSize: "0.72rem", color: INK.secondary }}>{c.motif}</div>
              </div>
              {delegable && (deja
                ? <BadgeConfiee info={deja} compact />
                : (
                  <button className="vk-bouton-mini" title={c.tache.titre}
                    onClick={() => onConfier(origineCible(a, c, estClient))}>
                    <UserPlus size={12} /> Confier
                  </button>
                ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}
import { useBriefing } from "./useBriefing";

export default function BriefingPanel({ filterPayload, peutConfier = false }: {
  filterPayload: Record<string, unknown>;

  peutConfier?: boolean;
}) {
  const {
    data, loading, charger, vue,
    ouvert, setOuvert, confier, setConfier, confiees, rechargerConfiees,
  } = useBriefing(filterPayload, peutConfier);

  if (loading && !data) {
    return <div style={{ gridColumn: "span 12" }}><Vide texte="Analyse de votre situation en cours…" /></div>;
  }
  if (data?.error || !vue.actions.length) {
    return (
      <div style={{ gridColumn: "span 12" }}>
        <Vide texte={data?.error ? "Analyse momentanément indisponible." : "Aucune priorité à signaler sur ce périmètre."} />
      </div>
    );
  }

  const portee = data?.portee_modeles;
  const premiere = vue.actions[0];
  const sevPresentes = Array.from(new Set(vue.top.map(t => t.severite)))
    .sort((a, b) => (ORDRE_SEV[a] ?? 9) - (ORDRE_SEV[b] ?? 9))
    .map(s => ({ couleur: (GRAVITE[s] || GRAVITE.moyenne).couleur, label: (GRAVITE[s] || GRAVITE.moyenne).label }));

  return (
    <Grille>
      {portee?.mode === "masque" && (
        <PanneauMasque motif={`Seules les cartes calculées sur vos factures sont affichées. ${portee.motif}`} />
      )}
      {portee?.mode === "clients" && (
        <div style={{ gridColumn: "span 12" }}><BadgeFiltreClients n={portee.n_clients} /></div>
      )}
      <div className="chart-card" style={{
        gridColumn: "span 12", padding: "18px 20px",
        background: "linear-gradient(120deg, rgba(58,63,176,0.10), rgba(47,91,234,0.07) 45%, rgba(20,194,214,0.07))",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
          <span style={{
            width: 44, height: 44, borderRadius: 13, display: "grid", placeItems: "center",
            background: BLEU[3], color: "#fff", flexShrink: 0,
          }}><Flag size={20} /></span>
          <div style={{ flex: 1, minWidth: 220 }}>
            <div style={{ fontSize: "0.74rem", fontWeight: 700, color: INK.secondary, textTransform: "uppercase", letterSpacing: "0.04em" }}>
              À traiter en premier
            </div>
            <div style={{ fontSize: "1.2rem", fontWeight: 800, color: INK.primary, marginTop: 2 }}>
              {premiere.titre}
            </div>
            <div style={{ fontSize: "0.82rem", color: INK.secondary, marginTop: 3 }}>
              {premiere.resume || premierePhrase(premiere.constat)}
            </div>
          </div>
          <button className="icon-button" onClick={charger} title="Actualiser">
            <RefreshCw size={15} className={loading ? "spin-icon" : ""} />
          </button>
        </div>
      </div>

      <RangeeTuiles>
        <TuileChiffre icone={<Wallet size={16} />} label="En jeu à court terme"
          valeur={fMoney(vue.total)} detail="tous domaines confondus" />
        <TuileChiffre icone={<Flag size={16} />} label="Actions prioritaires"
          valeur={`${vue.urgentes}`} detail={`sur ${vue.actions.length} points d'attention`}
          accent={GRAVITE.haute.couleur} />
        <TuileChiffre icone={<Users size={16} />} label="Clients à traiter en premier"
          valeur={`${vue.clients.length}`} detail="signalés dans plusieurs domaines" />
        <TuileChiffre icone={<Layers size={16} />} label="Domaines concernés"
          valeur={`${vue.parDomaine.length}`} detail={vue.parDomaine[0] ? `le plus exposé : ${vue.parDomaine[0].domaine}` : ""} />
      </RangeeTuiles>

      <Carte span={7} titre="Par quoi commencer" sousTitre="Montant réellement en jeu dans les prochains mois, par action">
        <ResponsiveContainer width="100%" height={Math.max(220, vue.top.length * 46)}>
          <BarChart layout="vertical" data={vue.top} margin={{ top: 4, right: 70, left: 0, bottom: 0 }} barCategoryGap={10}>
            <CartesianGrid stroke={INK.grid} horizontal={false} />
            <XAxis type="number" tickFormatter={fAxe} tick={{ fill: INK.secondary, fontSize: 11 }} axisLine={false} tickLine={false} />
            <YAxis type="category" dataKey="nom" width={210} tick={{ fill: INK.primary, fontSize: 12 }} axisLine={false} tickLine={false} />
            <Tooltip
              cursor={{ fill: "rgba(47,91,234,0.05)" }}
              contentStyle={INFOBULLE}
              formatter={(v) => [fMoney(Number(v)), "En jeu"]}
              labelFormatter={(_, p) => (p?.[0]?.payload as { titre?: string })?.titre || ""}
            />
            <Bar dataKey="enjeu" barSize={18} radius={[0, 4, 4, 0]}
              label={{ position: "right", formatter: (v: unknown) => fMoney(Number(v)), fill: INK.secondary, fontSize: 11 }}>
              {vue.top.map((t, i) => <Cell key={i} fill={(GRAVITE[t.severite] || GRAVITE.moyenne).couleur} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
        <Legende items={sevPresentes} />
      </Carte>

      <Carte span={5} titre="Où se situe l'enjeu" sousTitre="Montant en jeu regroupé par domaine">
        <ResponsiveContainer width="100%" height={Math.max(220, vue.parDomaine.length * 46)}>
          <BarChart layout="vertical" data={vue.parDomaine} margin={{ top: 4, right: 70, left: 0, bottom: 0 }} barCategoryGap={10}>
            <XAxis type="number" hide />
            <YAxis type="category" dataKey="domaine" width={120} tick={{ fill: INK.primary, fontSize: 12 }} axisLine={false} tickLine={false} />
            <Tooltip cursor={{ fill: "rgba(47,91,234,0.05)" }} contentStyle={INFOBULLE}
              formatter={(v) => [fMoney(Number(v)), "En jeu"]} />
            <Bar dataKey="enjeu" fill={BLEU[3]} barSize={18} radius={[0, 4, 4, 0]}
              label={{ position: "right", formatter: (v: unknown) => fMoney(Number(v)), fill: INK.secondary, fontSize: 11 }} />
          </BarChart>
        </ResponsiveContainer>
      </Carte>

      {vue.clients.length > 0 && (
        <Carte titre="Clients à traiter en premier" icone={<Users size={15} />}
          sousTitre="Ces comptes apparaissent dans plusieurs domaines à la fois : chaque problème aggrave l'autre">
          <div style={{ display: "grid", gap: 12, gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))" }}>
            {vue.clients.slice(0, 6).map(c => (
              <div key={c.client} className="vk-carte-action" style={{ borderLeft: `4px solid ${GRAVITE.haute.couleur}` }}>
                <div style={{ fontWeight: 800, color: INK.primary, fontSize: "0.92rem" }}>{c.client}</div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {c.domaines.map(d => <span key={d} className="vk-chip">{DOMAINE_AGENT[d] || d}</span>)}
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                  <div style={{ fontSize: "0.75rem", color: INK.secondary }}>
                    <b style={{ color: INK.primary, fontSize: "1rem" }}>{fMoney(c.montant_cumule_dt)}</b> concernés
                  </div>
                  {peutConfier && (
                    confiees[origineClient(c).titre]
                      ? <BadgeConfiee info={confiees[origineClient(c).titre]} />
                      : (
                        <button className="vk-bouton-mini"
                          onClick={() => setConfier(origineClient(c))}>
                          <UserPlus size={12} /> Confier
                        </button>
                      )
                  )}
                </div>
              </div>
            ))}
          </div>
        </Carte>
      )}

      <Carte titre="Toutes les actions" sousTitre="Cliquez sur une carte pour lire le détail">
        <div style={{ display: "grid", gap: 12, gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))" }}>
          {vue.actions.map((a, i) => {
            const d = DOMAINE[a.categorie] || { label: a.categorie, icone: <Layers size={15} /> };
            const g = GRAVITE[a.severite] || GRAVITE.moyenne;
            const detail = ouvert === i;
            const nCibles = (a.clients_concernes || []).length || (a.produits_concernes || []).length;
            return (
              <div key={i} className="vk-carte-action" style={{ borderTop: `3px solid ${g.couleur}` }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: "0.72rem", fontWeight: 700, color: INK.secondary }}>
                    <span style={{ color: BLEU[3], display: "inline-flex" }}>{d.icone}</span>{d.label}
                  </span>
                  <BadgeGravite severite={a.severite} />
                </div>
                <div style={{ fontWeight: 800, color: INK.primary, fontSize: "0.95rem", lineHeight: 1.3 }}>{a.titre}</div>
                {(a.enjeu_court_terme_dt || a.montant_dt) ? (
                  <div style={{ fontSize: "1.35rem", fontWeight: 800, color: INK.primary }}>
                    {fMoney(a.enjeu_court_terme_dt || a.montant_dt)}
                    <span style={{ fontSize: "0.72rem", fontWeight: 600, color: INK.muted }}> en jeu</span>
                  </div>
                ) : null}
                <div style={{ fontSize: "0.8rem", color: INK.secondary }}>{a.resume || premierePhrase(a.constat)}</div>
                <div className={detail ? "" : "vk-clamp-2"} style={{ fontSize: "0.8rem", color: BLEU[4], fontWeight: 600 }}>
                  → {a.action}
                </div>
                {detail && (
                  <div style={{ fontSize: "0.78rem", color: INK.secondary, lineHeight: 1.55, borderTop: `1px solid ${INK.border}`, paddingTop: 8 }}>
                    {a.constat}
                  </div>
                )}
                {detail && (
                  <ListeCibles a={a} peutConfier={peutConfier} confiees={confiees} onConfier={setConfier} />
                )}
                {detail && (a.pourquoi || []).map(p => (
                  <Raisons key={p.sujet} titre={`Pourquoi ${tronquer(p.sujet, 28)}`}
                    raisons={p.raisons.map(r => ({ explication: r }))} />
                ))}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                  <button className="vk-lien" onClick={() => setOuvert(detail ? null : i)}>
                    {detail ? "Masquer le détail" : "Voir le détail"}
                  </button>
                  {a.execution === null ? (
                    <span className="vk-chip" title="Action qui engage l'entreprise : elle se décide, elle ne se confie pas">
                      <Scale size={11} /> Décision de direction
                    </span>
                  ) : nCibles ? (
                    !detail && (
                      <button className="vk-bouton-mini" onClick={() => setOuvert(i)}
                        title="Chaque ligne se confie séparément, avec une tâche précise">
                        <Users size={12} /> {nCibles} {(a.clients_concernes || []).length ? "client(s)" : "produit(s)"} à confier
                      </button>
                    )
                  ) : peutConfier && (
                    confiees[a.titre] ? (
                      <BadgeConfiee info={confiees[a.titre]} />
                    ) : (
                      <button className="vk-bouton-mini" onClick={() => setConfier({
                        titre: a.titre, categorie: a.categorie, libelle: d.label,
                        severite: a.severite,
                        montant_dt: a.enjeu_court_terme_dt || a.montant_dt,
                        details: a.action, execution: a.execution,
                      })}>
                        <UserPlus size={12} /> Confier
                      </button>
                    )
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </Carte>

      {confier && (
        <ConfierTache
          origine={confier}
          onClose={() => setConfier(null)}
          onCree={() => void rechargerConfiees()}
        />
      )}
    </Grille>
  );
}
