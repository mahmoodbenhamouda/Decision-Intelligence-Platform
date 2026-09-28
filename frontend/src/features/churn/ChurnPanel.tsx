"use client";

/**
 * ChurnPanel — clients susceptibles de cesser de commander.
 *
 * Destiné au DIRECTEUR : aucun vocabulaire technique n'apparaît à l'écran.
 * Pas de « modèle », « score », « probabilité », « AUC » ni « prédiction » —
 * seulement des phrases qu'un responsable commercial lit sans traduction.
 *
 * Ce que le panneau montre réellement : parmi les clients qui commandent encore,
 * lesquels risquent de s'arrêter dans les trois mois. C'est la différence avec
 * l'onglet Clients, qui constate les baisses de chiffre d'affaires déjà
 * survenues — quand le compte est souvent déjà perdu.
 *
 * Le classement suit le MONTANT EN JEU (risque × chiffre d'affaires annuel) et
 * non le risque seul : un risque élevé sur un petit compte ne justifie pas la
 * même attention qu'un risque modéré sur un compte majeur.
 */

import {
  CartesianGrid, ResponsiveContainer, Scatter, ScatterChart,
  Tooltip as RTooltip, XAxis, YAxis, ZAxis,
} from "recharts";
import { AlertTriangle, CalendarClock, TrendingDown, UserMinus } from "lucide-react";
import Pourquoi from "@/shared/ui/Pourquoi";
import type { ChurnClient } from "./churn.types";
import { useChurn } from "./useChurn";

