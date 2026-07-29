"""
Jeu de données ÉTIQUETÉ d'appels d'offres (benchmark de pertinence).

Étiquette : 1 = pertinent pour Overlyne (diagnostic in vitro / biologie médicale
/ laboratoire / dispositifs médicaux) ; 0 = hors domaine (BTP, alimentaire,
nettoyage, bureautique, transport…).

Sert de vérité terrain pour entraîner ET évaluer (accuracy/précision/rappel/F1)
le classifieur de pertinence des AO scrappés.
Les libellés imitent la formulation des marchés publics tunisiens.
"""

# (titre_appel_offres, label)
LABELED_TENDERS = [
    # ── PERTINENTS (1) : diagnostic / labo / dispositifs médicaux ────────────
    ("Acquisition de réactifs de biochimie pour le laboratoire du CHU Farhat Hached", 1),
    ("Fourniture de kits ELISA pour sérologie infectieuse", 1),
    ("Acquisition d'un automate d'hématologie avec consommables associés", 1),
    ("Marché de réactifs d'immuno-analyse pour l'hôpital régional de Gabès", 1),
    ("Fourniture de tests PCR SARS-CoV-2 et extraction d'acides nucléiques", 1),
    ("Acquisition de tubes de prélèvement sous vide pour la banque du sang", 1),
    ("Fourniture de consommables de laboratoire d'analyses médicales", 1),
    ("Acquisition d'un analyseur automatique de coagulation", 1),
    ("Marché de réactifs de microbiologie et milieux de culture", 1),
    ("Fourniture de dispositifs médicaux de diagnostic in vitro", 1),
    ("Acquisition de réactifs d'hormonologie pour le service d'endocrinologie", 1),
    ("Fourniture d'un spectrophotomètre pour le laboratoire central", 1),
    ("Acquisition de bandelettes réactives et lecteurs de glycémie", 1),
    ("Marché de maintenance des automates de biochimie du CHU Sahloul", 1),
    ("Fourniture de réactifs d'immuno-hématologie et cartes de groupage sanguin", 1),
    ("Acquisition de contrôles et calibrateurs pour analyseurs de biochimie", 1),
    ("Fourniture de kits de dosage de la vitamine D par chimiluminescence", 1),
    ("Acquisition d'une centrifugeuse de paillasse pour laboratoire", 1),
    ("Marché de réactifs de gaz du sang et électrolytes", 1),
    ("Fourniture de matériel de prélèvement et micropipettes de laboratoire", 1),
    ("Acquisition de réactifs de sérologie virale (hépatites, VIH)", 1),
    ("Fourniture d'automates d'analyse d'urine pour les laboratoires régionaux", 1),
    ("Acquisition de tests rapides de diagnostic du paludisme", 1),
    ("Marché de consommables pour cytométrie en flux", 1),
    ("Fourniture de réactifs de parasitologie et mycologie médicale", 1),
    ("Acquisition d'un système d'hémoculture automatisé", 1),
    ("Fourniture de plaques et cônes pour automate d'immuno-analyse", 1),
    ("Acquisition de réactifs de biologie moléculaire pour oncologie", 1),
    ("Marché de trousses de dosage des marqueurs cardiaques (troponine)", 1),
    ("Fourniture de lames, colorants et réactifs d'anatomo-pathologie", 1),
    ("Acquisition de réactifs d'électrophorèse des protéines", 1),
    ("Fourniture d'un automate de numération formule sanguine", 1),
    ("Acquisition de kits de diagnostic de la tuberculose (GeneXpert)", 1),
    ("Marché de réactifs de bactériologie et antibiogramme", 1),
    ("Fourniture de consommables de diagnostic pour hôpital militaire", 1),

    # ── HORS DOMAINE (0) : BTP, alimentaire, services généraux… ──────────────
    ("Travaux de construction d'un bloc administratif à la municipalité de Tunis", 0),
    ("Acquisition de mobilier de bureau pour la direction régionale", 0),
    ("Marché de nettoyage et d'entretien des locaux administratifs", 0),
    ("Fourniture de denrées alimentaires pour la cantine scolaire", 0),
    ("Acquisition de véhicules utilitaires pour le parc automobile", 0),
    ("Travaux de réfection de la voirie et de l'éclairage public", 0),
    ("Fourniture de carburant et lubrifiants pour la flotte", 0),
    ("Marché de gardiennage et de sécurité des bâtiments publics", 0),
    ("Acquisition d'ordinateurs de bureau et imprimantes", 0),
    ("Fourniture de papeterie et articles de bureau", 0),
    ("Travaux d'installation de climatisation dans les bureaux", 0),
    ("Acquisition d'uniformes et de tenues de travail", 0),
    ("Marché d'assurance du parc immobilier de l'établissement", 0),
    ("Fourniture de matériel électrique et de câblage", 0),
    ("Acquisition de pneumatiques pour les véhicules de service", 0),
    ("Travaux de peinture et de plâtrerie des salles de classe", 0),
    ("Fourniture de produits d'entretien et consommables sanitaires", 0),
    ("Marché de restauration collective pour un internat", 0),
    ("Acquisition de matériel agricole (tracteurs et remorques)", 0),
    ("Fourniture de fournitures scolaires pour les élèves", 0),
    ("Travaux d'aménagement d'espaces verts et d'arrosage", 0),
    ("Acquisition de groupes électrogènes pour les administrations", 0),
    ("Marché de transport du personnel", 0),
    ("Fourniture de mobilier scolaire (tables et chaises)", 0),
    ("Acquisition de matériel de cuisine pour restaurant universitaire", 0),
    ("Travaux de forage et d'adduction d'eau potable", 0),
    ("Fourniture de pièces détachées pour engins de travaux publics", 0),
    ("Marché d'impression de documents et registres officiels", 0),
    ("Acquisition d'extincteurs et de matériel anti-incendie", 0),
    ("Fourniture de matériel de sonorisation pour salle des fêtes", 0),
    ("Acquisition de climatiseurs pour la bibliothèque municipale", 0),
    ("Travaux de maçonnerie pour la clôture du stade", 0),
    ("Fourniture de produits pharmaceutiques (médicaments) pour la pharmacie", 0),
    ("Acquisition de lits et matelas pour l'hébergement universitaire", 0),
    ("Marché de collecte et de traitement des déchets ménagers", 0),
]


def load() -> "tuple[list[str], list[int]]":
    texts = [t for t, _ in LABELED_TENDERS]
    labels = [y for _, y in LABELED_TENDERS]
    return texts, labels
