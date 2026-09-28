/**
 * Formatage commun à plusieurs écrans.
 *
 * Les montants gardent un formateur par écran (précision différente selon ce
 * qu'on y lit) ; seuls les formats strictement identiques sont réunis ici.
 */

/** Date courte française (jj/mm/aaaa), « — » si absente ou invalide. */
export function dateCourte(d?: string | null): string {
  if (!d) return "—";
  const t = new Date(d);
  return Number.isNaN(t.getTime()) ? "—" : t.toLocaleDateString("fr-FR");
}

/** Date ISO (aaaa-mm-jj) dans `n` jours — valeur par défaut des échéances. */
export function dansNJours(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}
