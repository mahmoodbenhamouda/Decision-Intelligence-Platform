"use client";

import { CalendarRange } from "lucide-react";
import { LIBELLE_PERIODE, type Filtres } from "./useFiltres";

const CHOIX = ["12m", "annee", "tout"] as const;

/**
 * Période sur laquelle portent les indicateurs. Par défaut : les 12 derniers
 * mois — un directeur veut savoir où il en est maintenant, pas le cumul depuis
 * 2017. Une année ou des dates choisies dans les filtres priment sur ce choix.
 */
export default function SelecteurPeriode({ f }: { f: Filtres }) {
  if (f.periodePersonnalisee) {
    return (
      <span className="vk-chip" title="Une année ou des dates sont choisies dans les filtres : elles priment">
        <CalendarRange size={12} /> Période choisie dans les filtres
      </span>
    );
  }
  return (
    <div className="vk-onglets" role="radiogroup" aria-label="Période des indicateurs">
      {CHOIX.map(c => (
        <button key={c} role="radio" aria-checked={f.periode === c}
          className={`vk-onglet${f.periode === c ? " actif" : ""}`}
          onClick={() => f.setPeriode(c)}>
          {c === "12m" && <CalendarRange size={13} />}{LIBELLE_PERIODE[c]}
        </button>
      ))}
    </div>
  );
}
