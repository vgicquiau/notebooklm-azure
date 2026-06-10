# Sprint 0 — Checklist d'exécution
# Cible : PC = IDE uniquement, tout sur Azure

**Objectif** : Infra 100% Azure opérationnelle (2-3 jours solo)
**Principe** : Aucun serveur local. Neo4j sur ACI. ArchiMind/OpenAI/Search réutilisés depuis la prod notebooklm-azure (pas de redéploiement).

---

## Avant de commencer

```powershell
# Vérifier az CLI installé et connecté
az --version           # doit afficher 2.x
az account show        # doit afficher ton subscription

# Si pas connecté :
az login
az account set --subscription "YOUR_SUBSCRIPTION_ID"
```

---

## Phase 1 : Provisioning Azure (1-2 h)

### 1.1 Variables — déjà configurées pour le sandbox existant

Le compte `v.gicquiau` n'a **aucun rôle au niveau abonnement** : impossible de
créer un nouveau Resource Group ni un nouveau compte Azure OpenAI/Search.
Les variables en haut de `SPRINT0_setup-azure.ps1` et `SPRINT0_fixup-azure.ps1`
sont donc déjà renseignées pour le RG sandbox existant — rien à adapter :
```powershell
$subscriptionId = "07875763-82ff-4808-a7da-e3d0dccc86fc"
$resourceGroup  = "rg-sp4-d-vgi-azu-vgi-sandbox-txt"   # RG existant (imposé)
$location       = "francecentral"                      # région du RG existant
$sqlPassword    = "ChangeMe@SQL2026!"
$neo4jPassword  = "ChangeMe@Neo4j2026"
```

Pour limiter coûts et complexité, on **réutilise** les ressources IA de
production de notebooklm-azure plutôt que d'en provisionner de nouvelles :
- `oai-nlmazure-prod` (Azure OpenAI — `disableLocalAuth=true`, donc auth
  exclusivement via Managed Identity + rôle RBAC "Cognitive Services OpenAI User")
- `srch-nlmazure-prod` (Azure AI Search)
- `app-api-nlmazure-prod` (ArchiMind — déjà déployé, pas de redéploiement)

### 1.2 Lancer les deux scripts (provisioning puis fixup)
```powershell
.\SPRINT0_setup-azure.ps1
.\SPRINT0_fixup-azure.ps1
```

Durée : ~15-20 min à eux deux. **Pourquoi deux scripts ?** Le premier passage
a buté sur 4 bugs d'environnement (flags `az` dépréciés, identités managées
trop fraîches pour la propagation AAD, parsing `cmd.exe` des valeurs
`@Microsoft.KeyVault(...)`) ; le fixup corrige uniquement ces manques sans
retraiter les ressources déjà créées avec succès. Détails des bugs et
correctifs documentés en en-tête de `SPRINT0_fixup-azure.ps1`. Les deux
scripts sont idempotents (sûrs à relancer).

À eux deux ils créent/configurent :
1. Storage Account + Application Insights
2. SQL Server + Database
3. **4 Function Apps avec identité managée système** (ADG-M / 7RQA / ADM-M / MWP)
4. Static Web App (frontend)
5. Key Vault **en mode RBAC** (pas access policies) + 7 secrets (connection
   strings, endpoints, mots de passe)
6. **Neo4j sur ACI** (Bolt public, GDS auto-installé au démarrage, ~2-3 min)
7. Rôle RBAC **"Cognitive Services OpenAI User"** sur `oai-nlmazure-prod`
   pour les 4 identités managées
8. Rôle RBAC **"Key Vault Secrets User"** sur le Key Vault pour les 4 identités
9. App settings de chaque Function App référençant les secrets via
   `@Microsoft.KeyVault(SecretUri=...)`

