#!/usr/bin/env python3
"""MCP server — accès en lecture au graphe GraphRAG LegacyKB (neo4j-legacykb).

Expose les outils suivants pour l'exploration de la base de connaissances :
  - legacykb_stats           : comptage nœuds/relations
  - legacykb_search          : recherche par nom/description
  - legacykb_get_node        : détail complet d'un nœud
  - legacykb_get_neighbors   : voisinage direct d'un nœud
  - legacykb_get_community   : entités + relations internes d'une communauté
  - legacykb_get_impact      : sous-graphe de dépendances ("blast radius")
  - legacykb_get_hierarchy   : arbre L2→L1 des communautés

Passe par l'API HTTPS déployée (/api/legacykb/*) plutôt que par une connexion
Bolt directe au conteneur Neo4j : Zscaler (inspection SSL d'entreprise) casse
le protocole Bolt sur le port 7687 (non-HTTP — le certificat retourné est
celui de Zscaler, et la negotiation échoue juste après le handshake TLS),
alors que les appels HTTPS standard passent sans problème par le même proxy.

Variables d'environnement requises (chargées depuis le fichier .env à la
racine du projet) :
  NOTEBOOKLM_API_URL   URL de base de l'API déployée (ex. https://ca-api-...azurecontainerapps.io)
  API_KEY              clé d'authentification de l'API (header X-API-Key)
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# ── Chargement .env (racine du projet = parent de ce dossier) ──────────────
load_dotenv(Path(__file__).parent.parent / ".env")

_API_BASE_URL = os.environ.get("NOTEBOOKLM_API_URL", "").rstrip("/")
if not _API_BASE_URL:
    raise RuntimeError(
        "NOTEBOOKLM_API_URL non configuré. Définir cette variable dans .env "
        "(URL de l'API déployée, ex. https://ca-api-<suffix>.azurecontainerapps.io)."
    )

_client = httpx.Client(
    base_url=f"{_API_BASE_URL}/api/legacykb",
    headers={"X-API-Key": os.environ.get("API_KEY", "")},
    timeout=30.0,
)


def _get(path: str, **params) -> dict:
    params = {k: v for k, v in params.items() if v is not None}
    try:
        resp = _client.get(path, params=params)
    except httpx.HTTPError as e:
        raise RuntimeError(f"API legacykb injoignable ({_API_BASE_URL}) : {e}") from e

    if resp.status_code == 404:
        detail = resp.json().get("detail", "Nœud introuvable.") if resp.content else "Nœud introuvable."
        raise ValueError(detail)
    if resp.status_code == 400:
        detail = resp.json().get("detail", "Requête invalide.") if resp.content else "Requête invalide."
        raise ValueError(detail)
    if resp.status_code >= 500:
        detail = resp.json().get("detail", "Erreur serveur.") if resp.content else "Erreur serveur."
        raise RuntimeError(f"Erreur API legacykb : {detail}")
    resp.raise_for_status()
    return resp.json()


def _node_path(node_id: str) -> str:
    return f"/nodes/{quote(node_id, safe='')}"


# ── MCP server ────────────────────────────────────────────────────────────

mcp = FastMCP(
    "legacykb",
    instructions=(
        "Accès en lecture au graphe GraphRAG LegacyKB (neo4j-legacykb), via l'API "
        "HTTPS déployée. 5 800+ entités (Programme, Copybook, BatchJob, Fichier, etc.) "
        "et 96 communautés fonctionnelles organisées en deux niveaux (L1 sous-domaine, "
        "L2 domaine). Les identifiants de nœuds ont le format 'e|Type|Nom' pour les "
        "entités et 'c|id' pour les communautés."
    ),
)


@mcp.tool()
def legacykb_stats() -> dict:
    """Renvoie le nombre de nœuds par type d'entité et par niveau de communauté.

    Utile pour avoir une vue d'ensemble de la taille et de la composition de la base.
    """
    return _get("/stats")


@mcp.tool()
def legacykb_search(
    q: str,
    limit: int = 25,
    types: str | None = None,
    descriptions: bool = False,
) -> dict:
    """Recherche des entités et des communautés par nom/titre dans LegacyKB.

    Args:
        q: Terme de recherche (insensible à la casse, recherche par sous-chaîne).
        limit: Nombre maximum de résultats (défaut 25, max 100).
        types: Types d'entité à filtrer, séparés par des virgules
               (ex. "Program,BatchJob"). Si fourni, les communautés sont exclues.
               Types disponibles : Program, Copybook, BatchJob, File, ExternalRef, etc.
        descriptions: Si True, étend la recherche aux descriptions fonctionnelles
                      et techniques (plus lent, résultats plus larges).

    Returns:
        {"items": [...]} — chaque item a les champs : id, kind, type/level, nom.
        L'identifiant `id` sert d'entrée aux autres outils (get_node, get_neighbors…).
    """
    return _get("/search", q=q, limit=limit, types=types, descriptions=descriptions)


@mcp.tool()
def legacykb_get_node(node_id: str) -> dict:
    """Renvoie le détail complet d'un nœud (entité ou communauté).

    Args:
        node_id: Identifiant du nœud au format 'e|Type|Nom' (entité)
                 ou 'c|id' (communauté). Obtenable via legacykb_search.

    Returns:
        Dictionnaire avec toutes les propriétés du nœud : descriptions fonctionnelles
        et techniques, localisation source, communauté d'appartenance, compteurs
        de relations entrantes/sortantes.
    """
    return _get(_node_path(node_id))


@mcp.tool()
def legacykb_get_neighbors(node_id: str, limit: int = 60) -> dict:
    """Renvoie le voisinage direct (toutes relations) d'un nœud.

    Utile pour explorer les connexions immédiates d'une entité ou d'une communauté :
    quels programmes appellent ce programme, quels fichiers il lit, etc.

    Args:
        node_id: Identifiant du nœud ('e|Type|Nom' ou 'c|id').
        limit: Nombre maximum de voisins (défaut 60, max 200).

    Returns:
        {"center": {...}, "neighbors": [...], "edges": [...]}
        Chaque arête a les champs : from, to, type (type de relation Neo4j).
    """
    return _get(f"{_node_path(node_id)}/neighbors", limit=limit)


@mcp.tool()
def legacykb_get_community(node_id: str, limit: int = 80) -> dict:
    """Renvoie les entités membres d'une communauté et leurs relations internes.

    Fonctionne pour les communautés L1 (sous-domaine) et L2 (domaine) :
    pour un domaine L2, agrège les entités de tous ses sous-domaines L1.

    Args:
        node_id: Identifiant d'une communauté au format 'c|id'.
                 Obtenir les IDs via legacykb_search ou legacykb_get_hierarchy.
        limit: Nombre maximum d'entités (défaut 80, max 200).

    Returns:
        {"center": {...}, "neighbors": [...], "edges": [...]}
        Les arêtes représentent les relations structurelles intra-communauté.
    """
    return _get(f"{_node_path(node_id)}/subgraph", limit=limit)


@mcp.tool()
def legacykb_get_impact(node_id: str, max_depth: int = 2, limit: int = 60) -> dict:
    """Calcule le sous-graphe de dépendances ("blast radius") depuis un nœud.

    Traverse les relations structurelles (CALLS, INCLUDES, READS, etc.) jusqu'à
    `max_depth` sauts. Utile pour évaluer l'impact d'une modification sur un
    programme ou un fichier.

    Args:
        node_id: Identifiant du nœud source ('e|Type|Nom' ou 'c|id').
        max_depth: Profondeur maximale de traversal (1–3, défaut 2).
        limit: Nombre maximum de nœuds dans le sous-graphe (défaut 60, max 200).

    Returns:
        {"center": {...}, "nodes": [...], "edges": [...]}
        Seules les relations structurelles sont incluses (pas IN_COMMUNITY).
    """
    return _get(f"{_node_path(node_id)}/impact", max_depth=max_depth, limit=limit)


@mcp.tool()
def legacykb_get_hierarchy() -> dict:
    """Renvoie l'arbre complet des communautés fonctionnelles (L2 → L1).

    Chaque domaine L2 contient ses sous-domaines L1 avec le nombre d'entités.
    Utile pour comprendre l'organisation fonctionnelle de la base.

    Returns:
        {"items": [...]} — liste de domaines L2, chacun avec "subdomains" (liste de L1).
    """
    return _get("/hierarchy")


if __name__ == "__main__":
    mcp.run()
