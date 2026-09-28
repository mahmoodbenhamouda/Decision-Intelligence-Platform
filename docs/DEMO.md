# Kit de démonstration — soutenance PFE

## 0. La règle qui fait la différence

Une démo rate rarement à cause du code : elle rate à cause du **réseau**, d'un **serveur non démarré**, d'un **cache corrompu** ou d'un **chemin non répété**. Les trois quarts de ce document servent à supprimer ces risques.

---

## 1. Trente minutes avant : le contrôle automatique

```bash
python scripts/preflight_demo.py
```

Le script vérifie et **donne la commande de correction** pour chaque problème : dépendances, entrepôt DuckDB, modèles entraînés, rapports de métriques, base d'authentification et comptes, secret JWT, dépendances frontend, modèle 3D de l'avatar, Tesseract, ports libres, suite de tests. Tant que vous n'avez pas `RÉSULTAT : prêt pour la démo ✓`, ne commencez pas.

### Installation en une commande (à faire une fois, bien avant le jour J)

```bash
python scripts/setup_tesseract_fr.py    # pack français de l'OCR, sans droits admin
python scripts/setup_avatar.py --check  # (optionnel) état du mode avatar
```

> L'avatar ne demande **aucune installation** : la tête 3D est générée localement par Three.js. Un GLB photoréaliste reste installable avec `--file`, mais n'est pas nécessaire.

### Démarrage (deux terminaux, dans cet ordre)

```bash
# Terminal 1 — API (attendre "Uvicorn running on http://127.0.0.1:9000")
.venv\Scripts\activate
python api\main.py

# Terminal 2 — frontend
cd frontend
npm run dev
```

Ouvrez ensuite http://localhost:4000/login, connectez-vous **une fois** en directeur, cliquez sur chaque onglet pour préchauffer les caches, puis déconnectez-vous. Le jour J, la première ouverture d'un onglet ne doit jamais faire attendre le jury.

---

## 2. Scénario minuté (12 minutes)

Fil narratif unique : **« transformer des données ERP dormantes en décisions chiffrées, traçables et cloisonnées. »** Chaque séquence y répond.

### Séquence 1 — Le problème (1 min, sans écran)

> « Overlyne distribue du matériel de diagnostic médical en Tunisie. Son ERP contient **128 000 factures sur 9 ans** — et personne ne les regarde. Les décisions se prennent à l'intuition : qui relancer, quel devis suivre, quel client est en train de partir. Ma plateforme répond à ces questions avec des chiffres. »

Annoncez le plan : *données → agents → décision → sécurité*.

### Séquence 2 — Le cockpit (2 min)

Connexion **directeur**. Onglet Synthèse.

- Pointez 3 indicateurs seulement : le **chiffre d'affaires** et le **délai moyen accordé** (bandeau du haut), puis les **créances au-delà de 60 j** (carte d'alerte). *« Le moteur calcule des dizaines d'indicateurs, j'en montre trois. »* (formules dans `docs/KPI_FORMULES.md`). Dites « délai moyen accordé », le mot affiché, et non « DSO » : l'ERP n'a pas de date de paiement (réponse prête dans `docs/KPI_FORMULES.md`, « Votre DSO est-il un vrai DSO ? »).
- Montrez les **quatre cartes d'alerte** — clients sur le départ, créances au-delà de 60 j, dépendance clients, taux de marge : chacune est chiffrée, et un clic mène à l'onglet qui l'explique.
- Une phrase sur la technique : *« DuckDB interroge les CSV bruts sans les charger en mémoire — l'entrepôt, un modèle en étoile, se reconstruit en une commande (`python -m etl.construire`), contrôles d'intégrité compris. »*

### Séquence 3 — La flotte d'agents (3 min) — **le cœur**

Onglet Copilote → question : **« Quelles sont mes priorités du moment ? »**

