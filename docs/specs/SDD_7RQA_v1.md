> **OBSOLÈTE (2026-06-13)** — Le scoring 7R s'appuyait sur le graphe ADG-M (neo4j-dev),
> retiré (refonte "golden source", scénario 3 — cf.
> `NOTE_devenir_ADGM_golden_source.md`). Document conservé pour mémoire.

# SDD — 7R Qualification Assistant (v1)
**Module** : 7RQA  **Priorité** : P0  **Dernière mise à jour** : 2026-06-06

---

## 1. Synthèse du module

**Rôle dans l'architecture globale** : 7RQA est le différenciateur produit. Là où ADG-M *cartographie*, 7RQA *décide* : pour un composant technique donné, il produit un **dossier de qualification** structuré recommandant la trajectoire de modernisation 7R optimale (Retire, Retain, Rehost, Replatform, Repurchase, Refactor, Rebuild), avec argumentation factuelle, alternatives écartées, niveau de confiance, hypothèses et kill criteria. Il s'appuie sur les métriques du graphe ADG-M et la rétro-doc ArchiMind (via le RAG existant), exécute une grille d'évaluation à 6 dimensions par un modèle de raisonnement, et calibre l'effort sur des références missions réelles (Arkéa, Retail Compagnie). Sa sortie est opposable en COMEX. Dans la séquence, il consomme ADG-M et alimente ADM-M (qui référence ses rapports) et MWP (qui lit les 7R validées).

**Dépendances en entrée** :
- **ADG-M** via `GET /api/v1/graph/nodes/{nodeId}` — retourne `TechnicalNode` + métriques (`inDegree`, `outDegree`, `criticalityScore`, `isSPOF`).
- **ADG-M** via `GET /api/v1/graph/clusters` — pour la qualification batch d'un appartement candidat.
- **Azure AI Search** (RAG ArchiMind) — résolution des `sourceDocIds` du nœud vers le contenu intégral de la rétro-doc.
- **Azure OpenAI o4-mini** (raisonnement) — exécution de la grille à 6 dimensions.
- **ADM-M** (optionnel, si disponible) via `GET /api/v1/matrix/position/{nodeId}` — décisions de positionnement déjà posées sur le domaine.

**Dépendances en sortie** :
- **ADG-M** via `PATCH /api/v1/graph/nodes/{nodeId}/qualification` — écrit la 7R validée (`source=7RQA`).
- **ADM-M** consomme `GET /api/v1/qualify/report/{reportId}` et `GET /api/v1/qualify/reports?nodeId=` — pour la section « Alternatives écartées » et « Lien 7RQA » de l'ADR.
- **MWP** lit indirectement les 7R validées (depuis le graphe) et peut lire la confiance via `GET /api/v1/qualify/reports`.

**Périmètre v1 — inclus** :
- Qualification unitaire (F2.1) avec rapport à structure fixe (F2.2).
- Validation / surcharge architecte versionnée (F2.3).
- Qualification batch par cluster ou portefeuille (F2.4).
- Calibration d'effort traçable depuis références missions (F2.5).
- API `/qualify/*` + stockage SQL versionné.

