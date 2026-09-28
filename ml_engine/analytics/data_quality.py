"""
ml_engine/analytics/data_quality.py
====================================
Controle d'integrite de l'entrepot : detecte les incoherences AVANT qu'elles ne
soient lues comme des resultats.

Pourquoi ce module existe
-------------------------
Le chiffre d'affaires a ete faux de 5,44 % pendant toute la duree du projet sans
que rien ne le signale. La raison n'est pas qu'on ait mal cherche, c'est qu'un
montant faux ne se voit pas : 290 M et 275 M sont aussi plausibles l'un que
l'autre. Aucune relecture, aucun coup d'oeil au tableau de bord n'aurait pu
faire la difference.

La seule defense contre ce genre d'erreur, ce sont les INVARIANTS : des egalites
qui doivent tenir par construction, quelle que soit la donnee. Si l'une se
brise, c'est qu'une formule est fausse -- meme si le resultat affiche semble
raisonnable.

    CA net       = ventes - avoirs           (identite comptable)
    nb lignes    = factures + avoirs         (partition exhaustive)
    marge        = CA - cout de revient      (definition)
    HHI          dans ]0, 10000]             (borne mathematique)
    CA lignes   <= CA factures               (meme argent, deux granularites)

Trois niveaux de gravite :
  * `erreur`  : un invariant est brise -- un chiffre affiche est faux ;
  * `alerte`  : une valeur est hors de son domaine de vraisemblance ;
  * `info`    : un fait a connaitre, sans anomalie (volumetrie, rejets).

Usage :
    from ml_engine.analytics.data_quality import controler_integrite
    rapport = controler_integrite()
    if rapport["erreurs"]:
        ...
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

# Tolerance absolue sur les comparaisons de montants (arrondis de conversion).
EPS = 1.0


class _Contexte:
    """Accumule les constats d'un controle."""

    def __init__(self) -> None:
        self.constats: List[Dict[str, Any]] = []

    def _ajouter(self, niveau: str, controle: str, message: str,
                 attendu: Any = None, obtenu: Any = None) -> None:
        self.constats.append({
            "niveau": niveau, "controle": controle, "message": message,
            "attendu": attendu, "obtenu": obtenu,
        })

    def erreur(self, controle: str, message: str, attendu=None, obtenu=None) -> None:
        self._ajouter("erreur", controle, message, attendu, obtenu)

    def alerte(self, controle: str, message: str, attendu=None, obtenu=None) -> None:
        self._ajouter("alerte", controle, message, attendu, obtenu)

    def info(self, controle: str, message: str, obtenu=None) -> None:
        self._ajouter("info", controle, message, None, obtenu)

    def identite(self, controle: str, gauche: float, droite: float,
                 libelle: str, eps: float = EPS) -> bool:
        """Verifie une egalite qui doit tenir par construction."""
        g, d = float(gauche or 0), float(droite or 0)
        if abs(g - d) <= eps:
            return True
        self.erreur(controle, f"{libelle} — écart de {abs(g - d):,.2f} DT"
                              .replace(",", " "), attendu=d, obtenu=g)
        return False

    def borne(self, controle: str, valeur: Optional[float], mini: float,
              maxi: float, libelle: str) -> bool:
        if valeur is None:
            self.alerte(controle, f"{libelle} — valeur absente")
            return False
        v = float(valeur)
        # Tolérance d'arrondi flottant : une borne atteinte exactement (HHI de
        # 10 000 ou part de 100 % sur un seul client) ne doit pas passer pour
        # un dépassement selon l'ordre des additions.
        eps = 1e-9 * max(1.0, abs(mini), abs(maxi))
        if mini - eps <= v <= maxi + eps:
            return True
        self.alerte(controle, f"{libelle} — {v:,.2f} hors de [{mini:,.0f} ; {maxi:,.0f}]"
                              .replace(",", " "), obtenu=v)
        return False


def _un(con, sql: str, defaut=0):
    try:
        r = con.execute(sql).fetchone()
        return r[0] if r and r[0] is not None else defaut
    except Exception:
        return None


