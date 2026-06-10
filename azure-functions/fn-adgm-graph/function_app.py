"""
Azure Functions — ADG-M Graph APIs
Module : fn-adgm-graph (Python 3.11, runtime v4)

APIs principales (SDD ADG-M §3) :
- GET /graph/health
- GET /graph/nodes
- GET /graph/nodes/{id}
- GET /graph/nodes/{id}/impact
- GET /graph/arcs
- GET /graph/clusters
- PATCH /graph/nodes/{id}/qualification

Routes opérationnelles (hors contrat SDD §3) :
- POST /graph/admin/analyze          — jobs F1.3/F1.5 (criticité, SPOF, clustering Louvain)
- POST /graph/admin/import-entities  — merge du graphe de connaissance extrait des documents Chat

Dépendances (requirements.txt) :
  azure-functions
  neo4j
  pyodbc
"""

import azure.functions as func
import json
import logging
import math
import os
from datetime import datetime, timezone
from neo4j import GraphDatabase
try:
    import pyodbc
    _pyodbc_available = True
except ImportError:
    _pyodbc_available = False

# ============================================================================
# Configuration
# ============================================================================

NEO4J_URI = os.getenv("NEO4J_BOLT_URI", "bolt://localhost:7687")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "neo4j")
SQL_CONNECTION_STRING = os.getenv("SQL_CONNECTION_STRING")

APP_VERSION = "1.0.0"

SEVEN_R_VALUES = {"RETIRE", "RETAIN", "REHOST", "REPLATFORM", "REPURCHASE", "REFACTOR", "REBUILD", "UNQUALIFIED"}
ARC_TYPES = {"FUNCTIONAL", "TECHNICAL_CALL_SYNC", "TECHNICAL_CALL_ASYNC", "TECHNICAL_BATCH", "DATA_FLOW", "TRANSITIONAL_COHABITATION"}
CRITICALITY_VALUES = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
DIRECTION_VALUES = {"UNIDIRECTIONAL", "BIDIRECTIONAL"}

# Analyse F1.3/F1.5 (SDD §2.1 + §4 tuning) — exécutée par /graph/admin/analyze, pas par l'ingestion
GDS_TECH_PROJECTION = "moderngraph_tech"
SPOF_BETWEENNESS_PERCENTILE = float(os.getenv("SPOF_BETWEENNESS_PERCENTILE", "90"))

logger = logging.getLogger(__name__)

_neo4j_driver = None

def get_neo4j_driver():
    global _neo4j_driver
    if not _neo4j_driver:
        _neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=("neo4j", NEO4J_PASSWORD))
    return _neo4j_driver


def get_sql_connection():
    """Connexion SQL à la demande — PAS de singleton mis en cache (à la différence de
    get_neo4j_driver) : un pyodbc.Connection est un connexion unique non thread-safe,
    contrairement au Driver neo4j qui est conçu pour être partagé. Le pooling assuré par
    le gestionnaire ODBC sous-jacent rend l'ouverture par requête peu coûteuse — c'est
    déjà ce que fait get_health()."""
    if not _pyodbc_available:
        raise RuntimeError("pyodbc not installed — SQL features unavailable")
    return pyodbc.connect(SQL_CONNECTION_STRING, timeout=5)

# ============================================================================
# Helpers — DTOs (SDD §2.3) et réponses d'erreur
# ============================================================================

def _to_json(v):
    """Converts neo4j.time.DateTime (and similar) to ISO string; passes other values through."""
    return v.isoformat() if hasattr(v, "isoformat") else v

def _technical_node_dto(props: dict) -> dict:
    return {
        "id": props.get("id"),
        "type": "technical",
        "componentName": props.get("componentName"),
        "technology": props.get("technology"),
        "linesOfCode": props.get("linesOfCode"),
        "callFrequency": props.get("callFrequency"),
        "candidate7R": props.get("candidate7R"),
        "knowledgeOwner": props.get("knowledgeOwner"),
        "regulatoryTags": props.get("regulatoryTags", []),
        "docCoveragePercent": props.get("docCoveragePercent"),
        "isGhost": props.get("isGhost", False),
        "sourceDocIds": props.get("sourceDocIds", []),
        "criticalityScore": props.get("criticalityScore", 0),
        "betweenness": props.get("betweenness", 0.0),
        "isSPOF": props.get("isSPOF", False),
        "clusterId": props.get("clusterId"),
        "createdAt": _to_json(props.get("createdAt")),
        "updatedAt": _to_json(props.get("updatedAt")),
    }

def _functional_node_dto(props: dict) -> dict:
    return {
        "id": props.get("id"),
        "type": "functional",
        "domain": props.get("domain"),
        "subdomain": props.get("subdomain"),
        "processes": props.get("processes", []),
        "sharedBusinessObjects": props.get("sharedBusinessObjects", []),
        "docCoveragePercent": props.get("docCoveragePercent"),
        "modernizationStatus": props.get("modernizationStatus"),
        "sourceDocIds": props.get("sourceDocIds", []),
        "createdAt": _to_json(props.get("createdAt")),
        "updatedAt": _to_json(props.get("updatedAt")),
    }

def node_to_dto(node) -> dict:
    """Nœud Neo4j -> DTO SDD §2.3 (métriques d'analyse F1.3/F1.5 absentes => défaut-valorisées)."""
    props = dict(node)
    labels = set(node.labels)
    if "TechnicalNode" in labels:
        dto = _technical_node_dto(props)
        if "Program" in labels:
            dto["subtype"] = "program"
        elif "System" in labels:
            dto["subtype"] = "system"
        else:
            dto["subtype"] = "component"
        return dto
    dto = _functional_node_dto(props)
    if "FunctionalDomain" in labels:
        dto["subtype"] = "domain"
    elif "MacroFunction" in labels:
        dto["subtype"] = "macrofunction"
    elif "DataEntity" in labels:
        dto["subtype"] = "dataentity"
    else:
        dto["subtype"] = "functional"
    return dto

def error_response(message: str, status_code: int, **extra) -> func.HttpResponse:
    body = {"error": message}
    body.update(extra)
    return func.HttpResponse(json.dumps(body), status_code=status_code, mimetype="application/json")

