# SDD — Architecture Decision Matrix for Modernization (v1)
**Module** : ADM-M  **Priorité** : P1  **Dernière mise à jour** : 2026-06-06

---

## 1. Synthèse du module

**Rôle dans l'architecture globale** : ADM-M apporte la lecture **stratégique portefeuille** (macro) là où 7RQA travaille composant par composant (micro). Il positionne chaque composant sur un quadrant **Criticité métier × Différenciation métier** à partir de 12 critères évalués automatiquement (puis ajustables par l'architecte), dérive la palette 7R « naturelle » du quadrant, et génère des **ADR** (Architecture Decision Records) traçables depuis chaque décision validée. Il consomme les métriques ADG-M et les dossiers 7RQA, et alimente MWP : la position de différenciation sert au mode de priorisation « Valeur » du séquençage de vagues, et les ADR documentent les couches d'interopérabilité requises. C'est l'instrument qui rend la stratégie de patrimoine lisible « d'un coup d'œil » et défendable en CoDir IT.

**Dépendances en entrée** :
- **ADG-M** via `GET /api/v1/graph/nodes/{nodeId}` (`TechnicalNode` + métriques), `GET /api/v1/graph/nodes` (portefeuille), `GET /api/v1/graph/arcs` (couplage C1/C2/D5), `GET /api/v1/graph/nodes/{nodeId}/impact` (C5 SPOF downstream), `GET /api/v1/graph/clusters` (appartements impactés dans l'ADR).
- **7RQA** via `GET /api/v1/qualify/report/{reportId}` et `GET /api/v1/qualify/reports?nodeId=` — alternatives écartées et lien 7RQA dans l'ADR.
- **Azure OpenAI GPT-4o** — critères nécessitant une analyse textuelle (D1 SaaS, D4 unicité processus, D6 propriété intellectuelle).

**Dépendances en sortie** :
- **ADG-M** via `PATCH /api/v1/graph/nodes/{nodeId}/qualification` (`source=ADM-M`) — écrit la 7R retenue lors de la validation d'un positionnement (F3.5).
- **7RQA** consomme `GET /api/v1/matrix/position/{nodeId}` (appel optionnel d'enrichissement, déjà référencé dans `SDD_7RQA_v1.md §7`).
- **MWP** consomme `GET /api/v1/matrix/portfolio` (score de différenciation pour le mode « Valeur ») et `GET /api/v1/matrix/adr/{adrId}` (couches d'interopérabilité documentées).

**Périmètre v1 — inclus** :
- Calcul des 12 critères (D1-D6, C1-C6) avec confiance par critère (F3.1).
- Positionnement quadrant + palette 7R naturelle.
- Pondération personnalisable sauvegardée en profil projet (F3.2).
- Vue portefeuille filtrable (F3.3).
- Traçabilité/versioning des repositionnements (F3.4).
- Génération d'ADR Markdown + export Blob (F3.5).

**Périmètre v1 — exclus** (et pourquoi) :
- **Export automatique vers Azure DevOps Wiki** : v1 exporte l'ADR en Markdown sur Blob ; l'intégration Wiki (API Azure DevOps) est mutualisée avec MWP F4.6 et traitée là-bas pour éviter deux connecteurs DevOps.
- **Détection automatique avancée de la propriété intellectuelle (D6)** : v1 s'appuie sur le raisonnement GPT-4o à partir de la rétro-doc ; pas d'analyse de code source brute (hors périmètre ArchiMind).
- **Recalcul temps réel à chaque modification du graphe** : le positionnement est recalculé à la demande (`POST /matrix/position`), pas en streaming.

---

## 2. Schémas de données

### 2.1 Modèle Neo4j

ADM-M **ne crée ni ne modifie aucun nœud/relation directement**. Lecture via l'API ADG-M ; écriture de la 7R retenue exclusivement via `PATCH /graph/nodes/{nodeId}/qualification`. Aucune contrainte/index Neo4j propre.

### 2.2 Schémas Azure SQL

ADM-M est propriétaire des tables de matrice, de profils de pondération, des historiques de positionnement et des ADR. Base : `modernagent_db`.

```sql
-- Script de création : ADM-M — Azure SQL Database
-- À exécuter dans la base modernagent_db (après ADG-M et 7RQA)

-- 1) Profils de pondération réutilisables (F3.2)
CREATE TABLE [dbo].[MatrixProfile] (
    [profileId]        UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID(),
    [name]             NVARCHAR(128)    NOT NULL,
    [weightsJson]      NVARCHAR(MAX)    NOT NULL,   -- { "D1":0.17,...,"C3":0.30,... } somme D=1 et somme C=1
    [isDefault]        BIT              NOT NULL DEFAULT 0,
    [author]           NVARCHAR(128)    NOT NULL,
    [createdAt]        DATETIME2(0)     NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT [PK_MatrixProfile] PRIMARY KEY CLUSTERED ([profileId] ASC),
    CONSTRAINT [UQ_MatrixProfile_name] UNIQUE ([name])
);

-- 2) Positionnement courant d'un composant sur le quadrant (F3.1)
CREATE TABLE [dbo].[MatrixPosition] (
    [positionId]       UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID(),
    [nodeId]           NVARCHAR(64)     NOT NULL,   -- TechnicalNode ADG-M
    [componentName]    NVARCHAR(128)    NOT NULL,
    [profileId]        UNIQUEIDENTIFIER NOT NULL,
    [scoreD]           DECIMAL(4,2)     NOT NULL,   -- 0.00 - 10.00 (différenciation)
    [scoreC]           DECIMAL(4,2)     NOT NULL,   -- 0.00 - 10.00 (criticité)
    [quadrant]         NVARCHAR(24)     NOT NULL,   -- CORE_CRITIQUE|COMMODITE_CRITIQUE|DIFFERENCIANT_NON_CRITIQUE|CONTEXT_NON_CRITIQUE
    [palette7R]        NVARCHAR(64)     NOT NULL,   -- ex : "REFACTOR,REBUILD"
    [status]           NVARCHAR(12)     NOT NULL DEFAULT 'DRAFT', -- DRAFT|VALIDATED
    [validated7R]      NVARCHAR(16)     NULL,        -- 7R retenue à la validation
    [version]          INT              NOT NULL DEFAULT 1,
    [author]           NVARCHAR(128)    NOT NULL,
    [createdAt]        DATETIME2(0)     NOT NULL DEFAULT SYSUTCDATETIME(),
    [updatedAt]        DATETIME2(0)     NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT [PK_MatrixPosition] PRIMARY KEY CLUSTERED ([positionId] ASC),
    CONSTRAINT [FK_MatrixPos_Profile] FOREIGN KEY ([profileId]) REFERENCES [dbo].[MatrixProfile]([profileId])
);
CREATE UNIQUE INDEX [UX_MatrixPos_node_current] ON [dbo].[MatrixPosition] ([nodeId]); -- 1 position courante / nœud

-- 3) Score détaillé par critère (12 lignes par position)
CREATE TABLE [dbo].[MatrixCriterionScore] (
    [id]               UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID(),
    [positionId]       UNIQUEIDENTIFIER NOT NULL,
    [criterion]        NVARCHAR(4)      NOT NULL,   -- D1..D6, C1..C6
    [axis]             NVARCHAR(1)      NOT NULL,   -- D | C
    [agentScore]       DECIMAL(4,2)     NOT NULL,   -- 0-10 calculé par l'agent
    [overrideScore]    DECIMAL(4,2)     NULL,        -- ajustement architecte
    [effectiveScore]   AS (COALESCE([overrideScore],[agentScore])) PERSISTED,
    [weight]           DECIMAL(5,4)     NOT NULL,   -- issu du profil
    [confidence]       NVARCHAR(10)     NOT NULL,   -- ELEVEE|MOYENNE|FAIBLE
    [note]             NVARCHAR(MAX)    NULL,
    CONSTRAINT [PK_MatrixCriterionScore] PRIMARY KEY CLUSTERED ([id] ASC),
    CONSTRAINT [FK_MatrixCrit_Pos] FOREIGN KEY ([positionId])
        REFERENCES [dbo].[MatrixPosition]([positionId]) ON DELETE CASCADE
);
CREATE INDEX [IX_MatrixCrit_pos] ON [dbo].[MatrixCriterionScore] ([positionId]);

-- 4) Historique des repositionnements (F3.4)
CREATE TABLE [dbo].[MatrixPositionHistory] (
    [historyId]        UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID(),
    [nodeId]           NVARCHAR(64)     NOT NULL,
    [version]          INT              NOT NULL,
    [scoreD]           DECIMAL(4,2)     NOT NULL,
    [scoreC]           DECIMAL(4,2)     NOT NULL,
    [quadrant]         NVARCHAR(24)     NOT NULL,
    [validated7R]      NVARCHAR(16)     NULL,
    [changeReason]     NVARCHAR(MAX)    NULL,
    [author]           NVARCHAR(128)    NOT NULL,
    [createdAt]        DATETIME2(0)     NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT [PK_MatrixPositionHistory] PRIMARY KEY CLUSTERED ([historyId] ASC)
);
CREATE INDEX [IX_MatrixHist_node] ON [dbo].[MatrixPositionHistory] ([nodeId], [version] DESC);

-- 5) ADR générés (F3.5)
CREATE TABLE [dbo].[Adr] (
    [adrId]            UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID(),
    [adrNumber]        INT              NOT NULL,   -- numéro séquentiel global (ADR-0001...)
    [nodeId]           NVARCHAR(64)     NOT NULL,
    [componentName]    NVARCHAR(128)    NOT NULL,
    [status]           NVARCHAR(12)     NOT NULL DEFAULT 'PROPOSE', -- PROPOSE|ACCEPTE|DEPRECIE
    [trajectory7R]     NVARCHAR(16)     NOT NULL,
    [scoreD]           DECIMAL(4,2)     NOT NULL,
    [scoreC]           DECIMAL(4,2)     NOT NULL,
    [qualificationReportId] UNIQUEIDENTIFIER NULL,  -- lien 7RQA
    [markdownContent]  NVARCHAR(MAX)    NOT NULL,
    [blobPath]         NVARCHAR(512)    NULL,        -- export Blob
    [author]           NVARCHAR(128)    NOT NULL,
    [createdAt]        DATETIME2(0)     NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT [PK_Adr] PRIMARY KEY CLUSTERED ([adrId] ASC),
    CONSTRAINT [UQ_Adr_number] UNIQUE ([adrNumber])
);
CREATE INDEX [IX_Adr_node] ON [dbo].[Adr] ([nodeId], [createdAt] DESC);

-- Profil par défaut (pondération uniforme : chaque critère pèse 1/6 sur son axe)
INSERT INTO [dbo].[MatrixProfile] (name, weightsJson, isDefault, author) VALUES
 ('Uniforme',
  '{"D1":0.1667,"D2":0.1667,"D3":0.1667,"D4":0.1667,"D5":0.1667,"D6":0.1665,"C1":0.1667,"C2":0.1667,"C3":0.1667,"C4":0.1667,"C5":0.1667,"C6":0.1665}',
  1, 'system');
```

### 2.3 Objets de transfert inter-modules (DTOs)

```typescript
// DTO : MatrixPosition — produit par ADM-M, consommé par 7RQA (enrichissement) et MWP (mode Valeur)
interface MatrixPosition {
  positionId: string;
  nodeId: string;
  componentName: string;
  profileId: string;
  scoreD: number;              // 0-10 différenciation
  scoreC: number;              // 0-10 criticité
  quadrant: Quadrant;
  palette7R: SevenR[];         // palette naturelle du quadrant
  status: "DRAFT" | "VALIDATED";
  validated7R: SevenR | null;
  version: number;
  criteria: MatrixCriterionScore[]; // 12 entrées
  author: string;
  createdAt: string;
  updatedAt: string;
}

type Quadrant = "CORE_CRITIQUE" | "COMMODITE_CRITIQUE"
              | "DIFFERENCIANT_NON_CRITIQUE" | "CONTEXT_NON_CRITIQUE";
type SevenR = "RETIRE" | "RETAIN" | "REHOST" | "REPLATFORM"
            | "REPURCHASE" | "REFACTOR" | "REBUILD";

interface MatrixCriterionScore {
  criterion: "D1"|"D2"|"D3"|"D4"|"D5"|"D6"|"C1"|"C2"|"C3"|"C4"|"C5"|"C6";
  axis: "D" | "C";
  agentScore: number;          // 0-10
  overrideScore: number | null;
  effectiveScore: number;      // override ?? agent
  weight: number;              // issu du profil
  confidence: "ELEVEE" | "MOYENNE" | "FAIBLE";
  note: string | null;
}

// DTO : Adr — produit par ADM-M, consommé par MWP (couches interop) et export
interface Adr {
  adrId: string;
  adrNumber: number;           // ADR-0001
  nodeId: string;
  componentName: string;
  status: "PROPOSE" | "ACCEPTE" | "DEPRECIE";
  trajectory7R: SevenR;
  scoreD: number;
  scoreC: number;
  qualificationReportId: string | null;
  markdownContent: string;
  blobPath: string | null;
  author: string;
  createdAt: string;
}

// DTO : PortfolioItem — élément de GET /matrix/portfolio (consommé par MWP)
interface PortfolioItem {
  nodeId: string;
  componentName: string;
  scoreD: number;
  scoreC: number;
  quadrant: Quadrant;
  validated7R: SevenR | null;
  status: "DRAFT" | "VALIDATED";
}
```

---

## 3. Contrats d'API REST

Base URL : `https://{{AZURE_FUNCTION_APP_NAME}}.azurewebsites.net/api/v1`
Authentification : `Authorization: Bearer {{TOKEN}}`.

### `POST /matrix/position/{nodeId}`

**Description** : Calcule (ou recalcule) la position d'un composant sur le quadrant à partir des 12 critères, en appliquant un profil de pondération. Crée la position en statut `DRAFT`.

**Request body** :
```json
{
  "profileId?": "string — profil de pondération (défaut : profil 'Uniforme')",
  "author": "string — UPN"
}
```
Exemple de valeur réaliste :
```json
{
  "profileId": "11111111-1111-1111-1111-111111111111",
  "author": "v.gicquiau@retail-compagnie.fr"
}
```

**Response 200** :
```json
{
  "positionId": "c0ffee00-1234-4abc-9def-0123456789ab",
  "nodeId": "7a3f9c12-4b8e-4d21-9f6a-2c1e5d8b0a44",
  "componentName": "GESTION-COMMANDE",
  "profileId": "11111111-1111-1111-1111-111111111111",
  "scoreD": 6.80,
  "scoreC": 8.20,
  "quadrant": "CORE_CRITIQUE",
  "palette7R": ["REFACTOR", "REBUILD"],
  "status": "DRAFT",
  "validated7R": null,
  "version": 1,
  "criteria": [
    { "criterion": "D1", "axis": "D", "agentScore": 8.0, "overrideScore": null, "effectiveScore": 8.0, "weight": 0.1667, "confidence": "MOYENNE", "note": "Aucun SaaS mature sur les règles de remise B2B" },
    { "criterion": "D2", "axis": "D", "agentScore": 7.5, "overrideScore": null, "effectiveScore": 7.5, "weight": 0.1667, "confidence": "ELEVEE", "note": "Règles de gestion fortement personnalisées" },
    { "criterion": "D3", "axis": "D", "agentScore": 5.0, "overrideScore": null, "effectiveScore": 5.0, "weight": 0.1667, "confidence": "FAIBLE", "note": "Backlog d'évolution indisponible : estimation" },
    { "criterion": "D4", "axis": "D", "agentScore": 6.0, "overrideScore": null, "effectiveScore": 6.0, "weight": 0.1667, "confidence": "MOYENNE", "note": "Processus de prise de commande semi-spécifique" },
    { "criterion": "D5", "axis": "D", "agentScore": 7.0, "overrideScore": null, "effectiveScore": 7.0, "weight": 0.1667, "confidence": "ELEVEE", "note": "3 canaux clients dépendants (web, EDI, agence)" },
    { "criterion": "D6", "axis": "D", "agentScore": 7.5, "overrideScore": null, "effectiveScore": 7.5, "weight": 0.1665, "confidence": "MOYENNE", "note": "Algorithme de remise propriétaire" },
    { "criterion": "C1", "axis": "C", "agentScore": 9.0, "overrideScore": null, "effectiveScore": 9.0, "weight": 0.1667, "confidence": "ELEVEE", "note": "Dans le flux de valeur 'commande -> facturation'" },
    { "criterion": "C2", "axis": "C", "agentScore": 8.0, "overrideScore": null, "effectiveScore": 8.0, "weight": 0.1667, "confidence": "ELEVEE", "note": "In-degree pondéré élevé (criticalityScore 27)" },
    { "criterion": "C3", "axis": "C", "agentScore": 7.0, "overrideScore": null, "effectiveScore": 7.0, "weight": 0.1667, "confidence": "ELEVEE", "note": "BCBS239 présent" },
    { "criterion": "C4", "axis": "C", "agentScore": 8.5, "overrideScore": null, "effectiveScore": 8.5, "weight": 0.1667, "confidence": "MOYENNE", "note": "~120 000 commandes/jour (rétro-doc)" },
    { "criterion": "C5", "axis": "C", "agentScore": 9.0, "overrideScore": null, "effectiveScore": 9.0, "weight": 0.1667, "confidence": "ELEVEE", "note": "SPOF : 14 composants downstream impactés" },
    { "criterion": "C6", "axis": "C", "agentScore": 7.5, "overrideScore": null, "effectiveScore": 7.5, "weight": 0.1665, "confidence": "MOYENNE", "note": "Données clients (PII)" }
  ],
  "author": "v.gicquiau@retail-compagnie.fr",
  "createdAt": "2026-06-06T23:05:00Z",
  "updatedAt": "2026-06-06T23:05:00Z"
}
```

| Code | Condition | Message retourné |
|---|---|---|
| 404 | `nodeId` inexistant dans ADG-M | `{"error": "Composant introuvable dans le graphe"}` |
| 404 | `profileId` inexistant | `{"error": "Profil de pondération introuvable"}` |
| 422 | Critères textuels non calculables (rétro-doc absente) | `{"error": "Données insuffisantes pour D1/D4/D6", "details": ["rétro-doc manquante"]}` |
| 502 | GPT-4o indisponible | `{"error": "Service d'analyse indisponible. Réessayer."}` |
| 500 | Erreur interne | `{"error": "Erreur interne. Réessayer ou contacter le support."}` |

---

### `GET /matrix/position/{nodeId}`

**Description** : Retourne la position courante d'un composant + son historique. **Endpoint consommé optionnellement par 7RQA** (`SDD_7RQA_v1.md §7`) — 404 toléré si non positionné.

**Response 200** : objet `MatrixPosition` (cf. ci-dessus) + champ `history`:
```json
{
  "position": { "...": "objet MatrixPosition" },
  "history": [
    { "version": 1, "scoreD": 6.80, "scoreC": 8.20, "quadrant": "CORE_CRITIQUE", "validated7R": null, "changeReason": "Positionnement initial", "author": "v.gicquiau@retail-compagnie.fr", "createdAt": "2026-06-06T23:05:00Z" }
  ]
}
```

| Code | Condition | Message retourné |
|---|---|---|
| 404 | Composant jamais positionné | `{"error": "Aucun positionnement pour ce composant"}` |
| 500 | Erreur interne | `{"error": "Erreur interne. Réessayer ou contacter le support."}` |

---

### `PUT /matrix/position/{nodeId}`

**Description** : Ajuste les scores de critères (surcharge architecte) et/ou valide le positionnement. La validation incrémente la version, historise, et propage la 7R retenue vers ADG-M (`PATCH .../qualification`, `source=ADM-M`).

**Request body** :
```json
{
  "criterionOverrides?": [ { "criterion": "string D1..C6", "overrideScore": "number 0-10", "note": "string" } ],
  "validate?": "boolean — true pour passer en VALIDATED",
  "validated7R?": "string — 7R retenue (requis si validate=true), doit appartenir à la palette ou être justifiée",
  "changeReason": "string — motif du repositionnement / de la validation",
  "author": "string — UPN"
}
```
Exemple de valeur réaliste :
```json
{
  "criterionOverrides": [ { "criterion": "D3", "overrideScore": 7.0, "note": "Backlog réel : 12 évolutions/an, forte fréquence" } ],
  "validate": true,
  "validated7R": "REFACTOR",
  "changeReason": "Validation COMEX : composant cœur critique, refactor prioritaire (aligne le macro ADM-M et arbitre le Rehost conservateur de 7RQA).",
  "author": "v.gicquiau@retail-compagnie.fr"
}
```

**Response 200** :
```json
{
  "positionId": "c0ffee00-1234-4abc-9def-0123456789ab",
  "scoreD": 7.13,
  "scoreC": 8.20,
  "quadrant": "CORE_CRITIQUE",
  "status": "VALIDATED",
  "validated7R": "REFACTOR",
  "version": 2,
  "graphUpdate": { "nodeId": "7a3f9c12-...", "candidate7R": "REFACTOR", "annotationId": "fa12..." }
}
```

| Code | Condition | Message retourné |
|---|---|---|
| 400 | `overrideScore` hors [0,10] ou critère inconnu | `{"error": "Score de critère invalide"}` |
| 422 | `validate=true` sans `validated7R` ou sans `changeReason` | `{"error": "Validation incomplète", "details": ["validated7R requis"]}` |
| 404 | Position inexistante (créer d'abord via POST) | `{"error": "Positionner le composant avant de l'ajuster"}` |
| 502 | Propagation ADG-M échouée | `{"error": "Position enregistrée mais propagation au graphe échouée."}` |
| 500 | Erreur interne | `{"error": "Erreur interne. Réessayer ou contacter le support."}` |

---

### `GET /matrix/portfolio`

**Description** : Retourne tous les composants positionnés (vue portefeuille F3.3). **Consommé par MWP** pour le mode de priorisation « Valeur ».

**Query params** : `domain`, `quadrant`, `status`, `technology`, `validated7R`.

**Response 200** :
```json
{
  "total": 38,
  "distribution": { "CORE_CRITIQUE": 9, "COMMODITE_CRITIQUE": 14, "DIFFERENCIANT_NON_CRITIQUE": 6, "CONTEXT_NON_CRITIQUE": 9 },
  "items": [
    { "nodeId": "7a3f9c12-...", "componentName": "GESTION-COMMANDE", "scoreD": 7.13, "scoreC": 8.20, "quadrant": "CORE_CRITIQUE", "validated7R": "REFACTOR", "status": "VALIDATED" },
    { "nodeId": "3e9a...", "componentName": "EDITION-BORDEREAU", "scoreD": 2.40, "scoreC": 4.10, "quadrant": "CONTEXT_NON_CRITIQUE", "validated7R": "RETIRE", "status": "VALIDATED" }
  ]
}
```

| Code | Condition | Message retourné |
|---|---|---|
| 400 | Filtre enum invalide | `{"error": "Paramètre de filtre invalide"}` |
| 500 | Erreur interne | `{"error": "Erreur interne. Réessayer ou contacter le support."}` |

---

### `POST /matrix/profile` / `GET /matrix/profiles`

**Description** : Crée un profil de pondération réutilisable (F3.2) / liste les profils.

**Request body** (`POST`) :
```json
{
  "name": "string — nom du profil",
  "weights": "objet { D1..D6, C1..C6 } — somme des D = 1, somme des C = 1",
  "author": "string"
}
```
Exemple de valeur réaliste (profil bancaire DORA) :
```json
{
  "name": "Banque DORA",
  "weights": { "D1":0.15,"D2":0.20,"D3":0.15,"D4":0.15,"D5":0.20,"D6":0.15, "C1":0.15,"C2":0.10,"C3":0.30,"C4":0.15,"C5":0.20,"C6":0.10 },
  "author": "v.gicquiau@retail-compagnie.fr"
}
```

**Response 200** : `{ "profileId": "...", "name": "Banque DORA" }`

| Code | Condition | Message retourné |
|---|---|---|
| 422 | Somme des poids D ≠ 1 ou C ≠ 1 (tolérance ±0.01) | `{"error": "Les poids de chaque axe doivent sommer à 1", "details": ["sum(D)=0.95"]}` |
| 409 | Nom déjà utilisé | `{"error": "Un profil porte déjà ce nom"}` |
| 500 | Erreur interne | `{"error": "Erreur interne. Réessayer ou contacter le support."}` |

---

### `POST /matrix/adr/generate/{nodeId}`

**Description** : Génère un ADR Markdown depuis la position validée + le rapport 7RQA, le persiste et l'exporte sur Blob (F3.5).

**Request body** :
```json
{
  "status?": "string — PROPOSE (défaut) | ACCEPTE",
  "author": "string"
}
```

**Response 200** :
```json
{
  "adrId": "ad120000-aaaa-4bbb-8ccc-000000000001",
  "adrNumber": 7,
  "nodeId": "7a3f9c12-4b8e-4d21-9f6a-2c1e5d8b0a44",
  "componentName": "GESTION-COMMANDE",
  "trajectory7R": "REFACTOR",
  "status": "PROPOSE",
  "blobPath": "adr/ADR-0007-GESTION-COMMANDE.md",
  "markdownContent": "# ADR-0007 — GESTION-COMMANDE\n**Date** : 2026-06-06  **Statut** : PROPOSÉ\n..."
}
```

Gabarit Markdown produit (conforme specs F3.5) :
```markdown
# ADR-0007 — GESTION-COMMANDE
**Date** : 2026-06-06  **Statut** : PROPOSÉ
**Décideur(s)** : v.gicquiau@retail-compagnie.fr

## Contexte
COBOL, 18 420 lignes, criticalityScore 27, in-degree 8 / out-degree 12, couverture rétro-doc 72%, SPOF (14 composants downstream).

## Décision
**Trajectoire 7R retenue** : REFACTOR
**Position quadrant** : Criticité 8.2/10 × Différenciation 7.1/10 (CORE_CRITIQUE)

## Justification
Synthèse des 12 critères : différenciation portée par D2 (règles personnalisées) et D6 (algorithme de remise propriétaire) ; criticité portée par C1 (flux de valeur), C5 (SPOF) et C3 (BCBS239).

## Conséquences
- Impact sur le graphe de dépendances : 14 nœuds downstream
- Appartements impactés (MWP) : cl-commandes-01
- Couche d'interopérabilité requise : OUI (API façade durant la cohabitation)

## Alternatives écartées
[Depuis le rapport 7RQA 5f2c8a10-...] REBUILD (BCBS239 sans plan de continuité), RETIRE (cœur métier), REPURCHASE (pas de SaaS mature).

## Lien 7RQA
Rapport de qualification : 5f2c8a10-9b44-4e07-8c1d-77a0f3e6b201
```

| Code | Condition | Message retourné |
|---|---|---|
| 409 | Position non validée | `{"error": "Valider le positionnement avant de générer l'ADR"}` |
| 404 | Composant inexistant | `{"error": "Composant introuvable"}` |
| 500 | Erreur interne | `{"error": "Erreur interne. Réessayer ou contacter le support."}` |

---

### `GET /matrix/adr/{adrId}`

**Description** : Retourne un ADR (objet `Adr`). Consommé par MWP (couches d'interopérabilité).

| Code | Condition | Message retourné |
|---|---|---|
| 404 | ADR inexistant | `{"error": "ADR introuvable"}` |
| 500 | Erreur interne | `{"error": "Erreur interne. Réessayer ou contacter le support."}` |

---

## 4. Infrastructure Azure

### Ressources à provisionner

| Ressource | Nom recommandé | SKU / Tier | Config clé | Coût estimé/mois |
|---|---|---|---|---|
| Azure Functions | `modernagent-admm-dev` | Consumption (Y1) Python 3.11 | Runtime v4 | ~0 € (grant 1M exéc.) |
| Azure SQL Database | `modernagent-sql-dev` / `modernagent_db` | Basic (partagé) | Tables matrice + ADR | 0 € (déjà compté) |
| Azure OpenAI | `modernagent-openai` (existant) | Déploiement GPT-4o | Critères D1/D4/D6 (analyse texte) | ~5-15 € (usage dev) |
| Azure Blob Storage | `modernagentstgdev` (partagé) | Standard LRS | Container `adr` (export Markdown) | ~0 € (négligeable) |
| Azure AI Search | (RAG existant) | Free/Basic | Lecture rétro-doc + catalogue SaaS | 0 € (réutilisé) |
| Application Insights | `modernagent-ai-dev` (partagé) | Pay-as-you-go (5 Go gratuits) | Traces | ~0 € |

### Variables d'environnement et secrets

```env
# ADM-M — Variables d'environnement
# Fichier : .env (ne jamais committer ; en prod -> Azure Key Vault)

ADGM_API_BASE_URL=http://localhost:7071/api/v1
SEVENRQA_API_BASE_URL=http://localhost:7072/api/v1

SQL_CONNECTION_STRING=Driver={ODBC Driver 18 for SQL Server};Server=tcp:modernagent-sql-dev.database.windows.net,1433;Database=modernagent_db;Authentication=ActiveDirectoryDefault;Encrypt=yes;

AZURE_OPENAI_ENDPOINT=https://modernagent-openai.openai.azure.com/
AZURE_OPENAI_API_KEY=<secret>
AZURE_OPENAI_DEPLOYMENT_GPT4O=gpt-4o
AZURE_OPENAI_API_VERSION=2024-10-21

AZURE_SEARCH_ENDPOINT=https://modernagent-search.search.windows.net
AZURE_SEARCH_API_KEY=<secret>
AZURE_SEARCH_INDEX=archimind-retrodocs

BLOB_ACCOUNT_URL=https://modernagentstgdev.blob.core.windows.net
BLOB_CONTAINER_ADR=adr

AAD_TENANT_ID=<tenant-guid>
AAD_API_CLIENT_ID=<app-registration-guid>

# --- Tuning quadrant ---
QUADRANT_THRESHOLD=5.0          # seuil D/C de bascule entre quadrants (médiane 0-10)
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

> **Prérequis bloquant** : ADG-M démarré (graphe + métriques) et 7RQA accessible (lien ADR). ADM-M peut fonctionner en mode dégradé sans 7RQA (ADR sans section « Alternatives écartées »).

### Mise en place de l'environnement

```powershell
# 1. Backend ADM-M
Set-Location .\modernization-agent\backend\admm
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt   # openai, pyodbc, httpx, azure-storage-blob, azure-search-documents

# 2. DDL SQL ADM-M (après ADG-M et 7RQA)
az login
sqlcmd -S modernagent-sql-dev.database.windows.net -d modernagent_db -G -i .\db\admm_schema.sql

# 3. Environnement
Copy-Item .\.env.example .\.env
# -> éditer ADGM_API_BASE_URL, SEVENRQA_API_BASE_URL, BLOB_CONTAINER_ADR

# 4. Créer le container Blob 'adr' (une fois) — via portail Azure ou az storage container create
```

### Démarrage en mode développement

```powershell
# Pré-requis : Neo4j + ADG-M (7071) + 7RQA (7072) démarrés

# Terminal : backend ADM-M
Set-Location .\backend\admm
.\.venv\Scripts\Activate.ps1
func start --port 7073   # http://localhost:7073/api/v1/matrix/...

# Frontend déjà lancé (vues quadrant intégrées)
```

### Vérification de l'environnement

```powershell
# 1. Positionner un composant (doit retourner scoreD/scoreC/quadrant)
$body = @{ author = "dev@local" } | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:7073/api/v1/matrix/position/7a3f9c12-4b8e-4d21-9f6a-2c1e5d8b0a44" `
  -Method POST -Body $body -ContentType "application/json"

# 2. Vue portefeuille
Invoke-RestMethod -Uri "http://localhost:7073/api/v1/matrix/portfolio" -Method GET
```

---

## 6. Architecture des composants frontend

### Arbre des composants React

```
App
└── MatrixPage — page principale du quadrant
    ├── MatrixToolbar — sélection profil, filtres, bascule single/portefeuille
    │   ├── ProfileSelector — profils de pondération (F3.2)
    │   └── PortfolioFilters — domaine / quadrant / techno / statut
    ├── QuadrantCanvas — quadrant interactif D3.js (drag-and-drop)
    │   ├── QuadrantAxes — axes Criticité (Y) × Différenciation (X) + libellés de quadrant
    │   ├── ComponentDot (× n) — point (D,C), couleur = 7R validée/palette
    │   └── PaletteOverlay — palette 7R naturelle du quadrant survolé
    ├── ScoringPanel — détail des 12 critères du composant sélectionné
    │   ├── DifferentiationCriteria — D1..D6 (score agent / surcharge / confiance / note)
    │   └── CriticalityCriteria — C1..C6
    ├── PositionHistory — timeline des repositionnements (F3.4)
    └── AdrPanel — génération + aperçu Markdown de l'ADR (F3.5)
```

### Gestion de l'état

| Données | Localisation | Type de state | Justification |
|---|---|---|---|
| Composant sélectionné | `MatrixPage` | `useState` | Pilote ScoringPanel, History, AdrPanel |
| Positions du portefeuille | `MatrixPage` | React Query | Cache serveur + invalidation au repositionnement |
| Surcharges de critères en cours | `ScoringPanel` | `useReducer` | Édition locale avant PUT |
| Profil actif | `MatrixToolbar` | Context (`ProfileContext`) | Partagé entre toolbar et calcul de position |
| Drag-and-drop temporaire | `QuadrantCanvas` | state interne D3 + `useRef` | Position visuelle avant persistance |
| Token Azure AD | `AuthProvider` (MSAL) | Context | Appels API |

### Configuration de la librairie de visualisation

```typescript
// Configuration D3.js — quadrant Criticité × Différenciation
// Fichier : src/config/quadrant.config.ts

import { R7_COLORS } from "./cytoscape.config"; // palette 7R partagée (cohérence ADG-M)

export const QUADRANT_THRESHOLD = 5.0; // bascule entre quadrants (cf. .env)

export const quadrantLabels = {
  CORE_CRITIQUE:              { x: "high", y: "high", title: "Cœur critique",        palette: ["REFACTOR","REBUILD"] },
  COMMODITE_CRITIQUE:         { x: "low",  y: "high", title: "Commodité critique",   palette: ["REHOST","REPLATFORM"] },
  DIFFERENCIANT_NON_CRITIQUE: { x: "high", y: "low",  title: "Différenciant non critique", palette: ["RETAIN","REFACTOR"] },
  CONTEXT_NON_CRITIQUE:       { x: "low",  y: "low",  title: "Context non critique", palette: ["RETIRE","REPURCHASE"] },
} as const;

export const quadrantConfig = {
  width: 720, height: 720, margin: 48,
  xDomain: [0, 10],  // Différenciation
  yDomain: [0, 10],  // Criticité
  dotRadius: 8,
  colorByValidated7R: R7_COLORS,
  dragEnabled: true, // drag = ajustement manuel (D,C) -> PUT au drop
};
```

---

## 7. Points d'intégration inter-modules

| Appelant | Endpoint appelé | Données envoyées | Données reçues | Déclencheur |
|---|---|---|---|---|
| ADM-M | `GET /graph/nodes/{nodeId}` (ADG-M) | `nodeId` | `TechnicalNode` + métriques | Calcul C2, contexte |
| ADM-M | `GET /graph/arcs?nodeId=` (ADG-M) | `nodeId` | arcs entrants/sortants | C1 (flux critiques), D5 (canaux) |
| ADM-M | `GET /graph/nodes/{nodeId}/impact` (ADG-M) | `nodeId` | downstream impactés | C5 (SPOF) |
| ADM-M | `GET /graph/clusters` (ADG-M) | — | clusters | « Appartements impactés » de l'ADR |
| ADM-M | `GET /qualify/reports?nodeId=` (7RQA) | `nodeId` | dernier rapport | Alternatives écartées + lien ADR |
| ADM-M | Azure OpenAI GPT-4o | descriptions fonctionnelles | scores D1/D4/D6 | Critères textuels F3.1 |
| ADM-M | `PATCH /graph/nodes/{nodeId}/qualification` (ADG-M) | 7R + `source=ADM-M` | nœud mis à jour | Validation position F3.5 |
| MWP | `GET /matrix/portfolio` (ADM-M) | filtres | scores D/C + 7R | Mode « Valeur » F4.1 |
| MWP | `GET /matrix/adr/{adrId}` (ADM-M) | `adrId` | ADR (interop) | Fiche de vague F4.2 |

> **Cohérence vérifiée** : tous les endpoints ADG-M référencés existent dans `SDD_ADG-M_v1.md §3` ; `GET /qualify/reports` existe dans `SDD_7RQA_v1.md §3`. La 7R écrite via `PATCH .../qualification` utilise le même contrat que 7RQA (champ `source` distinctif : `ADM-M`).

---

## 8. Gestion des erreurs

### Erreurs métier attendues

| Code d'erreur interne | Condition | Message utilisateur (FR) | Action recommandée |
|---|---|---|---|
| `ERR_ADMM_001` | Critère textuel non calculable (rétro-doc absente) | « Critères de différenciation incomplets : compléter manuellement D1/D4/D6. » | Surcharger les scores manquants |
| `ERR_ADMM_002` | Poids de profil ne sommant pas à 1 | « La somme des poids d'un axe doit valoir 1. » | Corriger la pondération |
| `ERR_ADMM_003` | ADR demandé sur position non validée | « Valider le positionnement avant de générer l'ADR. » | Valider la position |
| `ERR_ADMM_004` | 7R validée hors palette du quadrant | « La 7R choisie sort de la palette du quadrant : justification renforcée requise. » | Confirmer avec motif |
| `ERR_ADMM_005` | 7RQA indisponible à la génération d'ADR | « ADR généré sans section alternatives (7RQA indisponible). » | Régénérer plus tard |

### Stratégie de retry pour erreurs techniques

| Type d'erreur | Retry | Délai | Backoff | Fallback |
|---|---|---|---|---|
| Timeout Azure OpenAI (GPT-4o) | 2 tentatives | 2s, 5s | Linéaire | Critère en confiance FAIBLE + score neutre 5.0 |
| Appel ADG-M 5xx | 3 tentatives | 1s, 2s, 4s | Exponentiel | Log + erreur 502 |
| Appel 7RQA 5xx/404 | 1 tentative | 1s | — | ADR sans alternatives (`ERR_ADMM_005`) |
| Azure SQL indisponible | 3 tentatives | 1s, 3s, 9s | Exponentiel | Log + erreur 503 |
| Écriture Blob ADR échouée | 2 tentatives | 1s, 2s | Linéaire | ADR persisté en SQL, `blobPath=null` |

### Format de log structuré

```json
{
  "timestamp": "2026-06-06T23:05:10Z",
  "level": "INFO",
  "module": "ADM-M",
  "operation": "compute_position",
  "correlationId": "c0ffee00-1234-4abc-9def-0123456789ab",
  "message": "Position calculée",
  "data": { "nodeId": "7a3f9c12-...", "scoreD": 6.8, "scoreC": 8.2, "quadrant": "CORE_CRITIQUE", "profileId": "1111..." },
  "error": null
}
```

---

## 9. Stratégie de test

### Tests unitaires

Framework : **pytest** (backend) / **Vitest** (frontend).

| Composant à tester | Ce qui est testé | Ce qui est mocké | Priorité |
|---|---|---|---|
| `score_criterion_C2()` | in-degree → score 0-10 | métriques ADG-M | P0 |
| `score_criterion_C5()` | impactedCount → score SPOF | `/impact` ADG-M | P0 |
| `score_criterion_D1()` | présence SaaS → score différenciation inverse | réponse GPT-4o figée | P1 |
| `compute_axis_score()` | Σ(score × poids) normalisé 0-10 | scores + profil | P0 |
| `assign_quadrant()` | (D,C) vs seuil → quadrant + palette | — | P0 |
| `generate_adr()` | gabarit ADR conforme F3.5 + numérotation | position + rapport 7RQA | P0 |
| `validate_weights()` | somme par axe = 1 (±0.01) | — | P0 |
| `QuadrantCanvas` (Vitest) | placement des points + drag → PUT | données portefeuille | P1 |
| `ScoringPanel` (Vitest) | surcharge de critère recalcule l'aperçu | client API | P1 |

### Tests d'intégration

1. **Positionnement bout-en-bout** : `POST /matrix/position/{nodeId}` → 12 critères calculés, quadrant CORE_CRITIQUE attendu pour GESTION-COMMANDE.
2. **Surcharge + validation** : `PUT` avec override D3 + `validate=true` → version 2, 7R propagée dans Neo4j, historique enregistré.
3. **Génération d'ADR** : `POST /matrix/adr/generate/{nodeId}` → ADR Markdown conforme, sections alternatives renseignées depuis 7RQA, fichier sur Blob.
4. **Profil pondéré** : créer « Banque DORA » (C3=0.30) → recalcul → scoreC augmente pour un composant tagué DORA/BCBS239.

### Fixture de données de test

```
tests/fixtures/admm/
├── node_metrics_gestion_commande.json   # réponse ADG-M (nœud + métriques + impact)
├── arcs_gestion_commande.json           # arcs (réponse ADG-M)
├── qualification_report.json            # réponse 7RQA (alternatives)
├── gpt4o_textual_criteria.json          # scores D1/D4/D6 figés
└── expected_position.json               # scoreD/scoreC/quadrant attendus
```

### Critère "Done" du module

- [ ] Positionnement d'un composant réel produit 12 scores + quadrant + palette cohérents.
- [ ] La surcharge d'un critère recalcule le score d'axe et peut changer de quadrant.
- [ ] La validation propage la 7R dans ADG-M et historise la version.
- [ ] L'ADR généré est conforme au gabarit F3.5 et exporté sur Blob.
- [ ] Un profil pondéré modifie effectivement les positions du portefeuille.
- [ ] Tous les tests unitaires P0 passent.
- [ ] Scénario d'intégration 1 (positionnement bout-en-bout) passe en dev.

---

## 10. Questions ouvertes et hypothèses retenues

| # | Question | Hypothèse retenue pour ce SDD | Impact si fausse |
|---|---|---|---|
| 1 | **Incohérence du quadrant dans les specs** : les libellés des coins de l'ASCII contredisent la direction des axes (ex : RETAIN « différenciant » placé côté basse différenciation). | **[HYPOTHÈSE — à confirmer]** Lecture Core/Context standard, **axes prioritaires** : CORE_CRITIQUE (D↑C↑)=REFACTOR/REBUILD ; COMMODITE_CRITIQUE (D↓C↑)=REHOST/REPLATFORM ; DIFFERENCIANT_NON_CRITIQUE (D↑C↓)=RETAIN/REFACTOR ; CONTEXT_NON_CRITIQUE (D↓C↓)=RETIRE/REPURCHASE. | Si l'intention des specs diffère : remapper `quadrantLabels` et `assign_quadrant()` — changement localisé, mais ADR et palettes affichées à revoir. |
| 2 | Source du critère D3 (fréquence d'évolution) : backlog disponible ? | **[HYPOTHÈSE — à confirmer]** Backlog indisponible en v1 → estimation GPT-4o depuis la rétro-doc, confiance FAIBLE. | Si backlog accessible : brancher un connecteur (Azure DevOps/Jira) → confiance ELEVEE pour D3. |
| 3 | Seuil de bascule entre quadrants | Seuil unique à 5.0 sur les deux axes (configurable `QUADRANT_THRESHOLD`). | Si seuils différenciés D/C souhaités : deux paramètres distincts + UI de réglage. |
| 4 | Numérotation des ADR : globale ou par domaine ? | Séquence globale `ADR-NNNN` (table `Adr.adrNumber` unique). | Si par domaine : changer le schéma de numérotation et la contrainte d'unicité. |
| 5 | Stockage cible des ADR (Blob seul, ou Azure DevOps Wiki) ? | Blob Markdown en v1 ; push Wiki mutualisé avec MWP F4.6. | Si Wiki requis dès v1 : avancer le connecteur DevOps depuis MWP. |
