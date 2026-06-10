// ============================================================================
// Neo4j — Schéma ADG-M v1 (SDD_ADG-M_v1.md §2.1)
// Remplace le modèle smoke-test Sprint 0 (:Component/:Domain) par le modèle
// bi-plan réel : :TechnicalNode / :FunctionalNode / DEPENDS_ON / REALIZED_BY.
// Exécuter via cypher-shell ou Neo4j Browser sur neo4j-dev (ACI).
// ============================================================================

// ----------------------------------------------------------------------------
// 1) Nettoyage du smoke-test Sprint 0 (fixture FL + CardDemo, modèle :Component)
// ----------------------------------------------------------------------------
DROP CONSTRAINT node_id IF EXISTS;
DROP CONSTRAINT domain_id IF EXISTS;
DROP INDEX node_name_idx IF EXISTS;
DROP INDEX node_type_idx IF EXISTS;
DROP INDEX depends_idx IF EXISTS;

MATCH (n:Component) DETACH DELETE n;
MATCH (d:Domain) DETACH DELETE d;

// ----------------------------------------------------------------------------
// 2) Schéma cible SDD ADG-M §2.1 — contraintes d'unicité
// ----------------------------------------------------------------------------
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

// ----------------------------------------------------------------------------
// 3) Index de performance
// ----------------------------------------------------------------------------
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

// ----------------------------------------------------------------------------
// 4) Vérification (à exécuter séparément)
// ----------------------------------------------------------------------------
// SHOW CONSTRAINTS;
// SHOW INDEXES;
// MATCH (n) RETURN labels(n) AS label, count(*) AS total ORDER BY label;
