# Étude — "Exploration Avancée GraphRAG & Neo4j" : compatibilité, impact, plan adapté

> Analyse de [`Spécifications d'Exploration GraphRAG.pdf`](Spécifications%20d'Exploration%20GraphRAG.pdf)
> (3 fonctionnalités : Semantic Zoom, Auto-Clustering DDD, Assistant Chatbot copilote)
> au regard de l'état réel de `notebooklm-azure` (golden sources, contraintes techniques,
> usage). Référence métamodèle : [`METAMODELE_legacyKB.md`](METAMODELE_legacyKB.md).

## 0. Constat-clé : le document suppose un graphe "à construire", le nôtre existe déjà

Les 3 fonctionnalités du PDF sont écrites comme si on partait d'un graphe brut
programme-à-programme, sans hiérarchie ni résumés. **Ce n'est pas notre situation** :
`neo4j-legacykb` contient déjà, pour 5713 `:Entity` et 96 `:Community` (70 niveau 1
/ 26 niveau 2) :

- une hiérarchie à 2 niveaux (`IN_COMMUNITY`, `SUBCOMMUNITY_OF`) — exactement
  l'équivalent de `[:PART_OF]`/`[:BELONGS_TO_DOMAIN]` demandé en F1 ;
- des résumés fonctionnels **et** techniques pré-calculés par LLM, à chaque niveau
  (`functional_summary`/`technical_summary` sur les communautés, `functional_description`/
  `technical_description` sur les entités) — exactement le "pré-calcul IA bottom-up"
  demandé en F1 ;
- des **embeddings** (1536-dim) sur chaque nœud (`functional_embedding`,
  `technical_embedding`) — la matière première de F2, déjà calculée.

Conséquence : une bonne partie du travail "Mécanique sous-jacente" décrit pour F1 et F2
**est déjà fait** (probablement par le pipeline GraphRAG d'origine, cf.
`docs/extract/mapping-graphrag-to-adgm.md`). Le travail restant est surtout côté
**frontend/API** (exploiter ce qui existe), pas côté "construire le graphe".

## 1. Contrainte transversale : `neo4j-legacykb` est en lecture seule

Décision actée le 2026-06-13 (`NOTE_devenir_ADGM_golden_source.md`) :
`neo4j-legacykb` est une **golden source en lecture seule**, jamais modifiée par
l'application. Or :

- F1 demande de créer des relations `[:PART_OF]`/`[:BELONGS_TO_DOMAIN]` — **non
  nécessaire** (la hiérarchie existe déjà via `IN_COMMUNITY`/`SUBCOMMUNITY_OF`).
- F2 demande de stocker en base le résultat du clustering (nouvelles communautés +
  noms générés par LLM) — **incompatible tel que décrit**. Le résultat d'un
  ré-clustering devra être calculé à la demande et **mis en cache côté API**
  (mémoire ou petit fichier JSON local, comme `_jobs` dans `ingest.py`), jamais
  écrit dans `neo4j-legacykb`.

## 2. Vérifications techniques effectuées sur l'instance réelle

| Vérification | Résultat | Impact |
| --- | --- | --- |
| Édition Neo4j | **5.22 Community** | Pas de **GDS** (Graph Data Science) — `gds.louvain`, `gds.labelPropagation` etc. indisponibles. F2 telle que spécifiée (GDS pondéré physique+sémantique) **n'est pas exécutable in-base**. |
| Plugins disponibles | **APOC** présent | Utile pour parcours de chemins (`apoc.algo.dijkstra`, `apoc.path.*`) → utile pour F3 cas 2 (blast radius). |
| Index vectoriel | **Aucun** (seulement les index techniques `LOOKUP`) | `vector.similarity.cosine()` (fonction Cypher native depuis 5.13, **disponible en Community**) fonctionne mais en full scan — acceptable sur 96 communautés / 5713 entités pour un usage interactif occasionnel, pas pour du temps réel à chaque frappe. |
| Hiérarchie existante | 2 niveaux + résumés + embeddings déjà présents | Couvre l'essentiel de F1 et la matière première de F2 (cf. §0). |

## 3. Fonctionnalité 1 — "Semantic Zoom"

### Compatibilité
**Très bonne**, à condition de la reformuler : pas de "Group Nodes/Sub-Flows React
Flow" imbriqués (complexité élevée, peu adaptée à un graphe sans build), mais une
**navigation par niveaux** déjà esquissée par `LegacyKbPage.jsx` :

- Niveau "domaine" (`:Community` level 2, 26 nœuds) — vue actuelle `loadDomains()`.
- Niveau "sous-domaine" (`:Community` level 1, 70 nœuds, avec `functional_summary`) —
  zones actuelles.
