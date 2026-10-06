"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { visemeForChar, type AvatarHandle } from "@/shared/avatar/FinBotAvatar";
import { pickFrenchVoice } from "./voix";

export function useSyntheseVocale(voiceOn: boolean) {
  const [speaking, setSpeaking] = useState(false);
  const avatarRef = useRef<AvatarHandle>(null);
  const lipSyncRaf = useRef<number | null>(null);

  useEffect(() => {
    try {
      window.speechSynthesis?.getVoices();
      if (window.speechSynthesis) window.speechSynthesis.onvoiceschanged = () => { };
    } catch { }
  }, []);

  useEffect(() => () => {
    try { window.speechSynthesis?.cancel(); } catch { }
    if (lipSyncRaf.current != null) cancelAnimationFrame(lipSyncRaf.current);
  }, []);

  const stopLipSync = useCallback(() => {
    if (lipSyncRaf.current != null) {
      cancelAnimationFrame(lipSyncRaf.current);
      lipSyncRaf.current = null;
    }
    avatarRef.current?.restMouth();
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("finbot:avatar-rest-mouth"));
    }
  }, []);

  const speak = useCallback((text: string) => {
    if (typeof window === "undefined") return;
    try {
      if (window.speechSynthesis) window.speechSynthesis.cancel();
      stopLipSync();

      const clean = text
        .replace(/#{1,6}\s/g, "")
        .replace(/\*\*/g, "")
        .replace(/[_`>]/g, " ")
        .replace(/[-•]\s/g, "")
        .replace(/\n+/g, ". ")
        .replace(/\s+/g, " ")
        .slice(0, 600);

      const rate = 1.0;
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
          const v = visemeForChar(chars[idx]);
          avatarRef.current?.setViseme(v);
          window.dispatchEvent(new CustomEvent("finbot:avatar-viseme", { detail: v }));
          idx++;
        }
        if (idx < chars.length) {
          lipSyncRaf.current = requestAnimationFrame(step);
        } else {
          avatarRef.current?.restMouth();
          window.dispatchEvent(new CustomEvent("finbot:avatar-rest-mouth"));
          setSpeaking(false);
          lipSyncRaf.current = null;
        }
      };

      if (voiceOn && window.speechSynthesis) {
        const u = new SpeechSynthesisUtterance(clean);
        u.lang = "fr-FR"; u.rate = rate; u.pitch = 1.12;
        const voice = pickFrenchVoice();
        if (voice) u.voice = voice;

        u.onstart = () => {
          setSpeaking(true);
          last = 0; acc = 0; idx = 0;
          lipSyncRaf.current = requestAnimationFrame(step);
        };
        u.onboundary = (e) => {
          if (typeof e.charIndex === "number") idx = Math.max(idx, e.charIndex);
        };
        u.onend = () => { setSpeaking(false); stopLipSync(); };
        u.onerror = () => { setSpeaking(false); stopLipSync(); };

        window.speechSynthesis.speak(u);
      } else {
        // Si le son est coupé, exécuter la synchro labiale visuelle uniquement pendant 3 secondes
        setSpeaking(true);
        last = 0; acc = 0; idx = 0;
        lipSyncRaf.current = requestAnimationFrame(step);
      }
    } catch { setSpeaking(false); stopLipSync(); }
  }, [voiceOn, stopLipSync]);

  return { speaking, setSpeaking, speak, stopLipSync, avatarRef };
}