function fMoney(v: number | null | undefined) {
  if (v == null || Number.isNaN(v)) return "—";
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(2)} M DT`;
  if (Math.abs(v) >= 1e3) return `${(v / 1e3).toFixed(0)} K DT`;
  return `${v.toFixed(0)} DT`;
}

/** Quatre niveaux, pas dix. Un dégradé continu ne se traduit pas en décision ;
 *  quatre paliers correspondent à quatre conduites à tenir. */
function niveau(p: number) {
  if (p >= 0.7) return { label: "Très inquiétant", color: "#DC2626", action: "Appeler cette semaine" };
  if (p >= 0.5) return { label: "Inquiétant", color: "#F97316", action: "Reprendre contact" };
  if (p >= 0.3) return { label: "À surveiller", color: "#F59E0B", action: "Garder un œil" };
  return { label: "Rassurant", color: "#10B981", action: "Suivi habituel" };
}

/** Le risque exprimé en mots. Un pourcentage invite à une précision que
 *  l'estimation n'a pas ; une formulation verbale reste juste. */
function enMots(p: number): string {
  if (p >= 0.7) return "Très probable";
  if (p >= 0.5) return "Probable";
  if (p >= 0.3) return "Possible";
  return "Peu probable";
}

export default function ChurnPanel({ clientNames }: {
  clientNames?: Record<string, string>;
}) {
  const { data, loading } = useChurn();

  // Le nom vient de l'API, qui le joint depuis l'entrepôt. La table locale sert
  // de repli, et le code n'apparaît qu'en dernier recours.
  const nomDe = (c: ChurnClient) => c.nom || clientNames?.[c.code] || c.code;

  if (loading) return <p className="muted-note">Analyse de vos clients en cours…</p>;

  if (!data?.servi) {
    return (
      <div className="card-note">
        <AlertTriangle size={14} style={{ color: "#F59E0B" }} />
        <span className="card-label">
          Cette analyse n&apos;est pas disponible pour le moment
          {data?.motif ? ` — ${data.motif}` : ""}.
        </span>
      </div>
    );
  }

  const top = data.top || [];
  const nuage = top.map(c => ({
    x: Math.round(c.probabilite_decrochage * 100),
    y: c.ca_12m,
    z: Math.max(1, c.enjeu_dt),
    nom: nomDe(c),
    recence: c.recence_j,
    couleur: niveau(c.probabilite_decrochage).color,
  }));

  const urgents = top.filter(c => c.probabilite_decrochage >= 0.5);

  return (
    <div style={{ display: "grid", gap: 16 }}>
      {/* ── Ce qu'il faut retenir, en une phrase ────────────────────────── */}
      <div className="chart-card" style={{
        padding: "15px 17px", borderLeft: "4px solid #DC2626",
        background: "linear-gradient(90deg, rgba(220,38,38,0.04), rgba(255,255,255,0))",
      }}>
        <div style={{ fontSize: 15.5, fontWeight: 700, color: "#16204A", marginBottom: 4 }}>
          {urgents.length > 0
            ? `${urgents.length} client${urgents.length > 1 ? "s" : ""} risque${urgents.length > 1 ? "nt" : ""} de vous quitter`
            : "Aucun client majeur ne semble sur le départ"}
        </div>
        <div style={{ fontSize: 13, color: "#475569", lineHeight: 1.55 }}>
          {urgents.length > 0 ? (
            <>Ils représentent <b>{fMoney(urgents.reduce((s, c) => s + c.ca_12m, 0))}</b> de
            chiffre d&apos;affaires sur les douze derniers mois. Ils commandent encore
            aujourd&apos;hui — c&apos;est maintenant qu&apos;un contact peut les retenir.</>
          ) : (
            <>Vos clients actifs conservent leur rythme de commande habituel.</>
          )}
        </div>
      </div>

      {/* ── Trois chiffres, pas plus ────────────────────────────────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(190px,1fr))", gap: 12 }}>
        <Case icon={<UserMinus size={15} />} couleur="#DC2626"
              label="Clients à relancer"
              valeur={`${data.n_au_dessus_de_0_5 ?? 0}`}
              sous={`parmi ${data.n_clients_scores ?? 0} clients actifs`} />
        <Case icon={<TrendingDown size={15} />} couleur="#F97316"
              label="Chiffre d'affaires en jeu"
              valeur={fMoney(data.enjeu_total_dt)}
              sous="montant qui pourrait être perdu" />
        <Case icon={<CalendarClock size={15} />} couleur="#8B5CF6"
              label="Horizon"
              valeur="3 mois"
              sous="délai avant un arrêt probable" />
      </div>

      {/* ── La carte des priorités ──────────────────────────────────────── */}
      <div className="chart-card" style={{ padding: 15 }}>
        <p className="card-label" style={{ marginBottom: 10 }}>Où concentrer vos efforts</p>
        <div style={{ height: 280 }}>
          <ResponsiveContainer>
            <ScatterChart margin={{ top: 10, right: 20, bottom: 26, left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(26,35,72,0.07)" />
              <XAxis
                type="number" dataKey="x" domain={[0, 100]} tick={{ fontSize: 11 }}
                ticks={[0, 30, 50, 70, 100]}
                tickFormatter={(v: number) =>
                  v === 0 ? "Fidèle" : v === 50 ? "Incertain" : v === 100 ? "Sur le départ" : ""}
                label={{ value: "Risque de départ", position: "insideBottom", offset: -14, fontSize: 11.5, fill: "#64748B" }}
              />
              <YAxis
                type="number" dataKey="y" tick={{ fontSize: 11 }}
                tickFormatter={(v: number) => Math.abs(v) >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : `${(v / 1e3).toFixed(0)}k`}
                label={{ value: "CA sur 12 mois (DT)", angle: -90, position: "insideLeft", fontSize: 11.5, fill: "#64748B" }}
              />
              <ZAxis type="number" dataKey="z" range={[60, 500]} />
              <RTooltip
                cursor={{ strokeDasharray: "3 3" }}
                content={({ active, payload }) => {
                  if (!active || !payload?.length) return null;
                  const d = payload[0].payload as typeof nuage[number];
                  return (
                    <div style={{
                      background: "rgba(255,255,255,0.98)", border: "1px solid rgba(26,35,72,0.12)",
                      borderRadius: 10, padding: "9px 11px", fontSize: 12.5,
                      boxShadow: "0 8px 24px rgba(26,35,72,0.14)",
                    }}>
                      <b style={{ fontSize: 13 }}>{d.nom}</b>
                      <div style={{ marginTop: 4, color: "#475569" }}>
                        Départ {enMots(d.x / 100).toLowerCase()}<br />
                        {fMoney(d.y)} sur 12 mois<br />
                        Sans commande depuis {d.recence} jours
                      </div>
                    </div>
                  );
                }}
              />
              <Scatter data={nuage} fillOpacity={0.75}>
                {nuage.map((p, i) => <circle key={i} fill={p.couleur} />)}
              </Scatter>
            </ScatterChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* ── La liste d'appels ───────────────────────────────────────────── */}
      <div className="chart-card" style={{ padding: 15 }}>
        <p className="card-label" style={{ marginBottom: 10 }}>Votre liste d&apos;appels</p>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ textAlign: "left", color: "#64748B", fontSize: 11.5 }}>
                <th style={{ padding: "7px 9px" }}>Client</th>
                <th style={{ padding: "7px 9px" }}>Situation</th>
                <th style={{ padding: "7px 9px" }}>À faire</th>
                <th style={{ padding: "7px 9px", textAlign: "right" }}>Montant en jeu</th>
                <th style={{ padding: "7px 9px", textAlign: "right" }}>Dernière commande</th>
              </tr>
            </thead>
            <tbody>
              {top.map(c => {
                const n = niveau(c.probabilite_decrochage);
                // Un silence n'est anormal que rapporté au rythme habituel du
                // client : 60 jours ne signifient rien pour un client trimestriel,
                // beaucoup pour un client hebdomadaire.
                const anormal = c.intervalle_moyen_j > 0
                  && c.recence_j > c.intervalle_moyen_j * 2;
                return (
                  <tr key={c.code} style={{ borderTop: "1px solid rgba(26,35,72,0.07)" }}>
                    <td style={{ padding: "9px" }}>
                      <div style={{ fontWeight: 600, color: "#16204A" }}>{nomDe(c)}</div>
                      <div style={{ fontSize: 11, color: "#64748B" }}>
                        {fMoney(c.ca_12m)} sur 12 mois · {c.freq_12m} commande{c.freq_12m > 1 ? "s" : ""}
                      </div>
                      {/* La justification se lit là où la décision se prend :
                          sur la ligne du client qu'on s'apprête à appeler. */}
                      <div style={{ marginTop: 5 }}>
                        <Pourquoi raisons={c.raisons}
                          titre={`Pourquoi ${nomDe(c)} est signalé`} />
                      </div>
                    </td>
                    <td style={{ padding: "9px" }}>
                      <span style={{
                        background: `${n.color}18`, color: n.color, borderRadius: 6,
                        padding: "3px 8px", fontSize: 11.5, fontWeight: 600, whiteSpace: "nowrap",
                      }}>{n.label}</span>
                    </td>
                    <td style={{ padding: "9px", color: "#475569", fontSize: 12.5 }}>{n.action}</td>
                    <td style={{ padding: "9px", textAlign: "right", fontWeight: 700, color: "#16204A" }}>
                      {fMoney(c.enjeu_dt)}
                    </td>
                    <td style={{ padding: "9px", textAlign: "right" }}>
                      <span style={{ color: anormal ? "#DC2626" : "#475569", fontWeight: anormal ? 600 : 400 }}>
                        il y a {c.recence_j} j
                      </span>
                      <div style={{ fontSize: 10.5, color: "#94A3B8" }}>
                        habituellement tous les {c.intervalle_moyen_j.toFixed(0)} j
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

    </div>
  );
}

function Case({ icon, label, valeur, sous, couleur }: {
  icon: React.ReactNode; label: string; valeur: string; sous: string; couleur: string;
}) {
  return (
    <div style={{
      background: "rgba(255,255,255,0.65)", border: "1px solid rgba(26,35,72,0.09)",
      borderRadius: 12, padding: "12px 14px",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, color: couleur, marginBottom: 5 }}>
        {icon}<span style={{ fontSize: 11.5, fontWeight: 600 }}>{label}</span>
      </div>
      <div style={{ fontSize: 22, fontWeight: 700, color: "#16204A", lineHeight: 1.1 }}>{valeur}</div>
      <div style={{ fontSize: 11, color: "#64748B", marginTop: 3 }}>{sous}</div>
    </div>
  );
}
