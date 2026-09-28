"use client";

/**
 * ViewModel — « Mon espace » du portail client.
 *
 * Charge factures, demandes et produits proposés ; porte le formulaire libre
 * et l'action ouverte sur une facture ; envoie les actions puis recharge, pour
 * que le client voie aussitôt la suite donnée à son geste.
 */
import { useState } from "react";
import { useRequete } from "@/core/hooks/useRequete";
import { chargerEspace, envoyerActionPortail, envoyerDemande } from "./espaceClient.service";
import type { ActionFacture, Demande, Produit } from "./espaceClient.types";

const AUCUNE: Demande[] = [];
const AUCUN: Produit[] = [];

export function useEspaceClient() {
  const r = useRequete(chargerEspace);
  const inv = r.donnees?.inv ?? null;
  const error = r.donnees?.erreur ?? null;
  const demandes = r.donnees?.demandes ?? AUCUNE;
  const produits = r.donnees?.produits ?? AUCUN;
  const load = r.recharger;

  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState<string | null>(null);

  // Formulaire libre
  const [type, setType] = useState("echeancier");
  const [sujet, setSujet] = useState("");
  const [message, setMessage] = useState("");
  const [invoiceRef, setInvoiceRef] = useState("");

  // Action ouverte sur une facture précise
  const [action, setAction] = useState<ActionFacture | null>(null);

  /** Envoie une action structurée (bouton) — la tâche interne est créée par le serveur. */
  const envoyerAction = async (corps: Record<string, unknown>, confirmation: string) => {
    setSending(true);
    try {
      const erreur = await envoyerActionPortail(corps);
      if (erreur) { setSent(erreur); return false; }
      setSent(confirmation);
      load();
      return true;
    } catch {
      setSent("Envoi impossible — vérifiez votre connexion.");
      return false;
    } finally { setSending(false); }
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (sending || !sujet.trim() || !message.trim()) return;
    setSending(true);
    setSent(null);
    try {
      const erreur = await envoyerDemande({
        type, sujet: sujet.trim(), message: message.trim(),
        invoice_ref: invoiceRef.trim() || null,
      });
      if (!erreur) {
        setSent("Votre demande a bien été transmise.");
        setSujet(""); setMessage(""); setInvoiceRef("");
        load();
      } else {
        setSent(erreur);
      }
    } catch {
      setSent("Erreur d'envoi — vérifiez votre connexion.");
    } finally {
      setSending(false);
    }
  };

  return {
    inv, error, demandes, produits, loading: r.chargement, load,
    sending, sent, setSent, type, setType, sujet, setSujet, message, setMessage,
    invoiceRef, setInvoiceRef, action, setAction, envoyerAction, submit,
  };
}
