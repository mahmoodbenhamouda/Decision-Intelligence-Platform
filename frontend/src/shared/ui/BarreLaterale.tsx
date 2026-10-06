"use client";

import { useEffect, type ReactNode } from "react";
import {
  ChevronLeft, ChevronRight, LogOut, PanelLeftClose, SlidersHorizontal, Trash2,
  User as UserIcon, X,
} from "lucide-react";

export interface OngletDef { id: string; label: string; icon: ReactNode }

/** Une étape du cycle de gestion, et les écrans qui la servent. */
export interface GroupeDef { titre: string; aide?: string; onglets: OngletDef[] }

const CLE_REPLI = "finbot_barre_repliee";

export function lireRepli(): boolean {
  try { return localStorage.getItem(CLE_REPLI) === "1"; } catch { return false; }
}

export default function BarreLaterale({
  groupes, vue, onVue, replie, onReplie, ouverteMobile, onFermerMobile,
  nomCompte, sousTitreCompte, onDeconnexion,
  nFiltresActifs, resumeFiltres, onReinitialiser, filtres,
}: {
  groupes: GroupeDef[];
  vue: string;
  onVue: (id: string) => void;
  replie: boolean;
  onReplie: (v: boolean) => void;
  ouverteMobile: boolean;
  onFermerMobile: () => void;
  nomCompte: string;
  sousTitreCompte?: string;
  onDeconnexion: () => void;
  nFiltresActifs: number;
  resumeFiltres: string;
  onReinitialiser: () => void;

  filtres: ReactNode;
}) {
  useEffect(() => {
    try { localStorage.setItem(CLE_REPLI, replie ? "1" : "0"); } catch {  }
  }, [replie]);

  useEffect(() => {
    if (!ouverteMobile) return;
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") onFermerMobile(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [ouverteMobile, onFermerMobile]);

  return (
    <>
      {ouverteMobile && <div className="bl-voile" onClick={onFermerMobile} />}

      <aside className={`bl${replie ? " replie" : ""}${ouverteMobile ? " ouverte" : ""}`}>
        <div className="bl-tete">
          <img src="/overlyne.png" alt="Overlyne" className="bl-logo" />
          {!replie && (
            <div className="bl-marque">
              <b>Overlyne</b>
              <span>Cockpit décisionnel</span>
            </div>
          )}
          <button className="bl-repli" onClick={() => onReplie(!replie)}
            title={replie ? "Déployer le menu" : "Réduire le menu"}>
            {replie ? <ChevronRight size={15} /> : <ChevronLeft size={15} />}
          </button>
          <button className="bl-fermer" onClick={onFermerMobile} title="Fermer le menu">
            <X size={16} />
          </button>
        </div>

        {/* Les écrans sont groupés par étape du cycle de gestion. Replié, le
            menu n'affiche que les icônes : les titres de groupe laissent place
            à un simple séparateur, sans quoi la colonne devient illisible. */}
        <nav className="bl-nav">
          {groupes.map((g, i) => (
            <div key={g.titre} className="bl-groupe">
              {replie
                ? i > 0 && <div className="bl-separateur" />
                : <div className="bl-section" title={g.aide}>{g.titre}</div>}
              {g.onglets.map(o => (
                <button key={o.id} title={replie ? `${g.titre} · ${o.label}` : o.label}
                  className={`bl-item${vue === o.id ? " actif" : ""}`}
                  onClick={() => { onVue(o.id); onFermerMobile(); }}>
                  <span className="bl-icone">{o.icon}</span>
                  {!replie && <span className="bl-libelle">{o.label}</span>}
                </button>
              ))}
            </div>
          ))}
        </nav>

        {replie ? (

          <button className="bl-item bl-item-filtre" title="Filtres" onClick={() => onReplie(false)}>
            <span className="bl-icone"><SlidersHorizontal size={17} /></span>
            {nFiltresActifs > 0 && <span className="bl-pastille">{nFiltresActifs}</span>}
          </button>
        ) : (
          <div className="bl-filtres">
            <div className="bl-section">
              <SlidersHorizontal size={12} /> Filtres
              {nFiltresActifs > 0 && <span className="bl-compteur">{nFiltresActifs}</span>}
              {nFiltresActifs > 0 && (
                <button className="bl-raz" onClick={onReinitialiser} title="Tout réinitialiser">
                  <Trash2 size={12} />
                </button>
              )}
            </div>
            {filtres}
            <p className="bl-resume" title={resumeFiltres}>{resumeFiltres}</p>
          </div>
        )}

        <div className="bl-pied">
          <span className="bl-compte interne" title={sousTitreCompte}>
            <UserIcon size={13} />
            {!replie && <span className="bl-compte-nom">{nomCompte}</span>}
          </span>
          <button className="icon-button" onClick={onDeconnexion} title="Se déconnecter">
            <LogOut size={15} />
          </button>
        </div>
      </aside>
    </>
  );
}

export function BoutonMenu({ onClick }: { onClick: () => void }) {
  return (
    <button className="bl-burger" onClick={onClick} title="Ouvrir le menu">
      <PanelLeftClose size={18} />
    </button>
  );
}