✅ À la fin, le script de fixup affiche un résumé de vérification (Key Vault,
état Neo4j ACI, nombre de rôles RBAC assignés, échantillon d'app settings)
et la liste des étapes manuelles restantes (Phase 2).

---

## Phase 2 : Configuration manuelle (30 min)

### 2.1 Créer les containers blob (action manuelle obligatoire)

Le proxy d'entreprise (Zscaler) intercepte le trafic vers
`*.blob.core.windows.net` avec un certificat auto-signé que le bundle
`certifi` de Python rejette : `az storage container create` échoue avec
`[SSL: CERTIFICATE_VERIFY_FAILED]` **depuis ce PC uniquement** (les Function
Apps déployées sur Azure ne passent pas par ce proxy et ne sont pas
concernées). Créer les containers via le Portail :

Portail Azure → Storage Account `modernagentstgdev` → Containers → + Container
- `retrodocs` (niveau d'accès : Privé)
- `exports` (niveau d'accès : Privé)

### 2.2 Initialiser la base SQL
Azure Portal → SQL databases → `modernagent_db` → Query editor → Login (`sqladmin` / `ChangeMe@SQL2026!`)

Copier-coller le contenu de `SPRINT0_setup-sql.sql` → Exécuter

✅ Attendu : "Commands completed successfully"

### 2.3 Vérifier l'accès aux ressources IA réutilisées

Pas de redéploiement ici : ArchiMind, Azure OpenAI et Azure AI Search sont les
instances de **production existantes** (`app-api-nlmazure-prod`,
`oai-nlmazure-prod`, `srch-nlmazure-prod`), partagées avec notebooklm-azure.
```powershell
Invoke-WebRequest "https://app-api-nlmazure-prod.azurewebsites.net" -UseBasicParsing | Select-Object StatusCode
```
✅ Attendu : `StatusCode 200`. Pour tester du code Python en local contre
`oai-nlmazure-prod` (compte `disableLocalAuth=true`, pas de clé API possible),
il suffit d'avoir fait `az login` avec un compte disposant du rôle RBAC
"Cognitive Services OpenAI User" sur ce compte — déjà le cas pour `v.gicquiau`.

---

## Phase 3 : Neo4j — initialisation du graphe (15 min)

### 3.1 Attendre que Neo4j ACI soit prêt (GDS se télécharge au démarrage)
```powershell
# Vérifier l'état du container
az container show --resource-group rg-sp4-d-vgi-azu-vgi-sandbox-txt --name neo4j-dev --query instanceView.state

# Attendre : "Running" (peut prendre 2-3 min)
```

### 3.2 Ouvrir Neo4j Browser (cloud)
```
http://neo4j-modernagent-dev.francecentral.azurecontainer.io:7474
```
Login : `neo4j` / `ChangeMe@Neo4j2026` (ton mot de passe configuré)

### 3.3 Vérifier que GDS est installé
```cypher
SHOW PROCEDURES YIELD name WHERE name CONTAINS 'gds.louvain' RETURN name;
```
✅ Attendu : au moins une ligne `gds.louvain.stream`

### 3.4 Initialiser le graphe (fixture FL + CardDemo)
Copier-coller `SPRINT0_setup-neo4j.cypher` dans Neo4j Browser → Exécuter

✅ Attendu (dernières lignes) :
```
total_nodes: 23
total_relationships: 31
```

---

## Phase 4 : Déployer les Azure Functions (30 min)

### 4.1 Créer la structure Function App locale

```powershell
# Installer Azure Functions Core Tools si pas installé
npm install -g azure-functions-core-tools@4 --unsafe-perm true

# Créer la structure
# NOTE : le code fourni (SPRINT0_fn-adgm-*_function_app.py) est écrit au format V1
# (def main(...) + function.json séparé avec scriptFile), pas V2 (function_app.py
# unique avec décorateurs @app.route). Modèle V2 inadapté ici -- rester en V1.
# Sur func Core Tools v4.12.0, la syntaxe est --worker-runtime / valeur "v1" en minuscules
# (pas --python --model V2, qui est rejeté par cette version de l'outil).
func init modernagent-backend --worker-runtime python --model v1
cd modernagent-backend

# Copier le code Python ET les bindings (function.json -- requis en V1)
# SPRINT0_fn-adgm-ingest_function_app.py → fn-adgm-ingest/function_app.py
# SPRINT0_function-ingest.json           → fn-adgm-ingest/function.json
# SPRINT0_fn-adgm-graph_function_app.py  → fn-adgm-graph/function_app.py
# SPRINT0_function-graph.json            → fn-adgm-graph/function.json

# Copier requirements
# SPRINT0_requirements.txt → requirements.txt

# (Optionnel, pour tests locaux avec "func start") :
# SPRINT0_local.settings.json.template → local.settings.json (gitignored)
```

### 4.2 Déployer ADG-M (la Function Gate critique)
```powershell
func azure functionapp publish modernagent-adgm-dev
```

### 4.3 Tester les endpoints (curl depuis PC ou browser)
```powershell
# Remplacer par l'URL de ta Function App
$baseUrl = "https://modernagent-adgm-dev.azurewebsites.net/api"

# NOTE : utiliser Invoke-RestMethod, pas Invoke-WebRequest -- sous PowerShell 5.1,
# Invoke-WebRequest sans -UseBasicParsing tente d'utiliser le moteur DOM d'Internet
# Explorer et peut bloquer indéfiniment en contexte restreint/headless. De plus
# "Invoke-WebRequest ... | ConvertFrom-Json" ne fonctionne pas tel quel (il faudrait
# "(Invoke-WebRequest ...).Content | ConvertFrom-Json") -- Invoke-RestMethod retourne
# directement les objets désérialisés.

Invoke-RestMethod "$baseUrl/graph/health"
# → { "status": "healthy", "neo4j": "connected", ... }

Invoke-RestMethod "$baseUrl/graph/nodes"
# → { "nodes": [...23 composants...], "count": 23 }

Invoke-RestMethod "$baseUrl/graph/arcs"
# → { "arcs": [...31 relations...], "count": 31 }
```

✅ **Vérifié en Sprint 0** (2026-06-07) : les 3 endpoints répondent avec les chiffres
attendus (`count: 23` / `count: 31`) sur le premier essai après déploiement --
voir Gate Sprint 1 ci-dessous.

✅ Si 200 OK sur les 3 → **Gate critique Sprint 1 débloquée**

---

## Phase 5 : Frontend React (optionnel Sprint 0 — 30 min)

Le frontend peut être développé localement avec hot-reload, mais se connecte aux Functions en cloud.

```powershell
npm create vite@latest modernagent-frontend -- --template react-ts
cd modernagent-frontend
npm install
# NOTE : @msal/browser et @msal/react n'existent pas sur npm (404) -- les paquets
# MSAL sont scopés sous @azure/. Le skeleton fourni n'utilise pas encore MSAL
# (useAuth.ts mentionné en commentaire mais pas implémenté) ; installés ici en
# anticipation de l'auth à venir.
npm install cytoscape @types/cytoscape @azure/msal-browser @azure/msal-react
```

Copier `SPRINT0_frontend-skeleton.tsx` → `src/components/GraphView.tsx`, créer
`src/components/GraphView.css` (référencé par le skeleton mais non fourni --
classes utilisées : `.graph-view`, `.graph-header`, `.status`, `.graph-container`,
`.node-detail`, `.detail-field`, `.criticality.*`, `.actions`, `.btn-primary/secondary`),
et remplacer `src/App.tsx` par défaut (`function App() { return <GraphView /> }`).

⚠️ Le skeleton contient 2 erreurs TypeScript qui bloquent `tsc`/`npm run build`
(Vite dev les laisse passer car esbuild ne type-check pas, mais elles cassent le
build prod) :
- `style.stroke` sur le sélecteur `edge` -- propriété invalide pour Cytoscape
  (`line-color` est déjà présente juste en dessous ; supprimer `stroke`)
- `directed: true` dans les options du layout `cose` -- option inexistante pour
  ce layout (propre à `breadthfirst`/`dagre` ; supprimer la ligne)

Dans `vite.config.ts`, ajouter un proxy pour éviter CORS :
```typescript
server: {
  proxy: {
    '/api': {
      target: 'https://modernagent-adgm-dev.azurewebsites.net',
      changeOrigin: true,  // requis : Azure App Service route par Host header
    }
  }
}
```

```powershell
npm run dev
```
Ouvrir `http://localhost:5173` → graphe Cytoscape avec les 23 nœuds FL + CardDemo

✅ **Vérifié en Sprint 0** (2026-06-07) : serveur démarré (`VITE ... ready`),
page servie (200, `<div id="root">` présent), proxy `/api/graph/health` et
`/api/graph/nodes` testés via le serveur dev local → données réelles renvoyées
(`neo4j: connected`, `count: 23`). `npx tsc --noEmit` passe après les 2 corrections
ci-dessus. Rendu visuel du graphe Cytoscape non vérifié ici (pas de navigateur
headless disponible sans téléchargement ~300 Mo) -- à confirmer dans le navigateur.

Quand prêt pour production :
```powershell
npm run build
# Puis déployer sur Static Web App (GitHub Actions ou az staticwebapp deploy)
```

---

## Checklist finale

### Infrastructure Azure
- [x] Scripts `SPRINT0_setup-azure.ps1` + `SPRINT0_fixup-azure.ps1` exécutés sans erreur
- [x] SQL Database créée + DDL SPRINT0_setup-sql.sql exécuté (8 objets : 6 tables + 2 vues, 16 lignes seed EffortCalibration)
- [x] Key Vault (mode RBAC) : 7 secrets présents, rôle "Key Vault Secrets User" assigné aux 4 identités (vérifié 4/4)
- [x] Neo4j ACI : état "Running", GDS disponible (16 procédures gds.louvain.*/gds.betweenness.* confirmées)
- [x] Neo4j graphe initialisé : 23 nœuds, 31 relations (chiffres réels — corrigent l'estimation initiale 28/22)
- [x] Containers blob `retrodocs` + `exports` créés (Portail, manuel — proxy Zscaler bloque l'az CLI local)
- [x] 4 Function Apps créées avec identité managée + rôle "Cognitive Services OpenAI User" sur oai-nlmazure-prod (vérifié 4/4)
      ⚠️ Gap de provisioning détecté + corrigé sur les 4 Function Apps (adgm/mwp/admm/sevenrqa) :
      `AzureWebJobsStorage`, `FUNCTIONS_WORKER_RUNTIME`, `FUNCTIONS_EXTENSION_VERSION` étaient
      absents (host settings de base, sans lesquels le runtime Functions ne démarre pas --
      `func azure functionapp publish` échouait avec "missing host storage configuration").
      Probablement écrasés par l'étape 9 du script (app settings via `--settings`, qui peut
      remplacer plutôt que fusionner). Corrigé en pointant `AzureWebJobsStorage` vers la
      connection string de `modernagentstgdev` (réutilisée -- même compte que `BLOB_CONNECTION_STRING`)
      + `FUNCTIONS_WORKER_RUNTIME=python` + `FUNCTIONS_EXTENSION_VERSION=~4` sur les 4 apps.
- [ ] ArchiMind / Azure OpenAI / Azure AI Search accessibles (ressources de prod réutilisées, aucun redéploiement)
      ⚠️ `app-api-nlmazure-prod` ne répond pas actuellement (504 Gateway Timeout puis timeout réseau) —
      incident probable côté prod partagée ou chemin réseau, hors périmètre de cette infra (cf. Troubleshooting).
      Azure OpenAI + Azure AI Search : accès RBAC validé (rôles assignés et vérifiés ci-dessus).

### Gate Sprint 1 (ADG-M)
- [x] `GET /api/graph/health` → 200, `"neo4j": "connected"` (vérifié : `{"status":"healthy","neo4j":"connected"}`)
- [x] `GET /api/graph/nodes` → 23 nœuds (vérifié : `"count": 23`)
- [x] `GET /api/graph/arcs` → 31 relations (vérifié : `"count": 31`)

✅ **Gate Sprint 1 débloquée** — `modernagent-adgm-dev` déployé (scaffold V1, cf. 4.1) et
les 3 endpoints répondent avec les chiffres attendus sur les données réelles
(fixture FL + CardDemo chargée en Phase 3).

### PC
- [x] Aucun serveur qui tourne en permanence
- [x] Neo4j : accessible via browser Azure URL, pas Docker Desktop
- [x] ArchiMind : instance de prod réutilisée (`app-api-nlmazure-prod`), aucun serveur local ni redéploiement

---

## Économiser sur les coûts Azure

### Arrêter Neo4j ACI quand inactif
```powershell
az container stop --resource-group rg-sp4-d-vgi-azu-vgi-sandbox-txt --name neo4j-dev
az container start --resource-group rg-sp4-d-vgi-azu-vgi-sandbox-txt --name neo4j-dev
```
ACI = facturation par seconde d'exécution. Si tu travailles 4h/jour sur 5 jours :
`1 vCPU × 0.5 €/h × 20h = ~10 €/semaine` au lieu de 30 €/mois en continu.

### Functions : Free Tier
Premier 1 million d'exécutions/mois gratuit. Pas de facturation en Sprint 0.

---

## Troubleshooting

### Neo4j ACI ne démarre pas
```powershell
az container logs --resource-group rg-sp4-d-vgi-azu-vgi-sandbox-txt --name neo4j-dev
```
→ Chercher "GDS" dans les logs pour confirmer l'installation du plugin

### Function App : `func azure functionapp publish` échoue avec "missing host storage configuration"
→ Il manque les *host settings* de base (`AzureWebJobsStorage`, `FUNCTIONS_WORKER_RUNTIME`,
  `FUNCTIONS_EXTENSION_VERSION`) -- sans eux le runtime Functions ne démarre pas du tout
  (différent des settings métier comme `NEO4J_BOLT_URI` etc.). Repéré sur les 4 Function
  Apps de ce sprint (probablement écrasés par l'étape 9 du script de provisioning) et
  corrigé en une fois :
```powershell
$conn = az storage account show-connection-string --name modernagentstgdev `
  --resource-group rg-sp4-d-vgi-azu-vgi-sandbox-txt --query connectionString -o tsv
foreach ($app in "modernagent-adgm-dev","modernagent-mwp-dev","modernagent-admm-dev","modernagent-sevenrqa-dev") {
  az functionapp config appsettings set --name $app --resource-group rg-sp4-d-vgi-azu-vgi-sandbox-txt `
    --settings "AzureWebJobsStorage=$conn" "FUNCTIONS_WORKER_RUNTIME=python" "FUNCTIONS_EXTENSION_VERSION=~4"
}
```
→ Vérifier : `az functionapp config appsettings list --name <app> ... --query "[?name=='AzureWebJobsStorage']"`

### Function App : "Connection refused" sur Neo4j
→ Vérifier que l'ACI est `Running` : `az container show ... --query instanceView.state`
→ Vérifier le secret Key Vault neo4j-bolt-uri avec l'URL publique ACI

### ArchiMind / Azure OpenAI inaccessibles (ressources réutilisées)
→ Ce sont des instances de **production partagées** (`app-api-nlmazure-prod`,
  `oai-nlmazure-prod`) : si elles ne répondent pas, le problème vient du
  réseau/proxy local (Zscaler) ou d'un incident côté prod — pas de cette infra.
→ Tester l'accès direct : `Invoke-WebRequest https://app-api-nlmazure-prod.azurewebsites.net`
→ Pour un échec d'auth OpenAI (401/403) : vérifier le rôle RBAC
  "Cognitive Services OpenAI User" sur `oai-nlmazure-prod`
  (`az role assignment list --scope <id-ressource-openai> --query "[].roleDefinitionName"`)

### Function App : erreur de résolution `@Microsoft.KeyVault(...)`
→ Vérifier que le rôle RBAC "Key Vault Secrets User" est assigné à
  l'identité managée de la Function App, scopé sur `modernagent-kv-dev`
  (le Key Vault est en mode RBAC : `set-policy` est rejeté avec
  "Cannot set policies to a vault with '--enable-rbac-authorization' specified")

### SQL : "Login failed"
→ Firewall "Allow Azure Services" est configuré par le script (0.0.0.0/0.0.0.0)
→ Vérifier le mot de passe dans le secret Key Vault sql-connection-string

---

## Prochaine étape après Sprint 0

**Gate débloquée** → ADG-M Phase 1 (T12 + T14) :
- Uploader un rétro-doc ArchiMind en Blob → déclenche Blob Trigger → GPT-4o extraction → Neo4j
- Louvain clustering + Betweenness SPOF (GDS) → métriques stockées SQL
- Affichage dans Cytoscape : clusters colorés, badges SPOF
