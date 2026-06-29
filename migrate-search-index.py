"""Copie le contenu de l'index Azure AI Search "notebooklm-chunks" d'un service vers un autre.

Contexte : les fichiers source originaux sont supprimés après ingestion (cf. CLAUDE.md /
ARCHITECTURE.md, limite "Viewer document original") -- il est donc impossible de ré-ingérer
depuis zéro lors d'une migration. Ce script copie les documents déjà indexés (texte + vecteurs
d'embedding) tels quels, sans réappeler Azure OpenAI -- aucun coût de ré-embedding, aucune perte
de fidélité.

Usage :
    python migrate-search-index.py <ancien_endpoint> <nouvel_endpoint>

Exemple :
    python migrate-search-index.py https://srch-nlmavgi-prod.search.windows.net https://srch-nlmavg2-prod.search.windows.net

Prérequis : le compte qui exécute ce script doit avoir le rôle "Search Index Data Contributor"
(lecture) sur l'ancien service ET sur le nouveau (lecture+écriture) -- déjà accordé au
développeur par deploy.ps1 Phase 6 pour chaque déploiement.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient

from ingest.indexer import INDEX_NAME, Indexer

BATCH_SIZE = 500


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage : python migrate-search-index.py <ancien_endpoint> <nouvel_endpoint>")
        return 1

    old_endpoint, new_endpoint = sys.argv[1], sys.argv[2]
    credential = DefaultAzureCredential()

    print(f"Index source : {old_endpoint}/{INDEX_NAME}")
    print(f"Index cible  : {new_endpoint}/{INDEX_NAME}")

    print("Création/mise à jour du schéma d'index sur le service cible...")
    Indexer(new_endpoint, credential).ensure_index()

    old_client = SearchClient(old_endpoint, INDEX_NAME, credential)
    new_client = SearchClient(new_endpoint, INDEX_NAME, credential)

    print("Lecture de tous les documents de l'index source (texte + vecteurs)...")
    results = old_client.search(search_text="*", select="*", top=1000, include_total_count=True)
    total_expected = results.get_count()
    print(f"Documents attendus : {total_expected}")

    documents = []
    for doc in results:
        clean_doc = {k: v for k, v in doc.items() if not k.startswith("@search.")}
        documents.append(clean_doc)

    print(f"Documents lus : {len(documents)}")
    if total_expected is not None and len(documents) != total_expected:
        print(f"  !! Attention : {len(documents)} lus vs {total_expected} attendus -- vérifier la pagination.")

    if not documents:
        print("Aucun document à migrer.")
        return 0

    print(f"Upload vers l'index cible par lots de {BATCH_SIZE}...")
    uploaded = 0
    failed_total = 0
    for i in range(0, len(documents), BATCH_SIZE):
        batch = documents[i : i + BATCH_SIZE]
        result = new_client.upload_documents(documents=batch)
        failed = [r for r in result if not r.succeeded]
        uploaded += len(batch) - len(failed)
        failed_total += len(failed)
        for f in failed:
            print(f"  Erreur upload : {f.key} -- {f.error_message}")
        print(f"  Lot {i // BATCH_SIZE + 1} : {len(batch) - len(failed)}/{len(batch)} OK")

    print(f"\nTerminé : {uploaded} documents migrés, {failed_total} échecs.")
    return 1 if failed_total else 0


if __name__ == "__main__":
    sys.exit(main())
