"use client";

import { ArrowRight, Info, Timer, Truck } from "lucide-react";
import type { Delais, SensDelai } from "./tableauDeBord.types";
import { fMoney } from "./format";

const INK = { primary: "#16204A", secondary: "#5A6A8C", muted: "#93A0BC", border: "rgba(26,35,72,0.09)" };

function Sens({ titre, icone, d, couleur }: {
  titre: string; icone: React.ReactNode; d: SensDelai; couleur: string;
}) {
  return (
    <div style={{
      borderStyle: "solid", borderWidth: "1px 1px 1px 4px",
      borderColor: `${INK.border} ${INK.border} ${INK.border} ${couleur}`,
      borderRadius: 11, padding: "13px 15px", display: "grid", gap: 7,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 7, color: couleur }}>
        {icone}
        <span style={{ fontSize: "0.78rem", fontWeight: 700, color: INK.primary }}>{titre}</span>
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 9, flexWrap: "wrap" }}>
        <span style={{ fontSize: "1.7rem", fontWeight: 800, color: INK.primary, lineHeight: 1 }}>
          {d.moyenne_ponderee_j.toFixed(0)} j
        </span>
        <span style={{ fontSize: "0.72rem", color: INK.muted }}>
          pondéré par le montant
        </span>
      </div>
      <div style={{ fontSize: "0.73rem", color: INK.secondary }}>
        {d.moyenne_par_facture_j.toFixed(0)} j en moyenne simple, sur{" "}
        {d.n_factures.toLocaleString("fr-FR")} factures et {fMoney(d.montant_dt)}
      </div>
      <div style={{ fontSize: "0.72rem", color: INK.muted, lineHeight: 1.5 }}>{d.sens}</div>
    </div>
  );
}

/**
 * Les deux délais, leur écart, et ce que cet écart coûte ou rapporte.
 *
 * La moyenne pondérée est mise en avant et la moyenne simple reléguée : une
 * facture de 500 DT et une de 500 000 DT ne pèsent pas pareil sur la
 * trésorerie, alors qu'une moyenne par facture les compte à égalité. Sur ces
 * données, l'écart entre les deux lectures est important côté fournisseurs.
 */
export default function CarteDelais({ d }: { d?: Delais }) {
  if (!d) return null;
  const favorable = d.ecart_j < 0;
  const couleurEcart = favorable ? "#0CA30C" : "#D03B3B";

  return (
    <div className="chart-card" style={{ gridColumn: "span 12", padding: "16px 18px 14px" }}>
      <div className="card-label" style={{ display: "flex", alignItems: "center", gap: 7 }}>
        <Timer size={17} /> Qui attend qui, et combien de temps
      </div>
      <div style={{ fontSize: "0.74rem", color: INK.muted, marginTop: 3, textTransform: "none" }}>
        {d.nature}
      </div>

      <div style={{
        display: "grid", gap: 12, marginTop: 13, alignItems: "stretch",
        gridTemplateColumns: "1fr auto 1fr",
      }}>
        <Sens titre="Accordé à vos clients" icone={<Timer size={15} />}
          d={d.accorde_aux_clients} couleur="#2F5BEA" />
        <div style={{ display: "grid", placeItems: "center", padding: "0 4px" }}>
          <div style={{ textAlign: "center" }}>
            <ArrowRight size={18} style={{ color: INK.muted }} />
            <div style={{ fontSize: "1.2rem", fontWeight: 800, color: couleurEcart, marginTop: 4 }}>
              {d.ecart_j > 0 ? "+" : ""}{d.ecart_j.toFixed(0)} j
            </div>
            <div style={{ fontSize: "0.68rem", color: INK.muted }}>écart</div>
          </div>
        </div>
        <Sens titre="Obtenu de vos fournisseurs" icone={<Truck size={15} />}
          d={d.obtenu_des_fournisseurs} couleur="#0CA30C" />
      </div>

      <div style={{
        marginTop: 13, padding: "12px 14px", borderRadius: 10,
        background: favorable ? "rgba(12,163,12,0.06)" : "rgba(208,59,59,0.06)",
        border: `1px solid ${favorable ? "rgba(12,163,12,0.22)" : "rgba(208,59,59,0.22)"}`,
        display: "grid", gap: 6,
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", alignItems: "baseline" }}>
          <span style={{ fontSize: "0.8rem", fontWeight: 800, color: INK.primary }}>
            {d.tresorerie_cycle_libelle}
          </span>
          <span style={{ fontSize: "1.1rem", fontWeight: 800, color: couleurEcart }}>
            {fMoney(Math.abs(d.tresorerie_cycle_dt ?? 0))}
          </span>
        </div>
        <span style={{ fontSize: "0.75rem", color: INK.secondary, lineHeight: 1.55 }}>
          {d.ecart_lecture}
        </span>
        <span style={{ fontSize: "0.7rem", color: INK.muted, lineHeight: 1.5 }}>
          {d.tresorerie_cycle_methode}
        </span>
      </div>

      <div style={{ marginTop: 15 }}>
        <div style={{ fontSize: "0.74rem", fontWeight: 700, color: INK.secondary, marginBottom: 8 }}>
          Ce que vous accordez, par tranche
          {d.part_au_dela_du_seuil_pct != null && (
            <span style={{ fontWeight: 600, color: INK.muted }}>
              {" "}— {d.part_au_dela_du_seuil_pct.toFixed(0)} % du facturé au-delà de{" "}
              {d.seuil_surveillance_j} jours
            </span>
          )}
        </div>
        <div style={{ display: "grid", gap: 7 }}>
          {d.repartition.map(t => {
            const alerte = t.code === "j90" || t.code === "j90p";
            return (
              <div key={t.code} style={{
                display: "grid", gridTemplateColumns: "130px 1fr 150px",
                gap: 10, alignItems: "center",
              }}>
                <span style={{
                  fontSize: "0.76rem", fontWeight: 600,
                  color: alerte ? "#D03B3B" : INK.primary,
                }} title={t.signification}>
                  {t.tranche}
                </span>
                <div style={{ height: 8, borderRadius: 4, background: "rgba(26,35,72,0.05)" }}>
                  <div style={{
                    width: `${t.part_pct ?? 0}%`, height: "100%", borderRadius: 4,
                    background: alerte ? "#EC835A" : "#5580EE",
                  }} />
                </div>
                <span style={{ fontSize: "0.75rem", color: INK.secondary, textAlign: "right" }}>
                  <b style={{ color: INK.primary }}>{fMoney(t.montant_dt)}</b>
                  {t.part_pct != null && ` · ${t.part_pct.toFixed(0)} %`}
                  <em style={{ fontStyle: "normal", display: "block", fontSize: "0.67rem", color: INK.muted }}>
                    {t.n_factures.toLocaleString("fr-FR")} factures
                  </em>
                </span>
              </div>
            );
          })}
        </div>
      </div>

      <div style={{
        marginTop: 13, padding: "11px 13px", borderRadius: 10,
        background: "rgba(47,91,234,0.05)", border: `1px solid ${INK.border}`,
        fontSize: "0.74rem", color: INK.secondary, lineHeight: 1.55,
        display: "flex", gap: 9,
      }}>
        <Info size={15} style={{ color: "#2F5BEA", flexShrink: 0, marginTop: 1 }} />
        <span><b style={{ color: INK.primary }}>Ce n&apos;est pas</b> {d.ce_n_est_pas}</span>
      </div>
    </div>
  );
}
