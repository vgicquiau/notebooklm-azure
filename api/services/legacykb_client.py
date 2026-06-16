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

Note : ces variables sont lues à la première connexion (dans `_get_driver`), pas à
l'import du module — `load_dotenv()` dans `api/main.py` s'exécute après les imports.
"""

import logging
import os

from neo4j import GraphDatabase

logger = logging.getLogger(__name__)

_driver = None


class LegacyKbError(Exception):
    """Erreur d'accès à la base neo4j-legacykb (config manquante ou instance injoignable)."""


class LegacyKbNotFound(Exception):
    """Le nœud demandé n'existe pas dans neo4j-legacykb."""


def _get_driver():
    global _driver
    if _driver is None:
        uri = os.environ.get(
            "NEO4J_LEGACYKB_URI",
            "bolt://neo4j-legacykb-vgi.francecentral.azurecontainer.io:7687",
        )
        password = os.environ.get("NEO4J_LEGACYKB_PASSWORD")
        if not password:
            raise LegacyKbError("NEO4J_LEGACYKB_PASSWORD non configuré.")
        _driver = GraphDatabase.driver(uri, auth=("neo4j", password))
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

def get_health() -> dict:
    """Vérifie que l'instance neo4j-legacykb est joignable (pour le voyant de connexion)."""
    _run("RETURN 1")
    return {"status": "ok"}


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


def search(q: str, limit: int = 25, entity_types: list[str] | None = None, search_descriptions: bool = False) -> dict:
    """Recherche sur le nom des :Entity et le titre des :Community (insensible à la casse).

    `entity_types` filtre les :Entity sur leur propriété `type` (et exclut les
    :Community des résultats, puisque le filtre ne s'applique qu'aux entités).
    `search_descriptions` étend la recherche aux descriptions/résumés
    fonctionnels et techniques, pas seulement au nom/titre.
    """
    q = q.strip()
    if not q:
        return {"items": []}

    items = []
    for r in _run(
        """
        MATCH (e:Entity)
        WHERE ($types IS NULL OR e.type IN $types)
          AND (
            toLower(e.name) CONTAINS toLower($q)
            OR ($desc AND toLower(coalesce(e.functional_description, '')) CONTAINS toLower($q))
            OR ($desc AND toLower(coalesce(e.technical_description, '')) CONTAINS toLower($q))
          )
        RETURN e.type AS type, e.name AS name, e.file_location AS file_location
        ORDER BY e.type, e.name
        LIMIT $limit
        """,
        q=q, limit=limit, types=entity_types, desc=search_descriptions,
    ):
        items.append({
            "id": entity_id(r["type"], r["name"]),
            "kind": "entity",
            "type": r["type"],
            "nom": r["name"],
            "source": r["file_location"],
        })

    if not entity_types:
        for r in _run(
            """
            MATCH (c:Community)
            WHERE toLower(c.title) CONTAINS toLower($q)
              OR ($desc AND toLower(coalesce(c.functional_summary, '')) CONTAINS toLower($q))
              OR ($desc AND toLower(coalesce(c.technical_summary, '')) CONTAINS toLower($q))
            RETURN c.id AS id, c.level AS level, c.title AS title
            ORDER BY c.level, c.title
            LIMIT $limit
            """,
            q=q, limit=limit, desc=search_descriptions,
        ):
            items.append({
                "id": community_id(r["id"]),
                "kind": "community",
                "level": r["level"],
                "nom": r["title"],
            })

    return {"items": items[:limit]}


def list_domains() -> dict:
    """Domaines fonctionnels (:Community niveau 2) avec leur nombre de sous-domaines rattachés."""
    rows = _run(
        """
        MATCH (c2:Community {level: 2})
        OPTIONAL MATCH (c1:Community)-[:SUBCOMMUNITY_OF]->(c2)
        RETURN c2.id AS id, c2.title AS title, count(c1) AS subdomains
        ORDER BY c2.title
        """
    )
    return {
        "items": [
            {
                "id": community_id(r["id"]),
                "kind": "community",
                "level": 2,
                "nom": r["title"],
                "subdomains": r["subdomains"],
            }
            for r in rows
        ]
    }


