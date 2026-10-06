"use client";

import { useMemo, useState } from "react";
import { cleFiltres, useFiltresActifs } from "@/core/filtres/contexteFiltres";
import { useRequete } from "@/core/hooks/useRequete";
import { useConfiees } from "@/features/taches/useConfiees";
import type { Origine } from "@/features/taches/taches.types";
import { usePagination } from "@/shared/ui/Pagination";
import { tronquer } from "@/shared/ui/VisuelKit";
import { chargerCommercial } from "./commercial.service";
import type { CodeProtocole } from "./commercial.types";

/** Colonnes sur lesquelles la liste des devis ouverts peut être triée. */
export type TriDevis = "esperance" | "montant" | "chance" | "age";

/**
 * Tranches de chance de signature.
 *
 * `haute` et `basse` se calent sur le seuil que le BACKEND publie
 * (`seuils.chance_haute_pct`), jamais sur une valeur écrite ici : c'est ce même
 * seuil qui répartit les devis entre les quatre protocoles. Deux découpages
 * différents à l'écran pour une seule règle métier rendraient les deux cartes
 * incohérentes — un devis « à appeler » qui n'apparaîtrait pas en chance haute.
 */
export type TrancheChance = "toutes" | "haute" | "moyenne" | "basse";

export const LIBELLE_CHANCE: Record<TrancheChance, string> = {
  toutes: "Toutes les chances",
  haute: "Chance haute",
  moyenne: "Chance moyenne",
  basse: "Chance faible",
};

/** Colonnes de tri de la liste des clients dont la rentabilité se dégrade. */
export type TriMarge = "enjeu" | "ecart" | "probabilite" | "ca";