Pendant que ça calcule, expliquez le schéma (`docs/ARCHITECTURE_AGENTS.md`) :

> « Un orchestrateur LangGraph lance **cinq agents spécialistes en parallèle** : recouvrement, trésorerie, risque client, stock & approvisionnement, commercial. Ils n'ont pas la même nature, et je ne le cache pas : trois s'appuient sur des modèles appris, le recouvrement sur une règle qui a battu son modèle, et le stock sur des calculs déterministes et statistiques — parce que le registre a refusé les modèles qui n'apportaient rien. Deux collecteurs les alimentent — les indicateurs de l'entrepôt, puis **tous les modèles**, interrogés par une passerelle qui consulte le registre. À côté, un **volet fiabilité** audite les treize modèles du registre sans concurrencer les constats métier. Un arbitre hiérarchise, un rédacteur synthétise dans l'ordre de l'arbitre. Chaque agent est **isolé** : s'il échoue, le briefing sort quand même — c'est testé par injection de panne. »

Montrez la **trace d'exécution** : chaque étape est journalisée. Puis lisez une recommandation à voix haute et insistez : *« montant, client nommé, action — jamais de texte générique. »*

### Séquence 4 — L'OCR utile (2 min) — **l'effet « waouh » utile**

Onglet Documents & OCR, mode Facture. Déposez la facture papier préparée.

> « Le document est océrisé, les champs structurés sont extraits — numéro, dates, HT, TVA, TTC — la cohérence HT + TVA = TTC est vérifiée, et surtout : la facture est **rapprochée automatiquement de l'ERP**. »

Pointez le score et son explication (*montant identique · même date · nom similaire 100 %*), et la qualité de lecture affichée. Mentionnez les trois verdicts possibles : retrouvée, écart détecté, doublon probable.

### Séquence 5 — Le multi-comptes sécurisé (2 min 30) — **le passage qui rassure un jury**

1. Déconnexion → connexion **client** (`chu-charles-nicolle@overlyne.tn`). *« Il ne voit que ses données. »*
2. Onglet Mon espace : ses factures réelles. Sur une facture en retard, cliquez **« J'annonce une date »** — le client agit sur ce qu'il regarde, et cette action crée côté entreprise une tâche à traiter.
3. **La preuve** — ouvrez les outils développeur (F12), onglet Réseau, et montrez que même en modifiant la requête, le serveur renvoie son propre périmètre :
   > « L'isolation n'est pas un masquage d'interface. Le `client_code` est **forcé côté serveur**, et 31 tests le prouvent, dont : le client A demande les données du client B → il reçoit les siennes. »
4. Retour en directeur → onglet Administration : la demande du client est arrivée, vous la traitez. Montrez le **journal d'audit**.

### Séquence 5 bis — La boucle d'action (2 min) — **ce qui rend le projet réel**

> « Un tableau de bord qui signale un problème sans que personne ne soit chargé de le régler ne sert à rien. »

1. En **directeur**, onglet Priorités : sur la première carte, cliquez **« Confier »**. La fenêtre arrive pré-remplie — intitulé, domaine, client, montant en jeu — et propose la bonne personne, avec sa charge actuelle. Confiez la tâche.
2. Onglet **Suivi des actions** : la tâche apparaît dans sa colonne, avec son échéance calculée depuis la gravité de l'alerte.
3. Connectez-vous en **employé** (`recouvrement@overlyne.tn` / `Employe#2026`) : il ne voit **que ses tâches**, aucun chiffre d'affaires, aucun client. Il prend la tâche en charge, puis la clôture avec un résultat : *payé, 12 400 DT*.
4. Retour en **directeur** : la tuile « Récupéré grâce aux actions » a bougé, et le graphe mensuel aussi.
5. La phrase à dire :
   > « Les résultats ne servent pas qu'à l'écran : ils repartent dans l'entrepôt au ré-entraînement. La recommandation de produits reçoit ainsi ses premiers retours réels — un client qui dit "ça m'intéresse" est l'étiquette qui manquait. Et tant que ces retours sont peu nombreux, l'interface le dit : les modèles restent entraînés sur l'historique. »

