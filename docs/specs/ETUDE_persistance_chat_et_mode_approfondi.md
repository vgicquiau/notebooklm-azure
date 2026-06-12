# Étude — Persistance du chat, compaction & refonte du mode "Approfondi"

> Statut : **étude / proposition de plan, aucune implémentation réalisée**.
> Objectif : servir de feuille de route détaillée pour une session Claude Code future.

---

## 1. État des lieux (architecture actuelle)

### 1.1 Côté frontend (`App.jsx`)
- `messages` : `React.useState([])` — **perdu à chaque reload**, jamais persisté.
- `notes` : persisté via `localStorage` (`nlaz-notes`).
- `sessionId` : persisté via `localStorage` (`nlaz-session`), créé par `getOrCreateSessionId()`.
- `mode` : `rapide | standard | approfondi`, état local non persisté (reset à `standard` au reload).

### 1.2 Côté backend (`api/routers/chat.py`)
- `_sessions: dict[str, dict[str, Any]]` — **dictionnaire en mémoire**, clé = `session_id`.
  - Chaque entrée : `{"history": [...], "last_access": float}`.
  - `MAX_SESSION_TURNS = 20` → tronque l'historique aux 40 derniers messages (20 tours).
  - `SESSION_TTL_SECONDS = 86_400` (24h) → purge via `_cleanup_stale_sessions()`.
  - Commentaire existant dans le code : *"remplacer par Redis pour les déploiements multi-workers"*.
- **Conséquence** : un simple redémarrage du serveur (`uvicorn --reload` en dev, ou redéploiement en prod) efface tout l'historique de toutes les sessions.

### 1.3 Génération (`api/services/generator.py`)
- `_MODE_CONFIG` : un prompt + `max_tokens` + `temperature` par mode.
- `generate()` reçoit `conversation_history` et n'utilise que `conversation_history[-8:]` (4 derniers tours) — indépendamment de `MAX_SESSION_TURNS`.
- `MODE_TOP_K` (frontend) : `{ rapide: 5, standard: 10, approfondi: 20 }`.

### 1.4 Référence pour le mode "Approfondi"
`notebooklm-azure/prompts-extraction-graphrag-legacy.md` contient une bibliothèque de **8 prompts d'extraction structurée** (C1 à C7 + B-Relations) utilisés pour la fonctionnalité Graphe ADG-M (`extract.py`). Caractéristiques clés réutilisables :
- Un bloc **"Couche 0 — Fiabilité"** commun, qui taggue chaque information extraite avec `FAIT | HYPOTHÈSE | SUPPOSÉ | MANQUANT`.
- Une règle de fusion en cas de conflit : `FAIT > HYPOTHÈSE > SUPPOSÉ > MANQUANT`.
- Un schéma de sortie JSON strict par "passe" (`<format_sortie>`), avec règles d'extraction et catalogues de relations.
- Une logique multi-passes (une passe par "couche" d'analyse).

---

## 2. Persistance du chat à travers les reloads

### 2.1 Problème
À chaque `F5`/reload :
- Le frontend perd `messages` (UI vide).
- `sessionId` survit (localStorage), donc le **backend pourrait** théoriquement répondre avec le bon historique — mais le frontend ne le lui demande jamais, et de toute façon l'historique backend est en mémoire et ne survit pas à un redémarrage serveur.

### 2.2 Options évaluées

| Option | Description | Avantages | Inconvénients |
|---|---|---|---|
| **A — localStorage seul** | Persister `messages` (avec citations) dans `localStorage` côté frontend | Zéro changement backend, instantané, simple | Ne survit pas à un changement de navigateur/poste, limite ~5-10 Mo, ne corrige pas la perte d'historique backend (donc le LLM "oublie" le contexte même si l'UI affiche encore les anciens messages) |
| **B — Backend persistant seul (SQLite/fichier)** | Remplacer `_sessions` (dict mémoire) par un store SQLite, et faire fetch de l'historique au montage du frontend | Source de vérité unique, survit aux redémarrages, base pour la compaction et un futur export | Nécessite un nouvel endpoint `GET /api/chat/history/{session_id}` + logique d'hydratation frontend |
| **C — Hybride (recommandé)** | localStorage = cache instantané pour l'affichage (UX immédiate au reload) + SQLite backend = source de vérité pour l'historique LLM et la persistance long terme | Reload instantané sans flash vide, contexte LLM correct même après redémarrage serveur, base solide pour compaction/export | Légèrement plus de code (deux mécanismes à garder cohérents) |

