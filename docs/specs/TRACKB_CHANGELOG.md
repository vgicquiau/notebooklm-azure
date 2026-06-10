# Track B — Journal d'avancement (finition T13/T15/T16/T17/T18)

> Suivi de l'arc « finir Track B pour en faire une fonctionnalité utilisable dans l'interface NotebookLM Azure » (redirection utilisateur — pas un frontend séparé `modernagent-frontend`).
> Plan détaillé : `C:\Users\v.gicquiau\.claude\plans\immutable-splashing-harp.md`
> Rappel : T10/T11/T12/T14 (reste de Track B) ont été livrés et vérifiés lors de l'arc précédent — voir `PROGRESS.md` / Gate live `modernagent-adgm-dev`.

## État global

| # | Increment | Statut |
|---|---|---|
| 1 | Backend `fn-adgm-graph` — fix SQL + T13 (PATCH qualification) + T15 (Louvain/`/clusters`) | ✅ Terminé & vérifié (endpoints live) |
| 2 | Pont — proxy `api/routers/graph.py` + vendoring Cytoscape.js | ✅ Terminé & vérifié (local) |
| 3 | Frontend — `GraphPage` bi-plan (F1.2), switch Chat ⇄ Graphe | ✅ Terminé & vérifié (navigateur) |
| 4 | Frontend — panneau de détail + annotation 7R + SPOF/impact (F1.4) | ✅ Terminé & vérifié (navigateur, double preuve de persistance) |
| 5 | Frontend — visualisation clusters + exports JSON/CSV (T15 UI + T18) | ✅ Terminé & vérifié (navigateur, blobs JSON+CSV validés) |

## Journal

