# Guide de déploiement — NotebookLM Azure
> **Environnement : Windows + PowerShell**
> Toutes les commandes sont à exécuter dans un terminal PowerShell ouvert à la racine du projet `notebooklm-azure/`.

---

## Avant de commencer

Ouvrez un terminal PowerShell **en tant qu'administrateur** et naviguez dans le dossier du projet :

```powershell
cd "c:\Users\v.gicquiau\OneDrive - ONEPOINT\Documents\AI Work\tutorial-agentic-retrieval\notebooklm-azure"
```

---

## Étape 1 — Vérifier les outils

Vérifiez que chaque outil est installé. Chaque commande doit afficher un numéro de version.

```powershell
az --version
python --version
docker --version
```

Si Azure CLI n'est pas installé : https://docs.microsoft.com/fr-fr/cli/azure/install-azure-cli-windows

```powershell
# Installer les extensions Azure CLI nécessaires
az extension add --name containerapp --upgrade
az bicep install
az bicep version
```

> **Proxy d'entreprise (Zscaler/Forcepoint) — si `az extension add` échoue avec une erreur SSL :**
>
> Le proxy intercepte le TLS et son certificat racine n'est pas reconnu par pip.
> Contournement : télécharger le `.whl` manuellement avec `curl.exe -k` **dans le dossier courant du projet** (chemin court, droits en écriture garantis), puis installer depuis le fichier local.
>
> ```powershell
> # 1. Désactiver la vérification SSL côté Azure CLI (pour les appels REST Azure uniquement)
> az config set core.verify_ssl=false
>
> # 2. Télécharger le wheel dans le dossier courant du projet (PAS dans $env:TEMP ni à la racine C:\)
> #    curl.exe -k = ignorer les erreurs SSL ; -L = suivre les redirections
> curl.exe -k -L `
>   "https://azcliprod.blob.core.windows.net/cli-extensions/containerapp-1.2.0b4-py2.py3-none-any.whl" `
>   -o "containerapp-1.2.0b4-py2.py3-none-any.whl"
>
> # 3. Installer depuis le fichier local
> az extension add --source "containerapp-1.2.0b4-py2.py3-none-any.whl" --yes
>
> # 4. Vérifier
> az extension show --name containerapp --query version -o tsv
> ```
>
> **Pourquoi pas `$env:TEMP` ni `C:\` ?**
> - `$env:TEMP` se résout en chemin court 8.3 (ex. `V5C98~1.GIC`) que l'Azure CLI ne sait pas parser.
> - La racine `C:\` nécessite des droits administrateur en écriture.
> - Le dossier courant du projet (`notebooklm-azure\`) n'a aucun de ces problèmes.
>
> **Note :** `-SkipCertificateCheck` sur `Invoke-WebRequest` n'existe que dans PowerShell 7+. Sur Windows PowerShell 5.1 (celui installé par défaut), utilisez `curl.exe -k` à la place.

**Checkpoint :** Les trois commandes affichent une version sans erreur.

---

## Étape 2 — Se connecter à Azure

```powershell
az login
```

Un navigateur s'ouvre. Connectez-vous avec votre compte Azure. Revenez au terminal une fois connecté.

```powershell
# Vérifier la subscription active
az account show --query "{nom:name, id:id, tenant:tenantId}" -o table
```

Si vous avez plusieurs subscriptions, sélectionnez la bonne :

```powershell
az account list -o table
az account set --subscription "<ID_DE_VOTRE_SUBSCRIPTION>"
```

**Checkpoint :** `az account show` affiche la subscription sur laquelle vous voulez déployer.

---

## Étape 3 — Définir les variables de session

Copiez-collez ce bloc en entier dans PowerShell. Les variables durent le temps de la session.

```powershell
$env:PROJECT    = "notebooklm"
$env:ENV        = "prod"
$env:LOCATION   = "francecentral"
$env:RG         = "rg-notebooklm-prod"
$env:DEPLOYER_OID = (az ad signed-in-user show --query id -o tsv)

