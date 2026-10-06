"""Installe le PACK DE LANGUE FRANÇAIS de Tesseract — SANS droits administrateur."""

from __future__ import annotations

import argparse
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
TESSDATA = BASE / "models" / "tessdata"

SOURCES = [
    "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/fra.traineddata",
    "https://github.com/tesseract-ocr/tessdata_fast/raw/main/fra.traineddata",
]
MIN_SIZE = 200_000


def _tesseract_present() -> bool:
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _langues() -> list[str]:
    try:
        import pytesseract
        return sorted(pytesseract.get_languages(config=""))
    except Exception:
        return []


def installer_depuis_fichier(src: Path) -> int:
    if not src.exists():
        print(f"[erreur] fichier introuvable : {src}")
        return 1
    if src.stat().st_size < MIN_SIZE:
        print(f"[erreur] fichier trop petit ({src.stat().st_size} octets) — "
              "ce n'est probablement pas un fra.traineddata valide.")
        return 1
    TESSDATA.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, TESSDATA / "fra.traineddata")
    print(f"[ok] installé : {TESSDATA / 'fra.traineddata'}")
    return 0


def telecharger() -> int:
    TESSDATA.mkdir(parents=True, exist_ok=True)
    dest = TESSDATA / "fra.traineddata"
    tmp = dest.with_suffix(".part")
    for url in SOURCES:
        print(f"[..] téléchargement du pack français\n     {url}")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=90) as r, open(tmp, "wb") as out:
                total = int(r.headers.get("Content-Length") or 0)
                lu = 0
                while True:
                    bloc = r.read(64 * 1024)
                    if not bloc:
                        break
                    out.write(bloc)
                    lu += len(bloc)
                    if total:
                        print(f"\r     {lu * 100 // total:3d} %  ({lu // 1024} Ko)", end="")
            print()
            if tmp.stat().st_size >= MIN_SIZE:
                tmp.replace(dest)
                print(f"[ok] installé : {dest} ({dest.stat().st_size // 1024} Ko)")
                return 0
            print(f"[!] fichier incomplet ({tmp.stat().st_size} octets), essai suivant…")
        except Exception as e:
            print(f"\n[!] échec ({e}) — essai suivant…")
        finally:
            tmp.unlink(missing_ok=True)

    print("\n[erreur] téléchargement impossible.")
    print("        Récupérez fra.traineddata depuis :")
    print("        https://github.com/tesseract-ocr/tessdata_fast")
    print("        puis : python scripts/setup_tesseract_fr.py --file <chemin>")
    return 1


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Installe le pack français de Tesseract")
    ap.add_argument("--file", help="installer depuis un fra.traineddata local")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if not _tesseract_present():
        print("[!] Tesseract n'est pas installé sur cette machine.")
        print("    Le pack de langue seul ne suffit pas : installez d'abord le moteur.")
        print("    Windows : https://github.com/UB-Mannheim/tesseract/wiki")
        print("              (cochez « French » pendant l'installation : le pack sera déjà là)")
        print("    Linux   : sudo apt install tesseract-ocr tesseract-ocr-fra")
        print("    Puis relancez ce script si le français manque toujours.\n")

    langues = _langues()
    if "fra" in langues and not args.force:
        print(f"[ok] le pack français est déjà disponible (langues : {', '.join(langues)}).")
        print("     Rien à faire.")
        return 0

    dest = TESSDATA / "fra.traineddata"
    if dest.exists() and dest.stat().st_size >= MIN_SIZE and not args.force:
        print(f"[ok] pack déjà présent dans le projet : {dest}")
    else:
        code = installer_depuis_fichier(Path(args.file)) if args.file else telecharger()
        if code != 0:
            return code

    print("\n[..] vérification par le moteur OCR de la plateforme…")
    sys.path.insert(0, str(BASE))
    try:
        from ml_engine.ocr.engine import _languages, ocr_available
        if ocr_available():
            lang = _languages()
            if "fra" in lang:
                print(f"[ok] le moteur utilisera : {lang}")
                print("\nL'OCR reconnaît désormais correctement les accents et le "
                      "vocabulaire des factures françaises.")
                return 0
            print(f"[!] le moteur voit encore : {lang}")
            print("    Redémarrez l'API pour prendre en compte le nouveau dossier tessdata.")
            return 0
        print("[!] Tesseract absent : le pack est installé, mais le moteur manque.")
        return 1
    except Exception as e:
        print(f"[!] vérification impossible : {e}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