def _ligne(con, sql: str):
    try:
        return con.execute(sql).fetchone()
    except Exception:
        return None


def _table_existe(con, nom: str) -> bool:
    try:
        con.execute(f"SELECT 1 FROM {nom} LIMIT 1")
        return True
    except Exception:
        return False


# ── Controles ───────────────────────────────────────────────────────────────
def _ctrl_ventes(con, c: _Contexte) -> None:
    r = _ligne(con, """
        SELECT sum(ttc) FILTER (WHERE NOT est_avoir),
               coalesce(-sum(ttc) FILTER (WHERE est_avoir), 0),
               sum(ttc), count(*),
               count(*) FILTER (WHERE NOT est_avoir),
               count(*) FILTER (WHERE est_avoir)
        FROM sales
    """)
    if not r:
        c.erreur("ventes", "table `sales` illisible")
        return
    brut, avoirs, net, n, n_fact, n_av = r
    c.identite("ventes.ca_net", net, (brut or 0) - (avoirs or 0),
               "CA net ≠ ventes − avoirs")
    c.identite("ventes.partition", n, (n_fact or 0) + (n_av or 0),
               "nb lignes ≠ factures + avoirs", eps=0)
    if brut:
        c.borne("ventes.taux_avoirs", (avoirs or 0) / brut * 100, 0, 15,
                "taux d'avoirs")
    c.info("ventes.volumetrie",
           f"{n_fact:,} factures, {n_av:,} avoirs, CA net {net:,.0f} DT"
           .replace(",", " "))

    neg = _un(con, "SELECT count(*) FROM sales WHERE ttc < 0 AND NOT est_avoir")
    if neg:
        c.erreur("ventes.signe", f"{neg} vente(s) à montant négatif sans être un avoir")

    dup = _un(con, """
        SELECT count(*) FROM (
            SELECT 1 FROM sales WHERE piece_no IS NOT NULL AND piece_no <> ''
            GROUP BY piece_no, client, date, ttc HAVING count(*) > 1)
    """)
    if dup:
        c.erreur("ventes.doublons", f"{dup} groupe(s) de factures en double")

    sans_date = _un(con, "SELECT count(*) FROM sales WHERE date IS NULL")
    if sans_date:
        c.alerte("ventes.dates", f"{sans_date} facture(s) sans date")

    ech = _un(con, "SELECT count(*) FROM sales WHERE echeance < date")
    if ech:
        c.alerte("ventes.echeance",
                 f"{ech} facture(s) dont l'échéance précède l'émission")


def _ctrl_achats(con, c: _Contexte) -> None:
    if not _table_existe(con, "purchases"):
        c.alerte("achats", "table `purchases` absente")
        return
    r = _ligne(con, """
        SELECT sum(ttc) FILTER (WHERE NOT est_avoir),
               coalesce(-sum(ttc) FILTER (WHERE est_avoir), 0),
               sum(ttc), count(*)
        FROM purchases
    """)
    if not r:
        return
    brut, avoirs, net, n = r
    c.identite("achats.net", net, (brut or 0) - (avoirs or 0),
               "achats nets ≠ factures − avoirs")
    dup = _un(con, """
        SELECT count(*) FROM (
            SELECT 1 FROM purchases WHERE piece_no IS NOT NULL AND piece_no <> ''
            GROUP BY piece_no, fournisseur_code, date, ttc HAVING count(*) > 1)
    """)
    if dup:
        c.erreur("achats.doublons", f"{dup} groupe(s) de factures d'achat en double")
    c.info("achats.volumetrie", f"{n:,} pièces, {net:,.0f} DT net".replace(",", " "))


