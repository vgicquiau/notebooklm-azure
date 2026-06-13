"""Tests d'intégration — module Exploration, CRUD nœuds N1-N7 (T1-T-02,
PLAN_EXPLORATION_v1.md). Exécutés contre le graphe seedé par
`seed_exploration_graph` (cf. conftest.py / exploration_seed.cypher).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import azure.functions as func
import function_app


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

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


# ----------------------------------------------------------------------------
# N1 / N1b — GET /exploration/nodes (liste, filtres, pagination)
# ----------------------------------------------------------------------------

def test_list_nodes_scoped_to_seed(seed_exploration_graph):
    resp = _call("GET", "exploration/nodes", params={"tags": "seed-test", "limit": "200"})
    assert resp.status_code == 200
    data = _body(resp)
    assert data["total"] == 16
    assert len(data["items"]) == 16


def test_list_nodes_filter_by_layer(seed_exploration_graph):
    resp = _call(
        "GET", "exploration/nodes",
        params={"tags": "seed-test", "layer": "Business", "limit": "200"},
    )
    assert resp.status_code == 200
    data = _body(resp)
    assert data["total"] == 4
    assert all(item["layer"] == "Business" for item in data["items"])


def test_list_nodes_limit_clamp(seed_exploration_graph):
    resp = _call("GET", "exploration/nodes", params={"tags": "seed-test", "limit": "500"})
    assert resp.status_code == 200
    data = _body(resp)
    assert data["limit"] == 200


def test_list_nodes_invalid_layer(seed_exploration_graph):
    resp = _call("GET", "exploration/nodes", params={"layer": "NotALayer"})
    assert resp.status_code == 400
    assert _body(resp)["code"] == "VAL_LAYER"


# ----------------------------------------------------------------------------
# N2 — GET /exploration/nodes/{id} (détail + relations)
# ----------------------------------------------------------------------------

def test_get_node_detail_with_relations(seed_exploration_graph):
    node_id = _node_id_by_name(seed_exploration_graph, "Souscrire Contrat")
    resp = _call("GET", f"exploration/nodes/{node_id}")
    assert resp.status_code == 200
    data = _body(resp)
    assert data["node"]["name"] == "Souscrire Contrat"
    # 1 sortante (Triggering vers "Contrat Signé") + 2 entrantes (Serving, Assignment)
    assert len(data["outgoing"]) == 1
    assert len(data["incoming"]) == 2
    assert data["outgoing"][0]["relType"] == "Triggering"
    assert {r["relType"] for r in data["incoming"]} == {"Serving", "Assignment"}


def test_get_node_detail_no_relations(seed_exploration_graph):
    node_id = _node_id_by_name(seed_exploration_graph, "Datacenter Lyon")
    resp = _call("GET", f"exploration/nodes/{node_id}")
    assert resp.status_code == 200
    data = _body(resp)
    assert data["outgoing"] == []
    assert data["incoming"] == []


def test_get_node_not_found(seed_exploration_graph):
    resp = _call("GET", "exploration/nodes/does-not-exist")
    assert resp.status_code == 404
    assert _body(resp)["code"] == "NODE_NOT_FOUND"


# ----------------------------------------------------------------------------
# N3 — POST /exploration/nodes (création + validations)
# ----------------------------------------------------------------------------

def test_create_node_success(seed_exploration_graph):
    resp = _call(
        "POST", "exploration/nodes", role="ARCHITECT",
        body={
            "layer": "Business", "elementType": "BusinessActor",
            "name": "Acteur Test T1-T-02", "tags": ["seed-test"],
        },
    )
    assert resp.status_code == 201
    data = _body(resp)
    assert data["name"] == "Acteur Test T1-T-02"
    assert data["relCount"] == 0
    assert "id" in data

    # Nettoyage
    delete_resp = _call("DELETE", f"exploration/nodes/{data['id']}", role="ARCHITECT")
    assert delete_resp.status_code == 200


def test_create_node_invalid_element_type(seed_exploration_graph):
    resp = _call(
        "POST", "exploration/nodes", role="ARCHITECT",
        body={"layer": "Business", "elementType": "ApplicationComponent", "name": "X"},
    )
    assert resp.status_code == 400
    assert _body(resp)["code"] == "VAL_ELEMENT_TYPE"


def test_create_node_missing_name(seed_exploration_graph):
    resp = _call(
        "POST", "exploration/nodes", role="ARCHITECT",
        body={"layer": "Business", "elementType": "BusinessActor", "name": ""},
    )
    assert resp.status_code == 400
    assert _body(resp)["code"] == "VAL_NAME_REQUIRED"


def test_create_node_forbidden_for_viewer(seed_exploration_graph):
    resp = _call(
        "POST", "exploration/nodes", role="VIEWER",
        body={"layer": "Business", "elementType": "BusinessActor", "name": "X"},
    )
    assert resp.status_code == 403
    assert _body(resp)["code"] == "AUTH_INSUFFICIENT_ROLE"


# ----------------------------------------------------------------------------
# N4 — PATCH /exploration/nodes/{id} (mise à jour partielle, champs immuables)
# ----------------------------------------------------------------------------

def test_update_node_partial_and_immutable_fields(seed_exploration_graph):
    create_resp = _call(
        "POST", "exploration/nodes", role="ARCHITECT",
        body={
            "layer": "Business", "elementType": "BusinessActor",
            "name": "Acteur Update T1-T-02", "description": "Avant", "tags": ["seed-test"],
        },
    )
    node = _body(create_resp)
    node_id, original_created_at = node["id"], node["createdAt"]

    patch_resp = _call(
        "PATCH", f"exploration/nodes/{node_id}", role="ARCHITECT",
        body={"description": "Après", "id": "ignored-id", "createdAt": "ignored-date"},
    )
    assert patch_resp.status_code == 200
    after = _body(patch_resp)
    assert after["description"] == "Après"
    assert after["name"] == "Acteur Update T1-T-02"  # champ omis : inchangé
    assert after["id"] == node_id  # immuable, malgré la valeur envoyée
    assert after["createdAt"] == original_created_at  # immuable

    _call("DELETE", f"exploration/nodes/{node_id}", role="ARCHITECT")


def test_update_node_invalid_name(seed_exploration_graph):
    node_id = _node_id_by_name(seed_exploration_graph, "Datacenter Lyon")
    resp = _call(
        "PATCH", f"exploration/nodes/{node_id}", role="ARCHITECT",
        body={"name": ""},
    )
    assert resp.status_code == 400
    assert _body(resp)["code"] == "VAL_NAME_REQUIRED"


def test_update_node_not_found(seed_exploration_graph):
    resp = _call("PATCH", "exploration/nodes/does-not-exist", role="ARCHITECT", body={"description": "x"})
    assert resp.status_code == 404
    assert _body(resp)["code"] == "NODE_NOT_FOUND"


# ----------------------------------------------------------------------------
# N5 — DELETE /exploration/nodes/{id} (safe delete)
# ----------------------------------------------------------------------------

def test_delete_node_without_relations(seed_exploration_graph):
    create_resp = _call(
        "POST", "exploration/nodes", role="ARCHITECT",
        body={"layer": "Business", "elementType": "BusinessActor", "name": "Acteur Delete T1-T-02"},
    )
    node_id = _body(create_resp)["id"]

    resp = _call("DELETE", f"exploration/nodes/{node_id}", role="ARCHITECT")
    assert resp.status_code == 200
    assert _body(resp) == {"deleted": True}


def test_delete_node_with_relations_returns_409(seed_exploration_graph):
    node_id = _node_id_by_name(seed_exploration_graph, "Client")
    resp = _call("DELETE", f"exploration/nodes/{node_id}", role="ARCHITECT")
    assert resp.status_code == 409
    data = _body(resp)
    assert data["code"] == "NODE_HAS_RELATIONS"
    assert data["relCount"] > 0


def test_delete_node_not_found(seed_exploration_graph):
    resp = _call("DELETE", "exploration/nodes/does-not-exist", role="ARCHITECT")
    assert resp.status_code == 404
    assert _body(resp)["code"] == "NODE_NOT_FOUND"


# ----------------------------------------------------------------------------
# N7 — GET /exploration/orphans
# ----------------------------------------------------------------------------

def test_list_orphans_includes_seed_orphan(seed_exploration_graph):
    resp = _call("GET", "exploration/orphans", role="ARCHITECT", params={"limit": "200"})
    assert resp.status_code == 200
    data = _body(resp)
    names = {item["name"] for item in data["items"]}
    assert "Datacenter Lyon" in names
    orphan = next(item for item in data["items"] if item["name"] == "Datacenter Lyon")
    assert orphan["relCount"] == 0


def test_list_orphans_forbidden_for_viewer(seed_exploration_graph):
    resp = _call("GET", "exploration/orphans", role="VIEWER")
    assert resp.status_code == 403
    assert _body(resp)["code"] == "AUTH_INSUFFICIENT_ROLE"
