"use client";

import {
  Bot, ChevronDown, Mic, Paperclip, Send, Sparkles, Volume2, VolumeX, X,
} from "lucide-react";
import ChatMessage, { FileIcon } from "./MessageCopilote";
import { useCopilote } from "./useCopilote";

export default function Copilot({ filterPayload }: { filterPayload: Record<string, unknown> }) {
  const {
    messages, input, setInput, thinking, speaking, voiceOn, listening, attachment,
    uploadProgress, showSuggestions, setShowSuggestions, suggestions, scrollRef,
    fileInputRef, send, listen, handleFileSelect, removeAttachment, toggleVoice,
  } = useCopilote(filterPayload);

  return (
    <div className="cop-wrap" style={{ gridColumn: "span 12" }}>

      <div className="cop-chat-panel" style={{ width: "100%" }}>
        <div
          className="cop-chat-header"
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "14px 20px",
            borderBottom: "1px solid var(--border)",
            background: "rgba(255, 255, 255, 0.8)",
            backdropFilter: "blur(12px)",
            borderRadius: "18px 18px 0 0",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <div
              style={{
                width: "36px",
                height: "36px",
                borderRadius: "10px",
                background: "linear-gradient(135deg, #3A3FB0, #2F5BEA)",
                display: "grid",
                placeItems: "center",
                color: "#FFF",
                boxShadow: "0 4px 12px rgba(47,91,234,0.25)",
              }}
            >
              <Bot size={20} />
            </div>
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <span style={{ fontWeight: 800, fontSize: "1rem", color: "var(--text-primary)" }}>
                  FinBot - Copilote IA Finance
                </span>
                <span className={`cop-status ${thinking ? "think" : speaking ? "speak" : "idle"}`}>
                  {thinking ? "analyse en cours..." : speaking ? "parle..." : "à l'écoute"}
                </span>
              </div>
              <span style={{ fontSize: "0.74rem", color: "var(--text-muted)" }}>
                Assistant IA & Analyseur financier en temps réel
              </span>
            </div>
          </div>

          <button
            className="cop-voice-toggle"
            onClick={toggleVoice}
            title={voiceOn ? "Couper la voix" : "Activer la voix"}
            style={{
              background: "#FFF",
              border: "1px solid var(--border)",
              borderRadius: "10px",
              padding: "8px",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: "6px",
              color: voiceOn ? "var(--accent-blue)" : "var(--text-muted)",
              fontWeight: 600,
              fontSize: "0.78rem",
            }}
          >
            {voiceOn ? <Volume2 size={16} /> : <VolumeX size={16} />}
            <span>{voiceOn ? "Voix ON" : "Voix OFF"}</span>
          </button>
        </div>
        <div className="cop-messages" ref={scrollRef}>
          {messages.map((m, i) => (
            <ChatMessage key={i} msg={m} />
          ))}

          {(thinking || uploadProgress) && (
            <div className="cop-msg assistant">
              <span className="cop-msg-ava"><Bot size={14} /></span>
              <div className="cop-bubble-wrap">
                <div className="cop-bubble cop-typing">
                  <span></span><span></span><span></span>
                  {uploadProgress && (
                    <span className="cop-upload-label">Analyse du fichier…</span>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>

        {showSuggestions && (
          <div className="cop-suggestions">
            <button
              className="cop-suggestions-toggle"
              onClick={() => setShowSuggestions(false)}
              title="Masquer les suggestions"
            >
              <ChevronDown size={13} />
            </button>
            {suggestions.slice(0, 4).map((s, i) => (
              <button
                key={i}
                className="cop-chip"
                onClick={() => send(s)}
                disabled={thinking}
              >
                {s}
              </button>
            ))}
          </div>
        )}
        {!showSuggestions && (
          <button
            className="cop-suggestions-show"
            onClick={() => setShowSuggestions(true)}
          >
            <Sparkles size={12} /> Suggestions
          </button>
        )}

        {attachment && (
          <div className="cop-attachment-preview">
            {attachment.preview ? (
              <img src={attachment.preview} alt="aperçu" className="cop-attachment-img" />
            ) : (
              <FileIcon ext={attachment.file.name.split(".").pop()?.toLowerCase() || ""} />
            )}
            <span className="cop-attachment-name">{attachment.file.name}</span>
            <span className="cop-attachment-size">
              {(attachment.file.size / 1024).toFixed(0)} KB
            </span>
            <button className="cop-attachment-remove" onClick={removeAttachment} title="Supprimer">
              <X size={12} />
            </button>
          </div>
        )}

        <div className="cop-input-row">
          <button
            className={`cop-mic ${listening ? "on" : ""}`}
            onClick={listen}
            title="Parler (fr-FR)"
            disabled={thinking}
          >
            <Mic size={18} />
          </button>

          <button
            className="cop-attach"
            onClick={() => fileInputRef.current?.click()}
            title="Joindre un fichier (CSV, PDF, PNG, JPG)"
            disabled={thinking}
          >
            <Paperclip size={18} />
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,.pdf"
            onChange={handleFileSelect}
            style={{ display: "none" }}
          />

          <input
            className="cop-input"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === "Enter" && !e.shiftKey && send()}
            placeholder={
              attachment
                ? `Question sur "${attachment.file.name}"…`
                : "Posez votre question financière…"
            }
            disabled={thinking}
          />

          <button
            className="cop-send"
            onClick={() => send()}
            disabled={thinking || (!input.trim() && !attachment)}
          >
            <Send size={17} />
          </button>
        </div>

        <div className="cop-file-hint">
          <Paperclip size={10} /> CSV · PDF (max 20 Mo) — documents scannés : onglet « Documents &amp; OCR »
        </div>
      </div>
    </div>
  );
}
