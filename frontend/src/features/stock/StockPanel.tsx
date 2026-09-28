"use client";

/**
 * StockPanel — onglet « Stock », sur données entièrement réelles (factures
 * d'achat et de vente).
 *
 * Trois questions, trois sous-onglets, chacun porté par des graphes :
 *   · À commander        → produits en rupture, budget par produit, par urgence ;
 *   · Argent immobilisé  → où dort le stock, ce qui ne sera pas vendu, ce qui
 *                          va cesser de se vendre ;
 *   · Volumes à prévoir  → prévision par produit (StockForecastPanel).
 */

import { useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import {
  AlertTriangle, CalendarX2, LineChart as LineIcon, PackageX, RefreshCw, ShoppingCart,
  TrendingDown, Warehouse,
} from "lucide-react";
import Pourquoi from "@/shared/ui/Pourquoi";
import StockForecastPanel from "./StockForecastPanel";
import { URGENCE } from "./stock.constantes";
import { useStock } from "./useStock";
import {
  BLEU, Carte, GRAVITE, Grille, INFOBULLE, INK, Legende, RangeeTuiles, TuileChiffre, Vide,
  fAxe, fMoney, tronquer,
} from "@/shared/ui/VisuelKit";

type Onglet = "commander" | "immobilise" | "prevision";
const ONGLETS: { id: Onglet; label: string; icone: React.ReactNode }[] = [
  { id: "commander", label: "À commander", icone: <ShoppingCart size={14} /> },
  { id: "immobilise", label: "Argent immobilisé", icone: <Warehouse size={14} /> },
  { id: "prevision", label: "Volumes à prévoir", icone: <LineIcon size={14} /> },
];

export default function StockPanel({ selectedClient, selectedClientName }: {
  selectedClient?: string; selectedClientName?: string;
}) {
  const { data, loading, flux, v, load } = useStock(selectedClient);
  const [onglet, setOnglet] = useState<Onglet>("commander");

  if (loading && !data) return <div style={{ gridColumn: "span 12" }}><Vide texte="Chargement du stock…" /></div>;

  if (!flux?.disponible) {
    return (
      <Grille>
        <Carte titre="Stock indisponible" icone={<AlertTriangle size={15} />}>
          <Vide texte="Les données de stock ne sont pas disponibles pour le moment." />
        </Carte>
      </Grille>
    );
  }

  const barreHorizontale = (h: number) => ({
    width: "100%" as const, height: h,
  });

  return (
    <Grille>
      {/* ── Chiffres clés ────────────────────────────────────────────────── */}
      <RangeeTuiles>
        <TuileChiffre icone={<Warehouse size={16} />} label={`Argent immobilisé${selectedClientName ? ` — ${selectedClientName}` : ""}`}
          valeur={fMoney(flux.valeur_immobilisee_dt)}
          detail={`${flux.n_references_accumulees ?? 0} produits en stock`} />
        <TuileChiffre icone={<ShoppingCart size={16} />} label="Produits à commander"
          valeur={`${flux.n_ruptures_critiques ?? 0}`}
          detail={`budget estimé ${fMoney(flux.budget_commandes_dt)}`} accent={GRAVITE.haute.couleur} />
        <TuileChiffre icone={<TrendingDown size={16} />} label="Stock qui ne sera pas vendu"
          valeur={fMoney(flux.perte_quasi_certaine_dt)}
          detail={`${flux.n_obsoletes_certains ?? 0} produit(s) : plus de 2 ans de ventes en stock`} accent={GRAVITE.critique.couleur} />
        <TuileChiffre icone={<PackageX size={16} />} label="Produits en fin de vie"
          valeur={fMoney(data?.fin_de_vie?.capital_expose_total_dt)}
          detail="stock de produits qui cessent de se vendre" />
      </RangeeTuiles>

      {/* ── Sous-onglets ─────────────────────────────────────────────────── */}
      <div style={{ gridColumn: "span 12", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
        <div className="vk-onglets">
          {ONGLETS.map(o => (
            <button key={o.id} className={`vk-onglet${onglet === o.id ? " actif" : ""}`} onClick={() => setOnglet(o.id)}>
              {o.icone}{o.label}
            </button>
          ))}
        </div>
        <button className="icon-button" onClick={load} title="Actualiser"><RefreshCw size={15} /></button>
      </div>

      {/* ── À commander ──────────────────────────────────────────────────── */}
      {onglet === "commander" && (
        v.ruptures.length ? (
          <>
            <Carte span={8} titre="Budget à engager par produit" icone={<ShoppingCart size={15} />}
              sousTitre="Produits encore vendus dont l'approvisionnement s'est arrêté — la couleur indique l'urgence">
              <ResponsiveContainer {...barreHorizontale(Math.max(300, v.ruptures.length * 36))}>
                <BarChart layout="vertical" data={v.ruptures} margin={{ top: 0, right: 70, left: 0, bottom: 0 }} barCategoryGap={8}>
                  <CartesianGrid stroke={INK.grid} horizontal={false} />
                  <XAxis type="number" tickFormatter={fAxe} tick={{ fill: INK.secondary, fontSize: 11 }} axisLine={false} tickLine={false} />
                  <YAxis type="category" dataKey="nom" width={190} tick={{ fill: INK.primary, fontSize: 11.5 }} axisLine={false} tickLine={false} />
                  <Tooltip cursor={{ fill: "rgba(47,91,234,0.05)" }}
                    content={({ active, payload }) => {
                      if (!active || !payload?.length) return null;
                      const r = payload[0].payload as (typeof v.ruptures)[number];
                      return (
                        <div style={INFOBULLE}>
                          <b>{r.produit}</b>
                          <div>{(URGENCE[r.gravite] || URGENCE.a_commander).label}</div>
                          <div>{r.quantite_suggeree.toLocaleString("fr-FR")} unités à commander · {fMoney(r.budget)}</div>
                          <div>{Math.round(r.conso_mensuelle).toLocaleString("fr-FR")} vendues par mois · dernier achat il y a {r.mois_sans_approvisionnement} mois</div>
                        </div>
                      );
                    }} />
                  <Bar dataKey="budget" barSize={16} radius={[0, 4, 4, 0]}
                    label={{ position: "right", formatter: (x: unknown) => fMoney(Number(x)), fill: INK.secondary, fontSize: 11 }}>
                    {v.ruptures.map((r, i) => <Cell key={i} fill={(URGENCE[r.gravite] || URGENCE.a_commander).couleur} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
              <Legende items={Object.values(URGENCE).map(u => ({ couleur: u.couleur, label: u.label }))} />
            </Carte>

            <Carte span={4} titre="Ruptures par urgence" sousTitre="Parmi les produits les plus coûteux à réapprovisionner">
              <ResponsiveContainer width="100%" height={260}>
                <PieChart>
                  <Pie data={v.parUrgence} dataKey="n" nameKey="label" innerRadius={62} outerRadius={96}
                    paddingAngle={2} stroke="#fff" strokeWidth={2}>
                    {v.parUrgence.map(u => <Cell key={u.cle} fill={u.couleur} />)}
                  </Pie>
                  <Tooltip contentStyle={INFOBULLE} formatter={(x, n) => [`${x} produit(s)`, String(n)]} />
                </PieChart>
              </ResponsiveContainer>
              <div style={{ display: "grid", gap: 6 }}>
                {v.parUrgence.map(u => (
                  <div key={u.cle} style={{ display: "flex", justifyContent: "space-between", fontSize: "0.8rem", color: INK.secondary }}>
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 7 }}>
                      <span style={{ width: 10, height: 10, borderRadius: 3, background: u.couleur }} />{u.label}
                    </span>
                    <b style={{ color: INK.primary }}>{u.n}</b>
                  </div>
                ))}
              </div>
            </Carte>
          </>
        ) : (
          <Carte titre="À commander"><Vide texte="Aucun produit en rupture d'approvisionnement." /></Carte>
        )
      )}

      {/* ── Argent immobilisé ────────────────────────────────────────────── */}
      {onglet === "immobilise" && (
        <>
          <Carte span={7} titre="Où dort votre stock" icone={<Warehouse size={15} />}
            sousTitre="Les produits qui immobilisent le plus d'argent">
            {v.capital.length ? (
              <>
                <ResponsiveContainer width="100%" height={Math.max(300, v.capital.length * 34)}>
                  <BarChart layout="vertical" data={v.capital} margin={{ top: 0, right: 70, left: 0, bottom: 0 }} barCategoryGap={8}>
                    <CartesianGrid stroke={INK.grid} horizontal={false} />
                    <XAxis type="number" tickFormatter={fAxe} tick={{ fill: INK.secondary, fontSize: 11 }} axisLine={false} tickLine={false} />
                    <YAxis type="category" dataKey="nom" width={190} tick={{ fill: INK.primary, fontSize: 11.5 }} axisLine={false} tickLine={false} />
                    <Tooltip cursor={{ fill: "rgba(47,91,234,0.05)" }}
                      content={({ active, payload }) => {
                        if (!active || !payload?.length) return null;
                        const t = payload[0].payload as (typeof v.capital)[number];
                        return (
                          <div style={INFOBULLE}>
                            <b>{t.produit}</b>
                            <div>{fMoney(t.valeur_dt)} en stock</div>
                            <div>{Math.round(t.mois_couverture)} mois de ventes d&apos;avance</div>
                          </div>
                        );
                      }} />
                    <Bar dataKey="valeur_dt" barSize={15} radius={[0, 4, 4, 0]}
                      label={{ position: "right", formatter: (x: unknown) => fMoney(Number(x)), fill: INK.secondary, fontSize: 11 }}>
                      {v.capital.map((t, i) => <Cell key={i} fill={t.dormant ? GRAVITE.haute.couleur : BLEU[3]} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
                <Legende items={[
                  { couleur: BLEU[3], label: "Stock normal" },
                  { couleur: GRAVITE.haute.couleur, label: "Plus de 2 ans de ventes d'avance" },
                ]} />
              </>
            ) : <Vide texte="Aucun stock immobilisé significatif." />}
          </Carte>

          <Carte span={5} titre="Stock qui ne sera pas vendu" icone={<CalendarX2 size={15} />}
            sousTitre="Perte probable : ces produits périmeront avant d'être vendus">
            {v.pertes.length ? (
              <ResponsiveContainer width="100%" height={Math.max(300, v.pertes.length * 38)}>
                <BarChart layout="vertical" data={v.pertes} margin={{ top: 0, right: 70, left: 0, bottom: 0 }} barCategoryGap={8}>
                  <XAxis type="number" hide />
                  <YAxis type="category" dataKey="nom" width={170} tick={{ fill: INK.primary, fontSize: 11.5 }} axisLine={false} tickLine={false} />
                  <Tooltip cursor={{ fill: "rgba(47,91,234,0.05)" }}
                    content={({ active, payload }) => {
                      if (!active || !payload?.length) return null;
                      const o = payload[0].payload as (typeof v.pertes)[number];
                      return (
                        <div style={INFOBULLE}>
                          <b>{o.produit}</b>
                          <div>{o.position.toLocaleString("fr-FR")} en stock · {o.conso_mensuelle.toFixed(1)} vendues par mois</div>
                          <div>Perte probable : <b>{fMoney(o.perte_probable_dt)}</b></div>
                        </div>
                      );
                    }} />
                  <Bar dataKey="perte_probable_dt" fill={GRAVITE.critique.couleur} barSize={16} radius={[0, 4, 4, 0]}
                    label={{ position: "right", formatter: (x: unknown) => fMoney(Number(x)), fill: INK.secondary, fontSize: 11 }} />
                </BarChart>
              </ResponsiveContainer>
            ) : <Vide texte="Aucun produit en excès durable." />}
          </Carte>

          <Carte titre="Produits qui vont cesser de se vendre" icone={<PackageX size={15} />}
            sousTitre="Stock concerné dans les 6 prochains mois : à ne plus réapprovisionner">
            {v.finDeVie.length ? (
              <>
              <ResponsiveContainer width="100%" height={Math.max(260, v.finDeVie.length * 34)}>
                <BarChart layout="vertical" data={v.finDeVie} margin={{ top: 0, right: 70, left: 0, bottom: 0 }} barCategoryGap={8}>
                  <CartesianGrid stroke={INK.grid} horizontal={false} />
                  <XAxis type="number" tickFormatter={fAxe} tick={{ fill: INK.secondary, fontSize: 11 }} axisLine={false} tickLine={false} />
                  <YAxis type="category" dataKey="nom" width={220} tick={{ fill: INK.primary, fontSize: 11.5 }} axisLine={false} tickLine={false} />
                  <Tooltip cursor={{ fill: "rgba(47,91,234,0.05)" }}
                    content={({ active, payload }) => {
                      if (!active || !payload?.length) return null;
                      const r = payload[0].payload as (typeof v.finDeVie)[number];
                      return (
                        <div style={INFOBULLE}>
                          <b>{r.produit}</b>
                          <div>{fMoney(r.valeur_stock_dt)} en stock</div>
                          <div>{r.n_clients_12m} client(s) sur 12 mois · aucune vente depuis {r.mois_sans_vente} mois</div>
                        </div>
                      );
                    }} />
                  <Bar dataKey="capital_expose_dt" fill={BLEU[2]} barSize={15} radius={[0, 4, 4, 0]}
                    label={{ position: "right", formatter: (x: unknown) => fMoney(Number(x)), fill: INK.secondary, fontSize: 11 }} />
                </BarChart>
              </ResponsiveContainer>
              {v.finDeVie[0]?.raisons?.length ? (
                <div style={{ display: "flex", alignItems: "center", gap: 9, flexWrap: "wrap", marginTop: 8 }}>
                  <span style={{ fontSize: "0.78rem", fontWeight: 700, color: INK.primary }}>
                    {tronquer(v.finDeVie[0].produit, 30)}
                  </span>
                  <Pourquoi raisons={v.finDeVie[0].raisons}
                    libelle="Pourquoi celui-ci ?"
                    titre={`Pourquoi ${tronquer(v.finDeVie[0].produit, 30)}`} />
                </div>
              ) : null}
              </>
            ) : <Vide texte="Aucun produit en fin de vie." />}
          </Carte>
        </>
      )}

      {/* ── Volumes à prévoir ────────────────────────────────────────────── */}
      {onglet === "prevision" && (
        <div className="chart-card" style={{ gridColumn: "span 12" }}>
          <StockForecastPanel />
        </div>
      )}
    </Grille>
  );
}
