-- ============================================================================
-- Azure SQL — Schéma ADG-M v1 (SDD_ADG-M_v1.md §2.2)
-- Base : modernagent_db
-- Remplace les tables smoke-test Sprint 0 (dbo.Component et dépendances) par
-- les tables réelles ADG-M : IngestionJob, NodeAnnotationHistory.
-- Préserve dbo.EffortCalibration (propriété 7RQA, seedée -- cf. SDD_7RQA_v1.md
-- §2.2, partagée avec MWP) et dbo.AuditLog (transverse) : aucune FK vers
-- dbo.Component, donc aucun impact du nettoyage ci-dessous.
-- Exécuter via sqlcmd ou Azure Data Studio.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1) Nettoyage du smoke-test Sprint 0 (modèle dbo.Component)
--    Ordre : vue -> tables avec FK vers Component -> Component lui-même.
-- ----------------------------------------------------------------------------
DROP VIEW IF EXISTS dbo.vw_ComponentWithMetrics;
DROP TABLE IF EXISTS dbo.QualificationValidation;
DROP TABLE IF EXISTS dbo.ComponentMetrics;
DROP TABLE IF EXISTS dbo.ComponentDependency;
DROP TABLE IF EXISTS dbo.Component;

-- ----------------------------------------------------------------------------
-- 2) Schéma cible SDD ADG-M §2.2
-- ----------------------------------------------------------------------------

-- 2.1) Traçabilité des ingestions (F1.1)
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

-- 2.2) Historique versionné des annotations 7R manuelles (F1.4)
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

-- ----------------------------------------------------------------------------
-- 3) Vérification (à exécuter séparément)
-- ----------------------------------------------------------------------------
-- SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = 'dbo' ORDER BY TABLE_NAME;
-- SELECT COUNT(*) AS effort_calibration_rows FROM dbo.EffortCalibration;  -- doit rester 16
