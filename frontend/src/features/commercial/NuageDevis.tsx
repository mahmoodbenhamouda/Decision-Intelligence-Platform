"use client";

import { useMemo, useState } from "react";
import {
  CartesianGrid, Cell, Line, LineChart, ReferenceLine, ResponsiveContainer,
  Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from "recharts";
import { Grid3x3, LineChart as LineIcon, ScatterChart as ScatterIcon } from "lucide-react";
import { BLEU, INFOBULLE, INK, fAxe, fMoney } from "@/shared/ui/VisuelKit";
import { PROTOCOLE_STYLE } from "./commercial.regles";
import type { CalibrationDevis, CodeProtocole, DevisLigne } from "./commercial.types";

type Point = DevisLigne & { nomCourt: string; chance: number };

type Vue = "nuage" | "densite" | "calibration";

/** Les tranches de montant du graphique voisin : les deux cartes s'alignent. */
const TRANCHES = [
  { cle: "toutes", label: "Tous les montants", min: 0, max: Infinity },
  { cle: "petits", label: "moins de 5 K", min: 0, max: 5_000 },
  { cle: "moyens", label: "5 à 20 K", min: 5_000, max: 20_000 },
  { cle: "gros", label: "20 à 100 K", min: 20_000, max: 100_000 },
  { cle: "tres_gros", label: "plus de 100 K", min: 100_000, max: Infinity },
] as const;

type CleTranche = (typeof TRANCHES)[number]["cle"];

const fPt = (v: number) => `${v.toFixed(1).replace(".", ",")} pt`;

const ONGLET = (actif: boolean) => ({
  display: "inline-flex", alignItems: "center", gap: 5,
  background: actif ? "rgba(47,91,234,0.08)" : "none",
  border: `1px solid ${actif ? BLEU[3] : INK.border}`,
  borderRadius: 7, padding: "4px 10px", cursor: "pointer",
  font: "inherit", fontSize: "0.73rem", fontWeight: actif ? 800 : 600,
  color: actif ? BLEU[3] : INK.secondary,
} as const);

/* ------------------------------------------------------------------ */
/* Les quadrants : la lecture du nuage, chiffrée                       */
/* ------------------------------------------------------------------ */

/**
 * Les deux seuils du backend découpent le plan en quatre, et ces quatre zones
 * SONT les quatre protocoles de « Où passer votre semaine ».
 *
 * C'est ce qui rend le nuage lisible : la position d'un point détermine
 * l'action à mener. La couleur ne fait que la rappeler — l'identité ne repose
 * donc jamais sur elle seule, ce que la seule légende ne suffirait pas à
 * garantir avec un gris volontairement discret pour « sans action ».
 */
function quadrants(pts: Point[], seuilGros: number, seuilChance: number) {
  const zone = (p: Point): CodeProtocole => {
    const gros = p.montant_ht_dt >= seuilGros;
    const sur = p.chance >= seuilChance;
    if (gros && sur) return "appeler";
    if (gros && !sur) return "appel_offres";
    if (!gros && sur) return "traiter_en_lot";
    return "laisser";
  };
  const def: { code: CodeProtocole; ou: string }[] = [
    { code: "appeler", ou: "gros montant, chance haute" },
    { code: "traiter_en_lot", ou: "petit montant, chance haute" },
    { code: "appel_offres", ou: "gros montant, chance basse" },
    { code: "laisser", ou: "petit montant, chance basse" },
  ];
  return def.map(d => {
    const dedans = pts.filter(p => zone(p) === d.code);
    return {
      ...d,
      n: dedans.length,
      esperance: dedans.reduce((s, p) => s + p.esperance_dt, 0),
      part: pts.length ? (dedans.length / pts.length) * 100 : 0,
    };
  });
}

/* ------------------------------------------------------------------ */
/* Vue densité : aucun point ne peut être caché par un autre           */
/* ------------------------------------------------------------------ */

const PAS_CHANCE = 10;   // tranches de 10 points de chance
const N_COL = 6;         // six colonnes de montant, en échelle log

/**
 * Le nuage ment par omission : à 300 devis, les points se recouvrent et une
 * zone dense se lit comme un point unique. Cette vue compte les devis par
 * case — elle ne peut donc rien cacher, et c'est la réponse directe à « je ne
 * vois pas tous les points ».
 *
 * La rampe est SÉQUENTIELLE : une seule teinte, du clair au foncé, parce que
 * la grandeur encodée est un effectif. Chaque case porte aussi son compte en
 * clair : la couleur situe, le chiffre affirme.
 */
function Densite({ pts }: { pts: Point[] }) {
  const { cases, maxN, bornes } = useMemo(() => {
    const montants = pts.map(p => p.montant_ht_dt).filter(m => m > 0);
    const min = Math.min(...montants, 1);
    const max = Math.max(...montants, 10);
    const lMin = Math.log10(min);
    const lMax = Math.log10(max) || 1;
    const pas = (lMax - lMin) / N_COL || 1;
    const col = (m: number) =>
      Math.min(N_COL - 1, Math.max(0, Math.floor((Math.log10(Math.max(m, min)) - lMin) / pas)));

    const grille = new Map<string, { n: number; esperance: number }>();
    for (const p of pts) {
      const c = col(p.montant_ht_dt);
      const l = Math.min(Math.floor(p.chance / PAS_CHANCE), 100 / PAS_CHANCE - 1);
      const k = `${l}|${c}`;
      const prec = grille.get(k) || { n: 0, esperance: 0 };
      grille.set(k, { n: prec.n + 1, esperance: prec.esperance + p.esperance_dt });
    }
    const bornes = Array.from({ length: N_COL + 1 }, (_, i) => 10 ** (lMin + i * pas));
    return {
      cases: grille,
      maxN: Math.max(1, ...Array.from(grille.values(), v => v.n)),
      bornes,
    };
  }, [pts]);

  // Quatre pas d'une seule teinte : la plus claire reste lisible parce que la
  // case porte son effectif écrit.
  const teinte = (n: number) => {
    if (n === 0) return "transparent";
    const r = n / maxN;
    return r > 0.66 ? BLEU[4] : r > 0.33 ? BLEU[3] : r > 0.12 ? BLEU[2] : BLEU[1];
  };
  const encre = (n: number) => (n / maxN > 0.33 ? "#fff" : INK.primary);

  const lignes = Array.from({ length: 100 / PAS_CHANCE }, (_, i) => i).reverse();

  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ borderCollapse: "separate", borderSpacing: 2, fontSize: "0.68rem" }}>
        <tbody>
          {lignes.map(l => (
            <tr key={l}>
              <th style={{
                padding: "0 7px 0 0", textAlign: "right", color: INK.muted,
                fontWeight: 600, whiteSpace: "nowrap",
              }}>
                {l * PAS_CHANCE}&ndash;{(l + 1) * PAS_CHANCE} %
              </th>
              {Array.from({ length: N_COL }, (_, c) => {
                const v = cases.get(`${l}|${c}`);
                const n = v?.n ?? 0;
                return (
                  <td key={c}
                    title={n === 0 ? "aucun devis dans cette case"
                      : `${n} devis entre ${fMoney(bornes[c])} et ${fMoney(bornes[c + 1])}, `
                        + `chance ${l * PAS_CHANCE}–${(l + 1) * PAS_CHANCE} % — `
                        + `${fMoney(v?.esperance)} de ventes probables`}
                    style={{
                      width: 62, height: 27, textAlign: "center", borderRadius: 4,
                      background: teinte(n), color: encre(n), fontWeight: n ? 700 : 400,
                      border: n === 0 ? `1px dashed ${INK.grid}` : "none",
                    }}>
                    {n || ""}
                  </td>
                );
              })}
            </tr>
          ))}
          <tr>
            <th />
            {Array.from({ length: N_COL }, (_, c) => (
              <th key={c} style={{ color: INK.muted, fontWeight: 600, paddingTop: 3 }}>
                {fAxe(bornes[c])}
              </th>
            ))}
          </tr>
        </tbody>
      </table>
      <p className="muted-note" style={{ fontSize: "0.71rem", marginTop: 7 }}>
        Chaque case compte les devis ; la colonne suit une échelle
        <b> logarithmique</b> de montant, comme le nuage. Aucun devis n&apos;est
        caché par un autre, ce qui est impossible à garantir sur un nuage de
        points.
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Vue calibration : la probabilité annoncée vaut-elle ce qu'elle dit ?*/
/* ------------------------------------------------------------------ */