**Périmètre v1 — exclus** (et pourquoi) :
- **Apprentissage automatique du coefficient d'effort** (boucle de feedback réel vs estimé) : reporté — nécessite des données d'exécution post-migration non disponibles en v1. La calibration reste une table de référence figée, ajustable manuellement.
- **Recherche SaaS live sur internet** (dimension D5/SaaS) : v1 se limite au RAG catalogue interne + raisonnement GPT ; pas de scraping marché temps réel. [Cf. §10 Q3.]
- **Génération PowerPoint du dossier** : déléguée à MWP (qui porte l'export deck). 7RQA exporte en Markdown/JSON uniquement.

---

## 2. Schémas de données

### 2.1 Modèle Neo4j

7RQA **ne crée ni ne modifie aucun nœud/relation directement**. Il lit via l'API ADG-M et écrit la 7R retenue exclusivement via `PATCH /graph/nodes/{nodeId}/qualification`. Aucune contrainte/index Neo4j propre à ce module.

### 2.2 Schémas Azure SQL

7RQA est propriétaire des tables de qualification et de la table de calibration (partagée en lecture avec MWP). Base : `modernagent_db`.

```sql
-- Script de création : 7RQA — Azure SQL Database
-- À exécuter dans la base modernagent_db (après le script ADG-M)

-- 1) En-tête du dossier de qualification
CREATE TABLE [dbo].[QualificationReport] (
    [reportId]         UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID(),
    [nodeId]           NVARCHAR(64)     NOT NULL,   -- id Neo4j du TechnicalNode
    [componentName]    NVARCHAR(128)    NOT NULL,
    [recommended7R]    NVARCHAR(16)     NOT NULL,   -- recommandation agent
    [confidence]       NVARCHAR(10)     NOT NULL,   -- ELEVEE|MOYENNE|FAIBLE
    [justification]    NVARCHAR(MAX)    NOT NULL,
    [status]           NVARCHAR(12)     NOT NULL DEFAULT 'GENERATED', -- GENERATED|VALIDATED|OVERRIDDEN
    [finalDecision7R]  NVARCHAR(16)     NULL,        -- décision retenue après validation/surcharge
    [overrideReason]   NVARCHAR(MAX)    NULL,        -- obligatoire si status=OVERRIDDEN
    [calibrationRef]   NVARCHAR(64)     NULL,        -- ex : "Arkéa 2025"
    [effortMinJh]      DECIMAL(10,1)    NULL,
    [effortMedianJh]   DECIMAL(10,1)    NULL,
    [effortMaxJh]      DECIMAL(10,1)    NULL,
    [author]           NVARCHAR(128)    NOT NULL,
    [createdAt]        DATETIME2(0)     NOT NULL DEFAULT SYSUTCDATETIME(),
    [updatedAt]        DATETIME2(0)     NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT [PK_QualificationReport] PRIMARY KEY CLUSTERED ([reportId] ASC)
);
CREATE INDEX [IX_QualReport_node]   ON [dbo].[QualificationReport] ([nodeId], [createdAt] DESC);
CREATE INDEX [IX_QualReport_status] ON [dbo].[QualificationReport] ([status]);

-- 2) Évaluation par dimension (6 lignes par rapport)
CREATE TABLE [dbo].[QualificationDimension] (
    [id]               UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID(),
    [reportId]         UNIQUEIDENTIFIER NOT NULL,
    [dimension]        NVARCHAR(20)     NOT NULL,   -- COMPLEXITY|BUSINESS_VALUE|KNOWLEDGE|REGULATORY|SAAS|EFFORT
    [observedValue]    NVARCHAR(512)    NOT NULL,
    [impact]           NVARCHAR(MAX)    NOT NULL,
    [confidence]       NVARCHAR(10)     NOT NULL,   -- ELEVEE|MOYENNE|FAIBLE
    CONSTRAINT [PK_QualificationDimension] PRIMARY KEY CLUSTERED ([id] ASC),
    CONSTRAINT [FK_QualDim_Report] FOREIGN KEY ([reportId])
        REFERENCES [dbo].[QualificationReport]([reportId]) ON DELETE CASCADE
);
CREATE INDEX [IX_QualDim_report] ON [dbo].[QualificationDimension] ([reportId]);

-- 3) Alternatives 7R écartées
CREATE TABLE [dbo].[QualificationAlternative] (
    [id]               UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID(),
    [reportId]         UNIQUEIDENTIFIER NOT NULL,
    [excluded7R]       NVARCHAR(16)     NOT NULL,
    [reason]           NVARCHAR(MAX)    NOT NULL,
    CONSTRAINT [PK_QualificationAlternative] PRIMARY KEY CLUSTERED ([id] ASC),
    CONSTRAINT [FK_QualAlt_Report] FOREIGN KEY ([reportId])
        REFERENCES [dbo].[QualificationReport]([reportId]) ON DELETE CASCADE
);

-- 4) Hypothèses et kill criteria
CREATE TABLE [dbo].[QualificationAssumption] (
    [id]               UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID(),
    [reportId]         UNIQUEIDENTIFIER NOT NULL,
    [kind]             NVARCHAR(12)     NOT NULL,   -- ASSUMPTION|KILL_CRITERIA
    [text]             NVARCHAR(MAX)    NOT NULL,
    [fallback7R]       NVARCHAR(16)     NULL,        -- pour KILL_CRITERIA : 7R de repli
    CONSTRAINT [PK_QualificationAssumption] PRIMARY KEY CLUSTERED ([id] ASC),
    CONSTRAINT [FK_QualAssum_Report] FOREIGN KEY ([reportId])
        REFERENCES [dbo].[QualificationReport]([reportId]) ON DELETE CASCADE
);

-- 5) Historique des révisions (versioning F2.3)
CREATE TABLE [dbo].[QualificationRevision] (
    [revisionId]       UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID(),
    [reportId]         UNIQUEIDENTIFIER NOT NULL,
    [fromStatus]       NVARCHAR(12)     NULL,
    [toStatus]         NVARCHAR(12)     NOT NULL,
    [decision7R]       NVARCHAR(16)     NOT NULL,
    [reason]           NVARCHAR(MAX)    NULL,
    [author]           NVARCHAR(128)    NOT NULL,
    [createdAt]        DATETIME2(0)     NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT [PK_QualificationRevision] PRIMARY KEY CLUSTERED ([revisionId] ASC),
    CONSTRAINT [FK_QualRev_Report] FOREIGN KEY ([reportId])
        REFERENCES [dbo].[QualificationReport]([reportId]) ON DELETE CASCADE
);
CREATE INDEX [IX_QualRev_report] ON [dbo].[QualificationRevision] ([reportId], [createdAt] DESC);

-- 6) Table de calibration d'effort (F2.5) — lue aussi par MWP (F4.3)
CREATE TABLE [dbo].[EffortCalibration] (
    [calibrationId]    UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID(),
    [reference]        NVARCHAR(64)     NOT NULL,   -- ex : "Arkéa 2025", "Retail Compagnie 2024"
    [technology]       NVARCHAR(16)     NOT NULL,   -- COBOL|PL1|JAVA|...
    [trajectory7R]     NVARCHAR(16)     NOT NULL,   -- REHOST|REFACTOR|...
    [jhPerKlocMin]     DECIMAL(8,2)     NOT NULL,   -- jours-homme par millier de lignes
    [jhPerKlocMedian]  DECIMAL(8,2)     NOT NULL,
    [jhPerKlocMax]     DECIMAL(8,2)     NOT NULL,
    [qaOverheadPct]    INT              NOT NULL DEFAULT 0, -- surcoût QA (Arkéa)
    [isActive]         BIT              NOT NULL DEFAULT 1,
    [updatedAt]        DATETIME2(0)     NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT [PK_EffortCalibration] PRIMARY KEY CLUSTERED ([calibrationId] ASC)
);
CREATE INDEX [IX_EffortCal_lookup] ON [dbo].[EffortCalibration] ([technology], [trajectory7R], [isActive]);

-- Jeu de calibration initial (valeurs indicatives — à raffiner avec données réelles, cf. §10 Q4)
INSERT INTO [dbo].[EffortCalibration] (reference, technology, trajectory7R, jhPerKlocMin, jhPerKlocMedian, jhPerKlocMax, qaOverheadPct) VALUES
 ('Retail Compagnie 2024','COBOL','REHOST',     0.50, 0.90, 1.50, 0),
 ('Retail Compagnie 2024','COBOL','REPLATFORM', 1.50, 2.50, 4.00, 0),
 ('Retail Compagnie 2024','COBOL','REFACTOR',   3.00, 5.00, 9.00, 0),
 ('Retail Compagnie 2024','COBOL','REBUILD',    6.00, 9.00,15.00, 0),
 ('Retail Compagnie 2024','COBOL','REPURCHASE', 2.00, 4.00, 7.00, 0),
 ('Retail Compagnie 2024','COBOL','RETIRE',     0.20, 0.50, 1.00, 0),
 ('Arkéa 2025','COBOL','REFACTOR',              3.50, 5.50, 9.50,30),
 ('Arkéa 2025','COBOL','REBUILD',               6.50,10.00,16.00,30);
```

### 2.3 Objets de transfert inter-modules (DTOs)

```typescript
// DTO : QualificationReport — produit par 7RQA, consommé par ADM-M et le frontend
interface QualificationReport {
  reportId: string;            // UUID v4
  nodeId: string;              // TechnicalNode ADG-M
  componentName: string;       // ex : "GESTION-COMMANDE"
  recommended7R: SevenR;       // recommandation agent
  confidence: "ELEVEE" | "MOYENNE" | "FAIBLE";
  justification: string;       // 3-5 phrases factuelles
  status: "GENERATED" | "VALIDATED" | "OVERRIDDEN";
  finalDecision7R: SevenR | null;
  overrideReason: string | null;
  calibrationRef: string | null; // ex : "Arkéa 2025"
  effort: EffortEstimate;
  dimensions: QualificationDimensionResult[]; // 6 entrées
  excludedAlternatives: Array<{ excluded7R: SevenR; reason: string }>;
  assumptions: string[];
  killCriteria: Array<{ condition: string; fallback7R: SevenR }>;
  author: string;
  createdAt: string;
  updatedAt: string;
}

type SevenR = "RETIRE" | "RETAIN" | "REHOST" | "REPLATFORM"
            | "REPURCHASE" | "REFACTOR" | "REBUILD";

interface QualificationDimensionResult {
  dimension: "COMPLEXITY" | "BUSINESS_VALUE" | "KNOWLEDGE"
           | "REGULATORY" | "SAAS" | "EFFORT";
  observedValue: string;       // ex : "18 420 lignes, 12 arcs sortants"
  impact: string;              // effet sur la décision
  confidence: "ELEVEE" | "MOYENNE" | "FAIBLE";
}

interface EffortEstimate {
  minJh: number;               // jours-homme
  medianJh: number;
  maxJh: number;
  confidenceIntervalPct: number; // ex : 70
  calibrationRef: string;      // traçabilité (opposabilité COMEX)
}

// DTO : BatchQualificationResult — réponse de POST /qualify/batch
interface BatchQualificationResult {
  scope: { type: "cluster" | "nodeList"; id: string | null; count: number };
  distribution: Record<SevenR, number>;   // distribution des recommandations
  lowConfidenceNodeIds: string[];          // FAIBLE -> investigation humaine prioritaire
  reports: Array<{ nodeId: string; reportId: string; recommended7R: SevenR; confidence: string }>;
}
```

---

## 3. Contrats d'API REST

Base URL : `https://{{AZURE_FUNCTION_APP_NAME}}.azurewebsites.net/api/v1`
Authentification : `Authorization: Bearer {{TOKEN}}`.

### `POST /qualify/single/{nodeId}`

**Description** : Génère le dossier de qualification 7R d'un composant technique (charge nœud ADG-M + rétro-doc RAG, exécute la grille à 6 dimensions, calcule l'effort, persiste).

