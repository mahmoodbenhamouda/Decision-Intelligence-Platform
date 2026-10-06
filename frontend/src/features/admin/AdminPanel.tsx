"use client";

import {
  AlertTriangle, KeyRound, Pencil, RefreshCw, ScrollText, ShieldCheck, Trash2,
  UserMinus, UserPlus, Users, XCircle,
} from "lucide-react";
import { useAdmin } from "./useAdmin";

function fDate(d?: string | null) {
  if (!d) return "—";
  const t = new Date(d);
  return Number.isNaN(t.getTime()) ? "—" : t.toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
}

const POSTES = (
  <>
    <option value="recouvrement">Recouvrement</option>
    <option value="commercial">Commercial</option>
    <option value="logistique">Logistique</option>
    <option value="autre">Autre</option>
  </>
);

export default function AdminPanel() {
  const {
    users, auditLog, rolesRetires, loading, load, notice,
    mode, setMode, newPoste, setNewPoste, newEmail, setNewEmail,
    newName, changerNom, newPhone, setNewPhone, newPassword, setNewPassword,
    setEmailTouched, editing, setEditing, editForm, setEditForm,
    createUser, openEdit, saveEdit, deleteForever, toggleActive, resetPassword,
    purgerRetires,
  } = useAdmin();

  return (
    <div style={{ gridColumn: "span 12", display: "grid", gridTemplateColumns: "repeat(12, 1fr)", gap: 14 }}>

      {notice && (
        <div className="chart-card" style={{ gridColumn: "span 12", padding: "10px 16px", color: "#2F5BEA", fontWeight: 600 }}>
          {notice}
        </div>
      )}

      {rolesRetires > 0 && (
        <div className="chart-card" style={{
          gridColumn: "span 12", padding: "13px 16px", display: "flex", gap: 12,
          alignItems: "center", flexWrap: "wrap",
          border: "1px solid rgba(236,131,90,0.35)", background: "rgba(236,131,90,0.07)",
        }}>
          <AlertTriangle size={17} style={{ color: "#EC835A", flexShrink: 0 }} />
          <span style={{ fontSize: "0.8rem", lineHeight: 1.5, flex: 1, minWidth: 260 }}>
            <b>{rolesRetires} compte{rolesRetires > 1 ? "s" : ""} subsiste{rolesRetires > 1 ? "nt" : ""} en
            base sous un rôle que la plateforme ne sert plus.</b><br />
            Le portail client a été retiré : la plateforme est destinée au directeur et à
            ses employés. Ces comptes ne peuvent déjà plus se connecter et ne sont plus
            listés ci-dessous. Les effacer supprime la dernière trace de ce rôle — le
            journal d&apos;audit, lui, est conservé.
          </span>
          <button className="login-btn" type="button" onClick={purgerRetires}
            style={{ padding: "8px 14px", whiteSpace: "nowrap" }}>
            <Trash2 size={14} /> Purger {rolesRetires} compte{rolesRetires > 1 ? "s" : ""}
          </button>
        </div>
      )}

      <div className="chart-card" style={{ gridColumn: "span 5" }}>
        <div className="card-header">
          <span className="card-label"><UserPlus size={16} style={{ verticalAlign: "-3px" }} /> Créer un compte</span>
        </div>

        <div style={{ display: "flex", gap: 6, marginBottom: 10, flexWrap: "wrap" }}>
          <button type="button" className={`admin-mode ${mode === "employe" ? "on" : ""}`}
            onClick={() => setMode("employe")}>
            Employé
          </button>
          <button type="button" className={`admin-mode ${mode === "directeur" ? "on" : ""}`}
            onClick={() => setMode("directeur")}>
            Directeur
          </button>
        </div>

        <form onSubmit={createUser} style={{ display: "flex", flexDirection: "column", gap: 9 }}>
          {mode === "employe" ? (
            <>
              <select className="mini" value={newPoste} onChange={e => setNewPoste(e.target.value)}>
                {POSTES}
              </select>
              <span style={{ fontSize: "0.68rem", color: "var(--text-muted)", marginTop: -4 }}>
                Le métier sert à proposer la bonne personne quand vous confiez une
                tâche. Un employé ne voit que ses tâches, aucune donnée financière.
              </span>
            </>
          ) : (
            <span style={{ fontSize: "0.68rem", color: "var(--text-muted)" }}>
              Un directeur voit toutes les analyses et confie les tâches à l&apos;équipe.
            </span>
          )}
          <input className="mini" placeholder="Nom de la personne" value={newName}
            onChange={e => changerNom(e.target.value)} maxLength={255} />
          <input className="mini" type="email" placeholder="Identifiant de connexion" value={newEmail}
            onChange={e => { setEmailTouched(true); setNewEmail(e.target.value); }} required />
          <span style={{ fontSize: "0.68rem", color: "var(--text-muted)", marginTop: -4 }}>
            L&apos;identifiant est dérivé du nom saisi (modifiable).
          </span>
          <input className="mini" placeholder="Téléphone (optionnel)" value={newPhone}
            onChange={e => setNewPhone(e.target.value)} maxLength={40} />
          <input className="mini" type="text" placeholder="Mot de passe initial (≥10, Maj+min+chiffre)"
            value={newPassword} onChange={e => setNewPassword(e.target.value)} required />
          <button className="login-btn" type="submit" style={{ padding: 10 }}>
            <ShieldCheck size={14} /> Créer le compte
          </button>
        </form>
      </div>

      {editing && (
        <div className="spotlight-backdrop" onClick={() => setEditing(null)}>
          <div className="spotlight-panel" style={{ maxWidth: 460 }} onClick={e => e.stopPropagation()}>
            <div className="card-header">
              <span className="card-label">Modifier le compte</span>
              <button className="expand-btn" onClick={() => setEditing(null)}><XCircle size={18} /></button>
            </div>
            <form onSubmit={saveEdit} style={{ display: "flex", flexDirection: "column", gap: 10, padding: 16 }}>
              <label style={{ fontSize: "0.74rem", color: "var(--text-muted)" }}>Nom</label>
              <input className="mini" value={editForm.full_name} maxLength={255}
                onChange={e => setEditForm(f => ({ ...f, full_name: e.target.value }))} />
              <label style={{ fontSize: "0.74rem", color: "var(--text-muted)" }}>Identifiant de connexion</label>
              <input className="mini" type="email" value={editForm.email} required
                onChange={e => setEditForm(f => ({ ...f, email: e.target.value }))} />
              {editing.role === "employe" && (
                <>
                  <label style={{ fontSize: "0.74rem", color: "var(--text-muted)" }}>Métier</label>
                  <select className="mini" value={editForm.poste}
                    onChange={e => setEditForm(f => ({ ...f, poste: e.target.value }))}>
                    {POSTES}
                  </select>
                </>
              )}
              <label style={{ fontSize: "0.74rem", color: "var(--text-muted)" }}>Téléphone</label>
              <input className="mini" value={editForm.phone} maxLength={40}
                onChange={e => setEditForm(f => ({ ...f, phone: e.target.value }))} />
              <button className="login-btn" type="submit" style={{ padding: 10, marginTop: 4 }}>
                <ShieldCheck size={14} /> Enregistrer en base
              </button>
            </form>
          </div>
        </div>
      )}

      <div className="chart-card" style={{ gridColumn: "span 7" }}>
        <div className="card-header">
          <span className="card-label"><Users size={16} style={{ verticalAlign: "-3px" }} /> Comptes ({users.length})</span>
          <button className="icon-button" onClick={load} title="Rafraîchir">
            <RefreshCw size={14} className={loading ? "spin-icon" : ""} />
          </button>
        </div>
        <div className="data-table" style={{ maxHeight: 330, overflowY: "auto" }}>
          <div className="dt-head" style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr 90px 120px 120px" }}>
            <span>Compte</span><span>Rôle</span><span>Actif</span><span>Dernière connexion</span><span>Actions</span>
          </div>
          {users.map(u => (
            <div key={u.id} className="dt-row" style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr 90px 120px 120px", opacity: u.is_active ? 1 : 0.55 }}>
              <span className="dt-name" title={u.email}><b>{u.full_name || u.email}</b><br /><em style={{ fontStyle: "normal", fontSize: "0.7rem", color: "var(--text-muted)" }}>{u.email}</em></span>
              <span>
                {u.role === "directeur" ? "👑 directeur" : `équipe · ${u.poste || "interne"}`}
              </span>
              <span style={{ color: u.is_active ? "#10B981" : "#EF4444", fontWeight: 700 }}>{u.is_active ? "oui" : "non"}</span>
              <span style={{ fontSize: "0.72rem" }}>{fDate(u.last_login)}</span>
              <span style={{ display: "flex", gap: 6 }}>
                <button className="icon-button" title="Modifier (nom, identifiant, métier, téléphone)" onClick={() => openEdit(u)}><Pencil size={13} /></button>
                <button className="icon-button" title="Réinitialiser le mot de passe" onClick={() => resetPassword(u)}><KeyRound size={13} /></button>
                {u.role !== "directeur" && (
                  <>
                    <button className="icon-button" title={u.is_active ? "Désactiver (réversible)" : "Réactiver"} onClick={() => toggleActive(u)}>
                      <UserMinus size={13} />
                    </button>
                    <button className="icon-button danger" title="Supprimer définitivement (irréversible)" onClick={() => deleteForever(u)}>
                      <Trash2 size={13} />
                    </button>
                  </>
                )}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div className="chart-card" style={{ gridColumn: "span 12" }}>
        <div className="card-header">
          <span className="card-label"><ScrollText size={16} style={{ verticalAlign: "-3px" }} /> Journal d&apos;audit (60 dernières entrées)</span>
        </div>
        <div className="data-table" style={{ maxHeight: 260, overflowY: "auto" }}>
          <div className="dt-head" style={{ display: "grid", gridTemplateColumns: "140px 1fr 170px 1fr" }}>
            <span>Quand</span><span>Qui</span><span>Action</span><span>Détail</span>
          </div>
          {auditLog.map(a => (
            <div key={a.id} className="dt-row" style={{ display: "grid", gridTemplateColumns: "140px 1fr 170px 1fr", fontSize: "0.76rem" }}>
              <span>{fDate(a.at)}</span>
              <span className="dt-name">{a.email || "—"}</span>
              <span>{a.action}</span>
              <span style={{ color: "var(--text-muted)" }}>{a.resource || ""} {a.detail || ""}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
