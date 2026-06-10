"""
Azure Functions — ADG-M Ingestion Pipeline
Module : fn-adgm-ingest (Python 3.11, runtime v4)

Fonctionne:
- F1.1 : Ingestion pipeline (GPT-4o extraction)
Trigger : Azure Blob Storage (retrodocs/incoming/*.md)

Dépendances (requirements.txt) :
  azure-functions
  azure-storage-blob
  azure-identity
  openai
  neo4j
  pyodbc
  pydantic

Authentification Azure OpenAI :
  Le compte oai-nlmazure-prod a disableLocalAuth=true (pas de clé API).
  L'authentification se fait exclusivement via Managed Identity + role RBAC
  "Cognitive Services OpenAI User" (assigné à l'identité système de cette
  Function App lors du provisioning, voir SPRINT0_setup-azure.ps1 étape 7).
"""

import azure.functions as func
import json
import logging
from datetime import datetime
from typing import List, Dict, Any
from neo4j import GraphDatabase
import pyodbc
from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
import os

# ============================================================================
# Configuration
# ============================================================================

NEO4J_URI = os.getenv("NEO4J_BOLT_URI", "bolt://localhost:7687")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
SQL_CONNECTION_STRING = os.getenv("SQL_CONNECTION_STRING")
OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
OPENAI_GPT4O_DEPLOYMENT = os.getenv("AZURE_OPENAI_GPT4O_DEPLOYMENT", "gpt-4o")

logger = logging.getLogger(__name__)

# ============================================================================
# Azure OpenAI client (Managed Identity -- disableLocalAuth=true sur
# oai-nlmazure-prod, aucune clé API n'est disponible). DefaultAzureCredential
# utilise l'identité système de la Function App en production et la session
# `az login` de l'utilisateur en local (func start).
# ============================================================================

_token_provider = get_bearer_token_provider(
    DefaultAzureCredential(),
    "https://cognitiveservices.azure.com/.default"
)

_openai_client = None

def get_openai_client() -> AzureOpenAI:
    global _openai_client
    if not _openai_client:
        _openai_client = AzureOpenAI(
            azure_endpoint=OPENAI_ENDPOINT,
            azure_ad_token_provider=_token_provider,
            api_version="2024-08-01-preview"
        )
    return _openai_client

# ============================================================================
# Neo4j Driver (singleton)
# ============================================================================

_neo4j_driver = None

def get_neo4j_driver():
    global _neo4j_driver
    if not _neo4j_driver:
        _neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=("neo4j", NEO4J_PASSWORD))
    return _neo4j_driver

# ============================================================================
# GPT-4o Extraction — Entités et Relations
# ============================================================================

def extract_entities_and_relations(markdown_content: str) -> Dict[str, Any]:
    """
    Parse rétro-doc ArchiMind Markdown via GPT-4o.

    Les rétro-docs ArchiMind ont cette structure typique :
    - Section "Cartographie Macro des Domaines" : tableau | Domaine | Description | Programmes | Mots-clés |
    - Section "Composants du produit" : tableau | Composant | Rôle | Responsabilités |
    - Section "Interactions entre composants" : tableau | Interaction | Description | Objectif |
    - Sections "Hotspots" : SPOF, dépendances critiques
    - Sections "Technologies clés" : COBOL, CICS, VSAM, MQ, Datacom, DB2, IMS

    Retour : {
      "entities": [
        {"id": "unique-slug", "name": "...", "type": "System|Module|Service|Database|API|ExternalSystem",
         "description": "...", "language": "...", "sloc": N, "criticality": "CRITICAL|HIGH|MEDIUM|LOW",
         "businessValue": "HIGH|MEDIUM|LOW", "programs": "prog1, prog2"}
      ],
      "relations": [
        {"source": "id1", "target": "id2", "type": "CALLS|DATABASE|FILE|NETWORK|CONTAINS",
         "confidence": 0.95, "description": "..."}
      ]
    }
    """
    client = get_openai_client()

    system_prompt = """Tu es un expert en architecture legacy mainframe et en modernisation d'applications.
Tu analyses des documents de rétro-documentation générés par ArchiMind, un outil d'analyse de code COBOL/CICS.
Ces documents décrivent des applications mainframe z/OS avec des composants COBOL, CICS, VSAM, IBM MQ, DB2, IMS.

Règles d'extraction :
1. Chaque "Domaine Fonctionnel" dans les tableaux de cartographie devient une entité de type "Module"
2. Le système racine (ex: "FL Fruits & Légumes", "CardDemo") devient une entité de type "System"
3. Les fichiers VSAM, DB2, Datacom deviennent des entités de type "Database"
4. Les systèmes externes (WMS, supervision, partenaires) deviennent des entités de type "ExternalSystem"
5. Les wrappers techniques (MQ wrapper, Datacom wrapper) deviennent des entités de type "Service"
6. Les "Hotspots" et "SPOF" identifiés dans le document → criticality = CRITICAL
7. Les relations viennent des sections "Interactions entre composants" et "Dépendances"
8. Préfixer les ids avec un slug du système (ex: "fl-mod-" pour FL, "card-mod-" pour CardDemo)
9. Retourner UNIQUEMENT du JSON valide, sans markdown, sans explication."""

    user_prompt = f"""Analyse ce document de rétro-documentation ArchiMind et extrais toutes les entités et relations architecturales.

Format JSON strict :
{{
  "system_name": "Nom de l'application principale",
  "entities": [
    {{
      "id": "slug-unique-kebab-case",
      "name": "Nom lisible",
      "type": "System|Module|Service|Database|API|ExternalSystem",
      "description": "Description en 1-2 phrases max",
      "language": "COBOL|CICS|DB2|VSAM|IMS|MQ|Python|Java|N/A",
      "sloc": 0,
      "criticality": "CRITICAL|HIGH|MEDIUM|LOW",
      "businessValue": "HIGH|MEDIUM|LOW",
      "programs": "liste des programmes (ex: FLECOPD, FLRGE1D)"
    }}
  ],
  "relations": [
    {{
      "source": "id-source",
      "target": "id-target",
      "type": "CALLS|DATABASE|FILE|NETWORK|CONTAINS",
      "confidence": 0.9,
      "description": "Pourquoi cette dépendance existe"
    }}
  ]
}}

Document ArchiMind (extrait) :
{markdown_content[:8000]}"""

    response = client.chat.completions.create(
        model=OPENAI_GPT4O_DEPLOYMENT,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.1,
        max_tokens=4000,
        response_format={"type": "json_object"}
    )

    try:
        result = json.loads(response.choices[0].message.content)
        return result
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse GPT-4o response: {e}")
        return {"entities": [], "relations": []}

