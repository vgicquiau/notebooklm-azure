"""Test de cohérence — archimate_taxonomy.py (backend) vs archimateTaxonomy.js
(frontend) (T1-T-01, PLAN_EXPLORATION_v1.md).

Parsing volontairement simple (regex) : suffisant pour détecter une divergence
de contenu entre les deux fichiers, qui doivent rester des miroirs exacts.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import archimate_taxonomy as archimate

JS_PATH = Path(__file__).resolve().parents[3] / "frontend" / "src" / "archimateTaxonomy.js"


def _js_source() -> str:
    assert JS_PATH.exists(), f"Fichier introuvable : {JS_PATH}"
    return JS_PATH.read_text(encoding="utf-8")


def _extract_string_list(js_source: str, start_marker: str) -> list[str]:
    """Extrait la première liste `['a', 'b', ...]` (ou `["a", "b", ...]`) qui suit
    `start_marker` dans le source JS, jusqu'au premier `]`."""
    idx = js_source.index(start_marker)
    bracket_start = js_source.index("[", idx)
    bracket_end = js_source.index("]", bracket_start)
    segment = js_source[bracket_start:bracket_end + 1]
    return re.findall(r"['\"]([^'\"]+)['\"]", segment)


def _extract_object_block(js_source: str, start_marker: str) -> str:
    """Extrait le bloc `{ ... }` qui suit `start_marker` (comptage d'accolades)."""
    idx = js_source.index(start_marker)
    brace_start = js_source.index("{", idx)
    depth = 0
    for i in range(brace_start, len(js_source)):
        if js_source[i] == "{":
            depth += 1
        elif js_source[i] == "}":
            depth -= 1
            if depth == 0:
                return js_source[brace_start:i + 1]
    raise ValueError(f"Bloc non terminé pour {start_marker!r}")


def test_layers_match():
    js = _js_source()
    js_layers = _extract_string_list(js, "const LAYERS = ")
    assert js_layers == archimate.LAYERS


def test_element_types_by_layer_match():
    js = _js_source()
    block = _extract_object_block(js, "const ELEMENT_TYPES_BY_LAYER = ")
    for layer, py_types in archimate.ELEMENT_TYPES_BY_LAYER.items():
        # Repère la clé `LayerName: [...]` dans le bloc JS
        key_idx = block.index(layer + ":")
        js_types = _extract_string_list(block[key_idx:], "[")
        assert js_types == py_types, f"Divergence pour la couche {layer}"


def test_aspects_match():
    js = _js_source()
    js_aspects = _extract_string_list(js, "const ASPECTS = ")
    assert js_aspects == archimate.ASPECTS


def test_relation_types_match():
    js = _js_source()
    js_relations = _extract_string_list(js, "const RELATION_TYPES = ")
    assert js_relations == archimate.RELATION_TYPES


def test_access_types_match():
    js = _js_source()
    js_access = _extract_string_list(js, "const ACCESS_TYPES = ")
    assert js_access == archimate.ACCESS_TYPES
