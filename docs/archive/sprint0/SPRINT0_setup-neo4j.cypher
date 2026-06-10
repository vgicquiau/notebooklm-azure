// ============================================================================
// Neo4j Community — Initialisation graphe pour ADG-M
// Fixture basée sur les vrais rétro-docs ArchiMind :
//   - Application FL (Fruits & Légumes, Intermarché/STIME)
//   - Application CardDemo (IBM COBOL sample)
// Exécuter dans Neo4j Browser ou via cypher-shell après docker run
// ============================================================================

// 1. Contraintes et indexes
CREATE CONSTRAINT node_id IF NOT EXISTS FOR (n:Component) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT domain_id IF NOT EXISTS FOR (d:Domain) REQUIRE d.id IS UNIQUE;
CREATE INDEX node_name_idx IF NOT EXISTS FOR (n:Component) ON (n.name);
CREATE INDEX node_type_idx IF NOT EXISTS FOR (n:Component) ON (n.type);
CREATE INDEX depends_idx IF NOT EXISTS FOR ()-[r:DEPENDS_ON]-() ON (r.type);

// 2. Vérifier GDS est installé (à exécuter séparément, pas bloquant)
// SHOW PROCEDURES YIELD name WHERE name CONTAINS 'gds.louvain' RETURN name;

// ============================================================================
// APPLICATION FL (Fruits & Légumes — Intermarché/STIME)
// Source: 29-01-2026_11-01-17_cobol_archimind_cleaned.md
// ============================================================================

// Domaine racine
CREATE (fl_sys:Component {
  id: 'fl-system',
  name: 'FL Fruits & Légumes',
  type: 'System',
  description: 'Système legacy mainframe COBOL PACBASE gérant la filière F&L : gestion commerciale (promotions, ventes, référentiels) et logistique (approvisionnement, réception, taux de service)',
  language: 'COBOL/CICS',
  sloc: 0,
  businessValue: 'HIGH',
  criticality: 'CRITICAL',
  owner: 'STIME/Intermarché',
  lastUpdated: datetime('2026-01-29T11:01:17Z'),
  sourceFile: '29-01-2026_11-01-17_cobol_archimind_cleaned.md'
})

// Modules fonctionnels FL
CREATE (fl_op:Component {
  id: 'fl-mod-op-promotions',
  name: 'FL OP/Promotions',
  type: 'Module',
  description: 'Gestion des opérations promotionnelles : extraction hebdomadaire des données OP (dates, codes, libellés, types), contrôle d\'éligibilité magasins, suivi des ventes promotionnelles',
  language: 'COBOL',
  sloc: 3000,
  businessValue: 'HIGH',
  criticality: 'HIGH',
  owner: 'FL-Team',
  lastUpdated: datetime('2026-01-29T11:01:17Z'),
  sourceFile: '29-01-2026_11-01-17_cobol_archimind_cleaned.md',
  programs: 'FLECOPD'
})

CREATE (fl_pdv:Component {
  id: 'fl-mod-referentiel-pdv',
  name: 'FL Référentiel PDV',
  type: 'Module',
  description: 'Rapprochement et consolidation des référentiels points de vente FL et MR (fusion par NUMPDV), production d\'une fiche magasin unique (adresse, enseigne, statut)',
  language: 'COBOL',
  sloc: 2000,
  businessValue: 'HIGH',
  criticality: 'HIGH',
  owner: 'FL-Team',
  lastUpdated: datetime('2026-01-29T11:01:17Z'),
  sourceFile: '29-01-2026_11-01-17_cobol_archimind_cleaned.md',
  programs: 'FLEMQPD'
})

CREATE (fl_prod:Component {
  id: 'fl-mod-referentiel-produit',
  name: 'FL Référentiel Produit',
  type: 'Module',
  description: 'Gestion et recodification des référentiels produit : recodification CVENTE selon familles NFMLNT, listings produit, transcodification internationale (codes pays/langue/TVA/unités)',
  language: 'COBOL',
  sloc: 4500,
  businessValue: 'HIGH',
  criticality: 'HIGH',
  owner: 'FL-Team',
  lastUpdated: datetime('2026-01-29T11:01:17Z'),
  sourceFile: '29-01-2026_11-01-17_cobol_archimind_cleaned.md',
  programs: 'FLEPSGD, FLRGE1D, FLLRATC'
})