def _parse_int_param(request: func.HttpRequest, name: str, default: int) -> int:
    raw = request.params.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default

def _percentile(values: list, p: float) -> float:
    """Percentile par rang le plus proche (nearest-rank) sur une population finie.
    Évite une dépendance numpy pour cet unique calcul (SPOF_BETWEENNESS_PERCENTILE, SDD §4)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    k = min(len(ordered) - 1, max(0, math.ceil(p / 100 * len(ordered)) - 1))
    return ordered[k]

# ============================================================================
# API Handlers
# ============================================================================

def get_health() -> func.HttpResponse:
    """GET /graph/health — Sonde de disponibilité (Neo4j + SQL joignables)."""
    neo4j_status = "down"
    sql_status = "down"

    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            session.run("RETURN 1").consume()
        neo4j_status = "up"
    except Exception as e:
        logger.error(f"get_health — Neo4j injoignable : {e}")

    try:
        conn = get_sql_connection()
        try:
            conn.cursor().execute("SELECT 1")
        finally:
            conn.close()
        sql_status = "up"
    except Exception as e:
        logger.error(f"get_health — SQL injoignable : {e}")

    if neo4j_status == "up" and sql_status == "up":
        return func.HttpResponse(
            json.dumps({"status": "ok", "neo4j": neo4j_status, "sql": sql_status, "version": APP_VERSION}),
            status_code=200,
            mimetype="application/json"
        )

    return error_response("Dépendance indisponible", 503, neo4j=neo4j_status, sql=sql_status)


def get_nodes(request: func.HttpRequest) -> func.HttpResponse:
    """GET /graph/nodes — Liste filtrable et paginée des nœuds fonctionnels/techniques (SDD §3)."""
    try:
        node_type = request.params.get("type")
        status = request.params.get("status")
        candidate7r = request.params.get("candidate7R")
        is_ghost_raw = request.params.get("isGhost")

        if node_type and node_type not in ("functional", "technical"):
            return error_response("Paramètre type invalide", 400)
        if status and status not in ("UNQUALIFIED", "QUALIFIED"):
            return error_response("Paramètre type invalide", 400)
        if candidate7r and candidate7r not in SEVEN_R_VALUES:
            return error_response("Paramètre type invalide", 400)
        if is_ghost_raw is not None and is_ghost_raw.lower() not in ("true", "false"):
            return error_response("Paramètre type invalide", 400)

        params = {
            "type": node_type,
            "domain": request.params.get("domain"),
            "candidate7R": candidate7r,
            "clusterId": request.params.get("clusterId"),
            "status": status,
            "isGhost": (is_ghost_raw.lower() == "true") if is_ghost_raw is not None else None,
            "limit": max(0, _parse_int_param(request, "limit", 100)),
            "offset": max(0, _parse_int_param(request, "offset", 0)),
        }

        where_clause = """
            (n:TechnicalNode OR n:FunctionalNode)
            AND ($type IS NULL OR ($type = 'technical' AND n:TechnicalNode) OR ($type = 'functional' AND n:FunctionalNode))
            AND ($domain IS NULL OR n.domain = $domain)
            AND ($candidate7R IS NULL OR n.candidate7R = $candidate7R)
            AND ($clusterId IS NULL OR n.clusterId = $clusterId)
            AND ($isGhost IS NULL OR n.isGhost = $isGhost)
            AND ($status IS NULL
                 OR ($status = 'UNQUALIFIED' AND n.candidate7R = 'UNQUALIFIED')
                 OR ($status = 'QUALIFIED' AND n.candidate7R IS NOT NULL AND n.candidate7R <> 'UNQUALIFIED'))
        """

        driver = get_neo4j_driver()
        with driver.session() as session:
            total = session.run(
                f"MATCH (n) WHERE {where_clause} RETURN count(n) AS total", params
            ).single()["total"]
            records = session.run(
                f"MATCH (n) WHERE {where_clause} RETURN n ORDER BY n.id SKIP $offset LIMIT $limit", params
            )
            items = [node_to_dto(record["n"]) for record in records]

        return func.HttpResponse(
            json.dumps({"total": total, "limit": params["limit"], "offset": params["offset"], "items": items}),
            status_code=200,
            mimetype="application/json"
        )
    except Exception as e:
        logger.error(f"get_nodes failed: {e}")
        return error_response("Erreur interne. Réessayer ou contacter le support.", 500)


def get_node_by_id(node_id: str) -> func.HttpResponse:
    """GET /graph/nodes/{id} — Détail complet : métriques dérivées + arcs entrants/sortants résumés (SDD §3)."""
    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            record = session.run(
                "MATCH (n) WHERE (n:TechnicalNode OR n:FunctionalNode) AND n.id = $id RETURN n",
                {"id": node_id}
            ).single()

            if not record:
                return error_response("Nœud introuvable", 404)

            node = record["n"]
            is_technical = "TechnicalNode" in node.labels

            incoming_arcs = [
                {"id": rec["arcId"], "sourceNodeId": rec["otherId"], "arcType": rec["arcType"], "criticality": rec["criticality"]}
                for rec in session.run(
                    """
                    MATCH (src)-[r:DEPENDS_ON]->(n {id: $id})
                    RETURN r.id AS arcId, src.id AS otherId, r.arcType AS arcType, r.criticality AS criticality
                    ORDER BY arcId
                    """,
                    {"id": node_id}
                )
            ]
            outgoing_arcs = [
                {"id": rec["arcId"], "targetNodeId": rec["otherId"], "arcType": rec["arcType"], "criticality": rec["criticality"]}
                for rec in session.run(
                    """
                    MATCH (n {id: $id})-[r:DEPENDS_ON]->(tgt)
                    RETURN r.id AS arcId, tgt.id AS otherId, r.arcType AS arcType, r.criticality AS criticality
                    ORDER BY arcId
                    """,
                    {"id": node_id}
                )
            ]

            metrics = {
                "inDegree": len(incoming_arcs),
                "outDegree": len(outgoing_arcs),
                "criticalArcsIn": sum(1 for a in incoming_arcs if a["criticality"] == "CRITICAL"),
            }
            if is_technical:
                metrics["realizesFunctionalNodes"] = [
                    rec["fnId"] for rec in session.run(
                        "MATCH (fn:FunctionalNode)-[:REALIZED_BY]->(:TechnicalNode {id: $id}) RETURN fn.id AS fnId ORDER BY fnId",
                        {"id": node_id}
                    )
                ]
            else:
                metrics["realizedByTechnicalNodes"] = [
                    rec["tnId"] for rec in session.run(
                        "MATCH (:FunctionalNode {id: $id})-[:REALIZED_BY]->(tn:TechnicalNode) RETURN tn.id AS tnId ORDER BY tnId",
                        {"id": node_id}
                    )
                ]

        return func.HttpResponse(
            json.dumps({
                "node": node_to_dto(node),
                "metrics": metrics,
                "incomingArcs": incoming_arcs,
                "outgoingArcs": outgoing_arcs,
            }),
            status_code=200,
            mimetype="application/json"
        )
    except Exception as e:
        logger.error(f"get_node_by_id failed: {e}")
        return error_response("Erreur interne. Réessayer ou contacter le support.", 500)


def get_node_neighbors(node_id: str) -> func.HttpResponse:
    """GET /graph/nodes/{id}/neighbors — Tous les nœuds et relations adjacents (mode exploration IHM).

    Contrairement à /graph/arcs (DEPENDS_ON uniquement), cet endpoint traverse TOUTES les
    relations Neo4j du nœud : HAS_MACROFUNCTION, IMPLEMENTED_BY, READS/WRITES/CREATES/DELETES,
    DEPENDS_ON, etc. Utilisé par le double-clic d'exploration dans GraphPage.jsx.
    """
    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            center_rec = session.run(
                "MATCH (n) WHERE (n:TechnicalNode OR n:FunctionalNode) AND n.id = $id RETURN n",
                {"id": node_id}
            ).single()
            if not center_rec:
                return error_response("Nœud introuvable", 404)

            center_node = center_rec["n"]

            # Toutes les relations adjacentes — startNode/endNode préservent la direction réelle.
            # DISTINCT évite les doublons dus au parcours bidirectionnel de MATCH (n)-[r]-(m).
            records = session.run(
                """
                MATCH (center {id: $id})-[r]-(neighbor)
                WHERE (center:TechnicalNode OR center:FunctionalNode)
                  AND (neighbor:TechnicalNode OR neighbor:FunctionalNode)
                RETURN DISTINCT
                    neighbor,
                    type(r)          AS relType,
                    startNode(r).id  AS sourceId,
                    endNode(r).id    AS targetId,
                    r.id             AS relId,
                    r.arcType        AS arcType,
                    r.criticality    AS criticality
                ORDER BY relType, sourceId, targetId
                """,
                {"id": node_id}
            )

            neighbors: dict = {}
            edges: list = []
            seen_edges: set = set()

            for rec in records:
                neighbor = rec["neighbor"]
                nid = dict(neighbor).get("id")
                if nid and nid not in neighbors:
                    neighbors[nid] = node_to_dto(neighbor)

                source_id   = rec["sourceId"]
                target_id   = rec["targetId"]
                rel_type    = rec["relType"]
                rel_id      = rec["relId"] or f"{rel_type}-{source_id}-{target_id}"
                edge_key    = (source_id, target_id, rel_type)

                if edge_key not in seen_edges:
                    seen_edges.add(edge_key)
                    edges.append({
                        "id":           rel_id,
                        "sourceNodeId": source_id,
                        "targetNodeId": target_id,
                        "relType":      rel_type,
                        "arcType":      rec["arcType"] or rel_type,
                        "criticality":  rec["criticality"] or "MEDIUM",
                    })

        return func.HttpResponse(
            json.dumps({
                "center":    node_to_dto(center_node),
                "neighbors": list(neighbors.values()),
                "edges":     edges,
            }),
            status_code=200,
            mimetype="application/json",
        )
    except Exception as e:
        logger.error(f"get_node_neighbors failed: {e}")
        return error_response("Erreur interne. Réessayer ou contacter le support.", 500)


def get_node_impact(node_id: str) -> func.HttpResponse:
    """GET /graph/nodes/{id}/impact — Rayon d'impact downstream d'un nœud technique (SDD §3, consommé par ADM-M C5).

    `isSPOF`/`betweenness` sont des propriétés calculées par le job d'analyse F1.3/F1.5
    (cf. detect_spof / POST /graph/admin/analyze) — cet endpoint les lit telles que persistées,
    il ne relance pas GDS à la volée. La liste `downstreamImpacted` est calculée pour tout nœud
    technique existant (pas seulement les SPOF) : `isSPOF` indique au consommateur le poids à
    accorder au résultat, sans lui cacher l'information pour les nœuds non-SPOF.
    """
    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            record = session.run(
                "MATCH (n:TechnicalNode {id: $id}) RETURN n.isSPOF AS isSPOF",
                {"id": node_id}
            ).single()

            if not record:
                return error_response("Nœud introuvable", 404)

            downstream = [
                {
                    "id": rec["id"],
                    "componentName": rec["componentName"],
                    "distance": rec["distance"],
                    "criticality": rec["criticality"],
                }
                for rec in session.run(
                    """
                    MATCH (origin:TechnicalNode {id: $id})
                    MATCH path = (origin)-[:DEPENDS_ON*1..18]->(downstream:TechnicalNode)
                    WHERE downstream <> origin
                    WITH downstream, path, length(path) AS len
                    ORDER BY len ASC
                    WITH downstream, collect(path)[0] AS shortestPath, min(len) AS distance
                    RETURN downstream.id AS id, downstream.componentName AS componentName,
                           distance, last(relationships(shortestPath)).criticality AS criticality
                    ORDER BY distance, componentName
                    """,
                    {"id": node_id}
                )
            ]

        return func.HttpResponse(
            json.dumps({
                "nodeId": node_id,
                "isSPOF": record["isSPOF"] if record["isSPOF"] is not None else False,
                "downstreamImpacted": downstream,
                "impactedCount": len(downstream),
            }),
            status_code=200,
            mimetype="application/json"
        )
    except Exception as e:
        logger.error(f"get_node_impact failed: {e}")
        return error_response("Erreur interne. Réessayer ou contacter le support.", 500)


def patch_node_qualification(req: func.HttpRequest, node_id: str) -> func.HttpResponse:
    """PATCH /graph/nodes/{id}/qualification — Qualification 7R + historisation (SDD §3, T13).

    Endpoint d'écriture unique pour candidate7R : annotation manuelle (F1.4, source=MANUAL)
    et write-back validé par 7RQA/ADM-M (source=7RQA|ADM-M). Persiste dans Neo4j (candidate7R,
    updatedAt) et historise dans dbo.NodeAnnotationHistory (annotationId généré par SQL via
    OUTPUT INSERTED — la table définit déjà annotationId UNIQUEIDENTIFIER DEFAULT NEWID()).

    Ordre des contrôles = ordre des lignes du tableau d'erreurs SDD §3 (400, 404, 422), mais
    réorganisé pour qu'aucune écriture ne se produise avant la dernière validation : l'existence
    du nœud (404) est vérifiée par une lecture séparée avant le SET, et source/author (422) sont
    contrôlés avant toute mutation — une réponse d'erreur ne doit jamais avoir d'effet de bord.
    Une valeur `source` hors énumération MANUAL|7RQA|ADM-M est traitée comme absente (422,
    details=["source"]) : le SDD ne documente pas de code dédié à une valeur de source invalide.
    """
    try:
        try:
            body = req.get_json()
        except ValueError:
            body = {}

        candidate7r = body.get("candidate7R")
        justification = body.get("justification")
        source = body.get("source")
        author = body.get("author")

        if candidate7r not in SEVEN_R_VALUES or candidate7r == "UNQUALIFIED":
            return error_response("Valeur 7R invalide", 400)

        driver = get_neo4j_driver()
        with driver.session() as session:
            existing = session.run(
                "MATCH (n:TechnicalNode {id: $id}) RETURN n.candidate7R AS previous7R",
                {"id": node_id}
            ).single()
            if not existing:
                return error_response("Nœud technique introuvable", 404)

            missing = [name for name, ok in (
                ("source", source in ("MANUAL", "7RQA", "ADM-M")),
                ("author", bool(author)),
            ) if not ok]
            if missing:
                return error_response("Champs obligatoires manquants", 422, details=missing)

            previous7r = existing["previous7R"]
            updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            session.run(
                "MATCH (n:TechnicalNode {id: $id}) SET n.candidate7R = $candidate7R, n.updatedAt = $updatedAt",
                {"id": node_id, "candidate7R": candidate7r, "updatedAt": updated_at}
            ).consume()

        conn = get_sql_connection()
        try:
            cursor = conn.cursor()
            row = cursor.execute(
                """
                INSERT INTO dbo.NodeAnnotationHistory (nodeId, previous7R, new7R, justification, source, author)
                OUTPUT INSERTED.annotationId
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (node_id, previous7r, candidate7r, justification, source, author)
            ).fetchone()
            conn.commit()
            annotation_id = str(row[0])
        finally:
            conn.close()

        return func.HttpResponse(
            json.dumps({
                "nodeId": node_id,
                "candidate7R": candidate7r,
                "previous7R": previous7r,
                "annotationId": annotation_id,
                "updatedAt": updated_at,
            }),
            status_code=200,
            mimetype="application/json"
        )
    except Exception as e:
        logger.error(f"patch_node_qualification failed: {e}")
        return error_response("Erreur interne. Réessayer ou contacter le support.", 500)


