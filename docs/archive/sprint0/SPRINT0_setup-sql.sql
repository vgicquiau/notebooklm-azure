-- ============================================================================
-- Azure SQL DDL pour Modernization Agent — Sprint 0
-- Base : modernagent_db
-- Exécuter via Azure Portal Query Editor ou via sqlcmd
-- ============================================================================

-- 1. Tables ADG-M (Graphe + Métriques)
-- Schema de base pour stocker les versions/historique du graphe

CREATE TABLE dbo.Component (
    id NVARCHAR(50) PRIMARY KEY,
    name NVARCHAR(255) NOT NULL,
    type NVARCHAR(50) NOT NULL,  -- System|Module|Service|Database|API
    description NVARCHAR(MAX),
    language NVARCHAR(50),
    sloc INT,
    businessValue NVARCHAR(20),  -- HIGH|MEDIUM|LOW
    criticality NVARCHAR(20),    -- CRITICAL|HIGH|MEDIUM|LOW
    owner NVARCHAR(100),
    lastUpdated DATETIME2 DEFAULT GETUTCDATE(),
    sourceFile NVARCHAR(500),    -- traceabilité rétro-doc
    createdAt DATETIME2 DEFAULT GETUTCDATE(),
    updatedAt DATETIME2 DEFAULT GETUTCDATE()
);

CREATE TABLE dbo.ComponentDependency (
    id INT PRIMARY KEY IDENTITY(1,1),
    sourceComponentId NVARCHAR(50) NOT NULL,
    targetComponentId NVARCHAR(50) NOT NULL,
    dependencyType NVARCHAR(50),  -- CALLS|DATABASE|FILE|NETWORK
    confidence FLOAT,              -- 0..1
    bidirectional BIT,
    createdAt DATETIME2 DEFAULT GETUTCDATE(),
    FOREIGN KEY (sourceComponentId) REFERENCES dbo.Component(id),
    FOREIGN KEY (targetComponentId) REFERENCES dbo.Component(id)
);

-- Indexes pour la jointure Neo4j ↔ SQL
CREATE UNIQUE INDEX idx_component_id ON dbo.Component(id);
CREATE INDEX idx_dependency_source ON dbo.ComponentDependency(sourceComponentId);
CREATE INDEX idx_dependency_target ON dbo.ComponentDependency(targetComponentId);

-- 2. Tables métriques ADG-M (peuplées par GDS post-calcul)
CREATE TABLE dbo.ComponentMetrics (
    componentId NVARCHAR(50) PRIMARY KEY,
    clusterId INT,                 -- Louvain community
    betweennessCentrality FLOAT,   -- SPOF indicator
    degreeeCentrality FLOAT,
    inDegree INT,
    outDegree INT,
    lastCalculatedAt DATETIME2 DEFAULT GETUTCDATE(),
    FOREIGN KEY (componentId) REFERENCES dbo.Component(id)
);

CREATE INDEX idx_metrics_cluster ON dbo.ComponentMetrics(clusterId);
CREATE INDEX idx_metrics_betweenness ON dbo.ComponentMetrics(betweennessCentrality DESC);

-- 3. Historique qualification (pour write-back 7R validation)
-- Linked from SDD ADG-M §3 PATCH /graph/nodes/{id}/qualification
CREATE TABLE dbo.QualificationValidation (
    id INT PRIMARY KEY IDENTITY(1,1),
    componentId NVARCHAR(50) NOT NULL,
    sevenRChoice NVARCHAR(50),     -- Retire|Retain|Rehost|Replatform|Repurchase|Refactor|Rebuild
    validationSource NVARCHAR(100), -- '7RQA'|'ADM-M'
    confidence NVARCHAR(20),        -- ELEVEE|MOYENNE|FAIBLE
    validatedAt DATETIME2 DEFAULT GETUTCDATE(),
    validatedBy NVARCHAR(100),
    notes NVARCHAR(MAX),
    FOREIGN KEY (componentId) REFERENCES dbo.Component(id)
);

