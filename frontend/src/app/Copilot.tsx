"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import type { CSSProperties } from "react";
import {
  Bot, Mic, Send, Volume2, VolumeX, Sparkles,
  Paperclip, X, FileText, Image as ImageIcon, FileSpreadsheet,
  ChevronDown, Zap, Shield, TrendingUp, Palette
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import FinBotAvatar, {
  visemeForChar,
  type AvatarHandle,
  type AvatarMode,
  type AvatarMood,
} from "./FinBotAvatar";

/* ── Types ────────────────────────────────────────────────────────────────── */
type MsgRole = "user" | "assistant";

interface Attachment {
  file: File;
  preview: string | null; // data-URL pour images, null pour autres
}

interface Msg {
  role: MsgRole;
  text: string;
  via?: "llm" | "regles" | "error" | "rag";
  attachment?: { name: string; type: string };
}

interface RadarCard {
  titre: string;
  categorie: string;
  severite: string;
  montant_dt: number;
  montant_label: string;
}

/* ── Glossaire termes financiers (tooltips) ───────────────────────────────── */
const GLOSSARY_TOOLTIPS: Record<string, string> = {
  "DSO": "Days Sales Outstanding — délai moyen d'encaissement client (jours)",
  "DPO": "Days Payable Outstanding — délai moyen de paiement fournisseur",
  "BFR": "Besoin en Fonds de Roulement = Créances + Stocks - Dettes fournisseurs",
  "FRNG": "Fonds de Roulement Net Global — excédent des ressources stables",
  "VaR": "Value at Risk — perte maximale estimée sur le portefeuille de change",
  "EBITDA": "Résultat avant intérêts, impôts, dépréciations et amortissements",
  "HHI": "Indice de concentration du portefeuille clients (>0.25 = risque élevé)",
  "FOREX": "Marché des changes — impact sur le coût des achats importés",
  "TND": "Dinar Tunisien — monnaie nationale (DT)",
  "Factoring": "Cession de créances à un factor pour encaissement immédiat",
  "TUNEPS": "Portail officiel des marchés publics tunisiens",
  "Pareto": "Loi 80/20 — 20% des clients génèrent 80% du CA",
};

/* ── Suggestions dynamiques par contexte ─────────────────────────────────── */
const GLOBAL_SUGGESTIONS = [
  "Quelles sont mes priorités de recouvrement ?",
  "Quel est mon risque de change ce mois-ci ?",
  "Quelles opportunités d'appels d'offres viser ?",
  "Quelle est ma prévision de trésorerie ?",
  "C'est quoi le DSO et comment l'améliorer ?",
  "Analyse ma marge commerciale",
];

const CLIENT_SUGGESTIONS = (clientName: string) => [
  `Quel est le risque crédit de ${clientName} ?`,
  `Quelle est l'exposition de ${clientName} en retard ?`,
  `Historique de paiement de ${clientName}`,
  `Quelle action prendre sur ${clientName} ?`,
];

/* ── Détection de l'humeur à partir de la réponse + du radar ─────────────── */
const ALERT_WORDS = ["⚠️", "critique", "urgent", "risque élevé", "risque eleve", "alerte", "danger", "défaut", "defaut", "impayé", "impaye", "grave"];
const CONCERN_WORDS = ["retard", "risque", "attention", "surveiller", "exposition", "vigilance", "baisse", "détérior", "deterior", "perte", "litige"];
const HAPPY_WORDS = ["opportunité", "opportunite", "gain", "amélior", "amelior", "excellent", "positif", "hausse", "croissance", "félicit", "felicit", "bonne nouvelle", "économie", "economie", "marge en hausse", "solide"];

function detectMood(text: string, radar: RadarCard[]): AvatarMood {
  const t = text.toLowerCase();
  const radarSev = radar.map(r => (r.severite || "").toLowerCase());
  if (radarSev.some(s => s === "critique") || ALERT_WORDS.some(w => t.includes(w))) return "alert";
  if (radarSev.some(s => ["elevee", "haute"].includes(s)) || CONCERN_WORDS.some(w => t.includes(w))) return "concerned";
  if (HAPPY_WORDS.some(w => t.includes(w))) return "happy";
  return "neutral";
}

/* ── Icône selon type de fichier ─────────────────────────────────────────── */
function FileIcon({ ext }: { ext: string }) {
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
function ChatMessage({ msg }: { msg: Msg }) {
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

/* ── Composant principal Copilot ──────────────────────────────────────────── */
export default function Copilot({
  apiUrl,
  filterPayload,
}: {
  apiUrl: string;
  filterPayload: Record<string, unknown>;
}) {
  const [messages, setMessages] = useState<Msg[]>([
    {
      role: "assistant",
      text:
        "Bonjour 👋 Je suis **FinBot**, votre copilote financier expert.\n\n" +
        "Je suis spécialisé dans :\n" +
        "- 📋 **Recouvrement** — priorisation des relances et aging des créances\n" +
        "- 💱 **Risque de change** — exposition FOREX, sensibilité du dinar\n" +
        "- 💰 **Trésorerie** — DSO, DPO, cycle de conversion cash\n" +
        "- 📊 **Rentabilité** — marge brute, EBITDA, analyse des coûts\n" +
        "- 🎯 **Opportunités** — appels d'offres TUNEPS, prospects à fort potentiel\n\n" +
        "Je peux aussi analyser vos **fichiers** (CSV, PDF, images). Posez-moi votre question !",
      via: "regles",
    },
  ]);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [voiceOn, setVoiceOn] = useState(true);
  const [listening, setListening] = useState(false);
  const [radar, setRadar] = useState<RadarCard[]>([]);
  const [attachment, setAttachment] = useState<Attachment | null>(null);
  const [uploadProgress, setUploadProgress] = useState(false);
  const [showSuggestions, setShowSuggestions] = useState(true);
  const [avatarAccent, setAvatarAccent] = useState("#2F5BEA");
  const [mood, setMood] = useState<AvatarMood>("neutral");

  const avatarRef = useRef<AvatarHandle>(null);
  const lipSyncRaf = useRef<number | null>(null);

  // Mode courant de l'avatar (priorité : parle > réfléchit > écoute > repos)
  const avatarMode: AvatarMode = speaking
    ? "speaking"
    : thinking
      ? "thinking"
      : listening
        ? "listening"
        : "idle";

  const scrollRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Scroll automatique
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, thinking]);

  // Nettoyage voix + synchro labiale
  useEffect(() => () => {
    try { window.speechSynthesis?.cancel(); } catch { }
    if (lipSyncRaf.current != null) cancelAnimationFrame(lipSyncRaf.current);
  }, []);

  /* ── Synthèse vocale + synchro labiale ────────────────────────────────── */
  const stopLipSync = useCallback(() => {
    if (lipSyncRaf.current != null) {
      cancelAnimationFrame(lipSyncRaf.current);
      lipSyncRaf.current = null;
    }
    avatarRef.current?.restMouth();
  }, []);

  const speak = useCallback((text: string) => {
    if (typeof window === "undefined" || !window.speechSynthesis) return;
    if (!voiceOn) return;
    try {
      window.speechSynthesis.cancel();
      stopLipSync();

      // Nettoyer le markdown pour la voix
      const clean = text
        .replace(/#{1,6}\s/g, "")
        .replace(/\*\*/g, "")
        .replace(/[_`>]/g, " ")
        .replace(/[-•]\s/g, "")
        .replace(/\n+/g, ". ")
        .replace(/\s+/g, " ")
        .slice(0, 600);

      const rate = 1.03;
      const u = new SpeechSynthesisUtterance(clean);
      u.lang = "fr-FR"; u.rate = rate; u.pitch = 1.0;

      // ── Moteur de synchro labiale ──
      // On avance dans les caractères prononcés à un rythme estimé (≈14 c/s),
      // et on recale le pointeur sur les frontières de mots réelles (onboundary)
      // pour rester synchronisé avec la voix du navigateur.
      const chars = clean.split("");
      let idx = 0;
      const charMs = 1000 / (14 * rate);
      let last = 0;
      let acc = 0;

      const step = (now: number) => {
        if (last === 0) last = now;
        acc += now - last;
        last = now;
        while (acc >= charMs && idx < chars.length) {
          acc -= charMs;
          avatarRef.current?.setViseme(visemeForChar(chars[idx]));
          idx++;
        }
        if (idx < chars.length) {
          lipSyncRaf.current = requestAnimationFrame(step);
        } else {
          avatarRef.current?.restMouth();
          lipSyncRaf.current = null;
        }
      };

      u.onstart = () => {
        setSpeaking(true);
        last = 0; acc = 0; idx = 0;
        lipSyncRaf.current = requestAnimationFrame(step);
      };
      u.onboundary = (e) => {
        // Recale le pointeur sur le mot réellement prononcé
        if (typeof e.charIndex === "number") idx = Math.max(idx, e.charIndex);
      };
      u.onend = () => { setSpeaking(false); stopLipSync(); };
      u.onerror = () => { setSpeaking(false); stopLipSync(); };

      window.speechSynthesis.speak(u);
    } catch { setSpeaking(false); stopLipSync(); }
  }, [voiceOn, stopLipSync]);

  /* ── Réaction émotionnelle + geste à une nouvelle réponse ─────────────── */
  const reactToAnswer = useCallback((answer: string, nextRadar: RadarCard[]) => {
    const m = detectMood(answer, nextRadar);
    setMood(m);
    // Petit délai pour que le geste accompagne le début de la parole
    window.setTimeout(() => {
      avatarRef.current?.gesture(
        m === "alert" ? "alert" : m === "concerned" ? "lean" : "nod",
      );
      // Coup d'œil vers le radar s'il y a des priorités à signaler
      if (nextRadar.length > 0 && (m === "concerned" || m === "alert")) {
        window.setTimeout(() => avatarRef.current?.gesture("glance"), 700);
      }
    }, 160);
  }, []);

  /* ── Envoi message texte ──────────────────────────────────────────────── */
  const send = useCallback(async (q?: string) => {
    const question = (q ?? input).trim();
    if (!question || thinking) return;

    // Construire l'historique pour le backend (max 16 messages = 8 tours)
    const historyForBackend = messages.slice(-16).map(m => ({
      role: m.role,
      text: m.text,
    }));

    const newUserMsg: Msg = {
      role: "user",
      text: question,
      ...(attachment ? { attachment: { name: attachment.file.name, type: attachment.file.name.split(".").pop()?.toLowerCase() || "file" } } : {}),
    };

    setMessages(m => [...m, newUserMsg]);
    setInput("");
    setThinking(true);
    setShowSuggestions(false);

    // Si fichier joint → upload endpoint
    if (attachment) {
      setUploadProgress(true);
      try {
        const formData = new FormData();
        formData.append("file", attachment.file);
        formData.append("question", question);
        formData.append("filters", JSON.stringify(filterPayload));

        const res = await fetch(`${apiUrl}/api/copilot/upload`, {
          method: "POST",
          body: formData,
        });
        const data = await res.json();
        const answer: string = data.answer || "Je n'ai pas pu analyser ce fichier.";
        const nextRadar: RadarCard[] = Array.isArray(data.radar) ? data.radar.slice(0, 4) : radar;
        if (Array.isArray(data.radar)) setRadar(nextRadar);
        setMessages(m => [...m, {
          role: "assistant",
          text: answer,
          via: data.via,
        }]);
        reactToAnswer(answer, nextRadar);
        speak(answer);
      } catch {
        setMessages(m => [...m, {
          role: "assistant",
          text: "⚠️ Erreur lors de l'analyse du fichier. Vérifiez que l'API tourne (port 8000).",
          via: "error",
        }]);
      } finally {
        setUploadProgress(false);
        setAttachment(null);
      }
    } else {
      // Question texte standard
      try {
        const res = await fetch(`${apiUrl}/api/copilot`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ...filterPayload,
            question,
            history: historyForBackend,
          }),
        });
        const data = await res.json();
        const answer: string = data.answer || "Je n'ai pas trouvé de réponse.";
        const nextRadar: RadarCard[] = Array.isArray(data.radar) ? data.radar.slice(0, 4) : radar;
        if (Array.isArray(data.radar)) setRadar(nextRadar);
        setMessages(m => [...m, { role: "assistant", text: answer, via: data.via }]);
        reactToAnswer(answer, nextRadar);
        speak(answer);
      } catch {
        setMessages(m => [...m, {
          role: "assistant",
          text: "⚠️ Impossible de joindre l'agent finance. Vérifiez que l'API tourne (port 8000).",
          via: "error",
        }]);
      }
    }

    setThinking(false);
  }, [input, thinking, attachment, messages, filterPayload, apiUrl, radar, reactToAnswer, speak]);

  /* ── Reconnaissance vocale ────────────────────────────────────────────── */
  const listen = () => {
    if (typeof window === "undefined") return;
    const SR = (window as unknown as { SpeechRecognition?: unknown; webkitSpeechRecognition?: unknown });
    const Ctor = (SR.SpeechRecognition || SR.webkitSpeechRecognition) as (new () => {
      lang: string; interimResults: boolean;
      onresult: (e: { results: { [i: number]: { [j: number]: { transcript: string } } } }) => void;
      onend: () => void; start: () => void;
    }) | undefined;
    if (!Ctor) {
      setMessages(m => [...m, {
        role: "assistant",
        text: "La reconnaissance vocale n'est pas disponible sur ce navigateur (essayez Chrome).",
        via: "regles",
      }]);
      return;
    }
    try {
      const rec = new Ctor();
      rec.lang = "fr-FR"; rec.interimResults = false;
      rec.onresult = (e) => { const t = e.results[0][0].transcript; setInput(t); };
      rec.onend = () => setListening(false);
      setListening(true); rec.start();
    } catch { setListening(false); }
  };

  /* ── Gestion fichiers ─────────────────────────────────────────────────── */
  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const ext = file.name.split(".").pop()?.toLowerCase() || "";
    const allowed = ["csv", "pdf", "png", "jpg", "jpeg"];
    if (!allowed.includes(ext)) {
      alert(`Format non supporté (${ext}). Formats acceptés : CSV, PDF, PNG, JPG`);
      return;
    }
    // Aperçu image
    if (["png", "jpg", "jpeg"].includes(ext)) {
      const reader = new FileReader();
      reader.onload = (ev) => setAttachment({ file, preview: ev.target?.result as string });
      reader.readAsDataURL(file);
    } else {
      setAttachment({ file, preview: null });
    }
    // Reset l'input pour permettre de re-sélectionner le même fichier
    e.target.value = "";
  };

  const removeAttachment = () => setAttachment(null);

  /* ── Suggestions selon le contexte client ─────────────────────────────── */
  const selectedClients = (filterPayload.selected_clients as string[] | undefined) || [];
  const suggestions = selectedClients.length > 0
    ? CLIENT_SUGGESTIONS(selectedClients[0])
    : GLOBAL_SUGGESTIONS;

  /* ── Toggle voix ──────────────────────────────────────────────────────── */
  const toggleVoice = () => {
    if (voiceOn) { try { window.speechSynthesis?.cancel(); } catch { } setSpeaking(false); stopLipSync(); }
    setVoiceOn(v => !v);
  };

  /* ── Couleur badge sévérité ───────────────────────────────────────────── */
  const sevColor: Record<string, string> = {
    critique: "#ef4444",
    elevee: "#f97316",
    haute: "#f97316",
    moderee: "#eab308",
    faible: "#22c55e",
  };

  return (
    <div className="cop-wrap" style={{ gridColumn: "span 12" }}>

      {/* Panneau avatar */}
      <div className="cop-avatar-panel" style={{ "--avatar-accent": avatarAccent } as CSSProperties}>
        <div className={`cop-aura ${speaking || thinking ? "on" : ""} aura-${mood}`} />
        <div className="cop-avatar-stage">
          <FinBotAvatar
            ref={avatarRef}
            mode={avatarMode}
            mood={mood}
            accent={avatarAccent}
          />
        </div>

        <div className="cop-id">
          <span className="cop-name"><Bot size={15} /> FinBot - Copilote Finance</span>
          <span className={`cop-status ${thinking ? "think" : speaking ? "speak" : "idle"}`}>
            {thinking ? "analyse en cours..." : speaking ? "parle..." : "a l'ecoute"}
          </span>
          {selectedClients.length > 0 && (
            <span className="cop-client-scope">
              <TrendingUp size={11} />
              {selectedClients.length === 1 ? selectedClients[0] : `${selectedClients.length} clients`}
            </span>
          )}
        </div>

        <button className="cop-voice-toggle" onClick={toggleVoice} title={voiceOn ? "Couper la voix" : "Activer la voix"}>
          {voiceOn ? <Volume2 size={16} /> : <VolumeX size={16} />}
        </button>

        <div className="cop-avatar-controls" aria-label="Personnalisation avatar">
          <div className="cop-control-row">
            <span><Palette size={12} /> Couleur du noyau</span>
            <div className="cop-color-row">
              {["#2F5BEA", "#10B981", "#7C5CFC", "#14C2D6", "#EF4444"].map(c => <button key={c} className={avatarAccent === c ? "active" : ""} style={{ background: c }} onClick={() => setAvatarAccent(c)} title={c} />)}
            </div>
          </div>
        </div>

        {/* Mini radar */}
        {radar.length > 0 && (
          <div className="cop-radar-mini">
            <span className="cop-radar-h"><Sparkles size={13} /> Priorites du moment</span>
            {radar.map((c, i) => (
              <div key={i} className="cop-radar-row" style={{ borderLeftColor: sevColor[c.severite] || "#6366f1" }}>
                <span className="cop-radar-cat">{c.categorie}</span>
                <span className="cop-radar-amt">{Math.round(c.montant_dt).toLocaleString("fr-FR")} DT</span>
              </div>
            ))}
          </div>
        )}

        <div className="cop-glossary-legend">
          <span>Survolez les termes <strong>en gras</strong> pour leur definition</span>
        </div>
      </div>

      {/* Panneau chat */}
      <div className="cop-chat-panel">
        <div className="cop-messages" ref={scrollRef}>
          {messages.map((m, i) => (
            <ChatMessage key={i} msg={m} />
          ))}

          {/* Indicateur de chargement */}
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

        {/* Suggestions */}
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

        {/* Aperçu pièce jointe */}
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

        {/* Barre de saisie */}
        <div className="cop-input-row">
          {/* Bouton micro */}
          <button
            className={`cop-mic ${listening ? "on" : ""}`}
            onClick={listen}
            title="Parler (fr-FR)"
            disabled={thinking}
          >
            <Mic size={18} />
          </button>

          {/* Bouton upload fichier */}
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
            accept=".csv,.pdf,.png,.jpg,.jpeg"
            onChange={handleFileSelect}
            style={{ display: "none" }}
          />

          {/* Champ texte */}
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

          {/* Bouton envoyer */}
          <button
            className="cop-send"
            onClick={() => send()}
            disabled={thinking || (!input.trim() && !attachment)}
          >
            <Send size={17} />
          </button>
        </div>

        {/* Aide formats fichiers */}
        <div className="cop-file-hint">
          <Paperclip size={10} /> CSV · PDF · PNG · JPG — max 20 MB
        </div>
      </div>
    </div>
  );
}
