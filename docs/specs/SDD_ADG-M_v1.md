> **OBSOLÈTE (2026-06-13)** — Le graphe ADG-M (neo4j-dev) et son pipeline d'extraction
> sont retirés (refonte "golden source", scénario 3 — cf.
> `NOTE_devenir_ADGM_golden_source.md`). Document conservé pour mémoire.

# SDD — Architecture Dependency Graph for Modernization (v1)
**Module** : ADG-M  **Priorité** : P0  **Dernière mise à jour** : 2026-06-06

---

## 1. Synthèse du module

**Rôle dans l'architecture globale** : ADG-M est la fondation du produit. Il transforme les rétro-docs ArchiMind (Markdown/JSON) en une cartographie bi-plan vivante — un plan fonctionnel (domaines métier) et un plan technique (composants legacy) — stockée dans une base de graphe Neo4j. Il enrichit cette carte de métriques décisionnelles : score de criticité, détection de SPOF, et clustering d'« appartements candidats » (communautés faiblement couplées migrables ensemble). Tous les autres modules (7RQA, ADM-M, MWP) lisent leurs données d'entrée depuis ADG-M : aucun ne fonctionne sans lui. ADG-M est donc le premier à développer et le seul prérequis bloquant absolu.

**Dépendances en entrée** :
- **ArchiMind (rétro-docs)** via Azure Blob Storage, container `retrodocs`, préfixe `incoming/` — fichiers `.md` et `.json` structurés (déclencheur Blob).
- **Azure OpenAI GPT-4o** (déploiement existant) — extraction des entités (nœuds) et relations (arcs) depuis le texte de la rétro-doc.
- **Azure AI Search** (RAG existant) — résolution des `sourceDocIds` vers le contenu intégral de la rétro-doc (lecture seule).

**Dépendances en sortie** :
- **7RQA** consomme : `GET /graph/nodes/{nodeId}` (`TechnicalNode` + métriques), `GET /graph/clusters` (batch par cluster) ; écrit en retour la 7R validée via `PATCH /graph/nodes/{nodeId}/qualification`.
- **ADM-M** consomme : `GET /graph/nodes`, `GET /graph/nodes/{nodeId}`, `GET /graph/arcs`, `GET /graph/nodes/{nodeId}/impact` (pour les 12 critères) ; écrit la 7R retenue via le même `PATCH`.
- **MWP** consomme : `GET /graph/nodes`, `GET /graph/arcs`, `GET /graph/clusters` (entrées du tri topologique et du séquençage de vagues).

**Périmètre v1 — inclus** :
- Pipeline d'ingestion Blob → GPT-4o → Neo4j avec déplacement `incoming/` → `processed/`.
- Vue bi-plan commutable (fonctionnel / technique / superposée) en React + Cytoscape.js.
- Score de criticité (in-degree pondéré) et détection SPOF (betweenness GDS + absence de redondance).
- Clustering Louvain (appartements candidats) via Neo4j GDS.
- Annotation 7R manuelle versionnée sur nœud technique.
- API REST `/graph/*` + exports JSON (clusters) et CSV (nœuds `UNQUALIFIED`).

**Périmètre v1 — exclus** (et pourquoi) :
- **Édition collaborative temps réel / verrous multi-utilisateurs** : dépriorisé — la cible v1 est un architecte solo (cf. specs, utilisateur unique). Versioning d'annotation conservé, mais pas de résolution de conflit concurrent.
- **Diff visuel inter-versions du graphe** (avant/après une ré-ingestion) : complexité UI — reporté v2 ; v1 journalise les ingestions mais n'affiche pas de delta graphique.
- **Édition manuelle d'arcs depuis l'UI** : v1 dérive les arcs uniquement de l'ingestion ArchiMind ; la correction manuelle d'arcs est reportée.
- **Suppression de nœuds depuis l'UI** : opération destructive non requise en v1 (les nœuds obsolètes sont marqués, pas supprimés).

---

## 2. Schémas de données

### 2.1 Modèle Neo4j

Neo4j est la **source de vérité du graphe**. ADG-M en est le seul propriétaire en écriture ; les autres modules écrivent exclusivement via l'API `/graph/*` (jamais en Cypher direct).

**Labels** : `FunctionalNode`, `TechnicalNode`.
**Types de relations** : `DEPENDS_ON` (arcs fonctionnels et techniques, portant les propriétés de `DependencyArc`), `REALIZED_BY` (lien bi-plan : un nœud fonctionnel est porté par un ou plusieurs nœuds techniques).

```cypher
// ===== Contraintes d'unicité =====
CREATE CONSTRAINT functional_node_id IF NOT EXISTS
FOR (n:FunctionalNode) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT technical_node_id IF NOT EXISTS
FOR (n:TechnicalNode) REQUIRE n.id IS UNIQUE;

// Unicité métier secondaire : un composant technique = un componentName unique
CREATE CONSTRAINT technical_component_name IF NOT EXISTS
FOR (n:TechnicalNode) REQUIRE n.componentName IS UNIQUE;

// Unicité d'arc (Neo4j 5.7+ — relationship uniqueness constraint).
// Fallback si non supporté par l'édition : unicité gérée applicativement à l'ingestion.
CREATE CONSTRAINT arc_id IF NOT EXISTS
FOR ()-[r:DEPENDS_ON]-() REQUIRE r.id IS UNIQUE;

// ===== Index de performance =====
CREATE INDEX functional_domain IF NOT EXISTS
FOR (n:FunctionalNode) ON (n.domain);

CREATE INDEX functional_status IF NOT EXISTS
FOR (n:FunctionalNode) ON (n.modernizationStatus);

CREATE INDEX technical_candidate7r IF NOT EXISTS
FOR (n:TechnicalNode) ON (n.candidate7R);

CREATE INDEX technical_technology IF NOT EXISTS
FOR (n:TechnicalNode) ON (n.technology);

CREATE INDEX technical_isghost IF NOT EXISTS
FOR (n:TechnicalNode) ON (n.isGhost);
```

**Exemple de nœud `TechnicalNode`** — Retail Compagnie, programme GESTION-COMMANDE :

