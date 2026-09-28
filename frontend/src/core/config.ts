/**
 * Configuration de l'application.
 *
 * « localhost » (et non 127.0.0.1) : même site que le frontend → le cookie
 * httpOnly SameSite=Lax portant le JWT est bien envoyé par le navigateur.
 */
export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:9000";

/** Message affiché quand l'API ne répond pas : l'adresse réelle, pas un port
 *  écrit en dur (9000 en développement, 8000 sous Docker). */
export const API_INJOIGNABLE = `API injoignable (${API_URL}).`;
