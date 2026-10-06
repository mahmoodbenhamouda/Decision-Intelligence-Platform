
export type MsgRole = "user" | "assistant";

export interface Attachment {
  file: File;
  preview: string | null;
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

export interface ReponseCopilote {
  answer?: string;
  via?: Msg["via"];
  radar?: RadarCard[];
}