```json
// Nœud :TechnicalNode — propriétés calculées (criticalityScore, isSPOF, betweenness, clusterId)
// écrites par les jobs d'analyse F1.3 / F1.5, pas par l'ingestion.
{
  "id": "7a3f9c12-4b8e-4d21-9f6a-2c1e5d8b0a44",
  "type": "technical",
  "componentName": "GESTION-COMMANDE",
  "technology": "COBOL",
  "linesOfCode": 18420,
  "callFrequency": "HIGH",
  "candidate7R": "UNQUALIFIED",
  "knowledgeOwner": "TACIT",
  "regulatoryTags": ["BCBS239"],
  "docCoveragePercent": 72,
  "isGhost": false,
  "sourceDocIds": ["archimind-retail-cmd-001", "archimind-retail-cmd-002"],
  "criticalityScore": 27,
  "betweenness": 0.184,
  "isSPOF": true,
  "clusterId": "cl-commandes-01",
  "createdAt": "2026-06-02T09:14:00Z",
  "updatedAt": "2026-06-05T16:40:00Z"
}
```

**Exemple de nœud `FunctionalNode`** — domaine Gestion des commandes :

```json
{
  "id": "b21e7740-3c55-4a90-8e1d-9f0c4477aa10",
  "type": "functional",
  "domain": "Gestion des commandes",
  "subdomain": "Prise de commande B2B",
  "processes": ["Saisie commande", "Contrôle de crédit", "Réservation de stock"],
  "sharedBusinessObjects": ["Commande", "LigneCommande", "Client"],
  "docCoveragePercent": 80,
  "modernizationStatus": "EXISTING",
  "sourceDocIds": ["archimind-retail-dom-cmd-001"],
  "createdAt": "2026-06-02T09:14:00Z",
  "updatedAt": "2026-06-02T09:14:00Z"
}
```

**Exemple de relation `DEPENDS_ON`** (arc technique synchrone critique) :

```json
// (GESTION-COMMANDE)-[:DEPENDS_ON]->(CONTROLE-CREDIT)
{
  "id": "f0c8a1d3-77b2-4e6c-9a01-5b3e2d9f1c88",
  "arcType": "TECHNICAL_CALL_SYNC",
  "dataFormat": "COPYBOOK-CMD01",
  "direction": "UNIDIRECTIONAL",
  "criticality": "CRITICAL"
}
```

**Requêtes d'analyse clés** (référencées en §7 Logique de calcul) :

```cypher
// F1.3 — Score de criticité = somme pondérée des arcs entrants
// Poids : CRITICAL=4, HIGH=3, MEDIUM=2, LOW=1
MATCH (src)-[r:DEPENDS_ON]->(n:TechnicalNode)
WITH n, sum(
  CASE r.criticality WHEN 'CRITICAL' THEN 4 WHEN 'HIGH' THEN 3
                     WHEN 'MEDIUM' THEN 2 ELSE 1 END) AS score
SET n.criticalityScore = score;

// F1.5 — Projection GDS puis Louvain (nécessite le plugin GDS, cf. §4 / §10)
CALL gds.graph.project(
  'moderngraph_tech', 'TechnicalNode',
  { DEPENDS_ON: { orientation: 'UNDIRECTED' } }
);
CALL gds.louvain.write('moderngraph_tech', { writeProperty: 'communityId' })
YIELD communityCount, modularity;

// F1.3 — Betweenness pour appui à la détection SPOF
CALL gds.betweenness.write('moderngraph_tech', { writeProperty: 'betweenness' })
YIELD centralityDistribution;
```

### 2.2 Schémas Azure SQL

ADG-M utilise Azure SQL uniquement pour : (a) la traçabilité des jobs d'ingestion, (b) l'historique versionné des annotations 7R manuelles (F1.4). Le graphe lui-même reste dans Neo4j. Base partagée : `modernagent_db` (instance commune à tous les modules).

```sql
-- Script de création : ADG-M — Azure SQL Database
-- À exécuter dans la base modernagent_db (Azure Data Studio ou sqlcmd)

-- 1) Traçabilité des ingestions (F1.1)
CREATE TABLE [dbo].[IngestionJob] (
    [jobId]            UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID(),
    [blobPath]         NVARCHAR(512)    NOT NULL,
    [sourceDocId]      NVARCHAR(128)    NULL,
    [status]           NVARCHAR(20)     NOT NULL DEFAULT 'PENDING', -- PENDING|RUNNING|SUCCESS|FAILED
    [nodesCreated]     INT              NOT NULL DEFAULT 0,
    [nodesUpdated]     INT              NOT NULL DEFAULT 0,
    [arcsCreated]      INT              NOT NULL DEFAULT 0,
    [ghostsDetected]   INT              NOT NULL DEFAULT 0,
    [errorMessage]     NVARCHAR(MAX)    NULL,
    [startedAt]        DATETIME2(0)     NOT NULL DEFAULT SYSUTCDATETIME(),
    [finishedAt]       DATETIME2(0)     NULL,
    CONSTRAINT [PK_IngestionJob] PRIMARY KEY CLUSTERED ([jobId] ASC)
);
CREATE INDEX [IX_IngestionJob_status]  ON [dbo].[IngestionJob] ([status]);
CREATE INDEX [IX_IngestionJob_started] ON [dbo].[IngestionJob] ([startedAt] DESC);

-- 2) Historique versionné des annotations 7R manuelles (F1.4)
-- (Les décisions issues de 7RQA/ADM-M sont historisées par ces modules ; cette table
--  ne couvre que l'annotation directe depuis le graphe ADG-M.)
CREATE TABLE [dbo].[NodeAnnotationHistory] (
    [annotationId]     UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID(),
    [nodeId]           NVARCHAR(64)     NOT NULL,   -- id Neo4j du TechnicalNode
    [previous7R]       NVARCHAR(16)     NULL,
    [new7R]            NVARCHAR(16)     NOT NULL,   -- RETIRE|RETAIN|REHOST|REPLATFORM|REPURCHASE|REFACTOR|REBUILD|UNQUALIFIED
    [justification]    NVARCHAR(MAX)    NULL,
    [source]           NVARCHAR(20)     NOT NULL,   -- MANUAL|7RQA|ADM-M
    [author]           NVARCHAR(128)    NOT NULL,   -- UPN Azure AD
    [createdAt]        DATETIME2(0)     NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT [PK_NodeAnnotationHistory] PRIMARY KEY CLUSTERED ([annotationId] ASC)
);
CREATE INDEX [IX_NodeAnnotation_node] ON [dbo].[NodeAnnotationHistory] ([nodeId], [createdAt] DESC);
```

