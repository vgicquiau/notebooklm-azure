# Note — Devenir du graphe ADG-M (neo4j-dev) face aux golden sources

> **Décision (2026-06-13)** : scénario 3 retenu — retrait du graphe ADG-M, du pipeline
> d'extraction et des fonctionnalités qui en dépendent (classification ArchiMate, module
> Exploration). L'application se recentre sur les deux golden sources (documents +
> neo4j-legacykb).

> Contexte : l'application doit s'appuyer uniquement sur deux **golden sources** :
> 1. les documents indexés dans Azure AI Search (`notebooklm-chunks`)
> 2. `neo4j-legacykb` (dump GraphRAG brut de CardDemo — programmes, copybooks, jobs,
>    domaines, relations CALLS/INCLUDES/READS/INSERTS/...)
>
> Le graphe ADG-M (`neo4j-dev`, taxonomie v2.0) est aujourd'hui **construit par extraction
> LLM des documents** (golden source #1), via le pipeline `extract.py` (Inventaire →
> Enrichissement → Complétion). Il n'est donc pas lui-même une golden source — il en est
> une *interprétation*. La question est : que doit-il devenir ?
>
> Trois scénarios sont possibles. Ils ne sont pas mutuellement exclusifs dans le temps —
> on peut commencer par le scénario 1 et basculer plus tard vers 2 ou 3 si l'usage le
> justifie.

---

## Scénario 1 — Garder comme couche d'annotation (statu quo recadré)

**Principe** : ADG-M reste construit par extraction LLM des documents, mais on le
requalifie explicitement comme une **vue d'analyse régénérable**, jamais comme une
vérité indépendante. Le bouton "Mise à jour" reste le seul moyen de le faire évoluer
(pas d'édition manuelle qui le ferait diverger des documents).

**Ce que ça apporte** :
- Conserve tout l'investissement déjà fait : taxonomie v2.0 (19 labels, 11 relations,
  `fiabilite`), pipeline 3 étapes, vues par couche (Fonctionnel/Applicatif/Données/...),
  scoring 7R, détection SPOF, clustering Louvain.
- C'est une "lecture augmentée" des documents : ça répond à des questions que ni le
  chat texte ni legacykb (qui est un dump de code, sans dimension fonctionnelle/métier)
  ne couvrent directement — ex. "quels domaines fonctionnels dépendent les uns des
  autres", "quels composants sont des points de couplage fort".

**Coût / effort** :
- Quasi nul immédiatement — surtout du cadrage (documentation, garde-fous) plutôt que
  du code.
- Coût récurrent maintenu : chaque "Mise à jour" relance ~25 appels LLM sur le corpus.
- Limite connue et déjà documentée séparément : l'extraction actuelle sous-énumère les
  listes longues (cf. arc "Pipeline d'extraction v2", en attente).

**Choisir ce scénario si** : la vue ADG-M (qualification archi, SPOF, clusters, vues par
couche fonctionnelle) apporte une valeur d'analyse réelle au quotidien, et que son
statut de "vue dérivée, pas vérité" est acceptable.

---

## Scénario 2 — Refondre pour rebrancher sur legacykb

**Principe** : au lieu d'extraire ADG-M des documents, on le construit/enrichit à partir
de `neo4j-legacykb` (golden source #2, déjà structurée et fiable : 5812 entités/
communautés, ~19k relations issues du code réel). La taxonomie v2.0 (`Composant`,
`Job_Batch`, `Procedure_Reutilisable`, `Domaine_Technique`...) serait mappée/dérivée des
`Program`/`BatchJob`/`Copybook`/`Community` de legacykb.

**Ce que ça apporte** :
- ADG-M devient traçable et reproductible depuis une source structurée et fiable (issue
  du code), au lieu d'une extraction LLM sur du texte — moins de variabilité, moins de
  "trous" dans les listes (SPOF, clusters, dépendances applicatives/techniques).
- Réduit le périmètre du pipeline d'extraction documentaire à ce que legacykb ne couvre
  pas (la dimension fonctionnelle/métier : `Domaine_Fonctionnel`, `Fonction`,
  `Regle_Metier`, `Processus_Fonctionnel`).

