"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Radar, RefreshCw, ExternalLink, Building2, Sparkles, Target, Clock,
} from "lucide-react";

interface Opp {
  title: string;
  pertinence: number;
  client_match: string | null;
  client_score: number;
  source?: string;
  date?: string;
  url?: string;
}
interface ScanData {
  generated_at?: string;
  n_scanned?: number;
  n_relevant?: number;
  model_accuracy?: number | null;
  opportunities?: Opp[];
  error?: string;
}

function scoreColor(p: number): string {
  if (p >= 0.75) return "#10B981";
  if (p >= 0.6) return "#2F5BEA";
  return "#F59E0B";
}

export default function Opportunities({ apiUrl }: { apiUrl: string }) {
  const [data, setData] = useState<ScanData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (refresh = false) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${apiUrl}/api/fleet/opportunities${refresh ? "?refresh=true" : ""}`);
      const d: ScanData = await res.json();
      if (d.error) setError(d.error);
      else setData(d);
    } catch {
      setError("API injoignable — vérifiez que le serveur tourne (port 8000).");
    } finally {
      setLoading(false);
    }
  }, [apiUrl]);

  useEffect(() => { load(false); }, [load]);

  const opps = data?.opportunities || [];
  const acc = data?.model_accuracy;

  return (
    <div style={{ gridColumn: "span 12" }}>
      {/* En-tête */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        flexWrap: "wrap", gap: 12, marginBottom: 16,
        padding: "18px 20px", borderRadius: 16,
        background: "linear-gradient(135deg, rgba(47,91,234,0.10), rgba(20,194,214,0.08))",
        border: "1px solid var(--border)",
      }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: "1.05rem", fontWeight: 800, color: "var(--text-primary)" }}>
            <Radar size={20} /> Veille & Opportunités
          </div>
          <div style={{ fontSize: "0.8rem", color: "var(--text-muted)", marginTop: 4 }}>
            Appels d'offres scrapés, classés par un modèle de pertinence, puis matchés à vos clients.
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {acc != null && (
            <span style={{
              display: "inline-flex", alignItems: "center", gap: 5, fontSize: "0.72rem", fontWeight: 700,
              padding: "5px 11px", borderRadius: 20, color: "#0E9E6E",
              background: "rgba(16,185,129,0.12)", border: "1px solid rgba(16,185,129,0.25)",
            }}>
              <Target size={13} /> Accuracy modèle {(acc * 100).toFixed(0)}%
            </span>
          )}
          <button
            onClick={() => load(true)}
            disabled={loading}
            style={{
              display: "inline-flex", alignItems: "center", gap: 6, fontSize: "0.78rem", fontWeight: 700,
              padding: "8px 14px", borderRadius: 10, cursor: loading ? "default" : "pointer",
              color: "#fff", background: "var(--accent-blue, #2F5BEA)", border: "none",
              opacity: loading ? 0.6 : 1,
            }}
          >
            <RefreshCw size={14} className={loading ? "spin-icon" : ""} /> Rafraîchir le scan
          </button>
        </div>
      </div>

      {/* Bandeau de synthèse */}
      {data && !error && (
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginBottom: 16, color: "var(--text-muted)", fontSize: "0.82rem" }}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
            <Sparkles size={14} /> <strong style={{ color: "var(--text-primary)" }}>{data.n_relevant ?? 0}</strong> pertinents
            &nbsp;/ {data.n_scanned ?? 0} scannés
          </span>
          {data.generated_at && (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
              <Clock size={14} /> Dernier scan : {new Date(data.generated_at).toLocaleString("fr-FR")}
            </span>
          )}
        </div>
      )}

      {/* États */}
      {loading && <p style={{ color: "var(--text-muted)" }}>Analyse des appels d'offres…</p>}
      {error && (
        <div style={{ padding: 16, borderRadius: 12, background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.25)", color: "#B91C1C" }}>
          ⚠️ {error}
        </div>
      )}
      {!loading && !error && opps.length === 0 && (
        <p style={{ color: "var(--text-muted)" }}>Aucun appel d'offres pertinent pour le moment. Lancez un scan.</p>
      )}

      {/* Liste des opportunités */}
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {opps.map((o, i) => {
          const pct = Math.round(o.pertinence * 100);
          const col = scoreColor(o.pertinence);
          return (
            <div key={i} style={{
              display: "flex", alignItems: "center", gap: 14,
              padding: "14px 16px", borderRadius: 12,
              background: "var(--surface, #fff)", border: "1px solid var(--border)",
              boxShadow: "var(--shadow-sm)",
            }}>
              {/* Score circulaire */}
              <div style={{
                flexShrink: 0, width: 46, height: 46, borderRadius: "50%",
                display: "grid", placeItems: "center", fontWeight: 800, fontSize: "0.82rem",
                color: col, background: `conic-gradient(${col} ${pct}%, rgba(0,0,0,0.06) 0)`,
              }}>
                <span style={{ width: 36, height: 36, borderRadius: "50%", background: "var(--surface,#fff)", display: "grid", placeItems: "center" }}>
                  {pct}
                </span>
              </div>

              {/* Contenu */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 700, color: "var(--text-primary)", lineHeight: 1.3 }}>
                  {o.url ? (
                    <a href={o.url} target="_blank" rel="noopener noreferrer" style={{ color: "inherit", textDecoration: "none", display: "inline-flex", alignItems: "center", gap: 6 }}>
                      {o.title} <ExternalLink size={13} style={{ opacity: 0.5 }} />
                    </a>
                  ) : o.title}
                </div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 6 }}>
                  {o.client_match && (
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: "0.72rem", fontWeight: 600, padding: "3px 9px", borderRadius: 20, color: "#5B3A95", background: "rgba(124,92,252,0.12)", border: "1px solid rgba(124,92,252,0.22)" }}>
                      <Building2 size={12} /> Client : {o.client_match}
                    </span>
                  )}
                  {o.source && (
                    <span style={{ fontSize: "0.72rem", color: "var(--text-muted)", padding: "3px 9px", borderRadius: 20, background: "rgba(0,0,0,0.04)" }}>
                      {o.source}
                    </span>
                  )}
                  {o.date && (
                    <span style={{ fontSize: "0.72rem", color: "var(--text-muted)" }}>{o.date}</span>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <p style={{ marginTop: 16, fontSize: "0.72rem", color: "var(--text-muted)" }}>
        Score = probabilité de pertinence (diagnostic / biologie médicale) prédite par le classifieur entraîné.
        Le scan se met à jour automatiquement chaque matin.
      </p>
    </div>
  );
}
