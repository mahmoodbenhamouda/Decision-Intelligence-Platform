"use client";

import { Filter } from "lucide-react";

/** Affiché à la place d'une analyse que les filtres actifs rendent sans objet. */
export default function PanneauMasque({ motif, span = 12 }: { motif?: string; span?: number }) {
  return (
    <div className="chart-card" style={{
      gridColumn: `span ${span}`, display: "flex", gap: 12, alignItems: "flex-start",
      borderLeft: "4px solid #93A0BC", background: "rgba(147,160,188,0.06)",
    }}>
      <Filter size={18} style={{ color: "#5B6785", flexShrink: 0, marginTop: 2 }} />
      <div>
        <div style={{ fontWeight: 700, color: "#16204A", fontSize: "0.88rem" }}>
          Analyse masquée par vos filtres
        </div>
        <div style={{ fontSize: "0.8rem", color: "#5B6785", marginTop: 3, lineHeight: 1.5 }}>
          {motif || "Retirez les filtres pour l'afficher."}
        </div>
      </div>
    </div>
  );
}

/** Petit bandeau : la liste est restreinte aux clients du filtre. */
export function BadgeFiltreClients({ n }: { n?: number }) {
  if (!n) return null;
  return (
    <span className="vk-chip" title="La liste ne contient que les clients retenus par vos filtres">
      <Filter size={11} /> Filtré : {n} client{n > 1 ? "s" : ""}
    </span>
  );
}
