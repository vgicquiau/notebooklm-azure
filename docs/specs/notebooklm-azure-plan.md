# Plan d'action — Implémentation NotebookLM Azure

> Durée totale estimée : **~7h** pour un senior développeur Azure.
> Chaque phase se clôt sur un checkpoint de validation avant de passer à la suivante.
> Dépendance stricte : chaque phase requiert que la précédente soit validée.

---

## Vue d'ensemble

```
Phase 0  Prérequis & outils             ~15 min   ──┐
Phase 1  Scaffold du projet             ~20 min   ──┤
Phase 2  Infrastructure Bicep           ~60 min   ──┤  Blocker : Azure subscription active
Phase 3  Configuration post-déploiement ~20 min   ──┤
Phase 4  Pipeline d'ingestion           ~90 min   ──┤
Phase 5  Backend RAG API                ~90 min   ──┤
Phase 6  Frontend chat                  ~20 min   ──┤
Phase 7  Tests end-to-end locaux        ~30 min   ──┤
Phase 8  Containerisation & prod        ~30 min   ──┤
Phase 9  Validation production          ~15 min   ──┘
```

---

## Phase 0 — Prérequis & outils
**Durée : ~15 min | Prérequis : aucun**

### Tâches

| # | Action | Commande / vérification |
|---|---|---|
| 0.1 | Vérifier Azure CLI ≥ 2.60 | `az --version` |
| 0.2 | Installer extension Container Apps | `az extension add --name containerapp --upgrade` |
| 0.3 | Installer Bicep CLI | `az bicep install && az bicep version` |
| 0.4 | Vérifier Python ≥ 3.11 | `python --version` |
| 0.5 | Vérifier Docker daemon actif | `docker info` |
| 0.6 | Se connecter à Azure | `az login && az account set --subscription "<ID>"` |
| 0.7 | Définir les variables shell | voir bloc ci-dessous |

```bash
export PROJECT="notebooklm"
export ENV="prod"
export LOCATION="francecentral"
export RG="rg-${PROJECT}-${ENV}"
export DEPLOYER_OID=$(az ad signed-in-user show --query id -o tsv)
```

### Checkpoint ✅
```bash
az account show --query "{sub:id, tenant:tenantId}" -o table
# → affiche la subscription cible sans erreur
```

---

## Phase 1 — Scaffold du projet
**Durée : ~20 min | Prérequis : Phase 0**

### Tâches

| # | Action | Détail |
|---|---|---|
| 1.1 | Créer le répertoire racine | `mkdir notebooklm-azure && cd notebooklm-azure` |
| 1.2 | Créer l'arborescence complète | voir structure ci-dessous |
| 1.3 | Créer les fichiers `__init__.py` | `ingest/`, `ingest/chunkers/`, `api/`, `api/models/`, `api/routers/`, `api/services/` |
| 1.4 | Créer `.gitignore` | voir contenu ci-dessous |
| 1.5 | Créer `.env.example` | copier depuis le guide section 8 |
| 1.6 | Créer `documents/.gitkeep` | `touch documents/.gitkeep` |

### Arborescence à créer

```bash
mkdir -p infra/modules
mkdir -p ingest/chunkers
mkdir -p api/models api/routers api/services
mkdir -p frontend
mkdir -p documents

touch ingest/__init__.py ingest/chunkers/__init__.py
touch api/__init__.py api/models/__init__.py api/routers/__init__.py api/services/__init__.py
touch documents/.gitkeep
```

### `.gitignore` à créer

```gitignore
.env
.env.local
__pycache__/
*.pyc
.venv/
*.egg-info/
.pytest_cache/
node_modules/
dist/
*.log
.DS_Store
```

### Checkpoint ✅
```bash
find . -type f | sort
# → affiche l'arborescence avec tous les __init__.py et .gitkeep
```

---

## Phase 2 — Infrastructure Bicep
**Durée : ~60 min | Prérequis : Phase 1 + Azure subscription active**

