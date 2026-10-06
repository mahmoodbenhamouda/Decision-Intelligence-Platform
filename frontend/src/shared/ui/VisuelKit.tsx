"use client";

import type { ReactNode } from "react";
import { AlertOctagon, AlertTriangle, CheckCircle2, Info } from "lucide-react";

export const INK = {
  primary: "#16204A",
  secondary: "#5A6A8C",
  muted: "#93A0BC",
  grid: "rgba(26,35,72,0.07)",
  border: "rgba(26,35,72,0.09)",
};

export const BLEU = ["#C9D6FA", "#8FAAF3", "#5580EE", "#2F5BEA", "#2342B8"];

export const GRAVITE: Record<string, { couleur: string; fond: string; label: string; icone: ReactNode }> = {
  critique: { couleur: "#D03B3B", fond: "rgba(208,59,59,0.10)", label: "Urgent", icone: <AlertOctagon size={13} /> },
  haute: { couleur: "#EC835A", fond: "rgba(236,131,90,0.13)", label: "Prioritaire", icone: <AlertTriangle size={13} /> },
  moyenne: { couleur: "#E0A10F", fond: "rgba(250,178,25,0.15)", label: "À suivre", icone: <Info size={13} /> },
  faible: { couleur: "#0CA30C", fond: "rgba(12,163,12,0.10)", label: "Sous contrôle", icone: <CheckCircle2 size={13} /> },
};

export function fMoney(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  const a = Math.abs(v);
  if (a >= 1e6) return `${(v / 1e6).toFixed(2).replace(".", ",")} M DT`;
  if (a >= 1e3) return `${Math.round(v / 1e3)} K DT`;
  return `${Math.round(v)} DT`;
}
export function fAxe(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e6) return `${(v / 1e6).toFixed(1).replace(".", ",")} M`;
  if (a >= 1e3) return `${Math.round(v / 1e3)} K`;
  return `${Math.round(v)}`;
}
export function tronquer(t: string | undefined | null, n = 26): string {
  const s = (t || "").trim();
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

export const INFOBULLE = {
  borderRadius: 10,
  border: "1px solid rgba(26,35,72,0.12)",
  background: "rgba(255,255,255,0.98)",
  color: INK.primary,
  fontSize: 12,
  boxShadow: "0 8px 24px rgba(26,35,72,0.14)",
  padding: "8px 11px",
} as const;

export function BadgeGravite({ severite }: { severite?: string }) {
  const g = GRAVITE[severite || "moyenne"] || GRAVITE.moyenne;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 5,
      background: g.fond, color: INK.primary, borderRadius: 999,
      padding: "2px 9px 2px 7px", fontSize: "0.7rem", fontWeight: 700, whiteSpace: "nowrap",
    }}>
      <span style={{ color: g.couleur, display: "inline-flex" }}>{g.icone}</span>{g.label}
    </span>
  );
}

export function TuileChiffre({ icone, label, valeur, detail, accent = BLEU[3] }: {
  icone: ReactNode; label: string; valeur: string; detail?: string; accent?: string;
}) {
  return (
    <div className="chart-card" style={{ padding: "14px 16px", gap: 4 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{
          width: 30, height: 30, borderRadius: 9, display: "grid", placeItems: "center",
          background: `${accent}14`, color: accent,
        }}>{icone}</span>
        <span style={{ fontSize: "0.74rem", fontWeight: 700, color: INK.secondary }}>{label}</span>
      </div>
      <div style={{ fontSize: "1.65rem", fontWeight: 800, color: INK.primary, lineHeight: 1.15, marginTop: 6 }}>
        {valeur}
      </div>
      {detail && <div style={{ fontSize: "0.72rem", color: INK.muted }}>{detail}</div>}
    </div>
  );
}

export function Carte({ titre, sousTitre, icone, children, span = 12, droite }: {
  titre: string; sousTitre?: string; icone?: ReactNode; children: ReactNode;
  span?: number; droite?: ReactNode;
}) {
  return (
    <div className="chart-card" style={{ gridColumn: `span ${span}`, padding: "16px 18px 14px" }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 10, marginBottom: 10 }}>
        <div>
          <div className="card-label" style={{ display: "flex", alignItems: "center", gap: 7 }}>
            {icone}{titre}
          </div>
          {sousTitre && (
            <div style={{ fontSize: "0.74rem", color: INK.muted, marginTop: 3, textTransform: "none" }}>
              {sousTitre}
            </div>
          )}
        </div>
        {droite}
      </div>
      {children}
    </div>
  );
}

export function Legende({ items }: { items: { couleur: string; label: string }[] }) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 14, marginTop: 8 }}>
      {items.map(i => (
        <span key={i.label} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: "0.72rem", color: INK.secondary }}>
          <span style={{ width: 10, height: 10, borderRadius: 3, background: i.couleur }} />{i.label}
        </span>
      ))}
    </div>
  );
}

export function Grille({ children }: { children: ReactNode }) {
  return (
    <div className="vk-grille" style={{ gridColumn: "span 12", display: "grid", gridTemplateColumns: "repeat(12, minmax(0, 1fr))", gap: 14 }}>
      {children}
    </div>
  );
}

export function RangeeTuiles({ children }: { children: ReactNode }) {
  return (
    <div style={{ gridColumn: "span 12", display: "grid", gap: 14, gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))" }}>
      {children}
    </div>
  );
}

export function Vide({ texte }: { texte: string }) {
  return <p className="muted-note" style={{ padding: "18px 4px" }}>{texte}</p>;
}
