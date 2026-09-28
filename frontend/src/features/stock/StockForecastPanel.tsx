"use client";

/**
 * StockForecastPanel — volumes à prévoir par produit.
 *
 * Refonte complète. La version précédente affichait trois cartes « Horizon /
 * LightGBM / WAPE / MAE », puis huit lignes justifiant qu'aucun modèle appris
 * n'était déployé. C'était une page d'analyste : le directeur qui l'ouvrait ne
 * trouvait nulle part la réponse à sa seule question — combien commander.
 *
 * La page répond maintenant à cette question, et à elle seule : pour chaque
 * produit, les volumes attendus à 30, 60 et 90 jours, et l'écart avec le rythme
 * actuel. La méthode reste documentée dans le mémoire, pas à l'écran.
 */

import { useMemo, useState } from "react";
import {
  Area, CartesianGrid, ComposedChart, Line,
  ResponsiveContainer, Tooltip as RTooltip, XAxis, YAxis,
} from "recharts";
import { ArrowDownRight, ArrowRight, ArrowUpRight, Search } from "lucide-react";
import { usePrevisionStock } from "./usePrevisionStock";

const TT = {
  borderRadius: 10, border: "1px solid rgba(26,35,72,0.12)",
  background: "rgba(255,255,255,0.98)", color: "#16204A", fontSize: 12,
  boxShadow: "0 8px 24px rgba(26,35,72,0.14)",
} as const;

const fNum = (v: number) => Math.round(v).toLocaleString("fr-FR");

/** Évolution attendue par rapport au rythme des trois derniers mois. C'est la
 *  seule comparaison qui intéresse un acheteur : dois-je commander plus, autant
 *  ou moins que d'habitude ? */
function evolution(prevu30: number, moyenne3m: number) {
  if (!moyenne3m) return { pct: 0, label: "Stable", color: "#64748B", icone: <ArrowRight size={14} /> };
  const pct = ((prevu30 - moyenne3m) / moyenne3m) * 100;
  if (pct > 12) return { pct, label: "En hausse", color: "#0E9E6E", icone: <ArrowUpRight size={14} /> };
  if (pct < -12) return { pct, label: "En baisse", color: "#DC2626", icone: <ArrowDownRight size={14} /> };
  return { pct, label: "Stable", color: "#64748B", icone: <ArrowRight size={14} /> };
}