/**
 * La seule vue qui juge le MODÈLE et non les devis.
 *
 * L'AUC dit l'ordre. Elle ne dit rien de la valeur annoncée — un modèle qui
 * prédirait 3 % partout où le taux réel est 30 % aurait la même AUC, et
 * l'espérance en dinars affichée partout ailleurs serait dix fois trop basse.
 * Cette courbe est donc ce qui autorise à écrire « ventes probables » en dinars.
 */
function Calibration({ cal }: { cal: CalibrationDevis }) {
  if (!cal.applicable || !cal.par_groupe?.length) {
    return (
      <p className="muted-note" style={{ padding: "22px 4px", fontSize: "0.76rem", lineHeight: 1.6 }}>
        Courbe de calibration indisponible : {cal.motif || "non mesurée"}.
        <br />
        Elle ne se calcule pas à la demande — la mesurer honnêtement exige le
        découpage hors période de l&apos;évaluation. Relancez{" "}
        <code>python -m ml_engine.analytics.conversion_devis</code>.
      </p>
    );
  }

  const pts = cal.par_groupe;
  const haut = Math.ceil(Math.max(
    ...pts.map(g => Math.max(g.probabilite_predite_moyenne_pct, g.taux_observe_pct)), 5) / 5) * 5;
  const optimiste = (cal.biais_pt ?? 0) > 0;

  return (
    <>
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginBottom: 9 }}>
        <span style={{ fontSize: "0.73rem", color: INK.secondary }}>
          Écart moyen (ECE) : <b style={{ color: INK.primary }}>{fPt(cal.ece_pt ?? 0)}</b>
        </span>
        <span style={{ fontSize: "0.73rem", color: INK.secondary }}>
          Biais : <b style={{ color: optimiste ? "#D03B3B" : "#0CA30C" }}>
            {(cal.biais_pt ?? 0) >= 0 ? "+" : "−"}{fPt(Math.abs(cal.biais_pt ?? 0))}
          </b>{" "}
          <em style={{ fontStyle: "normal", color: INK.muted }}>— {cal.sens_du_biais}</em>
        </span>
        <span style={{ fontSize: "0.73rem", color: INK.muted }}>
          sur {cal.n_devis} devis du test, en {cal.n_groupes} groupes
        </span>
      </div>

      <ResponsiveContainer width="100%" height={236}>
        <LineChart data={pts} margin={{ top: 8, right: 16, left: 0, bottom: 16 }}>
          <CartesianGrid stroke={INK.grid} />
          <XAxis type="number" dataKey="probabilite_predite_moyenne_pct"
            domain={[0, haut]} unit=" %"
            tick={{ fill: INK.secondary, fontSize: 11 }} axisLine={false} tickLine={false}
            label={{ value: "Chance annoncée par le modèle", position: "insideBottom",
                     offset: -10, fill: INK.muted, fontSize: 11 }} />
          <YAxis type="number" domain={[0, haut]} unit=" %"
            tick={{ fill: INK.secondary, fontSize: 11 }} axisLine={false} tickLine={false}
            width={46}
            label={{ value: "Taux signé observé", angle: -90, position: "insideLeft",
                     fill: INK.muted, fontSize: 11 }} />
          <Tooltip content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const g = payload[0].payload as (typeof pts)[number];
            return (
              <div style={INFOBULLE}>
                <b>Groupe {g.groupe} sur {cal.n_groupes}</b>
                <div>Chance annoncée de {g.probabilite_min_pct} à {g.probabilite_max_pct} %</div>
                <div>Annoncé en moyenne : <b>{g.probabilite_predite_moyenne_pct} %</b></div>
                <div>Réellement signés : <b>{g.n_signes} sur {g.n_devis}</b> = {g.taux_observe_pct} %</div>
                <div style={{ color: g.ecart_pt > 0 ? "#D03B3B" : "#0CA30C" }}>
                  Écart : {g.ecart_pt > 0 ? "+" : ""}{g.ecart_pt} pt
                </div>
              </div>
            );
          }} />
          {/* La diagonale est une RÉFÉRENCE, pas une série : une calibration
              parfaite y pose tous ses points. */}
          <ReferenceLine segment={[{ x: 0, y: 0 }, { x: haut, y: haut }]}
            stroke={INK.muted} strokeDasharray="4 4" strokeWidth={2} />
          <Line type="monotone" dataKey="taux_observe_pct" stroke={BLEU[3]}
            strokeWidth={2} dot={{ r: 4, fill: BLEU[3], stroke: "#fff", strokeWidth: 2 }}
            activeDot={{ r: 6 }} />
        </LineChart>
      </ResponsiveContainer>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 14, marginTop: 6 }}>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: "0.72rem", color: INK.secondary }}>
          <span style={{ width: 14, height: 2, background: BLEU[3] }} /> Taux réellement observé
        </span>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: "0.72rem", color: INK.secondary }}>
          <span style={{ width: 14, height: 0, borderTop: `2px dashed ${INK.muted}` }} /> Calibration parfaite
        </span>
      </div>

      <p style={{
        marginTop: 11, padding: "11px 13px", borderRadius: 10,
        background: "rgba(47,91,234,0.05)", border: `1px solid ${INK.border}`,
        fontSize: "0.75rem", color: INK.secondary, lineHeight: 1.55,
      }}>
        {cal.lecture} <b style={{ color: INK.primary }}>{cal.pourquoi_hors_periode}</b>
      </p>
    </>
  );
}