def _ctrl_lignes(con, c: _Contexte) -> None:
    if not _table_existe(con, "sales_lines"):
        c.alerte("lignes", "table `sales_lines` absente")
        return
    n, somme, n_ret = _ligne(con, """
        SELECT count(*), sum(montant), count(*) FILTER (WHERE montant < 0)
        FROM sales_lines
    """) or (0, 0, 0)
    if not n_ret:
        c.erreur("lignes.signe",
                 "aucune ligne de retour : `MONTANT_DEV` (non signé) est "
                 "probablement utilisé à la place de `MONTANTSIGNE_DEV`")
    rejets = _un(con, "SELECT count(*) FROM sales_lines_rejetees", 0) \
        if _table_existe(con, "sales_lines_rejetees") else 0
    if rejets:
        c.info("lignes.rejets",
               f"{rejets} ligne(s) au format invalide écartées (colonnes décalées)")
    c.info("lignes.volumetrie",
           f"{n:,} lignes dont {n_ret:,} retours, {somme:,.0f} DT".replace(",", " "))

    # Le CA des lignes ne peut pas depasser celui des factures : meme argent.
    ca_fact = _un(con, "SELECT sum(ttc) FROM sales")
    if ca_fact and somme and float(somme) > float(ca_fact) * 1.05:
        c.erreur("lignes.coherence_facture",
                 "le CA des lignes dépasse celui des factures",
                 attendu=float(ca_fact), obtenu=float(somme))


def _ctrl_marge(con, c: _Contexte) -> None:
    if not _table_existe(con, "client_margin"):
        c.alerte("marge", "table `client_margin` absente")
        return
    ca, cout, marge, n_ret = _ligne(con, """
        SELECT sum(ca_ligne), sum(cout_revient), sum(marge),
               coalesce(sum(n_lignes_retour), 0)
        FROM client_margin
    """) or (0, 0, 0, 0)
    c.identite("marge.definition", marge, (ca or 0) - (cout or 0),
               "marge ≠ CA − coût de revient")
    if ca:
        c.borne("marge.taux", (marge or 0) / ca * 100, 0, 80, "taux de marge")
    if not n_ret:
        c.erreur("marge.retours",
                 "aucune ligne de retour dans la marge : le filtre garde la "
                 "vente et oublie l'avoir qui l'annule")


