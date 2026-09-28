"use client";

/**
 * EcranConnexion — écran de connexion — plateforme d'intelligence décisionnelle Overlyne.
 *
 * Deux moitiés, deux rôles :
 *   · à gauche, la MARQUE — le logo, une phrase, trois points courts. C'est le
 *     premier écran que voit un jury ou un client : il doit être tenu ;
 *   · à droite, le FORMULAIRE — posé dans une carte, pas flottant au milieu
 *     d'une page blanche.
 *
 * Ce qui bouge à l'écran répond à quelque chose de réel — jamais de l'animation
 * pour de l'animation :
 *   · les halos suivent le pointeur (repère de profondeur) ;
 *   · les trois points défilent lentement, pour qu'aucun ne soit ignoré ;
 *   · la pastille d'état interroge vraiment `/api/health` : si le serveur est
 *     arrêté, l'utilisateur le sait AVANT de taper son mot de passe.
 *
 * Aucun identifiant de démonstration n'est affiché : une application présentée
 * comme réelle ne montre pas ses mots de passe à l'écran.
 *
 * La logique d'authentification n'a pas changé : JWT posé en cookie httpOnly
 * par l'API, redirection vers le tableau de bord. Le contenu reste filtré côté
 * serveur — l'interface ne fait que s'adapter au rôle.
 */

import {
  Eye, EyeOff, Lock, LogIn, Mail, ShieldAlert, ShieldCheck, Target, TrendingUp,
} from "lucide-react";
import { useConnexion } from "./useConnexion";

/**
 * Trois points, une ligne chacun. Au-delà, personne ne lit.
 *
 * Ils s'adressent à celui qui se connecte — client comme directeur — et
 * parlent de ce qu'il y gagne, jamais du fonctionnement interne : « vos
 * chiffres », et non « neuf ans de factures consolidées ».
 */
const POINTS = [
  { icone: <TrendingUp size={16} />, texte: "Vos chiffres, vérifiés à la facture près" },
  { icone: <Target size={16} />, texte: "Vos priorités, prêtes dès la connexion" },
  { icone: <ShieldCheck size={16} />, texte: "Vos données, strictement confidentielles" },
];

export default function EcranConnexion() {
  const {
    email, setEmail, password, setPassword, visible, setVisible, majuscules, setMajuscules,
    error, loading, actif, setActif, etat, marque, suivre, submit, pret, dejaConnecte,
  } = useConnexion(POINTS.length);

  if (dejaConnecte) return null;

  return (
    <div className="auth">
      {/* ── Panneau de marque ────────────────────────────────────────────── */}
      <aside className="auth-marque" ref={marque} onMouseMove={suivre}>
        <div className="auth-grille" />
        <div className="auth-halo auth-halo-1" />
        <div className="auth-halo auth-halo-2" />

        {/* Le logo est détouré (fond transparent) et servi en blanc : sur ce
            dégradé, la version en couleurs ne se lirait pas. */}
        <img src="/overlyne-blanc.png" alt="Overlyne" className="auth-logo" />

        <div className="auth-marque-corps">
          <h1>
            Vos factures savent déjà<br />ce qu&apos;il faut décider.
          </h1>

          <ul className="auth-points">
            {POINTS.map((p, i) => (
              <li key={p.texte}
                  className={`auth-point${i === actif ? " actif" : ""}`}
                  onMouseEnter={() => setActif(i)}>
                <span className="auth-point-icone">{p.icone}</span>
                {p.texte}
              </li>
            ))}
          </ul>
        </div>

        <span className="auth-marque-pied">
          Distribution de matériel de diagnostic médical · Tunisie
        </span>
      </aside>

      {/* ── Formulaire ───────────────────────────────────────────────────── */}
      <main className="auth-panneau">
        <form className="auth-carte" onSubmit={submit}>
          {/* Sur petit écran, le panneau de marque disparaît : le logo revient
              ici, en couleurs, sur fond blanc. */}
          <img src="/overlyne.png" alt="Overlyne" className="auth-logo-mobile" />

          <div className="auth-entete">
            <h2>Connexion</h2>
            <span className={`auth-etat auth-etat-${etat}`}
                  title={etat === "en_ligne" ? "Le serveur de l'application répond"
                       : etat === "hors_ligne" ? "Le serveur de l'application ne répond pas"
                       : "Vérification en cours"}>
              <i />
              {etat === "en_ligne" ? "Service en ligne"
                : etat === "hors_ligne" ? "Service injoignable" : "Vérification…"}
            </span>
          </div>

          <label className="auth-champ">
            <span className="auth-label">Identifiant</span>
            <span className="auth-saisie">
              <Mail size={16} />
              <input
                type="email" value={email} autoComplete="username" required autoFocus
                placeholder="nom-de-votre-etablissement@overlyne.tn"
                onChange={e => setEmail(e.target.value)}
              />
            </span>
          </label>

          <label className="auth-champ">
            <span className="auth-label">Mot de passe</span>
            <span className="auth-saisie">
              <Lock size={16} />
              <input
                type={visible ? "text" : "password"} value={password}
                autoComplete="current-password" required placeholder="••••••••••"
                onChange={e => setPassword(e.target.value)}
                onKeyUp={e => setMajuscules(e.getModifierState?.("CapsLock") ?? false)}
              />
              <button type="button" className="auth-oeil" onClick={() => setVisible(v => !v)}
                title={visible ? "Masquer le mot de passe" : "Afficher le mot de passe"}
                aria-label={visible ? "Masquer le mot de passe" : "Afficher le mot de passe"}>
                {visible ? <EyeOff size={15} /> : <Eye size={15} />}
              </button>
            </span>
            {/* Cause n°1 des échecs de connexion, et invisible sans ce rappel. */}
            {majuscules && <span className="auth-indice">Majuscules verrouillées</span>}
          </label>

          {error && (
            <p className="auth-erreur" role="alert" aria-live="polite">
              <ShieldAlert size={15} /> {error}
            </p>
          )}

          <button className={`auth-bouton${pret ? " pret" : ""}`} type="submit"
                  disabled={loading || !pret}>
            {loading ? <span className="auth-spinner" /> : <LogIn size={17} />}
            {loading ? "Connexion…" : "Se connecter"}
          </button>
        </form>

        <p className="auth-pied">
          Un problème de connexion ? Contactez votre interlocuteur Overlyne.
        </p>
      </main>
    </div>
  );
}