### 2.3 Objets de transfert inter-modules (DTOs)

```typescript
// DTO : TechnicalNode — produit par ADG-M, consommé par 7RQA, ADM-M, MWP
interface TechnicalNode {
  id: string;                  // UUID v4
  type: "technical";
  componentName: string;       // ex : "GESTION-COMMANDE" (unique)
  technology: "COBOL" | "JCL" | "PL1" | "PACBASE" | "JAVA" | "DOTNET" | "OTHER";
  linesOfCode: number;         // >= 0
  callFrequency: "HIGH" | "MEDIUM" | "LOW" | "UNKNOWN";
  candidate7R: "RETIRE" | "RETAIN" | "REHOST" | "REPLATFORM"
             | "REPURCHASE" | "REFACTOR" | "REBUILD" | "UNQUALIFIED";
  knowledgeOwner: string;      // nom expert ou "TACIT"
  regulatoryTags: Array<"DORA" | "BCBS239" | "NIS2" | "AI_ACT">;
  docCoveragePercent: number;  // 0-100
  isGhost: boolean;            // true = référencé mais sans rétro-doc associée
  sourceDocIds: string[];      // réfs ArchiMind (résolvables via RAG)
  // Métriques dérivées (calculées par F1.3 / F1.5) :
  criticalityScore: number;    // in-degree pondéré
  betweenness: number;         // centralité d'intermédiarité [0-1] normalisée
  isSPOF: boolean;
  clusterId: string | null;    // appartement candidat (Louvain), null si non clusterisé
  createdAt: string;           // ISO-8601
  updatedAt: string;           // ISO-8601
}

// DTO : FunctionalNode — produit par ADG-M, consommé par ADM-M (axe différenciation)
interface FunctionalNode {
  id: string;
  type: "functional";
  domain: string;
  subdomain: string;
  processes: string[];
  sharedBusinessObjects: string[];
  docCoveragePercent: number;  // 0-100
  modernizationStatus: "EXISTING" | "IN_TRANSITION" | "TARGET";
  sourceDocIds: string[];
  createdAt: string;
  updatedAt: string;
}

// DTO : DependencyArc — produit par ADG-M, consommé par ADM-M (couplage) et MWP (tri topo)
interface DependencyArc {
  id: string;
  sourceNodeId: string;
  targetNodeId: string;
  arcType: "FUNCTIONAL" | "TECHNICAL_CALL_SYNC" | "TECHNICAL_CALL_ASYNC"
         | "TECHNICAL_BATCH" | "DATA_FLOW" | "TRANSITIONAL_COHABITATION";
  dataFormat: string | null;
  direction: "UNIDIRECTIONAL" | "BIDIRECTIONAL";
  criticality: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";
}

// DTO : Cluster (appartement candidat) — produit par ADG-M, consommé par 7RQA (batch) et MWP (vagues)
interface Cluster {
  clusterId: string;           // ex : "cl-commandes-01"
  name: string | null;         // nommé par l'architecte, null si non nommé
  nodeIds: string[];           // TechnicalNode ids membres
  cohesion: number;            // 0-1, couplage interne
  externalCoupling: number;    // 0-1, couplage externe
  isCandidateApartment: boolean; // cohesion > 0.7 ET externalCoupling < 0.3
  size: number;
}

// DTO : IngestionResult — réponse de POST /graph/ingest
interface IngestionResult {
  jobId: string;
  status: "SUCCESS" | "FAILED" | "RUNNING";
  nodesCreated: number;
  nodesUpdated: number;
  arcsCreated: number;
  ghostsDetected: number;
  processedBlobPath: string | null; // chemin après déplacement vers processed/
}
```

---

## 3. Contrats d'API REST

Base URL commune : `https://{{AZURE_FUNCTION_APP_NAME}}.azurewebsites.net/api/v1`
Authentification : `Authorization: Bearer {{TOKEN}}` (Azure AD) sur tous les endpoints.

### `GET /graph/health`

**Description** : Sonde de disponibilité (Neo4j + SQL joignables). Utilisé par la vérification d'environnement.

**Response 200** :
```json
{ "status": "ok", "neo4j": "up", "sql": "up", "version": "1.0.0" }
```

| Code | Condition | Message retourné |
|---|---|---|
| 503 | Neo4j ou SQL injoignable | `{"error": "Dépendance indisponible", "neo4j": "down", "sql": "up"}` |

---

### `POST /graph/ingest`

**Description** : Déclenche l'ingestion d'une rétro-doc ArchiMind déposée dans Blob (alternative au déclencheur Blob automatique ; utile pour rejouer un document).

**Request body** :
```json
{
  "blobPath": "string — chemin relatif dans le container retrodocs (incoming/...)",
  "force?": "boolean — réingérer même si déjà traité (défaut false)"
}
```
Exemple de valeur réaliste :
```json
{
  "blobPath": "incoming/retail-compagnie/GESTION-COMMANDE.md",
  "force": false
}
```

**Response 200** :
```json
{
  "jobId": "c4e1a9f0-2b77-4d3a-8e10-6f55ad902b11",
  "status": "SUCCESS",
  "nodesCreated": 3,
  "nodesUpdated": 1,
  "arcsCreated": 5,
  "ghostsDetected": 1,
  "processedBlobPath": "processed/retail-compagnie/GESTION-COMMANDE.md"
}
```

| Code | Condition | Message retourné |
|---|---|---|
| 400 | `blobPath` absent ou hors du préfixe `incoming/` | `{"error": "blobPath invalide : doit pointer dans incoming/"}` |
| 404 | Blob inexistant | `{"error": "Fichier introuvable dans le container retrodocs"}` |
| 409 | Déjà traité et `force=false` | `{"error": "Document déjà ingéré. Utiliser force=true pour rejouer."}` |
| 422 | GPT-4o n'a extrait aucune entité exploitable | `{"error": "Extraction infructueuse", "details": ["aucun nœud détecté"]}` |
| 500 | Erreur interne | `{"error": "Erreur interne. Réessayer ou contacter le support."}` |

---

### `GET /graph/nodes`

**Description** : Liste filtrable des nœuds (fonctionnels et/ou techniques).

