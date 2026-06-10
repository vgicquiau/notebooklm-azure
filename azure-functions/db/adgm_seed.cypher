// ============================================================================
// Neo4j — Jeu de données hand-seed ADG-M v1 (formes SDD_ADG-M_v1.md §2.1)
// Domaines et composants réels tirés du rétro-doc ArchiMind FL (Fruits & Légumes) :
//   notebooklm-azure/doc-archimind/29-01-2026_11-01-17_cobol_archimind_cleaned.md
//
// Objectif : débloquer le développement/test de T12 (API lecture) contre le
// modèle bi-plan réel sans attendre la réécriture du pipeline d'ingestion
// (T11, ~4j). À exécuter après neo4j_schema.cypher.
//
// NOTE : criticalityScore / betweenness / isSPOF / clusterId sont volontairement
// ABSENTS -- état "fraîchement ingéré, pas encore analysé" (cf. SDD §2.1 :
// "écrites par les jobs d'analyse F1.3/F1.5, pas par l'ingestion"). L'API (T12)
// doit les défaut-valoriser via COALESCE -- ce seed sert aussi à vérifier ce
// chemin avant que T14 ne calcule les vraies valeurs.
//
// IMPORTANT (forme d'exécution) : tout ce bloc CREATE (nœuds + arcs + liens
// bi-plan) est volontairement écrit comme UNE SEULE requête multi-clauses
// (aucun ';' avant la toute fin) -- comme le fixture Sprint 0 prouvé en
// production -- afin que les variables (fnRef, ge01, ...) restent liées d'une
// clause CREATE à l'autre. Des ';' intermédiaires feraient exécuter chaque
// CREATE isolément : les arcs créeraient alors de nouveaux nœuds vides au lieu
// de relier les nœuds réels (piège rencontré et corrigé lors du premier essai).
// ============================================================================

// ----------------------------------------------------------------------------
// FunctionalNodes (plan fonctionnel -- domaines réels du rétro-doc FL)
// ----------------------------------------------------------------------------
CREATE (fnRef:FunctionalNode {
  id: randomUUID(), type: 'functional',
  domain: 'Référentiel Produit',
  subdomain: 'Gestion des libellés et hiérarchie produit (GE01)',
  processes: ['Création article', 'Mise à jour libellés', 'Hiérarchie famille/sous-famille'],
  sharedBusinessObjects: ['Produit', 'Libellé', 'Famille'],
  docCoveragePercent: 70, modernizationStatus: 'EXISTING',
  sourceDocIds: ['archimind-fl-cobol-cleaned-referentiel-produit'],
  createdAt: '2026-06-07T09:00:00Z', updatedAt: '2026-06-07T09:00:00Z'
})

CREATE (fnLog:FunctionalNode {
  id: randomUUID(), type: 'functional',
  domain: 'Logistique / Préparation / Commandes',
  subdomain: 'Récapitulatif et préparation des lignes de commande',
  processes: ['Saisie commande', 'Récapitulatif lignes', 'Préparation expédition'],
  sharedBusinessObjects: ['Commande', 'LigneCommande', 'Expédition'],
  docCoveragePercent: 62, modernizationStatus: 'EXISTING',
  sourceDocIds: ['archimind-fl-cobol-cleaned-logistique-commandes'],
  createdAt: '2026-06-07T09:00:00Z', updatedAt: '2026-06-07T09:00:00Z'
})

CREATE (fnStat:FunctionalNode {
  id: randomUUID(), type: 'functional',
  domain: 'Statistiques / Ventes / Valorisation',
  subdomain: 'Agrégation des faits de vente (VSAM)',
  processes: ['Agrégation quotidienne', 'Valorisation stocks', 'Édition rapports'],
  sharedBusinessObjects: ['FaitVente', 'Stock', 'Rapport'],
  docCoveragePercent: 45, modernizationStatus: 'IN_TRANSITION',
  sourceDocIds: ['archimind-fl-cobol-cleaned-statistiques-ventes'],
  createdAt: '2026-06-07T09:00:00Z', updatedAt: '2026-06-07T09:00:00Z'
})

// ----------------------------------------------------------------------------
// TechnicalNodes (plan technique -- composants COBOL/JCL réels du périmètre FL)
// ----------------------------------------------------------------------------
CREATE (ge01:TechnicalNode {
  id: randomUUID(), type: 'technical', componentName: 'GE01-REFERENTIEL',
  technology: 'COBOL', linesOfCode: 14200, callFrequency: 'HIGH',
  candidate7R: 'UNQUALIFIED', knowledgeOwner: 'TACIT', regulatoryTags: [],
  docCoveragePercent: 65, isGhost: false,
  sourceDocIds: ['archimind-fl-cobol-cleaned-referentiel-produit'],
  createdAt: '2026-06-07T09:00:00Z', updatedAt: '2026-06-07T09:00:00Z'
})

CREATE (libelle:TechnicalNode {
  id: randomUUID(), type: 'technical', componentName: 'FL-LIBELLE-PRODUIT',
  technology: 'COBOL', linesOfCode: 5400, callFrequency: 'MEDIUM',
  candidate7R: 'UNQUALIFIED', knowledgeOwner: 'M. Lefèvre', regulatoryTags: [],
  docCoveragePercent: 70, isGhost: false,
  sourceDocIds: ['archimind-fl-cobol-cleaned-referentiel-produit'],
  createdAt: '2026-06-07T09:00:00Z', updatedAt: '2026-06-07T09:00:00Z'
})

