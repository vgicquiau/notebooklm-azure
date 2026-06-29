"""Legacy KB — accès en lecture au graphe GraphRAG brut importé dans `neo4j-legacykb`.

Instance Neo4j séparée (cf. docs/extract/mapping-graphrag-to-adgm.md) : héberge le dump
complet `repartition_cleaned_export.graphml` (5812 nœuds :Entity/:Community, 19368
relations), dont seule une partie est fusionnée dans ADG-M (cf. ingest/graphrag_to_adgm.py).

Module de service pur (sans dépendance FastAPI), utilisé par :
- `api/routers/legacykb.py` (endpoints HTTP pour l'exploration frontend)
- `api/services/graph_tools.py` (tools function-calling pour le Chat)

Transport : API HTTP transactionnelle de Neo4j (port 7473 HTTPS / 7474 HTTP), pas le
protocole Bolt (port 7687) — Zscaler (et proxys d'entreprise similaires interceptant le
TLS) cassent le handshake sur Bolt, protocole non-HTTP, alors que les appels HTTPS
standards passent normalement. Même contournement que `mcp-legacykb`, qui passe par
l'API HTTPS déployée (`NOTEBOOKLM_API_URL`) plutôt que par une connexion Bolt directe.
Le port Bolt reste exposé côté infra (cf. infra/modules/neo4j-legacykb.bicep) pour
d'éventuels autres clients, mais ce module ne s'en sert pas.

Variables d'environnement :
    NEO4J_LEGACYKB_URI       (défaut bolt+ssc://neo4j-legacykb-vgi.francecentral.azurecontainer.io:7687)
    NEO4J_LEGACYKB_PASSWORD  (pas de défaut)

Note : ces variables sont lues à la première connexion (dans `_get_connection`), pas à
l'import du module — `load_dotenv()` dans `api/main.py` s'exécute après les imports.
L'URI garde un schéma bolt par convention/compat (et pour le port Bolt documenté côté
infra) ; le host est réutilisé pour construire l'URL HTTP(S) réellement appelée.
"""

import logging
import os
from urllib.parse import urlsplit

import requests
import urllib3
from requests.exceptions import RequestException

logger = logging.getLogger(__name__)

_session: requests.Session | None = None
_base_url: str | None = None
_auth: tuple[str, str] | None = None


class LegacyKbError(Exception):
    """Erreur d'accès à la base neo4j-legacykb (config manquante ou instance injoignable)."""


class LegacyKbNotFound(Exception):
    """Le nœud demandé n'existe pas dans neo4j-legacykb."""


def _get_connection() -> tuple[requests.Session, str, tuple[str, str]]:
    global _session, _base_url, _auth
    if _session is None:
        uri = os.environ.get(
            "NEO4J_LEGACYKB_URI",
            "bolt+ssc://neo4j-legacykb-vgi.francecentral.azurecontainer.io:7687",
        )
        password = os.environ.get("NEO4J_LEGACYKB_PASSWORD")
        if not password:
            raise LegacyKbError("NEO4J_LEGACYKB_PASSWORD non configuré.")
        parsed = urlsplit(uri)
        host = parsed.hostname
        if not host:
            raise LegacyKbError(f"NEO4J_LEGACYKB_URI invalide : {uri!r}")

        # "+s"/"+ssc" (ex. bolt+ssc, neo4j+s) -> TLS actif côté Neo4j -> HTTPS:7473.
        # Schéma bolt:// nu (ex. instance locale sans TLS) -> HTTP:7474 (port par défaut).
        tls = "+s" in parsed.scheme
        scheme, port = ("https", 7473) if tls else ("http", 7474)
        _base_url = f"{scheme}://{host}:{port}"
        _auth = ("neo4j", password)
        _session = requests.Session()
        if tls:
            # Cert auto-signé (ACI interne) -- équivalent du bolt+ssc:// précédemment
            # utilisé par le driver Bolt (TLS actif, CA publique non requise).
            # AUDIT-2026-06 (finding haut) : faute de validation, le canal accepte tout
            # certificat présenté -- acceptable tant que l'ACI reste joignable uniquement
            # via son IP publique connue, à réévaluer si neo4j-legacykb passe derrière un
            # Private Endpoint/VNet (cf. finding réseau associé, même audit).
            _session.verify = False
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    return _session, _base_url, _auth