**Query params** : `type` (`functional|technical`), `domain`, `candidate7R`, `status` (`UNQUALIFIED|QUALIFIED`), `clusterId`, `isGhost`, `limit` (défaut 100), `offset`.

**Response 200** (exemple, `?type=technical&candidate7R=UNQUALIFIED&limit=2`) :
```json
{
  "total": 47,
  "limit": 2,
  "offset": 0,
  "items": [
    {
      "id": "7a3f9c12-4b8e-4d21-9f6a-2c1e5d8b0a44",
      "type": "technical",
      "componentName": "GESTION-COMMANDE",
      "technology": "COBOL",
      "linesOfCode": 18420,
      "callFrequency": "HIGH",
      "candidate7R": "UNQUALIFIED",
      "knowledgeOwner": "TACIT",
      "regulatoryTags": ["BCBS239"],
      "docCoveragePercent": 72,
      "isGhost": false,
      "sourceDocIds": ["archimind-retail-cmd-001"],
      "criticalityScore": 27,
      "betweenness": 0.184,
      "isSPOF": true,
      "clusterId": "cl-commandes-01",
      "createdAt": "2026-06-02T09:14:00Z",
      "updatedAt": "2026-06-05T16:40:00Z"
    },
    {
      "id": "9d2b1e55-0a44-4c7f-b8e2-1a6f3c0d7e22",
      "type": "technical",
      "componentName": "CALCUL-REMISE",
      "technology": "COBOL",
      "linesOfCode": 6230,
      "callFrequency": "MEDIUM",
      "candidate7R": "UNQUALIFIED",
      "knowledgeOwner": "M. Dubois",
      "regulatoryTags": [],
      "docCoveragePercent": 58,
      "isGhost": false,
      "sourceDocIds": ["archimind-retail-cmd-003"],
      "criticalityScore": 11,
      "betweenness": 0.041,
      "isSPOF": false,
      "clusterId": "cl-commandes-01",
      "createdAt": "2026-06-02T09:14:00Z",
      "updatedAt": "2026-06-02T09:14:00Z"
    }
  ]
}
```

| Code | Condition | Message retourné |
|---|---|---|
| 400 | Valeur d'enum invalide (ex : `type=foo`) | `{"error": "Paramètre type invalide"}` |
| 500 | Erreur interne | `{"error": "Erreur interne. Réessayer ou contacter le support."}` |

---

### `GET /graph/nodes/{nodeId}`

**Description** : Détail complet d'un nœud, incluant métriques dérivées et arcs entrants/sortants résumés. C'est l'endpoint principal consommé par 7RQA et ADM-M.

**Response 200** (nœud technique) :
```json
{
  "node": {
    "id": "7a3f9c12-4b8e-4d21-9f6a-2c1e5d8b0a44",
    "type": "technical",
    "componentName": "GESTION-COMMANDE",
    "technology": "COBOL",
    "linesOfCode": 18420,
    "callFrequency": "HIGH",
    "candidate7R": "UNQUALIFIED",
    "knowledgeOwner": "TACIT",
    "regulatoryTags": ["BCBS239"],
    "docCoveragePercent": 72,
    "isGhost": false,
    "sourceDocIds": ["archimind-retail-cmd-001"],
    "criticalityScore": 27,
    "betweenness": 0.184,
    "isSPOF": true,
    "clusterId": "cl-commandes-01",
    "createdAt": "2026-06-02T09:14:00Z",
    "updatedAt": "2026-06-05T16:40:00Z"
  },
  "metrics": {
    "inDegree": 8,
    "outDegree": 12,
    "criticalArcsIn": 4,
    "realizesFunctionalNodes": ["b21e7740-3c55-4a90-8e1d-9f0c4477aa10"]
  },
  "incomingArcs": [
    { "id": "a1...", "sourceNodeId": "...", "arcType": "TECHNICAL_CALL_SYNC", "criticality": "CRITICAL" }
  ],
  "outgoingArcs": [
    { "id": "f0c8a1d3-77b2-4e6c-9a01-5b3e2d9f1c88", "targetNodeId": "...", "arcType": "TECHNICAL_CALL_SYNC", "criticality": "CRITICAL" }
  ]
}
```

| Code | Condition | Message retourné |
|---|---|---|
| 404 | `nodeId` inexistant | `{"error": "Nœud introuvable"}` |
| 500 | Erreur interne | `{"error": "Erreur interne. Réessayer ou contacter le support."}` |

---

### `PATCH /graph/nodes/{nodeId}/qualification`

**Description** : Met à jour le champ `candidate7R` d'un nœud technique et historise la décision. **Endpoint d'écriture unique** utilisé par l'annotation manuelle ADG-M (F1.4), par 7RQA (décision validée) et par ADM-M (positionnement validé).

**Request body** :
```json
{
  "candidate7R": "string — valeur 7R cible (hors UNQUALIFIED)",
  "justification": "string — motif de la décision",
  "source": "string — MANUAL | 7RQA | ADM-M",
  "author": "string — UPN Azure AD du décideur"
}
```
Exemple de valeur réaliste :
```json
{
  "candidate7R": "REHOST",
  "justification": "Couplage sortant élevé (12 arcs), couverture doc 72%, BCBS239 présent : trajectoire conservatrice avant refactor.",
  "source": "7RQA",
  "author": "v.gicquiau@retail-compagnie.fr"
}
```

**Response 200** :
```json
{
  "nodeId": "7a3f9c12-4b8e-4d21-9f6a-2c1e5d8b0a44",
  "candidate7R": "REHOST",
  "previous7R": "UNQUALIFIED",
  "annotationId": "e7c0...-...",
  "updatedAt": "2026-06-06T22:31:00Z"
}
```

| Code | Condition | Message retourné |
|---|---|---|
| 400 | `candidate7R` invalide ou = `UNQUALIFIED` | `{"error": "Valeur 7R invalide"}` |
| 404 | Nœud inexistant ou non technique | `{"error": "Nœud technique introuvable"}` |
| 422 | `source` ou `author` manquant | `{"error": "Champs obligatoires manquants", "details": ["author"]}` |
| 500 | Erreur interne | `{"error": "Erreur interne. Réessayer ou contacter le support."}` |

---

### `GET /graph/arcs`

**Description** : Liste filtrable des arcs. Consommé par MWP (tri topologique) et ADM-M (couplage).

