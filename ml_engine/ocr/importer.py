"""
ml_engine/ocr/importer.py
=========================
Enregistrement d'une facture océrisée dans l'entrepôt, et rattachement client.

Pourquoi un module séparé
-------------------------
Jusqu'ici l'OCR *lisait* une facture et la rapprochait de l'ERP, mais ne la
**conservait** pas : fermer l'onglet effaçait le travail, et les montants lus
n'entraient dans aucun indicateur. Ce module referme la boucle.

Principe directeur : ne jamais mélanger le lu et le déclaré
-----------------------------------------------------------
Les factures importées sont écrites dans une table **distincte**
(`factures_importees`), jamais dans `sales`. Deux raisons :

* `sales` est l'export ERP, la référence. Y injecter des montants issus d'un OCR
  à 70 % de confiance corromprait la seule source vérifiable du projet.
* Les indicateurs doivent pouvoir être calculés avec ou sans les imports, et
  l'écart doit rester visible. La vue `sales_augmentee` réunit les deux avec une
  colonne `source` (`erp` / `ocr`).

Rattachement client
-------------------
Le tiers lu est rapproché des clients connus (normalisation + similarité). Trois
issues, toutes explicites dans la réponse :

* `existant`  — un client connu correspond, la facture rejoint son tableau de bord ;
* `nouveau`   — aucun ne correspond : une fiche est créée avec un code `OCR-xxxx` ;
* `ambigu`    — plusieurs candidats proches : rien n'est décidé, l'utilisateur tranche.

Le cas `ambigu` existe pour éviter le rattachement silencieux d'une facture au
mauvais client — une erreur qui fausserait durablement son encours.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

# Au-dessus : on considère que c'est le même client.
SEUIL_RATTACHEMENT = 0.88
# Entre les deux : on demande confirmation plutôt que de trancher seul.
SEUIL_AMBIGUITE = 0.72


def _connect(read_only: bool = False):
    import duckdb
    from ml_engine.analytics.kpi_engine import STORE_PATH
    return duckdb.connect(str(STORE_PATH), read_only=read_only)


def _norm(s: str) -> str:
    """Normalise une raison sociale pour la comparaison.

    « Ling & Consulting S.A.R.L. » et « LING AND CONSULTING SARL » doivent se
    ressembler : on retire les accents, la ponctuation, les formes juridiques et
    les mots vides."""
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\b(s\.?a\.?r\.?l|s\.?a|suarl|sarl|ste|societe|company|co|ltd|inc|group|groupe)\b",
               " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _similarite(a: str, b: str) -> float:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    # Un nom entièrement contenu dans l'autre est un très fort indice
    # (« ling and consulting » vs « ling and consulting tunisie »).
    if na in nb or nb in na:
        return 0.95
    return SequenceMatcher(None, na, nb).ratio()


# Colonnes ajoutées après coup : la migration est additive (ADD COLUMN IF NOT
# EXISTS), aucune ligne existante n'est réécrite. Une ligne ancienne a un `sens`
# NULL, lu comme « vente » : c'était la seule possibilité avant.
_NOUVELLES_COLONNES = [
    ("sens", "VARCHAR"),                 # 'achat' | 'vente' (point de vue de l'entreprise)
    ("fournisseur", "VARCHAR"),          # rattachement (achats)
    ("fournisseur_code", "VARCHAR"),
    ("fournisseur_lu", "VARCHAR"),       # tels que lus sur la facture
    ("client_lu", "VARCHAR"),
    ("taux_tva", "DOUBLE"),
    ("retenue_source", "DOUBLE"),        # TTC - net à payer, quand le net est inférieur
    ("moteur", "VARCHAR"),               # 'layoutlmv3+regles' | 'regles'
    ("statut_validation", "VARCHAR"),    # 'validee_telle_quelle' | 'corrigee' | 'sans_relecture'
    ("corrections", "VARCHAR"),          # JSON {champ: {lu, valide}} — la matière de l'apprentissage
    ("lecture_origine", "VARCHAR"),      # JSON des champs tels que lus, avant correction
    ("champs_confiance", "VARCHAR"),     # JSON
    ("avertissements", "VARCHAR"),       # JSON
    ("fichier_sha256", "VARCHAR"),       # empreinte du document : doublon exact, retrouver le fichier
    ("fichier_chemin", "VARCHAR"),
    # Rapprochement avec l'ERP au moment de l'import (voir reconcile.py), puis
    # recalculable après une mise à jour de l'ERP (`rerapprocher_imports`).
    ("rapprochement_statut", "VARCHAR"),   # rapprochee | ecart_detecte | introuvable | hors_periode…
    ("rapprochement_message", "VARCHAR"),
    ("rapprochement_piece", "VARCHAR"),    # pièce ERP retenue
    ("rapprochement_ecart", "DOUBLE"),
    ("rapproche_le", "TIMESTAMP"),
    ("reglee_le", "DATE"),                 # sortie de l'échéancier (echeancier.py)
]

# Champs qu'un utilisateur peut corriger avant validation, et leur type.
CHAMPS_VALIDABLES = {
    "numero": "texte", "date_facture": "date", "date_echeance": "date",
    "montant_ht": "montant", "montant_tva": "montant", "montant_ttc": "montant",
    "timbre_fiscal": "montant", "net_a_payer": "montant", "taux_tva": "montant",
    "fournisseur": "texte", "client": "texte", "matricule_fiscal": "texte", "devise": "texte",
}


def _table_existe(con, nom: str) -> bool:
    return bool(con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = ?",
                            [nom]).fetchone()[0])


def _assurer_schema(con) -> None:
    """Crée ou complète la table d'import, et les vues unifiées ERP + OCR."""
    con.execute("""
        CREATE TABLE IF NOT EXISTS factures_importees (
            id                BIGINT,
            numero            VARCHAR,
            client_code       VARCHAR,
            client_name       VARCHAR,
            date              DATE,
            echeance          DATE,
            ht                DOUBLE,
            tva               DOUBLE,
            ttc               DOUBLE,
            timbre_fiscal     DOUBLE,
            net_a_payer       DOUBLE,
            devise            VARCHAR,
            matricule_fiscal  VARCHAR,
            fichier_source    VARCHAR,
            confiance_ocr     DOUBLE,
            qualite_lecture   VARCHAR,
            coherence         VARCHAR,
            importe_le        TIMESTAMP,
            importe_par       VARCHAR
        )
    """)
    for col, typ in _NOUVELLES_COLONNES:
        con.execute(f"ALTER TABLE factures_importees ADD COLUMN IF NOT EXISTS {col} {typ}")

    # Ventes : l'ERP fait foi, les VENTES importées s'y ajoutent sans s'y confondre.
    # Les achats n'y entrent jamais : ils gonfleraient le chiffre d'affaires.
    if _table_existe(con, "sales"):
        con.execute("""
            CREATE OR REPLACE VIEW sales_augmentee AS
                SELECT client, client_name, date, echeance, ht, ttc,
                       mode_regl, nbr_article, year, payment_delay_days,
                       'erp' AS source
                  FROM sales
            UNION ALL
                SELECT client_code AS client, client_name, date, echeance, ht, ttc,
                       NULL AS mode_regl, NULL AS nbr_article,
                       CAST(year(date) AS INTEGER) AS year,
                       CASE WHEN echeance IS NOT NULL
                            THEN datediff('day', date, echeance) END AS payment_delay_days,
                       'ocr' AS source
                  FROM factures_importees
                 WHERE coalesce(sens, 'vente') = 'vente'
        """)
    # Achats : même principe, symétrique.
    ocr_achats = """
        SELECT fournisseur, fournisseur_code, date, echeance, ht, ttc,
               FALSE AS est_avoir, NULL AS mode_regl,
               CAST(year(date) AS INTEGER) AS year,
               CASE WHEN echeance IS NOT NULL
                    THEN datediff('day', date, echeance) END AS payment_delay_days,
               'ocr' AS source
          FROM factures_importees WHERE sens = 'achat'"""
    if _table_existe(con, "purchases"):
        con.execute(f"""
            CREATE OR REPLACE VIEW purchases_augmentee AS
                SELECT fournisseur, fournisseur_code, date, echeance, ht, ttc,
                       est_avoir, mode_regl, year, payment_delay_days, 'erp' AS source
                  FROM purchases
            UNION ALL {ocr_achats}
        """)
    else:
        con.execute(f"CREATE OR REPLACE VIEW purchases_augmentee AS {ocr_achats}")


