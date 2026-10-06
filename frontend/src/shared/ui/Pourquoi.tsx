"use client";

import { useState } from "react";
import { HelpCircle, Target, TrendingDown, TrendingUp } from "lucide-react";
import { BLEU } from "@/shared/ui/VisuelKit";

export interface Raison {
  variable?: string;
  libelle?: string;
  valeur?: number;
  valeur_affichee?: string;
  centile?: number | null;
  position?: string | null;
  poids?: number | null;
  sens?: string;
  explication: string;
}

/** Plus petit changement d'une variable qui ramène le score sous le seuil. */
export interface Contrefactuel {
  libelle?: string;
  valeur_actuelle_affichee?: string;
  valeur_cible_affichee?: string;
  phrase: string;
}

const POUSSE = new Set(["aggrave", "favorise", undefined, ""]);

/** Libellé et valeur séparés quand le backend les fournit, sinon la phrase. */
function Enonce({ r }: { r: Raison }) {
  if (!r.libelle || !r.valeur_affichee) return <span>{r.explication}</span>;
  return (
    <span>
      {r.libelle} : <b>{r.valeur_affichee}</b>
      {r.position ? <i className="xai-position"> — {r.position}</i> : null}
    </span>
  );
}

export function Raisons({ raisons, contrefactuel, titre = "Pourquoi ce classement" }: {
  raisons?: Raison[];
  contrefactuel?: Contrefactuel | null;
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
            <Enonce r={r} />
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
            <span>En sens inverse : </span><Enonce r={r} />
          </div>
        </div>
      ))}

      {contrefactuel?.phrase && (
        <div className="xai-raison xai-action">
          <div className="xai-phrase">
            <Target size={12} style={{ color: BLEU[4], flexShrink: 0, marginTop: 2 }} />
            <span>{contrefactuel.phrase}</span>
          </div>
        </div>
      )}
    </div>
  );
}

export default function Pourquoi({ raisons, contrefactuel, libelle = "Pourquoi ?", titre }: {
  raisons?: Raison[];
  contrefactuel?: Contrefactuel | null;
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
      {ouvert && <Raisons raisons={raisons} contrefactuel={contrefactuel} titre={titre} />}
    </>
  );
}
