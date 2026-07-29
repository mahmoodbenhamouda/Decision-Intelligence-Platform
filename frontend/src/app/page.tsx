"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Funnel, FunnelChart,
  LabelList, Legend, Line, Pie, PieChart, PolarAngleAxis, PolarGrid, Radar, RadarChart,
  RadialBar, RadialBarChart, ResponsiveContainer, Tooltip as RechartsTooltip, XAxis, YAxis,
} from "recharts";
import {
  Activity, AlertTriangle, BarChart3, Bot, Boxes, CalendarClock, Coins, FileText, Gauge,
  LayoutDashboard, Layers, Maximize2, PieChart as PieIcon, Receipt, RefreshCw,
  ShieldAlert, Target, Timer, TrendingUp, Trash2, Truck, Users, Wallet, X, Zap,
} from "lucide-react";
import Copilot from "./Copilot";
import Opportunities from "./Opportunities";
import SupplyCard from "./SupplyCard";

/* ── Types ── */
interface TopClient { client: string; nom?: string; revenue: number; invoices: number; share: number; rank: number; risque?: number; risk_score?: number | null; }
interface KPIs {
  ca_total_ttc: number | null; ca_total_ht: number | null; nb_clients: number | null;
  nb_factures_vente: number | null; panier_moyen: number | null; dso_jours: number | null;
  dpo_jours: number | null; cash_conversion_cycle: number | null;
  monthly_sales: { period: string; revenue: number }[];
  forecast_next: { period: string; montant: number }[];
  yoy_comparison: { current_year: number | null; previous_year: number | null; delta_pct: number | null; data: { month: string; courante: number | null; precedente: number | null }[] };
  waterfall: { step: string; value: number; kind: string }[];
  yearly_sales: { year: number; revenue: number }[];
  seasonality: { month: string; revenue: number }[];
  sales_vs_purchases: { period: string; ventes: number; achats: number }[];
  monthly_margin: { period: string; marge: number }[];
  aging_creances: { bucket: string; montant: number }[];
  payment_mix: { mode: string; montant: number; count: number }[];
  client_pareto: { pct_clients: number; pct_ca: number }[];
  cash_forecast: { period: string; montant: number }[];
  amount_distribution: { tranche: string; count: number }[];
  top_clients: TopClient[];
  top_fournisseurs: { fournisseur: string; montant: number; share: number; rank: number }[];
  top_produits: { produit: string; ca: number; qte: number }[];
  top_familles: { famille: string; ca: number }[];
  clients_a_risque: { client: string; nom?: string; montant_risque: number; factures: number; risk_score?: number | null }[];
  risk_ranking: { client: string; nom?: string; score: number; exposure: number; avg_delay: number; priority: number }[];
  nb_clients_risque_predit: number | null; exposition_risque_ponderee: number | null; risk_model_active?: boolean;
  funnel: { etape: string; valeur: number }[];
  mom_growth: number | null; yoy_growth: number | null; ttm_revenue: number | null; tendance: string;
  retards_critiques: number | null; retards_30j: number | null; retards_60j: number | null;
  paiements_a_risque_pct: number | null; paiements_a_risque_count: number | null;
  montant_risque_ttc: number | null; montant_critique_ttc: number | null;
  exposition_recente_dt: number | null; exposition_recente_critique_dt: number | null;
  exposition_recente_count: number | null; exposition_recente_periode: string | null;
  ca_retard_historique_ttc: number | null;
  hhi_clients: number | null; hhi_fournisseurs: number | null; top_clients_revenue_share: number | null;
  achats_total_ttc: number | null; nb_fournisseurs: number | null; nb_factures_achat: number | null;
  marge_brute: number | null; taux_marge: number | null; marge_quality_score: number | null; marge_note: string;
  nb_devis: number | null; montant_devis_total: number | null; taux_conversion_devis: number | null;
  nb_bl: number | null; nb_produits: number | null; anomalies_detectees: number; anomalies_details: string[];
  market_intel?: { timestamp: string; fx?: { usd_tnd: number; eur_tnd: number; eur_tnd_var_pct?: number; provider?: string } | null; signals: string[]; news?: { title: string; link: string; date?: string; source?: string; type?: string; reco?: string; client?: string; client_ca?: number; relevance?: number }[]; macro?: { inflation?: { value: number; year: string }; sante_pct_pib?: { value: number; year: string } } | null; fx_sensitivity?: { annual_fx_base_dt: number; impact_per_1pct_dt: number; var_pct?: number; var_impact_dt?: number; assumption?: string } | null; macro_context?: { public_ca_share_pct: number; public_ca_dt: number; sante_pct_pib?: number; note?: string } | null; sources_status?: Record<string, string>; as_of?: string };
  finance_radar?: { priorite: number; categorie: string; severite: string; titre: string; montant_dt: number; montant_label: string; constat: string; signal_externe: string; action: string; top?: { client: string; montant: number }[] }[];
}
interface FiltersData {
  available_years: number[]; available_clients: string[]; client_names?: Record<string, string>;
  fidelity_options: string[]; available_payment_modes: string[]; risk_levels: string[]; max_amount_possible: number;
}

