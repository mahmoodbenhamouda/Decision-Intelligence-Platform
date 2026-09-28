"use client";

/**
 * Vue — une bulle de conversation, avec pièce jointe, rendu Markdown, termes
 * du glossaire mis en évidence et badge d'origine de la réponse.
 */
import {
  Bot, FileSpreadsheet, FileText, Image as ImageIcon, Shield, Zap,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import { GLOSSARY_TOOLTIPS } from "./copilote.regles";
import type { Msg } from "./copilote.types";

/* ── Icône selon type de fichier ─────────────────────────────────────────── */
export function FileIcon({ ext }: { ext: string }) {
  if (["png", "jpg", "jpeg"].includes(ext)) return <ImageIcon size={14} />;
  if (ext === "pdf") return <FileText size={14} />;
  return <FileSpreadsheet size={14} />;
}

/* ── Badge Via (LLM vs Règles) ────────────────────────────────────────────── */
function ViaBadge({ via }: { via?: string }) {
  if (!via || via === "error") return null;
  if (via === "rag") {
    return (
      <span className="cop-via-badge cop-via-rag" title="Réponse basée sur votre base documentaire (RAG)">
        <FileText size={10} /> Docs
      </span>
    );
  }
  return (
    <span
      className={`cop-via-badge ${via === "llm" ? "cop-via-llm" : "cop-via-rules"}`}
      title={via === "llm" ? "Réponse générée par l'IA (Groq LLM)" : "Réponse déterministe (règles métier)"}
    >
      {via === "llm" ? <><Zap size={10} /> IA</> : <><Shield size={10} /> Règles</>}
    </span>
  );
}

/* ── Composant Message ────────────────────────────────────────────────────── */
export default function ChatMessage({ msg }: { msg: Msg }) {
  const isAssistant = msg.role === "assistant";

  return (
    <div className={`cop-msg ${msg.role}`}>
      {isAssistant && (
        <span className="cop-msg-ava"><Bot size={14} /></span>
      )}
      <div className="cop-bubble-wrap">
        {msg.attachment && (
          <div className="cop-attachment-chip">
            <FileIcon ext={msg.attachment.type} />
            <span>{msg.attachment.name}</span>
          </div>
        )}
        <div className="cop-bubble">
          {isAssistant ? (
            <ReactMarkdown
              components={{
                // Liens : ouvrir dans un nouvel onglet
                a: ({ href, children }) => (
                  <a href={href} target="_blank" rel="noopener noreferrer">
                    {children}
                  </a>
                ),
                // Mise en évidence des termes du glossaire
                strong: ({ children }) => {
                  const text = String(children);
                  const glossaryKey = Object.keys(GLOSSARY_TOOLTIPS).find(
                    k => text.toLowerCase().includes(k.toLowerCase())
                  );
                  if (glossaryKey) {
                    return (
                      <strong
                        className="cop-glossary-term"
                        data-tooltip={GLOSSARY_TOOLTIPS[glossaryKey]}
                      >
                        {children}
                      </strong>
                    );
                  }
                  return <strong>{children}</strong>;
                },
              }}
            >
              {msg.text}
            </ReactMarkdown>
          ) : (
            <span>{msg.text}</span>
          )}
        </div>
        {isAssistant && <ViaBadge via={msg.via} />}
      </div>
    </div>
  );
}
