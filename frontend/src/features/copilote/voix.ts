/**
 * Choix de la voix de synthèse (API Web Speech du navigateur).
 */

/* ── Sélection de la meilleure voix française disponible ──────────────────
 * Priorité aux voix NEURONALES du système (Microsoft "…Online (Natural)",
 * Google, Apple Siri/Amélie/Thomas), puis n'importe quelle voix fr-*.
 * Repli implicite : voix par défaut du navigateur. */
const PREFERRED_FR_VOICES = [
  /natural/i, /neural/i, /denise/i, /vivienne/i, /henri/i,
  /google.*fran/i, /am[ée]lie/i, /thomas/i, /audrey/i, /siri/i,
];

export function pickFrenchVoice(): SpeechSynthesisVoice | null {
  try {
    const voices = window.speechSynthesis?.getVoices() || [];
    const fr = voices.filter(v => v.lang?.toLowerCase().startsWith("fr"));
    if (fr.length === 0) return null;
    for (const rx of PREFERRED_FR_VOICES) {
      const hit = fr.find(v => rx.test(v.name));
      if (hit) return hit;
    }
    return fr[0];
  } catch { return null; }
}
