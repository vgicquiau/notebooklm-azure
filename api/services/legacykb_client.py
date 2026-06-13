"""Legacy KB — accès en lecture au graphe GraphRAG brut importé dans `neo4j-legacykb`.

Instance Neo4j séparée (cf. docs/extract/mapping-graphrag-to-adgm.md) : héberge le dump
complet `repartition_cleaned_export.graphml` (5812 nœuds :Entity/:Community, 19368
relations), dont seule une partie est fusionnée dans ADG-M (cf. ingest/graphrag_to_adgm.py).

Module de service pur (sans dépendance FastAPI), utilisé par :
- `api/routers/legacykb.py` (endpoints HTTP pour l'exploration frontend)
- `api/services/graph_tools.py` (tools function-calling pour le Chat)

Variables d'environnement :
    NEO4J_LEGACYKB_URI       (défaut bolt://neo4j-legacykb-vgi.francecentral.azurecontainer.io:7687)
    NEO4J_LEGACYKB_PASSWORD  (pas de défaut)
"""

import logging
import os

from neo4j import GraphDatabase

logger = logging.getLogger(__name__)

_URI = os.environ.get(
    "NEO4J_LEGACYKB_URI",
    "bolt://neo4j-legacykb-vgi.francecentral.azurecontainer.io:7687",
)
_driver = None


class LegacyKbError(Exception):
    """Erreur d'accès à la base neo4j-legacykb (config manquante ou instance injoignable)."""


class LegacyKbNotFound(Exception):
    """Le nœud demandé n'existe pas dans neo4j-legacykb."""


def _get_driver():
    global _driver
    if _driver is None:
        password = os.environ.get("NEO4J_LEGACYKB_PASSWORD")
        if not password:
            raise LegacyKbError("NEO4J_LEGACYKB_PASSWORD non configuré.")
        _driver = GraphDatabase.driver(_URI, auth=("neo4j", password))
    return _driver


def _run(query: str, **params):
    try:
        with _get_driver().session() as session:
            return list(session.run(query, **params))
    except (LegacyKbError, LegacyKbNotFound):
        raise
    except Exception as e:
        logger.exception("neo4j-legacykb injoignable")
        raise LegacyKbError("Instance Neo4j legacy-kb injoignable.") from e


# ── Identifiants ────────────────────────────────────────────────────────────
# :Entity n'a pas de propriété `id` (cf. ingest/graphrag_to_adgm.py) : on
# identifie un nœud par (type, name) — :Community a une propriété `id` native.

def entity_id(entity_type: str, name: str) -> str:
    return f"e|{entity_type}|{name}"


def community_id(community_id_: str) -> str:
    return f"c|{community_id_}"


def parse_node_id(node_id: str) -> tuple[str, ...]:
    parts = node_id.split("|")
    if len(parts) == 3 and parts[0] == "e":
        return ("e", parts[1], parts[2])
    if len(parts) == 2 and parts[0] == "c":
        return ("c", parts[1])
    raise ValueError(f"Identifiant de nœud invalide : {node_id!r}")


def _node_summary(node) -> dict:
    """Représentation compacte d'un nœud Neo4j (:Entity ou :Community) pour le frontend."""
    labels = set(node.labels)
    if "Entity" in labels:
        return {
            "id": entity_id(node["type"], node["name"]),
            "kind": "entity",
            "type": node["type"],
            "nom": node["name"],
        }
    if "Community" in labels:
        return {
            "id": community_id(node["id"]),
            "kind": "community",
            "level": node["level"],
            "nom": node["title"],
        }
    return {"id": None, "kind": "unknown", "nom": "?"}


# ── Fonctions de service ──────────────────────────────────────────────────────

def get_stats() -> dict:
    """Comptage des nœuds par type d':Entity et niveau de :Community."""
    entity_counts = {
        r["type"]: r["n"]
        for r in _run("MATCH (e:Entity) RETURN e.type AS type, count(*) AS n")
    }
    community_counts = {
        r["level"]: r["n"]
        for r in _run("MATCH (c:Community) RETURN c.level AS level, count(*) AS n")
    }
    return {"entities": entity_counts, "communities": community_counts}


