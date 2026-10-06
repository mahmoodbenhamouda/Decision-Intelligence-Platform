# Ce que les tests démontrent

*Tableau généré le 29/09/2026 par `python scripts/tableau_tests.py` — les comptages sont relus dans la suite, jamais recopiés.*

**666 tests** répartis en 12 familles. Le mémoire cite ce tableau, pas la liste des tests.

## Vue d'ensemble

| Famille | Tests | Ce qui est démontré |
|---|---:|---|
| **Sécurité et isolation** | 53 | Un client ne peut pas lire les données d'un autre, même en manipulant la requête. |
| **Boucle d'action** | 42 | De l'alerte au résultat mesuré, avec un cloisonnement strict des rôles ; la flotte confie l'exécution, jamais la décision. |
| **Flotte d'agents** | 99 | Cinq spécialistes et un volet fiabilité produisent des constats chiffrés, un agent en panne n'arrête pas le briefing, et le copilote n'affiche aucun montant non sourcé. |
| **Modèles — absence de fuite** | 100 | Aucun modèle ne regarde l'avenir, et aucun n'est déployé sans gain confirmé sur une référence. |
| **Entrepôt de données** | 21 | L'entrepôt se construit selon ses règles, et un contrôle en échec annule toute la construction. |
| **Intégrité des chiffres** | 75 | Chaque indicateur se recompose à partir des factures, et une incohérence fabriquée est détectée. |
| **Stock** | 18 | Filtres et bornes du module de stock, sur des données simulées explicitement marquées. |
| **Documents et OCR** | 165 | Une facture réelle est lue champ par champ, puis rapprochée de l'ERP. |
| **Comptes** | 10 | Les identifiants dérivés du nom de l'établissement restent uniques et stables. |
| **Explicabilité** | 10 | Chaque justification affichée tient sa promesse : décomposition exacte, parts cohérentes, aucun jargon. |
| **Architecture** | 43 | Les règles de l'architecture en couches sont vérifiées sur le code, pas seulement décrites. |
| **Robustesse** | 30 | Chaque repli est exercé : le service dégrade au lieu de tomber. |

## Le détail, fichier par fichier

### Sécurité et isolation

| Fichier | Tests | Ce qui est démontré |
|---|---:|---|
| `test_auth_rbac.py` | 31 | Aucun accès sans jeton valide ; un client ne peut pas lire les données d'un autre, même en manipulant la requête ; la force brute est bloquée ; la déconnexion révoque le jeton immédiatement. |
| `test_admin_portal.py` | 22 | Gestion des comptes par le directeur : unicité du code client, suppression qui conserve le journal d'audit, cloisonnement des demandes. |

### Boucle d'action

| Fichier | Tests | Ce qui est démontré |
|---|---:|---|
| `test_delegation.py` | 23 | La flotte confie elle-même le travail d'exécution, jamais une décision de direction ; elle ne confie jamais deux fois la même alerte, ménage la charge de l'équipe et ne fait qu'un passage planifié par jour. |
| `test_boucle_action.py` | 19 | De l'alerte au résultat mesuré : un employé ne voit que ses tâches, une tâche ne se clôture pas sans résultat, une issue perdue ne compte jamais comme un gain, et les résultats repartent vers les modèles. |

### Flotte d'agents

| Fichier | Tests | Ce qui est démontré |
|---|---:|---|
| `test_passerelle_agents.py` | 37 | Chaque modèle du registre a un consommateur réel ; un modèle refusé ou retiré n'est jamais présenté comme servi ; aucun terme technique n'apparaît dans ce que lit un dirigeant ou un client. |
| `test_fleet.py` | 30 | Les cinq spécialistes produisent des constats chiffrés et sourcés ; la panne d'un volet n'emporte pas l'autre ; le rédacteur suit l'ordre de l'arbitre et ne s'exécute qu'une fois (jointure avec le volet fiabilité). |
| `test_copilot_stock_client.py` | 22 | Le copilote route la question vers le bon thème, ne fabrique aucun montant, et reste reproductible d'une exécution à l'autre. |
| `test_copilote.py` | 10 | Le graphe du copilote suit l'ordre de ses nœuds ; une réponse du modèle de langage qui cite un montant absent des données est écartée, et le champ `via` dit d'où vient la réponse affichée. |

### Modèles — absence de fuite

| Fichier | Tests | Ce qui est démontré |
|---|---:|---|
| `test_ml_stock.py` | 20 | Séparation par produit, aucune variable future, déploiement autorisé seulement si le gain sur la référence est confirmé. |
| `test_ml_credit.py` | 17 | Le modèle de crédit est évalué sur des clients réellement nouveaux, et c'est une règle mesurée qui est servie, pas le modèle rejeté. |
| `test_ml_churn.py` | 15 | Aucune variable ne regarde après la date d'observation, aucune n'est la cible déguisée, et le registre refuse un modèle dont le rapport manque. |
| `test_segmentation.py` | 14 | La typologie de clientèle est stable, interprétable et reproductible. |
| `test_demande_reference.py` | 13 | La prévision par référence ne lit aucun mois postérieur à l'origine ; validation et test sont disjoints ; le modèle appris n'est servi que s'il bat la règle simple de 2 points avec un intervalle entièrement positif ; sans rapport, rien n'est servi. |
| `test_marge_conversion.py` | 11 | Marge et conversion des devis : cohérence des montants et des seuils. |
| `test_demand_engine.py` | 10 | La prévision de demande est mesurée hors période et bornée par une référence naïve. |

