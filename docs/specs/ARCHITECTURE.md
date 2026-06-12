# Architecture cible — Modernization Agent v1

## Diagramme d'architecture générale

> **Décision d'intégration ADG-M** : la vue graphe est intégrée dans NotebookLM Azure
> (toggle Chat ⇄ Graphe) plutôt que comme application standalone. Cela évite un second
> outil à maintenir et exploite le corpus documentaire déjà indexé dans AI Search.

```mermaid
graph TB
    subgraph sources["🔵 Sources"]
        archimind["ArchiMind<br/>(Rétro-docs Markdown/JSON)"]
    end

    subgraph nlmazure["🟣 NotebookLM Azure — hub unifié RAG + ADG-M<br/>app-api-nlmazure-prod"]
        nlm_ui["React UI (Babel standalone)<br/>Vue Chat : Sources │ ChatPanel │ Notes<br/>Vue Graphe : GraphPage (Cytoscape.js) ✅"]
        nlm_api["FastAPI<br/>chat · ingest · sources<br/>graph-proxy · extract"]
    end

    subgraph azure_shared["☁️ Azure — Services partagés"]
        openai["Azure OpenAI<br/>oai-nlmazure-prod<br/>gpt-4o · text-embedding-3-large"]
        search["Azure AI Search<br/>srch-nlmazure-prod<br/>notebooklm-chunks"]
        sql["Azure SQL Database<br/>modernagent-sql-dev<br/>(NodeAnnotationHistory + modules futurs)"]
    end

    subgraph adgm["🟢 ADG-M ✅ — modernagent-adgm-dev"]
        func_adgm["fn-adgm-graph<br/>Azure Functions Python<br/>GET/PATCH/DELETE /graph/*<br/>POST /admin/analyze · import-entities<br/>DELETE /admin/reset · functional-entities"]
        neo4j["Neo4j AuraDB<br/>Taxonomie GraphRAG v2.0<br/>Composant · Fonction · Regle_Metier · ...<br/>betweennessScore · communityId · candidate7R · fiabilite"]
        logic_adgm["GDS<br/>• Betweenness → isSPOF<br/>• Louvain → communityId"]
    end

    subgraph sevenrqa["🟠 7RQA — Planifié"]
        func_7rqa["Azure Functions<br/>(/qualify/*)<br/>Python SK"]
        ui_7rqa["Vue 7RQA<br/>(Backlog,<br/>Synthèse)"]
        logic_7rqa["Logique<br/>• 6 dimensions<br/>• gpt-4o<br/>• Effort"]
        sql_7rqa["SQL<br/>(Rapports,<br/>EffortCalibration)"]
    end

    subgraph admm["🔵 ADM-M — Planifié"]
        func_admm["Azure Functions<br/>(/matrix/*)<br/>Python"]
        ui_admm["Vue ADM-M<br/>(Quadrant D3.js,<br/>Portefeuille)"]
        logic_admm["Logique<br/>• 12 critères<br/>• Positionnement<br/>• ADR génération"]
        sql_admm["SQL<br/>(Positions,<br/>ADR)"]
    end

    subgraph mwp["🟡 MWP — Planifié"]
        func_mwp["Azure Functions<br/>(/wave/*)<br/>Python"]
        ui_mwp["Vue MWP<br/>(Gantt,<br/>Pilotage)"]
        logic_mwp["Logique<br/>• Tri topologique<br/>• 3 modes<br/>• Simulation"]
        sql_mwp["SQL<br/>(Plans,<br/>Vagues,<br/>Statuts)"]
    end

    subgraph exports["📤 Exports & Livrables"]
        export_md["Markdown<br/>(ADR, Fiches)"]
        export_pptx["PowerPoint<br/>(Deck COMEX)"]
        export_devops["Azure DevOps<br/>(Epics/Features)"]
    end

    subgraph user["👤 Utilisateur"]
        architect["Architecte Lead<br/>Solution Architect"]
    end

    %% Flux RAG Chat
    archimind -->|"Upload via UI"| nlm_ui
    nlm_ui <-->|"HTTP /api/*"| nlm_api
    nlm_api <-->|"Chunks + embeddings<br/>notebooklm-chunks"| search
    nlm_api <-->|"Génération RAG<br/>Extraction GPT-4o"| openai

    %% Flux Chat→Graphe (Track C — extract.py)
    nlm_api -->|"Lecture chunks<br/>groupés par source_file"| search
    nlm_api -->|"POST /admin/import-entities<br/>(server-to-server)"| func_adgm

    %% Flux ADG-M visualisation (proxy)
    nlm_ui -->|"/api/graph/* (proxy)"| nlm_api
    nlm_api -->|"server-to-server<br/>(contourne CSP)"| func_adgm
    func_adgm <-->|"Cypher / MERGE / MATCH"| neo4j
    func_adgm -->|"INSERT annotation history"| sql
    func_adgm --> logic_adgm
    logic_adgm -.->|"SET betweenness<br/>SET communityId"| neo4j

    %% 7RQA (planifié)
    func_adgm -->|"GET /graph/nodes<br/>GET /graph/clusters"| func_7rqa
    search -->|"RAG rétro-doc"| func_7rqa
    openai -->|"Raisonnement"| func_7rqa
    func_7rqa -->|"Rapports"| sql_7rqa
    func_7rqa -->|"GET /qualify/*"| nlm_api
    nlm_ui -->|"Vue 7RQA"| ui_7rqa

    %% ADM-M (planifié)
    func_adgm -->|"GET /graph/nodes<br/>GET /graph/arcs"| func_admm
    func_7rqa -->|"GET /qualify/reports"| func_admm
    openai -->|"Critères D1/D4/D6"| func_admm
    func_admm -->|"Positions + ADR"| sql_admm
    func_admm -->|"GET /matrix/*"| nlm_api
    nlm_ui -->|"Vue ADM-M"| ui_admm

    %% MWP (planifié)
    func_adgm -->|"GET /graph/*<br/>Tri topologique"| func_mwp
    func_admm -->|"GET /matrix/portfolio"| func_mwp
    sql_7rqa -->|"EffortCalibration"| func_mwp
    func_mwp -->|"Plans + Vagues"| sql_mwp
    func_mwp -->|"GET /wave/*"| nlm_api
    nlm_ui -->|"Vue MWP"| ui_mwp

    %% User
    architect -->|"ouvre"| nlm_ui

    %% Exports
    func_admm -->|"ADR Markdown"| export_md
    func_mwp -->|"Scenarios"| export_pptx
    func_mwp -->|"Epics/Features API"| export_devops
    architect -->|"Consulte"| export_md
    architect -->|"Télécharge"| export_pptx
    architect -->|"Synchro"| export_devops

    %% Styles
    classDef source fill:#e1f5ff
    classDef hub fill:#f3e5f5,stroke:#7b1fa2,color:#000
    classDef shared fill:#fff3e0,stroke:#e65100,color:#000
    classDef live fill:#e8f5e9,stroke:#2e7d32,color:#000
    classDef planned fill:#fff8e1,stroke:#f57f17,color:#000
    classDef output fill:#fce4ec
    classDef userStyle fill:#f1f8e9

    class archimind source
    class nlm_ui,nlm_api hub
    class openai,search,sql shared
    class func_adgm,neo4j,logic_adgm live
    class func_7rqa,ui_7rqa,logic_7rqa,sql_7rqa,func_admm,ui_admm,logic_admm,sql_admm,func_mwp,ui_mwp,logic_mwp,sql_mwp planned
    class export_md,export_pptx,export_devops output
    class architect userStyle
```