CREATE (fl_logistique:Component {
  id: 'fl-mod-logistique',
  name: 'FL Logistique / Taux de Service',
  type: 'Module',
  description: 'Gestion logistique : exports CSV préparation/commandes, calcul taux de service (KG/UL/UC), épuration réceptions comptabilisées, demandes d\'approvisionnement temps réel vers InfoLog',
  language: 'COBOL/CICS',
  sloc: 7000,
  businessValue: 'HIGH',
  criticality: 'CRITICAL',
  owner: 'FL-Team',
  lastUpdated: datetime('2026-01-29T11:01:17Z'),
  sourceFile: '29-01-2026_11-01-17_cobol_archimind_cleaned.md',
  programs: 'FLERECD, FLTASED, FLXE6TD, FLLR48C'
})

CREATE (fl_stats:Component {
  id: 'fl-mod-statistiques',
  name: 'FL Statistiques & Finance',
  type: 'Module',
  description: 'Cumuls de ventes par PDV (FLSTA8D), régularisations VSAM des agrégats (PE9A/PE9C/PE9G), staging VSAM vers séquentiel, calculs financiers par période',
  language: 'COBOL',
  sloc: 6000,
  businessValue: 'HIGH',
  criticality: 'CRITICAL',
  owner: 'FL-Team',
  lastUpdated: datetime('2026-01-29T11:01:17Z'),
  sourceFile: '29-01-2026_11-01-17_cobol_archimind_cleaned.md',
  programs: 'FLSTA8D, FLTP9AD, FLTP9CD, FLTP9GD, FLRSTGD'
})

CREATE (fl_cics:Component {
  id: 'fl-mod-cics-navigation',
  name: 'FL CICS Navigation (FLZAxx)',
  type: 'Module',
  description: 'Couche de navigation transactionnelle CICS : routeurs FLZAxxC positionnant la COMMAREA PACBASE (CT00/CT90) et XCTL vers les programmes métiers (FLARxx, FLADxx, FLRPxx). Fort couplage aux programmes cibles non livrés.',
  language: 'CICS/COBOL',
  sloc: 5000,
  businessValue: 'MEDIUM',
  criticality: 'HIGH',
  owner: 'FL-Team',
  lastUpdated: datetime('2026-01-29T11:01:17Z'),
  sourceFile: '29-01-2026_11-01-17_cobol_archimind_cleaned.md',
  programs: 'FLZA10C, FLZA14C, FLZA22C, FLZA25C'
})

CREATE (fl_mq:Component {
  id: 'fl-mod-messagerie-mq',
  name: 'FL Messagerie MQ / Intégration',
  type: 'Module',
  description: 'Intégration applicative : émission messages MQ batch (FLEMQBD) et temps réel (FLEMQSC, FLQ002C), routage paramétré via table FH3 (Datacom), supervision INFOLOG/Loréa (FLQ005C/FLSSLOC)',
  language: 'COBOL/CICS',
  sloc: 3500,
  businessValue: 'HIGH',
  criticality: 'CRITICAL',
  owner: 'FL-Team',
  lastUpdated: datetime('2026-01-29T11:01:17Z'),
  sourceFile: '29-01-2026_11-01-17_cobol_archimind_cleaned.md',
  programs: 'FLEMQBD, FLEMQSC, FLQ002C, FLQ005C, FLSSLOC, FLLR48C'
})

CREATE (fl_edition:Component {
  id: 'fl-mod-edition',
  name: 'FL Édition / Post-traitement',
  type: 'Module',
  description: 'Post-traitement d\'états PACBASE : renumérotation pagination 1/N (FLREN1D), filtrage pages (FLPAGED), conversion caractères PDF (FLMPDFD). Transverse à tous les batchs.',
  language: 'COBOL',
  sloc: 2500,
  businessValue: 'LOW',
  criticality: 'MEDIUM',
  owner: 'FL-Team',
  lastUpdated: datetime('2026-01-29T11:01:17Z'),
  sourceFile: '29-01-2026_11-01-17_cobol_archimind_cleaned.md',
  programs: 'FLREN1D, FLRENUD, FLPAGED, FLMPDFD'
})