Détails : `docs/BOUCLE_ACTION.md`.

### Séquence 6 — La rigueur scientifique (1 min 30) — **ce qui distingue un ingénieur**

Ouvrez `reports/METRICS_REPORT.md` :

> « Mon premier modèle de crédit affichait une AUC de 0,9975. **Je l'ai supprimé.** En mesurant, j'ai vu que l'écart-type du délai à l'intérieur d'un client est de 1 jour contre 20 au global : le délai est une constante contractuelle. Une règle à un seul seuil atteignait déjà 0,918 — mon modèle ne faisait que mémoriser le contrat. Je l'ai reconstruit sur le seul cas où la question se pose vraiment, un client nouveau. Il obtient 0,81 en validation par client… mais **0,57 sur des clients réellement nouveaux et postérieurs**. Donc je ne le déploie pas. Ce qui tourne en production est une règle déterministe, et les clients sans historique reçoivent le taux de base. »

C'est le moment le plus important de la soutenance. Un jury retient cette phrase.

### Séquence 7 — Clôture (30 s)

> « 642 tests automatisés, intégration continue, déploiement conteneurisé en une commande. Les limites sont documentées : pas de date de paiement réelle, pas de stock ERP. »

Terminez par la phrase d'unification :

> « Une plateforme qui transforme des données ERP dormantes en décisions chiffrées, avec la traçabilité et l'isolation qu'exige un usage multi-clients réel. »

---

## 3. Plans B (à connaître par cœur)

| Panne | Ce que vous faites | Ce que vous dites |
|---|---|---|
| **Pas de réseau** | Rien à faire | « Tout fonctionne hors-ligne : replis déterministes du copilote, tête 3D procédurale générée localement, scraper avec cache. Le projet ne dépend d'aucun CDN. » |
| **API lente au démarrage** | Attendre, ne pas relancer | « Le premier import charge pandas, DuckDB et scikit-learn. » Démarrez l'API **avant** d'entrer en salle. |
| **Erreur Turbopack** (cache corrompu) | Supprimer `frontend\.next`, relancer `npm run dev` | Ne commentez pas, corrigez en silence. |
| **PostgreSQL injoignable** | Commenter `AUTH_DATABASE_URL` dans `.env` → repli SQLite | « La base d'auth est portable : SQLAlchemy, une URL à changer. » |
| **Pas de clé LLM / quota** | Continuer | « Le copilote a un repli déterministe chiffré : la démo ne dépend pas d'un service externe. » **C'est un argument, pas une excuse.** |
| **Tesseract absent** | Utiliser un PDF texte | « L'OCR se dégrade proprement : les PDF natifs restent exploitables. » |
| **Avatar en mode orbe** | Continuer | « Chaîne de repli : GLB local optionnel → tête 3D procédurale → orbe SVG si WebGL absent. » |
| **Avatar en tête procédurale** | C'est le mode NORMAL | « La tête est générée en Three.js sur la machine, sans aucun téléchargement : mêmes visèmes, mêmes émotions, aucune dépendance réseau. » |
| **Question à laquelle vous ne savez pas répondre** | *« Je ne l'ai pas mesuré, mais voici comment je le testerais : … »* | Ne jamais inventer un chiffre. |

**Filet de sécurité ultime** : enregistrez une **vidéo de la démo complète** la veille (le bouton « Enregistrer une démo » de l'avatar, plus une capture d'écran globale). Si tout s'effondre, vous projetez la vidéo et commentez. Une démo enregistrée vaut infiniment mieux qu'un écran noir.

---

## 4. Les questions qui tombent, et vos réponses

