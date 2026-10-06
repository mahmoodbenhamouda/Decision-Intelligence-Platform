"use client";

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
import { GROUPES, VIEWS } from "./vues";

export function useTableauDeBord() {
  const session = useSession();

  useEffect(() => {
    if (session && !session.loggedIn) redirectToLogin();
  }, [session]);

  const isEmploye = session?.role === "employe";

  const filtres = useFiltres();
  const [view, setView] = useState("synthese");
  const [spot, setSpot] = useState<CarteAgrandie | null>(null);

  const [choixRepli, setBarreRepliee] = useState<boolean | null>(null);
  const repliMemorise = useSyncExternalStore(() => () => { }, lireRepli, () => false);
  const barreRepliee = choixRepli ?? repliMemorise;
  const [menuMobile, setMenuMobile] = useState(false);

  const requete = useRequete(
    () => chargerTableauDeBord(filtres.filterPayload),
    JSON.stringify(filtres.filterPayload),
    session !== null && session.loggedIn && !isEmploye,
  );

  const kpis: KPIs | null = requete.donnees?.kpis ?? null;
  const filtersData: FiltersData | null = requete.donnees?.filters ?? null;
  const loading = requete.chargement || session === null;

  useEffect(() => {
    if (!spot) return;
    const h = (e: KeyboardEvent) => e.key === "Escape" && setSpot(null);
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [spot]);

  const groupes = GROUPES;
  const titreVue = VIEWS.find(v => v.id === view)?.label ?? "";
  // L'étape du cycle à laquelle appartient l'écran courant : affichée en
  // surtitre, elle rappelle où l'on se trouve dans le parcours de gestion.
  const etapeVue = GROUPES.find(g => g.onglets.some(o => o.id === view))?.titre ?? "";

  const clientFocus = filtres.selectedClients.length > 0;
  const combinedFlow = useMemo(() => {
    if (!kpis) return [];
    const m = new Map((kpis.monthly_margin || []).map(x => [x.period, x.marge]));
    return (kpis.sales_vs_purchases || []).map(d => ({ ...d, marge: m.get(d.period) ?? null }));
  }, [kpis]);

  const gauges = useMemo(() => {
    const clamp = (v: number) => Math.max(0, Math.min(100, v));
    const g: Jauge[] = [];
    if (kpis?.marge_quality_score != null)
      g.push({ value: clamp(kpis.marge_quality_score), label: "Qualité marge", color: "#10B981" });
    if (kpis?.part_factures_delai_sup_60j_pct != null)
      g.push({ value: clamp(kpis.part_factures_delai_sup_60j_pct), label: "Délais accordés > 60 j", color: "#F59E0B" });
    if (kpis?.taux_conversion_devis != null && kpis.taux_conversion_devis > 0)
      g.push({ value: clamp(kpis.taux_conversion_devis), label: "Conversion devis", color: "#8B5CF6" });

    // La jauge « Ponctualité paiements » a été retirée : elle valait
    // `100 − part des délais accordés`, donc elle mesurait les conditions
    // négociées et non la ponctualité. L'ERP n'enregistre aucun règlement.
    if (g.length < 3 && kpis?.dso_jours != null)
      g.push({ value: clamp(100 - (kpis.dso_jours / 120) * 100), label: "Vitesse d'encaissement", color: "#2F5BEA" });
    return g.slice(0, 3);
  }, [kpis]);

  const gaugesNote = kpis?.marge_quality_score == null
    ? "Marge non calculable sur ce périmètre (aucune ligne de vente avec coût de revient) — indicateurs de paiement affichés à la place."
    : undefined;

  const g = useMemo(() => graphiques(kpis, combinedFlow), [kpis, combinedFlow]);

  return {
    session, isEmploye, filtres, view, setView, spot, setSpot, onExpand: setSpot,
    barreRepliee, setBarreRepliee, menuMobile, setMenuMobile,
    kpis, filtersData, loading, recharger: requete.recharger,
    groupes, titreVue, etapeVue, clientFocus, gauges, gaugesNote, g, deconnecter: seDeconnecter,
  };
}

export type TableauDeBord = ReturnType<typeof useTableauDeBord>;
