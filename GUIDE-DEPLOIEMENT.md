# Guide de déploiement — NotebookLM Azure

> **Environnement : Windows + PowerShell 5.1**
> Toutes les commandes s'exécutent dans PowerShell à la racine du projet `notebooklm-azure/`.

---

## Table des matières

1. [Déploiement rapide](#1-déploiement-rapide)
2. [Paramètres de deploy.ps1](#2-paramètres-de-deployps1)
3. [Ce que fait le script (8 phases)](#3-ce-que-fait-le-script-8-phases)
4. [Post-déploiement — indexer des documents](#4-post-déploiement--indexer-des-documents)
5. [Scénarios avancés](#5-scénarios-avancés)
6. [Teardown — supprimer les ressources](#6-teardown--supprimer-les-ressources)
7. [Gestion continue des documents](#7-gestion-continue-des-documents)
8. [Troubleshooting](#8-troubleshooting)

---

## 1. Déploiement rapide

**Prérequis :**
- [Azure CLI](https://aka.ms/installazurecliwindows) 2.60+
- [Python 3.11+](https://python.org/downloads)
- Une subscription Azure avec droits de créer des ressources

Docker **n'est pas nécessaire** — le build de l'image se fait dans le cloud via `az acr build`.

```powershell
# 1. Se connecter à Azure
az login

# 2. Lancer le déploiement complet (~15 min)
.\deploy.ps1

# Sur poste avec proxy d'entreprise (Zscaler, Forcepoint…)
.\deploy.ps1 -SkipSSL
```

À la fin du script :
- Toutes les ressources Azure sont créées et configurées
- L'image Docker est buildée et poussée dans Azure Container Registry
- Le fichier `.env` est généré à la racine du projet
- Le virtualenv Python est créé dans `api/.venv/`
- Un health check valide que l'API est bien démarrée en production

```powershell
# Démarrer l'interface locale (pointe sur les ressources Azure)
.\start-dev.ps1
```

---

## 2. Paramètres de deploy.ps1

| Paramètre | Type | Défaut | Description |
|-----------|------|--------|-------------|
| `-Location` | string | `swedencentral` | Région Azure du déploiement |
| `-ProjectName` | string | `nlmazure` | Préfixe des noms de ressources (3-8 chars lowercase) |
| `-ResourceGroup` | string | `rg-<ProjectName>-prod` | Nom exact du Resource Group (si différent de la convention) |
| `-Subscription` | string | *(auto)* | ID ou nom de la subscription. Si omis et une seule dispo, sélectionnée automatiquement |
| `-Neo4jPassword` | SecureString | *(prompt)* | Mot de passe du compte `neo4j` pour le conteneur ACI. Demandé interactivement si absent |
| `-Neo4jUri` | string | *(vide)* | URI `bolt+s://` d'une instance neo4j existante. Si fourni : pas de déploiement ACI |
| `-SkipSSL` | switch | false | Bypass SSL pour proxy d'entreprise. Désactive la vérif SSL az CLI et injecte les certs Zscaler Windows dans certifi |
| `-ImageOnly` | switch | false | Build + push de l'image Docker uniquement, sans toucher à l'infra Bicep |
| `-Force` | switch | false | Pas de prompt de confirmation (écrase `.env` existant) |

**Exemples :**

```powershell
# Standard — laisse le script choisir la subscription automatiquement
.\deploy.ps1

# Avec proxy d'entreprise
.\deploy.ps1 -SkipSSL

# Région et nom de projet personnalisés
.\deploy.ps1 -Location francecentral -ProjectName monprojet

# Neo4j existant (pas de déploiement ACI)
.\deploy.ps1 -Neo4jUri "bolt+s://mon-neo4j.example.com:7687" -SkipSSL

# Rebuild l'image uniquement (après modification du code API)
.\deploy.ps1 -ImageOnly -SkipSSL

# Resource Group personnalisé (infra déjà existante avec un autre nom)
.\deploy.ps1 -ResourceGroup rg-sp4-d-vgi-azu-notebook-txt -ProjectName nlmavgi
```

---

## 3. Ce que fait le script (8 phases)

### Phase 0 — Vérification des prérequis
Vérifie que `az` (Azure CLI) et `python` (3.11+) sont installés et affiche leurs versions détectées.

### Phase 1 — SSL + Extensions Azure CLI
- Si `-SkipSSL` : désactive la vérification SSL (`az config set core.verify_ssl=false`) et crée un bundle certifi temporaire en injectant les certificats Zscaler depuis le store Windows — nécessaire pour `az acr build` qui utilise la librairie Python `requests`
- Installe les extensions `containerapp` et `bicep` **en parallèle**

### Phase 2 — Authentification Azure
- Vérifie si une session `az login` est active, sinon ouvre le navigateur
- Si une seule subscription est disponible, la sélectionne automatiquement
- Si plusieurs : affiche un menu interactif
- Calcule l'Object ID de l'identité qui déploie (`az ad signed-in-user show`)

### Phase 3 — Build & push de l'image Docker
- Vérifie si l'ACR existe déjà (créé lors d'un déploiement précédent)
- Lance `az acr build` dans un job PowerShell en arrière-plan (évite le crash d'encodage cp1252 en console)
- Polle le statut du build toutes les 10 secondes via `az acr task list-runs`
- Si l'ACR n'existe pas encore (premier déploiement) : le build est reporté après la Phase 4

### Phase 4 — Infrastructure Bicep (~12 min)
Déploie ou met à jour toutes les ressources Azure :

| Ressource | Module | Détail |
|-----------|--------|--------|
| Application Insights + Log Analytics | `monitoring.bicep` | Monitoring et traces |
| Key Vault | `keyvault.bicep` | Stockage des secrets + accès déployeur |
| Azure OpenAI | `openai.bicep` | GPT-4o + text-embedding-3-large |
| Azure AI Search | `search.bicep` | Index vectoriel S1, semantic ranker |
| Blob Storage | `storage.bicep` | Documents sources |
| Document Intelligence | `docint.bicep` | OCR PDF |
| Container Registry | `registry.bicep` | Images Docker |
| neo4j-legacykb (ACI) | `neo4j-legacykb.bicep` | Conditonnel : si pas de `-Neo4jUri` |
| App Service | `containerapp.bicep` | API FastAPI + frontend |

Après le déploiement Bicep, les secrets sont automatiquement écrits dans Key Vault :
- `openai-endpoint`, `search-endpoint`, `docint-endpoint`, `storage-account-name`
- `neo4j-legacykb-password`
- `api-key` (clé générée aléatoirement par le script)

### Phase 5 — Génération du fichier `.env`
Génère `.env` à la racine du projet avec les outputs du déploiement Bicep. L'`API_KEY` générée en Phase 4 est incluse. `NEO4J_LEGACYKB_PASSWORD` est masqué (`***`) pour éviter de l'écrire en clair sur disque.

### Phase 6 — Rôles IAM (en parallèle)
Assigne les rôles nécessaires pour le développement local :

| Rôle | Bénéficiaire | Pour |
|------|-------------|------|
| Cognitive Services OpenAI User | Vous (az login) | Appels Azure OpenAI depuis le poste local |
| Search Index Data Contributor | Vous | Indexation de documents en local |
| Cognitive Services User | Vous | Azure Document Intelligence |
| Storage Blob Data Contributor | Vous | Upload de documents |
| Key Vault Secrets User | UAMI de l'App Service | L'API peut lire les secrets Key Vault |

> Attendez **3-5 minutes** après le déploiement avant d'indexer des documents (propagation IAM).

### Phase 7 — Virtualenv Python
Crée (ou réutilise) `api/.venv/` et installe les dépendances de `api/requirements.txt` et `ingest/requirements.txt`. Si `-SkipSSL` : injecte les certificats Zscaler dans le bundle certifi du venv.

### Phase 8 — Validation post-déploiement
Tente 5 fois (toutes les 20 s) un GET sur `/health`. Si l'API répond, teste aussi `/api/legacykb/health` avec l'API Key générée.

---

## 4. Post-déploiement — indexer des documents

### Accéder à l'application en production

```powershell
# L'URL de production est affichée à la fin de deploy.ps1
# Elle est aussi récupérable via :
$rg = "rg-<ProjectName>-prod"   # ou votre ResourceGroup personnalisé
az webapp list -g $rg --query "[0].defaultHostName" -o tsv
```

### Indexer des documents via l'interface (recommandé)

1. Ouvrir l'URL de production dans un navigateur
2. Cliquer sur **Ajouter un document** dans la barre supérieure
3. Sélectionner le fichier (PDF, DOCX, PPTX, XLSX, Markdown, TXT, code…)
4. Un toast de progression s'affiche — attendre le toast de confirmation

### Indexer des documents en masse (CLI)

```powershell
# Déposer les fichiers dans documents/
Copy-Item "C:\chemin\vers\mes-fichiers\*" documents\

# Venv activé, depuis la racine du projet
api\.venv\Scripts\Activate.ps1
python -m ingest.ingest --docs-dir documents/
```

La déduplication par hash SHA-256 évite de ré-indexer les fichiers déjà traités.

### Lancer l'interface locale

```powershell
.\start-dev.ps1
```

L'interface s'ouvre sur `http://127.0.0.1:8000` et pointe sur vos ressources Azure.

---

## 5. Scénarios avancés

### Redéployer après modification du code API

```powershell
# Rebuild l'image et met à jour l'App Service — sans recréer l'infra
.\deploy.ps1 -ImageOnly -SkipSSL
```

### Connecter une instance neo4j existante

Si vous avez déjà un conteneur neo4j-legacykb tournant ailleurs :

```powershell
.\deploy.ps1 -Neo4jUri "bolt+s://neo4j-legacykb-myprod.swedencentral.azurecontainer.io:7687" -SkipSSL
```

- `deployLegacyKb=false` dans Bicep → pas d'ACI créé
- L'URI fournie est passée directement à l'App Service (`NEO4J_LEGACYKB_URI`)
- Le mot de passe est quand même demandé et stocké dans Key Vault

### Déployer sur une subscription ou région différente

```powershell
.\deploy.ps1 -Subscription "Mon Abonnement Dev" -Location francecentral -ProjectName monprojet
```

### Resource Group avec nom personnalisé

Utile si votre organisation impose une convention de nommage différente :

```powershell
.\deploy.ps1 -ResourceGroup rg-sp4-d-vgi-azu-notebook-txt -ProjectName nlmavgi
```

### Forcer la régénération du `.env`

```powershell
.\deploy.ps1 -Force
```

---

## 6. Teardown — supprimer les ressources

```powershell
# Suppression interactive (demande confirmation)
.\teardown.ps1

# Suppression avec un ProjectName personnalisé
.\teardown.ps1 -ProjectName monprojet

# Resource Group avec nom exact (si différent de la convention rg-<ProjectName>-prod)
.\teardown.ps1 -ResourceGroup rg-sp4-d-vgi-azu-notebook-txt

# Sans prompt de confirmation
.\teardown.ps1 -Force
.\teardown.ps1 -ResourceGroup rg-sp4-d-vgi-azu-notebook-txt -Force
```

La suppression du Resource Group est **irréversible** et supprime toutes les ressources contenues :
Azure OpenAI, Azure AI Search, Document Intelligence, Key Vault, Blob Storage, Container Registry, App Service, Application Insights, UAMI, et l'ACI neo4j-legacykb.

La suppression s'effectue en arrière-plan Azure (~5-10 min). Suivre la progression sur le portail Azure.

**Fichiers locaux à supprimer manuellement si souhaité :**
- `.env` — contient les endpoints et l'API Key
- `api/.venv/` — virtualenv Python

---

## 7. Gestion continue des documents

### Ajouter de nouveaux documents

Déposer les fichiers dans `documents/` et relancer l'ingestion. La déduplication SHA-256 ignore les fichiers déjà indexés.

```powershell
api\.venv\Scripts\Activate.ps1
python -m ingest.ingest --docs-dir documents/
# → "Skipped (déjà indexé) : ancien.pdf"
# → "Indexé : nouveau-document.pdf (32 chunks)"
```

### Mettre à jour un document (version modifiée)

Le hash change → les anciens chunks restent dans l'index. Il faut les supprimer manuellement avant de re-indexer.

```powershell
api\.venv\Scripts\Activate.ps1

# Récupérer un token Azure AI Search
$token   = az account get-access-token --resource https://search.azure.com --query accessToken -o tsv
$headers = @{ Authorization = "Bearer $token"; "Content-Type" = "application/json" }
$searchEp = (Get-Content .env | Select-String "AZURE_SEARCH_ENDPOINT=(.+)").Matches.Groups[1].Value

# Trouver les chunks de l'ancien fichier
$filter = [uri]::EscapeDataString("source_file eq 'mon-document.pdf'")
$result = Invoke-RestMethod -Uri "$searchEp/indexes/notebooklm-chunks/docs?`$filter=$filter&`$select=id&api-version=2024-05-01-preview" -Headers $headers
$ids    = $result.value | ForEach-Object { @{ id = $_.id; "@search.action" = "delete" } }

# Supprimer les chunks
$body = @{ value = $ids } | ConvertTo-Json -Depth 5
Invoke-RestMethod -Method POST `
  -Uri "$searchEp/indexes/notebooklm-chunks/docs/index?api-version=2024-05-01-preview" `
  -Headers $headers -Body $body

# Re-copier et re-indexer
Copy-Item "C:\chemin\mon-document-v2.pdf" "documents\mon-document.pdf"
python -m ingest.ingest --docs-dir documents/
```

### Supprimer un document de l'index

Idem ci-dessus (étapes "Trouver" et "Supprimer"), sans la re-indexation. Supprimer aussi le fichier de `documents/`.

### Tout re-indexer depuis zéro

```powershell
api\.venv\Scripts\Activate.ps1

# Supprimer l'index (ATTENTION : perte de tous les chunks)
python -c "
from azure.identity import DefaultAzureCredential
from azure.search.documents.indexes import SearchIndexClient
import os; from dotenv import load_dotenv; load_dotenv()
SearchIndexClient(os.environ['AZURE_SEARCH_ENDPOINT'], DefaultAzureCredential()).delete_index('notebooklm-chunks')
print('Index supprimé.')
"

# Re-indexer (force-reindex ignore la déduplication par hash)
python -m ingest.ingest --docs-dir documents/ --force-reindex
```

---

## 8. Troubleshooting

| Symptôme | Cause probable | Solution |
|---|---|---|
| `az acr build` : `CERTIFICATE_VERIFY_FAILED` | Proxy Zscaler — certifi ne connaît pas le cert racine | Utiliser `-SkipSSL` |
| `az extension add` échoue en SSL | Idem | `az config set core.verify_ssl=false` puis relancer |
| Déploiement Bicep : `quota exceeded` | Quota OpenAI insuffisant dans la région | Changer `-Location swedencentral` (ou `francecentral`) |
| Déploiement Bicep : `InvalidResourceLocation` | Ressources existantes dans une autre région | Utiliser la même `-Location` que l'infra existante |
| API retourne 401 sur `/api/*` | API_KEY manquante ou incorrecte | Vérifier `.env` → `API_KEY` ; ou passer `X-API-Key: <value>` |
| API retourne 401 sur ingestion locale | Propagation IAM pas encore effective | Attendre 5 min après deploy.ps1 et relancer |
| `ingest.py` : `DisableLocalAuthError` | `disableLocalAuth: true` actif, `az login` non détecté | Vérifier `az account show` renvoie votre compte |
| App Service ne démarre pas | Variables env manquantes ou image incorrecte | `az webapp log tail -g <rg> -n <app-name>` |
| neo4j-legacykb inaccessible | ACI en cours de démarrage (2-3 min) | Attendre et retester `/api/legacykb/health` |
| `Set-ExecutionPolicy` refusé | Politique d'entreprise | Lancer `python -m ...` directement sans activer le venv |
| Health check échoue après deploy | App Service encore en cold start | Attendre 2-3 min et tester manuellement `/health` |
| `.env` a `NEO4J_LEGACYKB_PASSWORD=***` | Masqué intentionnellement | Renseigner manuellement le vrai mot de passe dans `.env` |
