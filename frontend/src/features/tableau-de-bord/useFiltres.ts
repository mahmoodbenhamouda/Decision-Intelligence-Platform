"use client";

import { useMemo, useState } from "react";
import type { FiltresPayload } from "./tableauDeBord.types";

export const LIBELLE_PERIODE: Record<string, string> = {
  "12m": "12 derniers mois", annee: "Année en cours", tout: "Tout l'historique",
};

export function useFiltres() {
  const [selectedYears, setSelectedYears] = useState<number[]>([]);
  const [selectedClients, setSelectedClients] = useState<string[]>([]);
  const [fidelityFilter, setFidelityFilter] = useState("Tous");
  const [dateStart, setDateStart] = useState(""); const [dateEnd, setDateEnd] = useState("");
  const [selectedPaymentModes, setSelectedPaymentModes] = useState<string[]>([]);
  const [riskLevel, setRiskLevel] = useState("Tous");
  // Période de référence quand aucune année ni date n'est choisie : 12 derniers mois.
  const [periode, setPeriode] = useState("12m");
  const [minAmount, setMinAmount] = useState<number | "">(""); const [maxAmount, setMaxAmount] = useState<number | "">("");

  const filterPayload: FiltresPayload = useMemo(() => ({
    selected_years: selectedYears, selected_clients: selectedClients, fidelity_filter: fidelityFilter,
    date_start: dateStart || null, date_end: dateEnd || null, payment_modes: selectedPaymentModes,
    risk_level: riskLevel, min_amount: minAmount === "" ? null : minAmount, max_amount: maxAmount === "" ? null : maxAmount,
    periode,
  }), [selectedYears, selectedClients, fidelityFilter, dateStart, dateEnd, selectedPaymentModes, riskLevel, minAmount, maxAmount, periode]);

  /** Une année ou des dates choisies à la main priment sur la période de référence. */
  const periodePersonnalisee = selectedYears.length > 0 || !!dateStart || !!dateEnd;

  const activeFilterText = useMemo(() => {
    const p: string[] = [];
    if (!selectedYears.length && !dateStart && !dateEnd) p.push(LIBELLE_PERIODE[periode] ?? periode);
    if (selectedYears.length) p.push(selectedYears.join(", "));
    if (dateStart || dateEnd) p.push(`Période: ${dateStart || "..."} → ${dateEnd || "..."}`);
    if (selectedClients.length) p.push(`${selectedClients.length} client(s)`);
    if (fidelityFilter !== "Tous") p.push(fidelityFilter);
    if (selectedPaymentModes.length) p.push(`${selectedPaymentModes.length} paiement(s)`);
    if (riskLevel !== "Tous") p.push(`Risque: ${riskLevel}`);
    if (minAmount !== "" || maxAmount !== "") p.push(`Montant: ${minAmount || 0} - ${maxAmount || "Max"}`);
    return p.join("  •  ");
  }, [selectedYears, dateStart, dateEnd, selectedClients, fidelityFilter, selectedPaymentModes, riskLevel, minAmount, maxAmount, periode]);

  const nFiltresActifs = selectedYears.length + selectedClients.length
    + selectedPaymentModes.length
    + (fidelityFilter !== "Tous" ? 1 : 0) + (riskLevel !== "Tous" ? 1 : 0)
    + (dateStart ? 1 : 0) + (dateEnd ? 1 : 0)
    + (minAmount !== "" ? 1 : 0) + (maxAmount !== "" ? 1 : 0);

  const toggleYear = (y: number) => setSelectedYears(p => p.includes(y) ? p.filter(i => i !== y) : [...p, y]);
  const toggleClient = (c: string) => setSelectedClients(p => p.includes(c) ? p.filter(i => i !== c) : [...p, c]);
  const togglePay = (m: string) => setSelectedPaymentModes(p => p.includes(m) ? p.filter(i => i !== m) : [...p, m]);
  const clearAll = () => { setSelectedYears([]); setSelectedClients([]); setFidelityFilter("Tous"); setDateStart(""); setDateEnd(""); setSelectedPaymentModes([]); setRiskLevel("Tous"); setMinAmount(""); setMaxAmount(""); setPeriode("12m"); };

  return {
    selectedYears, selectedClients, fidelityFilter, setFidelityFilter, dateStart, setDateStart,
    dateEnd, setDateEnd, selectedPaymentModes, riskLevel, setRiskLevel, minAmount, setMinAmount,
    maxAmount, setMaxAmount, filterPayload, activeFilterText, nFiltresActifs,
    periode, setPeriode, periodePersonnalisee,
    toggleYear, toggleClient, togglePay, clearAll,
  };
}

export type Filtres = ReturnType<typeof useFiltres>;