---

## Vue logique par flux

### Flux 1 : Ingestion et Cartographie (ADG-M) ✅
```
ArchiMind Rétro-docs
  ↓ [Upload via NotebookLM Azure UI]
Pipeline d'ingestion — NotebookLM Azure
  ├→ Extraction : Azure Document Intelligence (PDF) / chunkers natifs
  ├→ Embeddings : text-embedding-3-large
  └→ Index : Azure AI Search notebooklm-chunks (déduplication SHA-256)
  ↓
Architecte lance "Mettre à jour le graphe"
  ↓ [POST /api/extract/graph → BackgroundTask — extract.py]
Pipeline Chat→Graphe (Track C)
  ├→ DELETE /admin/functional-entities : vide tout le graphe SAUF Composant/System
  │   (préserve la qualification candidate7R et les propriétés calculées par GDS)
  ├→ Azure AI Search : lecture complète (top 5000 chunks, groupés par source_file)
  ├→ GPT-4o : extraction JSON structurée par document
  │   (taxonomie GraphRAG v2.0 : {nodes:[{id,label,properties}], relations:[{from,to,type,properties}]})
  └→ fn-adgm-graph POST /admin/import-entities : MERGE nœuds + arcs dans Neo4j (fiabilite upgrade-only)
  ↓
POST /graph/admin/analyze (déclenché séparément)
  ├→ GDS Betweenness → isSpof sur Composant/Store_Donnees
  └→ GDS Louvain → communityId par nœud de la projection structurelle (clusters candidats)
  ↓
Graphe bi-plan live dans NotebookLM Azure
  ↓ [Vue Graphe ADG-M — GraphPage.jsx, Cytoscape.js]
Architecte voit : domaines fonctionnels | composants techniques | SPOF | clusters
```

