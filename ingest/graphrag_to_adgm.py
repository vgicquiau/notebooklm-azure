"""Mapping GraphRAG -> taxonomie ADG-M v2.0 (Ext #4).

Lit le graphe GraphRAG importé dans l'instance Neo4j `neo4j-legacykb` (cf.
docs/extract/mapping-graphrag-to-adgm.md) et produit le payload {nodes, relations}
attendu par fn-adgm-graph/admin/import-entities. Tout est tagué fiabilite=HYPOTHÈSE
(à valider ensuite via Exploration).

Usage :
    python graphrag_to_adgm.py --dry-run            # écrit graphrag_mapped.json, ne touche pas à ADG-M
    python graphrag_to_adgm.py --apply              # POST vers fn-adgm-graph/admin/import-entities

Variables d'environnement :
    NEO4J_LEGACYKB_URI, NEO4J_LEGACYKB_PASSWORD   (instance source, défaut bolt://localhost:7687 / neo4j)
    ADGM_GRAPH_API_URL                            (défaut https://modernagent-adgm-dev.azurewebsites.net/api/graph)
"""

import argparse
import json
import os

import httpx
from neo4j import GraphDatabase

NEO4J_URI = os.environ.get("NEO4J_LEGACYKB_URI", "bolt://localhost:7687")
NEO4J_PASSWORD = os.environ.get("NEO4J_LEGACYKB_PASSWORD", "neo4j")

ADGM_BASE = os.environ.get(
    "ADGM_GRAPH_API_URL",
    "https://modernagent-adgm-dev.azurewebsites.net/api/graph",
).rstrip("/")

FIABILITE = "HYPOTHÈSE"

# :Entity.type GraphRAG -> (label ADG-M, préfixe id)
ENTITY_TYPE_MAP = {
    "Program": ("Composant", "comp:"),
    "BatchJob": ("Job_Batch", "job:"),
    "Copybook": ("Structure_Partagee", "struct:"),
    "GenericFile": ("Store_Echange", "store:"),
}


def _technologie(file_location: str) -> str | None:
    if "cbl_pacbase/" in file_location:
        return "COBOL_PACBASE"
    if file_location.endswith(".cbl"):
        return "COBOL_BATCH"
    return None


def _description(props: dict) -> str:
    return (
        props.get("functional_description")
        or props.get("technical_description")
        or props.get("technical_summary")
        or ""
    )


def fetch_entities(session):
    """Programmes/jobs/copybooks/fichiers mappables -> nœuds ADG-M + index elementId GraphRAG -> id ADG-M.

    Les nœuds :Entity n'ont pas de propriété `id` (seulement `name`, `type`,
    `file_location`, ...) : on utilise `elementId(e)` (identifiant interne Neo4j,
    stable pour la durée de la session) comme clé de correspondance pour les relations.
    """
    result = session.run(
        """
        MATCH (e:Entity)
        WHERE e.type IN $types AND e.name <> '.DS_Store'
        RETURN elementId(e) AS id, e.type AS type, e.name AS name,
               e.file_location AS file_location,
               e.functional_description AS functional_description,
               e.technical_description AS technical_description
        """,
        types=list(ENTITY_TYPE_MAP.keys()),
    )

    nodes = []
    id_map: dict[str, str] = {}  # elementId(e) -> ADG-M node id

    for record in result:
        label, prefix = ENTITY_TYPE_MAP[record["type"]]
        adgm_id = f"{prefix}{record['name']}"
        id_map[record["id"]] = adgm_id

        props = {
            "nom": record["name"],
            "description": _description(record),
            "source": record["file_location"],
            "fiabilite": FIABILITE,
        }
        if label == "Composant":
            tech = _technologie(record["file_location"] or "")
            if tech:
                props["technologie"] = tech

        nodes.append({"id": adgm_id, "label": label, "properties": props})

    return nodes, id_map


def fetch_communities(session):
    """Communautés GraphRAG niveau 2 -> Domaine_Fonctionnel + index elementId communauté -> id ADG-M."""
    result = session.run(
        """
        MATCH (c:Community)
        WHERE c.level = 2
        RETURN elementId(c) AS id, c.id AS community_id, c.title AS title,
               c.functional_summary AS functional_summary
        """
    )

    nodes = []
    id_map: dict[str, str] = {}  # elementId(c) -> ADG-M node id

    for record in result:
        adgm_id = f"dom:{record['community_id']}"
        id_map[record["id"]] = adgm_id
        nodes.append({
            "id": adgm_id,
            "label": "Domaine_Fonctionnel",
            "properties": {
                "nom": record["title"],
                "description": record["functional_summary"] or "",
                "source": f"GraphRAG community {record['community_id']}",
                "fiabilite": FIABILITE,
            },
        })

    return nodes, id_map