**Request body** :
```json
{
  "calibrationRef?": "string — référence de calibration à utiliser (défaut : auto par techno)",
  "author": "string — UPN de l'architecte demandeur"
}
```
Exemple de valeur réaliste :
```json
{
  "calibrationRef": "Arkéa 2025",
  "author": "v.gicquiau@retail-compagnie.fr"
}
```

**Response 200** :
```json
{
  "reportId": "5f2c8a10-9b44-4e07-8c1d-77a0f3e6b201",
  "nodeId": "7a3f9c12-4b8e-4d21-9f6a-2c1e5d8b0a44",
  "componentName": "GESTION-COMMANDE",
  "recommended7R": "REHOST",
  "confidence": "MOYENNE",
  "justification": "Couplage sortant élevé (12 arcs), couverture documentaire 72% et présence du tag BCBS239 orientent vers une trajectoire conservatrice : un Rehost stabilise le composant avant tout refactor profond, sans risque réglementaire immédiat.",
  "status": "GENERATED",
  "finalDecision7R": null,
  "overrideReason": null,
  "calibrationRef": "Arkéa 2025",
  "effort": { "minJh": 9.2, "medianJh": 16.6, "maxJh": 27.6, "confidenceIntervalPct": 70, "calibrationRef": "Arkéa 2025" },
  "dimensions": [
    { "dimension": "COMPLEXITY", "observedValue": "18 420 lignes, 12 arcs sortants", "impact": "Couplage modéré : refactor coûteux mais non bloquant", "confidence": "ELEVEE" },
    { "dimension": "BUSINESS_VALUE", "observedValue": "Domaine Gestion des commandes, objets partagés Commande/Client", "impact": "Composant cœur métier : exclut Retire et Repurchase", "confidence": "ELEVEE" },
    { "dimension": "KNOWLEDGE", "observedValue": "72% couverture, propriétaire : TACIT", "impact": "Connaissance partiellement tacite : favorise trajectoire conservatrice", "confidence": "MOYENNE" },
    { "dimension": "REGULATORY", "observedValue": "BCBS239", "impact": "Exclut Rebuild sans plan de continuité", "confidence": "ELEVEE" },
    { "dimension": "SAAS", "observedValue": "Aucun équivalent SaaS mature identifié", "impact": "Repurchase non pertinent", "confidence": "FAIBLE" },
    { "dimension": "EFFORT", "observedValue": "16,6 j·h médian (Rehost)", "impact": "Effort maîtrisable sur une vague", "confidence": "MOYENNE" }
  ],
  "excludedAlternatives": [
    { "excluded7R": "REBUILD", "reason": "Tag BCBS239 sans plan de continuité documenté" },
    { "excluded7R": "RETIRE", "reason": "Composant cœur métier porteur du processus de prise de commande" },
    { "excluded7R": "REPURCHASE", "reason": "Pas d'équivalent SaaS mature sur les règles de gestion spécifiques" }
  ],
  "assumptions": [
    "La volumétrie transactionnelle reste stable sur la période de migration",
    "La couverture documentaire de 72% est représentative de la logique métier réelle"
  ],
  "killCriteria": [
    { "condition": "Si la couverture documentaire réelle s'avère < 40% après audit", "fallback7R": "RETAIN" }
  ],
  "author": "v.gicquiau@retail-compagnie.fr",
  "createdAt": "2026-06-06T22:40:00Z",
  "updatedAt": "2026-06-06T22:40:00Z"
}
```

