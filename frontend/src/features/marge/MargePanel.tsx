"use client";

import {
  Area, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Line,
  ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import {
  AlertTriangle, Boxes, CalendarClock, Coins, Layers, Percent, RefreshCw,
  Target, TrendingDown,
} from "lucide-react";
import {
  BLEU, Carte, Grille, INFOBULLE, INK, RangeeTuiles, TuileChiffre, Vide,
  fAxe, fMoney, tronquer,
} from "@/shared/ui/VisuelKit";
import type { CategorieMarge, Completude, ProduitMarge } from "./marge.types";
import { useMarge } from "./useMarge";

/** Une couleur par catégorie, stable d'un graphique à l'autre. */
const COULEUR: Record<string, string> = {
  reactif: BLEU[3],
  equipement: "#EC835A",
  service: "#0CA30C",
  autre: INK.muted,
};

const fPct = (v: number | null | undefined) =>
  v == null ? "—" : `${v.toFixed(1).replace(".", ",")} %`;

/** Le compte à rebours du chiffre d'affaires vers la marge, en trois barres. */
function Waterfall({ ca, cout, marge }: { ca: number; cout: number; marge: number }) {
  const etapes = [
    { nom: "Chiffre d'affaires", valeur: ca, couleur: BLEU[2] },
    { nom: "Coût de revient", valeur: cout, couleur: "#D03B3B" },
    { nom: "Marge brute", valeur: marge, couleur: "#0CA30C" },
  ];
  return (
    <div style={{ display: "grid", gap: 9 }}>
      {etapes.map(e => (
        <div key={e.nom}>
          <div style={{
            display: "flex", justifyContent: "space-between", alignItems: "baseline",
            marginBottom: 4,
          }}>
            <span style={{ fontSize: "0.78rem", color: INK.secondary, fontWeight: 600 }}>
              {e.nom}
            </span>
            <span style={{ fontSize: "0.92rem", color: INK.primary, fontWeight: 800 }}>
              {fMoney(e.valeur)}
            </span>
          </div>
          <div style={{ height: 9, borderRadius: 5, background: "rgba(26,35,72,0.06)" }}>
            <div style={{
              width: `${ca ? Math.min(100, (e.valeur / ca) * 100) : 0}%`,
              height: "100%", borderRadius: 5, background: e.couleur,
            }} />
          </div>
        </div>
      ))}
    </div>
  );
}

/** Une catégorie : son poids dans le CA, la marge qu'elle dégage, son rôle. */
function LigneCategorie({ c }: { c: CategorieMarge }) {
  const perte = c.marge_dt < 0;
  const couleur = perte ? "#D03B3B" : (COULEUR[c.code] ?? BLEU[2]);
  return (
    <div style={{
      borderStyle: "solid", borderWidth: "1px 1px 1px 4px",
      borderColor: `${INK.border} ${INK.border} ${INK.border} ${couleur}`,
      borderRadius: 11, padding: "12px 14px", display: "grid", gap: 8,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
        <span style={{ fontWeight: 800, color: INK.primary, fontSize: "0.92rem" }}>{c.nom}</span>
        <span style={{ fontWeight: 800, color: couleur, fontSize: "1.1rem" }}>
          {fPct(c.taux_marge_pct)}
        </span>
      </div>
      <div style={{ display: "flex", gap: 18, flexWrap: "wrap", fontSize: "0.74rem", color: INK.secondary }}>
        <span>
          Chiffre d&apos;affaires <b style={{ color: INK.primary }}>{fMoney(c.ca_dt)}</b>
          {" "}({fPct(c.part_du_ca_pct)} du total)
        </span>
        <span>
          Marge <b style={{ color: perte ? "#D03B3B" : INK.primary }}>{fMoney(c.marge_dt)}</b>
          {perte
            ? " — cette catégorie a coûté plus qu'elle n'a rapporté"
            : ` (${fPct(c.part_de_la_marge_pct)} du total)`}
        </span>
      </div>
      <div style={{ fontSize: "0.74rem", color: INK.muted, lineHeight: 1.5 }}>{c.role}</div>
    </div>
  );
}

function TableauProduits({ lignes, perte }: { lignes: ProduitMarge[]; perte?: boolean }) {
  if (!lignes.length) {
    return <Vide texte={perte ? "Aucun produit vendu sous son coût sur cette période."
      : "Aucun produit à marge positive sur cette période."} />;
  }
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.79rem" }}>
        <thead>
          <tr style={{ textAlign: "left", color: INK.muted, fontSize: "0.7rem" }}>
            <th style={{ padding: "6px 8px" }}>Produit</th>
            <th style={{ padding: "6px 8px" }}>Catégorie</th>
            <th style={{ padding: "6px 8px", textAlign: "right" }}>Chiffre d&apos;affaires</th>
            <th style={{ padding: "6px 8px", textAlign: "right" }}>
              {perte ? "Perte" : "Marge"}
            </th>
            <th style={{ padding: "6px 8px", textAlign: "right" }}>Taux</th>
            <th style={{ padding: "6px 8px", textAlign: "right" }}>Clients</th>
          </tr>
        </thead>
        <tbody>
          {lignes.map(p => (
            <tr key={p.reference} style={{ borderTop: `1px solid ${INK.grid}` }}>
              <td style={{ padding: "8px" }}>
                <div style={{ fontWeight: 600, color: INK.primary }} title={p.designation}>
                  {tronquer(p.designation, 40)}
                </div>
                <div style={{ fontSize: "0.68rem", color: INK.muted }}>{p.reference}</div>
              </td>
              <td style={{ padding: "8px", color: INK.secondary }}>{p.categorie}</td>
              <td style={{ padding: "8px", textAlign: "right", color: INK.secondary }}>
                {fMoney(p.ca_dt)}
              </td>
              <td style={{
                padding: "8px", textAlign: "right", fontWeight: 800,
                color: perte ? "#D03B3B" : INK.primary,
              }}>
                {fMoney(p.marge_dt)}
              </td>
              <td style={{
                padding: "8px", textAlign: "right",
                color: perte ? "#D03B3B" : INK.secondary,
              }}>
                {fPct(p.taux_marge_pct)}
              </td>
              <td style={{ padding: "8px", textAlign: "right", color: INK.secondary }}>
                {p.n_clients}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Bandeau d'année incomplète.
 *
 * « Année en cours » s'arrête à la dernière facture de l'entrepôt. Afficher
 * 5,6 M DT sur quatre mois sans le dire laisse croire à un effondrement face
 * aux 14,3 M de l'an dernier, alors qu'il ne manque que du temps.
 */
function AnneeIncomplete({ c }: { c: Completude }) {
  const cm = c.comparaison;
  const hausse = (cm.evolution_pct ?? 0) >= 0;
  return (
    <div style={{
      gridColumn: "span 12", padding: "13px 15px", borderRadius: 11,
      background: "rgba(224,161,15,0.07)", borderWidth: 1, borderStyle: "solid",
      borderColor: "rgba(224,161,15,0.25)", display: "grid", gap: 9,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <CalendarClock size={16} style={{ color: "#E0A10F" }} />
        <span style={{ fontWeight: 800, color: INK.primary, fontSize: "0.86rem" }}>
          {c.annee} n&apos;est pas terminée : {c.mois_couverts} mois sur 12,
          arrêtés au {c.dernier_mois}
        </span>
      </div>

      <div style={{
        display: "grid", gap: 11,
        gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))",
      }}>
        <Chiffre titre="Réalisé à ce jour" valeur={fMoney(c.marge_realisee_dt)}
          detail={`${c.mois_couverts} mois de marge effectivement facturée`} />
        <Chiffre titre={`Même période ${cm.annee}`}
          valeur={fMoney(cm.marge_meme_periode_dt)}
          detail={cm.evolution_pct == null ? "comparaison indisponible"
            : `${hausse ? "▲" : "▼"} ${Math.abs(cm.evolution_pct).toFixed(1)} % — la seule comparaison honnête`}
          couleur={hausse ? "#0CA30C" : "#D03B3B"} />
        <Chiffre titre="Projection de fin d'année"
          valeur={c.projection_fin_d_annee_dt == null ? "—" : fMoney(c.projection_fin_d_annee_dt)}
          detail={`à comparer aux ${fMoney(cm.marge_annee_complete_dt)} de ${cm.annee}`}
          couleur="#2F5BEA" />
      </div>

      <div style={{ fontSize: "0.73rem", color: INK.secondary, lineHeight: 1.55 }}>
        <b style={{ color: INK.primary }}>Comment la projection est calculée :</b>{" "}
        {c.projection_methode}
      </div>
      <div style={{ fontSize: "0.72rem", color: INK.muted, lineHeight: 1.5 }}>
        {c.projection_limite} Les chiffres détaillés ci-dessous portent tous sur
        les {c.mois_couverts} mois réellement facturés, pas sur la projection.
      </div>
    </div>
  );
}

function Chiffre({ titre, valeur, detail, couleur = INK.primary }: {
  titre: string; valeur: string; detail: string; couleur?: string;
}) {
  return (
    <div>
      <div style={{ fontSize: "0.72rem", fontWeight: 700, color: INK.secondary }}>{titre}</div>
      <div style={{ fontSize: "1.25rem", fontWeight: 800, color: couleur, lineHeight: 1.2 }}>
        {valeur}
      </div>
      <div style={{ fontSize: "0.7rem", color: INK.muted, lineHeight: 1.45 }}>{detail}</div>
    </div>
  );
}

export default function MargePanel() {
  const { data, d, loading, recharger } = useMarge();

  if (loading && !data) return <Grille><Vide texte="Calcul de la marge…" /></Grille>;
  if (!data?.servi) {
    return (
      <Grille>
        <Carte titre="Marge brute">
          <Vide texte={data?.motif || "Marge non calculable sur ce périmètre."} />
        </Carte>
      </Grille>
    );
  }

  const cat = data.par_categorie!;
  const cout = cat.total_ca_dt - cat.total_marge_dt;
  const lim = data.limites ?? {};
  const periode = data.periode_reference?.libelle ?? "";
  const comp = data.completude as Completude | undefined;
  const anneePartielle = comp && "incomplete" in comp && comp.incomplete ? comp : null;

  return (
    <Grille>
      {anneePartielle && <AnneeIncomplete c={anneePartielle} />}
      <RangeeTuiles>
        <TuileChiffre icone={<Target size={16} />} label="Marge brute"
          valeur={fMoney(cat.total_marge_dt)}
          detail={`${fPct(cat.taux_ensemble_pct)} du chiffre d'affaires · ${periode.toLowerCase()}`}
          accent="#0CA30C" />
        <TuileChiffre icone={<Coins size={16} />} label="Chiffre d'affaires des lignes"
          valeur={fMoney(cat.total_ca_dt)}
          detail="base de calcul de la marge" />
        <TuileChiffre icone={<Percent size={16} />} label="Coût de revient"
          valeur={fMoney(cout)}
          detail="ce que les produits vendus ont coûté" accent="#D03B3B" />
        <TuileChiffre icone={<Boxes size={16} />} label="Références vendues"
          valeur={`${data.produits?.n_references ?? 0}`}
          detail={`dont ${data.produits?.pertes.length ?? 0} vendues à perte`} />
      </RangeeTuiles>

      <Carte span={5} titre="Du chiffre d'affaires à la marge"
        icone={<Layers size={15} />}
        sousTitre="Ce qui reste une fois le coût des produits déduit"
        droite={<button className="icon-button" onClick={recharger} title="Actualiser"><RefreshCw size={15} /></button>}>
        <Waterfall ca={cat.total_ca_dt} cout={cout} marge={cat.total_marge_dt} />
        <div style={{
          marginTop: 14, padding: "11px 13px", borderRadius: 10,
          background: "rgba(47,91,234,0.05)", border: `1px solid ${INK.border}`,
          fontSize: "0.75rem", color: INK.secondary, lineHeight: 1.55,
        }}>
          <b style={{ color: INK.primary }}>Marge brute</b>, et non résultat :{" "}
          {lim.ce_qui_n_est_pas_deduit}
        </div>
      </Carte>

      <Carte span={7} titre="D'où vient la marge" icone={<Layers size={15} />}
        sousTitre="Le taux diffère tellement d'une catégorie à l'autre qu'un total unique le cachait">
        <div style={{ display: "grid", gap: 10 }}>
          {d.cats.map(c => <LigneCategorie key={c.code} c={c} />)}
        </div>
      </Carte>

      <Carte span={7} titre="Taux de marge dans le temps" icone={<Percent size={15} />}
        sousTitre="Tout l'historique du périmètre : une pente ne se lit pas sur un point">
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart data={d.tendance} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
            <CartesianGrid stroke={INK.grid} vertical={false} />
            <XAxis dataKey="period" tick={{ fill: INK.secondary, fontSize: 10 }}
              axisLine={false} tickLine={false} interval="preserveStartEnd" minTickGap={28} />
            <YAxis yAxisId="g" tickFormatter={fAxe} tick={{ fill: INK.muted, fontSize: 10 }}
              axisLine={false} tickLine={false} width={46} />
            <YAxis yAxisId="t" orientation="right" unit=" %" domain={[0, 60]}
              tick={{ fill: INK.secondary, fontSize: 10 }} axisLine={false} tickLine={false} width={42} />
            <Tooltip contentStyle={INFOBULLE}
              content={({ active, payload, label }) => {
                if (!active || !payload?.length) return null;
                const p = payload[0].payload as (typeof d.tendance)[number];
                return (
                  <div style={INFOBULLE}>
                    <b>{label}</b>
                    <div>Chiffre d&apos;affaires : {fMoney(p.ca_dt)}</div>
                    <div>Marge : {fMoney(p.marge_dt)}</div>
                    <div>Taux : <b>{fPct(p.taux_marge_pct)}</b></div>
                  </div>
                );
              }} />
            <Area yAxisId="g" type="monotone" dataKey="marge_dt" name="Marge"
              stroke={BLEU[3]} fill={BLEU[3]} fillOpacity={0.14} strokeWidth={1.6} />
            {d.tauxMoyen != null && (
              <ReferenceLine yAxisId="t" y={d.tauxMoyen} stroke={INK.muted}
                strokeDasharray="4 4"
                label={{ value: `moyenne ${fPct(d.tauxMoyen)}`, position: "insideTopRight",
                  fill: INK.muted, fontSize: 10 }} />
            )}
            <Line yAxisId="t" type="monotone" dataKey="taux_marge_pct" name="Taux"
              stroke="#0CA30C" strokeWidth={2} dot={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </Carte>

      {/* En dinars et non en pourcentage : quand une catégorie DÉTRUIT de la
          marge, une « part du total » dépasse 100 % pour les autres et se lit à
          contresens. Une contribution signée se lit sans ambiguïté. */}
      <Carte span={5} titre="Ce que chaque catégorie apporte" icone={<Layers size={15} />}
        sousTitre="Marge dégagée, ou détruite, sur la période">
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={d.cats} layout="vertical"
            margin={{ top: 4, right: 62, left: 0, bottom: 0 }} barCategoryGap={10}>
            <CartesianGrid stroke={INK.grid} horizontal={false} />
            <XAxis type="number" tickFormatter={fAxe}
              tick={{ fill: INK.secondary, fontSize: 10 }} axisLine={false} tickLine={false} />
            <YAxis type="category" dataKey="nom" width={96}
              tick={{ fill: INK.primary, fontSize: 11 }} axisLine={false} tickLine={false} />
            <ReferenceLine x={0} stroke={INK.secondary} />
            <Tooltip cursor={{ fill: "rgba(47,91,234,0.05)" }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const c = payload[0].payload as CategorieMarge;
                return (
                  <div style={INFOBULLE}>
                    <b>{c.nom}</b>
                    <div>Marge : <b>{fMoney(c.marge_dt)}</b> ({fPct(c.taux_marge_pct)})</div>
                    <div>Chiffre d&apos;affaires : {fMoney(c.ca_dt)}</div>
                    <div>{fPct(c.part_du_ca_pct)} du chiffre d&apos;affaires total</div>
                  </div>
                );
              }} />
            <Bar dataKey="marge_dt" barSize={18} radius={[0, 4, 4, 0]}
              label={{ position: "right", formatter: (v: unknown) => fMoney(Number(v)),
                fill: INK.secondary, fontSize: 10.5 }}>
              {d.cats.map(c => (
                <Cell key={c.code}
                  fill={c.marge_dt < 0 ? "#D03B3B" : (COULEUR[c.code] ?? BLEU[2])} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
        {d.cats.some(c => c.marge_dt < 0) && (
          <p className="muted-note" style={{ marginTop: 8, fontSize: "0.72rem" }}>
            Une catégorie en rouge a coûté plus qu&apos;elle n&apos;a rapporté sur la période :
            les autres financent la différence.
          </p>
        )}
      </Carte>

      <Carte span={7} titre="Les produits qui portent la marge" icone={<Target size={15} />}
        sousTitre="Classés par marge dégagée sur la période">
        <TableauProduits lignes={d.porteurs} />
      </Carte>

      <Carte span={5} titre="Les produits vendus à perte" icone={<TrendingDown size={15} />}
        sousTitre={`${fMoney(Math.abs(data.produits?.perte_totale_dt ?? 0))} de marge négative`}>
        <TableauProduits lignes={d.pertes} perte />
        {d.pertes.length > 0 && (
          <div style={{
            marginTop: 12, padding: "11px 13px", borderRadius: 10,
            background: "rgba(236,131,90,0.07)", border: "1px solid rgba(236,131,90,0.22)",
            fontSize: "0.75rem", color: INK.secondary, lineHeight: 1.55,
            display: "flex", gap: 9,
          }}>
            <AlertTriangle size={15} style={{ color: "#EC835A", flexShrink: 0, marginTop: 1 }} />
            <span>{data.produits?.lecture_des_pertes}</span>
          </div>
        )}
      </Carte>

      {/* La carte « ce que ce chiffre ne dit pas » a été retirée : elle
          listait les exclusions du calcul — lignes écartées, lignes offertes,
          retours. C'est du commentaire sur la méthode, pas une information qui
          change une décision. La seule réserve qui compte, « marge brute et non
          résultat », reste sous le passage du chiffre d'affaires à la marge. */}
    </Grille>
  );
}
