"""Tests unitaires — module archimate_taxonomy (T1-T-01, PLAN_EXPLORATION_v1.md).

Couvre `validate_element_type` et `labels_for` pour les 48 types répartis sur
les 7 layers, plus les cas invalides (VAL-01).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import archimate_taxonomy as archimate


def test_layers_and_element_types_counts():
    assert archimate.LAYERS == [
        "Business", "Application", "Technology", "Strategy",
        "Motivation", "Physical", "Implementation",
    ]
    assert set(archimate.ELEMENT_TYPES_BY_LAYER.keys()) == set(archimate.LAYERS)
    total_types = sum(len(v) for v in archimate.ELEMENT_TYPES_BY_LAYER.values())
    assert total_types == len(archimate.ALL_ELEMENT_TYPES)


def test_validate_element_type_all_valid_pairs():
    for layer, types in archimate.ELEMENT_TYPES_BY_LAYER.items():
        for element_type in types:
            assert archimate.validate_element_type(layer, element_type) is True


def test_validate_element_type_invalid_pairs():
    # Type d'une autre couche
    assert archimate.validate_element_type("Business", "ApplicationComponent") is False
    # Layer inconnu
    assert archimate.validate_element_type("Unknown", "BusinessActor") is False
    # Type inconnu
    assert archimate.validate_element_type("Business", "NotAType") is False


def test_labels_for():
    assert archimate.labels_for("Business", "BusinessActor") == [
        "BusinessActor", "Business", "ArchiMateElement",
    ]
    assert archimate.labels_for("Application", "DataObject") == [
        "DataObject", "Application", "ArchiMateElement",
    ]


def test_aspects_relation_types_access_types():
    assert archimate.ASPECTS == ["ActiveStructure", "Behaviour", "PassiveStructure"]
    assert len(archimate.RELATION_TYPES) == 11
    assert archimate.ACCESS_TYPES == ["READ", "WRITE", "READWRITE"]


def test_realization_layer_rank():
    assert archimate.realization_layer_rank("Business") == 0
    assert archimate.realization_layer_rank("Application") == 1
    assert archimate.realization_layer_rank("Technology") == 2
    assert archimate.realization_layer_rank("Strategy") is None
    assert archimate.realization_layer_rank("Motivation") is None