def search(q: str, limit: int = 25) -> dict:
    """Recherche (sous-chaîne, insensible à la casse) sur le nom des :Entity et le titre des :Community."""
    q = q.strip()
    if not q:
        return {"items": []}

    items = []
    for r in _run(
        """
        MATCH (e:Entity)
        WHERE toLower(e.name) CONTAINS toLower($q)
        RETURN e.type AS type, e.name AS name, e.file_location AS file_location
        ORDER BY e.type, e.name
        LIMIT $limit
        """,
        q=q, limit=limit,
    ):
        items.append({
            "id": entity_id(r["type"], r["name"]),
            "kind": "entity",
            "type": r["type"],
            "nom": r["name"],
            "source": r["file_location"],
        })

    for r in _run(
        """
        MATCH (c:Community)
        WHERE toLower(c.title) CONTAINS toLower($q)
        RETURN c.id AS id, c.level AS level, c.title AS title
        ORDER BY c.level, c.title
        LIMIT $limit
        """,
        q=q, limit=limit,
    ):
        items.append({
            "id": community_id(r["id"]),
            "kind": "community",
            "level": r["level"],
            "nom": r["title"],
        })

    return {"items": items[:limit]}


def get_node_neighbors(node_id: str, limit: int = 60) -> dict:
    """Voisinage direct (toutes relations) d'un nœud — pour exploration au clic dans le graphe."""
    kind, *rest = parse_node_id(node_id)

    if kind == "e":
        entity_type, name = rest
        match_clause = "MATCH (n:Entity {type: $type, name: $name})"
        params = {"type": entity_type, "name": name}
    else:
        community_id_, = rest
        match_clause = "MATCH (n:Community {id: $id})"
        params = {"id": community_id_}

    params["limit"] = limit
    rows = _run(
        f"""
        {match_clause}
        CALL {{
            WITH n
            MATCH (n)-[r]->(m) RETURN type(r) AS relType, 'out' AS dir, m AS m
            UNION
            WITH n
            MATCH (n)<-[r]-(m) RETURN type(r) AS relType, 'in' AS dir, m AS m
        }}
        RETURN relType, dir, m
        LIMIT $limit
        """,
        **params,
    )

    center_rows = _run(f"{match_clause} RETURN n", **{k: v for k, v in params.items() if k != "limit"})
    if not center_rows:
        raise LegacyKbNotFound("Nœud introuvable.")

    neighbors = {}
    edges = []
    for r in rows:
        m_summary = _node_summary(r["m"])
        if m_summary["id"] is None:
            continue
        neighbors[m_summary["id"]] = m_summary
        if r["dir"] == "out":
            edges.append({"from": node_id, "to": m_summary["id"], "type": r["relType"]})
        else:
            edges.append({"from": m_summary["id"], "to": node_id, "type": r["relType"]})

    return {
        "center": _node_summary(center_rows[0]["n"]),
        "neighbors": list(neighbors.values()),
        "edges": edges,
    }


def get_node(node_id: str) -> dict:
    """Détail complet d'un nœud (:Entity ou :Community)."""
    kind, *rest = parse_node_id(node_id)

    if kind == "e":
        entity_type, name = rest
        rows = _run(
            """
            MATCH (e:Entity {type: $type, name: $name})
            RETURN e
            """,
            type=entity_type, name=name,
        )
        if not rows:
            raise LegacyKbNotFound("Entité introuvable.")
        e = rows[0]["e"]
        return {
            "id": node_id,
            "kind": "entity",
            "type": e["type"],
            "nom": e["name"],
            "source": e.get("file_location"),
            "functional_description": e.get("functional_description"),
            "technical_description": e.get("technical_description"),
        }

    community_id_, = rest
    rows = _run(
        """
        MATCH (c:Community {id: $id})
        RETURN c
        """,
        id=community_id_,
    )
    if not rows:
        raise LegacyKbNotFound("Communauté introuvable.")
    c = rows[0]["c"]
    return {
        "id": node_id,
        "kind": "community",
        "level": c["level"],
        "nom": c["title"],
        "functional_summary": c.get("functional_summary"),
        "technical_summary": c.get("technical_summary"),
    }