Write-Host "RG        : $($env:RG)"
Write-Host "Location  : $($env:LOCATION)"
Write-Host "Deployer  : $($env:DEPLOYER_OID)"
```

**Checkpoint :** Les trois lignes affichent des valeurs non vides.

> **Note région :** `francecentral` supporte gpt-4o et text-embedding-3-large.
> Si vous obtenez une erreur de quota OpenAI, remplacez par `swedencentral`.

---

## Étape 4 — Créer le Resource Group

```powershell
az group create `
  --name $env:RG `
  --location $env:LOCATION `
  --tags project=$env:PROJECT environment=$env:ENV managed-by=bicep
```

**Checkpoint :** La commande retourne `"provisioningState": "Succeeded"`.

---

## Étape 5 — Déployer l'infrastructure Bicep

### 5.1 — Injecter votre Object ID dans les paramètres

```powershell
# Lire le fichier, remplacer le placeholder, ré-écrire
(Get-Content infra\main.parameters.json) `
  -replace '<REMPLACER_PAR_VOTRE_OBJECT_ID_AAD>', $env:DEPLOYER_OID `
  | Set-Content infra\main.parameters.json

# Vérifier que le remplacement a bien eu lieu
Select-String -Path infra\main.parameters.json -Pattern "REMPLACER"
# → doit retourner vide (aucun résultat)
```

### 5.2 — Valider le template sans déployer (optionnel mais recommandé)

```powershell
az deployment group what-if `
  --resource-group $env:RG `
  --template-file infra\main.bicep `
  --parameters infra\main.parameters.json `
  --parameters deployerObjectId=$env:DEPLOYER_OID
```

### 5.3 — Déployer (environ 10-15 minutes)

```powershell
az deployment group create `
  --resource-group $env:RG `
  --template-file infra\main.bicep `
  --parameters infra\main.parameters.json `
  --parameters deployerObjectId=$env:DEPLOYER_OID `
  --name "deploy-init" `
  --output table
```

> **Patience :** Le déploiement des modèles Azure OpenAI est lent (~8-12 min).
> Le terminal affiche la progression. Ne pas interrompre.

**Checkpoint :**

```powershell
az resource list --resource-group $env:RG --query "[].{Nom:name, Type:type}" -o table
```

Vous devez voir 9+ ressources : OpenAI, Search, Storage, Document Intelligence, Key Vault, Container Registry, Container App, Container App Environment, App Insights.

---

## Étape 6 — Récupérer les outputs et remplir `.env`

### 6.1 — Extraire les valeurs de sortie du déploiement

```powershell
$deploy = "deploy-init"

$openaiEp  = az deployment group show -g $env:RG -n $deploy --query properties.outputs.openAIEndpoint.value   -o tsv
$searchEp  = az deployment group show -g $env:RG -n $deploy --query properties.outputs.searchEndpoint.value   -o tsv
$storageAcc= az deployment group show -g $env:RG -n $deploy --query properties.outputs.storageAccountName.value -o tsv
$docintEp  = az deployment group show -g $env:RG -n $deploy --query properties.outputs.docIntEndpoint.value    -o tsv
$acrServer = az deployment group show -g $env:RG -n $deploy --query properties.outputs.registryLoginServer.value -o tsv
$kvName    = az deployment group show -g $env:RG -n $deploy --query properties.outputs.keyVaultName.value      -o tsv

Write-Host "OpenAI   : $openaiEp"
Write-Host "Search   : $searchEp"
Write-Host "Storage  : $storageAcc"
Write-Host "DocInt   : $docintEp"
Write-Host "ACR      : $acrServer"
Write-Host "KeyVault : $kvName"
```

**Checkpoint :** Toutes les variables affichent des URLs Azure réelles (pas vides).

### 6.2 — Créer le fichier `.env`