### Tâches — Fichiers à créer dans l'ordre

| # | Fichier | Source dans le guide |
|---|---|---|
| 2.1 | `infra/modules/monitoring.bicep` | Section 3 |
| 2.2 | `infra/modules/keyvault.bicep` | Section 3 |
| 2.3 | `infra/modules/openai.bicep` | Section 3 |
| 2.4 | `infra/modules/search.bicep` | Section 3 |
| 2.5 | `infra/modules/storage.bicep` | Section 3 |
| 2.6 | `infra/modules/docint.bicep` | Section 3 |
| 2.7 | `infra/modules/registry.bicep` | Section 3 |
| 2.8 | `infra/modules/containerapp.bicep` | Section 3 |
| 2.9 | `infra/main.bicep` | Section 3 |
| 2.10 | `infra/main.parameters.json` | Section 3 — injecter `$DEPLOYER_OID` |

### Tâches — Déploiement

| # | Action | Commande |
|---|---|---|
| 2.11 | Créer le Resource Group | `az group create --name "$RG" --location "$LOCATION"` |
| 2.12 | Remplacer le placeholder OID | `sed -i "s/<REMPLACER...>/$DEPLOYER_OID/" infra/main.parameters.json` |
| 2.13 | Valider le template (what-if) | `az deployment group what-if -g "$RG" --template-file infra/main.bicep --parameters infra/main.parameters.json --parameters deployerObjectId="$DEPLOYER_OID"` |
| 2.14 | Déployer | `az deployment group create -g "$RG" --template-file infra/main.bicep --parameters infra/main.parameters.json --parameters deployerObjectId="$DEPLOYER_OID" --name "deploy-init"` |

> ⚠️ **Points d'attention Bicep**
> - Azure OpenAI n'est pas disponible dans toutes les régions. `francecentral` supporte gpt-4o et text-embedding-3-large.
> - Le déploiement prend ~10-15 min (OpenAI model deployments sont lents).
> - Le Container App démarre avec l'image placeholder `containerapps-helloworld` — c'est normal.

### Checkpoint ✅
```bash
az resource list -g "$RG" --query "[].{name:name, type:type}" -o table
# → 9 ressources : OpenAI, Search, Storage, DocInt, KeyVault, ACR, ContainerApp, ContainerAppEnv, AppInsights
```

---

## Phase 3 — Configuration post-déploiement
**Durée : ~20 min | Prérequis : Phase 2 validée**

### Tâches

| # | Action | Commande |
|---|---|---|
| 3.1 | Récupérer le nom du déploiement | `DEPLOY=$(az deployment group list -g "$RG" --query "[0].name" -o tsv)` |
| 3.2 | Extraire les outputs Bicep | voir bloc ci-dessous |
| 3.3 | Remplir `.env` depuis les outputs | `cp .env.example .env` puis sed |
| 3.4 | Assigner rôle **Cognitive Services OpenAI User** au déployeur | `az role assignment create ...` |
| 3.5 | Assigner rôle **Search Index Data Contributor** au déployeur | `az role assignment create ...` |
| 3.6 | Assigner rôle **Cognitive Services User** (DocInt) au déployeur | `az role assignment create ...` |
| 3.7 | Assigner rôle **Storage Blob Data Contributor** au déployeur | `az role assignment create ...` |