**« Une AUC de 0,997 sur le crédit, ce n'est pas de l'overfitting ? »**
> C'était pire que de l'overfitting : c'était une **tautologie**, et je l'ai retirée. Le problème n'était pas le modèle mais la question posée. Le délai de crédit est contractuel — écart-type de 1,05 j à l'intérieur d'un client contre 20,72 j au global. Le modèle recevait la moyenne des délais passés du client et devait prédire le délai suivant : il recopiait le contrat. Une règle à un seul seuil atteint 0,918 sans apprentissage, et reproduit la cible dans 86,5 % des cas. Un modèle qui redit ce que le contrat dit déjà n'a aucune valeur opérationnelle.

**« Et votre nouveau modèle, alors ? »**
> J'ai gardé le ML uniquement là où la question se pose : un **client nouveau**, pour lequel aucun historique n'existe par construction. Protocole GroupKFold par client — le modèle n'a jamais vu la moindre facture du client de test : AUC 0,8116. Mais ce protocole brasse les périodes. J'ai donc ajouté le protocole strict — client jamais vu **et arrivé après la coupure**, c'est-à-dire la situation réelle de production : **0,5664**, sous ma régression logistique de référence à 0,6729. L'écart entre les deux mesure une fuite temporelle. **Je ne déploie pas.** C'est la même règle d'acceptation que sur la prévision de demande.

**« Vous avez donc trois modèles non déployés. C'est un échec ? »**
> C'est l'inverse. Ces refus viennent tous d'un protocole de validation qui a fonctionné, et chacun a été détecté par un garde-fou automatisé, pas par chance. Le garde-fou « AUC > 0,98 = fuite suspectée » a par exemple révélé que le champ `MODEREGL` épelle la réponse : `C060` signifie « CHÈQUE 60 JOURS », et vaut 61 jours de délai médian. Seul, ce champ donne 0,934. Un projet qui ne refuse jamais rien n'a pas de critère de refus.

**« Pourquoi pas de deep learning partout ? »**
> Parce que je l'ai mesuré. Sur la prévision de trésorerie, le backtest walk-forward montre qu'une baseline naïve saisonnière fait 25,7 % de MAPE contre 26,4 % pour Holt-Winters. Ajouter de la complexité sans gain mesuré serait de l'ingénierie décorative.

**« Vos données sont-elles réelles ? »**
> L'ERP est réel : 121 763 factures de vente et 5 761 avoirs, pour 1 137 clients. L'export source compte 128 848 lignes : l'écart vient de 1 324 factures y figurant en double, détectées sur le numéro de pièce et écartées à la construction de l'entrepôt.
>
> Sur la profondeur d'historique, je suis précis, parce que les dates brutes sont trompeuses. La première facture porte janvier 2017 et la dernière avril 2026, mais **l'historique réellement exploitable court de 2021 à 2026**. 2019 et 2020 sont absentes de **toutes** les sources — ventes, lignes, achats, devis — ce qui exclut un défaut d'export et pointe une bascule d'ERP ou une reprise de dossier. 2017 et 2018 ne portent que 1 329 factures, soit 1,1 % du total, contre 20 333 pour la seule année 2021 : ce sont des résidus de migration, pas des années d'exploitation. Annoncer « 2017–2026 » serait revendiquer neuf ans d'historique là où il y en a cinq et demi. En revanche, deux limites sont assumées et documentées : pas de date de paiement réelle (je modélise le délai accordé, un proxy explicite), et pas de données de stock (je modélise la demande servie).