| Code | Condition | Message retourné |
|---|---|---|
| 404 | `nodeId` inexistant dans ADG-M | `{"error": "Composant introuvable dans le graphe"}` |
| 422 | Rétro-doc introuvable via RAG (aucun `sourceDocId` résolu) | `{"error": "Rétro-doc indisponible : qualification dégradée impossible", "details": ["sourceDocIds non résolus"]}` |
| 502 | Azure OpenAI o4-mini indisponible après retries | `{"error": "Service de raisonnement indisponible. Réessayer."}` |
| 500 | Erreur interne | `{"error": "Erreur interne. Réessayer ou contacter le support."}` |

---

### `POST /qualify/batch`

**Description** : Qualifie en lot tous les nœuds `UNQUALIFIED` d'un cluster ADG-M ou d'une liste de nœuds (F2.4). Traitement asynchrone si le périmètre est large.

**Request body** :
```json
{
  "clusterId?": "string — cluster ADG-M à qualifier",
  "nodeIds?": "string[] — alternative : liste explicite de nœuds",
  "calibrationRef?": "string",
  "author": "string"
}
```
Exemple de valeur réaliste :
```json
{
  "clusterId": "cl-commandes-01",
  "author": "v.gicquiau@retail-compagnie.fr"
}
```

**Response 200** :
```json
{
  "scope": { "type": "cluster", "id": "cl-commandes-01", "count": 9 },
  "distribution": { "RETIRE": 1, "RETAIN": 0, "REHOST": 4, "REPLATFORM": 2, "REPURCHASE": 0, "REFACTOR": 2, "REBUILD": 0 },
  "lowConfidenceNodeIds": ["9d2b1e55-0a44-4c7f-b8e2-1a6f3c0d7e22"],
  "reports": [
    { "nodeId": "7a3f9c12-4b8e-4d21-9f6a-2c1e5d8b0a44", "reportId": "5f2c8a10-...", "recommended7R": "REHOST", "confidence": "MOYENNE" },
    { "nodeId": "9d2b1e55-0a44-4c7f-b8e2-1a6f3c0d7e22", "reportId": "6a1b...", "recommended7R": "REFACTOR", "confidence": "FAIBLE" }
  ]
}
```

| Code | Condition | Message retourné |
|---|---|---|
| 400 | Ni `clusterId` ni `nodeIds` fourni | `{"error": "Fournir clusterId ou nodeIds"}` |
| 404 | Cluster inexistant | `{"error": "Cluster introuvable"}` |
| 207 | Succès partiel (certains nœuds en erreur) | `{"error": "Qualification partielle", "details": [{"nodeId": "...", "error": "ERR_7RQA_002"}]}` |
| 500 | Erreur interne | `{"error": "Erreur interne. Réessayer ou contacter le support."}` |

---

### `GET /qualify/report/{reportId}`

**Description** : Retourne un dossier de qualification complet (objet `QualificationReport`). Consommé par ADM-M (alternatives écartées, lien ADR).

