"use client";

import {
  Activity, AlertTriangle, BarChart3, Boxes, CalendarClock, Gauge, Layers,
  PieChart as PieIcon, ShieldAlert, Target, TrendingUp, UserMinus, Users, Wallet,
} from "lucide-react";
import AdminPanel from "@/features/admin/AdminPanel";
import BriefingPanel from "@/features/briefing/BriefingPanel";
import CaAttenduCarte from "@/features/commercial/CaAttenduCarte";
import ChurnPanel from "@/features/churn/ChurnPanel";
import CommercialPanel from "@/features/commercial/CommercialPanel";
import Copilot from "@/features/copilote/Copilot";
import ImpactPanel from "@/features/impact/ImpactPanel";
import RecommandationsPanel from "@/features/commercial/RecommandationsPanel";
import MargePanel from "@/features/marge/MargePanel";
import DocumentsOCR from "@/features/ocr/DocumentsOCR";
import StockPanel from "@/features/stock/StockPanel";
import TachesPanel from "@/features/taches/TachesPanel";
import PanneauMasque from "@/shared/ui/PanneauMasque";
import CarteDelais from "./CarteDelais";
import { Alerte, ChartCard, MiniGauge, PanelCard } from "./composants/Cartes";
import { fInt, fMoney } from "./format";
import type { TableauDeBord } from "./useTableauDeBord";

