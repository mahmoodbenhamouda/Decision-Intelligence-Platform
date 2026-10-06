# La boucle d'action — de l'alerte au résultat mesuré

## Le défaut que ce module corrige

Jusqu'ici, l'information ne circulait que dans un sens : l'ERP nourrissait
l'entrepôt, l'entrepôt nourrissait les modèles, les modèles nourrissaient les
agents, et les agents écrivaient un constat à l'écran. Là, tout s'arrêtait.

Personne n'était nommément chargé de traiter une alerte, rien ne disait si elle
avait été traitée, et surtout **aucun résultat ne revenait jamais**. Un modèle de
départ client pouvait se tromper toute l'année sans que rien dans le système ne
s'en aperçoive, et le directeur n'avait aucun moyen de savoir si tout ce
dispositif rapportait un dinar.

La boucle d'action ferme le circuit :

```
alerte (flotte d'agents)
      │
      ├─► la flotte CONFIE d'office l'exécution ───────┐   (délégation autonome)
      ├─► le directeur CONFIE une tâche à un employé ──┤
      │                                                │
   le client AGIT depuis son espace ───► tâche ────────┤
                                                       ▼
                                          l'employé traite et CONSIGNE
                                          le résultat (payé, signé, perdu…)
                                                       │
                          ┌────────────────────────────┤
                          ▼                            ▼
              « ce que les actions           export vers l'entrepôt
                ont rapporté »               (ml_engine/boucle.py)
                                                       │
                                                       ▼
                                          les modèles se confrontent
                                          au terrain au ré-entraînement
```

## Les trois rôles

| Rôle | Ce qu'il voit | Ce qu'il peut faire |
|---|---|---|
| `directeur` | tout | confier une tâche, réaffecter, déplacer une échéance, lire l'impact, régler et lancer la délégation autonome |
| `employe` | **seulement ses tâches** | prendre en charge, bloquer, clôturer avec un résultat |
| `client` | ses données à lui | agir sur ce qu'il consulte, suivre ses demandes |

Un employé n'a accès à **aucun** tableau de bord : le service de périmètre
(`api/services/perimetre.py`) le refuse côté serveur, et son écran est réduit à ses tâches — lui présenter un
cockpit dont chaque onglet renverrait un refus serait une fausse promesse.

Un client ne voit **rien** du suivi interne : `require_interne` protège tout le
routeur des tâches. Demander la tâche d'un collègue renvoie **404 et non 403**,
parce qu'un 403 confirmerait que cette tâche existe.

## Le schéma de données

Trois tables s'ajoutent dans la base applicative PostgreSQL :

| Table | Rôle |
|---|---|
| `taches` | qui fait quoi, pour quel client, pour quel montant, avec quelle issue |
| `evenements_tache` | l'histoire de chaque tâche : création, affectation, statuts, résultat |
| `client_requests` | les actions du client (table existante, étendue à cinq nouveaux types) |

Deux champs portent toute la mesure et ne doivent jamais être confondus :

- `montant_dt` — le montant **en jeu** au moment où la tâche est créée ;
- `resultat_montant_dt` — le montant **réellement obtenu**.

Les additionner produirait un gain fictif. Seuls les résultats de
`RESULTATS_GAGNANTS` (payé, devis signé, commande passée, client retenu) comptent
dans « récupéré grâce aux actions » ; un client perdu reste visible, mais du côté
de ce qui a été perdu.

## Les cinq actions du client

Elles sont **structurées** (un type, une référence, un montant, une date), pas du
texte libre : le serveur sait donc immédiatement quelle tâche créer, et le
résultat de cette tâche pourra plus tard être comparé à ce que le client avait
annoncé — c'est ce qui permettra de mesurer la part des promesses tenues.

| Action | Écran | Tâche créée | Gravité |
|---|---|---|---|
| `promesse_paiement` | facture en retard | proposer un échéancier | haute |
| `reclamation` | facture en retard | traiter une réclamation | haute |
| `devis_reponse` | devis en cours | relancer le devis | haute |
| `interet_produit` | produits proposés | appeler le client | moyenne |
| `reservation_stock` | produit tendu | commander / réserver | moyenne |

Une action du client crée une tâche **sans responsable** (`a_affecter`) : elle
arrive en tête du tableau de suivi, où le directeur l'attribue en un clic, plutôt
que de se perdre dans une boîte mail. À la clôture, la demande du client passe
automatiquement en « traitée » avec le commentaire de l'employé en réponse —
sans cette réponse, le client cesserait d'agir au bout de deux essais.

