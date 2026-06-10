"""
Azure Functions — ADG-M Graph APIs
Module : fn-adgm-graph (Python 3.11, runtime v4)

APIs principales (SDD ADG-M §3) :
- GET /graph/health
- GET /graph/nodes
- GET /graph/nodes/{id}
- GET /graph/arcs
- GET /graph/nodes/{id}/spof (betweenness)
- GET /graph/nodes/{id}/qualification (write-back)

Dépendances (requirements.txt) :
  azure-functions
  neo4j
  pyodbc
  flask
"""

import azure.functions as func
import json
import logging
import os
from neo4j import GraphDatabase
import pyodbc
from datetime import datetime

# ============================================================================
# Configuration
# ============================================================================

NEO4J_URI = os.getenv("NEO4J_BOLT_URI", "bolt://localhost:7687")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "neo4j")
SQL_CONNECTION_STRING = os.getenv("SQL_CONNECTION_STRING")

logger = logging.getLogger(__name__)

_neo4j_driver = None

def get_neo4j_driver():
    global _neo4j_driver
    if not _neo4j_driver:
        _neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=("neo4j", NEO4J_PASSWORD))
    return _neo4j_driver

# ============================================================================
# Helper : Convert Neo4j record to JSON
# ============================================================================

def neo4j_to_dict(record):
    """Convert Neo4j record to Python dict."""
    return dict(record)

# ============================================================================
# API Handlers
# ============================================================================