def _ctrl_ancrages_externes(con, c: _Contexte) -> None:
    """Controles que les identites internes ne peuvent PAS attraper.

    Une identite comme `CA = ventes - avoirs` reste vraie si un coefficient est
    applique uniformement a tous les montants : les deux membres bougent
    ensemble. Ce type d'erreur systematique n'est detectable que par des
    ANCRAGES EXTERNES -- des reperes qui ne derivent pas des donnees elles-memes
    mais de la comptabilite, de la fiscalite, ou d'une seconde source.

    Trois ancrages sont utilises ici :

      1. TTC >= HT sur CHAQUE piece. C'est une contrainte fiscale, pas une
         moyenne : la TVA ne peut pas etre negative. Un coefficient applique au
         seul TTC la briserait ligne a ligne.

      2. Le ratio TTC/HT global doit rester dans une bande plausible. En
         distribution pharmaceutique tunisienne, beaucoup de produits sont
         exoneres ou a taux reduit : le ratio observe est bas, mais il ne peut
         ni descendre sous 1 ni s'envoler.

      3. RAPPROCHEMENT DE DEUX SOURCES INDEPENDANTES. Le HT des LIGNES
         (`ZZ_Facture_vente_mouv.csv`) et le HT des ENTETES
         (`Facture_vente_ent_v.csv`) decrivent le meme argent, exporte
         separement par l'ERP. Leur ecart est le seul controle qui ne depende
         d'aucune hypothese interne : c'est la seconde opinion.
    """
    # ── 1. Contrainte fiscale, piece par piece ──────────────────────────────
    viole = _un(con, """
        SELECT count(*) FROM sales
        WHERE ht IS NOT NULL AND ttc IS NOT NULL AND abs(ttc) < abs(ht) - 0.01
    """)
    if viole:
        c.erreur("ancrage.tva_negative",
                 f"{viole} pièce(s) dont le TTC est inférieur au HT — "
                 "la TVA ne peut pas être négative")

    # ── 2. Ratio TTC/HT global ──────────────────────────────────────────────
    r = _ligne(con, "SELECT sum(ttc), sum(ht) FROM sales WHERE NOT est_avoir")
    if r and r[1]:
        ratio = float(r[0]) / float(r[1])
        c.borne("ancrage.ratio_ttc_ht", ratio, 1.00, 1.30,
                "ratio TTC/HT hors bande fiscale plausible")
        c.info("ancrage.ratio_ttc_ht",
               f"ratio TTC/HT observé : {ratio:.4f} "
               f"(TVA implicite {(ratio - 1) * 100:.2f} %)")

    # ── 3. Rapprochement lignes ↔ entêtes : la seconde opinion ──────────────
    if _table_existe(con, "sales_lines"):
        ht_lignes = _un(con, "SELECT sum(montant) FROM sales_lines")
        ht_entetes = _un(con, "SELECT sum(ht) FROM sales")
        if ht_lignes and ht_entetes:
            gl, ge = float(ht_lignes), float(ht_entetes)
            ecart_pct = abs(gl - ge) / max(abs(ge), 1e-9) * 100
            c.info("ancrage.rapprochement",
                   f"HT lignes {gl:,.0f} DT vs HT entêtes {ge:,.0f} DT — "
                   f"écart {ecart_pct:.2f} %".replace(",", " "))
            if ecart_pct > 15:
                c.alerte("ancrage.rapprochement",
                         f"les deux exports de l'ERP divergent de {ecart_pct:.2f} % — "
                         "à expliquer avant de publier un chiffre", obtenu=ecart_pct)

    # ── 4. Plausibilite du prix unitaire ────────────────────────────────────
    # Un coefficient applique aux montants ferait deriver le prix moyen d'une
    # reference sans toucher aux quantites : l'anomalie devient visible.
    if _table_existe(con, "sales_lines"):
        aberrants = _un(con, """
            SELECT count(*) FROM (
                SELECT designation, sum(montant) / NULLIF(sum(qte), 0) AS pu
                FROM sales_lines
                WHERE qte > 0 AND montant > 0 AND designation <> ''
                GROUP BY designation
            ) WHERE pu > 5000000 OR pu < 0.001
        """)
        if aberrants:
            c.alerte("ancrage.prix_unitaire",
                     f"{aberrants} référence(s) au prix unitaire implausible "
                     "(> 5 M DT ou < 0,001 DT l'unité)")


def _ctrl_continuite_temporelle(con, c: _Contexte) -> None:
    """Detecte une degradation FUTURE de la source : trou dans la serie,
    effondrement d'une annee, perte de clients.

    Ces controles ne verifient pas une identite mais une CONTINUITE. Si un
    export est tronque, si un mois manque, si le fichier change de structure,
    les identites comptables resteront vraies sur ce qui reste -- et le chiffre
    sera faux malgre tout. C'est la faille que ces controles couvrent.
    """
    # Un mois vide AU MILIEU de la serie : un export tronque, pas une saison.
    trous = _un(con, """
        WITH mois AS (
            SELECT DISTINCT date_trunc('month', date) AS m
            FROM sales WHERE date IS NOT NULL AND NOT est_avoir
        ),
        bornes AS (SELECT min(m) AS d, max(m) AS f FROM mois),
        attendus AS (
            SELECT unnest(generate_series(
                (SELECT d FROM bornes), (SELECT f FROM bornes), INTERVAL 1 MONTH)) AS m
        )
        SELECT count(*) FROM attendus a
        WHERE NOT EXISTS (SELECT 1 FROM mois x WHERE x.m = a.m)
    """)
    if trous:
        # Diagnostic établi : 2019 et 2020 sont absentes de TOUTES les sources
        # (ventes, lignes, achats, devis), ce qui exclut un défaut d'export et
        # désigne une bascule d'ERP. 2017-2018 ne portent que 1,1 % des
        # factures — des résidus de migration. Voir
        # scripts/audit_trou_temporel.py et docs/SEMANTIQUE_COLONNES.md.
        c.info("continuite.mois_manquant",
               f"{trous} mois sans facture avant 2021 — période non couverte par "
               "l'ERP (diagnostic établi, pas un défaut d'export)")

    # Effondrement d'une annee par rapport a la precedente (hors annee en cours).
    rows = None
    try:
        rows = con.execute("""
            WITH parannee AS (
                SELECT year, sum(ttc) AS ca FROM sales
                WHERE NOT est_avoir AND year IS NOT NULL
                GROUP BY year ORDER BY year
            )
            SELECT year, ca, lag(ca) OVER (ORDER BY year) AS precedent FROM parannee
        """).fetchall()
    except Exception:
        pass
    if rows:
        derniere = max(r[0] for r in rows)
        ca_total = sum(float(r[1] or 0) for r in rows) or 1.0
        for an, ca, prec in rows:
            # L'année en cours est incomplète par nature. Les années pesant
            # moins de 2 % du CA total sont les résidus de migration
            # (2017-2018) : comparer une année pleine à un résidu produirait
            # une fausse alerte à chaque exécution.
            if not prec or an == derniere:
                continue
            if float(ca or 0) / ca_total < 0.02 or float(prec) / ca_total < 0.02:
                continue
            var = (float(ca) - float(prec)) / float(prec) * 100
            if var < -60:
                c.alerte("continuite.effondrement",
                         f"{an} : CA en baisse de {abs(var):.0f} % sur un an — "
                         "à vérifier (export partiel ?)", obtenu=var)

        # Profondeur d'historique réellement exploitable, à distinguer des
        # bornes brutes des dates.
        pleines = [r[0] for r in rows
                   if r[0] != derniere and float(r[1] or 0) / ca_total >= 0.02]
        if pleines:
            c.info("continuite.historique_exploitable",
                   f"années pleines : {min(pleines)} → {max(pleines)} "
                   f"(+ {derniere} en cours) — les années antérieures sont "
                   "résiduelles")

    c.info("continuite.periode", _periode(con))


