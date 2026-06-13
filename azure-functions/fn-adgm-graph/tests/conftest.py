"""Fixtures pytest pour les tests d'intégration du module Exploration (T0-T-01).

Charge le seed `azure-functions/db/exploration_seed.cypher` (16 nœuds
:ArchiMateElement sur les 7 layers + 12 relations, tous tagués `seedTest: true`)
dans la base Neo4j configurée via NEO4J_BOLT_URI/NEO4J_PASSWORD (mêmes variables
que function_app.py), puis nettoie ce sous-graphe en fin de session via
`cleanup_test_data()`.

Voir notebooklm-azure/docs/specs/PLAN_EXPLORATION_v1.md (T0-T-01).
"""

import os
from pathlib import Path

import pytest
from neo4j import GraphDatabase

NEO4J_URI = os.getenv("NEO4J_BOLT_URI", "bolt://localhost:7687")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "neo4j")

SEED_CYPHER_PATH = Path(__file__).resolve().parents[2] / "db" / "exploration_seed.cypher"


def cleanup_test_data(driver):
    """Supprime tout le sous-graphe de seed (nœuds + relations seedTest:true)."""
    with driver.session() as session:
        session.run("MATCH (n:ArchiMateElement {seedTest: true}) DETACH DELETE n")


def _load_seed_statements():
    """Découpe exploration_seed.cypher en instructions exécutables (ignore
    commentaires `//` et la section nettoyage commentée en fin de fichier)."""
    text = SEED_CYPHER_PATH.read_text(encoding="utf-8")
    statements = []
    for raw_statement in text.split(";"):
        lines = [
            line for line in raw_statement.splitlines()
            if line.strip() and not line.strip().startswith("//")
        ]
        statement = "\n".join(lines).strip()
        if statement:
            statements.append(statement)
    return statements


@pytest.fixture(scope="session")
def neo4j_driver():
    driver = GraphDatabase.driver(NEO4J_URI, auth=("neo4j", NEO4J_PASSWORD))
    try:
        driver.verify_connectivity()
    except Exception as exc:
        pytest.skip(f"Neo4j inaccessible ({NEO4J_URI}) : {exc}")
    yield driver
    driver.close()


@pytest.fixture(scope="session")
def seed_exploration_graph(neo4j_driver):
    """Charge le seed une fois par session de tests, le nettoie à la fin."""
    cleanup_test_data(neo4j_driver)
    with neo4j_driver.session() as session:
        for statement in _load_seed_statements():
            session.run(statement)
    yield neo4j_driver
    cleanup_test_data(neo4j_driver)
