"""Tools function-calling (OpenAI) donnant au Chat un accès en lecture à `neo4j-legacykb`.

Base de connaissances legacy CardDemo (dump GraphRAG, cf. api/services/legacykb_client.py) :
- :Entity (Program, BatchJob, Copybook, GenericFile...) avec descriptions fonctionnelle/technique
- :Community (domaines fonctionnels, niveaux 1/2) avec résumés fonctionnel/technique
- Relations : CALLS, INCLUDES, READS/INSERTS/UPDATES/DELETES/CREATES, IN_COMMUNITY, EXECUTES, ...
"""

import logging

from . import legacykb_client as kb

logger = logging.getLogger(__name__)


LEGACYKB_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "legacykb_search",
            "description": (
                "Recherche dans la base de connaissances legacy CardDemo (graphe GraphRAG) "
                "des programmes COBOL, copybooks, batch jobs ou domaines fonctionnels dont le "
                "nom/titre contient le terme donné (recherche par sous-chaîne, insensible à la "
                "casse). À utiliser dès que l'utilisateur mentionne un nom (même partiel) de "
                "programme, copybook, job ou domaine fonctionnel du système CardDemo."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Terme ou fragment de nom à rechercher (ex. 'RE1570', 'stock', 'replenishment').",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Nombre maximum de résultats (défaut 10).",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "legacykb_get_entity",
            "description": (
                "Récupère le détail complet d'un élément de la base de connaissances legacy "
                "CardDemo (programme, copybook, batch job ou domaine fonctionnel) à partir de "
                "son identifiant (obtenu via legacykb_search). Pour un programme/copybook/job, "
                "renvoie ses descriptions fonctionnelle et technique. Pour un domaine "
                "fonctionnel (community), renvoie ses résumés fonctionnel et technique."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_id": {
                        "type": "string",
                        "description": "Identifiant du nœud, tel que retourné par legacykb_search (ex. 'e|Program|RE1570C' ou 'c|12').",
                    },
                },
                "required": ["node_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "legacykb_get_relations",
            "description": (
                "Liste les relations directes (appels de programmes CALLS, inclusions de "
                "copybooks INCLUDES, accès fichiers READS/INSERTS/UPDATES/DELETES/CREATES, "
                "appartenance à un domaine fonctionnel IN_COMMUNITY, exécution par un batch job "
                "EXECUTES, etc.) d'un élément de la base de connaissances legacy CardDemo, dans "
                "les deux sens, avec les éléments voisins. À utiliser pour répondre aux questions "
                "sur les dépendances, chaînes d'appel, accès aux données, ou le domaine "
                "fonctionnel d'un programme/copybook/job."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_id": {
                        "type": "string",
                        "description": "Identifiant du nœud, tel que retourné par legacykb_search (ex. 'e|Program|RE1570C' ou 'c|12').",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Nombre maximum de relations renvoyées (défaut 40).",
                    },
                },
                "required": ["node_id"],
            },
        },
    },
]


def execute_legacykb_tool(name: str, arguments: dict) -> dict:
    """Exécute un tool legacykb par son nom. Ne lève jamais d'exception : renvoie {"error": ...}."""
    try:
        if name == "legacykb_search":
            query = str(arguments.get("query", ""))
            limit = int(arguments.get("limit", 10))
            return kb.search(query, limit)

        if name == "legacykb_get_entity":
            node_id = str(arguments.get("node_id", ""))
            return kb.get_node(node_id)

        if name == "legacykb_get_relations":
            node_id = str(arguments.get("node_id", ""))
            limit = int(arguments.get("limit", 40))
            return kb.get_node_neighbors(node_id, limit)

        return {"error": f"Tool inconnu : {name!r}"}
    except (kb.LegacyKbNotFound, ValueError) as e:
        return {"error": str(e)}
    except kb.LegacyKbError as e:
        logger.warning("legacykb tool %s indisponible : %s", name, e)
        return {"error": str(e)}
    except Exception:
        logger.exception("Échec inattendu du tool legacykb %s", name)
        return {"error": "Erreur interne lors de l'accès à la base de connaissances legacy."}
