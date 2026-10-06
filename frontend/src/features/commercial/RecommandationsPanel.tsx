"use client";

import { useState } from "react";
import {
  Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { Package, ShoppingCart, UserPlus } from "lucide-react";
import ConfierTache, { BadgeConfiee } from "@/features/taches/ConfierTache";
import { useConfiees } from "@/features/taches/useConfiees";
import type { Origine } from "@/features/taches/taches.types";
import PanneauMasque, { BadgeFiltreClients } from "@/shared/ui/PanneauMasque";
import Pourquoi from "@/shared/ui/Pourquoi";
import {
  BLEU, Carte, INFOBULLE, INK, Vide, fMoney, tronquer,
} from "@/shared/ui/VisuelKit";
import { cleFiltres, qsFiltres, useFiltresActifs } from "@/core/filtres/contexteFiltres";
import { api } from "@/core/api/client";
import { useRequete } from "@/core/hooks/useRequete";
import { origineReco } from "./commercial.regles";
import type { Portee, RecoData } from "./commercial.types";

/**
 * Quels produits proposer, et à qui.
 *
 * Le panneau vit avec « Produits & achats » et non avec les devis : il parle
 * de catalogue et d'adoption de références, pas de pièces commerciales en
 * cours. Il charge ses propres données pour rester autonome de l'onglet Devis.
 */
export default function RecommandationsPanel() {
  const filtres = useFiltresActifs();
  const [confier, setConfier] = useState<Origine | null>(null);
  const { confiees, recharger: rechargerConfiees } = useConfiees();

  const r = useRequete<RecoData & Portee>(async () => {
    try {
      const rep = await api(`/api/commercial/recommandations?limit=12&${qsFiltres(filtres)}`);
      return await rep.json();
    } catch {
      return { servi: false, motif: "Connexion au serveur impossible." };
    }
  }, cleFiltres(filtres));

  const reco = r.donnees;
  if (r.chargement && !reco) {
    return <Carte titre="Produits à proposer"><Vide texte="Chargement…" /></Carte>;
  }
  if (reco?.masque) {
    return <div style={{ gridColumn: "span 12" }}><PanneauMasque motif={reco.motif} /></div>;
  }

  const clients = reco?.top ?? [];
  if (!reco?.servi || !clients.length) {
    return (
      <Carte titre="Produits à proposer">
        <Vide texte={reco?.motif || "Aucune recommandation disponible."} />
      </Carte>
    );
  }

  // Combien de clients pour chaque produit recommandé : le produit le plus
  // souvent conseillé est celui qui mérite une campagne, pas un appel isolé.
  const compte: Record<string, number> = {};
  clients.forEach(c => c.produits.forEach(p => {
    compte[p.designation] = (compte[p.designation] || 0) + 1;
  }));
  const produits = Object.entries(compte)
    .map(([produit, n]) => ({ produit: tronquer(produit, 28), complet: produit, n }))
    .sort((a, b) => b.n - a.n).slice(0, 8);
  const potentiel = clients.reduce((s, c) => s + c.potentiel_top3_dt, 0);

  return (
    <>
      {reco.portee === "clients" && (
        <div style={{ gridColumn: "span 12" }}>
          <BadgeFiltreClients n={reco.n_clients_filtre} />
        </div>
      )}

      <Carte span={5} titre="Produits les plus demandés à venir" icone={<Package size={15} />}
        sousTitre={`Nombre de clients à qui le proposer dans les ${reco.horizon_mois ?? 6} mois`}>
        <ResponsiveContainer width="100%" height={Math.max(260, produits.length * 38)}>
          <BarChart layout="vertical" data={produits}
            margin={{ top: 0, right: 36, left: 0, bottom: 0 }} barCategoryGap={8}>
            <XAxis type="number" hide allowDecimals={false} />
            <YAxis type="category" dataKey="produit" width={190}
              tick={{ fill: INK.primary, fontSize: 11.5 }} axisLine={false} tickLine={false} />
            <Tooltip cursor={{ fill: "rgba(47,91,234,0.05)" }} contentStyle={INFOBULLE}
              formatter={(v) => [`${v} client(s)`, "À proposer à"]}
              labelFormatter={(_, p) => (p?.[0]?.payload as { complet?: string })?.complet || ""} />
            <Bar dataKey="n" fill={BLEU[3]} barSize={16} radius={[0, 4, 4, 0]}
              label={{ position: "right", fill: INK.secondary, fontSize: 11 }} />
          </BarChart>
        </ResponsiveContainer>
      </Carte>

      <Carte span={7} titre="Quoi proposer, à qui" icone={<ShoppingCart size={15} />}
        sousTitre={`Produits jamais achetés par ces clients et qu'ils sont susceptibles d'adopter — ${fMoney(potentiel)} de potentiel annuel`}>
        <div style={{
          display: "grid", gap: 10,
          gridTemplateColumns: "repeat(auto-fill, minmax(230px, 1fr))",
        }}>
          {clients.slice(0, 8).map(c => (
            <div key={c.client} className="vk-carte-action">
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "baseline" }}>
                <span style={{ fontWeight: 800, color: INK.primary, fontSize: "0.86rem" }} title={c.nom}>
                  {tronquer(c.nom, 26)}
                </span>
                <span style={{ fontWeight: 800, color: INK.primary, fontSize: "0.86rem", whiteSpace: "nowrap" }}>
                  {fMoney(c.potentiel_top3_dt)}
                </span>
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                {c.produits.map(p => (
                  <span key={p.designation} className="vk-chip" title={p.designation}>
                    {tronquer(p.designation, 26)}
                  </span>
                ))}
              </div>
              <Pourquoi raisons={c.produits[0]?.raisons}
                libelle="Pourquoi ce produit ?"
                titre={`Pourquoi ${tronquer(c.produits[0]?.designation || "", 30)}`} />
              {confiees[origineReco(c).titre] ? (
                <BadgeConfiee info={confiees[origineReco(c).titre]} />
              ) : (
                <button className="vk-bouton-mini" style={{ alignSelf: "flex-start" }}
                  onClick={() => setConfier(origineReco(c))}>
                  <UserPlus size={12} /> Confier
                </button>
              )}
            </div>
          ))}
        </div>
        <p className="muted-note" style={{ marginTop: 10, fontSize: "0.72rem" }}>
          Le montant indique ce que dépensent en moyenne par an les clients qui achètent déjà ces produits.
        </p>
      </Carte>

      {confier && (
        <ConfierTache origine={confier} onClose={() => setConfier(null)}
          onCree={() => void rechargerConfiees()} />
      )}
    </>
  );
}
