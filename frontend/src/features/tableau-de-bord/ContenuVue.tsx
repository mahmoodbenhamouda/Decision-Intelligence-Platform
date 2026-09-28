"use client";

/**
 * Vue — le contenu de l'onglet ouvert.
 *
 * Les onglets financiers (synthèse, performance, risque, clients, produits)
 * sont composés ici à partir des graphes et des cartes du tableau de bord ;
 * les autres délèguent à la fonctionnalité correspondante.
 */
import {
  Activity, AlertTriangle, BarChart3, Boxes, CalendarClock, Gauge, Layers,
  PieChart as PieIcon, ShieldAlert, Target, TrendingUp, Truck, UserMinus, Users, Wallet,
} from "lucide-react";
import AdminPanel from "@/features/admin/AdminPanel";
import BriefingPanel from "@/features/briefing/BriefingPanel";
import ChurnPanel from "@/features/churn/ChurnPanel";
import CommercialPanel from "@/features/commercial/CommercialPanel";
import Copilot from "@/features/copilote/Copilot";
import ClientSpace from "@/features/espace-client/ClientSpace";
import DocumentsOCR from "@/features/ocr/DocumentsOCR";
import StockPanel from "@/features/stock/StockPanel";
import SupplyCard from "@/features/stock/SupplyCard";
import TachesPanel from "@/features/taches/TachesPanel";
import { Alerte, ChartCard, MiniGauge, PanelCard } from "./composants/Cartes";
import { fInt, fMoney } from "./format";
import type { TableauDeBord } from "./useTableauDeBord";

