"""
evaluation_ocr/preparation/6_integrer_production.py
===================================================
Boucle d'apprentissage, partie 2 : les factures VALIDÉES en production
rejoignent le jeu d'entraînement de LayoutLMv3.

    python evaluation_ocr/preparation/6_integrer_production.py            # aperçu
    python evaluation_ocr/preparation/6_integrer_production.py --ecrire   # met à jour le zip

Pour chaque facture relue à l'écran de validation (corrigée ou validée telle
quelle) dont le document est conservé :

  1. le document est relu par LA MÊME chaîne qu'en production
     (`pages_du_document` : texte PDF exact ou OCR renforcé, 200 dpi) ;
  2. les valeurs VALIDÉES servent de vérité terrain ;
  3. elles sont projetées sur les mots avec la MÊME fonction que les 89
     factures d'origine (`projeter` de 3_construire.py) : un montant n'est
     étiqueté que là où un libellé le justifie.

Le zip `layoutlmv3_factures.zip` reçoit ces documents en plus des 89 (identifiants
`p_<empreinte>`, champ `origine = "production"`). La première fois, l'original
est conservé sous `layoutlmv3_factures_base89.zip`. Relancer le script remplace
les documents de production, jamais les 89.

Ensuite : relancer le carnet Colab avec ce zip. La validation croisée mêle alors
les deux origines ; le carnet reste comparable à la référence 89 grâce à la copie.
"""
from __future__ import annotations

import importlib.util
import io
import json
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

_ICI = Path(__file__).resolve().parent
PROJET = _ICI.parent.parent
sys.path.insert(0, str(PROJET))
ZIP = _ICI.parent / "layoutlmv3" / "layoutlmv3_factures.zip"
BASE = _ICI.parent / "layoutlmv3" / "layoutlmv3_factures_base89.zip"


