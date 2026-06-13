"""Tests d'intégration — module Exploration, CRUD relations R1-R5 (T2-T-02,
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


# ----------------------------------------------------------------------------
# R1 — GET /exploration/relations (liste, filtres)
# ----------------------------------------------------------------------------

def test_list_relations_filter_by_source_and_target(seed_exploration_graph):
    client_id = _node_id_by_name(seed_exploration_graph, "Client")
    souscrire_id = _node_id_by_name(seed_exploration_graph, "Souscrire Contrat")

    resp = _call(
        "GET", "exploration/relations",
        params={"sourceId": client_id, "targetId": souscrire_id},
    )
    assert resp.status_code == 200
    data = _body(resp)
    assert data["total"] == 1
    assert data["items"][0]["relationType"] == "Assignment"
    assert data["items"][0]["source"]["name"] == "Client"
    assert data["items"][0]["target"]["name"] == "Souscrire Contrat"


def test_list_relations_filter_by_type_and_source_layer(seed_exploration_graph):
    resp = _call(
        "GET", "exploration/relations",
        params={"relationType": "Realization", "sourceLayer": "Technology"},
    )
    assert resp.status_code == 200
    data = _body(resp)
    assert data["total"] >= 1
    assert all(item["relationType"] == "Realization" for item in data["items"])
    assert all(item["source"]["layer"] == "Technology" for item in data["items"])


def test_list_relations_invalid_relation_type(seed_exploration_graph):
    resp = _call("GET", "exploration/relations", params={"relationType": "NotAType"})
    assert resp.status_code == 400
    assert _body(resp)["code"] == "VAL_RELATION_TYPE"


def test_list_relations_invalid_source_layer(seed_exploration_graph):
    resp = _call("GET", "exploration/relations", params={"sourceLayer": "NotALayer"})
    assert resp.status_code == 400
    assert _body(resp)["code"] == "VAL_LAYER"


# ----------------------------------------------------------------------------
# R2 — GET /exploration/relations/{id}
# ----------------------------------------------------------------------------

def test_get_relation_detail(seed_exploration_graph):
    rel_id = _rel_id_by_names(seed_exploration_graph, "API Souscription", "Souscrire Contrat", "Serving")

    resp = _call("GET", f"exploration/relations/{rel_id}")
    assert resp.status_code == 200
    data = _body(resp)
    assert data["relationType"] == "Serving"
    assert data["source"]["name"] == "API Souscription"
    assert data["target"]["name"] == "Souscrire Contrat"
    assert "aspect" in data["source"]


def test_get_relation_not_found(seed_exploration_graph):
    resp = _call("GET", "exploration/relations/does-not-exist")
    assert resp.status_code == 404
    assert _body(resp)["code"] == "RELATION_NOT_FOUND"


# ----------------------------------------------------------------------------
# R3 — POST /exploration/relations (création, sans avertissement)
# ----------------------------------------------------------------------------

def test_create_relation_success(seed_exploration_graph):
    datacenter_id = _node_id_by_name(seed_exploration_graph, "Datacenter Lyon")
    serveur_id = _node_id_by_name(seed_exploration_graph, "ServeurAppli")

    resp = _call(
        "POST", "exploration/relations", role="ARCHITECT",
        body={
            "relationType": "Association",
            "sourceId": datacenter_id, "targetId": serveur_id,
            "name": "Relation Test R3",
        },
    )
    assert resp.status_code == 201
    data = _body(resp)
    assert data["relationType"] == "Association"
    assert data["name"] == "Relation Test R3"
    assert data["source"]["name"] == "Datacenter Lyon"
    assert data["target"]["name"] == "ServeurAppli"
    assert "id" in data

    delete_resp = _call("DELETE", f"exploration/relations/{data['id']}", role="ARCHITECT")
    assert delete_resp.status_code == 200


def test_create_relation_invalid_relation_type(seed_exploration_graph):
    datacenter_id = _node_id_by_name(seed_exploration_graph, "Datacenter Lyon")
    serveur_id = _node_id_by_name(seed_exploration_graph, "ServeurAppli")

    resp = _call(
        "POST", "exploration/relations", role="ARCHITECT",
        body={"relationType": "NotAType", "sourceId": datacenter_id, "targetId": serveur_id},
    )
    assert resp.status_code == 400
    assert _body(resp)["code"] == "VAL_RELATION_TYPE"


def test_create_relation_access_missing_access_type(seed_exploration_graph):
    datacenter_id = _node_id_by_name(seed_exploration_graph, "Datacenter Lyon")
    serveur_id = _node_id_by_name(seed_exploration_graph, "ServeurAppli")

    resp = _call(
        "POST", "exploration/relations", role="ARCHITECT",
        body={"relationType": "Access", "sourceId": datacenter_id, "targetId": serveur_id},
    )
    assert resp.status_code == 400
    assert _body(resp)["code"] == "VAL_ACCESS_TYPE"


def test_create_relation_access_invalid_access_type_value(seed_exploration_graph):
    datacenter_id = _node_id_by_name(seed_exploration_graph, "Datacenter Lyon")
    serveur_id = _node_id_by_name(seed_exploration_graph, "ServeurAppli")

    resp = _call(
        "POST", "exploration/relations", role="ARCHITECT",
        body={
            "relationType": "Access", "accessType": "INVALID",
            "sourceId": datacenter_id, "targetId": serveur_id,
        },
    )
    assert resp.status_code == 400
    assert _body(resp)["code"] == "VAL_ACCESS_TYPE_VALUE"


def test_create_relation_invalid_weight(seed_exploration_graph):
    datacenter_id = _node_id_by_name(seed_exploration_graph, "Datacenter Lyon")
    serveur_id = _node_id_by_name(seed_exploration_graph, "ServeurAppli")

    resp = _call(
        "POST", "exploration/relations", role="ARCHITECT",
        body={
            "relationType": "Association", "weight": 1.5,
            "sourceId": datacenter_id, "targetId": serveur_id,
        },
    )
    assert resp.status_code == 400
    assert _body(resp)["code"] == "VAL_WEIGHT_RANGE"


def test_create_relation_node_not_found(seed_exploration_graph):
    serveur_id = _node_id_by_name(seed_exploration_graph, "ServeurAppli")

    resp = _call(
        "POST", "exploration/relations", role="ARCHITECT",
        body={
            "relationType": "Association",
            "sourceId": "does-not-exist", "targetId": serveur_id,
        },
    )
    assert resp.status_code == 404
    assert _body(resp)["code"] == "NODE_NOT_FOUND"


def test_create_relation_forbidden_for_viewer(seed_exploration_graph):
    datacenter_id = _node_id_by_name(seed_exploration_graph, "Datacenter Lyon")
    serveur_id = _node_id_by_name(seed_exploration_graph, "ServeurAppli")

    resp = _call(
        "POST", "exploration/relations", role="VIEWER",
        body={"relationType": "Association", "sourceId": datacenter_id, "targetId": serveur_id},
    )
    assert resp.status_code == 403
    assert _body(resp)["code"] == "AUTH_INSUFFICIENT_ROLE"


# ----------------------------------------------------------------------------
# R4 — PATCH /exploration/relations/{id}
# ----------------------------------------------------------------------------

def test_update_relation_weight_and_name(seed_exploration_graph):
    datacenter_id = _node_id_by_name(seed_exploration_graph, "Datacenter Lyon")
    serveur_id = _node_id_by_name(seed_exploration_graph, "ServeurAppli")

    create_resp = _call(
        "POST", "exploration/relations", role="ARCHITECT",
        body={"relationType": "Association", "sourceId": datacenter_id, "targetId": serveur_id},
    )
    rel_id = _body(create_resp)["id"]

    patch_resp = _call(
        "PATCH", f"exploration/relations/{rel_id}", role="ARCHITECT",
        body={"weight": 0.5, "name": "Mis à jour R4"},
    )
    assert patch_resp.status_code == 200
    data = _body(patch_resp)
    assert data["weight"] == 0.5
    assert data["name"] == "Mis à jour R4"

    _call("DELETE", f"exploration/relations/{rel_id}", role="ARCHITECT")


def test_update_relation_invalid_weight(seed_exploration_graph):
    rel_id = _rel_id_by_names(seed_exploration_graph, "Direction Commerciale", "Capacité Souscription", "Association")

    resp = _call(
        "PATCH", f"exploration/relations/{rel_id}", role="ARCHITECT",
        body={"weight": 2},
    )
    assert resp.status_code == 400
    assert _body(resp)["code"] == "VAL_WEIGHT_RANGE"


def test_update_relation_access_type_required(seed_exploration_graph):
    rel_id = _rel_id_by_names(seed_exploration_graph, "AppSouscription", "Contrat", "Access")

    resp = _call(
        "PATCH", f"exploration/relations/{rel_id}", role="ARCHITECT",
        body={"accessType": None},
    )
    assert resp.status_code == 400
    assert _body(resp)["code"] == "VAL_ACCESS_TYPE"


def test_update_relation_access_type_invalid_value(seed_exploration_graph):
    rel_id = _rel_id_by_names(seed_exploration_graph, "AppSouscription", "Contrat", "Access")

    resp = _call(
        "PATCH", f"exploration/relations/{rel_id}", role="ARCHITECT",
        body={"accessType": "INVALID"},
    )
    assert resp.status_code == 400
    assert _body(resp)["code"] == "VAL_ACCESS_TYPE_VALUE"


def test_update_relation_not_found(seed_exploration_graph):
    resp = _call(
        "PATCH", "exploration/relations/does-not-exist", role="ARCHITECT",
        body={"weight": 0.5},
    )
    assert resp.status_code == 404
    assert _body(resp)["code"] == "RELATION_NOT_FOUND"


# ----------------------------------------------------------------------------
# R5 — DELETE /exploration/relations/{id}
# ----------------------------------------------------------------------------

def test_delete_relation_success_then_not_found(seed_exploration_graph):
    datacenter_id = _node_id_by_name(seed_exploration_graph, "Datacenter Lyon")
    serveur_id = _node_id_by_name(seed_exploration_graph, "ServeurAppli")

    create_resp = _call(
        "POST", "exploration/relations", role="ARCHITECT",
        body={"relationType": "Association", "sourceId": datacenter_id, "targetId": serveur_id},
    )
    rel_id = _body(create_resp)["id"]

    resp = _call("DELETE", f"exploration/relations/{rel_id}", role="ARCHITECT")
    assert resp.status_code == 200
    assert _body(resp) == {"deleted": True}

    second_resp = _call("DELETE", f"exploration/relations/{rel_id}", role="ARCHITECT")
    assert second_resp.status_code == 404
    assert _body(second_resp)["code"] == "RELATION_NOT_FOUND"
