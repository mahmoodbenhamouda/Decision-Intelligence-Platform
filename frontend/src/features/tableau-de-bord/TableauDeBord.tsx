"use client";

import { Activity, RefreshCw, Users, X } from "lucide-react";
import { FournisseurFiltres } from "@/core/filtres/contexteFiltres";
import FloatingCompanion from "@/shared/avatar/FloatingCompanion";
import BarreLaterale, { BoutonMenu } from "@/shared/ui/BarreLaterale";
import BandeauKpi from "./BandeauKpi";
import ContenuVue from "./ContenuVue";
import EcranEmploye from "./EcranEmploye";
import PanneauFiltres from "./PanneauFiltres";
import SelecteurPeriode from "./SelecteurPeriode";
import { useTableauDeBord } from "./useTableauDeBord";
import { SANS_KPI, SANS_PERIODE } from "./vues";

export default function TableauDeBord() {
  const t = useTableauDeBord();
  const {
    session, isEmploye, filtres, view, setView, spot, setSpot,
    barreRepliee, setBarreRepliee, menuMobile, setMenuMobile,
    kpis, filtersData, loading, recharger, groupes, titreVue, etapeVue, clientFocus, deconnecter,
  } = t;

  if (!kpis && loading && !isEmploye) return (<div className="loader-container"><div className="spinner" /><p className="muted-note">Chargement des données financières…</p></div>);

  if (isEmploye) return <EcranEmploye session={session} />;

  return (
    <div className="cockpit shell-lateral">
      <BarreLaterale
        groupes={groupes}
        vue={view}
        onVue={setView}
        replie={barreRepliee}
        onReplie={setBarreRepliee}
        ouverteMobile={menuMobile}
        onFermerMobile={() => setMenuMobile(false)}
        nomCompte={session?.fullName || "Directeur"}
        sousTitreCompte={session?.email || ""}
        onDeconnexion={() => void deconnecter()}
        nFiltresActifs={filtres.nFiltresActifs}
        resumeFiltres={filtres.activeFilterText}
        onReinitialiser={filtres.clearAll}
        filtres={<PanneauFiltres f={filtres} filtersData={filtersData} />}
      />

      <div className="shell-colonne">
      <nav className="top-navbar">
        <div className="brand-block">
          <BoutonMenu onClick={() => setMenuMobile(true)} />
          <div className="barre-titre">
            <b>{etapeVue ? `${etapeVue} · ${titreVue}` : titreVue}</b>
            <span><Activity size={11} style={{ verticalAlign: "-1px" }} /> {filtres.activeFilterText}</span>
          </div>
        </div>
        <div className="nav-actions">
          {!SANS_PERIODE.includes(view) && <SelecteurPeriode f={filtres} />}
          <button className="icon-button" onClick={recharger} title="Rafraîchir"><RefreshCw size={17} className={loading ? "spin-icon" : ""} /></button>
        </div>
      </nav>

      <main className="cockpit-main">

        {!SANS_KPI.includes(view) && <BandeauKpi view={view} kpis={kpis} />}

        <section className="view-area">
          {clientFocus && (view === "clients" || view === "risque") && (
            <div className="focus-banner"><Users size={15} /><span>Vue centrée sur <b>{filtres.selectedClients.length} client(s)</b> — les analyses inter-clients (top clients, Pareto, priorité, entonnoir) sont masquées.</span></div>
          )}
          <FournisseurFiltres valeur={filtres.filterPayload as unknown as Record<string, unknown>}>
            <ContenuVue t={t} />
          </FournisseurFiltres>
        </section>
      </main>
      </div>

      {spot && (
        <div className="spotlight-backdrop" onClick={() => setSpot(null)}>
          <div className="spotlight-panel" onClick={e => e.stopPropagation()}>
            <div className="card-header"><span className="card-label">{spot.title}</span><button className="expand-btn" onClick={() => setSpot(null)}><X size={18} /></button></div>
            <div className="spotlight-body">{spot.render(window.innerHeight * 0.6)}</div>
          </div>
        </div>
      )}

      <FloatingCompanion onOpenChat={() => setView("copilot")} />
    </div>
  );
}