## La gravité devient une échéance

L'échéance par défaut découle de la gravité de l'alerte
(`DELAI_PAR_SEVERITE` : 2 / 5 / 10 / 20 jours). C'est le seul endroit du projet
où « urgent » se traduit en acte : sans cela, une alerte critique et une alerte
« à suivre » recevraient le même traitement, et le mot « critique » ne voudrait
plus rien dire.

## Ce qui repart vers les modèles

`ml_engine/boucle.py` copie les résultats dans l'entrepôt DuckDB, à chaque
`python scripts/retrain_all.py` :

| Table de l'entrepôt | Contenu | Ce que cela permet |
|---|---|---|
| `retours_taches` | une ligne par tâche : domaine d'origine, montant en jeu, issue, montant obtenu, délai | savoir si les alertes d'un domaine mènent réellement à un encaissement |
| `retours_clients` | une ligne par action client, dont `interet = 1` | donner enfin au moteur de recommandation le retour positif explicite qui lui manquait |

Les tables sont **recréées** à chaque export, jamais complétées : la source de
vérité reste la base applicative, où une tâche peut encore changer d'état ; un
export incrémental laisserait dans l'entrepôt des lignes périmées que plus rien
ne viendrait corriger.

L'export ne lève jamais d'exception. Si l'entrepôt est occupé par l'API (DuckDB
n'autorise qu'un seul écrivain), il le dit et ressort : ce n'est pas une panne du
projet, et le transfert se fera au passage suivant.

### Honnêteté sur l'état de l'apprentissage

L'écran de suivi affiche le nombre de retours déjà transférés. **Tant que ce
nombre est faible, les modèles restent entraînés sur l'historique seul** — et
c'est ce que l'interface dit, mot pour mot. Annoncer un « apprentissage continu »
avec trois retours en base serait une belle phrase et une fausse affirmation.

## L'API

