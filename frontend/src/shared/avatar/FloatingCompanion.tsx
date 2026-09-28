"use client";

import React, { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { Move, X, Minimize2, Sparkles, MessageSquare, RefreshCw } from "lucide-react";
import CuteMascotRenderer, { type MascotType } from "./CuteMascotRenderer";
import type { AvatarHandle, AvatarMode, AvatarMood, Viseme, GestureType } from "./FinBotAvatar";

interface FloatingCompanionProps {
  mode?: AvatarMode;
  mood?: AvatarMood;
  accent?: string;
  speechText?: string;
  onOpenChat?: () => void;
  onAccentChange?: (color: string) => void;
}

const FloatingCompanion = forwardRef<AvatarHandle, FloatingCompanionProps>(function FloatingCompanion(
  {
    mode = "idle",
    mood = "neutral",
    accent = "#2F5BEA",
    speechText = "",
    onOpenChat,
    onAccentChange,
  },
  ref
) {
  // Position du composant (persistance localStorage)
  const [pos, setPos] = useState<{ x: number; y: number }>({ x: 40, y: 120 });
  const [isDragging, setIsDragging] = useState(false);
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 });
  const [isMinimized, setIsMinimized] = useState(false);
  const [mascotType, setMascotType] = useState<MascotType>("astra");
  const [showSpeechBubble, setShowSpeechBubble] = useState(true);

  // États internes synchronisés avec le Copilote (via CustomEvents globaux)
  const [currentMode, setCurrentMode] = useState<AvatarMode>(mode);
  const [currentMood, setCurrentMood] = useState<AvatarMood>(mood);
  const [currentSpeechText, setCurrentSpeechText] = useState<string>(speechText);

  const mascotRef = useRef<AvatarHandle>(null);
  const companionRef = useRef<HTMLDivElement>(null);

  // Écouteurs d'événements globaux du Copilote
  useEffect(() => {
    const handleState = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (detail) {
        if (detail.mode !== undefined) setCurrentMode(detail.mode);
        if (detail.mood !== undefined) setCurrentMood(detail.mood);
        if (detail.text !== undefined) setCurrentSpeechText(detail.text);
      }
    };

    const handleViseme = (e: Event) => {
      const viseme = (e as CustomEvent).detail;
      if (viseme) mascotRef.current?.setViseme(viseme);
    };

    const handleRestMouth = () => {
      mascotRef.current?.restMouth();
    };

    const handleGesture = (e: Event) => {
      const gestureType = (e as CustomEvent).detail;
      if (gestureType) mascotRef.current?.gesture(gestureType);
    };

    window.addEventListener("finbot:avatar-state", handleState);
    window.addEventListener("finbot:avatar-viseme", handleViseme);
    window.addEventListener("finbot:avatar-rest-mouth", handleRestMouth);
    window.addEventListener("finbot:avatar-gesture", handleGesture);

    return () => {
      window.removeEventListener("finbot:avatar-state", handleState);
      window.removeEventListener("finbot:avatar-viseme", handleViseme);
      window.removeEventListener("finbot:avatar-rest-mouth", handleRestMouth);
      window.removeEventListener("finbot:avatar-gesture", handleGesture);
    };
  }, []);

  // Sync props initiales
  useEffect(() => {
    if (mode) setCurrentMode(mode);
    if (mood) setCurrentMood(mood);
    if (speechText) setCurrentSpeechText(speechText);
  }, [mode, mood, speechText]);

  // Transmission du handle
  useImperativeHandle(ref, () => ({
    setViseme: (v: Viseme) => mascotRef.current?.setViseme(v),
    restMouth: () => mascotRef.current?.restMouth(),
    gesture: (g: GestureType) => mascotRef.current?.gesture(g),
  }));

  // Initialisation de la position au chargement
  useEffect(() => {
    try {
      const saved = localStorage.getItem("finbot_companion_pos");
      if (saved) {
        const parsed = JSON.parse(saved);
        setPos(parsed);
      } else {
        // En bas à droite par défaut
        setPos({
          x: Math.max(20, window.innerWidth - 220),
          y: Math.max(20, window.innerHeight - 280),
        });
      }
    } catch {
      // Ignorer les erreurs d'accès au localStorage
    }
  }, []);

  // Sauvegarde de la position
  const savePosition = (newPos: { x: number; y: number }) => {
    setPos(newPos);
    try {
      localStorage.setItem("finbot_companion_pos", JSON.stringify(newPos));
    } catch {}
  };

  // Gestion du Drag & Drop (Souris + Tactile)
  const handlePointerDown = (e: React.PointerEvent) => {
    // Si on clique sur un bouton intérieur, ne pas démarrer le drag
    if ((e.target as HTMLElement).closest("button")) return;

    setIsDragging(true);
    const rect = companionRef.current?.getBoundingClientRect();
    if (rect) {
      setDragOffset({
        x: e.clientX - rect.left,
        y: e.clientY - rect.top,
      });
    }
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  };

  const handlePointerMove = (e: React.PointerEvent) => {
    if (!isDragging) return;
    const maxX = window.innerWidth - 160;
    const maxY = window.innerHeight - 160;
    const newX = Math.max(10, Math.min(maxX, e.clientX - dragOffset.x));
    const newY = Math.max(10, Math.min(maxY, e.clientY - dragOffset.y));
    setPos({ x: newX, y: newY });
  };

  const handlePointerUp = (e: React.PointerEvent) => {
    if (isDragging) {
      setIsDragging(false);
      savePosition(pos);
      try {
        (e.target as HTMLElement).releasePointerCapture(e.pointerId);
      } catch {}
    }
  };

  // Basculer la mascotte (Astra Mini-Bot ↔ CyberPet Bleu)
  const cycleMascot = () => {
    const types: MascotType[] = ["astra", "kitsune"];
    const nextIdx = (types.indexOf(mascotType) + 1) % types.length;
    setMascotType(types[nextIdx]);
  };

  if (isMinimized) {
    return (
      <button
        onClick={() => setIsMinimized(false)}
        className="floating-companion-badge"
        style={{
          position: "fixed",
          left: `${pos.x}px`,
          top: `${pos.y}px`,
          zIndex: 9999,
          background: `linear-gradient(135deg, ${accent}, #1E1B4B)`,
          color: "#FFF",
          border: "2px solid rgba(255,255,255,0.2)",
          borderRadius: "30px",
          padding: "8px 16px",
          display: "flex",
          alignItems: "center",
          gap: "8px",
          cursor: "pointer",
          boxShadow: "0 10px 25px rgba(0,0,0,0.25)",
          backdropFilter: "blur(10px)",
          fontWeight: 600,
          fontSize: "13px",
        }}
        title="Ouvrir le compagnon flottant"
      >
        <Sparkles size={16} />
        <span>FinBot</span>
      </button>
    );
  }

  return (
    <div
      ref={companionRef}
      className={`floating-companion-wrapper ${isDragging ? "dragging" : ""}`}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      style={{
        position: "fixed",
        left: `${pos.x}px`,
        top: `${pos.y}px`,
        zIndex: 9999,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        cursor: isDragging ? "grabbing" : "grab",
        userSelect: "none",
        touchAction: "none",
        transition: isDragging ? "none" : "transform 0.1s ease",
      }}
    >
      {/* Barre d'outils au survol (Drag handle, Changer mascotte, Réduire) */}
      <div
        className="floating-companion-controls"
        style={{
          display: "flex",
          alignItems: "center",
          gap: "4px",
          background: "rgba(15, 23, 42, 0.75)",
          backdropFilter: "blur(12px)",
          border: "1px solid rgba(255,255,255,0.15)",
          borderRadius: "20px",
          padding: "4px 8px",
          marginBottom: "6px",
          opacity: 0.9,
          boxShadow: "0 4px 12px rgba(0,0,0,0.2)",
        }}
      >
        <div style={{ cursor: "grab", color: "#94A3B8", padding: "2px" }} title="Glisser pour déplacer">
          <Move size={13} />
        </div>
        <button
          onClick={cycleMascot}
          style={{
            background: "none",
            border: "none",
            color: "#CBD5E1",
            cursor: "pointer",
            padding: "2px",
            display: "flex",
            alignItems: "center",
          }}
          title="Changer de mascotte (Astra / Kitsune / Sparky)"
        >
          <RefreshCw size={13} />
        </button>
        {onOpenChat && (
          <button
            onClick={onOpenChat}
            style={{
              background: "none",
              border: "none",
              color: "#38BDF8",
              cursor: "pointer",
              padding: "2px",
              display: "flex",
              alignItems: "center",
            }}
            title="Parler au Copilote"
          >
            <MessageSquare size={13} />
          </button>
        )}
        <button
          onClick={() => setIsMinimized(true)}
          style={{
            background: "none",
            border: "none",
            color: "#94A3B8",
            cursor: "pointer",
            padding: "2px",
            display: "flex",
            alignItems: "center",
          }}
          title="Réduire"
        >
          <Minimize2 size={13} />
        </button>
      </div>

      {/* Bulle de dialogue Glassmorphism (Speech Bubble) */}
      {(currentSpeechText || currentMode === "thinking" || currentMode === "speaking") && showSpeechBubble && (
        <div
          className="floating-companion-speech"
          style={{
            maxWidth: "220px",
            background: "rgba(15, 23, 42, 0.85)",
            backdropFilter: "blur(14px)",
            border: `1px solid ${accent}55`,
            borderRadius: "16px",
            padding: "10px 14px",
            color: "#F8FAFC",
            fontSize: "12px",
            lineHeight: "1.4",
            marginBottom: "8px",
            boxShadow: "0 8px 24px rgba(0,0,0,0.3)",
            position: "relative",
            animation: "fadeIn 0.2s ease-out",
          }}
        >
          {currentMode === "thinking" ? (
            <span style={{ fontStyle: "italic", color: "#94A3B8", display: "flex", alignItems: "center", gap: "6px" }}>
              <Sparkles size={12} className="spin-slow" /> Analyse en cours...
            </span>
          ) : (
            <span>{currentSpeechText.length > 100 ? currentSpeechText.substring(0, 97) + "..." : currentSpeechText || "À votre écoute !"}</span>
          )}
          {/* Petite flèche indicatrice de bulle en bas */}
          <div
            style={{
              position: "absolute",
              bottom: "-6px",
              left: "50%",
              transform: "translateX(-50%) rotate(45deg)",
              width: "10px",
              height: "10px",
              background: "rgba(15, 23, 42, 0.85)",
              borderRight: `1px solid ${accent}55`,
              borderBottom: `1px solid ${accent}55`,
            }}
          />
        </div>
      )}

      {/* Mascotte Mignonne */}
      <CuteMascotRenderer
        ref={mascotRef}
        mode={currentMode}
        mood={currentMood}
        accent={accent}
        type={mascotType}
        size={130}
      />
    </div>
  );
});

export default FloatingCompanion;
