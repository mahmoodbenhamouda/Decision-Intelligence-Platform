"use client";

/**
 * ViewModel — les filtres de la barre latérale.
 *
 * Porte chaque filtre, fabrique le corps envoyé à l'API (partagé avec le
 * briefing et le copilote), le résumé lisible affiché dans l'en-tête et le
 * nombre de filtres actifs affiché sur la barre repliée.
 */
import { useMemo, useState } from "react";
import type { FiltresPayload } from "./tableauDeBord.types";

export function useFiltres() {
  const [selectedYears, setSelectedYears] = useState<number[]>([]);
  const [selectedClients, setSelectedClients] = useState<string[]>([]);
  const [fidelityFilter, setFidelityFilter] = useState("Tous");
  const [dateStart, setDateStart] = useState(""); const [dateEnd, setDateEnd] = useState("");
  const [selectedPaymentModes, setSelectedPaymentModes] = useState<string[]>([]);
  const [riskLevel, setRiskLevel] = useState("Tous");
  const [minAmount, setMinAmount] = useState<number | "">(""); const [maxAmount, setMaxAmount] = useState<number | "">("");

  const filterPayload: FiltresPayload = useMemo(() => ({
    selected_years: selectedYears, selected_clients: selectedClients, fidelity_filter: fidelityFilter,
    date_start: dateStart || null, date_end: dateEnd || null, payment_modes: selectedPaymentModes,
    risk_level: riskLevel, min_amount: minAmount === "" ? null : minAmount, max_amount: maxAmount === "" ? null : maxAmount,
  }), [selectedYears, selectedClients, fidelityFilter, dateStart, dateEnd, selectedPaymentModes, riskLevel, minAmount, maxAmount]);

  const activeFilterText = useMemo(() => {
    const p: string[] = [];
    if (selectedYears.length) p.push(selectedYears.join(", "));
    if (dateStart || dateEnd) p.push(`Période: ${dateStart || "..."} → ${dateEnd || "..."}`);
    if (selectedClients.length) p.push(`${selectedClients.length} client(s)`);
    if (fidelityFilter !== "Tous") p.push(fidelityFilter);
    if (selectedPaymentModes.length) p.push(`${selectedPaymentModes.length} paiement(s)`);
    if (riskLevel !== "Tous") p.push(`Risque: ${riskLevel}`);
    if (minAmount !== "" || maxAmount !== "") p.push(`Montant: ${minAmount || 0} - ${maxAmount || "Max"}`);
    return p.length ? p.join("  •  ") : "Tous (aucun filtre)";
  }, [selectedYears, dateStart, dateEnd, selectedClients, fidelityFilter, selectedPaymentModes, riskLevel, minAmount, maxAmount]);

  // Nombre de filtres réellement actifs : c'est ce chiffre qui est affiché sur
  // la barre repliée, où les libellés ne sont plus lisibles.
  const nFiltresActifs = selectedYears.length + selectedClients.length
    + selectedPaymentModes.length
    + (fidelityFilter !== "Tous" ? 1 : 0) + (riskLevel !== "Tous" ? 1 : 0)
    + (dateStart ? 1 : 0) + (dateEnd ? 1 : 0)
    + (minAmount !== "" ? 1 : 0) + (maxAmount !== "" ? 1 : 0);

  const toggleYear = (y: number) => setSelectedYears(p => p.includes(y) ? p.filter(i => i !== y) : [...p, y]);
  const toggleClient = (c: string) => setSelectedClients(p => p.includes(c) ? p.filter(i => i !== c) : [...p, c]);
  const togglePay = (m: string) => setSelectedPaymentModes(p => p.includes(m) ? p.filter(i => i !== m) : [...p, m]);
  const clearAll = () => { setSelectedYears([]); setSelectedClients([]); setFidelityFilter("Tous"); setDateStart(""); setDateEnd(""); setSelectedPaymentModes([]); setRiskLevel("Tous"); setMinAmount(""); setMaxAmount(""); };

  return {
    selectedYears, selectedClients, fidelityFilter, setFidelityFilter, dateStart, setDateStart,
    dateEnd, setDateEnd, selectedPaymentModes, riskLevel, setRiskLevel, minAmount, setMinAmount,
    maxAmount, setMaxAmount, filterPayload, activeFilterText, nFiltresActifs,
    toggleYear, toggleClient, togglePay, clearAll,
  };
}

export type Filtres = ReturnType<typeof useFiltres>;
