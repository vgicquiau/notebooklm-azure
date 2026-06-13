"""Tests d'intégration — matrice RBAC complète (T3-T-02, PLAN_EXPLORATION_v1.md
SDD §8). 13 opérations × 3 rôles (VIEWER/ARCHITECT/ADMIN) = 39 cas, vérifiés
contre le graphe seedé par `seed_exploration_graph` (cf. conftest.py /
exploration_seed.cypher).
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import azure.functions as func
import function_app


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

ROLES = ["VIEWER", "ARCHITECT", "ADMIN"]


def _request(method, sub_path, role=None, params=None, body=None):
    headers = {}
    if role:
        headers["X-User-Role"] = role
    return func.HttpRequest(
        method=method,
        url=f"/api/graph/{sub_path}",
        headers=headers,
        params=params or {},
        route_params={"path": sub_path},
        body=json.dumps(body).encode("utf-8") if body is not None else b"",
    )


def _call(method, sub_path, **kw):
    return function_app.main(_request(method, sub_path, **kw))


def _body(resp):
    return json.loads(resp.get_body())


def _node_id_by_name(neo4j_driver, name):
    with neo4j_driver.session() as session:
        record = session.run(
            "MATCH (n:ArchiMateElement {name: $name, seedTest: true}) RETURN n.id AS id",
            name=name,
        ).single()
        assert record is not None, f"Nœud de seed introuvable : {name}"
        return record["id"]


def _rel_id_by_names(neo4j_driver, source_name, target_name, rel_type):
    with neo4j_driver.session() as session:
        record = session.run(
            f"""
            MATCH (a:ArchiMateElement {{name: $source, seedTest: true}})
                  -[r:`{rel_type}`]->
                  (b:ArchiMateElement {{name: $target, seedTest: true}})
            RETURN r.id AS id
            """,
            source=source_name, target=target_name,
        ).single()
        assert record is not None, (
            f"Relation de seed introuvable : {source_name} -{rel_type}-> {target_name}"
        )
        return record["id"]


def _create_temp_node(name):
    resp = _call(
        "POST", "exploration/nodes", role="ARCHITECT",
        body={"layer": "Business", "elementType": "BusinessActor", "name": name},
    )
    assert resp.status_code == 201
    return _body(resp)["id"]


def _delete_temp_node(node_id):
    _call("DELETE", f"exploration/nodes/{node_id}", role="ADMIN", params={"cascade": "true"})


def _create_temp_relation(source_id, target_id, relation_type="Association"):
    resp = _call(
        "POST", "exploration/relations", role="ARCHITECT",
        body={"relationType": relation_type, "sourceId": source_id, "targetId": target_id},
    )
    assert resp.status_code == 201
    return _body(resp)["id"]


# ----------------------------------------------------------------------------
# Opérations — chacune retourne la réponse HTTP pour le rôle donné, et nettoie
# toute ressource temporaire qu'elle a créée.
# ----------------------------------------------------------------------------

def _op_list_nodes(role, ctx):
    return _call("GET", "exploration/nodes", role=role, params={"limit": "5"})


def _op_read_node(role, ctx):
    return _call("GET", f"exploration/nodes/{ctx['orphan_id']}", role=role)


def _op_create_node(role, ctx):
    resp = _call(
        "POST", "exploration/nodes", role=role,
        body={"layer": "Business", "elementType": "BusinessActor", "name": f"RBAC Create {role}"},
    )
    if resp.status_code == 201:
        _delete_temp_node(_body(resp)["id"])
    return resp


def _op_update_node(role, ctx):
    node_id = _create_temp_node(f"RBAC Update {role}")
    resp = _call(
        "PATCH", f"exploration/nodes/{node_id}", role=role,
        body={"description": "rbac-update"},
    )
    _delete_temp_node(node_id)
    return resp


def _op_delete_node_safe(role, ctx):
    node_id = _create_temp_node(f"RBAC Delete Safe {role}")
    resp = _call("DELETE", f"exploration/nodes/{node_id}", role=role)
    if resp.status_code != 200:
        _delete_temp_node(node_id)
    return resp


def _op_delete_node_cascade(role, ctx):
    node_id = _create_temp_node(f"RBAC Delete Cascade {role}")
    resp = _call("DELETE", f"exploration/nodes/{node_id}", role=role, params={"cascade": "true"})
    if resp.status_code != 200:
        _delete_temp_node(node_id)
    return resp


def _op_list_orphans(role, ctx):
    return _call("GET", "exploration/orphans", role=role, params={"limit": "5"})


def _op_bulk_tag(role, ctx):
    node_id = _create_temp_node(f"RBAC Bulk Tag {role}")
    resp = _call(
        "POST", "exploration/nodes/bulk-tag", role=role,
        body={"nodeIds": [node_id], "action": "add", "tag": "rbac-test"},
    )
    _delete_temp_node(node_id)
    return resp


def _op_list_relations(role, ctx):
    return _call("GET", "exploration/relations", role=role, params={"limit": "5"})


def _op_read_relation(role, ctx):
    return _call("GET", f"exploration/relations/{ctx['rel_id']}", role=role)


def _op_create_relation(role, ctx):
    resp = _call(
        "POST", "exploration/relations", role=role,
        body={
            "relationType": "Association",
            "sourceId": ctx["datacenter_id"], "targetId": ctx["serveur_id"],
        },
    )
    if resp.status_code == 201:
        _call("DELETE", f"exploration/relations/{_body(resp)['id']}", role="ARCHITECT")
    return resp


def _op_update_relation(role, ctx):
    rel_id = _create_temp_relation(ctx["datacenter_id"], ctx["serveur_id"])
    resp = _call(
        "PATCH", f"exploration/relations/{rel_id}", role=role,
        body={"weight": 0.5},
    )
    _call("DELETE", f"exploration/relations/{rel_id}", role="ARCHITECT")
    return resp


def _op_delete_relation(role, ctx):
    rel_id = _create_temp_relation(ctx["datacenter_id"], ctx["serveur_id"])
    resp = _call("DELETE", f"exploration/relations/{rel_id}", role=role)
    if resp.status_code != 200:
        _call("DELETE", f"exploration/relations/{rel_id}", role="ARCHITECT")
    return resp


# ----------------------------------------------------------------------------
# Matrice — clé : op_id -> (handler, {role: statut_attendu})
# Statuts conformes à SDD §8 RBAC + comportements R3/R5/N5/N6 déjà testés en
# Phase 1/2 (✅ -> statut succès de l'opération, ❌ -> 403 AUTH_INSUFFICIENT_ROLE).
# ----------------------------------------------------------------------------

MATRIX = {
    "N1_list_nodes":          (_op_list_nodes,          {"VIEWER": 200, "ARCHITECT": 200, "ADMIN": 200}),
    "N2_read_node":           (_op_read_node,           {"VIEWER": 200, "ARCHITECT": 200, "ADMIN": 200}),
    "N3_create_node":         (_op_create_node,         {"VIEWER": 403, "ARCHITECT": 201, "ADMIN": 201}),
    "N4_update_node":         (_op_update_node,         {"VIEWER": 403, "ARCHITECT": 200, "ADMIN": 200}),
    "N5_delete_node_safe":    (_op_delete_node_safe,    {"VIEWER": 403, "ARCHITECT": 200, "ADMIN": 200}),
    "N6_delete_node_cascade": (_op_delete_node_cascade, {"VIEWER": 403, "ARCHITECT": 403, "ADMIN": 200}),
    "N7_list_orphans":        (_op_list_orphans,        {"VIEWER": 403, "ARCHITECT": 200, "ADMIN": 200}),
    "N8_bulk_tag":            (_op_bulk_tag,            {"VIEWER": 403, "ARCHITECT": 200, "ADMIN": 200}),
    "R1_list_relations":      (_op_list_relations,      {"VIEWER": 200, "ARCHITECT": 200, "ADMIN": 200}),
    "R2_read_relation":       (_op_read_relation,       {"VIEWER": 200, "ARCHITECT": 200, "ADMIN": 200}),
    "R3_create_relation":     (_op_create_relation,     {"VIEWER": 403, "ARCHITECT": 201, "ADMIN": 201}),
    "R4_update_relation":     (_op_update_relation,     {"VIEWER": 403, "ARCHITECT": 200, "ADMIN": 200}),
    "R5_delete_relation":     (_op_delete_relation,     {"VIEWER": 403, "ARCHITECT": 200, "ADMIN": 200}),
}

CASES = [
    (op_id, role, expected)
    for op_id, (_, expectations) in MATRIX.items()
    for role, expected in expectations.items()
]


@pytest.fixture(scope="module")
def rbac_ctx(seed_exploration_graph):
    return {
        "orphan_id": _node_id_by_name(seed_exploration_graph, "Datacenter Lyon"),
        "rel_id": _rel_id_by_names(seed_exploration_graph, "Client", "Souscrire Contrat", "Assignment"),
        "datacenter_id": _node_id_by_name(seed_exploration_graph, "Datacenter Lyon"),
        "serveur_id": _node_id_by_name(seed_exploration_graph, "ServeurAppli"),
    }


@pytest.mark.parametrize("op_id,role,expected_status", CASES)
def test_rbac_matrix(rbac_ctx, op_id, role, expected_status):
    handler, _ = MATRIX[op_id]
    resp = handler(role, rbac_ctx)
    assert resp.status_code == expected_status, (
        f"{op_id} / {role} : attendu {expected_status}, obtenu {resp.status_code} "
        f"({_body(resp)})"
    )
    if expected_status == 403:
        assert _body(resp)["code"] == "AUTH_INSUFFICIENT_ROLE"


def test_rbac_matrix_covers_39_cases():
    assert len(CASES) == 39
