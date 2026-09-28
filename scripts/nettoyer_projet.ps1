<#
    scripts/nettoyer_projet.ps1
    ===========================
    Range hors du projet tout ce qui n'est plus utilisé par le code.

    Rien n'est effacé : chaque élément est DÉPLACÉ dans `_a_supprimer\`, en
    conservant son chemin d'origine. Vous vérifiez que l'application tourne
    toujours, puis vous videz ce dossier — c'est à ce moment-là seulement que
    la place est réellement libérée.

    UTILISATION (PowerShell, depuis la racine du projet) :

        .\scripts\nettoyer_projet.ps1 -Simulation   # liste sans rien déplacer
        .\scripts\nettoyer_projet.ps1               # déplace vers _a_supprimer\
        .\scripts\nettoyer_projet.ps1 -Purger       # vide _a_supprimer\ définitivement

    Si Windows refuse d'exécuter le script :
        powershell -ExecutionPolicy Bypass -File .\scripts\nettoyer_projet.ps1

    CE QUI EST GARDÉ, ET POURQUOI
    -----------------------------
    · les 8 CSV que l'entrepôt lit réellement (les 23 autres partent) ;
    · tous les modules importés par l'API, les tests ou un script documenté ;
    · docs/, reports/, models/, rag/ : la documentation et les artefacts que
      le registre et la passerelle relisent au démarrage ;
    · le dictionnaire de données, le schéma du data warehouse et le notebook
      d'exploration, qui servent au mémoire.

    ATTENTION : output/, reports/, models/ et data_pfe/ sont exclus de Git
    (.gitignore). Ce qui en sort n'est PAS récupérable par Git — c'est
    précisément la raison du passage par `_a_supprimer\`.
#>

param(
    [switch]$Simulation,
    [switch]$Purger
)

$ErrorActionPreference = "Stop"
# Le script est rangé dans scripts\ : la racine du projet est le dossier parent.
$Racine = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Definition)
Set-Location $Racine
$Poubelle = Join-Path $Racine "_a_supprimer"

# Garde-fou : la racine calculée doit bien être celle du projet.
if (-not (Test-Path (Join-Path $Racine "api\main.py"))) {
    Write-Host "Ce script doit rester dans le dossier scripts\ du projet (api\main.py introuvable)." -ForegroundColor Red
    exit 1
}

# ── Mode purge : vider définitivement la corbeille du projet ────────────────
if ($Purger) {
    if (-not (Test-Path $Poubelle)) {
        Write-Host "Rien à purger : _a_supprimer\ n'existe pas." -ForegroundColor Yellow
        exit 0
    }
    $taille = (Get-ChildItem $Poubelle -Recurse -File -ErrorAction SilentlyContinue |
               Measure-Object -Property Length -Sum).Sum
    $mo = [math]::Round($taille / 1MB, 1)
    Write-Host "Suppression DÉFINITIVE de _a_supprimer\ ($mo Mo). Cette action est irréversible." -ForegroundColor Yellow
    $rep = Read-Host "Tapez SUPPRIMER pour confirmer"
    if ($rep -ne "SUPPRIMER") { Write-Host "Annulé." ; exit 0 }
    Remove-Item $Poubelle -Recurse -Force
    Write-Host "$mo Mo libérés." -ForegroundColor Green
    exit 0
}

# ── Ce qui part ─────────────────────────────────────────────────────────────

# 1. Caches et fichiers générés : ils se reconstruisent tout seuls.
$caches = @(
    ".pytest_cache",
    "frontend\.next",
    "frontend\tsconfig.tsbuildinfo"
)

# 2. Code mort : aucun import nulle part (ni API, ni tests, ni scripts).
$codeMort = @(
    "ml_engine\preprocessing\ml_preprocessing.py",   # pipeline ML abandonné (51 Ko)
    "ml_engine\nlp"                                   # paquet vide (ancienne veille AO)
)

# 3. Scripts d'analyse ponctuelle, cités dans aucun document.
$scripts = @(
    "scripts\audit_ecart_montantsigne.py",
    "scripts\audit_qualite_donnees.py",
    "scripts\diag_stock_reel.py",
    "scripts\export_stock.py",
    "scripts\show_auth_db.py"
)

# 4. Documents de travail d'une phase terminée.
$annexes = @(
    "brainstorming_français.md",
    "brainstorming_français.pdf",
    "plan_pfe_6mois_gratuit.md",
    "PROMPT_finalisation_PFE.md",
    "Claude outputs"
)

# 5. Artefacts orphelins : plus personne ne les lit.
$orphelins = @(
    "output\market_intel_history.json",   # agent de veille retiré
    "output\stock_simule.csv",            # export produit par export_stock.py, supprimé ci-dessus
    "frontend\README.md",                 # texte d'exemple de Next.js
    "frontend\public\file.svg",
    "frontend\public\globe.svg",
    "frontend\public\next.svg",
    "frontend\public\vercel.svg",
    "frontend\public\window.svg"
)

# 6. Extraction ERP non exploitée : 23 CSV que le code ne lit jamais.
#    Les 8 fichiers dont dépend l'entrepôt sont conservés (vérifié en fin de script).
$csvInutiles = @(
    "Devis_achat_ent_v.csv",
    "Devis_achat_mouv_v.csv",
    "Devis_vente_ent_v.csv",
    "Devis_vente_mouv_v.csv",
    "Devis_vente_mouv_vv.csv",
    "facture_vente_ent_vv.csv",
    "Facture_vente_mouv_v.csv",
    "GSL_ACHAT_BL_ENTETE.csv",
    "Gsl_achat_bl_ligne_detail.csv",
    "Gsl_achat_bl_ligne.csv",
    "Gsl_vente_bl_ligne_detail.csv",
    "Gsl_vente_bl_ligne.csv",
    "Gsl_vente_fa_ligne.csv",
    "Gsl_vente_ligne_detail.csv",
    "Mb_facture_vente_mouv_v.csv",
    "Ms_Bl_facture_ent_actif.csv",
    "Ms_comparatif_achat_facture.csv",
    "Ms_comparatif_achat.csv",
    "Ms_comparatif_vente_facturecsv.csv",
    "Ol_GCF_Facture_achat_base.csv",
    "Table_etat_devis_technique_v.csv",
    "table_nature_paiement_vcsv.csv",
    "Zz_facture_vente_ent.csv"
) | ForEach-Object { "data_pfe\$_" }

#: Ces huit-là restent : sans eux, l'entrepôt ne se reconstruit plus.
$csvIndispensables = @(
    "Facture_vente_ent_v.csv", "Facture_achat_ent_v.csv", "Facture_achat_mouv_v.csv",
    "ZZ_Facture_vente_mouv.csv", "Devis_vente_ent_vv.csv", "Fournisseurs_v.csv",
    "Gsl_vente_bl_entete.csv", "Gsl_vente_fa_entete.csv"
)

# Les dossiers __pycache__ sont trouvés dynamiquement (l'environnement virtuel
# et les dépendances npm ne sont jamais touchés).
$pycache = Get-ChildItem -Path $Racine -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch "\\\.venv\\|\\node_modules\\|\\_a_supprimer\\" } |
    ForEach-Object { $_.FullName.Substring($Racine.Length + 1) }

$lots = [ordered]@{
    "Caches et fichiers générés"      = $caches + $pycache
    "Code jamais importé"             = $codeMort
    "Scripts non cités"               = $scripts
    "Documents de travail"            = $annexes
    "Artefacts orphelins"             = $orphelins
    "Extraction ERP non exploitée"    = $csvInutiles
}

# ── Déplacement ─────────────────────────────────────────────────────────────
function Taille($chemin) {
    if (Test-Path $chemin -PathType Container) {
        return (Get-ChildItem $chemin -Recurse -File -ErrorAction SilentlyContinue |
                Measure-Object -Property Length -Sum).Sum
    }
    return (Get-Item $chemin).Length
}

$totalOctets = 0
$deplaces = 0
$absents = 0
$echecs = 0

Write-Host ""
Write-Host "  NETTOYAGE DU PROJET" -ForegroundColor Cyan
if ($Simulation) { Write-Host "  (simulation : rien ne sera déplacé)" -ForegroundColor Yellow }
Write-Host ("  " + ("-" * 62))

foreach ($lot in $lots.Keys) {
    $items = @($lots[$lot] | Where-Object { $_ })
    if (-not $items) { continue }
    $octetsLot = 0
    $lignes = @()
    foreach ($rel in $items) {
        $src = Join-Path $Racine $rel
        if (-not (Test-Path $src)) { $absents++ ; continue }
        $o = Taille $src
        if ($null -eq $o) { $o = 0 }
        $octetsLot += $o
        $lignes += ("      {0,8:N1} Mo  {1}" -f ($o / 1MB), $rel)

        if (-not $Simulation) {
            # Un élément verrouillé (serveur de développement encore ouvert sur
            # .next, par exemple) ne doit pas interrompre tout le nettoyage.
            try {
                $dest = Join-Path $Poubelle $rel
                $parent = Split-Path $dest -Parent
                if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
                if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
                Move-Item -LiteralPath $src -Destination $dest -Force
            } catch {
                $lignes[$lignes.Count - 1] = ("      {0,8}  {1}  <-- NON DÉPLACÉ : {2}" -f "", $rel, $_.Exception.Message)
                $echecs++
                continue
            }
        }
        $deplaces++
    }
    if ($lignes.Count -gt 0) {
        Write-Host ("  {0} — {1} élément(s), {2:N1} Mo" -f $lot, $lignes.Count, ($octetsLot / 1MB)) -ForegroundColor White
        $lignes | ForEach-Object { Write-Host $_ -ForegroundColor DarkGray }
        $totalOctets += $octetsLot
    }
}

Write-Host ("  " + ("-" * 62))
Write-Host ("  {0} élément(s), {1:N1} Mo" -f $deplaces, ($totalOctets / 1MB)) -ForegroundColor Green
if ($absents -gt 0) { Write-Host "  ($absents élément(s) déjà absent(s) — nettoyage déjà passé)" -ForegroundColor DarkGray }
if ($echecs -gt 0) {
    Write-Host "  $echecs élément(s) verrouillé(s) : fermez le serveur de développement" -ForegroundColor Yellow
    Write-Host "  (npm run dev) et l'API, puis relancez le script." -ForegroundColor Yellow
}

# ── Contrôle de sûreté ──────────────────────────────────────────────────────
$manquants = @()
foreach ($f in $csvIndispensables) {
    if (-not (Test-Path (Join-Path $Racine "data_pfe\$f"))) { $manquants += $f }
}
if ($manquants.Count -gt 0) {
    Write-Host ""
    Write-Host "  ATTENTION : des fichiers nécessaires à l'entrepôt sont introuvables :" -ForegroundColor Red
    $manquants | ForEach-Object { Write-Host "      $_" -ForegroundColor Red }
    Write-Host "  Récupérez-les dans _a_supprimer\data_pfe\ avant de purger." -ForegroundColor Red
}

if (-not $Simulation) {
    Write-Host ""
    Write-Host "  Tout est dans _a_supprimer\ — rien n'est encore perdu." -ForegroundColor Cyan
    Write-Host "  1. Vérifiez : python api/main.py  puis  npm --prefix frontend run dev"
    Write-Host "  2. Lancez la suite de tests : python -m pytest -q"
    Write-Host "  3. Si tout va bien : .\scripts\nettoyer_projet.ps1 -Purger"
    Write-Host ""
}
