"""Tests d'intégration — validations ArchiMate VAL-05/06/07/08 sur
POST /exploration/relations (T2-T-01, PLAN_EXPLORATION_v1.md). 1 cas positif
(warning levé, bloqué en 422 puis confirmé via confirmWarnings) + 1 cas négatif
(pas de warning, création directe) par règle. Exécutés contre le graphe seedé
par `seed_exploration_graph` (cf. conftest.py / exploration_seed.cypher).
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


def _create_relation(source_id, target_id, relation_type, confirm_warnings=False):
    return _call(
        "POST", "exploration/relations", role="ARCHITECT",
        body={
            "relationType": relation_type,
            "sourceId": source_id, "targetId": target_id,
            "confirmWarnings": confirm_warnings,
        },
    )


# ----------------------------------------------------------------------------
# VAL-07 (R-CHECK) — relation dupliquée
# ----------------------------------------------------------------------------

def test_val07_duplicate_relation_warns_then_confirms(seed_exploration_graph):
    client_id = _node_id_by_name(seed_exploration_graph, "Client")
    souscrire_id = _node_id_by_name(seed_exploration_graph, "Souscrire Contrat")

    # Cas positif : Assignment Client -> Souscrire Contrat existe déjà dans le seed.
    warn_resp = _create_relation(client_id, souscrire_id, "Assignment")
    assert warn_resp.status_code == 422
    warn_data = _body(warn_resp)
    assert warn_data["code"] == "ARCHIMATE_WARN"
    codes = {w["code"] for w in warn_data["warnings"]}
    assert "VAL_DUPLICATE_REL" in codes

    confirm_resp = _create_relation(client_id, souscrire_id, "Assignment", confirm_warnings=True)
    assert confirm_resp.status_code == 201
    rel_id = _body(confirm_resp)["id"]
    _call("DELETE", f"exploration/relations/{rel_id}", role="ARCHITECT")


def test_val07_no_duplicate_creates_directly(seed_exploration_graph):
    # Cas négatif : aucune Association n'existe entre ces deux nœuds dans le seed.
    souscrire_id = _node_id_by_name(seed_exploration_graph, "Souscrire Contrat")
    service_id = _node_id_by_name(seed_exploration_graph, "Service Souscription")

    resp = _create_relation(souscrire_id, service_id, "Aggregation")
    assert resp.status_code == 201
    rel_id = _body(resp)["id"]
    _call("DELETE", f"exploration/relations/{rel_id}", role="ARCHITECT")


# ----------------------------------------------------------------------------
# VAL-05 — Assignment depuis un élément non-ActiveStructure
# ----------------------------------------------------------------------------

def test_val05_assignment_from_non_active_structure_warns_then_confirms(seed_exploration_graph):
    # Cas positif : "Souscrire Contrat" a aspect=Behaviour.
    souscrire_id = _node_id_by_name(seed_exploration_graph, "Souscrire Contrat")
    contrat_signe_id = _node_id_by_name(seed_exploration_graph, "Contrat Signé")

    warn_resp = _create_relation(souscrire_id, contrat_signe_id, "Assignment")
    assert warn_resp.status_code == 422
    warn_data = _body(warn_resp)
    assert warn_data["code"] == "ARCHIMATE_WARN"
    codes = {w["code"] for w in warn_data["warnings"]}
    assert "VAL_ASSIGNMENT_ASPECT" in codes

    confirm_resp = _create_relation(souscrire_id, contrat_signe_id, "Assignment", confirm_warnings=True)
    assert confirm_resp.status_code == 201
    rel_id = _body(confirm_resp)["id"]
    _call("DELETE", f"exploration/relations/{rel_id}", role="ARCHITECT")


def test_val05_assignment_from_active_structure_creates_directly(seed_exploration_graph):
    # Cas négatif : "Client" a aspect=ActiveStructure.
    client_id = _node_id_by_name(seed_exploration_graph, "Client")
    contrat_signe_id = _node_id_by_name(seed_exploration_graph, "Contrat Signé")

    resp = _create_relation(client_id, contrat_signe_id, "Assignment")
    assert resp.status_code == 201
    rel_id = _body(resp)["id"]
    _call("DELETE", f"exploration/relations/{rel_id}", role="ARCHITECT")


# ----------------------------------------------------------------------------
# VAL-06 — Realization vers une couche de rang inférieur
# ----------------------------------------------------------------------------

def test_val06_realization_to_lower_layer_warns_then_confirms(seed_exploration_graph):
    # Cas positif : ServeurAppli (Technology, rang 2) réalise API Souscription
    # (Application, rang 1) -> rang cible < rang source.
    serveur_id = _node_id_by_name(seed_exploration_graph, "ServeurAppli")
    api_id = _node_id_by_name(seed_exploration_graph, "API Souscription")

    warn_resp = _create_relation(serveur_id, api_id, "Realization")
    assert warn_resp.status_code == 422
    warn_data = _body(warn_resp)
    assert warn_data["code"] == "ARCHIMATE_WARN"
    codes = {w["code"] for w in warn_data["warnings"]}
    assert "VAL_REALIZATION_LAYER" in codes

    confirm_resp = _create_relation(serveur_id, api_id, "Realization", confirm_warnings=True)
    assert confirm_resp.status_code == 201
    rel_id = _body(confirm_resp)["id"]
    _call("DELETE", f"exploration/relations/{rel_id}", role="ARCHITECT")


def test_val06_realization_same_layer_rank_creates_directly(seed_exploration_graph):
    # Cas négatif : Client et Souscrire Contrat sont tous deux Business (rang 0),
    # rang cible (0) >= rang source (0) -> pas de warning VAL-06.
    client_id = _node_id_by_name(seed_exploration_graph, "Client")
    souscrire_id = _node_id_by_name(seed_exploration_graph, "Souscrire Contrat")

    resp = _create_relation(client_id, souscrire_id, "Realization")
    assert resp.status_code == 201
    rel_id = _body(resp)["id"]
    _call("DELETE", f"exploration/relations/{rel_id}", role="ARCHITECT")


# ----------------------------------------------------------------------------
# VAL-08 — Composition/Aggregation cross-layer
# ----------------------------------------------------------------------------

def test_val08_structural_cross_layer_warns_then_confirms(seed_exploration_graph):
    # Cas positif : Datacenter Lyon (Physical) agrège ServeurAppli (Technology).
    datacenter_id = _node_id_by_name(seed_exploration_graph, "Datacenter Lyon")
    serveur_id = _node_id_by_name(seed_exploration_graph, "ServeurAppli")

    warn_resp = _create_relation(datacenter_id, serveur_id, "Aggregation")
    assert warn_resp.status_code == 422
    warn_data = _body(warn_resp)
    assert warn_data["code"] == "ARCHIMATE_WARN"
    codes = {w["code"] for w in warn_data["warnings"]}
    assert "VAL_STRUCTURAL_CROSS_LAYER" in codes

    confirm_resp = _create_relation(datacenter_id, serveur_id, "Aggregation", confirm_warnings=True)
    assert confirm_resp.status_code == 201
    rel_id = _body(confirm_resp)["id"]
    _call("DELETE", f"exploration/relations/{rel_id}", role="ARCHITECT")


def test_val08_structural_same_layer_creates_directly(seed_exploration_graph):
    # Cas négatif : Souscrire Contrat et Service Souscription sont tous deux Business.
    souscrire_id = _node_id_by_name(seed_exploration_graph, "Souscrire Contrat")
    service_id = _node_id_by_name(seed_exploration_graph, "Service Souscription")

    resp = _create_relation(souscrire_id, service_id, "Composition")
    assert resp.status_code == 201
    rel_id = _body(resp)["id"]
    _call("DELETE", f"exploration/relations/{rel_id}", role="ARCHITECT")
