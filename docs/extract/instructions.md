# Import du graphe Neo4j — `repartition_cleaned_export.graphml`

Ce document explique comment importer le fichier GraphML `repartition_cleaned_export.graphml`
(export complet d'une base Neo4j réalisé via APOC) dans une instance Neo4j.

---

## 1. Pré-requis

Le plugin **APOC** (Awesome Procedures On Cypher) doit être installé sur l'instance cible.
Sans lui, l'appel échoue avec l'erreur `42N08: no such procedure ... apoc.import.graphml`.

En plus de l'installation du jar APOC, la configuration doit autoriser l'import de fichiers.
Ajouter dans `apoc.conf` (ou `neo4j.conf` selon la version) :

```properties
apoc.import.file.enabled=true
```

> La version majeure d'APOC doit correspondre à la version de Neo4j (ex. Neo4j `2026.02.x` → APOC `2026.02.x`).

---

## 2. Où déposer le fichier

Le fichier doit être placé dans le dossier `import/` de l'instance cible. L'emplacement dépend du type d'installation :

| Type d'install | Dossier où copier le `.graphml` |
|---|---|
| **Neo4j Desktop** | Bouton `...` de la base → **Open folder → Import** |
| **Neo4j installé (tar / Homebrew / zip)** | le dossier `import/` sous le home Neo4j |
| **Docker** | copier/monter dans `/var/lib/neo4j/import` (ou `/import`) du conteneur |

Exemple de copie dans un conteneur Docker :

```bash
docker cp repartition_cleaned_export.graphml <nom_conteneur>:/var/lib/neo4j/import/
```

---

## 3. Commande d'import

Depuis **Neo4j Browser** ou **cypher-shell** :

```cypher
CALL apoc.import.graphml("repartition_cleaned_export.graphml", {readLabels: true})
```

- On passe **uniquement le nom du fichier** (pas le chemin complet) : APOC le cherche dans le dossier `import/`.
- `readLabels: true` est **important** : il recrée les **labels** des nœuds (sinon tous les nœuds sont importés sans label).

---

## 4. Points d'attention

- **Importer dans une base vide** de préférence : `apoc.import.graphml` ne déduplique pas, il ajoute.
  Réimporter deux fois dans la même base = doublons.
- Pour de gros volumes, créer les **index / contraintes** après l'import pour de meilleures performances.
- L'instance cible doit avoir la **même version majeure d'APOC** que sa version de Neo4j.
- Vérifier qu'on est bien connecté à la **bonne instance** (attention si plusieurs Neo4j tournent sur les mêmes ports 7474 / 7687).

---

## 5. Vérification après import

```cypher
// Nombre de nœuds
MATCH (n) RETURN count(n) AS nb_noeuds;

// Nombre de relations
MATCH ()-[r]->() RETURN count(r) AS nb_relations;

// Répartition par label
MATCH (n) RETURN labels(n) AS labels, count(*) AS nb ORDER BY nb DESC;
```