**Query params** : `nodeId` (arcs incidents à ce nœud), `arcType`, `criticality`, `direction`, `limit`, `offset`.

**Response 200** :
```json
{
  "total": 312,
  "items": [
    {
      "id": "f0c8a1d3-77b2-4e6c-9a01-5b3e2d9f1c88",
      "sourceNodeId": "7a3f9c12-4b8e-4d21-9f6a-2c1e5d8b0a44",
      "targetNodeId": "3e9a...",
      "arcType": "TECHNICAL_CALL_SYNC",
      "dataFormat": "COPYBOOK-CMD01",
      "direction": "UNIDIRECTIONAL",
      "criticality": "CRITICAL"
    }
  ]
}
```

| Code | Condition | Message retourné |
|---|---|---|
| 400 | Enum de filtre invalide | `{"error": "Paramètre de filtre invalide"}` |
| 500 | Erreur interne | `{"error": "Erreur interne. Réessayer ou contacter le support."}` |

---

### `GET /graph/nodes/{nodeId}/impact`

**Description** : Pour un nœud SPOF, retourne la liste des composants downstream impactés en cas de défaillance (parcours du graphe sortant). Consommé par ADM-M (critère C5).

**Response 200** :
```json
{
  "nodeId": "7a3f9c12-4b8e-4d21-9f6a-2c1e5d8b0a44",
  "isSPOF": true,
  "downstreamImpacted": [
    { "id": "3e9a...", "componentName": "FACTURATION-CLIENT", "distance": 1, "criticality": "CRITICAL" },
    { "id": "5b1c...", "componentName": "EDITION-BORDEREAU", "distance": 2, "criticality": "HIGH" }
  ],
  "impactedCount": 14
}
```

| Code | Condition | Message retourné |
|---|---|---|
| 404 | Nœud inexistant | `{"error": "Nœud introuvable"}` |
| 500 | Erreur interne | `{"error": "Erreur interne. Réessayer ou contacter le support."}` |

---

### `GET /graph/clusters`

**Description** : Liste des appartements candidats (Louvain). Consommé par 7RQA (qualification batch) et MWP (séquençage de vagues).

**Query params** : `candidateOnly` (booléen, défaut false — ne retourner que les clusters `isCandidateApartment`).

**Response 200** :
```json
{
  "total": 6,
  "items": [
    {
      "clusterId": "cl-commandes-01",
      "name": "Appartement Commandes",
      "nodeIds": ["7a3f9c12-...", "9d2b1e55-...", "3e9a..."],
      "cohesion": 0.81,
      "externalCoupling": 0.22,
      "isCandidateApartment": true,
      "size": 9
    }
  ]
}
```

| Code | Condition | Message retourné |
|---|---|---|
| 409 | Clustering jamais exécuté (graphe non analysé) | `{"error": "Clusters non calculés. Lancer l'analyse du graphe."}` |
| 500 | Erreur interne | `{"error": "Erreur interne. Réessayer ou contacter le support."}` |

---

## 4. Infrastructure Azure

### Ressources à provisionner

| Ressource | Nom recommandé | SKU / Tier | Config clé | Coût estimé/mois |
|---|---|---|---|---|
| Neo4j (dev) | `neo4j-local` (Docker Desktop) | Community 5.x + plugin GDS (gratuit) | Conteneur sur le PC Windows, ports 7474/7687, volume persistant | ~0 € (PC) |
| Neo4j (cloud, optionnel) | `modernagent-neo4j-aci` | Image `neo4j:5-community` sur **Azure Container Instances** (1 vCPU / 2 Go) | Stockage `/data` sur Azure Files ; GDS via `NEO4J_PLUGINS` ; **service Azure first-party, sans Marketplace** | ~30-45 € si 24/7, ~0 € en on-demand |
| Azure Functions | `modernagent-adgm-dev` | Consumption (Y1) Python 3.11 | Runtime v4, App Insights activé | ~0 € (grant 1M exéc.) |
| Azure SQL Database | `modernagent-sql-dev` / base `modernagent_db` | Basic (5 DTU, 2 Go) | Pare-feu : IP dev autorisée | ~5 € |
| Azure Blob Storage | `modernagentstgdev` (réutiliser RAG si existant) | Standard LRS, Hot | Container `retrodocs` (incoming/, processed/) | ~1 € |
| Azure OpenAI | `modernagent-openai` (existant) | Déploiement GPT-4o (Std) | Pay-as-you-go par token | ~10-30 € (usage dev) |
| Azure AI Search | (existant RAG) | Free ou Basic (déjà en place) | Index rétro-docs ArchiMind | 0 € (réutilisé) |
| Azure Static Web Apps | `modernagent-web-dev` | Free | Build Vite, auth Azure AD | ~0 € |
| Application Insights | `modernagent-ai-dev` | Pay-as-you-go (5 Go gratuits) | Logs structurés (cf. §8) | ~0 € |
| Azure Key Vault | `modernagent-kv-dev` | Standard | Secrets Neo4j/SQL/OpenAI | ~0 € (opérations négligeables) |

> **Décision Neo4j (contrainte « Azure, sans Marketplace » — cf. §10 Q2)** : Neo4j s'exécute comme **image Docker Community**, qui supporte le **plugin GDS gratuit** (algorithmes Louvain et betweenness, requis par F1.3 et F1.5). Deux hébergements conformes à la contrainte : (1) **dev** = Docker Desktop sur le PC Windows ; (2) **cloud optionnel** = la même image sur **Azure Container Instances** (ou Azure Container Apps), services Azure **first-party** qui ne passent **pas** par le Marketplace (l'image est tirée de Docker Hub ou d'un Azure Container Registry). Écartés explicitement par la contrainte : Neo4j via **Azure Marketplace** (interdit) et **Neo4j AuraDB / AuraDS** (SaaS tiers Neo4j, hors périmètre « solutions Azure »). Cosmos DB Gremlin (pourtant first-party) reste écarté car dépourvu des algorithmes GDS natifs — cf. fallback §10 Q2.

### Variables d'environnement et secrets

