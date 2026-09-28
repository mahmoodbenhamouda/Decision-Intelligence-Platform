# Protocole de validation métier

> **Ce document est le seul du projet qui ne peut pas être rempli par son auteur.**
> Il doit l'être par une personne de l'entreprise qui connaît les clients, les
> produits et les fournisseurs. Sans cette signature, la plateforme reste un
> exercice technique validé sur lui-même.

## Pourquoi cette étape, et pourquoi elle ne se remplace pas

Tous les indicateurs de ce projet sont **internes** : une AUC compare des
prédictions à des étiquettes calculées sur les mêmes données. Elle ne dit rien de
la pertinence métier.

Un exemple concret le montre. Le modèle de décrochage signale 28 clients à
risque. Rien dans les données ne distingue :

- un client qui **cesse réellement** de commander — vraie détection ;
- un client dont les commandes passent par une **autre entité** du groupe ;
- un client saisonnier dont l'absence est **normale** à cette période ;
- un client dont le marché public a été **suspendu**, indépendamment de nous.

Les quatre produisent le même signal statistique. Seul un responsable commercial
peut les séparer. C'est précisément ce que cette grille mesure.

---

## Grille 1 — Décrochage client

**À faire remplir par :** responsable commercial ou direction
**Support :** onglet Rétention, liste des clients à relancer
**Durée estimée :** 20 minutes

Pour chacun des 10 premiers clients de la liste :

| # | Client | Le signal est-il justifié ? | Si non, pourquoi ? | Action déclenchée |
|---|---|---|---|---|
| 1 | | ☐ oui ☐ non ☐ ne sait pas | | ☐ appel ☐ aucune ☐ autre |
| 2 | | ☐ oui ☐ non ☐ ne sait pas | | ☐ appel ☐ aucune ☐ autre |
| 3 | | ☐ oui ☐ non ☐ ne sait pas | | ☐ appel ☐ aucune ☐ autre |
| 4 | | ☐ oui ☐ non ☐ ne sait pas | | ☐ appel ☐ aucune ☐ autre |
| 5 | | ☐ oui ☐ non ☐ ne sait pas | | ☐ appel ☐ aucune ☐ autre |
| 6 | | ☐ oui ☐ non ☐ ne sait pas | | ☐ appel ☐ aucune ☐ autre |
| 7 | | ☐ oui ☐ non ☐ ne sait pas | | ☐ appel ☐ aucune ☐ autre |
| 8 | | ☐ oui ☐ non ☐ ne sait pas | | ☐ appel ☐ aucune ☐ autre |
| 9 | | ☐ oui ☐ non ☐ ne sait pas | | ☐ appel ☐ aucune ☐ autre |
| 10 | | ☐ oui ☐ non ☐ ne sait pas | | ☐ appel ☐ aucune ☐ autre |

**Résultat :** ____ / 10 signaux jugés justifiés.

**Question ouverte, et elle est la plus importante :** un client qui vous inquiète
**n'apparaît-il pas** dans cette liste ? Lequel, et pourquoi pensez-vous qu'il
manque ?

> Cette question cherche les **faux négatifs**, que le modèle ne peut pas voir
> par lui-même. Un client oublié coûte plus cher qu'une alerte inutile.

---

## Grille 2 — Priorités de recouvrement

**À faire remplir par :** responsable financier ou recouvrement
**Support :** onglet Risque crédit
**Durée estimée :** 15 minutes

| Question | Réponse |
|---|---|
| Les 5 premiers débiteurs correspondent-ils à vos préoccupations réelles ? | ☐ oui ☐ partiellement ☐ non |
| Le classement par montant est-il le bon critère de priorité ? | ☐ oui ☐ non — préférable : ________ |
| Le montant de 10,9 M DT au-delà de 60 jours vous paraît-il crédible ? | ☐ oui ☐ trop élevé ☐ trop bas |
| La distinction « délai accordé » / « retard constaté » est-elle claire ? | ☐ oui ☐ non |

**Point de vérification critique.** La plateforme ne connaît **aucune date de
règlement** — l'export ERP n'en contient pas. Elle mesure donc le délai *accordé*,
non le retard *constaté*.