**Response 200** : objet `QualificationReport` complet (cf. exemple `POST /qualify/single`).

| Code | Condition | Message retourné |
|---|---|---|
| 404 | `reportId` inexistant | `{"error": "Rapport introuvable"}` |
| 500 | Erreur interne | `{"error": "Erreur interne. Réessayer ou contacter le support."}` |

---

### `GET /qualify/reports`

**Description** : Liste filtrable des rapports (backlog de qualification, tableau de synthèse portefeuille).

**Query params** : `nodeId`, `status`, `confidence`, `recommended7R`, `clusterId`, `limit`, `offset`.

**Response 200** :
```json
{
  "total": 47,
  "items": [
    { "reportId": "5f2c8a10-...", "nodeId": "7a3f9c12-...", "componentName": "GESTION-COMMANDE", "recommended7R": "REHOST", "confidence": "MOYENNE", "status": "GENERATED", "createdAt": "2026-06-06T22:40:00Z" }
  ]
}
```

| Code | Condition | Message retourné |
|---|---|---|
| 400 | Enum de filtre invalide | `{"error": "Paramètre de filtre invalide"}` |
| 500 | Erreur interne | `{"error": "Erreur interne. Réessayer ou contacter le support."}` |

---

### `POST /qualify/report/{reportId}/decision`

**Description** : Valide ou surcharge la recommandation (F2.3). Sur succès, propage la 7R retenue vers ADG-M via `PATCH /graph/nodes/{nodeId}/qualification` et historise la révision.

**Request body** :
```json
{
  "action": "string — VALIDATE | OVERRIDE",
  "decision7R": "string — requis si OVERRIDE (la 7R imposée par l'architecte)",
  "overrideReason": "string — obligatoire si OVERRIDE",
  "author": "string — UPN"
}
```
Exemple de valeur réaliste (surcharge) :
```json
{
  "action": "OVERRIDE",
  "decision7R": "REFACTOR",
  "overrideReason": "Décision COMEX : différenciation métier jugée suffisante pour justifier un refactor malgré la couverture doc partielle.",
  "author": "v.gicquiau@retail-compagnie.fr"
}
```

**Response 200** :
```json
{
  "reportId": "5f2c8a10-9b44-4e07-8c1d-77a0f3e6b201",
  "status": "OVERRIDDEN",
  "finalDecision7R": "REFACTOR",
  "graphUpdate": { "nodeId": "7a3f9c12-...", "candidate7R": "REFACTOR", "annotationId": "e7c0..." },
  "revisionId": "aa01...",
  "updatedAt": "2026-06-06T22:55:00Z"
}
```

| Code | Condition | Message retourné |
|---|---|---|
| 400 | `action` invalide | `{"error": "Action invalide : VALIDATE ou OVERRIDE"}` |
| 422 | `OVERRIDE` sans `decision7R` ou sans `overrideReason` | `{"error": "Surcharge incomplète", "details": ["overrideReason obligatoire"]}` |
| 404 | Rapport inexistant | `{"error": "Rapport introuvable"}` |
| 502 | Écriture ADG-M (PATCH) échouée après retries | `{"error": "Décision enregistrée mais propagation au graphe échouée. Réessayer la synchronisation."}` |
| 500 | Erreur interne | `{"error": "Erreur interne. Réessayer ou contacter le support."}` |

---

## 4. Infrastructure Azure

### Ressources à provisionner

| Ressource | Nom recommandé | SKU / Tier | Config clé | Coût estimé/mois |
|---|---|---|---|---|
| Azure Functions | `modernagent-7rqa-dev` | Consumption (Y1) Python 3.11 | Semantic Kernel, runtime v4 | ~0 € (grant 1M exéc.) |
| Azure SQL Database | `modernagent-sql-dev` / `modernagent_db` | Basic (partagé ADG-M) | Tables qualification + calibration | 0 € (déjà compté) |
| Azure OpenAI | `modernagent-openai` (existant) | Déploiement **o4-mini** (reasoning) | Pay-as-you-go par token | ~15-40 € (raisonnement plus coûteux) |
| Azure OpenAI | `modernagent-openai` (existant) | Déploiement GPT-4o (recherche SaaS D5) | Pay-as-you-go | inclus ci-dessus |
| Azure AI Search | (RAG existant) | Free/Basic | Index ArchiMind (lecture) | 0 € (réutilisé) |
| Application Insights | `modernagent-ai-dev` (partagé) | Pay-as-you-go (5 Go gratuits) | Traces de pipeline SK | ~0 € |

> **[HYPOTHÈSE — à confirmer]** Le déploiement Azure OpenAI `o4-mini` (modèle de raisonnement) est disponible dans la région du tenant. Si indisponible, repli sur `o3-mini` ou GPT-4o avec prompt « chain-of-thought » structuré (cf. §10 Q1).

### Variables d'environnement et secrets

