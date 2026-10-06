"use client";

import { X } from "lucide-react";
import type { FiltersData } from "./tableauDeBord.types";
import type { Filtres } from "./useFiltres";

export default function PanneauFiltres({ f, filtersData }: {
  f: Filtres; filtersData: FiltersData | null;
}) {
  return (
    <>
    <div className="bl-champ">
      <label>Période</label>
      <div className="bl-controle">
        <input type="date" value={f.dateStart} onChange={e => f.setDateStart(e.target.value)} className="mini" />
      </div>
      <div className="bl-controle">
        <input type="date" value={f.dateEnd} onChange={e => f.setDateEnd(e.target.value)} className="mini" />
      </div>
    </div>

    <div className="bl-champ">
      <label>Années</label>
      <div className="bl-controle">
        <select onChange={e => f.toggleYear(Number(e.target.value))} value="" className="mini">
          <option value="" disabled>+ Ajouter une année</option>
          {filtersData?.available_years.map(y => <option key={y} value={y}>{y}</option>)}
        </select>
      </div>
      {f.selectedYears.length > 0 && (
        <div className="bl-chips">
          {f.selectedYears.map(y => (
            <span key={y} className="bl-chip"><span>{y}</span>
              <button onClick={() => f.toggleYear(y)} title="Retirer"><X size={11} /></button>
            </span>
          ))}
        </div>
      )}
    </div>

    <div className="bl-champ">
      <label>Clients</label>
      <div className="bl-controle">
        <select onChange={e => f.toggleClient(e.target.value)} value="" className="mini">
          <option value="" disabled>+ Ajouter un client</option>
          {filtersData?.available_clients.map(c => (
            <option key={c} value={c}>{filtersData?.client_names?.[c] ?? c}</option>
          ))}
        </select>
      </div>
      {f.selectedClients.length > 0 && (
        <div className="bl-chips">
          {f.selectedClients.map(c => (
            <span key={c} className="bl-chip" title={filtersData?.client_names?.[c] ?? c}>
              <span>{filtersData?.client_names?.[c] ?? c}</span>
              <button onClick={() => f.toggleClient(c)} title="Retirer"><X size={11} /></button>
            </span>
          ))}
        </div>
      )}
    </div>

    <div className="bl-champ">
      <label>Fidélité</label>
      <div className="bl-controle">
        <select value={f.fidelityFilter} onChange={e => f.setFidelityFilter(e.target.value)} className="mini">
          {filtersData?.fidelity_options.map(o => (
            <option key={o} value={o}>{o.includes("Tous") ? "Toutes" : o}</option>
          ))}
        </select>
      </div>
    </div>

    <div className="bl-champ">
      <label>Niveau de risque</label>
      <div className="bl-controle">
        <select value={f.riskLevel} onChange={e => f.setRiskLevel(e.target.value)} className="mini">
          {filtersData?.risk_levels?.map(r => (
            <option key={r} value={r}>{r.includes("Tous") ? "Tous" : r}</option>
          )) || <option>Tous</option>}
        </select>
      </div>
    </div>

    <div className="bl-champ">
      <label>Mode de paiement</label>
      <div className="bl-controle">
        <select onChange={e => f.togglePay(e.target.value)} value="" className="mini">
          <option value="" disabled>+ Ajouter un mode</option>
          {filtersData?.available_payment_modes?.map(m => <option key={m} value={m}>{m.trim()}</option>)}
        </select>
      </div>
      {f.selectedPaymentModes.length > 0 && (
        <div className="bl-chips">
          {f.selectedPaymentModes.map(m => (
            <span key={m} className="bl-chip"><span>{m.trim()}</span>
              <button onClick={() => f.togglePay(m)} title="Retirer"><X size={11} /></button>
            </span>
          ))}
        </div>
      )}
    </div>

    <div className="bl-champ">
      <label>Montant (DT)</label>
      <div className="bl-controle">
        <input type="number" placeholder="Minimum" value={f.minAmount} className="mini num"
          onChange={e => f.setMinAmount(e.target.value ? Number(e.target.value) : "")} />
      </div>
      <div className="bl-controle">
        <input type="number" placeholder="Maximum" value={f.maxAmount} className="mini num"
          onChange={e => f.setMaxAmount(e.target.value ? Number(e.target.value) : "")} />
      </div>
    </div>
  </>
  );
}
