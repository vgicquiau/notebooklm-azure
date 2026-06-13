// ============================================================================
// Neo4j — Jeu de données de seed pour les tests d'intégration du module
// Exploration (T0-T-01). Voir notebooklm-azure/docs/specs/PLAN_EXPLORATION_v1.md.
//
// 16 nœuds :ArchiMateElement couvrant les 7 layers (Business, Application,
// Technology, Strategy, Motivation, Physical, Implementation) + 12 relations
// couvrant Serving, Realization (intra et inter-layer pour exercer VAL-06),
// Assignment, Access (READ/WRITE pour VAL-03), Triggering, Influence,
// Aggregation (cross-layer pour VAL-08) et Association.
//
// Tous les nœuds/relations portent seedTest:true (et tags contenant
// "seed-test") — point d'ancrage pour cleanup_test_data() (cf.
// fn-adgm-graph/tests/conftest.py). Pas d'APOC requis (randomUUID() est une
// fonction native Neo4j >= 4.2). Exécuter via cypher-shell ou Neo4j Browser
// sur une base/instance de test dédiée.
// ============================================================================

// ----------------------------------------------------------------------------
// 1) Nœuds — Business
// ----------------------------------------------------------------------------
CREATE (:ArchiMateElement:Business:BusinessActor {
  id: randomUUID(), name: "Client", layer: "Business", elementType: "BusinessActor",
  aspect: "ActiveStructure", description: "Personne physique souscrivant un contrat.",
  tags: ["seed-test"], seedTest: true, createdAt: datetime(), updatedAt: datetime()
});

CREATE (:ArchiMateElement:Business:BusinessProcess {
  id: randomUUID(), name: "Souscrire Contrat", layer: "Business", elementType: "BusinessProcess",
  aspect: "Behaviour", description: "Processus de souscription d'un contrat par un client.",
  tags: ["seed-test"], seedTest: true, createdAt: datetime(), updatedAt: datetime()
});

CREATE (:ArchiMateElement:Business:BusinessService {
  id: randomUUID(), name: "Service Souscription", layer: "Business", elementType: "BusinessService",
  aspect: "Behaviour", description: "Service métier de souscription proposé aux clients.",
  tags: ["seed-test"], seedTest: true, createdAt: datetime(), updatedAt: datetime()
});

CREATE (:ArchiMateElement:Business:BusinessEvent {
  id: randomUUID(), name: "Contrat Signé", layer: "Business", elementType: "BusinessEvent",
  aspect: "Behaviour", description: "Événement déclenché à la signature du contrat.",
  tags: ["seed-test"], seedTest: true, createdAt: datetime(), updatedAt: datetime()
});

// ----------------------------------------------------------------------------
// 2) Nœuds — Application
// ----------------------------------------------------------------------------
CREATE (:ArchiMateElement:Application:ApplicationComponent {
  id: randomUUID(), name: "AppSouscription", layer: "Application", elementType: "ApplicationComponent",
  aspect: "ActiveStructure", description: "Composant applicatif gérant la souscription.",
  tags: ["seed-test"], seedTest: true, createdAt: datetime(), updatedAt: datetime()
});

CREATE (:ArchiMateElement:Application:ApplicationService {
  id: randomUUID(), name: "API Souscription", layer: "Application", elementType: "ApplicationService",
  aspect: "Behaviour", description: "Service applicatif exposé pour la souscription.",
  tags: ["seed-test"], seedTest: true, createdAt: datetime(), updatedAt: datetime()
});

CREATE (:ArchiMateElement:Application:DataObject {
  id: randomUUID(), name: "Contrat", layer: "Application", elementType: "DataObject",
  aspect: "PassiveStructure", description: "Objet de données représentant un contrat.",
  tags: ["seed-test"], seedTest: true, createdAt: datetime(), updatedAt: datetime()
});

// ----------------------------------------------------------------------------
// 3) Nœuds — Technology
// ----------------------------------------------------------------------------
CREATE (:ArchiMateElement:Technology:Node {
  id: randomUUID(), name: "ServeurAppli", layer: "Technology", elementType: "Node",
  aspect: "ActiveStructure", description: "Nœud d'infrastructure hébergeant AppSouscription.",
  tags: ["seed-test"], seedTest: true, createdAt: datetime(), updatedAt: datetime()
});