**Coût / effort** :
- Chantier important : nouveau mapping legacykb → taxonomie v2.0, nouvelle logique de
  transformation, et un pipeline qui reste **hybride** (couches techniques depuis
  legacykb, couches fonctionnelles toujours depuis les documents).
- Couplage fort à legacykb, qui est spécifique au corpus CardDemo (COBOL) — si l'app
  doit rester généralisable à d'autres systèmes (cf. "fiche d'instanciation"
  `EXTRACT_SYSTEM_NAME`/`EXTRACT_STACK_*`), ce rebranchement réduit cette généricité.

**Choisir ce scénario si** : l'objectif premier d'ADG-M est de cartographier
*fidèlement* l'existant technique CardDemo (appels, accès fichiers, dépendances), et que
la dimension fonctionnelle/métier issue des docs est secondaire ou peut continuer sur le
pipeline actuel en complément.

---

## Scénario 3 — Déprécier / retirer

**Principe** : on retire la vue Graphe ADG-M, le bouton "Mise à jour"/extraction, et
neo4j-dev de l'UI. Le chat (déjà branché sur les deux golden sources via les tools
function-calling) devient le seul point d'accès "intelligent" ; legacykb reste
consultable via sa propre vue (à terme en xyflow).

**Ce que ça apporte** :
- Simplifie radicalement la surface de l'app : 2 sources de vérité au lieu de 2 + 1 vue
  dérivée à entretenir.
- Supprime un poste de coût LLM récurrent (extraction) et une source de confusion/dette
  (un graphe "approximatif" en plus des golden sources).

**Coût / effort** :
- Faible côté app — retrait de composants/routes, pas de nouvelle construction.
- Le code et l'infra Azure (`fn-adgm-graph`, neo4j-dev) peuvent être conservés "au repos"
  ou décommissionnés séparément, sans urgence.

**Ce qu'on perd** :
- Les vues d'analyse spécifiques (scoring 7R, SPOF, clusters Louvain, vues par couche
  fonctionnelle) n'ont pas d'équivalent direct aujourd'hui dans le chat ou legacykb —
  sauf à les reconstruire plus tard sous une autre forme (ex. nouveaux tools de chat sur
  legacykb, ou requêtes ad hoc).

**Choisir ce scénario si** : avec le recul, la vue ADG-M n'a pas (ou plus) d'usage réel
au quotidien, et la priorité est de stabiliser l'app autour des deux golden sources.

---

## Tableau comparatif

| | Scénario 1 — Annotation | Scénario 2 — Rebranché legacykb | Scénario 3 — Retrait |
|---|---|---|---|
| Effort immédiat | Très faible (cadrage) | Important (nouveau mapping) | Faible (retrait UI) |
| Coût LLM récurrent | Maintenu | Réduit (couches techniques) | Supprimé |
| Fidélité technique | Limitée (extraction LLM) | Élevée (issue du code) | N/A |
| Couverture fonctionnelle/métier | Oui (via docs) | Oui, en complément (via docs) | Perdue |
| Généricité multi-systèmes | Conservée | Réduite (couplage CardDemo) | N/A |
| Vues 7R/SPOF/Louvain | Conservées | Conservées (sur base legacykb) | Perdues |

## Lien avec la décision ArchiMate / Exploration

Le module **Exploration** (CRUD `:ArchiMateElement`) opère sur le **même graphe neo4j-dev
qu'ADG-M** : ses nœuds sont des nœuds ADG-M étiquetés `:ArchiMateElement` par le pipeline
de classification (`archimate_classify.py`, groupe 6 — déjà décidé : à déprécier/retirer).
Conséquence : si ADG-M part en scénario 3 (retrait), Exploration n'a plus de données à
afficher de toute façon. Si ADG-M reste (scénarios 1 ou 2) mais que la classification
ArchiMate est retirée, Exploration perd sa source d'alimentation — son propre devenir
doit donc être tranché en cohérence avec le scénario ADG-M retenu (cf. investigation en
cours sur le module Exploration).