export function useCommercial() {
  const filtres = useFiltresActifs();
  const r = useRequete(() => chargerCommercial(filtres), cleFiltres(filtres));
  const devis = r.donnees?.devis ?? null;
  const marge = r.donnees?.marge ?? null;
  const [confier, setConfier] = useState<Origine | null>(null);

  // Tri et filtres de la liste des devis : un directeur qui cherche « les plus
  // vieux » ou « les plus gros » ne doit pas relire toute la liste.
  const [tri, setTri] = useState<TriDevis>("esperance");
  const [protocoleActif, setProtocoleActif] = useState<CodeProtocole | null>(null);
  const [tranche, setTranche] = useState<TrancheChance>("toutes");
  const [triMarge, setTriMarge] = useState<TriMarge>("enjeu");
  // Clic sur un point du nuage : la liste se réduit à ce devis. Le lien va
  // dans ce sens seulement — le nuage garde toujours tous les points, sans
  // quoi cliquer dessus le viderait de ce qu'on venait d'y voir.
  const [devisChoisi, setDevisChoisi] = useState<string | null>(null);

  const { confiees, recharger: rechargerConfiees } = useConfiees();

  // Le seuil de chance haute vient du backend ; 25 % n'est qu'un repli si la
  // réponse ne le porte pas, et la moitié de ce seuil sépare moyenne de faible.
  const seuilHaut = devis?.seuils?.chance_haute_pct ?? 25;
  const seuilBas = Math.round(seuilHaut / 2);

  const d = useMemo(() => {
    const devisTous = (devis?.top || []).map(x => ({
      ...x, nomCourt: tronquer(x.nom || x.client, 24),
      chance: Math.round(x.probabilite * 100),
    }));
    const COMPARE: Record<TriDevis, (a: typeof devisTous[number], b: typeof devisTous[number]) => number> = {
      esperance: (a, b) => b.esperance_dt - a.esperance_dt,
      montant: (a, b) => b.montant_ht_dt - a.montant_ht_dt,
      chance: (a, b) => b.probabilite - a.probabilite,
      age: (a, b) => b.age_j - a.age_j,
    };
    const dansLaTranche = (c: number) =>
      tranche === "toutes" ? true
        : tranche === "haute" ? c >= seuilHaut
        : tranche === "moyenne" ? c >= seuilBas && c < seuilHaut
        : c < seuilBas;

    const devisListe = (devisChoisi
      ? devisTous.filter(x => x.piece_no === devisChoisi)
      : devisTous
        .filter(x => !protocoleActif || x.protocole === protocoleActif)
        .filter(x => dansLaTranche(x.chance))
    ).sort(COMPARE[tri]);

    // Le graphique garde le classement par espérance, quel que soit le tri du
    // tableau : c'est le classement que le modèle produit.
    const devisTop = [...devisTous].sort(COMPARE.esperance);

    // Combien de devis par tranche, AVANT le filtre de tranche lui-même :
    // un sélecteur qui annonce « 0 » sur l'option qu'on vient de quitter est
    // inutilisable. Le filtre « À faire », lui, s'applique — les deux se
    // combinent, et les compteurs doivent le refléter.
    const basePourCompter = devisTous.filter(
      x => !protocoleActif || x.protocole === protocoleActif);
    const compteTranche: Record<TrancheChance, number> = {
      toutes: basePourCompter.length,
      haute: basePourCompter.filter(x => x.chance >= seuilHaut).length,
      moyenne: basePourCompter.filter(x => x.chance >= seuilBas && x.chance < seuilHaut).length,
      basse: basePourCompter.filter(x => x.chance < seuilBas).length,
    };

    const margeTous = (marge?.top || []).map(x => ({
      ...x, nomCourt: tronquer(x.nom || x.client, 24),
    }));
    const COMPARE_MARGE: Record<TriMarge, (a: typeof margeTous[number], b: typeof margeTous[number]) => number> = {
      enjeu: (a, b) => b.marge_en_jeu_dt - a.marge_en_jeu_dt,
      // L'écart au seuil le plus NÉGATIF d'abord : le plus enfoncé sous le seuil.
      ecart: (a, b) => (a.ecart_au_seuil_pct ?? 0) - (b.ecart_au_seuil_pct ?? 0),
      probabilite: (a, b) => b.probabilite - a.probabilite,
      ca: (a, b) => b.ca_12m_dt - a.ca_12m_dt,
    };
    const margeTop = [...margeTous].sort(COMPARE_MARGE[triMarge]);
    // Le total porte sur TOUS les clients servis, pas sur la page affichée.
    const margeTotale = margeTous.reduce((s, x) => s + x.marge_en_jeu_dt, 0);

    // Échelle COMMUNE à toutes les jauges, calculée sur le portefeuille entier
    // et non sur la page affichée. Une jauge mise à l'échelle de sa propre
    // ligne rendrait deux clients incomparables — et changerait de graduation
    // en tournant la page, ce qui est pire que de ne pas en avoir.
    const valeurs = margeTous.flatMap(x => [x.marge_actuelle_pct, x.marge_12m_pct]);
    const seuilM = marge?.seuil_marge_basse_pct ?? 0;
    const medianeM = marge?.marge_mediane_portefeuille_pct ?? 0;
    const hautMarge = Math.ceil(
      Math.max(medianeM * 1.25, seuilM * 1.25, ...valeurs, 1) / 5) * 5;

    return { devisTop, devisListe, margeTop, margeTotale, compteTranche,
             seuilHaut, seuilBas, hautMarge };
  }, [devis, marge, tri, protocoleActif, tranche, triMarge, seuilHaut, seuilBas,
      devisChoisi]);

  // La signature remet la pagination à la page 1 dès que la liste change de
  // contenu : sans elle, on reste sur une page 7 qui n'existe plus.
  const pDevis = usePagination(d.devisListe,
    `${cleFiltres(filtres)}|${tri}|${protocoleActif ?? ""}|${tranche}|${devisChoisi ?? ""}`);
  const pMarge = usePagination(d.margeTop, `${cleFiltres(filtres)}|${triMarge}`);

  return {
    devis, marge, loading: r.chargement, load: r.recharger, d,
    confier, setConfier, confiees, rechargerConfiees,
    tri, setTri, protocoleActif, setProtocoleActif,
    tranche, setTranche, triMarge, setTriMarge,
    devisChoisi, setDevisChoisi,
    pDevis, pMarge,
  };
}
