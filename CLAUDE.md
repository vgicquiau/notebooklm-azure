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
└── frontend/
    ├── index.html          # Point d'entrée — charge tous les scripts
    ├── vendor/             # Dépendances JS vendorisées (React, Babel, Mermaid, etc.)
    └── src/
        ├── tokens.jsx      # Design tokens (T.azure, T.ink, etc.) + icônes (Ic.*) + Logo
        ├── Header.jsx
        ├── SourcesRail.jsx # Rail gauche — sources indexées, upload, ingestion
        ├── NotesRail.jsx   # Rail droit — notes, indexation comme source
        ├── ChatPanel.jsx   # Zone de chat centrale
        └── App.jsx         # État global, logique métier, montage React
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
tokens.jsx → Header.jsx → SourcesRail.jsx → NotesRail.jsx → ChatPanel.jsx → App.jsx
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

## Quirks connus

- **MIME types sur Windows** : `main.py` enregistre explicitement `.js`, `.jsx`, `.css`, `.md` car le registre Windows ne les déclare pas toujours, ce qui ferait bloquer `X-Content-Type-Options: nosniff`.
- **Avertissement Babel** : `You are using the in-browser Babel transformer` — non bloquant, inhérent à l'architecture sans build.
- **Jobs d'ingestion** : stockés en mémoire dans `_jobs` (dict dans `ingest.py`). Perdus au redémarrage du serveur — par design (usage local).

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