def _construire():
    """Le module 3_construire (nom non importable), sans ses arguments de ligne de commande."""
    argv, sys.argv = sys.argv, sys.argv[:1]
    try:
        spec = importlib.util.spec_from_file_location("construire", _ICI / "3_construire.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    finally:
        sys.argv = argv


def verite_depuis_import(r: Dict[str, Any]) -> Dict[str, Any]:
    """Ligne de `factures_importees` → vérité terrain au format du jeu."""
    return {"type": "facture", "origine": "production", "manuscrite": False,
            "numero": r["numero"], "date": r["date"].isoformat() if r["date"] else None,
            "fournisseur": r["fournisseur_lu"] or r["fournisseur"],
            "client": r["client_lu"] or r["client_name"], "devise": r["devise"] or "TND",
            "total_ht": r["ht"], "total_tva": r["tva"], "timbre": r["timbre_fiscal"],
            "total_ttc": r["ttc"], "net_a_payer": r["net_a_payer"],
            "certitude": "validee_par_utilisateur", "note": r["statut_validation"]}


def factures_validees() -> List[Dict[str, Any]]:
    from ml_engine.ocr.importer import _assurer_schema, _connect
    con = _connect()
    try:
        _assurer_schema(con)
        cur = con.execute("""SELECT * FROM factures_importees
                             WHERE statut_validation IN ('corrigee', 'validee_telle_quelle')
                               AND fichier_sha256 IS NOT NULL ORDER BY id""")
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        con.close()


def construire_exemples(factures: List[Dict[str, Any]],
                        lire: Optional[Callable] = None) -> Tuple[List[dict], Dict, Dict, Dict, List[str]]:
    """→ (lignes pages.jsonl, vérité, règles, rapports de projection, images JPEG)."""
    from ml_engine.ocr import parse_invoice
    from ml_engine.ocr.layoutlm.mots import pages_du_document, texte_par_lignes
    from ml_engine.ocr.lectures import dossier
    c = _construire()
    lire = lire or pages_du_document
    lignes, verite, regles, rapports, images, absents = [], {}, {}, {}, {}, []
    for r in factures:
        sha = r["fichier_sha256"]
        doc_f = next(iter(sorted(p for p in dossier().glob(f"{sha}.*") if p.suffix != ".json")), None)
        if doc_f is None:
            absents.append(r["numero"]); continue
        doc = f"p_{sha[:10]}"
        v = verite_depuis_import(r)
        pages = lire(doc_f.read_bytes(), r["fichier_source"] or doc_f.name)
        pages_mots, dims, ims, srcs = {}, {}, {}, set()
        for k, (im, mots, src) in enumerate(pages, 1):
            p = f"{doc}_p{k}"
            mots = [{kk: m[kk] for kk in ("t", "x", "y", "w", "h")} for m in mots if m["t"].strip()]
            pages_mots[p] = [mots[i] for ids in c.lignes(mots) for i in ids]
            dims[p], ims[p] = im.size, im
            srcs.add("natif" if src == "pdf-texte" else "ocr")
        etq, rap = c.projeter(doc, v, pages_mots)
        verite[doc] = v
        rapports[doc] = {"source": "natif" if srcs == {"natif"} else "ocr", **rap}
        texte = "\n".join(texte_par_lignes(m) for m in pages_mots.values())
        lecture_regles = parse_invoice(texte).to_dict()
        regles[doc] = {"meme_ocr": lecture_regles, "production": lecture_regles}
        for p, mots in pages_mots.items():
            W, H = dims[p]
            im = ims[p].convert("RGB"); im.thumbnail((1000, 1000))
            b = io.BytesIO(); im.save(b, "JPEG", quality=85); images[f"images/{p}.jpg"] = b.getvalue()
            lignes.append({"doc": doc, "page": p, "image": f"images/{p}.jpg", "origine": "production",
                           "source": rapports[doc]["source"], "fournisseur": v["fournisseur"],
                           "mots": [m["t"] for m in mots],
                           "boites": [[max(0, min(1000, int(1000 * m["x"] / W))),
                                       max(0, min(1000, int(1000 * m["y"] / H))),
                                       max(0, min(1000, int(1000 * (m["x"] + m["w"]) / W))),
                                       max(0, min(1000, int(1000 * (m["y"] + m["h"]) / H)))] for m in mots],
                           "etiquettes": etq[p]})
    return lignes, verite, regles, rapports, images, absents


def fusionner_zip(zip_path: Path, lignes, verite, regles, rapports, images) -> Dict[str, int]:
    """Réécrit le zip : documents d'origine conservés, documents de production remplacés."""
    src = zipfile.ZipFile(zip_path)
    anciennes = [json.loads(l) for l in src.read("pages.jsonl").decode("utf-8").splitlines() if l.strip()]
    garder = lambda d: not str(d).startswith("p_")
    anc_v = {d: x for d, x in json.loads(src.read("verite.json")).items() if garder(d)}
    anc_r = {d: x for d, x in json.loads(src.read("regles.json")).items() if garder(d)}
    anc_p = {d: x for d, x in json.loads(src.read("projection_rapport.json")).items() if garder(d)}
    rogner = _construire().rogner_etiquettes
    pages = [l for l in anciennes if garder(l["doc"])] + lignes
    for l in pages:                       # corrige aussi les étiquettes d'origine (idempotent)
        l["etiquettes"] = rogner(l["mots"], l["etiquettes"])
    tmp = zip_path.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
        for n in src.namelist():
            if n in ("pages.jsonl", "verite.json", "regles.json", "projection_rapport.json"):
                continue
            if n.startswith("images/p_"):
                continue
            out.writestr(src.getinfo(n), src.read(n))
        out.writestr("pages.jsonl", "".join(json.dumps(l, ensure_ascii=False) + "\n" for l in pages))
        out.writestr("verite.json", json.dumps({**anc_v, **verite}, ensure_ascii=False, indent=1))
        out.writestr("regles.json", json.dumps({**anc_r, **regles}, ensure_ascii=False, indent=1, default=str))
        out.writestr("projection_rapport.json", json.dumps({**anc_p, **rapports}, ensure_ascii=False, indent=1))
        for n, b in images.items():
            out.writestr(n, b)
    src.close()
    shutil.copyfile(tmp, zip_path); tmp.unlink()
    return {"documents_origine": len(anc_v), "documents_production": len(verite), "pages": len(pages)}


def main():
    ecrire = "--ecrire" in sys.argv
    fact = factures_validees()
    print(f"{len(fact)} facture(s) validée(s) avec document conservé")
    if not fact:
        if ecrire:                        # aucune facture : on corrige quand même les étiquettes
            if not BASE.exists():
                shutil.copyfile(ZIP, BASE); print("original conservé :", BASE.name)
            print(fusionner_zip(ZIP, [], {}, {}, {}, {}))
        return
    lignes, verite, regles, rapports, images, absents = construire_exemples(fact)
    if absents:
        print("documents introuvables (non intégrés) :", ", ".join(absents))
    champs = ["NUMERO", "DATE", "FOURNISSEUR", "CLIENT", "TOTAL_HT", "TVA", "TIMBRE", "TTC", "NET"]
    print(f"{'document':14}" + "".join(f"{c[:8]:>9}" for c in champs))
    for d, rap in rapports.items():
        print(f"{d:14}" + "".join(f"{(rap.get(c) or '-')[:8]:>9}" for c in champs))
    print("trouve = étiqueté sur la page ; absent_ocr = valeur validée introuvable dans les mots lus")
    if not ecrire:
        print("\nAperçu seulement. Ajoutez --ecrire pour mettre à jour", ZIP.name); return
    if not BASE.exists():
        shutil.copyfile(ZIP, BASE); print("original conservé :", BASE.name)
    print(fusionner_zip(ZIP, lignes, verite, regles, rapports, images))
    print("Relancez le carnet Colab avec", ZIP)


if __name__ == "__main__":
    main()