// Systèmes externes FL
CREATE (infolog:Component {
  id: 'ext-infolog',
  name: 'InfoLog (WMS)',
  type: 'ExternalSystem',
  description: 'Système de gestion d\'entrepôt (WMS) du groupe ITM LAI. Reçoit les demandes d\'approvisionnement temps réel et les messages de supervision de FL.',
  language: 'N/A',
  sloc: 0,
  businessValue: 'HIGH',
  criticality: 'CRITICAL',
  owner: 'ITM-LAI',
  lastUpdated: datetime('2026-01-29T11:01:17Z'),
  sourceFile: '29-01-2026_11-01-17_cobol_archimind_cleaned.md'
})

CREATE (lorea:Component {
  id: 'ext-lorea',
  name: 'Loréa (Supervision centrale)',
  type: 'ExternalSystem',
  description: 'Système de supervision centrale du groupement. Reçoit les comptes-rendus et incidents depuis FL via MQ.',
  language: 'N/A',
  sloc: 0,
  businessValue: 'MEDIUM',
  criticality: 'HIGH',
  owner: 'ITM-LAI',
  lastUpdated: datetime('2026-01-29T11:01:17Z'),
  sourceFile: '29-01-2026_11-01-17_cobol_archimind_cleaned.md'
})

CREATE (udsbq0d:Component {
  id: 'fl-wrapper-mq',
  name: 'UDSBQ0D (Wrapper MQ)',
  type: 'Service',
  description: 'Wrapper unique IBM MQ batch (connect/put/disconnect). Point de défaillance unique (SPOF) : tous les batchs MQ passent par lui. Non livré dans le dépôt.',
  language: 'COBOL',
  sloc: 500,
  businessValue: 'HIGH',
  criticality: 'CRITICAL',
  owner: 'Platform-Team',
  lastUpdated: datetime('2026-01-29T11:01:17Z'),
  sourceFile: '29-01-2026_11-01-17_cobol_archimind_cleaned.md'
})

CREATE (dbntry:Component {
  id: 'fl-wrapper-datacom',
  name: 'DBNTRY (Wrapper Datacom)',
  type: 'Service',
  description: 'Wrapper accès CA-Datacom/DB. Accès aux référentiels FH3/FH5/FA6/FA7 et tables métiers. Multi-environnement (XENVIR). SPOF de la couche CICS.',
  language: 'Assembler',
  sloc: 1000,
  businessValue: 'HIGH',
  criticality: 'CRITICAL',
  owner: 'Platform-Team',
  lastUpdated: datetime('2026-01-29T11:01:17Z'),
  sourceFile: '29-01-2026_11-01-17_cobol_archimind_cleaned.md'
})

CREATE (fh3:Component {
  id: 'fl-referentiel-fh3',
  name: 'Référentiel FH3 (Routage MQ)',
  type: 'Database',
  description: 'Table Datacom de paramétrage du routage MQ (identifiants QMGR, ALIAS, etc.). Dépendance critique : un paramétrage incomplet bloque l\'acheminement de tous les messages.',
  language: 'N/A',
  sloc: 0,
  businessValue: 'HIGH',
  criticality: 'CRITICAL',
  owner: 'Platform-Team',
  lastUpdated: datetime('2026-01-29T11:01:17Z'),
  sourceFile: '29-01-2026_11-01-17_cobol_archimind_cleaned.md'
})

CREATE (fl_vsam_pe9:Component {
  id: 'fl-vsam-pe9',
  name: 'VSAM PE9 (Statistiques ventes)',
  type: 'Database',
  description: 'Fichiers VSAM KSDS des agrégats de ventes/finance : FLPE9APE, FLPE9CPE, FLPE9GPE. Mise à jour record-by-record (READ/REWRITE). Risque contention, non-idempotence, arrêt job sur I/O.',
  language: 'VSAM',
  sloc: 0,
  businessValue: 'HIGH',
  criticality: 'CRITICAL',
  owner: 'FL-Team',
  lastUpdated: datetime('2026-01-29T11:01:17Z'),
  sourceFile: '29-01-2026_11-01-17_cobol_archimind_cleaned.md'
})

// ============================================================================
// APPLICATION CardDemo (IBM COBOL open-source demo)
// Source: Macro-mainframe-modernization-carddemo_*.md + Transverse IT-*.md
// ============================================================================

