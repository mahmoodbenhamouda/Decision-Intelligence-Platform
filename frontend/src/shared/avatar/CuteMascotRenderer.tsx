"use client";

import React, { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import type { AvatarHandle, AvatarMode, AvatarMood, GestureType, Viseme } from "./FinBotAvatar";

export type MascotType = "astra" | "kitsune";

interface CuteMascotProps {
  mode?: AvatarMode;
  mood?: AvatarMood;
  accent?: string;
  type?: MascotType;
  size?: number;
  className?: string;
}

const CuteMascotRenderer = forwardRef<AvatarHandle, CuteMascotProps>(function CuteMascotRenderer(
  {
    mode = "idle",
    mood = "neutral",
    accent = "#2F5BEA",
    type = "astra",
    size = 140,
    className = "",
  },
  ref
) {
  const [blinking, setBlinking] = useState(false);
  const [mouthOpen, setMouthOpen] = useState(0.1);
  const [mouseOffset, setMouseOffset] = useState({ x: 0, y: 0 });
  const [gestureTilt, setGestureTilt] = useState(0);
  const [gestureBounce, setGestureBounce] = useState(0);

  const containerRef = useRef<HTMLDivElement>(null);
  const blinkTimerRef = useRef<NodeJS.Timeout | null>(null);

  // Exposition de l'API impérative (compatible Copilot / AvatarHandle)
  useImperativeHandle(ref, () => ({
    setViseme: (v: Viseme) => {
      setMouthOpen(Math.min(1, Math.max(0.1, v.open)));
    },
    restMouth: () => {
      setMouthOpen(0.1);
    },
    gesture: (gestureType: GestureType) => {
      if (gestureType === "nod") {
        setGestureBounce(8);
        setTimeout(() => setGestureBounce(-4), 150);
        setTimeout(() => setGestureBounce(0), 300);
      } else if (gestureType === "glance" || gestureType === "lean") {
        setGestureTilt(12);
        setTimeout(() => setGestureTilt(-6), 250);
        setTimeout(() => setGestureTilt(0), 500);
      } else if (gestureType === "alert") {
        setGestureBounce(-10);
        setGestureTilt(-10);
        setTimeout(() => {
          setGestureBounce(0);
          setGestureTilt(0);
        }, 400);
      }
    },
  }));

  // Clignement automatique des yeux (toutes les 2 à 5s)
  useEffect(() => {
    const scheduleBlink = () => {
      const delay = Math.random() * 3000 + 2000;
      blinkTimerRef.current = setTimeout(() => {
        setBlinking(true);
        setTimeout(() => setBlinking(false), 160);
        scheduleBlink();
      }, delay);
    };
    scheduleBlink();
    return () => {
      if (blinkTimerRef.current) clearTimeout(blinkTimerRef.current);
    };
  }, []);

  // Suivi doux du curseur de la souris pour les yeux
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const cx = rect.left + rect.width / 2;
      const cy = rect.top + rect.height / 2;
      const dx = (e.clientX - cx) / 100;
      const dy = (e.clientY - cy) / 100;
      const clampX = Math.max(-6, Math.min(6, dx));
      const clampY = Math.max(-5, Math.min(5, dy));
      setMouseOffset({ x: clampX, y: clampY });
    };

    window.addEventListener("mousemove", handleMouseMove);
    return () => window.removeEventListener("mousemove", handleMouseMove);
  }, []);

  const glowColor = accent;
  const isThinking = mode === "thinking";
  const isSpeaking = mode === "speaking";

  const getEyeExpression = () => {
    if (blinking) return "blink";
    if (mood === "happy" || isSpeaking) return "happy";
    if (mood === "concerned") return "concerned";
    if (mood === "alert" || isThinking) return "surprised";
    return "normal";
  };

  const eyeState = getEyeExpression();

  return (
    <div
      ref={containerRef}
      className={`cute-mascot-container ${className}`}
      style={{
        width: `${size}px`,
        height: `${size * 1.15}px`,
        position: "relative",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        userSelect: "none",
      }}
    >
      {/* Halo lumineux d'aura sous la mascotte */}
      <div
        className={`cute-mascot-aura ${isSpeaking || isThinking ? "active" : ""}`}
        style={{
          position: "absolute",
          top: "15%",
          left: "5%",
          width: "90%",
          height: "75%",
          borderRadius: "50%",
          background: `radial-gradient(circle, ${glowColor}55 0%, transparent 70%)`,
          filter: "blur(14px)",
          pointerEvents: "none",
          transition: "all 0.3s ease",
          opacity: isSpeaking ? 0.9 : isThinking ? 0.7 : 0.45,
          transform: isSpeaking ? "scale(1.12)" : "scale(1)",
        }}
      />

      {/* Corps animé de la Mascotte */}
      <div
        className="cute-mascot-body-wrapper"
        style={{
          width: "100%",
          height: "85%",
          position: "relative",
          animation: "cute-float 3.2s ease-in-out infinite",
          transform: `translateY(${gestureBounce}px) rotate(${gestureTilt}deg)`,
          transition: "transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1)",
        }}
      >
        {/* Rendu ASTRA (Mini-Bot Mignon) */}
        {type === "astra" && (
          <svg
            viewBox="0 0 200 210"
            className="cute-mascot-svg"
            style={{ width: "100%", height: "100%", overflow: "visible" }}
          >
            <defs>
              <linearGradient id={`headGlow-${accent}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#FFFFFF" />
                <stop offset="60%" stopColor="#F1F5F9" />
                <stop offset="100%" stopColor="#CBD5E1" />
              </linearGradient>
              <linearGradient id={`visorBg-${accent}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#0F172A" />
                <stop offset="100%" stopColor="#1E293B" />
              </linearGradient>
              <linearGradient id={`accentGrad-${accent}`} x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stopColor={accent} />
                <stop offset="100%" stopColor="#818CF8" />
              </linearGradient>

              <filter id="softGlow" x="-20%" y="-20%" width="140%" height="140%">
                <feGaussianBlur stdDeviation="3" result="blur" />
                <feComposite in="SourceGraphic" in2="blur" operator="over" />
              </filter>
            </defs>

            {/* Antenne lumineuse avec perle glow */}
            <g transform="translate(100, 20)">
              <line x1="0" y1="0" x2="0" y2="-18" stroke="#94A3B8" strokeWidth="4" strokeLinecap="round" />
              <circle
                cx="0"
                cy="-22"
                r="7"
                fill={accent}
                filter="url(#softGlow)"
                style={{
                  animation: isThinking ? "pulse-fast 0.6s infinite alternate" : "pulse-glow 2s infinite alternate",
                }}
              />
            </g>

            {/* Oreilles / Écouteurs latéraux */}
            <g>
              <rect x="24" y="80" width="14" height="28" rx="6" fill={`url(#accentGrad-${accent})`} />
              <rect x="162" y="80" width="14" height="28" rx="6" fill={`url(#accentGrad-${accent})`} />
              <circle cx="31" cy="94" r="3" fill="#FFF" opacity="0.8" />
              <circle cx="169" cy="94" r="3" fill="#FFF" opacity="0.8" />
            </g>

            {/* Casque / Tête Blanche Glossy */}
            <rect
              x="34"
              y="30"
              width="132"
              height="124"
              rx="46"
              fill={`url(#headGlow-${accent})`}
              stroke="#E2E8F0"
              strokeWidth="2.5"
              filter="drop-shadow(0px 8px 16px rgba(0,0,0,0.15))"
            />

            {/* Écran Visière Sombre Glossy */}
            <rect x="44" y="46" width="112" height="92" rx="34" fill={`url(#visorBg-${accent})`} />

            {/* Reflet sur la visière en haut à gauche */}
            <path
              d="M 54 56 Q 100 48 140 56 Q 120 66 56 66 Z"
              fill="#FFFFFF"
              opacity="0.12"
            />

            {/* Yeux LED Expressifs avec suivi du regard */}
            <g transform={`translate(${mouseOffset.x}, ${mouseOffset.y})`}>
              {/* Oeil Gauche */}
              {eyeState === "blink" ? (
                <line x1="68" y1="88" x2="88" y2="88" stroke={accent} strokeWidth="5" strokeLinecap="round" />
              ) : eyeState === "happy" ? (
                <path d="M 66 92 Q 78 74 90 92" fill="none" stroke={accent} strokeWidth="5.5" strokeLinecap="round" />
              ) : eyeState === "concerned" ? (
                <g>
                  <line x1="66" y1="78" x2="88" y2="84" stroke={accent} strokeWidth="3" strokeLinecap="round" />
                  <ellipse cx="78" cy="90" rx="9" ry="11" fill={accent} />
                  <circle cx="81" cy="86" r="3" fill="#FFF" />
                </g>
              ) : (
                <g>
                  <ellipse cx="78" cy="88" rx="10" ry="13" fill={accent} filter="url(#softGlow)" />
                  <circle cx="81" cy="84" r="3.5" fill="#FFFFFF" />
                  <circle cx="74" cy="92" r="1.8" fill="#FFFFFF" opacity="0.8" />
                </g>
              )}

              {/* Oeil Droit */}
              {eyeState === "blink" ? (
                <line x1="112" y1="88" x2="132" y2="88" stroke={accent} strokeWidth="5" strokeLinecap="round" />
              ) : eyeState === "happy" ? (
                <path d="M 110 92 Q 122 74 134 92" fill="none" stroke={accent} strokeWidth="5.5" strokeLinecap="round" />
              ) : eyeState === "concerned" ? (
                <g>
                  <line x1="134" y1="78" x2="112" y2="84" stroke={accent} strokeWidth="3" strokeLinecap="round" />
                  <ellipse cx="122" cy="90" rx="9" ry="11" fill={accent} />
                  <circle cx="125" cy="86" r="3" fill="#FFF" />
                </g>
              ) : (
                <g>
                  <ellipse cx="122" cy="88" rx="10" ry="13" fill={accent} filter="url(#softGlow)" />
                  <circle cx="125" cy="84" r="3.5" fill="#FFFFFF" />
                  <circle cx="118" cy="92" r="1.8" fill="#FFFFFF" opacity="0.8" />
                </g>
              )}

              {/* Joues Roses Cute */}
              <ellipse cx="64" cy="102" rx="7" ry="4" fill="#F43F5E" opacity={mood === "happy" ? "0.6" : "0.35"} />
              <ellipse cx="136" cy="102" rx="7" ry="4" fill="#F43F5E" opacity={mood === "happy" ? "0.6" : "0.35"} />

              {/* Bouche LED Réactive aux visèmes / parole */}
              {isSpeaking ? (
                <path
                  d={`M 90 108 Q 100 ${108 + mouthOpen * 18} 110 108`}
                  fill={accent}
                  opacity="0.9"
                  stroke={accent}
                  strokeWidth="3"
                  strokeLinecap="round"
                />
              ) : mood === "happy" ? (
                <path d="M 92 108 Q 100 118 108 108" fill="none" stroke={accent} strokeWidth="3.5" strokeLinecap="round" />
              ) : mood === "concerned" ? (
                <path d="M 92 114 Q 100 106 108 114" fill="none" stroke={accent} strokeWidth="3" strokeLinecap="round" />
              ) : (
                <ellipse cx="100" cy="110" rx="5" ry="3" fill={accent} opacity="0.85" />
              )}
            </g>

            {/* Corps Inférieur Flottant */}
            <g transform="translate(100, 160)">
              <path
                d="M -32 -6 Q 0 16 32 -6 Q 20 22 0 22 Q -20 22 -32 -6 Z"
                fill={`url(#accentGrad-${accent})`}
                filter="drop-shadow(0px 4px 6px rgba(0,0,0,0.15))"
              />
              <circle cx="0" cy="8" r="4" fill="#FFFFFF" opacity="0.9" />
            </g>
          </svg>
        )}

        {/* Rendu KITSUNE (CyberPet Bleu Mignon) */}
        {type === "kitsune" && (
          <svg viewBox="0 0 200 210" className="cute-mascot-svg" style={{ width: "100%", height: "100%", overflow: "visible" }}>
            <defs>
              <linearGradient id="cyberBlueBody" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#38BDF8" />
                <stop offset="60%" stopColor="#2F5BEA" />
                <stop offset="100%" stopColor="#1E3A8A" />
              </linearGradient>
              <linearGradient id="cyberBlueEars" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#0284C7" />
                <stop offset="100%" stopColor="#1D4ED8" />
              </linearGradient>
            </defs>

            {/* Oreilles Cyber Pet Bleues */}
            <path d="M 38 72 L 64 12 L 92 62 Z" fill="url(#cyberBlueEars)" />
            <path d="M 48 67 L 64 26 L 82 62 Z" fill="#E0F2FE" opacity="0.9" />
            <path d="M 162 72 L 136 12 L 108 62 Z" fill="url(#cyberBlueEars)" />
            <path d="M 152 67 L 136 26 L 118 62 Z" fill="#E0F2FE" opacity="0.9" />

            {/* Tête Cyber Pet Bleu Glossy */}
            <ellipse cx="100" cy="95" rx="60" ry="50" fill="url(#cyberBlueBody)" filter="drop-shadow(0 8px 16px rgba(14,165,233,0.3))" />
            <path d="M 52 95 Q 100 138 148 95 Q 100 152 52 95 Z" fill="#F0F9FF" />

            {/* Truffe */}
            <polygon points="95,110 105,110 100,117" fill="#0F172A" />

            {/* Yeux LED Bleus avec suivi du regard */}
            <g transform={`translate(${mouseOffset.x}, ${mouseOffset.y})`}>
              {eyeState === "blink" ? (
                <>
                  <line x1="68" y1="88" x2="84" y2="88" stroke="#0284C7" strokeWidth="4" strokeLinecap="round" />
                  <line x1="116" y1="88" x2="132" y2="88" stroke="#0284C7" strokeWidth="4" strokeLinecap="round" />
                </>
              ) : (
                <>
                  <ellipse cx="76" cy="88" rx="9" ry="13" fill="#0F172A" />
                  <circle cx="79" cy="84" r="3.5" fill="#38BDF8" />
                  <circle cx="74" cy="92" r="1.5" fill="#FFF" />

                  <ellipse cx="124" cy="88" rx="9" ry="13" fill="#0F172A" />
                  <circle cx="127" cy="84" r="3.5" fill="#38BDF8" />
                  <circle cx="122" cy="92" r="1.5" fill="#FFF" />
                </>
              )}

              {/* Joues cute */}
              <ellipse cx="62" cy="100" rx="6" ry="3.5" fill="#38BDF8" opacity="0.7" />
              <ellipse cx="138" cy="100" rx="6" ry="3.5" fill="#38BDF8" opacity="0.7" />

              {/* Bouche cute */}
              {isSpeaking ? (
                <path d={`M 92 108 Q 100 ${108 + mouthOpen * 14} 108 108`} fill="#0284C7" />
              ) : (
                <path d="M 93 108 Q 100 116 107 108" fill="none" stroke="#0F172A" strokeWidth="2.5" strokeLinecap="round" />
              )}
            </g>

            {/* Lunettes Cyber Bleues Mignonnes */}
            <rect x="56" y="76" width="36" height="26" rx="9" fill="none" stroke="#38BDF8" strokeWidth="3" filter="drop-shadow(0 0 4px #38BDF8)" />
            <rect x="108" y="76" width="36" height="26" rx="9" fill="none" stroke="#38BDF8" strokeWidth="3" filter="drop-shadow(0 0 4px #38BDF8)" />
            <line x1="92" y1="88" x2="108" y2="88" stroke="#38BDF8" strokeWidth="3" />
          </svg>
        )}
      </div>

      {/* Ombre Elliptique Dynamique au Sol */}
      <div
        className="cute-mascot-shadow"
        style={{
          width: "60px",
          height: "12px",
          borderRadius: "50%",
          background: "rgba(15, 23, 42, 0.25)",
          filter: "blur(4px)",
          marginTop: "-10px",
          animation: "cute-shadow-pulse 3.2s ease-in-out infinite",
        }}
      />
    </div>
  );
});

export default CuteMascotRenderer;
