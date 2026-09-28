# Sémantique des colonnes ERP — hypothèses vérifiées

> Ce document existe parce que le chiffre d'affaires a été faux de **5,44 %**
> pendant toute la durée du projet. L'erreur n'était pas de calcul : elle était
> **d'interprétation**. On croyait savoir ce que contenait `TTC_DEV`.
>
> Aucun invariant comptable ne pouvait la détecter, puisque le calcul était
> parfaitement cohérent avec lui-même. Ce qui l'a révélée, c'est d'avoir relu le
> fichier source colonne par colonne.
>
> Chaque affirmation ci-dessous est **vérifiée par un test** dans
> `tests/test_semantique_erp.py`. Si un export futur change de sémantique — même
> sans changer de structure — ces tests échouent.

## La colonne qui a tout causé

| Colonne | Ce qu'on croyait | Ce qu'elle est réellement |
|---|---|---|
| `TTC_DEV` | le montant, signé | une **valeur absolue** — jamais négative, même sur un avoir |
| `HT_DEV` | le montant hors taxe, signé | idem, **toujours positif** |
| `MONTANTSIGNE_DEV` | un doublon du HT | **le seul porteur du sens comptable** : `+HT` pour une facture, `−HT` pour un avoir |

**Conséquence.** Sommer `TTC_DEV` ajoutait les avoirs au chiffre d'affaires au
lieu de les en retrancher. Chaque avoir comptait donc **deux fois** :
7 377 921 × 2 = **14 755 841 DT** d'erreur.

**Règle retenue.** `MONTANTSIGNE_DEV` étant un HT signé, on n'en somme pas la
valeur : on applique **son signe** au `TTC_DEV`.

```sql
CASE WHEN TRY_CAST(MONTANTSIGNE_DEV AS DOUBLE) < 0 THEN -1 ELSE 1 END AS signe
...
ttc_abs * signe AS ttc
```

## Identifiant technique contre clé métier

| Colonne | Nature | Ce qu'elle peut détecter |
|---|---|---|
| `ENT_ID` | identifiant de ligne d'export, **unique par construction** | **rien** — un doublon reçoit deux `ENT_ID` distincts |
| `PIECENOFULL` | **numéro de facture**, la clé comptable | les 1 324 factures présentes deux fois |

C'est la seconde cause de l'écart : contrôler l'unicité sur `ENT_ID` est
*structurellement* incapable de révéler un doublon. Impact : **1 053 938 DT**.

## Lignes de facture — `ZZ_Facture_vente_mouv.csv`

| Colonne | Sémantique vérifiée |
|---|---|
| `MONTANT_DEV` | montant **non signé** — les retours y apparaissent en positif |
| `MONTANTSIGNE_DEV` | montant **signé** — à utiliser systématiquement |
| `QUANTITESIGNEE` | quantité signée (négative sur un retour) |
| `MTCRSIGNE` | coût de revient **signé comme la vente** : sur un retour, le coût revient en stock |
| `SENS` | `1` = retour, `2` = vente. **Aucune autre valeur n'est valide** |
| `NUMEROFULL` | numéro de la facture porteuse |

**Écart mesuré** entre les deux colonnes de montant : **14 136 671 DT (5,03 %)**.
C'est l'erreur que portaient le CA par produit et par famille.

### `SENS` — un détecteur de corruption

`SENS` ne peut valoir que `1` ou `2`. On y trouve aussi `CULTURE` et `GAFSA` :
des noms de catégorie et de ville. C'est un **décalage de colonnes** — une
virgule non échappée dans un champ texte a décalé la ligne entière, et les
montants lus appartiennent alors à **d'autres colonnes**.

Ces lignes sont écartées des agrégats mais **conservées** dans
`sales_lines_rejetees` : une donnée illisible doit rester consultable, pas
s'évaporer dans un `ignore_errors`.

## Ce que l'ERP ne contient pas

Limite fondamentale du projet, à énoncer sans ambiguïté.

| Colonne | État vérifié |
|---|---|
| `REG`, `REGTYP` | **vides** sur la totalité des lignes |
| `ETAT` | **constante** à `'NR'` |
| `SOLDEACOMPTE_DEV` | **0** partout |

**Il n'existe aucune date de paiement réelle.** Tout indicateur de « retard » est
donc un **proxy du délai accordé**, jamais un retard *constaté*. Le DSO mesuré
est un DSO *contractuel*.

Le test correspondant échoue si un futur export alimente ces colonnes — et ce
serait une excellente nouvelle : les vrais retards deviendraient calculables.

## Interprétations validées empiriquement

| Hypothèse | Méthode de validation | Résultat |
|---|---|---|
| `ETATPIECE = 8` signifie « devis transformé » | part des devis en état 8 ayant une facture du même client au même montant (± 1 %) | **89,4 %** contre 37,4 % pour l'état 1 |
| `MODEREGL` encode le délai | `C060` = « chèque 60 jours » → délai médian 61 j | validé, **et écarté du modèle** : cette variable épelle la réponse (AUC 0,934 seule) |

## Les deux niveaux de défense

Comprendre leur différence est essentiel, car ils n'attrapent pas les mêmes
erreurs.

**1. Identités internes** (`tests/test_coherence_financiere.py`) — des égalités
qui doivent tenir par construction :

```
CA net    = ventes − avoirs
nb lignes = factures + avoirs
marge     = CA − coût de revient
HHI       ∈ ]0, 10000]
```

Elles attrapent une formule incohérente. **Elles ne peuvent pas** attraper une
erreur systématique : si un coefficient était appliqué uniformément à tous les
montants, les deux membres bougeraient ensemble et chaque égalité resterait
vraie.

**2. Ancrages externes** (`_ctrl_ancrages_externes`) — des repères qui ne
dérivent pas des données :

- `TTC ≥ HT` sur **chaque** pièce — contrainte fiscale, pas une moyenne : la TVA
  ne peut pas être négative ;
- le ratio `TTC/HT` global dans une bande plausible ;
- **le rapprochement de deux exports indépendants** : le HT des lignes contre le
  HT des en-têtes. C'est la seule vérification qui ne repose sur aucune
  hypothèse interne — la seconde opinion.

C'est ce second niveau qui manquait, et son absence explique pourquoi l'erreur a
survécu si longtemps.

## Effet sur le modèle de risque crédit

`_load_invoices()` lisait le **CSV brut**. Le modèle s'entraînait donc sur les
5 761 avoirs traités comme des ventes — un avoir n'est pas un événement de
crédit, c'est l'annulation d'un précédent, et son « délai » n'a aucun sens comme
cible — et sur les 1 324 doublons, qui pondéraient doublement certaines
observations.

Les deux biais **gonflent** les métriques. Toute performance mesurée avant
correction est donc invalide, **y compris le refus de déploiement** : il fallait
refaire la mesure sur données propres pour que la conclusion, quelle qu'elle
soit, ait une valeur. Le rapport porte désormais un bloc `donnees` qui trace ce
nettoyage, et la version passe de 2 à 3.