CREATE (card_sys:Component {
  id: 'carddemo-system',
  name: 'CardDemo (Gestion Cartes)',
  type: 'System',
  description: 'Application COBOL z/OS de démonstration IBM pour la gestion de cartes de crédit : servicing en ligne CICS, traitement batch quotidien des transactions, relevés, autorisations, sécurité.',
  language: 'COBOL/CICS',
  sloc: 0,
  businessValue: 'HIGH',
  criticality: 'CRITICAL',
  owner: 'IBM-CardDemo',
  lastUpdated: datetime('2026-04-30T14:54:28Z'),
  sourceFile: 'Macro-mainframe-modernization-carddemo_20260430_145428_170840.md'
})

CREATE (card_online:Component {
  id: 'carddemo-mod-online-ops',
  name: 'Card Services Operations (Online)',
  type: 'Module',
  description: 'Cœur applicatif CICS : authentification (COSGN00C), menus (COMEN01C/COADM01C), gestion clients/comptes/cartes (COACTVWC, COCRDUPC), transactions (COTRN00-02C), paiement (COBIL00C), autorisations en attente (COPAUS0C)',
  language: 'CICS/COBOL',
  sloc: 25000,
  businessValue: 'HIGH',
  criticality: 'CRITICAL',
  owner: 'CardDemo-Team',
  lastUpdated: datetime('2026-04-30T14:54:28Z'),
  sourceFile: 'Macro-mainframe-modernization-carddemo_20260430_145428_170840.md',
  programs: 'COSGN00C, COMEN01C, COACTVWC, COTRN00C, COBIL00C'
})

CREATE (card_posting:Component {
  id: 'carddemo-mod-transaction-posting',
  name: 'Transaction Posting Cycle',
  type: 'Module',
  description: 'Traitement batch quotidien des transactions : posting (CBTRN02C, POSTTRAN.jcl), calcul intérêts et frais (CBACT04C, INTCALC.jcl), fusion transactions (COMBTRAN.jcl), maintenance VSAM CLOSEFIL/OPENFIL',
  language: 'COBOL',
  sloc: 8000,
  businessValue: 'HIGH',
  criticality: 'CRITICAL',
  owner: 'CardDemo-Team',
  lastUpdated: datetime('2026-04-30T14:54:28Z'),
  sourceFile: 'Macro-mainframe-modernization-carddemo_20260430_145428_170840.md',
  programs: 'CBTRN02C, CBACT04C'
})

CREATE (card_statements:Component {
  id: 'carddemo-mod-statements',
  name: 'Customer Xref & Statements',
  type: 'Module',
  description: 'Rechargement référentiels clients et cross-references carte/client/compte, génération relevés texte/HTML/PDF (CBSTM03A/B), export/import consolidé (CBEXPORT/CBIMPORT)',
  language: 'COBOL',
  sloc: 10000,
  businessValue: 'HIGH',
  criticality: 'HIGH',
  owner: 'CardDemo-Team',
  lastUpdated: datetime('2026-04-30T14:54:28Z'),
  sourceFile: 'Macro-mainframe-modernization-carddemo_20260430_145428_170840.md',
  programs: 'CBSTM03A, CBSTM03B, CBEXPORT, CBIMPORT'
})

CREATE (card_auth:Component {
  id: 'carddemo-mod-authorization',
  name: 'Authorization Data Services (IMS)',
  type: 'Module',
  description: 'Extension autorisations en attente sur IMS : stockage DBPAUTP0.dbd, consultation détaillée (COPAUS1C/2C), marquage fraude, purge autorisations expirées (PAUDBLOD/PAUDBUNL)',
  language: 'COBOL/IMS',
  sloc: 5000,
  businessValue: 'HIGH',
  criticality: 'HIGH',
  owner: 'CardDemo-Team',
  lastUpdated: datetime('2026-04-30T14:54:28Z'),
  sourceFile: 'Macro-mainframe-modernization-carddemo_20260430_145428_170840.md',
  programs: 'PAUDBLOD, PAUDBUNL, COPAUS1C, COPAUS2C'
})

CREATE (card_tranrept:Component {
  id: 'carddemo-mod-transaction-report',
  name: 'Transaction Report Batch',
  type: 'Module',
  description: 'Production rapports transactions : sauvegarde, filtrage date, enrichissement avec CARDXREF/TRANTYPE/TRANCATG (CBTRN03C), publication rapport AWS.M2.CARDDEMO.TRANREPT',
  language: 'COBOL',
  sloc: 4000,
  businessValue: 'MEDIUM',
  criticality: 'MEDIUM',
  owner: 'CardDemo-Team',
  lastUpdated: datetime('2026-04-30T14:54:28Z'),
  sourceFile: 'Macro-mainframe-modernization-carddemo_20260430_145428_170840.md',
  programs: 'CBTRN03C'
})

