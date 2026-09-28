# Modèle 3D de l'avatar

Placez ici `finbot.glb` pour que l'avatar 3D fonctionne **sans réseau**.

Installation automatique :

    python scripts/setup_avatar.py                 # modèle de démonstration
    python scripts/setup_avatar.py --id <RPM_ID>   # votre propre avatar
    python scripts/setup_avatar.py --file mon.glb  # depuis un fichier local

Tant que ce fichier est absent, `GET /avatar/finbot.glb` renvoie un **404 sans
conséquence** : l'avatar bascule automatiquement sur le CDN Ready Player Me,
puis sur la tête 3D procédurale si le réseau est indisponible.

Le fichier `.glb` n'est pas versionné (plusieurs Mo) — voir .gitignore.
