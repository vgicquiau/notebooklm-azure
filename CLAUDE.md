# CLAUDE.md — Guide de travail pour Claude Code

## Démarrage rapide

```powershell
# Lancer le serveur de dev (active le venv, ouvre le navigateur, démarre uvicorn)
.\start-dev.ps1
# Ou via VS Code : Ctrl+Shift+B
```

Le serveur écoute sur `http://127.0.0.1:8000`. Le frontend est servi statiquement par FastAPI.

---

## Structure du projet

```
notebooklm-azure/
├── api/                    # Backend FastAPI
│   ├── main.py             # App, middlewares, lifespan, montage du frontend
│   ├── routers/
│   │   ├── chat.py         # POST /api/chat
│   │   ├── extract.py      # POST /api/extract/graph (lance extraction Chat→Graph), GET /api/extract/graph/{job_id}
│   │   ├── graph.py        # Proxy server-to-server vers fn-adgm-graph : GET/PATCH /api/graph/*
│   │   ├── ingest.py       # POST /api/ingest, GET /api/ingest/{job_id}
│   │   └── sources.py      # GET /api/sources, GET /api/sources/{name}/chunks, DELETE /api/sources/{name}
│   └── services/
│       ├── retriever.py    # Recherche vectorielle dans Azure AI Search
│       └── generator.py    # Génération de réponse avec Azure OpenAI GPT-4o
├── ingest/
│   ├── chunkers/           # Un fichier par format (base.py définit Chunk)
│   │   ├── base.py         # Dataclass Chunk
│   │   ├── pdf_chunker.py  # Azure Document Intelligence
│   │   ├── docx_chunker.py # python-docx
│   │   ├── pptx_chunker.py # python-pptx — 1 slide = 1 chunk
│   │   ├── xlsx_chunker.py # openpyxl — lignes groupées par sheet
│   │   ├── md_chunker.py   # Sections par headings Markdown
│   │   └── text_chunker.py # Texte brut + code source (sliding window)
│   ├── embedder.py         # text-embedding-3-large via Azure OpenAI
│   └── indexer.py          # Azure AI Search — index "notebooklm-chunks"
├── frontend/
│   ├── index.html          # Point d'entrée — charge tous les scripts
│   ├── vendor/             # Dépendances JS vendorisées (React, Babel, Mermaid, Cytoscape…)
│   └── src/
│       ├── tokens.jsx      # Design tokens (T.azure, T.ink, etc.) + icônes (Ic.*) + Logo
│       ├── Header.jsx
│       ├── SourcesRail.jsx # Rail gauche — sources indexées, upload, ingestion
│       ├── NotesRail.jsx   # Rail droit — notes, indexation comme source
│       ├── ChatPanel.jsx   # Zone de chat centrale
│       ├── GraphPage.jsx   # Vue Graphe ADG-M (Cytoscape) — T16/T17/T18
│       └── App.jsx         # État global, vue active (chat|graph), montage React
├── azure-functions/        # Source des Azure Functions déployées (modernagent-adgm-dev)
│   ├── fn-adgm-graph/       # API Neo4j du graphe ADG-M (consommée via api/routers/graph.py)
│   ├── fn-adgm-ingest/      # Blob trigger — ingestion des rétro-docs
│   ├── db/                  # Schémas Neo4j / SQL (adgm_schema.sql, neo4j_schema.cypher, seed)
│   └── requirements.txt, host.json, .funcignore
├── doc-archimind/           # Corpus de référence CardDemo (architecture mainframe)
└── docs/
    ├── specs/               # Spécifications produit (SDD_*, ARCHITECTURE.md, plans…)
    └── archive/sprint0/     # Scripts/templates du bootstrap initial (superseded)
```

---

## Architecture frontend — points critiques

### Pas de build step
Le frontend utilise **Babel standalone** (`<script type="text/babel">`). Pas de `npm`, pas de webpack, pas de modules ES. Tout est transpilé dans le navigateur à la volée.

### Portée globale (scope `window`)
Tous les composants vivent dans `window`. Chaque fichier `.jsx` **doit** exporter ses composants publics en fin de fichier :

```jsx
Object.assign(window, { MonComposant });
```