```env
# 7RQA — Variables d'environnement
# Fichier : .env (ne jamais committer ; en prod -> Azure Key Vault)

# --- Intégration ADG-M ---
ADGM_API_BASE_URL=http://localhost:7071/api/v1     # dev ; prod -> https://modernagent-adgm-dev.azurewebsites.net/api/v1

# --- Azure SQL (partagé) ---
SQL_CONNECTION_STRING=Driver={ODBC Driver 18 for SQL Server};Server=tcp:modernagent-sql-dev.database.windows.net,1433;Database=modernagent_db;Authentication=ActiveDirectoryDefault;Encrypt=yes;

# --- Azure OpenAI (raisonnement) ---
AZURE_OPENAI_ENDPOINT=https://modernagent-openai.openai.azure.com/
AZURE_OPENAI_API_KEY=<secret>
AZURE_OPENAI_DEPLOYMENT_REASONING=o4-mini          # grille 6 dimensions
AZURE_OPENAI_DEPLOYMENT_GPT4O=gpt-4o               # recherche SaaS (D5)
AZURE_OPENAI_API_VERSION=2024-10-21

# --- Azure AI Search (RAG ArchiMind) ---
AZURE_SEARCH_ENDPOINT=https://modernagent-search.search.windows.net
AZURE_SEARCH_API_KEY=<secret>
AZURE_SEARCH_INDEX=archimind-retrodocs

# --- Azure AD ---
AAD_TENANT_ID=<tenant-guid>
AAD_API_CLIENT_ID=<app-registration-guid>

# --- Tuning qualification ---
KNOWLEDGE_COVERAGE_CONSERVATIVE_THRESHOLD=40       # < 40% -> trajectoire conservatrice
COMPLEXITY_REHOST_OUTDEGREE_THRESHOLD=500          # > 500 arcs sortants -> Rehost avant Refactor
DEFAULT_CONFIDENCE_INTERVAL_PCT=70
```

---

## 5. Configuration locale Windows

### Prérequis logiciels

| Outil | Version min. | Commande de vérification |
|---|---|---|
| Python | 3.11.x | `python --version` |
| Azure Functions Core Tools | 4.x | `func --version` |
| ODBC Driver for SQL Server | 18 | `Get-OdbcDriver -Name "ODBC Driver 18 for SQL Server"` |
| Azure CLI | 2.60+ | `az --version` |
| Node.js (frontend) | 20 LTS | `node --version` |
| Semantic Kernel (pip) | 1.x | `pip show semantic-kernel` |

> **Prérequis bloquant** : ADG-M doit être démarré et accessible (`ADGM_API_BASE_URL`) ; 7RQA n'a pas de base de données propre en écriture sur le graphe.

### Mise en place de l'environnement

```powershell
# 1. Se placer dans le backend 7RQA
Set-Location .\modernization-agent\backend\sevenrqa

# 2. Environnement virtuel + dépendances (semantic-kernel, openai, pyodbc, httpx, azure-search-documents)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 3. Appliquer le DDL SQL 7RQA sur modernagent_db (après le script ADG-M)
az login
sqlcmd -S modernagent-sql-dev.database.windows.net -d modernagent_db -G -i .\db\sevenrqa_schema.sql

# 4. Renseigner l'environnement
Copy-Item .\.env.example .\.env
# -> éditer .env (notamment ADGM_API_BASE_URL et AZURE_OPENAI_DEPLOYMENT_REASONING)
```

### Démarrage en mode développement

```powershell
# Pré-requis : ADG-M (func) + Neo4j déjà démarrés (cf. SDD_ADG-M §5)

# Terminal A : backend 7RQA (port distinct)
Set-Location .\backend\sevenrqa
.\.venv\Scripts\Activate.ps1
func start --port 7072   # http://localhost:7072/api/v1/qualify/...

# Terminal B : frontend (déjà lancé pour ADG-M, vues 7RQA intégrées)
Set-Location .\frontend
npm run dev
```

### Vérification de l'environnement

```powershell
# 1. ADG-M joignable depuis 7RQA
Invoke-RestMethod -Uri "http://localhost:7071/api/v1/graph/health" -Method GET

# 2. Qualifier un nœud de test (doit retourner un reportId)
$body = @{ author = "dev@local" } | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:7072/api/v1/qualify/single/7a3f9c12-4b8e-4d21-9f6a-2c1e5d8b0a44" `
  -Method POST -Body $body -ContentType "application/json"
```

---

## 6. Architecture des composants frontend

### Arbre des composants React

```
App
├── GraphPage (ADG-M)
│   └── RightPanel
│       ├── QualifyButton — déclenche la qualification du nœud sélectionné (F2.1)
│       └── QualificationDrawer — affiche le rapport généré en panneau latéral
│           └── QualificationReportView (réutilisé ci-dessous)
├── QualificationBacklogPage — vue autonome (F2.4 intake)
│   ├── BacklogFilters — domaine / criticité / confiance
│   ├── BacklogTable — nœuds UNQUALIFIED (tri, sélection multiple)
│   └── BatchQualifyAction — "Qualifier le portefeuille / le cluster"
├── PortfolioSummaryPage — tableau de synthèse (F2.4 sortie)
│   ├── R7DistributionChart — distribution des 7R
│   └── ConfidenceHeatmap — heatmap confiance par domaine
└── QualificationReportView — rendu d'un dossier
    ├── DecisionHeader — 7R recommandée + badge confiance
    ├── DimensionTable — 6 dimensions (valeur observée / impact / confiance)
    ├── ExcludedAlternativesList — 7R écartées + motif
    ├── AssumptionsKillCriteria — hypothèses + kill criteria
    ├── EffortPanel — fourchette j·h + référence de calibration
    └── DecisionActions — Valider / Surcharger (motif obligatoire)
