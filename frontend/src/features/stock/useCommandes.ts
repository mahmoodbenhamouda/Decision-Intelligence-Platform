"use client";

import { useCallback, useState } from "react";
import { api } from "@/core/api/client";
import { cleFiltres, qsFiltres, useFiltresActifs } from "@/core/filtres/contexteFiltres";
import { useRequete } from "@/core/hooks/useRequete";
import type {
  BilanCommandes, Commande, Proposition, Recommandations,
} from "./commandes.types";

async function poster(url: string, corps: unknown) {
  const r = await api(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(corps),
  });
  if (!r.ok) {
    const t = await r.json().catch(() => ({}));
    throw new Error(t?.detail || "L'opération a échoué.");
  }
  return r.json();
}

/**
 * La boucle d'approvisionnement, côté écran.
 *
 * Un seul compteur de version recharge les trois sources ensemble : décider
 * d'une recommandation la retire de la liste des propositions ET l'ajoute aux
 * commandes ET change le bilan. Les laisser se rafraîchir séparément
 * afficherait des états incohérents pendant quelques centaines de millisecondes.
 */
export function useCommandes() {
  const filtres = useFiltresActifs();
  const [version, setVersion] = useState(0);
  const [erreur, setErreur] = useState<string | null>(null);
  const [enCours, setEnCours] = useState<number | string | null>(null);
  const cle = `${cleFiltres(filtres)}#${version}`;

  const reco = useRequete<Recommandations>(async () => {
    try {
      const r = await api(`/api/commandes/recommandations?${qsFiltres(filtres)}`);
      return await r.json();
    } catch {
      return { servi: false, motif: "Connexion au serveur impossible." };
    }
  }, cle);

  const liste = useRequete<Commande[]>(async () => {
    try {
      const r = await api(`/api/commandes?limit=200`);
      return await r.json();
    } catch {
      return [];
    }
  }, cle);

  const bilan = useRequete<BilanCommandes | null>(async () => {
    try {
      const r = await api(`/api/commandes/bilan`);
      return await r.json();
    } catch {
      return null;
    }
  }, cle);

  const rafraichir = useCallback(() => setVersion(v => v + 1), []);

  const agir = useCallback(async (jeton: number | string, action: () => Promise<unknown>) => {
    setErreur(null);
    setEnCours(jeton);
    try {
      await action();
      setVersion(v => v + 1);
      return true;
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "L'opération a échoué.");
      return false;
    } finally {
      setEnCours(null);
    }
  }, []);

  /** Valide une proposition : elle est enregistrée puis immédiatement validée. */
  const validerProposition = useCallback((p: Proposition) =>
    agir(p.reference, async () => {
      const creee = await poster("/api/commandes", {
        reference: p.reference,
        designation: p.designation,
        fournisseur_code: p.fournisseur_code,
        fournisseur_nom: p.fournisseur_nom,
        motif: `Dernier achat il y a ${p.jours_depuis} jours pour un rythme de `
          + `${p.intervalle_median_j} jours, soit ${p.retard_x}× le délai habituel. `
          + `Encore vendu jusqu'au ${p.derniere_vente}.`,
        qte_proposee: p.qte_proposee ?? 0,
        montant_estime_dt: p.montant_estime_dt ?? 0,
      }) as Commande;
      await poster(`/api/commandes/${creee.id}/decision`, { valide: true });
    }), [agir]);

  /** Refuse une proposition : le motif est obligatoire, il apprend à l'analyse. */
  const refuserProposition = useCallback((p: Proposition, motif: string) =>
    agir(p.reference, async () => {
      const creee = await poster("/api/commandes", {
        reference: p.reference,
        designation: p.designation,
        fournisseur_code: p.fournisseur_code,
        fournisseur_nom: p.fournisseur_nom,
        motif: `Proposé : retard de ${p.retard_x}× le rythme habituel.`,
        qte_proposee: p.qte_proposee ?? 0,
        montant_estime_dt: p.montant_estime_dt ?? 0,
      }) as Commande;
      await poster(`/api/commandes/${creee.id}/decision`,
                   { valide: false, motif_refus: motif });
    }), [agir]);

  const passerCommande = useCallback((c: Commande) =>
    agir(c.id, () => poster(`/api/commandes/${c.id}/commander`, { commentaire: "" })),
    [agir]);

  const receptionner = useCallback((c: Commande, qte?: number) =>
    agir(c.id, () => poster(`/api/commandes/${c.id}/reception`,
                            { qte_recue: qte ?? null, commentaire: "" })),
    [agir]);

  const annuler = useCallback((c: Commande, motif: string) =>
    agir(c.id, () => poster(`/api/commandes/${c.id}/annulation`, { commentaire: motif })),
    [agir]);

  return {
    reco: reco.donnees,
    commandes: liste.donnees ?? [],
    bilan: bilan.donnees ?? null,
    chargement: reco.chargement || liste.chargement,
    erreur, setErreur, enCours, rafraichir,
    validerProposition, refuserProposition, passerCommande, receptionner, annuler,
  };
}
