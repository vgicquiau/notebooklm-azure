"""Tests d'intégration — exhaustivité AuditLog (T4-T-01, PLAN_EXPLORATION_v1.md)
et GET /exploration/audit (T4-B-02). Exécutés contre le graphe seedé par
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


def _audit_entries_for(entity_id, operation=None):
    params = {"entityId": entity_id, "limit": "50"}
    if operation:
        params["operation"] = operation
    resp = _call("GET", "exploration/audit", role="ADMIN", params=params)
    assert resp.status_code == 200
    return _body(resp)["items"]


# ----------------------------------------------------------------------------
# GET /exploration/audit — RBAC
# ----------------------------------------------------------------------------

def test_list_audit_forbidden_for_architect(seed_exploration_graph):
    resp = _call("GET", "exploration/audit", role="ARCHITECT")
    assert resp.status_code == 403
    assert _body(resp)["code"] == "AUTH_INSUFFICIENT_ROLE"


def test_list_audit_invalid_operation(seed_exploration_graph):
    resp = _call("GET", "exploration/audit", role="ADMIN", params={"operation": "NOPE"})
    assert resp.status_code == 400
    assert _body(resp)["code"] == "VAL_AUDIT_OPERATION"


# ----------------------------------------------------------------------------
# N3 — Create Node
# ----------------------------------------------------------------------------

def test_audit_create_node(seed_exploration_graph):
    resp = _call(
        "POST", "exploration/nodes", role="ARCHITECT",
        body={"layer": "Business", "elementType": "BusinessActor", "name": "Acteur Audit N3"},
    )
    node_id = _body(resp)["id"]

    entries = _audit_entries_for(node_id, operation="CREATE")
    assert len(entries) == 1
    entry = entries[0]
    assert entry["entityType"] == "NODE"
    assert entry["payload"]["before"] is None
    assert entry["payload"]["after"]["name"] == "Acteur Audit N3"

    _call("DELETE", f"exploration/nodes/{node_id}", role="ARCHITECT")


# ----------------------------------------------------------------------------
# N4 — Update Node
# ----------------------------------------------------------------------------

def test_audit_update_node(seed_exploration_graph):
    create_resp = _call(
        "POST", "exploration/nodes", role="ARCHITECT",
        body={"layer": "Business", "elementType": "BusinessActor", "name": "Acteur Audit N4", "description": "Avant"},
    )
    node_id = _body(create_resp)["id"]

    _call("PATCH", f"exploration/nodes/{node_id}", role="ARCHITECT", body={"description": "Après"})

    entries = _audit_entries_for(node_id, operation="UPDATE")
    assert len(entries) == 1
    entry = entries[0]
    assert entry["entityType"] == "NODE"
    assert entry["payload"]["before"]["description"] == "Avant"
    assert entry["payload"]["after"]["description"] == "Après"

    _call("DELETE", f"exploration/nodes/{node_id}", role="ARCHITECT")


# ----------------------------------------------------------------------------
# N5 — Delete Node (safe)
# ----------------------------------------------------------------------------

def test_audit_delete_node_safe(seed_exploration_graph):
    create_resp = _call(
        "POST", "exploration/nodes", role="ARCHITECT",
        body={"layer": "Business", "elementType": "BusinessActor", "name": "Acteur Audit N5"},
    )
    node_id = _body(create_resp)["id"]

    _call("DELETE", f"exploration/nodes/{node_id}", role="ARCHITECT")

    entries = _audit_entries_for(node_id, operation="DELETE")
    assert len(entries) == 1
    entry = entries[0]
    assert entry["entityType"] == "NODE"
    assert entry["payload"]["after"] is None
    assert entry["payload"]["before"]["name"] == "Acteur Audit N5"


# ----------------------------------------------------------------------------
# N6 — Delete Node (cascade)
# ----------------------------------------------------------------------------

def test_audit_delete_node_cascade(seed_exploration_graph):
    create_resp = _call(
        "POST", "exploration/nodes", role="ARCHITECT",
        body={"layer": "Business", "elementType": "BusinessActor", "name": "Acteur Audit N6"},
    )
    node_id = _body(create_resp)["id"]
    target_id = _node_id_by_name(seed_exploration_graph, "Datacenter Lyon")

    rel_resp = _call(
        "POST", "exploration/relations", role="ARCHITECT",
        body={"relationType": "Association", "sourceId": node_id, "targetId": target_id},
    )
    assert rel_resp.status_code == 201

    cascade_resp = _call(
        "DELETE", f"exploration/nodes/{node_id}", role="ADMIN", params={"cascade": "true"},
    )
    assert cascade_resp.status_code == 200

    entries = _audit_entries_for(node_id, operation="DELETE_CASCADE")
    assert len(entries) == 1
    entry = entries[0]
    assert entry["entityType"] == "NODE"
    assert entry["payload"]["after"]["relCount"] == 1


# ----------------------------------------------------------------------------
# N8 — Bulk tag
# ----------------------------------------------------------------------------

def test_audit_bulk_tag(seed_exploration_graph):
    create_resp = _call(
        "POST", "exploration/nodes", role="ARCHITECT",
        body={"layer": "Business", "elementType": "BusinessActor", "name": "Acteur Audit N8"},
    )
    node_id = _body(create_resp)["id"]

    resp = _call(
        "POST", "exploration/nodes/bulk-tag", role="ARCHITECT",
        body={"nodeIds": [node_id], "action": "add", "tag": "audit-test"},
    )
    assert resp.status_code == 200

    entries = _audit_entries_for(node_id, operation="UPDATE")
    assert len(entries) == 1
    entry = entries[0]
    assert entry["entityType"] == "NODE"
    assert "audit-test" in entry["payload"]["after"]["tags"]

    _call("DELETE", f"exploration/nodes/{node_id}", role="ARCHITECT")


# ----------------------------------------------------------------------------
# R3 — Create Relation
# ----------------------------------------------------------------------------

def test_audit_create_relation(seed_exploration_graph):
    datacenter_id = _node_id_by_name(seed_exploration_graph, "Datacenter Lyon")
    serveur_id = _node_id_by_name(seed_exploration_graph, "ServeurAppli")

    resp = _call(
        "POST", "exploration/relations", role="ARCHITECT",
        body={"relationType": "Association", "sourceId": datacenter_id, "targetId": serveur_id},
    )
    rel_id = _body(resp)["id"]

    entries = _audit_entries_for(rel_id, operation="CREATE")
    assert len(entries) == 1
    entry = entries[0]
    assert entry["entityType"] == "RELATION"
    assert entry["payload"]["before"] is None
    assert entry["payload"]["after"]["relationType"] == "Association"

    _call("DELETE", f"exploration/relations/{rel_id}", role="ARCHITECT")


# ----------------------------------------------------------------------------
# R4 — Update Relation
# ----------------------------------------------------------------------------

def test_audit_update_relation(seed_exploration_graph):
    datacenter_id = _node_id_by_name(seed_exploration_graph, "Datacenter Lyon")
    serveur_id = _node_id_by_name(seed_exploration_graph, "ServeurAppli")

    create_resp = _call(
        "POST", "exploration/relations", role="ARCHITECT",
        body={"relationType": "Association", "sourceId": datacenter_id, "targetId": serveur_id},
    )
    rel_id = _body(create_resp)["id"]

    _call("PATCH", f"exploration/relations/{rel_id}", role="ARCHITECT", body={"weight": 0.5})

    entries = _audit_entries_for(rel_id, operation="UPDATE")
    assert len(entries) == 1
    entry = entries[0]
    assert entry["entityType"] == "RELATION"
    assert entry["payload"]["after"]["weight"] == 0.5

    _call("DELETE", f"exploration/relations/{rel_id}", role="ARCHITECT")


# ----------------------------------------------------------------------------
# R5 — Delete Relation
# ----------------------------------------------------------------------------

def test_audit_delete_relation(seed_exploration_graph):
    datacenter_id = _node_id_by_name(seed_exploration_graph, "Datacenter Lyon")
    serveur_id = _node_id_by_name(seed_exploration_graph, "ServeurAppli")

    create_resp = _call(
        "POST", "exploration/relations", role="ARCHITECT",
        body={"relationType": "Association", "sourceId": datacenter_id, "targetId": serveur_id},
    )
    rel_id = _body(create_resp)["id"]

    _call("DELETE", f"exploration/relations/{rel_id}", role="ARCHITECT")

    entries = _audit_entries_for(rel_id, operation="DELETE")
    assert len(entries) == 1
    entry = entries[0]
    assert entry["entityType"] == "RELATION"
    assert entry["payload"]["after"] is None
