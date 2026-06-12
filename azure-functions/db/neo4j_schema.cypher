// ============================================================================
// Neo4j — Schéma ADG-M v2 (taxonomie GraphRAG Legacy-Modernisation v2.0, voir
// notebooklm-azure/glossaire-taxonomie-graphrag-legacy-modernisation.md)
// Remplace le modèle bi-plan v1 (:TechnicalNode/:FunctionalNode/DEPENDS_ON) par les
// 20 labels Phase-1 de la taxonomie, mergés génériquement par `id` (function_app.py
// import_entities / ALLOWED_NODE_LABELS). Exécuter via cypher-shell ou Neo4j Browser.
// ============================================================================

// ----------------------------------------------------------------------------
// 1) Nettoyage du schéma v1
// ----------------------------------------------------------------------------
DROP CONSTRAINT functional_node_id IF EXISTS;
DROP CONSTRAINT technical_node_id IF EXISTS;
DROP CONSTRAINT technical_component_name IF EXISTS;
DROP CONSTRAINT arc_id IF EXISTS;

// Processus_Metier renommé Processus_Fonctionnel (taxonomie révisée) — ancienne contrainte
DROP CONSTRAINT processus_metier_id IF EXISTS;

DROP INDEX functional_domain IF EXISTS;
DROP INDEX functional_status IF EXISTS;
DROP INDEX technical_candidate7r IF EXISTS;
DROP INDEX technical_technology IF EXISTS;
DROP INDEX technical_isghost IF EXISTS;

// ----------------------------------------------------------------------------
// 2) Schéma cible — une contrainte d'unicité .id par label (ALLOWED_NODE_LABELS,
//    function_app.py). MERGE-by-id (taxonomie F.2) ⇒ idempotence.
// ----------------------------------------------------------------------------
CREATE CONSTRAINT system_id IF NOT EXISTS
FOR (n:System) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT domaine_fonctionnel_id IF NOT EXISTS
FOR (n:Domaine_Fonctionnel) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT fonction_id IF NOT EXISTS
FOR (n:Fonction) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT regle_metier_id IF NOT EXISTS
FOR (n:Regle_Metier) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT processus_fonctionnel_id IF NOT EXISTS
FOR (n:Processus_Fonctionnel) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT domaine_technique_id IF NOT EXISTS
FOR (n:Domaine_Technique) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT composant_id IF NOT EXISTS
FOR (n:Composant) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT point_entree_id IF NOT EXISTS
FOR (n:Point_Entree) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT interface_utilisateur_id IF NOT EXISTS
FOR (n:Interface_Utilisateur) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT job_batch_id IF NOT EXISTS
FOR (n:Job_Batch) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT unite_execution_id IF NOT EXISTS
FOR (n:Unite_Execution) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT procedure_reutilisable_id IF NOT EXISTS
FOR (n:Procedure_Reutilisable) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT structure_partagee_id IF NOT EXISTS
FOR (n:Structure_Partagee) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT store_donnees_id IF NOT EXISTS
FOR (n:Store_Donnees) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT store_echange_id IF NOT EXISTS
FOR (n:Store_Echange) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT table_relationnelle_id IF NOT EXISTS
FOR (n:Table_Relationnelle) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT store_hierarchique_id IF NOT EXISTS
FOR (n:Store_Hierarchique) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT entite_donnees_id IF NOT EXISTS
FOR (n:Entite_Donnees) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT canal_messagerie_id IF NOT EXISTS
FOR (n:Canal_Messagerie) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT zone_incertitude_id IF NOT EXISTS
FOR (n:Zone_Incertitude) REQUIRE n.id IS UNIQUE;

// ----------------------------------------------------------------------------
// 3) Index de performance — propriétés calculées par GDS / qualification 7R
//    (Composant) et triage des incertitudes (Zone_Incertitude).
// ----------------------------------------------------------------------------
CREATE INDEX composant_strategie7r IF NOT EXISTS
FOR (n:Composant) ON (n.strategie7R);

CREATE INDEX composant_is_spof IF NOT EXISTS
FOR (n:Composant) ON (n.isSpof);

CREATE INDEX composant_community_id IF NOT EXISTS
FOR (n:Composant) ON (n.communityId);

CREATE INDEX zone_incertitude_niveau_urgence IF NOT EXISTS
FOR (n:Zone_Incertitude) ON (n.niveauUrgence);

// ----------------------------------------------------------------------------
// 4) Vérification (à exécuter séparément)
// ----------------------------------------------------------------------------
// SHOW CONSTRAINTS;
// SHOW INDEXES;
// MATCH (n) RETURN labels(n) AS label, count(*) AS total ORDER BY label;
