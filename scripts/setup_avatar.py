"""
scripts/setup_avatar.py
=======================
Installe un modèle 3D d'avatar EN LOCAL (option « photoréaliste »).

    python scripts/setup_avatar.py --file mon-avatar.glb   # installer un GLB
    python scripts/setup_avatar.py --url  https://…/x.glb  # depuis une URL
    python scripts/setup_avatar.py --check                 # état actuel

CE SCRIPT EST OPTIONNEL. Sans GLB, l'avatar utilise la **tête 3D procédurale**
générée par Three.js sur le poste : mêmes visèmes calés sur la voix, mêmes
émotions, mêmes gestes, **aucun téléchargement**. C'est le mode par défaut, et
le plus sûr pour une soutenance (rien à charger, rien qui puisse échouer).

Pourquoi pas de téléchargement automatique ?
--------------------------------------------
Le sous-domaine public de Ready Player Me (`models.readyplayer.me`) a été
retiré : il ne résout plus dans le DNS public. Dépendre d'un CDN externe au
démarrage d'une application de démonstration est de toute façon un point de
panne inutile. Le projet ne dépend donc plus d'aucun service tiers.

Obtenir un GLB compatible (si vous voulez un avatar photoréaliste)
------------------------------------------------------------------
Le fichier doit contenir des **morph targets** (blendshapes) nommés selon la
convention ARKit (`jawOpen`, `mouthSmileLeft`, `eyeBlinkLeft`…) et/ou les
visèmes Oculus (`viseme_aa`, `viseme_O`…). Sources possibles :
  • https://readyplayer.me — créez un avatar, exportez le .glb avec
    l'option « ARKit blendshapes » ;
  • Character Creator, Blender (add-on FaceIt), Mixamo + retargeting ;
  • toute bibliothèque 3D fournissant un glTF binaire avec blendshapes faciaux.
Puis : python scripts/setup_avatar.py --file <chemin-du-fichier>
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
DEST = BASE / "frontend" / "public" / "avatar" / "finbot.glb"
MIN_SIZE = 100_000          # un GLB avec blendshapes pèse plusieurs centaines de Ko


# Morphs réellement pilotés par le composant (FinBotAvatar3D.tsx → DRIVEN).
# Un GLB sans aucun de ces noms se chargerait mais resterait FIGÉ : ni parole,
# ni clignement, ni émotion. Mieux vaut le refuser à l'installation que de
# laisser l'utilisateur croire que l'avatar est cassé.
_MORPHS_ATTENDUS = {
    "jawOpen", "mouthSmileLeft", "mouthSmileRight", "mouthFunnel", "mouthPucker",
    "mouthFrownLeft", "mouthFrownRight", "mouthStretchLeft", "mouthStretchRight",
    "eyeBlinkLeft", "eyeBlinkRight", "eyeWideLeft", "eyeWideRight",
    "eyeSquintLeft", "eyeSquintRight", "browInnerUp", "browDownLeft", "browDownRight",
    "viseme_aa", "viseme_I", "viseme_O", "viseme_U", "viseme_PP", "viseme_sil",
}


def _morphs_du_glb(path: Path) -> set[str] | None:
    """Extrait les noms de morph targets d'un GLB, sans dépendance externe.

    Un GLB est un conteneur binaire : en-tête de 12 octets, puis des « chunks »
    (4 octets de longueur, 4 octets de type, données). Le premier chunk, de type
    `JSON`, contient la description glTF. Les noms de morphs y figurent dans
    `meshes[].extras.targetNames` — la convention utilisée par Ready Player Me,
    Blender et Character Creator.

    Renvoie None si la structure n'a pas pu être lue (le GLB reste alors accepté :
    on ne rejette pas un fichier au seul motif qu'on n'a pas su l'inspecter)."""
    try:
        with open(path, "rb") as f:
            entete = f.read(12)
            if len(entete) < 12:
                return None
            longueur = int.from_bytes(f.read(4), "little")
            type_chunk = f.read(4)
            if type_chunk != b"JSON":
                return None
            doc = json.loads(f.read(longueur).decode("utf-8", errors="replace"))
    except Exception:
        return None

    noms: set[str] = set()
    for mesh in doc.get("meshes", []) or []:
        for n in (mesh.get("extras", {}) or {}).get("targetNames", []) or []:
            noms.add(str(n))
    return noms


def _valide(path: Path) -> tuple[bool, str]:
    """Vérifie la signature glTF binaire, la taille, puis les blendshapes."""
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
        if magic != b"glTF":
            return False, ("signature « glTF » absente — ce n'est pas un GLB binaire "
                           "(un .gltf JSON ou un .fbx ne conviennent pas).")
        if path.stat().st_size < MIN_SIZE:
            return False, f"fichier suspect ({path.stat().st_size} octets, < {MIN_SIZE})."

        morphs = _morphs_du_glb(path)
        if morphs is None:
            return True, ""                      # inspection impossible : on accepte
        if not morphs:
            return False, ("aucun morph target dans le fichier — l'avatar serait "
                           "affiché mais totalement figé (pas de parole, pas de "
                           "clignement). Réexportez en cochant « ARKit blendshapes ».")
        communs = morphs & _MORPHS_ATTENDUS
        if not communs:
            apercu = ", ".join(sorted(morphs)[:6])
            return False, (f"{len(morphs)} morphs présents, mais aucun nom reconnu "
                           f"(vus : {apercu}…). Le composant pilote la convention "
                           "ARKit / visèmes Oculus.")
        return True, ""
    except Exception as e:
        return False, str(e)


