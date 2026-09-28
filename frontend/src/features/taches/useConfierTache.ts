"use client";

/**
 * ViewModel — la fenêtre « Confier cette action ».
 *
 * Elle arrive PRÉ-REMPLIE à partir de l'alerte : intitulé, type d'action
 * suggéré, échéance selon la gravité, montant. Le collègue dont le métier
 * correspond au domaine passe en tête de liste et, tant que le directeur n'a
 * choisi personne, c'est lui qui est proposé.
 */
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
  const [type, setType] = useState(typeSuggere(origine.categorie));
  const [titre, setTitre] = useState(origine.titre.slice(0, 200));
  const [details, setDetails] = useState(origine.details || "");
  const [echeance, setEcheance] = useState(dansNJours(DELAI[origine.severite || "moyenne"] ?? 10));
  const [montant, setMontant] = useState<string>(
    origine.montant_dt ? String(Math.round(origine.montant_dt)) : "");
  const [envoi, setEnvoi] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  // Le collègue dont le métier correspond au domaine passe en tête, et la
  // charge de chacun reste visible : on ne confie pas la dixième relance de la
  // semaine à la même personne sans le savoir.
  const classes = useMemo(() => {
    const p = posteSuggere(origine.categorie);
    return [...employes].sort((a, b) => {
      const pa = a.poste === p ? 0 : 1, pb = b.poste === p ? 0 : 1;
      return pa - pb || a.taches_ouvertes - b.taches_ouvertes;
    });
  }, [employes, origine.categorie]);

  // Tant que personne n'est choisi, le premier de la liste est proposé.
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
