"""Tests d'intégration — suppression cascade N6 (T3-T-01, PLAN_EXPLORATION_v1.md).
Exécutés contre le graphe seedé par `seed_exploration_graph` (cf. conftest.py /
exploration_seed.cypher).
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


def _node_and_rel_count(neo4j_driver, node_id):
    with neo4j_driver.session() as session:
        record = session.run(
            "MATCH (n:ArchiMateElement {id: $id}) OPTIONAL MATCH (n)-[r]-() "
            "RETURN n IS NOT NULL AS exists, count(r) AS relCount",
            id=node_id,
        ).single()
        return record["exists"], record["relCount"]


# ----------------------------------------------------------------------------
# N6 — DELETE /exploration/nodes/{id}?cascade=true (RBAC)
# ----------------------------------------------------------------------------

def test_cascade_delete_forbidden_for_architect(seed_exploration_graph):
    node_id = _node_id_by_name(seed_exploration_graph, "Client")
    resp = _call(
        "DELETE", f"exploration/nodes/{node_id}",
        role="ARCHITECT", params={"cascade": "true"},
    )
    assert resp.status_code == 403
    assert _body(resp)["code"] == "AUTH_INSUFFICIENT_ROLE"

    # Le nœud et ses relations doivent rester intacts.
    exists, rel_count = _node_and_rel_count(seed_exploration_graph, node_id)
    assert exists
    assert rel_count > 0


# ----------------------------------------------------------------------------
# N6 — Cascade réussie (ADMIN)
# ----------------------------------------------------------------------------

def test_cascade_delete_success_removes_node_and_relations(seed_exploration_graph):
    # Crée un nœud temporaire + relation vers un nœud du seed.
    create_resp = _call(
        "POST", "exploration/nodes", role="ARCHITECT",
        body={"layer": "Business", "elementType": "BusinessActor", "name": "Acteur Cascade T3-T-01"},
    )
    node_id = _body(create_resp)["id"]
    target_id = _node_id_by_name(seed_exploration_graph, "Datacenter Lyon")

    rel_resp = _call(
        "POST", "exploration/relations", role="ARCHITECT",
        body={"relationType": "Association", "sourceId": node_id, "targetId": target_id},
    )
    assert rel_resp.status_code == 201

    resp = _call(
        "DELETE", f"exploration/nodes/{node_id}",
        role="ADMIN", params={"cascade": "true"},
    )
    assert resp.status_code == 200
    data = _body(resp)
    assert data["deleted"] is True
    assert data["relCount"] == 1

    exists, _ = _node_and_rel_count(seed_exploration_graph, node_id)
    assert exists is False


# ----------------------------------------------------------------------------
# N6 — Rollback transactionnel sur erreur (INTEG-01)
# ----------------------------------------------------------------------------

def test_cascade_delete_rolls_back_on_error(seed_exploration_graph, monkeypatch):
    create_resp = _call(
        "POST", "exploration/nodes", role="ARCHITECT",
        body={"layer": "Business", "elementType": "BusinessActor", "name": "Acteur Cascade Rollback T3-T-01"},
    )
    node_id = _body(create_resp)["id"]
    target_id = _node_id_by_name(seed_exploration_graph, "Datacenter Lyon")

    rel_resp = _call(
        "POST", "exploration/relations", role="ARCHITECT",
        body={"relationType": "Association", "sourceId": node_id, "targetId": target_id},
    )
    assert rel_resp.status_code == 201

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated failure mid-transaction")

    monkeypatch.setattr(function_app, "_exploration_write_audit", _boom)

    resp = _call(
        "DELETE", f"exploration/nodes/{node_id}",
        role="ADMIN", params={"cascade": "true"},
    )
    assert resp.status_code == 500

    # La transaction doit avoir été annulée : nœud + relation toujours présents.
    exists, rel_count = _node_and_rel_count(seed_exploration_graph, node_id)
    assert exists is True
    assert rel_count == 1

    # Nettoyage (sans monkeypatch).
    monkeypatch.undo()
    cleanup_resp = _call(
        "DELETE", f"exploration/nodes/{node_id}",
        role="ADMIN", params={"cascade": "true"},
    )
    assert cleanup_resp.status_code == 200
