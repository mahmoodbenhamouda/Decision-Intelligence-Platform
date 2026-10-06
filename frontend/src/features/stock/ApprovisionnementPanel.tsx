"use client";

import {
  AlertTriangle, Globe, PackageSearch, ShoppingCart, Truck,
} from "lucide-react";
import { api } from "@/core/api/client";
import { cleFiltres, qsFiltres, useFiltresActifs } from "@/core/filtres/contexteFiltres";
import { useRequete } from "@/core/hooks/useRequete";
import {
  BLEU, Carte, INK, RangeeTuiles, TuileChiffre, Vide, fMoney, tronquer,
} from "@/shared/ui/VisuelKit";
import BoucleCommandes from "./BoucleCommandes";
import SupplyCard from "./SupplyCard";
import type { ConsommationClient, ProcessusAppro } from "./approvisionnement.types";

const fPct = (v: number | null | undefined) =>
  v == null ? "—" : `${v.toFixed(1).replace(".", ",")} %`;

/**
 * Ce que le client filtré consomme, et ce qui risque de lui manquer.
 *
 * Le stock est une analyse par produit : filtrer sur un client masquait tout
 * l'écran. C'était une réponse paresseuse — ce qu'un directeur veut savoir
 * d'un client ici existe très bien : ce qu'il achète, et si l'approvisionnement
 * de ces produits-là tient.
 */
