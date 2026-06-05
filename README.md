# NotebookLM Azure

Agent RAG (Retrieval-Augmented Generation) à interface conversationnelle, inspiré de NotebookLM. Indexez vos documents dans Azure AI Search, posez des questions en langage naturel, obtenez des réponses sourcées avec citations cliquables.

---

## Quick Start

**Prérequis :** [Azure CLI](https://aka.ms/installazurecliwindows) · [Python 3.11+](https://python.org/downloads) · [Docker](https://www.docker.com/products/docker-desktop) · une subscription Azure

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

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Navigateur                                              │
│  React (Babel standalone) — servi statiquement par API  │
│  SourcesRail │ ChatPanel │ NotesRail                    │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTP
┌──────────────────────▼──────────────────────────────────┐
│  FastAPI (Python 3.11)                                   │
│  POST /api/chat      GET/DELETE /api/sources             │
│  POST /api/ingest    GET /api/ingest/{job_id}            │
└──────┬───────────────────────┬──────────────────────────┘
       │                       │
┌──────▼──────┐    ┌──────────▼──────────┐
│ Azure OpenAI│    │ Azure AI Search      │
│ GPT-4o      │    │ Index vectoriel      │
│ Embeddings  │    │ notebooklm-chunks    │
└─────────────┘    └─────────────────────┘
                            ▲
              ┌─────────────┘
┌─────────────┴───────────────────────────┐
│  Azure Document Intelligence             │
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
├── vendor/            # Dépendances JS (React, Babel, Mermaid…)
└── src/               # Composants React (JSX transpilé in-browser)
```

---

## Déploiement

Le dossier `infra/` contient les templates Bicep pour déployer l'ensemble sur Azure Container Apps avec Managed Identity. Voir [GUIDE-DEPLOIEMENT.md](GUIDE-DEPLOIEMENT.md).
