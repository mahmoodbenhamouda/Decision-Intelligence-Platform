# Architecture du frontend — MVVM

Le frontend (Next.js 16, React 19, TypeScript strict) suit le patron **MVVM**
(Model – View – ViewModel), dans sa forme idiomatique React :

| Couche | Rôle | En React | Nommage |
|---|---|---|---|
| **Model** | les données, leurs types, l'accès à l'API et les règles métier | fonctions et types TypeScript, **sans React** | `x.types.ts`, `x.service.ts`, `x.regles.ts` |
| **ViewModel** | l'état de l'écran, les actions de l'utilisateur, les valeurs dérivées prêtes à afficher | hook personnalisé | `useX.ts` |
| **View** | l'affichage, et rien d'autre | composant qui appelle **un** hook et rend du JSX | `XPanel.tsx`, `EcranX.tsx` |

```
            ┌────────────────────────────── View ──────────────────────────────┐
            │  ChurnPanel.tsx : const { data, loading } = useChurn();  → JSX    │
            └───────────────────────────────┬──────────────────────────────────┘
                                            │ lit l'état, appelle les actions
            ┌────────────────────────── ViewModel ─────────────────────────────┐
            │  useChurn.ts : useRequete(chargerDecrochage) → { data, loading }  │
            └───────────────────────────────┬──────────────────────────────────┘
                                            │ appelle
            ┌──────────────────────────── Model ───────────────────────────────┐
            │  churn.service.ts : apiJson<ChurnData>("/api/churn?limite=25")    │
            │  churn.types.ts   : ChurnClient, ChurnData                        │
            └───────────────────────────────┬──────────────────────────────────┘
                                            │
                                  core/api/client.ts  →  API FastAPI
```

## Organisation des dossiers

```
src/
  app/                    routes Next.js uniquement (page.tsx, login/page.tsx, layout, styles)
  core/                   socle commun, sans rien de métier
    config.ts             URL de l'API (seul endroit)
    api/client.ts         authFetch, api, apiJson, apiEnvoyer — cookie httpOnly, 401 → /login
    auth/session.ts       session locale (rôle, nom, e-mail) — le JWT n'y est jamais
    auth/useSession.ts    lecture de la session, sans écart d'hydratation
    hooks/useRequete.ts   brique des ViewModels qui chargent des données
  features/               une fonctionnalité = un dossier (Model + ViewModel + View)
    tableau-de-bord/      cockpit : filtres, indicateurs, graphes, onglets
    auth/                 connexion, déconnexion
    briefing/             « Priorités » (flotte d'agents)
    taches/               « Suivi des actions », fenêtre « Confier »
    churn/                « Rétention »
    commercial/           « Devis & marge »
    stock/                « Stock », approvisionnement, volumes à prévoir
    copilote/             FinBot (conversation, voix, avatar)
    ocr/                  « Documents & OCR »
    espace-client/        « Mon espace » (portail client)
    admin/                « Administration »
  shared/                 réutilisé par plusieurs fonctionnalités, sans appel à l'API
    ui/                   VisuelKit, BarreLaterale, Pourquoi
    avatar/               FinBotAvatar, FinBotAvatar3D, FloatingCompanion, CuteMascotRenderer
    format.ts             formats de date communs
```

## Règles

1. **Une vue n'appelle jamais l'API.** Aucun `fetch` ni import de `core/api`
   dans un fichier `.tsx` de `features/` ou `shared/`.
2. **Un service ne connaît pas React.** Il reçoit des paramètres et renvoie des
   données typées ; il transforme les erreurs réseau en valeurs affichables
   (« service momentanément indisponible ») au lieu de les laisser remonter.
3. **Aucune URL en dur.** Les services passent des chemins relatifs
   (`/api/churn`) ; l'URL de base est dans `core/config.ts`.
4. **Le ViewModel ne fait pas de `setState` synchrone dans un effet.**
   `useRequete` déduit l'état de chargement au lieu de le positionner, et ne
   met l'état à jour qu'à l'arrivée de la réponse. Les 14 erreurs ESLint
   « setState synchronously within an effect » ont disparu avec la refonte.
5. **Les règles métier ont leur fichier** (`*.regles.ts`) : type d'action
   suggéré selon le domaine d'une alerte, délais par gravité, adresse de
   connexion dérivée du nom d'un établissement, champs vérifiables d'une
   facture… Elles se lisent et se testent sans écran.
6. **Une fonctionnalité en importe une autre par son ViewModel ou sa vue
   publique** (ex. `commercial` réutilise `useConfiees` et `ConfierTache` de
   `taches`), jamais par ses fichiers internes de service.

## Vérification de la refonte

La refonte ne change rien à l'écran. Pour le démontrer, l'ancienne et la
nouvelle version ont été construites puis ouvertes côte à côte sur la même API
factice, pour les trois rôles et les 20 onglets, ainsi que pour cinq parcours
(ouvrir « Confier », changer un filtre, poser une question au copilote,
agrandir un graphe, se connecter) :

* captures d'écran identiques (0 à 3 pixels différents par écran, dus à
  l'anticrénelage des graphes) ;
* mêmes requêtes envoyées à l'API, avec les mêmes corps ;
* `tsc --noEmit` et `next build` réussis ; ESLint : 0 erreur (18 avant),
  9 avertissements (35 avant), tous dans des fichiers d'avatar et des balises
  `<img>` non concernés par la refonte.