export default function ContenuVue({ t }: { t: TableauDeBord }) {
  const { view, setView, kpis, filtersData, session, clientFocus, gauges, onExpand, g } = t;
  const { filterPayload } = t.filtres;
  const { rMonthly, rFlow, rYoY, rSeason, rAging, rCash, rPareto, rPayMix, rProd, rPriority } = g;

  return (
    <div className="view-grid" key={view}>
      {view === "synthese" && <>
        <div style={{ gridColumn: "span 12", display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(215px,1fr))", gap: 12 }}>
          <Alerte
            couleur="#DC2626"
            icone={<UserMinus size={16} />}
            titre="Clients sur le départ"
            valeur={kpis?.churn_anticipe?.masque ? "—" : `${kpis?.churn_anticipe?.n_au_dessus_de_0_5 ?? 0}`}
            detail={kpis?.churn_anticipe?.masque ? "prévision masquée par vos filtres"
              : kpis?.churn_anticipe?.enjeu_total_dt
              ? `${fMoney(kpis.churn_anticipe.enjeu_total_dt)} en jeu`
              : "aucun compte majeur menacé"}
            onClick={() => setView("retention")}
          />
          <Alerte
            couleur="#F97316"
            icone={<ShieldAlert size={16} />}
            titre="Créances au-delà de 60 j"
            valeur={fMoney(kpis?.exposition_recente_dt)}
            detail={`${fInt(kpis?.exposition_recente_count)} factures concernées`}
            onClick={() => setView("risque")}
          />
          <Alerte
            couleur="#8B5CF6"
            icone={<Layers size={16} />}
            titre="Dépendance clients"
            valeur={`${(kpis?.top_clients_revenue_share ?? 0).toFixed(0)} %`}
            detail="du chiffre d'affaires sur 5 comptes"
            onClick={() => setView("clients")}
          />
          <Alerte
            couleur="#0E9E6E"
            icone={<Target size={16} />}
            titre="Taux de marge"
            valeur={kpis?.taux_marge == null ? "—" : `${kpis.taux_marge.toFixed(1)} %`}
            detail={fMoney(kpis?.marge_brute)}
            onClick={() => setView("performance")}
          />
        </div>

        <ChartCard title="Évolution du chiffre d'affaires" icon={<TrendingUp size={17} />} span={8} h={300} render={rMonthly} onExpand={onExpand} />
        <PanelCard title="Santé financière" icon={<Gauge size={17} />} span={4}>
          <div className="gauges-row">
            {gauges.map((g, i) => <MiniGauge key={i} value={g.value} label={g.label} color={g.color} />)}
            {!gauges.length && <p className="muted-note">Indisponibles sur ce périmètre.</p>}
          </div>
        </PanelCard>

        {/* Le chiffre d'affaires attendu prolonge la courbe au-dessus : sa place
            est ici, sous l'évolution dont il est la suite, et non dans un onglet
            commercial où il arrivait sans contexte. */}
        <CaAttenduCarte />
      </>}
      {view === "performance" && <>
        <ChartCard title={`${kpis?.yoy_comparison?.current_year ?? "Cette année"} face à ${kpis?.yoy_comparison?.previous_year ?? "l'an dernier"}`} icon={<TrendingUp size={17} />} span={12} h={260} render={rYoY}
          hint={kpis?.yoy_comparison?.delta_pct != null ? `${kpis.yoy_comparison.delta_pct >= 0 ? "+" : ""}${kpis.yoy_comparison.delta_pct.toFixed(1)} % sur les mois comparables` : undefined} onExpand={onExpand} />
        <ChartCard title="Ventes, achats et marge" icon={<BarChart3 size={17} />} span={7} render={rFlow} onExpand={onExpand} />
        <ChartCard title="Saisonnalité" icon={<Activity size={17} />} span={5} render={rSeason} onExpand={onExpand} />
      </>}
      {view === "risque" && <>
        <ChartCard title="Priorités de recouvrement" icon={<ShieldAlert size={17} />} span={7} render={rPriority} hidden={clientFocus} onExpand={onExpand} />
        <PanelCard title="Délais les plus longs" icon={<AlertTriangle size={17} />} span={5} hidden={clientFocus}>
          <div className="data-table"><div className="dt-head three"><span>Client</span><span>Créances</span><span>Factures</span></div>
            {(kpis?.clients_a_risque || []).length ? (kpis?.clients_a_risque || []).map((c, i) => (<div className="dt-row three" key={i}><span className="dt-name" title={c.client}>{c.nom || c.client}</span><span className="risk-tag">{fMoney(c.montant_risque)}</span><span>{fInt(c.factures)}</span></div>)) : <p className="muted-note">Aucun client concerné.</p>}
          </div>
        </PanelCard>
        <CarteDelais d={kpis?.delais} />
        <ChartCard title="Échelonnement des délais accordés" icon={<CalendarClock size={17} />} span={12} render={rAging} onExpand={onExpand} />
      </>}
      {view === "clients" && <>
        <PanelCard title="Vos principaux clients" icon={<Users size={17} />} span={7} hidden={clientFocus}>
          <div className="data-table"><div className="dt-head six"><span>#</span><span>Client</span><span>CA TTC</span><span>Part</span><span>Créances</span><span>Délai accordé</span></div>
            {(kpis?.top_clients || []).map(c => (<div className="dt-row six" key={c.rank}><span className="dt-rank">{c.rank}</span><span className="dt-name" title={c.client}>{c.nom || c.client}</span><span>{fMoney(c.revenue)}</span><span><span className="share-bar"><i style={{ width: `${Math.min(100, c.share)}%` }} /></span>{c.share.toFixed(1)}%</span><span className={c.risque ? "risk-tag" : "ok-tag"}>{c.risque ? fMoney(c.risque) : "—"}</span><span>{c.risk_score == null ? <span title="Trop peu de factures pour établir une habitude de paiement">Non établi</span> : <span className="score-pill" title={c.risk_score > 50 ? "Ce client règle habituellement à plus de 60 jours" : "Ce client règle habituellement sous 60 jours"} style={{ background: c.risk_score > 50 ? "rgba(239,68,68,0.15)" : "rgba(16,185,129,0.15)", color: c.risk_score > 50 ? "#EF4444" : "#10B981" }}>{c.risk_score > 50 ? "Long" : "Standard"}</span>}</span></div>))}
          </div>
        </PanelCard>
        <ChartCard title="Concentration du chiffre d'affaires" icon={<Layers size={17} />} span={5} render={rPareto} hidden={clientFocus} onExpand={onExpand} />
        <ChartCard title="Créances arrivant à échéance" icon={<Wallet size={17} />} span={7} render={rCash} onExpand={onExpand} />
        <ChartCard title="Modes de paiement" icon={<PieIcon size={17} />} span={5} render={rPayMix} onExpand={onExpand} />

        {kpis?.segmentation?.masque && (
          <PanneauMasque motif={`Types de clients : ${kpis.segmentation.motif ?? ""}`} />
        )}
        {kpis?.segmentation?.servi && (kpis.segmentation.segments || []).length > 0 && (
          <PanelCard title="Types de clients" icon={<Layers size={17} />} span={12}>
            <div className="data-table">
              <div className="dt-head" style={{ display: "grid", gridTemplateColumns: "2.2fr 90px 110px 110px 110px 120px" }}>
                <span>Profil</span><span>Clients</span><span>Part du CA</span>
                <span>Panier médian</span><span>Commandes</span><span>Menacés</span>
              </div>
              {(kpis.segmentation.segments || []).map(s => (
                <div key={s.segment} className="dt-row"
                     style={{ display: "grid", gridTemplateColumns: "2.2fr 90px 110px 110px 110px 120px", fontSize: "0.8rem" }}>
                  <span className="dt-name" title={s.caracterisation}>
                    <b>{s.nom}</b>
                  </span>
                  <span>{fInt(s.n_clients)}<em style={{ fontStyle: "normal", color: "var(--text-muted)", fontSize: "0.72rem" }}> ({s.part_clients_pct}%)</em></span>
                  <span><b>{s.part_ca_pct} %</b></span>
                  <span>{fMoney(s.panier_median_dt)}</span>
                  <span>{fInt(s.commandes_medianes)}</span>
                  <span>
                    {s.part_menacee_pct == null ? "—" : (
                      <span style={{
                        color: s.part_menacee_pct >= 10 ? "#DC2626"
                          : s.part_menacee_pct >= 5 ? "#F97316" : "#10B981",
                        fontWeight: 700,
                      }}>
                        {s.part_menacee_pct} %
                        {s.ca_menace_dt ? (
                          <em style={{ fontStyle: "normal", display: "block", fontSize: "0.7rem", color: "var(--text-muted)" }}>
                            {fMoney(s.ca_menace_dt)}
                          </em>
                        ) : null}
                      </span>
                    )}
                  </span>
                </div>
              ))}
            </div>
          </PanelCard>
        )}
      </>}
      {/* CATALOGUE : ce qui se vend. La prévision de demande et les
          fournisseurs ont rejoint Stock & achats, où ils servent une décision
          de réapprovisionnement ; ici restent les références et leur adoption. */}
      {view === "produits" && <>
        <ChartCard title="Produits les plus vendus" icon={<Boxes size={17} />} span={12} h={280} render={rProd} onExpand={onExpand} />
        <RecommandationsPanel />
      </>}

      {view === "retention" && (
        <div style={{ gridColumn: "span 12" }}>
          <ChurnPanel clientNames={filtersData?.client_names} />
        </div>
      )}

      {view === "impact" && <ImpactPanel />}

      {view === "commercial" && (
        <CommercialPanel />
      )}

      {view === "marge" && <MargePanel />}

      {view === "priorites" && (
        <div style={{ gridColumn: "span 12" }}>
          <BriefingPanel filterPayload={filterPayload}
            peutConfier />
        </div>
      )}

      {view === "taches" && (
        <div style={{ gridColumn: "span 12" }}>
          <TachesPanel role={session?.role || "directeur"} />
        </div>
      )}

      {view === "copilot" && <Copilot filterPayload={filterPayload} />}
      {view === "stock" && (
        <StockPanel />
      )}
      {view === "ocr" && <DocumentsOCR />}
      {view === "admin" && <AdminPanel />}
    </div>
  );
}
