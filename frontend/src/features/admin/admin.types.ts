/**
 * Model — administration : comptes, clients ERP, demandes, journal d'audit.
 */

export interface AdminUser {
  id: number; email: string; full_name: string | null; role: string;
  client_code: string | null; phone: string | null; poste?: string | null; is_active: boolean;
  created_at: string | null; last_login: string | null; in_erp?: boolean | null;
}
export interface ErpClient { code: string; nom: string; ca: number; factures: number }
export interface AdminRequest {
  id: number; type: string; sujet: string; message: string;
  invoice_ref: string | null; status: string; reponse: string | null;
  client_code: string | null; client_nom: string | null;
  created_at: string | null;
}
export interface AuditEntry {
  id: number; email: string | null; action: string; resource: string | null;
  detail: string | null; at: string | null;
}

export interface DonneesAdmin {
  users: AdminUser[]; erp: ErpClient[]; requests: AdminRequest[]; audit: AuditEntry[];
  erreur: string | null;
}

/** Mode du formulaire de création : client déjà facturé (ERP), nouveau client, employé. */
export type ModeCreation = "erp" | "nouveau" | "employe";
