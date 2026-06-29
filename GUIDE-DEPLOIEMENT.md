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
8. [Migrer vers un nouveau Resource Group](#8-migrer-vers-un-nouveau-resource-group)
9. [Troubleshooting](#9-troubleshooting)

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
| `-Neo4jUri` | string | *(vide)* | URI `bolt+ssc://` d'une instance neo4j existante. Si fourni : pas de déploiement ACI |
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
.\deploy.ps1 -Neo4jUri "bolt+ssc://mon-neo4j.example.com:7687" -SkipSSL

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
| Réseau privé (VNet + NSG) | `network.bicep` | Sous-réseaux `snet-aci-legacykb` et `snet-cae` — neo4j-legacykb n'est plus joignable que depuis `snet-cae` |
| neo4j-legacykb (ACI) | `neo4j-legacykb.bicep` | Conditonnel : si pas de `-Neo4jUri`. Déployé dans `snet-aci-legacykb` — IP privée uniquement, pas de FQDN public |
| Container Apps Environment + Container App + Job d'import | `containerapp.bicep` | API FastAPI uniquement, pas de frontend (Azure Container Apps, pas App Service). Environnement intégré au VNet (`snet-cae`) ; ingress public de `ca-api` inchangé. Container Apps Job `caj-import-legacykb-<suffix>` pour l'import GraphML |

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
| Key Vault Secrets User | UAMI du Container App | L'API peut lire les secrets Key Vault |

> Attendez **3-5 minutes** après le déploiement avant d'indexer des documents (propagation IAM).

### Phase 4b — Certificat TLS Neo4j

Si `deployLegacyKb=true` (pas de `-Neo4jUri` fourni) : génère un certificat auto-signé (RSA 2048,
validité 1 an), l'uploade dans le partage Azure Files `neo4j-ssl` monté sur le conteneur, puis
redémarre l'ACI pour que Neo4j démarre avec Bolt + HTTPS chiffrés (`bolt+ssc://`).

### Phase 4c — Import du dump (GraphML ou JSONL) dans Neo4j

Toujours si `deployLegacyKb=true`, `deploy.ps1` appelle automatiquement **`import-neo4j-legacykb.ps1`**.
Depuis la migration réseau de `neo4j-legacykb` vers un VNet privé (voir § Réseau privé ci-dessous),
ce script ne se connecte plus jamais directement à Neo4j (impossible — plus d'IP publique) :

1. Upload le fichier (`-DumpPath`, `.graphml` ou `.jsonl`) dans le partage Azure Files monté dans le conteneur (`/var/lib/neo4j/import/`) — `az storage file upload` par clé de compte, control-plane Azure Storage, fonctionne malgré le réseau privé
2. Déclenche le Container Apps Job `caj-import-legacykb-<suffix>` (`az containerapp job start`), qui s'exécute dans `snet-cae` — seul sous-réseau autorisé par le NSG de `neo4j-legacykb`
3. Le Job charge lui-même le mot de passe Neo4j depuis Key Vault (Managed Identity), attend que Neo4j soit joignable, puis importe selon l'extension du fichier (`api/scripts/import_legacykb.py`) :
   - **`.graphml`** : `CALL apoc.import.graphml(...)` → résultat attendu pour le dump canonique : **5 812 nœuds, 19 368 relations**, puis applique automatiquement le correctif `fix_utf8.cypher` (bug de double-encodage propre à `apoc.import.graphml`)
   - **`.jsonl`** : une ligne JSON par nœud/relation (`{"_type": "node", "id", "labels", "props"}` / `{"_type": "relationship", "fromId", "toId", "relType", "props"}`) ; création par lots via `apoc.create.node`/`apoc.create.relationship`, sans upsert — toujours additif, utiliser `-PurgeBeforeImport` pour réimporter sans dupliquer
4. `import-neo4j-legacykb.ps1` attend la fin de l'exécution du Job (jusqu'à 10 min) et relit son résultat (déposé en JSON dans le même partage Azure Files, via `az storage file download`)

> **Si le dump est absent** (`ingest/extract/repartition_cleaned_export.graphml` par défaut), l'import est ignoré silencieusement et un avertissement est affiché. L'application démarre mais la vue Legacy KB retournera des erreurs 502 / un graphe vide.
>
> **⚠️ `ingest/extract/`, pas `docs/extract/`** : tout le dossier `docs/` est exclu de Git
> (`.gitignore`) — après un `git clone`, `docs/extract/` **n'existe pas du tout**, ce qui ne
> laissait aucune information à un nouvel utilisateur sur où déposer son export. `ingest/`
> n'est lui pas exclu : `ingest/extract/` (avec un `README.md` qui explique quoi y mettre)
> existe donc déjà après le clone. Déposez-y votre fichier `.graphml` ou `.jsonl` avant de
> lancer `deploy.ps1`/`import-neo4j-legacykb.ps1`/`migrate-rg.ps1`.

> **Si `-Neo4jUri` est fourni** : l'ACI n'est pas créé et cet import est ignoré — vous êtes responsable de peupler votre instance Neo4j externe.

### Phase 7 — Virtualenv Python
Crée (ou réutilise) `api/.venv/` et installe les dépendances de `api/requirements.txt` et `ingest/requirements.txt`. Si `-SkipSSL` : injecte les certificats Zscaler dans le bundle certifi du venv.

### Phase 8 — Validation post-déploiement
Tente 5 fois (toutes les 20 s) un GET sur `/health`. Si l'API répond, teste aussi `/api/legacykb/health` avec l'API Key générée.

---

## 4. Post-déploiement — indexer des documents

### Le frontend ne tourne qu'en local — jamais sur Azure

Le Container App déployé (`ca-api-<suffix>`) n'héberge que l'API JSON (`/api/*`, `/health`) —
l'image Docker ne contient pas `frontend/` (cf. [api/Dockerfile](api/Dockerfile)), donc il n'y a
**aucune page web à ouvrir sur l'URL de production**. C'est volontaire : ça évite d'exposer
publiquement une interface donnant accès à des données sensibles (cf.
[docs/specs/SECURITY_AUDIT.md](docs/specs/SECURITY_AUDIT.md)).

Le Container App reste nécessaire pour deux usages purement API :
- `mcp-legacykb` (serveur MCP VS Code/Claude Desktop), qui passe par son URL HTTPS pour
  contourner l'inspection SSL Zscaler sur le port Bolt direct (cf.
  [mcp-legacykb/README.md](mcp-legacykb/README.md))
- Le health check de validation post-déploiement (`/health`, `/api/legacykb/health`)

### Utiliser l'interface (uniquement en local)

```powershell
# L'interface web tourne en local et pointe sur les ressources Azure (.env généré par deploy.ps1)
.\start-dev.ps1
```

1. Ouvrir `http://127.0.0.1:8000` (ouvert automatiquement par le script)
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
# Rebuild l'image et met à jour le Container App — sans recréer l'infra
.\deploy.ps1 -ImageOnly -SkipSSL
```

### Connecter une instance neo4j existante

Si vous avez déjà un conteneur neo4j-legacykb tournant ailleurs (atteignable depuis `ca-api` —
ex. une IP privée dans le même VNet, ou une instance encore exposée publiquement) :

```powershell
.\deploy.ps1 -Neo4jUri "bolt+ssc://10.20.1.4:7687" -SkipSSL
```

- `deployLegacyKb=false` dans Bicep → pas d'ACI créé
- L'URI fournie est passée directement au Container App (`NEO4J_LEGACYKB_URI`)
- Le mot de passe est quand même demandé et stocké dans Key Vault

### ⚠️ Réseau privé neo4j-legacykb — points de vigilance pour reproduire cette architecture

`neo4j-legacykb` est déployé en réseau privé (VNet `vnet-<suffix>`, sous-réseaux
`snet-aci-legacykb`/`snet-cae`, NSG — voir [ARCHITECTURE.md § 8](ARCHITECTURE.md#8-infrastructure-azure)).
Sur un **Resource Group vierge** (premier déploiement), tout se crée correctement du premier
coup. Deux pièges spécifiques se posent uniquement si vous appliquez cette architecture à un
déploiement **préexistant** (ex. une instance qui tournait encore sans VNet) :

**1. Recréation forcée de l'environnement Container Apps et de l'ACI**

Azure interdit d'ajouter une intégration VNet à un environnement Container Apps déjà existant
(erreur `ManagedEnvironmentCannotAddVnetToExistingEnv`). Pour appliquer cette architecture à un
déploiement existant, il faut **supprimer puis recréer** `cae-<suffix>` ET `ca-api-<suffix>` —
coupure de l'API de quelques minutes. Même chose pour l'ACI : changer son sous-réseau réseau force
aussi une suppression/recréation (`SubnetIdCannotChange`), ce qui **efface les données Neo4j**
(pas de disque persistant pour la base elle-même — seuls les partages Azure Files `neo4j-import`
et `neo4j-ssl` survivent). Un ré-import du dump GraphML (`import-neo4j-legacykb.ps1`) est donc
nécessaire après la recréation.

```powershell
# Si vous migrez une instance existante vers cette architecture réseau :
az containerapp delete -g <rg> -n ca-api-<suffix> --yes
az containerapp env delete -g <rg> -n cae-<suffix> --yes
az container delete -g <rg> -n aci-neo4j-legacykb-<suffix> --yes
# Puis redéployer normalement (.\deploy.ps1) — tout se recrée avec le VNet, et
# import-neo4j-legacykb.ps1 est rappelé automatiquement pour repeupler la base
```

**2. Policy de tags obligatoires sur l'abonnement**

Si votre abonnement applique une policy de tags obligatoires similaire à
*"Agentic Studio — Baseline Security"* (5 tags requis : `Squad`, `Environment`, `CostCenter`,
`ManagedBy`, `Project` — attention à la casse), le déploiement des **nouvelles ressources
réseau** (VNet, NSG) échouera avec `RequestDisallowedByPolicy` tant que ces tags ne sont pas
renseignés avec de vraies valeurs. `infra/main.bicep` (variable `tags`) définit actuellement des
valeurs génériques placeholder (`Squad=notebooklm-azure`, `CostCenter=unknown`) — à adapter aux
conventions de votre organisation avant un déploiement dans un nouvel abonnement/RG si une policy
de ce type existe.

### Mettre à jour le dump GraphML dans Neo4j (sans redéploiement complet)

Lorsque le fichier `ingest/extract/repartition_cleaned_export.graphml` est mis à jour — ou pour
repeupler une nouvelle instance neo4j-legacykb (nouveau `-ProjectName`, nouveau Resource Group...)
— relancez l'import seul sans toucher à l'infrastructure. `-StorageAccountName` et `-JobName` sont
découverts automatiquement depuis `-ResourceGroup` (cas courant : un seul conteneur
neo4j-legacykb dans le RG) :

```powershell
.\import-neo4j-legacykb.ps1 -ResourceGroup rg-mon-rg -SkipSSL
```

Le mot de passe Neo4j n'est plus demandé : `neo4j-legacykb` n'ayant plus d'IP publique, le script
ne s'y connecte plus jamais directement — il upload le dump (control-plane Azure Files) puis
déclenche le Container Apps Job `caj-import-legacykb-<suffix>`, qui charge lui-même le mot de
passe depuis Key Vault via sa Managed Identity et exécute l'import depuis l'intérieur du VNet.

S'il y a **plusieurs** conteneurs neo4j-legacykb dans le même RG (ex. plusieurs déploiements
successifs sous des noms de projet différents), précisez `-ProjectName` pour désambiguïser :

```powershell
.\import-neo4j-legacykb.ps1 -ResourceGroup rg-mon-rg -ProjectName nlmrep -SkipSSL
```

Le correctif `fix_utf8.cypher` (double-encodage UTF-8/Latin-1 systématique d'APOC) est appliqué
automatiquement après l'import — aucune étape manuelle requise.

> **Remarque** : L'import est additif — si des nœuds existent déjà, APOC les met à jour (upsert par propriété `id`). Pour repartir d'une base vide (ex. le nouveau dump a retiré des nœuds depuis le dernier import), ajoutez `-PurgeBeforeImport` :
>
> ```powershell
> .\import-neo4j-legacykb.ps1 -ResourceGroup rg-mon-rg -PurgeBeforeImport -SkipSSL
> ```
>
> Supprime tous les nœuds et relations (`MATCH (n) DETACH DELETE n`) avant l'import — destructif et irréversible, flag opt-in explicite.

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
Azure OpenAI, Azure AI Search, Document Intelligence, Key Vault, Blob Storage, Container Registry, Container Apps Environment + Container App, Application Insights, UAMI, et l'ACI neo4j-legacykb.

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

## 8. Migrer vers un nouveau Resource Group

Si votre organisation impose une durée de vie limitée aux Resource Groups, utilisez
`migrate-rg.ps1` pour déplacer toutes les ressources NotebookLM Azure vers un nouveau RG (même
subscription ou subscription différente, même tenant Entra) **sans tout reconstruire**.

### Pourquoi ce n'est pas un simple redéploiement

La quasi-totalité des ressources Azure supportent le déplacement ARM natif ("resource move") —
une opération de métadonnées qui **préserve les données et les endpoints** (index Azure AI
Search, images ACR, secrets Key Vault, blobs). Certaines ressources ne le supportent pas et sont
donc recréées en redéployant **l'intégralité de `infra/main.bicep`** (comme `deploy.ps1`, pas un
module isolé — depuis la migration réseau, `containerapp.bicep` dépend du sous-réseau créé par
`network.bicep` et du storage account créé par `neo4j-legacykb.bicep` ; laisser Bicep résoudre
cette chaîne de dépendances plutôt que l'orchestrer à la main évite de la reproduire — et de la
rater — manuellement) :

| Ressource | Pourquoi recréée |
|---|---|
| VNet + NSG (`vnet-<suffix>`, `snet-aci-legacykb`, `snet-cae`) | Ressources réseau neuves, aucune donnée — recréées sans coût par `network.bicep` |
| Container App + Managed Environment (`ca-api-<suffix>`, `cae-<suffix>`) + Job (`caj-import-legacykb-<suffix>`) | Azure Container Apps ne supporte pas le move ARM — recréés par `containerapp.bicep`, qui crée lui-même une UAMI fraîche |
| Conteneur ACI `neo4j-legacykb` | Les `containerGroups` ACI ne supportent aucun move ; le graphe vit de toute façon en mémoire éphémère (seuls `/import` et `/ssl` sont sur Azure Files) — il est ré-importé via le Job (cf. §7) |

Conséquence pratique : **pas de ré-indexation Azure AI Search, pas de ré-embedding, pas de copie
de blobs**. Le mot de passe neo4j-legacykb et la clé API sont **réutilisés tels quels** (lus
depuis les secrets du Key Vault déplacé, jamais régénérés) — aucun client existant
(`mcp-legacykb`, intégrations) n'a besoin d'être reconfiguré après la migration.

### Prérequis

- Droits **Contributor** (ou équivalent) sur la subscription source ET la subscription cible
- Les deux subscriptions doivent appartenir au **même tenant Entra** (le move ARM ne traverse
  pas les tenants)
- Même région Azure pour le RG cible (un move ARM ne change jamais de région — voir la section
  "Limites et axes d'amélioration" de [ARCHITECTURE.md](ARCHITECTURE.md) pour le cas d'un
  changement de région, hors scope de ce script)
- L'upload Azure Files (certificat TLS, dump GraphML) se fait via clé de compte — pas de rôle
  data-plane supplémentaire nécessaire au-delà de `Contributor` (suffisant pour lire la clé)

### Utilisation

```powershell
.\migrate-rg.ps1 -SourceResourceGroup rg-nlmazure-prod -DestResourceGroup rg-nlmazure-prod-v2 `
    -DestSubscription "Nouvelle Subscription"

# Avec proxy d'entreprise, sans prompt de confirmation
.\migrate-rg.ps1 -SourceResourceGroup rg-sp4-d-vgi-azu-vgi-sandbox-txt `
    -DestResourceGroup rg-sp4-d-vgi-azu-vgi-sandbox2-txt -DestSubscription "Sandbox 2" `
    -ProjectName nlmavgi -SkipSSL -Force

# En excluant un residu d'un deploiement anterieur (nommage incorrect, laisse dans l'ancien RG)
.\migrate-rg.ps1 -SourceResourceGroup rg-source -DestResourceGroup rg-cible `
    -DestSubscription "Sandbox 2" -ProjectName nlmavgi -ExcludeResourceNames oai-nlmavgi-prd
```

> **`-ProjectName` doit correspondre exactement au préfixe des ressources réellement déployées**
> (vérifiable avec `az resource list -g <rg> -o table`), pas forcément à la valeur par défaut
> `nlmazure` — le script échoue tôt en Phase 1 avec un message explicite si aucun Container
> Registry nommé `acr<ProjectName><Environment>` n'est trouvé.

### Ce que fait le script (6 phases)

0. **Prérequis + authentification** — vérifie l'accès aux deux subscriptions et qu'elles
   partagent le même tenant Entra
1. **Pré-vol** — enregistre les Resource Providers manquants sur la subscription cible (en
   parallèle, y compris `Microsoft.Network`/`Microsoft.App` pour le VNet et les Container Apps
   Jobs), inventorie les ressources déplaçables, et valide le move à blanc via l'API ARM
   `validateMoveResources` (aucun effet de bord) avant de demander confirmation
2. **Déplacement groupé** — un seul appel `az resource move` couvrant Azure OpenAI, Document
   Intelligence, Azure AI Search, Key Vault, Container Registry, Storage principal et
   Application Insights (VNet/NSG/Container App/Job/ACI ne sont **pas** déplacés — recréés en
   Phase 3)
3. **Redéploiement de `infra/main.bicep`** (comme `deploy.ps1`, image Docker déjà à jour donc pas
   de rebuild) — crée VNet/NSG, Container App + UAMI + rôles IAM, ACI neo4j-legacykb dans le
   VNet, Job d'import ; réutilise le mot de passe neo4j et la clé API depuis les secrets Key
   Vault déjà déplacés. En parallèle (ne dépend pas du déploiement Bicep) : réassignation des
   rôles IAM du développeur courant, perdus par le move (ceux de l'UAMI sont recréés
   automatiquement par `infra/main.bicep` lui-même)
4. **Stack neo4j-legacykb** — génère et installe le certificat TLS auto-signé (SAN = IP privée
   de l'ACI, plus de FQDN public), redémarre l'ACI, déclenche l'import via
   `import-neo4j-legacykb.ps1` (réutilisé tel quel — upload du dump + Job d'import)
5. **Régénération du `.env` local + validation** — health checks `/health` et
   `/api/legacykb/health`
6. **Résumé** — affiche la commande de suppression de l'ancien Resource Group **sans jamais
   l'exécuter** — c'est une étape manuelle, une fois la migration validée :

   ```powershell
   az group delete --name <ancien-rg> --subscription <ancienne-subscription> --yes
   ```

> **Non testé en conditions réelles** : ce script a été réécrit pour la nouvelle architecture
> réseau (VNet, ACI privé, Job d'import) par revue de code, mais une migration cross-RG/
> cross-subscription réelle n'a pas pu être exécutée pour validation (action coûteuse et peu
> réversible). Faites un essai sur un environnement non critique avant de vous y fier en
> production.

### Limites connues

- Ne gère pas un changement de région (un move ARM ne change jamais de région — il faudrait un
  redéploiement complet + migration de données, hors scope)
- Le storage account dédié à neo4j-legacykb est détecté dynamiquement (lecture des volumes Azure
  Files réellement montés sur l'ACI existant) plutôt que deviné par convention de nommage — un
  environnement créé par une version antérieure des templates peut suivre une convention
  différente de celle actuelle de `infra/modules/neo4j-legacykb.bicep` (déjà observé en
  pratique : `stneo4jimportvgi` au lieu de `stneo4jkb<suffix>`)
- Les résidus de déploiements antérieurs (comptes dupliqués, typos d'environnement) ne sont pas
  filtrés automatiquement — le script avertit si plus de 2 comptes Cognitive Services sont
  trouvés, et `-ExcludeResourceNames` permet de les exclure explicitement
- Les rôles RBAC scopés sur une ressource ne survivent jamais à un move ARM (documenté par
  Microsoft) — c'est pourquoi le script les recrée systématiquement, mais si d'autres
  utilisateurs/services avaient des rôles spécifiques sur ces ressources, ils devront être
  réassignés manuellement après la migration
- L'historique Application Insights antérieur au move reste accessible uniquement via une
  requête directe (le portail du composant déplacé ne le montre plus, l'instrumentation key
  ne change pas mais l'identifiant de ressource change)

---

## 9. Troubleshooting

| Symptôme | Cause probable | Solution |
|---|---|---|
| `az acr build` : `CERTIFICATE_VERIFY_FAILED` | Proxy Zscaler — certifi ne connaît pas le cert racine | Utiliser `-SkipSSL` |
| `az extension add` échoue en SSL | Idem | `az config set core.verify_ssl=false` puis relancer |
| Déploiement Bicep : `quota exceeded` | Quota OpenAI insuffisant dans la région | Changer `-Location swedencentral` (ou `francecentral`) |
| Déploiement Bicep : `InvalidResourceLocation` | Ressources existantes dans une autre région | Utiliser la même `-Location` que l'infra existante |
| API retourne 401 sur `/api/*` | API_KEY manquante ou incorrecte | Vérifier `.env` → `API_KEY` ; ou passer `X-API-Key: <value>` |
| API retourne 401 sur ingestion locale | Propagation IAM pas encore effective | Attendre 5 min après deploy.ps1 et relancer |
| `ingest.py` : `DisableLocalAuthError` | `disableLocalAuth: true` actif, `az login` non détecté | Vérifier `az account show` renvoie votre compte |
| Container App ne démarre pas (CrashLoopBackOff) | Variables env manquantes ou image incorrecte | `az containerapp logs show -g <rg> -n ca-api-<suffix> --container api --tail 100 --follow false` (nécessite `$env:REQUESTS_CA_BUNDLE` si proxy Zscaler) |
| neo4j-legacykb inaccessible | ACI en cours de démarrage (2-3 min) | Attendre et retester `/api/legacykb/health` |
| Import GraphML ignoré (`dump introuvable`) | Fichier absent de `ingest/extract/` (pas `docs/extract/`, exclu de Git en entier — cf. § Phase 4c) | Placer `repartition_cleaned_export.graphml` dans `ingest/extract/` et relancer `import-neo4j-legacykb.ps1` |
| Import GraphML échoué (`APOC not found`) | Plugin APOC non installé dans le conteneur | Vérifier l'image neo4j (`neo4j:5.22-community` + `apoc`/`graph-data-science` dans `NEO4J_PLUGINS`) |
| Import JSONL échoué (`Instance Neo4j legacy-kb injoignable`), reproductible (pas un aléa réseau) | Lot de nœuds trop volumineux pour le timeout HTTP de 30s (`legacykb_client._execute`) — typiquement des `:Entity` avec de gros vecteurs d'embedding | Réduire `_JSONL_NODE_BATCH_SIZE` dans `api/scripts/import_legacykb.py`, rebuilder l'image (`az acr build`) et la repousser sur le Job (`az containerapp job update --image ...`) |
| Nœuds Community avec caractères corrompus | Double-encodage UTF-8/Latin-1 lors de l'import | Appliqué automatiquement par le Job d'import (`fix_utf8.cypher`) — aucune action manuelle requise |
| `Set-ExecutionPolicy` refusé | Politique d'entreprise | Lancer `python -m ...` directement sans activer le venv |
| Health check échoue après deploy | Container App encore en cold start | Attendre 2-3 min et tester manuellement `/health` |
| `.env` a `NEO4J_LEGACYKB_PASSWORD=***` | Masqué intentionnellement | Renseigner manuellement le vrai mot de passe dans `.env` (uniquement utile pour debug manuel — le Job d'import et `ca-api` le chargent eux-mêmes depuis Key Vault) |
| Déploiement Bicep : `RequestDisallowedByPolicy` sur le VNet/NSG | Policy de tags obligatoires sur l'abonnement (ex. *"Agentic Studio — Baseline Security"*) | Renseigner de vraies valeurs pour les tags requis (`Squad`, `Environment`, `CostCenter`, `ManagedBy`, `Project`) dans `infra/main.bicep` (variable `tags`) |
| Déploiement Bicep : `ManagedEnvironmentCannotAddVnetToExistingEnv` | Tentative d'ajouter l'intégration VNet à un `cae-<suffix>` déjà existant | Supprimer puis recréer `ca-api-<suffix>` et `cae-<suffix>` (voir § Réseau privé neo4j-legacykb) |
| Déploiement Bicep : `SubnetIdCannotChange` sur l'ACI | Tentative de changer le sous-réseau d'un ACI existant | Supprimer puis recréer l'ACI `aci-neo4j-legacykb-<suffix>`, puis relancer `import-neo4j-legacykb.ps1` (les données Neo4j sont perdues — pas de disque persistant) |
| PowerShell : `NativeCommandError` après `az containerapp job update`/`start` ou `az storage file download` malgré un succès (exit 0) | Ces commandes écrivent un spinner de progression sur stderr ; sous PowerShell, `$ErrorActionPreference="Stop"` transforme tout texte stderr d'un exécutable natif en erreur fatale | Ne pas rediriger stderr (`2>&1`) sur ces appels précis, utiliser `--no-progress` quand disponible, ou neutraliser temporairement `$ErrorActionPreference` (pattern déjà appliqué dans `import-neo4j-legacykb.ps1`) |
| `az acr build` plante la console avec `UnicodeEncodeError` en streamant ses logs | Caractères Unicode dans les logs + codepage Windows cp1252 | Utiliser `--no-logs` et poller via `az acr task list-runs` à la place (pattern déjà appliqué dans `deploy.ps1`) |
| `az container restart` échoue avec `RegistryErrorResponse` (`index.docker.io`) | Erreur transitoire du registry Docker Hub | Relancer la commande suffit généralement |
| Script `.ps1` réécrit intégralement : erreurs de parsing déroutantes (ex. "accolade fermante manquante" sur une ligne correcte) | Fichier sauvegardé en UTF-8 **sans BOM** — PowerShell 5.1 mal-interprète alors les caractères accentués | Toujours sauvegarder un `.ps1` réécrit intégralement en UTF-8 **avec BOM** |