```powershell
Copy-Item .env.example .env

# Remplir les variables avec les valeurs réelles
(Get-Content .env) `
  -replace 'AZURE_OPENAI_ENDPOINT=.*',        "AZURE_OPENAI_ENDPOINT=$openaiEp" `
  -replace 'AZURE_SEARCH_ENDPOINT=.*',        "AZURE_SEARCH_ENDPOINT=$searchEp" `
  -replace 'AZURE_DOCINT_ENDPOINT=.*',        "AZURE_DOCINT_ENDPOINT=$docintEp" `
  -replace 'AZURE_STORAGE_ACCOUNT_NAME=.*',   "AZURE_STORAGE_ACCOUNT_NAME=$storageAcc" `
  -replace 'AZURE_KEYVAULT_URI=.*',           "AZURE_KEYVAULT_URI=https://$kvName.vault.azure.net/" `
  | Set-Content .env

# Vérifier le résultat
Get-Content .env | Where-Object { $_ -notmatch "^#" -and $_ -ne "" }
```

**Checkpoint :** Toutes les lignes `AZURE_*` contiennent des URLs réelles, pas de placeholder.

---

## Étape 7 — Assigner les rôles IAM pour l'ingestion locale

Ces rôles permettent à votre compte (`az login`) d'appeler les APIs Azure directement depuis votre machine.

```powershell
$subscriptionId = az account show --query id -o tsv
$scope = "/subscriptions/$subscriptionId/resourceGroups/$($env:RG)"

az role assignment create --assignee $env:DEPLOYER_OID --role "Cognitive Services OpenAI User" --scope $scope
az role assignment create --assignee $env:DEPLOYER_OID --role "Search Index Data Contributor"  --scope $scope
az role assignment create --assignee $env:DEPLOYER_OID --role "Cognitive Services User"         --scope $scope
az role assignment create --assignee $env:DEPLOYER_OID --role "Storage Blob Data Contributor"  --scope $scope
```

> **Important :** Attendez **3-5 minutes** après ces commandes avant de lancer l'ingestion.
> Les rôles IAM Azure ont un délai de propagation.

**Checkpoint :**

```powershell
az role assignment list --assignee $env:DEPLOYER_OID --scope $scope --query "[].roleDefinitionName" -o tsv
```

Vous devez voir les 4 rôles listés.

---

## Étape 8 — Préparer et lancer l'ingestion

### 8.1 — Copier vos documents

Copiez au moins un fichier de test (PDF, Markdown ou DOCX) dans le dossier `documents\` :

```powershell
# Exemple : copier un PDF
Copy-Item "C:\chemin\vers\votre\document.pdf" documents\

# Vérifier
Get-ChildItem documents\
```

### 8.2 — Créer l'environnement Python et installer les dépendances

```powershell
cd ingest
python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