### Entrepôt de données

| Fichier | Tests | Ce qui est démontré |
|---|---:|---|
| `test_entrepot.py` | 21 | Sur des exports fabriqués pour le test : les vues lues par l'application gardent leurs colonnes, les avoirs et les doublons sont traités, les dimensions sont conformes, et une construction dont un contrôle échoue est annulée d'un bloc. |

### Intégrité des chiffres

| Fichier | Tests | Ce qui est démontré |
|---|---:|---|
| `test_coherence_financiere.py` | 25 | Chaque indicateur se recompose : CA net = ventes − avoirs, marge = CA − coût, aucun doublon de pièce, et un contrôle d'intégrité détecte une incohérence fabriquée exprès. |
| `test_radar_financier.py` | 20 | Le radar financier reconnaît les établissements publics avec la règle des modèles de demande (« C.H.U. » oui, « LABORATOIRE KETATA » non), sur la fenêtre de l'exposition récente : sa part publique est un vrai pourcentage, et une erreur de calcul est journalisée, jamais avalée. |
| `test_payment_scenario.py` | 12 | Les scénarios d'encaissement restent bornés et cohérents avec l'encours. |
| `test_integrite_ca.py` | 9 | Le chiffre d'affaires est conforme à l'audit manuel des sources, et le montant brut erroné d'avant correction n'est plus atteignable. |
| `test_semantique_erp.py` | 9 | Les colonnes de l'ERP sont interprétées comme le métier les définit (montant signé, avoirs, nature de paiement). |

### Stock

| Fichier | Tests | Ce qui est démontré |
|---|---:|---|
| `test_stock.py` | 18 | Filtres, agrégations et bornes du module de stock, sur données simulées explicitement marquées comme telles. |

### Documents et OCR

| Fichier | Tests | Ce qui est démontré |
|---|---:|---|
| `test_layoutlm.py` | 55 | LayoutLMv3 décode les étiquettes en champs, la fusion avec les règles ne reprend jamais un montant invraisemblable, le chiffre des milliers est recollé sans faux positif, et le modèle n'est servi que si le registre l'autorise. |
| `test_ocr.py` | 32 | Extraction du texte, qualité de lecture, et repli propre quand Tesseract est absent. |
| `test_ocr_import.py` | 23 | Une facture réelle est lue champ par champ, l'identité comptable HT + TVA = TTC est vérifiée, et le rapprochement avec l'ERP distingue les raisons sociales proches. |
| `test_ocr_achats_ventes.py` | 18 | Un achat ne gonfle jamais les ventes ; le sens est détecté depuis l'identité de l'entreprise ; un doublon exige le même numéro ET le même fournisseur ; les corrections de l'utilisateur sont conservées. |
| `test_ocr_rapprochement.py` | 12 | Une facture importée est rapprochée de l'ERP : rapprochée, écart détecté, introuvable, hors période ou doublon probable. |
| `test_ocr_api_import.py` | 11 | De la lecture à l'enregistrement par l'API : un sens inconnu est refusé plutôt que deviné, un compte client reste dans son périmètre, un identifiant de lecture forgé est rejeté, un même document est repéré. |
| `test_ocr_echeancier.py` | 8 | L'échéancier compte le net à payer et non le TTC, lit ou déduit l'échéance, ne double pas une facture déjà dans l'ERP et retire les factures réglées. |
| `test_ocr_apprentissage.py` | 4 | Les corrections faites à l'écran mesurent l'exactitude réelle de la lecture en production. |
| `test_ocr_integration_production.py` | 2 | La valeur corrigée en production devient la vérité étiquetée, et la fusion se fait dans une copie du jeu d'entraînement, jamais dans l'original. |

### Comptes

| Fichier | Tests | Ce qui est démontré |
|---|---:|---|
| `test_emails.py` | 10 | Les identifiants de connexion dérivés du nom de l'établissement sont uniques, sans accent et stables. |

### Explicabilité

| Fichier | Tests | Ce qui est démontré |
|---|---:|---|
| `test_explication.py` | 10 | La décomposition d'un score linéaire est exacte au flottant près, les parts affichées totalisent 100 %, aucune phrase ne contient de jargon, et un modèle de forme inattendue ne produit aucune explication plutôt qu'une explication approximative. |

### Architecture

| Fichier | Tests | Ce qui est démontré |
|---|---:|---|
| `test_architecture_api.py` | 43 | Les règles de l'architecture en couches sont vérifiées sur le code : une route ne calcule rien, un service ne connaît pas FastAPI, l'API passe par la passerelle des modèles, et toute erreur métier a un code HTTP. |

