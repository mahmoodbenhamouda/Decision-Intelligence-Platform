"use client";

/**
 * Vue — briques visuelles du tableau de bord : tuile KPI animée, carte de
 * graphe agrandissable, carte de panneau, tuile d'alerte, jauge.
 */
import React, { useEffect, useRef, useState } from "react";
import { PolarAngleAxis, RadialBar, RadialBarChart, ResponsiveContainer } from "recharts";
import { Maximize2 } from "lucide-react";
import type { CarteAgrandie } from "../tableauDeBord.types";

/* ── Count-up hook ── */
function useCountUp(target: number, trigger: unknown) {
  const [val, setVal] = useState(target || 0);
  const ref = useRef(target || 0);
  useEffect(() => {
    const start = ref.current, end = target || 0, t0 = performance.now(), dur = 750;
    let raf = 0;
    const tick = (t: number) => {
      const p = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - p, 3), cur = start + (end - start) * e;
      setVal(cur); if (p < 1) raf = requestAnimationFrame(tick); else ref.current = end;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, trigger]);
  return val;
}

/* ── KPI stat card (with count-up) ── */
export function Stat({ label, value, format, icon, tone, sub, trigger, title }: {
  label: string; value: number | null; format: (n: number) => string; icon: React.ReactNode; tone: string; sub?: React.ReactNode; trigger: unknown; title?: string;
}) {
  const shown = useCountUp(value ?? 0, trigger);
  return (
    <div className={`kpi ${tone}`} title={title}>
      <div className="kpi-icon">{icon}</div>
      <div className="kpi-meta">
        <span className="kpi-label">{label}</span>
        <span className="kpi-value">{value == null ? "N/A" : format(shown)}</span>
        {sub && <span className="kpi-sub">{sub}</span>}
      </div>
    </div>
  );
}

/* ── Chart card (expandable) ── */
export function ChartCard({ title, icon, render, h = 232, span = 6, hint, hidden, onExpand }: {
  title: string; icon: React.ReactNode; render: (h: number) => React.ReactNode; h?: number; span?: number;
  hint?: string; hidden?: boolean; onExpand: (c: CarteAgrandie) => void;
}) {
  if (hidden) return null;
  return (
    <div className="chart-card" style={{ gridColumn: `span ${span}` }}>
      <div className="card-header">
        <span className="card-label">{title}</span>
        <div className="card-tools">
          <button className="expand-btn" title="Agrandir" onClick={() => onExpand({ title, render })}><Maximize2 size={14} /></button>
          <div className="card-icon">{icon}</div>
        </div>
      </div>
      {hint && <p className="chart-hint">{hint}</p>}
      <div className="chart-body">{render(h)}</div>
    </div>
  );
}
export function PanelCard({ title, icon, children, span = 6, hidden }: { title: string; icon: React.ReactNode; children: React.ReactNode; span?: number; hidden?: boolean; }) {
  if (hidden) return null;
  return (
    <div className="chart-card" style={{ gridColumn: `span ${span}` }}>
      <div className="card-header"><span className="card-label">{title}</span><div className="card-icon">{icon}</div></div>
      <div className="chart-body">{children}</div>
    </div>
  );
}
/** Tuile d'alerte de la page d'accueil. Cliquable : chaque chiffre mène à
 *  l'onglet qui permet d'agir dessus. Un indicateur qu'on ne peut pas suivre
 *  jusqu'à une action n'a pas sa place sur une page d'accueil. */
export function Alerte({ couleur, icone, titre, valeur, detail, onClick }: {
  couleur: string; icone: React.ReactNode; titre: string;
  valeur: string; detail: string; onClick?: () => void;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        textAlign: "left", cursor: onClick ? "pointer" : "default", width: "100%",
        border: "1px solid rgba(26,35,72,0.09)", borderLeft: `4px solid ${couleur}`,
        borderRadius: 13, padding: "13px 15px",
        background: "rgba(255,255,255,0.62)",
        transition: "transform .15s ease, box-shadow .15s ease",
      }}
      onMouseEnter={e => {
        e.currentTarget.style.transform = "translateY(-2px)";
        e.currentTarget.style.boxShadow = "0 8px 22px rgba(26,35,72,0.10)";
      }}
      onMouseLeave={e => {
        e.currentTarget.style.transform = "none";
        e.currentTarget.style.boxShadow = "none";
      }}
    >
      <span style={{ display: "flex", alignItems: "center", gap: 7, color: couleur, marginBottom: 6 }}>
        {icone}<span style={{ fontSize: "0.76rem", fontWeight: 700 }}>{titre}</span>
      </span>
      <div style={{ fontSize: "1.5rem", fontWeight: 800, color: "#16204A", lineHeight: 1.12 }}>{valeur}</div>
      <div style={{ fontSize: "0.72rem", color: "#64748B", marginTop: 3 }}>{detail}</div>
    </button>
  );
}

export function Empty() { return <p className="muted-note">Données insuffisantes.</p>; }
export function MiniGauge({ value, label, color }: { value: number; label: string; color: string; }) {
  const data = [{ name: label, value, fill: color }];
  return (
    <div className="mini-gauge">
      <ResponsiveContainer width="100%" height={108}>
        <RadialBarChart innerRadius="66%" outerRadius="100%" data={data} startAngle={90} endAngle={-270}>
          <PolarAngleAxis type="number" domain={[0, 100]} tick={false} />
          <RadialBar background={{ fill: "rgba(26,35,72,0.06)" }} dataKey="value" cornerRadius={8} />
        </RadialBarChart>
      </ResponsiveContainer>
      <div className="gauge-center" style={{ color }}>{value.toFixed(0)}%</div>
      <span className="gauge-label">{label}</span>
    </div>
  );
}