/* ------------------------------------------------------------------ */
/* Le composant                                                        */
/* ------------------------------------------------------------------ */

export default function NuageDevis({
  points, seuilGros, seuilChance, calibration, onChoisir, choisi,
}: {
  points: Point[];
  seuilGros: number;
  seuilChance: number;
  calibration?: CalibrationDevis;
  /** Clic sur un point : la liste se filtre sur ce devis. */
  onChoisir: (piece: string | null) => void;
  choisi: string | null;
}) {
  const [vue, setVue] = useState<Vue>("nuage");
  const [log, setLog] = useState(true);
  const [tranche, setTranche] = useState<CleTranche>("toutes");

  const bornes = TRANCHES.find(t => t.cle === tranche) ?? TRANCHES[0];
  const visibles = useMemo(
    () => points.filter(p => p.montant_ht_dt >= bornes.min && p.montant_ht_dt < bornes.max),
    [points, bornes]);

  const quads = useMemo(
    () => quadrants(visibles, seuilGros, seuilChance),
    [visibles, seuilGros, seuilChance]);

  // L'échelle log refuse les zéros ; les montants sont strictement positifs
  // (filtre `ht > 0` côté entrepôt), mais la borne basse est protégée.
  const bas = Math.max(1, Math.min(...visibles.map(p => p.montant_ht_dt), 1));
  const hautX = Math.max(...visibles.map(p => p.montant_ht_dt), 10);

  return (
    <>
      <div style={{ display: "flex", gap: 7, flexWrap: "wrap", marginBottom: 11 }}>
        <button type="button" style={ONGLET(vue === "nuage")} onClick={() => setVue("nuage")}>
          <ScatterIcon size={13} /> Nuage
        </button>
        <button type="button" style={ONGLET(vue === "densite")} onClick={() => setVue("densite")}>
          <Grid3x3 size={13} /> Densité
        </button>
        <button type="button" style={ONGLET(vue === "calibration")} onClick={() => setVue("calibration")}>
          <LineIcon size={13} /> Calibration
        </button>

        {vue !== "calibration" && (
          <>
            <span style={{ flex: 1, minWidth: 8 }} />
            <select className="mini" value={tranche}
              onChange={e => setTranche(e.target.value as CleTranche)}
              style={{ fontSize: "0.73rem" }}
              title="Restreindre l'échelle à une tranche de montant">
              {TRANCHES.map(t => (
                <option key={t.cle} value={t.cle}>{t.label}</option>
              ))}
            </select>
            {vue === "nuage" && (
              <button type="button" style={ONGLET(log)} onClick={() => setLog(v => !v)}
                title="Les montants vont de quelques centaines de dinars à plusieurs centaines de milliers : en échelle linéaire, les petits devis s'écrasent contre l'axe.">
                Échelle {log ? "logarithmique" : "linéaire"}
              </button>
            )}
          </>
        )}
      </div>

      {vue === "calibration" ? (
        <Calibration cal={calibration ?? { applicable: false, motif: "non chargée" }} />
      ) : (
        <>
          {/* Les quadrants, chiffrés : la lecture du nuage en quatre lignes. */}
          <div style={{
            display: "grid", gap: 6, marginBottom: 10,
            gridTemplateColumns: "repeat(auto-fit, minmax(188px, 1fr))",
          }}>
            {quads.map(q => {
              const st = PROTOCOLE_STYLE[q.code];
              return (
                <div key={q.code} style={{
                  borderLeft: `3px solid ${st.couleur}`, paddingLeft: 9,
                  fontSize: "0.71rem", color: INK.muted, lineHeight: 1.45,
                }}>
                  <div style={{ fontWeight: 800, color: INK.primary, fontSize: "0.74rem" }}>
                    {st.verbe} · {q.n} devis
                  </div>
                  <div>{q.ou}</div>
                  <div><b style={{ color: INK.secondary }}>{fMoney(q.esperance)}</b> de ventes probables</div>
                </div>
              );
            })}
          </div>

          {vue === "densite" ? <Densite pts={visibles} /> : (
            <>
              <ResponsiveContainer width="100%" height={252}>
                <ScatterChart margin={{ top: 10, right: 18, left: 0, bottom: 16 }}>
                  <CartesianGrid stroke={INK.grid} />
                  <XAxis type="number" dataKey="montant_ht_dt" name="Montant"
                    scale={log ? "log" : "linear"}
                    domain={log ? [bas, hautX] : [0, hautX]}
                    allowDataOverflow
                    tickFormatter={fAxe}
                    tick={{ fill: INK.secondary, fontSize: 11 }} axisLine={false} tickLine={false}
                    label={{ value: `Montant du devis (DT)${log ? " — échelle log" : ""}`,
                             position: "insideBottom", offset: -10, fill: INK.muted, fontSize: 11 }} />
                  <YAxis type="number" dataKey="chance" name="Chance" unit=" %"
                    domain={[0, 100]}
                    tick={{ fill: INK.secondary, fontSize: 11 }} axisLine={false} tickLine={false}
                    width={46}
                    label={{ value: "Chance de signature", angle: -90, position: "insideLeft",
                             fill: INK.muted, fontSize: 11 }} />
                  <ZAxis type="number" dataKey="esperance_dt" range={[40, 330]} />
                  <Tooltip cursor={{ strokeDasharray: "3 3" }}
                    content={({ active, payload }) => {
                      if (!active || !payload?.length) return null;
                      const x = payload[0].payload as Point;
                      const st = PROTOCOLE_STYLE[x.protocole];
                      return (
                        <div style={INFOBULLE}>
                          <b>{x.nom || x.client}</b>
                          <div>{x.piece_no}</div>
                          <div>{fMoney(x.montant_ht_dt)} · chance {x.chance} %</div>
                          <div>{fMoney(x.esperance_dt)} de ventes probables</div>
                          <div>Ouvert depuis {x.age_j} jours</div>
                          <div style={{ color: st.couleur, fontWeight: 700, marginTop: 3 }}>
                            {st.verbe}
                          </div>
                          <div style={{ color: INK.muted, marginTop: 3 }}>
                            Cliquez pour isoler ce devis dans la liste
                          </div>
                        </div>
                      );
                    }} />

                  {/* Les deux seuils : ils tracent les quadrants, donc les protocoles. */}
                  <ReferenceLine x={seuilGros} stroke={INK.muted} strokeDasharray="5 4"
                    label={{ value: `${fAxe(seuilGros)} DT`, position: "top",
                             fill: INK.muted, fontSize: 10 }} />
                  <ReferenceLine y={seuilChance} stroke={INK.muted} strokeDasharray="5 4"
                    label={{ value: `${seuilChance} %`, position: "right",
                             fill: INK.muted, fontSize: 10 }} />

                  <Scatter data={visibles} stroke="#fff" strokeWidth={1.5}
                    onClick={(e: unknown) => {
                      const p = (e as { payload?: Point })?.payload;
                      if (p) onChoisir(choisi === p.piece_no ? null : p.piece_no);
                    }}
                    style={{ cursor: "pointer" }}>
                    {visibles.map(p => (
                      <Cell key={p.piece_no}
                        fill={PROTOCOLE_STYLE[p.protocole]?.couleur ?? BLEU[3]}
                        fillOpacity={choisi && choisi !== p.piece_no ? 0.16 : 0.7} />
                    ))}
                  </Scatter>
                </ScatterChart>
              </ResponsiveContainer>

              <p className="muted-note" style={{ fontSize: "0.71rem", marginTop: 4, lineHeight: 1.5 }}>
                {visibles.length} devis affichés sur {points.length}. La taille du
                point est l&apos;espérance en dinars ; la couleur rappelle
                l&apos;action, que la <b>position dans un quadrant</b> détermine
                déjà. À 300 devis, des points se recouvrent : la vue
                <b> Densité</b> les compte sans en cacher aucun.
                {choisi && (
                  <>
                    {" "}<button type="button" onClick={() => onChoisir(null)}
                      style={{
                        background: "none", border: "none", padding: 0, font: "inherit",
                        fontWeight: 700, color: BLEU[3], cursor: "pointer",
                      }}>Afficher tous les devis dans la liste</button>
                  </>
                )}
              </p>
            </>
          )}
        </>
      )}
    </>
  );
}