### Flux 2 : Qualification composant par composant (7RQA)
```
Architecte clique "Qualifier" sur un nœud ADG-M
  ↓
7RQA Pipeline (F2.1)
  ├→ Charge nœud + rétro-doc (RAG)
  ├→ Évalue 6 dimensions (o4-mini)
  ├→ Estime effort (calibration Arkéa/Retail)
  └→ Génère rapport + alternatives écartées
  ↓ [SQL : rapports versionnés]
Architecte valide → 7R propagée dans Neo4j
  ↓
Backlog de qualification (composants FAIBLE confiance)
```

### Flux 3 : Positionnement stratégique (ADM-M)
```
Architecte positionne un composant sur le quadrant
  ↓
ADM-M Pipeline (F3.1)
  ├→ Calcule 12 critères (D1-D6, C1-C6)
  ├→ Applique profil de pondération
  └→ Place sur quadrant + dérive palette 7R
  ↓ [SQL : positions versionnées]
Architecte valide positionnement
  ↓
Génération ADR (F3.5)
  ├→ Gabarit structuré
  ├→ Lien 7RQA (alternatives écartées)
  └→ Export Markdown → Blob
```

### Flux 4 : Planification de vagues (MWP)
```
Architecte demande "Générer plan"
  ↓
MWP Pipeline (F4.1 → F4.4)
  ├→ Tri topologique du graphe
  ├→ Détecte cycles → propose couches interop
  ├→ Priorise (3 modes : Valeur / Risque / Budget)
  ├→ Estime effort/durée par vague
  └→ Simule 3 scénarios
  ↓ [SQL : plans + vagues]
Architecte compare variantes (3 indicateurs)
  ↓
Valide plan → Exports
  ├→ Gantt Markdown
  ├→ Deck PowerPoint (COMEX)
  └→ Epics/Features Azure DevOps
  ↓
Post-lancement : dashboard pilotage (F4.5)
  └→ Statuts composants + dérive + alertes
```

---

## Principes d'hébergement — Cloud-first

> **Règle** : Le PC Windows est uniquement IDE + browser + az CLI. Aucun serveur local.

| Composant | Hébergement Azure | Type | Coût estimé dev |
|---|---|---|---|
| **NotebookLM Azure ✅** | `app-api-nlmazure-prod` (App Service, hub Chat + ADG-M) | Réutilisé | ~0 € additionnel (partagé) |
| **Neo4j AuraDB + GDS** | Neo4j AuraDB (cloud géré, Free tier dev) | SaaS | ~0 € (Free Tier) |
| **ADG-M `fn-adgm-graph` ✅** | Azure Functions (Python 3.11) | Serverless | ~0 € (Free Tier 1M exec) |
| **7RQA** | Azure Functions (Python 3.11) | Serverless | ~0 € |
| **ADM-M** | Azure Functions (Python 3.11) | Serverless | ~0 € |
| **MWP** | Azure Functions (Python 3.11) | Serverless | ~0 € |
| **Azure SQL Database** | Azure SQL Basic — `modernagent-sql-dev` | PaaS | ~5 €/mois |
| **Azure Blob Storage** | StorageV2 LRS — `modernagentstgdev` (exports futurs ADM-M/MWP) | PaaS | ~1 €/mois |
| **Azure OpenAI** | `oai-nlmazure-prod` — gpt-4o + text-embedding-3-large, Managed Identity | Réutilisé | ~0 € additionnel (partagé) |
| **Azure AI Search** | `srch-nlmazure-prod` (Standard S1) | Réutilisé | ~0 € additionnel (partagé) |
| **Azure Key Vault** | Standard, mode RBAC | PaaS | ~0 € (opérations) |
| **Application Insights** | Workspace-based | PaaS | ~0 € (5 Go gratuits) |

**Coût total estimé (dev solo, 4h/jour)** : ~10-15 €/mois — l'essentiel des
coûts IA (OpenAI, Search, ArchiMind) est absorbé par les comptes de
production partagés et ne s'ajoute pas au budget de ce projet.

> ⚠️ **Écart identifié au Sprint 0** : `oai-nlmazure-prod` n'expose que deux
> déploiements — `gpt-4o` et `text-embedding-3-large`. Le modèle `o4-mini`,
> présent dans la conception de 7RQA (raisonnement sur les 6 dimensions, cf.
> diagrammes ci-dessous), **n'y est pas déployé**. À trancher avant le sprint
> 7RQA : soit demander l'ajout d'un déploiement `o4-mini` sur le compte
> partagé (hors périmètre de `v.gicquiau`, qui n'a aucun rôle au niveau
> abonnement), soit adapter la logique 7RQA pour utiliser `gpt-4o`.

