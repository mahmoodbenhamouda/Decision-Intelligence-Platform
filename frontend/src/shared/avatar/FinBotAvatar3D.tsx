"use client";

import {
  forwardRef, useEffect, useId, useImperativeHandle, useRef, useState,
} from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import FinBotAvatar, {
  type AvatarHandle, type AvatarMode, type AvatarMood, type GestureType, type Viseme,
} from "./FinBotAvatar";

export type { AvatarHandle, AvatarMode, AvatarMood, GestureType, Viseme };

const LOCAL_MODEL = "/avatar/finbot.glb";
const MAX_DPR = 2;
let _localModelMissing = false;

const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
const clamp01 = (v: number) => Math.max(0, Math.min(1, v));

function modelUrls(): string[] {
  if (typeof window !== "undefined") {
    const force = new URLSearchParams(window.location.search).get("avatar");
    if (force === "procedural" || force === "companion") return [];
    if (force === "local") return [LOCAL_MODEL];
  }
  return _localModelMissing ? [] : [LOCAL_MODEL];
}

function poseForMode(mode: AvatarMode): { rx: number; ry: number; rz: number; gaze: [number, number] } {
  switch (mode) {
    case "thinking": return { rx: -0.05, ry: 0.10, rz: 0.04, gaze: [0.24, -0.20] };
    case "listening": return { rx: 0.04, ry: -0.03, rz: -0.04, gaze: [0, 0.18] };
    case "speaking": return { rx: 0.01, ry: 0, rz: 0, gaze: [0, 0] };
    default: return { rx: 0, ry: 0, rz: 0, gaze: [0, 0] };
  }
}

const MOOD_SHAPES: Record<AvatarMood, Record<string, number>> = {
  neutral: { mouthSmileLeft: 0.22, mouthSmileRight: 0.22, browInnerUp: 0.08 },
  happy: {
    mouthSmileLeft: 0.64, mouthSmileRight: 0.64,
    cheekSquintLeft: 0.24, cheekSquintRight: 0.24,
    browInnerUp: 0.18, eyeSquintLeft: 0.14, eyeSquintRight: 0.14,
  },
  concerned: {
    browInnerUp: 0.46, browDownLeft: 0.12, browDownRight: 0.12,
    mouthSmileLeft: 0.04, mouthSmileRight: 0.04,
    mouthFrownLeft: 0.18, mouthFrownRight: 0.18,
  },
  alert: {
    browInnerUp: 0.38, browDownLeft: 0.28, browDownRight: 0.28,
    eyeWideLeft: 0.45, eyeWideRight: 0.45,
    mouthFrownLeft: 0.18, mouthFrownRight: 0.18,
  },
};

interface FacialRig {
  has(name: string): boolean;
  set(name: string, value: number): void;
}

class MorphRig implements FacialRig {
  private targets = new Map<string, { mesh: THREE.Mesh; index: number }[]>();

  register(mesh: THREE.Mesh): void {
    const dict = mesh.morphTargetDictionary;
    if (!dict || !mesh.morphTargetInfluences) return;
    for (const [name, index] of Object.entries(dict)) {
      const list = this.targets.get(name) || [];
      list.push({ mesh, index });
      this.targets.set(name, list);
    }
  }

  has(name: string): boolean { return this.targets.has(name); }

  set(name: string, value: number): void {
    const list = this.targets.get(name);
    if (!list) return;
    for (const { mesh, index } of list) mesh.morphTargetInfluences![index] = value;
  }
}

interface CompanionState {
  viseme: Viseme;
  speaking: boolean;
  mouthOpen: number;
  mouthWide: number;
  mouthRound: number;
  gazeX: number;
  gazeY: number;
  targetGazeX: number;
  targetGazeY: number;
  nextGazeAt: number;
  blink: number;
  blinkPhase: number;
  nextBlinkAt: number;
  gesture: { type: GestureType; start: number } | null;
  seed: number;
}

