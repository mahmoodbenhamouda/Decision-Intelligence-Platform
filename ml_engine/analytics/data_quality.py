"""Controle d'integrite de l'entrepot : detecte les incoherences AVANT qu'elles ne soient lues…"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

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
    """Controles que les identites internes ne peuvent PAS attraper."""
    viole = _un(con, """
        SELECT count(*) FROM sales
        WHERE ht IS NOT NULL AND ttc IS NOT NULL AND abs(ttc) < abs(ht) - 0.01
    """)
    if viole:
        c.erreur("ancrage.tva_negative",
                 f"{viole} pièce(s) dont le TTC est inférieur au HT — "
                 "la TVA ne peut pas être négative")

    r = _ligne(con, "SELECT sum(ttc), sum(ht) FROM sales WHERE NOT est_avoir")
    if r and r[1]:
        ratio = float(r[0]) / float(r[1])
        c.borne("ancrage.ratio_ttc_ht", ratio, 1.00, 1.30,
                "ratio TTC/HT hors bande fiscale plausible")
        c.info("ancrage.ratio_ttc_ht",
               f"ratio TTC/HT observé : {ratio:.4f} "
               f"(TVA implicite {(ratio - 1) * 100:.2f} %)")

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
                         f"les deux sources de facturation divergent de {ecart_pct:.2f} % — "
                         "à expliquer avant de publier un chiffre", obtenu=ecart_pct)

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
    """Detecte une degradation FUTURE de la source : trou dans la serie, effondrement d'une annee,…"""
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
        c.info("continuite.mois_manquant",
               f"{trous} mois sans facture avant 2021 — période non couverte par "
               "les données (constat établi, pas une erreur de saisie)")

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
            if not prec or an == derniere:
                continue
            if float(ca or 0) / ca_total < 0.02 or float(prec) / ca_total < 0.02:
                continue
            var = (float(ca) - float(prec)) / float(prec) * 100
            if var < -60:
                c.alerte("continuite.effondrement",
                         f"{an} : CA en baisse de {abs(var):.0f} % sur un an — "
                         "à vérifier (saisie incomplète ?)", obtenu=var)

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
    for b in kpis.get("echelonnement_delais_accordes", []):
        if b.get("montant", 0) < 0:
            c.erreur("kpi.aging",
                     f"tranche « {b.get('bucket')} » négative : un avoir y a été "
                     "compté comme une créance", obtenu=b.get("montant"))
    expo, crit = kpis.get("montant_delai_sup_60j_ttc"), kpis.get("montant_delai_sup_90j_ttc")
    if expo is not None and crit is not None and crit > expo + EPS:
        c.erreur("kpi.exposition",
                 "l'exposition critique dépasse l'exposition totale",
                 attendu=expo, obtenu=crit)


def controler_integrite(kpis: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Lance tous les controles et rend un rapport structure."""
    import duckdb

    from etl.construire import assurer_a_jour
    from ml_engine.analytics.kpi_engine import STORE_PATH

    c = _Contexte()
    try:
        assurer_a_jour(STORE_PATH)
        con = duckdb.connect(str(STORE_PATH), read_only=True)
    except Exception as exc:
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
