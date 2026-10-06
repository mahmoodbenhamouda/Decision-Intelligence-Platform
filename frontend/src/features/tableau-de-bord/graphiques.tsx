"use client";

import React from "react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Funnel, FunnelChart,
  LabelList, Legend, Line, Pie, PieChart, PolarAngleAxis, PolarGrid, Radar, RadarChart,
  ReferenceArea, ResponsiveContainer, Tooltip as RechartsTooltip, XAxis, YAxis,
} from "recharts";
import { Empty } from "./composants/Cartes";
import { fAxis, fInt, fMoney } from "./format";
import type { KPIs } from "./tableauDeBord.types";

const PIE_COLORS = ["#2F5BEA", "#10B981", "#8B5CF6", "#14C2D6", "#F59E0B", "#EF4444", "#EC4899", "#64748B"];
const TT = { borderRadius: 10, border: "1px solid rgba(26,35,72,0.12)", background: "rgba(255,255,255,0.97)", color: "#16204A", fontSize: 13, boxShadow: "0 8px 24px rgba(26,35,72,0.14)" } as const;

export type FluxMensuel = { period: string; ventes: number; achats: number; marge: number | null }[];

export type Graphe = (h: number) => React.ReactNode;

export function graphiques(kpis: KPIs | null, combinedFlow: FluxMensuel): Record<string, Graphe> {
  const rMonthly = (h: number) => {
    const base = kpis?.monthly_sales || [];
    if (!base.length) return <Empty />;
    const fc = kpis?.forecast_next || [];
    const data: { period: string; revenue: number | null; prevision: number | null }[] = [
      ...base.map(d => ({ period: d.period, revenue: d.revenue, prevision: null as number | null })),
      ...fc.map(d => ({ period: d.period, revenue: null as number | null, prevision: d.montant })),
    ];
    if (base.length && fc.length) data[base.length - 1].prevision = base[base.length - 1].revenue;
    // La période des indicateurs est surlignée sur l'historique complet.
    const ref = kpis?.periode_reference;
    const periodeDebut = ref?.debut ? ref.debut.slice(0, 7) : null;
    const periodeFin = ref?.fin ? ref.fin.slice(0, 7) : null;
    return (
      <ResponsiveContainer width="100%" height={h}>
        <AreaChart data={data} margin={{ top: 10, right: 12, left: 0, bottom: 0 }}>
          <defs><linearGradient id="gRev" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#2F5BEA" stopOpacity={0.45} /><stop offset="95%" stopColor="#2F5BEA" stopOpacity={0} /></linearGradient></defs>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(26,35,72,0.07)" vertical={false} />
          <XAxis dataKey="period" tick={{ fill: "#5A6A8C", fontSize: 11 }} axisLine={false} tickLine={false} minTickGap={24} />
          <YAxis tick={{ fill: "#5A6A8C", fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={fAxis} />
          <RechartsTooltip formatter={(v, n) => [fMoney(Number(v ?? 0)), n === "prevision" ? "Prévision IA" : "CA TTC"]} contentStyle={TT} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          {periodeDebut && periodeFin && (
            <ReferenceArea x1={periodeDebut} x2={periodeFin} fill="#2F5BEA" fillOpacity={0.06}
              label={{ value: kpis?.periode_reference?.libelle, position: "insideTopLeft", fill: "#5A6A8C", fontSize: 11 }} />
          )}
          <Area type="monotone" dataKey="revenue" name="CA TTC" stroke="#2F5BEA" strokeWidth={2.5} fill="url(#gRev)" connectNulls />
          <Area type="monotone" dataKey="prevision" name="Prévision IA (3 mois)" stroke="#8B5CF6" strokeWidth={2.5} strokeDasharray="5 4" fill="none" connectNulls />
        </AreaChart>
      </ResponsiveContainer>);
  };
  const rFlow = (h: number) => combinedFlow.length ? (
    <ResponsiveContainer width="100%" height={h}>
      <ComposedChart data={combinedFlow} margin={{ top: 10, right: 12, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(26,35,72,0.07)" vertical={false} />
        <XAxis dataKey="period" tick={{ fill: "#5A6A8C", fontSize: 11 }} axisLine={false} tickLine={false} minTickGap={24} />
        <YAxis tick={{ fill: "#5A6A8C", fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={fAxis} />
        <RechartsTooltip formatter={(v) => fMoney(Number(v ?? 0))} contentStyle={TT} /><Legend wrapperStyle={{ fontSize: 12 }} />
        <Bar dataKey="ventes" name="Ventes" fill="#2F5BEA" radius={[3, 3, 0, 0]} maxBarSize={20} />
        <Bar dataKey="achats" name="Achats" fill="#F59E0B" radius={[3, 3, 0, 0]} maxBarSize={20} />
        <Line type="monotone" dataKey="marge" name="Marge" stroke="#10B981" strokeWidth={2.5} dot={false} />
      </ComposedChart>
    </ResponsiveContainer>) : <Empty />;
  const rYoY = (h: number) => {
    const c = kpis?.yoy_comparison;
    if (!c?.data?.length) return <Empty />;
    return (
      <ResponsiveContainer width="100%" height={h}>
        <ComposedChart data={c.data} margin={{ top: 10, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(26,35,72,0.07)" vertical={false} />
          <XAxis dataKey="month" tick={{ fill: "#5A6A8C", fontSize: 11 }} axisLine={false} tickLine={false} />
          <YAxis tick={{ fill: "#5A6A8C", fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={fAxis} />
          <RechartsTooltip formatter={(v) => fMoney(Number(v ?? 0))} contentStyle={TT} /><Legend wrapperStyle={{ fontSize: 12 }} />
          <Line type="monotone" dataKey="precedente" name={String(c.previous_year ?? "N-1")} stroke="#64748B" strokeWidth={2} dot={false} connectNulls />
          <Line type="monotone" dataKey="courante" name={String(c.current_year ?? "N")} stroke="#2F5BEA" strokeWidth={2.6} dot={{ r: 2 }} connectNulls />
        </ComposedChart>
      </ResponsiveContainer>);
  };
  const rBridge = (h: number) => {
    const wf = kpis?.waterfall || [];
    if (wf.length >= 3) {
      const caHT = wf[0].value, achats = -wf[1].value, marge = wf[2].value;
      if (marge > 0 && caHT > 0) {
        const comp = [
          { name: "Marge brute", value: marge, fill: "#10B981" },
          { name: "Coût des achats", value: achats, fill: "#F59E0B" },
        ];
        return (
          <div style={{ position: "relative", height: h }}>
            <ResponsiveContainer width="100%" height={h}>
              <PieChart>
                <Pie data={comp} dataKey="value" nameKey="name" cx="50%" cy="46%" innerRadius="60%" outerRadius="86%" paddingAngle={2} startAngle={90} endAngle={-270} stroke="none">
                  {comp.map((d, i) => <Cell key={i} fill={d.fill} />)}
                </Pie>
                <RechartsTooltip formatter={(v, n) => [`${fMoney(Number(v))} · ${(Number(v) / caHT * 100).toFixed(0)}%`, String(n)]} contentStyle={TT} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
              </PieChart>
            </ResponsiveContainer>
            <div style={{ position: "absolute", top: `${h * 0.46}px`, left: 0, right: 0, textAlign: "center", transform: "translateY(-50%)", pointerEvents: "none" }}>
              <div style={{ fontSize: "1.25rem", fontWeight: 800, color: "var(--text-primary)" }}>{fMoney(caHT)}</div>
              <div style={{ fontSize: "0.68rem", letterSpacing: "0.05em", color: "var(--text-muted)", textTransform: "uppercase" }}>CA HT total</div>
              <div style={{ fontSize: "0.74rem", fontWeight: 700, color: "#10B981", marginTop: 2 }}>{(marge / caHT * 100).toFixed(0)}% de marge</div>
            </div>
          </div>);
      }
    }
    const base = kpis?.monthly_sales || [];
    if (!base.length) return <Empty />;
    let acc = 0;
    const data = base.map(m => ({ period: m.period, cumul: (acc += m.revenue) }));
    return (
      <ResponsiveContainer width="100%" height={h}>
        <AreaChart data={data} margin={{ top: 10, right: 12, left: 0, bottom: 0 }}>
          <defs><linearGradient id="gCum" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#10B981" stopOpacity={0.4} /><stop offset="95%" stopColor="#10B981" stopOpacity={0} /></linearGradient></defs>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(26,35,72,0.07)" vertical={false} />
          <XAxis dataKey="period" tick={{ fill: "#5A6A8C", fontSize: 10 }} axisLine={false} tickLine={false} minTickGap={24} />
          <YAxis tick={{ fill: "#5A6A8C", fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={fAxis} />
          <RechartsTooltip formatter={(v) => fMoney(Number(v ?? 0))} contentStyle={TT} />
          <Area type="monotone" dataKey="cumul" name="CA cumulé" stroke="#10B981" strokeWidth={2.5} fill="url(#gCum)" />
        </AreaChart>
      </ResponsiveContainer>);
  };
  const rYear = (h: number) => kpis?.yearly_sales?.length ? (
    <ResponsiveContainer width="100%" height={h}>
      <BarChart data={kpis.yearly_sales} margin={{ top: 10, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(26,35,72,0.07)" vertical={false} />
        <XAxis dataKey="year" tick={{ fill: "#5A6A8C", fontSize: 11 }} axisLine={false} tickLine={false} />
        <YAxis tick={{ fill: "#5A6A8C", fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={fAxis} />
        <RechartsTooltip formatter={(v) => fMoney(Number(v ?? 0))} contentStyle={TT} />
        <Bar dataKey="revenue" name="CA TTC" radius={[5, 5, 0, 0]} maxBarSize={46}>{kpis.yearly_sales.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}</Bar>
      </BarChart>
    </ResponsiveContainer>) : <Empty />;
  const rSeason = (h: number) => kpis?.seasonality?.length ? (
    <ResponsiveContainer width="100%" height={h}>
      <RadarChart data={kpis.seasonality} outerRadius="72%">
        <PolarGrid stroke="rgba(26,35,72,0.12)" /><PolarAngleAxis dataKey="month" tick={{ fill: "#5A6A8C", fontSize: 10 }} />
        <RechartsTooltip formatter={(v) => fMoney(Number(v ?? 0))} contentStyle={TT} />
        <Radar dataKey="revenue" stroke="#14C2D6" fill="#14C2D6" fillOpacity={0.4} />
      </RadarChart>
    </ResponsiveContainer>) : <Empty />;
  const rDist = (h: number) => kpis?.amount_distribution?.length ? (
    <ResponsiveContainer width="100%" height={h}>
      <BarChart data={kpis.amount_distribution} margin={{ top: 10, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(26,35,72,0.07)" vertical={false} />
        <XAxis dataKey="tranche" tick={{ fill: "#5A6A8C", fontSize: 10 }} axisLine={false} tickLine={false} />
        <YAxis tick={{ fill: "#5A6A8C", fontSize: 11 }} axisLine={false} tickLine={false} />
        <RechartsTooltip formatter={(v) => `${fInt(Number(v ?? 0))} factures`} contentStyle={TT} />
        <Bar dataKey="count" name="Factures" fill="#2F5BEA" radius={[4, 4, 0, 0]} maxBarSize={40} />
      </BarChart>
    </ResponsiveContainer>) : <Empty />;
  const rAging = (h: number) => kpis?.echelonnement_delais_accordes?.length ? (
    <ResponsiveContainer width="100%" height={h}>
      <BarChart data={kpis.echelonnement_delais_accordes} margin={{ top: 10, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(26,35,72,0.07)" vertical={false} />
        <XAxis dataKey="bucket" tick={{ fill: "#5A6A8C", fontSize: 11 }} axisLine={false} tickLine={false} />
        <YAxis tick={{ fill: "#5A6A8C", fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={fAxis} />
        <RechartsTooltip formatter={(v) => fMoney(Number(v ?? 0))} contentStyle={TT} />
        <Bar dataKey="montant" name="Montant TTC" radius={[5, 5, 0, 0]} maxBarSize={64}>{kpis.echelonnement_delais_accordes.map((_, i) => <Cell key={i} fill={["#10B981", "#2F5BEA", "#F59E0B", "#F97316", "#EF4444"][i]} />)}</Bar>
      </BarChart>
    </ResponsiveContainer>) : <Empty />;
  const rCash = (h: number) => kpis?.cash_forecast?.length ? (
    <ResponsiveContainer width="100%" height={h}>
      <BarChart data={kpis.cash_forecast} margin={{ top: 10, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(26,35,72,0.07)" vertical={false} />
        <XAxis dataKey="period" tick={{ fill: "#5A6A8C", fontSize: 10 }} axisLine={false} tickLine={false} minTickGap={16} />
        <YAxis tick={{ fill: "#5A6A8C", fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={fAxis} />
        <RechartsTooltip formatter={(v) => fMoney(Number(v ?? 0))} contentStyle={TT} />
        <Bar dataKey="montant" name="Échéances" fill="#14C2D6" radius={[3, 3, 0, 0]} maxBarSize={26} />
      </BarChart>
    </ResponsiveContainer>) : <Empty />;
  const rPareto = (h: number) => kpis?.client_pareto?.length ? (
    <ResponsiveContainer width="100%" height={h}>
      <AreaChart data={kpis.client_pareto} margin={{ top: 10, right: 12, left: 0, bottom: 0 }}>
        <defs><linearGradient id="gPar" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#8B5CF6" stopOpacity={0.4} /><stop offset="95%" stopColor="#8B5CF6" stopOpacity={0} /></linearGradient></defs>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(26,35,72,0.07)" />
        <XAxis dataKey="pct_clients" tick={{ fill: "#5A6A8C", fontSize: 11 }} axisLine={false} tickLine={false} unit="%" />
        <YAxis tick={{ fill: "#5A6A8C", fontSize: 11 }} axisLine={false} tickLine={false} unit="%" domain={[0, 100]} />
        <RechartsTooltip formatter={(v) => `${Number(v ?? 0).toFixed(1)}% du CA`} labelFormatter={(l) => `${l}% des clients`} contentStyle={TT} />
        <Area type="monotone" dataKey="pct_ca" name="% CA cumulé" stroke="#8B5CF6" strokeWidth={2.5} fill="url(#gPar)" />
      </AreaChart>
    </ResponsiveContainer>) : <Empty />;
  const rPayMix = (h: number) => kpis?.payment_mix?.length ? (
    <ResponsiveContainer width="100%" height={h}>
      <PieChart>
        <Pie data={kpis.payment_mix} dataKey="montant" nameKey="mode" cx="50%" cy="50%" innerRadius="48%" outerRadius="82%" paddingAngle={2}>{kpis.payment_mix.map((_, i) => <Cell key={i} stroke="#FFFFFF" fill={PIE_COLORS[i % PIE_COLORS.length]} />)}</Pie>
        <RechartsTooltip formatter={(v, n) => [fMoney(Number(v ?? 0)), String(n)]} contentStyle={TT} /><Legend wrapperStyle={{ fontSize: 11 }} />
      </PieChart>
    </ResponsiveContainer>) : <Empty />;
  const rFam = (h: number) => kpis?.top_familles?.length ? (
    <ResponsiveContainer width="100%" height={h}>
      <PieChart>
        <Pie data={kpis.top_familles} dataKey="ca" nameKey="famille" cx="50%" cy="50%" innerRadius="45%" outerRadius="80%" paddingAngle={2}>{kpis.top_familles.map((_, i) => <Cell key={i} stroke="#FFFFFF" fill={PIE_COLORS[i % PIE_COLORS.length]} />)}</Pie>
        <RechartsTooltip formatter={(v, n) => [fMoney(Number(v ?? 0)), String(n)]} contentStyle={TT} /><Legend wrapperStyle={{ fontSize: 11 }} />
      </PieChart>
    </ResponsiveContainer>) : <Empty />;
  const rProd = (h: number) => kpis?.top_produits?.length ? (
    <ResponsiveContainer width="100%" height={h}>
      <BarChart layout="vertical" data={kpis.top_produits} margin={{ top: 0, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(26,35,72,0.07)" horizontal={false} />
        <XAxis type="number" tick={{ fill: "#5A6A8C", fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={fAxis} />
        <YAxis type="category" dataKey="produit" tick={{ fill: "#5A6A8C", fontSize: 10 }} axisLine={false} tickLine={false} width={150} />
        <RechartsTooltip formatter={(v) => fMoney(Number(v ?? 0))} contentStyle={TT} />
        <Bar dataKey="ca" name="CA" fill="#10B981" radius={[0, 5, 5, 0]} maxBarSize={18} />
      </BarChart>
    </ResponsiveContainer>) : <Empty />;
  const rFourn = (h: number) => kpis?.top_fournisseurs?.length ? (
    <ResponsiveContainer width="100%" height={h}>
      <BarChart layout="vertical" data={kpis.top_fournisseurs} margin={{ top: 0, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(26,35,72,0.07)" horizontal={false} />
        <XAxis type="number" tick={{ fill: "#5A6A8C", fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={fAxis} />
        <YAxis type="category" dataKey="fournisseur" tick={{ fill: "#5A6A8C", fontSize: 10 }} axisLine={false} tickLine={false} width={150} />
        <RechartsTooltip formatter={(v) => fMoney(Number(v ?? 0))} contentStyle={TT} />
        <Bar dataKey="montant" name="Achats" fill="#F59E0B" radius={[0, 5, 5, 0]} maxBarSize={18} />
      </BarChart>
    </ResponsiveContainer>) : <Empty />;
  const rPriority = (h: number) => (kpis?.risk_model_active && kpis?.risk_ranking?.length) ? (
    <ResponsiveContainer width="100%" height={h}>
      <BarChart layout="vertical" data={kpis.risk_ranking} margin={{ top: 0, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(26,35,72,0.07)" horizontal={false} />
        <XAxis type="number" tick={{ fill: "#5A6A8C", fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={fAxis} />
        <YAxis type="category" dataKey="nom" tick={{ fill: "#5A6A8C", fontSize: 9 }} axisLine={false} tickLine={false} width={120} />
        <RechartsTooltip formatter={(v, n) => n === "priority" ? [fMoney(Number(v)), "Argent à risque"] : [`${Number(v).toFixed(0)}%`, "Score"]} contentStyle={TT} />
        <Bar dataKey="priority" name="priority" radius={[0, 5, 5, 0]} maxBarSize={16}>{kpis.risk_ranking.map((r, i) => <Cell key={i} fill={r.score > 70 ? "#EF4444" : r.score > 40 ? "#F59E0B" : "#10B981"} />)}</Bar>
      </BarChart>
    </ResponsiveContainer>) : <div className="muted-note" style={{ lineHeight: 1.6 }}>Classement indisponible pour le moment.</div>;
  const rFunnel = (h: number) => kpis?.funnel?.length ? (
    <ResponsiveContainer width="100%" height={h}>
      <FunnelChart><RechartsTooltip formatter={(v) => fInt(Number(v ?? 0))} contentStyle={TT} />
        <Funnel dataKey="valeur" data={kpis.funnel} isAnimationActive>{kpis.funnel.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}<LabelList position="right" fill="#fff" stroke="none" dataKey="etape" style={{ fontSize: 11 }} /></Funnel>
      </FunnelChart>
    </ResponsiveContainer>) : <Empty />;

  return { rMonthly, rFlow, rYoY, rBridge, rYear, rSeason, rDist, rAging, rCash, rPareto, rPayMix, rFam, rProd, rFourn, rPriority, rFunnel };
}