```env
# ADG-M — Variables d'environnement
# Fichier : .env (ne jamais committer ce fichier ; en prod -> Azure Key Vault)

# --- Neo4j ---
NEO4J_URI=bolt://localhost:7687          # Dev (PC) ; cloud ACI : bolt://<aci-fqdn>:7687
NEO4J_USER=neo4j                          # Utilisateur graphe
NEO4J_PASSWORD=<secret>                    # Mot de passe Neo4j
NEO4J_DATABASE=neo4j                       # Base par défaut

# --- Azure SQL ---
SQL_CONNECTION_STRING=Driver={ODBC Driver 18 for SQL Server};Server=tcp:modernagent-sql-dev.database.windows.net,1433;Database=modernagent_db;Authentication=ActiveDirectoryDefault;Encrypt=yes;

# --- Azure Blob ---
BLOB_ACCOUNT_URL=https://modernagentstgdev.blob.core.windows.net
BLOB_CONTAINER=retrodocs                   # incoming/ et processed/

# --- Azure OpenAI ---
AZURE_OPENAI_ENDPOINT=https://modernagent-openai.openai.azure.com/
AZURE_OPENAI_API_KEY=<secret>              # ou auth managée (recommandé)
AZURE_OPENAI_DEPLOYMENT_GPT4O=gpt-4o       # Déploiement d'extraction
AZURE_OPENAI_API_VERSION=2024-10-21

# --- Azure AI Search (RAG existant) ---
AZURE_SEARCH_ENDPOINT=https://modernagent-search.search.windows.net
AZURE_SEARCH_API_KEY=<secret>
AZURE_SEARCH_INDEX=archimind-retrodocs

# --- Azure AD (validation des tokens entrants) ---
AAD_TENANT_ID=<tenant-guid>
AAD_API_CLIENT_ID=<app-registration-guid>

# --- Tuning analyse ---
LOUVAIN_COHESION_THRESHOLD=0.7
LOUVAIN_EXTERNAL_COUPLING_MAX=0.3
SPOF_BETWEENNESS_PERCENTILE=90
```

---

## 5. Configuration locale Windows

### Prérequis logiciels

| Outil | Version min. | Commande de vérification |
|---|---|---|
| Python | 3.11.x | `python --version` |
| Node.js | 20 LTS | `node --version` |
| Azure Functions Core Tools | 4.x | `func --version` |
| Docker Desktop (WSL2) | 4.x | `docker --version` |
| Azure CLI | 2.60+ | `az --version` |
| ODBC Driver for SQL Server | 18 | `Get-OdbcDriver -Name "ODBC Driver 18 for SQL Server"` |
| Git | 2.4+ | `git --version` |
| VS Code | récent | extensions : Azure Functions, Python, Docker |

### Mise en place de l'environnement

```powershell
# 1. Cloner le dépôt et se placer dans le dossier backend ADG-M
git clone <repo-url> modernization-agent
Set-Location .\modernization-agent\backend\adgm

# 2. Créer et activer l'environnement virtuel Python
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Installer les dépendances backend (azure-functions, neo4j, openai, pyodbc, azure-storage-blob)
pip install -r requirements.txt

# 4. Démarrer Neo4j Community + GDS en Docker (volume persistant)
#    Le plugin GDS est activé via NEO4J_PLUGINS.
docker run -d --name neo4j-local `
  -p 7474:7474 -p 7687:7687 `
  -e NEO4J_AUTH=neo4j/dev_password_change_me `
  -e 'NEO4J_PLUGINS=["graph-data-science"]' `
  -e NEO4J_dbms_security_procedures_unrestricted=gds.* `
  -v neo4j_data:/data `
  neo4j:5-community

# 5. Appliquer les contraintes/index Neo4j (script du §2.1) via cypher-shell
docker exec -i neo4j-local cypher-shell -u neo4j -p dev_password_change_me < .\db\neo4j_schema.cypher

# 6. Appliquer le DDL SQL (§2.2) sur modernagent_db
az login
sqlcmd -S modernagent-sql-dev.database.windows.net -d modernagent_db -G -i .\db\adgm_schema.sql

# 7. Copier le modèle d'environnement et renseigner les secrets
Copy-Item .\.env.example .\.env
# -> éditer .env avec les vraies valeurs

# 8. Frontend : installer les dépendances
Set-Location ..\..\frontend
npm install
```

### Démarrage en mode développement

```powershell
# Terminal 1 : Neo4j (si conteneur arrêté)
docker start neo4j-local

# Terminal 2 : Azure Functions (backend ADG-M)
Set-Location .\backend\adgm
.\.venv\Scripts\Activate.ps1
func start   # expose http://localhost:7071/api/v1/...

# Terminal 3 : Frontend React (Vite)
Set-Location .\frontend
npm run dev  # expose http://localhost:5173
```

### Vérification de l'environnement

```powershell
# 1. Neo4j répond (interface web)
Start-Process "http://localhost:7474"

# 2. Sonde de santé du backend : doit retourner HTTP 200 + {"status":"ok"}
Invoke-RestMethod -Uri "http://localhost:7071/api/v1/graph/health" -Method GET

# 3. Vérifier que les contraintes Neo4j existent
docker exec -i neo4j-local cypher-shell -u neo4j -p dev_password_change_me "SHOW CONSTRAINTS;"
```

---

## 6. Architecture des composants frontend

### Arbre des composants React

```
App
└── GraphPage — page principale de visualisation bi-plan
    ├── TopBar — switch de plan + actions globales
    │   ├── PlanSwitch — Fonctionnel / Technique / Superposé
    │   └── GraphActions — relancer analyse, exporter clusters/CSV
    ├── LeftPanel — navigation et filtres
    │   ├── DomainFilter — liste des domaines fonctionnels (cases à cocher)
    │   └── NodeFilters — filtres technologie / 7R / SPOF / fantôme
    ├── GraphCanvas — zone centrale interactive
    │   └── CytoscapeGraph — rendu du graphe (zoom, pan, clic nœud)
    │       └── SpofBadge — overlay "⚠ SPOF" sur les nœuds concernés
    └── RightPanel — détail du nœud sélectionné
        ├── NodeDetail — propriétés + métriques (criticité, betweenness)
        ├── ArcList — arcs entrants / sortants
        └── AnnotationPanel — sélecteur 7R + justification (F1.4)
```

### Gestion de l'état