function companionMood(mood: AvatarMood, mode: AvatarMode) {
  const base = {
    smile: 0.24, frown: 0, browLift: 0.10, browPinch: 0,
    eyeWide: 0.05, squint: 0, cheek: 0.32,
  };
  if (mode === "thinking") return { ...base, smile: 0.12, browLift: 0.18, browPinch: 0.08, eyeWide: 0.02 };
  if (mode === "listening") return { ...base, smile: 0.30, browLift: 0.18, eyeWide: 0.12, cheek: 0.38 };
  switch (mood) {
    case "happy": return { ...base, smile: 0.72, browLift: 0.24, squint: 0.12, cheek: 0.68 };
    case "concerned": return { ...base, smile: 0.02, frown: 0.28, browLift: 0.28, browPinch: 0.24, eyeWide: 0.12, cheek: 0.22 };
    case "alert": return { ...base, smile: 0, frown: 0.34, browLift: 0.10, browPinch: 0.48, eyeWide: 0.42, cheek: 0.18 };
    default: return base;
  }
}

const FinBotCompanion = forwardRef<AvatarHandle, {
  mode: AvatarMode; mood: AvatarMood; accent: string;
}>(function FinBotCompanion({ mode, mood, accent }, ref) {
  const uid = useId().replace(/:/g, "");
  const rootRef = useRef<SVGGElement>(null);
  const faceRef = useRef<SVGGElement>(null);
  const eyesRef = useRef<SVGGElement>(null);
  const leftBrowRef = useRef<SVGPathElement>(null);
  const rightBrowRef = useRef<SVGPathElement>(null);
  const leftLidRef = useRef<SVGRectElement>(null);
  const rightLidRef = useRef<SVGRectElement>(null);
  const mouthRef = useRef<SVGPathElement>(null);
  const mouthFillRef = useRef<SVGEllipseElement>(null);
  const cheekLRef = useRef<SVGCircleElement>(null);
  const cheekRRef = useRef<SVGCircleElement>(null);
  const ringRef = useRef<SVGCircleElement>(null);
  const modeRef = useRef(mode);
  const moodRef = useRef(mood);
  const accentRef = useRef(accent);
  const state = useRef<CompanionState>({
    viseme: { open: 0, wide: 0.42, round: 0 },
    speaking: false,
    mouthOpen: 0,
    mouthWide: 0.42,
    mouthRound: 0,
    gazeX: 0,
    gazeY: 0,
    targetGazeX: 0,
    targetGazeY: 0,
    nextGazeAt: 0,
    blink: 0,
    blinkPhase: -1,
    nextBlinkAt: 0,
    gesture: null,
    seed: Math.random() * 1000,
  });

  useEffect(() => { modeRef.current = mode; }, [mode]);
  useEffect(() => { moodRef.current = mood; }, [mood]);
  useEffect(() => { accentRef.current = accent; }, [accent]);

  useImperativeHandle(ref, () => ({
    setViseme: (v) => { state.current.viseme = v; state.current.speaking = true; },
    restMouth: () => { state.current.speaking = false; },
    gesture: (type) => { state.current.gesture = { type, start: performance.now() }; },
  }), []);

  useEffect(() => {
    let raf = 0;
    let last = performance.now();
    const loop = (now: number) => {
      raf = requestAnimationFrame(loop);
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const t = now / 1000;
      const s = state.current;
      const md = modeRef.current;
      const moodTarget = companionMood(moodRef.current, md);
      const speakingEnergy = s.speaking ? clamp01(s.viseme.open * 0.85 + 0.18) : 0;

      s.mouthOpen = lerp(s.mouthOpen, s.speaking ? s.viseme.open : 0, 1 - Math.exp(-dt * 22));
      s.mouthWide = lerp(s.mouthWide, s.speaking ? s.viseme.wide : 0.42, 1 - Math.exp(-dt * 18));
      s.mouthRound = lerp(s.mouthRound, s.speaking ? s.viseme.round : 0, 1 - Math.exp(-dt * 18));

      if (s.blinkPhase < 0 && now >= s.nextBlinkAt) s.blinkPhase = 0;
      if (s.blinkPhase >= 0) {
        s.blinkPhase += dt * 1000;
        const p = s.blinkPhase / 150;
        if (p >= 1) {
          s.blink = 0;
          s.blinkPhase = -1;
          s.nextBlinkAt = now + 1800 + Math.random() * 2900;
        } else {
          s.blink = Math.sin(p * Math.PI);
        }
      }

      const pose = poseForMode(md);
      if (now >= s.nextGazeAt) {
        const amp = md === "idle" ? 5.5 : 2.2;
        s.targetGazeX = pose.gaze[0] * 10 + (Math.random() - 0.5) * amp;
        s.targetGazeY = pose.gaze[1] * 10 + (Math.random() - 0.5) * amp;
        s.nextGazeAt = now + 720 + Math.random() * 1900;
      }
      if (s.gesture?.type === "glance") { s.targetGazeX = -7; s.targetGazeY = 3; }
      s.gazeX = lerp(s.gazeX, s.targetGazeX, 1 - Math.exp(-dt * 9));
      s.gazeY = lerp(s.gazeY, s.targetGazeY, 1 - Math.exp(-dt * 9));

      let gx = 0, gy = 0, rot = 0;
      if (s.gesture) {
        const dur = s.gesture.type === "nod" ? 650 : s.gesture.type === "alert" ? 560 : 760;
        const p = (now - s.gesture.start) / dur;
        if (p >= 1) s.gesture = null;
        else if (s.gesture.type === "nod") gy = Math.sin(p * Math.PI * 2) * 7 * (1 - p);
        else if (s.gesture.type === "alert") { gx = Math.sin(p * Math.PI * 5) * 4.5 * (1 - p); rot = -Math.sin(p * Math.PI) * 4; }
        else if (s.gesture.type === "lean") rot = -Math.sin(p * Math.PI) * 4.5;
      }

      const breathe = 1 + Math.sin(t * 1.45 + s.seed) * 0.012 + speakingEnergy * 0.012;
      const microRot = Math.sin(t * 0.9 + s.seed) * 0.8 + speakingEnergy * Math.sin(t * 7.5) * 0.55;
      rootRef.current?.setAttribute(
        "transform",
        `translate(${gx.toFixed(2)} ${(gy + Math.sin(t * 1.2) * 1.2).toFixed(2)}) rotate(${(rot + microRot).toFixed(2)} 120 128) scale(${breathe.toFixed(4)})`,
      );
      faceRef.current?.setAttribute("transform", `translate(${(s.gazeX * 0.14).toFixed(2)} ${(s.gazeY * 0.10).toFixed(2)})`);
      eyesRef.current?.setAttribute("transform", `translate(${s.gazeX.toFixed(2)} ${s.gazeY.toFixed(2)})`);

      const blink = Math.max(s.blink, moodTarget.squint, s.mouthOpen * 0.05);
      const lidH = 3 + blink * 25;
      for (const [lid, x] of [[leftLidRef.current, 75], [rightLidRef.current, 137]] as const) {
        if (!lid) continue;
        lid.setAttribute("x", String(x));
        lid.setAttribute("y", (91 - lidH * 0.45).toFixed(2));
        lid.setAttribute("height", lidH.toFixed(2));
        lid.setAttribute("opacity", (0.08 + blink * 0.96).toFixed(3));
      }

      const browLift = moodTarget.browLift + speakingEnergy * 0.12;
      const pinch = moodTarget.browPinch;
      leftBrowRef.current?.setAttribute(
        "d",
        `M 69 ${(82 - browLift * 8 + pinch * 4).toFixed(1)} C 80 ${(76 - browLift * 10).toFixed(1)} 95 ${(77 + pinch * 7).toFixed(1)} 106 ${(82 + pinch * 3).toFixed(1)}`,
      );
      rightBrowRef.current?.setAttribute(
        "d",
        `M 134 ${(82 + pinch * 3).toFixed(1)} C 145 ${(77 + pinch * 7).toFixed(1)} 160 ${(76 - browLift * 10).toFixed(1)} 171 ${(82 - browLift * 8 + pinch * 4).toFixed(1)}`,
      );

      const open = s.mouthOpen;
      const round = s.mouthRound;
      const wide = s.mouthWide;
      const smile = moodTarget.smile + speakingEnergy * 0.18;
      const frown = moodTarget.frown;
      const rx = 18 + wide * 18 - round * 10;
      const ry = Math.max(2.2, open * 15 + round * 3);
      const cy = 151 + open * 3 + frown * 5 - smile * 3;
      mouthFillRef.current?.setAttribute("rx", Math.max(7, rx - round * 5).toFixed(2));
      mouthFillRef.current?.setAttribute("ry", ry.toFixed(2));
      mouthFillRef.current?.setAttribute("cy", cy.toFixed(2));
      mouthFillRef.current?.setAttribute("opacity", (0.18 + clamp01(open) * 0.86).toFixed(3));
      const lift = smile * 16 - frown * 13;
      const leftY = 151 - lift * 0.24 + frown * 6;
      const midY = 154 + open * 10 - smile * 9 + frown * 11;
      const rightY = leftY;
      mouthRef.current?.setAttribute(
        "d",
        `M ${(120 - rx).toFixed(1)} ${leftY.toFixed(1)} C ${(108 - wide * 5).toFixed(1)} ${midY.toFixed(1)} ${(132 + wide * 5).toFixed(1)} ${midY.toFixed(1)} ${(120 + rx).toFixed(1)} ${rightY.toFixed(1)}`,
      );
      mouthRef.current?.setAttribute("stroke-width", (4.5 + open * 2.4).toFixed(2));

      const cheekOpacity = moodTarget.cheek + speakingEnergy * 0.22;
      cheekLRef.current?.setAttribute("opacity", String(Math.min(0.78, cheekOpacity)));
      cheekRRef.current?.setAttribute("opacity", String(Math.min(0.78, cheekOpacity)));
      ringRef.current?.setAttribute("opacity", String(0.16 + speakingEnergy * 0.36 + moodTarget.eyeWide * 0.18));
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, []);

  const skin = mood === "alert" ? "#eeb18b" : "#efbf98";
  const cheek = mood === "alert" ? "#ff8f8f" : mood === "happy" ? "#ffb0a2" : "#e9a08d";
  const mouth = mood === "alert" ? "#8b263b" : "#8f3f4c";

  return (
    <svg className={`finbot-companion mode-${mode} mood-${mood}`} viewBox="0 0 240 260" width="240" height="260" aria-label="Compagnon FinBot">
      <defs>
        <radialGradient id={`${uid}-skin`} cx="42%" cy="28%" r="76%">
          <stop offset="0%" stopColor="#ffe2c8" />
          <stop offset="52%" stopColor={skin} />
          <stop offset="100%" stopColor="#b67858" />
        </radialGradient>
        <linearGradient id={`${uid}-suit`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#22305d" />
          <stop offset="58%" stopColor="#111a37" />
          <stop offset="100%" stopColor="#050916" />
        </linearGradient>
        <linearGradient id={`${uid}-accent`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor={accent} />
          <stop offset="100%" stopColor="#15c7d9" />
        </linearGradient>
        <filter id={`${uid}-soft-shadow`} x="-35%" y="-35%" width="170%" height="170%">
          <feDropShadow dx="0" dy="14" stdDeviation="12" floodColor="#111a37" floodOpacity="0.20" />
        </filter>
      </defs>

      <ellipse cx="120" cy="235" rx="74" ry="13" fill="#142044" opacity="0.16" />
      <g ref={rootRef} filter={`url(#${uid}-soft-shadow)`}>
        <path d="M46 221 C51 178 83 166 120 166 C157 166 189 178 194 221 C158 238 82 238 46 221 Z" fill={`url(#${uid}-suit)`} />
        <path d="M94 169 L120 226 L146 169 C137 175 103 175 94 169 Z" fill="#f5f8ff" opacity="0.92" />
        <path d="M110 184 L120 226 L130 184 L120 176 Z" fill={`url(#${uid}-accent)`} />
        <rect x="98" y="139" width="44" height="48" rx="20" fill="#c98763" />
        <path d="M96 166 C109 174 131 174 144 166 L137 184 C127 191 113 191 103 184 Z" fill="#dba17b" opacity="0.55" />

        <g ref={faceRef}>
          <path d="M58 99 C58 49 86 25 120 25 C154 25 182 49 182 99 C182 148 157 172 120 172 C83 172 58 148 58 99 Z" fill={`url(#${uid}-skin)`} />
          <path d="M59 92 C63 50 91 31 120 31 C149 31 176 50 181 92 C166 74 143 65 120 65 C97 65 74 74 59 92 Z" fill="#151a35" />
          <path d="M72 74 C85 49 104 39 124 38 C146 38 165 49 175 73 C153 58 96 57 72 74 Z" fill="#232b5b" opacity="0.72" />
          <path d="M62 100 C52 100 46 108 47 119 C48 130 55 136 64 133 Z" fill="#d59470" />
          <path d="M178 100 C188 100 194 108 193 119 C192 130 185 136 176 133 Z" fill="#d59470" />
          <circle ref={ringRef} cx="120" cy="102" r="78" fill="none" stroke={`url(#${uid}-accent)`} strokeWidth="3" opacity="0.16" />
          <path d="M117 111 C114 122 108 128 101 134 C112 139 125 139 136 134 C128 128 122 122 117 111 Z" fill="#9b674e" opacity="0.42" />
          <path d="M118 105 C123 112 127 119 128 125 C124 128 118 128 114 125 C115 119 116 112 118 105 Z" fill="#7c513e" opacity="0.54" />

          <circle ref={cheekLRef} cx="82" cy="132" r="14" fill={cheek} opacity="0.34" />
          <circle ref={cheekRRef} cx="158" cy="132" r="14" fill={cheek} opacity="0.34" />

          <path ref={leftBrowRef} d="M69 82 C80 76 95 77 106 82" stroke="#14192f" strokeWidth="5" strokeLinecap="round" fill="none" />
          <path ref={rightBrowRef} d="M134 82 C145 77 160 76 171 82" stroke="#14192f" strokeWidth="5" strokeLinecap="round" fill="none" />

          <g ref={eyesRef}>
            <g>
              <ellipse cx="91" cy="103" rx="22" ry="15" fill="#f9fbff" />
              <circle cx="91" cy="103" r="8.4" fill={accent} />
              <circle cx="91" cy="103" r="4" fill="#0b1024" />
              <circle cx="88" cy="100" r="2.3" fill="#fff" />
            </g>
            <g>
              <ellipse cx="149" cy="103" rx="22" ry="15" fill="#f9fbff" />
              <circle cx="149" cy="103" r="8.4" fill={accent} />
              <circle cx="149" cy="103" r="4" fill="#0b1024" />
              <circle cx="146" cy="100" r="2.3" fill="#fff" />
            </g>
          </g>
          <rect ref={leftLidRef} x="75" y="91" width="32" height="3" rx="8" fill={skin} opacity="0.08" />
          <rect ref={rightLidRef} x="137" y="91" width="32" height="3" rx="8" fill={skin} opacity="0.08" />

          <ellipse ref={mouthFillRef} cx="120" cy="151" rx="19" ry="3" fill="#331c25" opacity="0.18" />
          <path ref={mouthRef} d="M92 151 C105 158 135 158 148 151" stroke={mouth} strokeWidth="4.5" strokeLinecap="round" fill="none" />
          <path d="M94 38 C86 54 75 66 59 77" stroke="#11162e" strokeWidth="8" strokeLinecap="round" fill="none" opacity="0.55" />
          <path d="M146 39 C159 49 171 62 181 80" stroke="#11162e" strokeWidth="8" strokeLinecap="round" fill="none" opacity="0.45" />
          <ellipse cx="94" cy="61" rx="6" ry="4" fill="#f2f5ff" opacity="0.18" />
        </g>
      </g>
    </svg>
  );
});

interface AnimState {
  viseme: Viseme;
  speaking: boolean;
  cur: Record<string, number>;
  blink: { value: number; nextAt: number; phase: number };
  gaze: { x: number; y: number; tx: number; ty: number; nextAt: number };
  head: { rx: number; ry: number; rz: number };
  gesture: { type: GestureType; start: number } | null;
  seed: number;
}

const Avatar3DScene = forwardRef<AvatarHandle, {
  mode: AvatarMode; mood: AvatarMood; accent: string;
  onFail: () => void; onReady: () => void; onNoModel: () => void;
}>(function Avatar3DScene({ mode, mood, accent, onFail, onReady, onNoModel }, ref) {
  const mountRef = useRef<HTMLDivElement>(null);
  const modeRef = useRef(mode);
  const moodRef = useRef(mood);
  const accentRef = useRef(accent);
  const anim = useRef<AnimState>({
    viseme: { open: 0, wide: 0.3, round: 0 },
    speaking: false,
    cur: {},
    blink: { value: 0, nextAt: 0, phase: -1 },
    gaze: { x: 0, y: 0, tx: 0, ty: 0, nextAt: 0 },
    head: { rx: 0, ry: 0, rz: 0 },
    gesture: null,
    seed: Math.random() * 1000,
  });

  useEffect(() => { modeRef.current = mode; }, [mode]);
  useEffect(() => { moodRef.current = mood; }, [mood]);
  useEffect(() => { accentRef.current = accent; }, [accent]);

  useImperativeHandle(ref, () => ({
    setViseme: (v) => { anim.current.viseme = v; anim.current.speaking = true; },
    restMouth: () => { anim.current.speaking = false; },
    gesture: (type) => { anim.current.gesture = { type, start: performance.now() }; },
  }), []);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;
    const urls = modelUrls();
    if (urls.length === 0) { onNoModel(); return; }

    try {
      const probe = document.createElement("canvas");
      if (!probe.getContext("webgl2") && !probe.getContext("webgl")) { onFail(); return; }
    } catch { onFail(); return; }

    const W = mount.clientWidth || 240;
    const H = mount.clientHeight || 260;
    let disposed = false;
    let raf = 0;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch { onFail(); return; }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, MAX_DPR));
    renderer.setSize(W, H);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;
    mount.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(21, W / H, 0.1, 20);
    camera.position.set(0, 1.62, 0.95);
    camera.lookAt(0, 1.62, 0);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x8890a8, 1.15));
    const key = new THREE.DirectionalLight(0xffffff, 1.6);
    key.position.set(0.6, 2.4, 1.4);
    scene.add(key);
    const rim = new THREE.DirectionalLight(new THREE.Color(accentRef.current), 0.9);
    rim.position.set(0, 2.0, -1.6);
    scene.add(rim);

    const rig = new MorphRig();
    let headBone: THREE.Object3D | null = null;
    let neckBone: THREE.Object3D | null = null;
    let spineBone: THREE.Object3D | null = null;
    let eyeL: THREE.Object3D | null = null;
    let eyeR: THREE.Object3D | null = null;
    const baseRot = new Map<THREE.Object3D, THREE.Euler>();

    const loader = new GLTFLoader();
    loader.load(
      urls[0],
      (gltf) => {
        if (disposed) return;
        gltf.scene.traverse((obj) => {
          if ((obj as THREE.Mesh).isMesh) {
            const mesh = obj as THREE.Mesh;
            mesh.frustumCulled = false;
            rig.register(mesh);
          }
          const n = obj.name.toLowerCase();
          if (!headBone && n.includes("head") && !n.includes("headtop")) headBone = obj;
          if (!neckBone && n.includes("neck")) neckBone = obj;
          if (!spineBone && (n === "spine" || n === "spine1" || n === "spine2")) spineBone = obj;
          if (!eyeL && (n === "lefteye" || n === "eyeleft" || n === "eye_l")) eyeL = obj;
          if (!eyeR && (n === "righteye" || n === "eyeright" || n === "eye_r")) eyeR = obj;
        });
        for (const b of [headBone, neckBone, spineBone, eyeL, eyeR]) if (b) baseRot.set(b, b.rotation.clone());
        scene.add(gltf.scene);
        onReady();
      },
      undefined,
      () => {
        _localModelMissing = true;
        onNoModel();
      },
    );

    const mouthTargets = (v: Viseme, speaking: boolean): Record<string, number> => {
      const open = speaking ? v.open : 0;
      const wide = speaking ? v.wide : 0.05;
      const round = speaking ? v.round : 0;
      if (rig.has("viseme_aa")) {
        return {
          viseme_aa: Math.max(0, open - round * 0.4) * 0.9,
          viseme_I: wide * open * 0.7,
          viseme_O: round * open * 0.9,
          viseme_U: Math.max(0, round - open * 0.3) * 0.8,
          viseme_PP: open < 0.1 && speaking ? 0.6 : 0,
          viseme_sil: speaking ? 0 : 0.4,
          jawOpen: open * 0.35,
        };
      }
      return {
        jawOpen: open * 0.6,
        mouthFunnel: round * 0.7,
        mouthPucker: Math.max(0, round - open * 0.4) * 0.8,
        mouthStretchLeft: wide * 0.5,
        mouthStretchRight: wide * 0.5,
        mouthClose: !speaking ? 0.1 : 0,
      };
    };

    const driven = new Set<string>([
      "jawOpen", "mouthFunnel", "mouthPucker", "mouthClose",
      "mouthStretchLeft", "mouthStretchRight", "mouthSmileLeft", "mouthSmileRight",
      "mouthFrownLeft", "mouthFrownRight", "browDownLeft", "browDownRight",
      "browInnerUp", "eyeWideLeft", "eyeWideRight", "eyeSquintLeft", "eyeSquintRight",
      "cheekSquintLeft", "cheekSquintRight", "viseme_aa", "viseme_I", "viseme_O",
      "viseme_U", "viseme_PP", "viseme_sil", "eyeBlinkLeft", "eyeBlinkRight",
    ]);

    let hidden = document.visibilityState === "hidden";
    const onVis = () => {
      hidden = document.visibilityState === "hidden";
      if (!hidden) { cancelAnimationFrame(raf); raf = requestAnimationFrame(loop); }
    };
    document.addEventListener("visibilitychange", onVis);

    const ro = new ResizeObserver(() => {
      const w = mount.clientWidth || W;
      const h = mount.clientHeight || H;
      renderer.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    });
    ro.observe(mount);

    let last = performance.now();
    const loop = (now: number) => {
      if (disposed || hidden) return;
      raf = requestAnimationFrame(loop);
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const t = now / 1000;
      const a = anim.current;
      const targets: Record<string, number> = { ...MOOD_SHAPES[moodRef.current], ...mouthTargets(a.viseme, a.speaking) };

      if (a.blink.phase < 0 && now >= a.blink.nextAt) a.blink.phase = 0;
      if (a.blink.phase >= 0) {
        a.blink.phase += dt * 1000;
        const p = a.blink.phase / 140;
        if (p >= 1) {
          a.blink.phase = -1;
          a.blink.value = 0;
          a.blink.nextAt = now + 2100 + Math.random() * 3200;
        } else a.blink.value = Math.sin(p * Math.PI);
      }
      targets.eyeBlinkLeft = Math.max(targets.eyeBlinkLeft || 0, a.blink.value);
      targets.eyeBlinkRight = Math.max(targets.eyeBlinkRight || 0, a.blink.value);

      for (const name of driven) {
        const target = targets[name] || 0;
        const isMouth = name.startsWith("viseme") || name.startsWith("jaw") || name.startsWith("mouth");
        const isBlink = name.startsWith("eyeBlink");
        const k = isBlink ? 1 : isMouth ? 1 - Math.exp(-dt * 26) : 1 - Math.exp(-dt * 7);
        a.cur[name] = lerp(a.cur[name] || 0, target, k);
        rig.set(name, a.cur[name]);
      }

      const pose = poseForMode(modeRef.current);
      if (now >= a.gaze.nextAt) {
        const amp = modeRef.current === "idle" ? 0.14 : 0.06;
        a.gaze.tx = pose.gaze[0] + (Math.random() - 0.5) * amp;
        a.gaze.ty = pose.gaze[1] + (Math.random() - 0.5) * amp;
        a.gaze.nextAt = now + 700 + Math.random() * 2400;
      }
      a.gaze.x = lerp(a.gaze.x, a.gaze.tx, 1 - Math.exp(-dt * 10));
      a.gaze.y = lerp(a.gaze.y, a.gaze.ty, 1 - Math.exp(-dt * 10));
      for (const eye of [eyeL, eyeR]) {
        if (!eye) continue;
        const base = baseRot.get(eye);
        if (!base) continue;
        eye.rotation.x = base.x - a.gaze.y * 0.35;
        eye.rotation.y = base.y + a.gaze.x * 0.4;
      }

      const noise = (f: number, ph: number) => Math.sin(t * f + a.seed + ph) * 0.6 + Math.sin(t * f * 2.7 + ph * 2) * 0.4;
      a.head.rx = lerp(a.head.rx, pose.rx + noise(0.31, 1) * 0.012 + a.gaze.y * 0.15, 1 - Math.exp(-dt * 5));
      a.head.ry = lerp(a.head.ry, pose.ry + noise(0.23, 5) * 0.02 + a.gaze.x * 0.25, 1 - Math.exp(-dt * 5));
      a.head.rz = lerp(a.head.rz, pose.rz + noise(0.17, 9) * 0.008, 1 - Math.exp(-dt * 5));
      if (headBone) {
        const base = baseRot.get(headBone)!;
        headBone.rotation.set(base.x + a.head.rx, base.y + a.head.ry, base.z + a.head.rz);
      }
      if (neckBone) {
        const base = baseRot.get(neckBone)!;
        neckBone.rotation.set(base.x + a.head.rx * 0.35, base.y + a.head.ry * 0.35, base.z + a.head.rz * 0.35);
      }
      if (spineBone) {
        const base = baseRot.get(spineBone)!;
        spineBone.rotation.x = base.x + Math.sin(t * 1.4) * 0.006;
      }
      rim.color.set(accentRef.current);
      renderer.render(scene, camera);
    };
    raf = requestAnimationFrame(loop);

    return () => {
      disposed = true;
      cancelAnimationFrame(raf);
      document.removeEventListener("visibilitychange", onVis);
      ro.disconnect();
      renderer.dispose();
      scene.traverse((obj) => {
        const mesh = obj as THREE.Mesh;
        if (mesh.isMesh) {
          mesh.geometry?.dispose();
          const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
          mats.forEach((m) => m?.dispose());
        }
      });
      if (renderer.domElement.parentElement === mount) mount.removeChild(renderer.domElement);
    };
  }, [onFail, onNoModel, onReady]);

  return <div ref={mountRef} className="cop-avatar3d-mount" aria-label="Avatar 3D FinBot" />;
});

