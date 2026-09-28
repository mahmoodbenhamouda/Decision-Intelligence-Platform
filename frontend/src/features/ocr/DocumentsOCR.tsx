"use client";

/**
 * DocumentsOCR — onglet « Documents & OCR ».
 *
 * Trois usages du service OCR transversal :
 *  1. FACTURE : scan → champs structurés (n°, dates, HT/TVA/TTC, tiers) +
 *     RAPPROCHEMENT automatique avec l'entrepôt ERP (retrouvée / écart / doublon).
 *  2. TEXTE : extraction brute avec indicateur de qualité de lecture.
 *  3. BASE DOCUMENTAIRE (directeur) : le document océrisé est indexé dans le
 *     RAG et devient interrogeable par le copilote via le préfixe « doc: ».
 */

import {
  AlertTriangle, CheckCircle2, FileScan, FileText, Library, Loader2,
  Save, ScanLine, ShieldAlert, Upload, Wallet, XCircle,
} from "lucide-react";
import { CHAMPS, SOURCE_ECHEANCE, normSaisie, versSaisie } from "./ocr.regles";
import type { Mode, Sens } from "./ocr.types";
import { useDocumentsOCR } from "./useDocumentsOCR";

const STATUT_META: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  rapprochee: { label: "Facture retrouvée dans l'ERP", color: "#10B981", icon: <CheckCircle2 size={15} /> },
  ecart_detecte: { label: "Écart détecté", color: "#F59E0B", icon: <AlertTriangle size={15} /> },
  doublon_probable: { label: "Doublon probable", color: "#EF4444", icon: <ShieldAlert size={15} /> },
  introuvable: { label: "Introuvable dans l'ERP", color: "#64748B", icon: <XCircle size={15} /> },
  montant_absent: { label: "Montant illisible", color: "#64748B", icon: <XCircle size={15} /> },
  entrepot_indisponible: { label: "Entrepôt indisponible", color: "#64748B", icon: <XCircle size={15} /> },
  // Postérieure à la fin de l'export ERP : son absence ne prouve rien.
  hors_periode: { label: "Postérieure à l'export ERP", color: "#64748B", icon: <AlertTriangle size={15} /> },
  sens_a_choisir: { label: "Achat ou vente ?", color: "#64748B", icon: <AlertTriangle size={15} /> },
};

function fMoney(v: number | null | undefined, dev = "TND") {
  if (v == null || Number.isNaN(v)) return "—";
  const s = v.toLocaleString("fr-FR", { minimumFractionDigits: 3, maximumFractionDigits: 3 });
  return `${s} ${dev === "TND" ? "DT" : dev}`;
}
function fDate(d?: string | null) {
  if (!d) return "—";
  const t = new Date(d);
  return Number.isNaN(t.getTime()) ? d : t.toLocaleDateString("fr-FR");
}