CREATE (card_db2_tran_type:Component {
  id: 'carddemo-db2-transaction-types',
  name: 'Transaction Type Reference (Db2)',
  type: 'Database',
  description: 'Référentiel Db2 des types et catégories de transaction (TRNTYPE, TRNTYCAT). Maintenance en ligne (COTRTLIC/COTRTUPC) et batch (COBTUPDT). Consommé par tous les modules de transaction.',
  language: 'DB2/SQL',
  sloc: 0,
  businessValue: 'HIGH',
  criticality: 'HIGH',
  owner: 'CardDemo-Team',
  lastUpdated: datetime('2026-04-30T14:54:28Z'),
  sourceFile: 'Macro-mainframe-modernization-carddemo_20260430_145428_170840.md'
})

CREATE (card_vsam_master:Component {
  id: 'carddemo-vsam-master',
  name: 'VSAM Master Files (Cartes/Comptes/Clients)',
  type: 'Database',
  description: 'Fichiers VSAM KSDS maîtres : CARDDATA, CUSTDATA, ACCTDATA, CARDXREF. Utilisés par toutes les couches online et batch. AIX sur CARDXREF pour accès par clé secondaire.',
  language: 'VSAM',
  sloc: 0,
  businessValue: 'HIGH',
  criticality: 'CRITICAL',
  owner: 'CardDemo-Team',
  lastUpdated: datetime('2026-04-30T14:54:28Z'),
  sourceFile: 'Macro-mainframe-modernization-carddemo_20260430_145428_170840.md'
})

// ============================================================================
// RELATIONS FL
// ============================================================================

CREATE (fl_sys)-[:DEPENDS_ON {type: 'CONTAINS', confidence: 1.0}]->(fl_op)
CREATE (fl_sys)-[:DEPENDS_ON {type: 'CONTAINS', confidence: 1.0}]->(fl_pdv)
CREATE (fl_sys)-[:DEPENDS_ON {type: 'CONTAINS', confidence: 1.0}]->(fl_prod)
CREATE (fl_sys)-[:DEPENDS_ON {type: 'CONTAINS', confidence: 1.0}]->(fl_logistique)
CREATE (fl_sys)-[:DEPENDS_ON {type: 'CONTAINS', confidence: 1.0}]->(fl_stats)
CREATE (fl_sys)-[:DEPENDS_ON {type: 'CONTAINS', confidence: 1.0}]->(fl_cics)
CREATE (fl_sys)-[:DEPENDS_ON {type: 'CONTAINS', confidence: 1.0}]->(fl_mq)
CREATE (fl_sys)-[:DEPENDS_ON {type: 'CONTAINS', confidence: 1.0}]->(fl_edition)

// FL Logistique → InfoLog (via MQ)
CREATE (fl_logistique)-[:DEPENDS_ON {type: 'NETWORK', confidence: 0.95, description: 'Demandes appro temps réel via MQ (FLLR48C → UDSBQ0D → InfoLog)'}]->(infolog)
// FL Messagerie → InfoLog + Loréa (supervision)
CREATE (fl_mq)-[:DEPENDS_ON {type: 'NETWORK', confidence: 0.95, description: 'Routage messages FLQ002C/FLQ005C → InfoLog/Loréa via MQ'}]->(infolog)
CREATE (fl_mq)-[:DEPENDS_ON {type: 'NETWORK', confidence: 0.90, description: 'Supervision incidents FLSSLOC → Loréa via MQ'}]->(lorea)
// FL Messagerie → UDSBQ0D (SPOF critique)
CREATE (fl_mq)-[:DEPENDS_ON {type: 'CALLS', confidence: 1.0, description: 'Tous les batchs MQ passent par le wrapper unique UDSBQ0D (SPOF)'}]->(udsbq0d)
// FL CICS → DBNTRY (SPOF)
CREATE (fl_cics)-[:DEPENDS_ON {type: 'CALLS', confidence: 1.0, description: 'Toute la couche CICS accède aux référentiels via DBNTRY (Datacom)'}]->(dbntry)
// DBNTRY → FH3 (table routage critique)
CREATE (dbntry)-[:DEPENDS_ON {type: 'DATABASE', confidence: 0.95, description: 'Routage MQ paramétré dans table FH3 ; paramétrage incomplet = blocage messages'}]->(fh3)
// FL Stats → VSAM PE9
CREATE (fl_stats)-[:DEPENDS_ON {type: 'DATABASE', confidence: 0.98, description: 'VSAM READ/REWRITE record-by-record sur FLPE9APE/CPE/GPE'}]->(fl_vsam_pe9)
// FL Op → FL PDV (contrôle éligibilité magasin)
CREATE (fl_op)-[:DEPENDS_ON {type: 'DATABASE', confidence: 0.85, description: 'Contrôle éligibilité magasin utilise référentiel PDV'}]->(fl_pdv)
// FL Logistique → FL Prod (référentiel produits)
CREATE (fl_logistique)-[:DEPENDS_ON {type: 'DATABASE', confidence: 0.80, description: 'Exports logistiques référencent codes produits CDPROD'}]->(fl_prod)
// FL CICS → FL Logistique (navigation)
CREATE (fl_cics)-[:DEPENDS_ON {type: 'CALLS', confidence: 0.90, description: 'FLZAxx XCTL vers FLAR*, FLAD* (cœur approvisionnement)'}]->(fl_logistique)

