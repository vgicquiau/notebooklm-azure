# Sprint 0 — Infrastructure & Scaffolding

**État** : Livré le 2026-06-07
**Durée estimée** : 3-4 jours (solo)
**Critère de succès** : Graphe Cytoscape + APIs GET /graph/* répondent avec données fixture

---

## 📦 Fichiers livrés

| Fichier | Rôle | Format |
|---------|------|--------|
| `SPRINT0_setup-neo4j.cypher` | Initialisation graphe (3 nœuds fixture, 2 arcs) | Cypher |
| `SPRINT0_setup-sql.sql` | DDL : tables Component, Dependency, Metrics, EffortCalibration | T-SQL |
| `SPRINT0_setup-azure.ps1` | Provisioning Azure (SQL, Blob, KV, Functions, Static Web App, AppInsights) | PowerShell |
| `SPRINT0_fn-adgm-ingest_function_app.py` | Blob Trigger + GPT-4o extraction (skeleton) | Python |
| `SPRINT0_fn-adgm-graph_function_app.py` | HTTP APIs /graph/* (skeleton) | Python |
| `SPRINT0_frontend-skeleton.tsx` | React Cytoscape + node detail sidebar | TypeScript/React |
| `SPRINT0_CHECKLIST.md` | Étapes pas-à-pas d'exécution | Markdown |
| `SPRINT0_README.md` | Ce fichier | Markdown |

---

## 🚀 Quick Start (5 min overview)

### Ce qu'il y a dedans

**Infrastructure locale :**
- Neo4j Community Docker (graphe en-mémoire, gratuit, full GDS)
- SQL Azure (dev Basic tier ~5€/mois)
- Azure Functions (Python 3.11, Free Tier)

**Code skeleton :**
- 2 Azure Functions : ingestion (Blob trigger) + graph APIs (HTTP)
- React frontend : affichage Cytoscape + node detail
- Fixture : 3 composants (COBOL Core, DB2, REST Gateway) + 2 dépendances

**Infrastructure Cloud :**
- Resource Group dédié
- Key Vault pour secrets
- Blob Storage pour rétro-docs
- App Insights pour monitoring
- Static Web App pour fronted

---

## ⚙️ Étapes d'exécution

**Voir `SPRINT0_CHECKLIST.md` pour les commandes détaillées.**

### Phase 1 : Neo4j local (30 min)
```powershell
docker run -d --name modernagent-neo4j -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/neo4j neo4j:latest
# Puis copier SPRINT0_setup-neo4j.cypher → Neo4j Browser
```

### Phase 2 : Infra Azure (1 h)
```powershell
.\SPRINT0_setup-azure.ps1
# Puis exécuter SPRINT0_setup-sql.sql dans Azure Portal
```

### Phase 3 : Functions scaffolding (1 h)
```powershell
func init modernagent-backend --python
func new --name fn-adgm-ingest --template "Azure Blob Storage trigger"
func new --name fn-adgm-graph --template "HTTP trigger"
# Copier code Python fourni
func start  # Test local
```

### Phase 4 : Frontend Vite (30 min)
```powershell
npm create vite@latest modernagent-frontend -- --template react-ts
npm install cytoscape @msal/browser
# Copier SPRINT0_frontend-skeleton.tsx
npm run dev
```

### Phase 5 : Validation (30 min)
- Neo4j : `MATCH (n:Component) RETURN count(n)` → 3 ✓
- SQL : SELECT * FROM EffortCalibration → seed data ✓
- API : `curl http://localhost:7071/api/graph/health` → 200 ✓
- Frontend : `http://localhost:5173` → affiche graphe Cytoscape ✓

---

## 🔧 Architecture Sprint 0

```
┌─────────────────────────────────────────────────────────┐
│ Frontend (React Vite + Cytoscape.js)                    │
│ http://localhost:5173                                   │
└──────────────────────────────────────────────────────────┘
                           ↓ (HTTP)
┌──────────────────────────────────────────────────────────┐
│ Azure Functions (Python 3.11)                           │
│ GET /api/graph/health                                   │
│ GET /api/graph/nodes                                    │
│ GET /api/graph/arcs                                     │
│ GET /api/graph/nodes/{id}/spof                          │
│ PATCH /api/graph/nodes/{id}/qualification               │
└──────────────────────────────────────────────────────────┘
        ↓                               ↓
    ┌─────────────────┐          ┌─────────────────┐
    │ Neo4j Docker    │          │ Azure SQL       │
    │ :7687           │          │ modernagent_db  │
    │ (3 nœuds)       │          │ (audit + cal)   │
    └─────────────────┘          └─────────────────┘
```

---

## 📋 Fichiers de config à adapter

**SPRINT0_setup-azure.ps1** — Lignes 7-8:
```powershell
$subscriptionId = "YOUR_SUBSCRIPTION_ID"  # ← À remplacer
$resourceGroup = "YOUR_RESOURCE_GROUP"     # ← À remplacer (ex: rg-modernagent-dev)
```

**SPRINT0_fn-adgm-ingest_function_app.py** — Lignes 26-30:
```python
NEO4J_URI = os.getenv("NEO4J_BOLT_URI", "bolt://localhost:7687")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
SQL_CONNECTION_STRING = os.getenv("SQL_CONNECTION_STRING")
OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
OPENAI_API_KEY = os.getenv("AZURE_OPENAI_KEY")
# ↑ Vérifier que ces env vars sont dans local.settings.json (dev) + Key Vault (prod)
```

**SPRINT0_frontend-skeleton.tsx** — Ligne 67:
```typescript
const graphService = {
  async getHealth() {
    const resp = await fetch('/api/graph/health');  // ← Adapter le host si pas localhost:7071
    // ...
```

---

## 🎯 Validation Sprint 0

### ✅ Acceptance Criteria

1. **Neo4j** : Fixture (3 nœuds, 2 arcs) créée
   ```cypher
   MATCH (n:Component) RETURN n.name ORDER BY n.name
   → Résultat : COBOL Core, DB2 Production, REST Gateway
   ```

2. **SQL** : Tables créées + seed EffortCalibration
   ```sql
   SELECT COUNT(*) FROM dbo.Component WHERE id LIKE 'comp-%'
   → Résultat : 3
   ```

3. **APIs** : GET /graph/* répond 200 OK
   ```bash
   curl http://localhost:7071/api/graph/health
   curl http://localhost:7071/api/graph/nodes
   curl http://localhost:7071/api/graph/arcs
   → Tous : HTTP 200
   ```

4. **Frontend** : Cytoscape affiche le graphe
   - 3 nœuds visibles
   - 2 arcs visibles
   - Node detail sidebar au clic

5. **Infra Azure** : Ressources provisionées
   - SQL Server + Database
   - Blob Storage + container "retrodocs"
   - Key Vault + secrets
   - 4 Function Apps (empty deploy)
   - Static Web App

---

## ⚠️ Notes importantes

1. **Secrets** : Les clés OpenAI, SQL, Neo4j doivent être en Key Vault en prod
   - Dev local : utiliser `local.settings.json` (ajouté à `.gitignore`)
   - Prod : utiliser Key Vault + Managed Identity

2. **Coûts Azure** :
   - SQL Basic : ~5 € / mois
   - Blob Storage : ~1 € / mois (minimal)
   - Functions : Free Tier (1M exécutions)
   - **Total** : ~6-15 € / mois (solo dev, sans 24/7 server)

3. **Docker Desktop** : Neo4j local dépend de Docker running
   - Vérifier : `docker ps`
   - Arrêt : `docker stop modernagent-neo4j`
   - Redémarrage : `docker start modernagent-neo4j`

4. **Données réelles** : Fixture contient 3 nœuds de test
   - Remplacer avec vrais rétro-docs ArchiMind après Sprint 0
   - Voir T02 du plan : `notebooklm-azure/doc-archimind/*.md`

---

## 📅 Prochaine étape

Une fois Sprint 0 ✅, démarrer **ADG-M Phase 1** (T12 + T14) :

- **T12** : Ingestion F1.1
  - Lire 1-2 rétro-docs ArchiMind (ex: `cobol_archimind_cleaned.md`)
  - GPT-4o extraction (entités/relations)
  - Créer nœuds + arcs réels dans Neo4j

- **T14** : Métriques ADG-M
  - Louvain clustering (GDS)
  - Betweenness centrality (SPOF detection)
  - Stocker metrics en SQL

⏱️ Durée : ~5-7 jours (solo), puis ADM-M/7RQA peuvent commencer en parallèle

---

## 🆘 Support

Si blocage sur :
- **Neo4j** : `docker logs modernagent-neo4j`
- **SQL** : Azure Portal → Query Editor → Messages d'erreur
- **Functions** : `func start` → logs dans terminal + Application Insights
- **Frontend** : Browser DevTools → Console logs
- **Azure** : `az account show-error-details`

Cf. `SPRINT0_CHECKLIST.md` §"Problèmes courants"