export default function ContenuVue({ t }: { t: TableauDeBord }) {
  const { view, setView, kpis, filtersData, isClient, session, clientFocus, gauges, onExpand, g } = t;
  const { selectedClients, filterPayload } = t.filtres;
  const { rMonthly, rFlow, rYoY, rSeason, rAging, rCash, rPareto, rPayMix, rProd, rFourn, rPriority } = g;

  return (
    <div className="view-grid" key={view}>
      {/* SYNTHÈSE — page d'accueil. Elle répond à une seule question :
          « qu'est-ce qui demande mon attention aujourd'hui ? ». D'abord ce
          qui appelle une décision, ensuite la tendance, enfin la santé. */}
      {view === "synthese" && <>
        <div style={{ gridColumn: "span 12", display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(215px,1fr))", gap: 12 }}>
          <Alerte
            couleur="#DC2626"
            icone={<UserMinus size={16} />}
            titre="Clients sur le départ"
            valeur={`${kpis?.churn_anticipe?.n_au_dessus_de_0_5 ?? 0}`}
            detail={kpis?.churn_anticipe?.enjeu_total_dt
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

      </>}
      {/* Trois cartes au lieu de cinq. Le chiffre d'affaires annuel
          répétait ce que montre déjà le comparatif, et la distribution des
          montants de facture n'appelle aucune décision. */}
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
        <ChartCard title="Délais de paiement accordés" icon={<CalendarClock size={17} />} span={12} render={rAging} onExpand={onExpand} />
      </>}
      {view === "clients" && <>
        <PanelCard title="Vos principaux clients" icon={<Users size={17} />} span={7} hidden={clientFocus}>
          {/* La dernière colonne affichait « Score IA » et un nombre de 0 à
              100 que personne ne pouvait interpréter. Ce nombre traduit une
              réalité simple : le client bénéficie-t-il d'un délai de paiement
              long ? On l'écrit donc en clair. */}
          <div className="data-table"><div className="dt-head six"><span>#</span><span>Client</span><span>CA TTC</span><span>Part</span><span>Créances</span><span>Délai accordé</span></div>
            {(kpis?.top_clients || []).map(c => (<div className="dt-row six" key={c.rank}><span className="dt-rank">{c.rank}</span><span className="dt-name" title={c.client}>{c.nom || c.client}</span><span>{fMoney(c.revenue)}</span><span><span className="share-bar"><i style={{ width: `${Math.min(100, c.share)}%` }} /></span>{c.share.toFixed(1)}%</span><span className={c.risque ? "risk-tag" : "ok-tag"}>{c.risque ? fMoney(c.risque) : "—"}</span><span>{c.risk_score == null ? <span title="Trop peu de factures pour établir une habitude de paiement">Non établi</span> : <span className="score-pill" title={c.risk_score > 50 ? "Ce client règle habituellement à plus de 60 jours" : "Ce client règle habituellement sous 60 jours"} style={{ background: c.risk_score > 50 ? "rgba(239,68,68,0.15)" : "rgba(16,185,129,0.15)", color: c.risk_score > 50 ? "#EF4444" : "#10B981" }}>{c.risk_score > 50 ? "Long" : "Standard"}</span>}</span></div>))}
          </div>
        </PanelCard>
        <ChartCard title="Concentration du chiffre d'affaires" icon={<Layers size={17} />} span={5} render={rPareto} hidden={clientFocus} onExpand={onExpand} />
        <ChartCard title="Créances arrivant à échéance" icon={<Wallet size={17} />} span={7} render={rCash} onExpand={onExpand} />
        <ChartCard title="Modes de paiement" icon={<PieIcon size={17} />} span={5} render={rPayMix} onExpand={onExpand} />

        {/* Typologie — la seule vue qui parle de CATÉGORIES de clients.
            Le reste de l'onglet parle de clients nommés ; ici on regarde
            la clientèle par types, ce qui est l'échelle d'une politique
            commerciale. La colonne « menacés » vient du croisement avec
            le modèle de décrochage. */}
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
      {view === "produits" && <>
        <SupplyCard />
        <ChartCard title="Produits les plus vendus" icon={<Boxes size={17} />} span={7} h={260} render={rProd} onExpand={onExpand} />
        <ChartCard title="Principaux fournisseurs" icon={<Truck size={17} />} span={5} h={260} render={rFourn} onExpand={onExpand} />
      </>}

      {/* Rétention — le seul panneau PROSPECTIF du tableau de bord. Les
          autres vues décrivent ce qui s'est produit ; celle-ci estime ce
          qui va se produire, sur des clients encore actifs. Il occupe
          toute la largeur car sa lecture croise deux dimensions (risque
          et valeur du compte) qu'une demi-colonne écraserait. */}
      {view === "retention" && (
        <div style={{ gridColumn: "span 12" }}>
          <ChurnPanel clientNames={filtersData?.client_names} />
        </div>
      )}

      {/* Devis & marge — cycle commercial et rentabilité. Deux modèles
          appris sur données réelles, servis seulement si le registre les
          autorise : chacun affiche le motif de son refus plutôt qu'un
          tableau vide, car un classement non démontré orienterait le
          travail commercial sans le justifier. */}
      {view === "commercial" && !isClient && (
        <CommercialPanel />
      )}

      {/* Priorités — la sortie de la flotte d'agents. C'est la seule vue
          qui arbitre ENTRE les domaines : relancer un débiteur ou
          déstocker ? Aucun autre écran ne pose cette question, chacun
          restant dans son périmètre. */}
      {view === "priorites" && (
        <div style={{ gridColumn: "span 12" }}>
          <BriefingPanel filterPayload={filterPayload}
            peutConfier={!isClient} />
        </div>
      )}

      {/* Suivi des actions — le prolongement direct de Priorités : une
          alerte confiée devient une tâche, puis un résultat mesuré. */}
      {view === "taches" && !isClient && (
        <div style={{ gridColumn: "span 12" }}>
          <TachesPanel role={session?.role || "directeur"} />
        </div>
      )}

      {view === "copilot" && <Copilot filterPayload={filterPayload} />}
      {view === "stock" && !isClient && (
        <StockPanel
         
          selectedClient={selectedClients[0]}
          selectedClientName={selectedClients[0]
            ? (filtersData?.client_names?.[selectedClients[0]] ?? selectedClients[0])
            : undefined}
        />
      )}
      {view === "ocr" && <DocumentsOCR />}
      {view === "espace" && isClient && <ClientSpace />}
      {view === "admin" && !isClient && <AdminPanel />}
    </div>
  );
}