def get_hierarchy() -> dict:
    """Hiérarchie complète L2→L1 avec nombre d'entités par sous-domaine L1."""
    tree_rows = _run(
        """
        MATCH (c2:Community {level: 2})
        OPTIONAL MATCH (c1:Community)-[:SUBCOMMUNITY_OF]->(c2)
        WITH c2, collect(c1) AS c1s
        RETURN c2.id AS id, c2.title AS title,
               [c1 IN c1s WHERE c1 IS NOT NULL | {id: c1.id, title: c1.title}] AS subs
        ORDER BY c2.title
        """
    )
    count_rows = _run(
        """
        MATCH (c1:Community {level: 1})
        OPTIONAL MATCH (e:Entity)-[:IN_COMMUNITY]->(c1)
        RETURN c1.id AS c_id, count(e) AS n
        """
    )
    entity_counts = {r["c_id"]: r["n"] for r in count_rows}

    items = []
    for r in tree_rows:
        subs = sorted(
            [
                {
                    "id": community_id(s["id"]),
                    "kind": "community",
                    "level": 1,
                    "nom": s["title"],
                    "entity_count": entity_counts.get(s["id"], 0),
                }
                for s in (r["subs"] or [])
            ],
            key=lambda x: x["nom"],
        )
        items.append({
            "id": community_id(r["id"]),
            "kind": "community",
            "level": 2,
            "nom": r["title"],
            "subdomains": subs,
        })
    return {"items": items}


def get_community_subgraph(node_id: str, limit: int = 80) -> dict:
    """Entités membres d'une communauté + relations intra-communauté (pour charger dans le canvas).

    Fonctionne pour L1 (IN_COMMUNITY direct) et L2 (agrège les entités de tous les L1
    rattachés via SUBCOMMUNITY_OF).
    """
    kind, *rest = parse_node_id(node_id)
    if kind != "c":
        raise ValueError("Seules les communautés supportent cette opération.")
    community_id_ = rest[0]

    c_rows = _run("MATCH (c:Community {id: $id}) RETURN c", id=community_id_)
    if not c_rows:
        raise LegacyKbNotFound(f"Communauté {community_id_!r} introuvable.")
    center_summary = _node_summary(c_rows[0]["c"])

    entity_rows = _run(
        """
        MATCH (e:Entity)-[:IN_COMMUNITY]->(c1:Community)
        WHERE c1.id = $id
           OR EXISTS { MATCH (c1)-[:SUBCOMMUNITY_OF]->(:Community {id: $id}) }
        RETURN e
        LIMIT $limit
        """,
        id=community_id_,
        limit=limit,
    )

    nodes: dict = {}
    for r in entity_rows:
        s = _node_summary(r["e"])
        if s["id"]:
            nodes[s["id"]] = s

    edges: list = []
    if nodes:
        names = list({s["nom"] for s in nodes.values()})
        edge_rows = _run(
            """
            MATCH (e1:Entity)-[r]->(e2:Entity)
            WHERE e1.name IN $names AND e2.name IN $names
              AND type(r) IN ['CALLS', 'INCLUDES', 'READS', 'INSERTS', 'UPDATES',
                              'DELETES', 'CREATES', 'REFERENCES', 'EXECUTES',
                              'INTERACTS_WITH', 'SENDS', 'RECEIVES', 'TRIGGERS', 'DEPENDS_ON']
            RETURN e1.type AS t1, e1.name AS n1, type(r) AS relType, e2.type AS t2, e2.name AS n2
            LIMIT $limit
            """,
            names=names,
            limit=limit * 3,
        )
        seen_edges: set = set()
        for r in edge_rows:
            from_id = entity_id(r["t1"], r["n1"])
            to_id = entity_id(r["t2"], r["n2"])
            key = f"{from_id}|{to_id}|{r['relType']}"
            if from_id in nodes and to_id in nodes and key not in seen_edges:
                seen_edges.add(key)
                edges.append({"from": from_id, "to": to_id, "type": r["relType"]})

    entity_pairs = [(s["type"], s["nom"]) for s in nodes.values()]
    communities = _entity_communities(entity_pairs)
    for s in nodes.values():
        s["community"] = communities.get((s["type"], s["nom"]))

    return {
        "center": center_summary,
        "neighbors": list(nodes.values()),
        "edges": edges,
    }