| Méthode | Route | Qui | Rôle |
|---|---|---|---|
| GET | `/api/taches` | interne | le tableau de suivi (un employé n'y voit que ses tâches) |
| POST | `/api/taches` | directeur | confier une tâche, souvent depuis une alerte |
| GET | `/api/taches/{id}` | interne | détail + historique complet |
| PATCH | `/api/taches/{id}` | interne | avancer, réaffecter (directeur), clôturer avec un résultat |
| GET | `/api/taches/employes` | interne | à qui confier, avec la charge de chacun |
| GET | `/api/taches/confiees` | interne | les alertes déjà confiées, et à qui |
| GET | `/api/taches/impact` | interne | ce que les actions ont rapporté |
| GET | `/api/taches/boucle` | directeur | ce qui est déjà reparti vers les modèles |
| POST | `/api/portal/actions` | client | agir sur ce qu'il consulte |
| GET | `/api/portal/recommandations` | client | produits proposés, **sans aucun score** |

Le client voit les mêmes recommandations que l'écran commercial du directeur,
mais dépouillées : ni probabilité, ni espérance de signature, ni marge. Le même
calcul, deux lectures — montrer à un client la note que le système lui attribue
ne serait ni utile, ni sain.

## Les écrans

- **Priorités** : chaque carte d'action porte un bouton « Confier », qui ouvre
  une fenêtre **pré-remplie** (intitulé, domaine, client, montant en jeu) où il
  ne reste qu'à choisir la personne. Le collègue dont le métier correspond au
  domaine est proposé en premier, et la charge de chacun est affichée. Une fois
  l'action confiée, le bouton cède la place à **« Confiée à … »** : le nom de la
  personne qui s'en occupe, et non une coche.
- **Devis & marge** : relance d'un devis en un geste sur les trois premiers, et
  « Confier » sur chaque client à qui proposer des produits, les produits partant
  en consigne dans la tâche.
- **Suivi des actions** (nouvel onglet) : quatre chiffres clés, le montant obtenu
  mois par mois, la répartition des issues, puis le tableau de travail en cinq
  colonnes (à affecter, à faire, en cours, bloquée, terminée).
- **Mon espace** (client) : boutons « J'annonce une date » et « Je conteste » sur
  les factures en retard, « Ça m'intéresse » sur les produits proposés, et le
  suivi de ses demandes avec les réponses reçues.

## Une alerte ne se confie qu'une fois

L'information « cette alerte est déjà partie en tâche » vivait dans la mémoire
de l'onglet ouvert : après un rechargement de page, le bouton revenait, et la
même action pouvait être confiée deux fois — deux personnes appelant le même
client le même jour.

Elle vient désormais du serveur (`GET /api/taches/confiees`), et le contrôle qui
compte est lui aussi côté serveur : créer une seconde tâche pour une alerte déjà
ouverte est **refusé (409)**, avec le nom de la personne qui l'a en charge. Un
écran chargé avant l'affectation ne peut donc pas passer outre.

La clé est l'intitulé de l'alerte d'origine (`origine_titre`) : la seule valeur
stable d'un chargement à l'autre, le titre de la tâche étant modifiable au
moment de la confier. Le verrou porte sur les tâches **en cours** : une fois la
tâche terminée, la même alerte redevient confiable — si le problème revient, il
doit pouvoir repartir en action.

## La délégation autonome — la flotte confie elle-même l'exécution

Jusqu'ici, rien ne bougeait tant que le directeur n'avait pas ouvert l'onglet
Priorités et cliqué « Confier » sur chaque carte. La délégation autonome fait
ce tri à sa place, chaque jour, **pour le travail d'exécution seulement**.

### La frontière entre exécuter et décider

C'est l'agent qui émet un constat qui sait ce que son action demande. Il le
**déclare** dans le constat (clé `execution`) :

| Constat | Agent | `execution` | Pourquoi |
|---|---|---|---|
| Créances à relancer en priorité | Recouvrement | recouvrement · appel | relancer des comptes nommés |
| Clients qui ont fortement réduit leurs achats | Risque client | commercial · appel | rappeler des comptes nommés |
| Clients susceptibles de partir dans les 90 jours | Risque client | commercial · appel | idem, avant qu'ils partent |
| Devis à relancer en priorité | Commercial | commercial · relance du devis | des devis nommés |
| Clients dont la rentabilité va baisser | Commercial | commercial · visite | préparer la négociation compte par compte |
| Produits à proposer | Commercial | commercial · visite | présenter des produits à des clients nommés |
| Stock : ruptures et argent immobilisé | Stock & Appro. | logistique · commande | commander des références nommées |
| Client signalé par plusieurs domaines | Arbitre | le métier du premier domaine (créance d'abord) · appel | un seul interlocuteur pour ce compte |
| Trésorerie : encaissements et stock dormant | Trésorerie | **décision de direction** | renégocier les délais fournisseurs, décider un déstockage |
| Dépendance à un fournisseur | Stock & Appro. | **décision de direction** | choisir un second fournisseur engage l'entreprise |
| Types de clients les plus exposés au départ | Risque client | **décision de direction** | une politique pour tout un segment |

Un constat qui ne déclare rien n'est **jamais** délégué : l'autonomie ne se
suppose pas. Sur l'écran Priorités, les décisions de direction portent la
mention « Décision de direction » ; le bouton « Confier » reste disponible, le
directeur peut toujours les confier lui-même.

### Ce que fait un passage

```
flotte (périmètre complet) ──► arbitre ──► planifier()          agents/fleet/delegation.py (pur)
                                             │  1. clients multi-signaux
                                             │  2. constats dans l'ordre de l'arbitre,
                                             │     gravité haute ou urgente, exécution déclarée
                                             │  décisions de direction → mises de côté
                                             ▼
                        pour chaque proposition           api/services/delegation.py
                          déjà confiée (même alerte ouverte) ──► rien
                          traitée il y a < 14 jours          ──► rien
                          personne de ce métier / saturé     ──► « à affecter » (le directeur tranche)
                          sinon ──► confiée à l'employé du métier le moins chargé
                                             ▼
                        journal du passage (delegations_auto) + audit
```

| Règle | Valeur | Raison |
|---|---|---|
| Sans classement de l'arbitre | rien n'est confié | la gravité déclarée par chaque agent n'est pas une échelle commune |
| Gravités confiées d'office | haute, urgente | une alerte « à suivre » reste au jugement du directeur |
| Plafond par passage | 8 tâches | un défaut ne doit pas noyer l'équipe un matin |
| Charge maximale | 10 tâches ouvertes | au-delà, la tâche attend le directeur au lieu de surcharger quelqu'un |
| Carence après clôture | 14 jours | les données viennent d'exports : une créance payée hier y figure encore |
| Anti-doublon | même clé que le bouton « Confier » (`origine_titre`) | ni la flotte ni le directeur ne confient deux fois la même alerte |
| Passage planifié | un par jour, réservé en base (`jour_planifie` unique) | deux processus réveillés en même temps ne confient pas deux fois |

La clé d'un client multi-signaux, « Faire le point avec … », est fabriquée des
deux côtés (serveur et tableau de bord) : un test relit le fichier du tableau
de bord pour vérifier que les deux formulations n'ont pas divergé.

Une tâche confiée par la flotte s'écrit par le même chemin qu'une tâche
confiée par le directeur (`inserer_tache`) : même échéance selon la gravité,
même histoire (« Confiée d'office par la flotte d'agents — rang 1 du
classement… », « Confiée par la flotte à Sami — métier recouvrement, 2 tâches
déjà en cours »), même mesure. Seuls changent `delegation_auto = vrai` et
l'absence d'auteur humain.

### Qui décide de l'activer

Le **directeur**, depuis l'onglet « Suivi des actions » (carte « Délégation
autonome ») : activer ou couper, choisir l'heure (07:30 par défaut), lancer un
passage maintenant, relire le dernier passage — ce qui a été confié et à qui,
ce qui ne l'a pas été et pourquoi, et les décisions qui lui ont été laissées.
**Désactivée par défaut** : confier du travail à l'équipe n'est pas un
paramètre de déploiement.

Le réveil est une tâche de fond de l'API (`api/core/planificateur.py`), qui
demande chaque minute si le passage du jour est dû. Un serveur éteint à
l'heure prévue rattrape le passage à son redémarrage. Sans API démarrée en
permanence, le Planificateur de tâches Windows (ou cron) peut lancer
`python scripts/delegation_auto.py --si-du`, qui respecte le même réglage et
la même réservation du jour. `PLANIFICATEUR=0` coupe le réveil d'une instance.

Un passage planifié qui échoue (flotte indisponible) garde la réservation du
jour : il n'est pas relancé chaque minute. Le directeur voit l'échec et son
motif, et peut relancer à la main.

### Mesurer si elle mérite de rester active

`GET /api/taches/impact` renvoie `par_origine` : tâches, taux d'aboutissement
et montant obtenu, séparément pour la direction, la flotte et les clients.
L'export vers l'entrepôt porte la colonne `delegation_auto` : au
réentraînement, on sait ce que chaque voie a donné.

### API

| Méthode | Route | Qui | Rôle |
|---|---|---|---|
| GET | `/api/taches/delegation` | directeur | réglages, prochain passage, dernier passage (avec le briefing), historique |
| PUT | `/api/taches/delegation` | directeur | `{active, heure}` |
| POST | `/api/taches/delegation/lancer` | directeur | un passage maintenant (409 si un passage est déjà en cours) |

## Tests

`tests/test_delegation.py` (23 tests) démontre la frontière exécution /
décision, l'ordre de l'arbitre, l'absence de doublon avec les tâches confiées à
la main, la carence, la charge, la réservation du passage quotidien, le
cloisonnement des réglages et la mesure par origine.

`tests/test_boucle_action.py` (19 tests) démontre, dans l'ordre : le
cloisonnement des trois rôles, le fait qu'une tâche ne se clôture pas sans
résultat, qu'une issue perdue ne compte jamais comme un gain, qu'une action
client crée bien une tâche non affectée et reçoit une réponse à la clôture, et
que l'export produit des lignes exploitables — y compris les échecs, car un
modèle qui n'apprend que des succès n'apprend rien — et qu'une alerte déjà
confiée est refusée tant que sa tâche est ouverte.

## Comptes de démonstration

```bash
python -m api.auth.seed
```

| Compte | Identifiant | Mot de passe |
|---|---|---|
| Direction | `directeur@overlyne.tn` | `Directeur#2026` |
| Recouvrement (Sami) | `recouvrement@overlyne.tn` | `Employe#2026` |
| Commercial (Nadia) | `commercial@overlyne.tn` | `Employe#2026` |
| Logistique (Karim) | `logistique@overlyne.tn` | `Employe#2026` |

D'autres employés se créent depuis **Administration → Employé**, sans ligne de
commande.
