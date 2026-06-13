"""
Taxonomie ArchiMate 3.x — module Exploration (CRUD Neo4j).

Source de vérité pour :
- les 7 couches (`LAYERS`) et leurs types d'éléments (`ELEMENT_TYPES_BY_LAYER`)
- les 3 aspects (`ASPECTS`)
- les 11 types de relation (`RELATION_TYPES`)
- les 3 valeurs d'accessType (`ACCESS_TYPES`)

Voir notebooklm-azure/docs/specs/SDD_Exploration_v1.md §2 ("Mapping ArchiMate ->
Types de nœuds"). Une copie miroir existe côté frontend
(frontend/src/archimateTaxonomy.js) — la cohérence entre les deux fichiers est
vérifiée par tests/test_taxonomy_consistency.py (T1-T-01).
"""

LAYERS = [
    "Business",
    "Application",
    "Technology",
    "Strategy",
    "Motivation",
    "Physical",
    "Implementation",
]

ELEMENT_TYPES_BY_LAYER = {
    "Business": [
        "BusinessActor", "BusinessRole", "BusinessCollaboration", "BusinessProcess",
        "BusinessFunction", "BusinessInteraction", "BusinessEvent", "BusinessService",
        "BusinessObject", "Contract", "Representation", "Product",
    ],
    "Application": [
        "ApplicationComponent", "ApplicationCollaboration", "ApplicationInterface",
        "ApplicationFunction", "ApplicationInteraction", "ApplicationProcess",
        "ApplicationEvent", "ApplicationService", "DataObject",
    ],
    "Technology": [
        "Node", "Device", "SystemSoftware", "TechnologyCollaboration",
        "TechnologyInterface", "Path", "CommunicationNetwork", "TechnologyFunction",
        "TechnologyProcess", "TechnologyInteraction", "TechnologyEvent",
        "TechnologyService", "Artifact",
    ],
    "Strategy": [
        "Resource", "Capability", "CourseOfAction", "ValueStream",
    ],
    "Motivation": [
        "Stakeholder", "Driver", "Assessment", "Goal", "Outcome", "Principle",
        "Requirement", "Constraint", "Meaning", "Value",
    ],
    "Physical": [
        "Equipment", "Facility", "DistributionNetwork", "Material",
    ],
    "Implementation": [
        "WorkPackage", "Deliverable", "ImplementationEvent", "Gap", "Plateau",
    ],
}

# Ensemble plat de tous les types valides, toutes couches confondues — pratique pour
# une validation rapide indépendante de la couche.
ALL_ELEMENT_TYPES = {
    element_type
    for types in ELEMENT_TYPES_BY_LAYER.values()
    for element_type in types
}

ASPECTS = ["ActiveStructure", "Behaviour", "PassiveStructure"]

# 11 types de relation ArchiMate (SDD §2 "Filtres disponibles" / §6)
RELATION_TYPES = [
    "Association", "Aggregation", "Composition", "Specialization",
    "Realization", "Serving", "Access", "Influence", "Triggering", "Flow",
    "Assignment",
]

ACCESS_TYPES = ["READ", "WRITE", "READWRITE"]

# Ordre des couches pour VAL-06 (Realization : couche cible >= couche source,
# Business > Application > Technology). Plus l'indice est petit, plus la couche
# est "haute" (proche du métier).
_LAYER_RANK_FOR_REALIZATION = {"Business": 0, "Application": 1, "Technology": 2}


def validate_element_type(layer: str, element_type: str) -> bool:
    """VAL-01 — elementType doit appartenir au layer donné."""
    return element_type in ELEMENT_TYPES_BY_LAYER.get(layer, ())


def labels_for(layer: str, element_type: str) -> list:
    """Labels Neo4j cumulatifs pour un nouveau nœud ArchiMate (SDD §4 "Stratégie de
    labels") : [elementType, layer, 'ArchiMateElement']."""
    return [element_type, layer, "ArchiMateElement"]


def realization_layer_rank(layer: str):
    """Rang de couche pour VAL-06, ou None si la couche n'est pas concernée par la
    règle (Strategy/Motivation/Physical/Implementation -> pas de WARN)."""
    return _LAYER_RANK_FOR_REALIZATION.get(layer)