def _clients_connus(con) -> List[Dict[str, str]]:
    rows = con.execute("""
        SELECT DISTINCT client_code, client_name FROM dim_client
        WHERE client_name IS NOT NULL AND client_name <> ''
        UNION
        SELECT DISTINCT client, coalesce(client_name, client) FROM sales
        WHERE client IS NOT NULL AND client <> ''
    """).fetchall()
    return [{"code": r[0], "nom": r[1] or r[0]} for r in rows]


def _fournisseurs_connus(con) -> List[Dict[str, str]]:
    """Fournisseurs de l'ERP (`purchases`) et ceux déjà créés par l'OCR."""
    morceaux = []
    if _table_existe(con, "purchases"):
        morceaux.append("""SELECT DISTINCT fournisseur_code, fournisseur FROM purchases
                           WHERE fournisseur IS NOT NULL AND fournisseur <> ''""")
    if _table_existe(con, "factures_importees"):
        morceaux.append("""SELECT DISTINCT fournisseur_code, fournisseur FROM factures_importees
                           WHERE sens = 'achat' AND fournisseur_code IS NOT NULL""")
    if not morceaux:
        return []
    rows = con.execute(" UNION ".join(morceaux)).fetchall()
    return [{"code": (r[0] or "").strip(), "nom": r[1] or r[0]} for r in rows]


