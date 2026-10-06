
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
