"use client";

/**
 * Vue — bandeau d'indicateurs CONTEXTUEL.
 *
 * Huit indicateurs identiques s'affichaient sur toutes les pages : puisqu'ils
 * ne changeaient jamais, rien n'indiquait lesquels comptaient. Quatre
 * suffisent, et ils suivent l'onglet ouvert.
 */
import {
  AlertTriangle, Boxes, Coins, Layers, Receipt, ShieldAlert, Target, Timer, Truck,
  Users, Wallet,
} from "lucide-react";
import { Stat } from "./composants/Cartes";
import { fInt, fMoney } from "./format";
import type { KPIs } from "./tableauDeBord.types";

export default function BandeauKpi({ view, kpis }: { view: string; kpis: KPIs | null }) {
  return (
    <section className="kpi-bar">
      {view === "risque" ? <>
        <Stat label="Délai moyen accordé" value={kpis?.dso_jours ?? null} format={(n) => `${n.toFixed(0)} j`} icon={<Timer size={18} />} tone="t-cyan" trigger={view}
          sub={`Fournisseurs : ${(kpis?.dpo_jours ?? 0).toFixed(0)} j`} />
        <Stat label="Facturé au-delà de 60 j" value={kpis?.exposition_recente_dt ?? null} format={fMoney} icon={<ShieldAlert size={18} />} tone="t-red" trigger={view}
          sub={`dont ${fMoney(kpis?.exposition_recente_critique_dt)} au-delà de 90 j`} />
        <Stat label="Clients à surveiller" value={kpis?.nb_clients_risque_predit ?? null} format={fInt} icon={<AlertTriangle size={18} />} tone="t-amber" trigger={view}
          sub={`${fInt(kpis?.exposition_recente_count)} factures concernées`} />
        <Stat label="Créances concernées" value={kpis?.montant_risque_ttc ?? null} format={fMoney} icon={<Wallet size={18} />} tone="t-purple" trigger={view} />
      </> : view === "clients" || view === "retention" ? <>
        <Stat label="Clients actifs" value={kpis?.nb_clients ?? null} format={fInt} icon={<Users size={18} />} tone="t-purple" trigger={view} />
        <Stat label="Chiffre d'affaires" value={kpis?.ca_total_ttc ?? null} format={fMoney} icon={<Coins size={18} />} tone="t-blue" trigger={view}
          sub={<span className={(kpis?.yoy_growth ?? 0) >= 0 ? "up" : "down"}>{(kpis?.yoy_growth ?? 0) >= 0 ? "▲" : "▼"} {Math.abs(kpis?.yoy_growth ?? 0).toFixed(1)} % sur 12 mois</span>} />
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
          sub={<span className={(kpis?.yoy_growth ?? 0) >= 0 ? "up" : "down"}>{(kpis?.yoy_growth ?? 0) >= 0 ? "▲" : "▼"} {Math.abs(kpis?.yoy_growth ?? 0).toFixed(1)} % sur 12 mois</span>} />
        <Stat label="Marge brute" value={kpis?.marge_brute ?? null} format={fMoney} icon={<Target size={18} />} tone="t-green" trigger={view}
          sub={kpis?.taux_marge == null ? undefined : `${kpis?.taux_marge?.toFixed(1)} % du chiffre d'affaires`} />
        <Stat label="Délai moyen accordé" value={kpis?.dso_jours ?? null} format={(n) => `${n.toFixed(0)} j`} icon={<Timer size={18} />} tone="t-cyan" trigger={view}
          sub={`Fournisseurs : ${(kpis?.dpo_jours ?? 0).toFixed(0)} j`} />
        <Stat label="Clients actifs" value={kpis?.nb_clients ?? null} format={fInt} icon={<Users size={18} />} tone="t-purple" trigger={view}
          sub={`5 premiers : ${(kpis?.top_clients_revenue_share ?? 0).toFixed(0)} % du CA`} />
      </>}
    </section>
  );
}
