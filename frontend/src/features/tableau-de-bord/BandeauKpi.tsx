"use client";

import {
  AlertTriangle, Boxes, Coins, Layers, Receipt, ShieldAlert, Target, Timer, Truck,
  Users, Wallet,
} from "lucide-react";
import { Stat } from "./composants/Cartes";
import { fInt, fMoney } from "./format";
import type { KPIs } from "./tableauDeBord.types";

function Evolution({ kpis }: { kpis: KPIs | null }) {
  const p = kpis?.periode_reference;
  const v = p?.evolution_pct ?? kpis?.yoy_growth ?? null;
  if (v == null) return <span>{p?.libelle ?? ""}</span>;
  return (
    <span className={v >= 0 ? "up" : "down"} title={p?.libelle}>
      {v >= 0 ? "▲" : "▼"} {Math.abs(v).toFixed(1)} % {p?.libelle_comparaison ?? "sur 12 mois"}
    </span>
  );
}

/**
 * Délai de paiement, avec son sens dit en clair.
 *
 * « Délai moyen accordé » ne disait pas qui attend qui, et la sous-ligne
 * « Fournisseurs : 57 j » laissait croire à une comparaison de même nature.
 * La tuile porte maintenant la moyenne PONDÉRÉE par le montant — la seule qui
 * ait un sens financier — et nomme le sens de chaque délai.
 */
function TuileDelai({ kpis, view }: { kpis: KPIs | null; view: string }) {
  const d = kpis?.delais;
  const accorde = d?.accorde_aux_clients.moyenne_ponderee_j ?? kpis?.dso_jours ?? null;
  const obtenu = d?.obtenu_des_fournisseurs.moyenne_ponderee_j ?? kpis?.dpo_jours ?? null;
  return (
    <Stat label="Délai accordé à vos clients" value={accorde}
      format={(n) => `${n.toFixed(0)} j`} icon={<Timer size={18} />} tone="t-cyan" trigger={view}
      sub={obtenu == null ? undefined
        : `Obtenu des fournisseurs : ${obtenu.toFixed(0)} j`} />
  );
}

export default function BandeauKpi({ view, kpis }: { view: string; kpis: KPIs | null }) {
  const clientsSub = ({
    "12m": "ayant acheté ces 12 derniers mois",
    annee: "ayant acheté cette année",
    tout: "depuis le début de l'historique",
    personnalisee: "ayant acheté sur la période choisie",
  } as Record<string, string>)[kpis?.periode_reference?.code ?? ""];
  return (
    <section className="kpi-bar">
      {view === "risque" ? <>
        <TuileDelai kpis={kpis} view={view} />
        <Stat label="Facturé au-delà de 60 j" value={kpis?.exposition_recente_dt ?? null} format={fMoney} icon={<ShieldAlert size={18} />} tone="t-red" trigger={view}
          sub={`dont ${fMoney(kpis?.exposition_recente_critique_dt)} au-delà de 90 j`} />
        <Stat label="Clients à surveiller" value={kpis?.nb_clients_risque_predit ?? null} format={fInt} icon={<AlertTriangle size={18} />} tone="t-amber" trigger={view}
          sub={`${fInt(kpis?.exposition_recente_count)} factures concernées`} />
        <Stat label="Créances concernées" value={kpis?.montant_delai_sup_60j_ttc ?? null} format={fMoney} icon={<Wallet size={18} />} tone="t-purple" trigger={view} />
      </> : view === "clients" || view === "retention" ? <>
        <Stat label="Clients actifs" value={kpis?.nb_clients ?? null} format={fInt} icon={<Users size={18} />} tone="t-purple" trigger={view}
          sub={clientsSub} />
        <Stat label="Chiffre d'affaires" value={kpis?.ca_total_ttc ?? null} format={fMoney} icon={<Coins size={18} />} tone="t-blue" trigger={view}
          sub={<Evolution kpis={kpis} />} />
        <Stat label="Poids des 5 premiers" value={kpis?.top_clients_revenue_share ?? null} format={(n) => `${n.toFixed(0)} %`} icon={<Layers size={18} />} tone="t-amber" trigger={view} />
        <Stat label="Panier moyen" value={kpis?.panier_moyen ?? null} format={fMoney} icon={<Receipt size={18} />} tone="t-cyan" trigger={view}
          sub={`${fInt(kpis?.nb_factures_vente)} factures`} />
      </> : view === "produits" || view === "stock" ? <>
        <Stat label="Achats" value={kpis?.achats_total_ttc ?? null} format={fMoney} icon={<Truck size={18} />} tone="t-amber" trigger={view}
          sub={`${fInt(kpis?.nb_fournisseurs)} fournisseurs`} />
        <Stat label="Marge brute" value={kpis?.marge_brute ?? null} format={fMoney} icon={<Target size={18} />} tone="t-green" trigger={view}
          sub={kpis?.taux_marge == null ? undefined : `${kpis?.taux_marge?.toFixed(1)} % du chiffre d'affaires`} />
        <Stat label="Références vendues" value={kpis?.nb_produits ?? null} format={fInt} icon={<Boxes size={18} />} tone="t-blue" trigger={view} />
        <Stat label="Chiffre d'affaires" value={kpis?.ca_total_ttc ?? null} format={fMoney} icon={<Coins size={18} />} tone="t-cyan" trigger={view} />
      </> : <>
        <Stat label="Chiffre d'affaires" value={kpis?.ca_total_ttc ?? null} format={fMoney} icon={<Coins size={18} />} tone="t-blue" trigger={view}
          sub={<Evolution kpis={kpis} />} />
        <Stat label="Marge brute" value={kpis?.marge_brute ?? null} format={fMoney} icon={<Target size={18} />} tone="t-green" trigger={view}
          sub={kpis?.taux_marge == null ? undefined : `${kpis?.taux_marge?.toFixed(1)} % du chiffre d'affaires`} />
        <TuileDelai kpis={kpis} view={view} />
        <Stat label="Clients actifs" value={kpis?.nb_clients ?? null} format={fInt} icon={<Users size={18} />} tone="t-purple" trigger={view}
          sub={clientsSub ?? `5 premiers : ${(kpis?.top_clients_revenue_share ?? 0).toFixed(0)} % du CA`} />
      </>}
    </section>
  );
}