export default function DocumentsOCR() {
  const {
    mode, setMode, file, setFile, busy, engineOk, engineInfo, moteurMotif, moteurCause,
    invoice, rawText, ragMsg, error, importRes, ambigu, saisie, setSaisie, sens, setSens,
    identite, setIdentite, identiteOk, ech, regler, inputRef, isDirector, reset, submit,
    importer, valeurLue, modifie, nModifs, rapprocher, enregistrerIdentite,
  } = useDocumentsOCR();

  const conf = (f: string) => {
    const c = invoice?.facture.champs_confiance?.[f];
    if (!c) return null;
    const label = c === "explicite" ? "libellé trouvé" : c === "calcule" ? "calculé"
      : c === "corrige" ? "corrigé par le taux" : c === "layoutlmv3" ? "lu par LayoutLMv3"
      : c === "ecarte" ? "écarté — à saisir" : "déduit";
    const color = c === "explicite" ? "#10B981" : c === "calcule" ? "#2F5BEA"
      : c === "corrige" ? "#7C5CFC" : c === "layoutlmv3" ? "#0E9F8E"
      : c === "ecarte" ? "#EF4444" : "#F59E0B";
    return <em style={{ fontStyle: "normal", fontSize: "0.64rem", color, marginLeft: 6 }}>({label})</em>;
  };

  const st = invoice?.rapprochement ? (STATUT_META[invoice.rapprochement.statut] ||
    { label: invoice.rapprochement.statut, color: "#64748B", icon: <FileScan size={15} /> }) : null;

  const MODES: { id: Mode; label: string; desc: string; icon: React.ReactNode }[] = [
    { id: "facture", label: "Facture", icon: <FileScan size={15} />,
      desc: "Champs extraits (n°, dates, HT/TVA/TTC) puis rapprochement automatique avec l'ERP." },
    { id: "texte", label: "Texte brut", icon: <FileText size={15} />,
      desc: "Texte intégral du document, avec indicateur de qualité de lecture." },
    ...(isDirector ? [{ id: "rag" as Mode, label: "Base documentaire", icon: <Library size={15} />,
      desc: "Le document est indexé : interrogez-le ensuite dans le copilote avec « doc: »." }] : []),
  ];
  const modeCourant = MODES.find(m => m.id === mode) || MODES[0];
  // Tant qu'aucun résultat n'est affiché, le formulaire occupe toute la largeur
  // au lieu de 5 colonnes sur 12 — l'ancienne mise en page laissait 7 colonnes
  // vides à droite, ce qui donnait un écran minuscule et sans intention.
  const aUnResultat = Boolean(invoice || rawText);

  const zoneDepot = (
    <>
      <div className={`ocr-drop ${file ? "has-file" : ""}`} onClick={() => inputRef.current?.click()}
        onDragOver={e => e.preventDefault()}
        onDrop={e => { e.preventDefault(); const f = e.dataTransfer.files?.[0]; if (f) { setFile(f); reset(); } }}>
        <span className="ocr-drop-ico"><Upload size={22} /></span>
        {file ? (
          <>
            <span className="ocr-drop-title">{file.name}</span>
            <em>{(file.size / 1024 / 1024).toFixed(2)} Mo — cliquez pour changer de fichier</em>
          </>
        ) : (
          <>
            <span className="ocr-drop-title">Déposez un document ici</span>
            <em>ou cliquez pour parcourir · PDF, PNG, JPG, TIFF — 20 Mo max</em>
          </>
        )}
      </div>
      <input ref={inputRef} type="file" style={{ display: "none" }}
        accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp"
        onChange={e => { const f = e.target.files?.[0]; if (f) { setFile(f); reset(); } e.target.value = ""; }} />

      <div className="ocr-actions">
        <button className="login-btn ocr-go" onClick={submit} disabled={!file || busy}>
          {busy ? <><Loader2 size={15} className="spin-icon" /> Analyse en cours…</>
                : <><FileScan size={15} /> Analyser le document</>}
        </button>
        {file && !busy && (
          <button type="button" className="ocr-clear"
            onClick={() => { setFile(null); reset(); }}>Retirer</button>
        )}
      </div>

      {error && <p className="ocr-flash err"><XCircle size={13} /> {error}</p>}
      {ragMsg && <p className="ocr-flash ok"><Library size={13} /> {ragMsg}</p>}
    </>
  );

  return (
    <div style={{ gridColumn: "span 12", display: "grid", gridTemplateColumns: "repeat(12, 1fr)", gap: 14 }}>

      {/* Panneau de dépôt */}
      <div className="chart-card" style={{ gridColumn: aUnResultat ? "span 5" : "span 12" }}>
        <div className="card-header">
          <span className="card-label"><ScanLine size={16} style={{ verticalAlign: "-3px" }} /> Numériser un document</span>
          <span className={`ocr-engine ${engineOk ? "on" : engineOk === false ? "off" : ""}`}>
            {engineOk === null ? "moteur : vérification…"
              : engineOk ? `Moteur OCR actif — ${engineInfo}`
              : "Tesseract absent — les PDF texte restent exploitables"}
          </span>
        </div>

        {engineOk === false && engineInfo && (
          <p className="ocr-flash warn"><AlertTriangle size={13} /> {engineInfo}</p>
        )}

        {/* « Règles seules » a trois causes très différentes : modèle absent,
            dépendances absentes, ou modèle refusé par le registre. La dernière
            est invisible sans ce message. */}
        {moteurMotif && (
          <p className="muted-note" style={{ marginTop: 2,
              color: moteurCause === "refuse_par_registre" ? "#F59E0B" : "var(--text-muted)" }}>
            {moteurCause === "servi" ? "LayoutLMv3 " : "LayoutLMv3 non servi — "}{moteurMotif}
          </p>
        )}

        <div className="ocr-modes">
          {MODES.map(m => (
            <button key={m.id} type="button"
              className={`ocr-mode ${mode === m.id ? "on" : ""}`}
              onClick={() => { setMode(m.id); reset(); }}>
              {m.icon}<span>{m.label}</span>
            </button>
          ))}
        </div>
        <p className="ocr-mode-desc">{modeCourant.desc}</p>

        {aUnResultat ? zoneDepot : (
          <div className="ocr-split">
            <div>{zoneDepot}</div>
            <div className="ocr-steps">
              <h4>Comment ça marche</h4>
              <ol>
                <li><b>Déposez</b> une facture scannée, une photo ou un PDF.</li>
                <li><b>Le texte est extrait</b> (Tesseract, ou lecture directe pour un PDF texte), avec un indice de fiabilité.</li>
                <li><b>Les champs sont identifiés</b> — n°, dates, HT, TVA, TTC, tiers, matricule fiscal.</li>
                <li><b>La facture est rapprochée</b> de l&apos;entrepôt ERP : retrouvée, écart de montant, doublon probable ou introuvable.</li>
              </ol>
              <p className="ocr-steps-note">
                Chaque champ porte son origine — <em>libellé trouvé</em>, <em>calculé</em> ou <em>déduit</em> —
                afin qu&apos;une valeur reconstituée ne soit jamais confondue avec une valeur lue.
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Résultat facture */}
      {invoice && (
        <div className="chart-card" style={{ gridColumn: "span 7" }}>
          <div className="card-header">
            <span className="card-label"><FileText size={16} style={{ verticalAlign: "-3px" }} /> Facture extraite — {invoice.filename}</span>
            <span style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}>
              lecture : {invoice.ocr.quality}{invoice.ocr.confidence ? ` (${invoice.ocr.confidence}%)` : ""}
              {invoice.moteur && ` · ${invoice.moteur === "layoutlmv3+regles" ? "LayoutLMv3 + règles" : "règles seules"}`}
            </span>
          </div>

          {!invoice.facture.is_invoice && (
            <p className="muted-note" style={{ color: "#F59E0B" }}>
              <AlertTriangle size={12} style={{ verticalAlign: "-2px" }} /> Ce document ne ressemble pas à une facture — les champs ci-dessous sont peut-être incomplets.
            </p>
          )}

          {/* Le TTC est la valeur sur laquelle se joue le rapprochement :
              il est sorti de la grille pour être lisible d'un coup d'œil. */}
          <div className="ocr-hero">
            <div>
              <span>Montant TTC</span>
              <b>{fMoney(saisie.montant_ttc ? parseFloat(normSaisie(saisie.montant_ttc, "montant"))
                         : invoice.facture.montant_ttc, invoice.facture.devise)}</b>
              {conf("montant_ttc")}
            </div>
            {st && (
              <div className="ocr-hero-statut" style={{ color: st.color, borderColor: st.color }}>
                {st.icon}<span>{st.label}</span>
              </div>
            )}
          </div>

          {/* Enregistrement : sans cette étape, la lecture ne laissait aucune trace. */}
          <div className="ocr-import">
            {importRes?.ok ? (
              <p className="ocr-flash ok">
                <CheckCircle2 size={14} /> {importRes.message} —{" "}
                {importRes.n_factures_tiers ?? importRes.n_factures_client} facture(s) pour ce{" "}
                {importRes.genre_tiers ?? "client"},{" "}
                {(importRes.total_importe_tiers_dt ?? importRes.total_importe_client_dt ?? 0)
                  .toLocaleString("fr-FR")} DT importés.
              </p>
            ) : (
              <>
                {isDirector && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                      {(["achat", "vente"] as Sens[]).map(s => (
                        <button key={s} type="button" onClick={() => { setSens(s); rapprocher(s); }} style={{
                          padding: "6px 12px", borderRadius: 9, fontSize: "0.78rem", fontWeight: 700,
                          cursor: "pointer", color: "var(--text-primary)",
                          border: `1.5px solid ${sens === s ? "#2F5BEA" : "rgba(26,35,72,0.18)"}`,
                          background: sens === s ? "rgba(47,91,234,0.10)" : "transparent" }}>
                          {s === "achat" ? "Achat — reçue d'un fournisseur" : "Vente — émise à un client"}
                        </button>
                      ))}
                    </div>
                    {!!sens && nModifs > 0 && (
                      <button type="button" onClick={() => rapprocher(sens as Sens)}
                        style={{ alignSelf: "flex-start", background: "none", border: "none", padding: 0,
                                 cursor: "pointer", color: "#2F5BEA", fontSize: "0.74rem", textDecoration: "underline" }}>
                        Refaire le rapprochement ERP avec mes corrections
                      </button>
                    )}
                    {invoice.sens && (
                      <span className="ocr-import-note">
                        {invoice.sens.sens === "inconnu" ? "Sens non détecté : "
                          : `Détecté : ${invoice.sens.sens} (confiance ${invoice.sens.confiance}) — `}
                        {invoice.sens.motif}
                      </span>
                    )}
                    {invoice.entreprise && !invoice.entreprise.configuree && !identiteOk && (
                      <div className="ocr-ambigu">
                        <b>Qui est votre entreprise ? Déclarez-la une fois pour que le sens soit détecté.</b>
                        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                          {([["nom", "Raison sociale"], ["alias", "Variantes (virgules)"],
                             ["mf", "Matricule fiscal"]] as const).map(([k, ph]) => (
                            <input key={k} placeholder={ph} value={identite[k]}
                              onChange={e => setIdentite(v => ({ ...v, [k]: e.target.value }))}
                              style={{ flex: "1 1 140px", padding: "5px 8px", borderRadius: 7, fontSize: "0.76rem",
                                       border: "1px solid rgba(26,35,72,0.2)" }} />
                          ))}
                          <button type="button" onClick={enregistrerIdentite} disabled={!identite.nom.trim()}
                            style={{ padding: "5px 10px", borderRadius: 7, fontSize: "0.76rem", fontWeight: 700,
                                     border: "1px solid #B45309", background: "transparent", cursor: "pointer" }}>
                            Enregistrer
                          </button>
                        </div>
                      </div>
                    )}
                    {identiteOk && (
                      <span className="ocr-import-note" style={{ color: "#10B981" }}>
                        {`Identité enregistrée (${identiteOk}) : elle s'appliquera aux prochaines lectures. `}
                        {"Pour celle-ci, choisissez le sens ci-dessus."}
                      </span>
                    )}
                  </div>
                )}
                <button className="login-btn ocr-go" onClick={() => importer(true)}
                        disabled={busy || (isDirector && !sens)}>
                  {busy ? <><Loader2 size={14} className="spin-icon" /> Enregistrement…</>
                        : <><Save size={14} /> {nModifs
                            ? `Valider ${nModifs} correction${nModifs > 1 ? "s" : ""} et enregistrer`
                            : "Valider et enregistrer"}</>}
                </button>
                <span className="ocr-import-note">
                  Vérifiez les champs ci-dessous et corrigez-les si besoin : vos corrections sont
                  conservées et serviront à réentraîner le modèle.{" "}
                  {sens === "achat" ? "Un achat est rattaché à son fournisseur et n'entre jamais dans le chiffre d'affaires."
                    : sens === "vente" ? "Une vente est rattachée à son client (créé si nécessaire)." : ""}
                </span>
              </>
            )}
            {ambigu?.candidats?.length ? (
              <div className="ocr-ambigu">
                <b>{ambigu.action_requise || "Tiers à confirmer"}</b>
                <ul>
                  {ambigu.candidats.map(c => (
                    <li key={c.code}>
                      <button type="button" onClick={() => importer(true, c.code)} disabled={busy}
                        style={{ background: "none", border: "none", padding: 0, cursor: "pointer",
                                 color: "#2F5BEA", fontWeight: 700, textDecoration: "underline" }}>
                        {c.nom}
                      </button>{" "}<em>({Math.round(c.score * 100)} %)</em>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>

          <div className="ocr-fields">
            {CHAMPS.map(c => {
              const m = modifie(c);
              const orig = versSaisie(valeurLue(c.cle), c.type);
              return (
                <div key={c.cle} style={m ? { background: "rgba(124,92,252,0.08)", outline: "1.5px solid #7C5CFC" } : undefined}>
                  <span>{c.label}{conf(c.cle)}{m && (
                    <em style={{ fontStyle: "normal", fontSize: "0.64rem", color: "#7C5CFC", marginLeft: 6,
                                 textTransform: "none" }}>(corrigé — lu : {orig || "vide"})</em>)}</span>
                  <input type={c.type === "date" ? "date" : "text"}
                    inputMode={c.type === "montant" ? "decimal" : undefined}
                    value={saisie[c.cle] ?? ""} disabled={!!importRes?.ok} aria-label={c.label}
                    onChange={e => setSaisie(v => ({ ...v, [c.cle]: e.target.value }))}
                    style={{ border: "none", background: "transparent", font: "inherit", fontSize: "0.86rem",
                             fontWeight: 700, color: c.cle === "net_a_payer" ? "var(--accent-blue)" : "var(--text-primary)",
                             padding: "2px 0", width: "100%" }} />
                </div>
              );
            })}
            <div><span>Qualité de lecture</span><b>{invoice.ocr.quality}
              {invoice.ocr.confidence ? ` · ${invoice.ocr.confidence}%` : ""}</b></div>
          </div>

          {!!invoice.facture.avertissements?.length && (
            <p className="ocr-flash warn"><AlertTriangle size={13} />
              {invoice.facture.avertissements.join(" ")}</p>
          )}

          {invoice.facture.coherence && (
            <p className="muted-note" style={{ marginTop: 8, color: invoice.facture.coherence.startsWith("HT") ? "#10B981" : "#EF4444" }}>
              {invoice.facture.coherence}
            </p>
          )}

          {/* Rapprochement ERP */}
          {invoice.rapprochement && st && (
            <div style={{ marginTop: 14, borderTop: "1px solid rgba(26,35,72,0.10)", paddingTop: 12 }}>
              <p style={{ margin: "0 0 10px", fontSize: "0.82rem" }}>{invoice.rapprochement.message}</p>
              {!!invoice.rapprochement.candidats.length && (
                <div className="data-table">
                  <div className="dt-head" style={{ display: "grid", gridTemplateColumns: "1.5fr 90px 110px 60px 1.4fr" }}>
                    <span>{invoice.rapprochement.genre_tiers === "fournisseur" ? "Fournisseur ERP" : "Client ERP"}</span><span>Date</span><span>Montant</span><span>Score</span><span>Pourquoi</span>
                  </div>
                  {invoice.rapprochement.candidats.map((c, i) => (
                    <div key={i} className="dt-row" style={{ display: "grid", gridTemplateColumns: "1.5fr 90px 110px 60px 1.4fr", fontSize: "0.76rem" }}>
                      <span className="dt-name">{c.client_nom}</span>
                      <span>{fDate(c.date)}</span>
                      <span>{fMoney(c.montant_ttc)}</span>
                      <span style={{ fontWeight: 800, color: c.score > 80 ? "#10B981" : c.score > 50 ? "#F59E0B" : "#64748B" }}>{c.score}</span>
                      <span style={{ color: "var(--text-muted)" }}>{c.explication}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          <details style={{ marginTop: 12 }}>
            <summary style={{ cursor: "pointer", fontSize: "0.76rem", color: "var(--text-muted)" }}>
              Texte brut extrait ({invoice.ocr.text.length} caractères)
            </summary>
            <pre className="ocr-raw">{invoice.ocr.text.slice(0, 4000)}</pre>
          </details>
        </div>
      )}

      {/* Échéancier : factures lues, absentes de l'ERP, non réglées */}
      {!!ech?.n_factures && (
        <div className="chart-card" style={{ gridColumn: "span 12" }}>
          <div className="card-header">
            <span className="card-label"><Wallet size={16} style={{ verticalAlign: "-3px" }} /> Échéancier des factures scannées</span>
            <span style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}>
              {ech.n_factures} facture(s) hors ERP · {ech.n_echeances_deduites} échéance(s) déduite(s)
            </span>
          </div>
          <div className="ocr-fields" style={{ gridTemplateColumns: "repeat(4, 1fr)", marginBottom: 12 }}>
            <div><span>À payer</span><b>{fMoney(ech.a_payer_dt)}</b></div>
            <div><span>dont en retard</span><b style={{ color: ech.a_payer_en_retard_dt ? "#EF4444" : undefined }}>
              {fMoney(ech.a_payer_en_retard_dt)}</b></div>
            <div><span>À encaisser</span><b>{fMoney(ech.a_encaisser_dt)}</b></div>
            <div><span>dont en retard</span><b style={{ color: ech.a_encaisser_en_retard_dt ? "#F59E0B" : undefined }}>
              {fMoney(ech.a_encaisser_en_retard_dt)}</b></div>
          </div>
          <div className="data-table">
            <div className="dt-head" style={{ display: "grid", gridTemplateColumns: "110px 1fr 1fr 1fr" }}>
              <span>Mois</span><span>Décaissements</span><span>Encaissements</span><span>Solde</span>
            </div>
            {ech.mois.map(m => (
              <div key={m.periode} className="dt-row" style={{ display: "grid", gridTemplateColumns: "110px 1fr 1fr 1fr", fontSize: "0.78rem" }}>
                <span className="dt-name">{m.periode === "en_retard" ? "Échu" : m.periode}</span>
                <span>{fMoney(m.decaissements_dt)}</span>
                <span>{fMoney(m.encaissements_dt)}</span>
                <span style={{ fontWeight: 700, color: m.solde_dt < 0 ? "#EF4444" : "#10B981" }}>{fMoney(m.solde_dt)}</span>
              </div>
            ))}
          </div>
          <div className="data-table" style={{ marginTop: 12 }}>
            <div className="dt-head" style={{ display: "grid", gridTemplateColumns: "70px 1.3fr 1.2fr 1.4fr 110px 90px" }}>
              <span>Sens</span><span>Facture</span><span>Montant</span><span>Échéance</span><span>Statut</span><span></span>
            </div>
            {ech.factures.map(f => (
              <div key={f.id} className="dt-row" style={{ display: "grid", gridTemplateColumns: "70px 1.3fr 1.2fr 1.4fr 110px 90px", fontSize: "0.76rem" }}>
                <span>{f.sens === "achat" ? "Achat" : "Vente"}</span>
                <span className="dt-name">{f.numero} · {f.tiers || "—"}</span>
                <span>{fMoney(f.montant_dt)}</span>
                <span>{fDate(f.echeance)}{" "}
                  <em style={{ fontStyle: "normal", fontSize: "0.66rem", color: f.source_echeance === "lue" ? "#10B981" : "#F59E0B" }}>
                    ({SOURCE_ECHEANCE[f.source_echeance.replace("_sans_date", "")] || f.source_echeance}
                    {f.source_echeance.endsWith("_sans_date") ? ", sans date" : ""})</em></span>
                <span style={{ color: f.statut === "en_retard" ? "#EF4444" : "var(--text-muted)" }}>
                  {f.statut === "en_retard" ? `retard ${f.jours_de_retard} j` : "à venir"}</span>
                <span>{isDirector && (
                  <button type="button" onClick={() => regler(f.id)}
                    style={{ background: "none", border: "none", padding: 0, cursor: "pointer",
                             color: "#2F5BEA", fontSize: "0.72rem", textDecoration: "underline" }}>
                    Réglée
                  </button>)}</span>
              </div>
            ))}
          </div>
          <p className="muted-note" style={{ marginTop: 8 }}>{ech.note}</p>
        </div>
      )}

      {/* Résultat texte brut */}
      {rawText && (
        <div className="chart-card" style={{ gridColumn: "span 7" }}>
          <div className="card-header">
            <span className="card-label"><FileText size={16} style={{ verticalAlign: "-3px" }} /> Texte extrait</span>
            <span style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}>
              {rawText.source} · qualité : {rawText.quality}{rawText.confidence ? ` (${rawText.confidence}%)` : ""} · {rawText.pages} page(s)
            </span>
          </div>
          {!!rawText.warnings?.length && (
            <p className="muted-note" style={{ color: "#F59E0B" }}>{rawText.warnings.join(" ")}</p>
          )}
          <pre className="ocr-raw">{rawText.text || "(aucun texte détecté)"}</pre>
        </div>
      )}
    </div>
  );
}