# ============================================================================
# Neo4j Operations
# ============================================================================

def create_or_update_components(driver, entities: List[Dict]) -> int:
    """Crée ou met à jour les nœuds Component dans Neo4j."""
    created_count = 0

    with driver.session() as session:
        for entity in entities:
            query = """
            MERGE (c:Component {id: $id})
            SET c.name = $name,
                c.type = $type,
                c.description = $description,
                c.language = $language,
                c.sloc = $sloc,
                c.lastUpdated = datetime()
            RETURN c
            """
            result = session.run(query, {
                "id": entity.get("id"),
                "name": entity.get("name"),
                "type": entity.get("type"),
                "description": entity.get("description"),
                "language": entity.get("language"),
                "sloc": entity.get("sloc", 0)
            })
            if result.consume().counters.nodes_created > 0:
                created_count += 1

    return created_count

def create_or_update_relations(driver, relations: List[Dict]) -> int:
    """Crée ou met à jour les arcs DEPENDS_ON dans Neo4j."""
    created_count = 0

    with driver.session() as session:
        for rel in relations:
            query = """
            MATCH (source:Component {id: $source}), (target:Component {id: $target})
            MERGE (source)-[r:DEPENDS_ON]->(target)
            SET r.type = $type, r.confidence = $confidence
            RETURN r
            """
            result = session.run(query, {
                "source": rel.get("source"),
                "target": rel.get("target"),
                "type": rel.get("type"),
                "confidence": rel.get("confidence", 0.9)
            })
            if result.consume().counters.relationships_created > 0:
                created_count += 1

    return created_count

# ============================================================================
# SQL Logging (audit trail)
# ============================================================================

def log_ingestion_to_sql(file_name: str, status: str, component_count: int, relation_count: int):
    """Log l'ingestion en SQL pour traçabilité."""
    try:
        conn = pyodbc.connect(SQL_CONNECTION_STRING)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO dbo.AuditLog (tableName, operation, recordId, changedBy, details)
            VALUES (?, ?, ?, ?, ?)
        """, (
            "Component",
            "BULK_INSERT",
            file_name,
            "fn-adgm-ingest",
            json.dumps({
                "components_created": component_count,
                "relations_created": relation_count,
                "source_file": file_name,
                "timestamp": datetime.utcnow().isoformat()
            })
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"SQL logging failed: {e}")

# ============================================================================
# Azure Function — Blob Trigger
# ============================================================================

def main(myblob: func.InputStream):
    """
    Trigger : Blob incoming (nouvelle rétro-doc uploadée)
    Pipeline :
      1. Lire fichier Markdown
      2. GPT-4o extraction
      3. Créer nodes/arcs Neo4j
      4. Log SQL
    """
    logger.info(f"Processing blob: {myblob.name}")

    try:
        # 1. Lire contenu
        content = myblob.read().decode('utf-8')
        logger.info(f"Read {len(content)} bytes from {myblob.name}")

        # 2. GPT-4o extraction
        logger.info("Calling GPT-4o for extraction...")
        extracted = extract_entities_and_relations(content)
        entities = extracted.get("entities", [])
        relations = extracted.get("relations", [])
        logger.info(f"Extracted {len(entities)} entities, {len(relations)} relations")

        # 3. Neo4j operations
        driver = get_neo4j_driver()
        components_created = create_or_update_components(driver, entities)
        relations_created = create_or_update_relations(driver, relations)
        logger.info(f"Neo4j: {components_created} components, {relations_created} relations")

        # 4. SQL logging
        log_ingestion_to_sql(myblob.name, "SUCCESS", components_created, relations_created)

        logger.info(f"✓ Ingestion complete for {myblob.name}")

    except Exception as e:
        logger.error(f"✗ Ingestion failed: {e}", exc_info=True)
        log_ingestion_to_sql(myblob.name, "FAILED", 0, 0)
        raise


# ============================================================================
# Pour tester localement :
#
# 1. requirements.txt: voir SPRINT0_requirements.txt (inclut azure-identity)
#
# 2. az login (DefaultAzureCredential utilise la session CLI en local et
#    nécessite que le compte ait le rôle "Cognitive Services OpenAI User"
#    sur oai-nlmazure-prod -- déjà le cas pour v.gicquiau via le RG existant)
#
# 3. func start (dans le répertoire function app)
#
# 4. Uploader un fichier .md en Blob pour déclencher le trigger
#
# ============================================================================
