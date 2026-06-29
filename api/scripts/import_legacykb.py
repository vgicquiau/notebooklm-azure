"""Import GraphML ou JSONL dans neo4j-legacykb — exécuté en tant que Container Apps Job.

AUDIT-2026-06 (finding haut, exposition réseau) : neo4j-legacykb a perdu son IP
publique (cf. infra/modules/network.bicep) et n'est plus joignable que depuis
snet-cae (sous-réseau de l'environnement Container Apps). Ce script reprend la
logique réseau qu'effectuait auparavant import-neo4j-legacykb.ps1 directement
depuis le poste de l'opérateur, mais s'exécute désormais à l'intérieur du VNet,
en tant qu'exécution ponctuelle du Container Apps Job `caj-import-legacykb-*`
(déclenché par `az containerapp job start`, piloté par import-neo4j-legacykb.ps1).

Le fichier (GraphML ou JSONL, cf. format détecté par extension) reste uploadé par
import-neo4j-legacykb.ps1 (control-plane Azure Files via clé de compte, pas affecté
par le changement réseau) avant le lancement de ce job — ce script suppose le
fichier déjà présent dans le partage `neo4j-import`.

Format JSONL (alternative au GraphML, ex. export généré par un autre outil) : une
ligne JSON par enregistrement, deux types :
    {"_type": "node", "id": <int>, "labels": [...], "props": {...}}
    {"_type": "relationship", "fromId": <int>, "toId": <int>, "relType": "...", "props": {...}}
`id`/`fromId`/`toId` sont des identifiants internes Neo4j *au moment de l'export* --
non stables entre deux bases, mais cohérents entre eux à l'intérieur d'un même
fichier (générés en une seule passe) : utilisés uniquement pour relier les
relations à leurs nœuds via une propriété temporaire `_importId`, retirée en fin
d'import. Contrairement à l'upsert GraphML (par propriété métier), un import JSONL
crée toujours de nouveaux nœuds -- utiliser -PurgeBeforeImport pour réimporter sans
dupliquer.

Usage (à l'intérieur du conteneur du job) :
    DUMP_FILENAME=export.graphml PURGE_BEFORE_IMPORT=false python -m api.scripts.import_legacykb
    DUMP_FILENAME=export.jsonl   PURGE_BEFORE_IMPORT=false python -m api.scripts.import_legacykb
"""

from __future__ import annotations

import json
import os
import sys
import time

from api.services import legacykb_client as kb

_FIX_UTF8_PATH = "/app/fix_utf8.cypher"
_HEALTH_CHECK_TIMEOUT_S = 180
_HEALTH_CHECK_INTERVAL_S = 5
# Partage Azure Files "neo4j-import" monté en lecture/écriture sur ce Job (même partage
# que le dump GraphML) -- y déposer le résultat permet à import-neo4j-legacykb.ps1 de le
# relire via `az storage file download` (control-plane), sans accès réseau direct au Job.
_RESULT_DIR = "/import"


def _load_password_from_keyvault() -> None:
    """Reprend le pattern de api/main.py:_load_secrets_from_keyvault, restreint au
    seul secret nécessaire ici (le mot de passe est déjà en Key Vault, posé par
    infra/main.bicep — pas besoin de dupliquer un secret au niveau du Job)."""
    if os.environ.get("NEO4J_LEGACYKB_PASSWORD"):
        return
    kv_uri = os.environ.get("AZURE_KEYVAULT_URI")
    if not kv_uri:
        raise RuntimeError("AZURE_KEYVAULT_URI non défini — impossible de charger le mot de passe.")

    from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
    from azure.keyvault.secrets import SecretClient

    client_id = os.environ.get("AZURE_CLIENT_ID")
    credential = ManagedIdentityCredential(client_id=client_id) if client_id else DefaultAzureCredential()
    secret = SecretClient(vault_url=kv_uri, credential=credential).get_secret("neo4j-legacykb-password")
    os.environ["NEO4J_LEGACYKB_PASSWORD"] = secret.value


def _wait_until_ready() -> None:
    deadline = time.monotonic() + _HEALTH_CHECK_TIMEOUT_S
    while True:
        try:
            kb._run_rows("RETURN 1")
            return
        except kb.LegacyKbError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"neo4j-legacykb non joignable après {_HEALTH_CHECK_TIMEOUT_S}s.")
            time.sleep(_HEALTH_CHECK_INTERVAL_S)


def _purge() -> dict:
    cypher = (
        "CALL apoc.periodic.iterate('MATCH (n) RETURN n', 'DETACH DELETE n', "
        "{batchSize: 500, parallel: false}) "
        "YIELD total, committedOperations, failedOperations, errorMessages "
        "RETURN total, committedOperations, failedOperations, errorMessages"
    )
    row = kb._run_rows(cypher)[0]
    if row["failedOperations"] > 0:
        raise RuntimeError(f"Purge incomplète : {row['failedOperations']} opération(s) en échec — {row['errorMessages']}")
    return {"total": row["total"], "committed": row["committedOperations"]}


def _import_graphml(dump_filename: str) -> dict:
    cypher = (
        f"CALL apoc.import.graphml('file:///var/lib/neo4j/import/{dump_filename}', "
        "{readLabels: true}) YIELD nodes, relationships RETURN nodes, relationships"
    )
    row = kb._run_rows(cypher)[0]
    return {"nodes": row["nodes"], "relationships": row["relationships"]}


