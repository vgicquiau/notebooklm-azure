# Mapping GraphRAG → taxonomie ADG-M v2.0

> Spécification de transformation pour `repartition_cleaned_export.graphml`
> (export GraphRAG de l'application `repartition_cleaned`) vers le format
> `{nodes, relations}` attendu par `import_entities` (`fn-adgm-graph/function_app.py`).
> **Document de design — à valider avant écriture du script de mapping.**

---

## 1. Nœuds `:Entity`

| `type` GraphRAG | Label ADG-M | Préfixe `id` | Propriétés mappées | `fiabilite` |
|---|---|---|---|---|
| `Program` | `Composant` | `comp:` | `nom`=`name`, `description`=`technical_description` (FR via `functional_description` si dispo), `source`=`file_location`, `technologie`=déduit de `file_location` (`cbl_pacbase/` → `COBOL_PACBASE`, sinon `COBOL_BATCH`) | `HYPOTHÈSE` |
| `BatchJob` | `Job_Batch` | `job:` | `nom`, `description`, `source`=`file_location` | `HYPOTHÈSE` |
| `Copybook` | `Structure_Partagee` | `struct:` | `nom`, `description`, `source`=`file_location` | `HYPOTHÈSE` |
| `GenericFile` | `Store_Echange` | `store:` | `nom`, `description`, `source`=`file_location` | `HYPOTHÈSE` |
| `External/Doc` (4822, 83 % du dump) | **non mappé** | — | conservé uniquement comme valeur de `source` sur les relations qui le référencent (cf. §3) | — |

`functional_embedding`/`technical_embedding` ne sont **pas** importés dans ADG-M (pas de propriété vectorielle dans la taxonomie v2.0) — perdus pour ce mapping. Si une recherche sémantique sur ce corpus est souhaitée plus tard, elle devra passer par l'Option A (graphe séparé), pas par ADG-M.

## 2. Nœuds `:Community`

| `level` | Label ADG-M | Préfixe `id` | Propriétés | `fiabilite` |
|---|---|---|---|---|
| `2` (96 communautés macro) | `Domaine_Fonctionnel` | `dom:` | `nom`=`title`, `description`=`functional_summary`, `source`="GraphRAG community {id}" | `HYPOTHÈSE` |
| `1` (sous-communautés) | **non mappé en v1** — granularité trop fine pour `Domaine_Fonctionnel`, pas d'équivalent direct (`Processus_Fonctionnel` nécessiterait un déclencheur identifié, absent du dump) | — | — | — |

## 3. Relations

| Relation GraphRAG | Mapping ADG-M | Notes |
|---|---|---|
| `READS` (Program→GenericFile/Copybook) | `ACCEDE_A` (`mode: R`) | uniquement si cible mappée (`GenericFile`→`Store_Echange`) ; `READS`→`Copybook` n'a pas de sens (copybook = structure, pas un store) → ignoré dans ce cas |
| `INSERTS`/`UPDATES`/`DELETES`/`CREATES` (Program→GenericFile) | `ACCEDE_A` (`mode: W`, fusionné en `RW` si `READS` existe aussi) | |
| `CALLS` (Program→Program) | `APPELLE` (`typeAppel: STATIQUE`) | |
| `INCLUDES` (Program→Copybook) | `INCLUT` | |
| `IN_COMMUNITY` (Entity→Community, 5713 — une par Entity) | **non mappé** | pas d'équivalent dans `ALLOWED_REL_TYPES` : aucune relation `Domaine_Fonctionnel → Composant/Job_Batch/Structure_Partagee/Store_Echange` n'existe dans la taxonomie v2.0 (`CONTIENT`→Processus_Fonctionnel, `CATALOGUE`→Fonction uniquement) |
| `EXECUTES` (BatchJob→Program) | **non mappé** | `DECLENCHE` est restreint à `{Unite_Execution, Point_Entree}→Composant` ; `Job_Batch` n'y figure pas directement (il faudrait un nœud `Unite_Execution` intermédiaire, absent du dump) |
| `SUBCOMMUNITY_OF`, `TRIGGERS`, `DEPENDS_ON`, `SENDS`, `RECEIVES`, `INTERACTS_WITH`, `REFERENCES` | **non mappés** | hors `ALLOWED_REL_TYPES`, pas d'équivalent direct |

---

## 4. Écarts identifiés (décisions requises avant exécution)

Le mapping ci-dessus couvre `CALLS`, `INCLUDES`, `READS`/`INSERTS`/`UPDATES`/`DELETES`/`CREATES`
(soit ~9 700 des 19 368 relations, ~50 %). Les ~50 % restantes (`IN_COMMUNITY`, `EXECUTES`,
et les relations de la dernière ligne) **n'ont pas d'équivalent dans la taxonomie v2.0
actuelle** :

- **`IN_COMMUNITY`** est la seule façon de savoir quel `Composant`/`Job_Batch`/etc.
  appartient à quel `Domaine_Fonctionnel` (issu de §2). Sans mapping, les `Domaine_Fonctionnel`
  importés seraient des nœuds isolés (aucune relation entrante/sortante).
- **`EXECUTES`** (BatchJob→Program) est l'information qui dit "ce batch exécute ce programme"
  — perdre cette relation fait perdre une grande partie de la valeur du dump pour la couche
  applicative (40 BatchJob × en moyenne plusieurs programmes).

**Deux options :**

- **(a) Extension additive de la taxonomie** (type "Ext #4", dans l'esprit des Ext #1-3
  déjà documentées) : ajouter `APPARTIENT_DOMAINE` (`Composant|Job_Batch|Structure_Partagee|
  Store_Echange → Domaine_Fonctionnel`) et `CONTIENT_PROGRAMME` ou réutiliser `DECLENCHE` en
  élargissant son `from` à `Job_Batch`. Impact : `ALLOWED_REL_TYPES` (+ doc glossaire) +
  éventuellement `_PLANE_BY_LABEL`. Changement petit et rétrocompatible (ajout, rien retiré).
- **(b) v1 scope réduit** : importer uniquement `Composant`/`Job_Batch`/`Structure_Partagee`/
  `Store_Echange` + `APPELLE`/`INCLUT`/`ACCEDE_A` (sans `Domaine_Fonctionnel` ni regroupement
  par communauté). Les ~832 `Composant` resteront non rattachés à un domaine fonctionnel —
  acceptable si l'objectif immédiat est l'inventaire technique (programmes/jobs/copybooks/
  flux d'accès), le rattachement aux domaines pouvant être fait manuellement via Exploration
  ensuite.

---

## 5. Volumétrie attendue après mapping (option a, mapping complet)

| Label ADG-M | Nb nœuds | Origine |
|---|---|---|
| `Composant` | 832 | `:Entity[type=Program]` |
| `Job_Batch` | 40 | `:Entity[type=BatchJob]` |
| `Structure_Partagee` | 18 | `:Entity[type=Copybook]` |
| `Store_Echange` | 1 | `:Entity[type=GenericFile]` |
| `Domaine_Fonctionnel` | 96 | `:Community[level=2]` |

| Relation ADG-M | Nb (estimé) | Origine |
|---|---|---|
| `APPELLE` | 1948 | `CALLS` |
| `INCLUT` | 1518 | `INCLUDES` |
| `ACCEDE_A` | ~6800 | `READS`/`INSERTS`/`UPDATES`/`DELETES`/`CREATES` (après fusion R/W) |
| `APPARTIENT_DOMAINE` *(si Ext #4)* | ~891 | `IN_COMMUNITY` (Program/BatchJob/Copybook/GenericFile uniquement, pas External/Doc) |
| `DECLENCHE`/`CONTIENT_PROGRAMME` *(si Ext #4)* | 369 | `EXECUTES` |

Tout est `fiabilite: HYPOTHÈSE` à l'import — à confirmer/dégrader/upgrader ensuite via
Exploration (review humaine), conformément à la règle F.2 (upgrade-only, `FAIT` >
`HYPOTHÈSE` > `SUPPOSÉ` > `MANQUANT`).