| Données | Localisation | Type de state | Justification |
|---|---|---|---|
| Plan actif (func/tech/overlay) | `GraphPage` | `useState` | Local, pilote le rendu et le style Cytoscape |
| Nœuds + arcs chargés | `GraphDataContext` | Context + `useReducer` | Partagé entre Canvas, LeftPanel, RightPanel ; mutations à l'annotation |
| Nœud sélectionné | `GraphDataContext` | Context | Sélection lue par RightPanel et surlignée dans Canvas |
| Filtres actifs | `GraphPage` | `useReducer` | Combinaison multi-critères -> reducer plus lisible que multiples useState |
| Clusters | `GraphDataContext` | Context | Affichage des zones d'appartements + export |
| Token Azure AD | `AuthProvider` (MSAL) | Context | Injecté dans tous les appels API |

### Configuration de la librairie de visualisation

```typescript
// Configuration Cytoscape.js
// Fichier : src/config/cytoscape.config.ts

import type { Stylesheet, LayoutOptions } from "cytoscape";

// Couleurs des plans (cf. specs F1.2)
export const STATUS_COLORS = {
  EXISTING: "#9e9e9e",       // gris
  IN_TRANSITION: "#fb8c00",  // orange
  TARGET: "#43a047",         // vert
} as const;

export const R7_COLORS = {
  RETIRE: "#e53935", RETAIN: "#9e9e9e", REHOST: "#4fc3f7",
  REPLATFORM: "#1e88e5", REPURCHASE: "#8e24aa", REFACTOR: "#fb8c00",
  REBUILD: "#43a047", UNQUALIFIED: "#ffffff",
} as const;

export const graphStylesheet: Stylesheet[] = [
  { selector: "node", style: { "label": "data(label)", "font-size": 10, "text-valign": "center" } },
  { selector: "node[?isSPOF]", style: { "border-width": 3, "border-color": "#e53935" } },
  { selector: "node[?isGhost]", style: { "border-style": "dashed", "background-opacity": 0.4 } },
  { selector: "edge[criticality = 'CRITICAL']", style: { "line-color": "#e53935", "width": 3 } },
  { selector: ":selected", style: { "overlay-opacity": 0.2 } },
];

// Layout hiérarchique pour le plan technique ; concentrique pour la criticité
export const techLayout: LayoutOptions = {
  name: "breadthfirst", directed: true, spacingFactor: 1.3, animate: true,
};
export const functionalLayout: LayoutOptions = {
  name: "cose", idealEdgeLength: 100, nodeRepulsion: 8000, animate: true,
} as LayoutOptions;
```

---

## 7. Points d'intégration inter-modules

ADG-M est **fournisseur** pour tous les autres modules et **consommateur** des services Azure existants.

| Appelant | Endpoint appelé | Données envoyées | Données reçues | Déclencheur |
|---|---|---|---|---|
| ADG-M | Azure OpenAI GPT-4o (Chat Completions) | Texte rétro-doc + prompt d'extraction | JSON nœuds/arcs | Ingestion F1.1 |
| ADG-M | Azure AI Search (`/indexes/.../docs`) | `sourceDocId` | Contenu rétro-doc | Résolution doc à l'ingestion |
| ADG-M (Blob trigger) | `POST /graph/ingest` (interne) | `blobPath` | `IngestionResult` | Dépôt fichier dans `incoming/` |
| 7RQA | `GET /graph/nodes/{nodeId}` | `nodeId` | `TechnicalNode` + métriques | Qualification unitaire F2.1 |
| 7RQA | `GET /graph/clusters` | `candidateOnly` | `Cluster[]` | Qualification batch F2.4 |
| 7RQA | `PATCH /graph/nodes/{nodeId}/qualification` | 7R + justif + `source=7RQA` | nœud mis à jour | Décision validée F2.3 |
| ADM-M | `GET /graph/nodes`, `/graph/arcs`, `/graph/nodes/{id}/impact` | filtres / `nodeId` | nœuds, arcs, impact SPOF | Calcul 12 critères F3.1 |
| ADM-M | `PATCH /graph/nodes/{nodeId}/qualification` | 7R + `source=ADM-M` | nœud mis à jour | Positionnement validé F3.5 |
| MWP | `GET /graph/nodes`, `/graph/arcs`, `/graph/clusters` | filtres | graphe complet du périmètre | Génération de vagues F4.1 |

---

## 8. Gestion des erreurs

### Erreurs métier attendues

| Code d'erreur interne | Condition | Message utilisateur (FR) | Action recommandée |
|---|---|---|---|
| `ERR_ADGM_001` | Rétro-doc sans section `## Dépendances` ni `## Domaine` | « Le document ne contient pas de structure exploitable (dépendances/domaine). » | Vérifier le format ArchiMind du fichier |
| `ERR_ADGM_002` | GPT-4o renvoie un JSON non conforme au schéma | « Extraction automatique échouée sur ce document. » | Rejouer avec `force=true` ; sinon escalade |
| `ERR_ADGM_003` | Programme référencé sans rétro-doc → nœud fantôme | « N composants fantômes détectés (référencés sans documentation). » | Demander la rétro-doc manquante à ArchiMind |
| `ERR_ADGM_004` | Clustering demandé mais GDS indisponible | « Analyse de clusters indisponible : extension GDS non installée. » | Vérifier le plugin GDS Neo4j |
| `ERR_ADGM_005` | Annotation 7R sur un nœud inexistant | « Le composant ciblé n'existe plus dans le graphe. » | Rafraîchir la vue |

### Stratégie de retry pour erreurs techniques

| Type d'erreur | Retry | Délai | Backoff | Fallback |
|---|---|---|---|---|
| Timeout Neo4j | 3 tentatives | 1s, 2s, 4s | Exponentiel | Log + erreur 503 |
| Timeout Azure OpenAI | 2 tentatives | 2s, 5s | Linéaire | Log + job ingestion `FAILED` (rejouable) |
| Throttling OpenAI (429) | 3 tentatives | respect header `Retry-After` | Selon header | Log + erreur 503 |
| Azure SQL indisponible | 3 tentatives | 1s, 3s, 9s | Exponentiel | Log + erreur 503 |
| Blob introuvable au move | 2 tentatives | 1s, 2s | Linéaire | Log + conserver fichier dans `incoming/` |

### Format de log structuré

