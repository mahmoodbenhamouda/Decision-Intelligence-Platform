
import { api, apiEnvoyer } from "@/core/api/client";
import type { MsgRole, ReponseCopilote } from "./copilote.types";

export async function poserQuestion(
  filtres: Record<string, unknown>, question: string,
  historique: { role: MsgRole; text: string }[],
): Promise<ReponseCopilote> {
  const res = await apiEnvoyer("/api/copilot", { ...filtres, question, history: historique });
  return res.json();
}

export async function analyserFichier(
  fichier: File, question: string, filtres: Record<string, unknown>,
): Promise<ReponseCopilote> {
  const formData = new FormData();
  formData.append("file", fichier);
  formData.append("question", question);
  formData.append("filters", JSON.stringify(filtres));
  const res = await api("/api/copilot/upload", { method: "POST", body: formData });
  return res.json();
}
