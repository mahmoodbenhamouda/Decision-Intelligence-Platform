"use client";

import { CheckCircle2, UserPlus } from "lucide-react";
import type { Confiee, Origine } from "@/features/taches/taches.types";
import Pourquoi from "@/shared/ui/Pourquoi";
import { INK, fMoney, tronquer } from "@/shared/ui/VisuelKit";
import { PROTOCOLE_STYLE, origineDevis } from "./commercial.regles";
import type { CodeProtocole, DevisLigne, Protocole } from "./commercial.types";
import { LIBELLE_CHANCE, type TrancheChance, type TriDevis } from "./useCommercial";

const fDate = (d?: string) => (d ? new Date(d).toLocaleDateString("fr-FR") : "—");

const COLONNES: { cle: TriDevis; label: string }[] = [
  { cle: "esperance", label: "Ventes probables" },
  { cle: "montant", label: "Montant" },
  { cle: "chance", label: "Chance" },
  { cle: "age", label: "Ancienneté" },
];

/** Les quatre protocoles, en cases cliquables qui filtrent le tableau. */
export function CasesProtocole({ protocoles, actif, onActif, seuilGros, seuilChance }: {
  protocoles: Protocole[];
  actif: CodeProtocole | null;
  onActif: (p: CodeProtocole | null) => void;
  seuilGros?: number;
  seuilChance?: number;
}) {
  if (!protocoles.length) return null;
  return (
    <>
      <div style={{
        display: "grid", gap: 10,
        gridTemplateColumns: "repeat(auto-fit, minmax(235px, 1fr))",
      }}>
        {protocoles.map(p => {
          const style = PROTOCOLE_STYLE[p.code] ?? PROTOCOLE_STYLE.laisser;
          const choisi = actif === p.code;
          return (
            <button key={p.code} type="button"
              onClick={() => onActif(choisi ? null : p.code)}
              // Un seul raccourci par propriété, jamais de longue à côté :
              // `borderColor` couvre déjà les quatre côtés, lui adjoindre
              // `borderLeftColor` fait diverger React au rerendu. Les quatre
              // valeurs sont donc données dans l'ordre haut/droite/bas/gauche.
              style={{
                textAlign: "left", cursor: "pointer",
                borderStyle: "solid",
                borderWidth: "1px 1px 1px 4px",
                borderColor: [choisi ? style.couleur : INK.border,
                              choisi ? style.couleur : INK.border,
                              choisi ? style.couleur : INK.border,
                              style.couleur].join(" "),
                borderRadius: 11,
                padding: "12px 14px", display: "grid", gap: 6,
                background: choisi ? `${style.couleur}0D` : "rgba(255,255,255,0.6)",
              }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "baseline" }}>
                <span style={{ fontWeight: 800, color: INK.primary, fontSize: "0.86rem" }}>
                  {p.libelle}
                </span>
                <span style={{ fontWeight: 800, color: style.couleur, fontSize: "0.86rem", whiteSpace: "nowrap" }}>
                  {fMoney(p.esperance_dt)}
                </span>
              </div>
              <div style={{ fontSize: "0.72rem", color: INK.secondary }}>
                {p.n_devis} devis · {fMoney(p.montant_ouvert_dt)} ouverts ·{" "}
                {p.n_clients} client{p.n_clients > 1 ? "s" : ""} · {p.age_median_j} j d&apos;ancienneté médiane
              </div>
              <div style={{ fontSize: "0.71rem", color: INK.muted, lineHeight: 1.5 }}>
                {p.quoi_faire}
              </div>
            </button>
          );
        })}
      </div>
      <p className="muted-note" style={{ marginTop: 9, fontSize: "0.71rem" }}>
        Séparation à {fMoney(seuilGros)} de montant et {seuilChance ?? 25} % de chance de
        signature. Cliquez sur une case pour ne garder que ces devis.
        {actif && " Cliquez à nouveau pour tout revoir."}
      </p>
    </>
  );
}