- Niveau "entités" (`:Entity`, avec `technical_description`) — déjà la vue détaillée.

### Plan adapté
1. **Backend** : endpoint léger `GET /api/legacykb/communities/{id}/children` (déjà
   quasi équivalent à `get_node_neighbors` filtré sur `SUBCOMMUNITY_OF`/`IN_COMMUNITY`)
   — pas de nouveau calcul, juste une vue dédiée à la navigation hiérarchique.
2. **Frontend** : un mode "vue domaines" → clic = drill-down vers les sous-domaines
   (zones actuelles) → clic = drill-down vers les entités. Affichage de
   `functional_summary`/`technical_summary` au niveau approprié (déjà dans
   `get_node`).
3. **Zoom à la molette** (`onMove`/niveau de zoom xyflow) : *optionnel*, en confort
   visuel uniquement — le déclencheur fiable reste le **double-clic** déjà implémenté
   (`exploreNode`), pas la molette (ambigu : zoom de la vue vs. changement de niveau
   sémantique).

### Effort
Faible-moyen — réutilise `legacykb_client.py` existant, étend `LegacyKbPage.jsx`
(nouveau mode de navigation), pas de pipeline IA à construire.

## 4. Fonctionnalité 2 — Auto-Clustering "Bounded Contexts" (DDD)

### Compatibilité
**Partielle**, et à challenger sérieusement (voir §6). Ce que F2 propose
(re-clustering Louvain pondéré physique+sémantique + nommage LLM) **existe déjà
sous une forme proche** : les 70 communautés de niveau 1 sont vraisemblablement
issues d'un clustering GraphRAG (Leiden) sur ce même graphe, déjà nommées par LLM
(`title`, `functional_summary`).

### Si on le fait malgré tout : plan adapté (sans GDS, sans écrire dans Neo4j)
1. **Backend** (nouveau module, ex. `api/services/legacykb_clustering.py`) :
   - Lire structure (`:Entity`-[r]->`:Entity` relations structurelles) +
     `functional_embedding` via Cypher.
   - Construire un graphe **NetworkX** en Python, poids d'arête = combinaison
     `α·(lien physique) + β·(similarité cosinus des embeddings)`.
   - Lancer `python-louvain` (`networkx.algorithms.community`) — pas besoin de GDS.
   - Nommer chaque cluster via le LLM (échantillon de `functional_description`),
     **mettre en cache** (mémoire ou fichier JSON local, pattern `_jobs`).
2. **API** : `GET /api/legacykb/clusters` (calcul à la demande + cache), retourne
   `{cluster_id, title, member_ids[]}`.
3. **Frontend** : bouton "Découvrir les domaines sémantiques" → zones React Flow
   colorées par cluster (réutilise le mécanisme de zones déjà construit) + édges
   inter-clusters mis en évidence (couleur distincte) = "analyse de couplage".

### Effort
**Moyen-élevé** pour un gain incertain par rapport à l'existant — cf. recommandation §6.

## 5. Fonctionnalité 3 — Assistant Chatbot copilote du graphe

### Compatibilité
**Excellente — c'est la fonctionnalité la plus alignée avec l'existant.** Le Chat
dispose déjà d'un **agent function-calling avec accès lecture à `neo4j-legacykb`**
(`api/services/graph_tools.py` : `legacykb_search`, `get_entity`, `get_relations`).
Il manque uniquement le **canal retour vers le canvas** (le payload JSON
"nœuds à isoler/surligner" décrit en F3).

### Plan adapté
1. **Nouveaux tools function-calling** (dans `graph_tools.py`) :
   - `legacykb_highlight(node_ids, reason)` — le LLM appelle cet outil quand il veut
     "montrer" un sous-graphe ; son résultat n'est pas du texte mais un **payload de
     pilotage UI**.
   - `legacykb_impact_paths(node_id, max_depth)` — parcours `apoc.path.subgraphAll`
     ou Cypher variable-length sur les relations structurelles = "blast radius"
     (F3 cas 2), sans GDS.
2. **Transport** : le endpoint `/api/chat` (déjà SSE/streaming ?) ajoute un événement
   `graph_action` distinct du texte — le front (`ChatPanel.jsx` ou un nouveau panneau
   dans `LegacyKbPage.jsx`) écoute cet événement et appelle `setNodes`/`setEdges`
   (estompage + surbrillance), réutilisant `bundle`/`_layout` existants.
3. **Explicabilité** : les tools legacykb actuels exécutent déjà des requêtes Cypher
   **fixes et paramétrées** (pas de Text-to-Cypher libre) — le bouton "Détails" peut
   afficher la requête template + paramètres réellement exécutés. **Recommandation
   forte : ne pas implémenter de Text-to-Cypher libre** (cf. §6, risque sécurité).