export default function StockForecastPanel() {
  const { data, loading } = usePrevisionStock();
  const [selection, setSelection] = useState<string | null>(null);
  const [recherche, setRecherche] = useState("");

  const previsions = useMemo(() => data?.previsions || [], [data]);
  const courant = useMemo(
    () => previsions.find(p => p.produit === selection) || previsions[0],
    [previsions, selection],
  );
  const filtrees = useMemo(() => {
    const q = recherche.trim().toLowerCase();
    return q ? previsions.filter(p => p.produit.toLowerCase().includes(q)) : previsions;
  }, [previsions, recherche]);

  if (loading && !data) return <p className="muted-note">Calcul des volumes…</p>;

  if (data?.error || !previsions.length) {
    return (
      <p className="muted-note">
        Les volumes prévisionnels ne sont pas disponibles pour le moment.
      </p>
    );
  }

  const ev = courant ? evolution(courant.prevision_30j, courant.moyenne_3m) : null;

  // Trajectoire cumulée : ce qu'il faudra avoir livré à chaque échéance.
  const trajectoire = courant ? [
    { h: "Aujourd'hui", cumul: 0, rythme: 0 },
    { h: "Dans 1 mois", cumul: courant.prevision_30j, rythme: courant.moyenne_3m },
    { h: "Dans 2 mois", cumul: courant.prevision_60j, rythme: courant.moyenne_3m * 2 },
    { h: "Dans 3 mois", cumul: courant.prevision_90j, rythme: courant.moyenne_3m * 3 },
  ] : [];

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(12, 1fr)", gap: 14 }}>

      {/* ── Produit sélectionné : les trois volumes ─────────────────────── */}
      <div className="chart-card" style={{ gridColumn: "span 12" }}>
        <div className="card-header">
          <span className="card-label">{courant?.produit}</span>
          {ev && (
            <span style={{
              display: "inline-flex", alignItems: "center", gap: 5,
              background: `${ev.color}15`, color: ev.color, borderRadius: 999,
              padding: "3px 11px", fontSize: "0.74rem", fontWeight: 700,
            }}>
              {ev.icone} {ev.label} {ev.pct !== 0 && `${ev.pct > 0 ? "+" : ""}${ev.pct.toFixed(0)} %`}
            </span>
          )}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: 12, marginTop: 4 }}>
          <Volume label="Dans 1 mois" valeur={courant?.prevision_30j ?? 0} accent />
          <Volume label="Dans 2 mois" valeur={courant?.prevision_60j ?? 0} />
          <Volume label="Dans 3 mois" valeur={courant?.prevision_90j ?? 0} />
          <Volume label="Rythme actuel" valeur={courant?.moyenne_3m ?? 0} sousTitre="par mois" discret />
        </div>
      </div>

      {/* ── Courbe cumulée ──────────────────────────────────────────────── */}
      <div className="chart-card" style={{ gridColumn: "span 7" }}>
        <div className="card-header">
          <span className="card-label">Volumes à couvrir</span>
        </div>
        <ResponsiveContainer width="100%" height={250}>
          <ComposedChart data={trajectoire} margin={{ top: 12, right: 16, left: 0, bottom: 4 }}>
            <defs>
              <linearGradient id="gradVol" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#2F5BEA" stopOpacity={0.32} />
                <stop offset="100%" stopColor="#2F5BEA" stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(26,35,72,0.07)" vertical={false} />
            <XAxis dataKey="h" tick={{ fill: "#5A6A8C", fontSize: 11 }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fill: "#5A6A8C", fontSize: 11 }} axisLine={false} tickLine={false}
                   tickFormatter={(v: number) => fNum(v)} />
            <RTooltip
              contentStyle={TT}
              formatter={(v: unknown, n: unknown) => [
                `${fNum(Number(v))} unités`,
                n === "cumul" ? "Volume attendu" : "Au rythme actuel",
              ] as [string, string]}
            />
            <Area type="monotone" dataKey="cumul" stroke="#2F5BEA" strokeWidth={2.5}
                  fill="url(#gradVol)" dot={{ r: 4, fill: "#2F5BEA" }} />
            <Line type="monotone" dataKey="rythme" stroke="#94A3B8" strokeWidth={1.6}
                  strokeDasharray="5 4" dot={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* ── Choix du produit ────────────────────────────────────────────── */}
      <div className="chart-card" style={{ gridColumn: "span 5" }}>
        <div className="card-header">
          <span className="card-label">Vos références</span>
        </div>
        <div style={{ position: "relative", marginBottom: 8 }}>
          <Search size={14} style={{ position: "absolute", left: 10, top: 9, color: "#94A3B8" }} />
          <input
            value={recherche}
            onChange={e => setRecherche(e.target.value)}
            placeholder="Rechercher un produit"
            style={{
              width: "100%", padding: "7px 10px 7px 31px", fontSize: "0.78rem",
              borderRadius: 9, border: "1px solid rgba(26,35,72,0.14)",
              background: "rgba(255,255,255,0.7)",
            }}
          />
        </div>
        <div style={{ maxHeight: 205, overflowY: "auto", display: "grid", gap: 5 }}>
          {filtrees.map(p => {
            const actif = p.produit === courant?.produit;
            const e = evolution(p.prevision_30j, p.moyenne_3m);
            return (
              <button
                key={p.produit}
                onClick={() => setSelection(p.produit)}
                style={{
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                  gap: 10, textAlign: "left", cursor: "pointer", width: "100%",
                  padding: "8px 10px", borderRadius: 9,
                  border: `1px solid ${actif ? "#2F5BEA" : "rgba(26,35,72,0.09)"}`,
                  background: actif ? "rgba(47,91,234,0.07)" : "transparent",
                }}
              >
                <span style={{
                  fontSize: "0.77rem", fontWeight: actif ? 700 : 500, color: "#16204A",
                  overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                }} title={p.produit}>
                  {p.produit}
                </span>
                <span style={{ display: "flex", alignItems: "center", gap: 7, flexShrink: 0 }}>
                  <b style={{ fontSize: "0.8rem", color: "#16204A" }}>{fNum(p.prevision_30j)}</b>
                  <span style={{ color: e.color, display: "inline-flex" }}>{e.icone}</span>
                </span>
              </button>
            );
          })}
          {!filtrees.length && <p className="muted-note">Aucun produit ne correspond.</p>}
        </div>
      </div>
    </div>
  );
}

function Volume({ label, valeur, sousTitre, accent, discret }: {
  label: string; valeur: number; sousTitre?: string; accent?: boolean; discret?: boolean;
}) {
  return (
    <div style={{
      padding: "13px 15px", borderRadius: 12,
      border: `1px solid ${accent ? "rgba(47,91,234,0.25)" : "rgba(26,35,72,0.09)"}`,
      background: accent
        ? "linear-gradient(160deg, rgba(47,91,234,0.09), rgba(20,194,214,0.05))"
        : "rgba(255,255,255,0.55)",
    }}>
      <div style={{ fontSize: "0.72rem", color: discret ? "#94A3B8" : "#64748B", fontWeight: 600 }}>
        {label}
      </div>
      <div style={{
        fontSize: accent ? "1.55rem" : "1.25rem", fontWeight: 800,
        color: discret ? "#64748B" : "#16204A", lineHeight: 1.15, marginTop: 2,
      }}>
        {fNum(valeur)}
      </div>
      <div style={{ fontSize: "0.68rem", color: "#94A3B8" }}>
        {sousTitre || "unités"}
      </div>
    </div>
  );
}
