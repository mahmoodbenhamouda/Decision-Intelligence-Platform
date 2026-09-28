"""
ml_engine/stock/nomenclature.py
================================
Classification des références produit — le maillon le plus fragile, isolé et mesuré.

La nomenclature existait — et deux erreurs successives l'ont masquée
-------------------------------------------------------------------
Ce module a d'abord été écrit en affirmant qu'aucune famille produit n'existait
dans l'export. **C'était faux.** `ARTICLE_LIBELLE_FAM_STAT1` est renseignée pour
**340 912 lignes sur 340 913, soit 99,9 %** — mesuré par
`python scripts/diag_famille_produit.py`.

Puis une seconde erreur a fait croire le contraire une deuxième fois. Le chemin de
lecture ajouté ici renvoyait « 0 désignation », et j'en ai conclu que la colonne
était vide. La cause n'était pas dans les données : l'amorçage du cache se faisait
**après la fermeture de la connexion**, et son `except` avalait l'erreur sans
trace. Un `except` muet n'a donc pas seulement dégradé un chiffre — il a produit
une conclusion fausse sur les données, inscrite dans le rapport.

Deux leçons, la seconde plus coûteuse que la première :

1. lire du code et un commentaire n'est pas interroger la donnée ;
2. **un `except` qui avale une erreur doit laisser une trace**, sans quoi un
   repli silencieux devient un fait établi.

La famille ERP est donc la source **primaire** du classement, et les mots-clés de
libellé ne servent plus qu'en repli — là où la famille est absente ou porte une
valeur non répertoriée (la pollution « fournitures d'art » déjà identifiée
ailleurs dans le projet).

C'est la deuxième fois qu'une « donnée manquante » se révèle présente, après les
quantités d'achat qui ont permis de reconstruire le stock. Une limite annoncée
sans avoir épuisé la recherche est une limite fausse.

Pourquoi ce fichier existe
--------------------------
Presque toutes les conclusions du domaine stock dépendent d'une distinction que
la famille produit donne :

  * un **réactif** périme — un stock de deux ans est une perte annoncée ;
  * un **automate** s'amortit — un stock de deux ans est un investissement lent ;
  * une **pièce détachée** se conserve — on la détient *précisément parce que*
    sa rotation est lente ;
  * une **prestation** ne se stocke pas du tout.

Faute de cette colonne, la distinction se fait sur le **libellé**. C'est approché,
et un filtrage approché qui pilote 213 771 DT de perte annoncée ne peut pas rester
disséminé en trois expressions régulières au milieu d'un autre module : il doit
être isolé, mesurable, exportable et testé. C'est l'objet de ce fichier.

Ce qu'il apporte par rapport aux motifs dispersés
-------------------------------------------------
1. **Un point unique** — `classer()` est la seule autorité. Un motif ajouté ici
   se propage partout, et aucun appelant ne peut appliquer sa propre variante.
2. **Une mesure de couverture** — quelle part des références, et surtout quelle
   part de la VALEUR, est classée par un motif explicite plutôt que par défaut.
   Le classement par défaut est « consommable », donc le plus coûteux en cas
   d'erreur : il faut savoir combien de valeur en dépend.
3. **Une piste d'audit** — `exporter_pour_validation()` produit un fichier que
   l'entreprise peut corriger ligne par ligne. Une limite qu'on peut faire lever
   par son client n'est plus tout à fait une limite.

Ce que ce fichier ne prétend pas être
-------------------------------------
Il ne remplace pas une nomenclature. Il rend son absence **visible, chiffrée et
corrigeable**, au lieu de la laisser implicite.

Sortie : `reports/nomenclature_metrics.json` + `reports/nomenclature_a_valider.csv`

Lancement :
    python -m ml_engine.stock.nomenclature
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from config.settings import settings
    BASE = Path(settings.base_dir)
except Exception:  # pragma: no cover
    BASE = Path(__file__).resolve().parents[2]

REPORTS_DIR = BASE / "reports"


# ── Les quatre catégories ───────────────────────────────────────────────────
#
# L'ordre d'évaluation est significatif et volontairement figé : une même
# désignation peut porter plusieurs signaux, et le premier motif reconnu gagne.
#
#   PRESTATION avant tout   — « CONTRAT DE MAINTENANCE TOUS RISQUE VIDAS »
#                             contient « VIDAS » ; c'est pourtant un contrat.
#   PIECE avant EQUIPEMENT  — « VIDAS NSH UPGRADE KIT » contient un mot
#                             d'équipement, mais c'est un kit de mise à niveau.
#   EQUIPEMENT avant défaut — « Hb NEXT Analyzer » est un instrument.
#   CONSOMMABLE par défaut  — tout le reste. C'est la classe la plus coûteuse en
#                             cas d'erreur, puisque c'est la seule qui périme :
#                             elle est donc attribuée en dernier, jamais par un
#                             motif positif.
PRESTATION = "prestation"
EQUIPEMENT = "equipement"
PIECE = "piece_detachee"
CONSOMMABLE = "consommable"

CATEGORIES = (PRESTATION, EQUIPEMENT, PIECE, CONSOMMABLE)

_MOTIFS_PRESTATION = re.compile(
    r"\b(CONTRAT|MAINTENANCE|FORMATION|INSTALLATION|DEPLACEMENT|"
    r"MAIN\s*D.?\s*OEUVRE|PRESTATION|FRAIS|TRANSPORT|LOCATION|ABONNEMENT|"
    r"ETALONNAGE|QUALIFICATION|HOTLINE|ASSISTANCE)\b",
    re.IGNORECASE)

# Pièces détachées et consommables techniques. Ils franchissaient les anciens
# filtres — « Seals kit vidas range » n'est ni un automate ni une prestation —
# alors qu'ils ne périment pas comme un réactif : joints d'étanchéité, kit de mise
# à niveau, pièce de maintenance préventive se conservent des années. Les compter
# en péremption gonflait la perte de 90 711 DT.
#
# « P.M. » désigne la maintenance préventive dans la nomenclature du fournisseur ;
# il a fallu le vérifier avant de l'inscrire ici.
_MOTIFS_PIECE = re.compile(
    r"\b(SEALS?|JOINT|UPGRADE|P\.?M\.?\s|PIECE|SPARE|TUBULURE|TUBING|"
    r"FILTRE|FILTER|CABLE|BATTERIE|LAMPE|CARTE\s+ELECTRO|ADAPTAT|"
    r"SERINGUE\s+METAL|POMPE|VANNE|COURROIE|FUSIBLE|CAPOT|SUPPORT\s+METAL|"
    r"ECRAN|CLAVIER|ALIMENTATION\s+ELECT)",
    re.IGNORECASE)

# Un automate ne périme pas : il s'amortit. Le confondre avec un consommable
# ferait passer 356 000 DT d'équipement pour une perte imminente — situation
# inconfortable, mais d'une tout autre nature.
_MOTIFS_EQUIPEMENT = re.compile(
    r"\b(AUTOMATE|ANALYZER|ANALYSEUR|SYSTEM|SYSTEME|INSTRUMENT|APPAREIL|"
    r"MODULE|STATION|IMPRIMANTE|LECTEUR|CENTRIFUG|MICROSCOPE|ORDINATEUR|"
    r"PC\b|AGITATEUR|ETUVE|BAIN\s+MARIE|CONGELATEUR|REFRIGERATEUR|"
    r"INCUBATEUR|THERMOCYCLEUR|SPECTRO)",
    re.IGNORECASE)

# Motifs POSITIFS de consommable. Ils ne servent pas à classer — le défaut y
# pourvoit — mais à MESURER : une référence classée consommable par un motif
# explicite est mieux établie qu'une référence classée par défaut. C'est la
# différence entre « je sais que c'est un réactif » et « je n'ai rien reconnu ».
_MOTIFS_CONSOMMABLE = re.compile(
    r"\b(REACTIF|REAGENT|TEST|TESTS|CONTROLE|CONTRÔLE|CALIBRA|QCV|"
    r"DILLUANT|DILUANT|SOLUTION|GEL|SERUM|ANTISERUM|PANEL|KIT\s+DE\s+DOSAGE|"
    r"CARTOUCHE|BANDELETTE|STRIP|MILIEU|GELOSE|AGAR|TUBE|CUVETTE|"
    r"EMBOUT|CONE|PIPETTE|LAME|LAMELLE|POCHE|ANTIBIOGRAMME|VIDAS\s+[A-Z])",
    re.IGNORECASE)


# ── La famille ERP : source PRIMAIRE du classement ───────────────────────────
#
# `ARTICLE_LIBELLE_FAM_STAT1`, lue sous le nom `famille`, est renseignée à 99,9 %
# (mesuré, cf. `scripts/diag_famille_produit.py`). Elle prime donc sur les
# mots-clés : un libellé est déclaratif et changeant, une famille saisie dans
# l'ERP est structurelle. Même hiérarchie que pour `INDICMVTSTOCK` dans
# `flux_reels`, où l'indicateur ERP prime sur la désignation.
# Valeurs réellement observées, mesurées et non supposées
# (`python scripts/diag_famille_produit.py`) :
#
#   REACTIF            312 324 lignes   91,6 %
#   SERVICE DIVERS      14 754           4,3 %
#   SERVICE SAV          3 941           1,2 %
#   EQUIPEMENT           1 315           0,4 %
#   Brosses (Pinceaux), Peintures Aquarelles, ___Divers___, …
#                                        ~2,5 %  <- pollution « fournitures d'art »
#
# La dernière catégorie est la pollution de démonstration déjà identifiée et
# filtrée dans `product_family`. Elle n'est PAS mappée : une famille inconnue
# n'est jamais devinée, le repli par mots-clés prend le relais, et le compteur
# `defaut` la rend visible.
_FAMILLE_VERS_CATEGORIE = {
    "REACTIF": CONSOMMABLE,
    "REACTIFS": CONSOMMABLE,
    "CONSOMMABLE": CONSOMMABLE,
    "CONSOMMABLES": CONSOMMABLE,
    "EQUIPEMENT": EQUIPEMENT,
    "EQUIPEMENTS": EQUIPEMENT,
    "INSTRUMENT": EQUIPEMENT,
    "APPAREIL": EQUIPEMENT,
    "PRESTATION": PRESTATION,
    "PIECE": PIECE,
    "PIECES": PIECE,
    "PIECE DETACHEE": PIECE,
    "PIECES DETACHEES": PIECE,
}

# Préfixes, évalués après la table exacte. « SERVICE DIVERS » et « SERVICE SAV »
# sont deux valeurs distinctes de la même famille : les énumérer une à une
# casserait au premier libellé de service ajouté dans l'ERP.
_PREFIXES_FAMILLE = (
    ("SERVICE", PRESTATION),
    ("PRESTATION", PRESTATION),
    ("CONTRAT", PRESTATION),
    ("MAINTENANCE", PRESTATION),
    ("REACTIF", CONSOMMABLE),
    ("CONSOMMABLE", CONSOMMABLE),
    ("EQUIPEMENT", EQUIPEMENT),
    ("PIECE", PIECE),
)

# Cache des familles ERP par désignation, rempli à la demande. Une désignation
# peut porter plusieurs familles selon les lignes ; on retient la plus fréquente
# EN VALEUR, et les ex æquo sont départagés par ordre alphabétique pour que le
# résultat ne dépende pas de l'ordre des lignes.
_familles_erp: Optional[Dict[str, str]] = None

# Motif du dernier échec de chargement, s'il y en a eu un. Publié dans les
# métriques : un classement qui a basculé sur son repli doit le dire.
_echec_chargement: Optional[str] = None


def charger_familles_erp(con=None) -> Dict[str, str]:
    """Famille ERP dominante par désignation, lue dans `sales_lines`."""
    global _familles_erp
    if _familles_erp is not None:
        return _familles_erp

    fermer = con is None
    try:
        if con is None:
            from ml_engine.stock.flux_reels import _connect
            con = _connect()
        try:
            rows = con.execute("""
                SELECT upper(trim(designation)) AS cle,
                       upper(trim(famille))     AS famille,
                       sum(abs(montant))        AS poids
                FROM sales_lines
                WHERE designation IS NOT NULL AND trim(designation) <> ''
                  AND famille IS NOT NULL AND trim(famille) <> ''
                GROUP BY 1, 2
                ORDER BY 1, poids DESC, famille
            """).fetchall()
        finally:
            if fermer:
                con.close()
    except Exception as e:
        # Un `except` qui avale une erreur DOIT laisser une trace. Celui-ci n'en
        # laissait aucune, et une connexion fermée passée par erreur a suffi à
        # faire conclure que la nomenclature n'existait pas — alors qu'elle est
        # renseignée à 99,9 %. Le silence a coûté une conclusion fausse sur les
        # données, pas seulement un chiffre.
        global _echec_chargement
        _echec_chargement = f"{type(e).__name__}: {e}"
        print(f"[nomenclature] ÉCHEC de lecture des familles ERP — "
              f"{_echec_chargement}")
        print("[nomenclature]   le classement retombe sur les mots-clés de "
              "libellé, ce qui n'est PAS équivalent.")
        _familles_erp = {}
        return _familles_erp

    # La première ligne de chaque clé est la famille dominante : le tri ci-dessus
    # l'a placée en tête, ex æquo départagés alphabétiquement.
    out: Dict[str, str] = {}
    for cle, famille, _poids in rows:
        if cle not in out:
            out[cle] = famille
    _familles_erp = out
    return out


def _categorie_erp(produit: Optional[str]) -> Optional[str]:
    """Catégorie déduite de la famille ERP, si elle est renseignée et connue."""
    cle = (produit or "").strip().upper()
    if not cle:
        return None
    famille = charger_familles_erp().get(cle)
    if not famille:
        return None
    if famille in _FAMILLE_VERS_CATEGORIE:
        return _FAMILLE_VERS_CATEGORIE[famille]
    for prefixe, categorie in _PREFIXES_FAMILLE:
        if famille.startswith(prefixe):
            return categorie
    # Famille renseignée mais non répertoriée — typiquement la pollution
    # « fournitures d'art ». On ne devine pas : le repli par mots-clés prend le
    # relais, et `mesurer()` compte ces cas pour qu'une famille ERP inconnue se
    # voie au lieu d'être absorbée en silence.
    return None


def classer(produit: Optional[str]) -> str:
    """Catégorie d'une référence.

    **La famille ERP prime**, toujours. Le classement par mots-clés n'intervient
    qu'à défaut : un libellé est déclaratif et changeant, une famille saisie dans
    l'ERP est structurelle. C'est la même hiérarchie que celle appliquée à
    `INDICMVTSTOCK` dans `flux_reels`, où l'indicateur ERP prime sur le libellé.

    L'ordre d'évaluation du repli est celui documenté en tête de section. Il n'est
    pas interchangeable : le permuter reclasserait des contrats en équipements et
    des kits de maintenance en réactifs.
    """
    p = (produit or "").strip()
    depuis_erp = _categorie_erp(produit)

    if depuis_erp is not None:
        # ══ UNE SEULE EXCEPTION, ET ELLE N'EST PAS UN CONTOURNEMENT ══
        #
        # La famille ERP n'offre que trois valeurs : REACTIF, EQUIPEMENT,
        # SERVICE. Elle ne comporte **aucune catégorie « pièce détachée »**.
        # Quand un kit de joints est saisi en REACTIF, l'ERP n'affirme donc pas
        # qu'il périme : il constate qu'aucune case ne lui convient.
        #
        # Le mot-clé de pièce est ici PLUS SPÉCIFIQUE que la famille, et non
        # concurrent : il distingue à l'intérieur d'une classe que l'ERP ne
        # subdivise pas. C'est la seule raison pour laquelle il peut la préciser,
        # et cela ne vaut que dans ce sens — un EQUIPEMENT ou une PRESTATION
        # déclarés dans l'ERP sont respectés sans discussion.
        #
        # Sans cette règle, les 90 711 DT de faux positifs corrigés plus tôt
        # (kit de joints, kit d'upgrade, kit de maintenance préventive)
        # reviendraient dans la perte annoncée.
        if depuis_erp == CONSOMMABLE and _MOTIFS_PIECE.search(p):
            return PIECE
        return depuis_erp
    if not p:
        # Une désignation vide n'est pas un consommable : c'est une absence de
        # donnée. La classer par défaut ferait entrer un inconnu dans la classe
        # qui déclenche des pertes.
        return PRESTATION
    if _MOTIFS_PRESTATION.search(p):
        return PRESTATION
    if _MOTIFS_PIECE.search(p):
        return PIECE
    if _MOTIFS_EQUIPEMENT.search(p):
        return EQUIPEMENT
    return CONSOMMABLE


def origine_du_classement(produit: Optional[str]) -> str:
    """D'où vient la catégorie : `erp`, `erp_precise`, `mot_cle`, ou `defaut`.

    Distinction essentielle pour lire les chiffres du module : une perte annoncée
    sur une référence classée PAR DÉFAUT repose sur une absence de signal, non sur
    un signal. Les trois cas ne méritent pas la même confiance, et les confondre
    reviendrait à présenter une ignorance comme une mesure.
    """
    p = (produit or "").strip()
    depuis_erp = _categorie_erp(produit)
    if depuis_erp is not None:
        # Distingué du cas `erp` pur : une référence dont la famille ERP a été
        # précisée par un mot-clé de pièce mérite d'être comptée à part, pour que
        # la portée de cette exception reste chiffrée et vérifiable.
        if depuis_erp == CONSOMMABLE and _MOTIFS_PIECE.search(p):
            return "erp_precise"
        return "erp"
    if not p:
        return "defaut"
    if (_MOTIFS_PRESTATION.search(p) or _MOTIFS_PIECE.search(p)
            or _MOTIFS_EQUIPEMENT.search(p) or _MOTIFS_CONSOMMABLE.search(p)):
        return "mot_cle"
    return "defaut"


def classee_explicitement(produit: Optional[str]) -> bool:
    """La catégorie repose-t-elle sur un signal, quel qu'il soit ?

    Conservée sous ce nom : elle est appelée par les tests et par l'export de
    validation. « Explicitement » couvre désormais la famille ERP comme le motif
    de libellé — seul le classement PAR DÉFAUT reste une absence de signal.
    """
    return origine_du_classement(produit) != "defaut"


def est_perissable(produit: Optional[str]) -> bool:
    """Seuls les consommables périment.

    Un équipement s'amortit, une pièce se conserve, une prestation ne se stocke
    pas. C'est la seule question que le module d'obsolescence pose à ce fichier.
    """
    return classer(produit) == CONSOMMABLE


def _lignes(con) -> List[Tuple[str, float, float]]:
    """(produit, position, valeur_dt) des références à position positive."""
    tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
    if "stock_flux_reel" not in tables:
        return []
    return [(p or "", float(pos or 0), float(v or 0)) for p, pos, v in con.execute("""
        SELECT produit, position, position * cout_unitaire
        FROM stock_flux_reel
        WHERE position > 0 AND cout_unitaire IS NOT NULL
    """).fetchall()]


def mesurer(con=None) -> Dict[str, Any]:
    """Couverture du classement, en nombre de références ET en valeur.

    Les deux mesures disent des choses différentes, et seule la seconde compte
    pour le risque : classer correctement 900 références à 12 DT tout en se
    trompant sur un automate à 356 000 DT serait une réussite sans intérêt.
    """
    fermer = con is None
    if con is None:
        from ml_engine.stock.flux_reels import _connect
        con = _connect()
    try:
        lignes = _lignes(con)
        if not lignes:
            return {
                "disponible": False,
                "motif": ("table stock_flux_reel absente — lancer "
                          "ml_engine.stock.flux_reels"),
            }

        # ══ BUG CORRIGÉ ICI, ET IL A PRODUIT UNE FAUSSE CONCLUSION ══
        #
        # Cet appel se trouvait APRÈS le `finally` qui ferme la connexion. Il
        # opérait donc sur une connexion fermée, son exception était avalée par
        # le `except` de `charger_familles_erp`, et le cache retombait sur un
        # dictionnaire vide.
        #
        # Résultat : « 0 désignation porte une famille dans l'ERP », alors que la
        # colonne est renseignée à **99,9 %** (340 912 lignes sur 340 913). J'en
        # ai conclu que la nomenclature était absente et je l'ai écrit dans le
        # rapport. Une dégradation silencieuse n'a pas seulement dégradé un
        # chiffre : elle a produit une conclusion fausse sur les données.
        #
        # C'est pourquoi tout `except` qui avale une erreur doit laisser une
        # trace. Celui de `charger_familles_erp` en laisse une désormais.
        charger_familles_erp(con)
    finally:
        if fermer:
            con.close()

    par_cat: Dict[str, Dict[str, float]] = {
        c: {"n_references": 0, "valeur_dt": 0.0, "n_explicites": 0,
            "valeur_explicite_dt": 0.0} for c in CATEGORIES}

    # Trois origines, comptées séparément : c'est ce qui permet de dire quelle
    # part du montant annoncé repose sur une donnée ERP plutôt que sur un
    # mot-clé, et quelle part ne repose sur rien.
    par_origine: Dict[str, Dict[str, float]] = {
        o: {"n_references": 0, "valeur_dt": 0.0}
        for o in ("erp", "erp_precise", "mot_cle", "defaut")}

    for produit, _pos, valeur in lignes:
        cat = classer(produit)
        d = par_cat[cat]
        d["n_references"] += 1
        d["valeur_dt"] += valeur

        origine = origine_du_classement(produit)
        par_origine[origine]["n_references"] += 1
        par_origine[origine]["valeur_dt"] += valeur

        if origine != "defaut":
            d["n_explicites"] += 1
            d["valeur_explicite_dt"] += valeur

    n_total = sum(d["n_references"] for d in par_cat.values())
    val_total = sum(d["valeur_dt"] for d in par_cat.values())
    n_expl = sum(d["n_explicites"] for d in par_cat.values())
    val_expl = sum(d["valeur_explicite_dt"] for d in par_cat.values())

    for d in par_origine.values():
        d["valeur_dt"] = round(d["valeur_dt"], 0)
        d["part_valeur_pct"] = round(d["valeur_dt"] / max(val_total, 1) * 100, 1)

    for d in par_cat.values():
        d["valeur_dt"] = round(d["valeur_dt"], 0)
        d["valeur_explicite_dt"] = round(d["valeur_explicite_dt"], 0)
        d["part_valeur_pct"] = round(d["valeur_dt"] / max(val_total, 1) * 100, 1)

    # Le chiffre qui doit être regardé en premier : la part de VALEUR classée
    # consommable — donc susceptible d'être annoncée en perte — sans qu'aucun
    # motif de consommable n'ait été reconnu.
    conso = par_cat[CONSOMMABLE]
    val_conso_defaut = conso["valeur_dt"] - conso["valeur_explicite_dt"]

    return {
        "disponible": True,
        "version": 1,
        "n_references": n_total,
        "valeur_totale_dt": round(val_total, 0),
        "par_categorie": par_cat,
        "par_origine": par_origine,
        "n_designations_avec_famille_erp": len(charger_familles_erp()),
        "hierarchie": (
            "La famille ERP (`ARTICLE_LIBELLE_FAM_STAT1`, renseignée à 99,9 %) "
            "PRIME sur les mots-clés : un libellé est déclaratif et changeant, "
            "une famille saisie dans l'ERP est structurelle. Même hiérarchie que "
            "pour `INDICMVTSTOCK` dans flux_reels."),
        "echec_de_chargement": _echec_chargement,
        "deux_erreurs_documentees": (
            "1) Ce module a d'abord affirmé qu'aucune nomenclature n'existait, "
            "sans avoir interrogé la colonne. 2) Le chemin de lecture ajouté "
            "ensuite renvoyait 0 désignation, ce qui a fait conclure une "
            "deuxième fois à son absence — la cause étant un amorçage de cache "
            "APRÈS fermeture de la connexion, dont l'exception était avalée sans "
            "trace. Un `except` muet n'a pas seulement dégradé un chiffre : il a "
            "produit une conclusion fausse sur les données. Le champ "
            "`echec_de_chargement` ci-dessus existe pour que cela ne puisse plus "
            "se reproduire en silence."),
        "couverture_references_pct": round(n_expl / max(n_total, 1) * 100, 1),
        "couverture_valeur_pct": round(val_expl / max(val_total, 1) * 100, 1),
        "valeur_consommable_par_defaut_dt": round(val_conso_defaut, 0),
        "part_consommable_par_defaut_pct": round(
            val_conso_defaut / max(val_total, 1) * 100, 1),
        "pourquoi_ce_chiffre_compte": (
            "Une référence classée « consommable » PAR DÉFAUT l'est faute d'avoir "
            "reconnu quoi que ce soit dans son libellé. C'est la seule classe qui "
            "déclenche une perte par péremption : le montant ci-dessus mesure "
            "donc la valeur exposée à une erreur de classement, et lui seul "
            "borne honnêtement la fiabilité du module d'obsolescence."),
        "limite_residuelle": (
            "Ce qui reste classé par mot-clé ou par défaut correspond aux "
            "désignations dont la famille ERP est vide ou porte une valeur non "
            "répertoriée. Ces cas sont comptés ci-dessus et exportés dans "
            "reports/nomenclature_a_valider.csv, triés par valeur. Une famille "
            "ERP non répertoriée n'est jamais devinée : le repli prend le relais "
            "et le compteur la rend visible."),
    }


def exporter_pour_validation(con=None, limite: int = 300) -> Optional[Path]:
    """Fichier que l'entreprise corrige ligne par ligne.

    Trié par VALEUR décroissante, et non par ordre alphabétique : si l'entreprise
    ne valide que les trente premières lignes, ce sont celles qui portent le plus
    d'argent. Une grille d'audit doit être rentable à remplir partiellement.
    """
    fermer = con is None
    if con is None:
        from ml_engine.stock.flux_reels import _connect
        con = _connect()
    try:
        lignes = _lignes(con)
    finally:
        if fermer:
            con.close()

    if not lignes:
        return None

    lignes.sort(key=lambda t: -t[2])
    chemin = REPORTS_DIR / "nomenclature_a_valider.csv"
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    with open(chemin, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["produit", "valeur_en_stock_dt", "categorie_deduite",
                    "deduite_par", "perime_t_il", "CORRECTION_ENTREPRISE",
                    "duree_de_conservation_mois"])
        _ORIGINES = {"erp": "famille ERP",
                     "erp_precise": "famille ERP + pièce détachée reconnue",
                     "mot_cle": "mot-clé du libellé",
                     "defaut": "DÉFAUT — aucun signal"}
        for produit, _pos, valeur in lignes[:limite]:
            cat = classer(produit)
            w.writerow([
                produit,
                round(valeur, 0),
                cat,
                _ORIGINES[origine_du_classement(produit)],
                "oui" if cat == CONSOMMABLE else "non",
                "",     # l'entreprise écrit la bonne catégorie si celle-ci est fausse
                "",     # et la durée de conservation réelle si elle la connaît
            ])
    return chemin


def afficher() -> None:
    m = mesurer()
    if not m.get("disponible"):
        print(f"\n{m.get('motif')}\n")
        return

    def dt(v: float) -> str:
        return f"{v:,.0f} DT".replace(",", " ")

    print("\n" + "=" * 78)
    print("  NOMENCLATURE PRODUIT — couverture du classement par libellé")
    print("=" * 78)
    print(f"\n  Références valorisées : {m['n_references']:,}".replace(",", " "))
    print(f"  Valeur totale         : {dt(m['valeur_totale_dt'])}")

    print(f"\n  {'catégorie':<18}{'réfs':>7}{'valeur':>16}{'part':>8}{'motif reconnu':>16}")
    for cat, d in m["par_categorie"].items():
        print(f"  {cat:<18}{d['n_references']:>7}{dt(d['valeur_dt']):>16}"
              f"{d['part_valeur_pct']:>7.1f}%{d['n_explicites']:>12}/{d['n_references']}")

    print(f"\n  {'origine du classement':<26}{'réfs':>7}{'valeur':>16}{'part':>8}")
    _LIB = {"erp": "famille ERP",
            "erp_precise": "ERP + pièce reconnue",
            "mot_cle": "mot-clé du libellé",
            "defaut": "DÉFAUT — aucun signal"}
    for o, d in m["par_origine"].items():
        print(f"  {_LIB[o]:<26}{d['n_references']:>7}{dt(d['valeur_dt']):>16}"
              f"{d['part_valeur_pct']:>7.1f}%")
    print(f"\n  ({m['n_designations_avec_famille_erp']} désignations portent une "
          "famille dans l'ERP)")

    print(f"\n  Couverture en références : {m['couverture_references_pct']} %")
    print(f"  Couverture en valeur     : {m['couverture_valeur_pct']} %")
    print(f"\n  VALEUR EXPOSÉE À UNE ERREUR DE CLASSEMENT :")
    print(f"    {dt(m['valeur_consommable_par_defaut_dt'])}  "
          f"({m['part_consommable_par_defaut_pct']} % du stock valorisé)")
    print("    — classée « consommable » faute d'avoir reconnu son libellé,")
    print("      donc susceptible d'être annoncée en perte à tort.")

    chemin = exporter_pour_validation()
    if chemin:
        print(f"\n  Grille de correction écrite : {chemin.name}")
        print("  (triée par valeur : les premières lignes sont les plus rentables")
        print("   à faire valider par l'entreprise)")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json.dump(m, open(REPORTS_DIR / "nomenclature_metrics.json", "w",
                      encoding="utf-8"), indent=2, ensure_ascii=False)
    print("=" * 78 + "\n")


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    afficher()