```bash
# Extraction des outputs
OPENAI_EP=$(az deployment group show -g "$RG" -n "$DEPLOY" --query properties.outputs.openAIEndpoint.value -o tsv)
SEARCH_EP=$(az deployment group show -g "$RG" -n "$DEPLOY" --query properties.outputs.searchEndpoint.value -o tsv)
STORAGE_ACC=$(az deployment group show -g "$RG" -n "$DEPLOY" --query properties.outputs.storageAccountName.value -o tsv)
DOCINT_EP=$(az deployment group show -g "$RG" -n "$DEPLOY" --query properties.outputs.docIntEndpoint.value -o tsv)
ACR_SERVER=$(az deployment group show -g "$RG" -n "$DEPLOY" --query properties.outputs.registryLoginServer.value -o tsv)
KV_NAME=$(az deployment group show -g "$RG" -n "$DEPLOY" --query properties.outputs.keyVaultName.value -o tsv)

# Remplissage de .env
sed -i "s|AZURE_OPENAI_ENDPOINT=.*|AZURE_OPENAI_ENDPOINT=$OPENAI_EP|" .env
sed -i "s|AZURE_SEARCH_ENDPOINT=.*|AZURE_SEARCH_ENDPOINT=$SEARCH_EP|" .env
sed -i "s|AZURE_DOCINT_ENDPOINT=.*|AZURE_DOCINT_ENDPOINT=$DOCINT_EP|" .env
sed -i "s|AZURE_STORAGE_ACCOUNT_NAME=.*|AZURE_STORAGE_ACCOUNT_NAME=$STORAGE_ACC|" .env
sed -i "s|AZURE_KEYVAULT_URI=.*|AZURE_KEYVAULT_URI=https://${KV_NAME}.vault.azure.net/|" .env

# Attribution des rôles
SCOPE="/subscriptions/$(az account show --query id -o tsv)/resourceGroups/$RG"
az role assignment create --assignee "$DEPLOYER_OID" --role "Cognitive Services OpenAI User" --scope "$SCOPE"
az role assignment create --assignee "$DEPLOYER_OID" --role "Search Index Data Contributor" --scope "$SCOPE"
az role assignment create --assignee "$DEPLOYER_OID" --role "Cognitive Services User" --scope "$SCOPE"
az role assignment create --assignee "$DEPLOYER_OID" --role "Storage Blob Data Contributor" --scope "$SCOPE"
```

> ⚠️ Les rôles IAM peuvent mettre **2-3 minutes** à propager avant d'être effectifs.

### Checkpoint ✅
```bash
cat .env | grep -v "^#" | grep -v "^$"
# → toutes les variables AZURE_* sont remplies avec des valeurs réelles (pas de placeholder)

az role assignment list --assignee "$DEPLOYER_OID" --scope "$SCOPE" --query "[].roleDefinitionName" -o tsv
# → liste les 4 rôles assignés
```

---

## Phase 4 — Pipeline d'ingestion
**Durée : ~90 min | Prérequis : Phase 3 validée + propagation IAM**

### Tâches — Fichiers à créer dans l'ordre

| # | Fichier | Dépendances internes |
|---|---|---|
| 4.1 | `ingest/chunkers/base.py` | aucune |
| 4.2 | `ingest/chunkers/pdf_chunker.py` | `base.py` |
| 4.3 | `ingest/chunkers/md_chunker.py` | `base.py` |
| 4.4 | `ingest/chunkers/docx_chunker.py` | `base.py` |
| 4.5 | `ingest/embedder.py` | aucune |
| 4.6 | `ingest/indexer.py` | aucune |
| 4.7 | `ingest/ingest.py` | tous les chunkers + embedder + indexer |
| 4.8 | `ingest/requirements.txt` | — |

### Tâches — Installation & tests

| # | Action | Commande |
|---|---|---|
| 4.9 | Créer le venv et installer | `cd ingest && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt` |
| 4.10 | Préparer 1 document de test de chaque type | copier 1 PDF + 1 MD + 1 DOCX dans `../documents/` |
| 4.11 | Dry-run — vérifier la découverte des fichiers | `python ingest.py --docs-dir ../documents --dry-run` |
| 4.12 | Test unitaire chunker PDF (inspection des chunks) | `python -c "from chunkers.pdf_chunker import PDFChunker; ..."` |
| 4.13 | Ingestion réelle complète | `python ingest.py --docs-dir ../documents` |
| 4.14 | Vérifier le nombre de documents indexés | requête Azure Search ou log de sortie |

