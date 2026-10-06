
export function fMoney(v: number | null | undefined) {
  if (v == null || Number.isNaN(v)) return "N/A";
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(2)} M DT`;
  if (Math.abs(v) >= 1e3) return `${(v / 1e3).toFixed(1)} K DT`;
  return `${v.toFixed(0)} DT`;
}
export function fInt(v: number | null | undefined) { return v == null || Number.isNaN(v) ? "N/A" : v.toLocaleString("fr-FR"); }
export function fAxis(v: number) { return Math.abs(v) >= 1e6 ? `${(v / 1e6).toFixed(0)}M` : `${(v / 1e3).toFixed(0)}k`; }
export function fDate(d?: string) { if (!d) return ""; const t = new Date(d); return Number.isNaN(t.getTime()) ? "" : t.toLocaleDateString("fr-FR", { day: "2-digit", month: "short", year: "numeric" }); }