def get_health() -> func.HttpResponse:
    """GET /graph/health — Simple heartbeat."""
    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            session.run("RETURN 1")
        return func.HttpResponse(
            json.dumps({
                "status": "healthy",
                "timestamp": datetime.utcnow().isoformat(),
                "neo4j": "connected"
            }),
            status_code=200,
            mimetype="application/json"
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return func.HttpResponse(
            json.dumps({"status": "unhealthy", "error": str(e)}),
            status_code=503,
            mimetype="application/json"
        )

def get_nodes(request: func.HttpRequest) -> func.HttpResponse:
    """GET /graph/nodes — Retourner tous les nœuds (ou filtrer par type)."""
    try:
        driver = get_neo4j_driver()
        node_type = request.params.get("type")

        query = "MATCH (n:Component) "
        params = {}

        if node_type:
            query += "WHERE n.type = $type "
            params["type"] = node_type

        query += "RETURN n.id as id, n.name as name, n.type as type, n.criticality as criticality, n.businessValue as businessValue"

        with driver.session() as session:
            results = session.run(query, params)
            nodes = [dict(record) for record in results]

        return func.HttpResponse(
            json.dumps({"nodes": nodes, "count": len(nodes)}),
            status_code=200,
            mimetype="application/json"
        )
    except Exception as e:
        logger.error(f"get_nodes failed: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )

def get_node_by_id(node_id: str) -> func.HttpResponse:
    """GET /graph/nodes/{id} — Détail d'un nœud."""
    try:
        driver = get_neo4j_driver()
        query = """
        MATCH (n:Component {id: $id})
        RETURN n
        """
        with driver.session() as session:
            result = session.run(query, {"id": node_id})
            record = result.single()

        if not record:
            return func.HttpResponse(
                json.dumps({"error": "Component not found"}),
                status_code=404,
                mimetype="application/json"
            )

        node = record["n"]
        node_dict = dict(node)
        return func.HttpResponse(
            json.dumps(node_dict),
            status_code=200,
            mimetype="application/json"
        )
    except Exception as e:
        logger.error(f"get_node_by_id failed: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )

def get_arcs(request: func.HttpRequest) -> func.HttpResponse:
    """GET /graph/arcs — Retourner toutes les relations."""
    try:
        driver = get_neo4j_driver()
        query = """
        MATCH (source:Component)-[r:DEPENDS_ON]->(target:Component)
        RETURN source.id as source, target.id as target, r.type as type, r.confidence as confidence
        """
        with driver.session() as session:
            results = session.run(query)
            arcs = [dict(record) for record in results]

        return func.HttpResponse(
            json.dumps({"arcs": arcs, "count": len(arcs)}),
            status_code=200,
            mimetype="application/json"
        )
    except Exception as e:
        logger.error(f"get_arcs failed: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )

def get_spof(node_id: str) -> func.HttpResponse:
    """GET /graph/nodes/{id}/spof — Betweenness centrality (SPOF indicator)."""
    try:
        driver = get_neo4j_driver()
        # Assume metrics already calculated by Louvain job
        query = """
        MATCH (n:Component {id: $id})
        OPTIONAL MATCH (n)<-[m:METRICS]-()
        RETURN n.id as id, n.name as name,
               COALESCE(m.betweennessCentrality, 0.0) as betweenness,
               COALESCE(m.clusterId, -1) as cluster
        """
        with driver.session() as session:
            result = session.run(query, {"id": node_id})
            record = result.single()

        if not record:
            return func.HttpResponse(
                json.dumps({"error": "Component not found"}),
                status_code=404,
                mimetype="application/json"
            )

        data = dict(record)
        data["isSPOF"] = data["betweenness"] > 0.7
        return func.HttpResponse(
            json.dumps(data),
            status_code=200,
            mimetype="application/json"
        )
    except Exception as e:
        logger.error(f"get_spof failed: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )

def patch_qualification(node_id: str, req_body: dict) -> func.HttpResponse:
    """
    PATCH /graph/nodes/{id}/qualification
    Write-back 7R validation (from 7RQA or ADM-M)

    Body : {
      "sevenRChoice": "Refactor",
      "validationSource": "7RQA",
      "confidence": "ELEVEE"
    }
    """
    try:
        # Log to SQL
        conn = pyodbc.connect(SQL_CONNECTION_STRING)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO dbo.QualificationValidation (componentId, sevenRChoice, validationSource, confidence, validatedBy)
            VALUES (?, ?, ?, ?, ?)
        """, (
            node_id,
            req_body.get("sevenRChoice"),
            req_body.get("validationSource"),
            req_body.get("confidence"),
            "system"
        ))
        conn.commit()
        conn.close()

        return func.HttpResponse(
            json.dumps({"id": node_id, "status": "validated"}),
            status_code=200,
            mimetype="application/json"
        )
    except Exception as e:
        logger.error(f"patch_qualification failed: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )

# ============================================================================
# Main HTTP Trigger (routing)
# ============================================================================

def main(req: func.HttpRequest) -> func.HttpResponse:
    """HTTP trigger — Route requests to handlers."""
    method = req.method
    path = req.route_params.get('path', '')

    logger.info(f"{method} /graph/{path}")

    # Routing logic
    if path == "health" or path.startswith("health/"):
        if method == "GET":
            return get_health()

    elif path == "nodes" or path.startswith("nodes/"):
        if method == "GET":
            if "/" in path:
                # /graph/nodes/{id} or /graph/nodes/{id}/spof or /graph/nodes/{id}/qualification
                parts = path.split("/")
                node_id = parts[1]
                if len(parts) > 2:
                    subpath = parts[2]
                    if subpath == "spof":
                        return get_spof(node_id)
                    elif subpath == "qualification":
                        return func.HttpResponse(
                            json.dumps({"error": "Use PATCH"}),
                            status_code=405,
                            mimetype="application/json"
                        )
                else:
                    return get_node_by_id(node_id)
            else:
                return get_nodes(req)

        elif method == "PATCH":
            if "/" in path:
                parts = path.split("/")
                node_id = parts[1]
                if len(parts) > 2 and parts[2] == "qualification":
                    req_body = req.get_json()
                    return patch_qualification(node_id, req_body)

    elif path == "arcs" or path.startswith("arcs/"):
        if method == "GET":
            return get_arcs(req)

    return func.HttpResponse(
        json.dumps({"error": "Not found"}),
        status_code=404,
        mimetype="application/json"
    )


# ============================================================================
# Pour déployer localement (dev):
#
# 1. requirements.txt:
#    azure-functions
#    neo4j
#    pyodbc
#
# 2. function_app.py (ce fichier)
#
# 3. function.json:
#    {
#      "scriptFile": "function_app.py",
#      "bindings": [
#        {
#          "authLevel": "anonymous",
#          "type": "httpTrigger",
#          "direction": "in",
#          "name": "req",
#          "methods": ["get", "post", "patch"],
#          "route": "graph/{path:maxlength(100)?}"
#        },
#        {
#          "type": "http",
#          "direction": "out",
#          "name": "$return"
#        }
#      ]
#    }
#
# 4. Test local:
#    func start
#    curl http://localhost:7071/api/graph/health
#
# ============================================================================