def get_arcs(request: func.HttpRequest) -> func.HttpResponse:
    """GET /graph/arcs — Liste filtrable des arcs DEPENDS_ON (SDD §3)."""
    try:
        arc_type = request.params.get("arcType")
        criticality = request.params.get("criticality")
        direction = request.params.get("direction")

        if arc_type and arc_type not in ARC_TYPES:
            return error_response("Paramètre de filtre invalide", 400)
        if criticality and criticality not in CRITICALITY_VALUES:
            return error_response("Paramètre de filtre invalide", 400)
        if direction and direction not in DIRECTION_VALUES:
            return error_response("Paramètre de filtre invalide", 400)

        params = {
            "nodeId": request.params.get("nodeId"),
            "arcType": arc_type,
            "criticality": criticality,
            "direction": direction,
            "limit": max(0, _parse_int_param(request, "limit", 100)),
            "offset": max(0, _parse_int_param(request, "offset", 0)),
        }

        where_clause = """
            ($nodeId IS NULL OR source.id = $nodeId OR target.id = $nodeId)
            AND ($arcType IS NULL OR r.arcType = $arcType)
            AND ($criticality IS NULL OR r.criticality = $criticality)
            AND ($direction IS NULL OR r.direction = $direction)
        """

        driver = get_neo4j_driver()
        with driver.session() as session:
            total = session.run(
                f"MATCH (source)-[r:DEPENDS_ON]->(target) WHERE {where_clause} RETURN count(r) AS total", params
            ).single()["total"]
            records = session.run(
                f"""
                MATCH (source)-[r:DEPENDS_ON]->(target) WHERE {where_clause}
                RETURN r.id AS id, source.id AS sourceNodeId, target.id AS targetNodeId,
                       r.arcType AS arcType, r.dataFormat AS dataFormat,
                       r.direction AS direction, r.criticality AS criticality
                ORDER BY id SKIP $offset LIMIT $limit
                """,
                params
            )
            items = [dict(record) for record in records]

        return func.HttpResponse(
            json.dumps({"total": total, "items": items}),
            status_code=200,
            mimetype="application/json"
        )
    except Exception as e:
        logger.error(f"get_arcs failed: {e}")
        return error_response("Erreur interne. Réessayer ou contacter le support.", 500)