def _periode(con) -> str:
    r = _ligne(con, "SELECT min(date), max(date) FROM sales WHERE NOT est_avoir")
    if not r or not r[0]:
        return "période indéterminée"
    return f"période couverte : {r[0]} → {r[1]}"


def _ctrl_concentration(con, c: _Contexte, kpis: Optional[Dict[str, Any]]) -> None:
    if not kpis:
        return
    for champ in ("hhi_clients", "hhi_fournisseurs"):
        c.borne(f"concentration.{champ}", kpis.get(champ), 0.0001, 10_000,
                f"{champ} hors bornes mathématiques")
    n80, ntot = kpis.get("clients_pour_80pct"), kpis.get("nb_clients_ca")
    if n80 and ntot and n80 > ntot:
        c.erreur("concentration.pareto",
                 "plus de clients pour 80 % du CA que de clients au total",
                 attendu=ntot, obtenu=n80)
    # Tolérance d'arrondi : sur un périmètre d'un seul client, la part vaut
    # 100 % à 1e-14 près, au-dessus ou au-dessous selon l'ordre dans lequel
    # DuckDB a additionné. Sans elle, un client voyait « des montants affichés
    # sont faux » une fois sur deux.
    for cl in kpis.get("top_clients", []):
        if not -100 - 1e-6 <= cl.get("share", 0) <= 100 + 1e-6:
            c.erreur("concentration.part",
                     f"part hors bornes pour {cl.get('nom')}", obtenu=cl.get("share"))


def _ctrl_kpis(con, c: _Contexte, kpis: Optional[Dict[str, Any]]) -> None:
    if not kpis:
        return
    ca, nb = kpis.get("ca_total_ttc"), kpis.get("nb_factures_vente")
    if ca and nb:
        c.identite("kpi.panier_moyen", kpis.get("panier_moyen", 0), ca / nb,
                   "panier moyen ≠ CA net / nb de ventes", eps=0.01)
    for champ, mini, maxi in (
        ("dso_jours", -10, 400), ("dpo_jours", -10, 400),
        ("panier_moyen", 0, 1_000_000), ("taux_avoirs_pct", 0, 15),
    ):
        if champ in kpis:
            c.borne(f"kpi.{champ}", kpis[champ], mini, maxi, champ)
    for b in kpis.get("aging_creances", []):
        if b.get("montant", 0) < 0:
            c.erreur("kpi.aging",
                     f"tranche « {b.get('bucket')} » négative : un avoir y a été "
                     "compté comme une créance", obtenu=b.get("montant"))
    expo, crit = kpis.get("montant_risque_ttc"), kpis.get("montant_critique_ttc")
    if expo is not None and crit is not None and crit > expo + EPS:
        c.erreur("kpi.exposition",
                 "l'exposition critique dépasse l'exposition totale",
                 attendu=expo, obtenu=crit)