def _execute(query: str, params: dict) -> dict:
    """Exécute une requête Cypher via l'API transactionnelle HTTP et renvoie `results[0]`."""
    session, base_url, auth = _get_connection()
    body = {
        "statements": [
            {
                "statement": query,
                "parameters": params,
                "resultDataContents": ["row", "graph"],
            }
        ]
    }
    try:
        resp = session.post(f"{base_url}/db/neo4j/tx/commit", json=body, auth=auth, timeout=30)
    except RequestException as e:
        logger.exception("neo4j-legacykb injoignable")
        raise LegacyKbError("Instance Neo4j legacy-kb injoignable.") from e

    if resp.status_code == 401:
        raise LegacyKbError("Authentification neo4j-legacykb refusée (NEO4J_LEGACYKB_PASSWORD incorrect).")
    if resp.status_code >= 400:
        raise LegacyKbError(f"neo4j-legacykb a renvoyé HTTP {resp.status_code}.")

    try:
        payload = resp.json()
    except ValueError as e:
        raise LegacyKbError("Réponse invalide de neo4j-legacykb.") from e

    if payload.get("errors"):
        raise LegacyKbError(payload["errors"][0]["message"])
    return payload["results"][0]


def _run_rows(query: str, **params) -> list[dict]:
    """Requêtes ne renvoyant que des champs scalaires/listes/maps (pas de nœuds/relations bruts)."""
    result = _execute(query, params)
    columns = result["columns"]
    return [dict(zip(columns, item["row"])) for item in result["data"]]


class _HttpNode:
    """Nœud Neo4j tel que renvoyé par l'API HTTP ("graph" content) -- équivalent en
    lecture seule de `neo4j.graph.Node` (utilisé par le driver Bolt précédemment), pour
    que `_node_summary` et les accès `node["prop"]`/`node.get(...)` restent inchangés."""

    __slots__ = ("labels", "_props")

    def __init__(self, labels: list[str], properties: dict):
        self.labels = set(labels)
        self._props = properties

    def __getitem__(self, key):
        return self._props[key]

    def get(self, key, default=None):
        return self._props.get(key, default)


def _run_graph(query: str, **params) -> list[tuple[dict, list["_HttpNode"]]]:
    """Comme `_run_rows`, pour les requêtes renvoyant des nœuds bruts (RETURN e/c/n/m).

    Renvoie, par ligne de résultat, le tuple (champs scalaires, nœuds touchés par cette
    ligne) -- le "graph" content de l'API HTTP ne réattribue pas les nœuds par colonne,
    seulement par ligne, donc les appelants identifient le bon nœud par position/identité.
    """
    result = _execute(query, params)
    columns = result["columns"]
    rows = []
    for item in result["data"]:
        scalars = dict(zip(columns, item["row"]))
        nodes = [_HttpNode(n["labels"], n["properties"]) for n in item["graph"]["nodes"]]
        rows.append((scalars, nodes))
    return rows


def _run_graph_full(query: str, **params) -> list[tuple[list["_HttpNode"], list[tuple]]]:
    """Comme `_run_graph`, en renvoyant aussi les relations -- utilisé pour
    apoc.path.subgraphAll (get_impact_paths). Chaque relation est un tuple
    (nœud de départ, type, nœud d'arrivée)."""
    result = _execute(query, params)
    rows = []
    for item in result["data"]:
        graph = item["graph"]
        nodes_by_id = {n["id"]: _HttpNode(n["labels"], n["properties"]) for n in graph["nodes"]}
        rels = [
            (nodes_by_id[r["startNode"]], r["type"], nodes_by_id[r["endNode"]])
            for r in graph["relationships"]
        ]
        rows.append((list(nodes_by_id.values()), rels))
    return rows


# Types d':Entity "coeur" (vs. `External/Doc`/`GenericFile`, des fichiers/datasets
# référencés en masse par les jobs/programmes mais peu utiles pour comprendre les
# relations fonctionnelles) -- toujours affichés en entier, jamais tronqués par
# `limit` (cf. get_community_subgraph/get_node_neighbors). Cf. demande utilisateur
# du 2026-06-26 : dépriorise `External/Doc` dans le canvas, au profit des relations
# entre domaines/sous-domaines, Programme, Job batch et Copybook.
_PRIORITY_ENTITY_TYPES = ("BatchJob", "Program", "Copybook")
_DEPRIORITIZED_ENTITY_TYPES = ("External/Doc", "GenericFile")


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
    _run_rows("RETURN 1")
    return {"status": "ok"}