// ============================================================================
// RELATIONS CardDemo
// ============================================================================

CREATE (card_sys)-[:DEPENDS_ON {type: 'CONTAINS', confidence: 1.0}]->(card_online)
CREATE (card_sys)-[:DEPENDS_ON {type: 'CONTAINS', confidence: 1.0}]->(card_posting)
CREATE (card_sys)-[:DEPENDS_ON {type: 'CONTAINS', confidence: 1.0}]->(card_statements)
CREATE (card_sys)-[:DEPENDS_ON {type: 'CONTAINS', confidence: 1.0}]->(card_auth)
CREATE (card_sys)-[:DEPENDS_ON {type: 'CONTAINS', confidence: 1.0}]->(card_tranrept)

// CardDemo Online → VSAM Master (accès données)
CREATE (card_online)-[:DEPENDS_ON {type: 'DATABASE', confidence: 0.98, description: 'Accès VSAM KSDS pour comptes/cartes/transactions en ligne'}]->(card_vsam_master)
// CardDemo Online → Db2 Transaction Types
CREATE (card_online)-[:DEPENDS_ON {type: 'DATABASE', confidence: 0.90, description: 'Accès sélectif Db2 pour classification des types de transaction'}]->(card_db2_tran_type)
// CardDemo Posting → VSAM Master
CREATE (card_posting)-[:DEPENDS_ON {type: 'DATABASE', confidence: 0.99, description: 'CBTRN02C : validation et posting quotidien en VSAM TRANSACT'}]->(card_vsam_master)
// CardDemo Statements → VSAM Master
CREATE (card_statements)-[:DEPENDS_ON {type: 'DATABASE', confidence: 0.95, description: 'CBSTM03A consomme CUSTDATA, ACCTDATA, TRANSACT pour génération relevés'}]->(card_vsam_master)
// CardDemo Statements → Posting (dépendance données)
CREATE (card_statements)-[:DEPENDS_ON {type: 'FILE', confidence: 0.90, description: 'Relevés générés après posting quotidien (données mises à jour par CBTRN02C)'}]->(card_posting)
// CardDemo Report → VSAM Master + Db2
CREATE (card_tranrept)-[:DEPENDS_ON {type: 'DATABASE', confidence: 0.90, description: 'CBTRN03C enrichit avec CARDXREF, TRANTYPE, TRANCATG'}]->(card_vsam_master)
CREATE (card_tranrept)-[:DEPENDS_ON {type: 'DATABASE', confidence: 0.85, description: 'Enrichissement rapport avec types/catégories depuis Db2'}]->(card_db2_tran_type)
// CardDemo Auth → Online (consultation)
CREATE (card_auth)-[:DEPENDS_ON {type: 'CALLS', confidence: 0.80, description: 'COPAUS1C/2C consulté depuis CardDemo Online pour autorisations en attente'}]->(card_online);

// ============================================================================
// Verification
// ============================================================================

MATCH (n:Component) RETURN count(n) as total_nodes;
MATCH (n:Component)-[r:DEPENDS_ON]->(m:Component) RETURN count(r) as total_relationships;
MATCH (n:Component) WHERE n.criticality = 'CRITICAL' RETURN n.id, n.name, n.type ORDER BY n.name;
