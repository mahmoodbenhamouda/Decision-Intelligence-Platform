"use client";

/**
 * FinBotAvatar — assistant IA sous forme d'ORBE (pas de visage humain).
 *
 * Un noyau lumineux « vivant » : grands yeux expressifs, anneau orbital,
 * bouche = égaliseur vocal (barres synchronisées à la parole). Il expose une
 * petite API impérative (setViseme / restMouth / gesture) et fait tourner UNE
 * boucle requestAnimationFrame qui pilote :
 *   - la synchro labiale  → amplitude des barres d'égaliseur
 *   - les émotions        → forme des yeux + sourcils + teinte
 *   - le "vivant"         → regard (saccades) + clignements + respiration
 *   - les gestes          → hochement / recul alerte / penché / coup d'œil
 *
 * Les mouvements rapides sont appliqués directement sur le DOM SVG (refs) pour
 * ne pas re-rendre React 60x/seconde.
 */

import {
  forwardRef, useEffect, useImperativeHandle, useRef,
} from "react";

/* ── Types publics (inchangés pour rester compatibles) ──────────────────── */
export type AvatarMode = "idle" | "listening" | "thinking" | "speaking";
export type AvatarMood = "neutral" | "happy" | "concerned" | "alert";
export type GestureType = "nod" | "alert" | "glance" | "lean";

export interface Viseme { open: number; wide: number; round: number }

export interface AvatarHandle {
  setViseme: (v: Viseme) => void;
  restMouth: () => void;
  gesture: (type: GestureType) => void;
}

interface AvatarProps {
  mode: AvatarMode;
  mood: AvatarMood;
  accent: string;
}

/* ── Visèmes : caractère → forme de bouche (amplitude via .open) ─────────── */
const REST: Viseme = { open: 0.05, wide: 0.42, round: 0 };

function stripAccent(c: string): string {
  return c
    .replace(/[àâä]/g, "a").replace(/[éèêë]/g, "e")
    .replace(/[îï]/g, "i").replace(/[ôö]/g, "o").replace(/[ûü]/g, "u");
}

export function visemeForChar(raw: string): Viseme {
  const c = stripAccent(raw.toLowerCase());
  if ("ae".includes(c)) return { open: 0.95, wide: 0.55, round: 0 };
  if ("iy".includes(c)) return { open: 0.45, wide: 0.95, round: 0 };
  if (c === "o") return { open: 0.78, wide: 0.2, round: 0.9 };
  if (c === "u" || c === "w") return { open: 0.5, wide: 0.12, round: 1 };
  if ("mbp".includes(c)) return { open: 0.06, wide: 0.32, round: 0.1 };
  if ("fv".includes(c)) return { open: 0.25, wide: 0.5, round: 0 };
  if ("lntdszrcgkjqxh".includes(c)) return { open: 0.4, wide: 0.58, round: 0.1 };
  if (c === " " || c === "." || c === "," || c === ";" || c === "!" || c === "?" || c === "\n")
    return { open: 0.05, wide: 0.4, round: 0 };
  return { open: 0.45, wide: 0.5, round: 0.1 };
}

/* ── Utilitaires ────────────────────────────────────────────────────────── */
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

/** Couleur d'accent secondaire (yeux / lueur) selon l'humeur. */
function moodGlow(mood: AvatarMood, accent: string): string {
  switch (mood) {
    case "happy": return "#28E0A8";
    case "concerned": return "#FBA53B";
    case "alert": return "#FF5A5A";
    default: return accent;
  }
}

/** Cibles émotionnelles : courbure des yeux + inclinaison des sourcils. */
interface MoodTarget { eyeCurve: number; browTy: number; browRot: number; squint: number }
function moodTarget(mode: AvatarMode, mood: AvatarMood): MoodTarget {
  if (mode === "thinking") return { eyeCurve: 0, browTy: -2, browRot: 4, squint: 0.15 };
  if (mode === "listening") return { eyeCurve: 0.15, browTy: -2, browRot: 0, squint: 0 };
  switch (mood) {
    case "happy": return { eyeCurve: 1, browTy: -3, browRot: 0, squint: 0.35 };
    case "concerned": return { eyeCurve: -0.35, browTy: 1, browRot: 16, squint: 0.1 };
    case "alert": return { eyeCurve: -0.6, browTy: 2, browRot: 24, squint: 0.15 };
    default: return { eyeCurve: 0, browTy: 0, browRot: 0, squint: 0 };
  }
}

function poseTarget(mode: AvatarMode): { gx: number; gy: number; rot: number } {
  switch (mode) {
    case "thinking": return { gx: -3, gy: -2, rot: -5 };
    case "listening": return { gx: 2, gy: 1, rot: 3 };
    default: return { gx: 0, gy: 0, rot: 0 };
  }
}

