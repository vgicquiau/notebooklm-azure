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
- POST /graph/admin/archimate-classify — étiquette des nœuds v2.0 existants avec la taxonomie
  ArchiMate 3.x (elementType/layer/aspect), produit par le pipeline de classification LLM

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
import sys
import uuid
from datetime import datetime, timezone
from neo4j import GraphDatabase

# Le worker Python du modèle V1 (function.json + scriptFile) n'ajoute pas
# systématiquement le dossier de la function au sys.path — sans ce répertoire,
# `import archimate_taxonomy` lève ModuleNotFoundError en production bien que le
# fichier soit déployé à côté de function_app.py (fonctionne en local car le cwd
# y est déjà).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import archimate_taxonomy as archimate
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

# Analyse F1.3/F1.5 (SDD §2.1 + §4 tuning) — exécutée par /graph/admin/analyze, pas par l'ingestion
GDS_TECH_PROJECTION = "moderngraph_tech"
SPOF_BETWEENNESS_PERCENTILE = float(os.getenv("SPOF_BETWEENNESS_PERCENTILE", "90"))

# 1B — projection structurelle (taxonomie v2.0, Couches 3-4) : labels/relations porteurs de
# couplage réel. Remplace l'ancienne projection (:TechnicalNode)-[:DEPENDS_ON] (edgeless,
# aucun DEPENDS_ON Program->Program n'a jamais existé — cf. plan).
GDS_STRUCTURAL_NODE_LABELS = [
    "Composant", "Structure_Partagee", "Store_Donnees", "Store_Echange",
    "Table_Relationnelle", "Store_Hierarchique", "Canal_Messagerie",
]
GDS_STRUCTURAL_REL_CONFIG = {
    "APPELLE": {"orientation": "UNDIRECTED"},
    "INCLUT": {"orientation": "UNDIRECTED"},
    "ACCEDE_A": {"orientation": "UNDIRECTED"},
}

# Poids heuristiques de Score_Criticite (Partie C, ligne 128 : "agrège fan-in, fan-out,
# ... présence SPOF") — fan-in/fan-out comptent modérément, SPOF/articulation (signaux
# structurels forts) pèsent plus lourd. Score plafonné à 100 (Partie C : integer [0-100]).
_CRITICITE_FANINOUT_WEIGHT = 5
_CRITICITE_SPOF_BONUS = 30
_CRITICITE_ARTICULATION_BONUS = 20

# ============================================================================
# Taxonomie GraphRAG Legacy-Modernisation v2.0 — Phase 1 (voir
# notebooklm-azure/glossaire-taxonomie-graphrag-legacy-modernisation.md)
# ============================================================================

# 18 labels de la taxonomie + System (racine, non-taxonomie, conservé). Préfixes d'id
# (Partie C, "<préfixe>:<nom>") documentés dans le system prompt extract.py.
ALLOWED_NODE_LABELS = {
    "System", "Domaine_Fonctionnel", "Fonction", "Regle_Metier", "Processus_Fonctionnel",
    "Composant", "Point_Entree", "Interface_Utilisateur",
    "Job_Batch", "Unite_Execution", "Procedure_Reutilisable", "Structure_Partagee",
    "Store_Donnees", "Store_Echange", "Table_Relationnelle", "Store_Hierarchique",
    "Entite_Donnees", "Canal_Messagerie", "Zone_Incertitude",
}

# 12 types de relation de la taxonomie v2 (Partie B.1/B.2, ASCII : IMPLEMENTE/DECLENCHE —
# accents retirés des identifiants Cypher, plan decision #3) + CORRESPOND_A (B.2,
# Entite_Donnees -> stores). from -> to attendus (non vérifiés à l'exécution — le moteur
# d'import est générique/label-driven, plan decision #1) :
#   CONTIENT            Domaine_Fonctionnel->Processus_Fonctionnel | System->
#                        Domaine_Fonctionnel  (2e groupe = Ext #2)
#   CATALOGUE           Domaine_Fonctionnel->Fonction  (rattachement logique au catalogue,
#                        indépendant de l'exécution — distinct de CONTIENT)
#   PORTE_REGLE         Fonction->Regle_Metier
#   ORCHESTRE           Processus_Fonctionnel->Fonction
#   ORIENTE_PAR         Processus_Fonctionnel->Regle_Metier  (règle qui oriente le routage/
#                        branchement du processus — distinct de PORTE_REGLE)
#   IMPLEMENTE          Composant->Fonction
#   ENCODE_REGLE        Composant->Regle_Metier
#   APPELLE             Composant->Composant
#   INCLUT              Composant->Structure_Partagee
#   ACCEDE_A            Composant->{Store_Donnees,Store_Echange,Table_Relationnelle,
#                        Store_Hierarchique,Canal_Messagerie}  (operations[] = Ext #1)
#   DECLENCHE           {Unite_Execution,Point_Entree}->Composant
#   CONTIENT_STEP       Job_Batch->Unite_Execution
#   CORRESPOND_A        Entite_Donnees->{Store_Donnees,Table_Relationnelle,Store_Hierarchique}
#   GENERE_INCERTITUDE  <tout nœud>->Zone_Incertitude
#   DEPEND_DE           Domaine_Fonctionnel->Domaine_Fonctionnel | Fonction->Fonction |
#                        Processus_Fonctionnel->Processus_Fonctionnel  (relation générique
#                        même-label, ext. dépendances inter-domaines/fonctions/processus ;
#                        props : fiabilite, nature [DONNEES|ORDONNANCEMENT|APPEL|
#                        DECLENCHEMENT|GOUVERNANCE], description optionnelle)
#   APPARTIENT_DOMAINE  {Composant,Job_Batch,Structure_Partagee,Store_Echange}->
#                        Domaine_Fonctionnel  (Ext #4, extension additive — rattachement
#                        d'un artefact applicatif/données à son domaine fonctionnel,
#                        typiquement issu d'un clustering automatique (communautés
#                        GraphRAG/Louvain) ; fiabilite généralement HYPOTHÈSE)
#   CONTIENT_PROGRAMME  Job_Batch->Composant  (Ext #4, extension additive — ce job batch
#                        exécute ce composant ; distinct de CONTIENT_STEP qui passe par un
#                        Unite_Execution intermédiaire, absent de certaines sources
#                        automatiques (ex. GraphRAG))
ALLOWED_REL_TYPES = {
    "CONTIENT", "CATALOGUE", "PORTE_REGLE", "ORCHESTRE", "ORIENTE_PAR", "IMPLEMENTE",
    "ENCODE_REGLE", "APPELLE", "INCLUT", "ACCEDE_A", "DECLENCHE", "CONTIENT_STEP",
    "CORRESPOND_A", "GENERE_INCERTITUDE", "DEPEND_DE",
    "APPARTIENT_DOMAINE", "CONTIENT_PROGRAMME",
}

# F.2 — fiabilite : priorité d'upgrade FAIT > HYPOTHÈSE > SUPPOSÉ > MANQUANT. Une ré-extraction
# ne peut jamais dégrader la fiabilite déjà connue d'un nœud/relation (import_entities).
_FIABILITE_RANK = {"MANQUANT": 0, "SUPPOSÉ": 1, "HYPOTHÈSE": 2, "FAIT": 3}
_DEFAULT_FIABILITE = "SUPPOSÉ"

# Regroupement par plan pour le frontend bi-plan (GraphPage.jsx, increment 1C) — chaque
# label Phase-1 vers functional|technical|data|global.
_PLANE_BY_LABEL = {
    "System": "global",
    "Domaine_Fonctionnel": "functional", "Fonction": "functional",
    "Regle_Metier": "functional", "Processus_Fonctionnel": "functional",
    "Composant": "technical",
    "Point_Entree": "technical", "Interface_Utilisateur": "technical",
    "Job_Batch": "technical", "Unite_Execution": "technical",
    "Procedure_Reutilisable": "technical",
    "Structure_Partagee": "data", "Store_Donnees": "data",
    "Store_Echange": "data", "Table_Relationnelle": "data",
    "Store_Hierarchique": "data", "Entite_Donnees": "data",
    "Canal_Messagerie": "data",
    "Zone_Incertitude": "global",
}

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

def _generic_node_dto(props: dict, label: str) -> dict:
    """DTO générique pour les 20 labels Phase-1 de la taxonomie GraphRAG v2.0 — propriétés
    brutes (dates converties) + label/plane/subtype. Le détail par sous-type (couleurs,
    formes, panneau de détail) est calculé côté frontend (GraphPage.jsx, increment 1C)."""
    dto = {k: _to_json(v) for k, v in props.items()}
    dto["label"] = label
    dto["plane"] = _PLANE_BY_LABEL.get(label, "global")
    dto["type"] = dto["plane"]
    dto["subtype"] = label.lower()
    return dto

def node_to_dto(node) -> dict:
    """Nœud Neo4j -> DTO générique (taxonomie v2.0, 20 labels Phase-1)."""
    props = dict(node)
    labels = set(node.labels)
    label = next((l for l in ALLOWED_NODE_LABELS if l in labels), None) or sorted(labels)[0]
    return _generic_node_dto(props, label)

def error_response(message: str, status_code: int, **extra) -> func.HttpResponse:
    body = {"error": message}
    body.update(extra)
    return func.HttpResponse(json.dumps(body), status_code=status_code, mimetype="application/json")

# ============================================================================
# Module Exploration — RBAC minimal (PLAN_EXPLORATION_v1.md T0-B-03)
#
# L'app n'a pas de JWT (usage local mono-utilisateur, cf. README). Le rôle est lu
# depuis le header `X-User-Role` — whitelist VIEWER/ARCHITECT/ADMIN, défaut VIEWER
# si absent/invalide. `resolve_role()` est le seul point à remplacer par une vraie
# résolution JWT en v2 ; `require_role()` reste inchangé.
# ============================================================================

