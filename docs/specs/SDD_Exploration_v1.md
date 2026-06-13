> **OBSOLÈTE (2026-06-13)** — Le module Exploration (CRUD `:ArchiMateElement`) dépendait
> du graphe ADG-M et de la classification ArchiMate, tous deux retirés (refonte "golden
> source", scénario 3 — cf. `NOTE_devenir_ADGM_golden_source.md`). Document conservé pour
> mémoire.

# Software Design Document — Module Exploration

**Neo4j + ArchiMate 3.x CRUD Interface**  
v1.0 · Juin 2026

---

## 1. Vue d'ensemble

### Objectifs

Le module **Exploration** est le troisième onglet de l'application web ADG-M. Il fournit une interface CRUD complète, consciente du métamodèle ArchiMate 3.x, directement sur la base Neo4j sous-jacente. Son objectif est de permettre aux architectes SI de créer, lire, modifier et supprimer des éléments du graphe — nœuds et relations — depuis le navigateur, sans passer par une console Neo4j ou un outil externe.

### Périmètre du module

| Fonctionnalité | In scope | Out of scope |
|---|---|---|
| CRUD nœuds ArchiMate (7 couches) | ✅ | |
| CRUD relations ArchiMate (11 types) | ✅ | |
| Filtrage multi-critères (layer, type, aspect, tags, name) | ✅ | |
| Validation règles métier ArchiMate (warn + block) | ✅ | |
| Détail nœud avec liste de ses relations | ✅ | |
| Gestion des nœuds orphelins | ✅ | |
| Audit trail par mutation | ✅ | |
| Visualisation graphe interactive | | → Graphe ADG-M |
| Requêtes LLM / raisonnement | | → Chat |
| Import/export en masse (CSV, JSON) | | Roadmap v2 |
| Gestion utilisateurs & rôles | | → module Admin |
| Éditeur de modèle ArchiMate complet | | Hors périmètre |

### Acteurs

| Acteur | Rôle métier | Permissions CRUD |
|---|---|---|
| ROLE_VIEWER | Consultant, lecture seule | R |
| ROLE_ARCHITECT | Architecte SI — usage quotidien | C R U + Delete safe |
| ROLE_ADMIN | Administrateur de la base | C R U D + Delete cascade + AuditLog |
| Service / API interne | Intégration système | C R U D via service token |

### Frontières avec les modules existants

**Chat**  
Consomme le graphe Neo4j en lecture via RAG/context. L'Exploration peut créer des nœuds que le Chat interrogera ensuite. Aucun couplage direct : partage du client Neo4j. Pas d'invalidation de cache entre Chat et Exploration.

**Graphe ADG-M**  
Visualisation read-only du même graphe. Partage le QueryClient React Query. Les mutations de l'Exploration appellent `queryClient.invalidateQueries(['graph'])` pour maintenir la cohérence affichée.

**Exploration ●**  
Interface CRUD complète. Source de vérité pour la modification de la structure du graphe. Déclenche les invalidations de cache cross-onglets. Route `/exploration`, bundle lazy-loaded.

### Contraintes techniques

| Contrainte | Valeur |
|---|---|
| Base de données | Neo4j 5.x avec plugin APOC (apoc.create.node, apoc.create.relationship, apoc.create.uuid) |
| Authentification | JWT Bearer, signé RS256, expiration 24 h |
| Pagination | 50 nœuds / page par défaut — maximum 200 |
| Timeout requêtes | 30 s (session Neo4j) |
| Suppression cascade | ROLE_ADMIN uniquement, confirmation double obligatoire |
| Audit trail | Nœud :AuditLog créé dans la même transaction que chaque mutation |
| APOC fallback | Si APOC absent : whitelist serveur + requêtes Cypher statiques avec SET labels |

---

## 2. Requirements

### CRUD — Nœuds

| ID | Opération | Description | Priorité |
|---|---|---|---|
| N-01 | List | Lister les nœuds avec pagination, tri et filtres multi-critères (layer, elementType, aspect, name, tags, orphelins) | P0 |
| N-02 | Read | Afficher le détail complet d'un nœud : toutes ses propriétés + relations entrantes et sortantes | P0 |
| N-03 | Create | Créer un nœud avec sélection layer / elementType et saisie des propriétés standards | P0 |
| N-04 | Update | Modifier les propriétés mutables d'un nœud existant (sauf id, createdAt) | P0 |
| N-05 | Delete (safe) | Supprimer un nœud non connecté — refus 409 si relCount > 0 | P0 |
| N-06 | Delete (cascade) | Supprimer un nœud et toutes ses relations — ROLE_ADMIN uniquement, confirmation double | P1 |
| N-07 | List orphans | Lister les nœuds sans aucune relation (vue maintenance) | P1 |
| N-08 | Bulk tag | Ajouter / supprimer un tag sur une sélection de nœuds — ROLE_ARCHITECT+ | P2 |

### CRUD — Relations

| ID | Opération | Description | Priorité |
|---|---|---|---|
| R-01 | List | Lister les relations avec filtres (relationType, sourceId, targetId, layer source/cible) | P0 |
| R-02 | Read | Afficher les propriétés d'une relation et ses nœuds source/cible | P0 |
| R-03 | Create | Créer une relation entre deux nœuds existants avec sélection du type et saisie des propriétés | P0 |
| R-04 | Update | Modifier name, description, weight, accessType d'une relation existante | P0 |
| R-05 | Delete | Supprimer une relation (suppression directe, pas de cascade) | P0 |

### Filtres disponibles

| Filtre | Type | Valeurs possibles | Appliqué sur |
|---|---|---|---|
| layer | Enum multi-select | Business, Application, Technology, Strategy, Motivation, Physical, Implementation | Nœuds |
| elementType | Enum conditionnel | Types du layer sélectionné (ex: BusinessActor si layer=Business) | Nœuds |
| aspect | Enum multi-select | ActiveStructure, Behaviour, PassiveStructure | Nœuds |
| name | Texte libre | Substring case-insensitive (CONTAINS) | Nœuds + Relations |
| tags | Texte libre | Intersection — tous les tags saisis doivent être présents | Nœuds |
| hasRelations | Booléen | true = connecté / false = orphelin | Nœuds |
| relationType | Enum multi-select | Association, Aggregation, Composition, Specialization, Realization, Serving, Access, Influence, Triggering, Flow, Assignment | Relations |
| sourceId / targetId | UUID | Filtrage par nœud source ou cible précis | Relations |

### Mapping ArchiMate → Types de nœuds

**Business**  
`BusinessActor`, `BusinessRole`, `BusinessCollaboration`, `BusinessProcess`, `BusinessFunction`, `BusinessInteraction`, `BusinessEvent`, `BusinessService`, `BusinessObject`, `Contract`, `Representation`, `Product`

**Application**  
`ApplicationComponent`, `ApplicationCollaboration`, `ApplicationInterface`, `ApplicationFunction`, `ApplicationInteraction`, `ApplicationProcess`, `ApplicationEvent`, `ApplicationService`, `DataObject`

**Technology**  
`Node`, `Device`, `SystemSoftware`, `TechnologyCollaboration`, `TechnologyInterface`, `Path`, `CommunicationNetwork`, `TechnologyFunction`, `TechnologyProcess`, `TechnologyInteraction`, `TechnologyEvent`, `TechnologyService`, `Artifact`

**Strategy**  
`Resource`, `Capability`, `CourseOfAction`, `ValueStream`

**Motivation**  
`Stakeholder`, `Driver`, `Assessment`, `Goal`, `Outcome`, `Principle`, `Requirement`, `Constraint`, `Meaning`, `Value`

**Physical**  
`Equipment`, `Facility`, `DistributionNetwork`, `Material`

**Implementation**  
`WorkPackage`, `Deliverable`, `ImplementationEvent`, `Gap`, `Plateau`

### Règles de validation métier ArchiMate

| Code | Sévérité | Règle | Message utilisateur |
|---|---|---|---|
| VAL-01 | 🔴 ERROR | elementType doit appartenir au layer sélectionné | Type '{type}' invalide pour la couche '{layer}' |
| VAL-02 | 🔴 ERROR | name non vide, 1–256 caractères | Le nom est obligatoire (1 à 256 caractères) |
| VAL-03 | 🔴 ERROR | Relation Access requiert accessType ∈ {READ, WRITE, READWRITE} | accessType obligatoire pour une relation Access |
| VAL-04 | 🔴 ERROR | id UUID unique dans la base (contrôle UNIQUE constraint) | Cet identifiant est déjà utilisé |
| VAL-05 | 🟡 WARN | Assignment : source=ActiveStructure, cible=Behaviour | Assignment non conforme ArchiMate — continuer ? |
| VAL-06 | 🟡 WARN | Realization : couche cible ≥ couche source (Business > App > Tech) | Realization inter-couche inversée — continuer ? |
| VAL-07 | 🟡 WARN | Doublon relation (sourceId, targetId, relationType) | Une relation de ce type existe déjà entre ces éléments |
| VAL-08 | 🔵 INFO | Composition / Aggregation recommandée dans la même couche | Relation structurelle cross-layer détectée |

---

## 3. Architecture

### Stack front-end

| Composant | Technologie | Rôle |
|---|---|---|
| Framework UI | React 18 + TypeScript | Rendu composants, state management local |
| Data fetching / cache | TanStack Query v5 (React Query) | Fetch, cache, invalidation cross-onglets, optimistic updates |
| Formulaires | React Hook Form + Zod | Validation côté client typée, schémas partagés avec le serveur |
| Routing | React Router v6 | Tab navigation via history API — /exploration route lazy-loaded |
| Notifications | React Hot Toast | Toasts success / error / warn — réutilisation composant existant |
| Icons | Lucide React | Icônes SVG légères et cohérentes |
| Style | CSS Modules ou Tailwind | Cohérence avec l'app existante — pas de nouveau système CSS |

### Architecture en couches

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        Frontend — React / TypeScript                         │
│                                                                              │
│  ExplorationTab (route /exploration)                                         │
│  ├─ NodeListView      ← useNodes(filters, page)                             │
│  ├─ NodeDetailView    ← useNode(id) + useNodeRelations(id)                  │
│  ├─ NodeFormView      ← useMutationCreateNode / useMutationUpdateNode       │
│  ├─ RelListView       ← useRelations(filters, page)                         │
│  ├─ RelFormView       ← useMutationCreateRelation / useMutationUpdateRel    │
│  └─ OrphanListView    ← useOrphans(page)                                    │
│                                                                              │
│  Shared: QueryClient (singleton) · AuthContext (JWT) · ToastContext         │
└────────────────────────────────┬─────────────────────────────────────────────┘
                                 │ HTTPS · Bearer JWT
┌────────────────────────────────▼─────────────────────────────────────────────┐
│                 API Layer (Express / Fastify / NestJS)                        │
│                                                                               │
│  Middleware: verifyJWT → extractRole → rateLimit → auditContext              │
│                                                                               │
│  POST   /api/exploration/nodes/list         list + filtres + pagination      │
│  GET    /api/exploration/nodes/:id          détail nœud + relations          │
│  POST   /api/exploration/nodes              création nœud                   │
│  PATCH  /api/exploration/nodes/:id          mise à jour propriétés          │
│  DELETE /api/exploration/nodes/:id          suppression (safe ou cascade)    │
│  GET    /api/exploration/orphans            nœuds sans relation              │
│  GET    /api/exploration/relations          liste relations filtrée          │
│  GET    /api/exploration/relations/:id      détail relation                  │
│  POST   /api/exploration/relations          création relation                │
│  PATCH  /api/exploration/relations/:id      mise à jour relation             │
│  DELETE /api/exploration/relations/:id      suppression relation             │
│  GET    /api/exploration/audit              journal mutations (ADMIN)        │
│                                                                               │
│  explorationService.ts — encapsule le driver Neo4j + exécution Cypher        │
└────────────────────────────────┬─────────────────────────────────────────────┘
                                 │ Bolt Protocol · neo4j-driver
┌────────────────────────────────▼─────────────────────────────────────────────┐
│                         Neo4j 5.x + APOC                                      │
│                                                                               │
│  Labels    :ArchiMateElement + :<Layer> + :<ElementType>                     │
│  Relations :<RELATION_TYPE> (ex: :Serving, :Assignment)                      │
│  Indexes   UNIQUE(id) · FULLTEXT(name, description) · COMPOSITE(layer,type)  │
└───────────────────────────────────────────────────────────────────────────────┘
```

### Intégration avec l'application existante

| Point d'intégration | Mécanisme | Impact |
|---|---|---|
| QueryClient partagé | Singleton exporté depuis queryClient.ts | Mutations Exploration → invalidateQueries(['graph']) → rafraîchit Graphe ADG-M automatiquement |
| Client Neo4j | Instance unique neo4jDriver partagée | Pas de connexion supplémentaire — session par requête API |
| Auth / JWT | AuthContext.token injecté dans chaque fetch | Rôle décodé côté serveur pour RBAC |
| Notification / Toast | Composant global de l'app | Réutilisation — Exploration ne crée pas de nouveau système |
| Route onglet | `<Route path='/exploration' element={<Lazy />} />` | Lazy loading — bundle Exploration chargé au premier clic |
| Thème CSS | Variables CSS globales (--color-*) | Exploration hérite du thème de l'app |

### Risques architecturaux

#### PERF-01 — Volumétrie
Sur un graphe de +100 k nœuds, un MATCH sans filtre obligatoire entraîne un full scan malgré l'index. Imposer au moins un filtre `layer` ou `elementType` avant d'exécuter N1, ou limiter strictement à 50 résultats par défaut avec avertissement visible.

#### SCHEMA-01 — Labels dynamiques sans APOC
Sans APOC, la création de nœuds avec labels dynamiques est impossible via paramètre. Le serveur doit whitelister toutes les combinaisons layer/elementType et construire les requêtes Cypher statiquement. Documenter cette contrainte pour l'équipe DevOps.

#### INTEG-01 — Cohérence en cas de timeout cascade
La suppression cascade doit être exécutée dans une transaction Neo4j explicite. Un timeout interrompant la transaction à mi-parcours doit provoquer un rollback complet — le driver néo4j-driver gère cela via `session.executeWrite()`.

#### MAINT-01 — Migration de schéma
L'ajout de nouveaux types ArchiMate (Physical, Implementation non encore présents) ne nécessite pas de migration Neo4j — les labels sont ajoutés dynamiquement. Seule la whitelist serveur et la validation client doivent être mises à jour.

---

## 4. Modèle de données

### Stratégie de labels

Chaque nœud ArchiMate porte **trois labels cumulatifs** en Neo4j. Cette stratégie permet des requêtes efficaces à chaque niveau de granularité grâce aux index couvrant chaque label.

| Label | Rôle | Exemple |
|---|---|---|
| `:ArchiMateElement` | Label racine — unicité globale sur id, index FULLTEXT name | Tous les nœuds du graphe SI |
| `:<Layer>` | Appartenance à une couche — filtrage rapide par communauté | `:Business`, `:Application`, `:Technology`… |
| `:<ElementType>` | Type ArchiMate précis — filtrage granulaire, validation métier | `:BusinessActor`, `:DataObject`, `:Node`… |

**Exemple :** Un nœud représentant un acteur métier porte les labels `:ArchiMateElement:Business:BusinessActor`. La requête `MATCH (n:BusinessActor)` utilise directement l'index du label le plus sélectif.

### Propriétés — Nœud ArchiMateElement

| Propriété | Type Neo4j | Obligatoire | Contrainte | Description |
|---|---|---|---|---|
| id | String | ✅ | UNIQUE INDEX | UUID v4 généré par apoc.create.uuid() |
| elementType | String | ✅ | Whitelist 48 valeurs | Nom du type ArchiMate (BusinessActor, DataObject…) |
| layer | String | ✅ | Enum 7 valeurs | Business \| Application \| Technology \| Strategy \| Motivation \| Physical \| Implementation |
| aspect | String | ❌ | Enum 3 valeurs | ActiveStructure \| Behaviour \| PassiveStructure |
| name | String | ✅ | 1–256 chars, NOT NULL | Nom métier de l'élément — indexé FULLTEXT |
| description | String | ❌ | Max 4 096 chars | Description longue (Markdown accepté) |
| stereotype | String | ❌ | Texte libre | Extension custom du métamodèle (ex: «legacy») |
| tags | String[] | ❌ | Tableau, max 20 | Tags libres pour la recherche et le filtrage |
| metadata | String (JSON) | ❌ | JSON stringifié | Propriétés additionnelles clé-valeur non structurées |
| createdAt | String | ✅ | ISO 8601, immutable | Généré côté serveur au CREATE |
| updatedAt | String | ✅ | ISO 8601 | Mis à jour à chaque PATCH |

### Propriétés — Relation ArchiMate

| Propriété | Type Neo4j | Obligatoire | Contrainte | Description |
|---|---|---|---|---|
| id | String | ✅ | Recommandé UNIQUE | UUID v4 généré par apoc.create.uuid() |
| relationType | String | ✅ | Whitelist 11 valeurs | Identique au type de la relation Neo4j (type(r)) |
| accessType | String | ❌ | READ \| WRITE \| READWRITE | Obligatoire uniquement pour le type Access |
| name | String | ❌ | Max 256 chars | Label sémantique optionnel |
| description | String | ❌ | Max 4 096 chars | Justification ou description de la relation |
| weight | Float | ❌ | 0.0 – 1.0 | Force ou confiance de la relation (usage analytique) |
| createdAt | String | ✅ | ISO 8601 | Généré au CREATE |

### Schéma Neo4j — Contraintes d'unicité

```cypher
// Unicité globale sur l'identifiant de nœud
CREATE CONSTRAINT archimate_element_id_unique
  IF NOT EXISTS
  FOR (n:ArchiMateElement)
  REQUIRE n.id IS UNIQUE;

// Valeur obligatoire — name
CREATE CONSTRAINT archimate_element_name_exists
  IF NOT EXISTS
  FOR (n:ArchiMateElement)
  REQUIRE n.name IS NOT NULL;

// Unicité sur l'identifiant de relation (Neo4j 5.x)
// Note: nécessite que toutes les relations portent le même type de base
// Alternative : gérer l'unicité applicativement via MERGE sur r.id
CREATE CONSTRAINT archimate_relation_id_unique
  IF NOT EXISTS
  FOR ()-[r:Association]-()
  REQUIRE r.id IS UNIQUE;
// Répliquer pour chaque type de relation ArchiMate
```

### Schéma Neo4j — Index de performance

```cypher
// Index full-text pour la recherche par nom et description
CREATE FULLTEXT INDEX archimate_name_fulltext
  IF NOT EXISTS
  FOR (n:ArchiMateElement)
  ON EACH [n.name, n.description];

// Index composite layer + elementType (filtre le plus fréquent)
CREATE INDEX archimate_layer_type_idx
  IF NOT EXISTS
  FOR (n:ArchiMateElement)
  ON (n.layer, n.elementType);

// Index sur tags (Neo4j 5.x supporte les index sur propriétés tableaux)
CREATE INDEX archimate_tags_idx
  IF NOT EXISTS
  FOR (n:ArchiMateElement)
  ON (n.tags);

// Index chronologique pour tri et pagination
CREATE INDEX archimate_created_idx
  IF NOT EXISTS
  FOR (n:ArchiMateElement)
  ON (n.createdAt);

// Index pour les AuditLog (consultation ADMIN)
CREATE INDEX audit_entity_idx
  IF NOT EXISTS
  FOR (log:AuditLog)
  ON (log.entityId, log.timestamp);
```

### Nœud AuditLog

| Propriété | Type | Description |
|---|---|---|
| id | String (UUID) | Identifiant unique de l'entrée d'audit |
| operation | String | CREATE \| UPDATE \| DELETE \| DELETE_CASCADE |
| entityType | String | NODE \| RELATION |
| entityId | String | id de l'entité ciblée |
| userId | String | Identifiant de l'utilisateur JWT |
| userRole | String | ROLE_ARCHITECT \| ROLE_ADMIN \| ROLE_SERVICE |
| payload | String (JSON) | JSON stringify({before: {...}, after: {...}}) — diff des propriétés |
| timestamp | String | ISO 8601 |
| ipAddress | String | IP client masquée en prod (ex: 192.168.x.x) |

---

## 5. Design UI/UX

### Structure générale de l'onglet

```
┌─ Header application ─────────────────────────────────────────────────────────┐
│  ADG-M   [Chat]   [Graphe ADG-M]   [Exploration ●]                          │
├──────────────────────────────────────────────────────────────────────────────┤
│ ┌──────────────────┐  ┌────────────────────────────────────────────────────┐ │
│ │  📋 Nœuds    [●] │  │  Vue principale — contextuelle selon sélection     │ │
│ │  🔗 Relations    │  │                                                    │ │
│ │  ─────────────   │  │  (liste / formulaire / détail / confirmation)      │ │
│ │  ⚠ Orphelins    │  │                                                    │ │
│ └──────────────────┘  └────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Wireframe — Liste Nœuds

```
┌─ EXPLORATION / Nœuds ──────────────────────────────────────── [+ Nouveau nœud]
│
│  Filtres
│  ┌──────────┐  ┌──────────────────┐  ┌──────────┐  ┌─────────────────────┐
│  │ Layer  ▾ │  │ ElementType    ▾ │  │ Aspect ▾ │  │ 🔍 Rechercher...    │
│  └──────────┘  └──────────────────┘  └──────────┘  └─────────────────────┘
│  [☐ Orphelins uniquement]   Tags: [_______________]   [Effacer filtres ×]
│
│  ┌────┬───────────────────────────┬──────────────┬──────────────────┬────┬──┐
│  │ ☐  │ Nom ↑                     │ Layer        │ Type             │ R  │  │
│  ├────┼───────────────────────────┼──────────────┼──────────────────┼────┼──┤
│  │ ☐  │ Système de Paie           │ Business     │ BusinessActor    │  8 │⋯ │
│  │ ☐  │ API Gateway               │ Application  │ AppComponent     │ 12 │⋯ │
│  │ ☐  │ Postgres Prod             │ Technology   │ Node             │  4 │⋯ │
│  │ ☐  │ Stratégie Cloud 2027      │ Strategy     │ Resource         │  0 │⋯ │
│  │ ☐  │ Conformité RGPD           │ Motivation   │ Requirement      │  2 │⋯ │
│  └────┴───────────────────────────┴──────────────┴──────────────────┴────┴──┘
│
│  Sélection : 0 nœud   [Tag ▾]         ← Prec    1 / 5  (247 résultats)   Suiv →
│  Afficher : [25 ▾]  [50]  [100]
│
│  Actions contextuelles sur ⋯  →  👁 Voir détail   ✏️ Modifier   🗑 Supprimer
└──────────────────────────────────────────────────────────────────────────────────
```

### Wireframe — Formulaire Création / Édition Nœud

```
┌─ EXPLORATION / Nœuds / Nouveau nœud ──────────────────────────── [✕ Fermer]
│
│  Identification ArchiMate
│  ┌────────────────────────────────────────────────────────────────────────┐
│  │  Couche *                        Type *                               │
│  │  ┌────────────────────────┐      ┌──────────────────────────────────┐ │
│  │  │ Business             ▾ │      │ BusinessActor                  ▾ │ │
│  │  └────────────────────────┘      └──────────────────────────────────┘ │
│  │  ℹ Sélectionnez la couche en premier — le type se met à jour          │
│  └────────────────────────────────────────────────────────────────────────┘
│
│  Propriétés
│  ┌────────────────────────────────────────────────────────────────────────┐
│  │  Nom *                                                                 │
│  │  ┌──────────────────────────────────────────────────────────────────┐ │
│  │  │ Saisir le nom de l'élément (1–256 caractères)                    │ │
│  │  └──────────────────────────────────────────────────────────────────┘ │
│  │  Description (Markdown)                                               │
│  │  ┌──────────────────────────────────────────────────────────────────┐ │
│  │  │                                                                  │ │
│  │  │                                                                  │ │
│  │  └──────────────────────────────────────────────────────────────────┘ │
│  │                                                                        │
│  │  Aspect             Tags (virgule)         Stéréotype                │
│  │  ┌──────────────┐   ┌──────────────────┐   ┌────────────────────┐   │
│  │  │ ActiveStr… ▾ │   │ core, rh, legacy  │   │                    │   │
│  │  └──────────────┘   └──────────────────┘   └────────────────────┘   │
│  └────────────────────────────────────────────────────────────────────────┘
│
│  ── Validation ─────────────────────────────────────────────────────────────
│  🟡 [VAL-05 WARN] Assignment : la source devrait être ActiveStructure
│
│                             [Annuler]     [Créer le nœud  →]
└────────────────────────────────────────────────────────────────────────────────
```

### Wireframe — Détail Nœud

```
┌─ EXPLORATION / Nœuds / Système de Paie ─────── [✏️ Modifier]  [🗑 Supprimer]
│
│  🏷 BusinessActor  ·  Business  ·  ActiveStructure
│  id  550e8400-e29b-41d4-a716-446655440000
│
│  ┌────────────────────────────────────────────────────────────────────────┐
│  │  Nom           Système de Paie                                         │
│  │  Description   Système assurant le calcul et le versement des salaires  │
│  │  Tags          [RH]  [Core]  [Legacy]                                  │
│  │  Stéréotype    —                                                        │
│  │  Créé le       2026-01-15 09:32:11   │   Modifié   2026-05-20 14:07:03 │
│  └────────────────────────────────────────────────────────────────────────┘
│
│  Relations  (8)  ──────────────────────────────────── [+ Ajouter une relation]
│  ┌───────────────┬────────────────────┬──────────────────────────────┬──────┐
│  │ Direction     │ Type               │ Nœud lié                     │      │
│  ├───────────────┼────────────────────┼──────────────────────────────┼──────┤
│  │ → Sortant     │ Serving            │ API Paie (AppService)         │ Voir │
│  │ → Sortant     │ Realization        │ Process Paie (BizProcess)     │ Voir │
│  │ ← Entrant     │ Assignment         │ DBA Role (BusinessRole)       │ Voir │
│  │ ← Entrant     │ Association        │ Direction RH (BusinessActor)  │ Voir │
│  │   ··· +4 autres                                                    │      │
│  └───────────────┴────────────────────┴──────────────────────────────┴──────┘
└────────────────────────────────────────────────────────────────────────────────
```

### Wireframe — Formulaire Création Relation

```
┌─ EXPLORATION / Relations / Nouvelle relation ─────────────────── [✕ Fermer]
│
│  Nœud source *                           Nœud cible *
│  ┌──────────────────────────────────┐    ┌──────────────────────────────────┐
│  │ 🔍 Rechercher un nœud...        │    │ 🔍 Rechercher un nœud...        │
│  │  ↳ Système de Paie (BizActor)   │    │  ↳ [aucun sélectionné]          │
│  └──────────────────────────────────┘    └──────────────────────────────────┘
│
│  Type de relation *
│  ┌────────────────────────────────────────┐
│  │ Serving                              ▾ │
│  └────────────────────────────────────────┘
│
│  [Si Access]  accessType *
│  ┌────────────────────┐
│  │ READ             ▾ │   (champ affiché uniquement si type = Access)
│  └────────────────────┘
│
│  Nom (optionnel)             Poids (0.0–1.0)
│  ┌──────────────────────┐   ┌───────────┐
│  │                      │   │ 0.8       │
│  └──────────────────────┘   └───────────┘
│
│  Description (optionnel)
│  ┌──────────────────────────────────────────────────────────────────────┐
│  │                                                                      │
│  └──────────────────────────────────────────────────────────────────────┘
│
│                             [Annuler]     [Créer la relation  →]
└────────────────────────────────────────────────────────────────────────────────
```

### Wireframe — Confirmation Suppression

```
┌───────────────────────────────────────────────────────┐
│  🗑  Supprimer le nœud                                 │
├───────────────────────────────────────────────────────┤
│                                                       │
│  Vous allez supprimer :                               │
│  « Système de Paie »   BusinessActor · Business       │
│                                                       │
│  ⚠  Ce nœud possède 8 relations actives.             │
│                                                       │
│  ☐  Supprimer aussi les 8 relations (cascade)         │
│     ↳  Requiert le rôle ADMIN                         │
│     ↳  Irréversible — non restaurable en v1           │
│                                                       │
│  Cette action est définitive.                         │
│                                                       │
│   [Annuler]            [🗑  Confirmer la suppression] │
└───────────────────────────────────────────────────────┘
```

### États et transitions

| État | Description | Transitions possibles |
|---|---|---|
| IDLE | Liste nœuds chargée et affichée | → LOADING_LIST · → DETAIL · → FORM_CREATE |
| LOADING_LIST | Requête N1 / N1b en cours | → IDLE (success) · → ERROR (timeout/500) |
| DETAIL | Détail nœud affiché | → FORM_EDIT · → DELETE_CONFIRM · → IDLE (retour) |
| FORM_CREATE | Formulaire nouveau nœud | → SAVING · → IDLE (annulation) |
| FORM_EDIT | Formulaire modification nœud | → SAVING · → DETAIL (annulation) |
| SAVING | Mutation CREATE/UPDATE en cours | → DETAIL (success) · → FORM_* (erreur validation) |
| DELETE_CONFIRM | Modal confirmation suppression | → DELETING · → DETAIL (annulation) |
| DELETING | Suppression en cours | → IDLE (success + toast) · → DELETE_CONFIRM (erreur) |
| REL_FORM | Formulaire création/édition relation | → SAVING_REL · → DETAIL (annulation) |
| SAVING_REL | Mutation relation en cours | → DETAIL (success) · → REL_FORM (erreur) |
| ERROR | Erreur API non récupérable | → IDLE (dismiss) · → LOADING_LIST (retry) |

---

## 6. Requêtes Cypher

> **Note :** Toutes les requêtes utilisent des **paramètres nommés** (syntaxe `$param`) — aucune concaténation de chaîne côté serveur. Les valeurs `null` sont passées explicitement pour les filtres optionnels.

### Nœuds — READ (List)

#### N1 — Liste paginée avec filtres dynamiques

```cypher
MATCH (n:ArchiMateElement)
WHERE ($layer IS NULL OR n.layer = $layer)
  AND ($elementType IS NULL OR n.elementType = $elementType)
  AND ($aspect IS NULL OR n.aspect = $aspect)
  AND ($nameSearch IS NULL
       OR toLower(n.name) CONTAINS toLower($nameSearch))
  AND ($tagsFilter IS NULL
       OR ALL(t IN $tagsFilter WHERE t IN n.tags))
  AND (NOT $orphansOnly
       OR NOT (n)--())
WITH n, size((n)--()) AS relCount
RETURN n, relCount
ORDER BY n.layer ASC, n.name ASC
SKIP $skip LIMIT $limit
```

#### N1b — Comptage total pour la pagination

```cypher
MATCH (n:ArchiMateElement)
WHERE ($layer IS NULL OR n.layer = $layer)
  AND ($elementType IS NULL OR n.elementType = $elementType)
  AND ($nameSearch IS NULL
       OR toLower(n.name) CONTAINS toLower($nameSearch))
  AND (NOT $orphansOnly OR NOT (n)--())
RETURN count(n) AS total
```

### Nœuds — READ (Detail)

#### N2 — Détail nœud + relations entrantes et sortantes

```cypher
MATCH (n:ArchiMateElement {id: $id})
OPTIONAL MATCH (n)-[rOut]->(tgt:ArchiMateElement)
OPTIONAL MATCH (src:ArchiMateElement)-[rIn]->(n)
RETURN n,
  collect(DISTINCT {
    direction:  'OUT',
    relId:      rOut.id,
    relType:    type(rOut),
    relProps:   properties(rOut),
    linkedNode: tgt { .id, .name, .elementType, .layer }
  }) AS outgoing,
  collect(DISTINCT {
    direction:  'IN',
    relId:      rIn.id,
    relType:    type(rIn),
    relProps:   properties(rIn),
    linkedNode: src { .id, .name, .elementType, .layer }
  }) AS incoming
```

### Nœuds — CREATE

#### N3 — Création avec APOC (recommandé)

```cypher
// Labels dynamiques via apoc.create.node
// $labels = [$elementType, $layer, 'ArchiMateElement']
// ex: ['BusinessActor', 'Business', 'ArchiMateElement']
CALL apoc.create.node($labels, {
  id:          apoc.create.uuid(),
  elementType: $elementType,
  layer:       $layer,
  aspect:      $aspect,
  name:        $name,
  description: $description,
  stereotype:  $stereotype,
  tags:        $tags,
  createdAt:   toString(datetime()),
  updatedAt:   toString(datetime())
}) YIELD node
RETURN node
```

#### N3b — Fallback sans APOC (whitelist serveur obligatoire)

```cypher
// Le serveur valide elementType et layer avant d'exécuter
// et construit la requête avec des labels littéraux

CREATE (n:ArchiMateElement {
  id:          randomUUID(),
  elementType: $elementType,
  layer:       $layer,
  aspect:      $aspect,
  name:        $name,
  description: $description,
  stereotype:  $stereotype,
  tags:        $tags,
  createdAt:   toString(datetime()),
  updatedAt:   toString(datetime())
})
// Labels additionnels injectés statiquement par le serveur
// selon la valeur validée de $layer et $elementType
// ex: SET n:Business SET n:BusinessActor
RETURN n
```

### Nœuds — UPDATE

#### N4 — Mise à jour des propriétés mutables

```cypher
MATCH (n:ArchiMateElement {id: $id})
SET n.name        = COALESCE($name, n.name),
    n.description = COALESCE($description, n.description),
    n.aspect      = COALESCE($aspect, n.aspect),
    n.stereotype  = COALESCE($stereotype, n.stereotype),
    n.tags        = COALESCE($tags, n.tags),
    n.metadata    = COALESCE($metadata, n.metadata),
    n.updatedAt   = toString(datetime())
RETURN n
```

### Nœuds — DELETE (safe)

#### N5 — Suppression sécurisée — refus si relations actives

```cypher
MATCH (n:ArchiMateElement {id: $id})
WITH n, size((n)--()) AS relCount
// Bloque si le nœud a des relations — lève une exception Neo4j
CALL apoc.util.validate(
  relCount > 0,
  'NODE_HAS_RELATIONS: %d relation(s) active(s). Utilisez cascade=true (ADMIN).',
  [relCount]
)
// Audit trail dans la même transaction
CREATE (log:AuditLog {
  id:         randomUUID(),
  operation:  'DELETE',
  entityType: 'NODE',
  entityId:   $id,
  userId:     $userId,
  userRole:   $userRole,
  payload:    apoc.convert.toJson(properties(n)),
  timestamp:  toString(datetime()),
  ipAddress:  $ipAddress
})
DELETE n
RETURN true AS deleted, log.id AS auditId
```

### Nœuds — DELETE (cascade)

#### N6 — Suppression cascade — ROLE_ADMIN uniquement — transaction explicite

```cypher
// Exécuté dans session.executeWrite() — rollback automatique si erreur
MATCH (n:ArchiMateElement {id: $id})
OPTIONAL MATCH (n)-[r]-()
WITH n, collect(r) AS rels, count(r) AS relCount,
     properties(n) AS nodeProps
FOREACH (rel IN rels | DELETE rel)
CREATE (log:AuditLog {
  id:         randomUUID(),
  operation:  'DELETE_CASCADE',
  entityType: 'NODE',
  entityId:   $id,
  userId:     $userId,
  userRole:   'ADMIN',
  payload:    apoc.convert.toJson({
                nodeProps: nodeProps,
                relCount:  relCount
              }),
  timestamp:  toString(datetime()),
  ipAddress:  $ipAddress
})
DELETE n
RETURN true AS deleted, relCount, log.id AS auditId
```

### Nœuds — Liste orphelins

#### N7 — Nœuds sans aucune relation

```cypher
MATCH (n:ArchiMateElement)
WHERE NOT (n)--()
RETURN n.id        AS id,
       n.name      AS name,
       n.elementType AS elementType,
       n.layer     AS layer,
       n.createdAt AS createdAt
ORDER BY n.layer ASC, n.createdAt DESC
SKIP $skip LIMIT $limit
```

### Relations — READ (List)

#### R1 — Liste relations avec filtres

```cypher
MATCH (src:ArchiMateElement)-[r]->(tgt:ArchiMateElement)
WHERE ($relationType IS NULL OR type(r) = $relationType)
  AND ($sourceId IS NULL OR src.id = $sourceId)
  AND ($targetId IS NULL OR tgt.id = $targetId)
  AND ($sourceLayer IS NULL OR src.layer = $sourceLayer)
  AND ($targetLayer IS NULL OR tgt.layer = $targetLayer)
RETURN properties(r) AS rel,
       type(r)        AS relationType,
       src { .id, .name, .elementType, .layer } AS source,
       tgt { .id, .name, .elementType, .layer } AS target
ORDER BY r.createdAt DESC
SKIP $skip LIMIT $limit
```

### Relations — READ (Detail)

#### R2 — Détail d'une relation par son id

```cypher
MATCH (src:ArchiMateElement)-[r {id: $id}]->(tgt:ArchiMateElement)
RETURN properties(r) AS relation,
       type(r)        AS relationType,
       src { .id, .name, .elementType, .layer, .aspect } AS source,
       tgt { .id, .name, .elementType, .layer, .aspect } AS target
```

### Relations — CREATE

#### R3 — Création de relation avec APOC

```cypher
MATCH (src:ArchiMateElement {id: $sourceId})
MATCH (tgt:ArchiMateElement {id: $targetId})
// Vérification doublon avant création
OPTIONAL MATCH (src)-[existing {relationType: $relationType}]->(tgt)
// Guard applicatif : si existing != null → renvoyer VAL-07 WARN
CALL apoc.create.relationship(src, $relationType, {
  id:          apoc.create.uuid(),
  relationType: $relationType,
  accessType:  $accessType,
  name:        $name,
  description: $description,
  weight:      $weight,
  createdAt:   toString(datetime())
}, tgt) YIELD rel
RETURN properties(rel) AS relation,
       type(rel)        AS relationType,
       src { .id, .name } AS source,
       tgt { .id, .name } AS target
```

### Relations — UPDATE

#### R4 — Mise à jour propriétés d'une relation

```cypher
MATCH ()-[r {id: $id}]->()
SET r.name        = COALESCE($name, r.name),
    r.description = COALESCE($description, r.description),
    r.weight      = COALESCE($weight, r.weight),
    r.accessType  = COALESCE($accessType, r.accessType)
RETURN properties(r) AS relation, type(r) AS relationType
```

### Relations — DELETE

#### R5 — Suppression d'une relation

```cypher
MATCH ()-[r {id: $id}]->()
WITH r, properties(r) AS relProps, type(r) AS relType
CREATE (log:AuditLog {
  id:         randomUUID(),
  operation:  'DELETE',
  entityType: 'RELATION',
  entityId:   $id,
  userId:     $userId,
  userRole:   $userRole,
  payload:    apoc.convert.toJson(relProps),
  timestamp:  toString(datetime()),
  ipAddress:  $ipAddress
})
DELETE r
RETURN true AS deleted, relType, log.id AS auditId
```

### Vérification doublon relation (pré-CREATE)

#### R-CHECK — Vérification VAL-07 avant création

```cypher
MATCH (src:ArchiMateElement {id: $sourceId})
MATCH (tgt:ArchiMateElement {id: $targetId})
OPTIONAL MATCH (src)-[r]->(tgt)
  WHERE type(r) = $relationType
RETURN count(r) AS duplicateCount,
       r.id AS existingRelId
```

---

## 7. Erreurs & Validation

### Codes d'erreur API

| HTTP | Code métier | Message utilisateur | Cause |
|---|---|---|---|
| 400 | VAL_ELEMENT_TYPE | Type '{type}' invalide pour la couche '{layer}' | elementType non whitelisté pour ce layer |
| 400 | VAL_NAME_REQUIRED | Le nom est obligatoire (1 à 256 caractères) | name null, vide ou trop long |
| 400 | VAL_ACCESS_TYPE | accessType obligatoire pour une relation Access | Relation Access sans accessType |
| 400 | VAL_ACCESS_TYPE_VALUE | accessType doit être READ, WRITE ou READWRITE | Valeur d'accessType hors whitelist |
| 400 | VAL_DUPLICATE_REL | Une relation de ce type existe déjà entre ces éléments | Doublon (sourceId, targetId, relationType) |
| 400 | VAL_WEIGHT_RANGE | Le poids doit être compris entre 0.0 et 1.0 | weight hors intervalle |
| 403 | AUTH_INSUFFICIENT_ROLE | Opération non autorisée pour votre rôle | DELETE cascade sans ADMIN, ou VIEWER sur mutation |
| 404 | NODE_NOT_FOUND | Nœud introuvable | id inexistant ou supprimé |
| 404 | RELATION_NOT_FOUND | Relation introuvable | id inexistant ou supprimé |
| 409 | NODE_HAS_RELATIONS | Ce nœud possède {n} relation(s) active(s) | Delete safe avec relCount > 0 |
| 422 | ARCHIMATE_WARN | Avertissement ArchiMate — voir détails dans la réponse | VAL-05, 06, 07 ou 08 levé |
| 429 | RATE_LIMIT | Trop de requêtes — réessayez dans {s} secondes | Dépassement 100 req/min |
| 500 | NEO4J_ERROR | Erreur base de données — réessayez | Driver error, requête invalide, APOC absent |
| 503 | DB_UNAVAILABLE | Base de données temporairement indisponible | Neo4j unreachable, timeout connexion |

### Règles de validation par opération

| Opération | Règles bloquantes (ERROR) | Règles non-bloquantes (WARN/INFO) |
|---|---|---|
| CREATE Node | VAL-01, VAL-02, VAL-04 | VAL-05 si type Assignment, VAL-08 si struct cross-layer |
| UPDATE Node | VAL-02 (si name modifié) | VAL-05 si changement d'aspect |
| DELETE Node (safe) | NODE_HAS_RELATIONS si relCount > 0 | — |
| DELETE Node (cascade) | AUTH: ROLE_ADMIN requis | — |
| CREATE Relation | VAL-03 (si Access), source/target EXISTS | VAL-05, VAL-06, VAL-07, VAL-08 |
| UPDATE Relation | VAL-03 si type=Access et accessType modifié | VAL-07 si changement effectif de doublon |
| DELETE Relation | Aucune — suppression directe autorisée | — |

### Cas limites — Suppression de nœuds

**CASCADE — Perte de données irréversible en v1 :**  
La suppression cascade supprime définitivement toutes les relations. Le payload AuditLog contient le nombre de relations supprimées mais pas leur contenu complet. Envisager un **soft-delete** (propriété `deletedAt` + label `:Deleted`) pour les environnements critiques.

| Cas limite | Comportement attendu | Requête concernée |
|---|---|---|
| Nœud avec 0 relation, ARCHITECT | DELETE autorisé immédiatement — toast success | N5 (relCount = 0, guard passe) |
| Nœud avec N relations, ARCHITECT | Refus 409 NODE_HAS_RELATIONS — message indique N | N5 (apoc.util.validate bloque) |
| Nœud avec N relations, ADMIN | Modal confirmation cascade → N6 en transaction | N6 dans executeWrite() |
| Nœud avec N relations, ADMIN + timeout | Rollback transaction — nœud et relations intacts | N6 — session.executeWrite() rollback |
| Suppression concurrente | Second DELETE → 404 NODE_NOT_FOUND | MATCH retourne 0 nœud |
| Nœud orphelin récent | Identifié par N7, supprimable par N5 directement | relCount = 0 |
| Source / cible supprimée avant relation | Impossible : source et cible vérifiées au MATCH dans R3 | R3 — MATCH échoue si absent |

### Avertissements ArchiMate — Détail et vérification

| Code | Règle ArchiMate | Vérification Cypher | Action UX |
|---|---|---|---|
| VAL-05 | Assignment : source=ActiveStructure, cible=Behaviour | MATCH (s {id:$src}) RETURN s.aspect — côté client puis serveur | Badge 🟡 WARN + checkbox 'Créer quand même' — non-bloquant |
| VAL-06 | Realization : couche cible ≥ source (Business > App > Tech) | MATCH (t {id:$tgt}) RETURN t.layer — comparaison ordinale | Badge 🟡 WARN + explication couches + checkbox confirmation |
| VAL-07 | Doublon (sourceId, targetId, relationType) | R-CHECK : MATCH (s)-[r]->(t) WHERE type(r) = $rt RETURN count(r) | Badge 🟡 WARN + lien vers relation existante — non-bloquant |
| VAL-08 | Composition / Aggregation recommandée dans la même couche | src.layer = tgt.layer — comparaison locale | Badge 🔵 INFO discret sous le formulaire — non-bloquant |

### Comportement UX sur erreur

| Contexte | Comportement |
|---|---|
| Erreur de validation (400) | Champ concerné mis en erreur rouge, message inline, focus automatique |
| Erreur WARN ArchiMate | Badge jaune persistant + checkbox 'Créer quand même' débloque le bouton |
| Erreur 403 (rôle) | Toast rouge 'Opération non autorisée' + fermeture du formulaire |
| Erreur 404 (nœud disparu) | Toast rouge + retour à la liste + invalidation cache |
| Erreur 409 (NODE_HAS_RELATIONS) | Message inline dans le modal de confirmation avec N relations |
| Erreur 500 / 503 | Toast rouge 'Erreur base de données' + bouton Réessayer visible |
| État vide (aucun résultat) | Illustration + message 'Aucun nœud ne correspond à ces filtres.' + bouton Effacer |

---

## 8. Sécurité

### Authentification

| Mesure | Détail |
|---|---|
| Transport | HTTPS obligatoire (TLS 1.2+) — HTTP rejeté avec 301 redirect |
| Authentification | JWT Bearer — signé RS256, payload {sub, role, exp} |
| Expiration token | 24 h — renouvellement silencieux via refresh token |
| Session expirée | Redirect vers /login — état Exploration préservé en sessionStorage |
| CSRF | SameSite=Lax sur les cookies + vérification Origin header sur API |
| Rate limiting | 100 requêtes / minute / token — réponse 429 avec Retry-After header |
| Audit de connexion | Chaque appel API loggé (userId, endpoint, ip, timestamp) côté serveur |

### RBAC — Matrice des permissions

| Opération | ROLE_VIEWER | ROLE_ARCHITECT | ROLE_ADMIN |
|---|---|---|---|
| List Nodes (N1) | ✅ | ✅ | ✅ |
| Read Node (N2) | ✅ | ✅ | ✅ |
| Create Node (N3) | ❌ | ✅ | ✅ |
| Update Node (N4) | ❌ | ✅ | ✅ |
| Delete Node — safe (N5) | ❌ | ✅ | ✅ |
| Delete Node — cascade (N6) | ❌ | ❌ | ✅ |
| List Orphans (N7) | ❌ | ✅ | ✅ |
| Bulk tag (N8) | ❌ | ✅ | ✅ |
| List Relations (R1) | ✅ | ✅ | ✅ |
| Read Relation (R2) | ✅ | ✅ | ✅ |
| Create Relation (R3) | ❌ | ✅ | ✅ |
| Update Relation (R4) | ❌ | ✅ | ✅ |
| Delete Relation (R5) | ❌ | ✅ | ✅ |
| Consulter AuditLog | ❌ | ❌ | ✅ |

> Le rôle est extrait du payload JWT côté serveur (`req.user.role`) — jamais du corps de la requête. Tout endpoint mutation vérifie le rôle avant d'exécuter la requête Cypher.

### Sécurité de la donnée — Matrice des risques

| Risque | Mitigation | Niveau |
|---|---|---|
| Injection Cypher via paramètres libres | Paramètres nommés $param exclusivement — jamais de concaténation de chaîne | 🔴 CRITIQUE |
| Labels dynamiques non validés | Whitelist serveur exhaustive avant toute exécution Cypher avec SET label | 🔴 CRITIQUE |
| Suppression accidentelle en masse | DELETE cascade réservé ADMIN + confirmation double (checkbox + bouton) + AuditLog | 🟠 ÉLEVÉ |
| Contournement RBAC via appel direct API | Middleware vérifie JWT et rôle à chaque endpoint — pas de confiance client | 🟠 ÉLEVÉ |
| XSS via champs libres rendus en HTML | Strip HTML côté serveur avant stockage si rendu via dangerouslySetInnerHTML | 🟠 ÉLEVÉ |
| Incohérence ArchiMate silencieuse | VAL-05 à VAL-08 vérifiés côté serveur (pas uniquement côté client) | 🟡 MOYEN |
| Exposition d'identifiants séquentiels | IDs UUID opaques — pas d'int auto-incrémenté exposé dans les URLs | 🟡 MOYEN |
| Audit trail incomplet | Chaque mutation CREATE/UPDATE/DELETE écrit un :AuditLog dans la même transaction | 🟡 MOYEN |
| Données sensibles dans les logs serveur | Payload AuditLog stocké en base Neo4j chiffrée — pas dans les logs stdout | 🔵 FAIBLE |

### Audit Trail — Spécification Cypher

#### AuditLog — créé dans la même transaction que la mutation

```cypher
// Pattern systématique dans chaque mutation (N3, N4, N5, N6, R3, R4, R5)
CREATE (log:AuditLog {
  id:         randomUUID(),
  operation:  $operation,   // 'CREATE' | 'UPDATE' | 'DELETE' | 'DELETE_CASCADE'
  entityType: $entityType,  // 'NODE' | 'RELATION'
  entityId:   $entityId,
  userId:     $userId,      // extrait du JWT sub
  userRole:   $userRole,    // extrait du JWT role
  payload:    $payloadJson, // JSON.stringify({before: {...}, after: {...}})
  timestamp:  toString(datetime()),
  ipAddress:  $ipMasked     // ex: '192.168.1.x' (dernier octet masqué)
})
RETURN log.id AS auditId
```

#### Consultation de l'audit — endpoint ADMIN

```cypher
// GET /api/exploration/audit
MATCH (log:AuditLog)
WHERE ($entityId IS NULL OR log.entityId = $entityId)
  AND ($userId IS NULL OR log.userId = $userId)
  AND ($operation IS NULL OR log.operation = $operation)
  AND ($since IS NULL OR log.timestamp >= $since)
RETURN log
ORDER BY log.timestamp DESC
SKIP $skip LIMIT $limit
```

### Recommandations v2

**Soft Delete :**  
Ajouter une propriété `deletedAt` et un label `:Deleted` plutôt que de supprimer physiquement. Permet la restauration, préserve l'historique, et simplifie la piste d'audit. La suppression physique devient une opération de purge dédiée ADMIN.

**Chiffrement données sensibles :**  
Si des propriétés de nœuds contiennent des données personnelles (nom de personne réelle dans `name`), envisager le chiffrement applicatif avant stockage Neo4j et la pseudonymisation dans AuditLog.

**Contrôle d'accès au niveau du nœud :**  
En v2, ajouter une propriété `visibility` (`PUBLIC` / `RESTRICTED`) sur les nœuds pour filtrer les ROLE_VIEWER vers un sous-ensemble du graphe.

---

**Fin du SDD**