-- 4. Placeholder pour EffortCalibration (partagée avec 7RQA + MWP)
-- Sera peuplée via T02 (fixture) ou Q4 (données réelles Arkéa/Retail)
CREATE TABLE dbo.EffortCalibration (
    id INT PRIMARY KEY IDENTITY(1,1),
    sevenROption NVARCHAR(50),     -- Retire|Retain|Rehost|Replatform|Repurchase|Refactor|Rebuild
    complexityLevel NVARCHAR(20),  -- LOW|MEDIUM|HIGH|CRITICAL
    kloc INT,                       -- Kilo Lines of Code reference
    estimatedDaysPerKloc FLOAT,    -- effort ratio j/KLOC
    source NVARCHAR(100),          -- 'Arkea-2025'|'RetailCie-2024'|'Seed-v1'
    notes NVARCHAR(MAX),
    createdAt DATETIME2 DEFAULT GETUTCDATE()
);

-- Seed v1 : placeholder pour démarrer sans données Arkéa/Retail
INSERT INTO dbo.EffortCalibration (sevenROption, complexityLevel, kloc, estimatedDaysPerKloc, source, notes)
VALUES
    ('Retire', 'LOW', 100, 1.0, 'Seed-v1', 'Minimal : retrait / archivage'),
    ('Retire', 'MEDIUM', 100, 1.5, 'Seed-v1', NULL),
    ('Retain', 'LOW', 100, 2.0, 'Seed-v1', 'Maintenance ongoing'),
    ('Retain', 'MEDIUM', 100, 3.0, 'Seed-v1', NULL),
    ('Retain', 'HIGH', 100, 5.0, 'Seed-v1', 'Complex refactoring possible'),
    ('Rehost', 'LOW', 100, 3.0, 'Seed-v1', 'Lift & shift minimal changes'),
    ('Rehost', 'MEDIUM', 100, 5.0, 'Seed-v1', NULL),
    ('Rehost', 'HIGH', 100, 8.0, 'Seed-v1', 'Significant VM/container setup'),
    ('Replatform', 'MEDIUM', 100, 7.0, 'Seed-v1', 'Runtime changes (e.g., Java version)'),
    ('Replatform', 'HIGH', 100, 12.0, 'Seed-v1', NULL),
    ('Repurchase', 'LOW', 100, 4.0, 'Seed-v1', 'SaaS integration'),
    ('Repurchase', 'MEDIUM', 100, 10.0, 'Seed-v1', 'Significant migration'),
    ('Refactor', 'MEDIUM', 100, 15.0, 'Seed-v1', 'Code rewrite, modernization'),
    ('Refactor', 'HIGH', 100, 25.0, 'Seed-v1', NULL),
    ('Rebuild', 'HIGH', 100, 40.0, 'Seed-v1', 'Complete rewrite'),
    ('Rebuild', 'CRITICAL', 100, 60.0, 'Seed-v1', 'Mission-critical large system');

-- 5. Views utiles pour reporting
-- ADG-M ↔ Métriques
-- NOTE: CREATE VIEW doit être la première instruction d'un batch (erreur SQL
-- Server "Msg 111" sinon) -- le séparateur GO est requis ici, sqlcmd comme
-- Azure Portal Query Editor traitant sinon tout le fichier comme un seul batch.
GO
CREATE VIEW dbo.vw_ComponentWithMetrics AS
SELECT
    c.id,
    c.name,
    c.type,
    c.criticality,
    c.businessValue,
    m.clusterId,
    m.betweennessCentrality,
    m.degreeeCentrality,
    CASE WHEN m.betweennessCentrality > 0.7 THEN 1 ELSE 0 END AS isSPOF
FROM dbo.Component c
LEFT JOIN dbo.ComponentMetrics m ON c.id = m.componentId;
GO

-- 6. Auditing
CREATE TABLE dbo.AuditLog (
    id INT PRIMARY KEY IDENTITY(1,1),
    tableName NVARCHAR(100),
    operation NVARCHAR(20),        -- INSERT|UPDATE|DELETE
    recordId NVARCHAR(100),
    changedAt DATETIME2 DEFAULT GETUTCDATE(),
    changedBy NVARCHAR(100),
    details NVARCHAR(MAX)
);

-- ============================================================================
-- Exécution post-création :
-- 1. Vérifier les tables : SELECT * FROM INFORMATION_SCHEMA.TABLES
-- 2. Seed data EffortCalibration est automatique (INSERT ci-dessus)
-- 3. Neo4j et SQL sont maintenant synchronisés en structure
-- ============================================================================
