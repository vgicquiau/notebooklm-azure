"""
Azure Functions — ADG-M Ingestion Pipeline
Module : fn-adgm-ingest (Python 3.11, runtime v4)

Fonctionne :
- F1.1 : Ingestion pipeline -- extraction GPT-4o du graphe bi-plan FunctionalNode/TechnicalNode
Trigger : Azure Blob Storage (retrodocs/incoming/*.md)
Pipeline : lecture -> extraction GPT-4o (bi-plan) -> upsert Neo4j (MERGE) -> déplacement
incoming/ -> processed/ -> traçabilité dbo.IngestionJob (cf. SDD_ADG-M_v1.md §1, périmètre v1).

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
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any
from neo4j import GraphDatabase
import pyodbc
from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.storage.blob import BlobServiceClient
import os

# ============================================================================
# Configuration
# ============================================================================

NEO4J_URI = os.getenv("NEO4J_BOLT_URI", "bolt://localhost:7687")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
SQL_CONNECTION_STRING = os.getenv("SQL_CONNECTION_STRING")
OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
OPENAI_GPT4O_DEPLOYMENT = os.getenv("AZURE_OPENAI_GPT4O_DEPLOYMENT", "gpt-4o")
BLOB_CONNECTION_STRING = os.getenv("BLOB_CONNECTION_STRING")
BLOB_CONTAINER_RETRODOCS = os.getenv("BLOB_CONTAINER_RETRODOCS", "retrodocs")

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
# Blob Service Client (singleton) -- pour le déplacement incoming/ -> processed/
# (le binding du trigger résout BLOB_CONNECTION_STRING pour la lecture ; le
# déplacement nécessite un client applicatif distinct pour écrire/supprimer).
# ============================================================================

_blob_service_client = None

def get_blob_service_client() -> BlobServiceClient:
    global _blob_service_client
    if not _blob_service_client:
        _blob_service_client = BlobServiceClient.from_connection_string(BLOB_CONNECTION_STRING)
    return _blob_service_client

# ============================================================================
# GPT-4o Extraction — Graphe bi-plan (FunctionalNode / TechnicalNode / arcs)
# ============================================================================

def extract_graph_from_retrodoc(markdown_content: str) -> Dict[str, Any]:
    """
    Extrait le graphe bi-plan d'une rétro-doc ArchiMind via GPT-4o
    (modèle cible : SDD_ADG-M_v1.md §2.1 Modèle Neo4j / §2.3 DTOs).

    Structure réelle observée dans les rétro-docs ArchiMind (cf. doc-archimind/*.md,
    plus fiable que l'hypothèse de structure du §10 du SDD) :
      "# 1. Cartographie Macro des Domaines"      -- tableau résumé (plusieurs angles/domaine)
      "# 2. Analyse Détaillée par Domaine"        -- une section "## Domaine : <Nom> (<Détail>)"
                                                       par domaine, avec §2.1 Modèle de Données /
                                                       §2.2 Processus & Règles / §2.3 Flux & Interfaces
      "# 3. Matrice des Interactions Inter-Domaines" -- dépendances croisées entre domaines

    Retour :
    {
      "functionalNodes": [
        {"domain", "subdomain", "processes": [...], "sharedBusinessObjects": [...],
         "modernizationStatus": "EXISTING|IN_TRANSITION|TARGET", "docCoveragePercent": 0-100}
      ],
      "technicalNodes": [
        {"componentName", "technology": "COBOL|JCL|PL1|PACBASE|JAVA|DOTNET|OTHER",
         "linesOfCode": int, "callFrequency": "HIGH|MEDIUM|LOW|UNKNOWN", "knowledgeOwner",
         "regulatoryTags": [...], "docCoveragePercent": 0-100, "isGhost": bool}
      ],
      "functionalDependsOn": [
        {"sourceDomain", "targetDomain", "dataFormat": str|None,
         "direction": "UNIDIRECTIONAL|BIDIRECTIONAL", "criticality": "CRITICAL|HIGH|MEDIUM|LOW"}
      ],
      "technicalDependsOn": [
        {"sourceComponentName", "targetComponentName",
         "arcType": "TECHNICAL_CALL_SYNC|TECHNICAL_CALL_ASYNC|TECHNICAL_BATCH|DATA_FLOW|TRANSITIONAL_COHABITATION",
         "dataFormat": str|None, "direction": "UNIDIRECTIONAL|BIDIRECTIONAL",
         "criticality": "CRITICAL|HIGH|MEDIUM|LOW"}
      ],
      "realizedBy": [{"domain", "componentName"}]
    }
    """
    client = get_openai_client()

    system_prompt = """Tu es un expert en architecture legacy mainframe et en modernisation d'applications.
Tu analyses des rétro-documentations ArchiMind décrivant des applications COBOL/CICS/JCL/VSAM/MQ z/OS,
afin de construire le graphe de dépendances bi-plan d'ADG-M (Architecture Dependency Graph for Modernization).

LE MODÈLE BI-PLAN -- deux plans reliés UNIQUEMENT par des liens REALIZED_BY (jamais de DEPENDS_ON entre les deux) :

1. PLAN FONCTIONNEL -- FunctionalNode = un domaine métier ("ce que fait le système")
   Une FunctionalNode par section "## Domaine : <Nom> (<Détail>)" de "Analyse Détaillée par Domaine"
   -- PAS une par ligne du tableau de "Cartographie Macro" (ce tableau regroupe plusieurs angles
   d'un même domaine sous des intitulés voisins, il n'énumère pas les domaines un par un).
   - domain : nom métier court et stable (ex: "Référentiel Produit", "Logistique")
   - subdomain : angle/périmètre de cette section précise (souvent le détail entre parenthèses du titre)
   - processes : intitulés des "Processus Clés" (§2.2, ex: "Extraction OP hebdomadaire (batch FLECOPD)")
   - sharedBusinessObjects : colonne "Entité Métier" des tableaux "Modèle de Données" (§2.1)
   - modernizationStatus : "EXISTING" par défaut (système legacy déjà en place -- quasi toujours
     le cas dans une rétro-doc) ; "IN_TRANSITION" seulement si le texte décrit une transition en cours

2. PLAN TECHNIQUE -- TechnicalNode = un composant exécutable ("comment il le fait")
   Un TechnicalNode par composant exécutable nommé : programme batch/CICS/online, job, wrapper,
   service (ex: FLECOPD, FLZA12C, UDSBQ0D) -- qu'il soit détaillé en profondeur ou seulement cité
   comme dépendance. componentName = le code/identifiant écrit dans le document.
   NE PAS créer de TechnicalNode pour des structures de données pures -- tables référentielles,
   fichiers, copybooks, formats de message (ex: FH3, BG2, IQ7, COPYBOOK-CMD01, FLTE9BWL) :
   elles vont dans sharedBusinessObjects (si pertinentes côté métier) ou dataFormat (sur les arcs).

3. ARCS DEPENDS_ON -- toujours intra-plan :
   - functionalDependsOn relie deux domaines -- dépendances domaine-à-domaine de la section
     "Matrice des Interactions Inter-Domaines" et des "Liens inter-domaines"
   - technicalDependsOn relie deux composants : appel direct (CICS XCTL/CALL) -> TECHNICAL_CALL_SYNC,
     échange messages/MQ -> TECHNICAL_CALL_ASYNC, chaînage/ordonnancement batch -> TECHNICAL_BATCH,
     échange fichier/copybook -> DATA_FLOW, cohabitation transitoire (rare en legacy pur) ->
     TRANSITIONAL_COHABITATION

4. REALIZED_BY -- seul pont entre les plans : quel(s) composant(s) réalise(nt) quel domaine
   (typiquement les programmes cités dans les "Processus Clés" du domaine et dans la colonne
   "Volumétrie" de la cartographie macro pour ce domaine). N'émets le lien que si le texte
   établit clairement le rattachement programme -> domaine.

RÈGLES DE VALORISATION DES CHAMPS
- candidate7R : ne le génère JAMAIS -- le pipeline le valorise systématiquement à "UNQUALIFIED"
  (c'est une décision humaine ultérieure, pas une extraction documentaire).
- isGhost = true si le composant n'apparaît QUE comme cible/source de dépendance, sans section
  ni paragraphe qui explique son fonctionnement -- le document le signale parfois explicitement
  ("non fourni", "non présent dans le dépôt", "programmes cibles non fournis"). Pour un ghost,
  docCoveragePercent doit rester bas (0-20).
- docCoveragePercent (0-100, par paliers de 10) : estime ce que LE DOCUMENT explique de CE
  composant/domaine précis -- règles/flux détaillés en profondeur -> haut, juste cité dans une
  liste/tableau -> bas, ghost -> proche de 0. N'invente pas une précision que le texte n'a pas.
- technology : "COBOL" par défaut (corpus très majoritairement COBOL/CICS) ; "JCL" seulement si
  le document désigne explicitement un script de contrôle de job distinct du programme COBOL
  invoqué ; "PACBASE" pour les éléments de socle explicitement décrits comme générés par PACBASE.
- linesOfCode = 0 si le document ne donne pas de chiffre explicite (ne pas inventer de précision).
- knowledgeOwner = "TACIT" par défaut (un nom d'expert nommé est rarissime dans ce type de document).
- regulatoryTags = [] par défaut ; n'ajoute "DORA"/"BCBS239"/"NIS2"/"AI_ACT" que si le document
  mentionne explicitement l'enjeu réglementaire correspondant.
- callFrequency mesure la SOLLICITATION par d'autres composants, PAS le calendrier d'exécution
  batch (hebdomadaire/quotidien...) : "HIGH" si rôle de hub/SPOF/forte sollicitation explicite,
  "MEDIUM" si réutilisation modérée, "LOW" si composant isolé, "UNKNOWN" si aucun indice.
- Arcs -- dataFormat : nom du fichier/copybook/message si le document le nomme (ex: "FLTE9BWL"),
  sinon null. direction = "UNIDIRECTIONAL" sauf échange explicitement bidirectionnel décrit.
  criticality : "CRITICAL"/"HIGH" si le document qualifie la dépendance de hotspot/SPOF/critique,
  "MEDIUM"/"LOW" selon le ton du texte sinon.

Retourne UNIQUEMENT du JSON valide conforme au schéma du message utilisateur -- sans markdown, sans explication."""

    user_prompt = f"""Analyse cette rétro-documentation ArchiMind et extrais le graphe bi-plan complet
(domaines fonctionnels, composants techniques, dépendances intra-plan, liens de réalisation)
selon le modèle et les règles définis dans le system prompt.

Format JSON strict :
{{
  "functionalNodes": [
    {{
      "domain": "nom métier court",
      "subdomain": "angle/périmètre de cette section",
      "processes": ["intitulé processus 1", "..."],
      "sharedBusinessObjects": ["entité métier 1", "..."],
      "modernizationStatus": "EXISTING|IN_TRANSITION|TARGET",
      "docCoveragePercent": 0
    }}
  ],
  "technicalNodes": [
    {{
      "componentName": "CODE-COMPOSANT",
      "technology": "COBOL|JCL|PL1|PACBASE|JAVA|DOTNET|OTHER",
      "linesOfCode": 0,
      "callFrequency": "HIGH|MEDIUM|LOW|UNKNOWN",
      "knowledgeOwner": "TACIT",
      "regulatoryTags": [],
      "docCoveragePercent": 0,
      "isGhost": false
    }}
  ],
  "functionalDependsOn": [
    {{
      "sourceDomain": "domaine source", "targetDomain": "domaine cible",
      "dataFormat": null, "direction": "UNIDIRECTIONAL|BIDIRECTIONAL",
      "criticality": "CRITICAL|HIGH|MEDIUM|LOW"
    }}
  ],
  "technicalDependsOn": [
    {{
      "sourceComponentName": "composant source", "targetComponentName": "composant cible",
      "arcType": "TECHNICAL_CALL_SYNC|TECHNICAL_CALL_ASYNC|TECHNICAL_BATCH|DATA_FLOW|TRANSITIONAL_COHABITATION",
      "dataFormat": "nom du format ou null", "direction": "UNIDIRECTIONAL|BIDIRECTIONAL",
      "criticality": "CRITICAL|HIGH|MEDIUM|LOW"
    }}
  ],
  "realizedBy": [
    {{"domain": "domaine réalisé", "componentName": "composant qui le réalise"}}
  ]
}}

Document ArchiMind (rétro-documentation complète, éventuellement tronquée si très volumineuse) :
{markdown_content[:150000]}"""

    response = client.chat.completions.create(
        model=OPENAI_GPT4O_DEPLOYMENT,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.1,
        max_tokens=16000,
        response_format={"type": "json_object"}
    )

    try:
        return json.loads(response.choices[0].message.content)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse GPT-4o response: {e}")
        return {"functionalNodes": [], "technicalNodes": [], "functionalDependsOn": [],
                "technicalDependsOn": [], "realizedBy": []}

# ============================================================================
# Neo4j Operations — upserts bi-plan (MERGE = ré-ingestion sûre, cf. SDD §2.1)
# ============================================================================

def upsert_functional_nodes(driver, nodes: List[Dict], source_doc_id: str, now_iso: str) -> tuple[int, int]:
    """MERGE keyed on domain -- un même domaine évoqué dans plusieurs rétro-docs s'enrichit
    au lieu de se dupliquer (id/createdAt valorisés une seule fois, à la création)."""
    created = 0
    with driver.session() as session:
        for node in nodes:
            result = session.run(
                """
                MERGE (fn:FunctionalNode {domain: $domain})
                ON CREATE SET fn.id = randomUUID(), fn.type = 'functional', fn.createdAt = $now
                SET fn.subdomain = $subdomain,
                    fn.processes = $processes,
                    fn.sharedBusinessObjects = $sharedBusinessObjects,
                    fn.docCoveragePercent = $docCoveragePercent,
                    fn.modernizationStatus = $modernizationStatus,
                    fn.sourceDocIds = CASE WHEN $sourceDocId IN coalesce(fn.sourceDocIds, [])
                                           THEN coalesce(fn.sourceDocIds, [])
                                           ELSE coalesce(fn.sourceDocIds, []) + $sourceDocId END,
                    fn.updatedAt = $now
                """,
                {
                    "domain": node.get("domain"),
                    "subdomain": node.get("subdomain"),
                    "processes": node.get("processes", []),
                    "sharedBusinessObjects": node.get("sharedBusinessObjects", []),
                    "docCoveragePercent": node.get("docCoveragePercent", 0),
                    "modernizationStatus": node.get("modernizationStatus", "EXISTING"),
                    "sourceDocId": source_doc_id,
                    "now": now_iso,
                }
            )
            if result.consume().counters.nodes_created > 0:
                created += 1
    return created, len(nodes) - created


def upsert_technical_nodes(driver, nodes: List[Dict], source_doc_id: str, now_iso: str) -> tuple[int, int]:
    """MERGE keyed on componentName (contrainte d'unicité technical_component_name).
    candidate7R n'est valorisé qu'à la création (ON CREATE) : une qualification 7R ultérieure
    (PATCH .../qualification, hors-périmètre ici) ne doit jamais être écrasée par une ré-ingestion.
    criticalityScore/betweenness/isSPOF/clusterId ne sont PAS écrits ici -- propriétés calculées
    par les jobs d'analyse F1.3/F1.5 (cf. commentaire SDD §2.1), pas par l'ingestion."""
    created = 0
    with driver.session() as session:
        for node in nodes:
            result = session.run(
                """
                MERGE (tn:TechnicalNode {componentName: $componentName})
                ON CREATE SET tn.id = randomUUID(), tn.type = 'technical',
                              tn.candidate7R = 'UNQUALIFIED', tn.createdAt = $now
                SET tn.technology = $technology,
                    tn.linesOfCode = $linesOfCode,
                    tn.callFrequency = $callFrequency,
                    tn.knowledgeOwner = $knowledgeOwner,
                    tn.regulatoryTags = $regulatoryTags,
                    tn.docCoveragePercent = $docCoveragePercent,
                    tn.isGhost = $isGhost,
                    tn.sourceDocIds = CASE WHEN $sourceDocId IN coalesce(tn.sourceDocIds, [])
                                           THEN coalesce(tn.sourceDocIds, [])
                                           ELSE coalesce(tn.sourceDocIds, []) + $sourceDocId END,
                    tn.updatedAt = $now
                """,
                {
                    "componentName": node.get("componentName"),
                    "technology": node.get("technology", "OTHER"),
                    "linesOfCode": node.get("linesOfCode", 0),
                    "callFrequency": node.get("callFrequency", "UNKNOWN"),
                    "knowledgeOwner": node.get("knowledgeOwner", "TACIT"),
                    "regulatoryTags": node.get("regulatoryTags", []),
                    "docCoveragePercent": node.get("docCoveragePercent", 0),
                    "isGhost": node.get("isGhost", False),
                    "sourceDocId": source_doc_id,
                    "now": now_iso,
                }
            )
            if result.consume().counters.nodes_created > 0:
                created += 1
    return created, len(nodes) - created


def create_functional_arcs(driver, arcs: List[Dict]) -> int:
    """DEPENDS_ON{arcType:'FUNCTIONAL'} entre deux FunctionalNode (clé domain).
    La paire (source,target,arcType) identifie l'arc -- id stable assigné une seule fois ;
    dataFormat/direction/criticality rafraîchis à chaque ré-ingestion (meilleure relecture GPT-4o)."""
    created = 0
    with driver.session() as session:
        for arc in arcs:
            result = session.run(
                """
                MATCH (source:FunctionalNode {domain: $sourceDomain})
                MATCH (target:FunctionalNode {domain: $targetDomain})
                MERGE (source)-[r:DEPENDS_ON {arcType: 'FUNCTIONAL'}]->(target)
                ON CREATE SET r.id = randomUUID()
                SET r.dataFormat = $dataFormat, r.direction = $direction, r.criticality = $criticality
                """,
                {
                    "sourceDomain": arc.get("sourceDomain"),
                    "targetDomain": arc.get("targetDomain"),
                    "dataFormat": arc.get("dataFormat"),
                    "direction": arc.get("direction", "UNIDIRECTIONAL"),
                    "criticality": arc.get("criticality", "MEDIUM"),
                }
            )
            created += result.consume().counters.relationships_created
    return created


def create_technical_arcs(driver, arcs: List[Dict]) -> int:
    """DEPENDS_ON{arcType: TECHNICAL_*|DATA_FLOW|TRANSITIONAL_COHABITATION} entre deux
    TechnicalNode (clé componentName). Même logique de MERGE que les arcs fonctionnels --
    voir create_functional_arcs."""
    created = 0
    with driver.session() as session:
        for arc in arcs:
            result = session.run(
                """
                MATCH (source:TechnicalNode {componentName: $sourceComponentName})
                MATCH (target:TechnicalNode {componentName: $targetComponentName})
                MERGE (source)-[r:DEPENDS_ON {arcType: $arcType}]->(target)
                ON CREATE SET r.id = randomUUID()
                SET r.dataFormat = $dataFormat, r.direction = $direction, r.criticality = $criticality
                """,
                {
                    "sourceComponentName": arc.get("sourceComponentName"),
                    "targetComponentName": arc.get("targetComponentName"),
                    "arcType": arc.get("arcType", "TECHNICAL_CALL_SYNC"),
                    "dataFormat": arc.get("dataFormat"),
                    "direction": arc.get("direction", "UNIDIRECTIONAL"),
                    "criticality": arc.get("criticality", "MEDIUM"),
                }
            )
            created += result.consume().counters.relationships_created
    return created


def create_realized_by_links(driver, links: List[Dict]) -> int:
    """REALIZED_BY -- seul pont bi-plan : (FunctionalNode)-[:REALIZED_BY]->(TechnicalNode).
    Lien structurel pur (pas de propriétés), MERGE idempotent."""
    created = 0
    with driver.session() as session:
        for link in links:
            result = session.run(
                """
                MATCH (fn:FunctionalNode {domain: $domain})
                MATCH (tn:TechnicalNode {componentName: $componentName})
                MERGE (fn)-[r:REALIZED_BY]->(tn)
                """,
                {"domain": link.get("domain"), "componentName": link.get("componentName")}
            )
            created += result.consume().counters.relationships_created
    return created

# ============================================================================
# Déplacement Blob — incoming/ -> processed/ (SDD §1 : périmètre v1 explicite)
# ============================================================================

def move_blob_to_processed(content: str, source_path: str) -> str:
    """Azure Blob Storage n'a pas d'opération de déplacement atomique : on recopie le
    contenu déjà lu (évite un aller-retour réseau pour un fichier de quelques 100 Ko)
    vers processed/<reste-du-chemin>, puis on supprime l'original. source_path est
    garanti préfixé par 'incoming/' (chemin du binding du trigger)."""
    dest_path = "processed/" + source_path[len("incoming/"):]
    container = get_blob_service_client().get_container_client(BLOB_CONTAINER_RETRODOCS)
    container.upload_blob(name=dest_path, data=content.encode("utf-8"), overwrite=True)
    container.delete_blob(source_path)
    return dest_path

# ============================================================================
# SQL Logging — traçabilité des ingestions (dbo.IngestionJob, SDD §2.2)
# ============================================================================

def log_ingestion_job(job_id: str, blob_path: str, source_doc_id: str, status: str,
                       nodes_created: int, nodes_updated: int, arcs_created: int,
                       ghosts_detected: int, started_at: datetime, error_message: str = None):
    """Une ligne par job, écrite à l'issue du traitement (succès ou échec) -- remplace
    l'ancien write générique vers dbo.AuditLog par la table dédiée F1.1 du nouveau schéma."""
    try:
        conn = pyodbc.connect(SQL_CONNECTION_STRING)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO dbo.IngestionJob
                (jobId, blobPath, sourceDocId, status, nodesCreated, nodesUpdated,
                 arcsCreated, ghostsDetected, errorMessage, startedAt, finishedAt)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, SYSUTCDATETIME())
            """,
            (job_id, blob_path, source_doc_id, status, nodes_created, nodes_updated,
             arcs_created, ghosts_detected, error_message, started_at)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"SQL logging failed: {e}")

# ============================================================================
# Azure Function — Blob Trigger
# ============================================================================

def main(myblob: func.InputStream):
    """
    Trigger : Blob incoming (nouvelle rétro-doc uploadée dans retrodocs/incoming/)
    Pipeline (SDD §1, périmètre v1) :
      1. Lire le Markdown
      2. GPT-4o : extraction du graphe bi-plan (domaines, composants, arcs, liens REALIZED_BY)
      3. Neo4j : upsert nœuds + arcs (MERGE -- ré-ingestion sûre)
      4. Déplacement incoming/ -> processed/
      5. Traçabilité dans dbo.IngestionJob
    """
    job_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    now_iso = started_at.strftime("%Y-%m-%dT%H:%M:%SZ")

    container_prefix = f"{BLOB_CONTAINER_RETRODOCS}/"
    blob_path = myblob.name[len(container_prefix):] if myblob.name.startswith(container_prefix) else myblob.name
    source_doc_id = os.path.basename(blob_path)

    logger.info(f"[{job_id}] Processing blob: {blob_path}")

    nodes_created = nodes_updated = arcs_created = ghosts_detected = 0

    try:
        # 1. Lire contenu
        content = myblob.read().decode('utf-8')
        logger.info(f"[{job_id}] Read {len(content)} characters from {blob_path}")

        # 2. GPT-4o extraction (graphe bi-plan)
        logger.info(f"[{job_id}] Calling GPT-4o for bi-plan extraction...")
        extracted = extract_graph_from_retrodoc(content)
        functional_nodes = extracted.get("functionalNodes", [])
        technical_nodes = extracted.get("technicalNodes", [])
        functional_arcs = extracted.get("functionalDependsOn", [])
        technical_arcs = extracted.get("technicalDependsOn", [])
        realized_by = extracted.get("realizedBy", [])
        ghosts_detected = sum(1 for n in technical_nodes if n.get("isGhost"))

        logger.info(
            f"[{job_id}] Extracted {len(functional_nodes)} functional + {len(technical_nodes)} technical "
            f"nodes ({ghosts_detected} ghosts), {len(functional_arcs) + len(technical_arcs)} arcs, "
            f"{len(realized_by)} realizedBy links"
        )

        if not functional_nodes and not technical_nodes:
            raise ValueError("Extraction infructueuse : aucun nœud détecté")

        # 3. Neo4j -- upserts bi-plan
        driver = get_neo4j_driver()
        fn_created, fn_updated = upsert_functional_nodes(driver, functional_nodes, source_doc_id, now_iso)
        tn_created, tn_updated = upsert_technical_nodes(driver, technical_nodes, source_doc_id, now_iso)
        nodes_created, nodes_updated = fn_created + tn_created, fn_updated + tn_updated

        arcs_created = (
            create_functional_arcs(driver, functional_arcs)
            + create_technical_arcs(driver, technical_arcs)
            + create_realized_by_links(driver, realized_by)
        )
        logger.info(
            f"[{job_id}] Neo4j: {nodes_created} nœuds créés, {nodes_updated} mis à jour, "
            f"{arcs_created} arcs/liens créés"
        )

        # 4. Déplacement incoming/ -> processed/
        processed_path = move_blob_to_processed(content, blob_path)
        logger.info(f"[{job_id}] Blob déplacé vers {processed_path}")

        # 5. Traçabilité SQL
        log_ingestion_job(job_id, blob_path, source_doc_id, "SUCCESS", nodes_created, nodes_updated,
                          arcs_created, ghosts_detected, started_at)

        logger.info(f"✓ [{job_id}] Ingestion terminée pour {blob_path} -> {processed_path}")

    except Exception as e:
        logger.error(f"✗ [{job_id}] Ingestion failed: {e}", exc_info=True)
        log_ingestion_job(job_id, blob_path, source_doc_id, "FAILED", nodes_created, nodes_updated,
                          arcs_created, ghosts_detected, started_at, error_message=str(e))
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
# 4. Uploader un fichier .md dans retrodocs/incoming/ pour déclencher le trigger
#    (le fichier est déplacé vers retrodocs/processed/ une fois l'ingestion réussie)
#
# ============================================================================
