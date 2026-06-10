# SDD — Migration Wave Planner (v1)
**Module** : MWP  **Priorité** : P1  **Dernière mise à jour** : 2026-06-06

---

## 1. Synthèse du module

**Rôle dans l'architecture globale** : MWP est le livrable final de la chaîne — il transforme l'analyse en **programme de transformation pilotable**. À partir du graphe de dépendances (ADG-M), des 7R validées (7RQA + ADM-M) et des appartements candidats (clusters ADG-M), il génère un plan de migration **séquencé par vagues**, chaque vague étant un « appartement livrable » à état stable. Il identifie les couches d'interopérabilité et kill criteria de cohabitation (F4.2), estime l'effort/durée calibré sur des références missions (F4.3), simule des scénarios alternatifs (F4.4), pilote l'avancement post-lancement (F4.5) et exporte vers Markdown, Azure DevOps et PowerPoint (F4.6). Il est le terminal de la séquence ADG-M → 7RQA → ADM-M → **MWP** : rien ne le consomme en aval hormis les humains et les exports.

**Dépendances en entrée** :
- **ADG-M** via `GET /api/v1/graph/nodes`, `GET /api/v1/graph/arcs` (tri topologique), `GET /api/v1/graph/clusters` (vagues alignées sur les appartements).
- **ADM-M** via `GET /api/v1/matrix/portfolio` (scoreD pour le mode « Valeur ») et `GET /api/v1/matrix/adr/{adrId}` (couches d'interopérabilité documentées).
- **7RQA** via `GET /api/v1/qualify/reports` (confiance, pour pondérer l'incertitude) et la table SQL `EffortCalibration` (lecture directe, partagée — cf. `SDD_7RQA_v1.md §2.2`).
- **Azure DevOps REST API** (export Epics/Features) et **python-pptx** (export deck).

**Dépendances en sortie** :
- **Aucun module aval.** Sorties destinées aux humains : fiches de vague Markdown, backlog Azure DevOps, deck COMEX PowerPoint, dashboard de pilotage.

**Périmètre v1 — inclus** :
- Génération automatique de vagues (tri topologique + 3 modes de priorisation) (F4.1).
- États stables : couches d'interopérabilité, double run, kill criteria (F4.2).
- Estimation effort/durée calibrée (F4.3).
- Simulation de 3 scénarios sur 3 indicateurs (F4.4).
- Dashboard de pilotage d'avancement (F4.5).
- Exports Markdown / Azure DevOps / PowerPoint (F4.6).

**Périmètre v1 — exclus** (et pourquoi) :
- **Calcul automatique du pic de coût de double run en euros** : nécessite des données OPEX legacy/cible non disponibles en v1 ; l'indicateur est calculé en **proxy relatif** (nb de composants en double run × durée), pas en euros. [Cf. §10 Q3.]
- **Synchronisation bidirectionnelle avec Azure DevOps** (relecture de l'avancement réel depuis DevOps) : v1 fait un export descendant (création Epics/Features) ; le pilotage F4.5 se fait dans MWP. Reporté.
- **Optimisation multi-contraintes avancée** (solveur) : v1 utilise un tri topologique heuristique pondéré, pas un solveur d'optimisation combinatoire.

---

## 2. Schémas de données

### 2.1 Modèle Neo4j

MWP **lit** le graphe (nœuds/arcs/clusters) via l'API ADG-M pour le tri topologique. Il **n'écrit pas** dans Neo4j. Aucune contrainte/index propre.

Cypher de référence pour le tri topologique (exécuté côté ADG-M ou via le driver en lecture) :
```cypher
// Ordre topologique partiel des composants techniques selon DEPENDS_ON
// (les cycles sont détectés puis brisés par insertion d'une couche d'interopérabilité)
MATCH (n:TechnicalNode)
OPTIONAL MATCH (n)-[:DEPENDS_ON]->(dep:TechnicalNode)
RETURN n.id AS nodeId, n.componentName AS name, n.candidate7R AS r7,
       n.clusterId AS clusterId, collect(dep.id) AS dependsOn;
```

### 2.2 Schémas Azure SQL

MWP est propriétaire des tables de plan, vagues, composants de vague, couches d'interop, scénarios et historique de statut. Base : `modernagent_db`. Il lit `EffortCalibration` (propriété 7RQA).

```sql
-- Script de création : MWP — Azure SQL Database
-- À exécuter dans modernagent_db (après ADG-M, 7RQA, ADM-M)

-- 1) Plan de migration
CREATE TABLE [dbo].[WavePlan] (
    [planId]           UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID(),
    [name]             NVARCHAR(128)    NOT NULL,
    [mode]             NVARCHAR(10)     NOT NULL,   -- VALUE|RISK|BUDGET
    [waveLengthMonths] INT              NOT NULL DEFAULT 6,
    [teamSize]         DECIMAL(5,1)     NOT NULL DEFAULT 5.0, -- ETP
    [status]           NVARCHAR(10)     NOT NULL DEFAULT 'DRAFT', -- DRAFT|VALIDATED|ACTIVE
    [totalEffortMedianJh] DECIMAL(12,1) NULL,
    [author]           NVARCHAR(128)    NOT NULL,
    [createdAt]        DATETIME2(0)     NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT [PK_WavePlan] PRIMARY KEY CLUSTERED ([planId] ASC)
);
CREATE INDEX [IX_WavePlan_status] ON [dbo].[WavePlan] ([status]);

-- 2) Vague
CREATE TABLE [dbo].[Wave] (
    [waveId]           UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID(),
    [planId]           UNIQUEIDENTIFIER NOT NULL,
    [sequence]         INT              NOT NULL,   -- 1,2,3...
    [name]             NVARCHAR(128)    NOT NULL,
    [startMonth]       INT              NOT NULL,   -- mois relatif (0-based)
    [endMonth]         INT              NOT NULL,
    [effortMinJh]      DECIMAL(12,1)    NOT NULL,
    [effortMedianJh]   DECIMAL(12,1)    NOT NULL,
    [effortMaxJh]      DECIMAL(12,1)    NOT NULL,
    [uncertainty]      NVARCHAR(8)      NOT NULL,   -- LOW|MEDIUM|HIGH
    [calibrationRef]   NVARCHAR(64)     NULL,
    [deliversValue]    NVARCHAR(MAX)    NULL,        -- valeur métier indépendante (condition 3)
    CONSTRAINT [PK_Wave] PRIMARY KEY CLUSTERED ([waveId] ASC),
    CONSTRAINT [FK_Wave_Plan] FOREIGN KEY ([planId]) REFERENCES [dbo].[WavePlan]([planId]) ON DELETE CASCADE
);
CREATE INDEX [IX_Wave_plan] ON [dbo].[Wave] ([planId], [sequence]);

-- 3) Composant rattaché à une vague (+ statut de pilotage F4.5)
CREATE TABLE [dbo].[WaveComponent] (
    [id]               UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID(),
    [waveId]           UNIQUEIDENTIFIER NOT NULL,
    [nodeId]           NVARCHAR(64)     NOT NULL,   -- TechnicalNode ADG-M
    [componentName]    NVARCHAR(128)    NOT NULL,
    [trajectory7R]     NVARCHAR(16)     NOT NULL,
    [effortMedianJh]   DECIMAL(10,1)    NOT NULL,
    [status]           NVARCHAR(12)     NOT NULL DEFAULT 'TODO', -- TODO|IN_PROGRESS|DONE|BLOCKED
    [devopsWorkItemId] INT              NULL,        -- id Feature Azure DevOps (après export)
    CONSTRAINT [PK_WaveComponent] PRIMARY KEY CLUSTERED ([id] ASC),
    CONSTRAINT [FK_WaveComp_Wave] FOREIGN KEY ([waveId]) REFERENCES [dbo].[Wave]([waveId]) ON DELETE CASCADE
);
CREATE INDEX [IX_WaveComp_wave] ON [dbo].[WaveComponent] ([waveId]);
CREATE INDEX [IX_WaveComp_node] ON [dbo].[WaveComponent] ([nodeId]);

-- 4) Couches d'interopérabilité / cohabitation (F4.2)
CREATE TABLE [dbo].[WaveInteropLayer] (
    [id]               UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID(),
    [waveId]           UNIQUEIDENTIFIER NOT NULL,
    [type]             NVARCHAR(16)     NOT NULL,   -- PROXY|CDC|API_FACADE|BATCH_BRIDGE
    [description]      NVARCHAR(MAX)    NOT NULL,
    [doubleRunComponents] NVARCHAR(MAX) NULL,        -- liste des composants en double run (JSON)
    [killCriteria]     NVARCHAR(MAX)    NOT NULL,    -- condition mesurable de décommissionnement
    [cohabitationWeeksMin] INT          NULL,
    [cohabitationWeeksMax] INT          NULL,
    CONSTRAINT [PK_WaveInteropLayer] PRIMARY KEY CLUSTERED ([id] ASC),
    CONSTRAINT [FK_WaveInterop_Wave] FOREIGN KEY ([waveId]) REFERENCES [dbo].[Wave]([waveId]) ON DELETE CASCADE
);

-- 5) Scénarios de simulation (F4.4)
CREATE TABLE [dbo].[WaveScenario] (
    [scenarioId]       UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID(),
    [planId]           UNIQUEIDENTIFIER NOT NULL,   -- plan généré pour ce scénario
    [label]            NVARCHAR(64)     NOT NULL,   -- "Variante A", ...
    [description]      NVARCHAR(256)    NULL,
    [monthsToFirstValue]   INT          NOT NULL,   -- indicateur 1
    [doubleRunCostPeak]    DECIMAL(10,2) NOT NULL,  -- indicateur 2 (proxy relatif, cf. §10 Q3)
    [maxRiskLevel]         INT          NOT NULL,   -- indicateur 3 (échelle 0-100)
    [createdAt]        DATETIME2(0)     NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT [PK_WaveScenario] PRIMARY KEY CLUSTERED ([scenarioId] ASC),
    CONSTRAINT [FK_WaveScenario_Plan] FOREIGN KEY ([planId]) REFERENCES [dbo].[WavePlan]([planId])
);

-- 6) Historique de statut (pilotage F4.5)
CREATE TABLE [dbo].[ComponentStatusHistory] (
    [id]               UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID(),
    [nodeId]           NVARCHAR(64)     NOT NULL,
    [planId]           UNIQUEIDENTIFIER NOT NULL,
    [fromStatus]       NVARCHAR(12)     NULL,
    [toStatus]         NVARCHAR(12)     NOT NULL,
    [author]           NVARCHAR(128)    NOT NULL,
    [createdAt]        DATETIME2(0)     NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT [PK_ComponentStatusHistory] PRIMARY KEY CLUSTERED ([id] ASC)
);
CREATE INDEX [IX_CompStatus_plan] ON [dbo].[ComponentStatusHistory] ([planId], [createdAt] DESC);
```

### 2.3 Objets de transfert inter-modules (DTOs)

```typescript
// DTO : WavePlan — produit par MWP, consommé par le frontend et les exports
interface WavePlan {
  planId: string;
  name: string;
  mode: "VALUE" | "RISK" | "BUDGET";
  waveLengthMonths: number;
  teamSize: number;            // ETP
  status: "DRAFT" | "VALIDATED" | "ACTIVE";
  totalEffortMedianJh: number;
  waves: Wave[];
  author: string;
  createdAt: string;
}

interface Wave {
  waveId: string;
  sequence: number;
  name: string;                // ex : "Vague 1 — Décommissionnement Context"
  startMonth: number;
  endMonth: number;
  effort: { minJh: number; medianJh: number; maxJh: number };
  uncertainty: "LOW" | "MEDIUM" | "HIGH";
  calibrationRef: string | null;
  deliversValue: string | null; // valeur métier indépendante (condition de validité 3)
  components: WaveComponent[];
  interopLayers: InteropLayer[];
}

interface WaveComponent {
  nodeId: string;
  componentName: string;
  trajectory7R: SevenR;
  effortMedianJh: number;
  status: "TODO" | "IN_PROGRESS" | "DONE" | "BLOCKED";
  devopsWorkItemId: number | null;
}

type SevenR = "RETIRE" | "RETAIN" | "REHOST" | "REPLATFORM"
            | "REPURCHASE" | "REFACTOR" | "REBUILD";

interface InteropLayer {
  type: "PROXY" | "CDC" | "API_FACADE" | "BATCH_BRIDGE";
  description: string;
  doubleRunComponents: string[];
  killCriteria: string;        // ex : "100% des flux validés sur cible depuis 30 jours"
  cohabitationWeeks: { min: number; max: number } | null;
}

// DTO : ScenarioComparison — réponse de POST /wave/simulate (F4.4)
interface ScenarioComparison {
  scenarios: Array<{
    label: string;             // "Variante A"
    description: string;
    mode: "VALUE" | "RISK" | "BUDGET";
    waveLengthMonths: number;
    monthsToFirstValue: number;     // indicateur 1
    doubleRunCostPeak: number;      // indicateur 2 (proxy relatif)
    maxRiskLevel: number;           // indicateur 3 (0-100)
    planId: string;
  }>;
  recommendation: string | null;    // synthèse comparative
}
```

---

## 3. Contrats d'API REST

Base URL : `https://{{AZURE_FUNCTION_APP_NAME}}.azurewebsites.net/api/v1`
Authentification : `Authorization: Bearer {{TOKEN}}`.

### `POST /wave/generate`

**Description** : Génère un plan de vagues à partir du graphe, des 7R validées et des clusters, selon un mode de priorisation (F4.1).

**Request body** :
```json
{
  "name": "string — nom du plan",
  "mode": "string — VALUE | RISK | BUDGET",
  "waveLengthMonths?": "number — durée cible d'une vague (défaut 6)",
  "teamSize?": "number — ETP disponibles (défaut 5)",
  "scopeClusterIds?": "string[] — limiter le plan à certains appartements (défaut : tout le périmètre)",
  "author": "string — UPN"
}
```
Exemple de valeur réaliste :
```json
{
  "name": "Programme Retail — trajectoire Budget",
  "mode": "BUDGET",
  "waveLengthMonths": 6,
  "teamSize": 5,
  "scopeClusterIds": ["cl-commandes-01", "cl-facturation-02"],
  "author": "v.gicquiau@retail-compagnie.fr"
}
```

**Response 200** :
```json
{
  "planId": "9b7e0a44-1c2d-4e3f-8a90-aa11bb22cc33",
  "name": "Programme Retail — trajectoire Budget",
  "mode": "BUDGET",
  "waveLengthMonths": 6,
  "teamSize": 5,
  "status": "DRAFT",
  "totalEffortMedianJh": 612.4,
  "waves": [
    {
      "waveId": "w1-...",
      "sequence": 1,
      "name": "Vague 1 — Décommissionnement Context (finance le Core)",
      "startMonth": 0,
      "endMonth": 6,
      "effort": { "minJh": 28.0, "medianJh": 52.0, "maxJh": 90.0 },
      "uncertainty": "LOW",
      "calibrationRef": "Retail Compagnie 2024",
      "deliversValue": "OPEX legacy réduite : 2 batchs et 1 module édition décommissionnés",
      "components": [
        { "nodeId": "3e9a...", "componentName": "EDITION-BORDEREAU", "trajectory7R": "RETIRE", "effortMedianJh": 9.2, "status": "TODO", "devopsWorkItemId": null },
        { "nodeId": "5b1c...", "componentName": "CHARGEMENT-STOCK-NUIT", "trajectory7R": "REPURCHASE", "effortMedianJh": 42.8, "status": "TODO", "devopsWorkItemId": null }
      ],
      "interopLayers": [
        { "type": "BATCH_BRIDGE", "description": "Pont batch temporaire vers le SaaS stock", "doubleRunComponents": ["CHARGEMENT-STOCK-NUIT"], "killCriteria": "100% des chargements validés sur SaaS depuis 30 jours", "cohabitationWeeks": { "min": 6, "max": 12 } }
      ]
    },
    {
      "waveId": "w3-...",
      "sequence": 3,
      "name": "Vague 3 — Refactor Core (Gestion des commandes)",
      "startMonth": 12,
      "endMonth": 18,
      "effort": { "minJh": 95.0, "medianJh": 168.0, "maxJh": 270.0 },
      "uncertainty": "HIGH",
      "calibrationRef": "Arkéa 2025",
      "deliversValue": "Prise de commande modernisée, règles de remise externalisées",
      "components": [
        { "nodeId": "7a3f9c12-4b8e-4d21-9f6a-2c1e5d8b0a44", "componentName": "GESTION-COMMANDE", "trajectory7R": "REFACTOR", "effortMedianJh": 141.0, "status": "TODO", "devopsWorkItemId": null }
      ],
      "interopLayers": [
        { "type": "API_FACADE", "description": "Façade API devant GESTION-COMMANDE pendant la réécriture", "doubleRunComponents": ["GESTION-COMMANDE"], "killCriteria": "100% des flux commande routés sur cible + parité fonctionnelle validée 30 j", "cohabitationWeeks": { "min": 8, "max": 16 } }
      ]
    }
  ],
  "author": "v.gicquiau@retail-compagnie.fr",
  "createdAt": "2026-06-06T23:20:00Z"
}
```

| Code | Condition | Message retourné |
|---|---|---|
| 400 | `mode` invalide | `{"error": "Mode invalide : VALUE, RISK ou BUDGET"}` |
| 409 | Composants non qualifiés dans le périmètre (UNQUALIFIED) | `{"error": "N composants non qualifiés dans le périmètre", "details": ["nodeId..."]}` |
| 422 | Cycle de dépendances non résolvable même avec interop | `{"error": "Cycle bloquant détecté", "details": ["A<->B"]}` |
| 502 | ADG-M injoignable | `{"error": "Graphe indisponible. Réessayer."}` |
| 500 | Erreur interne | `{"error": "Erreur interne. Réessayer ou contacter le support."}` |

---

### `GET /wave/plan/{planId}`

**Description** : Retourne un plan complet (objet `WavePlan`).

| Code | Condition | Message retourné |
|---|---|---|
| 404 | Plan inexistant | `{"error": "Plan introuvable"}` |
| 500 | Erreur interne | `{"error": "Erreur interne. Réessayer ou contacter le support."}` |

---

### `POST /wave/simulate`

**Description** : Génère et compare plusieurs variantes de plan sur les 3 indicateurs (F4.4).

**Request body** :
```json
{
  "scopeClusterIds?": "string[]",
  "variants": [
    { "label": "string", "mode": "VALUE|RISK|BUDGET", "waveLengthMonths": "number", "teamSize": "number" }
  ],
  "author": "string"
}
```
Exemple de valeur réaliste :
```json
{
  "variants": [
    { "label": "Variante A", "mode": "VALUE",  "waveLengthMonths": 6, "teamSize": 5 },
    { "label": "Variante B", "mode": "RISK",   "waveLengthMonths": 3, "teamSize": 5 },
    { "label": "Variante C", "mode": "BUDGET", "waveLengthMonths": 6, "teamSize": 5 }
  ],
  "author": "v.gicquiau@retail-compagnie.fr"
}
```

**Response 200** :
```json
{
  "scenarios": [
    { "label": "Variante A", "description": "Vagues de 6 mois, mode Valeur", "mode": "VALUE",  "waveLengthMonths": 6, "monthsToFirstValue": 6,  "doubleRunCostPeak": 7.5, "maxRiskLevel": 72, "planId": "p-a-..." },
    { "label": "Variante B", "description": "Vagues de 3 mois, mode Risque", "mode": "RISK",   "waveLengthMonths": 3, "monthsToFirstValue": 3,  "doubleRunCostPeak": 4.0, "maxRiskLevel": 41, "planId": "p-b-..." },
    { "label": "Variante C", "description": "Retire d'abord, mode Budget",   "mode": "BUDGET", "waveLengthMonths": 6, "monthsToFirstValue": 6,  "doubleRunCostPeak": 3.0, "maxRiskLevel": 55, "planId": "p-c-..." }
  ],
  "recommendation": "Variante B minimise le risque et délivre de la valeur dès M3 ; Variante C minimise le pic de double run mais retarde la valeur cœur."
}
```

| Code | Condition | Message retourné |
|---|---|---|
| 400 | Moins de 2 variantes | `{"error": "Fournir au moins 2 variantes à comparer"}` |
| 422 | Périmètre non qualifié | `{"error": "Composants non qualifiés dans le périmètre"}` |
| 500 | Erreur interne | `{"error": "Erreur interne. Réessayer ou contacter le support."}` |

---

### `PUT /wave/status/{componentId}`

**Description** : Met à jour le statut d'avancement d'un composant d'une vague (pilotage F4.5) et historise.

**Request body** :
```json
{
  "status": "string — TODO | IN_PROGRESS | DONE | BLOCKED",
  "author": "string"
}
```
Exemple :
```json
{ "status": "DONE", "author": "v.gicquiau@retail-compagnie.fr" }
```

**Response 200** :
```json
{
  "componentId": "wc-7a3f...",
  "nodeId": "7a3f9c12-...",
  "status": "DONE",
  "waveSequence": 3,
  "downstreamAlerts": [
    { "nodeId": "9d2b...", "componentName": "CALCUL-REMISE", "wave": 3, "reason": "Prérequis livré : déblocage possible" }
  ],
  "driftMonths": 0
}
```

| Code | Condition | Message retourné |
|---|---|---|
| 400 | Statut invalide | `{"error": "Statut invalide"}` |
| 404 | Composant de vague inexistant | `{"error": "Composant de vague introuvable"}` |
| 409 | Passage à DONE alors qu'un prérequis n'est pas livré | `{"error": "Prérequis non livré", "details": ["GESTION-COMMANDE non DONE"]}` |
| 500 | Erreur interne | `{"error": "Erreur interne. Réessayer ou contacter le support."}` |

---

### `POST /wave/export/devops`

**Description** : Crée les Epics (une par vague) et Features (une par composant) dans Azure DevOps via l'API REST (F4.6).

**Request body** :
```json
{
  "planId": "string",
  "organization": "string — org Azure DevOps",
  "project": "string — projet cible",
  "areaPath?": "string"
}
```
Exemple :
```json
{
  "planId": "9b7e0a44-1c2d-4e3f-8a90-aa11bb22cc33",
  "organization": "retail-compagnie",
  "project": "Modernisation-SI",
  "areaPath": "Modernisation-SI\\Vagues"
}
```

**Response 200** :
```json
{
  "planId": "9b7e0a44-...",
  "epicsCreated": 3,
  "featuresCreated": 17,
  "links": [
    { "wave": 1, "epicId": 1042, "url": "https://dev.azure.com/retail-compagnie/Modernisation-SI/_workitems/edit/1042" }
  ]
}
```

| Code | Condition | Message retourné |
|---|---|---|
| 401 | PAT Azure DevOps invalide/expiré | `{"error": "Authentification Azure DevOps refusée"}` |
| 404 | Projet/organisation inexistant | `{"error": "Projet Azure DevOps introuvable"}` |
| 502 | API DevOps indisponible | `{"error": "Azure DevOps indisponible. Réessayer."}` |
| 500 | Erreur interne | `{"error": "Erreur interne. Réessayer ou contacter le support."}` |

---

### `POST /wave/export/pptx`

**Description** : Génère un deck PowerPoint de synthèse (une slide par variante + slide de comparaison) via python-pptx (F4.6). Retourne un lien Blob.

**Request body** :
```json
{ "planId?": "string", "scenarioComparisonId?": "string", "author": "string" }
```

**Response 200** :
```json
{
  "blobPath": "exports/deck-comex-programme-retail-2026-06-06.pptx",
  "downloadUrl": "https://modernagentstgdev.blob.core.windows.net/exports/deck-comex-programme-retail-2026-06-06.pptx?<sas>",
  "slides": 5
}
```

| Code | Condition | Message retourné |
|---|---|---|
| 404 | Plan/comparaison inexistant | `{"error": "Plan ou comparaison introuvable"}` |
| 500 | Génération pptx échouée | `{"error": "Erreur de génération du deck. Réessayer."}` |

---

## 4. Infrastructure Azure

### Ressources à provisionner

| Ressource | Nom recommandé | SKU / Tier | Config clé | Coût estimé/mois |
|---|---|---|---|---|
| Azure Functions | `modernagent-mwp-dev` | Consumption (Y1) Python 3.11 | Runtime v4 ; calcul scénarios en batch | ~0 € (grant 1M exéc.) |
| Azure SQL Database | `modernagent-sql-dev` / `modernagent_db` | Basic (partagé) | Tables plan/vagues/scénarios | 0 € (déjà compté) |
| Azure Blob Storage | `modernagentstgdev` (partagé) | Standard LRS | Container `exports` (pptx, fiches md) | ~0 € |
| Azure DevOps | `retail-compagnie` (à confirmer) | Basic (5 users gratuits) | PAT scope Work Items (RW) | 0 € (5 users gratuits) |
| Application Insights | `modernagent-ai-dev` (partagé) | Pay-as-you-go (5 Go gratuits) | Traces de génération | ~0 € |

> **[HYPOTHÈSE — à confirmer]** Le tenant/organisation Azure DevOps cible existe (cf. §10 Q1). Sinon, l'export DevOps est désactivable ; Markdown et PowerPoint restent fonctionnels.

### Variables d'environnement et secrets

```env
# MWP — Variables d'environnement
# Fichier : .env (ne jamais committer ; en prod -> Azure Key Vault)

ADGM_API_BASE_URL=http://localhost:7071/api/v1
ADMM_API_BASE_URL=http://localhost:7073/api/v1
SEVENRQA_API_BASE_URL=http://localhost:7072/api/v1

SQL_CONNECTION_STRING=Driver={ODBC Driver 18 for SQL Server};Server=tcp:modernagent-sql-dev.database.windows.net,1433;Database=modernagent_db;Authentication=ActiveDirectoryDefault;Encrypt=yes;

BLOB_ACCOUNT_URL=https://modernagentstgdev.blob.core.windows.net
BLOB_CONTAINER_EXPORTS=exports

# --- Azure DevOps ---
AZDO_ORG_URL=https://dev.azure.com/retail-compagnie
AZDO_PROJECT=Modernisation-SI
AZDO_PAT=<secret>                        # PAT scope Work Items (Read & Write)

AAD_TENANT_ID=<tenant-guid>
AAD_API_CLIENT_ID=<app-registration-guid>

# --- Tuning estimation/séquençage ---
DEFAULT_TEAM_SIZE=5                       # ETP
DEFAULT_WAVE_LENGTH_MONTHS=6
WORKING_DAYS_PER_MONTH=20
COUPLING_COEFF_TIERS=50,200,500          # seuils out-degree LOW/MEDIUM/HIGH/VERYHIGH
```

---

## 5. Configuration locale Windows

### Prérequis logiciels

| Outil | Version min. | Commande de vérification |
|---|---|---|
| Python | 3.11.x | `python --version` |
| Azure Functions Core Tools | 4.x | `func --version` |
| Node.js | 20 LTS | `node --version` |
| ODBC Driver for SQL Server | 18 | `Get-OdbcDriver -Name "ODBC Driver 18 for SQL Server"` |
| Azure CLI | 2.60+ | `az --version` |
| python-pptx (pip) | 0.6.23+ | `pip show python-pptx` |

> **Prérequis bloquant** : ADG-M (graphe), 7RQA (`EffortCalibration` + confiance) et ADM-M (`/matrix/portfolio` pour le mode Valeur) doivent être accessibles. Le mode RISK/BUDGET fonctionne sans ADM-M ; le mode VALUE en dépend.

### Mise en place de l'environnement

```powershell
# 1. Backend MWP
Set-Location .\modernization-agent\backend\mwp
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt   # pyodbc, httpx, python-pptx, azure-storage-blob, azure-devops

# 2. DDL SQL MWP (après les 3 autres modules)
az login
sqlcmd -S modernagent-sql-dev.database.windows.net -d modernagent_db -G -i .\db\mwp_schema.sql

# 3. Environnement
Copy-Item .\.env.example .\.env
# -> éditer AZDO_* et les ports des autres modules

# 4. Frontend : ajouter la dépendance vis-timeline si non présente
Set-Location ..\..\frontend
npm install vis-timeline vis-data
```

### Démarrage en mode développement

```powershell
# Pré-requis : Neo4j + ADG-M (7071) + 7RQA (7072) + ADM-M (7073)

# Terminal : backend MWP
Set-Location .\backend\mwp
.\.venv\Scripts\Activate.ps1
func start --port 7074   # http://localhost:7074/api/v1/wave/...

# Frontend (vue Gantt intégrée)
Set-Location .\frontend
npm run dev
```

### Vérification de l'environnement

```powershell
# 1. Générer un plan (mode RISK, ne dépend pas d'ADM-M)
$body = @{ name="Test plan"; mode="RISK"; author="dev@local" } | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:7074/api/v1/wave/generate" `
  -Method POST -Body $body -ContentType "application/json"

# 2. Vérifier la lecture de la calibration (doit renvoyer des lignes)
sqlcmd -S modernagent-sql-dev.database.windows.net -d modernagent_db -G `
  -Q "SELECT reference, trajectory7R, jhPerKlocMedian FROM dbo.EffortCalibration WHERE isActive=1;"
```

---

## 6. Architecture des composants frontend

### Arbre des composants React

```
App
└── WavePlanPage — page principale de planification
    ├── PlanToolbar — mode (Valeur/Risque/Budget), durée vague, taille équipe, "Générer"
    ├── GanttTimeline — timeline vis-timeline (X=mois, Y=vagues)
    │   ├── ComponentBlock (× n) — bloc composant, couleur = 7R
    │   ├── DoubleRunCostCurve — courbe superposée (proxy coût double run)
    │   └── ValueDeliveredCurve — courbe superposée (valeur livrée cumulée)
    ├── WaveDependencyView — graphe ADG-M filtré sur la vague (arcs de cohabitation en évidence)
    ├── ScenarioComparisonView — 3 variantes côte à côte sur 3 indicateurs (F4.4)
    │   └── IndicatorRadar — radar/barres des 3 indicateurs
    ├── PilotageDashboard — tableau d'avancement par vague (F4.5)
    │   ├── StatusBoard — TODO/EN COURS/LIVRÉ/BLOQUÉ par composant
    │   ├── DriftIndicator — dérive calendaire si vague en retard
    │   └── BudgetReleasedGauge — OPEX legacy éteint cumulé
    └── ExportPanel — Markdown / Azure DevOps / PowerPoint (F4.6)
```

### Gestion de l'état

| Données | Localisation | Type de state | Justification |
|---|---|---|---|
| Plan courant | `WavePlanPage` | React Query | Cache + invalidation après génération/statut |
| Paramètres de génération | `PlanToolbar` | `useReducer` | mode + durée + équipe combinés |
| Vague sélectionnée | `WavePlanPage` | `useState` | Pilote WaveDependencyView |
| Comparaison de scénarios | `ScenarioComparisonView` | React Query | Résultat de `/wave/simulate` |
| Statuts de pilotage | `PilotageDashboard` | React Query + mutation optimiste | Réactivité du board + PUT statut |
| Token Azure AD | `AuthProvider` (MSAL) | Context | Appels API |

### Configuration de la librairie de visualisation

```typescript
// Configuration vis-timeline — Gantt des vagues
// Fichier : src/config/timeline.config.ts

import type { TimelineOptions } from "vis-timeline";
import { R7_COLORS } from "./cytoscape.config"; // palette 7R partagée (cohérence inter-modules)

export const timelineOptions: TimelineOptions = {
  orientation: "top",
  stack: true,
  zoomable: true,
  margin: { item: 8 },
  timeAxis: { scale: "month", step: 1 },
  groupOrder: "sequence",        // groupes = vagues, ordonnés par séquence
  editable: false,               // v1 : lecture seule (replanification manuelle reportée)
};

// Couleur d'un bloc composant selon sa trajectoire 7R
export function blockStyle(trajectory7R: keyof typeof R7_COLORS): string {
  return `background-color:${R7_COLORS[trajectory7R]};border-color:#333;`;
}

// Groupes = vagues
export const buildGroups = (waves: { sequence: number; name: string }[]) =>
  waves.map(w => ({ id: w.sequence, content: w.name }));
```

---

## 7. Points d'intégration inter-modules

| Appelant | Endpoint appelé | Données envoyées | Données reçues | Déclencheur |
|---|---|---|---|---|
| MWP | `GET /graph/nodes` (ADG-M) | filtres périmètre | `TechnicalNode[]` + 7R | Génération F4.1 |
| MWP | `GET /graph/arcs` (ADG-M) | — | `DependencyArc[]` | Tri topologique / cycles |
| MWP | `GET /graph/clusters` (ADG-M) | `candidateOnly` | `Cluster[]` | Alignement vagues/appartements |
| MWP | `GET /matrix/portfolio` (ADM-M) | filtres | scoreD + 7R validée | Mode VALUE (priorisation) |
| MWP | `GET /matrix/adr/{adrId}` (ADM-M) | `adrId` | ADR (interop) | Fiche de vague F4.2 |
| MWP | `GET /qualify/reports?nodeId=` (7RQA) | `nodeId` | confiance | Niveau d'incertitude de vague F4.3 |
| MWP | SQL `EffortCalibration` (7RQA) | techno + 7R | ratios j·h/KLOC | Estimation effort F4.3 |
| MWP | Azure DevOps REST API | Epics/Features | ids work items | Export F4.6 |
| MWP | Azure Blob (`exports`) | fichier pptx/md | URL SAS | Export F4.6 |

> **Cohérence vérifiée** : `GET /graph/*` (ADG-M §3), `GET /matrix/portfolio` et `GET /matrix/adr/{adrId}` (ADM-M §3), `GET /qualify/reports` (7RQA §3) et la table `EffortCalibration` (7RQA §2.2) existent tous. MWP n'écrit dans aucun autre module.

---

## 8. Gestion des erreurs

### Erreurs métier attendues

| Code d'erreur interne | Condition | Message utilisateur (FR) | Action recommandée |
|---|---|---|---|
| `ERR_MWP_001` | Composants UNQUALIFIED dans le périmètre | « N composants non qualifiés : les qualifier (7RQA) avant de planifier. » | Lancer 7RQA sur le reste |
| `ERR_MWP_002` | Cycle de dépendances non résolvable | « Dépendance circulaire bloquante : insérer une couche d'interopérabilité. » | Décision d'architecture |
| `ERR_MWP_003` | Pas de calibration pour techno/7R | « Effort non chiffrable : calibration manquante. » | Compléter `EffortCalibration` |
| `ERR_MWP_004` | Mode VALUE sans positions ADM-M | « Mode Valeur indisponible : positionner les composants (ADM-M). » | Utiliser RISK/BUDGET ou compléter ADM-M |
| `ERR_MWP_005` | Passage DONE avec prérequis non livré | « Prérequis non livré : impossible de clôturer ce composant. » | Livrer le prérequis d'abord |
| `ERR_MWP_006` | Export DevOps : PAT manquant/expiré | « Connexion Azure DevOps requise (jeton expiré). » | Renouveler le PAT |

### Stratégie de retry pour erreurs techniques

| Type d'erreur | Retry | Délai | Backoff | Fallback |
|---|---|---|---|---|
| Appel ADG-M/ADM-M/7RQA 5xx | 3 tentatives | 1s, 2s, 4s | Exponentiel | Log + erreur 502 |
| Azure SQL indisponible | 3 tentatives | 1s, 3s, 9s | Exponentiel | Log + erreur 503 |
| Azure DevOps API 5xx | 3 tentatives | 2s, 4s, 8s | Exponentiel | Export partiel + liste des échecs |
| Azure DevOps 429 | respect `Retry-After` | header | Selon header | Reprise après délai |
| Écriture Blob (pptx) échouée | 2 tentatives | 1s, 2s | Linéaire | Erreur 500 (fichier non produit) |

### Format de log structuré

```json
{
  "timestamp": "2026-06-06T23:20:30Z",
  "level": "INFO",
  "module": "MWP",
  "operation": "generate_plan",
  "correlationId": "9b7e0a44-1c2d-4e3f-8a90-aa11bb22cc33",
  "message": "Plan généré",
  "data": { "mode": "BUDGET", "waves": 3, "totalEffortMedianJh": 612.4, "scopeClusters": ["cl-commandes-01","cl-facturation-02"] },
  "error": null
}
```

---

## 9. Stratégie de test

### Tests unitaires

Framework : **pytest** (backend) / **Vitest** (frontend).

| Composant à tester | Ce qui est testé | Ce qui est mocké | Priorité |
|---|---|---|---|
| `topological_sort()` | ordre respectant DEPENDS_ON ; détection de cycle | graphe (fixture) | P0 |
| `prioritize(mode)` | VALUE/RISK/BUDGET réordonnent correctement | nœuds + scoreD ADM-M | P0 |
| `validate_wave()` | 3 conditions de validité (cycle/état stable/valeur) | vague (fixture) | P0 |
| `estimate_effort()` | LOC × coeff_complexité × coeff_couplage × (1/coverage) | `EffortCalibration` | P0 |
| `estimate_duration()` | effort / (teamSize × WORKING_DAYS) → mois | — | P0 |
| `simulate_scenarios()` | 3 indicateurs cohérents par variante | plans générés | P1 |
| `detect_downstream_alerts()` | DONE → débloque les dépendants | graphe + statuts | P1 |
| `export_devops()` | mapping vagues→Epics, composants→Features | client Azure DevOps | P1 |
| `export_pptx()` | nb de slides = variantes + 1 comparaison | python-pptx | P1 |
| `GanttTimeline` (Vitest) | blocs colorés par 7R, groupes = vagues | plan (fixture) | P1 |

### Tests d'intégration

1. **Génération bout-en-bout (BUDGET)** : graphe qualifié → plan à 3 vagues, Vague 1 = RETIRE/REPURCHASE, effort total chiffré, états stables présents.
2. **Mode VALUE dépend d'ADM-M** : sans positions ADM-M → `ERR_MWP_004` ; avec positions → composants à forte différenciation priorisés tôt.
3. **Simulation** : 3 variantes → tableau comparatif sur les 3 indicateurs, recommandation produite.
4. **Pilotage** : `PUT /wave/status` DONE → alerte de déblocage downstream + recalcul de dérive.
5. **Export DevOps (mock)** : plan → 3 Epics + N Features créés (work item ids retournés).

### Fixture de données de test

```
tests/fixtures/mwp/
├── graph_nodes.json          # nœuds qualifiés (réponse ADG-M)
├── graph_arcs.json           # arcs (incluant un cycle à résoudre)
├── matrix_portfolio.json     # positions ADM-M (scoreD) pour mode VALUE
├── effort_calibration.json   # lignes EffortCalibration
└── expected_plan_budget.json # plan attendu en mode BUDGET (vagues + efforts)
```

### Critère "Done" du module

- [ ] Génération d'un plan à vagues valides (3 conditions) sur un graphe qualifié.
- [ ] Les 3 modes produisent des séquencements distincts et cohérents.
- [ ] L'effort par vague est chiffré (min/médian/max) avec référence de calibration.
- [ ] La simulation compare 3 variantes sur les 3 indicateurs.
- [ ] Le dashboard de pilotage met à jour les statuts et signale les déblocages.
- [ ] L'export DevOps crée Epics/Features ; l'export PowerPoint produit le deck.
- [ ] Tous les tests unitaires P0 passent.
- [ ] Scénario d'intégration 1 (génération BUDGET) passe en dev.

---

## 10. Questions ouvertes et hypothèses retenues

| # | Question | Hypothèse retenue pour ce SDD | Impact si fausse |
|---|---|---|---|
| 1 | Le tenant/organisation Azure DevOps cible existe-t-il ? | **[HYPOTHÈSE — à confirmer]** Organisation `retail-compagnie` / projet `Modernisation-SI` à créer ; export désactivable sinon. | Si absent : F4.6 DevOps reporté ; Markdown + PowerPoint suffisent à la démo. |
| 2 | Données de calibration Arkéa / Retail structurées ? | **[HYPOTHÈSE — à confirmer]** Lues depuis `EffortCalibration` (7RQA), valeurs indicatives à raffiner. | Chiffrages provisoires ; ajuster la table dès données réelles disponibles. |
| 3 | Calcul du pic de coût de double run | **[HYPOTHÈSE — à confirmer]** Proxy relatif (nb composants en double run × semaines de cohabitation), pas d'euros (OPEX indisponible). | Si euros requis : injecter coûts OPEX legacy/cible par composant. |
| 4 | Échelle du « niveau de risque maximal » (indicateur 3) | Score 0-100 = f(composants critiques en transition simultanée, SPOF non encore migrés, cohabitations actives). | Si méthode imposée différente : recalibrer la formule de risque. |
| 5 | Hypothèse d'équipe (ETP) pour la durée calendaire | Défaut 5 ETP, 20 j ouvrés/mois (configurable). | Modifier `DEFAULT_TEAM_SIZE` ; la durée calendaire s'ajuste linéairement. |
| 6 | Replanification manuelle (drag sur le Gantt) en v1 ? | Exclue (timeline en lecture seule) ; replanification via régénération. | Si requise : activer `editable` vis-timeline + endpoint `PUT /wave/plan`. |
