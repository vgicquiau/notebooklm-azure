# ingest/extract/ — Dump GraphRAG pour neo4j-legacykb

Déposez ici le fichier d'export à importer dans `neo4j-legacykb` (utilisé par
`import-neo4j-legacykb.ps1`, appelé automatiquement par `deploy.ps1` et `migrate-rg.ps1`) :

- **`repartition_cleaned_export.graphml`** — nom et emplacement attendus par défaut (format
  GraphML, généré par le pipeline GraphRAG)
- ou tout autre fichier **`.graphml`** / **`.jsonl`** (format détecté automatiquement par
  l'extension, cf. `api/scripts/import_legacykb.py`), en le précisant explicitement :

  ```powershell
  .\import-neo4j-legacykb.ps1 -ResourceGroup <rg> -DumpPath ingest\extract\mon_export.jsonl
  ```

## Pourquoi ce dossier (et pas `docs/extract/`)

**Ce dossier est volontairement *suivi par Git*** (contrairement à son contenu — les fichiers
`.graphml`/`.jsonl` eux-mêmes sont gitignorés, trop volumineux et régénérables). C'est
important : tout le dossier `docs/` est exclu de Git (`.gitignore`), donc **`docs/extract/`
n'existe pas du tout après un `git clone`** — un nouvel utilisateur du dépôt ne pouvait pas
deviner qu'il fallait créer ce dossier lui-même. `ingest/` n'est lui pas exclu : ce dossier
(et ce README) sont donc bien présents dès le clone, même si vous devez quand même y déposer
votre propre fichier d'export vous-même (les données elles-mêmes ne sont jamais commitées).

Si vous reprenez un export existant : copiez-le simplement ici avant de lancer
`deploy.ps1`/`import-neo4j-legacykb.ps1`/`migrate-rg.ps1`.
