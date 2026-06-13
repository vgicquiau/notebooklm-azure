// src/archimateTaxonomy.js — Taxonomie ArchiMate 3.x (module Exploration)
//
// Miroir JS de azure-functions/fn-adgm-graph/archimate_taxonomy.py — la cohérence
// entre les deux fichiers est vérifiée par tests/test_taxonomy_consistency.py
// (T1-T-01). Toute modification doit être répercutée dans les deux fichiers.
// Voir notebooklm-azure/docs/specs/SDD_Exploration_v1.md §2.

const LAYERS = [
  'Business',
  'Application',
  'Technology',
  'Strategy',
  'Motivation',
  'Physical',
  'Implementation',
];

const ELEMENT_TYPES_BY_LAYER = {
  Business: [
    'BusinessActor', 'BusinessRole', 'BusinessCollaboration', 'BusinessProcess',
    'BusinessFunction', 'BusinessInteraction', 'BusinessEvent', 'BusinessService',
    'BusinessObject', 'Contract', 'Representation', 'Product',
  ],
  Application: [
    'ApplicationComponent', 'ApplicationCollaboration', 'ApplicationInterface',
    'ApplicationFunction', 'ApplicationInteraction', 'ApplicationProcess',
    'ApplicationEvent', 'ApplicationService', 'DataObject',
  ],
  Technology: [
    'Node', 'Device', 'SystemSoftware', 'TechnologyCollaboration',
    'TechnologyInterface', 'Path', 'CommunicationNetwork', 'TechnologyFunction',
    'TechnologyProcess', 'TechnologyInteraction', 'TechnologyEvent',
    'TechnologyService', 'Artifact',
  ],
  Strategy: [
    'Resource', 'Capability', 'CourseOfAction', 'ValueStream',
  ],
  Motivation: [
    'Stakeholder', 'Driver', 'Assessment', 'Goal', 'Outcome', 'Principle',
    'Requirement', 'Constraint', 'Meaning', 'Value',
  ],
  Physical: [
    'Equipment', 'Facility', 'DistributionNetwork', 'Material',
  ],
  Implementation: [
    'WorkPackage', 'Deliverable', 'ImplementationEvent', 'Gap', 'Plateau',
  ],
};

// Ensemble plat de tous les types valides, toutes couches confondues.
const ALL_ELEMENT_TYPES = new Set(
  Object.values(ELEMENT_TYPES_BY_LAYER).flat()
);

const ASPECTS = ['ActiveStructure', 'Behaviour', 'PassiveStructure'];

// 11 types de relation ArchiMate (SDD §2 "Filtres disponibles" / §6)
const RELATION_TYPES = [
  'Association', 'Aggregation', 'Composition', 'Specialization',
  'Realization', 'Serving', 'Access', 'Influence', 'Triggering', 'Flow',
  'Assignment',
];

const ACCESS_TYPES = ['READ', 'WRITE', 'READWRITE'];

// Ordre des couches pour VAL-06 (Realization : couche cible >= couche source,
// Business > Application > Technology).
const _LAYER_RANK_FOR_REALIZATION = { Business: 0, Application: 1, Technology: 2 };

// VAL-01 — elementType doit appartenir au layer donné.
const validateElementType = (layer, elementType) =>
  (ELEMENT_TYPES_BY_LAYER[layer] || []).includes(elementType);

// Labels Neo4j cumulatifs pour un nouveau nœud ArchiMate (SDD §4 "Stratégie de
// labels") : [elementType, layer, 'ArchiMateElement'].
const labelsFor = (layer, elementType) => [elementType, layer, 'ArchiMateElement'];

// Rang de couche pour VAL-06, ou undefined si la couche n'est pas concernée par
// la règle (Strategy/Motivation/Physical/Implementation -> pas de WARN).
const realizationLayerRank = (layer) => _LAYER_RANK_FOR_REALIZATION[layer];

Object.assign(window, {
  ARCHIMATE_LAYERS: LAYERS,
  ARCHIMATE_ELEMENT_TYPES_BY_LAYER: ELEMENT_TYPES_BY_LAYER,
  ARCHIMATE_ALL_ELEMENT_TYPES: ALL_ELEMENT_TYPES,
  ARCHIMATE_ASPECTS: ASPECTS,
  ARCHIMATE_RELATION_TYPES: RELATION_TYPES,
  ARCHIMATE_ACCESS_TYPES: ACCESS_TYPES,
  archimateValidateElementType: validateElementType,
  archimateLabelsFor: labelsFor,
  archimateRealizationLayerRank: realizationLayerRank,
});