**Risque de collision** : deux fichiers ne peuvent pas définir un composant du même nom. Exemple passé : `SourceCard` existait dans `ChatPanel.jsx` et `SourcesRail.jsx` — ça a écrasé silencieusement l'un d'eux. Nommer les composants locaux de façon distinctive.

### Ordre de chargement impératif
Dans `index.html`, les scripts sont chargés dans cet ordre (chaque fichier peut utiliser ce que le précédent a mis dans `window`) :

```
tokens.jsx → Header.jsx → SourcesRail.jsx → NotesRail.jsx → ChatPanel.jsx → GraphPage.jsx → App.jsx
```

Si tu ajoutes un nouveau composant, ajoute le `<script>` **avant** le fichier qui l'utilise, et **après** ses dépendances.

### Design tokens
Tout passe par l'objet `T` défini dans `tokens.jsx` (couleurs, radius, font). Ne jamais hardcoder de couleurs dans les composants.

---

## Ajouter un nouveau format d'ingestion

1. Créer `ingest/chunkers/mon_chunker.py` — implémenter `chunk_file(file_path: str) -> Iterator[Chunk]`
2. Ajouter l'extension dans `_CODE_EXTENSIONS` ou créer un set dédié dans `api/routers/ingest.py`
3. Ajouter la validation magic bytes dans `_check_magic_bytes()`
4. Ajouter le routing dans `_run_ingest()` (imports lazy à l'intérieur de la fonction)
5. Ajouter la dépendance Python dans `ingest/requirements.txt` et l'installer dans le venv
6. Mettre à jour l'attribut `accept` du `<input type="file">` dans `SourcesRail.jsx`

---

## Authentification Azure

En local : `DefaultAzureCredential` → utilise `az login`. Si `az account get-access-token` timeout, relancer `az login`.

En production (Azure Container Apps) : `ManagedIdentityCredential` avec `AZURE_CLIENT_ID`.

---

## Index Azure AI Search

- Nom : `notebooklm-chunks`
- Champs : `id`, `content`, `content_vector`, `source_file`, `page_number`, `chunk_index`, `doc_type`, `section`, `title`, `file_hash`, `created_at`
- Filtres OData utilisés : `chunk_index eq 0`, `source_file eq '...'`
- Facets sur `source_file` pour compter les chunks par source
- Les single quotes dans les valeurs OData sont échappées avec `''` (fonction `_odata_escape` dans `sources.py`)

---

## Graphe ADG-M

### Vue d'ensemble

La vue **Graphe ADG-M** (toggle "Graphe ADG-M" dans le header) est une fonctionnalité distincte de la vue Chat. Elle visualise l'architecture applicative extraite des documents Chat sous forme de graphe interactif (Cytoscape.js), qualifie les composants selon le modèle 7R et détecte les points de couplage fort (clusters Louvain).

### Composants impliqués

| Fichier | Rôle |
|---|---|
| `frontend/src/GraphPage.jsx` | Vue complète : canvas Cytoscape, bi-plan switch, detail panel, ExtractButton, ResetButton |
| `api/routers/graph.py` | Proxy server-to-server GET/PATCH/DELETE `/api/graph/*` → `fn-adgm-graph` (Azure Function) |
| `api/routers/extract.py` | Pipeline Chat→Graphe : lit l'index Search, appelle GPT-4o, pousse via `/admin/import-entities` |
| `frontend/vendor/cytoscape.min.js` | Cytoscape.js vendorisé (même pattern que mermaid.min.js / marked.min.js) |

### Variable d'environnement

```
ADGM_GRAPH_API_URL=https://modernagent-adgm-dev.azurewebsites.net/api/graph
```
Défaut dans les deux routers si absent. Ajouter dans `.env` pour cibler un autre déploiement.

### Bouton "Mise à jour" (ExtractButton)

1. `DELETE /api/graph/admin/functional-entities` — supprime les nœuds fonctionnels (`:FunctionalDomain`, `:MacroFunction`, `:Program`, `:DataEntity`) en préservant les `:TechnicalNode` et leurs annotations 7R
2. Lit **tous** les chunks de l'index Azure AI Search, groupés par `source_file`
3. Pour chaque document : appel GPT-4o (extraction JSON structurée) → `POST /api/graph/admin/import-entities`

Résultat : dataset cohérent sur l'intégralité du corpus, pas seulement une mise à jour delta.

### Bouton "Reset" (ResetButton)

- Deux-clics de confirmation (pattern sécurité : premier clic → "⚠ Confirmer le reset", second → exécution)
- `DELETE /api/graph/admin/reset` → `MATCH (n) DETACH DELETE n` dans Neo4j (toutes les données)
- Auto-annulation après 4 s si le second clic n'arrive pas

### Proxy `graph.py` — points à retenir

- Sert à contourner la CSP `connect-src 'self'` du frontend (le navigateur ne peut pas appeler directement `fn-adgm-graph` sur une autre origine)
- Relaie GET, PATCH et DELETE ; ne relaie **pas** `POST /admin/analyze` ni `POST /admin/import-entities` (administration back-office hors surface utilisateur)
- `httpx.AsyncClient` (0.28.1) — dépendance directe dans `api/requirements.txt`

### Azure Function `fn-adgm-graph` — quirk `function.json`

```json
{ "methods": ["get", "post", "patch", "delete"] }
```

Le tableau `methods` dans `function.json` contrôle l'acceptation HTTP **au niveau du trigger Azure**, avant que le code Python soit atteint. Si `"delete"` est absent, l'Azure Function retourne 404 sans jamais exécuter le handler — les logs Python restent vierges, ce qui rend le diagnostic non-évident.

### Déploiement de `azure-functions/`

Le code source de `fn-adgm-graph` et `fn-adgm-ingest` (sous `azure-functions/`) est déployé sur l'Azure Function App `modernagent-adgm-dev` :

```powershell
cd azure-functions
func azure functionapp publish modernagent-adgm-dev --python --build remote
```

`local.settings.json` (non commité) contient les chaînes de connexion locales et n'est jamais publié (`.funcignore`).

---

## Quirks connus

- **MIME types sur Windows** : `main.py` enregistre explicitement `.js`, `.jsx`, `.css`, `.md` car le registre Windows ne les déclare pas toujours, ce qui ferait bloquer `X-Content-Type-Options: nosniff`.
- **Avertissement Babel** : `You are using the in-browser Babel transformer` — non bloquant, inhérent à l'architecture sans build.
- **Jobs d'ingestion** : stockés en mémoire dans `_jobs` (dict dans `ingest.py` et `extract.py`). Perdus au redémarrage du serveur — par design (usage local).

---

## Git workflow

### Stratégie de branches

```
master          — branche principale, toujours stable et déployable
feature/<sujet> — toute nouvelle fonctionnalité ou correction
```

Pas de `develop`, pas de `release/*` — le projet est petit, on travaille en trunk-based allégé.

### Cycle de travail type

```powershell
# 1. Créer une branche depuis master à jour
git checkout master
git pull
git checkout -b feature/mon-sujet

# 2. Travailler, commiter au fil de l'eau
git add api/routers/mon_fichier.py frontend/src/MonComposant.jsx
git commit -m "feat: décrire ce que ça fait et pourquoi"

# 3. Pousser et ouvrir une PR
git push -u origin feature/mon-sujet
gh pr create --title "feat: mon sujet" --body "Description des changements"

# 4. Après review/merge → nettoyer
git checkout master
git pull
git branch -d feature/mon-sujet
```

### Règles de commit

- Format : `type: message court` (pas de majuscule, pas de point final)
- Types : `feat` · `fix` · `refactor` · `docs` · `chore`
- Message = le **pourquoi**, pas le quoi (le diff montre le quoi)
- Tous les commits assistés par Claude incluent la co-signature :
  ```
  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
  ```

### Mettre à jour sa copie locale (amis/collaborateurs)

```powershell
# Récupérer les dernières modifications sans perdre ses changements locaux
git pull --rebase

# Si conflit : résoudre, puis
git rebase --continue
```

### Ne jamais faire

- `git push --force` sur `master`
- Commiter `.env`, `api/.venv/`, `documents/`, `infra/main.parameters.json`
- Merger sa propre PR sans review (sauf urgence documentée)

---

## Ce qui n'est jamais commité

- `.env`, `api/.env`, `ingest/.env` — contiennent les endpoints et clés Azure
- `infra/main.parameters.json` — contient les valeurs de déploiement Bicep
- `documents/` — documents métier uploadés par l'utilisateur
- `api/.venv/` — environnement virtuel Python