const API_URL = "http://127.0.0.1:8000";
const PIE_COLORS = ["#2F5BEA", "#10B981", "#8B5CF6", "#14C2D6", "#F59E0B", "#EF4444", "#EC4899", "#64748B"];
const TT = { borderRadius: 10, border: "1px solid rgba(26,35,72,0.12)", background: "rgba(255,255,255,0.97)", color: "#16204A", fontSize: 13, boxShadow: "0 8px 24px rgba(26,35,72,0.14)" } as const;

function fMoney(v: number | null | undefined) {
  if (v == null || Number.isNaN(v)) return "N/A";
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(2)} M DT`;
  if (Math.abs(v) >= 1e3) return `${(v / 1e3).toFixed(1)} K DT`;
  return `${v.toFixed(0)} DT`;
}
function fInt(v: number | null | undefined) { return v == null || Number.isNaN(v) ? "N/A" : v.toLocaleString("fr-FR"); }
function fAxis(v: number) { return Math.abs(v) >= 1e6 ? `${(v / 1e6).toFixed(0)}M` : `${(v / 1e3).toFixed(0)}k`; }
function fDate(d?: string) { if (!d) return ""; const t = new Date(d); return Number.isNaN(t.getTime()) ? "" : t.toLocaleDateString("fr-FR", { day: "2-digit", month: "short", year: "numeric" }); }

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target, trigger]);
  return val;
}

/* ── KPI stat card (with count-up) ── */
function Stat({ label, value, format, icon, tone, sub, trigger }: {
  label: string; value: number | null; format: (n: number) => string; icon: React.ReactNode; tone: string; sub?: React.ReactNode; trigger: unknown;
}) {
  const shown = useCountUp(value ?? 0, trigger);
  return (
    <div className={`kpi ${tone}`}>
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
function ChartCard({ title, icon, render, h = 232, span = 6, hint, hidden, onExpand }: {
  title: string; icon: React.ReactNode; render: (h: number) => React.ReactNode; h?: number; span?: number;
  hint?: string; hidden?: boolean; onExpand: (c: { title: string; render: (h: number) => React.ReactNode }) => void;
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
function PanelCard({ title, icon, children, span = 6, hidden }: { title: string; icon: React.ReactNode; children: React.ReactNode; span?: number; hidden?: boolean; }) {
  if (hidden) return null;
  return (
    <div className="chart-card" style={{ gridColumn: `span ${span}` }}>
      <div className="card-header"><span className="card-label">{title}</span><div className="card-icon">{icon}</div></div>
      <div className="chart-body">{children}</div>
    </div>
  );
}
function Empty() { return <p className="muted-note">Données insuffisantes.</p>; }
function MiniGauge({ value, label, color }: { value: number; label: string; color: string; }) {
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

const VIEWS = [
  { id: "synthese", label: "Synthèse", icon: <LayoutDashboard size={16} /> },
  { id: "performance", label: "Performance", icon: <TrendingUp size={16} /> },
  { id: "risque", label: "Risque crédit", icon: <ShieldAlert size={16} /> },
  { id: "clients", label: "Clients", icon: <Users size={16} /> },
  { id: "produits", label: "Produits & achats", icon: <Boxes size={16} /> },
  { id: "veille", label: "Veille & Opportunités", icon: <Target size={16} /> },
  { id: "copilot", label: "Copilote IA", icon: <Bot size={16} /> },
];

export default function Dashboard() {
  const [kpis, setKpis] = useState<KPIs | null>(null);
  const [filtersData, setFiltersData] = useState<FiltersData | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedYears, setSelectedYears] = useState<number[]>([]);
  const [selectedClients, setSelectedClients] = useState<string[]>([]);
  const [fidelityFilter, setFidelityFilter] = useState("Tous");
  const [dateStart, setDateStart] = useState(""); const [dateEnd, setDateEnd] = useState("");
  const [selectedPaymentModes, setSelectedPaymentModes] = useState<string[]>([]);
  const [riskLevel, setRiskLevel] = useState("Tous");
  const [minAmount, setMinAmount] = useState<number | "">(""); const [maxAmount, setMaxAmount] = useState<number | "">("");
  const [view, setView] = useState("synthese");
  const [spot, setSpot] = useState<{ title: string; render: (h: number) => React.ReactNode } | null>(null);

  const filterPayload = useMemo(() => ({
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

  const fetchData = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/dashboard`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(filterPayload) });
      const data = await res.json();
      if (!data.error) {
        setKpis(data.kpis);
        if (data.filters) setFiltersData(data.filters);
      }
    } catch (e) { console.error(e); } finally { setLoading(false); }
  };
  useEffect(() => { fetchData(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [filterPayload]);
  useEffect(() => { if (spot) { const h = (e: KeyboardEvent) => e.key === "Escape" && setSpot(null); window.addEventListener("keydown", h); return () => window.removeEventListener("keydown", h); } }, [spot]);

  const toggleYear = (y: number) => setSelectedYears(p => p.includes(y) ? p.filter(i => i !== y) : [...p, y]);
  const toggleClient = (c: string) => setSelectedClients(p => p.includes(c) ? p.filter(i => i !== c) : [...p, c]);
  const togglePay = (m: string) => setSelectedPaymentModes(p => p.includes(m) ? p.filter(i => i !== m) : [...p, m]);
  const clearAll = () => { setSelectedYears([]); setSelectedClients([]); setFidelityFilter("Tous"); setDateStart(""); setDateEnd(""); setSelectedPaymentModes([]); setRiskLevel("Tous"); setMinAmount(""); setMaxAmount(""); };

  const clientFocus = selectedClients.length > 0;
  const combinedFlow = useMemo(() => {
    if (!kpis) return [];
    const m = new Map((kpis.monthly_margin || []).map(x => [x.period, x.marge]));
    return (kpis.sales_vs_purchases || []).map(d => ({ ...d, marge: m.get(d.period) ?? null }));
  }, [kpis]);
  const marginScore = Math.max(0, Math.min(100, kpis?.marge_quality_score ?? 0));
  const riskScore = Math.max(0, Math.min(100, kpis?.paiements_a_risque_pct ?? 0));
  const convScore = Math.max(0, Math.min(100, kpis?.taux_conversion_devis ?? 0));

  /* ── chart renderers (height param → reusable in spotlight) ── */
  const rMonthly = (h: number) => {
    const base = kpis?.monthly_sales || [];
    if (!base.length) return <Empty />;
    const fc = kpis?.forecast_next || [];
    const data: { period: string; revenue: number | null; prevision: number | null }[] = [
      ...base.map(d => ({ period: d.period, revenue: d.revenue, prevision: null as number | null })),
      ...fc.map(d => ({ period: d.period, revenue: null as number | null, prevision: d.montant })),
    ];
    if (base.length && fc.length) data[base.length - 1].prevision = base[base.length - 1].revenue;
    return (
      <ResponsiveContainer width="100%" height={h}>
        <AreaChart data={data} margin={{ top: 10, right: 12, left: 0, bottom: 0 }}>
          <defs><linearGradient id="gRev" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#2F5BEA" stopOpacity={0.45} /><stop offset="95%" stopColor="#2F5BEA" stopOpacity={0} /></linearGradient></defs>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(26,35,72,0.07)" vertical={false} />
          <XAxis dataKey="period" tick={{ fill: "#5A6A8C", fontSize: 11 }} axisLine={false} tickLine={false} minTickGap={24} />
          <YAxis tick={{ fill: "#5A6A8C", fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={fAxis} />
          <RechartsTooltip formatter={(v, n) => [fMoney(Number(v ?? 0)), n === "prevision" ? "Prévision IA" : "CA TTC"]} contentStyle={TT} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
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
  const rAging = (h: number) => kpis?.aging_creances?.length ? (
    <ResponsiveContainer width="100%" height={h}>
      <BarChart data={kpis.aging_creances} margin={{ top: 10, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(26,35,72,0.07)" vertical={false} />
        <XAxis dataKey="bucket" tick={{ fill: "#5A6A8C", fontSize: 11 }} axisLine={false} tickLine={false} />
        <YAxis tick={{ fill: "#5A6A8C", fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={fAxis} />
        <RechartsTooltip formatter={(v) => fMoney(Number(v ?? 0))} contentStyle={TT} />
        <Bar dataKey="montant" name="Montant TTC" radius={[5, 5, 0, 0]} maxBarSize={64}>{kpis.aging_creances.map((_, i) => <Cell key={i} fill={["#10B981", "#2F5BEA", "#F59E0B", "#F97316", "#EF4444"][i]} />)}</Bar>
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
    </ResponsiveContainer>) : <div className="muted-note" style={{ lineHeight: 1.6 }}>Modèle de risque non entraîné. Lancez : <code style={{ color: "var(--accent-cyan)" }}>python -m ml_engine.analytics.credit_risk_model</code></div>;
  const rFunnel = (h: number) => kpis?.funnel?.length ? (
    <ResponsiveContainer width="100%" height={h}>
      <FunnelChart><RechartsTooltip formatter={(v) => fInt(Number(v ?? 0))} contentStyle={TT} />
        <Funnel dataKey="valeur" data={kpis.funnel} isAnimationActive>{kpis.funnel.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}<LabelList position="right" fill="#fff" stroke="none" dataKey="etape" style={{ fontSize: 11 }} /></Funnel>
      </FunnelChart>
    </ResponsiveContainer>) : <Empty />;

  const onExpand = (c: { title: string; render: (h: number) => React.ReactNode }) => setSpot(c);

  if (!kpis && loading) return (<div className="loader-container"><div className="spinner" /><p className="muted-note">Chargement des données financières…</p></div>);

  return (
    <div className="cockpit">
      <nav className="top-navbar">
        <div className="brand-block"><img src="/overlyne.png" alt="Overlyne" className="brand-logo" /><div><h2>Cockpit Décisionnel Finance</h2><p>Risque crédit & performance</p></div></div>
        <div className="nav-actions">
          <button className="icon-button" onClick={fetchData} title="Rafraîchir"><RefreshCw size={17} className={loading ? "spin-icon" : ""} /></button>
        </div>
      </nav>

      <main className="cockpit-main">
        <section className="filter-strip">
          <span className="filter-label"><Activity size={13} /> Filtres :</span>
          <div className="fp"><input type="date" value={dateStart} onChange={e => setDateStart(e.target.value)} className="mini" /><span className="sep">→</span><input type="date" value={dateEnd} onChange={e => setDateEnd(e.target.value)} className="mini" /></div>
          <div className="fp"><select onChange={e => toggleYear(Number(e.target.value))} value="" className="mini"><option value="" disabled>+ Année</option>{filtersData?.available_years.map(y => <option key={y} value={y}>{y}</option>)}</select>{selectedYears.length > 0 && <span className="cnt">{selectedYears.length}</span>}</div>
          <div className="fp"><select onChange={e => toggleClient(e.target.value)} value="" className="mini"><option value="" disabled>+ Client</option>{filtersData?.available_clients.map(c => <option key={c} value={c}>{filtersData?.client_names?.[c] ?? c}</option>)}</select>{selectedClients.length > 0 && <span className="cnt">{selectedClients.length}</span>}</div>
          <div className="fp"><select value={fidelityFilter} onChange={e => setFidelityFilter(e.target.value)} className="mini">{filtersData?.fidelity_options.map(o => <option key={o} value={o}>{o.includes("Tous") ? "Fidélité: Tous" : o}</option>)}</select></div>
          <div className="fp"><select value={riskLevel} onChange={e => setRiskLevel(e.target.value)} className="mini">{filtersData?.risk_levels?.map(r => <option key={r} value={r}>{r.includes("Tous") ? "Risque: Tous" : r}</option>) || <option>Risque: Tous</option>}</select></div>
          <div className="fp"><select onChange={e => togglePay(e.target.value)} value="" className="mini"><option value="" disabled>+ Paiement</option>{filtersData?.available_payment_modes?.map(m => <option key={m} value={m}>{m.trim()}</option>)}</select>{selectedPaymentModes.length > 0 && <span className="cnt">{selectedPaymentModes.length}</span>}</div>
          <div className="fp"><span style={{ fontSize: "0.74rem", color: "var(--text-muted)" }}>Montant</span><input type="number" placeholder="Min" value={minAmount} onChange={e => setMinAmount(e.target.value ? Number(e.target.value) : "")} className="mini num" /><input type="number" placeholder="Max" value={maxAmount} onChange={e => setMaxAmount(e.target.value ? Number(e.target.value) : "")} className="mini num" /></div>
          <button className="clear-btn" onClick={clearAll} title="Réinitialiser"><Trash2 size={14} /></button>
          <span className="filter-active">{activeFilterText}</span>
        </section>

        <section className="kpi-bar">
          <Stat label="CA TTC" value={kpis?.ca_total_ttc ?? null} format={fMoney} icon={<Coins size={18} />} tone="t-blue" trigger={view}
            sub={<span className={(kpis?.yoy_growth ?? 0) >= 0 ? "up" : "down"}>{(kpis?.yoy_growth ?? 0) >= 0 ? "▲" : "▼"} {Math.abs(kpis?.yoy_growth ?? 0).toFixed(1)}% / 12 m</span>} />
          <Stat label="Marge (est.)" value={kpis?.marge_brute ?? null} format={fMoney} icon={<Target size={18} />} tone="t-green" trigger={view} sub={kpis?.taux_marge == null ? "Non attribuable" : `${kpis?.taux_marge?.toFixed(1)}%`} />
          <Stat label="DSO" value={kpis?.dso_jours ?? null} format={(n) => `${n.toFixed(0)} j`} icon={<Timer size={18} />} tone="t-cyan" trigger={view} sub={`DPO ${(kpis?.dpo_jours ?? 0).toFixed(0)}j • Cycle ${(kpis?.cash_conversion_cycle ?? 0).toFixed(0)}j`} />
          <Stat label="Exposition récente > 60j" value={kpis?.exposition_recente_dt ?? null} format={fMoney} icon={<ShieldAlert size={18} />} tone="t-red" trigger={view} sub={`${fMoney(kpis?.exposition_recente_critique_dt)} critique • ${fInt(kpis?.exposition_recente_count)} factures`} />
          <Stat label="Clients" value={kpis?.nb_clients ?? null} format={fInt} icon={<Users size={18} />} tone="t-purple" trigger={view} sub={`Top 5 = ${(kpis?.top_clients_revenue_share ?? 0).toFixed(0)}%`} />
          <Stat label="Achats" value={kpis?.achats_total_ttc ?? null} format={fMoney} icon={<Truck size={18} />} tone="t-amber" trigger={view} sub={`${fInt(kpis?.nb_fournisseurs)} fourn.`} />
          <Stat label="Panier moyen" value={kpis?.panier_moyen ?? null} format={fMoney} icon={<Receipt size={18} />} tone="t-blue" trigger={view} sub={`${fInt(kpis?.nb_factures_vente)} fact.`} />
          <Stat label="Pipeline devis" value={kpis?.montant_devis_total ?? null} format={fMoney} icon={<FileText size={18} />} tone="t-green" trigger={view} sub={`${fInt(kpis?.nb_devis)} • conv ${(kpis?.taux_conversion_devis ?? 0).toFixed(0)}%`} />
        </section>

        <nav className="tab-bar">
          {VIEWS.map(v => (
            <button key={v.id} className={`tab ${view === v.id ? "active" : ""}`} onClick={() => setView(v.id)}>{v.icon}<span>{v.label}</span></button>
          ))}
        </nav>

        <section className="view-area">
          {clientFocus && (view === "clients" || view === "risque") && (
            <div className="focus-banner"><Users size={15} /><span>Vue centrée sur <b>{selectedClients.length} client(s)</b> — les analyses inter-clients (top clients, Pareto, priorité, entonnoir) sont masquées.</span></div>
          )}
          <div className="view-grid" key={view}>
            {view === "synthese" && <>
              <ChartCard title="Évolution mensuelle du chiffre d'affaires" icon={<TrendingUp size={17} />} span={8} h={288} render={rMonthly} onExpand={onExpand} />
              <PanelCard title="Indicateurs de santé" icon={<Gauge size={17} />} span={4}>
                <div className="gauges-row"><MiniGauge value={marginScore} label="Qualité marge" color="#10B981" /><MiniGauge value={riskScore} label="Factures à risque" color="#EF4444" /><MiniGauge value={convScore} label="Conversion devis" color="#8B5CF6" /></div>
              </PanelCard>
              {!!(kpis?.finance_radar || []).length && (
                <PanelCard title="Radar financier — actions prioritaires" icon={<Bot size={17} />} span={12}>
                  <div className="radar">
                    <p className="radar-sub">Signaux externes croisés avec vos données ERP → décisions finance chiffrées.</p>
                    {(kpis!.finance_radar || []).map((c, i) => (
                      <div key={i} className={`radar-card sev-${c.severite}`}>
                        <div className="radar-head">
                          <span className="radar-prio">#{c.priorite}</span>
                          <span className="radar-cat">{c.categorie}</span>
                          <span className={`radar-sev sev-${c.severite}`}>{c.severite}</span>
                          <span className="radar-amount">{Math.round(c.montant_dt).toLocaleString("fr-FR")} DT<em>{c.montant_label}</em></span>
                        </div>
                        <div className="radar-title">{c.titre}</div>
                        <div className="radar-constat">{c.constat}</div>
                        <div className="radar-ext">📡 {c.signal_externe}</div>
                        <div className="radar-action">→ {c.action}</div>
                        {!!(c.top || []).length && (
                          <div className="radar-top">
                            {(c.top || []).map((t, j) => (
                              <span key={j} className="radar-chip">{t.client} · {Math.round(t.montant).toLocaleString("fr-FR")} DT</span>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </PanelCard>
              )}
            </>}
            {view === "performance" && <>
              <ChartCard title={`Comparatif ${kpis?.yoy_comparison?.current_year ?? "année courante"} vs ${kpis?.yoy_comparison?.previous_year ?? "précédente"}`} icon={<TrendingUp size={17} />} span={12} h={250} render={rYoY}
                hint={kpis?.yoy_comparison?.delta_pct != null ? `Écart cumulé sur les mois comparables : ${kpis.yoy_comparison.delta_pct >= 0 ? "+" : ""}${kpis.yoy_comparison.delta_pct.toFixed(1)}%` : undefined} onExpand={onExpand} />
              <ChartCard title="Chiffre d'affaires annuel" icon={<BarChart3 size={17} />} span={6} render={rYear} onExpand={onExpand} />
              <ChartCard title="Saisonnalité du CA (moyenne mensuelle)" icon={<Activity size={17} />} span={6} render={rSeason} onExpand={onExpand} />
              <ChartCard title="Ventes vs Achats & marge mensuelle" icon={<BarChart3 size={17} />} span={8} render={rFlow} onExpand={onExpand} />
              <ChartCard title="Distribution des montants de facture" icon={<BarChart3 size={17} />} span={4} render={rDist} onExpand={onExpand} />
              <ChartCard title={clientFocus ? "CA cumulé dans le temps" : "Composition du CA — marge vs achats"} icon={<Coins size={17} />} span={12} h={250} render={rBridge}
                hint={clientFocus ? "Accumulation du CA du client sélectionné (pas de coûts attribuables par client)" : "Répartition du CA HT : marge brute vs coût des achats"} onExpand={onExpand} />
            </>}
            {view === "risque" && <>
              <ChartCard title="Structure des délais de paiement accordés" icon={<CalendarClock size={17} />} span={6} render={rAging} hint="Répartition du CA par tranche de délai (pièce → échéance)" onExpand={onExpand} />
              <ChartCard title="Prévision d'encaissement (par échéance)" icon={<Wallet size={17} />} span={6} render={rCash} onExpand={onExpand} />
              <ChartCard title="Priorité de recouvrement (IA)" icon={<ShieldAlert size={17} />} span={6} render={rPriority} hidden={clientFocus} hint={kpis?.risk_model_active ? `${fInt(kpis?.nb_clients_risque_predit)} clients à risque élevé • ${fMoney(kpis?.exposition_risque_ponderee)} d'exposition pondérée` : undefined} onExpand={onExpand} />
              <PanelCard title="Clients à surveiller (délais > 60j)" icon={<AlertTriangle size={17} />} span={6} hidden={clientFocus}>
                <div className="data-table"><div className="dt-head three"><span>Client</span><span>Exposition</span><span>Factures</span></div>
                  {(kpis?.clients_a_risque || []).length ? (kpis?.clients_a_risque || []).map((c, i) => (<div className="dt-row three" key={i}><span className="dt-name" title={c.client}>{c.nom || c.client}</span><span className="risk-tag">{fMoney(c.montant_risque)}</span><span>{fInt(c.factures)}</span></div>)) : <p className="muted-note">Aucun client à risque sur ce périmètre.</p>}
                </div>
              </PanelCard>
            </>}
            {view === "clients" && <>
              <PanelCard title="Top clients — CA & exposition" icon={<Users size={17} />} span={7} hidden={clientFocus}>
                <div className="data-table"><div className="dt-head six"><span>#</span><span>Client</span><span>CA TTC</span><span>Part</span><span>Risque</span><span>Score IA</span></div>
                  {(kpis?.top_clients || []).map(c => (<div className="dt-row six" key={c.rank}><span className="dt-rank">{c.rank}</span><span className="dt-name" title={c.client}>{c.nom || c.client}</span><span>{fMoney(c.revenue)}</span><span><span className="share-bar"><i style={{ width: `${Math.min(100, c.share)}%` }} /></span>{c.share.toFixed(1)}%</span><span className={c.risque ? "risk-tag" : "ok-tag"}>{c.risque ? fMoney(c.risque) : "—"}</span><span>{c.risk_score == null ? "—" : <span className="score-pill" style={{ background: c.risk_score > 70 ? "rgba(239,68,68,0.15)" : c.risk_score > 40 ? "rgba(245,158,11,0.15)" : "rgba(16,185,129,0.15)", color: c.risk_score > 70 ? "#EF4444" : c.risk_score > 40 ? "#F59E0B" : "#10B981" }}>{c.risk_score.toFixed(0)}</span>}</span></div>))}
                </div>
              </PanelCard>
              <ChartCard title="Concentration du CA — courbe de Pareto" icon={<Layers size={17} />} span={5} render={rPareto} hidden={clientFocus} hint={`HHI clients = ${(kpis?.hhi_clients ?? 0).toFixed(0)} (>2500 = concentré)`} onExpand={onExpand} />
              <ChartCard title="Répartition des modes de paiement" icon={<PieIcon size={17} />} span={6} render={rPayMix} onExpand={onExpand} />
              <ChartCard title="Entonnoir commercial" icon={<Layers size={17} />} span={6} render={rFunnel} hidden={clientFocus} onExpand={onExpand} />
            </>}
            {view === "produits" && <>
              <SupplyCard apiUrl={API_URL} />
              <ChartCard title="Top 10 produits par CA" icon={<Boxes size={17} />} span={6} h={250} render={rProd} onExpand={onExpand} />
              <ChartCard title="Top fournisseurs (achats)" icon={<Truck size={17} />} span={6} h={250} render={rFourn} onExpand={onExpand} />
              <ChartCard title="Répartition du CA par famille produit" icon={<Layers size={17} />} span={6} render={rFam} onExpand={onExpand} />
              <ChartCard title="Prévision d'encaissement (par échéance)" icon={<Wallet size={17} />} span={6} render={rCash} onExpand={onExpand} />
            </>}
            {view === "veille" && <Opportunities apiUrl={API_URL} />}
            {view === "copilot" && <Copilot apiUrl={API_URL} filterPayload={filterPayload} />}
          </div>
        </section>
      </main>

      {spot && (
        <div className="spotlight-backdrop" onClick={() => setSpot(null)}>
          <div className="spotlight-panel" onClick={e => e.stopPropagation()}>
            <div className="card-header"><span className="card-label">{spot.title}</span><button className="expand-btn" onClick={() => setSpot(null)}><X size={18} /></button></div>
            <div className="spotlight-body">{spot.render(window.innerHeight * 0.6)}</div>
          </div>
        </div>
      )}
    </div>
  );
}