def _rapprocher(tiers: str, connus: List[Dict[str, str]], genre: str) -> Dict[str, Any]:
    """Cherche à quel tiers connu (`genre` : client / fournisseur) correspond un nom lu."""
    if not (tiers or "").strip():
        return {"statut": "inconnu", "motif": "aucun tiers lu sur la facture", "candidats": []}
    scores = sorted(
        ({"code": c["code"], "nom": c["nom"], "score": round(_similarite(tiers, c["nom"]), 3)}
         for c in connus),
        key=lambda c: (-c["score"], c["nom"]))
    meilleurs = [c for c in scores if c["score"] >= SEUIL_AMBIGUITE][:5]
    if meilleurs and meilleurs[0]["score"] >= SEUIL_RATTACHEMENT:
        # Deux candidats aussi bons l'un que l'autre : on ne tranche pas.
        ex_aequo = [c for c in meilleurs if abs(c["score"] - meilleurs[0]["score"]) < 0.02]
        if len(ex_aequo) > 1:
            return {"statut": "ambigu", "candidats": ex_aequo,
                    "motif": f"{len(ex_aequo)} {genre}s également proches de « {tiers} »"}
        return {"statut": "existant", "client": meilleurs[0], "candidats": meilleurs,
                "motif": f"correspondance {meilleurs[0]['score']:.0%} avec « {meilleurs[0]['nom']} »"}
    if meilleurs:
        return {"statut": "ambigu", "candidats": meilleurs,
                "motif": f"aucune correspondance certaine pour « {tiers} » "
                         f"(meilleure : {meilleurs[0]['score']:.0%})"}
    return {"statut": "nouveau", "candidats": [],
            "motif": f"aucun {genre} connu ne ressemble à « {tiers} »"}


def rapprocher_client(tiers: str, con=None) -> Dict[str, Any]:
    """Cherche à quel client connu correspond le tiers lu sur la facture."""
    fermer = con is None
    con = con or _connect(read_only=True)
    try:
        if not (tiers or "").strip():
            return {"statut": "inconnu", "motif": "aucun tiers lu sur la facture", "candidats": []}
        return _rapprocher(tiers, _clients_connus(con), "client")
    finally:
        if fermer:
            con.close()


