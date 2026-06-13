// ============================================================================
// Neo4j — Schéma module Exploration (CRUD ArchiMate 3.x)
// Voir notebooklm-azure/docs/specs/SDD_Exploration_v1.md (§4) et
// notebooklm-azure/docs/specs/PLAN_EXPLORATION_v1.md (T0-B-01).
// Coexiste avec le schéma ADG-M (neo4j_schema.cypher) — labels et contraintes
// disjoints (:ArchiMateElement vs taxonomie GraphRAG). Exécuter via cypher-shell
// ou Neo4j Browser.
// ============================================================================

// ----------------------------------------------------------------------------
// 1) Contraintes d'unicité / existence — nœuds ArchiMate
// ----------------------------------------------------------------------------
CREATE CONSTRAINT archimate_element_id_unique IF NOT EXISTS
FOR (n:ArchiMateElement) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT archimate_element_name_exists IF NOT EXISTS
FOR (n:ArchiMateElement) REQUIRE n.name IS NOT NULL;

// Note : pas de contrainte UNIQUE par type de relation (11 types, peu pratique).
// L'unicité de r.id est garantie applicativement (id généré serveur uniquement,
// jamais accepté depuis le payload client — cf. R3 dans function_app.py).

// ----------------------------------------------------------------------------
// 2) Index de performance
// ----------------------------------------------------------------------------
// Recherche full-text par nom / description
CREATE FULLTEXT INDEX archimate_name_fulltext IF NOT EXISTS
FOR (n:ArchiMateElement) ON EACH [n.name, n.description];

// Filtre le plus fréquent (N1)
CREATE INDEX archimate_layer_type_idx IF NOT EXISTS
FOR (n:ArchiMateElement) ON (n.layer, n.elementType);

// Filtrage par tags (N1)
CREATE INDEX archimate_tags_idx IF NOT EXISTS
FOR (n:ArchiMateElement) ON (n.tags);

// Tri chronologique / pagination (N7)
CREATE INDEX archimate_created_idx IF NOT EXISTS
FOR (n:ArchiMateElement) ON (n.createdAt);

// ----------------------------------------------------------------------------
// 3) AuditLog — index de consultation (ADMIN)
// ----------------------------------------------------------------------------
CREATE INDEX audit_entity_idx IF NOT EXISTS
FOR (log:AuditLog) ON (log.entityId, log.timestamp);

// ----------------------------------------------------------------------------
// 4) Vérification (à exécuter séparément)
// ----------------------------------------------------------------------------
// SHOW CONSTRAINTS;
// SHOW INDEXES;
// MATCH (n:ArchiMateElement) RETURN n.layer, count(*) ORDER BY n.layer;