def get_clusters(request: func.HttpRequest) -> func.HttpResponse:
    """GET /graph/clusters — Appartements candidats issus du clustering Louvain (SDD §3, T15).

    Cluster n'a pas de label dans le schéma Neo4j (SDD §2.1 ne définit que TechnicalNode/
    FunctionalNode) : agrégation calculée à la lecture, par regroupement des TechnicalNode
    sur communityId (écrit par run_louvain / gds.louvain.write — 409 si jamais exécuté).

    cohesion/externalCoupling n'ont pas de formule donnée dans le SDD (seulement les seuils
    > 0.7 / < 0.3 et "ratios 0-1", §2.3 lignes 263-265) — gap structurel identique à "pas de
    voisin redondant" pour detect_spof. Dérivés ici à partir des arcs DEPENDS_ON internes vs.
    sortants de chaque communauté :
      cohesion         = densité interne = arêtes internes / paires possibles n·(n-1)/2
      externalCoupling = arêtes sortantes / (arêtes internes + arêtes sortantes)
    isCandidateApartment est calculé sur les valeurs arrondies (cohérence affichage/flag :
    un cohesion affiché à 0.70 ne doit jamais sembler "passer" un seuil > 0.7).

    clusterId est généré en cl-{communityId} (entier stable Louvain, inchangé tant que la
    partition ne bouge pas — pas d'ID inventé). name reste null : "nommé par l'architecte"
    (SDD §2.3) et aucun endpoint d'écriture pour ce champ n'existe dans le contrat SDD §3.
    """
    try:
        candidate_only_raw = request.params.get("candidateOnly")
        if candidate_only_raw is not None and candidate_only_raw.lower() not in ("true", "false"):
            return error_response("Paramètre candidateOnly invalide", 400)
        candidate_only = candidate_only_raw is not None and candidate_only_raw.lower() == "true"

        driver = get_neo4j_driver()
        with driver.session() as session:
            community_rows = [
                {"communityId": rec["communityId"], "id": rec["id"]}
                for rec in session.run(
                    "MATCH (n:TechnicalNode) WHERE n.communityId IS NOT NULL "
                    "RETURN n.communityId AS communityId, n.id AS id"
                )
            ]
            if not community_rows:
                return error_response("Clusters non calculés. Lancer l'analyse du graphe.", 409)

            edges = [
                (rec["sourceId"], rec["targetId"])
                for rec in session.run(
                    "MATCH (a:TechnicalNode)-[:DEPENDS_ON]->(b:TechnicalNode) "
                    "RETURN a.id AS sourceId, b.id AS targetId"
                )
            ]

        node_community = {row["id"]: row["communityId"] for row in community_rows}
        members: dict = {}
        for row in community_rows:
            members.setdefault(row["communityId"], []).append(row["id"])

        internal = {community_id: 0 for community_id in members}
        external = {community_id: 0 for community_id in members}
        for source_id, target_id in edges:
            source_community = node_community.get(source_id)
            target_community = node_community.get(target_id)
            if source_community is None or target_community is None:
                continue
            if source_community == target_community:
                internal[source_community] += 1
            else:
                external[source_community] += 1
                external[target_community] += 1

        items = []
        for community_id, node_ids in members.items():
            size = len(node_ids)
            max_internal = size * (size - 1) / 2
            cohesion = round(internal[community_id] / max_internal, 2) if max_internal > 0 else 0.0
            total_incident = internal[community_id] + external[community_id]
            external_coupling = round(external[community_id] / total_incident, 2) if total_incident > 0 else 0.0
            items.append({
                "clusterId": f"cl-{community_id}",
                "name": None,
                "nodeIds": sorted(node_ids),
                "cohesion": cohesion,
                "externalCoupling": external_coupling,
                "isCandidateApartment": cohesion > 0.7 and external_coupling < 0.3,
                "size": size,
            })

        if candidate_only:
            items = [item for item in items if item["isCandidateApartment"]]
        items.sort(key=lambda item: item["clusterId"])

        return func.HttpResponse(
            json.dumps({"total": len(items), "items": items}),
            status_code=200,
            mimetype="application/json"
        )
    except Exception as e:
        logger.error(f"get_clusters failed: {e}")
        return error_response("Erreur interne. Réessayer ou contacter le support.", 500)