```

### Gestion de l'état

| Données | Localisation | Type de state | Justification |
|---|---|---|---|
| Rapport courant | `QualificationReportView` (props) | `useState` (parent) | Rendu d'un rapport unique à la fois |
| Backlog (liste rapports) | `QualificationBacklogPage` | `useReducer` + React Query | Pagination/filtres + cache serveur |
| Sélection batch | `QualificationBacklogPage` | `useState` (Set d'ids) | Sélection multiple avant batch |
| Distribution portefeuille | `PortfolioSummaryPage` | React Query | Données agrégées en lecture seule |
| Token Azure AD | `AuthProvider` (MSAL) | Context | Injecté dans les appels API |

### Configuration de la librairie de visualisation

```typescript
// Configuration Recharts — distribution 7R et heatmap confiance
// Fichier : src/config/charts.config.ts
// [HYPOTHÈSE — à confirmer] Recharts retenu (léger, suffisant pour barres/heatmap).
// D3.js n'est pas requis ici (réservé à ADM-M pour le quadrant).

import { R7_COLORS } from "./cytoscape.config"; // réutilise la palette 7R d'ADG-M

export const r7DistributionConfig = {
  colorByKey: R7_COLORS,         // cohérence visuelle avec le graphe ADG-M
  layout: "vertical" as const,
};