const FinBotAvatar3D = forwardRef<AvatarHandle, {
  mode: AvatarMode; mood: AvatarMood; accent: string;
}>(function FinBotAvatar3D({ mode, mood, accent }, ref) {
  const [failed, setFailed] = useState(false);
  const [ready, setReady] = useState(false);
  const [useCompanion, setUseCompanion] = useState(() => modelUrls().length === 0);
  const sceneRef = useRef<AvatarHandle>(null);
  const companionRef = useRef<AvatarHandle>(null);
  const orbRef = useRef<AvatarHandle>(null);

  useImperativeHandle(ref, () => ({
    setViseme: (v) => {
      sceneRef.current?.setViseme(v);
      companionRef.current?.setViseme(v);
      orbRef.current?.setViseme(v);
    },
    restMouth: () => {
      sceneRef.current?.restMouth();
      companionRef.current?.restMouth();
      orbRef.current?.restMouth();
    },
    gesture: (g) => {
      sceneRef.current?.gesture(g);
      companionRef.current?.gesture(g);
      orbRef.current?.gesture(g);
    },
  }), []);

  if (failed) {
    return (
      <div className="cop-avatar3d-wrap companion-on">
        <FinBotAvatar ref={orbRef} mode={mode} mood={mood} accent={accent} />
      </div>
    );
  }

  return (
    <div className={`cop-avatar3d-wrap ${useCompanion ? "companion-on" : ""}`}>
      {(!ready || useCompanion) && (
        <div className="cop-avatar3d-loading companion-loading">
          <FinBotCompanion ref={companionRef} mode={mode} mood={mood} accent={accent} />
        </div>
      )}
      {!useCompanion && (
        <div className={`cop-avatar3d-canvas ${ready ? "on" : ""}`}>
          <Avatar3DScene
            ref={sceneRef}
            mode={mode}
            mood={mood}
            accent={accent}
            onFail={() => setFailed(true)}
            onReady={() => setReady(true)}
            onNoModel={() => setUseCompanion(true)}
          />
        </div>
      )}
    </div>
  );
});

export default FinBotAvatar3D;