"use client";

/**
 * BarreLaterale — navigation et filtres réunis sur le bord gauche.
 *
 * Pourquoi ce changement : les onglets et la bande de filtres occupaient deux
 * rangées en haut de page. Sur un portable, le premier graphique commençait
 * donc sous la ligne de flottaison, et la liste des filtres actifs était
 * tronquée faute de largeur. En vertical, l'écran retrouve sa hauteur, les
 * onglets tiennent tous sans défilement, et chaque filtre peut enfin afficher
 * ce qui est réellement sélectionné plutôt qu'un simple compteur.
 *
 * Trois états :
 *   · déployée (par défaut) — icône + libellé, filtres visibles ;
 *   · repliée — colonne d'icônes ; les filtres passent derrière un bouton qui
 *     redéploie la barre, car un filtre sans son libellé ne se lit pas ;
 *   · mobile — la barre se superpose au contenu et se ferme au clic extérieur.
 *
 * Le choix déployée/repliée est mémorisé dans le navigateur : c'est une
 * préférence d'affichage, elle n'a pas à être refaite à chaque visite.
 */

import { useEffect, type ReactNode } from "react";
import {
  ChevronLeft, ChevronRight, LogOut, PanelLeftClose, SlidersHorizontal, Trash2,
  User as UserIcon, X,
} from "lucide-react";

export interface OngletDef { id: string; label: string; icon: ReactNode }

const CLE_REPLI = "finbot_barre_repliee";

/** Lit la préférence d'affichage ; tout échec (navigation privée) → déployée. */
export function lireRepli(): boolean {
  try { return localStorage.getItem(CLE_REPLI) === "1"; } catch { return false; }
}

export default function BarreLaterale({
  onglets, vue, onVue, replie, onReplie, ouverteMobile, onFermerMobile,
  nomCompte, sousTitreCompte, estClient, onDeconnexion,
  nFiltresActifs, resumeFiltres, onReinitialiser, filtres,
}: {
  onglets: OngletDef[];
  vue: string;
  onVue: (id: string) => void;
  replie: boolean;
  onReplie: (v: boolean) => void;
  ouverteMobile: boolean;
  onFermerMobile: () => void;
  nomCompte: string;
  sousTitreCompte?: string;
  estClient: boolean;
  onDeconnexion: () => void;
  nFiltresActifs: number;
  resumeFiltres: string;
  onReinitialiser: () => void;
  /** Les contrôles de filtre, rendus par la page (elle seule connaît son état). */
  filtres: ReactNode;
}) {
  useEffect(() => {
    try { localStorage.setItem(CLE_REPLI, replie ? "1" : "0"); } catch { /* préférence non mémorisée */ }
  }, [replie]);

  // Échap ferme la barre superposée : sur mobile, elle masque tout le contenu.
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
        {/* ── Marque et repli ─────────────────────────────────────────── */}
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

        {/* ── Navigation ──────────────────────────────────────────────── */}
        <nav className="bl-nav">
          {!replie && <div className="bl-section">Navigation</div>}
          {onglets.map(o => (
            <button key={o.id} title={o.label}
              className={`bl-item${vue === o.id ? " actif" : ""}`}
              onClick={() => { onVue(o.id); onFermerMobile(); }}>
              <span className="bl-icone">{o.icon}</span>
              {!replie && <span className="bl-libelle">{o.label}</span>}
            </button>
          ))}
        </nav>

        {/* ── Filtres ─────────────────────────────────────────────────── */}
        {replie ? (
          // Repliée, un filtre ne montrerait qu'une icône muette : on propose
          // plutôt de redéployer, en signalant s'il y en a d'actifs.
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

        {/* ── Compte ──────────────────────────────────────────────────── */}
        <div className="bl-pied">
          <span className={`bl-compte ${estClient ? "client" : "interne"}`} title={sousTitreCompte}>
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

/** Bouton d'ouverture, affiché seulement quand la barre est superposée. */
export function BoutonMenu({ onClick }: { onClick: () => void }) {
  return (
    <button className="bl-burger" onClick={onClick} title="Ouvrir le menu">
      <PanelLeftClose size={18} />
    </button>
  );
}