### 2026-06-08 — Increment 1 : Backend `fn-adgm-graph` (T13 + T15)
- **Correctif bloquant** `SQL_CONNECTION_STRING` : reformatage ADO.NET → syntaxe ODBC (`Driver={ODBC Driver 18 for SQL Server};Server=tcp:...;UID=...;PWD=...`) dans `local.settings.json` + paramètres de la Function App déployée. `/graph/health` confirme désormais `sql: "up"`.
- **T13** — `PATCH /graph/nodes/{id}/qualification` : validations (400 candidat7R invalide, 422 source/author manquants, 404 nœud absent/non technique), écriture Neo4j (`SET candidate7R` en capturant l'ancienne valeur) + historisation dans `dbo.NodeAnnotationHistory` via un nouveau helper `get_sql_connection()` (1ʳᵉ écriture pyodbc de cette function app, miroir de `get_neo4j_driver()`). Réponse `{nodeId, candidate7R, previous7R, annotationId, updatedAt}` conforme SDD §3.
- **T15** — Louvain + `GET /graph/clusters` : `gds.louvain.write` (Cypher verbatim SDD §2.1) intégré au job existant `POST /graph/admin/analyze` (réutilise `_drop_projection_if_exists`). `cohesion`/`externalCoupling`/`isCandidateApartment` n'ont pas de formule dans la SDD (seulement les seuils 0.7/0.3) → dérivés des arcs `DEPENDS_ON` internes/externes par communauté, formule documentée inline et validée à la main sur le graphe live (même discipline « prédire puis vérifier » que pour le betweenness). `GET /graph/clusters` agrège à la lecture par `communityId` (pas de nouveau label Neo4j inventé) ; 409 si pas encore calculé.
- **Vérifié en direct** : redeploy (`func azure functionapp publish modernagent-adgm-dev --python`) puis `Invoke-RestMethod` contre les endpoints live, diffés contre les formes SDD §3 — PATCH + re-GET confirment la persistance `candidate7R`/historique ; `analyze` → `GET /clusters` renvoie les communautés attendues.

### 2026-06-08 — Increment 2 : Pont proxy + vendoring Cytoscape
- Nouveau routeur `api/routers/graph.py` : proxy async `httpx.AsyncClient` (mêmes conventions que `chat.py`/`sources.py`/`ingest.py`), forward `health | nodes | nodes/{id} | nodes/{id}/impact | arcs | clusters` (GET) et `nodes/{id}/qualification` (PATCH) vers `${ADGM_GRAPH_API_URL}`. `httpx==0.28.1` épinglé dans `api/requirements.txt`, monté via `app.include_router(graph_router, prefix="/api")` dans `main.py` — hérite de `APIKeyMiddleware` sans rien ajouter. Nouvelle variable d'env `ADGM_GRAPH_API_URL` documentée dans `.env.example`/`CLAUDE.md`.
- `cytoscape.min.js` copié depuis `modernagent-frontend/node_modules/cytoscape/dist/` vers `frontend/vendor/` (même politique de vendoring locale que mermaid/marked/dompurify — SEC-008), balise `<script>` ajoutée dans `index.html` avant les scripts applicatifs.
- **Vérifié en local** : serveur de dev démarré, `Invoke-RestMethod http://127.0.0.1:8000/api/graph/health` fait l'aller-retour vers la Function live (forme `{status, neo4j, sql, version}` correcte) ; `window.cytoscape` confirmé défini dans la console navigateur.

### 2026-06-08 — Increment 3 : Vue graphe bi-plan (F1.2)
- `Header.jsx` : ajout d'un switch de vue Chat ⇄ « Graphe ADG-M » (`ViewSwitch`). `App.jsx` : état `view` + rendu conditionnel — layout 3-rails existant ou `GraphPage` plein écran.
- Nouveau `GraphPage.jsx` : charge `nodes`/`arcs` via le proxy `/api/graph/*`, rendu Cytoscape avec feuille de style/layouts/couleurs **verbatim SDD §6** (`STATUS_COLORS`, `R7_COLORS`, `graphStylesheet`, `techLayout`/`functionalLayout` + layout `overlay` en `cose` — non prescrit par la SDD, choisi car il sépare naturellement deux sous-graphes disjoints). Switch de plan (Fonctionnel / Technique / Superposé) qui filtre nœuds+arcs et adapte le layout, légende adaptative (`showStatus`/`showR7` selon le plan), indices visuels SPOF (préfixe `⚠` + bordure rouge épaisse — équivalent du « badge » SDD en rendu canvas), fantôme (bordure pointillée) et arcs critiques (rouge épais).
- **Vérifié dans le navigateur** (automatisation CDP — scripts/captures supprimés après usage, repo laissé propre) :
  - Les 3 plans chargent avec des comptages cohérents et croisés : Technique 24 nœuds/12 arcs, Fonctionnel 13/6, Superposé 37/18 (24+13=37 ✓, 12+6=18 ✓).
  - **Diagnostic notable** : le premier passage de vérification affichait un écran « Chargement… » figé sur les 3 plans (0 nœud/0 arc) — ressemblait à un bug bloquant. Investigation (capture des événements réseau + polling du DOM) : `/api/graph/nodes` et `/api/graph/arcs` renvoyaient bien 200, le chargement réel prend ~6 s (cold-start du proxy vers la Function Azure) contre 3-3,5 s attendus dans le script de test. **Le code était correct ; seul le calibrage du test était trop court.** Reconfirmé avec un helper `waitForLoaded()` (poll 2 s, jusqu'à 20 s).
  - SPOF connu `fdc54935-56b8-44b3-a43b-9c66467d7844` / `FL-PREP-COMMANDE` rendu `⚠ FL-PREP-COMMANDE` avec bordure rouge + arcs critiques en rouge ; sélection de nœud (`:selected`, overlay 0.2) confirmée fonctionnelle par clic synthétique CDP sur les coordonnées rendues du nœud.
- Nettoyage complet de l'infrastructure de test ad hoc (scripts `_cdp_*.mjs`, dossier `_shots/`, arborescence de processus Chrome headless, profil temporaire) — aucune trace laissée dans le repo.

### 2026-06-08 — Increment 4 : Panneau de détail + annotation 7R + SPOF/impact (F1.4) — ✅ TERMINÉ & VÉRIFIÉ
- Recherche SDD complétée : contrats exacts `GET /graph/nodes/{id}` (node + metrics + arcs entrants/sortants), `GET /graph/nodes/{id}/impact` (liste downstream + `isSPOF`), `PATCH .../qualification` (payload/réponse/erreurs 400/404/422), arborescence prescrite `RightPanel` → `NodeDetail` + `ArcList` + `AnnotationPanel` (sélecteur 7R + justification obligatoire — SDD §9 ligne 879).
- Décisions de conception actées (gaps de spec comblés) :
  - Pas d'auth Azure AD/MSAL dans cette app (seulement clé API `_apiFetch`) alors que la SDD attend un `author` = UPN du décideur → champ texte libre, persisté dans `localStorage` (`nlaz-adgm-author`), miroir du pattern `nlaz-session`/`getOrCreateSessionId` déjà en place.
  - `source` figé à `'MANUAL'` (non sélectionnable) : cette UI EST l'outil d'« annotation manuelle ADG-M (F1.4) » visé par la SDD ligne 460 — un sélecteur serait une fausse option.
  - `GET .../impact` n'est interrogé que si `node.isSPOF === true`, conformément au cadrage de cet endpoint dans la SDD (« pour un nœud SPOF, retourne... »).
  - Sous-composants (`NodeDetailPanel`, `AnnotationForm`, `ArcSection`, `ImpactSection`, etc.) ajoutés directement dans `GraphPage.jsx` plutôt qu'un fichier séparé — cohérent avec `PlanSwitch`/`Legend` qui y vivent déjà ; fait passer le fichier de 309 à 584 lignes (dans la fourchette ~560-660 prévue), conforme à la norme du projet (`ChatPanel.jsx`=484, `SourcesRail.jsx`=510, `NotesRail.jsx`=415 lignes).
- Code transcrit en 3 éditions ciblées (nouveaux composants entre `Legend` et la section page-principale, état `selectedId`/`nodesById`/`closeDetail`/`handleQualified`, restructuration du canvas en wrapper flex avec panneau conditionnel) ; syntaxe validée hors-navigateur par un smoke test Babel (`Babel.transform(src, {presets:['react']})` exécuté dans un sandbox Node `vm` chargeant `babel.min.js` — `BABEL_OK, output length: 34007`).
- **Vérifié dans le navigateur** (automatisation CDP — scripts/captures supprimés après usage, repo laissé propre), checklist du plan suivie clause par clause :
  - Clic sur le SPOF connu `fdc54935-.../FL-PREP-COMMANDE` → panneau affichant toutes les sections (propriétés, métriques, badge `⚠ SPOF`, impact, arcs, formulaire d'annotation).
  - Liste d'impact confirmée : 3 composants en aval avec noms/distances/criticités correctes (FL-STAT-VENTES-VSAM +1 MEDIUM, GE01-REFERENTIEL +1 CRITICAL, FL-EDITION-RAPPORTS +2 LOW).
  - Soumission réelle d'une qualification (`UNQUALIFIED → REFACTOR`) via le PATCH live ; message de retour `« Qualifié : Non qualifié → Refactor »` (donc `previous7R` bien reflété dans l'UI).
  - Persistance prouvée par **deux canaux indépendants** (plutôt que de répéter l'écriture de test et polluer l'historique) : (a) un `Invoke-RestMethod` GET totalement frais (nouveau process, sans aucun état navigateur) renvoyant `candidate7R=REFACTOR` + `updatedAt=2026-06-08T17:13:15Z` ; (b) une session Chrome headless neuve (profil/cookies/localStorage vierges) où, dès le tout premier chargement, le nœud SPOF est rendu en orange (`R7_COLORS.REFACTOR`) et le tout premier clic affiche directement la pastille « Refactor ».
  - **Diagnostic notable (bug du script de test, pas du produit)** : entre les deux clics prévus par le script de vérification, le nœud SPOF avait visuellement « bougé » à l'écran (x≈1481 → x≈1147) — pas un défaut du graphe, mais le redimensionnement du canvas à l'ouverture/fermeture du panneau qui décale les coordonnées écran (`renderedPosition()`) de tous les nœuds ; corrigé en recalculant la position juste avant chaque clic synthétique (+ délai de stabilisation après `cy.resize()`). Même style de diagnostic que le faux-bug « chargement figé » de l'Increment 3 — l'environnement de test, pas le produit, était en cause.
- Nettoyage complet de l'infrastructure de test ad hoc (scripts `_cdp_verify4*.mjs`, dossier `_shots4/`, profils Chrome temporaires `cdp-profile-i4`/`i4b`) — aucune trace laissée dans le repo.

### 2026-06-08 — Increment 5 : Visualisation clusters + exports JSON/CSV (T15 UI + T18) — ✅ TERMINÉ & VÉRIFIÉ
- **Diagnostic préalable (gap spec↔impl)** : `TechnicalNode.clusterId` est documenté dans la SDD mais jamais peuplé par le backend (Louvain écrit `communityId` sur les nœuds Neo4j, pas `clusterId` — vérifié live sur les 24 nœuds techniques, tous `clusterId: null`). Décision : dériver l'appartenance côté client en inversant `nodeIds[]` de `GET /graph/clusters?candidateOnly=true`. Sans surprise ni compromis : la SDD ne prescrit pas où ce mapping doit se faire.
- **Encodage visuel** : `overlay-*` (Cytoscape) choisi pour le halo de cluster car il ne touche ni au remplissage (`7R_COLORS`/`STATUS_COLORS`), ni à la bordure (`isSPOF` : rouge épaisse), ni à `:selected` (l'overlay-opacity 0.2 reste actif par-dessus le halo, `overlay-color` étant absent du sélecteur `:selected`). Règle `node[clusterColor]` placée juste avant `:selected` dans `GRAPH_STYLE` — collision visuellement vérifiée nulle.
- **Composants ajoutés à `GraphPage.jsx`** (de 584 → 787 lignes) :
  - `CLUSTER_PALETTE` (8 couleurs) + `ClusterToggle` (pill button avec point coloré, badge de comptage `Appartements candidats (N)`, désactivé en plan Fonctionnel ou si pas de clusters)
  - `ClusterList` : panneau flottant `position:absolute` dans la zone canvas, liste scrollable des clusters candidats avec swatch couleur, `clusterId`, et métriques (`size · cohésion X · couplage ext. Y`) ; clic → `cy.fit(members, 80)` (viewport focus garanti non-animé)
  - Helpers d'export : `_downloadFile` (Blob + `<a download>` + revokeObjectURL), `_csvCell` (quote-doubling + arrays `|`-joinés + BOM `﻿`), `exportClustersJson` (wrapper `{exportedAt,total,items}`, filename `adgm-clusters-{date}.json`), `exportUnqualifiedCsv` (filtre `type===technical && candidate7R===UNQUALIFIED`, 11 colonnes, filename `adgm-non-qualifies-{date}.csv`)
  - `GraphActions` : deux boutons export (Clusters·JSON + Non qualifiés·CSV avec compteur)
- **Câblage** : état `showClusters`/`clusters`, `useEffect` clusters séparé (graceful 409 — analyse Louvain jamais lancée = état normal, pas une erreur de page), `nodeClusterIndex` memo (Map<nodeId, {cluster,color}>), `elements` memo augmenté d'un champ `clusterColor` conditionnel, `focusCluster` callback (`cy.fit`), effet auto-désactivation en plan Fonctionnel, toggle-disabled + tooltip contextuel, TopBar restructurée (`PlanSwitch` + `ClusterToggle` à gauche, `GraphActions` + `Legend` à droite), `ClusterList` conditionnel dans la zone canvas.
- **Syntaxe validée** : `BABEL_OK, output length: 46944` (Babel transform dans sandbox Node `vm`, même technique qu'Increment 4).
- **Vérifié dans le navigateur** (automatisation CDP — scripts/profils supprimés après usage, repo laissé propre) :
  - Graphe chargé : `24 nœuds · 12 arcs` (plan Technique, cohérent avec les increments précédents ; cold-start Azure ~6 s, attendu).
  - `ClusterToggle` : bouton trouvé avec text `"Appartements candidats (4)"` — le comptage 4 correspond aux 4 clusters `isCandidateApartment: true` retournés par `GET /graph/clusters?candidateOnly=true` (vérifié en Increment 1 + live avant codage). Initialement `disabled` le temps du cold-start du proxy, devient enabled dès le retour 200.
  - `ClusterList` panel : visible après clic toggle. Premier clic de rang : `FOCUSED:cl-13 · 2 nœuds · cohésion 1.00 · couplage ext. 0.00` — viewport recentré sur les membres du cluster.
  - **Export JSON** (`Clusters · JSON`) : blob `application/json, 1 219 octets`, head = `{"exportedAt":"2026-06-08T21:03:10.688Z","total":4,"items":[{"clusterId":"cl-13","name":null,"nodeIds":[...]` — forme `{exportedAt,total,items}` conforme SDD §3 + `_downloadFile`.
  - **Export CSV** (`Non qualifiés · CSV`) : blob `text/csv;charset=utf-8, 2 076 octets`, header `id,componentName,technology,linesOfCode,callFrequency,criticalityScore,betweenness,isSPOF,docCoveragePercent,knowledgeOwner,regulatoryTags` — 11 colonnes correctes, BOM UTF-8 présent (compatibilité Excel/locale française).
- Nettoyage complet (`_cdp_verify5.mjs`, profils Chrome temporaires `cdp-profile-i5*`) — aucune trace laissée dans le repo.

---
*Une entrée par increment livré (granularité alignée sur le plan `immutable-splashing-harp.md`). Mise à jour au fil de l'eau, pas en fin d'arc — pour que le travail reste suivable et reprenable à tout moment.*
