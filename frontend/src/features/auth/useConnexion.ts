"use client";

import { useEffect, useRef, useState } from "react";
import { saveSession } from "@/core/auth/session";
import { useSession } from "@/core/auth/useSession";
import { seConnecter, serveurEnLigne } from "./auth.service";

export type EtatServeur = "attente" | "en_ligne" | "hors_ligne";

export function useConnexion(nPoints: number) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [visible, setVisible] = useState(false);
  const [majuscules, setMajuscules] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [actif, setActif] = useState(0);
  const [etat, setEtat] = useState<EtatServeur>("attente");
  const marque = useRef<HTMLElement | null>(null);
  const dejaConnecte = useSession()?.loggedIn === true;

  useEffect(() => {
    if (dejaConnecte) window.location.href = "/";
  }, [dejaConnecte]);

  useEffect(() => {
    const t = setInterval(() => setActif(i => (i + 1) % nPoints), 3400);
    return () => clearInterval(t);
  }, [nPoints]);

  useEffect(() => {
    const stop = new AbortController();
    const delai = setTimeout(() => stop.abort(), 6000);
    serveurEnLigne(stop.signal)
      .then(ok => setEtat(ok ? "en_ligne" : "hors_ligne"))
      .catch(() => setEtat("hors_ligne"))
      .finally(() => clearTimeout(delai));
    return () => { clearTimeout(delai); stop.abort(); };
  }, []);

  const suivre = (e: React.MouseEvent<HTMLElement>) => {
    const el = marque.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    el.style.setProperty("--mx", String((e.clientX - r.left) / r.width - 0.5));
    el.style.setProperty("--my", String((e.clientY - r.top) / r.height - 0.5));
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password || loading) return;
    setLoading(true);
    setError(null);
    try {
      const res = await seConnecter(email, password);
      if (!res.ok) {
        setError(res.status === 429
          ? "Trop de tentatives. Réessayez dans quelques minutes."
          : res.data.detail || "Identifiants invalides.");
        return;
      }
      saveSession(res.data as { role: string; email: string });
      window.location.href = "/";
    } catch {

      setError("Service injoignable. Vérifiez que le serveur de l'application est démarré.");
      setEtat("hors_ligne");
    } finally {
      setLoading(false);
    }
  };

  const pret = email.length > 0 && password.length > 0;

  return {
    email, setEmail, password, setPassword, visible, setVisible, majuscules, setMajuscules,
    error, loading, actif, setActif, etat, marque, suivre, submit, pret, dejaConnecte,
  };
}