### Robustesse

| Fichier | Tests | Ce qui est démontré |
|---|---:|---|
| `test_modules_branches.py` | 30 | Les chemins de repli de chaque module sont exercés : entrepôt absent, modèle manquant, rapport illisible — le service dégrade, il ne tombe pas. |

## Les tests à citer

Ces **22 tests** portent chacun une affirmation forte du mémoire. Ils se rejouent en une commande, en moins de deux minutes :

```bash
python -m pytest -m vitrine -v
```

| Affirmation | Test |
|---|---|
| Cinq échecs de connexion suffisent à bloquer une tentative de force brute | `test_auth_rbac.py::test_rate_limiting_apres_5_echecs` |
| La déconnexion révoque le jeton sur-le-champ, sans attendre son expiration | `test_auth_rbac.py::test_logout_revoque_le_jeton_immediatement` |
| Le périmètre d'un client est forcé côté serveur : demander les données d'un autre renvoie les siennes | `test_auth_rbac.py::test_client_scope_force_sur_dashboard` |
| La tâche d'un collègue renvoie 404 — un 403 confirmerait son existence | `test_boucle_action.py::test_une_tache_dun_collegue_est_introuvable` |
| Un client perdu ne gonfle jamais le montant récupéré grâce aux actions | `test_boucle_action.py::test_une_issue_perdue_ne_compte_pas_comme_un_gain` |
| Une alerte déjà confiée est refusée par le serveur : un client n'est jamais relancé deux fois pour la même raison | `test_boucle_action.py::test_une_alerte_deja_confiee_ne_se_confie_pas_une_seconde_fois` |
| Une réponse du copilote qui cite un montant inventé est écartée, et la source affichée est celle qui a réellement répondu | `test_copilote.py::test_via_dit_d_ou_vient_la_reponse` |
| La flotte confie l'exécution, jamais la décision : une action qui engage l'entreprise reste au directeur | `test_delegation.py::test_une_decision_de_direction_n_est_jamais_confiee_d_office` |
| La flotte ne recrée jamais une alerte déjà confiée, par elle-même ou par le directeur | `test_delegation.py::test_la_flotte_ne_confie_jamais_deux_fois_la_meme_alerte` |
| La prévision par référence ne lit aucun mois postérieur à l'origine : réécrire le futur ne change rien | `test_demande_reference.py::test_aucune_variable_ne_lit_le_futur` |
| Dans l'entrepôt, un avoir est déduit du chiffre d'affaires et une facture exportée deux fois n'est comptée qu'une fois | `test_entrepot.py::test_un_avoir_est_deduit_et_un_doublon_compte_une_fois` |
| Aucun fait de l'entrepôt ne pointe vers un client, un produit ou une date inconnus : c'est contrôlé à chaque construction | `test_entrepot.py::test_aucun_fait_orphelin_de_sa_dimension` |
| L'explication affichée reconstitue exactement le score du modèle, au flottant près | `test_explication.py::test_la_somme_des_contributions_reconstitue_le_score_du_modele` |
| Aucune justification affichée ne contient de terme technique ni de nom de variable | `test_explication.py::test_aucune_phrase_affichee_ne_contient_de_jargon` |
| Une panne injectée dans un agent ne supprime pas le briefing : il sort amputé, jamais vide | `test_fleet.py::test_briefing_survit_a_un_agent_en_panne` |
| Le chiffre d'affaires publié est conforme à l'audit manuel des sources | `test_integrite_ca.py::test_ca_net_conforme_a_l_audit` |
| Aucune variable du modèle de départ client n'est la cible déguisée | `test_ml_churn.py::test_aucune_variable_n_est_la_cible_deguisee` |
| Un modèle n'est déployé que si son gain sur la référence est confirmé | `test_ml_stock.py::test_modele_deploye_uniquement_si_gain_confirme` |
| Sur une facture lue par OCR, HT + TVA = TTC est vérifié, pas supposé | `test_ocr_import.py::test_identite_comptable_verifiee` |
| Chaque modèle du registre a un consommateur réel : un agent métier, ou la chaîne OCR pour la lecture de factures | `test_passerelle_agents.py::test_chaque_modele_du_registre_atteint_un_agent` |
| Aucun terme technique n'apparaît dans ce que lisent un dirigeant ou un client | `test_passerelle_agents.py::test_aucun_terme_technique_dans_les_textes_lus_par_un_dirigeant` |
| Un modèle refusé ou retiré ne peut pas être présenté comme servi | `test_passerelle_agents.py::test_un_modele_refuse_ou_retire_n_est_jamais_presente_comme_servi` |

## Comment lire un échec

Un test qui échoue nomme la règle métier violée, pas une ligne de code : « une issue perdue ne compte pas comme un gain » se lit sans ouvrir le fichier. C'est le critère retenu pour nommer les tests.