### 2.3 Recommandation : **Option C (hybride)**

**Pourquoi** : l'option A seule ne résout que la moitié du problème (l'UI réaffiche les messages, mais le LLM via `_sessions` en mémoire backend a toujours pu perdre le contexte si le serveur a redémarré entre-temps — incohérence UI/LLM). L'option B seule ajoute un aller-retour réseau systématique au chargement (léger flash de chargement). L'option C combine confort immédiat et robustesse.

### 2.4 Plan d'implémentation détaillé

#### Backend
1. **Nouveau module `api/services/session_store.py`** :
   - Backend SQLite (`sqlite3`, stdlib — pas de nouvelle dépendance), fichier `api/data/chat_history.db` (à ajouter au `.gitignore`, comme `documents/`).
   - Schéma :
     ```sql
     CREATE TABLE sessions (
       session_id TEXT PRIMARY KEY,
       created_at REAL,
       last_access REAL,
       summary_text TEXT DEFAULT NULL  -- voir §3 compaction
     );
     CREATE TABLE messages (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       session_id TEXT NOT NULL,
       role TEXT NOT NULL,             -- 'user' | 'assistant'
       content TEXT NOT NULL,
       citations_json TEXT,            -- NULL pour role='user'
       mode TEXT,
       tokens_used INTEGER,
       created_at REAL,
       FOREIGN KEY(session_id) REFERENCES sessions(session_id)
     );
     CREATE INDEX idx_messages_session ON messages(session_id, id);
     ```
   - Fonctions exposées : `get_or_create_session(session_id)`, `append_message(session_id, role, content, citations=None, mode=None, tokens_used=None)`, `get_history(session_id, limit=None)`, `clear_session(session_id)`, `cleanup_stale_sessions()`.
   - `get_history()` retourne la forme `[{"role": ..., "content": ...}]` attendue par `generator.generate()`, en excluant les colonnes superflues.

2. **`api/routers/chat.py`** :
   - Remplacer `_sessions` (dict) par des appels à `session_store`.
   - `get_or_create_session()` devient un wrapper fin autour de `session_store.get_or_create_session()`.
   - Après génération, `session_store.append_message(...)` pour le tour user + assistant (avec `citations_json` = JSON des `sources`).
   - Nouvel endpoint :
     ```python
     @router.get("/chat/history/{session_id}")
     async def get_chat_history(session_id: str):
         messages = session_store.get_full_history_for_ui(session_id)  # avec citations, timestamps
         summary = session_store.get_summary(session_id)
         return {"messages": messages, "summary": summary}
     ```
   - `/chat/clear` : appelle `session_store.clear_session(session_id)` (DELETE des lignes `messages` + `sessions`).