def get_stats() -> dict:
    """Comptage des nœuds par type d':Entity et niveau de :Community."""
    entity_counts = {
        r["type"]: r["n"]
        for r in _run_rows("MATCH (e:Entity) RETURN e.type AS type, count(*) AS n")
    }
    community_counts = {
        r["level"]: r["n"]
        for r in _run_rows("MATCH (c:Community) RETURN c.level AS level, count(*) AS n")
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
    for r in _run_rows(
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
        for r in _run_rows(
            """
            MATCH (c:Community)
            WHERE toLower(c.title) CONTAINS toLower($q)
              OR toLower(c.id) CONTAINS toLower($q)
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
    rows = _run_rows(
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
    tree_rows = _run_rows(
        """
        MATCH (c2:Community {level: 2})
        OPTIONAL MATCH (c1:Community)-[:SUBCOMMUNITY_OF]->(c2)
        WITH c2, collect(c1) AS c1s
        RETURN c2.id AS id, c2.title AS title,
               [c1 IN c1s WHERE c1 IS NOT NULL | {id: c1.id, title: c1.title}] AS subs
        ORDER BY c2.title
        """
    )
    count_rows = _run_rows(
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

    Les entités "coeur" (Program/BatchJob/Copybook) sont toujours renvoyées en entier,
    sans troncature -- ce sont elles que l'exploration fonctionnelle a besoin de voir
    complètement. `limit` ne borne plus que le nombre d'entités `External/Doc`/
    `GenericFile` ajoutées en complément (masse de loin la plus nombreuse -- 4822
    `External/Doc` contre 832 `Program`/40 `BatchJob`/18 `Copybook` au total -- mais la
    moins utile pour comprendre les relations entre domaines, programmes et jobs).
    """
    kind, *rest = parse_node_id(node_id)
    if kind != "c":
        raise ValueError("Seules les communautés supportent cette opération.")
    community_id_ = rest[0]

    c_rows = _run_graph("MATCH (c:Community {id: $id}) RETURN c", id=community_id_)
    if not c_rows or not c_rows[0][1]:
        raise LegacyKbNotFound(f"Communauté {community_id_!r} introuvable.")
    center_summary = _node_summary(c_rows[0][1][0])

    membership_clause = """
        MATCH (e:Entity)-[:IN_COMMUNITY]->(c1:Community)
        WHERE c1.id = $id
           OR EXISTS { MATCH (c1)-[:SUBCOMMUNITY_OF]->(:Community {id: $id}) }
    """

    priority_rows = _run_graph(
        f"""
        {membership_clause}
        AND e.type IN $priority_types
        RETURN e
        """,
        id=community_id_,
        priority_types=list(_PRIORITY_ENTITY_TYPES),
    )

    nodes: dict = {}
    for _scalars, row_nodes in priority_rows:
        for n in row_nodes:
            s = _node_summary(n)
            if s["id"]:
                nodes[s["id"]] = s

    remaining = max(0, limit - len(nodes))
    if remaining:
        other_rows = _run_graph(
            f"""
            {membership_clause}
            AND NOT e.type IN $priority_types
            RETURN e
            LIMIT $remaining
            """,
            id=community_id_,
            priority_types=list(_PRIORITY_ENTITY_TYPES),
            remaining=remaining,
        )
        for _scalars, row_nodes in other_rows:
            for n in row_nodes:
                s = _node_summary(n)
                if s["id"]:
                    nodes[s["id"]] = s

    edges: list = []
    if nodes:
        names = list({s["nom"] for s in nodes.values()})
        edge_rows = _run_rows(
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
            # Le nombre d'entités "coeur" peut dépasser largement `limit` (jusqu'à ~400
            # dans les plus gros domaines) -- la borne d'arêtes doit suivre, sinon on
            # retronque silencieusement les relations qu'on vient de débloquer côté nœuds.
            limit=max(limit * 3, len(names) * 8),
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
    rows = _run_rows(
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
    """Voisinage direct (toutes relations) d'un nœud — pour exploration au clic dans le graphe.

    Les voisins "coeur" (Program/BatchJob/Copybook, et les :Community -- sans
    propriété `type`) sont toujours renvoyés en entier ; `limit` ne borne que les
    voisins `External/Doc`/`GenericFile` ajoutés en complément (cf. commentaire sur
    `_PRIORITY_ENTITY_TYPES` -- ce sont eux qui saturent un nœud à fort fan-out comme
    un job batch, via READS/INSERTS/UPDATES/DELETES/CREATES vers des datasets).
    """
    kind, *rest = parse_node_id(node_id)

    if kind == "e":
        entity_type, name = rest
        match_clause = "MATCH (n:Entity {type: $type, name: $name})"
        params = {"type": entity_type, "name": name}
    else:
        community_id_, = rest
        match_clause = "MATCH (n:Community {id: $id})"
        params = {"id": community_id_}

    priority_rows = _run_graph(
        f"""
        {match_clause}
        CALL {{
            WITH n
            MATCH (n)-[r]->(m) WHERE NOT coalesce(m.type, '') IN $deprioritized
            RETURN type(r) AS relType, 'out' AS dir, m AS m
            UNION
            WITH n
            MATCH (n)<-[r]-(m) WHERE NOT coalesce(m.type, '') IN $deprioritized
            RETURN type(r) AS relType, 'in' AS dir, m AS m
        }}
        RETURN relType, dir, m
        """,
        deprioritized=list(_DEPRIORITIZED_ENTITY_TYPES),
        **params,
    )

    rows = list(priority_rows)
    remaining = max(0, limit - len(rows))
    if remaining:
        other_rows = _run_graph(
            f"""
            {match_clause}
            CALL {{
                WITH n
                MATCH (n)-[r]->(m) WHERE coalesce(m.type, '') IN $deprioritized
                RETURN type(r) AS relType, 'out' AS dir, m AS m
                UNION
                WITH n
                MATCH (n)<-[r]-(m) WHERE coalesce(m.type, '') IN $deprioritized
                RETURN type(r) AS relType, 'in' AS dir, m AS m
            }}
            RETURN relType, dir, m
            LIMIT $remaining
            """,
            deprioritized=list(_DEPRIORITIZED_ENTITY_TYPES),
            remaining=remaining,
            **params,
        )
        rows.extend(other_rows)

    center_rows = _run_graph(f"{match_clause} RETURN n", **params)
    if not center_rows or not center_rows[0][1]:
        raise LegacyKbNotFound("Nœud introuvable.")
    center_summary = _node_summary(center_rows[0][1][0])

    neighbors = {}
    edges = []
    for scalars, row_nodes in rows:
        if not row_nodes:
            continue
        m_summary = _node_summary(row_nodes[0])
        if m_summary["id"] is None:
            continue
        neighbors[m_summary["id"]] = m_summary
        if scalars["dir"] == "out":
            edges.append({"from": node_id, "to": m_summary["id"], "type": scalars["relType"]})
        else:
            edges.append({"from": m_summary["id"], "to": node_id, "type": scalars["relType"]})

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

    rows = _run_graph_full(cypher, **params)
    if not rows:
        raise LegacyKbNotFound("Nœud introuvable.")
    all_nodes, rels = rows[0]

    # apoc.path.subgraphAll inclut toujours le nœud de départ dans `nodes` -- on
    # retrouve le nœud central par identité plutôt que de refaire un aller-retour.
    if kind == "e":
        center_node = next(
            (nd for nd in all_nodes if "Entity" in nd.labels and nd["type"] == entity_type and nd["name"] == name),
            None,
        )
    else:
        center_node = next(
            (nd for nd in all_nodes if "Community" in nd.labels and nd["id"] == community_id_),
            None,
        )
    if center_node is None:
        raise LegacyKbNotFound("Nœud introuvable.")
    center_summary = _node_summary(center_node)

    summaries = {}
    for node in all_nodes:
        s = _node_summary(node)
        if s["id"] is not None:
            summaries[s["id"]] = s
    summaries.pop(center_summary["id"], None)

    edges = []
    seen = set()
    for start_node, rel_type, end_node in rels:
        start_s = _node_summary(start_node)
        end_s = _node_summary(end_node)
        if start_s["id"] is None or end_s["id"] is None:
            continue
        key = (start_s["id"], end_s["id"], rel_type)
        if key in seen:
            continue
        seen.add(key)
        edges.append({"from": start_s["id"], "to": end_s["id"], "type": rel_type})

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
    rows = _run_rows(
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
        rows = _run_graph(
            """
            MATCH (e:Entity {type: $type, name: $name})
            RETURN e
            """,
            type=entity_type, name=name,
        )
        if not rows or not rows[0][1]:
            raise LegacyKbNotFound("Entité introuvable.")
        e = rows[0][1][0]

        # Domaine fonctionnel (Community niveau 2) et sous-domaine (niveau 1) — via IN_COMMUNITY/SUBCOMMUNITY_OF
        domain = []
        domain_rows = _run_rows(
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
    rows = _run_graph(
        """
        MATCH (c:Community {id: $id})
        RETURN c
        """,
        id=community_id_,
    )
    if not rows or not rows[0][1]:
        raise LegacyKbNotFound("Communauté introuvable.")
    c = rows[0][1][0]
    level = c["level"]

    parent_domain = None
    subdomain_count = None
    if level == 1:
        parent_rows = _run_rows(
            """
            MATCH (c1:Community {id: $id})-[:SUBCOMMUNITY_OF]->(c2:Community)
            RETURN c2.id AS id, c2.title AS title
            """,
            id=community_id_,
        )
        if parent_rows:
            parent_domain = {"id": community_id(parent_rows[0]["id"]), "nom": parent_rows[0]["title"]}
        member_rows = _run_rows(
            "MATCH (e:Entity)-[:IN_COMMUNITY]->(c1:Community {id: $id}) RETURN count(e) AS n",
            id=community_id_,
        )
        member_count = member_rows[0]["n"]
    else:
        sub_rows = _run_rows(
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