def _entity_communities(entities: list[tuple[str, str]]) -> dict[tuple[str, str], dict]:
    """Communauté de rattachement directe (IN_COMMUNITY) pour un lot d'entités.

    Une requête groupée (UNWIND) plutôt qu'une requête par entité — utilisé pour
    annoter les nœuds renvoyés par `get_node_neighbors` (regroupement visuel par
    communauté dans le frontend).
    """
    if not entities:
        return {}
    rows = _run(
        """
        UNWIND $items AS item
        MATCH (e:Entity {type: item.type, name: item.name})-[:IN_COMMUNITY]->(c:Community)
        RETURN item.type AS type, item.name AS name, c.id AS c_id, c.title AS c_title, c.level AS c_level
        """,
        items=[{"type": t, "name": n} for t, n in entities],
    )
    return {
        (r["type"], r["name"]): {
            "id": community_id(r["c_id"]),
            "nom": r["c_title"],
            "level": r["c_level"],
        }
        for r in rows
    }


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

    center_summary = _node_summary(center_rows[0]["n"])

    entity_pairs = [
        (s["type"], s["nom"])
        for s in [center_summary, *neighbors.values()]
        if s["kind"] == "entity"
    ]
    communities = _entity_communities(entity_pairs)
    for s in [center_summary, *neighbors.values()]:
        if s["kind"] == "entity":
            s["community"] = communities.get((s["type"], s["nom"]))

    return {
        "center": center_summary,
        "neighbors": list(neighbors.values()),
        "edges": edges,
    }


# Relations structurelles (hors hiérarchie IN_COMMUNITY/SUBCOMMUNITY_OF) — utilisées
# pour le calcul de "blast radius" (get_impact_paths).
_IMPACT_REL_TYPES = (
    "CALLS|INCLUDES|READS|INSERTS|UPDATES|DELETES|CREATES|REFERENCES|"
    "EXECUTES|INTERACTS_WITH|SENDS|RECEIVES|TRIGGERS|DEPENDS_ON"
)


def get_impact_paths(node_id: str, max_depth: int = 2, limit: int = 60) -> dict:
    """Sous-graphe atteint depuis `node_id` via les relations structurelles, jusqu'à
    `max_depth` sauts ("blast radius"). Utilise `apoc.path.subgraphAll` (APOC
    disponible sur l'instance). Renvoie aussi `cypher`/`params` (requête et
    paramètres réellement exécutés) pour l'explicabilité côté frontend."""
    kind, *rest = parse_node_id(node_id)

    if kind == "e":
        entity_type, name = rest
        match_clause = "MATCH (n:Entity {type: $type, name: $name})"
        match_params = {"type": entity_type, "name": name}
    else:
        community_id_, = rest
        match_clause = "MATCH (n:Community {id: $id})"
        match_params = {"id": community_id_}

    max_depth = max(1, min(int(max_depth), 3))
    limit = max(1, min(int(limit), 200))

    cypher = (
        f"{match_clause}\n"
        "CALL apoc.path.subgraphAll(n, {maxLevel: $max_depth, relationshipFilter: $rels, limit: $limit})\n"
        "YIELD nodes, relationships\n"
        "RETURN n, nodes, relationships"
    )
    params = {**match_params, "max_depth": max_depth, "rels": _IMPACT_REL_TYPES, "limit": limit}

    rows = _run(cypher, **params)
    if not rows:
        raise LegacyKbNotFound("Nœud introuvable.")
    row = rows[0]

    center_summary = _node_summary(row["n"])

    summaries = {}
    for node in row["nodes"]:
        s = _node_summary(node)
        if s["id"] is not None:
            summaries[s["id"]] = s
    summaries.pop(center_summary["id"], None)

    edges = []
    seen = set()
    for rel in row["relationships"]:
        start_s = _node_summary(rel.nodes[0])
        end_s = _node_summary(rel.nodes[1])
        if start_s["id"] is None or end_s["id"] is None:
            continue
        key = (start_s["id"], end_s["id"], rel.type)
        if key in seen:
            continue
        seen.add(key)
        edges.append({"from": start_s["id"], "to": end_s["id"], "type": rel.type})

    neighbors = list(summaries.values())

    entity_pairs = [
        (s["type"], s["nom"])
        for s in [center_summary, *neighbors]
        if s["kind"] == "entity"
    ]
    communities = _entity_communities(entity_pairs)
    for s in [center_summary, *neighbors]:
        if s["kind"] == "entity":
            s["community"] = communities.get((s["type"], s["nom"]))

    return {
        "center": center_summary,
        "nodes": neighbors,
        "edges": edges,
        "cypher": cypher,
        "params": {"node_id": node_id, "max_depth": max_depth, "limit": limit},
    }


