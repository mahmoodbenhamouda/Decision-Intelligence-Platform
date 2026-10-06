"use client";

import { useMemo, useState } from "react";
import { useRequete } from "@/core/hooks/useRequete";
import { dansNJours } from "@/shared/format";
import { DELAI, posteSuggere, typeSuggere } from "./taches.regles";
import { chargerEmployesAssignables, creerTache } from "./taches.service";
import type { EmployeAssignable, Origine } from "./taches.types";

const PERSONNE: EmployeAssignable[] = [];

export function useConfierTache(origine: Origine, onClose: () => void, onCree?: () => void) {
  const employes = useRequete(chargerEmployesAssignables).donnees ?? PERSONNE;
  const [choix, setAssigne] = useState<number | "">("");
  const [type, setType] = useState(origine.execution?.type || typeSuggere(origine.categorie));
  const [titre, setTitre] = useState((origine.titre_tache || origine.titre).slice(0, 200));
  const [details, setDetails] = useState(origine.details || "");
  const [echeance, setEcheance] = useState(dansNJours(DELAI[origine.severite || "moyenne"] ?? 10));
  const [montant, setMontant] = useState<string>(
    origine.montant_dt ? String(Math.round(origine.montant_dt)) : "");
  const [envoi, setEnvoi] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  const classes = useMemo(() => {
    const p = origine.execution?.poste || posteSuggere(origine.categorie);
    return [...employes].sort((a, b) => {
      const pa = a.poste === p ? 0 : 1, pb = b.poste === p ? 0 : 1;
      return pa - pb || a.taches_ouvertes - b.taches_ouvertes || a.id - b.id;
    });
  }, [employes, origine.execution?.poste, origine.categorie]);

  const assigne: number | "" = choix === "" && classes.length ? classes[0].id : choix;

  const envoyer = async () => {
    setEnvoi(true); setErreur(null);
    try {
      await creerTache({
        titre: titre.trim(), type, details: details.trim() || null,
        client_code: origine.client_code || null,
        client_nom: origine.client_nom || null,
        origine_categorie: origine.categorie || null,
        origine_titre: origine.titre,
        severite: origine.severite || "moyenne",
        montant_dt: Number(montant) || 0,
        assigne_id: assigne === "" ? null : assigne,
        echeance: echeance || null,
      });
      onCree?.();
      onClose();
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "La tâche n'a pas pu être créée.");
    } finally { setEnvoi(false); }
  };

  return {
    classes, assigne, setAssigne, type, setType, titre, setTitre, details, setDetails,
    echeance, setEcheance, montant, setMontant, envoi, erreur, envoyer,
  };
}