export const confidenceScale = {
  ELEVEE:  "#43a047",  // vert
  MOYENNE: "#fb8c00",  // orange
  FAIBLE:  "#e53935",  // rouge — priorité investigation humaine
} as const;
```

---

## 7. Points d'intégration inter-modules

| Appelant | Endpoint appelé | Données envoyées | Données reçues | Déclencheur |
|---|---|---|---|---|
| 7RQA | `GET /graph/nodes/{nodeId}` (ADG-M) | `nodeId` | `TechnicalNode` + métriques | Qualification unitaire F2.1 |
| 7RQA | `GET /graph/clusters` (ADG-M) | `candidateOnly` | `Cluster[]` | Qualification batch F2.4 |
| 7RQA | Azure AI Search (`/indexes/archimind-retrodocs/docs`) | `sourceDocIds` du nœud | contenu rétro-doc | Chargement contexte F2.1 |
| 7RQA | Azure OpenAI o4-mini (Chat Completions) | grille 6 dimensions + contexte | évaluation structurée | Exécution de la grille |
| 7RQA | Azure OpenAI GPT-4o | description fonctionnelle | recherche équivalent SaaS (D5) | Dimension SAAS |
| 7RQA | `GET /matrix/position/{nodeId}` (ADM-M, optionnel) | `nodeId` | position quadrant si existante | Enrichissement contexte F2.1 |
| 7RQA | `PATCH /graph/nodes/{nodeId}/qualification` (ADG-M) | 7R + justif + `source=7RQA` | nœud mis à jour | Décision validée F2.3 |
| ADM-M | `GET /qualify/report/{reportId}` (7RQA) | `reportId` | `QualificationReport` | Génération ADR F3.5 (alternatives écartées) |
| ADM-M | `GET /qualify/reports?nodeId=` (7RQA) | `nodeId` | dernier rapport du nœud | Lien 7RQA dans l'ADR |

> **Cohérence vérifiée** : les endpoints ADG-M référencés (`GET /graph/nodes/{nodeId}`, `GET /graph/clusters`, `PATCH /graph/nodes/{nodeId}/qualification`) existent bien dans `SDD_ADG-M_v1.md §3`. L'appel optionnel à `GET /matrix/position/{nodeId}` est défini dans `SDD_ADM-M_v1.md §3` (tolérance : 404 toléré si ADM-M absent).

---

## 8. Gestion des erreurs

### Erreurs métier attendues

| Code d'erreur interne | Condition | Message utilisateur (FR) | Action recommandée |
|---|---|---|---|
| `ERR_7RQA_001` | Nœud non technique ou inexistant | « Seuls les composants techniques peuvent être qualifiés. » | Sélectionner un composant technique |
| `ERR_7RQA_002` | Rétro-doc introuvable via RAG | « Documentation source indisponible : confiance dégradée à FAIBLE. » | Vérifier l'ingestion ArchiMind du composant |
| `ERR_7RQA_003` | Données insuffisantes (confiance FAIBLE) | « Données insuffisantes : qualification à valider manuellement en priorité. » | Investigation humaine |
| `ERR_7RQA_004` | Surcharge sans motif | « Un motif de surcharge est obligatoire. » | Saisir le motif |
| `ERR_7RQA_005` | Aucune calibration pour la techno/7R | « Pas de référence de calibration : effort non chiffré. » | Ajouter une entrée EffortCalibration |

### Stratégie de retry pour erreurs techniques

| Type d'erreur | Retry | Délai | Backoff | Fallback |
|---|---|---|---|---|
| Timeout Azure OpenAI (o4-mini) | 2 tentatives | 2s, 5s | Linéaire | Log + erreur 502 |
| Throttling OpenAI (429) | 3 tentatives | header `Retry-After` | Selon header | Log + erreur 502 |
| Timeout Azure AI Search | 2 tentatives | 1s, 3s | Linéaire | Dégradation : rapport en confiance FAIBLE |
| Appel ADG-M (GET/PATCH) 5xx | 3 tentatives | 1s, 2s, 4s | Exponentiel | Log + erreur 502 (PATCH : décision conservée en SQL) |
| Azure SQL indisponible | 3 tentatives | 1s, 3s, 9s | Exponentiel | Log + erreur 503 |

### Format de log structuré

```json
{
  "timestamp": "2026-06-06T22:40:05Z",
  "level": "INFO",
  "module": "7RQA",
  "operation": "qualify_single",
  "correlationId": "5f2c8a10-9b44-4e07-8c1d-77a0f3e6b201",
  "message": "Qualification générée",
  "data": { "nodeId": "7a3f9c12-...", "recommended7R": "REHOST", "confidence": "MOYENNE", "calibrationRef": "Arkéa 2025" },
  "error": null
}
```

---

## 9. Stratégie de test

### Tests unitaires

Framework : **pytest** (backend) / **Vitest** (frontend).

| Composant à tester | Ce qui est testé | Ce qui est mocké | Priorité |
|---|---|---|---|
| `eval_complexity()` | outDegree > seuil → Rehost avant Refactor | métriques nœud (fixture) | P0 |
| `eval_business_value()` | différenciant → exclut Retire/Repurchase | rétro-doc + domaine | P0 |
| `eval_knowledge()` | coverage < 40% ou TACIT → conservateur | nœud | P0 |
| `eval_regulatory()` | DORA/BCBS239 → exclut Rebuild | tags nœud | P0 |
| `eval_saas()` | marché mature + non différenciant → Repurchase | réponse GPT-4o figée | P1 |
| `estimate_effort()` | LOC × calibration → fourchette min/médian/max | table EffortCalibration | P0 |
| `assemble_report()` | composition des 6 dimensions + cohérence recommandation | sorties d'évaluateurs | P0 |
| `compute_confidence()` | dégradation à FAIBLE si rétro-doc absente | flags de complétude | P0 |
| `apply_decision()` | OVERRIDE → PATCH ADG-M + révision SQL | client ADG-M, SQL | P0 |
| `DecisionActions` (Vitest) | motif obligatoire en surcharge | client API | P0 |

### Tests d'intégration

1. **Qualification unitaire bout-en-bout** : `POST /qualify/single/{nodeId}` sur GESTION-COMMANDE (graphe + rétro-doc de test) → rapport persisté avec 6 dimensions, recommandation cohérente, effort chiffré.
2. **Dégradation RAG** : rétro-doc absente → rapport généré en confiance FAIBLE + `ERR_7RQA_002` loggé (pas d'échec dur).
3. **Validation → write-back** : `POST /decision` (VALIDATE) → `candidate7R` mis à jour dans Neo4j (vérifié via `GET /graph/nodes/{id}`) + ligne `QualificationRevision`.
4. **Batch cluster** : `POST /qualify/batch` sur `cl-commandes-01` → distribution renseignée + nœuds FAIBLE listés.

### Fixture de données de test

```
tests/fixtures/7rqa/
├── node_gestion_commande.json        # TechnicalNode + métriques (réponse ADG-M mockée)
├── retrodoc_gestion_commande.md      # rétro-doc (réponse RAG mockée)
├── o4mini_dimensions_response.json   # sortie figée du modèle de raisonnement
├── gpt4o_saas_response.json          # sortie figée recherche SaaS (D5)
└── expected_report.json              # rapport attendu (assertions)
```

### Critère "Done" du module

- [ ] Qualification unitaire d'un nœud réel produit un rapport aux 6 dimensions avec recommandation et effort chiffré.
- [ ] La confiance se dégrade correctement quand la rétro-doc manque.
- [ ] Validation/surcharge met à jour le graphe ADG-M et historise la révision.
- [ ] Le batch sur un cluster produit la distribution + liste FAIBLE confiance.
- [ ] La référence de calibration apparaît dans chaque rapport (opposabilité).
- [ ] Tous les tests unitaires P0 passent.
- [ ] Scénario d'intégration 1 (qualification bout-en-bout) passe en dev.

---

## 10. Questions ouvertes et hypothèses retenues

| # | Question | Hypothèse retenue pour ce SDD | Impact si fausse |
|---|---|---|---|
| 1 | Le déploiement Azure OpenAI `o4-mini` (reasoning) est-il disponible dans la région ? | **[HYPOTHÈSE — à confirmer]** Disponible ; sinon repli `o3-mini` ou GPT-4o « CoT ». | Changement de `AZURE_OPENAI_DEPLOYMENT_REASONING` + recalibrage des prompts ; coût et latence différents. |
| 2 | Données de calibration Arkéa / Retail : structurées ou à extraire manuellement ? | **[HYPOTHÈSE — à confirmer]** Valeurs indicatives saisies dans `EffortCalibration`, à raffiner. | Si extraction manuelle nécessaire : effort de calibration F2.5 à planifier ; chiffrages provisoires entre-temps. |
| 3 | Source de la dimension SaaS (D5) : catalogue interne RAG ou marché live ? | **[HYPOTHÈSE — à confirmer]** RAG catalogue interne + raisonnement GPT-4o ; pas de recherche web. | Si marché live requis : ajouter un connecteur externe + gestion de fraîcheur/coût. |
| 4 | Méthode de calcul de la confiance globale | Confiance = min des confiances dimensionnelles, dégradée à FAIBLE si rétro-doc absente ou coverage < 40%. | Si pondération souhaitée : remplacer le « min » par une moyenne pondérée paramétrable. |
| 5 | 7RQA doit-il écrire la 7R dans le graphe à la **génération** ou à la **validation** uniquement ? | À la **validation/surcharge** seulement (le graphe ne reflète que les décisions humaines). | Si écriture à la génération : risque de candidate7R non validés dans MWP ; ajouter un statut intermédiaire. |
