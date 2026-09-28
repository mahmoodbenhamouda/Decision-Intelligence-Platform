"use client";

/**
 * ViewModel — « Documents & OCR ».
 *
 * Porte tout le parcours d'un document : choix du mode, lecture, saisie
 * vérifiée champ par champ (les écarts avec la lecture deviennent des
 * corrections), sens achat / vente, enregistrement, rapprochement avec l'ERP,
 * identité de l'entreprise et échéancier des factures enregistrées.
 */
import { useCallback, useRef, useState } from "react";
import { useSession } from "@/core/auth/useSession";
import { API_INJOIGNABLE } from "@/core/config";
import { useRequete } from "@/core/hooks/useRequete";
import { CHAMPS, brouillon, lectureDe, normSaisie, versSaisie } from "./ocr.regles";
import {
  chargerEcheancier, chargerEtatMoteur, enregistrerEntreprise, enregistrerFacture,
  lireDocument, rapprocherFacture, reglerFacture,
} from "./ocr.service";
import type {
  ImportResult, InvoiceFields, InvoiceResponse, Mode, OcrMeta, Reconciliation, Sens,
} from "./ocr.types";

export function useDocumentsOCR() {
  const [mode, setMode] = useState<Mode>("facture");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [invoice, setInvoice] = useState<InvoiceResponse | null>(null);
  const [rawText, setRawText] = useState<OcrMeta | null>(null);
  const [ragMsg, setRagMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [importRes, setImportRes] = useState<ImportResult | null>(null);
  const [ambigu, setAmbigu] = useState<ImportResult | null>(null);
  const [saisie, setSaisie] = useState<Record<string, string>>({});
  const [sens, setSens] = useState<Sens | "">("");
  const [identite, setIdentite] = useState({ nom: "", alias: "", mf: "" });
  const [identiteOk, setIdentiteOk] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const isDirector = useSession()?.role === "directeur";

  const moteur = useRequete(chargerEtatMoteur).donnees ?? null;
  const engineOk = moteur ? moteur.ok : null;
  const engineInfo = moteur?.info ?? "";
  const moteurMotif = moteur?.motif ?? "";
  const moteurCause = moteur?.cause ?? "";

  const echeancier = useRequete(chargerEcheancier);
  const ech = echeancier.donnees ?? null;
  const rechargerEcheancier = echeancier.recharger;

  const regler = useCallback(async (id: number) => {
    try {
      const r = await reglerFacture(id);
      if (r.ok) rechargerEcheancier();
      else setError(`Règlement refusé (${r.status})`);
    } catch { setError("API injoignable."); }
  }, [rechargerEcheancier]);

  const reset = () => {
    setInvoice(null); setRawText(null); setRagMsg(null); setError(null);
    setImportRes(null); setAmbigu(null);
  };

  const submit = useCallback(async () => {
    if (!file || busy) return;
    setBusy(true); reset();
    try {
      const res = await lireDocument<InvoiceResponse & OcrMeta & { message?: string; detail?: string }>(mode, file);
      const d = res.data;
      if (!res.ok) { setError(d.detail || `Erreur ${res.status}`); return; }
      if (mode === "facture") {
        setInvoice(d);
        setSaisie(brouillon(d.facture));          // le brouillon part des valeurs lues
        const ds = d.sens?.sens;
        setSens(ds === "achat" || ds === "vente" ? ds : "");
      }
      else if (mode === "texte") setRawText(d);
      else setRagMsg(d.message || "Document indexé.");
    } catch {
      setError(API_INJOIGNABLE);
    } finally { setBusy(false); }
  }, [file, busy, mode]);

  const valeursSaisies = () => {
    const valeurs: Record<string, string | null> = {};
    for (const c of CHAMPS) valeurs[c.cle] = (saisie[c.cle] ?? "").trim() || null;
    return valeurs;
  };

  /* Enregistrement en base : la lecture seule ne conservait rien, et les
     montants extraits n'alimentaient aucun indicateur. */
  const importer = async (creerClient: boolean, tiersCode?: string) => {
    if (!invoice || busy) return;
    if (isDirector && !sens) { setError("Précisez s'il s'agit d'un achat ou d'une vente."); return; }
    setBusy(true); setError(null); setImportRes(null); setAmbigu(null);
    try {
      const res = await enregistrerFacture<{
        import?: ImportResult; rapprochement?: Reconciliation; detail?: unknown; erreur?: string;
      }>({
        lectureId: invoice.lecture_id, fichier: file, valeurs: valeursSaisies(),
        sens, tiersCode, creerClient,
      });
      const d = res.data;
      if (res.ok) {
        setImportRes(d.import ?? null);
        rechargerEcheancier();
        if (d.rapprochement) {
          const rap = d.rapprochement;
          setInvoice(inv => (inv ? { ...inv, rapprochement: rap } : inv));
        }
        return;
      }
      // 409 : lecture réussie mais enregistrement refusé (doublon, tiers ambigu…)
      const det = (d.detail && typeof d.detail === "object" ? d.detail : d) as ImportResult;
      if (det?.candidats?.length) setAmbigu(det);
      setError(det?.erreur || (typeof d.detail === "string" ? d.detail : "") || `Erreur ${res.status}`);
    } catch {
      setError(API_INJOIGNABLE);
    } finally { setBusy(false); }
  };

  const valeurLue = (cle: keyof InvoiceFields): unknown =>
    invoice ? lectureDe(invoice.facture, cle) : undefined;
  const modifie = (c: (typeof CHAMPS)[number]) =>
    normSaisie(saisie[c.cle] ?? "", c.type) !== normSaisie(versSaisie(valeurLue(c.cle), c.type), c.type);
  const nModifs = invoice ? CHAMPS.filter(modifie).length : 0;

  const rapprocher = async (s: Sens) => {
    const lectureId = invoice?.lecture_id;
    if (!lectureId) return;
    try {
      const d = await rapprocherFacture<Reconciliation>(lectureId, s, valeursSaisies());
      if (d) setInvoice(inv => (inv ? { ...inv, rapprochement: d } : inv));
    } catch { /* le rapprochement reste celui affiché */ }
  };

  const enregistrerIdentite = async () => {
    if (!identite.nom.trim()) return;
    try {
      const r = await enregistrerEntreprise(identite);
      if (!r.ok) { setError(r.data.detail || `Erreur ${r.status}`); return; }
      setIdentiteOk(r.data.nom ?? null);
    } catch { setError("API injoignable."); }
  };

  return {
    mode, setMode, file, setFile, busy, engineOk, engineInfo, moteurMotif, moteurCause,
    invoice, rawText, ragMsg, error, importRes, ambigu, saisie, setSaisie, sens, setSens,
    identite, setIdentite, identiteOk, ech, regler, inputRef, isDirector, reset, submit,
    importer, valeurLue, modifie, nModifs, rapprocher, enregistrerIdentite,
  };
}