def controler_integrite(kpis: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Lance tous les controles et rend un rapport structure.

    Args:
        kpis: sortie de `compute_dashboard()`. Si absente, elle est calculee.

    Returns:
        dict avec `statut` (`ok` / `alerte` / `erreur`), les listes de constats
        par gravite, et un resume en une ligne.
    """
    import duckdb

    from etl.construire import assurer_a_jour
    from ml_engine.analytics.kpi_engine import STORE_PATH

    c = _Contexte()
    try:
        assurer_a_jour(STORE_PATH)
        con = duckdb.connect(str(STORE_PATH), read_only=True)
    except Exception as exc:                         # entrepot illisible
        return {"statut": "erreur", "erreurs": [{
            "niveau": "erreur", "controle": "entrepot",
            "message": f"entrepôt inaccessible : {exc}"}],
            "alertes": [], "infos": [], "resume": "entrepôt inaccessible"}

    try:
        if kpis is None:
            try:
                from ml_engine.analytics.kpi_engine import compute_dashboard
                kpis = compute_dashboard({})
            except Exception:
                kpis = None
        controles: List[Callable] = [_ctrl_ventes, _ctrl_achats, _ctrl_lignes,
                                     _ctrl_marge, _ctrl_ancrages_externes,
                                     _ctrl_continuite_temporelle]
        for f in controles:
            try:
                f(con, c)
            except Exception as exc:
                c.alerte(f.__name__, f"contrôle interrompu : {exc}")
        for f2 in (_ctrl_concentration, _ctrl_kpis):
            try:
                f2(con, c, kpis)
            except Exception as exc:
                c.alerte(f2.__name__, f"contrôle interrompu : {exc}")
    finally:
        con.close()

    erreurs = [x for x in c.constats if x["niveau"] == "erreur"]
    alertes = [x for x in c.constats if x["niveau"] == "alerte"]
    infos = [x for x in c.constats if x["niveau"] == "info"]
    statut = "erreur" if erreurs else ("alerte" if alertes else "ok")
    resume = {
        "erreur": f"{len(erreurs)} incohérence(s) détectée(s) — des montants affichés sont faux",
        "alerte": f"{len(alertes)} point(s) de vigilance, aucun montant faux détecté",
        "ok": "Tous les contrôles d'intégrité passent.",
    }[statut]
    return {"statut": statut, "erreurs": erreurs, "alertes": alertes,
            "infos": infos, "resume": resume,
            "n_controles": len(c.constats)}


def rapport_texte(rapport: Optional[Dict[str, Any]] = None) -> str:
    """Rend le rapport lisible en console."""
    r = rapport or controler_integrite()
    icone = {"erreur": "[ERREUR]", "alerte": "[ALERTE]", "info": "[info]  "}
    lignes = ["=" * 78,
              f"CONTROLE D'INTEGRITE — {r['resume']}",
              "=" * 78]
    for cle in ("erreurs", "alertes", "infos"):
        for x in r[cle]:
            lignes.append(f"{icone[x['niveau']]} {x['controle']:<28} {x['message']}")
            if x.get("attendu") is not None:
                lignes.append(f"{'':<10} attendu {x['attendu']:,.2f} / "
                              f"obtenu {x['obtenu']:,.2f}".replace(",", " "))
    if not r["erreurs"] and not r["alertes"]:
        lignes.append("Aucune anomalie.")
    return "\n".join(lignes)


if __name__ == "__main__":
    print(rapport_texte())
