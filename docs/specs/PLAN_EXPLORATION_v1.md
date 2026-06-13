# Plan d'action — Module Exploration (Neo4j + ArchiMate)

> Basé sur [SDD_Exploration_v1.md](SDD_Exploration_v1.md) (v1.0, juin 2026). Plan exécutable pour une équipe de 2-4 développeurs.

---

## Adaptations d'architecture vs SDD

Le SDD propose une stack générique (Express/NestJS, TypeScript, TanStack Query, Zod, JWT RS256, rate limiting). Le code existant de `notebooklm-azure` est différent — pour démarrer **sans nouvelle décision d'architecture**, ce plan adapte le SDD au stack en place plutôt que d'en introduire un nouveau :

| Élément SDD | Décision pour ce plan | Raison |
|---|---|---|
| API Layer (Express/NestJS/TS) | Nouvelles routes dans `azure-functions/fn-adgm-graph/function_app.py` (même pattern que l'existant : `get_neo4j_driver()`, `_to_json`, `error_response`), préfixe `/api/exploration/*`. Si le fichier devient trop gros, extraire `exploration_routes.py` importé par `function_app.py`. | Driver Neo4j + APOC déjà configurés là, même Function App déployée (`modernagent-adgm-dev`) — pas de nouvelle infra Bicep. |
| Proxy FastAPI | Nouveau `api/routers/exploration.py`, même pattern `_forward` que `api/routers/graph.py` (GET/POST/PATCH/DELETE → `{ADGM_GRAPH_API_URL}/exploration/...`). | Cohérence avec `graph.py` existant, CORS/CSP déjà gérés. |
| React 18 + TS + TanStack Query + Zod | `frontend/src/ExplorationPage.jsx` — React + Babel standalone (comme `GraphPage.jsx`), hooks maison (`useState`/`useEffect`/`fetch`), validation manuelle (pas de Zod). | Aucun build step / TS / React Query dans le projet actuellement — ne pas introduire ces dépendances pour un seul module. |
| Invalidation cross-onglets via QueryClient | Pas de QueryClient dans l'app. Remplacé par : un événement custom `window.dispatchEvent(new CustomEvent('adgm:graph-changed'))` après chaque mutation Exploration ; `GraphPage.jsx` écoute cet événement et relance son fetch si l'onglet est actif. | Mécanisme minimal équivalent, zéro nouvelle dépendance. |
| JWT RS256 + refresh token + sessions | App actuelle = local, mono-utilisateur, `APIKeyMiddleware` global. Remplacé par un header `X-User-Role` (valeurs `VIEWER`/`ARCHITECT`/`ADMIN`, défaut `ARCHITECT`), résolu par une fonction `resolve_role(request)` côté Function. Un sélecteur de rôle est ajouté dans l'UI (zone Header, usage dev/démo RBAC). | Permet d'implémenter et tester réellement la matrice RBAC du SDD sans construire un système d'auth complet inutile pour un usage local. `resolve_role()` est le seul point à remplacer par un vrai JWT en v2. |
| Rate limiting, CSRF, masquage IP, HTTPS forcé | Hors scope (app locale, déjà documenté comme "Dev" dans le README). | Pas pertinent pour un usage local mono-poste — à revisiter si l'app est un jour exposée. |
| AuditLog, contraintes, index, validations ArchiMate (VAL-01..08), soft-delete cascade | Implémentés tels que décrits dans le SDD. | Valeur réelle indépendamment du contexte d'auth — pas de raison de descope. |

**Tout le reste du SDD (modèle de données, requêtes Cypher N1-N7/R1-R5, wireframes, codes d'erreur, règles de validation) est repris tel quel.**

---

## PHASE 0 — Fondations (~3 jours)

### Tranche BACKEND

- **TÂCHE-0-B-01** : Schéma Neo4j (contraintes + index)
  - Prérequis : aucun
  - Description : Créer le script `azure-functions/db/exploration_schema.cypher` avec les contraintes/index du §4 du SDD (`archimate_element_id_unique`, `archimate_element_name_exists`, `archimate_name_fulltext`, `archimate_layer_type_idx`, `archimate_tags_idx`, `archimate_created_idx`, `audit_entity_idx`). Note : ignorer la contrainte `archimate_relation_id_unique` par type de relation (peu pratique avec 11 types) — gérer l'unicité de `r.id` applicativement (généré serveur, jamais fourni par le client).
  - Artefact : `azure-functions/db/exploration_schema.cypher`
  - Critère acceptation : exécution du script via `cypher-shell` sur AuraDB sans erreur ; `SHOW CONSTRAINTS`/`SHOW INDEXES` listent les nouveaux éléments.
  - Estimation : 0.5 jour
  - Dépendances croisées : bloque T1-B-* (toutes les requêtes Cypher supposent ces index).

- **TÂCHE-0-B-02** : Module whitelist ArchiMate (labels, types, règles)
  - Prérequis : aucun
  - Description : Nouveau module `azure-functions/fn-adgm-graph/archimate_taxonomy.py` — constantes Python : `LAYERS` (7), `ELEMENT_TYPES_BY_LAYER` (48 types, §2 "Mapping ArchiMate → Types de nœuds"), `ASPECTS` (3), `RELATION_TYPES` (11), `ACCESS_TYPES` (3). Fonctions `validate_element_type(layer, elementType)`, `labels_for(layer, elementType)` → `['ArchiMateElement', layer, elementType]`.
  - Artefact : `azure-functions/fn-adgm-graph/archimate_taxonomy.py`
  - Critère acceptation : test unitaire `test_archimate_taxonomy.py` couvrant les 48 types + cas invalide (VAL-01).
  - Estimation : 1 jour
  - Dépendances croisées : bloque T1-B-03/04, T2-B-03 (toutes les validations) ; T0-F-03 doit refléter la même liste côté frontend.

- **TÂCHE-0-B-03** : `resolve_role()` + middleware RBAC minimal
  - Prérequis : aucun
  - Description : Fonction `resolve_role(req)` dans `function_app.py` lisant le header `X-User-Role` (whitelist `VIEWER`/`ARCHITECT`/`ADMIN`, défaut `VIEWER` si absent/invalide). Décorateur/helper `require_role(req, *allowed_roles)` levant `error_response(..., 403, "AUTH_INSUFFICIENT_ROLE")`.
  - Artefact : modif `function_app.py` (nouvelles fonctions utilitaires, section "RBAC")
  - Critère acceptation : test unitaire — header absent → VIEWER ; header `ADMIN` → ADMIN ; header invalide → 403 sur un endpoint factice protégé.
  - Estimation : 0.5 jour
  - Dépendances croisées : bloque toutes les tâches backend de mutation (T1-B-03/04/05, T2-B-03/04/05, T3-B-01/02).

- **TÂCHE-0-B-04** : Squelette routes `/api/exploration/*` + proxy FastAPI
  - Prérequis : aucun
  - Description : Dans `function_app.py`, créer les 12 routes du §3 (squelettes retournant `501 Not Implemented` sauf health-check trivial). Côté API, créer `api/routers/exploration.py` (copie du pattern `_forward` de `graph.py`, GET/POST/PATCH/DELETE sur `/exploration/{path:path}`), l'enregistrer dans `api/main.py`.
  - Artefact : `azure-functions/fn-adgm-graph/function_app.py` (12 routes stub), `api/routers/exploration.py`, `api/main.py` (registration)
  - Critère acceptation : `curl http://127.0.0.1:8000/api/exploration/nodes` retourne une réponse (501 ou JSON stub), pas de 404 de routing.
  - Estimation : 1 jour
  - Dépendances croisées : bloque toutes les tâches T1+/T2+ backend (chaque tâche remplace un stub).

### Tranche FRONTEND

- **TÂCHE-0-F-01** : Onglet Exploration — shell + routing
  - Prérequis : aucun
  - Description : Nouveau composant `frontend/src/ExplorationPage.jsx` (squelette : header local "Nœuds / Relations / Orphelins" + zone vue principale vide). Ajouter l'onglet dans `Header.jsx` / `App.jsx` (état `activeTab` existant, pas de React Router — l'app actuelle bascule des vues via state, suivre ce pattern). Charger le script dans `index.html` (ordre des `<script type="text/babel">`).
  - Artefact : `frontend/src/ExplorationPage.jsx`, modifs `Header.jsx`/`App.jsx`/`index.html`
  - Critère acceptation : clic sur l'onglet "Exploration" affiche le squelette sans erreur console ; bascule Chat ↔ Graphe ↔ Exploration fonctionne.
  - Estimation : 0.5 jour
  - Dépendances croisées : tous les composants F1+ se montent dans ce shell.

- **TÂCHE-0-F-02** : Client API + hooks fetch maison
  - Prérequis : T0-B-04 (routes stub doivent répondre)
  - Description : Module `frontend/src/explorationApi.js` — fonctions `fetchNodes(filters, page)`, `fetchNode(id)`, `createNode(payload)`, `updateNode(id, payload)`, `deleteNode(id, {cascade})`, `fetchOrphans(page)`, `fetchRelations(filters, page)`, `fetchRelation(id)`, `createRelation(payload)`, `updateRelation(id, payload)`, `deleteRelation(id)`, `fetchAudit(filters)`. Chaque fonction `fetch('/api/exploration/...', {headers: {'X-User-Role': currentRole}})`. Hook `useCurrentRole()` (lit/écrit `localStorage`, défaut `ARCHITECT`).
  - Artefact : `frontend/src/explorationApi.js`
  - Critère acceptation : appel `fetchNodes({}, 1)` depuis la console retourne une réponse (même stub) sans erreur CORS/réseau.
  - Estimation : 1 jour
  - Dépendances croisées : utilisé par tous les composants F1+.

- **TÂCHE-0-F-03** : Catalogue ArchiMate côté frontend
  - Prérequis : T0-B-02 (même source de vérité)
  - Description : `frontend/src/archimateTaxonomy.js` — recopie des constantes `LAYERS`, `ELEMENT_TYPES_BY_LAYER`, `ASPECTS`, `RELATION_TYPES`, `ACCESS_TYPES` (JS, miroir de `archimate_taxonomy.py`). Utilisé pour peupler les `<select>` Layer/ElementType en cascade.
  - Artefact : `frontend/src/archimateTaxonomy.js`
  - Critère acceptation : revue manuelle — les deux fichiers (Python/JS) listent exactement les 48 types par couche (test de cohérence ajouté en T1-T-01).
  - Estimation : 0.5 jour
  - Dépendances croisées : T1-F-03 (formulaire création nœud), T2-F-02 (formulaire relation).

### Tranche TESTS & QA

- **TÂCHE-0-T-01** : Jeu de données de test + fixtures Neo4j
  - Prérequis : T0-B-01
  - Description : Script `azure-functions/db/exploration_seed.cypher` créant ~15 nœuds (couvrant les 7 layers) + ~10 relations (couvrant Access/Assignment/Realization/Serving pour exercer VAL-03/05/06) sur une base de test isolée (ou un sous-graphe taggé `test:true` nettoyable). Fonction helper `cleanup_test_data()`.
  - Artefact : `azure-functions/db/exploration_seed.cypher`, `azure-functions/fn-adgm-graph/tests/conftest.py` (fixtures pytest)
  - Critère acceptation : `pytest --collect-only` détecte les fixtures sans erreur de connexion.
  - Estimation : 1 jour
  - Dépendances croisées : utilisé par tous les tests d'intégration T1-T/T2-T/T3-T/T4-T.

**Total Phase 0 : ~3 jours (parallélisable sur 3 personnes : Backend A → T0-B-01+02, Backend B → T0-B-03+04, Frontend → T0-F-01+02+03, en parallèle avec T0-T-01)**

---

## PHASE 1 — CRUD Nœuds (MVP) (~6 jours)

### Tranche BACKEND

- **TÂCHE-1-B-01** : `GET /api/exploration/nodes` (N1 + N1b)
  - Prérequis : T0-B-01, T0-B-04
  - Description : Implémenter N1 (liste paginée filtrée) + N1b (count) du §6. Paramètres query : `layer`, `elementType`, `aspect`, `name`, `tags` (CSV), `orphansOnly`, `skip`, `limit` (défaut 50, max 200 — clamp serveur, cf. risque PERF-01). Réponse `{items: [...], total, skip, limit}`. Chaque item = `node_to_dto(n) + {relCount}`.
  - Artefact : `function_app.py` (route `list_exploration_nodes`)
  - Critère acceptation : `curl ".../exploration/nodes?layer=Business&limit=10"` → JSON paginé ; `limit=500` → clampé à 200.
  - Estimation : 1 jour
  - Dépendances croisées : T1-F-01 (NodeListView).

- **TÂCHE-1-B-02** : `GET /api/exploration/nodes/{id}` (N2)
  - Prérequis : T0-B-01, T0-B-04
  - Description : Implémenter N2 — détail nœud + `outgoing`/`incoming` (relations avec `relType`, `relProps`, `linkedNode`). 404 `NODE_NOT_FOUND` si absent.
  - Artefact : `function_app.py` (route `get_exploration_node`)
  - Critère acceptation : `curl .../exploration/nodes/{id}` → objet avec `outgoing: []`/`incoming: []` même si 0 relation ; id inexistant → 404.
  - Estimation : 0.5 jour
  - Dépendances croisées : T1-F-02 (NodeDetailView), T2-F-03 (affichage relations).

- **TÂCHE-1-B-03** : `POST /api/exploration/nodes` (N3 + VAL-01/02/04)
  - Prérequis : T0-B-02, T0-B-03, T0-B-04
  - Description : Implémenter N3 (création via `apoc.create.node` avec labels dynamiques `[elementType, layer, 'ArchiMateElement']`, via `archimate_taxonomy.labels_for`). Validations avant exécution : VAL-01 (elementType ∈ layer, sinon 400 `VAL_ELEMENT_TYPE`), VAL-02 (name 1-256, sinon 400 `VAL_NAME_REQUIRED`). VAL-04 garanti par la contrainte UNIQUE (id généré serveur, collision quasi impossible). RBAC : `ARCHITECT`/`ADMIN` (403 sinon). AuditLog `CREATE`/`NODE` dans la même requête (transaction explicite via `session.execute_write`).
  - Artefact : `function_app.py` (route `create_exploration_node`)
  - Critère acceptation : création valide → 201 + nœud ; layer/type incohérent → 400 `VAL_ELEMENT_TYPE` ; rôle `VIEWER` → 403.
  - Estimation : 1.5 jour
  - Dépendances croisées : T1-F-03 (NodeFormView create).

- **TÂCHE-1-B-04** : `PATCH /api/exploration/nodes/{id}` (N4)
  - Prérequis : T0-B-03, T1-B-03 (réutilise AuditLog/transaction helper)
  - Description : Implémenter N4 (COALESCE sur name/description/aspect/stereotype/tags/metadata, `updatedAt` régénéré). VAL-02 si `name` fourni. AuditLog `UPDATE`/`NODE` avec `{before, after}`. RBAC `ARCHITECT`/`ADMIN`.
  - Artefact : `function_app.py` (route `update_exploration_node`)
  - Critère acceptation : PATCH partiel ne touche pas les champs omis ; `id`/`createdAt` immuables même si fournis dans le payload (ignorés serveur).
  - Estimation : 1 jour
  - Dépendances croisées : T1-F-03 (NodeFormView edit).

- **TÂCHE-1-B-05** : `DELETE /api/exploration/nodes/{id}` (N5, safe)
  - Prérequis : T0-B-03, T1-B-03
  - Description : Implémenter N5 — `size((n)--())` ; si > 0 → 409 `NODE_HAS_RELATIONS` avec `{relCount}` dans le body (pas d'`apoc.util.validate` qui complique le retour du compte côté client — préférer un check explicite en deux temps : `MATCH` + `WITH ... CASE` retournant `relCount`, le serveur décide 409 vs DELETE). AuditLog `DELETE`/`NODE`. RBAC `ARCHITECT`/`ADMIN`. 404 si id absent.
  - Artefact : `function_app.py` (route `delete_exploration_node`)
  - Critère acceptation : nœud avec 0 relation → 200 `{deleted: true}` ; nœud avec N relations → 409 `{relCount: N}`.
  - Estimation : 1 jour
  - Dépendances croisées : T1-F-05 (modal confirmation).

- **TÂCHE-1-B-06** : `GET /api/exploration/orphans` (N7)
  - Prérequis : T0-B-01, T0-B-04
  - Description : Implémenter N7 (pagination, tri `layer ASC, createdAt DESC`). RBAC `ARCHITECT`/`ADMIN` (lecture restreinte selon matrice §8).
  - Artefact : `function_app.py` (route `list_exploration_orphans`)
  - Critère acceptation : `curl .../exploration/orphans` (rôle VIEWER) → 403 ; (rôle ARCHITECT) → liste paginée.
  - Estimation : 0.5 jour
  - Dépendances croisées : T1-F-04 (OrphanListView).

### Tranche FRONTEND

- **TÂCHE-1-F-01** : `NodeListView` (liste + filtres)
  - Prérequis : T0-F-01/02/03, T1-B-01 (peut démarrer sur stub T0-B-04 avec données mockées, puis brancher)
  - Description : Composant liste paginée (wireframe §5 "Liste Nœuds") — filtres Layer/ElementType (cascade via `archimateTaxonomy.js`)/Aspect/recherche nom/tags/orphelins ; tableau (Nom, Layer, Type, nb relations) ; pagination 25/50/100 ; actions ⋯ (Voir/Modifier/Supprimer).
  - Artefact : `frontend/src/ExplorationPage.jsx` (sous-composant `NodeListView`)
  - Critère acceptation : changement de filtre déclenche un nouveau fetch ; état vide affiche le message du §7 ("Aucun nœud ne correspond à ces filtres").
  - Estimation : 1.5 jour
  - Dépendances croisées : bloqué par T1-B-01 pour données réelles ; bloque T1-F-02/03/05 (navigation depuis la liste).

- **TÂCHE-1-F-02** : `NodeDetailView`
  - Prérequis : T1-B-02, T1-F-01
  - Description : Vue détail (wireframe §5 "Détail Nœud") — propriétés, tags, dates ; section Relations en lecture simple pour Phase 1 (tableau direction/type/nœud lié, sans édition — l'édition arrive en Phase 2 via T2-F-03).
  - Artefact : `ExplorationPage.jsx` (sous-composant `NodeDetailView`)
  - Critère acceptation : clic "Voir" depuis la liste affiche le détail correct ; bouton retour revient à la liste avec les filtres préservés.
  - Estimation : 1 jour
  - Dépendances croisées : T2-F-03 enrichira la section Relations.

- **TÂCHE-1-F-03** : `NodeFormView` (création/édition)
  - Prérequis : T0-F-03, T1-B-03, T1-B-04
  - Description : Formulaire (wireframe §5 "Formulaire Création/Édition Nœud") — sélecteurs Couche→Type en cascade, champs Nom/Description/Aspect/Tags/Stéréotype. Validation client immédiate VAL-01 (type cohérent avec couche, désactive le submit sinon) et VAL-02 (longueur nom). Affichage des erreurs serveur (400) inline avec focus auto (cf. §7 "Comportement UX sur erreur").
  - Artefact : `ExplorationPage.jsx` (sous-composant `NodeFormView`)
  - Critère acceptation : création réussie → toast succès + redirection détail + `window.dispatchEvent('adgm:graph-changed')` ; erreur 400 → champ en rouge + message.
  - Estimation : 1.5 jour
  - Dépendances croisées : VAL-05/08 (badges warning) ajoutés en Phase 2 (dépend de la logique relation, hors scope nœud seul).

- **TÂCHE-1-F-04** : `OrphanListView`
  - Prérequis : T1-B-06, T1-F-01 (réutilise le composant tableau)
  - Description : Vue dédiée "⚠ Orphelins" (menu latéral §5) — réutilise le tableau de `NodeListView` sans les filtres layer/type (juste pagination), avec lien direct vers `NodeDetailView`.
  - Artefact : `ExplorationPage.jsx` (sous-composant `OrphanListView`)
  - Critère acceptation : liste affiche uniquement des nœuds avec `relCount === 0`.
  - Estimation : 0.5 jour
  - Dépendances croisées : aucune.

- **TÂCHE-1-F-05** : Modal confirmation suppression (safe)
  - Prérequis : T1-B-05, T1-F-02
  - Description : Modal (wireframe §5 "Confirmation Suppression") — variante "safe" uniquement en Phase 1 (la case cascade/ADMIN arrive en Phase 3, T3-F-01). Si 409 `NODE_HAS_RELATIONS` reçu → message inline avec `relCount`, pas de fermeture automatique.
  - Artefact : `ExplorationPage.jsx` (sous-composant `DeleteConfirmModal`)
  - Critère acceptation : suppression nœud sans relation → toast succès + retour liste + invalidation ; suppression nœud avec relations → message 409 affiché, modal reste ouverte.
  - Estimation : 0.5 jour
  - Dépendances croisées : T3-F-01 étendra ce composant (option cascade).

### Tranche TESTS & QA

- **TÂCHE-1-T-01** : Tests unitaires whitelist + cohérence taxonomie
  - Prérequis : T0-B-02, T0-F-03
  - Description : Tests pytest pour `validate_element_type`/`labels_for` (48 types × 7 layers, cas valides/invalides). Test de cohérence Python ↔ JS : script comparant `archimate_taxonomy.py` et `archimateTaxonomy.js` (parsing simple, échoue si divergence).
  - Artefact : `azure-functions/fn-adgm-graph/tests/test_archimate_taxonomy.py`, `azure-functions/fn-adgm-graph/tests/test_taxonomy_consistency.py`
  - Critère acceptation : `pytest tests/test_archimate_taxonomy.py tests/test_taxonomy_consistency.py` → 100% pass.
  - Estimation : 0.5 jour
  - Dépendances croisées : T0-B-02, T0-F-03.

- **TÂCHE-1-T-02** : Tests d'intégration N1-N7
  - Prérequis : T0-T-01, T1-B-01..06
  - Description : Tests pytest (httpx contre Function locale `func start`, ou Flask test client si applicable) couvrant : pagination/filtres N1 (incl. clamp `limit=500`→200), N2 (avec/sans relations, 404), N3 (succès, VAL-01, VAL-02, 403 VIEWER), N4 (champs immuables), N5 (200 vs 409 selon relCount), N7 (uniquement orphelins).
  - Artefact : `azure-functions/fn-adgm-graph/tests/test_exploration_nodes.py`
  - Critère acceptation : `pytest tests/test_exploration_nodes.py` → 100% pass sur la base de seed T0-T-01.
  - Estimation : 1.5 jour
  - Dépendances croisées : exécuté en CI après chaque merge backend Phase 1.

- **TÂCHE-1-T-03** : E2E manuel/scripté — cycle de vie nœud
  - Prérequis : T1-F-01..05, T1-T-02
  - Description : Scénario E2E (script Playwright si outillage dispo, sinon checklist manuelle documentée) : créer un nœud Business/BusinessActor → le retrouver dans la liste (filtre layer) → ouvrir détail → modifier description → supprimer (safe, succès car 0 relation).
  - Artefact : `frontend/tests/e2e/exploration_node_lifecycle.md` (ou `.spec.js` si Playwright ajouté)
  - Critère acceptation : scénario complet sans erreur console, toasts corrects à chaque étape.
  - Estimation : 1 jour
  - Dépendances croisées : dernière étape de Phase 1 — jalon "MVP CRUD Nœuds" atteint si ce test passe.

**Total Phase 1 : ~6 jours. Parallélisation : Backend (T1-B-01→06, ~2 devs) en parallèle avec Frontend sur stubs T0-B-04 (T1-F-01→05, ~1-2 devs) ; Tests T1-T-01 démarre dès J1, T1-T-02/03 en fin de phase.**

---

## PHASE 2 — CRUD Relations + validations ArchiMate (~5 jours)

### Tranche BACKEND

- **TÂCHE-2-B-01** : `GET /api/exploration/relations` (R1)
  - Prérequis : T0-B-04, Phase 1 backend terminée (réutilise patterns pagination)
  - Description : Implémenter R1 — filtres `relationType`, `sourceId`, `targetId`, `sourceLayer`, `targetLayer`, pagination, tri `r.createdAt DESC`.
  - Artefact : `function_app.py` (route `list_exploration_relations`)
  - Critère acceptation : filtrage par `relationType=Access` ne retourne que des relations Access.
  - Estimation : 1 jour
  - Dépendances croisées : T2-F-01 (RelListView).

- **TÂCHE-2-B-02** : `GET /api/exploration/relations/{id}` (R2)
  - Prérequis : T0-B-04
  - Description : Implémenter R2 — détail relation + nœuds source/cible (avec `aspect`). 404 `RELATION_NOT_FOUND`.
  - Artefact : `function_app.py` (route `get_exploration_relation`)
  - Critère acceptation : `curl .../exploration/relations/{id}` → relation + source/target.
  - Estimation : 0.5 jour
  - Dépendances croisées : T2-F-02 (RelFormView edit).

- **TÂCHE-2-B-03** : `POST /api/exploration/relations` (R3 + R-CHECK + VAL-03/05/06/07/08)
  - Prérequis : T0-B-02, T0-B-03, T1-B-02 (vérif existence src/tgt)
  - Description : Implémenter R3 (`apoc.create.relationship`, type dynamique parmi les 11 `RELATION_TYPES` — whitelist obligatoire). Avant création : (1) MATCH src/tgt — 404 si absent ; (2) VAL-03 bloquant si `relationType==Access` et `accessType` absent/invalide → 400 ; (3) R-CHECK pour VAL-07 (doublon) ; (4) VAL-05 (Assignment: src.aspect != ActiveStructure), VAL-06 (Realization: ordre couches), VAL-08 (Composition/Aggregation cross-layer) — ces 3 retournent **422 `ARCHIMATE_WARN`** avec détail, sauf si le payload contient `confirmWarnings: true` (alors la création procède malgré l'avertissement, warning loggé dans l'AuditLog `payload.warnings`). AuditLog `CREATE`/`RELATION`. RBAC `ARCHITECT`/`ADMIN`.
  - Artefact : `function_app.py` (route `create_exploration_relation`)
  - Critère acceptation : Access sans accessType → 400 `VAL_ACCESS_TYPE` ; doublon sans `confirmWarnings` → 422 avec `existingRelId` ; doublon avec `confirmWarnings:true` → 201.
  - Estimation : 2 jours (la plus complexe de la phase)
  - Dépendances croisées : T2-F-02 (formulaire avec badges warning), T2-T-01 (tests de validation).

- **TÂCHE-2-B-04** : `PATCH /api/exploration/relations/{id}` (R4)
  - Prérequis : T2-B-03 (réutilise validations VAL-03)
  - Description : Implémenter R4 (COALESCE name/description/weight/accessType). VAL-03 ré-évalué si `accessType` modifié sur une relation `Access`. `weight` validé ∈ [0.0, 1.0] → 400 `VAL_WEIGHT_RANGE` sinon.
  - Artefact : `function_app.py` (route `update_exploration_relation`)
  - Critère acceptation : `weight=1.5` → 400 ; `accessType` retiré d'une relation Access → 400 `VAL_ACCESS_TYPE`.
  - Estimation : 0.5 jour
  - Dépendances croisées : T2-F-02 (édition).

- **TÂCHE-2-B-05** : `DELETE /api/exploration/relations/{id}` (R5)
  - Prérequis : T0-B-03
  - Description : Implémenter R5 — suppression directe + AuditLog `DELETE`/`RELATION`. 404 si absent. RBAC `ARCHITECT`/`ADMIN`.
  - Artefact : `function_app.py` (route `delete_exploration_relation`)
  - Critère acceptation : suppression → 200 ; second appel → 404.
  - Estimation : 0.5 jour
  - Dépendances croisées : T2-F-03.

### Tranche FRONTEND

- **TÂCHE-2-F-01** : `RelListView`
  - Prérequis : T0-F-01/02/03, T2-B-01
  - Description : Liste paginée des relations — filtres relationType (multi-select), sourceId/targetId (recherche nœud), sourceLayer/targetLayer. Colonnes : Type, Source, Cible, propriétés clés (weight, accessType).
  - Artefact : `ExplorationPage.jsx` (sous-composant `RelListView`)
  - Critère acceptation : filtre `relationType=Access` n'affiche que des relations Access avec leur `accessType`.
  - Estimation : 1 jour
  - Dépendances croisées : T2-B-01.

- **TÂCHE-2-F-02** : `RelFormView` (création/édition + badges warning)
  - Prérequis : T0-F-03, T2-B-03, T2-B-04
  - Description : Formulaire (wireframe §5 "Formulaire Création Relation") — recherche nœud source/cible (debounce sur `fetchNodes({name: ...})`), sélection type relation, champ `accessType` conditionnel (affiché seulement si type=Access), name/weight/description. Sur 422 `ARCHIMATE_WARN` : afficher le(s) badge(s) 🟡/🔵 correspondant (VAL-05/06/07/08, mapping table §7 "Avertissements ArchiMate"), case "Créer quand même" qui renvoie la requête avec `confirmWarnings: true`.
  - Artefact : `ExplorationPage.jsx` (sous-composant `RelFormView`)
  - Critère acceptation : création Assignment avec source non-ActiveStructure → badge VAL-05 + checkbox ; case cochée + resubmit → 201.
  - Estimation : 1.5 jour
  - Dépendances croisées : T2-B-03 (contrat 422 doit être stable avant cette tâche).

- **TÂCHE-2-F-03** : Brancher `NodeDetailView` sur les vraies relations + actions
  - Prérequis : T1-F-02, T2-B-02, T2-B-05, T2-F-02
  - Description : Étendre la section "Relations" de `NodeDetailView` (T1-F-02) : bouton "+ Ajouter une relation" ouvre `RelFormView` pré-rempli avec le nœud courant en source ; chaque ligne a une action "Voir" (→ R2 detail) et "Supprimer" (→ R5, avec confirmation simple).
  - Artefact : `ExplorationPage.jsx` (modif `NodeDetailView`)
  - Critère acceptation : ajout de relation depuis le détail nœud rafraîchit la liste de relations affichée sans rechargement de page complet.
  - Estimation : 1 jour
  - Dépendances croisées : ferme la boucle CRUD relations.

### Tranche TESTS & QA

- **TÂCHE-2-T-01** : Tests unitaires règles de validation VAL-03/05/06/07/08
  - Prérequis : T2-B-03, T0-T-01
  - Description : Tests pytest dédiés, un par règle : Access sans/avec accessType valide/invalide (VAL-03) ; Assignment source ActiveStructure vs autre (VAL-05) ; Realization Business→Tech vs Tech→Business (VAL-06) ; doublon avec/sans `confirmWarnings` (VAL-07) ; Composition cross-layer (VAL-08).
  - Artefact : `azure-functions/fn-adgm-graph/tests/test_exploration_validation.py`
  - Critère acceptation : 1 cas positif + 1 cas négatif par règle, tous passent.
  - Estimation : 1.5 jour
  - Dépendances croisées : T2-B-03.

- **TÂCHE-2-T-02** : Tests d'intégration R1-R5
  - Prérequis : T0-T-01, T2-B-01..05
  - Description : Tests pytest httpx — R1 filtres, R2 detail/404, R3 (succès, 404 src/tgt absent, 400 Access), R4 (weight range, accessType), R5 (succès, 404 second appel).
  - Artefact : `azure-functions/fn-adgm-graph/tests/test_exploration_relations.py`
  - Critère acceptation : 100% pass.
  - Estimation : 1 jour
  - Dépendances croisées : exécuté en CI.

- **TÂCHE-2-T-03** : E2E — création relation avec warning
  - Prérequis : T2-F-01..03, T2-T-02
  - Description : Scénario E2E : depuis le détail d'un nœud Business (ActiveStructure), créer une relation Assignment vers un nœud non-Behaviour → badge VAL-05 affiché → cocher "Créer quand même" → relation créée et visible dans la liste de relations du nœud.
  - Artefact : `frontend/tests/e2e/exploration_relation_warning.md`
  - Critère acceptation : scénario complet, badge correctement affiché et requête `confirmWarnings:true` envoyée.
  - Estimation : 0.5 jour
  - Dépendances croisées : jalon "MVP CRUD complet (Nœuds + Relations)" atteint.

**Total Phase 2 : ~5 jours. Parallélisation : T2-B-01/02/05 (simples, 1 dev) en parallèle de T2-B-03/04 (complexe, 1 dev) ; Frontend T2-F-01 démarre dès T2-B-01 livré, T2-F-02 attend le contrat 422 de T2-B-03 (peut commencer sur mock entre-temps).**

---

## PHASE 3 — Cascade, bulk, intégration cross-onglets (~4 jours)

### Tranche BACKEND

- **TÂCHE-3-B-01** : `DELETE /api/exploration/nodes/{id}?cascade=true` (N6, ADMIN)
  - Prérequis : T1-B-05, T0-B-03
  - Description : Étendre la route N5 : si query param `cascade=true` → vérifier `ADMIN` (403 sinon) → exécuter N6 dans `session.execute_write()` (transaction explicite, rollback automatique si exception — couvre INTEG-01). AuditLog `DELETE_CASCADE`/`NODE` avec `relCount`.
  - Artefact : `function_app.py` (extension route `delete_exploration_node`)
  - Critère acceptation : rôle ARCHITECT + `cascade=true` → 403 ; rôle ADMIN + `cascade=true` sur nœud à N relations → 200, nœud et les N relations supprimés, vérifié par requête de contrôle.
  - Estimation : 1 jour
  - Dépendances croisées : T3-F-01 (modal cascade).

- **TÂCHE-3-B-02** : `POST /api/exploration/nodes/bulk-tag` (N8)
  - Prérequis : T1-B-04 (réutilise logique tags), T0-B-03
  - Description : Endpoint `{nodeIds: [...], action: 'add'|'remove', tag: string}` — `UNWIND $nodeIds AS id MATCH (n:ArchiMateElement {id:id}) SET n.tags = CASE ...`. RBAC `ARCHITECT`/`ADMIN`. AuditLog une entrée agrégée (`entityId` = liste des ids concaténée ou une entrée par nœud — choisir une entrée par nœud pour cohérence avec le reste).
  - Artefact : `function_app.py` (route `bulk_tag_exploration_nodes`)
  - Critère acceptation : `add` ajoute le tag aux nœuds sans doublon (idempotent) ; `remove` retire le tag s'il existe, no-op sinon.
  - Estimation : 1 jour
  - Dépendances croisées : T3-F-02.

### Tranche FRONTEND

- **TÂCHE-3-F-01** : Modal cascade (extension `DeleteConfirmModal`)
  - Prérequis : T1-F-05, T3-B-01
  - Description : Étendre la modal (wireframe §5) — si `relCount > 0` et rôle courant = `ADMIN` : afficher checkbox "Supprimer aussi les N relations (cascade)" + texte "Irréversible". Si rôle != ADMIN et relCount > 0 : afficher uniquement le message 409 (comme Phase 1), pas de case cascade.
  - Artefact : `ExplorationPage.jsx` (modif `DeleteConfirmModal`)
  - Critère acceptation : ADMIN + relCount>0 + case cochée → DELETE avec `cascade=true` → 200 ; ARCHITECT + relCount>0 → message 409 sans option cascade.
  - Estimation : 1 jour
  - Dépendances croisées : T3-B-01.

- **TÂCHE-3-F-02** : Sélection multiple + Bulk tag UI
  - Prérequis : T1-F-01, T3-B-02
  - Description : Ajouter cases à cocher par ligne dans `NodeListView` (déjà esquissées dans le wireframe §5), barre "Sélection : N nœud(s)" + dropdown `[Tag ▾]` (ajouter/retirer un tag saisi). Visible seulement pour `ARCHITECT`/`ADMIN`.
  - Artefact : `ExplorationPage.jsx` (modif `NodeListView`)
  - Critère acceptation : sélection de 3 nœuds + ajout tag "core" → les 3 nœuds affichent le tag après refetch.
  - Estimation : 1 jour
  - Dépendances croisées : T3-B-02.

- **TÂCHE-3-F-03** : Invalidation cross-onglets Exploration ↔ Graphe ADG-M
  - Prérequis : toutes mutations Phase 1/2/3 émettent déjà `adgm:graph-changed` (convention posée en T1-F-03)
  - Description : Dans `GraphPage.jsx`, ajouter un `useEffect` qui écoute `window.addEventListener('adgm:graph-changed', refetch)` et déclenche un refetch des nœuds/arcs si l'onglet Graphe est actif (sinon marquer "stale", refetch au prochain focus).
  - Artefact : `frontend/src/GraphPage.jsx` (ajout listener)
  - Critère acceptation : création d'un nœud dans Exploration puis bascule vers Graphe ADG-M → le nouveau nœud apparaît sans rechargement manuel (F5).
  - Estimation : 0.5 jour
  - Dépendances croisées : ferme l'intégration décrite au §3 "Frontières avec les modules existants".

### Tranche TESTS & QA

- **TÂCHE-3-T-01** : Test rollback transaction cascade
  - Prérequis : T3-B-01, T0-T-01
  - Description : Test pytest simulant une erreur en cours de N6 (ex. monkeypatch pour lever une exception après suppression partielle des relations) → vérifier que `session.execute_write()` a bien tout annulé (nœud + relations intacts en relisant la base après l'exception).
  - Artefact : `azure-functions/fn-adgm-graph/tests/test_exploration_cascade.py`
  - Critère acceptation : après exception simulée, le nœud et ses N relations existent toujours.
  - Estimation : 1 jour
  - Dépendances croisées : T3-B-01.

- **TÂCHE-3-T-02** : Tests matrice RBAC complète
  - Prérequis : Phase 1+2+3 backend terminées
  - Description : Test paramétré pytest parcourant la matrice §8 (13 opérations × 3 rôles = 39 cas) — vérifie 200/201 attendu vs 403.
  - Artefact : `azure-functions/fn-adgm-graph/tests/test_exploration_rbac.py`
  - Critère acceptation : 39/39 cas conformes à la matrice.
  - Estimation : 1 jour
  - Dépendances croisées : dernier gate avant Phase 4 (sécurité).

- **TÂCHE-3-T-03** : E2E invalidation cross-onglets
  - Prérequis : T3-F-03
  - Description : Scénario manuel : créer un nœud dans Exploration → switch onglet Graphe ADG-M → vérifier apparition sans F5.
  - Artefact : `frontend/tests/e2e/exploration_cross_tab.md`
  - Critère acceptation : nœud visible dans Graphe ADG-M sans rechargement.
  - Estimation : 0.5 jour
  - Dépendances croisées : T3-F-03.

**Total Phase 3 : ~4 jours.**

---

## PHASE 4 — Audit Trail + erreurs/UX restantes (~3 jours)

### Tranche BACKEND

- **TÂCHE-4-B-01** : AuditLog systématique (vérification + complétion)
  - Prérequis : Phases 1-3 (chaque mutation a déjà son `CREATE (:AuditLog)` ajouté au fil de l'eau dans T1-B-03/04/05, T2-B-03/04/05, T3-B-01/02)
  - Description : Revue transversale — vérifier que les 8 opérations de mutation écrivent bien `:AuditLog` dans **la même transaction** (pas d'écriture séparée après coup), avec `payload` = `{before, after}` pour UPDATE et propriétés complètes pour CREATE/DELETE. `ipAddress` masqué (dernier octet → `.x`) via une fonction utilitaire `mask_ip(req)`.
  - Artefact : `function_app.py` (ajout `mask_ip`, revue des 8 routes)
  - Critère acceptation : pour chaque opération, une requête `MATCH (log:AuditLog {entityId: $id}) RETURN log` retourne une entrée cohérente immédiatement après l'appel.
  - Estimation : 1 jour
  - Dépendances croisées : T4-B-02.

- **TÂCHE-4-B-02** : `GET /api/exploration/audit` (ADMIN)
  - Prérequis : T4-B-01, T0-B-03
  - Description : Implémenter la requête de consultation §8 (filtres `entityId`, `userId`, `operation`, `since`, pagination). RBAC `ADMIN` uniquement.
  - Artefact : `function_app.py` (route `list_exploration_audit`)
  - Critère acceptation : ARCHITECT → 403 ; ADMIN → liste paginée triée par `timestamp DESC`.
  - Estimation : 0.5 jour
  - Dépendances croisées : T4-F-01.

### Tranche FRONTEND

- **TÂCHE-4-F-01** : Vue Audit (ADMIN-only)
  - Prérequis : T4-B-02, T0-F-01/02
  - Description : Nouvelle sous-vue "Audit" dans `ExplorationPage` (visible uniquement si rôle courant = ADMIN) — tableau `operation/entityType/entityId/userId/timestamp`, filtres basiques (operation, since).
  - Artefact : `ExplorationPage.jsx` (sous-composant `AuditListView`)
  - Critère acceptation : visible/masqué selon rôle sélectionné dans le header.
  - Estimation : 1 jour
  - Dépendances croisées : T4-B-02.

- **TÂCHE-4-F-02** : Couverture complète des cas d'erreur UX (§7)
  - Prérequis : Phases 1-3 frontend (gère déjà les cas principaux au fil de l'eau)
  - Description : Revue transversale — vérifier que chaque code d'erreur du tableau §7 a un traitement UI explicite : 403 → toast rouge + fermeture formulaire ; 404 → toast + retour liste + invalidation ; 500/503 → toast + bouton "Réessayer" ; 429 → toast avec `Retry-After` (même si rate limiting non implémenté backend, gérer le cas générique). Centraliser dans un helper `handleApiError(error, {toast, navigate})`.
  - Artefact : `frontend/src/explorationApi.js` (helper `handleApiError`), revue des composants Phase 1-3
  - Critère acceptation : test manuel — couper le réseau pendant un fetch → toast 503 + bouton Réessayer fonctionnel.
  - Estimation : 1 jour
  - Dépendances croisées : aucune (polish transversal).

### Tranche TESTS & QA

- **TÂCHE-4-T-01** : Test exhaustivité AuditLog
  - Prérequis : T4-B-01, T0-T-01
  - Description : Test pytest paramétré sur les 8 opérations de mutation — pour chacune, vérifier la présence d'une entrée `:AuditLog` avec les bons `operation`/`entityType`/`payload`.
  - Artefact : `azure-functions/fn-adgm-graph/tests/test_exploration_audit.py`
  - Critère acceptation : 8/8 opérations produisent une entrée AuditLog valide.
  - Estimation : 1 jour
  - Dépendances croisées : T4-B-01.

- **TÂCHE-4-T-02** : Revue finale + checklist de release
  - Prérequis : toutes les phases précédentes
  - Description : Exécution complète de la suite pytest (`test_exploration_*.py`) + tous les scénarios E2E (T1-T-03, T2-T-03, T3-T-03) + mise à jour `README.md`/`ARCHITECTURE.md` (nouvelle section "Module Exploration", nouveau endpoint `/api/exploration/*`, nouveau rôle `X-User-Role`).
  - Artefact : mise à jour `notebooklm-azure/README.md`, `ARCHITECTURE.md`
  - Critère acceptation : suite verte + doc à jour, jalon "Module Exploration v1 complet".
  - Estimation : 1 jour
  - Dépendances croisées : clôture du plan.

**Total Phase 4 : ~3 jours.**

---

## TIMELINE PARALLÈLE (équipe de 3 : Backend, Frontend, Tests/QA)

```
Jour       1    2    3    4    5    6    7    8    9   10   11   12   13   14   15   16   17   18
Backend  [0-B-01/02/03/04][--1-B-01..06--------][--2-B-01..05------][3-B-01/02][4-B-01/02]
Frontend [0-F-01/02/03--][--1-F-01..05--------][--2-F-01..03------][3-F-01..03][4-F-01/02]
Tests    [0-T-01--------][--1-T-01..03--------][--2-T-01..03------][3-T-01..03][4-T-01/02]
         └─ Phase 0 ─┘   └──── Phase 1 ────┘   └──── Phase 2 ────┘ └─Phase 3─┘ └─Phase 4─┘
            ~3j              ~6j                    ~5j               ~4j         ~3j

Jalons :
  J3   : Fondations prêtes (schéma, whitelist, RBAC stub, shell UI)
  J9   : MVP CRUD Nœuds (Phase 1) — démontrable
  J14  : MVP CRUD complet Nœuds+Relations (Phase 2) — jalon "intégration app existante"
  J18  : Cascade/bulk/cross-onglets (Phase 3)
  J21  : Sécurité/Audit complète (Phase 4) — release v1
```

Durée totale séquentielle si parallélisée à fond : **~21 jours** (≈ 4 semaines calendaires pour une équipe de 3, avec marge revue de code/intégration).

---

## RÉSUMÉ DES DÉPENDANCES CRITIQUES

```
T0-B-02 (whitelist ArchiMate) ──┬─→ T0-F-03 (catalogue JS) ──→ T1-F-03, T2-F-02
                                 ├─→ T1-B-03 (create node)
                                 └─→ T2-B-03 (create relation, validations)

T0-B-03 (resolve_role/RBAC) ──→ toutes les routes de mutation (T1-B-03/04/05, T2-B-03/04/05, T3-B-01/02, T4-B-02)
                              ──→ T3-T-02 (matrice RBAC complète)

T0-B-04 (routes stub) ──→ T0-F-02 (client API) ──→ tous les composants F1+

T1-B-02 (N2 détail+relations) ──→ T1-F-02 (NodeDetailView) ──→ T2-F-03 (relations dans détail)
                                ──→ T2-B-03 (vérif existence src/tgt avant création relation)

T1-B-05 (N5 safe delete) ──→ T1-F-05 (modal confirm) ──→ T3-B-01 (N6 cascade) ──→ T3-F-01 (modal cascade ADMIN)

T2-B-03 (contrat 422 ARCHIMATE_WARN) ──→ T2-F-02 (RelFormView badges) :
  ⚠ BLOQUANT — T2-F-02 ne peut finaliser l'UI de warning qu'une fois le format exact
  du body 422 (codes VAL-05/06/07/08, structure {code, message, ...}) figé par T2-B-03.
  Mitigation : T2-F-02 démarre sur un mock du contrat dès le début de Phase 2,
  branchement réel en fin de phase.

Convention "adgm:graph-changed" (posée en T1-F-03) ──→ T3-F-03 (invalidation cross-onglets GraphPage)
  ⚠ Si cette convention n'est pas respectée dans TOUTES les mutations (T1-F-03, T2-F-02/03, T3-F-01/02),
  l'invalidation cross-onglets sera incomplète. À vérifier en revue de code à chaque PR Phase 1-3.

T0-T-01 (seed Neo4j) ──→ tous les tests d'intégration (T1-T-02, T2-T-02, T3-T-01/02, T4-T-01)
```

**Risques de blocage les plus probables** :
1. **T2-B-03** (création relation + 4 règles de validation) est la tâche la plus complexe (2j) — si elle dérape, bloque T2-F-02 et T2-T-01/03. Recommandation : démarrer T2-B-03 en tout premier dans Phase 2, dédier le développeur backend le plus expérimenté.
2. **Cohérence taxonomie Python/JS** (T0-B-02/T0-F-03) — toute modification ultérieure d'un type ArchiMate doit être répercutée dans les deux fichiers ; T1-T-01 (test de cohérence) doit tourner en CI pour éviter la dérive.
3. **Discipline `adgm:graph-changed`** — convention informelle (pas de système de cache central) ; risque d'oubli sur une mutation isolée. À ajouter en checklist de revue de PR pour toute la durée du projet.