CREATE (prep:TechnicalNode {
  id: randomUUID(), type: 'technical', componentName: 'FL-PREP-COMMANDE',
  technology: 'COBOL', linesOfCode: 21800, callFrequency: 'HIGH',
  candidate7R: 'UNQUALIFIED', knowledgeOwner: 'TACIT', regulatoryTags: ['DORA'],
  docCoveragePercent: 58, isGhost: false,
  sourceDocIds: ['archimind-fl-cobol-cleaned-logistique-commandes'],
  createdAt: '2026-06-07T09:00:00Z', updatedAt: '2026-06-07T09:00:00Z'
})

CREATE (recap:TechnicalNode {
  id: randomUUID(), type: 'technical', componentName: 'FL-RECAP-LIGNES',
  technology: 'COBOL', linesOfCode: 9200, callFrequency: 'MEDIUM',
  candidate7R: 'UNQUALIFIED', knowledgeOwner: 'TACIT', regulatoryTags: [],
  docCoveragePercent: 62, isGhost: false,
  sourceDocIds: ['archimind-fl-cobol-cleaned-logistique-commandes'],
  createdAt: '2026-06-07T09:00:00Z', updatedAt: '2026-06-07T09:00:00Z'
})

CREATE (stat:TechnicalNode {
  id: randomUUID(), type: 'technical', componentName: 'FL-STAT-VENTES-VSAM',
  technology: 'COBOL', linesOfCode: 12600, callFrequency: 'LOW',
  candidate7R: 'UNQUALIFIED', knowledgeOwner: 'Mme Caron', regulatoryTags: ['BCBS239'],
  docCoveragePercent: 45, isGhost: false,
  sourceDocIds: ['archimind-fl-cobol-cleaned-statistiques-ventes'],
  createdAt: '2026-06-07T09:00:00Z', updatedAt: '2026-06-07T09:00:00Z'
})

CREATE (edit:TechnicalNode {
  id: randomUUID(), type: 'technical', componentName: 'FL-EDITION-RAPPORTS',
  technology: 'JCL', linesOfCode: 3100, callFrequency: 'LOW',
  candidate7R: 'UNQUALIFIED', knowledgeOwner: 'TACIT', regulatoryTags: [],
  docCoveragePercent: 30, isGhost: true, sourceDocIds: [],
  createdAt: '2026-06-07T09:00:00Z', updatedAt: '2026-06-07T09:00:00Z'
})

// ----------------------------------------------------------------------------
// DEPENDS_ON (plan technique -- arcs typés/qualifiés par criticité).
// FL-PREP-COMMANDE est délibérément placé en hub de passage (entrée <- RECAP,
// sorties -> GE01 + STAT) : seul chemin RECAP -> STAT, bon cas de test
// SPOF/betweenness pour T14.
// ----------------------------------------------------------------------------
CREATE (recap)-[:DEPENDS_ON {
  id: randomUUID(), arcType: 'TECHNICAL_CALL_SYNC', dataFormat: 'COPYBOOK-CMD01',
  direction: 'UNIDIRECTIONAL', criticality: 'CRITICAL'
}]->(prep)

CREATE (prep)-[:DEPENDS_ON {
  id: randomUUID(), arcType: 'TECHNICAL_CALL_SYNC', dataFormat: 'COPYBOOK-PROD01',
  direction: 'UNIDIRECTIONAL', criticality: 'CRITICAL'
}]->(ge01)

CREATE (libelle)-[:DEPENDS_ON {
  id: randomUUID(), arcType: 'TECHNICAL_CALL_SYNC', dataFormat: 'COPYBOOK-LIB01',
  direction: 'UNIDIRECTIONAL', criticality: 'HIGH'
}]->(ge01)

CREATE (prep)-[:DEPENDS_ON {
  id: randomUUID(), arcType: 'TECHNICAL_BATCH', dataFormat: 'VSAM-EXTRACT',
  direction: 'UNIDIRECTIONAL', criticality: 'MEDIUM'
}]->(stat)

CREATE (stat)-[:DEPENDS_ON {
  id: randomUUID(), arcType: 'DATA_FLOW', dataFormat: 'FLAT-FILE',
  direction: 'UNIDIRECTIONAL', criticality: 'LOW'
}]->(edit)

CREATE (recap)-[:DEPENDS_ON {
  id: randomUUID(), arcType: 'TECHNICAL_CALL_ASYNC', dataFormat: 'MQ-MSG-CMD',
  direction: 'UNIDIRECTIONAL', criticality: 'MEDIUM'
}]->(ge01)

// ----------------------------------------------------------------------------
// REALIZED_BY -- lien bi-plan : (FunctionalNode)-[:REALIZED_BY]->(TechnicalNode)
// "un nœud fonctionnel est porté par un ou plusieurs nœuds techniques" (§2.1)
// Dernière clause du bloc -- ';' de fin ICI SEULEMENT (cf. note d'exécution).
// ----------------------------------------------------------------------------
CREATE (fnRef)-[:REALIZED_BY]->(ge01)
CREATE (fnRef)-[:REALIZED_BY]->(libelle)
CREATE (fnLog)-[:REALIZED_BY]->(prep)
CREATE (fnLog)-[:REALIZED_BY]->(recap)
CREATE (fnStat)-[:REALIZED_BY]->(stat)
CREATE (fnStat)-[:REALIZED_BY]->(edit);

// ----------------------------------------------------------------------------
// Vérification (à exécuter séparément)
// ----------------------------------------------------------------------------
// MATCH (n) RETURN labels(n)[0] AS label, count(*) AS total ORDER BY label;
//   -- attendu : FunctionalNode 3, TechnicalNode 6
// MATCH ()-[r]->() RETURN type(r) AS relType, count(*) AS total ORDER BY relType;
//   -- attendu : DEPENDS_ON 6, REALIZED_BY 6
// MATCH (n:TechnicalNode) WHERE n.isGhost = true RETURN n.componentName;
//   -- attendu : FL-EDITION-RAPPORTS