const TRANCHES: TrancheChance[] = ["toutes", "haute", "moyenne", "basse"];

/**
 * Les deux filtres que la liste accepte, et ils se combinent.
 *
 * « À faire » reprend les quatre protocoles — les mêmes que les cases
 * cliquables au-dessus, en sélecteur pour qui préfère la liste. « Chance »
 * découpe selon le seuil publié par le backend, et non selon une valeur écrite
 * ici : le même seuil sépare les protocoles, donc les deux filtres ne peuvent
 * pas se contredire.
 */
export function FiltresDevis({
  protocoleActif, onProtocole, protocoles,
  tranche, onTranche, compteTranche, seuilHaut, seuilBas,
}: {
  protocoleActif: CodeProtocole | null;
  onProtocole: (p: CodeProtocole | null) => void;
  protocoles: Protocole[];
  tranche: TrancheChance;
  onTranche: (t: TrancheChance) => void;
  compteTranche: Record<TrancheChance, number>;
  seuilHaut: number;
  seuilBas: number;
}) {
  const bornes: Record<TrancheChance, string> = {
    toutes: "",
    haute: `≥ ${seuilHaut} %`,
    moyenne: `${seuilBas}–${seuilHaut} %`,
    basse: `< ${seuilBas} %`,
  };
  return (
    <div style={{
      display: "flex", gap: 14, flexWrap: "wrap", alignItems: "flex-end",
      marginBottom: 12,
    }}>
      <label style={{ display: "grid", gap: 4 }}>
        <span style={{ fontSize: "0.7rem", color: INK.muted, fontWeight: 700 }}>
          À faire
        </span>
        <select className="mini" value={protocoleActif ?? ""}
          onChange={e => onProtocole((e.target.value || null) as CodeProtocole | null)}
          style={{ minWidth: 180, fontSize: "0.76rem" }}>
          <option value="">Toutes les actions</option>
          {protocoles.map(p => (
            <option key={p.code} value={p.code}>
              {PROTOCOLE_STYLE[p.code]?.verbe ?? p.libelle} ({p.n_devis})
            </option>
          ))}
        </select>
      </label>

      <label style={{ display: "grid", gap: 4 }}>
        <span style={{ fontSize: "0.7rem", color: INK.muted, fontWeight: 700 }}>
          Chance de signature
        </span>
        <select className="mini" value={tranche}
          onChange={e => onTranche(e.target.value as TrancheChance)}
          style={{ minWidth: 200, fontSize: "0.76rem" }}>
          {TRANCHES.map(t => (
            <option key={t} value={t}>
              {LIBELLE_CHANCE[t]}{bornes[t] ? ` ${bornes[t]}` : ""} ({compteTranche[t]})
            </option>
          ))}
        </select>
      </label>

      {(protocoleActif || tranche !== "toutes") && (
        <button type="button"
          onClick={() => { onProtocole(null); onTranche("toutes"); }}
          style={{
            background: "none", border: "none", padding: "0 0 6px", font: "inherit",
            fontSize: "0.73rem", fontWeight: 700, color: "#2F5BEA", cursor: "pointer",
          }}>
          Tout revoir
        </button>
      )}
    </div>
  );
}

