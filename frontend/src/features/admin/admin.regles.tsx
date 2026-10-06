
/** Identifiant de connexion proposé à partir du nom de la personne (modifiable). */
export function emailFromName(nom: string): string {
  let s = (nom || "").trim().toLowerCase();
  s = s.normalize("NFKD").replace(/[̀-ͯ]/g, "");
  s = s.replace(/['’]/g, " ");
  s = s.replace(/[^a-z0-9]+/g, ".").replace(/^\.+|\.+$/g, "").replace(/\.{2,}/g, ".");
  if (s.length > 40) s = s.slice(0, 40).replace(/\.[^.]*$/, "");
  return s ? `${s}@overlyne.tn` : "";
}