4. **UI** : popup chatbot flottante sur `LegacyKbPage.jsx`, réutilisant le composant
   de chat existant (`ChatPanel.jsx`) en mode compact, scoping ses tools sur
   legacykb uniquement (déjà le cas pour ce type de question via le system prompt).

### Effort
**Faible-moyen** — l'agent et l'accès lecture existent déjà ; le travail est le
"data binding" front (nouveau type d'événement SSE + handlers React Flow) et 1-2
nouveaux tools.

## 6. Challenge & recommandations

### 6.1 Priorisation recommandée
1. **F3 (chatbot copilote)** — le plus proche de l'existant, le plus de valeur
   immédiate (le Chat sait déjà répondre sur legacykb ; il manque "juste" le pilotage
   visuel). À faire **en premier**.
2. **F1 (navigation par niveaux)** — quasi gratuite vu la hiérarchie + résumés déjà
   en base ; bon complément naturel de F3 ("zoome sur le module facturation").
3. **F2 (re-clustering DDD)** — à **discuter avant de lancer** : la valeur ajoutée
   par rapport aux 70 communautés GraphRAG déjà nommées et résumées est à valider.
   Une alternative à moindre coût : exposer une **analyse de couplage sur les
   communautés existantes** (compter les relations structurelles inter-communautés
   vs. intra-communauté, sans aucun re-clustering) — donne le "pain points"
   visuel de F2 (liens rouges inter-boîtes) pour un coût quasi nul.

### 6.2 Risque sécurité — Text-to-Cypher libre (F3)
Le PDF propose que l'agent **génère lui-même des requêtes Cypher** à partir du
langage naturel. Sur une base en lecture seule le risque d'écriture est nul, mais :
- une requête Cypher générée par LLM à partir d'un prompt utilisateur **non
  fiable** peut être détournée (prompt injection) pour exfiltrer massivement les
  `functional_description`/embeddings, ou lancer des requêtes coûteuses (déni de
  service sur la petite instance Neo4j partagée).
- **Recommandation** : conserver l'approche actuelle (tools paramétrés, requêtes
  Cypher fixes côté code) et l'étendre avec 2-3 tools supplémentaires ciblés
  (recherche sémantique, blast radius, stats de couplage) plutôt que d'ouvrir
  Text-to-Cypher généraliste.

### 6.3 Recherche sémantique (amélioration transverse, peu coûteuse)
La fonction `search()` de `legacykb_client.py` ne fait que du `CONTAINS`
(sous-chaîne). Les embeddings existent déjà sur chaque nœud : ajouter une recherche
**sémantique** via `vector.similarity.cosine(node.functional_embedding, $queryEmbedding)`
améliorerait à la fois la recherche dans `LegacyKbPage` et la pertinence des tools
`legacykb_search` du Chat — prérequis naturel et réutilisable pour F2 si elle est
faite plus tard. Coût : un appel d'embedding (Azure OpenAI, déjà utilisé par
`ingest/embedder.py`) + une requête Cypher, pas d'index nécessaire à ce volume.

### 6.4 Autre piste pertinente vue l'usage réel
**Tableau de "santé du corpus"** : 529 `:Entity` ont `is_missing = true` (référencées
mais sans fichier source dans le périmètre analysé). Pour un usage "préparation de
migration", lister/filtrer ces entités manquantes (déjà visible nœud par nœud, mais
pas en vue agrégée) aide à cadrer le périmètre réel avant toute décision — effort
minimal (une requête + un panneau), valeur immédiate pour le métier.

## 7. Synthèse — ce qui est proposé concrètement

| # | Fonctionnalité (reformulée) | Écrit dans neo4j-legacykb ? | Nouveau composant majeur | Effort |
| --- | --- | --- | --- | --- |
| F3' | Chatbot copilote pilote le canvas LegacyKB (highlight, blast radius) | Non (lecture only) | event SSE `graph_action` + 2 tools | Faible-moyen |
| F1' | Navigation par niveaux (domaine → sous-domaine → entité) avec résumés | Non | mode "drill-down" dans `LegacyKbPage` | Faible |
| F2' | Analyse de couplage inter-communautés (sans re-clustering) | Non | endpoint stats + édges colorés | Faible |
| F2'' (optionnel, à valider) | Re-clustering DDD (NetworkX + cache local) | Non (cache local) | nouveau module clustering | Moyen-élevé |
| (bonus) | Recherche sémantique via embeddings existants | Non | requête `vector.similarity.cosine` | Faible |
| (bonus) | Vue "santé du corpus" (entités `is_missing`) | Non | endpoint + panneau | Très faible |
