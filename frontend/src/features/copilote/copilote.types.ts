/**
 * Model — conversation avec le copilote FinBot.
 */

export type MsgRole = "user" | "assistant";

export interface Attachment {
  file: File;
  preview: string | null; // data-URL pour images, null pour autres
}

export interface Msg {
  role: MsgRole;
  text: string;
  via?: "llm" | "regles" | "error" | "rag";
  attachment?: { name: string; type: string };
}

export interface RadarCard {
  titre: string;
  categorie: string;
  severite: string;
  montant_dt: number;
  montant_label: string;
}

/** Réponse de /api/copilot et /api/copilot/upload. */
export interface ReponseCopilote {
  answer?: string;
  via?: Msg["via"];
  radar?: RadarCard[];
}