> ⚠️ **Points d'attention ingestion**
> - `disableLocalAuth: true` sur Azure OpenAI — `DefaultAzureCredential` doit trouver les credentials `az login`. Si erreur 401 : vérifier la propagation IAM (attendre 3 min).
> - Document Intelligence peut être lent sur les gros PDFs (>50 pages). Tester d'abord avec un petit fichier.
> - Si tiktoken rate-limite : réduire `BATCH_SIZE` dans `embedder.py` de 16 à 8.

### Checkpoint ✅
```bash
# Vérifier que l'index existe et contient des documents
az rest --method GET \
  --url "${SEARCH_EP}/indexes/notebooklm-chunks/docs/\$count?api-version=2024-05-01-preview" \
  --headers "Authorization=Bearer $(az account get-access-token --resource https://search.azure.com --query accessToken -o tsv)"
# → nombre > 0
```

---

## Phase 5 — Backend RAG API
**Durée : ~90 min | Prérequis : Phase 4 validée (index peuplé)**

### Tâches — Fichiers à créer dans l'ordre

| # | Fichier | Dépendances internes |
|---|---|---|
| 5.1 | `api/models/schemas.py` | aucune |
| 5.2 | `api/services/retriever.py` | `schemas.py` |
| 5.3 | `api/services/generator.py` | `retriever.py` (type `RetrievedChunk`) |
| 5.4 | `api/routers/chat.py` | `schemas.py`, `retriever.py`, `generator.py` |
| 5.5 | `api/main.py` | `chat.py`, `retriever.py`, `generator.py` |
| 5.6 | `api/requirements.txt` | — |
| 5.7 | `api/Dockerfile` | `requirements.txt` |

### Tâches — Test local

| # | Action | Commande |
|---|---|---|
| 5.8 | Créer le venv API et installer | `cd api && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt` |
| 5.9 | Copier `.env` dans `api/` | `cp ../.env .env` |
| 5.10 | Lancer l'API | `uvicorn api.main:app --reload --port 8000` |
| 5.11 | Test health check | `curl http://localhost:8000/health` |
| 5.12 | Test premier chat | `curl -X POST .../api/chat -d '{"message":"test"}'` |
| 5.13 | Test avec session_id (historique) | deux appels successifs avec le même session_id |
| 5.14 | Test clear session | `curl -X DELETE .../api/chat/{session_id}` |

> ⚠️ **Points d'attention API**
> - Le `lifespan` initialise les services au démarrage — si les variables `.env` sont manquantes, FastAPI plantera au boot avec un `KeyError`.
> - L'endpoint `/api/chat` est enregistré dans `on_event("startup")` APRÈS le `lifespan`. En dev `--reload`, vérifier que les deux s'exécutent bien à chaque rechargement.
> - `QueryType.SEMANTIC` requiert le Semantic Ranker actif sur Azure AI Search S1. Vérifier le SKU si erreur 400.

### Checkpoint ✅
```bash
curl -s -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Résume les règles métier", "top_k": 3}' | python -m json.tool
# → réponse JSON avec answer (non vide) + sources (liste non vide) + tokens_used > 0
```

---

## Phase 6 — Frontend chat
**Durée : ~20 min | Prérequis : Phase 5 validée**

### Tâches — Fichiers à créer

| # | Fichier | Contenu |
|---|---|---|
| 6.1 | `frontend/index.html` | Guide section 6 |
| 6.2 | `frontend/styles.css` | Guide section 6 |
| 6.3 | `frontend/app.js` | Guide section 6 |

> L'API FastAPI monte le répertoire `frontend/` en static files sur `/`.  
> Aucun build step requis — ouvrir directement `http://localhost:8000`.

### Checkpoint ✅
- Ouvrir `http://localhost:8000` dans Chrome/Edge
- Envoyer une question via l'interface
- Vérifier : bulle de réponse + badge de sources sous la réponse
- Cliquer "↺ Nouvelle conversation" → réinitialisation de l'affichage