```json
{
  "timestamp": "2026-06-06T22:31:05Z",
  "level": "ERROR",
  "module": "ADG-M",
  "operation": "ingest_retrodoc",
  "correlationId": "c4e1a9f0-2b77-4d3a-8e10-6f55ad902b11",
  "message": "Extraction GPT-4o non conforme au schéma",
  "data": { "blobPath": "incoming/retail-compagnie/GESTION-COMMANDE.md", "nodesParsed": 0 },
  "error": "ERR_ADGM_002: JSON schema validation failed at $.nodes[0].technology"
}
```

---

## 9. Stratégie de test

### Tests unitaires

Framework : **pytest** (backend) / **Vitest** (frontend).

| Composant à tester | Ce qui est testé | Ce qui est mocké | Priorité |
|---|---|---|---|
| `parse_retrodoc()` | Détection sections `## Dépendances` / `## Domaine` → arcs/nœuds | Fichier rétro-doc (fixture) | P0 |
| `gpt_extract_entities()` | Mapping réponse GPT-4o → schéma nœud/arc + validation | Client Azure OpenAI (réponse figée) | P0 |
| `compute_criticality()` | Somme pondérée des arcs entrants (4/3/2/1) | Driver Neo4j (graphe in-memory) | P0 |
| `detect_spof()` | SPOF = betweenness > p90 ET pas de voisin redondant | Métriques GDS (figées) | P0 |
| `run_louvain()` | Seuils cohésion>0.7 / couplage<0.3 → `isCandidateApartment` | Projection GDS (figée) | P1 |
| `ghost_detection()` | Programme référencé sans doc → `isGhost=true` | — | P1 |
| `CytoscapeGraph` (Vitest) | Couleurs par statut/7R, badge SPOF, style fantôme | Données graphe (fixture) | P1 |
| `AnnotationPanel` (Vitest) | PATCH appelé avec payload correct + champ justif obligatoire | Client API | P0 |

### Tests d'intégration

1. **Ingestion bout-en-bout** : déposer `GESTION-COMMANDE.md` (fixture) dans `incoming/` → vérifier création de 3 nœuds + 5 arcs dans Neo4j + déplacement vers `processed/` + ligne `IngestionJob` SUCCESS.
2. **Détection SPOF réelle** : ingérer un mini-corpus où `GESTION-COMMANDE` est un point de passage unique → `isSPOF=true` et `/impact` retourne les 2 downstream attendus.
3. **Clustering** : ingérer 9 composants formant 2 communautés → `GET /graph/clusters?candidateOnly=true` retourne 2 clusters avec cohésion > 0.7.
4. **Write-back qualification** : `PATCH .../qualification` (source=7RQA) → `candidate7R` mis à jour dans Neo4j + ligne `NodeAnnotationHistory`.

### Fixture de données de test

```
tests/fixtures/adgm/
├── retrodoc_gestion_commande.md      # Rétro-doc ArchiMind avec ## Domaine, ## Dépendances, volumétrie
├── retrodoc_facturation.md           # 2e doc, dépend de GESTION-COMMANDE (crée un arc inter-doc)
├── retrodoc_with_ghost.md            # Référence un programme CALCUL-TVA sans doc associée
├── gpt_extraction_response.json      # Réponse GPT-4o figée pour le mock d'extraction
└── expected_graph.json               # État attendu du graphe après ingestion (nœuds + arcs)
```

### Critère "Done" du module

- [ ] Ingestion d'une rétro-doc réelle Retail Compagnie crée nœuds + arcs corrects dans Neo4j.
- [ ] Les 3 plans (fonctionnel, technique, superposé) s'affichent avec le bon code couleur.
- [ ] Score de criticité et badge SPOF calculés et visibles sur le graphe.
- [ ] `GET /graph/clusters` retourne au moins un appartement candidat sur le corpus de test.
- [ ] `PATCH .../qualification` met à jour Neo4j et historise en SQL.
- [ ] Tous les tests unitaires P0 passent.
- [ ] Le scénario d'intégration 1 (ingestion bout-en-bout) passe en environnement de dev.

---

## 10. Questions ouvertes et hypothèses retenues

| # | Question | Hypothèse retenue pour ce SDD | Impact si fausse |
|---|---|---|---|
| 1 | Format exact des rétro-docs ArchiMind (Markdown pur, JSON, les deux ?) | **[HYPOTHÈSE — à confirmer]** Markdown structuré avec sections `## Domaine`, `## Dépendances`, `## Objets métier`, `## Volumétrie` + JSON optionnel. Le pipeline gère les deux, le MD prime. | Si JSON strict only : le prompt GPT-4o d'extraction se simplifie (parsing direct) ; si format libre : F1.1 plus fragile, ajouter une étape de normalisation. |
| 2 | Hébergement Neo4j sous contrainte « Azure, sans Marketplace » | **Image Docker Neo4j Community + GDS** : Docker Desktop (PC) en dev, **Azure Container Instances / Container Apps** en cloud (first-party, hors Marketplace). Neo4j Marketplace et AuraDB/AuraDS écartés. | Si un graphe **managé Azure-natif** est exigé : bascule vers **Cosmos DB for Apache Gremlin** (first-party) + réimplémentation applicative de Louvain/betweenness (networkx/igraph dans une Azure Function) — surcoût dev notable, perte des algos GDS natifs. |
| 3 | Gestion des nœuds fantômes : bloquer l'ingestion ou les matérialiser ? | Matérialisés (`isGhost=true`), visibles en pointillé, jamais bloquants. | Si à exclure : retirer le style fantôme et filtrer à l'ingestion. |
| 4 | `docCoveragePercent` : fourni par ArchiMind ou calculé par ADG-M ? | **[HYPOTHÈSE — à confirmer]** Fourni par ArchiMind dans la rétro-doc ; défaut 0 si absent. | Si à calculer : ajouter une heuristique (sections documentées / sections attendues) en F1.1. |
| 5 | Multi-utilisateurs concurrents sur l'annotation 7R ? | Mono-utilisateur v1 (architecte solo), pas de verrou concurrent. | Si multi : ajouter optimistic locking (`updatedAt`) sur le PATCH. |
| 6 | Granularité Azure AD (utilisateur unique vs rôles) ? | **[HYPOTHÈSE — à confirmer]** App Registration single-tenant, un seul rôle « Architecte ». | Si RBAC requis : ajouter app roles + vérification de scope par endpoint. |