/**
 * Path d'un œil : morphe entre un œil "pilule" arrondi (neutre),
 * un arc souriant (curve>0) et un œil incliné/agacé (curve<0).
 * cx = centre horizontal, cy = centre vertical, curve ∈ [-1,1].
 */
function eyePath(cx: number, cy: number, curve: number, side: 1 | -1): string {
  const w = 9;                       // demi-largeur
  const h = 11;                      // demi-hauteur
  const L = cx - w, R = cx + w;
  if (curve > 0) {
    // œil souriant : arc convexe vers le haut
    const lift = curve * 11;
    const yb = cy + 3;
    return `M ${L} ${yb} Q ${cx} ${yb - lift - 8} ${R} ${yb} Q ${cx} ${yb - lift} ${L} ${yb} Z`;
  }
  // œil neutre → incliné : pilule arrondie, coin intérieur relevé si curve<0
  const inner = side === 1 ? R : L;   // côté nez
  const outer = side === 1 ? L : R;
  const tilt = -curve * 6;            // inclinaison "agacé"
  const topInner = cy - h - tilt, topOuter = cy - h + tilt * 0.4;
  const botInner = cy + h - tilt, botOuter = cy + h + tilt * 0.4;
  return `M ${outer} ${topOuter}
          Q ${cx} ${cy - h - 2} ${inner} ${topInner}
          Q ${inner + side * 3} ${cy} ${inner} ${botInner}
          Q ${cx} ${cy + h + 2} ${outer} ${botOuter}
          Q ${outer - side * 3} ${cy} ${outer} ${topOuter} Z`;
}