EXPLORATION_ROLES = ("VIEWER", "ARCHITECT", "ADMIN")


def resolve_role(request: func.HttpRequest) -> str:
    role = (request.headers.get("X-User-Role") or "").strip().upper()
    return role if role in EXPLORATION_ROLES else "VIEWER"


def require_role(request: func.HttpRequest, *allowed_roles: str):
    """Retourne None si le rôle courant est autorisé, sinon une 403 AUTH_INSUFFICIENT_ROLE
    (SDD §7/§8) prête à être `return`ée par le handler appelant."""
    role = resolve_role(request)
    if role not in allowed_roles:
        return error_response(
            "Opération non autorisée pour votre rôle", 403,
            code="AUTH_INSUFFICIENT_ROLE", role=role,
        )
    return None

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
    """GET /graph/nodes — Liste filtrable et paginée des nœuds (taxonomie v2.0, 20 labels Phase-1).

    Filtres optionnels : `label` (un des ALLOWED_NODE_LABELS), `plane`
    (functional|technical|data|global, via _PLANE_BY_LABEL), `fiabilite`
    (FAIT|HYPOTHÈSE|SUPPOSÉ|MANQUANT), `candidate7R` (qualification 7R, propriété
    Composant uniquement — ignoré pour les autres labels)."""
    try:
        label = request.params.get("label")
        plane = request.params.get("plane")
        fiabilite = request.params.get("fiabilite")
        candidate7r = request.params.get("candidate7R")

        if label and label not in ALLOWED_NODE_LABELS:
            return error_response("Paramètre label invalide", 400)
        if plane and plane not in _PLANE_BY_LABEL.values():
            return error_response("Paramètre plane invalide", 400)
        if fiabilite and fiabilite not in _FIABILITE_RANK:
            return error_response("Paramètre fiabilite invalide", 400)
        if candidate7r and candidate7r not in SEVEN_R_VALUES:
            return error_response("Paramètre candidate7R invalide", 400)

        plane_labels = [l for l, p in _PLANE_BY_LABEL.items() if p == plane] if plane else None

        params = {
            "allowedLabels": list(ALLOWED_NODE_LABELS),
            "label": label,
            "planeLabels": plane_labels,
            "fiabilite": fiabilite,
            "candidate7R": candidate7r,
            "limit": max(0, _parse_int_param(request, "limit", 100)),
            "offset": max(0, _parse_int_param(request, "offset", 0)),
        }

        where_clause = """
            any(l IN labels(n) WHERE l IN $allowedLabels)
            AND ($label IS NULL OR $label IN labels(n))
            AND ($planeLabels IS NULL OR any(l IN labels(n) WHERE l IN $planeLabels))
            AND ($fiabilite IS NULL OR n.fiabilite = $fiabilite)
            AND ($candidate7R IS NULL OR n.candidate7R = $candidate7R)
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
    """GET /graph/nodes/{id} — Détail complet : métriques dérivées + arcs entrants/sortants résumés
    (taxonomie v2.0, ALLOWED_REL_TYPES uniquement)."""
    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            record = session.run(
                "MATCH (n) WHERE any(l IN labels(n) WHERE l IN $allowedLabels) AND n.id = $id RETURN n",
                {"id": node_id, "allowedLabels": list(ALLOWED_NODE_LABELS)}
            ).single()

            if not record:
                return error_response("Nœud introuvable", 404)

            node = record["n"]

            incoming_arcs = [
                {
                    "id": f"{rec['relType']}-{rec['otherId']}-{node_id}",
                    "sourceNodeId": rec["otherId"],
                    "type": rec["relType"],
                    **{k: _to_json(v) for k, v in rec["props"].items()},
                }
                for rec in session.run(
                    """
                    MATCH (src)-[r]->(n {id: $id}) WHERE type(r) IN $relTypes
                    RETURN type(r) AS relType, src.id AS otherId, properties(r) AS props
                    ORDER BY relType, otherId
                    """,
                    {"id": node_id, "relTypes": list(ALLOWED_REL_TYPES)}
                )
            ]
            outgoing_arcs = [
                {
                    "id": f"{rec['relType']}-{node_id}-{rec['otherId']}",
                    "targetNodeId": rec["otherId"],
                    "type": rec["relType"],
                    **{k: _to_json(v) for k, v in rec["props"].items()},
                }
                for rec in session.run(
                    """
                    MATCH (n {id: $id})-[r]->(tgt) WHERE type(r) IN $relTypes
                    RETURN type(r) AS relType, tgt.id AS otherId, properties(r) AS props
                    ORDER BY relType, otherId
                    """,
                    {"id": node_id, "relTypes": list(ALLOWED_REL_TYPES)}
                )
            ]

            metrics = {
                "inDegree": len(incoming_arcs),
                "outDegree": len(outgoing_arcs),
            }

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

    Contrairement à /graph/arcs (relations structurelles uniquement), cet endpoint traverse
    TOUTES les relations Neo4j du nœud parmi ALLOWED_REL_TYPES. Utilisé par le double-clic
    d'exploration dans GraphPage.jsx.
    """
    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            allowed_labels = list(ALLOWED_NODE_LABELS)
            allowed_rels = list(ALLOWED_REL_TYPES)

            center_rec = session.run(
                "MATCH (n) WHERE any(l IN labels(n) WHERE l IN $allowedLabels) AND n.id = $id RETURN n",
                {"id": node_id, "allowedLabels": allowed_labels}
            ).single()
            if not center_rec:
                return error_response("Nœud introuvable", 404)

            center_node = center_rec["n"]

            # Toutes les relations adjacentes (ALLOWED_REL_TYPES) — startNode/endNode préservent
            # la direction réelle. DISTINCT évite les doublons dus au parcours bidirectionnel
            # de MATCH (n)-[r]-(m).
            records = session.run(
                """
                MATCH (center {id: $id})-[r]-(neighbor)
                WHERE any(l IN labels(center) WHERE l IN $allowedLabels)
                  AND any(l IN labels(neighbor) WHERE l IN $allowedLabels)
                  AND type(r) IN $allowedRels
                RETURN DISTINCT
                    neighbor,
                    type(r)          AS relType,
                    startNode(r).id  AS sourceId,
                    endNode(r).id    AS targetId,
                    r.fiabilite      AS fiabilite
                ORDER BY relType, sourceId, targetId
                """,
                {"id": node_id, "allowedLabels": allowed_labels, "allowedRels": allowed_rels}
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
                edge_key    = (source_id, target_id, rel_type)

                if edge_key not in seen_edges:
                    seen_edges.add(edge_key)
                    edges.append({
                        "id":           f"{rel_type}-{source_id}-{target_id}",
                        "sourceNodeId": source_id,
                        "targetNodeId": target_id,
                        "type":         rel_type,
                        "fiabilite":    rec["fiabilite"] or _DEFAULT_FIABILITE,
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
    """GET /graph/nodes/{id}/impact — Rayon d'impact downstream d'un :Composant (SDD §3, consommé par ADM-M C5).

    `isSpof`/`betweennessScore` sont des propriétés calculées par le job d'analyse F1.3/F1.5
    (cf. detect_spof / POST /graph/admin/analyze, 1B) — cet endpoint les lit telles que
    persistées, il ne relance pas GDS à la volée. `downstreamImpacted` parcourt les appels
    [:APPELLE*] (1B — projection structurelle) pour tout :Composant existant (pas seulement
    les SPOF) : `isSpof` indique au consommateur le poids à accorder au résultat.
    """
    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            record = session.run(
                "MATCH (n:Composant {id: $id}) RETURN n.isSpof AS isSpof",
                {"id": node_id}
            ).single()

            if not record:
                return error_response("Nœud introuvable", 404)

            downstream = [
                {
                    "id": rec["id"],
                    "nom": rec["nom"],
                    "distance": rec["distance"],
                    "fiabilite": rec["fiabilite"],
                }
                for rec in session.run(
                    """
                    MATCH (origin:Composant {id: $id})
                    MATCH path = (origin)-[:APPELLE*1..18]->(downstream:Composant)
                    WHERE downstream <> origin
                    WITH downstream, path, length(path) AS len
                    ORDER BY len ASC
                    WITH downstream, collect(path)[0] AS shortestPath, min(len) AS distance
                    RETURN downstream.id AS id, downstream.nom AS nom,
                           distance, last(relationships(shortestPath)).fiabilite AS fiabilite
                    ORDER BY distance, nom
                    """,
                    {"id": node_id}
                )
            ]

        return func.HttpResponse(
            json.dumps({
                "nodeId": node_id,
                "isSpof": record["isSpof"] if record["isSpof"] is not None else False,
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
                "MATCH (n:Composant {id: $id}) RETURN n.candidate7R AS previous7R",
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
                "MATCH (n:Composant {id: $id}) SET n.candidate7R = $candidate7R, n.updatedAt = $updatedAt",
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
    """GET /graph/arcs — Liste filtrable des relations (taxonomie v2.0, ALLOWED_REL_TYPES).

    Filtres optionnels : `nodeId` (source ou cible), `type` (un des ALLOWED_REL_TYPES),
    `fiabilite` (FAIT|HYPOTHÈSE|SUPPOSÉ|MANQUANT)."""
    try:
        rel_type = request.params.get("type")
        fiabilite = request.params.get("fiabilite")

        if rel_type and rel_type not in ALLOWED_REL_TYPES:
            return error_response("Paramètre de filtre invalide", 400)
        if fiabilite and fiabilite not in _FIABILITE_RANK:
            return error_response("Paramètre de filtre invalide", 400)

        params = {
            "allowedRels": list(ALLOWED_REL_TYPES),
            "nodeId": request.params.get("nodeId"),
            "type": rel_type,
            "fiabilite": fiabilite,
            "limit": max(0, _parse_int_param(request, "limit", 100)),
            "offset": max(0, _parse_int_param(request, "offset", 0)),
        }

        where_clause = """
            type(r) IN $allowedRels
            AND ($nodeId IS NULL OR source.id = $nodeId OR target.id = $nodeId)
            AND ($type IS NULL OR type(r) = $type)
            AND ($fiabilite IS NULL OR r.fiabilite = $fiabilite)
        """

        driver = get_neo4j_driver()
        with driver.session() as session:
            total = session.run(
                f"MATCH (source)-[r]->(target) WHERE {where_clause} RETURN count(r) AS total", params
            ).single()["total"]
            records = session.run(
                f"""
                MATCH (source)-[r]->(target) WHERE {where_clause}
                RETURN source.id AS sourceNodeId, target.id AS targetNodeId,
                       type(r) AS type, r.fiabilite AS fiabilite, properties(r) AS properties
                ORDER BY type, sourceNodeId, targetNodeId SKIP $offset LIMIT $limit
                """,
                params
            )
            items = []
            for record in records:
                props = {k: _to_json(v) for k, v in record["properties"].items()}
                items.append({
                    "id": f"{record['type']}-{record['sourceNodeId']}-{record['targetNodeId']}",
                    "sourceNodeId": record["sourceNodeId"],
                    "targetNodeId": record["targetNodeId"],
                    "type": record["type"],
                    "fiabilite": record["fiabilite"] or _DEFAULT_FIABILITE,
                    "properties": props,
                })

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

    Cluster n'a pas de label dans le schéma Neo4j : agrégation calculée à la lecture, par
    regroupement des nœuds de la projection structurelle (1B — GDS_STRUCTURAL_NODE_LABELS)
    sur communityId (écrit par run_louvain / gds.louvain.write — 409 si jamais exécuté).

    cohesion/externalCoupling n'ont pas de formule donnée dans le SDD (seulement les seuils
    > 0.7 / < 0.3 et "ratios 0-1", §2.3 lignes 263-265) — gap structurel identique à "pas de
    voisin redondant" pour detect_spof. Dérivés ici à partir des arcs structurels (1B —
    GDS_STRUCTURAL_REL_CONFIG) internes vs. sortants de chaque communauté :
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
            structural_labels = list(GDS_STRUCTURAL_NODE_LABELS)
            structural_rels = list(GDS_STRUCTURAL_REL_CONFIG.keys())

            community_rows = [
                {"communityId": rec["communityId"], "id": rec["id"]}
                for rec in session.run(
                    """
                    MATCH (n) WHERE any(l IN labels(n) WHERE l IN $labels) AND n.communityId IS NOT NULL
                    RETURN n.communityId AS communityId, n.id AS id
                    """,
                    {"labels": structural_labels}
                )
            ]
            if not community_rows:
                return error_response("Clusters non calculés. Lancer l'analyse du graphe.", 409)

            edges = [
                (rec["sourceId"], rec["targetId"])
                for rec in session.run(
                    """
                    MATCH (a)-[r]->(b)
                    WHERE any(l IN labels(a) WHERE l IN $labels) AND any(l IN labels(b) WHERE l IN $labels)
                      AND type(r) IN $relTypes
                    RETURN a.id AS sourceId, b.id AS targetId
                    """,
                    {"labels": structural_labels, "relTypes": structural_rels}
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


def _structural_projection_inputs(session) -> tuple[list[str], dict]:
    """gds.graph.project lève IllegalArgumentException si un label/type de
    GDS_STRUCTURAL_NODE_LABELS / GDS_STRUCTURAL_REL_CONFIG n'existe pas du tout dans le
    graphe (ex : aucune relation APPELLE/INCLUT/ACCEDE_A pas encore extraite). On restreint
    donc la projection aux labels/types réellement présents — un sous-ensemble vide signale
    à l'appelant de sauter la projection GDS et renvoyer un résultat neutre."""
    existing_labels = {r["label"] for r in session.run("CALL db.labels() YIELD label RETURN label")}
    existing_rel_types = {r["relationshipType"] for r in session.run(
        "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType"
    )}
    node_labels = [l for l in GDS_STRUCTURAL_NODE_LABELS if l in existing_labels]
    rel_config = {t: cfg for t, cfg in GDS_STRUCTURAL_REL_CONFIG.items() if t in existing_rel_types}
    return node_labels, rel_config


def compute_criticality(driver) -> int:
    """F1.3 — criticiteScore [0-100] (Partie C, ligne 128) sur Composant et Store_Donnees.

    fanIn/fanOut (Partie C : applicable sur Composant, + fanIn sur Structure_Partagee et
    Store_Donnees) sont calculés depuis les arcs structurels APPELLE/INCLUT/ACCEDE_A/
    DECLENCHE (1B). criticiteScore agrège fanIn/fanOut/isSpof/isArticulationPoint — ces deux
    derniers doivent déjà être écrits par detect_spof (run_analysis appelle detect_spof
    avant compute_criticality)."""
    with driver.session() as session:
        session.run(
            """
            MATCH (c:Composant)
            SET c.fanOut = COUNT { (c)-[:APPELLE]->(:Composant) },
                c.fanIn  = COUNT { (c)<-[:APPELLE]-(:Composant) } + COUNT { (c)<-[:DECLENCHE]-() }
            """
        ).consume()
        session.run(
            """
            MATCH (s:Structure_Partagee)
            SET s.fanIn = COUNT { (s)<-[:INCLUT]-(:Composant) }
            """
        ).consume()
        session.run(
            """
            MATCH (s:Store_Donnees)
            SET s.fanIn = COUNT { (s)<-[:ACCEDE_A]-(:Composant) }
            """
        ).consume()

        result = session.run(
            """
            MATCH (n)
            WHERE n:Composant OR n:Store_Donnees
            WITH n, (coalesce(n.fanIn, 0) * $w + coalesce(n.fanOut, 0) * $w
                     + CASE WHEN coalesce(n.isSpof, false) THEN $spof ELSE 0 END
                     + CASE WHEN coalesce(n.isArticulationPoint, false) THEN $art ELSE 0 END) AS raw
            SET n.criticiteScore = CASE WHEN raw > 100 THEN 100 ELSE raw END
            RETURN count(n) AS updated
            """,
            {"w": _CRITICITE_FANINOUT_WEIGHT, "spof": _CRITICITE_SPOF_BONUS, "art": _CRITICITE_ARTICULATION_BONUS},
        )
        return result.single()["updated"]


def detect_spof(driver, percentile: float = SPOF_BETWEENNESS_PERCENTILE) -> dict:
    """F1.3/F1.5 — isSpof = betweennessScore > pXX ET pas de voisin redondant (Partie C : SPOF
    / Noeud_Articulation).

    « Pas de voisin redondant » est opérationnalisé comme : le nœud est un point d'articulation
    (gds.articulationPoints — sa suppression déconnecterait le graphe, donc aucun chemin de
    secours n'existe entre ses voisins). Une betweenness élevée seule ne suffit pas : un hub très
    sollicité mais doublé par un chemin alternatif n'est pas un SPOF réel — d'où le ET.

    Projection structurelle 1B (GDS_STRUCTURAL_NODE_LABELS / GDS_STRUCTURAL_REL_CONFIG, non
    orientée, partagée avec run_louvain) ; supprimée après lecture des métriques (op. coûteuse
    en mémoire GDS, ne doit pas persister entre deux exécutions du job). Écrit
    betweennessScore/isSpof/isArticulationPoint sur Composant et Store_Donnees (Partie C
    "applicable sur").
    """
    with driver.session() as session:
        _drop_projection_if_exists(session, GDS_TECH_PROJECTION)
        node_labels, rel_config = _structural_projection_inputs(session)

        if not node_labels or not rel_config:
            # Graphe structurel vide ou incomplet (aucun Composant/Store_*/Structure_Partagee,
            # ou aucune relation APPELLE/INCLUT/ACCEDE_A pas encore extraite) — gds.graph.project
            # lève IllegalArgumentException si un label/type projeté n'existe pas du tout dans
            # le graphe ; retour neutre dans ce cas.
            return {
                "nodesAnalyzed": 0,
                "betweennessPercentile": percentile,
                "betweennessThreshold": 0.0,
                "spofCount": 0,
                "spofNodeIds": [],
            }

        session.run(
            "CALL gds.graph.project($name, $nodeLabels, $relConfig)",
            {"name": GDS_TECH_PROJECTION, "nodeLabels": node_labels, "relConfig": rel_config}
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
            {
                "id": node_id, "betweenness": score,
                "isArticulationPoint": node_id in articulation_ids,
                "isSpof": score > threshold and node_id in articulation_ids,
            }
            for node_id, score in betweenness.items()
        ]

        session.run(
            """
            UNWIND $rows AS row
            MATCH (n {id: row.id})
            WHERE n:Composant OR n:Store_Donnees
            SET n.betweennessScore = row.betweenness, n.isSpof = row.isSpof,
                n.isArticulationPoint = row.isArticulationPoint
            """,
            {"rows": rows}
        ).consume()

        spof_ids = sorted(row["id"] for row in rows if row["isSpof"])
        return {
            "nodesAnalyzed": len(rows),
            "betweennessPercentile": percentile,
            "betweennessThreshold": threshold,
            "spofCount": len(spof_ids),
            "spofNodeIds": spof_ids,
        }


def run_louvain(driver) -> dict:
    """F1.5/Couche 6 — Communaute_Louvain (Partie B ligne 126) : projette la même projection
    structurelle que detect_spof (GDS_STRUCTURAL_NODE_LABELS / GDS_STRUCTURAL_REL_CONFIG,
    supprimée après écriture) puis gds.louvain.write(..., writeProperty: 'communityId').
    communityId est écrit sur tous les labels projetés (Partie C : "Tous") — proxy
    automatique pour valider/challenger les Bounded Contexts candidats (Couche 5, hors
    scope de cet arc). Le reste (cohesion, externalCoupling, regroupement) est calculé à la
    lecture par get_clusters."""
    with driver.session() as session:
        _drop_projection_if_exists(session, GDS_TECH_PROJECTION)
        node_labels, rel_config = _structural_projection_inputs(session)

        if not node_labels or not rel_config:
            # Graphe structurel vide ou incomplet — cf. detect_spof.
            return {"communityCount": 0, "modularity": 0.0}

        session.run(
            "CALL gds.graph.project($name, $nodeLabels, $relConfig)",
            {"name": GDS_TECH_PROJECTION, "nodeLabels": node_labels, "relConfig": rel_config}
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
    """DELETE /graph/admin/functional-entities — pré-étape du bouton "Mise à jour" (ré-extraction
    complète, taxonomie v2.0) : supprime tout le graphe SAUF :Composant/:System, puis détache
    les :Composant de leurs relations. Les nœuds :Composant et leurs propriétés de
    qualification (strategie7R, candidate7R) et calculées par GDS (isSpof, betweennessScore,
    communityId, ...) survivent ainsi à une ré-extraction ; tout le reste (Fonction,
    Regle_Metier, stores, relations...) est intégralement reconstruit par l'extraction
    suivante."""
    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            count_result = session.run(
                "MATCH (n) WHERE NOT n:Composant AND NOT n:System RETURN count(n) AS total"
            )
            total = count_result.single()["total"]
            session.run("MATCH (n) WHERE NOT n:Composant AND NOT n:System DETACH DELETE n")
            session.run("MATCH (c:Composant)-[r]-() DELETE r")
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

    Ordre 1B : detect_spof avant compute_criticality — criticiteScore agrège isSpof/
    isArticulationPoint/betweennessScore, écrits par detect_spof.
    """
    try:
        driver = get_neo4j_driver()
        spof = detect_spof(driver)
        nodes_scored = compute_criticality(driver)
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
    """Merge un graphe de connaissance (extrait des documents Chat via GPT-4o, taxonomie
    GraphRAG Legacy-Modernisation v2.0) dans Neo4j.

    Payload JSON :
    {
      "nodes":     [{"id": str, "label": str, "properties": {...}}],
      "relations": [{"from": str, "to": str, "type": str, "properties": {...}}]
    }

    `label` doit appartenir à ALLOWED_NODE_LABELS et `type` à ALLOWED_REL_TYPES — toute
    entrée hors de ces ensembles est ignorée (défense contre la dérive du LLM extracteur).
    MERGE par `id` pour les nœuds, par triplet (from, type, to) pour les relations (F.2).
    Le label/type dynamique est injecté par interpolation de chaîne dans la requête Cypher
    (APOC n'est pas disponible sur cette instance — `apoc.merge.*` retourne
    ProcedureNotFound) ; c'est sans risque d'injection car `label`/`rel_type` sont
    systématiquement vérifiés contre ALLOWED_NODE_LABELS/ALLOWED_REL_TYPES (ensembles fermés
    de littéraux) avant interpolation. La propriété `fiabilite` (FAIT > HYPOTHÈSE > SUPPOSÉ >
    MANQUANT, F.2) est upgrade-only : un import qui re-merge un nœud/relation existant ne
    peut jamais dégrader sa fiabilite.
    """
    try:
        body = req.get_json()
    except Exception:
        return error_response("Corps JSON invalide", 400)

    nodes     = body.get("nodes") or []
    relations = body.get("relations") or []
    counts: dict[str, int] = {}
    now = datetime.now(timezone.utc).isoformat()

    try:
        driver = get_neo4j_driver()
        with driver.session() as session:

            # ── Nœuds ─────────────────────────────────────────────────────────
            for n in nodes:
                node_id = n.get("id")
                label = n.get("label")
                if not node_id or label not in ALLOWED_NODE_LABELS:
                    logger.warning("import_entities: nœud ignoré (id=%r, label=%r)", node_id, label)
                    continue

                props = dict(n.get("properties") or {})
                props["id"] = node_id
                fiabilite = props.get("fiabilite")
                if fiabilite not in _FIABILITE_RANK:
                    fiabilite = _DEFAULT_FIABILITE
                props["fiabilite"] = fiabilite

                on_create = dict(props)
                on_create["createdAt"] = now
                on_match = {k: v for k, v in props.items() if k != "fiabilite"}
                on_match["updatedAt"] = now

                session.run(
                    f"""
                    MERGE (node:{label} {{id: $id}})
                    ON CREATE SET node += $onCreate
                    ON MATCH SET node += $onMatch
                    WITH node, coalesce($fiabiliteRank[node.fiabilite], -1) AS existingRank
                    SET node.fiabilite = CASE WHEN $incomingRank > existingRank
                                              THEN $incomingFiabilite ELSE node.fiabilite END
                    """,
                    {
                        "id": node_id,
                        "onCreate": on_create, "onMatch": on_match,
                        "fiabiliteRank": _FIABILITE_RANK,
                        "incomingRank": _FIABILITE_RANK[fiabilite],
                        "incomingFiabilite": fiabilite,
                    },
                ).consume()
                counts[label] = counts.get(label, 0) + 1

            # ── Relations ─────────────────────────────────────────────────────
            for r in relations:
                from_id, to_id, rel_type = r.get("from"), r.get("to"), r.get("type")
                if not from_id or not to_id or rel_type not in ALLOWED_REL_TYPES:
                    logger.warning("import_entities: relation ignorée (from=%r, to=%r, type=%r)",
                                    from_id, to_id, rel_type)
                    continue

                props = dict(r.get("properties") or {})
                fiabilite = props.get("fiabilite")
                if fiabilite not in _FIABILITE_RANK:
                    fiabilite = _DEFAULT_FIABILITE
                props["fiabilite"] = fiabilite

                on_create = dict(props)
                on_create["createdAt"] = now
                on_match = {k: v for k, v in props.items() if k != "fiabilite"}
                on_match["updatedAt"] = now

                result = session.run(
                    f"""
                    MATCH (a {{id: $from}}), (b {{id: $to}})
                    MERGE (a)-[rel:{rel_type}]->(b)
                    ON CREATE SET rel += $onCreate
                    ON MATCH SET rel += $onMatch
                    WITH rel, coalesce($fiabiliteRank[rel.fiabilite], -1) AS existingRank
                    SET rel.fiabilite = CASE WHEN $incomingRank > existingRank
                                             THEN $incomingFiabilite ELSE rel.fiabilite END
                    RETURN rel
                    """,
                    {
                        "from": from_id, "to": to_id,
                        "onCreate": on_create, "onMatch": on_match,
                        "fiabiliteRank": _FIABILITE_RANK,
                        "incomingRank": _FIABILITE_RANK[fiabilite],
                        "incomingFiabilite": fiabilite,
                    },
                )
                if not list(result):
                    logger.warning("import_entities: relation %s -[%s]-> %s ignorée (nœud(s) introuvable(s))",
                                    from_id, rel_type, to_id)
                    continue
                counts["relations"] = counts.get("relations", 0) + 1

    except Exception as exc:
        logger.error(f"import_entities failed: {exc}")
        return error_response("Erreur interne lors de l'import dans Neo4j.", 500)

    return func.HttpResponse(
        json.dumps({
            "status": "ok",
            "imported": counts,
            "timestamp": now,
        }),
        status_code=200,
        mimetype="application/json",
    )


# ============================================================================
# POST /graph/admin/archimate-classify — étiquette des nœuds existants (taxonomie
# GraphRAG v2.0) avec la taxonomie ArchiMate 3.x, pour le module Exploration
# ============================================================================

def archimate_classify_nodes(req: func.HttpRequest) -> func.HttpResponse:
    """POST /graph/admin/archimate-classify — applique elementType/layer/aspect (taxonomie
    ArchiMate 3.x, archimate_taxonomy.py) sur des nœuds existants identifiés par leur `id`
    (taxonomie GraphRAG v2.0). Approche multi-label additive : le label v2.0 (ex.
    `:Composant`) est conservé, `:ArchiMateElement` + labels dérivés de
    `archimate.labels_for(layer, elementType)` sont ajoutés. Rend les 1078 nœuds ADG-M
    visibles dans le module Exploration (MATCH (n:ArchiMateElement)).

    Payload JSON :
    {
      "classifications": [
        {"id": str, "elementType": str, "layer": str, "aspect": str|null,
         "description": str|null, "stereotype": str|null, "tags": [str]|null}
      ]
    }

    elementType/layer/aspect validés contre archimate_taxonomy (mêmes règles que
    POST /exploration/nodes — label dynamique sans risque d'injection : valeurs
    systématiquement vérifiées contre les ensembles fermés LAYERS/ALL_ELEMENT_TYPES avant
    interpolation). description/stereotype/tags ne sont écrits que si le nœud ne porte pas
    déjà la propriété (coalesce) — complète sans écraser les données issues de
    l'extraction v2.0.
    """
    try:
        body = req.get_json()
    except Exception:
        return error_response("Corps JSON invalide", 400)

    classifications = body.get("classifications") or []
    now = datetime.now(timezone.utc).isoformat()

    classified = 0
    errors: list[dict] = []

    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            for c in classifications:
                node_id = c.get("id")
                layer = c.get("layer")
                element_type = c.get("elementType")
                aspect = c.get("aspect")

                if not node_id:
                    errors.append({"id": node_id, "reason": "id manquant"})
                    continue
                if layer not in archimate.LAYERS or not archimate.validate_element_type(layer, element_type):
                    errors.append({"id": node_id, "reason": "elementType invalide pour ce layer"})
                    continue
                if aspect is not None and aspect not in archimate.ASPECTS:
                    errors.append({"id": node_id, "reason": "aspect invalide"})
                    continue

                extra_labels = [l for l in archimate.labels_for(layer, element_type) if l != "ArchiMateElement"]
                label_clause = "".join(f" SET n:`{label}`" for label in extra_labels)

                result = session.run(
                    f"""
                    MATCH (n {{id: $id}})
                    SET n:ArchiMateElement{label_clause}
                    SET n.elementType = $elementType, n.layer = $layer, n.aspect = $aspect,
                        n.description = coalesce(n.description, $description),
                        n.stereotype = coalesce(n.stereotype, $stereotype),
                        n.tags = coalesce(n.tags, $tags),
                        n.updatedAt = $now
                    RETURN n
                    """,
                    id=node_id, elementType=element_type, layer=layer, aspect=aspect,
                    description=c.get("description"), stereotype=c.get("stereotype"),
                    tags=c.get("tags"), now=now,
                )
                if not list(result):
                    errors.append({"id": node_id, "reason": "nœud introuvable"})
                    continue
                classified += 1

    except Exception as exc:
        logger.error(f"archimate_classify_nodes failed: {exc}")
        return error_response("Erreur interne lors de la classification ArchiMate.", 500)

    return func.HttpResponse(
        json.dumps({"status": "ok", "classified": classified, "errors": errors, "timestamp": now}),
        status_code=200,
        mimetype="application/json",
    )


# ============================================================================
# Module Exploration — CRUD ArchiMate (PLAN_EXPLORATION_v1.md)
#
# Routes /exploration/* (préfixe /api/graph/exploration/* côté Function, relayé par
# api/routers/exploration.py). Phase 1 : CRUD nœuds (N1-N7, T1-B-01..06). R1-R5 et
# l'audit restent en 501 pour le moment, hors health-check.
# ============================================================================

def _exploration_not_implemented(task_id: str) -> func.HttpResponse:
    return error_response(
        f"Non implémenté — voir PLAN_EXPLORATION_v1.md ({task_id})", 501,
    )


def _exploration_node_dto(node, rel_count=None) -> dict:
    """DTO nœud Exploration — propriétés brutes (dates converties via _to_json), avec
    relCount optionnel (SDD §2.3 / §6 N1/N2/N7)."""
    dto = {k: _to_json(v) for k, v in dict(node).items()}
    if rel_count is not None:
        dto["relCount"] = rel_count
    return dto


def _exploration_pagination(request: func.HttpRequest):
    """skip/limit pour les endpoints de liste Exploration (N1/N7) — skip>=0,
    1<=limit<=200, défaut limit=50 (PLAN_EXPLORATION_v1.md T1-B-01)."""
    skip = max(0, _parse_int_param(request, "skip", 0))
    limit = max(1, min(200, _parse_int_param(request, "limit", 50)))
    return skip, limit


def _exploration_client_ip(request: func.HttpRequest) -> str:
    """Adresse IP masquée (SDD §4 AuditLog.ipAddress) — derniers octets remplacés par x.x."""
    raw = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    parts = raw.split(".")
    if len(parts) == 4:
        return f"{parts[0]}.{parts[1]}.x.x"
    return raw or "unknown"


def _exploration_write_audit(tx, request, operation, entity_type, entity_id, before, after):
    """Écrit un nœud :AuditLog dans la transaction courante (SDD §4)."""
    tx.run(
        """
        CREATE (:AuditLog {
          id: randomUUID(), operation: $operation, entityType: $entityType,
          entityId: $entityId, userId: $userId, userRole: $userRole,
          payload: $payload, timestamp: toString(datetime()), ipAddress: $ipAddress
        })
        """,
        operation=operation, entityType=entity_type, entityId=entity_id,
        userId=request.headers.get("X-User-Id") or "anonymous",
        userRole=resolve_role(request),
        payload=json.dumps({"before": before, "after": after}, default=str, ensure_ascii=False),
        ipAddress=_exploration_client_ip(request),
    )


def list_exploration_nodes(req: func.HttpRequest) -> func.HttpResponse:
    """GET /exploration/nodes — N1/N1b (T1-B-01)."""
    layer = req.params.get("layer")
    element_type = req.params.get("elementType")
    aspect = req.params.get("aspect")
    name_search = req.params.get("name")
    tags_param = req.params.get("tags")
    orphans_only = (req.params.get("orphansOnly") or "").lower() == "true"
    skip, limit = _exploration_pagination(req)

    if layer is not None and layer not in archimate.LAYERS:
        return error_response("layer invalide", 400, code="VAL_LAYER")
    if element_type is not None and element_type not in archimate.ALL_ELEMENT_TYPES:
        return error_response("elementType invalide", 400, code="VAL_ELEMENT_TYPE")
    if aspect is not None and aspect not in archimate.ASPECTS:
        return error_response("aspect invalide", 400, code="VAL_ASPECT")

    tags_filter = [t.strip() for t in tags_param.split(",") if t.strip()] if tags_param else None

    conditions = []
    params = {}
    if layer is not None:
        conditions.append("n.layer = $layer")
        params["layer"] = layer
    if element_type is not None:
        conditions.append("n.elementType = $elementType")
        params["elementType"] = element_type
    if aspect is not None:
        conditions.append("n.aspect = $aspect")
        params["aspect"] = aspect
    if name_search is not None:
        conditions.append("toLower(n.name) CONTAINS toLower($nameSearch)")
        params["nameSearch"] = name_search
    if tags_filter:
        conditions.append("ALL(tag IN $tagsFilter WHERE tag IN n.tags)")
        params["tagsFilter"] = tags_filter
    if orphans_only:
        conditions.append("NOT (n)--()")

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            total = session.run(
                f"MATCH (n:ArchiMateElement) {where_clause} RETURN count(n) AS total",
                **params,
            ).single()["total"]

            records = session.run(
                f"""
                MATCH (n:ArchiMateElement) {where_clause}
                WITH n, COUNT {{ (n)--() }} AS relCount
                RETURN n, relCount
                ORDER BY n.layer ASC, n.name ASC
                SKIP $skip LIMIT $limit
                """,
                skip=skip, limit=limit, **params,
            )
            items = [_exploration_node_dto(r["n"], rel_count=r["relCount"]) for r in records]
    except Exception as e:
        logger.error(f"list_exploration_nodes — erreur Neo4j : {e}")
        return error_response("Erreur lors de la lecture du graphe", 500)

    return func.HttpResponse(
        json.dumps({"items": items, "total": total, "skip": skip, "limit": limit}),
        status_code=200, mimetype="application/json",
    )


def get_exploration_node(req: func.HttpRequest, node_id: str) -> func.HttpResponse:
    """GET /exploration/nodes/{id} — N2 (T1-B-02)."""
    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            record = session.run(
                """
                MATCH (n:ArchiMateElement {id: $id})
                OPTIONAL MATCH (n)-[rOut]->(tgt:ArchiMateElement)
                OPTIONAL MATCH (src:ArchiMateElement)-[rIn]->(n)
                RETURN n,
                  collect(DISTINCT CASE WHEN rOut IS NULL THEN NULL ELSE {
                    relId: rOut.id, relType: type(rOut), relProps: properties(rOut),
                    linkedNode: {id: tgt.id, name: tgt.name, elementType: tgt.elementType, layer: tgt.layer}
                  } END) AS outgoing,
                  collect(DISTINCT CASE WHEN rIn IS NULL THEN NULL ELSE {
                    relId: rIn.id, relType: type(rIn), relProps: properties(rIn),
                    linkedNode: {id: src.id, name: src.name, elementType: src.elementType, layer: src.layer}
                  } END) AS incoming
                """,
                id=node_id,
            ).single()
    except Exception as e:
        logger.error(f"get_exploration_node — erreur Neo4j : {e}")
        return error_response("Erreur lors de la lecture du graphe", 500)

    if record is None or record["n"] is None:
        return error_response("Nœud introuvable", 404, code="NODE_NOT_FOUND")

    def _clean(entries):
        out = []
        for entry in entries:
            if entry is None:
                continue
            entry = dict(entry)
            entry["relProps"] = {k: _to_json(v) for k, v in dict(entry["relProps"]).items()}
            out.append(entry)
        return out

    return func.HttpResponse(
        json.dumps({
            "node": _exploration_node_dto(record["n"]),
            "outgoing": _clean(record["outgoing"]),
            "incoming": _clean(record["incoming"]),
        }),
        status_code=200, mimetype="application/json",
    )


def create_exploration_node(req: func.HttpRequest) -> func.HttpResponse:
    """POST /exploration/nodes — N3 (T1-B-03)."""
    denied = require_role(req, "ARCHITECT", "ADMIN")
    if denied:
        return denied

    try:
        body = req.get_json()
    except ValueError:
        body = {}

    layer = body.get("layer")
    element_type = body.get("elementType")
    name = body.get("name")
    aspect = body.get("aspect")
    description = body.get("description")
    stereotype = body.get("stereotype")
    tags = body.get("tags")
    metadata = body.get("metadata")

    if layer not in archimate.LAYERS or not archimate.validate_element_type(layer, element_type):
        return error_response("elementType invalide pour ce layer", 400, code="VAL_ELEMENT_TYPE")
    if not isinstance(name, str) or not (1 <= len(name) <= 256):
        return error_response("name requis (1-256 caractères)", 400, code="VAL_NAME_REQUIRED")
    if aspect is not None and aspect not in archimate.ASPECTS:
        return error_response("aspect invalide", 400, code="VAL_ASPECT")
    if tags is not None and (not isinstance(tags, list) or not all(isinstance(t, str) for t in tags)):
        return error_response("tags doit être une liste de chaînes", 400, code="VAL_TAGS")
    if metadata is not None and not isinstance(metadata, str):
        metadata = json.dumps(metadata, ensure_ascii=False)

    extra_labels = [l for l in archimate.labels_for(layer, element_type) if l != "ArchiMateElement"]
    label_clause = "".join(f" SET n:`{label}`" for label in extra_labels)

    params = {
        "elementType": element_type, "layer": layer, "aspect": aspect, "name": name,
        "description": description, "stereotype": stereotype, "tags": tags, "metadata": metadata,
    }

    def _tx(tx):
        node = tx.run(
            f"""
            CREATE (n:ArchiMateElement {{
              id: randomUUID(), elementType: $elementType, layer: $layer, aspect: $aspect,
              name: $name, description: $description, stereotype: $stereotype, tags: $tags,
              metadata: $metadata, createdAt: toString(datetime()), updatedAt: toString(datetime())
            }}){label_clause}
            RETURN n
            """,
            **params,
        ).single()["n"]
        _exploration_write_audit(tx, req, "CREATE", "NODE", node["id"], None, dict(node))
        return node

    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            node = session.execute_write(_tx)
    except Exception as e:
        logger.error(f"create_exploration_node — erreur Neo4j : {e}")
        return error_response("Erreur lors de l'écriture du graphe", 500)

    return func.HttpResponse(
        json.dumps(_exploration_node_dto(node, rel_count=0)),
        status_code=201, mimetype="application/json",
    )


def update_exploration_node(req: func.HttpRequest, node_id: str) -> func.HttpResponse:
    """PATCH /exploration/nodes/{id} — N4 (T1-B-04)."""
    denied = require_role(req, "ARCHITECT", "ADMIN")
    if denied:
        return denied

    try:
        body = req.get_json()
    except ValueError:
        body = {}

    name = body.get("name")
    aspect = body.get("aspect")
    tags = body.get("tags")
    metadata = body.get("metadata")

    if "name" in body and (not isinstance(name, str) or not (1 <= len(name) <= 256)):
        return error_response("name doit faire 1-256 caractères", 400, code="VAL_NAME_REQUIRED")
    if "aspect" in body and aspect is not None and aspect not in archimate.ASPECTS:
        return error_response("aspect invalide", 400, code="VAL_ASPECT")
    if "tags" in body and tags is not None and (not isinstance(tags, list) or not all(isinstance(t, str) for t in tags)):
        return error_response("tags doit être une liste de chaînes", 400, code="VAL_TAGS")
    if "metadata" in body and metadata is not None and not isinstance(metadata, str):
        metadata = json.dumps(metadata, ensure_ascii=False)

    params = {
        "id": node_id,
        "name": body.get("name"),
        "description": body.get("description"),
        "aspect": body.get("aspect"),
        "stereotype": body.get("stereotype"),
        "tags": body.get("tags"),
        "metadata": metadata,
    }

    def _tx(tx):
        before_record = tx.run("MATCH (n:ArchiMateElement {id: $id}) RETURN n", id=node_id).single()
        if before_record is None:
            return None, None
        before = dict(before_record["n"])

        after = tx.run(
            """
            MATCH (n:ArchiMateElement {id: $id})
            SET n.name = COALESCE($name, n.name),
                n.description = COALESCE($description, n.description),
                n.aspect = COALESCE($aspect, n.aspect),
                n.stereotype = COALESCE($stereotype, n.stereotype),
                n.tags = COALESCE($tags, n.tags),
                n.metadata = COALESCE($metadata, n.metadata),
                n.updatedAt = toString(datetime())
            RETURN n
            """,
            **params,
        ).single()["n"]

        _exploration_write_audit(tx, req, "UPDATE", "NODE", node_id, before, dict(after))
        return before, after

    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            before, after = session.execute_write(_tx)
    except Exception as e:
        logger.error(f"update_exploration_node — erreur Neo4j : {e}")
        return error_response("Erreur lors de l'écriture du graphe", 500)

    if after is None:
        return error_response("Nœud introuvable", 404, code="NODE_NOT_FOUND")

    return func.HttpResponse(
        json.dumps(_exploration_node_dto(after)),
        status_code=200, mimetype="application/json",
    )


def delete_exploration_node(req: func.HttpRequest, node_id: str) -> func.HttpResponse:
    """DELETE /exploration/nodes/{id} — N5 (safe) / N6 (cascade, ?cascade=true, ADMIN)
    (T1-B-05 / T3-B-01)."""
    cascade = (req.params.get("cascade") or "").lower() == "true"

    if cascade:
        denied = require_role(req, "ADMIN")
        if denied:
            return denied
    else:
        denied = require_role(req, "ARCHITECT", "ADMIN")
        if denied:
            return denied

    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            if cascade:
                def _tx(tx):
                    check = tx.run(
                        "MATCH (n:ArchiMateElement {id: $id}) "
                        "OPTIONAL MATCH (n)-[r]-() "
                        "RETURN n, count(r) AS relCount",
                        id=node_id,
                    ).single()
                    if check is None or check["n"] is None:
                        return None, None

                    before = dict(check["n"])
                    rel_count = check["relCount"]

                    tx.run(
                        "MATCH (n:ArchiMateElement {id: $id}) "
                        "OPTIONAL MATCH (n)-[r]-() "
                        "DELETE r, n",
                        id=node_id,
                    )

                    audit_payload = dict(before)
                    audit_payload["relCount"] = rel_count
                    _exploration_write_audit(
                        tx, req, "DELETE_CASCADE", "NODE", node_id, before, audit_payload,
                    )
                    return before, rel_count

                before, rel_count = session.execute_write(_tx)
                if before is None:
                    return error_response("Nœud introuvable", 404, code="NODE_NOT_FOUND")

                return func.HttpResponse(
                    json.dumps({"deleted": True, "relCount": rel_count}),
                    status_code=200, mimetype="application/json",
                )

            check = session.run(
                "MATCH (n:ArchiMateElement {id: $id}) RETURN n, COUNT { (n)--() } AS relCount",
                id=node_id,
            ).single()

            if check is None:
                return error_response("Nœud introuvable", 404, code="NODE_NOT_FOUND")

            rel_count = check["relCount"]
            if rel_count > 0:
                return error_response(
                    "Le nœud a des relations — suppression refusée", 409,
                    code="NODE_HAS_RELATIONS", relCount=rel_count,
                )

            before = dict(check["n"])

            def _tx(tx):
                tx.run("MATCH (n:ArchiMateElement {id: $id}) DELETE n", id=node_id)
                _exploration_write_audit(tx, req, "DELETE", "NODE", node_id, before, None)

            session.execute_write(_tx)
    except Exception as e:
        logger.error(f"delete_exploration_node — erreur Neo4j : {e}")
        return error_response("Erreur lors de l'écriture du graphe", 500)

    return func.HttpResponse(
        json.dumps({"deleted": True}),
        status_code=200, mimetype="application/json",
    )


def list_exploration_orphans(req: func.HttpRequest) -> func.HttpResponse:
    """GET /exploration/orphans — N7 (T1-B-06)."""
    denied = require_role(req, "ARCHITECT", "ADMIN")
    if denied:
        return denied

    skip, limit = _exploration_pagination(req)

    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            total = session.run(
                "MATCH (n:ArchiMateElement) WHERE NOT (n)--() RETURN count(n) AS total"
            ).single()["total"]

            records = session.run(
                """
                MATCH (n:ArchiMateElement) WHERE NOT (n)--()
                RETURN n
                ORDER BY n.layer ASC, n.createdAt DESC
                SKIP $skip LIMIT $limit
                """,
                skip=skip, limit=limit,
            )
            items = [_exploration_node_dto(r["n"], rel_count=0) for r in records]
    except Exception as e:
        logger.error(f"list_exploration_orphans — erreur Neo4j : {e}")
        return error_response("Erreur lors de la lecture du graphe", 500)

    return func.HttpResponse(
        json.dumps({"items": items, "total": total, "skip": skip, "limit": limit}),
        status_code=200, mimetype="application/json",
    )


def bulk_tag_exploration_nodes(req: func.HttpRequest) -> func.HttpResponse:
    """POST /exploration/nodes/bulk-tag — N8 (T3-B-02)."""
    denied = require_role(req, "ARCHITECT", "ADMIN")
    if denied:
        return denied

    try:
        body = req.get_json()
    except ValueError:
        body = {}

    node_ids = body.get("nodeIds")
    action = body.get("action")
    tag = body.get("tag")

    if not isinstance(node_ids, list) or not node_ids or not all(isinstance(i, str) for i in node_ids):
        return error_response("nodeIds doit être une liste non vide d'identifiants", 400, code="VAL_BULK_TAG_NODE_IDS")
    if action not in ("add", "remove"):
        return error_response("action doit être 'add' ou 'remove'", 400, code="VAL_BULK_TAG_ACTION")
    if not isinstance(tag, str) or not (1 <= len(tag) <= 64):
        return error_response("tag doit être une chaîne non vide (1-64 caractères)", 400, code="VAL_BULK_TAG_TAG")

    def _tx(tx):
        updated = 0
        for node_id in node_ids:
            record = tx.run("MATCH (n:ArchiMateElement {id: $id}) RETURN n", id=node_id).single()
            if record is None:
                continue

            before = dict(record["n"])
            tags = list(before.get("tags") or [])

            if action == "add":
                if tag not in tags:
                    tags.append(tag)
            else:
                if tag in tags:
                    tags = [t for t in tags if t != tag]

            after_record = tx.run(
                """
                MATCH (n:ArchiMateElement {id: $id})
                SET n.tags = $tags, n.updatedAt = toString(datetime())
                RETURN n
                """,
                id=node_id, tags=tags,
            ).single()["n"]

            _exploration_write_audit(tx, req, "UPDATE", "NODE", node_id, before, dict(after_record))
            updated += 1
        return updated

    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            updated = session.execute_write(_tx)
    except Exception as e:
        logger.error(f"bulk_tag_exploration_nodes — erreur Neo4j : {e}")
        return error_response("Erreur lors de l'écriture du graphe", 500)

    return func.HttpResponse(
        json.dumps({"updated": updated, "action": action, "tag": tag}),
        status_code=200, mimetype="application/json",
    )


def list_exploration_relations(req: func.HttpRequest) -> func.HttpResponse:
    """GET /exploration/relations — R1 (T2-B-01)."""
    relation_type = req.params.get("relationType")
    source_id = req.params.get("sourceId")
    target_id = req.params.get("targetId")
    source_layer = req.params.get("sourceLayer")
    target_layer = req.params.get("targetLayer")
    skip, limit = _exploration_pagination(req)

    if relation_type is not None and relation_type not in archimate.RELATION_TYPES:
        return error_response("relationType invalide", 400, code="VAL_RELATION_TYPE")
    if source_layer is not None and source_layer not in archimate.LAYERS:
        return error_response("sourceLayer invalide", 400, code="VAL_LAYER")
    if target_layer is not None and target_layer not in archimate.LAYERS:
        return error_response("targetLayer invalide", 400, code="VAL_LAYER")

    conditions = []
    params = {}
    if relation_type is not None:
        conditions.append("type(r) = $relationType")
        params["relationType"] = relation_type
    if source_id is not None:
        conditions.append("src.id = $sourceId")
        params["sourceId"] = source_id
    if target_id is not None:
        conditions.append("tgt.id = $targetId")
        params["targetId"] = target_id
    if source_layer is not None:
        conditions.append("src.layer = $sourceLayer")
        params["sourceLayer"] = source_layer
    if target_layer is not None:
        conditions.append("tgt.layer = $targetLayer")
        params["targetLayer"] = target_layer

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            total = session.run(
                f"""
                MATCH (src:ArchiMateElement)-[r]->(tgt:ArchiMateElement) {where_clause}
                RETURN count(r) AS total
                """,
                **params,
            ).single()["total"]

            records = session.run(
                f"""
                MATCH (src:ArchiMateElement)-[r]->(tgt:ArchiMateElement) {where_clause}
                RETURN properties(r) AS rel, type(r) AS relationType,
                       src {{.id, .name, .elementType, .layer}} AS source,
                       tgt {{.id, .name, .elementType, .layer}} AS target
                ORDER BY r.createdAt DESC
                SKIP $skip LIMIT $limit
                """,
                skip=skip, limit=limit, **params,
            )
            items = []
            for r in records:
                item = {k: _to_json(v) for k, v in dict(r["rel"]).items()}
                item["relationType"] = r["relationType"]
                item["source"] = dict(r["source"])
                item["target"] = dict(r["target"])
                items.append(item)
    except Exception as e:
        logger.error(f"list_exploration_relations — erreur Neo4j : {e}")
        return error_response("Erreur lors de la lecture du graphe", 500)

    return func.HttpResponse(
        json.dumps({"items": items, "total": total, "skip": skip, "limit": limit}),
        status_code=200, mimetype="application/json",
    )


def get_exploration_relation(req: func.HttpRequest, rel_id: str) -> func.HttpResponse:
    """GET /exploration/relations/{id} — R2 (T2-B-02)."""
    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            record = session.run(
                """
                MATCH (src:ArchiMateElement)-[r {id: $id}]->(tgt:ArchiMateElement)
                RETURN properties(r) AS rel, type(r) AS relationType,
                       src {.id, .name, .elementType, .layer, .aspect} AS source,
                       tgt {.id, .name, .elementType, .layer, .aspect} AS target
                """,
                id=rel_id,
            ).single()
    except Exception as e:
        logger.error(f"get_exploration_relation — erreur Neo4j : {e}")
        return error_response("Erreur lors de la lecture du graphe", 500)

    if record is None:
        return error_response("Relation introuvable", 404, code="RELATION_NOT_FOUND")

    item = {k: _to_json(v) for k, v in dict(record["rel"]).items()}
    item["relationType"] = record["relationType"]
    item["source"] = dict(record["source"])
    item["target"] = dict(record["target"])

    return func.HttpResponse(
        json.dumps(item),
        status_code=200, mimetype="application/json",
    )


def _exploration_weight_valid(weight) -> bool:
    return isinstance(weight, (int, float)) and not isinstance(weight, bool) and 0.0 <= weight <= 1.0


def create_exploration_relation(req: func.HttpRequest) -> func.HttpResponse:
    """POST /exploration/relations — R3 + R-CHECK + VAL-03/05/06/07/08 (T2-B-03)."""
    denied = require_role(req, "ARCHITECT", "ADMIN")
    if denied:
        return denied

    try:
        body = req.get_json()
    except ValueError:
        body = {}

    relation_type = body.get("relationType")
    source_id = body.get("sourceId")
    target_id = body.get("targetId")
    access_type = body.get("accessType")
    weight = body.get("weight")
    name = body.get("name")
    description = body.get("description")
    confirm_warnings = body.get("confirmWarnings") is True

    if relation_type not in archimate.RELATION_TYPES:
        return error_response("relationType invalide", 400, code="VAL_RELATION_TYPE")

    if relation_type == "Access":
        if access_type is None:
            return error_response("accessType requis pour une relation Access", 400, code="VAL_ACCESS_TYPE")
        if access_type not in archimate.ACCESS_TYPES:
            return error_response("accessType invalide", 400, code="VAL_ACCESS_TYPE_VALUE")
    else:
        access_type = None

    if weight is not None and not _exploration_weight_valid(weight):
        return error_response("weight doit être un nombre entre 0.0 et 1.0", 400, code="VAL_WEIGHT_RANGE")

    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            endpoints = session.run(
                """
                OPTIONAL MATCH (src:ArchiMateElement {id: $sourceId})
                OPTIONAL MATCH (tgt:ArchiMateElement {id: $targetId})
                RETURN src, tgt
                """,
                sourceId=source_id, targetId=target_id,
            ).single()

            src, tgt = endpoints["src"], endpoints["tgt"]
            if src is None or tgt is None:
                return error_response("Nœud source ou cible introuvable", 404, code="NODE_NOT_FOUND")

            warnings = []

            duplicate = session.run(
                """
                MATCH (src {id: $sourceId})-[r]->(tgt {id: $targetId})
                WHERE type(r) = $relationType
                RETURN r.id AS existingRelId LIMIT 1
                """,
                sourceId=source_id, targetId=target_id, relationType=relation_type,
            ).single()
            if duplicate is not None:
                warnings.append({
                    "code": "VAL_DUPLICATE_REL", "level": "WARN",
                    "message": f"Une relation {relation_type} existe déjà entre ces deux éléments.",
                    "existingRelId": duplicate["existingRelId"],
                })

            if relation_type == "Assignment" and src["aspect"] != "ActiveStructure":
                warnings.append({
                    "code": "VAL_ASSIGNMENT_ASPECT", "level": "WARN",
                    "message": "Une relation Assignment part généralement d'un élément ActiveStructure.",
                })

            if relation_type == "Realization":
                src_rank = archimate.realization_layer_rank(src["layer"])
                tgt_rank = archimate.realization_layer_rank(tgt["layer"])
                if src_rank is not None and tgt_rank is not None and tgt_rank < src_rank:
                    warnings.append({
                        "code": "VAL_REALIZATION_LAYER", "level": "WARN",
                        "message": "L'élément cible appartient à une couche inférieure à la couche source.",
                    })

            if relation_type in ("Composition", "Aggregation") and src["layer"] != tgt["layer"]:
                warnings.append({
                    "code": "VAL_STRUCTURAL_CROSS_LAYER", "level": "INFO",
                    "message": "Relation structurelle entre deux éléments de couches différentes.",
                })

            if warnings and not confirm_warnings:
                return error_response(
                    "Avertissements ArchiMate — confirmation requise", 422,
                    code="ARCHIMATE_WARN", warnings=warnings,
                )

            def _tx(tx):
                rel = tx.run(
                    f"""
                    MATCH (src:ArchiMateElement {{id: $sourceId}}), (tgt:ArchiMateElement {{id: $targetId}})
                    CREATE (src)-[r:`{relation_type}`]->(tgt)
                    SET r.id = randomUUID(),
                        r.name = $name,
                        r.description = $description,
                        r.accessType = $accessType,
                        r.weight = $weight,
                        r.createdAt = toString(datetime()),
                        r.updatedAt = toString(datetime())
                    RETURN properties(r) AS rel
                    """,
                    sourceId=source_id, targetId=target_id, name=name,
                    description=description, accessType=access_type, weight=weight,
                ).single()["rel"]
                after = {k: _to_json(v) for k, v in dict(rel).items()}
                after["relationType"] = relation_type
                audit_after = dict(after)
                if warnings:
                    audit_after["warnings"] = warnings
                _exploration_write_audit(tx, req, "CREATE", "RELATION", after["id"], None, audit_after)
                return after

            after = session.execute_write(_tx)
    except Exception as e:
        logger.error(f"create_exploration_relation — erreur Neo4j : {e}")
        return error_response("Erreur lors de l'écriture du graphe", 500)

    return func.HttpResponse(
        json.dumps({
            **after,
            "source": {"id": src["id"], "name": src["name"]},
            "target": {"id": tgt["id"], "name": tgt["name"]},
        }),
        status_code=201, mimetype="application/json",
    )


def update_exploration_relation(req: func.HttpRequest, rel_id: str) -> func.HttpResponse:
    """PATCH /exploration/relations/{id} — R4 (T2-B-04)."""
    denied = require_role(req, "ARCHITECT", "ADMIN")
    if denied:
        return denied

    try:
        body = req.get_json()
    except ValueError:
        body = {}

    if "weight" in body and body["weight"] is not None and not _exploration_weight_valid(body["weight"]):
        return error_response("weight doit être un nombre entre 0.0 et 1.0", 400, code="VAL_WEIGHT_RANGE")

    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            current = session.run(
                "MATCH ()-[r {id: $id}]->() RETURN properties(r) AS rel, type(r) AS relationType",
                id=rel_id,
            ).single()
            if current is None:
                return error_response("Relation introuvable", 404, code="RELATION_NOT_FOUND")

            relation_type = current["relationType"]
            before = {k: _to_json(v) for k, v in dict(current["rel"]).items()}
            before["relationType"] = relation_type

            if relation_type == "Access":
                new_access_type = body["accessType"] if "accessType" in body else before.get("accessType")
                if new_access_type is None:
                    return error_response("accessType requis pour une relation Access", 400, code="VAL_ACCESS_TYPE")
                if new_access_type not in archimate.ACCESS_TYPES:
                    return error_response("accessType invalide", 400, code="VAL_ACCESS_TYPE_VALUE")

            def _tx(tx):
                rel = tx.run(
                    """
                    MATCH ()-[r {id: $id}]->()
                    SET r.name = COALESCE($name, r.name),
                        r.description = COALESCE($description, r.description),
                        r.weight = COALESCE($weight, r.weight),
                        r.accessType = COALESCE($accessType, r.accessType),
                        r.updatedAt = toString(datetime())
                    RETURN properties(r) AS rel
                    """,
                    id=rel_id, name=body.get("name"), description=body.get("description"),
                    weight=body.get("weight"), accessType=body.get("accessType"),
                ).single()["rel"]
                after = {k: _to_json(v) for k, v in dict(rel).items()}
                after["relationType"] = relation_type
                _exploration_write_audit(tx, req, "UPDATE", "RELATION", rel_id, before, after)
                return after

            after = session.execute_write(_tx)
    except Exception as e:
        logger.error(f"update_exploration_relation — erreur Neo4j : {e}")
        return error_response("Erreur lors de l'écriture du graphe", 500)

    return func.HttpResponse(
        json.dumps(after),
        status_code=200, mimetype="application/json",
    )


def delete_exploration_relation(req: func.HttpRequest, rel_id: str) -> func.HttpResponse:
    """DELETE /exploration/relations/{id} — R5 (T2-B-05)."""
    denied = require_role(req, "ARCHITECT", "ADMIN")
    if denied:
        return denied

    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            current = session.run(
                "MATCH ()-[r {id: $id}]->() RETURN properties(r) AS rel, type(r) AS relationType",
                id=rel_id,
            ).single()
            if current is None:
                return error_response("Relation introuvable", 404, code="RELATION_NOT_FOUND")

            before = {k: _to_json(v) for k, v in dict(current["rel"]).items()}
            before["relationType"] = current["relationType"]

            def _tx(tx):
                tx.run("MATCH ()-[r {id: $id}]->() DELETE r", id=rel_id)
                _exploration_write_audit(tx, req, "DELETE", "RELATION", rel_id, before, None)

            session.execute_write(_tx)
    except Exception as e:
        logger.error(f"delete_exploration_relation — erreur Neo4j : {e}")
        return error_response("Erreur lors de l'écriture du graphe", 500)

    return func.HttpResponse(
        json.dumps({"deleted": True}),
        status_code=200, mimetype="application/json",
    )


def list_exploration_audit(req: func.HttpRequest) -> func.HttpResponse:
    """GET /exploration/audit — consultation AuditLog, ADMIN uniquement (T4-B-02).
    Filtres : entityId, entityType, operation, userId, since (ISO 8601),
    pagination skip/limit. Tri par timestamp DESC."""
    denied = require_role(req, "ADMIN")
    if denied:
        return denied

    entity_id = req.params.get("entityId")
    entity_type = req.params.get("entityType")
    operation = req.params.get("operation")
    user_id = req.params.get("userId")
    since = req.params.get("since")

    if operation is not None and operation not in ("CREATE", "UPDATE", "DELETE", "DELETE_CASCADE"):
        return error_response("operation invalide", 400, code="VAL_AUDIT_OPERATION")
    if entity_type is not None and entity_type not in ("NODE", "RELATION"):
        return error_response("entityType invalide", 400, code="VAL_AUDIT_ENTITY_TYPE")

    skip, limit = _exploration_pagination(req)

    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            total = session.run(
                """
                MATCH (log:AuditLog)
                WHERE ($entityId IS NULL OR log.entityId = $entityId)
                  AND ($entityType IS NULL OR log.entityType = $entityType)
                  AND ($operation IS NULL OR log.operation = $operation)
                  AND ($userId IS NULL OR log.userId = $userId)
                  AND ($since IS NULL OR log.timestamp >= $since)
                RETURN count(log) AS total
                """,
                entityId=entity_id, entityType=entity_type, operation=operation,
                userId=user_id, since=since,
            ).single()["total"]

            records = session.run(
                """
                MATCH (log:AuditLog)
                WHERE ($entityId IS NULL OR log.entityId = $entityId)
                  AND ($entityType IS NULL OR log.entityType = $entityType)
                  AND ($operation IS NULL OR log.operation = $operation)
                  AND ($userId IS NULL OR log.userId = $userId)
                  AND ($since IS NULL OR log.timestamp >= $since)
                RETURN log
                ORDER BY log.timestamp DESC
                SKIP $skip LIMIT $limit
                """,
                entityId=entity_id, entityType=entity_type, operation=operation,
                userId=user_id, since=since, skip=skip, limit=limit,
            )

            items = []
            for r in records:
                entry = {k: _to_json(v) for k, v in dict(r["log"]).items()}
                try:
                    entry["payload"] = json.loads(entry["payload"])
                except (TypeError, ValueError, KeyError):
                    pass
                items.append(entry)
    except Exception as e:
        logger.error(f"list_exploration_audit — erreur Neo4j : {e}")
        return error_response("Erreur lors de la lecture du graphe", 500)

    return func.HttpResponse(
        json.dumps({"items": items, "total": total, "skip": skip, "limit": limit}),
        status_code=200, mimetype="application/json",
    )


def get_exploration_health() -> func.HttpResponse:
    """GET /exploration/health — sonde triviale (toujours up si le code est atteint ;
    réutilise get_neo4j_driver pour vérifier la connectivité comme get_health)."""
    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            session.run("RETURN 1").consume()
        neo4j_status = "up"
    except Exception as e:
        logger.error(f"get_exploration_health — Neo4j injoignable : {e}")
        neo4j_status = "down"

    if neo4j_status == "up":
        return func.HttpResponse(
            json.dumps({"status": "ok", "neo4j": neo4j_status, "version": APP_VERSION}),
            status_code=200, mimetype="application/json",
        )
    return error_response("Dépendance indisponible", 503, neo4j=neo4j_status)


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
        if parts == ["admin", "archimate-classify"]:
            return archimate_classify_nodes(req)

    if method == "DELETE":
        if parts == ["admin", "functional-entities"]:
            return clear_functional_entities(req)
        if parts == ["admin", "reset"]:
            return reset_graph(req)

    if method == "PATCH":
        if len(parts) == 3 and parts[0] == "nodes" and parts[2] == "qualification":
            return patch_node_qualification(req, parts[1])

    # ------------------------------------------------------------------
    # Module Exploration — /exploration/* (PLAN_EXPLORATION_v1.md)
    # ------------------------------------------------------------------
    if parts and parts[0] == "exploration":
        sub = parts[1:]

        if method == "GET":
            if sub == ["health"]:
                return get_exploration_health()
            if sub == ["nodes"]:
                return list_exploration_nodes(req)
            if len(sub) == 2 and sub[0] == "nodes":
                return get_exploration_node(req, sub[1])
            if sub == ["orphans"]:
                return list_exploration_orphans(req)
            if sub == ["relations"]:
                return list_exploration_relations(req)
            if len(sub) == 2 and sub[0] == "relations":
                return get_exploration_relation(req, sub[1])
            if sub == ["audit"]:
                return list_exploration_audit(req)

        if method == "POST":
            if sub == ["nodes"]:
                return create_exploration_node(req)
            if sub == ["nodes", "bulk-tag"]:
                return bulk_tag_exploration_nodes(req)
            if sub == ["relations"]:
                return create_exploration_relation(req)

        if method == "PATCH":
            if len(sub) == 2 and sub[0] == "nodes":
                return update_exploration_node(req, sub[1])
            if len(sub) == 2 and sub[0] == "relations":
                return update_exploration_relation(req, sub[1])

        if method == "DELETE":
            if len(sub) == 2 and sub[0] == "nodes":
                return delete_exploration_node(req, sub[1])
            if len(sub) == 2 and sub[0] == "relations":
                return delete_exploration_relation(req, sub[1])

        return error_response("Not found", 404)

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
