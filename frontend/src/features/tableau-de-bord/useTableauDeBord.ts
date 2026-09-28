"use client";

/**
 * ViewModel — le tableau de bord.
 *
 * Garde d'authentification, rôle de l'utilisateur, onglet ouvert, barre
 * latérale, filtres, chargement des indicateurs pour le périmètre filtré, et
 * tout ce qui se calcule à partir d'eux : série ventes / achats / marge,
 * jauges de santé, graphe agrandi.
 */
import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { redirectToLogin } from "@/core/auth/session";
import { useSession } from "@/core/auth/useSession";
import { useRequete } from "@/core/hooks/useRequete";
import { seDeconnecter } from "@/features/auth/auth.service";
import { lireRepli } from "@/shared/ui/BarreLaterale";
import { graphiques } from "./graphiques";
import { chargerTableauDeBord } from "./tableauDeBord.service";
import type { CarteAgrandie, FiltersData, Jauge, KPIs } from "./tableauDeBord.types";
import { useFiltres } from "./useFiltres";
import { VIEWS, ongletsPourRole } from "./vues";

export function useTableauDeBord() {
  const session = useSession();

  // ── Garde d'authentification : pas de session → écran de connexion ──
  useEffect(() => {
    if (session && !session.loggedIn) redirectToLogin();
  }, [session]);

  const isClient = session?.role === "client";
  // Un employé ne consulte aucun tableau de bord : le serveur le lui refuse, et
  // l'écran le reflète — il reçoit directement ses tâches, sans filtres ni KPI
  // qu'il n'a pas le droit de lire.
  const isEmploye = session?.role === "employe";

  const filtres = useFiltres();
  const [view, setView] = useState("synthese");
  const [spot, setSpot] = useState<CarteAgrandie | null>(null);
  // Barre latérale : repliée ou non (préférence mémorisée), et ouverture
  // superposée sur petit écran.
  // La préférence mémorisée n'est lue qu'une fois la page montée (le stockage
  // local n'existe pas au rendu serveur) ; le choix de la session l'emporte.
  const [choixRepli, setBarreRepliee] = useState<boolean | null>(null);
  const repliMemorise = useSyncExternalStore(() => () => { }, lireRepli, () => false);
  const barreRepliee = choixRepli ?? repliMemorise;
  const [menuMobile, setMenuMobile] = useState(false);

  // Inutile de demander des chiffres qu'on n'a pas le droit de lire : un
  // employé recevrait un refus du serveur et un écran vide.
  const requete = useRequete(
    () => chargerTableauDeBord(filtres.filterPayload),
    JSON.stringify(filtres.filterPayload),
    session !== null && session.loggedIn && !isEmploye,
  );
  // En cas d'erreur de l'API, `useRequete` garde les derniers chiffres reçus.
  const kpis: KPIs | null = requete.donnees?.kpis ?? null;
  const filtersData: FiltersData | null = requete.donnees?.filters ?? null;
  const loading = requete.chargement || session === null;

  useEffect(() => {
    if (!spot) return;
    const h = (e: KeyboardEvent) => e.key === "Escape" && setSpot(null);
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [spot]);

  // Onglets visibles selon le rôle — la même liste alimente la barre latérale
  // et sert à retrouver le titre de la vue ouverte pour l'en-tête.
  const onglets = useMemo(() => ongletsPourRole(isClient), [isClient]);
  const titreVue = onglets.find(v => v.id === view)?.label
    ?? VIEWS.find(v => v.id === view)?.label ?? "";

  const clientFocus = filtres.selectedClients.length > 0;
  const combinedFlow = useMemo(() => {
    if (!kpis) return [];
    const m = new Map((kpis.monthly_margin || []).map(x => [x.period, x.marge]));
    return (kpis.sales_vs_purchases || []).map(d => ({ ...d, marge: m.get(d.period) ?? null }));
  }, [kpis]);

  /* ── Jauges de santé DYNAMIQUES ──
   * Un indicateur non calculable (ex. marge non attribuable sur un périmètre
   * client, devis non reliés) est REMPLACÉ par un indicateur pertinent au lieu
   * d'afficher un 0 % trompeur. */
  const gauges = useMemo(() => {
    const clamp = (v: number) => Math.max(0, Math.min(100, v));
    const g: Jauge[] = [];
    if (kpis?.marge_quality_score != null)
      g.push({ value: clamp(kpis.marge_quality_score), label: "Qualité marge", color: "#10B981" });
    if (kpis?.paiements_a_risque_pct != null)
      g.push({ value: clamp(kpis.paiements_a_risque_pct), label: "Factures à risque", color: "#EF4444" });
    if (kpis?.taux_conversion_devis != null && kpis.taux_conversion_devis > 0)
      g.push({ value: clamp(kpis.taux_conversion_devis), label: "Conversion devis", color: "#8B5CF6" });
    // Compléments pertinents (surtout en vue client) :
    if (g.length < 3 && kpis?.paiements_a_risque_pct != null)
      g.push({ value: clamp(100 - kpis.paiements_a_risque_pct), label: "Ponctualité paiements", color: "#14C2D6" });
    if (g.length < 3 && kpis?.dso_jours != null)
      g.push({ value: clamp(100 - (kpis.dso_jours / 120) * 100), label: "Vitesse d'encaissement", color: "#2F5BEA" });
    return g.slice(0, 3);
  }, [kpis]);

  const gaugesNote = kpis?.marge_quality_score == null
    ? "Marge non calculable sur ce périmètre (aucune ligne de vente avec coût de revient) — indicateurs de paiement affichés à la place."
    : undefined;

  const g = useMemo(() => graphiques(kpis, combinedFlow), [kpis, combinedFlow]);

  return {
    session, isClient, isEmploye, filtres, view, setView, spot, setSpot, onExpand: setSpot,
    barreRepliee, setBarreRepliee, menuMobile, setMenuMobile,
    kpis, filtersData, loading, recharger: requete.recharger,
    onglets, titreVue, clientFocus, gauges, gaugesNote, g, deconnecter: seDeconnecter,
  };
}

export type TableauDeBord = ReturnType<typeof useTableauDeBord>;
