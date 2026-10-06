"use client";

import {
  Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import {
  CheckCircle2, FileSignature, Info, ListChecks, Percent, RefreshCw,
  ShoppingCart, Target, TrendingDown, UserPlus, Users,
} from "lucide-react";
import ConfierTache from "@/features/taches/ConfierTache";
import PanneauMasque, { BadgeFiltreClients } from "@/shared/ui/PanneauMasque";
import Pourquoi from "@/shared/ui/Pourquoi";
import {
  BLEU, Carte, Grille, INFOBULLE, INK, RangeeTuiles, TuileChiffre, Vide,
  fMoney, tronquer,
} from "@/shared/ui/VisuelKit";
import Pagination from "@/shared/ui/Pagination";
import DevisOuverts, { CasesProtocole, FiltresDevis } from "./DevisOuverts";
import NuageDevis from "./NuageDevis";
import { origineMarge } from "./commercial.regles";
import { type TriMarge, useCommercial } from "./useCommercial";

const NIVEAUX = [
  { min: 0.6, label: "Risque élevé", couleur: BLEU[4] },
  { min: 0.35, label: "Risque modéré", couleur: BLEU[2] },
  { min: 0, label: "Risque faible", couleur: BLEU[0] },
];
const niveau = (p: number) => NIVEAUX.find(n => p >= n.min) || NIVEAUX[2];

const fPct = (v: number | null | undefined) =>
  v == null ? "—" : `${v.toFixed(1).replace(".", ",")} %`;

const ROUGE = "#D03B3B";
const VERT = "#0CA30C";

/**
 * La trajectoire de marge d'un client, sur l'axe du portefeuille.
 *
 * Les quatre repères ne sont pas quatre mesures : ce sont **deux règles et une
 * trajectoire**, sur un seul axe — celui du taux de marge en %.
 *
 *   · le SEUIL et la MÉDIANE sont fixes, identiques pour tous les clients ;
 *   · 12 MOIS et 3 MOIS appartiennent au client, et c'est l'ÉCART ENTRE EUX qui
 *     constitue l'alerte.
 *
 * La version précédente posait quatre traits de 2 px sans graduation ni
 * étiquette : on voyait quatre marques sans savoir laquelle était laquelle, ni
 * dans quel sens lire. Le segment orienté de 12 mois vers 3 mois dit maintenant
 * la seule chose qui déclenche une décision — ça baisse, et de combien.
 *
 * L'échelle est COMMUNE à toutes les lignes (`haut`), sinon deux clients ne se
 * comparent pas.
 */
function Jauge({ actuelle, douze, seuil, mediane, haut }: {
  actuelle: number; douze: number; seuil: number; mediane: number; haut: number;
}) {
  const pc = (v: number) => Math.max(0, Math.min(100, (v / (haut || 1)) * 100));
  const xDouze = pc(douze);
  const xTrois = pc(actuelle);
  const baisse = actuelle < douze;
  const couleur = baisse ? ROUGE : VERT;
  const gauche = Math.min(xDouze, xTrois);
  const largeur = Math.abs(xTrois - xDouze);

  return (
    <div style={{ minWidth: 190, paddingTop: 2 }}>
      <div style={{ position: "relative", height: 26 }}>
        {/* L'axe, neutre : il ne porte aucune information, il la situe. */}
        <div style={{
          position: "absolute", top: 11, left: 0, right: 0, height: 4,
          borderRadius: 2, background: "rgba(26,35,72,0.07)",
        }} />

        {/* Les deux règles, fixes pour tout le portefeuille. */}
        {[{ v: seuil, c: ROUGE, t: `Seuil de surveillance : ${fPct(seuil)}` },
          { v: mediane, c: INK.muted, t: `Médiane du portefeuille : ${fPct(mediane)}` }]
          .map(m => (
            <span key={m.t} title={m.t} style={{
              position: "absolute", left: `${pc(m.v)}%`, top: 3, width: 2, height: 20,
              background: m.c, opacity: 0.75, borderRadius: 1,
              transform: "translateX(-50%)",
            }} />
          ))}

        {/* La trajectoire : le segment porte le sens, la tête porte l'arrivée. */}
        {largeur > 0.4 && (
          <div title={`De ${fPct(douze)} sur 12 mois à ${fPct(actuelle)} sur 3 mois`}
            style={{
              position: "absolute", top: 11.5, left: `${gauche}%`,
              width: `${largeur}%`, height: 3, background: couleur,
              borderRadius: 2, opacity: 0.55,
            }} />
        )}
        {/* Le départ : creux, c'est le passé. */}
        <span title={`Marge sur 12 mois : ${fPct(douze)}`} style={{
          position: "absolute", left: `${xDouze}%`, top: 8,
          width: 9, height: 9, borderRadius: "50%",
          background: "var(--card-bg, #fff)", border: `2px solid ${BLEU[2]}`,
          transform: "translateX(-50%)", boxSizing: "border-box",
        }} />
        {/* L'arrivée : pleine, plus grande, c'est elle qu'on lit. */}
        <span title={`Marge sur 3 mois : ${fPct(actuelle)}`} style={{
          position: "absolute", left: `${xTrois}%`, top: 6.5,
          width: 13, height: 13, borderRadius: "50%", background: couleur,
          // 2 px de surface autour de la pastille : elle reste lisible même
          // posée sur une des deux règles.
          boxShadow: "0 0 0 2px var(--card-bg, #fff)",
          transform: "translateX(-50%)",
        }} />
      </div>

      {/* Les chiffres en clair : une position sur un axe ne se lit pas au pixel. */}
      <div style={{ fontSize: "0.69rem", color: INK.muted, display: "flex",
                    gap: 5, alignItems: "baseline", flexWrap: "wrap" }}>
        <span>12 m <b style={{ color: INK.secondary }}>{fPct(douze)}</b></span>
        <span style={{ color: couleur, fontWeight: 800 }}>{baisse ? "→" : "↗"}</span>
        <span>3 m <b style={{ color: couleur }}>{fPct(actuelle)}</b></span>
        <span style={{ color: couleur, fontWeight: 700 }}>
          ({actuelle - douze >= 0 ? "+" : "\u2212"}
          {Math.abs(actuelle - douze).toFixed(1).replace(".", ",")} pt)
        </span>
      </div>
    </div>
  );
}

/** En-tête cliquable : la liste est longue, le tri est la seule façon d'y entrer. */
function TriMargeBouton({ cle, actif, onTri, label, aide }: {
  cle: TriMarge; actif: TriMarge; onTri: (t: TriMarge) => void;
  label: string; aide: string;
}) {
  const choisi = actif === cle;
  return (
    <button type="button" onClick={() => onTri(cle)}
      title={`Trier par ${aide}`}
      style={{
        background: "none", border: "none", cursor: "pointer", padding: 0,
        font: "inherit", textTransform: "inherit", textAlign: "inherit",
        color: choisi ? INK.primary : INK.muted, fontWeight: choisi ? 800 : 600,
      }}>
      {label}{choisi ? " ↓" : ""}
    </button>
  );
}

/** Ce que les quatre repères veulent dire — deux règles, une trajectoire. */
function LireLaJauge({ seuil, mediane, horizon }: {
  seuil: number; mediane: number; horizon: number;
}) {
  const lignes: { couleur: string; quoi: string; nature: string; dit: string }[] = [
    { couleur: ROUGE, quoi: `Seuil de surveillance (${fPct(seuil)})`,
      nature: "fixe, le même pour tous",
      dit: "en dessous, le client est dans les 20 % les moins rentables du portefeuille" },
    { couleur: INK.muted, quoi: `Médiane du portefeuille (${fPct(mediane)})`,
      nature: "fixe, point de comparaison",
      dit: "la moitié de vos clients font mieux que cette marge" },
    { couleur: BLEU[2], quoi: "Marge sur 12 mois",
      nature: "propre au client",
      dit: "sa marge habituelle — le point de départ" },
    { couleur: ROUGE, quoi: "Marge sur 3 mois",
      nature: "propre au client",
      dit: "sa marge récente — le point d'arrivée, et celui qu'on lit" },
  ];
  return (
    <div style={{
      padding: "12px 14px", borderRadius: 10, marginBottom: 13,
      background: "rgba(47,91,234,0.04)", border: `1px solid ${INK.border}`,
      display: "grid", gap: 9,
    }}>
      <span style={{ fontSize: "0.78rem", fontWeight: 800, color: INK.primary }}>
        Comment lire la colonne « Trajectoire de marge »
      </span>
      <p style={{ margin: 0, fontSize: "0.75rem", color: INK.secondary, lineHeight: 1.6 }}>
        Les quatre repères sont <b>sur un seul axe</b>, celui du taux de marge en
        pourcentage. Deux sont des <b>règles</b> valables pour tout le
        portefeuille, deux appartiennent au <b>client</b> :
      </p>
      <table style={{ borderCollapse: "collapse", fontSize: "0.74rem" }}>
        <tbody>
          {lignes.map(l => (
            <tr key={l.quoi}>
              <td style={{ padding: "3px 8px 3px 0", whiteSpace: "nowrap", verticalAlign: "top" }}>
                <span style={{
                  display: "inline-block", width: 9, height: 9, borderRadius: 2,
                  background: l.couleur, marginRight: 7,
                }} />
                <b style={{ color: INK.primary }}>{l.quoi}</b>
              </td>
              <td style={{ padding: "3px 10px 3px 0", color: INK.muted, whiteSpace: "nowrap", verticalAlign: "top" }}>
                {l.nature}
              </td>
              <td style={{ padding: "3px 0", color: INK.secondary, verticalAlign: "top" }}>
                {l.dit}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p style={{ margin: 0, fontSize: "0.75rem", color: INK.secondary, lineHeight: 1.6 }}>
        <b style={{ color: INK.primary }}>L&apos;alerte, c&apos;est l&apos;écart entre les deux
        derniers</b>, pas leur position absolue. Le segment va du rond creux
        (12 mois) à la pastille pleine (3 mois) : <b style={{ color: ROUGE }}>vers
        la gauche, la marge se dégrade</b> — c&apos;est ce que le modèle prolonge
        sur {horizon} mois pour estimer le risque de passer sous le seuil. Un
        client peut donc être <i>au-dessus</i> de la médiane et tout de même
        signalé, parce qu&apos;il descend vite.
      </p>
    </div>
  );
}

export default function CommercialPanel() {
  const {
    devis, marge, loading, load, d,
    confier, setConfier, confiees, rechargerConfiees,
    tri, setTri, protocoleActif, setProtocoleActif,
    tranche, setTranche, triMarge, setTriMarge,
    devisChoisi, setDevisChoisi,
    pDevis, pMarge,
  } = useCommercial();

  if (loading && !devis) return <div style={{ gridColumn: "span 12" }}><Vide texte="Chargement…" /></div>;
  if (devis?.masque) return <Grille><PanneauMasque motif={devis.motif} /></Grille>;

  const reperes = devis?.reperes;
  const seuilMarge = marge?.seuil_marge_basse_pct ?? 0;
  const medianeMarge = marge?.marge_mediane_portefeuille_pct ?? 0;

  return (
    <Grille>
      {devis?.portee === "clients" && (
        <div style={{ gridColumn: "span 12" }}><BadgeFiltreClients n={devis.n_clients_filtre} /></div>
      )}
      <RangeeTuiles>
        <TuileChiffre icone={<FileSignature size={16} />} label="Devis ouverts"
          valeur={`${devis?.n_devis ?? 0}`}
          detail={`${fMoney(devis?.montant_ouvert_total_dt)} émis sur ${devis?.horizon_maturation_mois ?? 6} mois, pas encore signés`} />
        <TuileChiffre icone={<ShoppingCart size={16} />} label="Ventes probables"
          valeur={fMoney(devis?.esperance_totale_dt)}
          detail="somme des montants pondérés par leur chance de signature" />
        <TuileChiffre icone={<Users size={16} />} label="Clients concernés"
          valeur={`${devis?.n_clients_concernes ?? 0}`}
          detail="établissements avec au moins un devis ouvert" />
        <TuileChiffre icone={<TrendingDown size={16} />} label="Marge menacée"
          valeur={fMoney(d.margeTotale)}
          detail={`sur ${d.margeTop.length} clients, sous ${fPct(seuilMarge)} dans ${marge?.horizon_mois ?? 3} mois`}
          accent="#EC835A" />
      </RangeeTuiles>

      {devis?.servi && (devis.protocoles || []).length > 0 && (
        <Carte span={12} titre="Où passer votre semaine" icone={<ListChecks size={15} />}
          sousTitre="Les ventes probables, réparties par action à mener — un gros devis improbable ne se traite pas comme un petit devis sûr">
          <CasesProtocole protocoles={devis.protocoles!} actif={protocoleActif}
            onActif={setProtocoleActif}
            seuilGros={devis.seuils?.montant_gros_dt}
            seuilChance={devis.seuils?.chance_haute_pct} />
        </Carte>
      )}

      {devis?.servi && (devis.top || []).length ? (
        <Carte span={12} titre="Liste des devis ouverts" icone={<FileSignature size={15} />}
          sousTitre={`${d.devisListe.length} devis retenus sur ${devis.n_devis ?? 0} ouverts — filtrez, puis cliquez sur un en-tête pour trier`}
          droite={<button className="icon-button" onClick={load} title="Actualiser"><RefreshCw size={15} /></button>}>
          {devisChoisi && (
            <div style={{
              display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap",
              padding: "9px 13px", borderRadius: 9, marginBottom: 11,
              background: "rgba(47,91,234,0.06)", border: `1px solid ${BLEU[1]}`,
              fontSize: "0.76rem", color: INK.secondary,
            }}>
              <span>
                Liste réduite au devis <b style={{ color: INK.primary }}>{devisChoisi}</b>,
                choisi dans le nuage. Les deux filtres ci-dessous sont suspendus.
              </span>
              <button type="button" onClick={() => setDevisChoisi(null)}
                style={{
                  background: "none", border: "none", padding: 0, font: "inherit",
                  fontWeight: 700, color: BLEU[3], cursor: "pointer",
                }}>Revenir à la liste complète</button>
            </div>
          )}
          <FiltresDevis
            protocoleActif={protocoleActif} onProtocole={setProtocoleActif}
            protocoles={devis.protocoles || []}
            tranche={tranche} onTranche={setTranche}
            compteTranche={d.compteTranche}
            seuilHaut={d.seuilHaut} seuilBas={d.seuilBas} />
          <DevisOuverts lignes={pDevis.visibles} tri={tri} onTri={setTri}
            confiees={confiees} onConfier={setConfier}
            ageMort={devis.seuils?.age_devis_mort_j} />
          <Pagination p={pDevis} nom="devis" toujours />
        </Carte>
      ) : (
        <Carte titre="Devis ouverts"><Vide texte={devis?.motif || "Aucun devis ouvert."} /></Carte>
      )}

      {reperes?.par_tranche_de_montant?.length ? (
        <Carte span={12} titre="Ce qui se signe vraiment, par tranche de montant"
          icone={<Percent size={15} />}
          sousTitre={`Taux constaté sur les devis émis il y a plus de ${reperes.maturation_mois ?? 6} mois`}>
          <ResponsiveContainer width="100%" height={230}>
            <BarChart data={reperes.par_tranche_de_montant}
              margin={{ top: 8, right: 14, left: 0, bottom: 0 }} barCategoryGap={18}>
              <CartesianGrid stroke={INK.grid} vertical={false} />
              <XAxis dataKey="tranche" tick={{ fill: INK.secondary, fontSize: 11 }}
                axisLine={false} tickLine={false} />
              <YAxis unit=" %" tick={{ fill: INK.muted, fontSize: 10 }}
                axisLine={false} tickLine={false} width={40} />
              <Tooltip cursor={{ fill: "rgba(47,91,234,0.05)" }}
                content={({ active, payload }) => {
                  if (!active || !payload?.length) return null;
                  const t = payload[0].payload as NonNullable<typeof reperes.par_tranche_de_montant>[number];
                  return (
                    <div style={INFOBULLE}>
                      <b>{t.tranche}</b>
                      <div>{t.n_signes} signés sur {t.n_devis} devis</div>
                      <div>Taux : <b>{fPct(t.taux_pct)}</b></div>
                      <div>{fMoney(t.montant_dt)} proposés au total</div>
                    </div>
                  );
                }} />
              <Bar dataKey="taux_pct" barSize={44} radius={[5, 5, 0, 0]}
                label={{ position: "top", formatter: (v: unknown) => `${Number(v).toFixed(1)} %`,
                  fill: INK.secondary, fontSize: 11 }}>
                {reperes.par_tranche_de_montant.map((t, i) => (
                  <Cell key={i} fill={(t.taux_pct ?? 0) >= 10 ? "#0CA30C"
                    : (t.taux_pct ?? 0) >= 3 ? "#E0A10F" : "#D03B3B"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <div style={{
            marginTop: 11, padding: "11px 13px", borderRadius: 10,
            background: "rgba(47,91,234,0.05)", border: `1px solid ${INK.border}`,
            fontSize: "0.75rem", color: INK.secondary, lineHeight: 1.55,
            display: "flex", gap: 9,
          }}>
            <Info size={15} style={{ color: BLEU[3], flexShrink: 0, marginTop: 1 }} />
            <span>{reperes.lecture}</span>
          </div>
          {reperes.non_jugeables && (
            <p className="muted-note" style={{ marginTop: 8, fontSize: "0.71rem" }}>
              {reperes.non_jugeables.n_devis} devis récents ({fMoney(reperes.non_jugeables.montant_dt)})
              sont exclus de ce taux : {reperes.non_jugeables.motif}
            </p>
          )}
        </Carte>
      ) : null}

      {devis?.servi && d.devisTop.length ? (
        <Carte span={12} titre="Montant et chance de signature"
          icone={<Target size={15} />}
          sousTitre={"Chaque point est un devis. Les deux pointillés sont les seuils "
            + "qui définissent les quatre actions : un point se lit d'abord par son quadrant"}>
          <NuageDevis points={d.devisTop}
            seuilGros={devis.seuils?.montant_gros_dt ?? 20000}
            seuilChance={devis.seuils?.chance_haute_pct ?? 25}
            calibration={devis.calibration}
            onChoisir={setDevisChoisi} choisi={devisChoisi} />
        </Carte>
      ) : null}

      {marge?.servi && d.margeTop.length ? (
        <Carte span={12} titre="Clients dont la rentabilité va baisser" icone={<Percent size={15} />}
          sousTitre={marge.menace_definition}>
          <div style={{
            padding: "11px 13px", borderRadius: 10, marginBottom: 13,
            background: "rgba(236,131,90,0.07)", border: "1px solid rgba(236,131,90,0.22)",
            fontSize: "0.75rem", color: INK.secondary, lineHeight: 1.55,
            display: "grid", gap: 6,
          }}>
            <span><b style={{ color: INK.primary }}>Menacée par rapport à quoi ?</b> {marge.menace_vis_a_vis_de_qui}</span>
            <span><b style={{ color: INK.primary }}>Pourquoi ça baisse ?</b> {marge.cause_principale}</span>
            <span><b style={{ color: INK.primary }}>Que vaut le montant ?</b> {marge.marge_en_jeu_definition}</span>
          </div>

          <LireLaJauge seuil={seuilMarge} mediane={medianeMarge}
            horizon={marge.horizon_mois ?? 3} />

          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.79rem" }}>
              <thead>
                <tr style={{ textAlign: "left", color: INK.muted, fontSize: "0.7rem" }}>
                  <th style={{ padding: "6px 8px" }}>
                    <TriMargeBouton cle="ca" actif={triMarge} onTri={setTriMarge}
                      label="Client" aide="chiffre d'affaires sur 12 mois" />
                  </th>
                  <th style={{ padding: "6px 8px", minWidth: 195 }}>
                    <TriMargeBouton cle="ecart" actif={triMarge} onTri={setTriMarge}
                      label="Trajectoire de marge" aide="écart au seuil de surveillance" />
                  </th>
                  <th style={{ padding: "6px 8px", textAlign: "right" }}>Taux 3 mois</th>
                  <th style={{ padding: "6px 8px", textAlign: "right" }}>Part équipement</th>
                  <th style={{ padding: "6px 8px" }}>
                    <TriMargeBouton cle="probabilite" actif={triMarge} onTri={setTriMarge}
                      label="Risque" aide="probabilité de passer sous le seuil" />
                  </th>
                  <th style={{ padding: "6px 8px", textAlign: "right" }}>
                    <TriMargeBouton cle="enjeu" actif={triMarge} onTri={setTriMarge}
                      label="Marge en jeu" aide="montant de marge menacée" />
                  </th>
                  <th style={{ padding: "6px 8px", textAlign: "right" }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {pMarge.visibles.map(x => {
                  const n = niveau(x.probabilite);
                  const origine = origineMarge(x);
                  const deja = confiees[origine.titre];
                  return (
                    <tr key={x.client} style={{ borderTop: `1px solid ${INK.grid}` }}>
                      <td style={{ padding: "8px" }}>
                        <div style={{ fontWeight: 600, color: INK.primary }} title={x.nom || x.client}>
                          {tronquer(x.nom || x.client, 28)}
                        </div>
                        <div style={{ fontSize: "0.68rem", color: INK.muted }}>
                          {fMoney(x.ca_12m_dt)} sur 12 mois
                        </div>
                        {!!x.raisons?.length && (
                          <div style={{ marginTop: 4 }}>
                            <Pourquoi raisons={x.raisons} titre={`Pourquoi ${x.nom || x.client}`} />
                          </div>
                        )}
                      </td>
                      <td style={{ padding: "8px" }}>
                        <Jauge actuelle={x.marge_actuelle_pct} douze={x.marge_12m_pct}
                          seuil={x.seuil_pct ?? seuilMarge}
                          mediane={x.mediane_pct ?? medianeMarge}
                          haut={d.hautMarge} />
                      </td>
                      <td style={{
                        padding: "8px", textAlign: "right", fontWeight: 700,
                        color: x.deja_sous_le_seuil ? "#D03B3B" : INK.primary,
                      }}>
                        {fPct(x.marge_actuelle_pct)}
                        {x.deja_sous_le_seuil && (
                          <em style={{ fontStyle: "normal", display: "block", fontSize: "0.66rem", color: "#D03B3B" }}>
                            déjà sous le seuil
                          </em>
                        )}
                      </td>
                      <td style={{ padding: "8px", textAlign: "right", color: INK.secondary }}>
                        {x.part_equipement_pct == null ? "—" : `${x.part_equipement_pct.toFixed(0)} %`}
                      </td>
                      <td style={{ padding: "8px" }}>
                        <span style={{
                          background: `${n.couleur}44`, color: INK.primary, borderRadius: 6,
                          padding: "3px 8px", fontSize: "0.7rem", fontWeight: 700, whiteSpace: "nowrap",
                        }}>{n.label}</span>
                      </td>
                      <td style={{ padding: "8px", textAlign: "right", fontWeight: 800, color: INK.primary }}>
                        {fMoney(x.marge_en_jeu_dt)}
                      </td>
                      <td style={{ padding: "8px", textAlign: "right" }}>
                        {deja ? (
                          <span className="vk-confiee"
                            title={`Confiée à ${deja.assigne_nom || "un responsable à désigner"}`}>
                            <CheckCircle2 size={12} /> Confiée
                          </span>
                        ) : (
                          <button className="vk-bouton-mini" onClick={() => setConfier(origine)}>
                            <UserPlus size={12} /> Confier
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <Pagination p={pMarge} nom="clients" toujours />
        </Carte>
      ) : (
        <Carte titre="Rentabilité des clients"><Vide texte={marge?.motif || "Aucun client concerné."} /></Carte>
      )}

      {/* « Produits les plus demandés » et « Quoi proposer, à qui » ont rejoint
          l'onglet Produits & achats : ils parlent de catalogue et d'adoption de
          références, pas de pièces commerciales en cours. */}

      {confier && (
        <ConfierTache origine={confier} onClose={() => setConfier(null)}
          onCree={() => void rechargerConfiees()} />
      )}
    </Grille>
  );
}
