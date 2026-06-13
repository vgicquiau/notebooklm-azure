# NotebookLM Azure

Agent RAG (Retrieval-Augmented Generation) à interface conversationnelle, inspiré de NotebookLM. Indexez vos documents dans Azure AI Search, posez des questions en langage naturel, obtenez des réponses sourcées avec citations cliquables. Inclut une vue **Graphe ADG-M** pour visualiser et qualifier (7R) l'architecture applicative extraite du corpus.

---

## Documentation

| Document | Contenu |
|---|---|
| [README.md](README.md) (ce fichier) | Quick start, installation, utilisation |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Dossier d'architecture complet — fonctionnel, technique, sécurité, spécifications par fonctionnalité (F1-F7) |
| [ADG-M_GRAPH_METHODOLOGIE.md](ADG-M_GRAPH_METHODOLOGIE.md) | Méthodologie du Graphe ADG-M : pipeline d'extraction, typage des nœuds Neo4j, glossaire |
| [GUIDE-DEPLOIEMENT.md](GUIDE-DEPLOIEMENT.md) | Déploiement pas-à-pas sur Azure (infra Bicep, App Service, Docker) |
| [azure-functions/README.md](azure-functions/README.md) | Backend du Graphe ADG-M (`fn-adgm-graph`, `fn-adgm-ingest`) — config, schémas DB, déploiement |
| [docs/specs/](docs/specs/) | Spécifications produit détaillées (SDD) |

---

## Quick Start

