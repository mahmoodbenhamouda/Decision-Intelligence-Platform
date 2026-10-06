"use client";

import { TrendingDown, TrendingUp } from "lucide-react";
import { cleFiltres, qsFiltres, useFiltresActifs } from "@/core/filtres/contexteFiltres";
import { api } from "@/core/api/client";
import { useRequete } from "@/core/hooks/useRequete";
import PanneauMasque from "@/shared/ui/PanneauMasque";
import { INK, fMoney, tronquer } from "@/shared/ui/VisuelKit";
import type { CaClientData, CaClientLigne, Portee } from "./commercial.types";

/**
 * Chiffre d'affaires attendu sur 3 mois, en Synthèse.
 *
 * La carte prolonge la courbe d'évolution juste au-dessus : le passé mesuré,
 * puis ce qui est attendu de la suite. Autonome dans son chargement, pour ne
 * pas faire dépendre la Synthèse des trois autres appels de l'onglet Devis.
 */
export default function CaAttenduCarte() {
  const filtres = useFiltresActifs();
  const r = useRequete<CaClientData & Portee>(async () => {
    try {
      const rep = await api(`/api/commercial/ca-client?horizon=3&limit=8&${qsFiltres(filtres)}`);
      return await rep.json();
    } catch {
      return { servi: false, motif: "Connexion au serveur impossible." };
    }
  }, cleFiltres(filtres));

  const ca = r.donnees;
  const horizon = ca?.horizon_mois ?? 3;

  if (r.chargement && !ca) {
    return (
      <div className="chart-card" style={{ gridColumn: "span 12" }}>
        <p className="muted-note">Prévision du chiffre d&apos;affaires…</p>
      </div>
    );
  }

  if (ca?.masque) {
    return (
      <div style={{ gridColumn: "span 12" }}>
        <PanneauMasque motif={ca.motif} />
      </div>
    );
  }

  const top = (ca?.top ?? []) as CaClientLigne[];
  if (!ca?.servi || !top.length) {
    return (
      <div className="chart-card" style={{ gridColumn: "span 12" }}>
        <div className="card-label">Chiffre d&apos;affaires attendu</div>
        <p className="muted-note" style={{ marginTop: 8 }}>
          {ca?.motif || "Prévision indisponible sur ce périmètre."}
        </p>
      </div>
    );
  }

  const nBaisse = top.filter(c => c.ecart_vs_passe_dt < 0).length;
  const max = Math.max(...top.map(c => Math.max(c.ca_attendu_dt, c.ca_passe_dt)), 1);
  const f = ca.fenetres;

  return (
    <div className="chart-card" style={{ gridColumn: "span 12", padding: "16px 18px 14px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
        <div>
          <div className="card-label" style={{ display: "flex", alignItems: "center", gap: 7 }}>
            <TrendingUp size={17} /> Chiffre d&apos;affaires attendu sur {horizon} mois
          </div>
          <div style={{ fontSize: "0.74rem", color: INK.muted, marginTop: 3, textTransform: "none" }}>
            {f
              ? <>Attendu <b>{f.futur_debut} → {f.futur_fin}</b>, comparé au mesuré{" "}
                  <b>{f.passe_debut} → {f.passe_fin}</b></>
              : <>Ce que les clients devraient acheter si rien ne change</>}
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: "1.5rem", fontWeight: 800, color: INK.primary, lineHeight: 1.1 }}>
            {fMoney(ca.ca_attendu_total_dt)}
          </div>
          <div style={{ fontSize: "0.72rem", color: INK.muted }}>
            {ca.n_clients ?? top.length} client{(ca.n_clients ?? top.length) > 1 ? "s" : ""} ·{" "}
            {nBaisse} en recul prévu
          </div>
        </div>
      </div>

      <div style={{ display: "grid", gap: 11, marginTop: 14 }}>
        {top.map(c => {
          const baisse = c.ecart_vs_passe_dt < 0;
          const pct = c.ca_passe_dt
            ? Math.round((c.ecart_vs_passe_dt / c.ca_passe_dt) * 100) : 0;
          // Une base de comparaison qui s'écarte de plus de 25 % du rythme
          // habituel du client rend le pourcentage trompeur : on le dit.
          const base = c.base_vs_rythme_pct ?? 0;
          const baseAnormale = Math.abs(base) >= 25 && c.rythme_habituel_dt != null;
          return (
            <div key={c.client} style={{
              display: "grid", gridTemplateColumns: "minmax(120px,1.4fr) 3fr auto",
              gap: 10, alignItems: "center",
            }}>
              <span style={{ fontSize: "0.79rem", fontWeight: 600, color: INK.primary }}
                    title={c.nom || c.client}>
                {tronquer(c.nom || c.client, 24)}
              </span>
              <div style={{ display: "grid", gap: 3 }}>
                <div style={{ height: 7, borderRadius: 4, background: "rgba(26,35,72,0.05)" }}
                     title={`Mesuré : ${fMoney(c.ca_passe_dt)}`}>
                  <div style={{
                    width: `${(c.ca_passe_dt / max) * 100}%`, height: "100%",
                    borderRadius: 4, background: "#C9D6FA",
                  }} />
                </div>
                <div style={{ height: 7, borderRadius: 4, background: "rgba(26,35,72,0.05)" }}
                     title={`Attendu : ${fMoney(c.ca_attendu_dt)}`}>
                  <div style={{
                    width: `${(c.ca_attendu_dt / max) * 100}%`, height: "100%",
                    borderRadius: 4, background: baisse ? "#EC835A" : "#34A853",
                  }} />
                </div>
                <div style={{ fontSize: "0.68rem", color: INK.muted }}>
                  mesuré {fMoney(c.ca_passe_dt)}
                  {c.rythme_habituel_dt != null && (
                    <> · rythme habituel {fMoney(c.rythme_habituel_dt)}</>
                  )}
                  {baseAnormale && (
                    <b style={{ color: "#E0A10F" }}>
                      {" "}— période {base > 0 ? "exceptionnellement forte" : "inhabituellement faible"} ({base > 0 ? "+" : ""}{base} %)
                    </b>
                  )}
                </div>
              </div>
              <span style={{
                fontSize: "0.78rem", fontWeight: 700, whiteSpace: "nowrap",
                color: baisse ? "#D03B3B" : "#0CA30C", minWidth: 118, textAlign: "right",
              }}>
                {fMoney(c.ca_attendu_dt)}
                <em style={{
                  fontStyle: "normal", display: "block", fontSize: "0.68rem",
                  color: INK.muted, fontWeight: 600,
                }}>
                  {baisse ? <TrendingDown size={9} style={{ verticalAlign: -1 }} />
                          : <TrendingUp size={9} style={{ verticalAlign: -1 }} />}{" "}
                  {pct >= 0 ? "+" : ""}{pct} % vs mesuré
                </em>
              </span>
            </div>
          );
        })}
      </div>

      {/* L'avertissement sur la base de comparaison tenait en un pavé que
          personne ne lisait. Il est devenu la mention « période exceptionnelle »
          posée sur la ligne concernée, là où elle sert. */}
      <div style={{
        display: "flex", gap: 16, marginTop: 12, flexWrap: "wrap",
        fontSize: "0.71rem", color: INK.secondary,
      }}>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <span style={{ width: 10, height: 6, borderRadius: 2, background: "#C9D6FA" }} />
          {horizon} mois écoulés
        </span>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <span style={{ width: 10, height: 6, borderRadius: 2, background: "#34A853" }} />
          attendu, en hausse
        </span>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <span style={{ width: 10, height: 6, borderRadius: 2, background: "#EC835A" }} />
          attendu, en recul
        </span>
      </div>
    </div>
  );
}
