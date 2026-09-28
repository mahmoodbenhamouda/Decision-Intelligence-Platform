"use client";

/**
 * ViewModel — onglet « Priorités ».
 *
 * Demande le briefing à la flotte d'agents pour les filtres courants, écarte
 * les constats techniques, puis prépare : les actions, les six plus gros
 * enjeux, le total, le nombre d'urgences, les clients à signaux multiples et
 * l'enjeu par domaine. Gère aussi la fenêtre « Confier ».
 */
import { useMemo, useState } from "react";
import { useRequete } from "@/core/hooks/useRequete";
import { useConfiees } from "@/features/taches/useConfiees";
import type { Origine } from "@/features/taches/taches.types";
import { tronquer } from "@/shared/ui/VisuelKit";
import { DOMAINE, TECHNIQUE } from "./briefing.regles";
import { chargerBriefing } from "./briefing.service";

export function useBriefing(filterPayload: Record<string, unknown>, peutConfier: boolean) {
  const r = useRequete(() => chargerBriefing(filterPayload), JSON.stringify(filterPayload));
  const data = r.donnees ?? null;
  const [ouvert, setOuvert] = useState<number | null>(null);
  const [confier, setConfier] = useState<Origine | null>(null);
  // Les alertes déjà confiées viennent du serveur : elles survivent au
  // rechargement de la page, contrairement à une simple liste en mémoire.
  const { confiees, recharger: rechargerConfiees } = useConfiees(peutConfier);

  const vue = useMemo(() => {
    const findings = data?.findings || [];
    const synthese = findings.find(f => f.classement && f.classement.length);
    const classement = (synthese?.classement || []).filter(c => c.categorie !== TECHNIQUE);
    const actions = (classement.length ? classement : findings.filter(f => !f.classement))
      .filter(c => c.categorie !== TECHNIQUE);
    const total = classement.reduce((s, c) => s + (c.enjeu_court_terme_dt || 0), 0);
    const parDomaine = Object.entries(
      classement.reduce<Record<string, number>>((acc, c) => {
        const d = DOMAINE[c.categorie]?.label || c.categorie;
        acc[d] = (acc[d] || 0) + (c.enjeu_court_terme_dt || 0);
        return acc;
      }, {}),
    ).map(([domaine, enjeu]) => ({ domaine, enjeu })).sort((a, b) => b.enjeu - a.enjeu);
    return {
      actions,
      top: classement.slice(0, 6).map(c => ({
        nom: tronquer(c.titre, 34), titre: c.titre, enjeu: c.enjeu_court_terme_dt || 0,
        severite: c.severite, resume: c.resume,
      })),
      total,
      urgentes: actions.filter(a => a.severite === "critique" || a.severite === "haute").length,
      clients: synthese?.clients_multi_signaux || [],
      parDomaine,
    };
  }, [data]);

  return {
    data, loading: r.chargement, charger: r.recharger, vue,
    ouvert, setOuvert, confier, setConfier, confiees, rechargerConfiees,
  };
}