**Prérequis :** [Azure CLI](https://aka.ms/installazurecliwindows) · [Python 3.11+](https://python.org/downloads) · une subscription Azure

```powershell
git clone https://github.com/vgicquiau/notebooklm-azure.git
cd notebooklm-azure

az login

# Setup complet (~15 min — provisionne Azure + configure l'environnement local)
.\deploy.ps1

# Sur poste avec proxy d'entreprise (Zscaler, Forcepoint…)
.\deploy.ps1 -SkipSSL

# Lancer l'interface
.\start-dev.ps1
```

L'interface s'ouvre automatiquement sur `http://127.0.0.1:8000`.

> Pour tout supprimer : `.\teardown.ps1`

---

## Fonctionnalités

- **Ingestion multi-format** : PDF (OCR Azure Document Intelligence), Word, PowerPoint, Excel, Markdown, texte brut, code source
- **Recherche vectorielle** : embeddings `text-embedding-3-large` dans Azure AI Search
- **Réponses sourcées** : citations `[1]` cliquables ouvrant le passage exact du document
- **3 modes de recherche** : Rapide (5 chunks), Standard (10), Approfondi (20)
- **Rail sources** : liste des documents indexés, prévisualisation des chunks, suppression de l'index
- **Rail notes** : enregistrement des réponses de l'agent, indexation d'une note comme source
- **Interface redimensionnable** : les deux rails sont redimensionnables par glisser-déposer
- **Graphe ADG-M** : visualisation interactive de l'architecture applicative extraite du corpus — bi-plan switch (Fonctionnel/Technique), qualification 7R des composants, détection SPOF et clusters Louvain, exports JSON/CSV
- **Module Exploration** : CRUD ArchiMate 3.x sur le graphe (nœuds, relations, suppression cascade, bulk-tag, orphelins), RBAC par rôle (Viewer/Architect/Admin) et journal d'audit — voir `ARCHITECTURE.md` §F8

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Navigateur                                                       │
│  React (Babel standalone) — servi statiquement par API            │
│  Vue Chat : SourcesRail │ ChatPanel │ NotesRail                   │
│  Vue Graphe : GraphPage (Cytoscape.js)                            │
└─────────────────────────┬────────────────────────────────────────┘
                          │ HTTP
┌─────────────────────────▼────────────────────────────────────────┐
│  FastAPI (Python 3.11)                                            │
│  POST /api/chat           GET/DELETE /api/sources                 │
│  POST /api/ingest         GET /api/ingest/{job_id}                │
│  GET/PATCH/DELETE /api/graph/*  (proxy → fn-adgm-graph)          │
│  POST /api/extract/graph  GET /api/extract/graph/{job_id}         │
└──────┬───────────────────────┬──────────────────┬────────────────┘
       │                       │                  │
┌──────▼──────┐    ┌──────────▼──────────┐  ┌───▼────────────────────────┐
│ Azure OpenAI│    │ Azure AI Search      │  │ Azure Function App          │
│ GPT-4o      │    │ Index vectoriel      │  │ fn-adgm-graph               │
│ Embeddings  │    │ notebooklm-chunks    │  │  ├─ Neo4j AuraDB             │
└─────────────┘    └─────────────────────┘  │  │  TechnicalNode · 7R       │
                            ▲               │  │  SPOF · Louvain clusters   │
              ┌─────────────┘               │  └─ Azure SQL                 │
┌─────────────┴───────────────────────────┐ │     NodeAnnotationHistory     │
│  Azure Document Intelligence             │ └────────────────────────────────┘
│  OCR et extraction layout PDF            │
└─────────────────────────────────────────┘
```

---

## Prérequis

- Python 3.11+
- Azure CLI (`az login` pour l'authentification locale)
- Ressources Azure provisionnées :
  - Azure OpenAI (déploiements `gpt-4o` + `text-embedding-3-large`)
  - Azure AI Search
  - Azure Document Intelligence

---

## Installation

### 1. Cloner le repo

```bash
git clone https://github.com/vgicquiau/notebooklm-azure.git
cd notebooklm-azure
```

### 2. Créer et activer le virtualenv

```powershell
python -m venv api/.venv
api\.venv\Scripts\activate
```

### 3. Installer les dépendances

```powershell
pip install -r api/requirements.txt
pip install -r ingest/requirements.txt
```

### 4. Configurer les variables d'environnement

```powershell
cp .env.example .env
# Éditer .env avec vos endpoints Azure
```

Variables requises :

| Variable | Description |
|----------|-------------|
| `AZURE_OPENAI_ENDPOINT` | Endpoint Azure OpenAI |
| `AZURE_OPENAI_GPT4O_DEPLOYMENT` | Nom du déploiement GPT-4o |
| `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` | Nom du déploiement d'embeddings |
| `AZURE_SEARCH_ENDPOINT` | Endpoint Azure AI Search |
| `AZURE_DOCINT_ENDPOINT` | Endpoint Azure Document Intelligence |
| `API_KEY` | Clé d'authentification (optionnelle en local) |
| `ADGM_GRAPH_API_URL` | URL de base de `fn-adgm-graph` (défaut : instance de dev partagée `https://modernagent-adgm-dev.azurewebsites.net/api/graph` — voir [azure-functions/README.md](azure-functions/README.md) pour déployer votre propre instance) |

### 5. Authentification Azure

```bash
az login
```

---

## Lancement

```powershell
.\start-dev.ps1
```

Ou via VS Code : **Ctrl+Shift+B** (tâche `Start NotebookLM Dev`).

L'interface s'ouvre automatiquement sur `http://127.0.0.1:8000`.

---

## Utilisation

### Indexer des documents

1. Cliquer sur **Ajouter un document** dans le rail gauche
2. Sélectionner un fichier (PDF, DOCX, PPTX, XLSX, Markdown, TXT, code source…)
3. L'ingestion se déroule en arrière-plan — la progression s'affiche dans le rail

Formats supportés :

| Format | Chunking |
|--------|----------|
| PDF | OCR Azure Document Intelligence, découpage par page/section |
| DOCX | Sections par styles de titre, tableaux inclus |
| PPTX | Une slide = un chunk, titre de slide = section |
| XLSX | Lignes groupées par feuille jusqu'à 800 tokens |
| Markdown | Sections par headings `#`, `##`, `###` |
| TXT / Code | Sliding window 800 tokens, overlap 150 |

### Interroger l'agent

Tapez votre question dans la zone de saisie. Les citations `[1]`, `[2]`… dans les réponses sont cliquables et affichent le passage source exact.

**Modes de recherche :**
- **Rapide** — 5 chunks, réponse concise
- **Standard** — 10 chunks, analyse équilibrée
- **Approfondi** — 20 chunks, analyse exhaustive

### Notes

Les réponses de l'agent peuvent être sauvegardées comme notes (bouton **Enregistrer** sous chaque réponse). Une note peut ensuite être indexée comme source via l'icône dans le rail droit.

---

## Structure des sources

```
api/
├── main.py            # FastAPI app, middlewares sécurité, lifespan
├── routers/
│   ├── chat.py        # Endpoint de conversation
│   ├── extract.py     # Pipeline Chat→Graphe (extraction GPT-4o → fn-adgm-graph)
│   ├── graph.py       # Proxy GET/PATCH/DELETE /api/graph/* → fn-adgm-graph
│   ├── ingest.py      # Ingestion asynchrone avec polling
│   └── sources.py     # CRUD sources dans l'index
└── services/
    ├── retriever.py   # Recherche vectorielle
    └── generator.py   # Génération RAG

ingest/
├── chunkers/          # Un chunker par format de fichier
├── embedder.py        # Génération d'embeddings par batch
└── indexer.py         # Upload dans Azure AI Search

frontend/
├── index.html         # Chargement ordonné des composants
├── vendor/            # Dépendances JS (React, Babel, Mermaid, Cytoscape…)
└── src/               # Composants React (JSX transpilé in-browser)
    ├── GraphPage.jsx  # Vue Graphe ADG-M (Cytoscape.js)
    └── ...            # Chat : Header, SourcesRail, ChatPanel, NotesRail, App

azure-functions/        # Backend du Graphe ADG-M (déployé sur Azure Functions)
├── fn-adgm-graph/      # API Neo4j — nœuds, arcs, clusters, qualification 7R
├── fn-adgm-ingest/     # Blob trigger — ingestion automatique des rétro-docs
└── db/                 # Schémas Neo4j (Cypher) et Azure SQL

doc-archimind/           # Corpus de référence (architecture mainframe CardDemo)
docs/
├── specs/               # Spécifications produit (SDD_*, plans, audits)
└── archive/sprint0/     # Scripts du bootstrap initial (superseded)
```

---

## Mise à jour

Pour récupérer les dernières évolutions du projet :

```powershell
git pull --rebase
# Redémarrer le serveur si des fichiers Python ont changé
.\start-dev.ps1
```

Si les dépendances Python ont changé (nouveau `requirements.txt`) :

```powershell
api\.venv\Scripts\pip install -r api\requirements.txt -r ingest\requirements.txt
```

---

## Contribuer

```powershell
git checkout -b feature/ma-fonctionnalite
# ... développer ...
git add <fichiers modifiés>
git commit -m "feat: description courte"
git push -u origin feature/ma-fonctionnalite
gh pr create
```

---

## Déploiement

Le dossier `infra/` contient les templates Bicep pour déployer l'ensemble sur Azure Container Apps avec Managed Identity. Voir [GUIDE-DEPLOIEMENT.md](GUIDE-DEPLOIEMENT.md).