**Neo4j** : migré sur **Neo4j AuraDB** (cloud géré, Free Tier) — les commandes `az container stop/start` ne s'appliquent plus. La connexion passe par `NEO4J_URI` (neo4j+s://...) configurée dans `local.settings.json` de `fn-adgm-graph`.

---

## Flux de données inter-modules

```mermaid
graph LR
    ADG["<b>ADG-M</b><br/>Graph<br/>Métriques<br/>Clusters"]
    
    7RQA["<b>7RQA</b><br/>Rapports<br/>Confiance<br/>EffortCal"]
    
    ADMM["<b>ADM-M</b><br/>Positions<br/>ADR"]
    
    MWP["<b>MWP</b><br/>Plans<br/>Vagues"]
    
    SQL["<b>Azure SQL</b><br/>History<br/>Versioning"]
    
    Neo["<b>Neo4j</b><br/>Graph<br/>State"]
    
    ADG -->|GET /graph/nodes<br/>GET /graph/clusters| 7RQA
    ADG -->|GET /graph/nodes<br/>GET /graph/arcs| ADMM
    ADG -->|GET /graph/*<br/>Tri topo| MWP
    
    7RQA -->|"PATCH /qualification<br/>(7R validée)"| ADG
    7RQA -->|SQL rapports| SQL
    
    ADMM -->|"PATCH /qualification<br/>(7R stratégique)"| ADG
    ADMM -->|GET /qualify/reports| 7RQA
    ADMM -->|SQL positions| SQL
    
    MWP -->|GET /matrix/portfolio<br/>GET /matrix/adr| ADMM
    MWP -->|SQL EffortCalibration| SQL
    MWP -->|SQL plans| SQL
    
    ADG -->|Write state| Neo
    
    classDef module fill:#e3f2fd,stroke:#1976d2,color:#000
    classDef storage fill:#f3e5f5,stroke:#7b1fa2,color:#000
    classDef sync fill:#c8e6c9,stroke:#388e3c,color:#000
    
    class ADG,7RQA,ADMM,MWP module
    class SQL,Neo storage
```

---

## Conventions de nommage Azure

Tous les services respectent le format : `{prefixe}-{composant}-{env}`

```
modernagent-adgm-dev              # Azure Functions ADG-M ✅ déployé
modernagent-sevenrqa-dev          # Azure Functions 7RQA (planifié)
modernagent-admm-dev              # Azure Functions ADM-M (planifié)
modernagent-mwp-dev               # Azure Functions MWP (planifié)
modernagent-sql-dev               # SQL Server (base modernagent_db)
modernagentstgdev                 # Blob Storage (exports futurs ADM-M/MWP)
modernagent-ai-dev                # Application Insights
modernagent-kv-dev                # Key Vault (mode RBAC)
                                  # Neo4j : Neo4j AuraDB cloud (pas d'ACI)
                                  # Frontend : intégré dans app-api-nlmazure-prod (pas de Static Web Apps)
```

**Ressources de production réutilisées** (hors convention `modernagent-*`,
comptes partagés notebooklm-azure existants — RBAC Managed Identity) :
```
oai-nlmazure-prod                 # Azure OpenAI (gpt-4o, text-embedding-3-large)
srch-nlmazure-prod                # Azure AI Search (notebooklm-chunks)
app-api-nlmazure-prod             # NotebookLM Azure — hub RAG + ADG-M (App Service) ✅
```

---

## Points de synchronisation (gates)

```mermaid
graph TD
    A["✅ Sprint 1 — LIVRÉ<br/>ADG-M API live<br/>GET /graph/nodes/arcs/health<br/>PATCH /qualification + SQL history<br/>fn-adgm-graph déployé"]
    B["✅ Sprint 2 — LIVRÉ<br/>ADG-M métriques + Visualisation<br/>SPOF betweenness · Clusters Louvain<br/>Graphe intégré NotebookLM Azure<br/>Pipeline Chat→Graphe (Track C)"]
    C["Sprint 3 — Planifié<br/>7RQA rapports +<br/>ADM-M positions"]
    D["Sprint 4 — Planifié<br/>MWP plans +<br/>Simulation"]
    E["Sprint 5 — Planifié<br/>Navigation croisée<br/>+ E2E"]
    
    A -->|"Gate ✅ :<br/>tous les /graph/*<br/>répondent"| B
    B -->|"Gate ✅ :<br/>Louvain + Betweenness<br/>en Neo4j"| C
    C -->|"Gate:<br/>7RQA valide →<br/>write-back Neo4j"| D
    D -->|"Gate:<br/>plans lisibles"| E
    
    style A fill:#d4edda,stroke:#28a745,color:#000
    style B fill:#d4edda,stroke:#28a745,color:#000
    style C fill:#fff3cd
    style D fill:#fff3cd
    style E fill:#d1ecf1
```
