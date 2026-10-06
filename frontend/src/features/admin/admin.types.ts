
export interface AdminUser {
  id: number; email: string; full_name: string | null; role: string;
  phone: string | null; poste?: string | null; is_active: boolean;
  created_at: string | null; last_login: string | null;
}
export interface AuditEntry {
  id: number; email: string | null; action: string; resource: string | null;
  detail: string | null; at: string | null;
}

export interface DonneesAdmin {
  users: AdminUser[]; audit: AuditEntry[];
  /** Comptes subsistant en base sous un rôle que la plateforme ne sert plus. */
  rolesRetires: number;
  erreur: string | null;
}

/** Deux rôles : le directeur décide, l'employé exécute les tâches confiées. */
export type ModeCreation = "employe" | "directeur";
