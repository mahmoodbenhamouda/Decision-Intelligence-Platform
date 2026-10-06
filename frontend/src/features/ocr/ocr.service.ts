
import { api } from "@/core/api/client";
import type { Echeancier, EtatMoteur, Mode, Reponse, Sens } from "./ocr.types";

async function lire<T>(res: Response): Promise<Reponse<T>> {
  return { ok: res.ok, status: res.status, data: await res.json().catch(() => ({})) as T };
}

export async function chargerEtatMoteur(): Promise<EtatMoteur | null> {
  try {
    const r = await api("/api/ocr/status");
    if (!r.ok) return null;
    const d = await r.json();
    return {
      ok: !!d.disponible,
      motif: d.layoutlmv3_motif || "",
      cause: d.layoutlmv3_cause || "",
      info: d.disponible
        ? `Tesseract ${d.version || ""} · langues : ${(d.langues || []).filter((l: string) => ["fra", "eng"].includes(l)).join(", ") || "n/d"}`
          + (d.layoutlmv3 ? " · LayoutLMv3 actif" : " · règles seules")
        : d.installation || "",
    };
  } catch {
    return null;
  }
}

export async function chargerEcheancier(): Promise<Echeancier | null> {
  try {
    const r = await api("/api/ocr/echeancier");
    return r.ok ? await r.json() : null;
  } catch {
    return null;
  }
}

const CHEMIN_LECTURE: Record<Mode, string> = {
  facture: "/api/ocr/invoice", texte: "/api/ocr/extract", rag: "/api/ocr/to-rag",
};

export async function lireDocument<T>(mode: Mode, fichier: File): Promise<Reponse<T>> {
  const fd = new FormData();
  fd.append("file", fichier);
  return lire<T>(await api(CHEMIN_LECTURE[mode], { method: "POST", body: fd }));
}

export async function enregistrerFacture<T>(p: {
  lectureId?: string; fichier?: File | null; valeurs: Record<string, string | null>;
  sens: Sens | ""; tiersCode?: string; creerClient: boolean;
}): Promise<Reponse<T>> {
  const fd = new FormData();
  if (p.lectureId) fd.append("lecture_id", p.lectureId);
  else if (p.fichier) fd.append("file", p.fichier);
  fd.append("facture", JSON.stringify(p.valeurs));
  if (p.sens) fd.append("sens", p.sens);
  if (p.tiersCode) fd.append("tiers_code", p.tiersCode);
  fd.append("creer_client", String(p.creerClient));
  return lire<T>(await api("/api/ocr/invoice/import", { method: "POST", body: fd }));
}

export async function rapprocherFacture<T>(lectureId: string, sens: Sens, valeurs: Record<string, string | null>): Promise<T | null> {
  const fd = new FormData();
  fd.append("lecture_id", lectureId); fd.append("sens", sens);
  fd.append("facture", JSON.stringify(valeurs));
  const r = await api("/api/ocr/rapprocher", { method: "POST", body: fd });
  return r.ok ? await r.json() : null;
}

export async function enregistrerEntreprise(id: { nom: string; alias: string; mf: string }): Promise<Reponse<{ nom?: string; detail?: string }>> {
  const fd = new FormData();
  fd.append("nom", id.nom); fd.append("alias", id.alias);
  if (id.mf) fd.append("mf", id.mf);
  return lire(await api("/api/ocr/entreprise", { method: "PUT", body: fd }));
}

export async function reglerFacture(id: number): Promise<Reponse> {
  return lire(await api(`/api/ocr/imports/${id}/reglement`, { method: "POST", body: new FormData() }));
}
