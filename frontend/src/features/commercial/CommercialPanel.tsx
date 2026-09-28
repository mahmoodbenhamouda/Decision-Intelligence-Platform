"use client";

/**
 * CommercialPanel — onglet « Devis & marge ».
 *
 * Trois questions de dirigeant, trois visuels :
 *   · quels devis relancer ?            → barres des ventes probables + nuage montant / chance ;
 *   · quels clients deviennent moins rentables ? → barres de marge menacée, par niveau de risque ;
 *   · quels produits proposer ?         → produits les plus recommandés + cartes client.
 *
 * Aucun terme technique à l'écran : ni méthode, ni seuil, ni score de modèle.
 */

import {
  Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Scatter, ScatterChart,
  Tooltip, XAxis, YAxis, ZAxis,
} from "recharts";
import {
  CheckCircle2, FileSignature, Package, Percent, RefreshCw, ShoppingCart,
  TrendingDown, UserPlus,
} from "lucide-react";
import ConfierTache, { BadgeConfiee } from "@/features/taches/ConfierTache";
import Pourquoi, { type Raison } from "@/shared/ui/Pourquoi";
import {
  BLEU, Carte, Grille, INFOBULLE, INK, Legende, RangeeTuiles, TuileChiffre, Vide,
  fAxe, fMoney, tronquer,
} from "@/shared/ui/VisuelKit";
import { origineDevis, origineReco } from "./commercial.regles";
import type { MargeLigne } from "./commercial.types";
import { useCommercial } from "./useCommercial";

const NIVEAUX = [
  { min: 0.6, label: "Risque élevé", couleur: BLEU[4] },
  { min: 0.35, label: "Risque modéré", couleur: BLEU[2] },
  { min: 0, label: "Risque faible", couleur: BLEU[0] },
];
const niveau = (p: number) => NIVEAUX.find(n => p >= n.min) || NIVEAUX[2];

/** Justifications des premières lignes d'un classement, sous le graphe.
 *  Le graphe montre QUI est en tête ; ce bloc dit POURQUOI, sans quitter l'écran. */
function Justifications({ lignes }: {
  lignes: { cle: string; nom: string; raisons?: Raison[] }[];
}) {
  const avecRaisons = lignes.filter(l => (l.raisons || []).length);
  if (!avecRaisons.length) return null;
  return (
    <div style={{ marginTop: 12, borderTop: `1px solid ${INK.border}`, paddingTop: 10 }}>
      <div style={{ fontSize: "0.72rem", fontWeight: 700, color: INK.muted, marginBottom: 7 }}>
        Pourquoi ces trois-là
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
        {avecRaisons.slice(0, 3).map(l => (
          <div key={l.cle} style={{ display: "flex", alignItems: "center", gap: 9, flexWrap: "wrap" }}>
            <span style={{ fontSize: "0.8rem", fontWeight: 700, color: INK.primary }}>
              {tronquer(l.nom, 26)}
            </span>
            <Pourquoi raisons={l.raisons} titre={`Pourquoi ${l.nom}`} />
          </div>
        ))}
      </div>
    </div>
  );
}
const fDate = (d?: string) => (d ? new Date(d).toLocaleDateString("fr-FR") : "—");