# ============================================================================
# Analyse F1.3 / F1.5 — jobs séparés de l'ingestion (SDD §2.1 : "écrites par les
# jobs d'analyse F1.3/F1.5, pas par l'ingestion"). Invoqués via POST /graph/admin/analyze,
# pas chaînés sur le trigger blob — l'ingestion reste rapide et découplée du coût GDS.
# ============================================================================

def _drop_projection_if_exists(session, name: str) -> None:
    session.run(
        """
        CALL gds.graph.exists($name) YIELD exists
        WHERE exists
        CALL { CALL gds.graph.drop($name) YIELD graphName RETURN graphName }
        RETURN 1
        """,
        {"name": name}
    ).consume()


def compute_criticality(driver) -> int:
    """F1.3 — Score de criticité = somme pondérée des arcs entrants (SDD §2.1, Cypher fourni verbatim).
    Poids : CRITICAL=4, HIGH=3, MEDIUM=2, LOW=1. Un nœud sans arc entrant n'est pas retourné par ce
    MATCH ; son criticalityScore reste à sa valeur initiale (0, valorisée par l'ingestion)."""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (src)-[r:DEPENDS_ON]->(n:TechnicalNode)
            WITH n, sum(
              CASE r.criticality WHEN 'CRITICAL' THEN 4 WHEN 'HIGH' THEN 3
                                 WHEN 'MEDIUM' THEN 2 ELSE 1 END) AS score
            SET n.criticalityScore = score
            RETURN count(n) AS updated
            """
        )
        return result.single()["updated"]


def detect_spof(driver, percentile: float = SPOF_BETWEENNESS_PERCENTILE) -> dict:
    """F1.3/F1.5 — isSPOF = betweenness > pXX ET pas de voisin redondant (SDD §9 detect_spof).

    « Pas de voisin redondant » est opérationnalisé comme : le nœud est un point d'articulation
    (gds.articulationPoints — sa suppression déconnecterait le graphe, donc aucun chemin de
    secours n'existe entre ses voisins). Une betweenness élevée seule ne suffit pas : un hub très
    sollicité mais doublé par un chemin alternatif n'est pas un SPOF réel — d'où le ET.

    Projection 'moderngraph_tech' non orientée, identique à celle prescrite par le Cypher SDD §2.1
    pour Louvain (réutilisable telle quelle par F1.5) ; supprimée après lecture des métriques
    (op. coûteuse en mémoire GDS, ne doit pas persister entre deux exécutions du job).
    """
    with driver.session() as session:
        _drop_projection_if_exists(session, GDS_TECH_PROJECTION)
        session.run(
            "CALL gds.graph.project($name, 'TechnicalNode', {DEPENDS_ON: {orientation: 'UNDIRECTED'}})",
            {"name": GDS_TECH_PROJECTION}
        ).consume()

        try:
            betweenness = {
                rec["id"]: rec["score"]
                for rec in session.run(
                    "CALL gds.betweenness.stream($name) YIELD nodeId, score "
                    "RETURN gds.util.asNode(nodeId).id AS id, score",
                    {"name": GDS_TECH_PROJECTION}
                )
            }
            articulation_ids = {
                rec["id"]
                for rec in session.run(
                    "CALL gds.articulationPoints.stream($name) YIELD nodeId "
                    "RETURN gds.util.asNode(nodeId).id AS id",
                    {"name": GDS_TECH_PROJECTION}
                )
            }
        finally:
            _drop_projection_if_exists(session, GDS_TECH_PROJECTION)

        threshold = _percentile(list(betweenness.values()), percentile)
        rows = [
            {"id": node_id, "betweenness": score, "isSPOF": score > threshold and node_id in articulation_ids}
            for node_id, score in betweenness.items()
        ]

        session.run(
            """
            UNWIND $rows AS row
            MATCH (n:TechnicalNode {id: row.id})
            SET n.betweenness = row.betweenness, n.isSPOF = row.isSPOF
            """,
            {"rows": rows}
        ).consume()

        spof_ids = sorted(row["id"] for row in rows if row["isSPOF"])
        return {
            "nodesAnalyzed": len(rows),
            "betweennessPercentile": percentile,
            "betweennessThreshold": threshold,
            "spofCount": len(spof_ids),
            "spofNodeIds": spof_ids,
        }


def run_louvain(driver) -> dict:
    """F1.5 — Clustering Louvain "appartements candidats" (SDD §2.1, Cypher fourni verbatim) :
    projette moderngraph_tech (même projection non orientée que detect_spof, supprimée après
    écriture — réutilise _drop_projection_if_exists) puis gds.louvain.write(..., writeProperty:
    'communityId'). Persiste uniquement communityId sur chaque TechnicalNode : Cluster n'a pas
    de label dans le schéma SDD (§2.1 ne définit que TechnicalNode/FunctionalNode), le reste
    (cohesion, externalCoupling, regroupement) est calculé à la lecture par get_clusters."""
    with driver.session() as session:
        _drop_projection_if_exists(session, GDS_TECH_PROJECTION)
        session.run(
            "CALL gds.graph.project($name, 'TechnicalNode', {DEPENDS_ON: {orientation: 'UNDIRECTED'}})",
            {"name": GDS_TECH_PROJECTION}
        ).consume()

        try:
            result = session.run(
                """
                CALL gds.louvain.write($name, {writeProperty: 'communityId'})
                YIELD communityCount, modularity
                RETURN communityCount, modularity
                """,
                {"name": GDS_TECH_PROJECTION}
            ).single()
        finally:
            _drop_projection_if_exists(session, GDS_TECH_PROJECTION)

        return {"communityCount": result["communityCount"], "modularity": round(result["modularity"], 4)}


def clear_functional_entities(req: func.HttpRequest) -> func.HttpResponse:
    """DELETE /graph/admin/functional-entities — Supprime la couche fonctionnelle extraite des
    documents Chat (FunctionalDomain, MacroFunction, Program, DataEntity + leurs relations).
    Les TechnicalNode et leurs annotations candidate7R sont préservés."""
    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            count_result = session.run(
                "MATCH (n) WHERE n:FunctionalDomain OR n:MacroFunction OR n:Program OR n:DataEntity "
                "RETURN count(n) AS total"
            )
            total = count_result.single()["total"]
            session.run(
                "MATCH (n) WHERE n:FunctionalDomain OR n:MacroFunction OR n:Program OR n:DataEntity "
                "DETACH DELETE n"
            )
        return func.HttpResponse(
            json.dumps({"status": "ok", "deleted": total, "timestamp": datetime.now(timezone.utc).isoformat()}),
            status_code=200, mimetype="application/json"
        )
    except Exception as exc:
        logger.error(f"clear_functional_entities failed: {exc}")
        return error_response("Erreur lors de la suppression des entités fonctionnelles.", 500)


def reset_graph(req: func.HttpRequest) -> func.HttpResponse:
    """DELETE /graph/admin/reset — Supprime TOUS les nœuds et relations du graphe.
    Irréversible. À utiliser avant une reconstruction complète depuis le Chat."""
    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            count_result = session.run("MATCH (n) RETURN count(n) AS total")
            total = count_result.single()["total"]
            session.run("MATCH (n) DETACH DELETE n")
        return func.HttpResponse(
            json.dumps({"status": "ok", "deleted": total, "timestamp": datetime.now(timezone.utc).isoformat()}),
            status_code=200, mimetype="application/json"
        )
    except Exception as exc:
        logger.error(f"reset_graph failed: {exc}")
        return error_response("Erreur lors du reset du graphe.", 500)


def run_analysis(req: func.HttpRequest) -> func.HttpResponse:
    """POST /graph/admin/analyze — Lance F1.3 (criticité), F1.3/F1.5 (SPOF) et F1.5 (Louvain)
    sur le graphe courant.

    Route opérationnelle/interne, hors contrat consommateurs SDD §3 : à invoquer après une
    (ré)ingestion plutôt qu'auto-enchaînée sur le trigger blob (cf. plan Sprint 1 increment 4 —
    garde l'ingestion rapide et découple son coût du calcul GDS, conformément au commentaire
    SDD §2.1 qui distingue explicitement jobs d'analyse et ingestion). Les trois algorithmes
    sont groupés dans un seul script Cypher au SDD §2.1 — gardés ensemble ici pour la même raison.
    """
    try:
        driver = get_neo4j_driver()
        nodes_scored = compute_criticality(driver)
        spof = detect_spof(driver)
        clustering = run_louvain(driver)
        return func.HttpResponse(
            json.dumps({
                "status": "completed",
                "criticality": {"nodesScored": nodes_scored},
                "spof": spof,
                "clustering": clustering,
            }),
            status_code=200,
            mimetype="application/json"
        )
    except Exception as e:
        logger.error(f"run_analysis failed: {e}")
        return error_response("Erreur interne. Réessayer ou contacter le support.", 500)


# ============================================================================
# POST /graph/admin/import-entities — merge graphe de connaissance extrait des docs
# ============================================================================

def import_entities(req: func.HttpRequest) -> func.HttpResponse:
    """Merge un graphe de connaissance (extrait des documents Chat via GPT-4o) dans Neo4j.

    Payload JSON (tous les champs sont optionnels — les imports partiels sont supportés) :
    {
      "system":             {"id": str, "name": str},
      "functional_domains": [{"id": str, "code": str|null, "name": str, "description": str|null}],
      "macro_functions":    [{"id": str, "code": str|null, "name": str, "mode": str|null,
                              "domain_id": str, "description": str|null}],
      "programs":           [{"name": str, "technology": str|null, "mode": str|null,
                              "macro_function_ids": list[str], "description": str|null}],
      "data_entities":      [{"name": str, "type": str|null, "description": str|null}],
      "crud_relationships": [{"program_name": str, "entity_name": str, "operations": list[str]}]
    }

    Toutes les opérations sont des MERGE sur l'identifiant canonique — idempotent,
    safe pour les re-lancements successifs. Les annotations 7R sur les TechnicalNode
    existants ne sont jamais écrasées (ON MATCH SET ne touche pas candidate7R).
    """
    try:
        body = req.get_json()
    except Exception:
        return error_response("Corps JSON invalide", 400)

    system            = body.get("system") or {}
    functional_domains = body.get("functional_domains") or []
    macro_functions   = body.get("macro_functions") or []
    programs          = body.get("programs") or []
    data_entities     = body.get("data_entities") or []
    crud_relationships = body.get("crud_relationships") or []

    counts = {
        "systems": 0, "domains": 0, "macro_functions": 0,
        "programs": 0, "data_entities": 0, "relationships": 0,
    }

    # Opérations CRUD → types de relation Neo4j (contrôlés — pas de risque d'injection)
    _CRUD_REL = {"C": "CREATES", "R": "READS", "U": "UPDATES", "D": "DELETES"}

    try:
        driver = get_neo4j_driver()
        with driver.session() as session:

            # ── System ────────────────────────────────────────────────────────
            if system.get("id"):
                session.run(
                    """
                    MERGE (sys:System {id: $id})
                    ON CREATE SET sys.name = $name, sys.createdAt = datetime()
                    ON MATCH  SET sys.name = $name, sys.updatedAt = datetime()
                    """,
                    id=system["id"], name=system.get("name", system["id"]),
                )
                counts["systems"] += 1

            # ── Domaines fonctionnels → :FunctionalDomain:FunctionalNode ─────
            # Multi-label Neo4j : :FunctionalDomain conserve le label domaine-métier ;
            # :FunctionalNode est le label standard lu par get_nodes(). La propriété
            # `domain` (attendue par _functional_node_dto) est mappée depuis `name`.
            for d in functional_domains:
                if not d.get("id"):
                    continue
                d_name = d.get("name", d["id"])
                session.run(
                    """
                    MERGE (d:FunctionalDomain:FunctionalNode {id: $id})
                    ON CREATE SET d.code = $code, d.name = $name, d.domain = $name,
                                  d.description = $desc, d.systemId = $sys_id,
                                  d.modernizationStatus = 'EXISTING',
                                  d.createdAt = datetime()
                    ON MATCH  SET d.name = $name, d.domain = $name,
                                  d.description = $desc, d.updatedAt = datetime()
                    """,
                    id=d["id"], code=d.get("code"), name=d_name,
                    desc=d.get("description"), sys_id=system.get("id"),
                )
                if system.get("id"):
                    session.run(
                        """
                        MATCH (sys:System {id: $sys_id})
                        MATCH (d:FunctionalDomain {id: $d_id})
                        MERGE (sys)-[:HAS_DOMAIN]->(d)
                        """,
                        sys_id=system["id"], d_id=d["id"],
                    )
                counts["domains"] += 1

            # ── Macro-fonctions → :MacroFunction:FunctionalNode ──────────────
            for mf in macro_functions:
                if not mf.get("id"):
                    continue
                mf_name = mf.get("name", mf["id"])
                session.run(
                    """
                    MERGE (mf:MacroFunction:FunctionalNode {id: $id})
                    ON CREATE SET mf.code = $code, mf.name = $name, mf.domain = $name,
                                  mf.mode = $mode, mf.description = $desc,
                                  mf.modernizationStatus = 'EXISTING',
                                  mf.createdAt = datetime()
                    ON MATCH  SET mf.name = $name, mf.domain = $name,
                                  mf.mode = $mode, mf.description = $desc,
                                  mf.updatedAt = datetime()
                    """,
                    id=mf["id"], code=mf.get("code"), name=mf_name,
                    mode=mf.get("mode"), desc=mf.get("description"),
                )
                if mf.get("domain_id"):
                    session.run(
                        """
                        MATCH (d:FunctionalDomain {id: $d_id})
                        MATCH (mf:MacroFunction {id: $mf_id})
                        MERGE (d)-[:HAS_MACROFUNCTION]->(mf)
                        """,
                        d_id=mf["domain_id"], mf_id=mf["id"],
                    )
                    session.run(
                        """
                        MATCH (d:FunctionalDomain {id: $d_id}), (mf:MacroFunction {id: $mf_id})
                        MERGE (d)-[dep:DEPENDS_ON {id: $arc_id}]->(mf)
                        ON CREATE SET dep.arcType = 'FUNCTIONAL', dep.direction = 'UNIDIRECTIONAL', dep.criticality = 'LOW'
                        """,
                        d_id=mf["domain_id"], mf_id=mf["id"],
                        arc_id=f"fn-{mf['domain_id']}-{mf['id']}",
                    )
                counts["macro_functions"] += 1

            # ── Programmes → :Program:TechnicalNode ──────────────────────────
            # Les programmes (COBOL, JCL…) sont des composants techniques : label
            # :TechnicalNode pour get_nodes(). `id` et `componentName` mappés depuis
            # `name` (identifiant canonique du programme).
            for p in programs:
                if not p.get("name"):
                    continue
                session.run(
                    """
                    MERGE (p:Program:TechnicalNode {id: $name})
                    ON CREATE SET p.name = $name, p.componentName = $name,
                                  p.technology = $tech, p.mode = $mode,
                                  p.description = $desc, p.candidate7R = 'UNQUALIFIED',
                                  p.isGhost = false, p.criticalityScore = 0,
                                  p.betweenness = 0.0, p.isSPOF = false,
                                  p.createdAt = datetime()
                    ON MATCH  SET p.componentName = $name, p.technology = $tech,
                                  p.mode = $mode, p.description = $desc,
                                  p.updatedAt = datetime()
                    """,
                    name=p["name"], tech=p.get("technology"),
                    mode=p.get("mode"), desc=p.get("description"),
                )
                for mf_id in (p.get("macro_function_ids") or []):
                    session.run(
                        """
                        MATCH (mf:MacroFunction {id: $mf_id})
                        MATCH (p:Program {id: $p_id})
                        MERGE (mf)-[:IMPLEMENTED_BY]->(p)
                        """,
                        mf_id=mf_id, p_id=p["name"],
                    )
                    session.run(
                        """
                        MATCH (mf:MacroFunction {id: $mf_id}), (p:Program {id: $p_id})
                        MERGE (mf)-[dep:DEPENDS_ON {id: $arc_id}]->(p)
                        ON CREATE SET dep.arcType = 'FUNCTIONAL', dep.direction = 'UNIDIRECTIONAL', dep.criticality = 'MEDIUM'
                        """,
                        mf_id=mf_id, p_id=p["name"],
                        arc_id=f"fn-{mf_id}-{p['name']}",
                    )
                counts["programs"] += 1

            # ── Entités de données → :DataEntity:FunctionalNode ──────────────
            for e in data_entities:
                if not e.get("name"):
                    continue
                session.run(
                    """
                    MERGE (e:DataEntity:FunctionalNode {id: $name})
                    ON CREATE SET e.name = $name, e.domain = $name,
                                  e.type = $type, e.description = $desc,
                                  e.modernizationStatus = 'EXISTING',
                                  e.createdAt = datetime()
                    ON MATCH  SET e.type = $type, e.description = $desc,
                                  e.domain = $name, e.updatedAt = datetime()
                    """,
                    name=e["name"], type=e.get("type"), desc=e.get("description"),
                )
                counts["data_entities"] += 1

            # ── Relations CRUD ────────────────────────────────────────────────
            for cr in crud_relationships:
                p_name = cr.get("program_name")
                e_name = cr.get("entity_name")
                ops    = cr.get("operations") or []
                if not p_name or not e_name:
                    continue
                # Garantit l'existence de l'entité même si absente de data_entities
                session.run(
                    "MERGE (e:DataEntity:FunctionalNode {id: $name}) ON CREATE SET e.name = $name, e.domain = $name",
                    name=e_name,
                )
                for op in ops:
                    rel_type = _CRUD_REL.get(str(op).upper())
                    if not rel_type:
                        continue
                    session.run(
                        f"MATCH (p:Program {{id: $p}}) MATCH (e:DataEntity {{id: $e}}) MERGE (p)-[:{rel_type}]->(e)",
                        p=p_name, e=e_name,
                    )
                    counts["relationships"] += 1
                # Un seul DEPENDS_ON par paire (program, entity) pour la vue graphe
                session.run(
                    """
                    MATCH (p:Program {id: $p}), (e:DataEntity {id: $e})
                    MERGE (p)-[dep:DEPENDS_ON {id: $arc_id}]->(e)
                    ON CREATE SET dep.arcType = 'DATA_FLOW', dep.direction = 'UNIDIRECTIONAL', dep.criticality = 'MEDIUM'
                    """,
                    p=p_name, e=e_name, arc_id=f"data-{p_name}-{e_name}",
                )

    except Exception as exc:
        logger.error(f"import_entities failed: {exc}")
        return error_response("Erreur interne lors de l'import dans Neo4j.", 500)

    return func.HttpResponse(
        json.dumps({
            "status": "ok",
            "imported": counts,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }),
        status_code=200,
        mimetype="application/json",
    )


# ============================================================================
# Main HTTP Trigger (routing)
# ============================================================================

def main(req: func.HttpRequest) -> func.HttpResponse:
    """HTTP trigger — route /graph/* vers les handlers (SDD §3)."""
    method = req.method
    path = req.route_params.get('path', '') or ''
    parts = [p for p in path.split("/") if p]

    logger.info(f"{method} /graph/{path}")

    if method == "GET":
        if parts == ["health"]:
            return get_health()
        if parts and parts[0] == "nodes":
            if len(parts) == 1:
                return get_nodes(req)
            if len(parts) == 2:
                return get_node_by_id(parts[1])
            if len(parts) == 3 and parts[2] == "impact":
                return get_node_impact(parts[1])
            if len(parts) == 3 and parts[2] == "neighbors":
                return get_node_neighbors(parts[1])
        if parts == ["arcs"]:
            return get_arcs(req)
        if parts == ["clusters"]:
            return get_clusters(req)

    if method == "POST":
        if parts == ["admin", "analyze"]:
            return run_analysis(req)
        if parts == ["admin", "import-entities"]:
            return import_entities(req)

    if method == "DELETE":
        if parts == ["admin", "functional-entities"]:
            return clear_functional_entities(req)
        if parts == ["admin", "reset"]:
            return reset_graph(req)

    if method == "PATCH":
        if len(parts) == 3 and parts[0] == "nodes" and parts[2] == "qualification":
            return patch_node_qualification(req, parts[1])

    return error_response("Not found", 404)


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
#          "route": "graph/{*path}"
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
