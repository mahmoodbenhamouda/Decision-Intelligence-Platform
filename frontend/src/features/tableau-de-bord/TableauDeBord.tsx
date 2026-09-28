"use client";

/**
 * TableauDeBord — le cockpit : barre latérale (onglets + filtres), en-tête,
 * bandeau d'indicateurs, contenu de l'onglet ouvert, graphe agrandi et
 * mascotte flottante. Toute la logique est dans `useTableauDeBord`.
 */
import { Activity, RefreshCw, Users, X } from "lucide-react";
import FloatingCompanion from "@/shared/avatar/FloatingCompanion";
import BarreLaterale, { BoutonMenu } from "@/shared/ui/BarreLaterale";
import BandeauKpi from "./BandeauKpi";
import ContenuVue from "./ContenuVue";
import EcranEmploye from "./EcranEmploye";
import PanneauFiltres from "./PanneauFiltres";
import { useTableauDeBord } from "./useTableauDeBord";
import { SANS_KPI } from "./vues";

export default function TableauDeBord() {
  const t = useTableauDeBord();
  const {
    session, isClient, isEmploye, filtres, view, setView, spot, setSpot,
    barreRepliee, setBarreRepliee, menuMobile, setMenuMobile,
    kpis, filtersData, loading, recharger, onglets, titreVue, clientFocus, deconnecter,
  } = t;

  if (!kpis && loading && !isEmploye) return (<div className="loader-container"><div className="spinner" /><p className="muted-note">Chargement des données financières…</p></div>);

  // ── Écran de l'employé : ses tâches, rien d'autre ──
  if (isEmploye) return <EcranEmploye session={session} />;

  return (
    <div className="cockpit shell-lateral">
      <BarreLaterale
        onglets={onglets}
        vue={view}
        onVue={setView}
        replie={barreRepliee}
        onReplie={setBarreRepliee}
        ouverteMobile={menuMobile}
        onFermerMobile={() => setMenuMobile(false)}
        nomCompte={session?.fullName || (isClient ? `Client ${session?.clientCode ?? ""}` : "Directeur")}
        sousTitreCompte={`${session?.email || ""}${session?.clientCode ? ` · code ${session.clientCode}` : ""}`}
        estClient={isClient}
        onDeconnexion={() => void deconnecter()}
        nFiltresActifs={filtres.nFiltresActifs}
        resumeFiltres={filtres.activeFilterText}
        onReinitialiser={filtres.clearAll}
        filtres={<PanneauFiltres f={filtres} filtersData={filtersData} isClient={isClient} />}
      />

      <div className="shell-colonne">
      <nav className="top-navbar">
        <div className="brand-block">
          <BoutonMenu onClick={() => setMenuMobile(true)} />
          <div className="barre-titre">
            <b>{titreVue}</b>
            <span><Activity size={11} style={{ verticalAlign: "-1px" }} /> {filtres.activeFilterText}</span>
          </div>
        </div>
        <div className="nav-actions">
          <button className="icon-button" onClick={recharger} title="Rafraîchir"><RefreshCw size={17} className={loading ? "spin-icon" : ""} /></button>
        </div>
      </nav>

      <main className="cockpit-main">

        {/* Bandeau contextuel : il suit l'onglet ouvert et disparaît là où il
            n'a rien à dire (tâches, copilote, documents, administration,
            espace client). */}
        {!SANS_KPI.includes(view) && <BandeauKpi view={view} kpis={kpis} />}

        <section className="view-area">
          {clientFocus && (view === "clients" || view === "risque") && (
            <div className="focus-banner"><Users size={15} /><span>Vue centrée sur <b>{filtres.selectedClients.length} client(s)</b> — les analyses inter-clients (top clients, Pareto, priorité, entonnoir) sont masquées.</span></div>
          )}
          <ContenuVue t={t} />
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

      {/* Mascotte Flottante Globale accessible partout dans l'application */}
      <FloatingCompanion onOpenChat={() => setView("copilot")} />
    </div>
  );
}
