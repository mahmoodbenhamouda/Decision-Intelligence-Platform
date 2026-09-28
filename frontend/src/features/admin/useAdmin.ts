"use client";

/**
 * ViewModel — administration réservée au directeur.
 *
 * Porte l'état des trois blocs (création de compte, liste des comptes avec
 * édition, traitement des demandes) et toutes les actions. Chaque action
 * affiche un message cinq secondes puis recharge les listes.
 */
import { useState } from "react";
import { useRequete } from "@/core/hooks/useRequete";
import { STATUS_META, emailFromName } from "./admin.regles";
import {
  chargerAdmin, creerCompte, modifierCompte, supprimerCompte, traiterDemande,
} from "./admin.service";
import type { AdminRequest, AdminUser, ModeCreation } from "./admin.types";

export function useAdmin() {
  const r = useRequete(chargerAdmin);
  const users = r.donnees?.users ?? [];
  const erp = r.donnees?.erp ?? [];
  const requests = r.donnees?.requests ?? [];
  const auditLog = r.donnees?.audit ?? [];
  const load = r.recharger;

  const [message, setNotice] = useState<string | null>(null);
  const notice = message ?? r.donnees?.erreur ?? null;
  const flash = (m: string) => { setNotice(m); window.setTimeout(() => setNotice(null), 5000); };

  // Formulaire création — trois parcours : client déjà facturé (ERP), nouveau
  // client, ou membre de l'équipe interne à qui confier des tâches.
  const [mode, setMode] = useState<ModeCreation>("erp");
  const [newPoste, setNewPoste] = useState("recouvrement");
  const [newCode, setNewCode] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [newName, setNewName] = useState("");
  const [newPhone, setNewPhone] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [emailTouched, setEmailTouched] = useState(false);

  // Modale d'édition
  const [editing, setEditing] = useState<AdminUser | null>(null);
  const [editForm, setEditForm] = useState({ full_name: "", email: "", client_code: "", phone: "" });

  // Réponses en cours d'édition (demandes)
  const [draft, setDraft] = useState<Record<number, string>>({});

  const pickErp = (code: string) => {
    setNewCode(code);
    const c = erp.find(x => x.code === code);
    if (c) {
      setNewName(c.nom);
      setNewEmail(emailFromName(c.nom, code));   // proposition alignée sur le nom
    }
  };

  const createUser = async (e: React.FormEvent) => {
    e.preventDefault();
    // Un employé n'a pas de code client : son périmètre, ce sont ses tâches.
    const estEmploye = mode === "employe";
    const res = await creerCompte({
      email: newEmail.trim(), password: newPassword, full_name: newName.trim() || null,
      role: estEmploye ? "employe" : "client",
      client_code: estEmploye ? null : newCode.trim(),
      phone: newPhone.trim() || null,
      poste: estEmploye ? newPoste : null,
    });
    const d = res.data;
    if (res.ok) {
      flash(estEmploye
        ? `Compte employé créé : ${d.email} — vous pouvez lui confier des tâches.`
        : `Compte créé et enregistré en base : ${d.email}`
          + (d.in_erp === false ? " (nouveau client — aucune donnée ERP pour l'instant)" : ""));
      setNewCode(""); setNewEmail(""); setNewName(""); setNewPhone(""); setNewPassword("");
      setEmailTouched(false);
      load();
    } else flash(`Erreur : ${d.detail || res.status}`);
  };

  /* ── Édition complète via modale ──────────────────────────────────────── */
  const openEdit = (u: AdminUser) => {
    setEditing(u);
    setEditForm({
      full_name: u.full_name || "", email: u.email,
      client_code: u.client_code || "", phone: u.phone || "",
    });
  };

  const saveEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editing) return;
    const payload: Record<string, unknown> = {
      full_name: editForm.full_name.trim() || null,
      phone: editForm.phone.trim() || null,
    };
    if (editForm.email.trim().toLowerCase() !== editing.email.toLowerCase())
      payload.email = editForm.email.trim().toLowerCase();
    if (editing.role === "client" && editForm.client_code.trim() !== (editing.client_code || ""))
      payload.client_code = editForm.client_code.trim();
    const res = await modifierCompte(editing.id, payload);
    flash(res.ok ? "Compte mis à jour en base." : `Erreur : ${res.data.detail || res.status}`);
    if (res.ok) setEditing(null);
    load();
  };

  /** Suppression DÉFINITIVE : double confirmation, dont la saisie de l'email. */
  const deleteForever = async (u: AdminUser) => {
    if (!window.confirm(
      `SUPPRESSION DÉFINITIVE de ${u.full_name || u.email}\n\n` +
      `• Le compte sera retiré de la base de données (irréversible)\n` +
      `• Ses demandes seront supprimées\n` +
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
      ? `Compte ${d.email} supprimé définitivement (${d.demandes_supprimees} demande(s) supprimée(s), ${d.audit_anonymise} entrée(s) d'audit conservée(s)).`
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

  /* ── Traitement des demandes ──────────────────────────────────────────── */
  const setRequestStatus = async (req: AdminRequest, status: string) => {
    const ok = await traiterDemande(req.id, status, draft[req.id] ?? req.reponse ?? null);
    flash(ok ? `Demande #${req.id} → ${STATUS_META[status]?.label || status}` : "Erreur de traitement.");
    load();
  };

  const nNew = requests.filter(x => x.status === "nouvelle").length;

  return {
    users, erp, requests, auditLog, loading: r.chargement, load, notice,
    mode, setMode, newPoste, setNewPoste, newCode, setNewCode, newEmail, setNewEmail,
    newName, setNewName, newPhone, setNewPhone, newPassword, setNewPassword,
    emailTouched, setEmailTouched, editing, setEditing, editForm, setEditForm,
    draft, setDraft, pickErp, createUser, openEdit, saveEdit, deleteForever,
    toggleActive, resetPassword, setRequestStatus, nNew,
  };
}
