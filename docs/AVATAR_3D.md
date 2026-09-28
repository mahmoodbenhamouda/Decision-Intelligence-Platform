# Avatar 3D FinBot — nouvelle génération

## Vue d'ensemble

L'avatar orbe SVG a été remplacé par un **avatar 3D réaliste** (`frontend/src/shared/avatar/FinBotAvatar3D.tsx`) basé sur **Three.js** et un modèle **Ready Player Me** (GLB avec blendshapes ARKit + visèmes Oculus). L'orbe SVG historique (`FinBotAvatar.tsx`) est conservé comme **repli automatique**.

## Architecture

```
features/copilote/useSyntheseVocale.ts (ViewModel : voix + synchro labiale)
  └── FinBotAvatar3D (wrapper)
        ├── Avatar3DScene (Three.js, si WebGL + GLB OK)
        │     ├── MorphRig : registre nom→blendshape sur tous les meshes
        │     ├── Boucle rAF unique : visèmes, émotions, clignements,
        │     │   regard, micro-mouvements de tête, respiration, gestes
        │     └── Éclairage 3 points + contre-jour couleur d'accent
        └── FinBotAvatar (orbe SVG) : affiché pendant le chargement
            et en repli si WebGL/GLB indisponible
```

L'API impérative est **inchangée** (`AvatarHandle` : `setViseme`, `restMouth`, `gesture` ; props `mode`/`mood`/`accent`) — aucune régression dans `Copilot.tsx`.

## Synchro labiale par visèmes

1. `useSyntheseVocale.ts` (ViewModel du copilote) nettoie le texte, lance le TTS (Web Speech API, voix **française neuronale** si disponible — Microsoft *(Natural)*, Google, Siri — via `pickFrenchVoice()`).
2. Le moteur de lip-sync avance dans les caractères au rythme estimé (~14 c/s) et se **recale sur les frontières de mots réelles** (`onboundary`) — la bouche est donc calée sur l'audio, pas une boucle.
3. Chaque caractère est projeté en axes articulatoires `{open, wide, round}` (`visemeForChar`), puis sur les blendshapes du modèle :
   - visèmes Oculus si présents (`viseme_aa/I/O/U/PP/sil` + `jawOpen`) ;
   - sinon repli ARKit (`jawOpen`, `mouthFunnel`, `mouthPucker`, `mouthStretch*`).
4. Lissage exponentiel rapide pour la bouche (~26 s⁻¹), doux pour les émotions (~7 s⁻¹).

## Émotions et états

| Source | Effet 3D |
|---|---|
| `mood=happy` | sourire, joues, sourcils levés |
| `mood=concerned` | sourcils froncés + `browInnerUp`, coins de bouche baissés |
| `mood=alert` | yeux écarquillés, sourcils bas, mâchoire avancée |
| `mode=thinking` | tête inclinée, regard en haut-gauche |
| `mode=listening` | tête penchée vers l'avant, regard bas |
| Gestes | `nod` (hochement), `alert` (secousse+recul), `lean`, `glance` |

## Micro-comportements

Clignements toutes les 2–5 s (18 % de double-clignement), saccades oculaires aléatoires, micro-rotations de tête par bruit basse fréquence, respiration du buste.

## Performance et dégradation (chaîne à 3 niveaux, sans aucun CDN)

1. **GLB local** (`public/avatar/finbot.glb`) — *optionnel* : mode photoréaliste
   si vous fournissez un modèle avec blendshapes ARKit.
2. **Tête robot 3D PROCÉDURALE** (`ProceduralHeadRig`) — **mode par défaut**,
   construite en pur Three.js (mâchoire pivotante, lèvres, paupières, sourcils,
   iris lumineux avec reflet), **zéro téléchargement**. Même interface
   `FacialRig` que les blendshapes du GLB → la boucle d'animation (visèmes,
   émotions, clignements, regard, gestes) est strictement identique.
