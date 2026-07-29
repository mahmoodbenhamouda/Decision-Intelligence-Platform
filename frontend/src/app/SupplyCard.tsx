"use client";

import { useCallback, useEffect, useState } from "react";
import { PackageSearch, AlertTriangle, TrendingUp, Factory } from "lucide-react";

interface Supplier { fournisseur: string; part_pct: number; achats_dt: number; n_factures: number }
interface Forecast { period: string; qte: number }
interface SupplyData {
  demande_mape?: number | null;
  demande_methode?: string;
  demande_prevision?: Forecast[];
  fournisseurs_nb?: number;
  fournisseurs_hhi?: number;
  fournisseur_top1_pct?: number;
  fournisseurs_top3_pct?: number;
  fournisseurs_top?: Supplier[];
  dependance_fournisseur?: string;
  error?: string;
}

const DEP_COLOR: Record<string, string> = {
  critique: "#EF4444", élevée: "#F97316", elevee: "#F97316", modérée: "#EAB308", moderee: "#EAB308", faible: "#22C55E",
};

function fMoney(n?: number): string {
  const v = n || 0;
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(2)} M DT`;
  if (Math.abs(v) >= 1e3) return `${(v / 1e3).toFixed(0)} K DT`;
  return `${v.toFixed(0)} DT`;
}

export default function SupplyCard({ apiUrl }: { apiUrl: string }) {
  const [data, setData] = useState<SupplyData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const res = await fetch(`${apiUrl}/api/supply`);
      const d: SupplyData = await res.json();
      if (d.error) setError(d.error); else setData(d);
    } catch {
      setError("API injoignable (port 8000).");
    } finally { setLoading(false); }
  }, [apiUrl]);

  useEffect(() => { load(); }, [load]);

  const dep = (data?.dependance_fournisseur || "").toLowerCase();
  const depColor = DEP_COLOR[dep] || "#64748b";
  const top = data?.fournisseurs_top || [];
  const fc = data?.demande_prevision || [];

  return (
    <div style={{ gridColumn: "span 12", padding: 20, borderRadius: 16, background: "var(--surface,#fff)", border: "1px solid var(--border)", boxShadow: "var(--shadow-sm)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 800, fontSize: "1rem", color: "var(--text-primary)", marginBottom: 4 }}>
        <PackageSearch size={18} /> Demande & Approvisionnement
      </div>
      <div style={{ fontSize: "0.78rem", color: "var(--text-muted)", marginBottom: 16 }}>
        Prévision de demande (volume d'articles) et risque de dépendance fournisseur.
        <em> Analyse de la demande — pas de gestion de stock par référence (données stock ERP indisponibles).</em>
      </div>

      {loading && <p style={{ color: "var(--text-muted)" }}>Calcul en cours…</p>}
      {error && <div style={{ padding: 12, borderRadius: 10, background: "rgba(239,68,68,0.08)", color: "#B91C1C", border: "1px solid rgba(239,68,68,0.25)" }}>⚠️ {error}</div>}

      {data && !error && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
          {/* Colonne fournisseurs */}
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: "0.72rem", fontWeight: 800, padding: "4px 10px", borderRadius: 20, color: "#fff", background: depColor }}>
                <AlertTriangle size={13} /> Dépendance {data.dependance_fournisseur}
              </span>
              <span style={{ fontSize: "0.74rem", color: "var(--text-muted)" }}>
                {data.fournisseurs_nb} fournisseurs · HHI {Math.round(data.fournisseurs_hhi || 0)}
              </span>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {top.slice(0, 5).map((s, i) => (
                <div key={i}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.78rem", color: "var(--text-primary)" }}>
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      <Factory size={12} /> {s.fournisseur}
                    </span>
                    <strong>{s.part_pct}%</strong>
                  </div>
                  <div style={{ height: 7, borderRadius: 6, background: "rgba(0,0,0,0.06)", marginTop: 3 }}>
                    <div style={{ height: "100%", width: `${Math.min(100, s.part_pct)}%`, borderRadius: 6, background: i === 0 ? depColor : "var(--accent-blue,#2F5BEA)" }} />
                  </div>
                </div>
              ))}
            </div>
            <p style={{ marginTop: 10, fontSize: "0.72rem", color: "var(--text-muted)" }}>
              Top 3 = <strong style={{ color: "var(--text-primary)" }}>{data.fournisseurs_top3_pct}%</strong> des achats →
              {dep === "critique" || dep === "élevée" ? " sécuriser une 2ᵉ source d'appro." : " diversification correcte."}
            </p>
          </div>

          {/* Colonne demande */}
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: "0.78rem", fontWeight: 700, color: "var(--text-primary)" }}>
                <TrendingUp size={15} /> Prévision de demande (articles / mois)
              </span>
              {data.demande_mape != null && (
                <span style={{ fontSize: "0.68rem", fontWeight: 700, padding: "3px 8px", borderRadius: 20, color: "#0E9E6E", background: "rgba(16,185,129,0.12)", border: "1px solid rgba(16,185,129,0.25)" }}>
                  erreur MAPE {data.demande_mape}%
                </span>
              )}
            </div>
            <div style={{ display: "flex", gap: 10 }}>
              {fc.map((p, i) => (
                <div key={i} style={{ flex: 1, textAlign: "center", padding: "12px 8px", borderRadius: 12, background: "linear-gradient(160deg, rgba(47,91,234,0.08), rgba(20,194,214,0.06))", border: "1px solid var(--border)" }}>
                  <div style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}>{p.period}</div>
                  <div style={{ fontSize: "1.1rem", fontWeight: 800, color: "var(--text-primary)" }}>{Math.round(p.qte).toLocaleString("fr-FR")}</div>
                </div>
              ))}
            </div>
            <p style={{ marginTop: 10, fontSize: "0.72rem", color: "var(--text-muted)" }}>
              Méthode retenue : <strong style={{ color: "var(--text-primary)" }}>{data.demande_methode}</strong> (choisie par backtest).
              MAPE plus bas = meilleur.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