def fetch_relations(session, entity_ids: dict, community_ids: dict):
    relations: list[dict] = []

    # CALLS (Program->Program) -> APPELLE
    for record in session.run(
        "MATCH (a:Entity)-[:CALLS]->(b:Entity) RETURN elementId(a) AS src, elementId(b) AS dst"
    ):
        if record["src"] in entity_ids and record["dst"] in entity_ids:
            relations.append({
                "from": entity_ids[record["src"]],
                "to": entity_ids[record["dst"]],
                "type": "APPELLE",
                "properties": {"fiabilite": FIABILITE, "typeAppel": "STATIQUE"},
            })

    # INCLUDES (Program->Copybook) -> INCLUT
    for record in session.run(
        "MATCH (a:Entity)-[:INCLUDES]->(b:Entity) RETURN elementId(a) AS src, elementId(b) AS dst"
    ):
        if record["src"] in entity_ids and record["dst"] in entity_ids:
            relations.append({
                "from": entity_ids[record["src"]],
                "to": entity_ids[record["dst"]],
                "type": "INCLUT",
                "properties": {"fiabilite": FIABILITE},
            })

    # READS / INSERTS / UPDATES / DELETES / CREATES (Program->GenericFile) -> ACCEDE_A (mode R/W/RW)
    # Quasi-vide dans ce dump : la quasi-totalité des cibles R/W sont des `External/Doc`
    # (non mappés), seul `GenericFile` -> `Store_Echange` est éligible.
    access_mode: dict[tuple[str, str], set[str]] = {}
    for rel_type, mode in (
        ("READS", "R"), ("INSERTS", "W"), ("UPDATES", "W"),
        ("DELETES", "W"), ("CREATES", "W"),
    ):
        for record in session.run(
            f"MATCH (a:Entity)-[:{rel_type}]->(b:Entity {{type: 'GenericFile'}}) "
            "RETURN elementId(a) AS src, elementId(b) AS dst"
        ):
            if record["src"] not in entity_ids or record["dst"] not in entity_ids:
                continue
            pair = (entity_ids[record["src"]], entity_ids[record["dst"]])
            access_mode.setdefault(pair, set()).add(mode)

    for (from_id, to_id), modes in access_mode.items():
        mode = "RW" if modes == {"R", "W"} else next(iter(modes))
        relations.append({
            "from": from_id,
            "to": to_id,
            "type": "ACCEDE_A",
            "properties": {"fiabilite": FIABILITE, "mode": mode},
        })

    # IN_COMMUNITY (Entity->Community L1) -[:SUBCOMMUNITY_OF]-> Community L2 -> APPARTIENT_DOMAINE (Ext #4)
    # Les Entity sont rattachées à des communautés de niveau 1 ; seules les
    # communautés de niveau 2 sont mappées en Domaine_Fonctionnel (cf. fetch_communities).
    for record in session.run(
        "MATCH (e:Entity)-[:IN_COMMUNITY]->(:Community {level: 1})-[:SUBCOMMUNITY_OF]->(c:Community {level: 2}) "
        "RETURN elementId(e) AS src, elementId(c) AS dst"
    ):
        if record["src"] in entity_ids and record["dst"] in community_ids:
            relations.append({
                "from": entity_ids[record["src"]],
                "to": community_ids[record["dst"]],
                "type": "APPARTIENT_DOMAINE",
                "properties": {"fiabilite": FIABILITE},
            })

    # EXECUTES (BatchJob->Program) -> CONTIENT_PROGRAMME (Ext #4)
    # Restreint à Program : EXECUTES contient aussi BatchJob->External/Doc et
    # BatchJob->BatchJob, hors périmètre de CONTIENT_PROGRAMME (Job_Batch->Composant).
    for record in session.run(
        "MATCH (a:Entity)-[:EXECUTES]->(b:Entity {type: 'Program'}) "
        "RETURN elementId(a) AS src, elementId(b) AS dst"
    ):
        if record["src"] in entity_ids and record["dst"] in entity_ids:
            relations.append({
                "from": entity_ids[record["src"]],
                "to": entity_ids[record["dst"]],
                "type": "CONTIENT_PROGRAMME",
                "properties": {"fiabilite": FIABILITE},
            })

    return relations


def build_payload() -> dict:
    driver = GraphDatabase.driver(NEO4J_URI, auth=("neo4j", NEO4J_PASSWORD))
    try:
        with driver.session() as session:
            entity_nodes, entity_ids = fetch_entities(session)
            community_nodes, community_ids = fetch_communities(session)
            relations = fetch_relations(session, entity_ids, community_ids)
    finally:
        driver.close()

    return {"nodes": entity_nodes + community_nodes, "relations": relations}


def summarize(payload: dict) -> None:
    label_counts: dict[str, int] = {}
    for n in payload["nodes"]:
        label_counts[n["label"]] = label_counts.get(n["label"], 0) + 1
    rel_counts: dict[str, int] = {}
    for r in payload["relations"]:
        rel_counts[r["type"]] = rel_counts.get(r["type"], 0) + 1

    print(f"Nœuds : {len(payload['nodes'])}")
    for label, n in sorted(label_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {label}: {n}")
    print(f"Relations : {len(payload['relations'])}")
    for rel_type, n in sorted(rel_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {rel_type}: {n}")


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="écrit graphrag_mapped.json sans appeler ADG-M")
    group.add_argument("--apply", action="store_true", help="POST vers fn-adgm-graph/admin/import-entities")
    args = parser.parse_args()

    payload = build_payload()
    summarize(payload)

    if args.dry_run:
        out_path = os.path.join(os.path.dirname(__file__), "graphrag_mapped.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"\nÉcrit dans {out_path} (--apply pour fusionner dans ADG-M)")
        return

    with httpx.Client(timeout=120.0) as client:
        resp = client.post(f"{ADGM_BASE}/admin/import-entities", json=payload)
        resp.raise_for_status()
        print("\nImporté :", resp.json())


if __name__ == "__main__":
    main()
