"""Legacy KB — lecture en direct du graphe GraphRAG brut importé dans `neo4j-legacykb`.

Instance Neo4j séparée (cf. docs/extract/instructions.md et
docs/extract/mapping-graphrag-to-adgm.md) : héberge le dump complet
`repartition_cleaned_export.graphml` (5812 nœuds :Entity/:Community, 19368 relations),
dont seule une partie est fusionnée dans ADG-M (cf. ingest/graphrag_to_adgm.py).
Ce router donne un accès en lecture à l'intégralité du dump pour exploration
("Legacy KB"), sans toucher au graphe ADG-M.

Logique Neo4j dans `api/services/legacykb_client.py` (réutilisée aussi par les tools
function-calling du Chat, cf. `api/services/graph_tools.py`).
"""

from fastapi import APIRouter, HTTPException

from api.services import legacykb_client as kb

router = APIRouter(prefix="/legacykb", tags=["legacykb"])


@router.get("/health")
def get_health():
    """Vérifie que l'instance neo4j-legacykb est joignable (voyant de connexion)."""
    try:
        return kb.get_health()
    except kb.LegacyKbError as e:
        raise HTTPException(502, detail=str(e))


@router.get("/stats")
def get_stats():
    """Comptage des nœuds par type d':Entity et niveau de :Community."""
    try:
        return kb.get_stats()
    except kb.LegacyKbError as e:
        raise HTTPException(502, detail=str(e))


@router.get("/domains")
def list_domains():
    """Domaines fonctionnels (:Community niveau 2) — pour parcourir le graphe par domaine."""
    try:
        return kb.list_domains()
    except kb.LegacyKbError as e:
        raise HTTPException(502, detail=str(e))


@router.get("/hierarchy")
def get_hierarchy():
    """Hiérarchie complète L2→L1 avec nombre d'entités par sous-domaine."""
    try:
        return kb.get_hierarchy()
    except kb.LegacyKbError as e:
        raise HTTPException(502, detail=str(e))


@router.get("/search")
def search(q: str, limit: int = 25, types: str | None = None, descriptions: bool = False):
    """Recherche sur le nom des :Entity et le titre des :Community.

    `types` : liste de types d':Entity séparés par des virgules (ex. "Program,BatchJob")
    pour filtrer les résultats — exclut alors les :Community.
    `descriptions` : étend la recherche aux descriptions/résumés fonctionnels et techniques.
    """
    entity_types = [t.strip() for t in types.split(",") if t.strip()] if types else None
    try:
        return kb.search(q, limit, entity_types=entity_types, search_descriptions=descriptions)
    except kb.LegacyKbError as e:
        raise HTTPException(502, detail=str(e))


@router.get("/nodes/{node_id:path}/subgraph")
def get_community_subgraph(node_id: str, limit: int = 80):
    """Entités membres d'une communauté + relations intra-communauté (pour charger dans le canvas)."""
    try:
        return kb.get_community_subgraph(node_id, limit)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    except kb.LegacyKbNotFound as e:
        raise HTTPException(404, detail=str(e))
    except kb.LegacyKbError as e:
        raise HTTPException(502, detail=str(e))


@router.get("/nodes/{node_id:path}/neighbors")
def get_node_neighbors(node_id: str, limit: int = 60):
    """Voisinage direct (toutes relations) d'un nœud — pour exploration au clic dans le graphe."""
    try:
        return kb.get_node_neighbors(node_id, limit)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    except kb.LegacyKbNotFound as e:
        raise HTTPException(404, detail=str(e))
    except kb.LegacyKbError as e:
        raise HTTPException(502, detail=str(e))


@router.get("/nodes/{node_id:path}/impact")
def get_impact_paths(node_id: str, max_depth: int = 2, limit: int = 60):
    """Sous-graphe atteint depuis ce nœud via les relations structurelles ("blast radius")."""
    try:
        return kb.get_impact_paths(node_id, max_depth, limit)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    except kb.LegacyKbNotFound as e:
        raise HTTPException(404, detail=str(e))
    except kb.LegacyKbError as e:
        raise HTTPException(502, detail=str(e))


@router.get("/nodes/{node_id:path}")
def get_node(node_id: str):
    """Détail complet d'un nœud (:Entity ou :Community)."""
    try:
        return kb.get_node(node_id)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    except kb.LegacyKbNotFound as e:
        raise HTTPException(404, detail=str(e))
    except kb.LegacyKbError as e:
        raise HTTPException(502, detail=str(e))