export default function CommercialPanel() {
  const {
    devis, marge, reco, loading, load, d,
    confier, setConfier, confiees, rechargerConfiees,
  } = useCommercial();

  if (loading && !devis) return <div style={{ gridColumn: "span 12" }}><Vide texte="Chargement…" /></div>;

  return (
    <Grille>
      {/* ── Chiffres clés ────────────────────────────────────────────────── */}
      <RangeeTuiles>
        <TuileChiffre icone={<FileSignature size={16} />} label="Devis ouverts"
          valeur={`${devis?.n_devis ?? 0}`} detail="émis ces 6 derniers mois, pas encore signés" />
        <TuileChiffre icone={<ShoppingCart size={16} />} label="Ventes probables"
          valeur={fMoney(devis?.esperance_totale_dt)} detail="si les devis suivent leur tendance" />
        <TuileChiffre icone={<TrendingDown size={16} />} label="Marge menacée"
          valeur={fMoney(d.margeTotale)} detail={`sur ${d.margeTop.length} clients, dans les 3 mois`} accent="#EC835A" />
        <TuileChiffre icone={<Package size={16} />} label="Potentiel produits"
          valeur={fMoney(d.potentiel)} detail={`par an, sur ${d.clientsReco.length} clients`} />
      </RangeeTuiles>

      {/* ── Devis ────────────────────────────────────────────────────────── */}
      {devis?.servi && d.devisTop.length ? (
        <>
          <Carte span={7} titre="Devis à relancer en priorité" icone={<FileSignature size={15} />}
            sousTitre="Ventes probables par devis : montant du devis pondéré par sa chance de signature"
            droite={<button className="icon-button" onClick={load} title="Actualiser"><RefreshCw size={15} /></button>}>
            <ResponsiveContainer width="100%" height={380}>
              <BarChart layout="vertical" data={d.devisTop.slice(0, 10)} margin={{ top: 0, right: 64, left: 0, bottom: 0 }} barCategoryGap={8}>
                <CartesianGrid stroke={INK.grid} horizontal={false} />
                <XAxis type="number" tickFormatter={fAxe} tick={{ fill: INK.secondary, fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis type="category" dataKey="nomCourt" width={170} tick={{ fill: INK.primary, fontSize: 11.5 }} axisLine={false} tickLine={false} />
                <Tooltip cursor={{ fill: "rgba(47,91,234,0.05)" }} contentStyle={INFOBULLE}
                  content={({ active, payload }) => {
                    if (!active || !payload?.length) return null;
                    const x = payload[0].payload as (typeof d.devisTop)[number];
                    return (
                      <div style={INFOBULLE}>
                        <b>{x.nom || x.client}</b>
                        <div>Devis de {fMoney(x.montant_ht_dt)} émis le {fDate(x.date)}</div>
                        <div>Chance de signature : {x.chance} %</div>
                        <div>Ventes probables : <b>{fMoney(x.esperance_dt)}</b></div>
                      </div>
                    );
                  }} />
                <Bar dataKey="esperance_dt" fill={BLEU[3]} barSize={16} radius={[0, 4, 4, 0]}
                  label={{ position: "right", formatter: (v: unknown) => fMoney(Number(v)), fill: INK.secondary, fontSize: 11 }} />
              </BarChart>
            </ResponsiveContainer>
            {/* Relance en un geste sur les trois premiers : le graphe désigne,
                le bouton engage. */}
            <div style={{ display: "flex", flexWrap: "wrap", gap: 7, marginTop: 10, alignItems: "center" }}>
              <span style={{ fontSize: "0.72rem", color: INK.muted, fontWeight: 700 }}>Relancer :</span>
              {d.devisTop.slice(0, 3).map(x => {
                const deja = confiees[origineDevis(x).titre];
                return deja ? (
                  <span key={x.piece_no} className="vk-confiee"
                    title={`${x.nom || x.client} — confiée à ${deja.assigne_nom || "un responsable à désigner"}`}>
                    <CheckCircle2 size={12} /> {tronquer(x.nom || x.client, 18)}
                  </span>
                ) : (
                  <button key={x.piece_no} className="vk-bouton-mini"
                    onClick={() => setConfier(origineDevis(x))}>
                    <UserPlus size={12} /> {tronquer(x.nom || x.client, 18)}
                  </button>
                );
              })}
            </div>
            <Justifications
              lignes={d.devisTop.slice(0, 3).map(x => ({
                cle: x.piece_no, nom: x.nom || x.client, raisons: x.raisons }))} />
          </Carte>

          <Carte span={5} titre="Montant et chance de signature" sousTitre="Chaque point est un devis : en haut à droite, les plus intéressants">
            <ResponsiveContainer width="100%" height={380}>
              <ScatterChart margin={{ top: 10, right: 16, left: 0, bottom: 10 }}>
                <CartesianGrid stroke={INK.grid} />
                <XAxis type="number" dataKey="montant_ht_dt" name="Montant" tickFormatter={fAxe}
                  tick={{ fill: INK.secondary, fontSize: 11 }} axisLine={false} tickLine={false}
                  label={{ value: "Montant du devis (DT)", position: "insideBottom", offset: -6, fill: INK.muted, fontSize: 11 }} />
                <YAxis type="number" dataKey="chance" name="Chance" unit=" %" tick={{ fill: INK.secondary, fontSize: 11 }}
                  axisLine={false} tickLine={false} width={48} />
                <ZAxis type="number" dataKey="esperance_dt" range={[60, 420]} />
                <Tooltip cursor={{ strokeDasharray: "3 3" }}
                  content={({ active, payload }) => {
                    if (!active || !payload?.length) return null;
                    const x = payload[0].payload as (typeof d.devisTop)[number];
                    return (
                      <div style={INFOBULLE}>
                        <b>{x.nom || x.client}</b>
                        <div>{fMoney(x.montant_ht_dt)} · chance {x.chance} %</div>
                      </div>
                    );
                  }} />
                <Scatter data={d.devisTop} fill={BLEU[3]} fillOpacity={0.72} stroke="#fff" strokeWidth={2} />
              </ScatterChart>
            </ResponsiveContainer>
          </Carte>
        </>
      ) : (
        <Carte titre="Devis à relancer"><Vide texte={devis?.motif || "Aucun devis ouvert."} /></Carte>
      )}

      {/* ── Rentabilité ──────────────────────────────────────────────────── */}
      {marge?.servi && d.margeTop.length ? (
        <Carte titre="Clients dont la rentabilité va baisser" icone={<Percent size={15} />}
          sousTitre="Marge menacée dans les 3 prochains mois — la couleur indique le niveau de risque">
          <ResponsiveContainer width="100%" height={Math.max(280, d.margeTop.length * 30)}>
            <BarChart layout="vertical" data={d.margeTop} margin={{ top: 0, right: 64, left: 0, bottom: 0 }} barCategoryGap={6}>
              <CartesianGrid stroke={INK.grid} horizontal={false} />
              <XAxis type="number" tickFormatter={fAxe} tick={{ fill: INK.secondary, fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis type="category" dataKey="nomCourt" width={190} tick={{ fill: INK.primary, fontSize: 11.5 }} axisLine={false} tickLine={false} />
              <Tooltip cursor={{ fill: "rgba(47,91,234,0.05)" }}
                content={({ active, payload }) => {
                  if (!active || !payload?.length) return null;
                  const x = payload[0].payload as MargeLigne;
                  return (
                    <div style={INFOBULLE}>
                      <b>{x.nom || x.client}</b>
                      <div>Marge des 3 derniers mois : {x.marge_actuelle_pct.toFixed(1)} %</div>
                      <div>Marge sur 12 mois : {x.marge_12m_pct.toFixed(1)} %</div>
                      <div>{niveau(x.probabilite).label} · <b>{fMoney(x.marge_en_jeu_dt)}</b> menacés</div>
                    </div>
                  );
                }} />
              <Bar dataKey="marge_en_jeu_dt" barSize={16} radius={[0, 4, 4, 0]}
                label={{ position: "right", formatter: (v: unknown) => fMoney(Number(v)), fill: INK.secondary, fontSize: 11 }}>
                {d.margeTop.map((x, i) => <Cell key={i} fill={niveau(x.probabilite).couleur} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <Legende items={NIVEAUX.map(n => ({ couleur: n.couleur, label: n.label }))} />
          <Justifications
            lignes={d.margeTop.slice(0, 3).map(x => ({
              cle: x.client, nom: x.nom || x.client, raisons: x.raisons }))} />
        </Carte>
      ) : (
        <Carte titre="Rentabilité des clients"><Vide texte={marge?.motif || "Aucun client concerné."} /></Carte>
      )}

      {/* ── Produits à proposer ──────────────────────────────────────────── */}
      {reco?.servi && d.clientsReco.length ? (
        <>
          <Carte span={5} titre="Produits les plus demandés à venir" icone={<Package size={15} />}
            sousTitre={`Nombre de clients à qui le proposer dans les ${reco.horizon_mois ?? 6} mois`}>
            <ResponsiveContainer width="100%" height={Math.max(260, d.produits.length * 38)}>
              <BarChart layout="vertical" data={d.produits} margin={{ top: 0, right: 36, left: 0, bottom: 0 }} barCategoryGap={8}>
                <XAxis type="number" hide allowDecimals={false} />
                <YAxis type="category" dataKey="produit" width={190} tick={{ fill: INK.primary, fontSize: 11.5 }} axisLine={false} tickLine={false} />
                <Tooltip cursor={{ fill: "rgba(47,91,234,0.05)" }} contentStyle={INFOBULLE}
                  formatter={(v) => [`${v} client(s)`, "À proposer à"]}
                  labelFormatter={(_, p) => (p?.[0]?.payload as { complet?: string })?.complet || ""} />
                <Bar dataKey="n" fill={BLEU[3]} barSize={16} radius={[0, 4, 4, 0]}
                  label={{ position: "right", fill: INK.secondary, fontSize: 11 }} />
              </BarChart>
            </ResponsiveContainer>
          </Carte>

          <Carte span={7} titre="Quoi proposer, à qui" icone={<ShoppingCart size={15} />}
            sousTitre="Produits que ces clients n'ont jamais achetés et qu'ils sont susceptibles d'adopter">
            <div style={{ display: "grid", gap: 10, gridTemplateColumns: "repeat(auto-fill, minmax(230px, 1fr))" }}>
              {d.clientsReco.slice(0, 8).map(c => (
                <div key={c.client} className="vk-carte-action">
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "baseline" }}>
                    <span style={{ fontWeight: 800, color: INK.primary, fontSize: "0.86rem" }} title={c.nom}>{tronquer(c.nom, 26)}</span>
                    <span style={{ fontWeight: 800, color: INK.primary, fontSize: "0.86rem", whiteSpace: "nowrap" }}>{fMoney(c.potentiel_top3_dt)}</span>
                  </div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                    {c.produits.map(p => <span key={p.designation} className="vk-chip" title={p.designation}>{tronquer(p.designation, 26)}</span>)}
                  </div>
                  {/* Pourquoi ce produit chez ce client : adoption chez les
                      établissements comparables, nombre d'acheteurs, montant annuel. */}
                  <Pourquoi raisons={c.produits[0]?.raisons}
                    libelle="Pourquoi ce produit ?"
                    titre={`Pourquoi ${tronquer(c.produits[0]?.designation || "", 30)}`} />
                  {/* Une proposition qui reste à l'écran ne rapporte rien : elle
                      part ici en tâche, avec les produits en consigne. */}
                  {confiees[origineReco(c).titre] ? (
                    <BadgeConfiee info={confiees[origineReco(c).titre]} />
                  ) : (
                    <button className="vk-bouton-mini" style={{ alignSelf: "flex-start" }}
                      onClick={() => setConfier(origineReco(c))}>
                      <UserPlus size={12} /> Confier
                    </button>
                  )}
                </div>
              ))}
            </div>
            <p className="muted-note" style={{ marginTop: 10, fontSize: "0.72rem" }}>
              Le montant indique ce que dépensent en moyenne par an les clients qui achètent déjà ces produits.
            </p>
          </Carte>
        </>
      ) : (
        <Carte titre="Produits à proposer"><Vide texte={reco?.motif || "Aucune recommandation disponible."} /></Carte>
      )}

      {confier && (
        <ConfierTache origine={confier} onClose={() => setConfier(null)}
          onCree={() => void rechargerConfiees()} />
      )}
    </Grille>
  );
}
