"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { AvatarMode, AvatarMood } from "@/shared/avatar/FinBotAvatar";
import { API_URL } from "@/core/config";
import {
  CLIENT_SUGGESTIONS, GLOBAL_SUGGESTIONS, MESSAGE_ACCUEIL, detectMood,
} from "./copilote.regles";
import { analyserFichier, poserQuestion } from "./copilote.service";
import type { Attachment, Msg, RadarCard } from "./copilote.types";
import { useSyntheseVocale } from "./useSyntheseVocale";

export function useCopilote(filterPayload: Record<string, unknown>) {
  const [messages, setMessages] = useState<Msg[]>([MESSAGE_ACCUEIL]);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const [voiceOn, setVoiceOn] = useState(true);
  const [listening, setListening] = useState(false);
  const [radar, setRadar] = useState<RadarCard[]>([]);
  const [attachment, setAttachment] = useState<Attachment | null>(null);
  const [uploadProgress, setUploadProgress] = useState(false);
  const [showSuggestions, setShowSuggestions] = useState(true);
  const [mood, setMood] = useState<AvatarMood>("neutral");
  const { speaking, setSpeaking, speak, stopLipSync, avatarRef } = useSyntheseVocale(voiceOn);

  const avatarMode: AvatarMode = speaking
    ? "speaking"
    : thinking
      ? "thinking"
      : listening
        ? "listening"
        : "idle";

  const latestSpeechText = messages
    .filter(m => m.role === "assistant")
    .pop()?.text.replace(/[*_#`[\]()]/g, "") || "";

  const scrollRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Scroll automatique
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, thinking]);

  // Émission constante de l'état de l'avatar vers la mascotte globale
  useEffect(() => {
    if (typeof window !== "undefined") {
      window.dispatchEvent(
        new CustomEvent("finbot:avatar-state", {
          detail: { mode: avatarMode, mood, text: latestSpeechText },
        })
      );
    }
  }, [avatarMode, mood, latestSpeechText]);

  /* ── Réaction émotionnelle + geste à une nouvelle réponse ─────────────── */
  const reactToAnswer = useCallback((answer: string, nextRadar: RadarCard[]) => {
    const m = detectMood(answer, nextRadar);
    setMood(m);
    const gestureType = m === "alert" ? "alert" : m === "concerned" ? "lean" : "nod";

    // Petit délai pour que le geste accompagne le début de la parole
    window.setTimeout(() => {
      avatarRef.current?.gesture(gestureType);
      if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent("finbot:avatar-gesture", { detail: gestureType }));
      }
      if (nextRadar.length > 0 && (m === "concerned" || m === "alert")) {
        window.setTimeout(() => {
          avatarRef.current?.gesture("glance");
          if (typeof window !== "undefined") {
            window.dispatchEvent(new CustomEvent("finbot:avatar-gesture", { detail: "glance" }));
          }
        }, 700);
      }
    }, 150);
  }, [avatarRef]);

  /** Affiche la réponse, met à jour le radar, fait réagir et parler l'avatar. */
  const recevoir = (answer: string, via: Msg["via"], radarRecu: unknown) => {
    const nextRadar: RadarCard[] = Array.isArray(radarRecu) ? radarRecu.slice(0, 4) : radar;
    if (Array.isArray(radarRecu)) setRadar(nextRadar);
    setMessages(m => [...m, { role: "assistant", text: answer, via }]);
    reactToAnswer(answer, nextRadar);
    speak(answer);
  };

  /* ── Envoi message texte ──────────────────────────────────────────────── */
  const send = async (q?: string) => {
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
        const data = await analyserFichier(attachment.file, question, filterPayload);
        recevoir(data.answer || "Je n'ai pas pu analyser ce fichier.", data.via, data.radar);
      } catch {
        setMessages(m => [...m, {
          role: "assistant",
          text: `⚠️ Erreur lors de l'analyse du fichier. Vérifiez que l'API tourne (${API_URL}).`,
          via: "error",
        }]);
      } finally {
        setUploadProgress(false);
        setAttachment(null);
      }
    } else {
      // Question texte standard
      try {
        const data = await poserQuestion(filterPayload, question, historyForBackend);
        recevoir(data.answer || "Je n'ai pas trouvé de réponse.", data.via, data.radar);
      } catch {
        setMessages(m => [...m, {
          role: "assistant",
          text: `⚠️ Impossible de joindre le copilote. Vérifiez que l'API tourne (${API_URL}).`,
          via: "error",
        }]);
      }
    }

    setThinking(false);
  };

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
    // Le copilote traite les fichiers TEXTUELS ; les documents scannés
    // (images, factures papier) relèvent de l'onglet « Documents & OCR ».
    const allowed = ["csv", "pdf"];
    if (!allowed.includes(ext)) {
      alert(`Format non supporté (${ext}).\n\nLe copilote analyse les CSV et PDF.\n` +
        `Pour une image ou un document scanné (facture, contrat), utilisez ` +
        `l'onglet « Documents & OCR » : il extrait les champs et rapproche la ` +
        `facture de vos données ERP.`);
      return;
    }
    setAttachment({ file, preview: null });
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

  return {
    messages, input, setInput, thinking, speaking, voiceOn, listening, attachment,
    uploadProgress, showSuggestions, setShowSuggestions, suggestions, scrollRef,
    fileInputRef, send, speak, listen, handleFileSelect, removeAttachment, toggleVoice,
  };
}