def rapprocher_fournisseur(tiers: str, con=None) -> Dict[str, Any]:
    """Cherche à quel fournisseur connu (ERP ou import antérieur) correspond le tiers lu."""
    fermer = con is None
    con = con or _connect(read_only=True)
    try:
        if not (tiers or "").strip():
            return {"statut": "inconnu", "motif": "aucun fournisseur lu sur la facture",
                    "candidats": []}
        return _rapprocher(tiers, _fournisseurs_connus(con), "fournisseur")
    finally:
        if fermer:
            con.close()


def _code_nouveau_client(con, nom: str) -> str:
    """Attribue un code au format `OCR-0001`, distinct des codes ERP (`CP…`)."""
    n = con.execute("SELECT count(*) FROM dim_client WHERE client_code LIKE 'OCR-%'").fetchone()[0]
    return f"OCR-{int(n) + 1:04d}"


def _code_nouveau_fournisseur(con) -> str:
    """Attribue un code `OCR-F-0001` à un fournisseur absent de l'ERP."""
    n = con.execute("""SELECT count(DISTINCT fournisseur_code) FROM factures_importees
                       WHERE fournisseur_code LIKE 'OCR-F-%'""").fetchone()[0]
    return f"OCR-F-{int(n) + 1:04d}"


def _to_date(v: Any) -> Optional[date]:
    if isinstance(v, date):
        return v
    if isinstance(v, str) and v.strip():
        try:
            return datetime.fromisoformat(v.strip()[:10]).date()
        except ValueError:
            return None
    return None


def _valeur(type_: str, v: Any) -> Any:
    """Normalise une valeur saisie ou lue, pour comparer et enregistrer."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if type_ == "montant":
        try:
            return round(float(str(v).replace(" ", "").replace(" ", "").replace(",", ".")), 3)
        except ValueError:
            return None
    if type_ == "date":
        d = _to_date(v)
        return d.isoformat() if d else None
    return " ".join(str(v).split())


def nettoyer_saisie(facture: Dict[str, Any]) -> Dict[str, Any]:
    """Ne garde que les champs validables, typés. Une saisie ne peut pas injecter
    de colonne arbitraire."""
    return {k: _valeur(t, facture.get(k)) for k, t in CHAMPS_VALIDABLES.items() if k in facture}


def comparer(lu: Dict[str, Any], valide: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Champs modifiés par l'utilisateur : {champ: {"lu": …, "valide": …}}.

    C'est la matière première de la boucle d'apprentissage : chaque correction
    est une annotation gratuite, faite sur une facture réelle."""
    diff = {}
    for k, t in CHAMPS_VALIDABLES.items():
        if k not in valide:
            continue
        a, b = _valeur(t, lu.get(k)), _valeur(t, valide.get(k))
        if t == "montant" and a is not None and b is not None:
            egal = abs(a - b) < 0.0005
        else:
            egal = a == b
        if not egal:
            diff[k] = {"lu": a, "valide": b}
    return diff


