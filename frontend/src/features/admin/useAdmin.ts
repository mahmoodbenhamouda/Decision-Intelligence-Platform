"use client";

import { useState } from "react";
import { useRequete } from "@/core/hooks/useRequete";
import { emailFromName } from "./admin.regles";
import { chargerAdmin, creerCompte, modifierCompte, purgerRolesRetires, supprimerCompte } from "./admin.service";
import type { AdminUser, ModeCreation } from "./admin.types";

export function useAdmin() {
  const r = useRequete(chargerAdmin);
  const users = r.donnees?.users ?? [];
  const auditLog = r.donnees?.audit ?? [];
  const rolesRetires = r.donnees?.rolesRetires ?? 0;
  const load = r.recharger;

  const [message, setNotice] = useState<string | null>(null);
  const notice = message ?? r.donnees?.erreur ?? null;
  const flash = (m: string) => { setNotice(m); window.setTimeout(() => setNotice(null), 5000); };

  const [mode, setMode] = useState<ModeCreation>("employe");
  const [newPoste, setNewPoste] = useState("recouvrement");
  const [newEmail, setNewEmail] = useState("");
  const [newName, setNewName] = useState("");
  const [newPhone, setNewPhone] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [emailTouched, setEmailTouched] = useState(false);

  const [editing, setEditing] = useState<AdminUser | null>(null);
  const [editForm, setEditForm] = useState({ full_name: "", email: "", phone: "", poste: "" });

  const changerNom = (v: string) => {
    setNewName(v);
    if (!emailTouched) setNewEmail(emailFromName(v));
  };

  const createUser = async (e: React.FormEvent) => {
    e.preventDefault();
    const estEmploye = mode === "employe";
    const res = await creerCompte({
      email: newEmail.trim(), password: newPassword, full_name: newName.trim() || null,
      role: mode, phone: newPhone.trim() || null,
      poste: estEmploye ? newPoste : null,
    });
    const d = res.data;
    if (res.ok) {
      flash(estEmploye
        ? `Compte employé créé : ${d.email} — vous pouvez lui confier des tâches.`
        : `Compte directeur créé : ${d.email}`);
      setNewEmail(""); setNewName(""); setNewPhone(""); setNewPassword("");
      setEmailTouched(false);
      load();
    } else flash(`Erreur : ${d.detail || res.status}`);
  };

  const openEdit = (u: AdminUser) => {
    setEditing(u);
    setEditForm({ full_name: u.full_name || "", email: u.email, phone: u.phone || "", poste: u.poste || "" });
  };

  const saveEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editing) return;
    const payload: Record<string, unknown> = {
      full_name: editForm.full_name.trim() || null,
      phone: editForm.phone.trim() || null,
    };
    if (editing.role === "employe") payload.poste = editForm.poste || null;
    if (editForm.email.trim().toLowerCase() !== editing.email.toLowerCase())
      payload.email = editForm.email.trim().toLowerCase();
    const res = await modifierCompte(editing.id, payload);
    flash(res.ok ? "Compte mis à jour en base." : `Erreur : ${res.data.detail || res.status}`);
    if (res.ok) setEditing(null);
    load();
  };

  const deleteForever = async (u: AdminUser) => {
    if (!window.confirm(
      `SUPPRESSION DÉFINITIVE de ${u.full_name || u.email}\n\n` +
      `• Le compte sera retiré de la base de données (irréversible)\n` +
      `• Ses tâches ouvertes repasseront « à affecter »\n` +
      `• Le journal d'audit sera conservé (anonymisé)\n\n` +
      `Astuce : la désactivation (icône ⊖) suffit si vous voulez juste bloquer l'accès.\n\n` +
      `Continuer ?`)) return;
    const typed = window.prompt(
      `Confirmation finale — tapez l'identifiant du compte à supprimer :\n${u.email}`);
    if ((typed || "").trim().toLowerCase() !== u.email.toLowerCase()) {
      flash("Suppression annulée (identifiant non confirmé).");
      return;
    }
    const res = await supprimerCompte(u.id, true);
    const d = res.data;
    flash(res.ok
      ? `Compte ${d.email} supprimé définitivement (${d.taches_a_reaffecter} tâche(s) à réaffecter, ${d.audit_anonymise} entrée(s) d'audit conservée(s)).`
      : `Erreur : ${d.detail || res.status}`);
    load();
  };

  /** Le rôle « client » a été retiré : ses comptes n'ont plus lieu d'être en base. */
  const purgerRetires = async () => {
    if (!window.confirm(
      `SUPPRESSION DÉFINITIVE de ${rolesRetires} compte(s)\n\n` +
      `La plateforme ne sert plus que le directeur et ses employés. Ces comptes ont\n` +
      `été créés sous un rôle retiré et ne peuvent déjà plus se connecter.\n\n` +
      `• Ils seront effacés de la base de données (irréversible)\n` +
      `• Leurs tâches ouvertes repasseront « à affecter »\n` +
      `• Le journal d'audit sera conservé (anonymisé)\n\n` +
      `Aucun compte directeur ou employé n'est concerné.\n\nContinuer ?`)) return;
    const res = await purgerRolesRetires();
    const d = res.data as { n_supprimes?: number; emails?: string[]; detail?: string };
    flash(res.ok
      ? `${d.n_supprimes ?? 0} compte(s) de rôle retiré supprimé(s)${
          d.emails?.length ? ` : ${d.emails.join(", ")}` : ""}.`
      : `Erreur : ${d.detail || res.status}`);
    load();
  };

  const toggleActive = async (u: AdminUser) => {
    const res = u.is_active
      ? await supprimerCompte(u.id)
      : await modifierCompte(u.id, { is_active: true });
    flash(res.ok ? `${u.email} ${u.is_active ? "désactivé" : "réactivé"}.` : `Erreur : ${res.data.detail || res.status}`);
    load();
  };

  const resetPassword = async (u: AdminUser) => {
    const pwd = window.prompt(
      `Nouveau mot de passe pour ${u.email}\n(≥10 caractères, majuscule + minuscule + chiffre) :`);
    if (!pwd) return;
    const res = await modifierCompte(u.id, { password: pwd });
    flash(res.ok ? "Mot de passe réinitialisé." : `Erreur : ${res.data.detail || res.status}`);
  };

  return {
    users, auditLog, rolesRetires, loading: r.chargement, load, notice,
    mode, setMode, newPoste, setNewPoste, newEmail, setNewEmail,
    newName, changerNom, newPhone, setNewPhone, newPassword, setNewPassword,
    setEmailTouched, editing, setEditing, editForm, setEditForm,
    createUser, openEdit, saveEdit, deleteForever, toggleActive, resetPassword,
    purgerRetires,
  };
}
