"use client";

/**
 * Pourquoi — l'explication d'un classement, en trois phrases.
 *
 * Un écran qui affiche « ce client risque de partir » sans dire pourquoi
 * demande un acte de foi. Ce composant rend la justification consultable là où
 * la décision se prend : une ligne, un clic, trois raisons chiffrées.
 *
 * Ce qu'on y lit, et rien d'autre : les RAISONS, en français, sans jargon. La
 * mécanique du calcul (décomposition exacte, valeurs de Shapley, seuils d'une
 * règle) n'a pas sa place à l'écran — ni pour un client, ni pour le directeur,
 * qui a besoin de savoir QUOI faire, pas COMMENT le score a été obtenu. Cette
 * partie-là est documentée dans `docs/XAI.md`.
 *
 * La barre de poids ne s'affiche que pour les facteurs qui poussent DANS le
 * sens du signalement : leurs parts totalisent 100 %. Le facteur qui joue en
 * sens inverse est écrit sans barre — lui donner un pourcentage laisserait
 * croire qu'il appartient à la même somme.
 */

import { useState } from "react";
import { HelpCircle, TrendingDown, TrendingUp } from "lucide-react";
import { BLEU } from "@/shared/ui/VisuelKit";

export interface Raison {
  variable?: string;
  valeur?: number;
  poids?: number | null;
  sens?: string;            // aggrave | protege | favorise | freine
  explication: string;
}

const POUSSE = new Set(["aggrave", "favorise", undefined, ""]);

/** Bloc d'explication déplié sous une ligne ou une carte. */
export function Raisons({ raisons, titre = "Pourquoi ce classement" }: {
  raisons?: Raison[];
  titre?: string;
}) {
  const liste = (raisons || []).filter(r => r?.explication);
  if (!liste.length) return null;

  const poussent = liste.filter(r => POUSSE.has(r.sens as string));
  const inverses = liste.filter(r => !POUSSE.has(r.sens as string));

  return (
    <div className="xai-bloc">
      <div className="xai-titre">{titre}</div>

      {poussent.map((r, i) => (
        <div key={i} className="xai-raison">
          <div className="xai-phrase">
            <TrendingUp size={12} style={{ color: BLEU[3], flexShrink: 0, marginTop: 2 }} />
            <span>{r.explication}</span>
          </div>
          {typeof r.poids === "number" && (
            <div className="xai-barre" title={`${Math.round(r.poids * 100)} % du poids`}>
              <i style={{ width: `${Math.max(4, Math.min(100, r.poids * 100))}%` }} />
              <b>{Math.round(r.poids * 100)} %</b>
            </div>
          )}
        </div>
      ))}

      {inverses.map((r, i) => (
        <div key={`c${i}`} className="xai-raison xai-inverse">
          <div className="xai-phrase">
            <TrendingDown size={12} style={{ color: "#0CA30C", flexShrink: 0, marginTop: 2 }} />
            <span>En sens inverse : {r.explication}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

/** Bouton « Pourquoi ? » qui déplie le bloc ci-dessus. */
export default function Pourquoi({ raisons, libelle = "Pourquoi ?", titre }: {
  raisons?: Raison[];
  libelle?: string;
  titre?: string;
}) {
  const [ouvert, setOuvert] = useState(false);
  if (!(raisons || []).some(r => r?.explication)) return null;
  return (
    <>
      <button className="xai-bouton" onClick={() => setOuvert(o => !o)}
        aria-expanded={ouvert}>
        <HelpCircle size={12} /> {ouvert ? "Masquer" : libelle}
      </button>
      {ouvert && <Raisons raisons={raisons} titre={titre} />}
    </>
  );
}