CREATE (:ArchiMateElement:Technology:TechnologyService {
  id: randomUUID(), name: "Service Hébergement", layer: "Technology", elementType: "TechnologyService",
  aspect: "Behaviour", description: "Service technique d'hébergement applicatif.",
  tags: ["seed-test"], seedTest: true, createdAt: datetime(), updatedAt: datetime()
});

// ----------------------------------------------------------------------------
// 4) Nœud — Strategy
// ----------------------------------------------------------------------------
CREATE (:ArchiMateElement:Strategy:Capability {
  id: randomUUID(), name: "Capacité Souscription", layer: "Strategy", elementType: "Capability",
  aspect: "ActiveStructure", description: "Capacité métier de souscription de contrats.",
  tags: ["seed-test"], seedTest: true, createdAt: datetime(), updatedAt: datetime()
});

// ----------------------------------------------------------------------------
// 5) Nœuds — Motivation
// ----------------------------------------------------------------------------
CREATE (:ArchiMateElement:Motivation:Stakeholder {
  id: randomUUID(), name: "Direction Commerciale", layer: "Motivation", elementType: "Stakeholder",
  aspect: "ActiveStructure", description: "Partie prenante portant l'objectif de conversion.",
  tags: ["seed-test"], seedTest: true, createdAt: datetime(), updatedAt: datetime()
});

CREATE (:ArchiMateElement:Motivation:Goal {
  id: randomUUID(), name: "Augmenter le taux de conversion", layer: "Motivation", elementType: "Goal",
  aspect: "Behaviour", description: "Objectif d'amélioration du taux de conversion des souscriptions.",
  tags: ["seed-test"], seedTest: true, createdAt: datetime(), updatedAt: datetime()
});

CREATE (:ArchiMateElement:Motivation:Requirement {
  id: randomUUID(), name: "Disponibilité 99.9%", layer: "Motivation", elementType: "Requirement",
  aspect: "Behaviour", description: "Exigence de disponibilité du service de souscription.",
  tags: ["seed-test"], seedTest: true, createdAt: datetime(), updatedAt: datetime()
});

// ----------------------------------------------------------------------------
// 6) Nœud — Physical
// ----------------------------------------------------------------------------
CREATE (:ArchiMateElement:Physical:Equipment {
  id: randomUUID(), name: "Datacenter Lyon", layer: "Physical", elementType: "Equipment",
  aspect: "ActiveStructure", description: "Équipement physique hébergeant ServeurAppli.",
  tags: ["seed-test"], seedTest: true, createdAt: datetime(), updatedAt: datetime()
});

// ----------------------------------------------------------------------------
// 7) Nœuds — Implementation
// ----------------------------------------------------------------------------
CREATE (:ArchiMateElement:Implementation:WorkPackage {
  id: randomUUID(), name: "Migration Cloud", layer: "Implementation", elementType: "WorkPackage",
  aspect: "Behaviour", description: "Paquet de travail de migration vers le cloud.",
  tags: ["seed-test"], seedTest: true, createdAt: datetime(), updatedAt: datetime()
});

CREATE (:ArchiMateElement:Implementation:Gap {
  id: randomUUID(), name: "Écart Couverture Cloud", layer: "Implementation", elementType: "Gap",
  aspect: "Behaviour", description: "Écart identifié entre l'état actuel et l'état cible cloud.",
  tags: ["seed-test"], seedTest: true, createdAt: datetime(), updatedAt: datetime()
});

// ----------------------------------------------------------------------------
// 8) Relations
// ----------------------------------------------------------------------------

// Serving — API Souscription dessert le processus métier
MATCH (a:ArchiMateElement {name: "API Souscription"}), (b:ArchiMateElement {name: "Souscrire Contrat"})
CREATE (a)-[:Serving {id: randomUUID(), type: "Serving", seedTest: true, createdAt: datetime()}]->(b);

