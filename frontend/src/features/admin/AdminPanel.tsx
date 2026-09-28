"use client";

/**
 * AdminPanel — administration réservée au directeur.
 *  - CRUD des comptes clients : création (reliée à un code client ERP réel),
 *    édition (nom, téléphone, mot de passe), activation/désactivation ;
 *  - traitement des demandes clients (statut + réponse) ;
 *  - journal d'audit (qui a fait quoi, quand).
 */

import {
  CheckCircle2, ClipboardList, Clock3, KeyRound, Pencil, RefreshCw,
  ScrollText, ShieldCheck, Trash2, UserMinus, UserPlus, Users, XCircle,
} from "lucide-react";
import { STATUS_META, emailFromName } from "./admin.regles";
import { useAdmin } from "./useAdmin";

function fDate(d?: string | null) {
  if (!d) return "—";
  const t = new Date(d);
  return Number.isNaN(t.getTime()) ? "—" : t.toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
}
function fMoney(v: number) {
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(1)} M DT`;
  if (Math.abs(v) >= 1e3) return `${(v / 1e3).toFixed(0)} K DT`;
  return `${v.toFixed(0)} DT`;
}

export default function AdminPanel() {
  const {
    users, erp, requests, auditLog, loading, load, notice,
    mode, setMode, newPoste, setNewPoste, newCode, setNewCode, newEmail, setNewEmail,
    newName, setNewName, newPhone, setNewPhone, newPassword, setNewPassword,
    emailTouched, setEmailTouched, editing, setEditing, editForm, setEditForm,
    draft, setDraft, pickErp, createUser, openEdit, saveEdit, deleteForever,
    toggleActive, resetPassword, setRequestStatus, nNew,
  } = useAdmin();

  return (
    <div style={{ gridColumn: "span 12", display: "grid", gridTemplateColumns: "repeat(12, 1fr)", gap: 14 }}>

      {notice && (
        <div className="chart-card" style={{ gridColumn: "span 12", padding: "10px 16px", color: "#2F5BEA", fontWeight: 600 }}>
          {notice}
        </div>
      )}

      {/* Création de compte */}
      <div className="chart-card" style={{ gridColumn: "span 5" }}>
        <div className="card-header">
          <span className="card-label"><UserPlus size={16} style={{ verticalAlign: "-3px" }} /> Créer un compte</span>
        </div>

        {/* Trois parcours : client déjà facturé (ERP), nouveau client, employé */}
        <div style={{ display: "flex", gap: 6, marginBottom: 10, flexWrap: "wrap" }}>
          <button type="button" className={`admin-mode ${mode === "erp" ? "on" : ""}`}
            onClick={() => { setMode("erp"); setNewCode(""); setNewName(""); setNewEmail(""); setEmailTouched(false); }}>
            Client existant (ERP)
          </button>
          <button type="button" className={`admin-mode ${mode === "nouveau" ? "on" : ""}`}
            onClick={() => { setMode("nouveau"); setNewCode(""); setNewName(""); setNewEmail(""); setEmailTouched(false); }}>
            Nouveau client
          </button>
          <button type="button" className={`admin-mode ${mode === "employe" ? "on" : ""}`}
            onClick={() => { setMode("employe"); setNewCode(""); setNewName(""); setNewEmail(""); setEmailTouched(false); }}>
            Employé
          </button>
        </div>

        <form onSubmit={createUser} style={{ display: "flex", flexDirection: "column", gap: 9 }}>
          {mode === "employe" ? (
            <>
              <select className="mini" value={newPoste} onChange={e => setNewPoste(e.target.value)}>
                <option value="recouvrement">Recouvrement</option>
                <option value="commercial">Commercial</option>
                <option value="logistique">Logistique</option>
                <option value="autre">Autre</option>
              </select>
              <span style={{ fontSize: "0.68rem", color: "var(--text-muted)", marginTop: -4 }}>
                Le métier sert à proposer la bonne personne quand vous confiez une
                tâche. Un employé ne voit que ses tâches, aucune donnée financière.
              </span>
            </>
          ) : mode === "erp" ? (
            <select className="mini" value={newCode} onChange={e => pickErp(e.target.value)} required>
              <option value="" disabled>Choisir un client ERP (code — nom — CA)</option>
              {erp.map(c => (
                <option key={c.code} value={c.code}>
                  {c.code} — {c.nom.slice(0, 34)} — {fMoney(c.ca)}
                </option>
              ))}
            </select>
          ) : (
            <>
              <input className="mini" placeholder="Code client (ex. CE000123)" value={newCode}
                onChange={e => {
                  const v = e.target.value.toUpperCase();
                  setNewCode(v);
                  if (!emailTouched && newName) setNewEmail(emailFromName(newName, v));
                }} maxLength={64} required />
              <span style={{ fontSize: "0.68rem", color: "var(--text-muted)", marginTop: -4 }}>
                Code unique, non encore attribué. Le client n&apos;a pas encore de
                données ERP : son espace se remplira dès la première facture.
              </span>
            </>
          )}
          <input className="mini" placeholder={mode === "employe" ? "Nom de la personne" : "Nom de l'établissement"} value={newName}
            onChange={e => {
              const v = e.target.value;
              setNewName(v);
              // L'adresse suit le nom tant que l'utilisateur ne l'a pas éditée
              if (!emailTouched) setNewEmail(emailFromName(v, newCode));
            }} maxLength={255} />
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

      {/* Modale d'édition complète */}
      {editing && (
        <div className="spotlight-backdrop" onClick={() => setEditing(null)}>
          <div className="spotlight-panel" style={{ maxWidth: 460 }} onClick={e => e.stopPropagation()}>
            <div className="card-header">
              <span className="card-label">Modifier le compte</span>
              <button className="expand-btn" onClick={() => setEditing(null)}><XCircle size={18} /></button>
            </div>
            <form onSubmit={saveEdit} style={{ display: "flex", flexDirection: "column", gap: 10, padding: 16 }}>
              <label style={{ fontSize: "0.74rem", color: "var(--text-muted)" }}>Nom de l&apos;établissement</label>
              <input className="mini" value={editForm.full_name} maxLength={255}
                onChange={e => {
                  const v = e.target.value;
                  setEditForm(f => ({
                    ...f, full_name: v,
                    // l'identifiant suit le nom tant qu'il correspondait à l'ancien
                    email: f.email === emailFromName(editing.full_name || "", editing.client_code || "")
                      ? emailFromName(v, f.client_code) : f.email,
                  }));
                }} />
              <label style={{ fontSize: "0.74rem", color: "var(--text-muted)" }}>Identifiant de connexion</label>
              <input className="mini" type="email" value={editForm.email} required
                onChange={e => setEditForm(f => ({ ...f, email: e.target.value }))} />
              {editing.role === "client" && (
                <>
                  <label style={{ fontSize: "0.74rem", color: "var(--text-muted)" }}>
                    Code client (périmètre de données{editing.in_erp === false ? " — pas encore dans l'ERP" : ""})
                  </label>
                  <input className="mini" value={editForm.client_code} maxLength={64} required
                    onChange={e => setEditForm(f => ({ ...f, client_code: e.target.value.toUpperCase() }))} />
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

      {/* Liste des comptes */}
      <div className="chart-card" style={{ gridColumn: "span 7" }}>
        <div className="card-header">
          <span className="card-label"><Users size={16} style={{ verticalAlign: "-3px" }} /> Comptes ({users.length})</span>
          <button className="icon-button" onClick={load} title="Rafraîchir">
            <RefreshCw size={14} className={loading ? "spin-icon" : ""} />
          </button>
        </div>
        <div className="data-table" style={{ maxHeight: 330, overflowY: "auto" }}>
          <div className="dt-head" style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr 90px 120px 120px" }}>
            <span>Compte</span><span>Code / rôle</span><span>Actif</span><span>Dernière connexion</span><span>Actions</span>
          </div>
          {users.map(u => (
            <div key={u.id} className="dt-row" style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr 90px 120px 120px", opacity: u.is_active ? 1 : 0.55 }}>
              <span className="dt-name" title={u.email}><b>{u.full_name || u.email}</b><br /><em style={{ fontStyle: "normal", fontSize: "0.7rem", color: "var(--text-muted)" }}>{u.email}</em></span>
              <span>
                {u.role === "directeur" ? "👑 directeur"
                  : u.role === "employe" ? `équipe · ${u.poste || "interne"}`
                  : (u.client_code || "—")}
                {u.in_erp === false && (
                  <em title="Nouveau client : aucune facture dans l'entrepôt pour l'instant"
                    style={{ fontStyle: "normal", display: "block", fontSize: "0.66rem", color: "#F59E0B", fontWeight: 700 }}>
                    nouveau (hors ERP)
                  </em>
                )}
              </span>
              <span style={{ color: u.is_active ? "#10B981" : "#EF4444", fontWeight: 700 }}>{u.is_active ? "oui" : "non"}</span>
              <span style={{ fontSize: "0.72rem" }}>{fDate(u.last_login)}</span>
              <span style={{ display: "flex", gap: 6 }}>
                <button className="icon-button" title="Modifier (nom, identifiant, code, téléphone)" onClick={() => openEdit(u)}><Pencil size={13} /></button>
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

      {/* Demandes clients */}
      <div className="chart-card" style={{ gridColumn: "span 12" }}>
        <div className="card-header">
          <span className="card-label">
            <ClipboardList size={16} style={{ verticalAlign: "-3px" }} /> Demandes clients
            {nNew > 0 && <span style={{ marginLeft: 8, background: "rgba(47,91,234,0.12)", color: "#2F5BEA", borderRadius: 999, padding: "2px 9px", fontSize: "0.72rem", fontWeight: 800 }}>{nNew} nouvelle(s)</span>}
          </span>
        </div>
        {!requests.length && <p className="muted-note">Aucune demande client pour l&apos;instant.</p>}
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {requests.map(r => {
            const st = STATUS_META[r.status] || STATUS_META.nouvelle;
            return (
              <div key={r.id} style={{ border: "1px solid rgba(26,35,72,0.10)", borderLeft: `4px solid ${st.color}`, borderRadius: 10, padding: "10px 14px" }}>
                <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                  <b>{r.sujet}</b>
                  <span style={{ fontSize: "0.72rem", color: "var(--text-muted)" }}>
                    {r.client_nom || r.client_code} · {r.type}{r.invoice_ref ? ` · fact. ${r.invoice_ref}` : ""} · {fDate(r.created_at)}
                  </span>
                  <span style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 5, color: st.color, fontWeight: 700, fontSize: "0.76rem" }}>
                    {st.icon} {st.label}
                  </span>
                </div>
                <p style={{ margin: "6px 0 8px", fontSize: "0.82rem" }}>{r.message}</p>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <input className="mini" style={{ flex: 1, minWidth: 220 }}
                    placeholder="Réponse au client…"
                    value={draft[r.id] ?? r.reponse ?? ""}
                    onChange={e => setDraft(p => ({ ...p, [r.id]: e.target.value }))} />
                  <button className="icon-button" title="Marquer en cours" onClick={() => setRequestStatus(r, "en_cours")}><Clock3 size={14} /></button>
                  <button className="icon-button" title="Traiter (envoyer la réponse)" onClick={() => setRequestStatus(r, "traitee")}><CheckCircle2 size={14} /></button>
                  <button className="icon-button" title="Rejeter" onClick={() => setRequestStatus(r, "rejetee")}><XCircle size={14} /></button>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Audit */}
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