---

## Phase 7 — Tests end-to-end locaux
**Durée : ~30 min | Prérequis : Phases 4 + 5 + 6 validées**

### Tâches

| # | Test | Critère de succès |
|---|---|---|
| 7.1 | Question factuelle simple | Réponse avec au moins 1 source citée |
| 7.2 | Question hors corpus | Réponse "Je n'ai pas trouvé…" (pas d'hallucination) |
| 7.3 | Question de synthèse | Réponse structurée avec titres `##` et listes |
| 7.4 | Question de contradiction | Réponse présentant les deux positions avec sources |
| 7.5 | Conversation multi-tours | 3 questions successives avec références au contexte précédent |
| 7.6 | Ingestion d'un 4ème document | `python ingest.py --docs-dir ../documents` + question sur ce doc |
| 7.7 | Réingestion (idempotence) | Re-lancer l'ingestion → "Skipped (déjà indexé)" pour tous les fichiers |
| 7.8 | Force reindex | `python ingest.py --docs-dir ../documents --force-reindex` → tout réindexé |
| 7.9 | Test `top_k` = 1 vs 10 | Vérifier l'impact sur la qualité de la réponse |

### Checkpoint ✅
Tests 7.1 à 7.4 réussis sans hallucination ni erreur 500.

---

## Phase 8 — Containerisation & déploiement production
**Durée : ~30 min | Prérequis : Phase 7 validée**

### Tâches

| # | Action | Commande |
|---|---|---|
| 8.1 | Se connecter à ACR | `az acr login --name "${ACR_SERVER%%.*}"` |
| 8.2 | Builder l'image depuis la racine du projet | `docker build -f api/Dockerfile -t "${ACR_SERVER}/notebooklm-api:latest" .` |
| 8.3 | Tester l'image en local | `docker run --env-file .env -p 8001:8000 "${ACR_SERVER}/notebooklm-api:latest"` |
| 8.4 | Vérifier le container en local | `curl http://localhost:8001/health` |
| 8.5 | Pusher l'image | `docker push "${ACR_SERVER}/notebooklm-api:latest"` |
| 8.6 | Récupérer le nom du Container App | `CA_NAME=$(az containerapp list -g "$RG" --query "[0].name" -o tsv)` |
| 8.7 | Mettre à jour le Container App | `az containerapp update -g "$RG" -n "$CA_NAME" --image "${ACR_SERVER}/notebooklm-api:latest"` |
| 8.8 | Attendre la révision active | `az containerapp revision list -g "$RG" -n "$CA_NAME" -o table` |

> ⚠️ **Points d'attention Docker**
> - Le Dockerfile copie `api/` et `frontend/` depuis la racine — builder depuis la racine du projet, pas depuis `api/`.
> - Variables d'environnement en prod : `AZURE_CLIENT_ID` et `AZURE_KEYVAULT_URI` sont injectées par Container Apps via les `env:` du Bicep. Les autres secrets viennent de Key Vault via le code.
> - Si le Container App ne démarre pas : `az containerapp logs show -g "$RG" -n "$CA_NAME"` pour voir les logs.

### Checkpoint ✅
```bash
REVISION=$(az containerapp revision list -g "$RG" -n "$CA_NAME" \
  --query "[?properties.active].name" -o tsv | head -1)
az containerapp revision show -g "$RG" -n "$CA_NAME" -r "$REVISION" \
  --query properties.healthState -o tsv
# → "Healthy"
```

---

## Phase 9 — Validation production
**Durée : ~15 min | Prérequis : Phase 8 validée**

### Tâches

| # | Test | Commande / action |
|---|---|---|
| 9.1 | Récupérer l'URL de prod | `API_URL=$(az containerapp show -g "$RG" -n "$CA_NAME" --query properties.configuration.ingress.fqdn -o tsv)` |
| 9.2 | Health check prod | `curl -s "https://${API_URL}/health"` |
| 9.3 | Chat prod via curl | `curl -X POST "https://${API_URL}/api/chat" -d '{"message":"test prod"}'` |
| 9.4 | Interface prod dans le navigateur | ouvrir `https://${API_URL}` |
| 9.5 | Test scale-to-zero | attendre 5 min sans requête → `minReplicas: 0` doit provoquer le scale-down |
| 9.6 | Test cold start | première requête après scale-down doit répondre en < 10s |
| 9.7 | Vérifier App Insights | portail Azure → Application Insights → Live Metrics pendant un test |

### Checkpoint ✅
```bash
echo "Interface disponible sur : https://${API_URL}"
curl -s "https://${API_URL}/health" | python -m json.tool
# → {"status": "ok", "service": "notebooklm-api"}
```

---

## Récapitulatif des livrables

| Phase | Livrables créés |
|---|---|
| 0 | Environnement local configuré, session Azure active |
| 1 | Arborescence projet, `.gitignore`, `.env.example` |
| 2 | 9 fichiers Bicep, Resource Group + 9 ressources Azure déployées |
| 3 | `.env` rempli, 4 rôles IAM assignés |
| 4 | 8 fichiers Python ingestion, index Azure AI Search peuplé |
| 5 | 7 fichiers Python API, API FastAPI fonctionnelle en local |
| 6 | 3 fichiers frontend, interface chat fonctionnelle |
| 7 | Suite de tests end-to-end validée, corpus interrogeable |
| 8 | Image Docker dans ACR, Container App déployé sur l'image réelle |
| 9 | URL de production validée, App Insights actif |

---

## Matrice des risques

| Risque | Phase | Probabilité | Mitigation |
|---|---|---|---|
| Azure OpenAI non disponible en `francecentral` | 2 | Faible | Changer `location` en `swedencentral` dans `main.parameters.json` |
| Propagation IAM trop lente (401 sur les APIs) | 3-4 | Moyenne | Attendre 3-5 min après les `role assignment create` |
| Rate limit embedding lors de l'ingestion | 4 | Moyenne | Réduire `BATCH_SIZE` de 16 à 8 dans `embedder.py` |
| `disableLocalAuth: true` bloque les tests SDK | 4-5 | Faible | `DefaultAzureCredential` doit trouver `az login` dans `~/.azure/` |
| Container App ne trouve pas l'image ACR | 8 | Faible | Vérifier le rôle `AcrPull` sur la Managed Identity du Container App |
| Cold start > 30s (Container Apps scale-to-zero) | 9 | Moyenne | Passer `minReplicas: 1` si la latence est inacceptable (+~15 €/mois) |

---

## Ordre de création des fichiers pour Claude Code

```
# Phase 1 — Scaffold
.gitignore
.env.example
documents/.gitkeep
ingest/__init__.py
ingest/chunkers/__init__.py
api/__init__.py
api/models/__init__.py
api/routers/__init__.py
api/services/__init__.py

# Phase 2 — Bicep
infra/modules/monitoring.bicep
infra/modules/keyvault.bicep
infra/modules/openai.bicep
infra/modules/search.bicep
infra/modules/storage.bicep
infra/modules/docint.bicep
infra/modules/registry.bicep
infra/modules/containerapp.bicep
infra/main.bicep
infra/main.parameters.json

# Phase 4 — Ingestion
ingest/chunkers/base.py
ingest/chunkers/pdf_chunker.py
ingest/chunkers/md_chunker.py
ingest/chunkers/docx_chunker.py
ingest/embedder.py
ingest/indexer.py
ingest/ingest.py
ingest/requirements.txt

# Phase 5 — API
api/models/schemas.py
api/services/retriever.py
api/services/generator.py
api/routers/chat.py
api/main.py
api/requirements.txt
api/Dockerfile

# Phase 6 — Frontend
frontend/index.html
frontend/styles.css
frontend/app.js
```

**Total : 37 fichiers à créer.**