// Realization — AppSouscription réalise l'API Souscription (Application -> Application)
MATCH (a:ArchiMateElement {name: "AppSouscription"}), (b:ArchiMateElement {name: "API Souscription"})
CREATE (a)-[:Realization {id: randomUUID(), type: "Realization", seedTest: true, createdAt: datetime()}]->(b);

// Realization — Service Hébergement (Technology) réalise AppSouscription (Application)
// -> rang cible (Application=1) < rang source (Technology=2) : exerce VAL-06 (WARN).
MATCH (a:ArchiMateElement {name: "Service Hébergement"}), (b:ArchiMateElement {name: "AppSouscription"})
CREATE (a)-[:Realization {id: randomUUID(), type: "Realization", seedTest: true, createdAt: datetime()}]->(b);

// Assignment — Client est assigné au processus de souscription
MATCH (a:ArchiMateElement {name: "Client"}), (b:ArchiMateElement {name: "Souscrire Contrat"})
CREATE (a)-[:Assignment {id: randomUUID(), type: "Assignment", seedTest: true, createdAt: datetime()}]->(b);

// Assignment — ServeurAppli est assigné à AppSouscription
MATCH (a:ArchiMateElement {name: "ServeurAppli"}), (b:ArchiMateElement {name: "AppSouscription"})
CREATE (a)-[:Assignment {id: randomUUID(), type: "Assignment", seedTest: true, createdAt: datetime()}]->(b);

// Access (WRITE) — AppSouscription écrit l'objet Contrat — exerce VAL-03
MATCH (a:ArchiMateElement {name: "AppSouscription"}), (b:ArchiMateElement {name: "Contrat"})
CREATE (a)-[:Access {id: randomUUID(), type: "Access", accessType: "WRITE", seedTest: true, createdAt: datetime()}]->(b);

// Access (READ) — API Souscription lit l'objet Contrat — exerce VAL-03
MATCH (a:ArchiMateElement {name: "API Souscription"}), (b:ArchiMateElement {name: "Contrat"})
CREATE (a)-[:Access {id: randomUUID(), type: "Access", accessType: "READ", seedTest: true, createdAt: datetime()}]->(b);

// Triggering — la souscription déclenche l'événement de signature
MATCH (a:ArchiMateElement {name: "Souscrire Contrat"}), (b:ArchiMateElement {name: "Contrat Signé"})
CREATE (a)-[:Triggering {id: randomUUID(), type: "Triggering", seedTest: true, createdAt: datetime()}]->(b);

// Influence — l'objectif de conversion influence l'exigence de disponibilité
MATCH (a:ArchiMateElement {name: "Augmenter le taux de conversion"}), (b:ArchiMateElement {name: "Disponibilité 99.9%"})
CREATE (a)-[:Influence {id: randomUUID(), type: "Influence", seedTest: true, createdAt: datetime()}]->(b);

// Realization — Migration Cloud (Implementation) réalise l'écart Gap (Implementation)
// -> couches hors table VAL-06 (pas de WARN attendu).
MATCH (a:ArchiMateElement {name: "Migration Cloud"}), (b:ArchiMateElement {name: "Écart Couverture Cloud"})
CREATE (a)-[:Realization {id: randomUUID(), type: "Realization", seedTest: true, createdAt: datetime()}]->(b);

// Aggregation — Capacité Souscription (Strategy) agrège Service Souscription (Business)
// -> cross-layer, exerce VAL-08 (INFO).
MATCH (a:ArchiMateElement {name: "Capacité Souscription"}), (b:ArchiMateElement {name: "Service Souscription"})
CREATE (a)-[:Aggregation {id: randomUUID(), type: "Aggregation", seedTest: true, createdAt: datetime()}]->(b);

// Association — Direction Commerciale est associée à la Capacité Souscription
MATCH (a:ArchiMateElement {name: "Direction Commerciale"}), (b:ArchiMateElement {name: "Capacité Souscription"})
CREATE (a)-[:Association {id: randomUUID(), type: "Association", seedTest: true, createdAt: datetime()}]->(b);

// ----------------------------------------------------------------------------
// 9) Nettoyage (cf. cleanup_test_data() dans tests/conftest.py)
// ----------------------------------------------------------------------------
// MATCH (n:ArchiMateElement {seedTest: true}) DETACH DELETE n;