export default function DevisOuverts({
  lignes, tri, onTri, confiees, onConfier, ageMort,
}: {
  lignes: (DevisLigne & { nomCourt: string; chance: number })[];
  tri: TriDevis;
  onTri: (t: TriDevis) => void;
  confiees: Record<string, Confiee>;
  onConfier: (o: Origine) => void;
  ageMort?: number;
}) {
  if (!lignes.length) {
    return <p className="muted-note" style={{ padding: "16px 2px" }}>
      Aucun devis ne répond à ces deux filtres. Élargissez la tranche de chance
      ou choisissez une autre action à mener.
    </p>;
  }
  const limite = ageMort ?? 120;

  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.79rem" }}>
        <thead>
          <tr style={{ textAlign: "left", color: INK.muted, fontSize: "0.7rem" }}>
            <th style={{ padding: "6px 8px" }}>Client et devis</th>
            <th style={{ padding: "6px 8px" }}>À faire</th>
            {COLONNES.map(c => (
              <th key={c.cle} style={{ padding: "6px 8px", textAlign: "right" }}>
                <button type="button" onClick={() => onTri(c.cle)}
                  style={{
                    background: "none", border: "none", cursor: "pointer", padding: 0,
                    font: "inherit", textTransform: "inherit",
                    color: tri === c.cle ? INK.primary : INK.muted,
                    fontWeight: tri === c.cle ? 800 : 600,
                  }}
                  title={`Trier par ${c.label.toLowerCase()}`}>
                  {c.label}{tri === c.cle ? " ↓" : ""}
                </button>
              </th>
            ))}
            <th style={{ padding: "6px 8px", textAlign: "right" }}>Action</th>
          </tr>
        </thead>
        <tbody>
          {lignes.map(x => {
            const style = PROTOCOLE_STYLE[x.protocole] ?? PROTOCOLE_STYLE.laisser;
            const origine = origineDevis(x);
            const deja = confiees[origine.titre];
            const vieux = x.age_j > limite;
            return (
              <tr key={x.piece_no} style={{ borderTop: `1px solid ${INK.grid}` }}>
                <td style={{ padding: "8px" }}>
                  <div style={{ fontWeight: 600, color: INK.primary }} title={x.nom || x.client}>
                    {tronquer(x.nom || x.client, 30)}
                  </div>
                  <div style={{ fontSize: "0.68rem", color: INK.muted }}>
                    {x.piece_no} · émis le {fDate(x.date)}
                  </div>
                  {!!x.raisons?.length && (
                    <div style={{ marginTop: 4 }}>
                      <Pourquoi raisons={x.raisons} titre={`Pourquoi ce devis — ${x.nom || x.client}`} />
                    </div>
                  )}
                </td>
                <td style={{ padding: "8px" }}>
                  <span style={{
                    background: `${style.couleur}18`, color: style.couleur, borderRadius: 6,
                    padding: "3px 8px", fontSize: "0.7rem", fontWeight: 700, whiteSpace: "nowrap",
                  }}>{style.verbe}</span>
                </td>
                <td style={{ padding: "8px", textAlign: "right", fontWeight: 800, color: INK.primary }}>
                  {fMoney(x.esperance_dt)}
                </td>
                <td style={{ padding: "8px", textAlign: "right", color: INK.secondary }}>
                  {fMoney(x.montant_ht_dt)}
                </td>
                <td style={{ padding: "8px", textAlign: "right", color: INK.secondary }}>
                  {x.chance} %
                </td>
                <td style={{ padding: "8px", textAlign: "right" }}>
                  <span style={{ color: vieux ? "#D03B3B" : INK.secondary, fontWeight: vieux ? 700 : 400 }}>
                    {x.age_j} j
                  </span>
                  {vieux && (
                    <em style={{
                      fontStyle: "normal", display: "block", fontSize: "0.66rem", color: INK.muted,
                    }}>
                      au-delà de {limite} j
                    </em>
                  )}
                </td>
                <td style={{ padding: "8px", textAlign: "right" }}>
                  {x.protocole === "laisser" ? (
                    <span style={{ fontSize: "0.7rem", color: INK.muted }}>—</span>
                  ) : deja ? (
                    <span className="vk-confiee"
                      title={`Confiée à ${deja.assigne_nom || "un responsable à désigner"}`}>
                      <CheckCircle2 size={12} /> Confiée
                    </span>
                  ) : (
                    <button className="vk-bouton-mini" onClick={() => onConfier(origine)}>
                      <UserPlus size={12} /> Confier
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