def _relation_counts(match_clause: str, **params) -> list[dict]:
    """Compteurs de relations entrantes/sortantes par type, pour la carte de connectivité."""
    rows = _run(
        f"""
        {match_clause}
        CALL {{
            WITH n
            MATCH (n)-[r]->() RETURN type(r) AS relType, 'out' AS dir
            UNION ALL
            WITH n
            MATCH (n)<-[r]-() RETURN type(r) AS relType, 'in' AS dir
        }}
        RETURN relType, dir, count(*) AS n
        ORDER BY n DESC
        """,
        **params,
    )
    return [{"type": r["relType"], "dir": r["dir"], "count": r["n"]} for r in rows]


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

        # Domaine fonctionnel (Community niveau 2) et sous-domaine (niveau 1) — via IN_COMMUNITY/SUBCOMMUNITY_OF
        domain = []
        domain_rows = _run(
            """
            MATCH (e:Entity {type: $type, name: $name})-[:IN_COMMUNITY]->(c1:Community)
            OPTIONAL MATCH (c1)-[:SUBCOMMUNITY_OF]->(c2:Community)
            RETURN c1.id AS c1_id, c1.title AS c1_title, c2.id AS c2_id, c2.title AS c2_title
            """,
            type=entity_type, name=name,
        )
        if domain_rows:
            r = domain_rows[0]
            if r["c2_id"] is not None:
                domain.append({"id": community_id(r["c2_id"]), "nom": r["c2_title"], "level": 2})
            if r["c1_id"] is not None:
                domain.append({"id": community_id(r["c1_id"]), "nom": r["c1_title"], "level": 1})

        relations = _relation_counts(
            "MATCH (n:Entity {type: $type, name: $name})", type=entity_type, name=name,
        )

        return {
            "id": node_id,
            "kind": "entity",
            "type": e["type"],
            "nom": e["name"],
            "source": e.get("file_location"),
            "file_name": e.get("file_name"),
            "repo_name": e.get("repo_name"),
            "updated_at": e.get("updated_at"),
            "is_missing": e.get("is_missing", False),
            "domain": domain,
            "relations": relations,
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
    level = c["level"]

    parent_domain = None
    subdomain_count = None
    if level == 1:
        parent_rows = _run(
            """
            MATCH (c1:Community {id: $id})-[:SUBCOMMUNITY_OF]->(c2:Community)
            RETURN c2.id AS id, c2.title AS title
            """,
            id=community_id_,
        )
        if parent_rows:
            parent_domain = {"id": community_id(parent_rows[0]["id"]), "nom": parent_rows[0]["title"]}
        member_rows = _run(
            "MATCH (e:Entity)-[:IN_COMMUNITY]->(c1:Community {id: $id}) RETURN count(e) AS n",
            id=community_id_,
        )
        member_count = member_rows[0]["n"]
    else:
        sub_rows = _run(
            """
            MATCH (c1:Community)-[:SUBCOMMUNITY_OF]->(c2:Community {id: $id})
            OPTIONAL MATCH (e:Entity)-[:IN_COMMUNITY]->(c1)
            RETURN count(DISTINCT c1) AS subdomains, count(DISTINCT e) AS members
            """,
            id=community_id_,
        )
        subdomain_count = sub_rows[0]["subdomains"]
        member_count = sub_rows[0]["members"]

    relations = _relation_counts("MATCH (n:Community {id: $id})", id=community_id_)

    return {
        "id": node_id,
        "kind": "community",
        "level": level,
        "nom": c["title"],
        "member_count": member_count,
        "subdomain_count": subdomain_count,
        "parent_domain": parent_domain,
        "relations": relations,
        "functional_summary": c.get("functional_summary"),
        "technical_summary": c.get("technical_summary"),
    }