**« Comment savez-vous que votre chiffre d'affaires est juste ? »**
> Parce que je l'ai audité, et qu'il ne l'était pas. Le CA affiché était de 290,5 M DT ; il est de **274,7 M DT**. L'écart de 15,8 M, soit 5,44 %, vient de deux erreurs cumulées. D'abord les avoirs : `TTC_DEV` est toujours positif, y compris pour une note de crédit, et le sens comptable est porté par `MONTANTSIGNE_DEV`. Sommer le TTC ajoutait donc les avoirs au chiffre d'affaires au lieu de les en retrancher — chacun comptait deux fois, soit 14,8 M. Ensuite les doublons : `ENT_ID` est un identifiant technique d'export, unique par construction, donc structurellement incapable de détecter un doublon ; la clé métier est `PIECENOFULL`, sur laquelle 1 324 factures se répètent, pour 1,05 M. Le détail est reproductible par `scripts/audit_ca_corrige.py`, et neuf tests figent le résultat.
>
> Un point mérite d'être souligné : le panier moyen, lui, n'a pratiquement pas bougé — 2 255 contre 2 256 DT. Numérateur et dénominateur étaient faux dans la même proportion. Cet indicateur était juste par compensation, pas par justesse, et aucun contrôle de vraisemblance ne l'aurait signalé.

**« Comment garantissez-vous qu'un client ne voit pas les données d'un autre ? »**
> L'isolation est côté serveur, pas dans l'interface. Un service dédié (`api/services/perimetre.py`) écrase le périmètre demandé par le `client_code` du jeton JWT. Vingt-deux tests le prouvent, dont un où le client A réclame explicitement les données du client B et reçoit les siennes. Les ressources internes renvoient 403.

**« Qu'est-ce qui se passe si un agent plante ? »**
> Chaque nœud est enveloppé par un décorateur `_safe_node` : l'exception devient une trace d'erreur, le briefing sort avec les agents valides. C'est testé par injection de panne. Et si LangGraph est absent, un repli séquentiel exécute les mêmes agents.

**« Combien de temps pour déployer chez un client ? »**
> `docker compose up -d --build` puis une commande de seed. Trois conteneurs : PostgreSQL, l'API, le frontend. L'intégration continue vérifie les tests, le typage et la construction de l'image à chaque commit.

**« Quelle est la prochaine étape ? »**
> Trois choses, dans l'ordre : brancher les vraies dates de paiement pour passer du délai accordé au retard constaté, ajouter à la prévision de la demande le calendrier des appels d'offres et les dates de commande, et passer le rate-limiting sur Redis pour un déploiement multi-instances.

---

## 5. Checklist de la veille

- [ ] `python scripts/preflight_demo.py` → tout vert
- [ ] `python -m pytest tests/ -q` → 642 tests verts (capture d'écran gardée)
- [ ] Avatar vérifié : `python scripts/setup_avatar.py --check` (tête procédurale = OK)
- [ ] Facture papier imprimée **et** sa version image sur le bureau, testée dans l'onglet OCR
- [ ] Vidéo de secours de la démo enregistrée
- [ ] Démo répétée **3 fois** en entier, chronomètre en main
- [ ] Mots de passe notés sur papier (pas seulement dans un gestionnaire)
- [ ] Deux terminaux préparés, commandes déjà tapées (prêtes à valider)
- [ ] Navigateur : onglets ouverts sur `/login`, `reports/METRICS_REPORT.md`, `docs/ARCHITECTURE_AGENTS.md`
- [ ] Zoom du navigateur à 110–125 % (le jury est loin de l'écran)
- [ ] Mode « Ne pas déranger » activé, notifications coupées
- [ ] Chargeur, adaptateur HDMI, clé USB avec le projet

---

## 6. Trois erreurs qui coûtent des points

1. **Montrer du code source.** Sauf si on vous le demande. Un jury juge le raisonnement et le résultat ; le code, il le lit dans le mémoire.
2. **Dire « c'est juste une démo ».** Vous dévaluez votre travail. Dites plutôt « voici le comportement en conditions réelles ».
3. **Masquer une limite.** Si un jury découvre lui-même une faiblesse que vous n'avez pas mentionnée, votre crédibilité chute d'un coup. Si vous l'annoncez avant, elle monte. C'est exactement pour cela que `METRICS_REPORT.md` contient une section « limites assumées ».