# Lots nœuds nettement plus petits que les lots relations -- les :Entity portent des
# propriétés d'embedding volumineuses (functional_embedding/technical_embedding, vecteurs
# de plusieurs Ko chacun ; jusqu'à ~75 Ko pour un seul nœud, ~10 Ko en moyenne, mesuré sur le
# dump réel). Un lot de 500 nœuds peut dépasser le timeout HTTP de 30s de legacykb_client._execute
# sur le conteneur 1 CPU/2 Go (constaté en pratique : "Instance Neo4j legacy-kb injoignable",
# reproductible -- pas un aléa réseau). Les relations, elles, sont minuscules (~95 octets en
# moyenne, pas de gros payload), un lot de 500 reste largement sous la limite.
_JSONL_NODE_BATCH_SIZE = 50
_JSONL_REL_BATCH_SIZE = 500
# Seuls labels présents dans neo4j-legacykb (cf. legacykb_client._node_summary) --
# utilisés pour indexer temporairement _importId pendant l'import (sinon le MATCH
# des relations sur cette propriété fait un scan complet à chaque lot).
_JSONL_KNOWN_LABELS = ("Entity", "Community")


def _jsonl_records(path: str, record_type: str):
    """Lit le fichier en streaming, ne garde que les lignes du type demandé --
    deux passes complètes (une pour les nœuds, une pour les relations) plutôt
    qu'une passe unique avec tampons, pour ne faire aucune hypothèse sur l'ordre
    nœuds/relations dans le fichier (notre propre export les écrit dans cet ordre,
    mais un fichier JSONL externe n'a aucune raison de le garantir)."""
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec["_type"] == record_type:
                yield rec


def _batched(iterable, size: int):
    batch = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _import_jsonl(dump_filename: str) -> dict:
    path = os.path.join(_RESULT_DIR, dump_filename)

    for label in _JSONL_KNOWN_LABELS:
        kb._run_rows(f"CREATE INDEX nlaz_import_id_{label.lower()} IF NOT EXISTS FOR (n:{label}) ON (n._importId)")

    node_count = 0
    for batch in _batched(_jsonl_records(path, "node"), _JSONL_NODE_BATCH_SIZE):
        rows = [{"importId": r["id"], "labels": r["labels"], "props": r["props"]} for r in batch]
        kb._run_rows(
            "UNWIND $rows AS row "
            "CALL apoc.create.node(row.labels, apoc.map.setKey(row.props, '_importId', row.importId)) "
            "YIELD node RETURN count(node) AS n",
            rows=rows,
        )
        node_count += len(rows)

    rel_count = 0
    for batch in _batched(_jsonl_records(path, "relationship"), _JSONL_REL_BATCH_SIZE):
        rows = [{"fromId": r["fromId"], "toId": r["toId"], "relType": r["relType"], "props": r["props"]} for r in batch]
        kb._run_rows(
            "UNWIND $rows AS row "
            "MATCH (a {_importId: row.fromId}), (b {_importId: row.toId}) "
            "CALL apoc.create.relationship(a, row.relType, row.props, b) "
            "YIELD rel RETURN count(rel) AS n",
            rows=rows,
        )
        rel_count += len(rows)

    kb._run_rows("MATCH (n) WHERE n._importId IS NOT NULL REMOVE n._importId")
    for label in _JSONL_KNOWN_LABELS:
        kb._run_rows(f"DROP INDEX nlaz_import_id_{label.lower()} IF EXISTS")

    return {"nodes": node_count, "relationships": rel_count}


def _fix_utf8() -> dict:
    if not os.path.exists(_FIX_UTF8_PATH):
        return {"skipped": True}
    with open(_FIX_UTF8_PATH, encoding="utf-8") as f:
        cypher = f.read()
    row = kb._run_rows(cypher)[0]
    return {"fixed_count": next(iter(row.values()))}


def main() -> int:
    # DUMP_FILENAME/PURGE_BEFORE_IMPORT poussés via `az containerapp job update
    # --set-env-vars` juste avant `az containerapp job start` (cf.
    # import-neo4j-legacykb.ps1) -- pas d'arguments CLI : `job start` ne permet pas de
    # surcharger la commande/les args du conteneur à la volée, seulement son template.
    dump_filename = os.environ.get("DUMP_FILENAME", "")
    purge = os.environ.get("PURGE_BEFORE_IMPORT", "false").lower() == "true"
    if not dump_filename:
        print(json.dumps({"error": "DUMP_FILENAME non défini."}), flush=True)
        return 1

    suffix = os.path.splitext(dump_filename)[1].lower()
    if suffix not in (".graphml", ".jsonl"):
        print(json.dumps({"error": f"Format de dump non reconnu ({suffix!r}) -- attendu .graphml ou .jsonl."}), flush=True)
        return 1

    summary: dict = {}
    exit_code = 0
    try:
        _load_password_from_keyvault()
        _wait_until_ready()
        if purge:
            summary["purge"] = _purge()
        if suffix == ".graphml":
            summary["import"] = _import_graphml(dump_filename)
            # Bug connu d'apoc.import.graphml (double décodage Latin-1/UTF-8 sur les
            # propriétés Community) -- sans objet pour le chemin JSONL, dont les
            # propriétés viennent directement d'un json.loads déjà correctement décodé.
            summary["fix_utf8"] = _fix_utf8()
        else:
            summary["import"] = _import_jsonl(dump_filename)
    except Exception as e:
        summary["error"] = str(e)
        exit_code = 1

    print(json.dumps(summary), flush=True)
    _write_result(summary)
    return exit_code


def _write_result(summary: dict) -> None:
    execution_name = os.environ.get("CONTAINER_APP_JOB_EXECUTION_NAME", f"local-{int(time.time())}")
    if not os.path.isdir(_RESULT_DIR):
        return  # Partage non monté (ex. exécution locale de test) -- résultat déjà sur stdout.
    result_path = os.path.join(_RESULT_DIR, f"{execution_name}-result.json")
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(summary, f)


if __name__ == "__main__":
    sys.exit(main())
