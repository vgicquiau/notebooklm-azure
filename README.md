# NotebookLM Azure

Agent RAG (Retrieval-Augmented Generation) à interface conversationnelle, inspiré de NotebookLM. Indexez vos documents dans Azure AI Search, posez des questions en langage naturel, obtenez des réponses sourcées avec citations cliquables. Inclut une vue **Legacy KB** pour explorer le graphe GraphRAG de l'application mainframe CardDemo.

---

## Documentation

| Document | Contenu |
|---|---|
| [README.md](README.md) (ce fichier) | Quick start, installation, utilisation |
| [GUIDE-UTILISATEUR.md](GUIDE-UTILISATEUR.md) | **Pour les utilisateurs non techniques** — comment démarrer et utiliser l'application au quotidien (Chat, Sources, Notes, Legacy KB), sans jargon |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Dossier d'architecture complet — fonctionnel, technique, sécurité, spécifications F1-F7 |
| [GUIDE-DEPLOIEMENT.md](GUIDE-DEPLOIEMENT.md) | Déploiement Azure via `deploy.ps1` — paramètres, phases, post-déploiement, teardown |
| [docs/specs/](docs/specs/) | Spécifications produit détaillées (SDD) |

---

## Quick Start

**Prérequis :** [Azure CLI](https://aka.ms/installazurecliwindows) · [Python 3.11+](https://python.org/downloads) · une subscription Azure

```powershell
git clone https://github.com/vgicquiau/notebooklm-azure.git
cd notebooklm-azure

az login

# Déploiement complet (~15 min : provisionne Azure + build Docker + configure l'environnement local)
.\deploy.ps1

# Sur poste avec proxy d'entreprise (Zscaler, Forcepoint…)
.\deploy.ps1 -SkipSSL

# Lancer l'interface en développement local
.\start-dev.ps1
```

L'interface s'ouvre automatiquement sur `http://127.0.0.1:8000`.

> Pour tout supprimer : `.\teardown.ps1`

---

## Fonctionnalités

- **Ingestion multi-format** : PDF (OCR Azure Document Intelligence), Word, PowerPoint, Excel, Markdown, texte brut, code source
- **Recherche vectorielle** : embeddings `text-embedding-3-large` dans Azure AI Search (recherche hybride BM25 + sémantique avec Reciprocal Rank Fusion)
- **Réponses sourcées** : citations `[1]` cliquables ouvrant le passage exact du document
- **3 modes de recherche** : Rapide (5 chunks), Standard (10), Approfondi (20)
- **Rail sources** : liste des documents indexés, prévisualisation des chunks, suppression de l'index
- **Rail notes** : enregistrement des réponses de l'agent, indexation d'une note comme source
- **Interface redimensionnable** : les deux rails sont redimensionnables par glisser-déposer
- **Legacy KB** : vue graphe (React Flow/dagre) du dump GraphRAG `neo4j-legacykb` — exploration par domaine fonctionnel, recherche, recentrage et redisposition sur un nœud
- **Tool-calling Legacy KB dans le Chat** : GPT-4o interroge directement `neo4j-legacykb` pour répondre aux questions sur l'application CardDemo (programmes, copybooks, batch jobs, domaines fonctionnels)

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Navigateur — local uniquement (start-dev.ps1, 127.0.0.1:8000)    │
│  React 18 (Babel standalone) — servi statiquement par l'API      │
│  Vue Chat : SourcesRail │ ChatPanel │ NotesRail                   │
│  Vue Legacy KB : LegacyKbPage (React Flow + dagre)                │
└──────────┬──────────────────────────────────────┬────────────────┘
           │ HTTP (API Key)        /api/legacykb/* en cross-origin │
           │ backend local                  (CORS, vers ca-api)    │
┌──────────▼─────────┐                  ┌─────────────────────────▼┐
│ FastAPI local       │                  │ ca-api (Azure Container  │
│ (start-dev.ps1)      │                  │ Apps) — API JSON seule, │
│                      │                  │ jamais de frontend      │
└──────────┬───────────┘                  └──────────┬──────────────┘
           │                                          │ intégré au VNet
┌──────────▼──────┐  ┌──────────────────┐  ┌──────────▼─────────────┐
│ Azure OpenAI    │  │ Azure AI Search   │  │ neo4j-legacykb          │
│ GPT-4o          │  │ Index vectoriel   │  │ ACI auto-hébergé,       │
│ Embeddings      │  │ notebooklm-chunks │  │ réseau privé (VNet/NSG) │
└─────────────────┘  └─────────┬─────────┘  │ IP privée, pas de FQDN  │
                                │            └─────────────────────────┘
                  ┌─────────────┘
┌─────────────────▼────────────────┐   ┌───────────────────────────┐
│ Azure Document Intelligence       │   │ Azure Key Vault            │
│ OCR et extraction layout PDF      │   │ Secrets API + endpoints    │
└───────────────────────────────────┘   └───────────────────────────┘
```

**Authentification** : Managed Identity en production (zéro clé dans le code). `DefaultAzureCredential` / `az login` en local.

**Réseau** : `neo4j-legacykb` n'a plus d'IP publique (réseau privé Azure VNet) — seul `ca-api`
(intégré au même VNet) peut l'atteindre. Le backend local ne peut donc plus l'atteindre
directement ; la vue Legacy KB en local appelle `ca-api` en cross-origin pour compenser (voir
[ARCHITECTURE.md § CORS](ARCHITECTURE.md#cors--accès-cross-origin-du-frontend-local-à-ca-api)).

---

## Prérequis

- [Azure CLI](https://aka.ms/installazurecliwindows) 2.60+
- [Python 3.11+](https://python.org/downloads)
- Une subscription Azure avec droits de créer des ressources

> Docker **n'est pas requis** en local — `deploy.ps1` utilise `az acr build` pour construire l'image directement dans Azure Container Registry.

---

## Développement local

### Après un premier déploiement (`deploy.ps1`)

`deploy.ps1` crée automatiquement le fichier `.env` et le virtualenv. Pour démarrer :

```powershell
.\start-dev.ps1
```

Ou via VS Code : **Ctrl+Shift+B** (tâche `Start NotebookLM Dev`).

### Installation manuelle (sans passer par deploy.ps1)

```powershell
# 1. Cloner
git clone https://github.com/vgicquiau/notebooklm-azure.git
cd notebooklm-azure

# 2. Créer le virtualenv et installer les dépendances
python -m venv api/.venv
api\.venv\Scripts\pip install -r api/requirements.txt -r ingest/requirements.txt

# 3. Configurer les variables d'environnement
Copy-Item .env.example .env
# Éditer .env avec vos endpoints Azure

# 4. S'authentifier sur Azure
az login

# 5. Lancer le serveur
.\start-dev.ps1
```

### Variables d'environnement

Le fichier `.env` (généré par `deploy.ps1` ou copié depuis `.env.example`) doit contenir :

| Variable | Description | Obligatoire |
|----------|-------------|-------------|
| `AZURE_OPENAI_ENDPOINT` | Endpoint Azure OpenAI | Oui |
| `AZURE_OPENAI_GPT4O_DEPLOYMENT` | Nom du déploiement GPT-4o | Oui |
| `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` | Nom du déploiement d'embeddings | Oui |
| `AZURE_SEARCH_ENDPOINT` | Endpoint Azure AI Search | Oui |
| `AZURE_DOCINT_ENDPOINT` | Endpoint Azure Document Intelligence | Oui |
| `AZURE_STORAGE_ACCOUNT_NAME` | Nom du compte de stockage | Oui |
| `API_KEY` | Clé d'authentification pour les endpoints `/api/*` | Recommandé en prod |
| `NEO4J_LEGACYKB_URI` | URI `bolt://` (local sans TLS) ou `bolt+ssc://` (prod, cert auto-signé) du conteneur neo4j-legacykb — IP **privée**, change à chaque recréation de l'ACI | Pour la vue Legacy KB |
| `NEO4J_LEGACYKB_PASSWORD` | Mot de passe neo4j | Pour la vue Legacy KB |
| `NOTEBOOKLM_API_URL` | FQDN public de l'API déployée (`ca-api`) — change à chaque recréation de l'environnement Container Apps. Utilisée par `mcp-legacykb`, et par le backend local pour le CORS/CSP afin que le frontend local puisse appeler `ca-api` en cross-origin pour `/api/legacykb/*` (`neo4j-legacykb` n'a plus d'IP publique) | Pour `mcp-legacykb` et pour la vue Legacy KB en local |
| `CORS_ALLOWED_ORIGINS` | Origines CORS autorisées sur `ca-api` (virgule-séparées) — défaut `http://127.0.0.1:8000` pour le frontend local | Si frontend sur domaine différent |

En production, tous les secrets (`API_KEY`, endpoints, mot de passe neo4j) sont lus depuis **Azure Key Vault** via Managed Identity — le `.env` de prod ne contient pas de secrets. `NEO4J_LEGACYKB_URI` et `NOTEBOOKLM_API_URL` ne sont jamais des valeurs fixes : elles changent chaque fois que l'ACI ou l'environnement Container Apps sont recréés.

---

## Utilisation

### Indexer des documents

**Mode UI (recommandé) :**
1. Cliquer sur **Ajouter un document** dans la barre supérieure
2. Sélectionner un fichier (PDF, DOCX, PPTX, XLSX, Markdown, TXT, code source…)
3. L'ingestion se déroule en arrière-plan — un toast de progression s'affiche

**Mode CLI (lot de documents) :**
```powershell
# Depuis la racine du projet, venv activé
python -m ingest.ingest --docs-dir documents/
```

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

Les réponses de l'agent peuvent être sauvegardées comme notes (bouton **Enregistrer** sous chaque réponse). Une note peut ensuite être indexée comme source via le rail droit, ou injectée dans le contexte de la prochaine question.

### Vue Legacy KB

Accessible via le menu en haut de page. Explore le graphe neo4j-legacykb (dump GraphRAG de l'application mainframe CardDemo) :
- Recherche de nœuds par nom ou domaine fonctionnel
- Visualisation des relations (React Flow + dagre)
- Recentrage et redisposition sur un nœud sélectionné
- Tool-calling depuis le chat : GPT-4o peut requêter le graphe directement

---

## Structure des sources

```
notebooklm-azure/
├── api/
│   ├── main.py                 # FastAPI app, middlewares, lifespan (Key Vault → env)
│   ├── routers/
│   │   ├── chat.py             # POST /api/chat · GET /api/chat/history/{id} · POST /api/chat/clear
│   │   ├── ingest.py           # POST /api/ingest, GET /api/ingest/{job_id}
│   │   ├── legacykb.py         # GET /api/legacykb/* (golden source CardDemo)
│   │   └── sources.py          # GET/DELETE /api/sources
│   ├── services/
│   │   ├── retriever.py        # Recherche vectorielle Azure AI Search
│   │   ├── generator.py        # Génération RAG (GPT-4o + tools)
│   │   ├── graph_tools.py      # Tools function-calling → legacykb_*
│   │   ├── legacykb_client.py  # Client Neo4j
│   │   ├── session_store.py    # Persistance SQLite des sessions de chat
│   │   ├── compactor.py        # Compaction glissante de l'historique (résumé LLM)
│   │   └── rate_limiter.py     # Rate limiting /api/chat (20 req/IP/60s)
│   ├── scripts/
│   │   └── import_legacykb.py  # Exécuté par le Container Apps Job caj-import-legacykb-*
│   │                           # (import GraphML depuis l'intérieur du VNet)
│   └── data/
│       └── chat_history.db     # Base SQLite (créée au démarrage, non commitée)
├── ingest/
│   ├── chunkers/               # Un chunker par format (PDF, DOCX, PPTX, XLSX, MD, TXT)
│   ├── embedder.py             # Génération d'embeddings par batch
│   └── indexer.py              # Upload dans Azure AI Search
├── frontend/
│   ├── index.html              # Chargement ordonné des composants
│   ├── vendor/                 # Dépendances JS vendorisées (React, Babel, xyflow, dagre…)
│   └── src/                    # Composants React (JSX transpilé in-browser)
├── infra/
│   ├── main.bicep              # Orchestration, rôles IAM, secrets Key Vault, tags obligatoires
│   ├── main.parameters.json    # Paramètres de déploiement (non commité)
│   └── modules/                # network (VNet/NSG), containerapp (+ Job d'import), openai,
│                                # search, keyvault, neo4j-legacykb (réseau privé)…
├── deploy.ps1                  # Déploiement complet en 8 phases
├── teardown.ps1                # Suppression de toutes les ressources Azure
├── start-dev.ps1               # Lancement du serveur de développement local
├── azure-functions/            # fn-adgm-graph / fn-adgm-ingest — conservés au repos
│                               # (retrait du graphe ADG-M le 2026-06-13)
├── doc-archimind/              # Corpus de référence CardDemo (architecture mainframe)
└── docs/
    ├── specs/                  # Spécifications produit (SDD_*, plans, audits)
    └── archive/sprint0/        # Scripts du bootstrap initial (superseded)
```

---

## Mise à jour

```powershell
git pull --rebase
# Redémarrer si des fichiers Python ont changé
.\start-dev.ps1
```

Si les dépendances Python ont changé :

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

## Déploiement et teardown

Voir **[GUIDE-DEPLOIEMENT.md](GUIDE-DEPLOIEMENT.md)** pour le détail complet.

```powershell
# Déployer (crée ou met à jour toutes les ressources Azure, importe le dump GraphML)
.\deploy.ps1 -SkipSSL          # avec proxy d'entreprise
.\deploy.ps1 -ImageOnly        # rebuild l'image Docker uniquement
.\deploy.ps1 -Neo4jUri "bolt+ssc://mon-neo4j:7687"  # neo4j externe existant

# Re-importer seul le dump GraphML (nouveau dump, ou nouvelle instance neo4j-legacykb)
.\import-neo4j-legacykb.ps1 -ResourceGroup rg-mon-rg -SkipSSL

# Migrer vers un nouveau Resource Group / subscription (durée de vie limitée du RG)
.\migrate-rg.ps1 -SourceResourceGroup rg-actuel -DestResourceGroup rg-nouveau -DestSubscription "Ma Sub"

# Supprimer toutes les ressources Azure
.\teardown.ps1
.\teardown.ps1 -ResourceGroup rg-mon-rg-custom   # nom de RG personnalisé
```