> Si PowerShell refuse d'exécuter le script d'activation (politique d'exécution) :
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```
> Puis relancez `.\.venv\Scripts\Activate.ps1`.

> **Proxy d'entreprise (Zscaler) — si l'ingestion échoue avec `SSL: CERTIFICATE_VERIFY_FAILED` :**
>
> Le SDK Azure utilise `requests` → `certifi` pour valider les certificats TLS.
> Zscaler substitue son propre certificat, absent du bundle `certifi` par défaut.
> Solution : exporter le certificat racine Zscaler depuis le store Windows et l'ajouter au bundle `certifi` du venv.
>
> ```powershell
> # Exporter le cert Zscaler depuis le store Windows
> $cert = Get-ChildItem Cert:\LocalMachine\Root | Where-Object { $_.Subject -match "Zscaler" } | Select-Object -First 1
> $certBytes = $cert.Export([System.Security.Cryptography.X509Certificates.X509ContentType]::Cert)
> $pem = "-----BEGIN CERTIFICATE-----`n" + [Convert]::ToBase64String($certBytes, "InsertLineBreaks") + "`n-----END CERTIFICATE-----`n"
>
> # Ajouter au bundle certifi du venv
> $certifiBundle = python -c "import certifi; print(certifi.where())"
> Add-Content -Path $certifiBundle -Value $pem -Encoding ascii
> Write-Host "OK: cert Zscaler ajouté à $certifiBundle"
> ```
>
> **Important :** Cette modification est locale au venv — si vous recréez le venv, vous devrez la rejouer.
> Relancez ensuite `python ingest.py --docs-dir ..\documents`.

### 8.3 — Copier le `.env` et faire un dry-run

```powershell
Copy-Item ..\.env .env

# Dry-run : liste les fichiers sans rien indexer
python ingest.py --docs-dir ..\documents --dry-run
```

**Checkpoint :** La commande affiche la liste de vos fichiers sans erreur.

### 8.4 — Lancer l'ingestion réelle

```powershell
python ingest.py --docs-dir ..\documents
```

Vous devriez voir des lignes du type :
```
Indexé : mon-document.pdf (47 chunks)
Ingestion terminée.
```

**Checkpoint :**

```powershell
$token = az account get-access-token --resource https://search.azure.com --query accessToken -o tsv
$headers = @{ Authorization = "Bearer $token" }
Invoke-RestMethod -Uri "${searchEp}/indexes/notebooklm-chunks/docs/`$count?api-version=2024-05-01-preview" -Headers $headers
# → retourne un nombre > 0
```

### 8.5 — Revenir à la racine du projet

```powershell
deactivate
cd ..
```

---

## Gestion continue des documents

> Les commandes ci-dessous s'exécutent depuis le dossier `ingest\` avec le venv activé.
> ```powershell
> cd ingest
> .\.venv\Scripts\Activate.ps1
> Copy-Item ..\.env .env   # si vous avez mis à jour le .env depuis
> ```

### Ajouter de nouveaux documents

Copiez les fichiers dans `documents\` (ou dans un sous-dossier) et relancez l'ingestion.
Le script détecte les fichiers déjà indexés via leur hash SHA256 et les **ignore automatiquement** — seuls les nouveaux sont traités.

```powershell
Copy-Item "C:\chemin\nouveau-document.pdf" ..\documents\

python ingest.py --docs-dir ..\documents
# → "Skipped (déjà indexé) : ancien.pdf"
# → "Indexé : nouveau-document.pdf (32 chunks)"
```

### Mettre à jour un document existant (version modifiée)

Si le contenu d'un fichier change, son hash change → les anciens chunks **restent dans l'index** (leurs IDs sont basés sur l'ancien hash). Il faut supprimer les anciens chunks manuellement avant de re-indexer.

```powershell
# 1. Identifier le hash de l'ancien fichier dans l'index
$token   = az account get-access-token --resource https://search.azure.com --query accessToken -o tsv
$headers = @{ Authorization = "Bearer $token"; "Content-Type" = "application/json" }

# Chercher tous les chunks de ce fichier
$filter  = [uri]::EscapeDataString("source_file eq 'mon-document.pdf'")
$uri     = "${env:AZURE_SEARCH_ENDPOINT}/indexes/notebooklm-chunks/docs?`$filter=$filter&`$select=id&api-version=2024-05-01-preview"
$result  = Invoke-RestMethod -Uri $uri -Headers $headers
$ids     = $result.value | ForEach-Object { @{ id = $_.id } }

# 2. Supprimer ces chunks
$body = @{ value = ($ids | ForEach-Object { $_ + @{ "@search.action" = "delete" } }) } | ConvertTo-Json -Depth 5
Invoke-RestMethod -Method POST `
  -Uri "${env:AZURE_SEARCH_ENDPOINT}/indexes/notebooklm-chunks/docs/index?api-version=2024-05-01-preview" `
  -Headers $headers -Body $body

# 3. Re-copier la nouvelle version et relancer
Copy-Item "C:\chemin\mon-document-v2.pdf" "..\documents\mon-document.pdf"
python ingest.py --docs-dir ..\documents
```

### Supprimer un document de l'index

Même procédure que ci-dessus (étapes 1 et 2), sans re-indexer ensuite. Supprimez aussi le fichier du dossier `documents\`.

### Tout re-indexer depuis zéro

Utile si vous avez modifié les paramètres de chunking ou changé le modèle d'embedding.

```powershell
# Supprimer et recréer l'index (ATTENTION : supprime tous les chunks)
python -c "
from azure.identity import DefaultAzureCredential
from azure.search.documents.indexes import SearchIndexClient
import os
from dotenv import load_dotenv
load_dotenv()
client = SearchIndexClient(os.environ['AZURE_SEARCH_ENDPOINT'], DefaultAzureCredential())
client.delete_index('notebooklm-chunks')
print('Index supprimé.')
"

# Re-indexer tous les documents
python ingest.py --docs-dir ..\documents --force-reindex
```

> **`--force-reindex`** ignore la déduplication par hash et retraite tous les fichiers.
> À utiliser aussi si un document a été partiellement indexé suite à une erreur.

---

## Étape 9 — Tester l'API en local

### 9.1 — Installer les dépendances API

```powershell
cd api
python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
Copy-Item ..\.env .env
```

> **Dépendances supplémentaires requises** — non incluses dans `requirements.txt` de base car utilisées uniquement pour le endpoint d'ingestion via UI :
>
> ```powershell
> pip install python-multipart tiktoken azure-ai-documentintelligence python-docx
> ```
>
> - `python-multipart` — **obligatoire** : FastAPI en a besoin au démarrage pour tout endpoint `UploadFile`. Sans lui, l'API refuse de démarrer.
> - `tiktoken`, `azure-ai-documentintelligence`, `python-docx` — utilisés par la task d'ingestion en arrière-plan. L'API démarre sans eux, mais retourne une erreur lors d'un upload.

> **Variable d'environnement supplémentaire** — à ajouter dans `api\.env` (ou `.env` racine) si elle n'y est pas :
>
> ```
> AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-large
> ```
>
> Cette variable est lue par l'`Embedder` lors de l'ingestion via UI (le router `/api/ingest`). Elle est déjà requise par le `Retriever` — vérifier qu'elle est bien présente.

### 9.2 — Lancer l'API

Ouvrez un **second terminal PowerShell** et naviguez à la **racine du projet** (pas dans `api\`) :

```powershell
cd "c:\Users\v.gicquiau\OneDrive - ONEPOINT\Documents\AI Work\tutorial-agentic-retrieval\notebooklm-azure"
api\.venv\Scripts\uvicorn api.main:app --reload --port 8000
```

> **Pourquoi depuis la racine ?** `main.py` utilise des imports absolus (`from api.routers.chat import ...`).
> Python doit voir `api` comme un package dans le répertoire courant — ce qui n'est possible que depuis `notebooklm-azure\`.
> De plus, `load_dotenv()` cherche `.env` dans le répertoire courant, qui se trouve à la racine.

> Le terminal doit afficher `Application startup complete.`

### 9.3 — Tester dans le premier terminal

```powershell
# Health check
Invoke-RestMethod -Uri "http://localhost:8000/health"

# Test chat — vérifier que sources contiennent bien le champ content
$body = '{"message": "Résume les règles métier principales", "top_k": 5}'
$bytes = [System.Text.Encoding]::UTF8.GetBytes($body)
Invoke-RestMethod -Uri "http://localhost:8000/api/chat" `
  -Method POST `
  -ContentType "application/json; charset=utf-8" `
  -Body $bytes | ConvertTo-Json -Depth 5
```

**Checkpoint :** La réponse JSON contient `answer` (non vide), `sources` (liste non vide dont chaque item a un champ `content`) et `tokens_used > 0`.

```powershell
# Test upload d'un document via l'API (remplacer le chemin par un vrai fichier)
$filePath = "C:\chemin\vers\votre\document.pdf"
$form = @{ file = Get-Item $filePath }
$job = Invoke-RestMethod -Uri "http://localhost:8000/api/ingest" `
  -Method POST `
  -Form $form
Write-Host "Job ID : $($job.job_id) — Statut : $($job.status)"

# Vérifier l'avancement (relancer plusieurs fois ou attendre quelques secondes)
Invoke-RestMethod -Uri "http://localhost:8000/api/ingest/$($job.job_id)" | ConvertTo-Json
```

**Checkpoint :** Le premier appel retourne `status: "pending"` avec un `job_id`. Le second retourne `status: "running"` puis `status: "done"` avec `chunks > 0`.

### 9.4 — Tester l'interface graphique

Ouvrez votre navigateur sur : **http://localhost:8000** (Ctrl+Shift+R pour vider le cache si nécessaire)

Vérifiez les fonctionnalités dans l'ordre :

**Chat et citations :**
- [ ] Poser une question → réponse avec badges `[N]` bleus dans le texte
- [ ] Cliquer sur un badge `[N]` → modale qui affiche le texte exact du chunk source
- [ ] Cliquer sur une fiche "Références" → même modale
- [ ] Seules les sources réellement citées apparaissent dans "Références"

**Notes :**
- [ ] Cliquer "Enregistrer" sur une réponse → note apparaît dans le rail droit
- [ ] Recharger la page (F5) → note toujours présente (localStorage)
- [ ] Survoler une note → bouton × visible → clic supprime la note
- [ ] Cliquer sur une note → modale plein écran avec le texte complet
- [ ] Dans la modale : "Injecter dans le contexte" → bandeau bleu apparaît au-dessus de la saisie
- [ ] Poser une question avec une note injectée → la réponse s'appuie sur le contenu de la note
- [ ] Cliquer "Nouvelle note" → zone de saisie manuelle dans le rail

**Upload de document :**
- [ ] Cliquer "Ajouter un document" dans le bandeau → file picker s'ouvre
- [ ] Sélectionner un PDF/DOCX/MD → toast apparaît en bas à droite avec progression
- [ ] Toast final : `✓ N chunks indexés avec succès` (disparaît après 6s)
- [ ] En cas d'erreur : toast rouge avec le message, bouton × pour fermer

**Autres :**
- [ ] Bouton "↺ Nouvelle conversation" → chat vidé, nouvelle session
- [ ] Sélecteur Rapide/Standard/Approfondi → mode affiché sur chaque message utilisateur

---

## Étape 10 — Déployer en production (Docker + App Service)

> **Note :** Le déploiement utilise **Azure App Service for Containers** (`Microsoft.Web/sites`)
> au lieu de Container Apps — même Docker, même Managed Identity, même résultat.

### 10.1 — S'authentifier sur le Container Registry

```powershell
cd ..   # Revenir à la racine du projet si besoin
$acrName = $acrServer.Split('.')[0]
az acr login --name $acrName
```

### 10.2 — Builder l'image Docker

> Builder depuis la **racine du projet** (pas depuis `api\`).

```powershell
docker build -f api\Dockerfile -t "${acrServer}/notebooklm-api:latest" .
```

La construction prend 2-5 minutes. Vous devez voir `Successfully built ...` à la fin.

### 10.3 — Tester l'image en local (optionnel)

```powershell
docker run --env-file .env -p 8001:8000 "${acrServer}/notebooklm-api:latest"
```

Dans un autre terminal :

```powershell
Invoke-RestMethod -Uri "http://localhost:8001/health"
```

Arrêtez le container avec Ctrl+C.

### 10.4 — Pousser l'image sur ACR

```powershell
docker push "${acrServer}/notebooklm-api:latest"
```

### 10.5 — Mettre à jour l'App Service

```powershell
$appName = az webapp list -g $env:RG --query "[?contains(name,'app-api')].name" -o tsv

az webapp config container set `
  --name $appName `
  --resource-group $env:RG `
  --docker-custom-image-name "${acrServer}/notebooklm-api:latest"

# Redémarrer pour forcer le pull de la nouvelle image
az webapp restart --name $appName --resource-group $env:RG
```

**Checkpoint :**

```powershell
az webapp show -g $env:RG -n $appName --query state -o tsv
# → doit retourner "Running"
```

---

## Étape 11 — Valider la production

### 11.1 — Récupérer l'URL publique

```powershell
$appName = az webapp list -g $env:RG --query "[?contains(name,'app-api')].name" -o tsv
$apiUrl  = az webapp show -g $env:RG -n $appName --query defaultHostName -o tsv

Write-Host "Interface disponible sur : https://$apiUrl"
```

### 11.2 — Health check production

```powershell
Invoke-RestMethod -Uri "https://$apiUrl/health"
```

### 11.3 — Test chat en production

```powershell
$body = '{"message": "Test connexion production", "top_k": 3}'
Invoke-RestMethod -Uri "https://$apiUrl/api/chat" `
  -Method POST `
  -ContentType "application/json" `
  -Body $body | ConvertTo-Json -Depth 5
```

### 11.4 — Ouvrir l'interface dans le navigateur

```powershell
Start-Process "https://$apiUrl"
```

**Checkpoint final :** L'interface s'ouvre, vous posez une question, vous recevez une réponse avec sources.

---

## Résumé des variables importantes

Si vous fermez et rouvrez PowerShell, re-déclarez ces variables avant de continuer :

```powershell
$env:RG           = "rg-notebooklm-prod"
$env:DEPLOYER_OID = (az ad signed-in-user show --query id -o tsv)
$deploy           = "deploy-init"

$openaiEp  = az deployment group show -g $env:RG -n $deploy --query properties.outputs.openAIEndpoint.value    -o tsv
$searchEp  = az deployment group show -g $env:RG -n $deploy --query properties.outputs.searchEndpoint.value    -o tsv
$storageAcc= az deployment group show -g $env:RG -n $deploy --query properties.outputs.storageAccountName.value -o tsv
$docintEp  = az deployment group show -g $env:RG -n $deploy --query properties.outputs.docIntEndpoint.value     -o tsv
$acrServer = az deployment group show -g $env:RG -n $deploy --query properties.outputs.registryLoginServer.value -o tsv
$kvName    = az deployment group show -g $env:RG -n $deploy --query properties.outputs.keyVaultName.value       -o tsv
$appName   = az webapp list -g $env:RG --query "[?contains(name,'app-api')].name" -o tsv
$apiUrl    = az webapp show -g $env:RG -n $appName --query defaultHostName -o tsv
```

---

## En cas de problème

| Symptôme | Cause probable | Solution |
|---|---|---|
| `az deployment create` échoue avec "quota exceeded" | Quota OpenAI insuffisant en `francecentral` | Changer `location` en `swedencentral` dans `infra\main.parameters.json` et redéployer |
| Erreur 401 lors de l'ingestion | Propagation IAM pas encore effective | Attendre 5 min et relancer `python ingest.py` |
| `ingest.py` échoue avec "DisableLocalAuthError" | `disableLocalAuth: true` est actif, `az login` non détecté | Vérifier `az account show` renvoie bien votre compte |
| Docker build échoue sur le COPY | Builder depuis la racine, pas depuis `api\` | Revenir à la racine : `cd ..` puis relancer le build |
| App Service ne démarre pas | Variables env manquantes ou image KO | `az webapp log tail -g $env:RG -n $appName` pour voir les logs en direct |
| `Set-ExecutionPolicy` refusé | Politique d'entreprise restrictive | Utiliser `python -m pip` et lancer Python directement sans activer le venv |
