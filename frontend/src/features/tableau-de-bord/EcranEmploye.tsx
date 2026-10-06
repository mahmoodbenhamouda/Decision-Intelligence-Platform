"use client";

import { LogOut, User as UserIcon } from "lucide-react";
import type { SessionInfo } from "@/core/auth/session";
import { seDeconnecter } from "@/features/auth/auth.service";
import MesCommandes from "@/features/stock/MesCommandes";
import TachesPanel from "@/features/taches/TachesPanel";

export default function EcranEmploye({ session }: { session: SessionInfo | null }) {
  return (
    <div className="cockpit">
      <nav className="top-navbar">
        <div className="brand-block">
          <img src="/overlyne.png" alt="Overlyne" className="brand-logo" />
          <div><h2>Mes actions</h2><p>Ce qui vous est confié aujourd&apos;hui</p></div>
        </div>
        <div className="nav-actions">
          <span className="role-badge role-dir" title={session?.email || ""}>
            <UserIcon size={13} />{session?.fullName || "Employé"}
          </span>
          <button className="icon-button" onClick={() => void seDeconnecter()} title="Se déconnecter"><LogOut size={17} /></button>
        </div>
      </nav>
      <main className="cockpit-main">
        <section className="view-area">
          <div className="view-grid">
            {/* Les commandes validées par la direction arrivent ici : c'est
                l'employé qui les passe et qui saisit la réception. */}
            <MesCommandes />
            <TachesPanel role="employe" />
          </div>
        </section>
      </main>
    </div>
  );
}