def _rapport_morphs(path: Path) -> None:
    """Détaille ce que le GLB installé sait animer, et ce qui manquera."""
    morphs = _morphs_du_glb(path)
    if morphs is None:
        print("     morphs : non inspectables (le modèle sera tout de même essayé).")
        return
    presents = sorted(morphs & _MORPHS_ATTENDUS)
    absents = sorted(_MORPHS_ATTENDUS - morphs)
    print(f"     morphs pilotables : {len(presents)}/{len(_MORPHS_ATTENDUS)}")
    if absents:
        print(f"     non fournis ({len(absents)}) : {', '.join(absents[:8])}"
              + ("…" if len(absents) > 8 else ""))
        print("     → ces expressions resteront neutres, le reste fonctionnera.")


def etat() -> int:
    """Affiche le mode d'avatar actuellement actif."""
    if DEST.exists():
        ok, err = _valide(DEST)
        if ok:
            print(f"[ok] GLB installé : {DEST}")
            print(f"     taille : {DEST.stat().st_size // 1024} Ko")
            _rapport_morphs(DEST)
            print("     → l'avatar utilise ce modèle (mode photoréaliste).")
            return 0
        print(f"[!] {DEST} présent mais INVALIDE : {err}")
        print("    → l'avatar bascule sur la tête procédurale.")
        return 1
    print("[i] Aucun GLB installé — c'est le cas par défaut, tout fonctionne.")
    print("    → l'avatar utilise la TÊTE 3D PROCÉDURALE (Three.js, 100 % locale) :")
    print("      visèmes synchronisés à la voix, émotions, clignements, gestes.")
    print("\n    Pour un avatar photoréaliste : voir l'en-tête de ce script")
    print("    (obtenir un .glb avec blendshapes ARKit), puis :")
    print("      python scripts/setup_avatar.py --file <chemin>")
    return 0


def depuis_fichier(src: Path) -> int:
    if not src.exists():
        print(f"[erreur] fichier introuvable : {src}")
        return 1
    ok, err = _valide(src)
    if not ok:
        print(f"[erreur] {src.name} : {err}")
        return 1
    DEST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, DEST)
    print(f"[ok] installé : {DEST} ({DEST.stat().st_size // 1024} Ko)")
    _rapport_morphs(DEST)
    print("\nRafraîchissez la page du copilote (Ctrl+Shift+R).")
    print("Vérification : http://localhost:4000/?avatar=local")
    return 0


def depuis_url(url: str) -> int:
    DEST.parent.mkdir(parents=True, exist_ok=True)
    tmp = DEST.with_suffix(".part")
    print(f"[..] téléchargement\n     {url}")
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
    except Exception as e:
        tmp.unlink(missing_ok=True)
        msg = str(e)
        print(f"\n[erreur] téléchargement impossible : {msg}\n")
        if "getaddrinfo" in msg or "11001" in msg or "Name or service" in msg:
            print("  Le nom de domaine ne se résout pas (DNS). Vérifiez l'URL, ou")
            print("  téléchargez le fichier via votre navigateur puis utilisez --file.")
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
        if proxy:
            print(f"  Proxy détecté : {proxy}")
        else:
            print("  Derrière un proxy : $env:HTTPS_PROXY=\"http://proxy:port\"")
        print("\n  RAPPEL : ce script est optionnel. Sans GLB, la tête 3D")
        print("  procédurale fonctionne parfaitement et sans réseau.")
        return 1

    ok, err = _valide(tmp)
    if not ok:
        print(f"[erreur] fichier reçu invalide : {err}")
        tmp.unlink(missing_ok=True)
        return 1
    tmp.replace(DEST)
    print(f"[ok] installé : {DEST} ({DEST.stat().st_size // 1024} Ko)")
    print("\nRafraîchissez la page du copilote (Ctrl+Shift+R).")
    return 0


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(
        description="Installe un GLB d'avatar en local (optionnel)")
    ap.add_argument("--file", help="chemin d'un .glb à installer")
    ap.add_argument("--url", help="URL d'un .glb à télécharger")
    ap.add_argument("--check", action="store_true", help="afficher l'état actuel")
    args = ap.parse_args()

    if args.check or (not args.file and not args.url):
        return etat()
    if args.file:
        return depuis_fichier(Path(args.file))
    return depuis_url(args.url)


if __name__ == "__main__":
    sys.exit(main())
