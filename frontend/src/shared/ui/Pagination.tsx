"use client";

import { useMemo, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { INK } from "./VisuelKit";

export const TAILLES = [25, 50, 100] as const;

/**
 * Pagination d'une liste déjà filtrée et triée, en mémoire.
 *
 * Volontairement côté client : l'API sert la liste entière (jusqu'à 400 devis)
 * et les filtres du tableau de bord s'appliquent côté serveur. Paginer au
 * serveur en plus obligerait à refaire un appel à chaque page et à chaque
 * changement de tri, pour des volumes qui tiennent sans peine en mémoire.
 *
 * Le piège qu'il faut éviter : rester sur la page 7 après un filtre qui ne
 * laisse que deux pages. `page` est donc ramenée à 1 dès que la SIGNATURE de la
 * liste change (tri, filtre, périmètre), et bornée au nombre de pages réel.
 */
export function usePagination<T>(lignes: T[], signature: string, taille0 = 25) {
  // La signature est MÉMORISÉE avec la page, et non surveillée par un effet.
  // Remettre la page à 1 depuis un `useEffect` provoquerait un premier rendu
  // sur une page qui n'existe plus, puis un second pour la corriger — la liste
  // clignoterait. Ajuster l'état pendant le rendu, quand une entrée change,
  // est le motif que React recommande pour ce cas précis.
  const [etat, setEtat] = useState({ page: 1, sig: signature, taille: taille0 });
  const perime = etat.sig !== signature;
  if (perime) setEtat({ page: 1, sig: signature, taille: etat.taille });

  const page = perime ? 1 : etat.page;
  const taille = etat.taille;
  const setTaille = (t: number) => setEtat(e => ({ ...e, page: 1, taille: t }));

  const total = lignes.length;
  const nPages = Math.max(1, Math.ceil(total / taille));
  // `page` peut dépasser `nPages` quand la liste raccourcit sans que la
  // signature change. C'est `pageSure` qui est affichée, donc c'est d'elle que
  // partent les boutons — sinon « Précédent » depuis la page 7 bornée à 2
  // ramènerait à 6, soit toujours la page 2, et le bouton paraîtrait mort.
  const pageSure = Math.min(page, nPages);
  const aller = (cible: number) =>
    setEtat(e => ({ ...e, page: Math.min(Math.max(1, cible), nPages) }));

  const visibles = useMemo(
    () => lignes.slice((pageSure - 1) * taille, pageSure * taille),
    [lignes, pageSure, taille]);

  return {
    visibles, page: pageSure, nPages, total, taille, setTaille,
    premier: total === 0 ? 0 : (pageSure - 1) * taille + 1,
    dernier: Math.min(pageSure * taille, total),
    precedent: () => aller(pageSure - 1),
    suivant: () => aller(pageSure + 1),
    aller,
  };
}

export type Pagineur<T> = ReturnType<typeof usePagination<T>>;

const BOUTON = {
  display: "inline-flex", alignItems: "center", gap: 4,
  background: "none", border: `1px solid ${INK.border}`, borderRadius: 7,
  padding: "4px 9px", font: "inherit", fontSize: "0.73rem", fontWeight: 600,
  color: INK.secondary, cursor: "pointer",
} as const;

/** La barre de navigation. Masquée quand tout tient sur une page. */
export default function Pagination<T>({ p, nom = "lignes", toujours = false }: {
  p: Pagineur<T>; nom?: string; toujours?: boolean;
}) {
  if (p.total === 0) return null;
  if (p.nPages <= 1 && !toujours) return null;

  const inerte = { opacity: 0.4, cursor: "not-allowed" } as const;
  const premierePage = p.page <= 1;
  const dernierePage = p.page >= p.nPages;

  return (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "space-between",
      gap: 12, flexWrap: "wrap", marginTop: 11, paddingTop: 10,
      borderTop: `1px solid ${INK.grid}`,
    }}>
      <span style={{ fontSize: "0.73rem", color: INK.muted }}>
        <b style={{ color: INK.primary }}>{p.premier}&ndash;{p.dernier}</b> sur{" "}
        <b style={{ color: INK.primary }}>{p.total}</b> {nom}
      </span>

      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <label style={{ fontSize: "0.72rem", color: INK.muted, display: "inline-flex", alignItems: "center", gap: 5 }}>
          Par page
          <select className="mini" value={p.taille}
            onChange={e => p.setTaille(Number(e.target.value))}
            style={{ padding: "3px 6px", fontSize: "0.73rem" }}>
            {TAILLES.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>

        <button type="button" onClick={p.precedent} disabled={premierePage}
          aria-label="Page précédente"
          style={{ ...BOUTON, ...(premierePage ? inerte : {}) }}>
          <ChevronLeft size={13} /> Précédent
        </button>
        <span style={{ fontSize: "0.73rem", color: INK.secondary, fontWeight: 700, minWidth: 62, textAlign: "center" }}>
          {p.page} / {p.nPages}
        </span>
        <button type="button" onClick={p.suivant} disabled={dernierePage}
          aria-label="Page suivante"
          style={{ ...BOUTON, ...(dernierePage ? inerte : {}) }}>
          Suivant <ChevronRight size={13} />
        </button>
      </div>
    </div>
  );
}
