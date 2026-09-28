# Formules des KPI — référence EXHAUSTIVE

> Document **fidèle au code**, vérifié contre les valeurs réellement produites.
> Source : `ml_engine/analytics/kpi_engine.py` (fonction `compute_dashboard`), complétée par `demand_engine.py`, `lstm_cashflow.py`, `credit_risk_model.py`.
>
> **Inventaire : 81 clés** renvoyées par `compute_dashboard` = **58 scalaires** + **23 séries/objets** — toutes documentées ci-dessous, plus les indicateurs des modules annexes.

## Conventions

| Terme | Définition dans ce projet |
|---|---|
| `ttc`, `ht` | montants de la facture (`TTC_DEV`, `HT_DEV` de l'ERP) |
| `date` | date de pièce = émission (`DATEPIECE`) |
| `echeance` | date d'échéance contractuelle (`DATEECHEANCE`, bornée aux années 2000–2035) |
| **`payment_delay_days`** | `datediff('day', date, echeance)` = **délai de crédit ACCORDÉ** |
| `W` | clause SQL des filtres actifs (années, clients, dates, montants, mode de règlement, risque, fidélité). **Tous les KPI sont recalculés sur ce périmètre**, sauf mention contraire |
| `g` | `ca_total_ttc` (ou 1 si nul), utilisé comme dénominateur des parts |

> ⚠️ **Limite fondamentale.** L'ERP fournit l'émission et l'échéance, **jamais la date de paiement réelle** — vérifié sur les 32 fichiers : `REG`, `REGTYP` vides, `ETAT` constant à `'NR'`, `SOLDEACOMPTE_DEV` à 0 sur 128 848 lignes. Donc `payment_delay_days` = délai *accordé*, pas retard *constaté*. Tous les indicateurs de « risque » ci-dessous sont des **proxys explicites** du risque de crédit.
>
> **Ce que le projet en fait** : aucune prédiction inventée (impossible sans cible d'entraînement), mais un module de **scénarios** (`payment_scenario.py`, onglet Risque crédit) qui chiffre l'impact d'hypothèses de retard **explicites et modifiables** — et mesure l'incertitude résiduelle : 26,3 jours de DSO et 6,34 M DT d'écart entre hypothèse douce et dure. Analyse complète et demande technique à l'entreprise : `docs/DONNEES_MANQUANTES.md`.

---

# PARTIE A — Les 58 scalaires

## A1. Chiffre d'affaires et volumétrie (5)

| # | Clé | Formule exacte |
|---|---|---|
| 1 | `ca_total_ttc` | `sum(ttc) WHERE W` |
| 2 | `ca_total_ht` | `sum(ht) WHERE W` |
| 3 | `nb_factures_vente` | `count(*) WHERE W` |
| 4 | `nb_clients` | `count(DISTINCT client) WHERE W` |
| 5 | `panier_moyen` | `ca_total_ttc ÷ nb_factures_vente` (0 si aucune facture) |

## A2. Dynamique temporelle (5)

| # | Clé | Formule exacte |
|---|---|---|
| 6 | `mom_growth` | `(CA_dernier_mois − CA_mois_précédent) ÷ CA_mois_précédent × 100` |
| 7 | `tendance` | `"Haussiere"` si dernier mois ≥ précédent, sinon `"Baissiere"` ; `"Stable"` si < 2 mois |
| 8 | `ttm_revenue` | `sum(ttc) WHERE date > max(date) − 12 mois` (12 mois glissants) |
| 9 | `yoy_growth` | `(ttm_revenue − TTM_précédent) ÷ TTM_précédent × 100`, où TTM_précédent = mois −24 à −12 |
| 10 | `top_clients_revenue_share` | `Σ CA des 5 premiers clients ÷ g × 100` |

## A3. Délais, DSO/DPO, risque de crédit (14)

| # | Clé | Formule exacte |
|---|---|---|
| 11 | `dso_jours` | `avg(payment_delay_days)` sur `sales` = délai moyen accordé |
| 12 | `dpo_jours` | `avg(payment_delay_days)` sur `purchases` |
| 13 | `cash_conversion_cycle` | `dso_jours − dpo_jours` |
| 14 | `retards_30j` | `count(*) WHERE payment_delay_days > 30` |
| 15 | `retards_60j` | `count(*) WHERE payment_delay_days > 60` |
| 16 | `retards_critiques` | `count(*) WHERE payment_delay_days > 90` |
| 17 | `paiements_total_analyses` | `count(*) WHERE payment_delay_days IS NOT NULL` (factures avec échéance) |
| 18 | `paiements_a_risque_count` | identique à `retards_60j` |
| 19 | `paiements_a_risque_pct` | `retards_60j ÷ paiements_total_analyses × 100` |
| 20 | `montant_risque_ttc` | `sum(ttc) WHERE payment_delay_days > 60` |
| 21 | `montant_critique_ttc` | `sum(ttc) WHERE payment_delay_days > 90` |
| 22 | `ca_retard_historique_ttc` | = `montant_risque_ttc`. **Nom volontairement explicite** : cumul historique de comportement de paiement, **pas un encours dû aujourd'hui** (le schéma n'a ni statut payé/impayé ni solde) |
| 23 | `ca_retard_historique_critique_ttc` | = `montant_critique_ttc` |
| 24 | `exposition_recente_periode` | libellé `"échéances des 6 mois jusqu'à <YYYY-MM>"`, calculé depuis `max(echeance)` du périmètre |

## A4. Exposition récente — le chiffre actionnable (3)

Cumuler 9 ans donnerait un montant inutilisable. On borne aux **6 derniers mois d'échéances**, relativement à `max(echeance)` du périmètre :

```sql
WITH ref AS (SELECT max(echeance) md FROM sales WHERE W)
SELECT sum(ttc) FILTER (WHERE payment_delay_days > 60)  -- (25)
     , sum(ttc) FILTER (WHERE payment_delay_days > 90)  -- (26)
     , count(*) FILTER (WHERE payment_delay_days > 60)  -- (27)
FROM sales WHERE W AND echeance >= (SELECT md FROM ref) - INTERVAL 6 MONTH
```

| # | Clé | Formule |
|---|---|---|
| 25 | `exposition_recente_dt` | Σ TTC des factures à délai > 60 j, échéance dans les 6 derniers mois |
| 26 | `exposition_recente_critique_dt` | idem avec délai > 90 j |
| 27 | `exposition_recente_count` | nombre de factures concernées |

## A5. Concentration du portefeuille (4)

| # | Clé | Formule exacte |
|---|---|---|
| 28 | `hhi_clients` | **`Σ (CA_client ÷ CA_total × 100)²`** (Herfindahl-Hirschman, échelle 0–10 000 ; **> 2 500 = concentré**) |
| 29 | `hhi_fournisseurs` | même formule sur `purchases` groupé par fournisseur |
| 30 | `clients_pour_80pct` | `min(rang)` tel que le **CA cumulé ≥ 80 %** du total (clients triés par CA décroissant) |
| 31 | `nb_clients_ca` | nombre total de clients ayant du CA sur le périmètre |

## A6. Marge et rentabilité — **marge RÉELLE par coût de revient** (9)

> **Correction majeure (v8).** La marge était auparavant approximée par `CA HT − achats TTC`, ce qui donnait **77 %** (invraisemblable) et devenait `None` dès qu'un client était filtré. L'exploration des données a révélé que les **lignes de vente portent le coût de revient ERP** (`MTCRSIGNE`, rempli sur 340 709 lignes). La marge est désormais **réelle et attribuable par client**.

| # | Clé | Formule exacte |
|---|---|---|
| 32 | `marge_brute` | **`Σ CA_ligne − Σ coût_revient`** sur les lignes du périmètre (table `client_margin`) |
| 33 | `taux_marge` | `marge_brute ÷ marge_ca_reference_dt × 100` → **28,3 %** |
| 34 | `marge_quality_score` | `taux_marge` borné à `[0, 100]` (jauge) |
| 35 | `marge_note` | texte explicatif accompagnant systématiquement la valeur |
| 36 | `marge_ca_reference_dt` | `Σ MONTANTSIGNE_DEV` des lignes retenues (dénominateur du taux) |
| 37 | `marge_cout_revient_dt` | `Σ MTCRSIGNE` des lignes retenues |
| 38 | `marge_source` | `"cout_revient_erp"` ou `"indisponible"` |
| 39 | `marge_lignes_exclues` | lignes écartées par le nettoyage : **387** |
| 39b | `marge_lignes_exclues_pct` | part correspondante : **0,12 %** des lignes facturées |
| 40 | `marge_cout_articles_offerts_dt` | coût des articles livrés à montant nul (consommables offerts) |

**Nettoyage des aberrations (indispensable et documenté).** 318 lignes sur 340 912 portent un coût **supérieur à 10× le prix de vente** — par exemple un panel vendu 28 300 DT avec un coût déclaré de 665 450 DT : erreur de saisie manifeste. Le moteur écarte les lignes dont `coût > 5 × CA` (seuil conservateur : la marge se stabilise entre 5× et 2×, et seules 387 lignes sont exclues). Le nombre de lignes écartées est **exposé dans les KPI** pour que l'utilisateur puisse juger.

| Seuil d'exclusion | Lignes retenues | Taux de marge |
|---|---|---|
| aucun | 329 687 | 22,2 % |
| coût ≤ 10× CA | 329 369 | 28,1 % |
| **coût ≤ 5× CA** (retenu) | **329 300** | **28,3 %** |
| coût ≤ 3× CA | 328 922 | 29,3 % |

**Cas particulier des articles offerts** : 3 208 lignes ont un montant nul mais un coût réel (2,2 M DT) — consommables offerts avec les automates, pratique courante du secteur. Ils sont comptabilisés séparément (`marge_cout_articles_offerts_dt`) et n'entrent pas dans le taux, qui porte sur les lignes facturées.

`marge_brute` ne vaut `None` que si le périmètre ne contient **aucune ligne exploitable**.

## A7. Achats et fournisseurs (3)

| # | Clé | Formule exacte |
|---|---|---|
| 36 | `achats_total_ttc` | `sum(ttc) FROM purchases` (filtre **année seulement**) |
| 37 | `nb_factures_achat` | `count(*) FROM purchases` |
| 38 | `nb_fournisseurs` | `count(DISTINCT fournisseur) FROM purchases` |

## A8. Pipeline commercial (5)

| # | Clé | Formule exacte |
|---|---|---|
| 39 | `nb_devis` | `count(*) FROM devis` (filtre année) |
| 40 | `montant_devis_total` | `sum(ttc) FROM devis` |
| 41 | `taux_conversion_devis` | **`devis transformés ÷ total devis × 100`** = **9,0 %** (415 / 4 621) |
| 42 | `nb_bl` | `count(*) FROM bl` (bons de livraison, **non filtré**) |
| 43 | `montant_bl_total` | `None` — le fichier BL ne porte pas de montant fiable ; laissé nul plutôt qu'inventé |
| 43b | `devis_transformes` | `count(*) WHERE ETATPIECE = '8'` = **415** |
| 43c | `montant_devis_transforme` | `sum(ttc) WHERE transforme` |
| 43d | `taux_conversion_source` | `"etat_piece_erp"` |
| 43e | `taux_conversion_note` | texte explicatif accompagnant le taux |

> **Correction majeure (v8).** Le taux était auparavant calculé au niveau client (« ce client a-t-il facturé quelque chose ? »), ce qui donnait **94,8 %** — un chiffre sans signification commerciale. L'exploration a montré que le champ ERP `ETATPIECE` porte le statut du devis, et que la valeur **8 correspond au devis transformé en facture**.
>
> **Validation empirique de cette interprétation** (méthode reproductible) : pour chaque devis, on vérifie s'il existe une facture du même client au même montant (± 1 %).
>
> | État `ETATPIECE` | Devis appariés à une facture |
> |---|---|
> | **8** | **371 / 415 → 89,4 %** |
> | 1 | 1 567 / 4 189 → 37,4 % |
>
> L'écart est massif et sans ambiguïté : l'état 8 signifie bien « transformé ». Le taux réel de transformation est donc de **9,0 %**, et non 94,8 %. Le test `test_hypothese_etat_8_reste_valide` re-vérifie cette interprétation à chaque exécution de la suite.

## A9. Produits (1)

| # | Clé | Formule exacte |
|---|---|---|
| 44 | `nb_produits` | `count(DISTINCT produit) FROM product_sales` (filtre année) |

## A10. Risque crédit prédit par le modèle ML (3)

Alimenté par `models/credit_risk_model.joblib` → `output/client_risk.json` :

| # | Clé | Formule exacte |
|---|---|---|
| 45 | `nb_clients_risque_predit` | nombre de clients du périmètre dont `score > 70` |
| 46 | `exposition_risque_ponderee` | **`Σ (score ÷ 100 × exposition)`** sur tous les clients = **argent à risque total** |
| 47 | `risk_model_active` | `True` si `client_risk.json` est chargé, sinon `False` (les 2 clés ci-dessus valent alors `None`) |

## A11. Anomalies (1)

| # | Clé | Formule exacte |
|---|---|---|
| 48 | `anomalies_detectees` | **`retards_critiques + count(ttc < 0) + count(ttc = 0)`** |

---

# PARTIE B — Les 23 séries et objets

## B1. Séries temporelles (6)

| Clé | n | Formule |
|---|---|---|
| `monthly_sales` | 85 | `sum(ttc)` groupé par `strftime(date,'%Y-%m')` → `{period, revenue}` |
| `yearly_sales` | 9 | `sum(ttc)` groupé par année → `{year, revenue}` |
| `seasonality` | 12 | **`Σ CA du mois calendaire ÷ nombre d'années distinctes`** → `{month, revenue}` = CA **moyen** du mois |
| `monthly_margin` | 85 | par mois : `Σ ht des ventes − Σ ttc des achats` → `{period, marge}`. Vide si marge non attribuable |
| `sales_vs_purchases` | 85 | jointure mensuelle → `{period, ventes, achats}` (achats à 0 si le mois n'existe pas côté achats) |
| `cash_forecast` | 18 | `sum(ttc)` groupé par **mois d'ÉCHÉANCE** (18 derniers) → `{period, montant}` = encaissements attendus |

## B2. Comparaison annuelle (1 objet)

`yoy_comparison` = `{current_year, previous_year, data[], delta_pct}`

- `data[]` : par mois, `{month, courante, precedente}` = `sum(ttc) FILTER (WHERE year = cy | py)`
- **`delta_pct`** = `(Σ courante − Σ precedente) ÷ Σ precedente × 100` sur les **mois comparables uniquement**

## B3. Distributions (3)

| Clé | n | Formule |
|---|---|---|
| `aging_creances` | 5 | `sum(ttc)` par tranche de `payment_delay_days` : **Comptant** (≤ 0), **0-30 j**, **31-60 j**, **61-90 j**, **90 j +** → `{bucket, montant}` |
| `amount_distribution` | 6 | `count(*)` par tranche de `ttc` : `< 500`, `0.5-1K`, `1-5K`, `5-10K`, `10-50K`, `50K +` → `{tranche, count}` |
| `payment_mix` | 8 | `sum(ttc)`, `count(*)` par mode de règlement (top 8) → `{mode, montant, count}`. Libellés **normalisés** : trim, espaces multiples réduits, `"90JOURS"` → `"90 JOURS"`, vide/`NULL` → `"Non renseigné"` ; le libellé affiché est la variante **la plus fréquente** de chaque groupe |

## B4. Clients (5)

### `top_clients` (10) — top par `sum(ttc)`

| Sous-champ | Formule |
|---|---|
| `client` | code client ERP |
| `nom` | `client_name` (repli sur le code) |
| `revenue` | `sum(ttc)` |
| `invoices` | `count(*)` |
| `share` | `revenue ÷ g × 100` |
| `rank` | rang (1 à 10) |
| `risque` | `sum(ttc) FILTER (WHERE payment_delay_days > 30)` |
| `risk_score` | score ML `P(délai > 60 j) × 100` (si modèle actif) |

### `clients_fideles` (8) — la fidélité = **récurrence**, pas le CA

```
mois_actifs = count(DISTINCT strftime(date, '%Y-%m'))
filtre      : count(*) >= 2 factures
exclusions  : noms contenant « passager », « comptant », « divers », « espèce »
tri         : mois_actifs ↓, puis invoices ↓, puis revenue ↓
```
Sous-champs : `client, nom, revenue, invoices, mois_actifs, premier, dernier, share`.

### `clients_decrochent` (8) — détection de perte de client

```
Conditions cumulatives :
  • mois_actifs ≥ 6                              (client établi)
  • ca_prev > 0
  • ca_recent < ca_prev × 0.4                    (chute > 60 %)
où  ca_recent = Σ ttc sur [max(date) − 90 j, max(date)]
    ca_prev   = Σ ttc sur [max(date) − 180 j, max(date) − 90 j[
chute_pct     = (1 − ca_recent ÷ ca_prev) × 100
jours_inactif = datediff('day', dernière facture, max(date))
tri : perte absolue (ca_prev − ca_recent) ↓
```

### `clients_relance` (8) et `clients_a_risque` (8)

| Clé | Périmètre | Formule |
|---|---|---|
| `clients_relance` | **6 derniers mois d'échéances** | par client : `sum(ttc)` et `count(*)` avec délai > 60 j, `HAVING montant > 0`, top 8 |
| `clients_a_risque` | **tout l'historique** du périmètre | même calcul, sans borne temporelle |

Sous-champs : `client, nom, montant_risque, factures` (+ `risk_score` si modèle actif).

### `client_pareto` (21)

Pour chaque tranche de **5 %** de clients (triés par CA décroissant) : `{pct_clients, pct_ca}` où `pct_ca = CA cumulé ÷ CA total × 100`.

## B5. Classement de risque ML (1)

`risk_ranking` (10) — trié par `priority` décroissante :

| Sous-champ | Formule |
|---|---|
| `score` | moyenne des probabilités `P(délai > 60 j)` du client × 100 |
| `exposure` | `sum(ttc)` historique du client |
| `avg_delay` | délai moyen accordé du client |
| **`priority`** | **`score ÷ 100 × exposure`** = argent à risque |

> On classe par **probabilité × montant**, pas par probabilité seule : un client à 95 % sur 500 DT est moins prioritaire qu'un client à 60 % sur 200 000 DT.

## B6. Fournisseurs et produits (3)

| Clé | n | Formule |
|---|---|---|
| `top_fournisseurs` | 8 | `sum(ttc)` par fournisseur ; `share = montant ÷ achats_total_ttc × 100` → `{fournisseur, montant, share, rank}` |
| `top_produits` | 10 | `sum(ca)`, `sum(qte)` depuis `product_sales` (pré-agrégé par produit × année) → `{produit, ca, qte}` |
| `top_familles` | 6 | `sum(ca)` par `ARTICLE_LIBELLE_FAM_STAT1` (RÉACTIF, ÉQUIPEMENT, SERVICE…) → `{famille, ca}` |

## B7. Vues de synthèse (3)

| Clé | n | Formule |
|---|---|---|
| `waterfall` | 3 | cascade « du CA à la marge » → `{step, value, kind}` |
| `funnel` | 3 | entonnoir commercial → `{etape, valeur}` |
| `anomalies_details` | 3 | liste de messages (chaînes) générés par les règles ci-dessous |

### Détail de `waterfall` — sous-champs `{step, value, kind}`

| `step` | `value` | `kind` |
|---|---|---|
| `"CA HT"` | `+ca_total_ht` | `"start"` |
| `"Achats"` | `−achats_total_ttc` (valeur **négative**) | `"neg"` |
| `"Marge brute"` | `+marge_brute` | `"total"` |

Liste **vide** si la marge est non attribuable (voir A6) ou si `ca_total_ht` est nul.

### Détail de `funnel` — sous-champs `{etape, valeur}`

| `etape` | `valeur` |
|---|---|
| `"Devis"` | `nb_devis` |
| `"Clients convertis"` | clients devisés ayant aussi facturé (numérateur de `taux_conversion_devis`) |
| `"Clients facturés"` | `nb_clients` |

### Règles de génération de `anomalies_details`

| Message | Condition |
|---|---|
| « N facture(s) avec délai accordé > 90 jours » | `retards_critiques > 0` |
| « N facture(s) avec délai accordé de 30 à 90 jours » | `retards_30j − retards_critiques > 0` |
| « N facture(s) avec montant négatif (avoirs) » | `count(ttc < 0) > 0` |
| « N facture(s) avec montant nul » | `count(ttc = 0) > 0` |
| « Forte concentration client (HHI=… > 2500) » | `hhi_clients > 2500` |
| « Aucune anomalie majeure détectée. » | si aucune des règles ci-dessus |

## B8. Enrichissements ajoutés par le copilote (2, `agents/copilote/noeuds.py`)

`forecast_next` (projection linéaire du CA sur 3 mois, à partir des 12 derniers mois) et `finance_radar` — détaillé en partie D.

---

# PARTIE C — Demande et approvisionnement (`demand_engine.py`, 11 clés)

| Clé | Formule exacte |
|---|---|
| `demande_mensuelle` | `sum(nbr_article)` groupé par mois → **volume d'articles vendus** (proxy de la demande, faute de données de stock) |
| `demande_backtest_mape` | MAPE de **chaque** méthode sur les 12 derniers mois en walk-forward : `{saisonnier: 20.3, saisonnier_croissance: 29.9, moyenne_mobile: 30.2, tendance: 25.4}` |
| `demande_methode` | méthode retenue = **`argmin(MAPE)`** → `"saisonnier"` |
| `demande_mape` | MAPE de la méthode retenue = **20,3 %** |
| `demande_prevision` | 3 mois projetés → `{period, qte}` |
| `fournisseurs_nb` | `count(DISTINCT fournisseur)` = 38 |
| `fournisseurs_hhi` | `Σ (part_fournisseur × 100)²` = **7 177** |
| `fournisseur_top1_pct` | `achats_top1 ÷ achats_total × 100` = **84,6 %** (Biomérieux) |
| `fournisseurs_top3_pct` | somme des parts des 3 premiers = **89,9 %** |
| `fournisseurs_top` | top 5 → `{fournisseur, part_pct, achats_dt, n_factures}` |
| `dependance_fournisseur` | **seuils sur `top1_pct`** : ≥ 50 % → `"critique"` · ≥ 30 % → `"élevée"` · ≥ 15 % → `"modérée"` · sinon `"faible"` |

### Formules des 4 méthodes de prévision

| Méthode | Formule |
|---|---|
| `saisonnier` | `prévision = valeur(m − 12)` |
| `saisonnier_croissance` | `valeur(m−12) × facteur`, où `facteur = moyenne(3 derniers mois) ÷ moyenne(mois −15 à −12)`, borné à `[0.5, 2.0]` |
| `moyenne_mobile` | `moyenne(3 derniers mois)` |
| `tendance` | régression linéaire de degré 1 sur les 12 derniers mois, extrapolée d'un pas |
| **MAPE** | `moyenne(|réel − prévu| ÷ |réel|) × 100`, les mois à zéro étant ignorés |

---

# PARTIE D — Radar financier (`finance_radar`)

Des cartes d'action chiffrées, triées par sévérité puis par montant. Chaque carte :
`{priorite, id, categorie, severite, titre, montant_dt, montant_label, constat,
signal_externe, action, top[]}`. Le radar alimente le copilote : titre, montant et
action de chaque carte entrent dans le contexte du modèle de langage, et la
première carte est citée dans la trace d'exécution.

**Établissement de santé public** — une seule règle, `ml_engine/typologie.py`
(`MOTS_HOPITAL_PUBLIC`), celle que les modèles de demande utilisent déjà comme
variable : la raison sociale, en majuscules, contient `C.H.U`, `CHU`, `HOPITAL`,
`HÔPITAL`, `HOSPITAL`, `MILITAIRE`, `INSTITUT` ou `CENTRE HOSPITALIER`. Même verdict
en Python (`est_hopital_public`) et en SQL (`condition_sql_hopital_public`). Les
facultés et les ministères n'en font pas partie.

| Carte (`id`) | Formule | Condition d'affichage |
|---|---|---|
| **Recouvrement des établissements de santé publics** (`recouvrement_public`) | sur l'**exposition récente** (A4 : factures à délai > 60 j, échéances des 6 derniers mois, **même périmètre filtré**) : `montant_dt = Σ TTC` des établissements publics ; part = `montant_dt ÷ exposition_recente_dt` ; nombre d'établissements ; montant à plus de 90 j ; `top` = les 3 plus gros débiteurs publics de la fenêtre ; sévérité « haute » s'il existe un montant à plus de 90 j | montant > 0 |
| **Créances exigibles le mois prochain** (`echeancier_1m`) | montant arrivant à échéance le mois suivant, lu dans le carnet des factures émises (`ml_engine/forecasting/carnet_echeances.py`) ; le constat cite la part déjà inscrite au carnet, puis la **part publique de cette part inscrite** : factures émises au plus tard le mois d'origine, échéance au mois cible, avoirs exclus, portefeuille entier (mêmes factures au numérateur et au dénominateur, donc entre 0 et 100 %) | le registre sert l'échéancier (`est_deploye("echeancier")`) |

Une erreur de calcul d'une carte est écrite dans le journal (`WARNING`) : la carte
manque, le reste du radar est servi.

> **Historique (corrigé en septembre 2026).** La carte publique lisait une liste
> `_PUBLIC_CLIENT_KEYWORDS` supprimée avec la veille externe : l'erreur était
> avalée, la carte n'apparaissait jamais et la phrase de l'échéancier valait
> « 0 % ». L'ancienne liste avait en outre trois défauts : « CHU » ne reconnaissait
> pas « C.H.U. », « ETAT » classait public le « LABORATOIRE KETATA », et le montant
> cumulait neuf ans d'historique (42,5 M DT au lieu de 6,0 M DT d'exposition
> récente), ce qui aurait fait écrire « 755 % » dans la phrase de l'échéancier.
> Tests : `tests/test_radar_financier.py`, et le contrôle croisé avec
> `exposition_recente_dt` dans `tests/test_coherence_financiere.py`.

**Retirés avec la veille externe** : la sensibilité au change EUR/TND
(`fx_margin_sensitivity`), le pipeline d'appels d'offres et le contexte
macroéconomique. Tous dépendaient de sources hors ERP (taux de change, TUNEPS,
données macro) dont la qualité ne pouvait pas être auditée comme celle des
factures (`reports/METRICS_REPORT.md`, §2).

---

# PARTIE E — Modèles ML (rappel des formules de score)

| Modèle | Cible | Formule du score |
|---|---|---|
| **Risque crédit** | `P(payment_delay_days > 60)` | HistGradientBoosting ; `risk_score = moyenne des probabilités du client × 100` ; `priority = score ÷ 100 × exposure` |
| **Prévision trésorerie** | encaissements mensuels | série `log1p` standardisée → LSTM ou Holt-Winters amorti ; **bande = `expm1(prévision ± 1,96 σ_résidus)`**, bornée à `[0.6 × centre, 1.7 × centre]` |
| **Prévision demande** | volume d'articles | `argmin(MAPE)` parmi 4 méthodes (voir partie C) |

---

# Valeurs de référence (périmètre complet, sans filtre)

| KPI | Valeur | Contrôle de la formule |
|---|---|---|
| Panier moyen | 2 254,64 DT | = CA TTC ÷ nb factures ✓ |
| DSO / DPO | 44,3 j / 33,7 j | délais moyens accordés |
| Cycle de conversion | 10,6 j | = 44,3 − 33,7 ✓ |
| Factures à risque | 39,26 % | = retards_60j ÷ paiements_total_analyses ✓ |
| Taux de marge | **28,3 %** | = (CA lignes − coût de revient) ÷ CA lignes ✓ — **marge réelle** (l'ancienne approximation donnait 77 %) |
| HHI clients | 32 | portefeuille **peu concentré**, aucune alerte |
| Pareto | 401 clients / 1 137 pour 80 % du CA | cohérent avec le HHI faible |
| Exposition récente > 60 j | 11,2 M DT | échéances des 6 derniers mois |
| HHI fournisseurs | 7 177 | **dépendance critique** (Biomérieux 84,6 %) |

> Savoir **opposer** ces deux concentrations en soutenance montre que vous comprenez vos chiffres : portefeuille client sain (HHI 32), dépendance fournisseur critique (HHI 7 177).

---

# Les questions que le jury posera

**« Votre DSO est-il un vrai DSO ? »**
> Non, et je le dis explicitement. Le DSO comptable se calcule sur les encaissements réels. L'ERP ne fournit pas la date de paiement : je mesure le **délai moyen accordé**. C'est un proxy du risque de crédit — un délai long augmente mécaniquement l'encours — mais je ne prétends pas mesurer le retard constaté.

**« La marge est-elle disponible par client ? »**
> Oui, depuis la v8. Elle vient du coût de revient porté par chaque ligne de vente, donc elle suit le filtre client : l'Hôpital Militaire de Tunis dégage par exemple 25,7 % de marge. Auparavant elle était marquée « non attribuable » parce que les achats fournisseurs ne sont pas rattachables aux clients — c'était honnête, mais incomplet : la donnée existait ailleurs, dans les lignes.

**« Comment calculez-vous la marge ? »**
> Sur le coût de revient réel : les lignes de vente portent `MTCRSIGNE`, le coût de revient de l'ERP. La marge est donc `CA des lignes − coût de revient`, soit **28,3 %** — cohérent pour un distributeur de matériel médical, et surtout **attribuable par client**. J'ai d'abord utilisé l'approximation « CA HT − achats TTC », qui donnait 77 % : en explorant les 32 fichiers, j'ai trouvé le coût de revient ligne à ligne et corrigé. J'écarte 387 lignes (0,12 %) dont le coût dépasse 5× le prix de vente — des erreurs de saisie manifestes — et je l'affiche dans les KPI.

**« Comment interprétez-vous un HHI de 2 500 ? »**
> C'est le seuil des autorités de concurrence pour un marché concentré. Au-delà, la perte d'un seul acteur fait basculer le chiffre d'affaires — le moteur lève alors une anomalie automatique. C'est un indicateur de **risque de dépendance**, pas de performance.

**« Pourquoi classer par `priority` et pas par score de risque ? »**
> Parce qu'un recouvrement se priorise en dinars, pas en probabilités. `priority = score × exposition` répond à la vraie question du directeur financier : « où est mon argent à risque ? »