def _colonnes_rapprochement(r: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not r:
        return {"rapprochement_statut": None, "rapprochement_message": None,
                "rapprochement_piece": None, "rapprochement_ecart": None, "rapproche_le": None}
    c = (r.get("candidats") or [{}])[0] if r.get("statut") in (
        "rapprochee", "ecart_detecte", "doublon_probable") else {}
    return {"rapprochement_statut": r.get("statut"), "rapprochement_message": r.get("message"),
            "rapprochement_piece": c.get("numero_erp"), "rapprochement_ecart": c.get("ecart_montant"),
            "rapproche_le": datetime.now()}


def rerapprocher_imports(seulement: Optional[List[str]] = None) -> Dict[str, Any]:
    """Refait le rapprochement des factures déjà importées — après une mise à
    jour de l'ERP, une facture « hors période » ou « introuvable » peut avoir
    été saisie entre-temps.

    `seulement` : limite aux statuts donnés (ex. ["hors_periode", "introuvable"]).
    Le rapprochement lit l'entrepôt en lecture seule : les lectures se font
    connexion d'écriture FERMÉE, puis les mises à jour en une fois.
    """
    from .reconcile import reconcile_invoice
    con = _connect()
    try:
        _assurer_schema(con)
        rows = con.execute("""
            SELECT id, numero, coalesce(sens, 'vente'), fournisseur_lu, client_lu, client_name,
                   fournisseur, strftime(date, '%Y-%m-%d'), ttc, rapprochement_statut
            FROM factures_importees""").fetchall()
    finally:
        con.close()
    nouveaux, avant = [], {}
    for i, num, sens, f_lu, c_lu, c_nom, f_nom, d, ttc, st in rows:
        if seulement and (st or "non_rapprochee") not in seulement:
            continue
        r = reconcile_invoice({"numero": num, "montant_ttc": ttc, "date_facture": d,
                               "fournisseur": f_lu or f_nom, "client": c_lu or c_nom},
                              sens=sens)
        avant[i] = st
        nouveaux.append((i, r))
    con = _connect()
    try:
        for i, r in nouveaux:
            v = _colonnes_rapprochement(r)
            con.execute(f"UPDATE factures_importees SET {', '.join(k + ' = ?' for k in v)} WHERE id = ?",
                        [*v.values(), i])
    finally:
        con.close()
    changes = [{"id": i, "avant": avant[i], "apres": r["statut"]}
               for i, r in nouveaux if avant[i] != r["statut"]]
    return {"n_revus": len(nouveaux), "n_changes": len(changes), "changements": changes}


def _norm_numero(numero: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (numero or "").upper())


def importer_facture(facture: Dict[str, Any],
                     ocr: Optional[Dict[str, Any]] = None,
                     fichier: str = "",
                     utilisateur: str = "",
                     client_code: Optional[str] = None,
                     creer_client: bool = True,
                     *,
                     sens: Optional[str] = "vente",
                     tiers_code: Optional[str] = None,
                     lecture: Optional[Dict[str, Any]] = None,
                     moteur: Optional[str] = None,
                     fichier_sha256: Optional[str] = None,
                     fichier_chemin: Optional[str] = None,
                     rapprochement: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Enregistre une facture océrisée, du bon côté (achat ou vente), et la
    rattache à son tiers.

    Args:
        facture: champs VALIDÉS (éventuellement corrigés par l'utilisateur).
        ocr: métadonnées de lecture (confiance, qualité).
        fichier: nom du fichier d'origine.
        utilisateur: auteur de l'import.
        client_code / tiers_code: rattachement imposé par l'utilisateur (sortie
            du cas `ambigu`). `client_code` pour une vente, `tiers_code` pour
            les deux.
        creer_client: autorise la création d'une fiche pour un tiers inconnu.
        sens: 'vente' (nous sommes l'émetteur) ou 'achat' (nous sommes le client).
        lecture: champs tels que lus AVANT correction. S'il est fourni, les
            écarts avec `facture` sont enregistrés comme corrections.
        moteur, fichier_sha256, fichier_chemin: traçabilité.
        rapprochement: résultat de `reconcile_invoice` sur les valeurs validées,
            calculé AVANT l'appel (il lit l'entrepôt en lecture seule).

    Refus explicites plutôt qu'import silencieux : sans TTC ni numéro, pas
    d'enregistrement ; un doublon n'est jamais réécrit.
    """
    ocr = ocr or {}
    sens = sens or "vente"
    if sens not in ("achat", "vente"):
        return {"ok": False, "erreur": f"sens « {sens} » inconnu : achat ou vente"}
    genre = "client" if sens == "vente" else "fournisseur"
    ttc = facture.get("montant_ttc")
    numero = (facture.get("numero") or "").strip()
    if ttc is None:
        return {"ok": False, "erreur": "montant TTC illisible — facture non enregistrée"}
    if not numero:
        return {"ok": False, "erreur": "numéro de facture illisible — facture non enregistrée"}

    fournisseur_lu = (facture.get("fournisseur") or "").strip() or None
    client_lu = (facture.get("client") or facture.get("tiers") or "").strip() or None
    tiers = (client_lu if sens == "vente" else fournisseur_lu) or ""
    impose = (client_code or tiers_code) if sens == "vente" else tiers_code

    con = _connect()
    try:
        _assurer_schema(con)

        # ── Doublon exact : le même document, octet pour octet ──
        if fichier_sha256:
            deja = con.execute("""SELECT numero, coalesce(client_name, fournisseur), importe_le
                                  FROM factures_importees WHERE fichier_sha256 = ?""",
                               [fichier_sha256]).fetchone()
            if deja:
                return {"ok": False, "statut_client": "doublon",
                        "erreur": f"Ce document a déjà été importé (facture {deja[0]}, "
                                  f"{deja[1]}, le {deja[2]:%d/%m/%Y})"}

        # ── Rattachement ──
        if impose:
            connus = _clients_connus(con) if sens == "vente" else _fournisseurs_connus(con)
            trouve = next((c for c in connus if c["code"] == impose), None)
            rappro = ({"statut": "existant", "client": trouve, "candidats": [],
                       "motif": "rattachement choisi par l'utilisateur"} if trouve else
                      {"statut": "nouveau", "candidats": [], "motif": f"code {impose} inconnu"})
        elif sens == "vente":
            rappro = rapprocher_client(tiers, con)
        else:
            rappro = rapprocher_fournisseur(tiers, con)

        if rappro["statut"] == "ambigu":
            return {"ok": False, "statut_client": "ambigu", "sens": sens,
                    "erreur": rappro["motif"], "candidats": rappro["candidats"],
                    "action_requise": f"Choisissez le {genre} à rattacher, ou confirmez "
                                      f"la création d'un nouveau {genre}."}
        if rappro["statut"] == "existant":
            code, nom, nouveau = rappro["client"]["code"], rappro["client"]["nom"], False
        else:
            if not creer_client:
                return {"ok": False, "statut_client": "inconnu", "sens": sens,
                        "erreur": rappro["motif"],
                        "action_requise": f"Confirmez la création d'un nouveau {genre}."}
            nom = tiers or f"{genre.capitalize()} sans nom ({numero})"
            if sens == "vente":
                code = impose or _code_nouveau_client(con, nom)
                # Colonnes nommées : dim_client porte aussi `origine`, que la
                # table renseigne par défaut (« application ») ; l'ETL le
                # recalcule à la construction suivante (« ocr »).
                con.execute("INSERT INTO dim_client (client_code, client_name) VALUES (?, ?)",
                            [code, nom])
            else:
                code = impose or _code_nouveau_fournisseur(con)
            nouveau = True

        # ── Doublon : même numéro, même tiers, même sens ──
        # (le numéro seul ne suffit pas : deux fournisseurs numérotent tous deux « 000975 »)
        col_code = "client_code" if sens == "vente" else "fournisseur_code"
        deja = con.execute(f"""
            SELECT coalesce(client_name, fournisseur), ttc, importe_le FROM factures_importees
             WHERE regexp_replace(upper(numero), '[^A-Z0-9]', '', 'g') = ?
               AND coalesce(sens, 'vente') = ? AND {col_code} = ?""",
            [_norm_numero(numero), sens, code]).fetchone()
        if deja:
            return {"ok": False, "statut_client": "doublon", "sens": sens,
                    "erreur": f"La facture {numero} de {deja[0]} a déjà été importée "
                              f"({float(deja[1] or 0):,.3f} DT, le {deja[2]:%d/%m/%Y})"
                              .replace(",", " ")}

        corrections = comparer(lecture, facture) if lecture is not None else {}
        statut = ("sans_relecture" if lecture is None else
                  "corrigee" if corrections else "validee_telle_quelle")
        net = facture.get("net_a_payer")
        retenue = (round(float(ttc) - float(net), 3)
                   if net is not None and float(ttc) - float(net) > 0.0005 else None)
        dumps = lambda x: json.dumps(x, ensure_ascii=False, default=str) if x is not None else None

        prochain_id = int(con.execute(
            "SELECT coalesce(max(id), 0) + 1 FROM factures_importees").fetchone()[0])
        valeurs = {
            "id": prochain_id, "numero": numero,
            "client_code": code if sens == "vente" else None,
            "client_name": nom if sens == "vente" else None,
            "fournisseur_code": code if sens == "achat" else None,
            "fournisseur": nom if sens == "achat" else None,
            "sens": sens, "fournisseur_lu": fournisseur_lu, "client_lu": client_lu,
            "date": _to_date(facture.get("date_facture")),
            "echeance": _to_date(facture.get("date_echeance")),
            "ht": facture.get("montant_ht"), "tva": facture.get("montant_tva"), "ttc": ttc,
            "timbre_fiscal": facture.get("timbre_fiscal"), "net_a_payer": net,
            "taux_tva": facture.get("taux_tva"), "retenue_source": retenue,
            "devise": facture.get("devise") or "TND",
            "matricule_fiscal": facture.get("matricule_fiscal"),
            "fichier_source": fichier, "confiance_ocr": ocr.get("confidence"),
            "qualite_lecture": ocr.get("quality"), "coherence": facture.get("coherence"),
            "importe_le": datetime.now(), "importe_par": utilisateur,
            "moteur": moteur, "statut_validation": statut,
            "corrections": dumps(corrections) if lecture is not None else None,
            "lecture_origine": dumps(lecture),
            "champs_confiance": dumps(facture.get("champs_confiance")),
            "avertissements": dumps(facture.get("avertissements")),
            "fichier_sha256": fichier_sha256, "fichier_chemin": fichier_chemin,
            **_colonnes_rapprochement(rapprochement),
        }
        cols = list(valeurs)
        con.execute(f"INSERT INTO factures_importees ({', '.join(cols)}) "
                    f"VALUES ({', '.join('?' * len(cols))})", [valeurs[c] for c in cols])

        tot = con.execute(f"""SELECT count(*), sum(ttc) FROM factures_importees
                              WHERE coalesce(sens, 'vente') = ? AND {col_code} = ?""",
                          [sens, code]).fetchone()
        n_tiers, total_tiers = int(tot[0] or 0), round(float(tot[1] or 0), 3)
        res = {
            "ok": True, "id": prochain_id, "numero": numero, "sens": sens,
            "tiers_code": code, "tiers_nom": nom, "genre_tiers": genre,
            "statut_tiers": "nouveau" if nouveau else "existant",
            "statut_client": "nouveau" if nouveau else "existant",     # compatibilité
            "motif_rattachement": rappro["motif"],
            "montant_ttc": float(ttc), "net_a_payer": net,
            "statut_validation": statut, "n_corrections": len(corrections),
            "corrections": corrections,
            "n_factures_tiers": n_tiers, "total_importe_tiers_dt": total_tiers,
            "rapprochement_statut": (rapprochement or {}).get("statut"),
            "message": (f"{'Vente' if sens == 'vente' else 'Achat'} {numero} rattaché"
                        f"{'e' if sens == 'vente' else ''} à « {nom} »"
                        + (f" — nouveau {genre} créé." if nouveau else ".")
                        + (f" {len(corrections)} correction(s) enregistrée(s)."
                           if corrections else "")),
        }
        if sens == "vente":        # clés historiques, encore lues par l'interface
            res.update({"client_code": code, "client_name": nom,
                        "n_factures_client": n_tiers, "total_importe_client_dt": total_tiers})
        return res
    finally:
        con.close()


def factures_importees(client_code: Optional[str] = None, limit: int = 100,
                       sens: Optional[str] = None,
                       rapprochement: Optional[str] = None) -> List[Dict[str, Any]]:
    """Factures importées par OCR, éventuellement filtrées sur un client ou un sens."""
    con = _connect()
    try:
        _assurer_schema(con)
        conds, args = [], []
        if client_code:
            conds.append("client_code = ?"); args.append(client_code)
        if sens:
            conds.append("coalesce(sens, 'vente') = ?"); args.append(sens)
        if rapprochement:
            conds.append("coalesce(rapprochement_statut, 'non_rapprochee') = ?")
            args.append(rapprochement)
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        rows = con.execute(f"""
            SELECT numero, client_code, client_name, date, ht, tva, ttc,
                   net_a_payer, fichier_source, confiance_ocr, importe_le,
                   coalesce(sens, 'vente'), fournisseur_code, fournisseur,
                   statut_validation, corrections, moteur,
                   rapprochement_statut, rapprochement_message
            FROM factures_importees {where}
            ORDER BY importe_le DESC, numero ASC
            LIMIT {int(limit)}
        """, args).fetchall()
        return [{
            "numero": r[0], "client_code": r[1], "client_name": r[2],
            "date": r[3].isoformat() if r[3] else None,
            "ht": r[4], "tva": r[5], "ttc": r[6], "net_a_payer": r[7],
            "fichier": r[8], "confiance_ocr": r[9],
            "importe_le": r[10].isoformat() if r[10] else None,
            "sens": r[11], "fournisseur_code": r[12], "fournisseur": r[13],
            "tiers": r[2] if r[11] == "vente" else r[13],
            "statut_validation": r[14],
            "n_corrections": len(json.loads(r[15])) if r[15] else 0,
            "moteur": r[16],
            "rapprochement_statut": r[17], "rapprochement_message": r[18],
        } for r in rows]
    finally:
        con.close()


def stats_import() -> Dict[str, Any]:
    """Volumétrie des imports, par sens, et part des factures corrigées à la main."""
    con = _connect()
    try:
        _assurer_schema(con)
        r = con.execute("""
            SELECT count(*), count(DISTINCT coalesce(client_code, fournisseur_code)),
                   sum(ttc), avg(confiance_ocr),
                   count(*) FILTER (WHERE coalesce(sens, 'vente') = 'vente'),
                   count(*) FILTER (WHERE sens = 'achat'),
                   sum(ttc) FILTER (WHERE coalesce(sens, 'vente') = 'vente'),
                   sum(ttc) FILTER (WHERE sens = 'achat'),
                   count(*) FILTER (WHERE statut_validation IN ('corrigee', 'validee_telle_quelle')),
                   count(*) FILTER (WHERE statut_validation = 'corrigee')
            FROM factures_importees
        """).fetchone()
        n_nouveaux = con.execute(
            "SELECT count(*) FROM dim_client WHERE client_code LIKE 'OCR-%'").fetchone()[0] \
            if _table_existe(con, "dim_client") else 0
        relues, corrigees = int(r[8] or 0), int(r[9] or 0)
        par_statut = {f"{sens}:{st}": int(n) for sens, st, n in con.execute("""
            SELECT coalesce(sens, 'vente'), coalesce(rapprochement_statut, 'non_rapprochee'), count(*)
            FROM factures_importees GROUP BY 1, 2""").fetchall()}
        return {
            "n_factures": int(r[0] or 0),
            "n_clients": int(r[1] or 0),           # tiers distincts (compatibilité)
            "total_ttc_dt": round(float(r[2] or 0), 3),
            "confiance_moyenne": round(float(r[3]), 1) if r[3] is not None else None,
            "n_clients_crees": int(n_nouveaux or 0),
            "n_ventes": int(r[4] or 0), "n_achats": int(r[5] or 0),
            "total_ventes_ttc_dt": round(float(r[6] or 0), 3),
            "total_achats_ttc_dt": round(float(r[7] or 0), 3),
            "n_relues": relues, "n_corrigees": corrigees,
            "part_corrigees": round(100 * corrigees / relues, 1) if relues else None,
            # ex. {"achat:introuvable": 3} : achats absents de l'ERP, à instruire
            "rapprochements": par_statut,
        }
    finally:
        con.close()