3. **Orbe SVG** — uniquement si WebGL lui-même est indisponible.

> **Décision d'architecture — aucune dépendance à un CDN.** La version initiale
> chargeait un modèle depuis `models.readyplayer.me` ; ce sous-domaine public a
> depuis été retiré et ne résout plus dans le DNS. Au-delà de cet incident,
> faire dépendre le démarrage d'une application de démonstration d'un service
> tiers est un point de panne inutile : une salle hors-ligne, un proxy filtrant
> ou la disparition du service suffisent à casser la démo. Le projet ne dépend
> donc plus d'aucun réseau pour son avatar.

- Une seule boucle `requestAnimationFrame`, morphs écrits sans re-render React → 60 fps.
- `pixelRatio` plafonné à 2 ; rendu **suspendu quand l'onglet est masqué**.
- Pendant le chargement → orbe SVG (jamais d'écran vide, UI jamais bloquée).
- TTS absent → l'avatar reste vivant (idle/gestes), le texte s'affiche normalement.

## Capture de démonstration intégrée

Bouton **« Enregistrer une démo »** sous l'avatar : capture le canvas WebGL
(`captureStream` 30 fps + `MediaRecorder` VP9) pendant une séquence scriptée de
16 s (présentation parlée, humeurs happy → alert → concerned, gestes nod/alert/
glance/lean) et télécharge `finbot-avatar-demo.webm` — le livrable de
démonstration se produit en un clic, hors-ligne. Conversion GIF si besoin :
`ffmpeg -i finbot-avatar-demo.webm -vf "fps=15,scale=420:-1" demo.gif`.

## Modèle 3D

Ordre d'essai :
1. `frontend/public/avatar/finbot.glb` (**recommandé pour la soutenance** : fonctionne hors-ligne).
2. CDN Ready Player Me (`models.readyplayer.me/64bfa15f0e72c63d7c3934a6.glb?morphTargets=ARKit,Oculus Visemes`).

### Installer un GLB (optionnel — mode photoréaliste)

```bash
python scripts/setup_avatar.py --file mon-avatar.glb   # depuis un fichier
python scripts/setup_avatar.py --url  https://…/x.glb  # depuis une URL
python scripts/setup_avatar.py --check                 # état actuel
```

Le script vérifie la signature `glTF` et la taille, puis installe le fichier dans `frontend/public/avatar/finbot.glb`.

**Le modèle doit contenir des morph targets** nommés selon la convention ARKit (`jawOpen`, `mouthSmileLeft`, `eyeBlinkLeft`…) et/ou les visèmes Oculus (`viseme_aa`, `viseme_O`…). Sources : [readyplayer.me](https://readyplayer.me) (exporter avec l'option « ARKit blendshapes »), Character Creator, Blender + add-on FaceIt, ou toute bibliothèque fournissant un glTF binaire avec blendshapes faciaux.

**Sans GLB, tout fonctionne** : c'est le mode par défaut du projet.

### Forçage manuel (répétitions)

| URL | Effet |
|---|---|
| `http://localhost:4000/?avatar=procedural` | force la **tête 3D procédurale** |
| `http://localhost:4000/?avatar=local` | force le GLB local uniquement |

### État du mode actif

```bash
python scripts/setup_avatar.py --check
```

Pour créer votre propre avatar : https://readyplayer.me → créez-le → copiez l'identifiant présent dans l'URL du `.glb` → `python scripts/setup_avatar.py --id <identifiant>`.

## Installation

```bash
cd frontend
npm install        # installe three@0.170.0 (+ @types/three)
npm run dev
```

## Tests navigateurs

Testé sur Chrome/Edge récents (WebGL2 + Web Speech API complets). Firefox : rendu 3D OK, `onboundary` non émis → le lip-sync reste sur l'estimation temporelle (dégradation prévue). Safari : voix Siri françaises prises en charge par `pickFrenchVoice()`.
