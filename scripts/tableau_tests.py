"""
scripts/tableau_tests.py
========================
Génère `docs/TESTS.md` : la synthèse de la suite de tests, en une page.

## Pourquoi ce script existe

Un mémoire ne peut pas énumérer des centaines de tests, et personne ne lirait la liste. Ce
qu'un jury attend, c'est une réponse à « qu'est-ce que vos tests DÉMONTRENT ? ».
Le tableau produit ici répond famille par famille : ce qui est prouvé, combien
de tests le prouvent, et lesquels citer.

Les comptages sont RELUS DANS LA SUITE à chaque exécution (`pytest --collect-only`),
jamais recopiés à la main : un tableau de qualité qui ment sur son propre nombre
de tests serait le comble.

Usage :
    python scripts/tableau_tests.py            # écrit docs/TESTS.md
    python scripts/tableau_tests.py --afficher # affiche sans écrire
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
SORTIE = BASE / "docs" / "TESTS.md"

#: Ce que chaque fichier démontre — en français, sans jargon de test.
#: (famille, ce qui est prouvé)
FAMILLES: dict[str, tuple[str, str]] = {
    "test_auth_rbac.py": (
        "Sécurité et isolation",
        "Aucun accès sans jeton valide ; un client ne peut pas lire les données "
        "d'un autre, même en manipulant la requête ; la force brute est bloquée ; "
        "la déconnexion révoque le jeton immédiatement."),
    "test_admin_portal.py": (
        "Sécurité et isolation",
        "Gestion des comptes par le directeur : unicité du code client, "
        "suppression qui conserve le journal d'audit, cloisonnement des demandes."),
    "test_boucle_action.py": (
        "Boucle d'action",
        "De l'alerte au résultat mesuré : un employé ne voit que ses tâches, "
        "une tâche ne se clôture pas sans résultat, une issue perdue ne compte "
        "jamais comme un gain, et les résultats repartent vers les modèles."),
    "test_fleet.py": (
        "Flotte d'agents",
        "Les cinq spécialistes produisent des constats chiffrés et sourcés ; la "
        "panne d'un volet n'emporte pas l'autre ; le rédacteur suit l'ordre de "
        "l'arbitre et ne s'exécute qu'une fois (jointure avec le volet fiabilité)."),
    "test_passerelle_agents.py": (
        "Flotte d'agents",
        "Chaque modèle du registre a un consommateur réel ; un modèle refusé ou "
        "retiré n'est jamais présenté comme servi ; aucun terme technique "
        "n'apparaît dans ce que lit un dirigeant ou un client."),
    "test_copilote.py": (
        "Flotte d'agents",
        "Le graphe du copilote suit l'ordre de ses nœuds ; une réponse du modèle "
        "de langage qui cite un montant absent des données est écartée, et le "
        "champ `via` dit d'où vient la réponse affichée."),
    "test_copilot_stock_client.py": (
        "Flotte d'agents",
        "Le copilote route la question vers le bon thème, ne fabrique aucun "
        "montant, et reste reproductible d'une exécution à l'autre."),
    "test_ml_churn.py": (
        "Modèles — absence de fuite",
        "Aucune variable ne regarde après la date d'observation, aucune n'est la "
        "cible déguisée, et le registre refuse un modèle dont le rapport manque."),
    "test_ml_credit.py": (
        "Modèles — absence de fuite",
        "Le modèle de crédit est évalué sur des clients réellement nouveaux, et "
        "c'est une règle mesurée qui est servie, pas le modèle rejeté."),
    "test_ml_stock.py": (
        "Modèles — absence de fuite",
        "Séparation par produit, aucune variable future, déploiement autorisé "
        "seulement si le gain sur la référence est confirmé."),
    "test_segmentation.py": (
        "Modèles — absence de fuite",
        "La typologie de clientèle est stable, interprétable et reproductible."),
    "test_marge_conversion.py": (
        "Modèles — absence de fuite",
        "Marge et conversion des devis : cohérence des montants et des seuils."),
    "test_demande_reference.py": (
        "Modèles — absence de fuite",
        "La prévision par référence ne lit aucun mois postérieur à l'origine ; "
        "validation et test sont disjoints ; le modèle appris n'est servi que "
        "s'il bat la règle simple de 2 points avec un intervalle entièrement "
        "positif ; sans rapport, rien n'est servi."),
    "test_demand_engine.py": (
        "Modèles — absence de fuite",
        "La prévision de demande est mesurée hors période et bornée par une "
        "référence naïve."),
    "test_entrepot.py": (
        "Entrepôt de données",
        "Sur des exports fabriqués pour le test : les vues lues par l'application "
        "gardent leurs colonnes, les avoirs et les doublons sont traités, les "
        "dimensions sont conformes, et une construction dont un contrôle échoue "
        "est annulée d'un bloc."),
    "test_coherence_financiere.py": (
        "Intégrité des chiffres",
        "Chaque indicateur se recompose : CA net = ventes − avoirs, marge = "
        "CA − coût, aucun doublon de pièce, et un contrôle d'intégrité détecte "
        "une incohérence fabriquée exprès."),
    "test_integrite_ca.py": (
        "Intégrité des chiffres",
        "Le chiffre d'affaires est conforme à l'audit manuel des sources, et le "
        "montant brut erroné d'avant correction n'est plus atteignable."),
    "test_radar_financier.py": (
        "Intégrité des chiffres",
        "Le radar financier reconnaît les établissements publics avec la règle "
        "des modèles de demande (« C.H.U. » oui, « LABORATOIRE KETATA » non), "
        "sur la fenêtre de l'exposition récente : sa part publique est un vrai "
        "pourcentage, et une erreur de calcul est journalisée, jamais avalée."),
    "test_semantique_erp.py": (
        "Intégrité des chiffres",
        "Les colonnes de l'ERP sont interprétées comme le métier les définit "
        "(montant signé, avoirs, nature de paiement)."),
    "test_payment_scenario.py": (
        "Intégrité des chiffres",
        "Les scénarios d'encaissement restent bornés et cohérents avec l'encours."),
    "test_stock.py": (
        "Stock",
        "Filtres, agrégations et bornes du module de stock, sur données simulées "
        "explicitement marquées comme telles."),
    "test_ocr.py": (
        "Documents et OCR",
        "Extraction du texte, qualité de lecture, et repli propre quand Tesseract "
        "est absent."),
    "test_ocr_import.py": (
        "Documents et OCR",
        "Une facture réelle est lue champ par champ, l'identité comptable "
        "HT + TVA = TTC est vérifiée, et le rapprochement avec l'ERP distingue "
        "les raisons sociales proches."),
    "test_layoutlm.py": (
        "Documents et OCR",
        "LayoutLMv3 décode les étiquettes en champs, la fusion avec les règles ne "
        "reprend jamais un montant invraisemblable, le chiffre des milliers est "
        "recollé sans faux positif, et le modèle n'est servi que si le registre "
        "l'autorise."),
    "test_ocr_achats_ventes.py": (
        "Documents et OCR",
        "Un achat ne gonfle jamais les ventes ; le sens est détecté depuis "
        "l'identité de l'entreprise ; un doublon exige le même numéro ET le même "
        "fournisseur ; les corrections de l'utilisateur sont conservées."),
    "test_ocr_api_import.py": (
        "Documents et OCR",
        "De la lecture à l'enregistrement par l'API : un sens inconnu est refusé "
        "plutôt que deviné, un compte client reste dans son périmètre, un "
        "identifiant de lecture forgé est rejeté, un même document est repéré."),
    "test_ocr_rapprochement.py": (
        "Documents et OCR",
        "Une facture importée est rapprochée de l'ERP : rapprochée, écart détecté, "
        "introuvable, hors période ou doublon probable."),
    "test_ocr_echeancier.py": (
        "Documents et OCR",
        "L'échéancier compte le net à payer et non le TTC, lit ou déduit "
        "l'échéance, ne double pas une facture déjà dans l'ERP et retire les "
        "factures réglées."),
    "test_ocr_apprentissage.py": (
        "Documents et OCR",
        "Les corrections faites à l'écran mesurent l'exactitude réelle de la "
        "lecture en production."),
    "test_ocr_integration_production.py": (
        "Documents et OCR",
        "La valeur corrigée en production devient la vérité étiquetée, et la "
        "fusion se fait dans une copie du jeu d'entraînement, jamais dans "
        "l'original."),
    "test_emails.py": (
        "Comptes",
        "Les identifiants de connexion dérivés du nom de l'établissement sont "
        "uniques, sans accent et stables."),
    "test_explication.py": (
        "Explicabilité",
        "La décomposition d'un score linéaire est exacte au flottant près, les "
        "parts affichées totalisent 100 %, aucune phrase ne contient de jargon, "
        "et un modèle de forme inattendue ne produit aucune explication plutôt "
        "qu'une explication approximative."),
    "test_architecture_api.py": (
        "Architecture",
        "Les règles de l'architecture en couches sont vérifiées sur le code : une "
        "route ne calcule rien, un service ne connaît pas FastAPI, l'API passe par "
        "la passerelle des modèles, et toute erreur métier a un code HTTP."),
    "test_modules_branches.py": (
        "Robustesse",
        "Les chemins de repli de chaque module sont exercés : entrepôt absent, "
        "modèle manquant, rapport illisible — le service dégrade, il ne tombe pas."),
}


#: Une ligne par famille pour la vue d'ensemble — sinon le tableau récapitulatif
#: recopierait la description de chaque fichier et deviendrait illisible.
RESUME_FAMILLE: dict[str, str] = {
    "Sécurité et isolation":
        "Un client ne peut pas lire les données d'un autre, même en manipulant la requête",
    "Boucle d'action":
        "De l'alerte au résultat mesuré, avec un cloisonnement strict des rôles",
    "Flotte d'agents":
        "Cinq spécialistes et un volet fiabilité produisent des constats chiffrés, un agent en panne n'arrête pas le briefing, et le copilote n'affiche aucun montant non sourcé",
    "Modèles — absence de fuite":
        "Aucun modèle ne regarde l'avenir, et aucun n'est déployé sans gain confirmé sur une référence",
    "Entrepôt de données":
        "L'entrepôt se construit selon ses règles, et un contrôle en échec annule toute la construction",
    "Intégrité des chiffres":
        "Chaque indicateur se recompose à partir des factures, et une incohérence fabriquée est détectée",
    "Stock":
        "Filtres et bornes du module de stock, sur des données simulées explicitement marquées",
    "Documents et OCR":
        "Une facture réelle est lue champ par champ, puis rapprochée de l'ERP",
    "Comptes":
        "Les identifiants dérivés du nom de l'établissement restent uniques et stables",
    "Explicabilité":
        "Chaque justification affichée tient sa promesse : décomposition exacte, parts cohérentes, aucun jargon",
    "Architecture":
        "Les règles de l'architecture en couches sont vérifiées sur le code, pas seulement décrites",
    "Robustesse":
        "Chaque repli est exercé : le service dégrade au lieu de tomber",
}

#: Ce que prouve chaque test emblématique, en une phrase citable telle quelle.
AFFIRMATIONS: dict[str, str] = {
    "test_client_scope_force_sur_dashboard":
        "Le périmètre d'un client est forcé côté serveur : demander les données d'un autre renvoie les siennes",
    "test_rate_limiting_apres_5_echecs":
        "Cinq échecs de connexion suffisent à bloquer une tentative de force brute",
    "test_logout_revoque_le_jeton_immediatement":
        "La déconnexion révoque le jeton sur-le-champ, sans attendre son expiration",
    "test_briefing_survit_a_un_agent_en_panne":
        "Une panne injectée dans un agent ne supprime pas le briefing : il sort amputé, jamais vide",
    "test_chaque_modele_du_registre_atteint_un_agent":
        "Chaque modèle du registre a un consommateur réel : un agent métier, ou la chaîne OCR pour la lecture de factures",
    "test_aucune_variable_ne_lit_le_futur":
        "La prévision par référence ne lit aucun mois postérieur à l'origine : réécrire le futur ne change rien",
    "test_un_modele_refuse_ou_retire_n_est_jamais_presente_comme_servi":
        "Un modèle refusé ou retiré ne peut pas être présenté comme servi",
    "test_aucun_terme_technique_dans_les_textes_lus_par_un_dirigeant":
        "Aucun terme technique n'apparaît dans ce que lisent un dirigeant ou un client",
    "test_aucune_variable_n_est_la_cible_deguisee":
        "Aucune variable du modèle de départ client n'est la cible déguisée",
    "test_modele_deploye_uniquement_si_gain_confirme":
        "Un modèle n'est déployé que si son gain sur la référence est confirmé",
    "test_ca_net_conforme_a_l_audit":
        "Le chiffre d'affaires publié est conforme à l'audit manuel des sources",
    "test_identite_comptable_verifiee":
        "Sur une facture lue par OCR, HT + TVA = TTC est vérifié, pas supposé",
    "test_une_issue_perdue_ne_compte_pas_comme_un_gain":
        "Un client perdu ne gonfle jamais le montant récupéré grâce aux actions",
    "test_une_tache_dun_collegue_est_introuvable":
        "La tâche d'un collègue renvoie 404 — un 403 confirmerait son existence",
    "test_la_somme_des_contributions_reconstitue_le_score_du_modele":
        "L'explication affichée reconstitue exactement le score du modèle, au flottant près",
    "test_une_alerte_deja_confiee_ne_se_confie_pas_une_seconde_fois":
        "Une alerte déjà confiée est refusée par le serveur : un client n'est jamais relancé deux fois pour la même raison",
    "test_via_dit_d_ou_vient_la_reponse":
        "Une réponse du copilote qui cite un montant inventé est écartée, et la source affichée est celle qui a réellement répondu",
    "test_un_avoir_est_deduit_et_un_doublon_compte_une_fois":
        "Dans l'entrepôt, un avoir est déduit du chiffre d'affaires et une facture exportée deux fois n'est comptée qu'une fois",
    "test_aucun_fait_orphelin_de_sa_dimension":
        "Aucun fait de l'entrepôt ne pointe vers un client, un produit ou une date inconnus : c'est contrôlé à chaque construction",
    "test_aucune_phrase_affichee_ne_contient_de_jargon":
        "Aucune justification affichée ne contient de terme technique ni de nom de variable",
}


def collecte() -> tuple[Counter, dict[str, list[str]], int]:
    """Compte les tests par fichier et relève les tests marqués `vitrine`."""
    def lancer(args: list[str]) -> list[str]:
        r = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", *args],
                           cwd=BASE, capture_output=True, text=True, timeout=900)
        return [l.strip() for l in r.stdout.splitlines() if "::" in l]

    tous = lancer([])
    vitrine = lancer(["-m", "vitrine"])
    par_fichier: Counter = Counter()
    for l in tous:
        par_fichier[l.split("::")[0].replace("tests/", "").replace("tests\\", "")] += 1
    marques: dict[str, list[str]] = {}
    for l in vitrine:
        f, nom = l.split("::")[0], l.split("::")[1].split("[")[0]
        marques.setdefault(f.replace("tests/", "").replace("tests\\", ""), []).append(nom)
    return par_fichier, marques, len(tous)


def lisible(nom_test: str) -> str:
    """`test_une_issue_perdue_ne_compte_pas_comme_un_gain` → phrase lisible."""
    t = re.sub(r"^test_", "", nom_test).replace("_", " ")
    return t[:1].upper() + t[1:]


def construire() -> str:
    par_fichier, marques, total = collecte()

    # Regroupement par famille, dans l'ordre de FAMILLES.
    familles: dict[str, list[tuple[str, int, str]]] = {}
    for fichier, (famille, preuve) in FAMILLES.items():
        n = par_fichier.get(fichier, 0)
        familles.setdefault(famille, []).append((fichier, n, preuve))
    inconnus = sorted(set(par_fichier) - set(FAMILLES))

    L = []
    L.append("# Ce que les tests démontrent\n")
    L.append(f"*Tableau généré le {date.today().strftime('%d/%m/%Y')} par "
             "`python scripts/tableau_tests.py` — les comptages sont relus dans "
             "la suite, jamais recopiés.*\n")
    L.append(f"**{total} tests** répartis en {len(familles)} familles. Le mémoire "
             "cite ce tableau, pas la liste des tests.\n")

    L.append("## Vue d'ensemble\n")
    L.append("| Famille | Tests | Ce qui est démontré |")
    L.append("|---|---:|---|")
    for famille, lignes in familles.items():
        n = sum(x[1] for x in lignes)
        phrase = RESUME_FAMILLE.get(famille) or lignes[0][2].split(";")[0].strip().rstrip(".")
        L.append(f"| **{famille}** | {n} | {phrase}. |")
    L.append("")

    L.append("## Le détail, fichier par fichier\n")
    for famille, lignes in familles.items():
        L.append(f"### {famille}\n")
        L.append("| Fichier | Tests | Ce qui est démontré |")
        L.append("|---|---:|---|")
        for fichier, n, preuve in sorted(lignes, key=lambda x: -x[1]):
            L.append(f"| `{fichier}` | {n} | {preuve} |")
        L.append("")

    if inconnus:
        L.append("### Non décrits dans ce tableau\n")
        for f in inconnus:
            L.append(f"- `{f}` ({par_fichier[f]} tests) — ajoutez-le à `FAMILLES` "
                     "dans `scripts/tableau_tests.py`.")
        L.append("")

    n_vitrine = sum(len(v) for v in marques.values())
    L.append("## Les tests à citer\n")
    L.append(f"Ces **{n_vitrine} tests** portent chacun une affirmation forte du "
             "mémoire. Ils se rejouent en une commande, en moins de deux minutes :\n")
    L.append("```bash\npython -m pytest -m vitrine -v\n```\n")
    L.append("| Affirmation | Test |")
    L.append("|---|---|")
    for fichier in sorted(marques):
        for nom in marques[fichier]:
            L.append(f"| {AFFIRMATIONS.get(nom, lisible(nom))} | `{fichier}::{nom}` |")
    L.append("")
    L.append("## Comment lire un échec\n")
    L.append("Un test qui échoue nomme la règle métier violée, pas une ligne de "
             "code : « une issue perdue ne compte pas comme un gain » se lit sans "
             "ouvrir le fichier. C'est le critère retenu pour nommer les tests.\n")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="Génère docs/TESTS.md")
    ap.add_argument("--afficher", action="store_true", help="afficher sans écrire")
    args = ap.parse_args()
    texte = construire()
    if args.afficher:
        print(texte)
        return 0
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(texte, encoding="utf-8")
    print(f"[tests] {SORTIE.relative_to(BASE)} mis à jour.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