function ConsommationCarte({ c }: { c: ConsommationClient }) {
  const alerte = c.n_produits_menaces > 0;
  return (
    <Carte span={12} titre="Ce que ce client consomme" icone={<PackageSearch size={15} />}
      sousTitre={`${c.n_produits} références sur les ${c.periode}, pour ${fMoney(c.ca_total_dt)}`}>
      {alerte && (
        <div style={{
          padding: "11px 13px", borderRadius: 10, marginBottom: 12,
          background: "rgba(208,59,59,0.06)", borderWidth: 1, borderStyle: "solid",
          borderColor: "rgba(208,59,59,0.22)", display: "flex", gap: 9,
        }}>
          <AlertTriangle size={16} style={{ color: "#D03B3B", flexShrink: 0, marginTop: 2 }} />
          <span style={{ fontSize: "0.78rem", color: INK.secondary, lineHeight: 1.55 }}>
            <b style={{ color: INK.primary }}>
              {c.n_produits_menaces} produit{c.n_produits_menaces > 1 ? "s" : ""} à
              réapprovisionner d&apos;urgence
            </b>{" "}
            — {fMoney(c.ca_menace_dt)} du chiffre d&apos;affaires de ce client en dépend.
            {" "}{c.lecture}
          </span>
        </div>
      )}
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.79rem" }}>
          <thead>
            <tr style={{ textAlign: "left", color: INK.muted, fontSize: "0.7rem" }}>
              <th style={{ padding: "6px 8px" }}>Produit</th>
              <th style={{ padding: "6px 8px", textAlign: "right" }}>Chiffre d&apos;affaires</th>
              <th style={{ padding: "6px 8px", textAlign: "right" }}>Quantité</th>
              <th style={{ padding: "6px 8px", textAlign: "right" }}>Mois actifs</th>
              <th style={{ padding: "6px 8px" }}>Approvisionnement</th>
            </tr>
          </thead>
          <tbody>
            {c.produits.map(p => (
              <tr key={p.reference} style={{ borderTopWidth: 1, borderTopStyle: "solid", borderTopColor: INK.grid }}>
                <td style={{ padding: "8px" }}>
                  <div style={{ fontWeight: 600, color: INK.primary }} title={p.designation}>
                    {tronquer(p.designation, 38)}
                  </div>
                  <div style={{ fontSize: "0.68rem", color: INK.muted }}>{p.reference}</div>
                </td>
                <td style={{ padding: "8px", textAlign: "right", fontWeight: 700, color: INK.primary }}>
                  {fMoney(p.ca_dt)}
                </td>
                <td style={{ padding: "8px", textAlign: "right", color: INK.secondary }}>
                  {p.quantite.toLocaleString("fr-FR")}
                </td>
                <td style={{ padding: "8px", textAlign: "right", color: INK.secondary }}>
                  {p.mois_actifs} / 12
                </td>
                <td style={{ padding: "8px" }}>
                  {p.approvisionnement_menace ? (
                    <span style={{
                      background: "rgba(208,59,59,0.12)", color: "#D03B3B", borderRadius: 6,
                      padding: "3px 8px", fontSize: "0.69rem", fontWeight: 700, whiteSpace: "nowrap",
                    }}>
                      à recommander · {p.jours_depuis_achat} j sans achat
                    </span>
                  ) : (
                    <span style={{ fontSize: "0.71rem", color: INK.muted }}>
                      {p.rythme_reassort_j
                        ? `réassorti tous les ${p.rythme_reassort_j} j`
                        : "rythme non établi"}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Carte>
  );
}

export default function ApprovisionnementPanel() {
  const filtres = useFiltresActifs();
  const r = useRequete<ProcessusAppro>(async () => {
    try {
      const rep = await api(`/api/stock/approvisionnement?${qsFiltres(filtres)}`);
      return await rep.json();
    } catch {
      return { servi: false, motif: "Connexion au serveur impossible." };
    }
  }, cleFiltres(filtres));

  const d = r.donnees;
  if (r.chargement && !d) {
    return <Carte titre="Processus d'approvisionnement"><Vide texte="Chargement…" /></Carte>;
  }
  if (!d?.servi) {
    return (
      <Carte titre="Processus d'approvisionnement">
        <Vide texte={d?.motif || "Aucune facture d'achat sur ce périmètre."} />
      </Carte>
    );
  }

  const f = d.fournisseurs!;
  const ms = d.mono_source!;
  const ra = d.reapprovisionnement!;
  const dep = f.dependance;
  const cc = d.consommation_client as ConsommationClient | undefined;
  const parClient = cc && "n_produits" in cc && cc.n_produits > 0 ? cc : null;

  return (
    <>
      {/* Quand des clients sont filtrés, ce qu'ils consomment passe en tête :
          c'est la seule partie de ce volet qui dépende d'eux. */}
      {parClient && <ConsommationCarte c={parClient} />}

      {/* Prévision de demande et concentration des achats : le modèle vivait
          dans « Produits & achats », loin du stock qu'il sert à anticiper. */}
      <SupplyCard />

      <RangeeTuiles>
        <TuileChiffre icone={<Truck size={16} />} label="Fournisseurs"
          valeur={`${f.n_fournisseurs}`}
          detail={`${fMoney(f.achats_total_dt)} d'achats`} />
        <TuileChiffre icone={<AlertTriangle size={16} />} label="Dépendance au premier"
          valeur={fPct(dep.part_pct)}
          detail={dep.fournisseur ? tronquer(dep.fournisseur, 26) : "—"}
          accent={dep.critique ? "#D03B3B" : BLEU[3]} />
        <TuileChiffre icone={<PackageSearch size={16} />} label="Références sans repli"
          valeur={`${ms.n_mono_source}`}
          detail={`${fPct(ms.part_mono_source_pct)} du catalogue acheté`}
          accent="#EC835A" />
        <TuileChiffre icone={<ShoppingCart size={16} />} label="Rythme de réassort"
          valeur={ra.intervalle_median_j == null ? "—" : `${ra.intervalle_median_j} j`}
          detail={`médiane sur ${ra.n_references} références`} />
      </RangeeTuiles>

      {/* La carte « processus étape par étape » a été retirée : elle décrivait
          l'application au lieu de servir une décision, et occupait un écran
          entier. Ce qu'elle apportait d'utile — le délai de livraison désormais
          mesuré — vit dans la boucle ci-dessous. */}
      <BoucleCommandes />

      {dep.critique && dep.consequence && (
        <div style={{
          gridColumn: "span 12", padding: "13px 15px", borderRadius: 11,
          background: "rgba(208,59,59,0.06)", borderWidth: 1, borderStyle: "solid",
          borderColor: "rgba(208,59,59,0.22)", display: "flex", gap: 10,
        }}>
          <AlertTriangle size={17} style={{ color: "#D03B3B", flexShrink: 0, marginTop: 2 }} />
          <div style={{ display: "grid", gap: 5 }}>
            <span style={{ fontWeight: 800, color: INK.primary, fontSize: "0.86rem" }}>
              Dépendance à un fournisseur unique
            </span>
            <span style={{ fontSize: "0.76rem", color: INK.secondary, lineHeight: 1.55 }}>
              {dep.consequence}
            </span>
          </div>
        </div>
      )}

      <Carte span={7} titre="Qui vous fournit" icone={<Truck size={15} />}
        sousTitre="Montant acheté, part, délai de paiement obtenu">
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.79rem" }}>
            <thead>
              <tr style={{ textAlign: "left", color: INK.muted, fontSize: "0.7rem" }}>
                <th style={{ padding: "6px 8px" }}>Fournisseur</th>
                <th style={{ padding: "6px 8px", textAlign: "right" }}>Achats</th>
                <th style={{ padding: "6px 8px", textAlign: "right" }}>Part</th>
                <th style={{ padding: "6px 8px", textAlign: "right" }}>Références</th>
                <th style={{ padding: "6px 8px", textAlign: "right" }}>Délai obtenu</th>
              </tr>
            </thead>
            <tbody>
              {f.top.map(x => (
                <tr key={x.code} style={{ borderTop: `1px solid ${INK.grid}` }}>
                  <td style={{ padding: "8px" }}>
                    <div style={{ fontWeight: 600, color: INK.primary }} title={x.nom}>
                      {tronquer(x.nom, 30)}
                    </div>
                    <div style={{ fontSize: "0.68rem", color: INK.muted }}>
                      {x.pays} · {x.n_factures} factures
                    </div>
                  </td>
                  <td style={{ padding: "8px", textAlign: "right", fontWeight: 700, color: INK.primary }}>
                    {fMoney(x.montant_dt)}
                  </td>
                  <td style={{
                    padding: "8px", textAlign: "right", fontWeight: 700,
                    color: x.part_pct >= f.dependance.seuil_pct ? "#D03B3B" : INK.secondary,
                  }}>
                    {fPct(x.part_pct)}
                  </td>
                  <td style={{ padding: "8px", textAlign: "right", color: INK.secondary }}>
                    {x.n_references}
                  </td>
                  <td style={{ padding: "8px", textAlign: "right", color: INK.secondary }}>
                    {x.delai_obtenu_j == null ? "—" : `${x.delai_obtenu_j} j`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Carte>

      <Carte span={5} titre="D'où viennent les achats" icone={<Globe size={15} />}
        sousTitre="Concentration géographique de l'approvisionnement">
        <div style={{ display: "grid", gap: 8 }}>
          {f.par_pays.map(p => (
            <div key={p.pays} style={{
              display: "grid", gridTemplateColumns: "120px 1fr 118px",
              gap: 10, alignItems: "center",
            }}>
              <span style={{ fontSize: "0.77rem", fontWeight: 600, color: INK.primary }}>
                {tronquer(p.pays, 18)}
              </span>
              <div style={{ height: 8, borderRadius: 4, background: "rgba(26,35,72,0.05)" }}>
                <div style={{
                  width: `${p.part_pct}%`, height: "100%", borderRadius: 4,
                  background: p.part_pct >= 50 ? "#EC835A" : BLEU[3],
                }} />
              </div>
              <span style={{ fontSize: "0.74rem", color: INK.secondary, textAlign: "right" }}>
                <b style={{ color: INK.primary }}>{fPct(p.part_pct)}</b>
                <em style={{ fontStyle: "normal", display: "block", fontSize: "0.67rem", color: INK.muted }}>
                  {fMoney(p.montant_dt)} · {p.n_fournisseurs} fourn.
                </em>
              </span>
            </div>
          ))}
        </div>
      </Carte>

      {/* La liste des références mono-source a été retirée : 1 834 lignes
          toutes chez le même fournisseur ne se traitent pas une par une. Le
          chiffre global et sa conséquence restent dans l'alerte de dépendance
          ci-dessus, qui est le niveau où la décision se prend. */}

      {/* Les réassorts en retard ne sont plus listés ici : ils apparaissent
          plus haut dans la boucle de décision, où ils sont ACTIONNABLES. Une
          même liste à deux endroits, dont une sans bouton, invite à chercher
          laquelle fait foi. */}

      {/* La carte « ce que la position de stock vaut vraiment » listait des
          réserves de méthode : c'est du commentaire sur l'outil, pas une
          information de gestion. Les mêmes chiffres sont disponibles au survol
          des produits concernés, là où ils changent une décision. */}
    </>
  );
}
