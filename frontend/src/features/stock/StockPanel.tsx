"use client";

import { useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import {
  AlertTriangle, CalendarX2, LineChart as LineIcon, PackageX, RefreshCw, ShoppingCart,
  TrendingDown, Truck, Warehouse,
} from "lucide-react";
import PanneauMasque from "@/shared/ui/PanneauMasque";
import Pourquoi from "@/shared/ui/Pourquoi";
import ApprovisionnementPanel from "./ApprovisionnementPanel";
import StockForecastPanel from "./StockForecastPanel";
import { useStock } from "./useStock";
import {
  BLEU, Carte, GRAVITE, Grille, INFOBULLE, INK, Legende, RangeeTuiles, TuileChiffre, Vide,
  fAxe, fMoney, tronquer,
} from "@/shared/ui/VisuelKit";

// « À commander » a été retiré : les produits à réapprovisionner se décident
// dans l'onglet Approvisionnement, où ils sont ACTIONNABLES — proposés,
// validés, commandés. Une liste à deux endroits, dont une sans bouton, invite
// à chercher laquelle fait foi.
type Onglet = "immobilise" | "prevision" | "amont";
const ONGLETS: { id: Onglet; label: string; icone: React.ReactNode }[] = [
  { id: "immobilise", label: "Argent immobilisé", icone: <Warehouse size={14} /> },
  { id: "prevision", label: "Volumes à prévoir", icone: <LineIcon size={14} /> },
  // Le processus amont rejoint le stock : ce sont les deux bouts de la même
  // chaîne, et séparer « qui fournit » de « ce qu'il reste » obligeait à
  // changer d'onglet pour décider d'une commande.
  { id: "amont", label: "Approvisionnement", icone: <Truck size={14} /> },
];

export default function StockPanel() {
  const { data, loading, flux, v, load } = useStock();
  const [onglet, setOnglet] = useState<Onglet>("amont");

  if (loading && !data) return <div style={{ gridColumn: "span 12" }}><Vide texte="Chargement du stock…" /></div>;

  // L'onglet Approvisionnement reste TOUJOURS accessible. Les trois autres
  // comptent par produit et n'ont pas de sens sous un filtre client ; celui-ci
  // répond justement « ce que ce client consomme, et ce qui risque de lui
  // manquer ». Le masquer privait le directeur de la seule réponse disponible.
  const ongletsAffiches = ONGLETS;
  const barreOnglets = (
    <div className="vk-onglets" style={{ gridColumn: "span 12" }}>
      {ongletsAffiches.map(o => (
        <button key={o.id} className={`vk-onglet${onglet === o.id ? " actif" : ""}`}
          onClick={() => setOnglet(o.id)}>{o.icone}{o.label}</button>
      ))}
    </div>
  );

  if (data?.masque && onglet !== "amont") {
    return (
      <Grille>
        {barreOnglets}
        <PanneauMasque motif={data.error} />
      </Grille>
    );
  }

  // L'analyse amont ne dépend pas des flux de stock : elle lit les factures
  // d'achat. Elle reste donc consultable même quand le stock est indisponible.
  if (onglet === "amont") {
    return <Grille>{barreOnglets}<ApprovisionnementPanel /></Grille>;
  }

  if (!flux?.disponible) {
    return (
      <Grille>
        {barreOnglets}
        <Carte titre="Stock indisponible" icone={<AlertTriangle size={15} />}>
          <Vide texte="Les données de stock ne sont pas disponibles pour le moment." />
        </Carte>
      </Grille>
    );
  }

  return (
    <Grille>
      <RangeeTuiles>
        <TuileChiffre icone={<Warehouse size={16} />} label="Argent immobilisé"
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

      <div style={{ gridColumn: "span 12", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
        <div className="vk-onglets">
          {ongletsAffiches.map(o => (
            <button key={o.id} className={`vk-onglet${onglet === o.id ? " actif" : ""}`} onClick={() => setOnglet(o.id)}>
              {o.icone}{o.label}
            </button>
          ))}
        </div>
        <button className="icon-button" onClick={load} title="Actualiser"><RefreshCw size={15} /></button>
      </div>

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

      {onglet === "prevision" && (
        <div className="chart-card" style={{ gridColumn: "span 12" }}>
          <StockForecastPanel />
        </div>
      )}

      {/* L'onglet Approvisionnement est rendu plus haut, avant les garde-fous
          de masquage : il reste accessible sous un filtre client, puisqu'il
          est le seul à savoir répondre pour un client. */}
    </Grille>
  );
}
