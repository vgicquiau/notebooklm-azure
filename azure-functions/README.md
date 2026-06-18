# Azure Functions — Backend Graphe ADG-M

Source des deux Azure Functions Python qui alimentent la vue **Graphe ADG-M** de l'application (`frontend/src/GraphPage.jsx`, proxy `api/routers/graph.py` et `api/routers/extract.py`).

| Function | Trigger | Rôle |
|---|---|---|
| `fn-adgm-graph` | HTTP (anonymous) | API de lecture/écriture du graphe Neo4j (nœuds, arcs, clusters, qualification 7R, admin) |
| `fn-adgm-ingest` | Blob (`retrodocs/incoming/{name}`) | Ingestion automatique des rétro-docs déposés dans le Storage Account |

Voir [`../ADG-M_GRAPH_METHODOLOGIE.md`](../ADG-M_GRAPH_METHODOLOGIE.md) pour la méthodologie complète (typage des nœuds, pipeline d'extraction, glossaire) et la section **F7 — Graphe ADG-M** de [`../ARCHITECTURE.md`](../ARCHITECTURE.md) pour la liste détaillée des endpoints.

---

## Prérequis

> Ces functions sont actuellement **au repos** (non consommées par l'application depuis le
> retrait du graphe ADG-M, 2026-06-13) — n'installer ce qui suit que si tu repars travailler
> spécifiquement sur ce backend.

| Outil / accès | Vérifier | Installer (Windows) |
|---|---|---|
| **Python 3.11** | `py -3.11 --version` | `winget install --id Python.Python.3.11` — installer en plus d'une éventuelle autre version déjà présente (le launcher `py` permet de choisir) |
| **Azure Functions Core Tools v4** | `func --version` | `winget install Microsoft.Azure.FunctionsCoreTools` ou [doc officielle](https://learn.microsoft.com/azure/azure-functions/functions-run-local) |
| **Azure CLI** (déploiement / config appsettings) | `az --version` | `winget install --id Microsoft.AzureCLI` |
| **cypher-shell** (init schéma Neo4j) | `cypher-shell --version` | Fourni avec Neo4j Desktop, ou [téléchargement standalone](https://neo4j.com/download-center/#shell) |
| **sqlcmd** (init schéma Azure SQL) | `sqlcmd -?` | `winget install Microsoft.SqlServer.Cmd` ou [ODBC Driver 18 for SQL Server](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server) |
| Une instance **Neo4j** (AuraDB ou self-hosted) accessible en Bolt | — | Créer une instance AuraDB (gratuite) ou utiliser une instance existante |
| Une base **Azure SQL** (historique des qualifications 7R) | — | Provisionner via le Portail Azure ou `az sql db create` |
| Un **Storage Account** Azure (déclencheur Blob de `fn-adgm-ingest`) | — | Provisionner via le Portail Azure ou `az storage account create` |
| (optionnel, pour `fn-adgm-ingest`) un déploiement **Azure OpenAI GPT-4o** | — | Provisionner une ressource Azure OpenAI avec un déploiement `gpt-4o` |

---

## Variables d'environnement (`local.settings.json`)

`local.settings.json` n'est **jamais commité** (contient des chaînes de connexion). Créer ce fichier à la racine de `azure-functions/` à partir du template ci-dessous :

```json
{
  "IsEncrypted": false,
  "Values": {
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "AzureWebJobsStorage": "<connection string du Storage Account>",

    "NEO4J_BOLT_URI": "neo4j+s://<id>.databases.neo4j.io",
    "NEO4J_PASSWORD": "<mot de passe Neo4j — utilisateur 'neo4j'>",

    "SQL_CONNECTION_STRING": "Driver={ODBC Driver 18 for SQL Server};Server=tcp:<server>.database.windows.net,1433;Database=modernagent_db;Authentication=ActiveDirectoryMsi",

    "BLOB_CONNECTION_STRING": "<connection string du Storage Account>",
    "BLOB_CONTAINER_RETRODOCS": "retrodocs",

    "AZURE_OPENAI_ENDPOINT": "https://<resource>.openai.azure.com/",
    "AZURE_OPENAI_GPT4O_DEPLOYMENT": "gpt-4o",

    "SPOF_BETWEENNESS_PERCENTILE": "90"
  }
}
```

| Variable | Utilisée par | Description |
|---|---|---|
| `NEO4J_BOLT_URI` | les deux | URI Bolt de l'instance Neo4j (défaut local : `bolt://localhost:7687`) |
| `NEO4J_PASSWORD` | les deux | Mot de passe — l'utilisateur est toujours `neo4j` |
| `SQL_CONNECTION_STRING` | les deux | Chaîne ODBC vers Azure SQL (historique `dbo.NodeAnnotationHistory`) |
| `BLOB_CONNECTION_STRING` | `fn-adgm-ingest` | Connexion au Storage Account contenant `retrodocs/incoming/` |
| `BLOB_CONTAINER_RETRODOCS` | `fn-adgm-ingest` | Nom du conteneur surveillé (défaut `retrodocs`) |
| `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_GPT4O_DEPLOYMENT` | `fn-adgm-ingest` | Extraction GPT-4o lors de l'ingestion automatique |
| `SPOF_BETWEENNESS_PERCENTILE` | `fn-adgm-graph` | Seuil de centralité (percentile) pour marquer `isSPOF` |

---

## Initialiser les bases de données

Le dossier [`db/`](db/) contient les schémas à exécuter une fois sur des bases vides :

```powershell
# Neo4j — contraintes, index, modèle bi-plan (TechnicalNode / FunctionalNode)
cypher-shell -a $env:NEO4J_BOLT_URI -u neo4j -p $env:NEO4J_PASSWORD -f db/neo4j_schema.cypher

# (optionnel) jeu de données de démonstration
cypher-shell -a $env:NEO4J_BOLT_URI -u neo4j -p $env:NEO4J_PASSWORD -f db/adgm_seed.cypher

# Azure SQL — tables IngestionJob, NodeAnnotationHistory, etc.
sqlcmd -S <server>.database.windows.net -d modernagent_db -G -i db/adgm_schema.sql
```

---

## Lancer en local

```powershell
cd azure-functions
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

func start
```

Par défaut `fn-adgm-graph` répond sur `http://localhost:7071/api/graph/...`. Pour pointer l'application principale dessus en local, définir dans `notebooklm-azure/.env` :

```
ADGM_GRAPH_API_URL=http://localhost:7071/api/graph
```

---

## Déployer

```powershell
cd azure-functions
func azure functionapp publish <nom-function-app> --python --build remote
```

`local.settings.json` n'est jamais publié (`.funcignore`) — configurer les variables d'environnement de la Function App cible (Portail Azure → Configuration, ou `az functionapp config appsettings set`).

L'instance de référence utilisée par défaut par l'application (`ADGM_GRAPH_API_URL` dans `.env.example`) est `https://modernagent-adgm-dev.azurewebsites.net/api/graph`.

---

## Structure

```
azure-functions/
├── fn-adgm-graph/      # API HTTP du graphe (lecture, qualification 7R, admin, analyse)
│   ├── function_app.py
│   ├── function.json   # methods: get, post, patch, delete
│   └── host.json
├── fn-adgm-ingest/      # Blob trigger — ingestion automatique des rétro-docs
│   ├── function_app.py
│   └── function.json
├── db/
│   ├── neo4j_schema.cypher  # contraintes + index Neo4j (modèle bi-plan)
│   ├── adgm_seed.cypher     # jeu de données de démonstration (CardDemo)
│   └── adgm_schema.sql      # schéma Azure SQL (IngestionJob, NodeAnnotationHistory...)
├── host.json
├── requirements.txt
└── .funcignore
```