Cette distinction est-elle comprise par les utilisateurs ? ☐ oui ☐ non

> Si la réponse est « non », c'est un défaut d'interface, pas de modèle. Il doit
> être corrigé avant tout déploiement réel : un utilisateur qui lit « créances à
> risque » et comprend « impayés » prendra de mauvaises décisions.

---

## Grille 3 — Stock et réapprovisionnement

**À faire remplir par :** responsable achats ou logistique
**Support :** onglet Stock
**Durée estimée :** 15 minutes

**Avertissement à lire avant de remplir.** Les **quantités** en stock sont
simulées : l'ERP n'en tient pas l'inventaire. Les prix et la demande sont réels.
Cette grille valide donc la **méthode**, pas les valeurs.

| Question | Réponse |
|---|---|
| Les produits signalés à commander sont-ils plausibles ? | ☐ oui ☐ non |
| Les délais fournisseurs utilisés correspondent-ils à la réalité ? | ☐ oui ☐ non — écart : ______ |
| La logique « livraison plus longue que le stock restant » est-elle celle que vous appliquez ? | ☐ oui ☐ non |
| Disposez-vous d'un inventaire réel qui pourrait remplacer la simulation ? | ☐ oui ☐ non |

> La dernière question est la plus utile pour la suite : si un inventaire existe
> quelque part, la principale limite du projet disparaît.

---

## Grille 4 — Briefing automatique

**À faire remplir par :** direction
**Support :** briefing de la flotte multi-agents
**Durée estimée :** 10 minutes

| Question | Réponse |
|---|---|
| Le briefing est-il compréhensible sans explication ? | ☐ oui ☐ non |
| Les trois priorités correspondent-elles aux vôtres ? | ☐ oui ☐ partiellement ☐ non |
| Avez-vous repéré une affirmation **fausse** ? | ☐ non ☐ oui : ____________ |
| Avez-vous repéré un **chiffre inventé** (absent de vos données) ? | ☐ non ☐ oui : ____________ |
| Combien de temps vous faudrait-il pour produire cette synthèse à la main ? | ______ heures |

> Les deux questions sur les erreurs sont délibérées. Le rédacteur automatique a
> déjà été pris à fabriquer des chiffres — remises, objectifs, volumes — et à
> proposer d'écouler des produits en rupture. Des règles l'en empêchent
> désormais, mais **seul un lecteur métier peut confirmer** qu'elles tiennent.
>
> La dernière question sert à chiffrer le temps épargné, seul apport aujourd'hui
> déclaré « non mesurable » faute de point de comparaison.

---

## Synthèse à joindre au mémoire

À compléter une fois les grilles remplies :

| Élément | Résultat |
|---|---|
| Date de la validation | |
| Personne(s) ayant validé | |
| Fonction | |
| Signaux de décrochage justifiés | ____ / 10 |
| Priorités de recouvrement pertinentes | ☐ oui ☐ partiellement ☐ non |
| Erreur factuelle relevée dans le briefing | ☐ non ☐ oui |
| Temps de production manuelle estimé | ______ heures |
| Utilisation envisagée | ☐ quotidienne ☐ hebdomadaire ☐ mensuelle ☐ aucune |

**Commentaire libre de l'entreprise** (le plus utile de tout le document — ce qui
manque, ce qui gêne, ce qui servirait vraiment) :

```
_______________________________________________________________________

_______________________________________________________________________

_______________________________________________________________________
```

---

## Comment exploiter le résultat, y compris s'il est mauvais

**Si les retours sont bons**, le mémoire peut affirmer que les sorties ont été
confrontées au terrain, avec le taux de justesse constaté. C'est la seule preuve
externe qu'un projet de ce type puisse produire.

**Si les retours sont mauvais**, c'est un résultat également publiable — à
condition d'être analysé. Un signal jugé injustifié pointe l'une de trois choses :
une variable métier absente des données, une cible mal formulée, ou une interface
qui fait comprendre autre chose que ce qui est mesuré. Les trois se documentent.

**Ce qui ne se fait pas** : remplir cette grille soi-même, ou n'en rapporter que
les réponses favorables. Une validation métier fabriquée est pire qu'une
validation absente — elle transforme une lacune assumée en affirmation fausse.