3. **Lifespan / cleanup** : appeler `session_store.cleanup_stale_sessions()` périodiquement (ex. dans le hook `lifespan` existant de `main.py`, ou paresseusement à chaque appel `/chat` comme aujourd'hui).

#### Frontend (`App.jsx`)
1. Au montage (nouveau `React.useEffect`), si `sessionId` existe :
   ```javascript
   _apiFetch(`${API_BASE}/chat/history/${sessionId}`)
     .then(r => r.ok ? r.json() : null)
     .then(data => {
       if (data?.messages?.length) setMessages(data.messages);
       else {
         // fallback localStorage si le backend n'a rien (ex: redémarrage serveur après usage récent)
         const cached = loadMessagesCache();
         if (cached.length) setMessages(cached);
       }
     });
   ```
2. Persister `messages` dans `localStorage` (`nlaz-messages`) à chaque changement, comme pour `notes` (`React.useEffect(() => saveMessagesCache(messages), [messages])`) — sert de fallback rapide et de cache offline.
3. `clearSession()` : vider aussi `localStorage.removeItem('nlaz-messages')`.
4. Limiter la taille du cache localStorage (ex. ne stocker que les 50 derniers messages) pour éviter de dépasser le quota.

#### Effort estimé
- Backend : ~2-3h (module SQLite + adaptation router + endpoint).
- Frontend : ~1h (hydratation + cache localStorage).
- Risque faible — change la couche de stockage sans changer les contrats API existants (sauf ajout d'un endpoint).

---

## 3. Stratégie de "compact" (compaction de l'historique)

### 3.1 Problème actuel
- Troncature brutale : au-delà de `MAX_SESSION_TURNS=20` tours, les plus anciens sont **supprimés purement et simplement** — perte d'information potentiellement utile.
- `generator.generate()` n'utilise déjà que les 4 derniers tours (`conversation_history[-8:]`), donc même sans troncature côté session, le contexte envoyé au LLM est très court — le "compact" doit donc surtout servir à préserver une **mémoire longue résumée**, pas juste à limiter les tokens immédiats (qui sont déjà bien maîtrisés).

### 3.2 Proposition : résumé glissant ("rolling summary")

Mécanisme :
1. À chaque appel `/chat`, après ajout du nouveau tour, si `len(history) > COMPACT_THRESHOLD` (ex. 12 tours / 24 messages) :
   - Prendre les `N` plus anciens messages non encore résumés (ex. les 8 plus anciens : 4 tours).
   - Appeler le LLM avec un prompt court et peu coûteux (config `rapide` : `max_tokens≈300`, `temperature=0.1`) :
     > *"Résume en 5-8 points factuels les éléments clés (sujets abordés, décisions, faits importants, questions en attente) de cet échange. Sois concis. Français."*
   - Fusionner ce résumé avec le `summary_text` existant de la session (concaténer / re-résumer si le résumé cumulé dépasse une taille limite, ex. 800 tokens).
   - Stocker le résultat dans `sessions.summary_text` (SQLite, cf §2.4).
   - Retirer ces messages de la fenêtre "active" envoyée au LLM (mais les garder en base pour l'affichage UI / export — l'utilisateur ne perd rien visuellement).
2. `generator.generate()` reçoit alors :
   ```python
   messages = [
       {"role": "system", "content": cfg["prompt"]},
       *( [{"role": "system", "content": f"Résumé de la conversation précédente :\n{summary_text}"}] if summary_text else [] ),
       *conversation_history[-8:],  # tours récents non résumés
       {"role": "user", "content": user_message},
   ]
   ```

### 3.3 Implémentation
- Nouveau module `api/services/compactor.py` :
  - `should_compact(history, threshold) -> bool`
  - `compact(history, existing_summary, generator) -> tuple[new_summary, remaining_history]`
- Appelé depuis `chat.py` **après** la réponse au tour courant (pour ne pas ralentir la requête en cours) — ou en tâche de fond (`BackgroundTasks` FastAPI) pour ne pas impacter la latence perçue.
- Constantes ajustables : `COMPACT_THRESHOLD_TURNS = 12`, `COMPACT_BATCH_TURNS = 4`, `SUMMARY_MAX_TOKENS = 300`.

### 3.4 UI (optionnel, phase 2)
- Petit indicateur discret dans le header du chat : *"🗜 Conversation compactée (résumé disponible)"*, cliquable pour afficher `summary_text` dans une popover. Non bloquant — peut être ajouté après le MVP backend.

### 3.5 Coût
- 1 appel LLM supplémentaire (très court, mode `rapide`) tous les ~4 tours. Négligeable comparé au coût des réponses elles-mêmes.

---

## 4. Réévaluation du mode "Approfondi"

### 4.1 Constat
Le mode `approfondi` actuel (`_PROMPT_APPROFONDI`, `top_k=20`, `max_tokens=4000`) reste un **passage unique** (single-pass) : tous les chunks sont mis dans le contexte et le LLM produit une réponse en un seul appel. C'est efficace pour de la synthèse/corrélation, mais :
- Limité par `top_k=20` chunks (~16k tokens) — pour une extraction réellement exhaustive sur un gros corpus, c'est insuffisant.
- Pas de garde-fou de fiabilité (`FAIT/HYPOTHÈSE/SUPPOSÉ/MANQUANT`) comme dans les prompts GraphRAG.
- Pas de mécanisme de "passes multiples" pour garantir l'exhaustivité demandée par l'utilisateur (ex. "liste-moi TOUTES les règles métier liées à X").

### 4.2 Principe retenu : garder 3 niveaux, mais transformer "Approfondi" en mode **agentique multi-passes** (map-reduce)

On conserve `rapide` / `standard` tels quels (ils fonctionnent bien et sont peu coûteux). "Approfondi" devient un **pipeline en 2 étapes** :

#### Étape 0 — Classification de la requête (peu coûteux)
Nouvel appel LLM léger (`max_tokens≈10`, mode `rapide`) :
```
classify_query(query) -> "synthese" | "extraction"
```
- `"synthese"` : questions d'analyse/explication/comparaison classiques → comportement actuel inchangé (single-pass, `_PROMPT_APPROFONDI`, `top_k=20`).
- `"extraction"` : requêtes de type "liste exhaustive", "extrais tous les...", "quelles sont toutes les règles/processus/interfaces liés à...", "fais-moi l'inventaire de..." → déclenche le **pipeline d'extraction multi-passes** (§4.3).

Heuristique de repli (si on veut éviter l'appel LLM de classification) : détection par mots-clés (`liste`, `inventaire`, `tous les`, `toutes les`, `exhaustif`, `extrais`, `recense`) — peut servir de fallback ou de première version sans coût LLM additionnel.

#### Étape 1 — Pipeline d'extraction multi-passes (cas "extraction")

Inspiré de `prompts-extraction-graphrag-legacy.md`, mais **généralisé** (pas limité au schéma C1-C7 du graphe — adapté dynamiquement à la question de l'utilisateur) :

1. **Retrieval élargi** :
   - `top_k` augmenté (ex. 30-40 au lieu de 20).
   - Optionnel (v2) : reformulation de requête — générer 2-3 variantes de la question (LLM léger) pour élargir le rappel, puis fusionner/dédupliquer les chunks récupérés.

2. **Passe d'extraction par lot ("map")** :
   - Découper les chunks récupérés en lots (ex. 5 chunks/lot → jusqu'à 6-8 lots pour 30-40 chunks).
   - Pour chaque lot, appel LLM avec un prompt d'extraction structurée incluant :
     - La question originale de l'utilisateur (ce qu'il faut extraire).
     - **Le bloc "Couche 0 — Fiabilité"** repris/adapté de `prompts-extraction-graphrag-legacy.md` : chaque élément extrait est tagué `FAIT | HYPOTHÈSE | SUPPOSÉ | MANQUANT` avec sa source.
     - Un schéma de sortie JSON simple et générique, ex. :
       ```json
       { "items": [ { "label": "...", "description": "...", "fiabilite": "FAIT", "source": 1 }, ... ] }
       ```
   - Chaque lot tourne en parallèle (asyncio.gather) si possible pour limiter la latence totale.

3. **Passe de fusion ("reduce")** :
   - Concaténer les `items` de tous les lots.
   - Dédupliquer (par `label` normalisé / similarité simple).
   - Appliquer la règle de fusion en cas de doublon avec fiabilités différentes : `FAIT > HYPOTHÈSE > SUPPOSÉ > MANQUANT`.

4. **Passe de synthèse finale** :
   - Un dernier appel LLM transforme la liste structurée fusionnée en réponse finale au format demandé (tableau, liste hiérarchique, etc.), avec citations `[n]` vers les sources d'origine — réutilise `_PROMPT_APPROFONDI` comme base de style.

#### Schéma du flux
```
Question utilisateur
   │
   ▼
classify_query() ──"synthese"──► pipeline actuel (top_k=20, 1 appel)
   │
 "extraction"
   │
   ▼
retrieve(top_k=30-40) ──► découpage en lots de 5 chunks
   │
   ▼
[appel LLM extraction lot 1] [lot 2] ... [lot N]   (parallèle, fiabilité taguée)
   │
   ▼
fusion + dédoublonnage + résolution fiabilité
   │
   ▼
appel LLM synthèse finale → réponse Markdown avec citations
```

### 4.3 Implémentation (`api/services/generator.py`)

Nouvelles constantes/méthodes :
- `_RELIABILITY_BLOCK` : constante texte, extraite/adaptée du bloc "Couche 0 — Fiabilité" commun aux 8 prompts de `prompts-extraction-graphrag-legacy.md`.
- `_PROMPT_EXTRACTION_BATCH` : prompt système pour la passe "map" (générique, paramétré par la question utilisateur).
- `_PROMPT_SYNTHESIS_FINAL` : prompt système pour la passe "reduce" finale (réutilise l'esprit de `_PROMPT_APPROFONDI`).
- `classify_query(self, query: str) -> Literal["synthese", "extraction"]`
- `_extract_batch(self, query: str, chunks: list[RetrievedChunk]) -> dict` (1 appel par lot)
- `_merge_extractions(self, batch_results: list[dict]) -> list[dict]` (dédup + fusion fiabilité, **pas d'appel LLM** — logique Python pure)
- `_synthesize_final(self, query: str, merged_items: list[dict], chunks: list[RetrievedChunk], conversation_history) -> tuple[str, int]`
- `generate_deep_extraction(self, query, chunks, conversation_history, injected_notes) -> tuple[str, int]` — orchestre 2-4.
- `generate()` (méthode existante) : pour `mode == "approfondi"`, appelle `classify_query()` puis route vers `generate_deep_extraction()` ou le comportement single-pass actuel.

### 4.4 Implémentation (`api/routers/chat.py`)
- Si `mode == "approfondi"` ET `classify_query() == "extraction"` :
  - Appeler `retriever.retrieve(message, top_k=35)` (au lieu de `request_data.top_k`).
- `tokens_used` retourné = somme des `tokens_used` de tous les appels LLM du pipeline (classification + lots + synthèse).

### 4.5 Frontend
- Pas de changement structurel obligatoire. Améliorations optionnelles (phase 2) :
  - Pendant le traitement d'une requête "extraction" (latence plus longue, ~20-60s), afficher un message d'attente différent : *"🔍 Analyse approfondie multi-passes en cours…"* (le frontend ne peut le savoir qu'après coup, sauf si le backend renvoie un statut intermédiaire via SSE/streaming — hors scope immédiat).

### 4.6 Garde-fous de coût/latence
- Plafonner : `MAX_BATCHES = 8` (donc `top_k` effectif borné à `MAX_BATCHES * BATCH_SIZE` = 40 avec `BATCH_SIZE=5`).
- Si `classify_query()` échoue (erreur réseau) → fallback silencieux sur le pipeline single-pass actuel (ne jamais bloquer l'utilisateur).
- Logger le nombre d'appels LLM et le total `tokens_used` par requête "extraction" pour suivre le coût réel en usage.

---

## 5. Ordre d'implémentation recommandé

| # | Chantier | Dépend de | Effort estimé |
|---|---|---|---|
| 1 | Persistance backend SQLite (`session_store.py`) + endpoint `/chat/history/{id}` | — | ~3h |
| 2 | Hydratation frontend au reload + cache `localStorage` messages | 1 | ~1h |
| 3 | Compaction (rolling summary) — `compactor.py` + intégration `chat.py` | 1 | ~2h |
| 4 | Refonte mode "Approfondi" (classification + pipeline map-reduce) | — (indépendant, peut être fait en parallèle) | ~4-6h |

Chaque chantier correspond idéalement à une branche `feature/...` distincte (cf. workflow git du projet) :
- `feature/chat-persistence`
- `feature/chat-compaction`
- `feature/mode-approfondi-extraction`

---

## 6. Points ouverts / décisions à confirmer avant implémentation

1. **SQLite vs fichier JSON** : SQLite recommandé (requêtes, pas de corruption en cas d'écriture concurrente), mais si simplicité maximale est préférée, un fichier JSON par session (`api/data/sessions/{session_id}.json`) est une alternative plus légère (suffisant pour un usage local mono-utilisateur).
2. **Seuils de compaction** (`COMPACT_THRESHOLD_TURNS`, `COMPACT_BATCH_TURNS`) : valeurs proposées (12 / 4) à ajuster selon usage réel.
3. **Mode "Approfondi" — classification automatique vs choix explicite utilisateur** : la classification heuristique/LLM peut parfois se tromper. Une alternative plus simple (et 100% prévisible) serait d'ajouter un **4ᵉ mode explicite** ("Extraction exhaustive" / "Approfondi+") au lieu d'une classification automatique — au prix d'un 4ᵉ bouton dans l'UI. À trancher selon préférence UX.
4. **Reformulation de requête (query expansion)** pour l'étape de retrieval élargi du mode extraction : proposée en v2, pas indispensable pour un MVP.