/* ── Composant ──────────────────────────────────────────────────────────── */
const FinBotAvatar = forwardRef<AvatarHandle, AvatarProps>(function FinBotAvatar(
  { mode, mood, accent },
  ref,
) {
  const coreRef = useRef<SVGGElement>(null);       // groupe animé (respiration/pose/gestes)
  const ringRef = useRef<SVGGElement>(null);       // anneau orbital rotatif
  const eyesRef = useRef<SVGGElement>(null);       // groupe yeux (regard + clignement)
  const eyeLRef = useRef<SVGPathElement>(null);
  const eyeRRef = useRef<SVGPathElement>(null);
  const browLRef = useRef<SVGPathElement>(null);
  const browRRef = useRef<SVGPathElement>(null);
  const barRefs = useRef<(SVGRectElement | null)[]>([]);

  const modeRef = useRef<AvatarMode>(mode);
  const moodRef = useRef<AvatarMood>(mood);
  const targetAmp = useRef(0);      // amplitude bouche cible (via viseme.open)
  const speakingRef = useRef(false);

  const cur = useRef({
    amp: 0, eyeCurve: 0, browTy: 0, browRot: 0, squint: 0,
    gazeX: 0, gazeY: 0, poseGx: 0, poseGy: 0, poseRot: 0, ring: 0,
  });
  const gaze = useRef({ tx: 0, ty: 0, nextAt: 0 });
  const blink = useRef({ open: 1, nextAt: 0, closing: false, startAt: 0 });
  const gest = useRef<{ type: GestureType; start: number } | null>(null);

  useEffect(() => { modeRef.current = mode; }, [mode]);
  useEffect(() => { moodRef.current = mood; }, [mood]);

  useImperativeHandle(ref, () => ({
    setViseme: (v: Viseme) => { targetAmp.current = v.open; speakingRef.current = true; },
    restMouth: () => { targetAmp.current = 0; speakingRef.current = false; },
    gesture: (type: GestureType) => { gest.current = { type, start: performance.now() }; },
  }), []);

  const NBARS = 9;

  /* ── Boucle d'animation ───────────────────────────────────────────────── */
  useEffect(() => {
    let raf = 0;
    const loop = (now: number) => {
      const t = now / 1000;
      const md = modeRef.current;

      /* Respiration (pulsation douce) */
      const breath = 1 + Math.sin(t * 1.5) * 0.018;

      /* Anneau orbital : rotation continue (plus vite quand il parle/réfléchit) */
      const ringSpeed = speakingRef.current ? 46 : md === "thinking" ? 34 : 14;
      cur.current.ring = (cur.current.ring + ringSpeed / 60) % 360;
      if (ringRef.current)
        ringRef.current.setAttribute("transform", `rotate(${cur.current.ring.toFixed(1)} 110 110)`);

      /* Pose (mode) lissée */
      const pt = poseTarget(md);
      cur.current.poseGx = lerp(cur.current.poseGx, pt.gx, 0.06);
      cur.current.poseGy = lerp(cur.current.poseGy, pt.gy, 0.06);
      cur.current.poseRot = lerp(cur.current.poseRot, pt.rot, 0.06);

      /* Gestes ponctuels */
      let gGx = 0, gGy = 0, gRot = 0;
      if (gest.current) {
        const g = gest.current;
        const dur = g.type === "nod" ? 620 : g.type === "alert" ? 520 : 700;
        const p = (now - g.start) / dur;
        if (p >= 1) { gest.current = null; }
        else if (g.type === "nod") { gGy = Math.sin(p * Math.PI) * 7; gRot = Math.sin(p * Math.PI) * 2; }
        else if (g.type === "alert") {
          const decay = 1 - p;
          gGx = Math.sin(p * Math.PI * 4) * 5 * decay;
          gRot = -Math.sin(p * Math.PI) * 4; gGy = -Math.sin(p * Math.PI) * 3;
        } else if (g.type === "lean") { gRot = Math.sin(p * Math.PI) * -5; }
      }

      if (coreRef.current) {
        const gx = cur.current.poseGx + gGx;
        const gy = cur.current.poseGy + gGy;
        const rot = cur.current.poseRot + gRot;
        coreRef.current.setAttribute(
          "transform",
          `translate(${gx.toFixed(2)} ${gy.toFixed(2)}) rotate(${rot.toFixed(2)} 110 110) scale(${breath.toFixed(4)})`,
        );
      }

      /* Regard : saccades / dirigé selon le mode */
      if (now >= gaze.current.nextAt) {
        if (md === "thinking") { gaze.current.tx = -3.5; gaze.current.ty = -3; }
        else if (md === "listening") { gaze.current.tx = 0; gaze.current.ty = 1.6; }
        else { gaze.current.tx = (Math.random() - 0.5) * 6; gaze.current.ty = (Math.random() - 0.5) * 4; }
        gaze.current.nextAt = now + 900 + Math.random() * 2600;
      }
      if (gest.current?.type === "glance") { gaze.current.tx = 5; gaze.current.ty = 4.5; }
      cur.current.gazeX = lerp(cur.current.gazeX, gaze.current.tx, 0.14);
      cur.current.gazeY = lerp(cur.current.gazeY, gaze.current.ty, 0.14);

      /* Clignement */
      if (!blink.current.closing && now >= blink.current.nextAt) {
        blink.current.closing = true; blink.current.startAt = now;
      }
      if (blink.current.closing) {
        const bp = (now - blink.current.startAt) / 130;
        if (bp >= 1) { blink.current.closing = false; blink.current.open = 1; blink.current.nextAt = now + 2200 + Math.random() * 3600; }
        else blink.current.open = 1 - Math.sin(bp * Math.PI) * 0.9;
      }

      /* Émotion (yeux + sourcils) lissée */
      const mt = moodTarget(md, moodRef.current);
      cur.current.eyeCurve = lerp(cur.current.eyeCurve, mt.eyeCurve, 0.1);
      cur.current.browTy = lerp(cur.current.browTy, mt.browTy, 0.1);
      cur.current.browRot = lerp(cur.current.browRot, mt.browRot, 0.1);
      cur.current.squint = lerp(cur.current.squint, mt.squint, 0.1);

      // Yeux : path (émotion) + clignement/squint via scaleY autour du centre
      const eScale = (blink.current.open * (1 - cur.current.squint * 0.45)).toFixed(3);
      if (eyeLRef.current) eyeLRef.current.setAttribute("d", eyePath(88, 100, cur.current.eyeCurve, -1));
      if (eyeRRef.current) eyeRRef.current.setAttribute("d", eyePath(132, 100, cur.current.eyeCurve, 1));
      if (eyesRef.current)
        eyesRef.current.setAttribute(
          "transform",
          `translate(${cur.current.gazeX.toFixed(2)} ${cur.current.gazeY.toFixed(2)}) translate(110 100) scale(1 ${eScale}) translate(-110 -100)`,
        );

      // Sourcils (deux traits qui s'inclinent)
      if (browLRef.current)
        browLRef.current.setAttribute("transform", `translate(0 ${cur.current.browTy.toFixed(2)}) rotate(${cur.current.browRot.toFixed(2)} 88 80)`);
      if (browRRef.current)
        browRRef.current.setAttribute("transform", `translate(0 ${cur.current.browTy.toFixed(2)}) rotate(${(-cur.current.browRot).toFixed(2)} 132 80)`);

      /* Bouche = égaliseur vocal */
      const k = speakingRef.current ? 0.4 : 0.16;
      cur.current.amp = lerp(cur.current.amp, speakingRef.current ? targetAmp.current : 0, k);
      const amp = cur.current.amp;
      const cyBar = 150, maxH = 26, minH = 3;
      for (let i = 0; i < NBARS; i++) {
        const el = barRefs.current[i];
        if (!el) continue;
        // profil en cloche (barres centrales plus hautes) + oscillation temporelle
        const bell = 0.55 + 0.45 * Math.sin((i / (NBARS - 1)) * Math.PI);
        const wobble = 0.45 + 0.55 * Math.abs(Math.sin(t * 11 + i * 0.9));
        const h = minH + amp * maxH * bell * wobble;
        el.setAttribute("y", (cyBar - h / 2).toFixed(2));
        el.setAttribute("height", h.toFixed(2));
      }

      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, []);

  const glow = moodGlow(mood, accent);
  const barX = Array.from({ length: NBARS }, (_, i) => 82 + i * 7);

  return (
    <svg
      className={`cop-orb mode-${mode} mood-${mood}`}
      viewBox="0 0 220 220" width="210" height="210"
      aria-label="Assistant IA FinBot"
    >
      <defs>
        <radialGradient id="orbBody" cx="38%" cy="32%" r="75%">
          <stop offset="0%" stopColor="#FFFFFF" stopOpacity="0.95" />
          <stop offset="26%" stopColor={accent} stopOpacity="0.95" />
          <stop offset="72%" stopColor={accent} />
          <stop offset="100%" stopColor="#0B1B4D" />
        </radialGradient>
        <radialGradient id="orbInner" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor={glow} stopOpacity="0.0" />
          <stop offset="70%" stopColor={glow} stopOpacity="0.0" />
          <stop offset="100%" stopColor={glow} stopOpacity="0.5" />
        </radialGradient>
        <linearGradient id="orbRing" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor={glow} />
          <stop offset="100%" stopColor="#14C2D6" />
        </linearGradient>
        <filter id="orbBlur" x="-40%" y="-40%" width="180%" height="180%">
          <feGaussianBlur stdDeviation="2.2" />
        </filter>
      </defs>

      {/* Ombre portée */}
      <ellipse cx="110" cy="205" rx="60" ry="10" fill="rgba(11,27,77,0.16)" />

      {/* Anneau orbital rotatif + particule */}
      <g ref={ringRef}>
        <circle cx="110" cy="110" r="97" fill="none" stroke="url(#orbRing)" strokeWidth="2"
          strokeDasharray="3 10" opacity="0.55" />
        <circle cx="110" cy="13" r="4.5" fill={glow} filter="url(#orbBlur)" />
        <circle cx="207" cy="110" r="3" fill="#14C2D6" opacity="0.8" />
      </g>

      {/* Noyau (groupe animé) */}
      <g ref={coreRef}>
        {/* corps de l'orbe */}
        <circle cx="110" cy="110" r="80" fill="url(#orbBody)" />
        {/* liseré lumineux interne selon l'humeur */}
        <circle cx="110" cy="110" r="80" fill="url(#orbInner)" />
        <circle cx="110" cy="110" r="80" fill="none" stroke={glow} strokeWidth="2" opacity="0.6" />
        {/* reflet glossy */}
        <ellipse cx="84" cy="78" rx="34" ry="22" fill="#FFFFFF" opacity="0.18" />
        <circle cx="150" cy="150" r="30" fill="#0B1B4D" opacity="0.14" />

        {/* Sourcils (émotion) */}
        <path ref={browLRef} d="M76 82 q12 -6 24 -1" stroke="#EAF2FF" strokeWidth="3.4"
          strokeLinecap="round" fill="none" opacity="0.9" />
        <path ref={browRRef} d="M120 81 q12 -5 24 1" stroke="#EAF2FF" strokeWidth="3.4"
          strokeLinecap="round" fill="none" opacity="0.9" />

        {/* Yeux (regard + clignement + émotion) */}
        <g ref={eyesRef}>
          <path ref={eyeLRef} d={eyePath(88, 100, 0, -1)} fill="#F4FBFF" />
          <path ref={eyeRRef} d={eyePath(132, 100, 0, 1)} fill="#F4FBFF" />
          {/* petits éclats dans les yeux */}
          <circle cx="91" cy="96" r="2.4" fill={accent} opacity="0.85" />
          <circle cx="135" cy="96" r="2.4" fill={accent} opacity="0.85" />
        </g>

        {/* Bouche = égaliseur vocal */}
        <g>
          {barX.map((x, i) => (
            <rect
              key={i}
              ref={(el) => { barRefs.current[i] = el; }}
              x={x} y={148} width={4} height={3} rx={2}
              fill="#EAF2FF" opacity="0.92"
            />
          ))}
        </g>
      </g>
    </svg>
  );
});

export default FinBotAvatar;
